#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

SUPPORTED_LANGUAGES = ("zh", "en")
DEFAULT_LANGUAGE = "zh"


TRANSLATIONS: dict[str, dict[str, str]] = {
    "zh": {
        "language.zh": "中文",
        "language.en": "English",
        "home.default_title": "欢迎选购",
        "home.default_intro": "请选择下方商品进行购买",
        "home.choose_product": "请选择商品：",
        "home.language_label": "语言 / Language",
        "common.back": "⬅️ 返回",
        "common.support": "💁联系客服",
        "common.buy": "🛒 购买",
        "common.unknown": "未知",
        "support.not_configured": "ℹ️ 暂未配置客服联系方式。",
        "support.title": "🆘 客服\n点击下方按钮",
        "support.contact": "🆘 客服联系方式：\n{contact}",
        "support.failed": "❗ 获取客服信息失败，请稍后重试。",
        "product.unavailable": "⚠️ 商品不存在或已下架",
        "product.no_tiers": "暂无可购买档位",
        "product.price_tiers": "💰 价格档位：",
        "product.detail_caption": " {name}\n\n{description}\n\n{price_title}\n{price_text}",
        "payment.choose_method": "商品：{subject}\n价格：¥{price}\n💳 请选择支付方式：",
        "payment.generating": "⏳ 正在生成付款链接，请稍候…\n请勿重复点击按钮，预计几秒完成。",
        "payment.min_amount": "❌ 该通道最小支付金额为 3.00 元，请返回重新选择支付方式或购买金额≥3.00 的商品。",
        "payment.create_failed": "❌ 下单失败：{error}\n请稍后重试，或返回重新选择支付方式。",
        "payment.acknowledged": "✅ 已确认",
        "payment.ack_button": "✅ 我知道了，继续支付",
        "payment.order_no": "🧾 订单号：{out_trade_no}",
        "payment.product_name": "📦 商品名：{subject}",
        "payment.product_detail": "📝 商品详情：{detail}",
        "payment.price": "💰 价格：¥{price}",
        "payment.method": "💳 支付方式：{method}",
        "payment.wallet": "📍 USDT钱包地址：`{address}`",
        "payment.link": "🔗 支付链接：{url}",
        "payment.timeout": "⏱️ 订单有效期约 {minutes} 分钟，超时将自动取消。",
        "payment.usdt_qr_hint": "提示：扫描上方二维码完成USDT支付，支付成功后请返回本聊天等待邀请链接。",
        "payment.usdt_link_hint": "提示：点击链接完成USDT支付，支付成功后系统会自动检测并发送邀请链接。",
        "payment.qr_caption": "📷 请扫码支付 ¥{price}\n🧾 订单号：{out_trade_no}\n⏱️ 订单有效期约 {minutes} 分钟，超时将自动取消。\n提示：支付成功后我会自动发送自动拉群邀请链接。",
        "payment.link_hint": "提示：若链接无法直接打开，可复制到浏览器；完成支付后请返回本聊天等待邀请链接。",
        "payment.cancelled": "✅ 已取消订单，正在返回商品列表…",
        "payment.confirm_cancel": "✅ 确定取消",
        "payment.continue_pay": "↩️ 继续付款",
        "payment.confirm_leave": "✅ 确定离开",
        "payment.stay_pay": "↩️ 留在付款台",
        "payment.recheck_too_fast": "⏳ 操作过于频繁，请稍后再试…",
        "payment.order_not_found": "未找到该订单，请返回重试。",
        "payment.expired": "⏱️ 订单已超时并取消，请返回重新下单。",
        "payment.not_paid": "尚未检测到支付成功，请完成支付后再点“🔄 我已支付，重新检查”。",
        "payment.current_status": "当前订单状态：{status}",
        "payment.recheck_button": "🔄 我已支付，重新检查",
        "payment.cancel_button": "❌ 取消本次付款",
        "announcement.usdt_default": "📢 USDT支付重要提醒\n\n\n⚠️ 请注意手续费问题\n\n🏦 交易所转账（火币/欧易/币安）\n   会扣 1U 手续费\n   商品价格 10U → 请转 11U\n   否则到账不足，无法自动拉群\n\n💳 钱包转账（推荐 ✅）\n   支持 Bitpie / TP / imToken 等钱包\n   直接按商品金额转（例：10U 转 10U）\n   钱包自动扣矿工费，到账准确，更省钱！\n\n⚡️ 付款即发货，1-3分钟快速到账\n   机器人自动拉你进会员群 ✅",
        "announcement.rmb_default": "📢 欢迎光临官方商店\n\n\n💳 微信 / 支付宝付款说明\n\n✅ 按提示金额准确付款即可\n✅ 支持微信扫码、支付宝扫码\n✅ 付款后请勿关闭页面\n\n⚡️ 付款即发货，1-3分钟快速到账\n   机器人自动拉你进会员群 ✅",
        "delivery.group_success": "🎉 已成功进群：{title}\n🔒 一次性邀请链接将自动撤销\n✅ 订单已完成 感谢支持！！！",
        "status.pending": "待支付",
        "status.paid": "已支付",
        "status.processing": "处理中",
        "status.completed": "已完成",
        "status.cancelled": "已取消",
        "status.expired": "已超时",
        "status.refunded": "已退款",
        "status.failed": "支付失败",
    },
    "en": {
        "language.zh": "中文",
        "language.en": "English",
        "home.default_title": "Welcome",
        "home.default_intro": "Please choose a product below",
        "home.choose_product": "Choose a product:",
        "home.language_label": "Language / 语言",
        "common.back": "⬅️ Back",
        "common.support": "💁 Contact Support",
        "common.buy": "🛒 Buy",
        "common.unknown": "Unknown",
        "support.not_configured": "ℹ️ Support contact has not been configured.",
        "support.title": "🆘 Support\nTap the button below",
        "support.contact": "🆘 Support contact:\n{contact}",
        "support.failed": "❗ Failed to get support info. Please try again later.",
        "product.unavailable": "⚠️ Product is unavailable or has been removed",
        "product.no_tiers": "No purchasable tiers yet",
        "product.price_tiers": "💰 Price tiers:",
        "product.detail_caption": " {name}\n\n{description}\n\n{price_title}\n{price_text}",
        "payment.choose_method": "Product: {subject}\nPrice: ¥{price}\n💳 Please choose a payment method:",
        "payment.generating": "⏳ Generating payment link, please wait...\nPlease do not tap repeatedly. This should take a few seconds.",
        "payment.min_amount": "❌ This channel requires a minimum payment of 3.00 CNY. Please go back and choose another payment method or buy a product priced at least 3.00 CNY.",
        "payment.create_failed": "❌ Failed to create order: {error}\nPlease try again later or choose another payment method.",
        "payment.acknowledged": "✅ Confirmed",
        "payment.ack_button": "✅ Got it, continue to pay",
        "payment.order_no": "🧾 Order No.: {out_trade_no}",
        "payment.product_name": "📦 Product: {subject}",
        "payment.product_detail": "📝 Details: {detail}",
        "payment.price": "💰 Price: ¥{price}",
        "payment.method": "💳 Payment method: {method}",
        "payment.wallet": "📍 USDT wallet address: `{address}`",
        "payment.link": "🔗 Payment link: {url}",
        "payment.timeout": "⏱️ Order expires in about {minutes} minutes and will be cancelled automatically.",
        "payment.usdt_qr_hint": "Tip: scan the QR code above to complete USDT payment, then return to this chat and wait for the invite link.",
        "payment.usdt_link_hint": "Tip: open the link to complete USDT payment. The system will detect payment and send the invite link automatically.",
        "payment.qr_caption": "📷 Please scan to pay ¥{price}\n🧾 Order No.: {out_trade_no}\n⏱️ Order expires in about {minutes} minutes and will be cancelled automatically.\nTip: after payment succeeds, I will send the group invite link automatically.",
        "payment.link_hint": "Tip: if the link cannot be opened directly, copy it into your browser. After payment, return to this chat and wait for the invite link.",
        "payment.cancelled": "✅ Order cancelled. Returning to product list...",
        "payment.confirm_cancel": "✅ Cancel order",
        "payment.continue_pay": "↩️ Continue payment",
        "payment.confirm_leave": "✅ Leave",
        "payment.stay_pay": "↩️ Stay on payment page",
        "payment.recheck_too_fast": "⏳ Too many attempts. Please try again later...",
        "payment.order_not_found": "Order not found. Please go back and try again.",
        "payment.expired": "⏱️ The order has expired and was cancelled. Please place a new order.",
        "payment.not_paid": "Payment has not been detected yet. Please complete payment, then tap \"🔄 I have paid, recheck\".",
        "payment.current_status": "Current order status: {status}",
        "payment.recheck_button": "🔄 I have paid, recheck",
        "payment.cancel_button": "❌ Cancel this payment",
        "announcement.usdt_default": "📢 Important USDT payment notice\n\n\n⚠️ Please mind transfer fees\n\n🏦 Exchange transfers (Huobi/OKX/Binance)\n   Usually deduct a 1U fee\n   Product price 10U → please transfer 11U\n   Otherwise the received amount may be insufficient\n\n💳 Wallet transfer (recommended ✅)\n   Supports Bitpie / TP / imToken and other wallets\n   Transfer the exact product amount (e.g. 10U for a 10U product)\n   Wallets deduct miner fees separately, which is more accurate and cheaper.\n\n⚡️ Instant delivery after payment, usually within 1-3 minutes\n   The bot will invite you to the member group automatically ✅",
        "announcement.rmb_default": "📢 Welcome to the official store\n\n\n💳 WeChat / Alipay payment instructions\n\n✅ Pay the exact amount shown\n✅ WeChat scan and Alipay scan are supported\n✅ Do not close the page after payment\n\n⚡️ Instant delivery after payment, usually within 1-3 minutes\n   The bot will invite you to the member group automatically ✅",
        "delivery.group_success": "🎉 Joined successfully: {title}\n🔒 The one-time invite link will be revoked automatically\n✅ Order completed. Thank you!",
        "status.pending": "Pending",
        "status.paid": "Paid",
        "status.processing": "Processing",
        "status.completed": "Completed",
        "status.cancelled": "Cancelled",
        "status.expired": "Expired",
        "status.refunded": "Refunded",
        "status.failed": "Payment failed",
    },
}


def normalize_language(language: Any) -> str:
    raw = str(language or "").strip().lower().replace("_", "-")
    if raw.startswith("en"):
        return "en"
    if raw.startswith("zh") or raw in {"cn", "中文"}:
        return "zh"
    return DEFAULT_LANGUAGE


def t(key: str, language: Any = DEFAULT_LANGUAGE, **kwargs: Any) -> str:
    lang = normalize_language(language)
    template = TRANSLATIONS.get(lang, {}).get(key) or TRANSLATIONS[DEFAULT_LANGUAGE].get(key) or key
    if not kwargs:
        return template
    try:
        return template.format(**kwargs)
    except Exception:
        return template


def language_button_label(language: Any, selected_language: Any | None = None) -> str:
    lang = normalize_language(language)
    label = t(f"language.{lang}", lang)
    return f"✅ {label}" if selected_language and normalize_language(selected_language) == lang else label
