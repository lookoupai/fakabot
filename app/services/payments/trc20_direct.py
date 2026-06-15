from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urlencode, urlsplit, urlunsplit

from app.services.payments.base import PaymentCreateResult, PaymentOrderRequest, PaymentQueryResult


USDT_TRC20_CONTRACT_ADDRESS = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"
TRC20_TRANSFER_METHOD_ID = "a9059cbb"
TRC20_USDT_SCALE = 1_000_000
TRON_BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TRON_BASE58_CHARS = set(TRON_BASE58_ALPHABET)
TRON_BASE58_CHECK_VERSION = b"\x41"
TRON_HEX_ADDRESS_LENGTH = 42
TRON_TX_HASH_LENGTH = 64


@dataclass(frozen=True)
class TronUsdtTransfer:
    tx_hash: str
    block_number: int
    timestamp_ms: int
    from_address: str
    to_address: str
    contract_address: str
    raw_amount: int
    amount: Decimal


@dataclass(frozen=True)
class TronUsdtPaymentCandidate:
    out_trade_no: str
    monitor_address: str
    expected_raw_amount: int
    created_at_ms: int
    expires_at_ms: int

    def __post_init__(self) -> None:
        out_trade_no = _normalize_out_trade_no(self.out_trade_no)
        monitor_address = normalize_tron_address(self.monitor_address, field_name="monitor_address")
        expected_raw_amount = _normalize_positive_int(self.expected_raw_amount, "expected_raw_amount")
        created_at_ms = _normalize_non_negative_int(self.created_at_ms, "created_at_ms")
        expires_at_ms = _normalize_non_negative_int(self.expires_at_ms, "expires_at_ms")
        if expires_at_ms < created_at_ms:
            raise ValueError("expires_at_ms 不能早于 created_at_ms")
        object.__setattr__(self, "out_trade_no", out_trade_no)
        object.__setattr__(self, "monitor_address", monitor_address)
        object.__setattr__(self, "expected_raw_amount", expected_raw_amount)
        object.__setattr__(self, "created_at_ms", created_at_ms)
        object.__setattr__(self, "expires_at_ms", expires_at_ms)


@dataclass(frozen=True)
class TronUsdtMatchDecision:
    matched: bool
    reason: str
    out_trade_no: Optional[str]
    tx_hash: Optional[str]
    confirmations: int


class Trc20DirectPaymentProvider:
    provider = "usdt_trc20_direct"

    def __init__(self, config: Any, *, public_base_url: str) -> None:
        self._config = config
        self._public_base_url = public_base_url

    async def create_order(self, request: PaymentOrderRequest) -> PaymentCreateResult:
        if request.currency != "USDT":
            raise ValueError("TRC20 直付当前只支持 USDT 订单")
        amount = _normalize_usdt_decimal(request.amount)
        min_amount = _normalize_usdt_decimal(getattr(self._config, "min_usdt_amount", Decimal("0.01")))
        if amount < min_amount:
            raise ValueError("TRC20 直付金额低于最低支付金额")
        monitor_address = normalize_tron_address(getattr(self._config, "monitor_address", None))
        payment_url = build_trc20_direct_payment_url(
            self._public_base_url,
            out_trade_no=request.out_trade_no,
            monitor_address=monitor_address,
            amount=amount,
            asset=str(getattr(self._config, "asset", "USDT") or "USDT"),
            network=str(getattr(self._config, "network", "TRC20") or "TRC20"),
        )
        return PaymentCreateResult(
            provider=self.provider,
            out_trade_no=request.out_trade_no,
            provider_trade_no=None,
            payment_url=payment_url,
            raw_response={
                "offline_intent": True,
                "asset": "USDT",
                "network": "TRC20",
                "amount": _format_usdt_decimal(amount),
            },
        )

    def verify_callback(self, payload: dict[str, Any]) -> Any:
        raise NotImplementedError("TRC20 直付不支持公网回调")

    async def query_order(self, provider_trade_no: str) -> PaymentQueryResult:
        raise NotImplementedError("TRC20 直付不支持公网查单")


def build_trc20_direct_payment_url(
    public_base_url: str,
    *,
    out_trade_no: str,
    monitor_address: str,
    amount: Decimal,
    asset: str = "USDT",
    network: str = "TRC20",
) -> str:
    base_url = _normalize_public_base_url(public_base_url)
    order_no = _normalize_out_trade_no(out_trade_no)
    address = normalize_tron_address(monitor_address)
    normalized_amount = _normalize_usdt_decimal(amount)
    normalized_asset = _normalize_fixed_text(asset, "asset", expected="USDT")
    normalized_network = _normalize_fixed_text(network, "network", expected="TRC20")
    query = urlencode(
        {
            "address": address,
            "amount": _format_usdt_decimal(normalized_amount),
            "asset": normalized_asset,
            "network": normalized_network,
        }
    )
    return f"{base_url}/payments/trc20-direct/{order_no}?{query}"


def normalize_tron_address(value: Any, *, field_name: str = "monitor_address") -> str:
    text = _required_text(value, field_name, max_length=64)
    if len(text) != 34 or not text.startswith("T"):
        raise ValueError(f"{field_name} 必须是 TRON 地址")
    if any(char not in TRON_BASE58_CHARS for char in text):
        raise ValueError(f"{field_name} 必须是 TRON 地址")
    decoded = decode_base58(text)
    if len(decoded) != 25 or decoded[:1] != TRON_BASE58_CHECK_VERSION:
        raise ValueError(f"{field_name} 必须是 TRON 地址")
    checksum = hashlib.sha256(hashlib.sha256(decoded[:-4]).digest()).digest()[:4]
    if decoded[-4:] != checksum:
        raise ValueError(f"{field_name} 必须是 TRON 地址")
    return text


def decode_base58(value: str) -> bytes:
    number = 0
    for char in value:
        number = number * 58 + TRON_BASE58_ALPHABET.index(char)
    data = number.to_bytes((number.bit_length() + 7) // 8, "big") if number else b""
    leading_zero_count = len(value) - len(value.lstrip("1"))
    return (b"\x00" * leading_zero_count) + data


def tron_address_to_hex(address: Any, *, field_name: str = "address") -> str:
    normalized = normalize_tron_address(address, field_name=field_name)
    decoded = decode_base58(normalized)
    return decoded[:-4].hex()


def tron_address_from_hex(value: Any, *, field_name: str = "address") -> str:
    text = _normalize_hex(value, field_name)
    if len(text) == 40:
        text = "41" + text
    if len(text) != TRON_HEX_ADDRESS_LENGTH or not text.startswith("41"):
        raise ValueError(f"{field_name} 必须是 TRON hex 地址")
    payload = bytes.fromhex(text)
    checksum = hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:4]
    return _encode_base58(payload + checksum)


def normalize_tron_tx_hash(value: Any) -> str:
    text = _required_text(value, "tx_hash", max_length=66).lower()
    if text.startswith("0x"):
        text = text[2:]
    if len(text) != TRON_TX_HASH_LENGTH or any(char not in "0123456789abcdef" for char in text):
        raise ValueError("tx_hash 必须是 64 位十六进制字符串")
    return text


def trc20_usdt_raw_to_decimal(raw_amount: int) -> Decimal:
    raw = _normalize_positive_int(raw_amount, "raw_amount")
    return Decimal(raw) / Decimal(TRC20_USDT_SCALE)


def trc20_usdt_amount_to_raw(value: Any) -> int:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("USDT 金额必须是数字") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("USDT 金额必须大于 0")
    scaled = amount * Decimal(TRC20_USDT_SCALE)
    integral = scaled.to_integral_value()
    if scaled != integral:
        raise ValueError("USDT 金额最多支持 6 位小数")
    return int(integral)


def _normalize_usdt_decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("USDT 金额必须是数字") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("USDT 金额必须大于 0")
    normalized = amount.normalize()
    trc20_usdt_amount_to_raw(normalized)
    return normalized


def _format_usdt_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _normalize_public_base_url(value: Any) -> str:
    text = _required_text(value, "public_base_url", max_length=2048).rstrip("/")
    parts = urlsplit(text)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("PUBLIC_BASE_URL 必须是 http/https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("PUBLIC_BASE_URL 不能包含用户信息、query 或 fragment")
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))


def _normalize_fixed_text(value: Any, field_name: str, *, expected: str) -> str:
    text = _required_text(value, field_name, max_length=32).upper()
    if text != expected:
        raise ValueError(f"{field_name} 只支持 {expected}")
    return text


def parse_tron_usdt_transfer(transaction: Mapping[str, Any], *, block_number: int | None = None) -> TronUsdtTransfer | None:
    if not isinstance(transaction, Mapping):
        raise ValueError("transaction 必须是字典")
    tx_hash = normalize_tron_tx_hash(transaction.get("txID") or transaction.get("txid") or transaction.get("hash"))
    if not _is_success_transaction(transaction):
        return None

    raw_data = transaction.get("raw_data") or {}
    if not isinstance(raw_data, Mapping):
        raise ValueError("raw_data 必须是字典")
    contracts = raw_data.get("contract") or []
    if not isinstance(contracts, list) or not contracts:
        return None
    contract = contracts[0]
    if not isinstance(contract, Mapping):
        raise ValueError("contract 必须是字典")
    if contract.get("type") != "TriggerSmartContract":
        return None

    value = contract.get("parameter", {}).get("value", {})
    if not isinstance(value, Mapping):
        raise ValueError("contract value 必须是字典")
    data = _normalize_optional_call_data(value.get("data"))
    if data is None:
        return None
    if not data.startswith(TRC20_TRANSFER_METHOD_ID):
        return None
    if len(data) != 136:
        raise ValueError("TRC20 transfer calldata 长度无效")

    contract_address = tron_address_from_hex(value.get("contract_address"), field_name="contract_address")
    if contract_address != USDT_TRC20_CONTRACT_ADDRESS:
        return None

    raw_amount = int(data[72:136], 16)
    if raw_amount <= 0:
        raise ValueError("raw_amount 必须大于 0")
    resolved_block_number = _normalize_block_number(block_number, raw_data)
    timestamp_ms = _normalize_timestamp_ms(raw_data.get("timestamp") or transaction.get("timestamp"))
    return TronUsdtTransfer(
        tx_hash=tx_hash,
        block_number=resolved_block_number,
        timestamp_ms=timestamp_ms,
        from_address=tron_address_from_hex(value.get("owner_address"), field_name="owner_address"),
        to_address=tron_address_from_hex("41" + data[8:72][-40:], field_name="to_address"),
        contract_address=contract_address,
        raw_amount=raw_amount,
        amount=trc20_usdt_raw_to_decimal(raw_amount),
    )


def match_tron_usdt_transfer(
    transfer: TronUsdtTransfer,
    candidates: Iterable[TronUsdtPaymentCandidate],
    *,
    latest_block_number: int,
    required_confirmations: int = 1,
    seen_tx_hashes: Iterable[str] | None = None,
) -> TronUsdtMatchDecision:
    if not isinstance(transfer, TronUsdtTransfer):
        raise ValueError("transfer 必须是 TronUsdtTransfer")
    latest_block = _normalize_non_negative_int(latest_block_number, "latest_block_number")
    required = _normalize_non_negative_int(required_confirmations, "required_confirmations")
    confirmations = max(0, latest_block - transfer.block_number)
    normalized_seen = {normalize_tron_tx_hash(tx_hash) for tx_hash in (seen_tx_hashes or ())}
    if transfer.tx_hash in normalized_seen:
        return TronUsdtMatchDecision(False, "duplicate_tx", None, transfer.tx_hash, confirmations)
    if confirmations < required:
        return TronUsdtMatchDecision(False, "not_confirmed", None, transfer.tx_hash, confirmations)

    normalized_candidates = list(candidates)
    for candidate in normalized_candidates:
        if not isinstance(candidate, TronUsdtPaymentCandidate):
            raise ValueError("candidates 必须包含 TronUsdtPaymentCandidate")
    if not normalized_candidates:
        return TronUsdtMatchDecision(False, "no_candidate", None, transfer.tx_hash, confirmations)

    address_candidates = [candidate for candidate in normalized_candidates if candidate.monitor_address == transfer.to_address]
    if not address_candidates:
        return TronUsdtMatchDecision(False, "address_mismatch", None, transfer.tx_hash, confirmations)
    amount_candidates = [
        candidate for candidate in address_candidates if candidate.expected_raw_amount == transfer.raw_amount
    ]
    if not amount_candidates:
        return TronUsdtMatchDecision(False, "amount_mismatch", None, transfer.tx_hash, confirmations)
    time_candidates = [
        candidate
        for candidate in amount_candidates
        if candidate.created_at_ms <= transfer.timestamp_ms <= candidate.expires_at_ms
    ]
    if not time_candidates:
        return TronUsdtMatchDecision(False, "outside_time_window", None, transfer.tx_hash, confirmations)
    if len(time_candidates) > 1:
        return TronUsdtMatchDecision(False, "ambiguous", None, transfer.tx_hash, confirmations)
    return TronUsdtMatchDecision(True, "matched", time_candidates[0].out_trade_no, transfer.tx_hash, confirmations)


def _is_success_transaction(transaction: Mapping[str, Any]) -> bool:
    ret_list = transaction.get("ret") or []
    if not isinstance(ret_list, list) or not ret_list:
        return False
    first_ret = ret_list[0]
    return isinstance(first_ret, Mapping) and first_ret.get("contractRet") == "SUCCESS"


def _normalize_optional_call_data(value: Any) -> str | None:
    if value is None:
        return None
    text = _normalize_hex(value, "data")
    if not text:
        return None
    if len(text) % 2 != 0:
        raise ValueError("TRC20 calldata 必须是偶数长度十六进制字符串")
    return text


def _normalize_block_number(block_number: int | None, raw_data: Mapping[str, Any]) -> int:
    if block_number is not None:
        return _normalize_non_negative_int(block_number, "block_number")
    candidate = raw_data.get("block_number")
    if candidate is None:
        raise ValueError("block_number 不能为空")
    return _normalize_non_negative_int(candidate, "block_number")


def _normalize_timestamp_ms(value: Any) -> int:
    timestamp_ms = _normalize_non_negative_int(value, "timestamp_ms")
    if timestamp_ms <= 0:
        raise ValueError("timestamp_ms 必须大于 0")
    return timestamp_ms


def _normalize_positive_int(value: Any, field_name: str) -> int:
    number = _normalize_non_negative_int(value, field_name)
    if number <= 0:
        raise ValueError(f"{field_name} 必须大于 0")
    return number


def _normalize_non_negative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} 必须是整数")
    if value < 0:
        raise ValueError(f"{field_name} 不能为负数")
    return value


def _normalize_out_trade_no(value: Any) -> str:
    text = _required_text(value, "out_trade_no", max_length=96)
    return text


def _required_text(value: Any, field_name: str, *, max_length: int) -> str:
    text = str(value).strip() if value is not None else ""
    if not text:
        raise ValueError(f"{field_name} 不能为空")
    if len(text) > max_length:
        raise ValueError(f"{field_name} 长度不能超过 {max_length}")
    if any(ord(char) < 32 or ord(char) == 127 for char in text):
        raise ValueError(f"{field_name} 不能包含控制字符")
    return text


def _normalize_hex(value: Any, field_name: str) -> str:
    text = _required_text(value, field_name, max_length=4096).lower()
    if text.startswith("0x"):
        text = text[2:]
    if any(char not in "0123456789abcdef" for char in text):
        raise ValueError(f"{field_name} 必须是十六进制字符串")
    return text


def _encode_base58(data: bytes) -> str:
    number = int.from_bytes(data, "big")
    chars: list[str] = []
    while number:
        number, remainder = divmod(number, 58)
        chars.append(TRON_BASE58_ALPHABET[remainder])
    leading_zero_count = len(data) - len(data.lstrip(b"\x00"))
    return ("1" * leading_zero_count) + ("".join(reversed(chars)) if chars else "")
