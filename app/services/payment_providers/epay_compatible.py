"""
易支付兼容 Provider

兼容易支付（YPay）接口标准的支付网关。
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class EpayConfig:
    """易支付配置"""
    pid: str  # 商户ID
    key: str  # 密钥
    gateway_url: str  # 网关地址
    callback_url: str  # 回调地址


@dataclass
class EpayPaymentResult:
    """支付创建结果"""
    payment_url: str
    trade_no: str
    amount: Decimal


class EpayCompatibleProvider:
    """易支付兼容 Provider"""

    def __init__(self, config: EpayConfig):
        self.config = config

    async def create_payment(
        self,
        out_trade_no: str,
        amount: Decimal,
        payment_type: str = "alipay",
        name: str = "商品购买",
        notify_url: Optional[str] = None,
        return_url: Optional[str] = None,
    ) -> EpayPaymentResult:
        """
        创建支付订单

        Args:
            out_trade_no: 商户订单号
            amount: 支付金额
            payment_type: 支付方式（alipay/wxpay/qqpay/usdt等）
            name: 商品名称
            notify_url: 异步回调地址
            return_url: 同步返回地址

        Returns:
            EpayPaymentResult: 支付结果

        Raises:
            Exception: 创建失败时抛出异常
        """
        # 构造请求参数
        params = {
            "pid": self.config.pid,
            "type": payment_type,
            "out_trade_no": out_trade_no,
            "notify_url": notify_url or self.config.callback_url,
            "name": name,
            "money": str(amount),
        }

        if return_url:
            params["return_url"] = return_url

        # 签名
        params["sign"] = self._sign(params)
        params["sign_type"] = "MD5"

        # 构造支付 URL（易支付使用 GET 跳转）
        payment_url = f"{self.config.gateway_url}/submit.php?{urlencode(params)}"

        return EpayPaymentResult(
            payment_url=payment_url,
            trade_no=out_trade_no,  # 易支付没有独立的交易号
            amount=amount,
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

        # 提取除签名和签名类型外的参数
        params = {
            k: v for k, v in payload.items()
            if k not in ("sign", "sign_type")
        }

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
                - status: 支付状态
                - paid_at: 支付时间

        Raises:
            ValueError: 数据格式错误
        """
        # 验证签名
        if not await self.verify_callback(payload):
            raise ValueError("回调签名验证失败")

        # 提取数据
        return {
            "out_trade_no": payload["out_trade_no"],
            "trade_no": payload.get("trade_no", payload["out_trade_no"]),
            "amount": Decimal(payload["money"]),
            "status": self._map_status(payload.get("trade_status", "TRADE_SUCCESS")),
            "paid_at": None,  # 易支付回调不包含支付时间
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
            "pid": self.config.pid,
            "out_trade_no": out_trade_no,
            "type": "query",
        }
        params["sign"] = self._sign(params)
        params["sign_type"] = "MD5"

        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.config.gateway_url}/api.php",
                params=params,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                if response.status != 200:
                    raise Exception(f"易支付 API 返回错误: {response.status}")

                data = await response.json()

                if data.get("code") != 1:
                    raise Exception(f"易支付查询订单失败: {data.get('msg')}")

                result = data.get("data", {})
                return {
                    "out_trade_no": result["out_trade_no"],
                    "trade_no": result.get("trade_no", result["out_trade_no"]),
                    "amount": Decimal(result["money"]),
                    "status": self._map_status(result.get("status")),
                    "paid_at": result.get("endtime"),
                    "created_at": result.get("addtime"),
                }

    def get_callback_response(self, success: bool = True) -> str:
        """
        获取回调响应内容

        易支付要求回调成功时返回 "success"，失败时返回 "fail"

        Args:
            success: 是否处理成功

        Returns:
            str: 响应内容
        """
        return "success" if success else "fail"

    def _sign(self, params: Dict[str, Any]) -> str:
        """
        生成签名

        易支付签名规则：
        1. 对参数按 key 排序（去除 sign 和 sign_type）
        2. 拼接为 key1=value1&key2=value2&key=密钥
        3. MD5 哈希并转小写

        Args:
            params: 参数字典

        Returns:
            str: 签名
        """
        # 过滤并排序参数
        filtered_params = {
            k: v for k, v in params.items()
            if v and k not in ("sign", "sign_type")
        }
        sorted_params = sorted(filtered_params.items())

        # 拼接字符串
        sign_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        sign_str += self.config.key

        # MD5 哈希
        md5 = hashlib.md5()
        md5.update(sign_str.encode("utf-8"))
        return md5.hexdigest()

    def _map_status(self, status: str) -> str:
        """
        映射支付状态

        易支付状态：
        - TRADE_SUCCESS: 支付成功
        - TRADE_PENDING: 待支付
        - TRADE_CLOSED: 已关闭

        标准状态：
        - pending: 待支付
        - success: 支付成功
        - failed: 支付失败

        Args:
            status: 易支付状态

        Returns:
            str: 标准状态
        """
        status_map = {
            "TRADE_SUCCESS": "success",
            "TRADE_PENDING": "pending",
            "TRADE_CLOSED": "failed",
        }
        return status_map.get(status, "pending")
