"""
EPUSDT (GMPay) 支付 Provider

EPUSDT 是一个 USDT TRC20 支付网关，支持自动回调和查单。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class EpusdtConfig:
    """EPUSDT 配置"""
    merchant_id: str
    api_key: str
    gateway_url: str
    callback_url: str


@dataclass
class PaymentResult:
    """支付创建结果"""
    payment_url: str
    trade_no: str
    amount: Decimal
    expires_at: Optional[str] = None


class EpusdtGmpayProvider:
    """EPUSDT GMPay 支付 Provider"""

    def __init__(self, config: EpusdtConfig):
        self.config = config

    async def create_payment(
        self,
        out_trade_no: str,
        amount: Decimal,
        notify_url: Optional[str] = None,
        return_url: Optional[str] = None,
    ) -> PaymentResult:
        """
        创建支付订单

        Args:
            out_trade_no: 商户订单号
            amount: 支付金额（USDT）
            notify_url: 异步回调地址
            return_url: 同步返回地址

        Returns:
            PaymentResult: 支付结果

        Raises:
            Exception: 创建失败时抛出异常
        """
        # 构造请求参数
        params = {
            "merchant_id": self.config.merchant_id,
            "out_trade_no": out_trade_no,
            "amount": str(amount),
            "notify_url": notify_url or self.config.callback_url,
        }

        if return_url:
            params["return_url"] = return_url

        # 签名
        params["sign"] = self._sign(params)

        # 发送请求
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{self.config.gateway_url}/api/v1/order/create",
                json=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise Exception(f"EPUSDT API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"EPUSDT 创建订单失败: {data.get('message')}")

                result = data.get("data", {})
                return PaymentResult(
                    payment_url=result["payment_url"],
                    trade_no=result["trade_no"],
                    amount=Decimal(result["amount"]),
                    expires_at=result.get("expires_at"),
                )

    async def verify_callback(self, payload: Dict[str, Any]) -> bool:
        """
        验证回调签名

        Args:
            payload: 回调数据

        Returns:
            bool: 签名是否有效
        """
        sign = payload.get("sign")
        if not sign:
            return False

        # 提取除签名外的参数
        params = {k: v for k, v in payload.items() if k != "sign"}

        # 计算签名
        expected_sign = self._sign(params)

        return sign == expected_sign

    async def process_callback(
        self,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        处理回调数据

        Args:
            payload: 回调数据

        Returns:
            Dict: 标准化的回调结果
                - out_trade_no: 商户订单号
                - trade_no: 支付平台订单号
                - amount: 支付金额
                - status: 支付状态（success/failed/pending）
                - paid_at: 支付时间（ISO 格式）

        Raises:
            ValueError: 数据格式错误
        """
        # 验证签名
        if not await self.verify_callback(payload):
            raise ValueError("回调签名验证失败")

        # 提取数据
        return {
            "out_trade_no": payload["out_trade_no"],
            "trade_no": payload["trade_no"],
            "amount": Decimal(payload["amount"]),
            "status": self._map_status(payload["status"]),
            "paid_at": payload.get("paid_at"),
        }

    async def query_order(self, out_trade_no: str) -> Dict[str, Any]:
        """
        查询订单状态

        Args:
            out_trade_no: 商户订单号

        Returns:
            Dict: 订单信息

        Raises:
            Exception: 查询失败
        """
        params = {
            "merchant_id": self.config.merchant_id,
            "out_trade_no": out_trade_no,
        }
        params["sign"] = self._sign(params)

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.config.gateway_url}/api/v1/order/query",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise Exception(f"EPUSDT API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 0:
                    raise Exception(f"EPUSDT 查询订单失败: {data.get('message')}")

                result = data.get("data", {})
                return {
                    "out_trade_no": result["out_trade_no"],
                    "trade_no": result["trade_no"],
                    "amount": Decimal(result["amount"]),
                    "status": self._map_status(result["status"]),
                    "paid_at": result.get("paid_at"),
                    "created_at": result.get("created_at"),
                }

    def _sign(self, params: Dict[str, Any]) -> str:
        """
        生成签名

        EPUSDT 签名规则：
        1. 对参数按 key 排序
        2. 拼接为 key1=value1&key2=value2&key=api_key
        3. MD5 哈希并转大写

        Args:
            params: 参数字典

        Returns:
            str: 签名
        """
        # 排序参数
        sorted_params = sorted(params.items())

        # 拼接字符串
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        sign_str += f"&key={self.config.api_key}"

        # MD5 哈希
        md5 = hashlib.md5()
        md5.update(sign_str.encode("utf-8"))
        return md5.hexdigest().upper()

    def _map_status(self, status: str) -> str:
        """
        映射支付状态

        EPUSDT 状态：
        - 0: 待支付
        - 1: 已支付
        - 2: 已过期
        - 3: 已取消

        标准状态：
        - pending: 待支付
        - success: 支付成功
        - failed: 支付失败
        - expired: 已过期

        Args:
            status: EPUSDT 状态

        Returns:
            str: 标准状态
        """
        status_map = {
            "0": "pending",
            "1": "success",
            "2": "expired",
            "3": "failed",
        }
        return status_map.get(str(status), "pending")
