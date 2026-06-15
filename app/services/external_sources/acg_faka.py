"""
acg-faka 外部货源 Provider

对接 acg-faka 系统作为上游供货商。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class AcgFakaConfig:
    """acg-faka 配置"""
    api_url: str
    api_key: str
    merchant_id: str


@dataclass
class ExternalProduct:
    """外部商品"""
    external_id: str
    name: str
    price: Decimal
    currency: str
    stock: int
    description: Optional[str] = None


@dataclass
class ExternalOrder:
    """外部订单"""
    external_order_id: str
    status: str  # pending/success/failed
    delivery_content: Optional[str] = None


class AcgFakaProvider:
    """acg-faka Provider"""

    def __init__(self, config: AcgFakaConfig):
        self.config = config

    async def sync_catalog(
        self,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> tuple[List[ExternalProduct], Optional[str]]:
        """
        同步商品目录

        Args:
            cursor: 分页游标
            limit: 每页数量

        Returns:
            tuple: (商品列表, 下一页游标)

        Raises:
            Exception: 同步失败
        """
        params = {
            "merchant_id": self.config.merchant_id,
            "limit": limit,
        }

        if cursor:
            params["cursor"] = cursor

        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.config.api_url}/api/v1/products",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise Exception(f"acg-faka API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"acg-faka 同步失败: {data.get('message')}")

                products = []
                for item in data.get("data", {}).get("items", []):
                    products.append(ExternalProduct(
                        external_id=item["id"],
                        name=item["name"],
                        price=Decimal(item["price"]),
                        currency=item.get("currency", "CNY"),
                        stock=item.get("stock", 0),
                        description=item.get("description"),
                    ))

                next_cursor = data.get("data", {}).get("next_cursor")
                return products, next_cursor

    async def place_order(
        self,
        external_product_id: str,
        quantity: int,
        out_trade_no: str,
    ) -> ExternalOrder:
        """
        在上游下单

        Args:
            external_product_id: 外部商品ID
            quantity: 数量
            out_trade_no: 商户订单号

        Returns:
            ExternalOrder: 外部订单

        Raises:
            Exception: 下单失败
        """
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "merchant_id": self.config.merchant_id,
            "product_id": external_product_id,
            "quantity": quantity,
            "out_trade_no": out_trade_no,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.config.api_url}/api/v1/orders",
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise Exception(f"acg-faka API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"acg-faka 下单失败: {data.get('message')}")

                result = data.get("data", {})
                return ExternalOrder(
                    external_order_id=result["order_id"],
                    status=self._map_status(result.get("status")),
                    delivery_content=result.get("delivery_content"),
                )

    async def query_delivery(
        self,
        external_order_id: str,
    ) -> ExternalOrder:
        """
        查询发货状态

        Args:
            external_order_id: 外部订单ID

        Returns:
            ExternalOrder: 订单信息

        Raises:
            Exception: 查询失败
        """
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
        }

        params = {
            "merchant_id": self.config.merchant_id,
        }

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.config.api_url}/api/v1/orders/{external_order_id}",
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    raise Exception(f"acg-faka API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"acg-faka 查询失败: {data.get('message')}")

                result = data.get("data", {})
                return ExternalOrder(
                    external_order_id=result["order_id"],
                    status=self._map_status(result.get("status")),
                    delivery_content=result.get("delivery_content"),
                )

    def _map_status(self, status: str) -> str:
        """
        映射订单状态

        acg-faka 状态：
        - pending: 待处理
        - processing: 处理中
        - completed: 已完成
        - failed: 失败

        标准状态：
        - pending: 待处理
        - success: 成功
        - failed: 失败

        Args:
            status: acg-faka 状态

        Returns:
            str: 标准状态
        """
        status_map = {
            "pending": "pending",
            "processing": "pending",
            "completed": "success",
            "failed": "failed",
        }
        return status_map.get(status, "pending")
