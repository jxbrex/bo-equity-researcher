#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_common.py — 跨校验域共享的常量与工具，不依赖任何 validate_* 域模块。"""
import json
import re


_HTML_FIELDS = ("thesis_html", "conclusion_html", "p0_html", "l1_html", "l3_html", "l4_html",
                "valuation_html", "gap_html", "peers_html", "dash_html", "position_html", "review_html")
_HTML_TABLE_FIELDS = _HTML_FIELDS[1:]


_TYPE_ALIASES = [
    ("稳定价值", "稳定价值", None),
    ("稳健成长", "成长型", "mid"),
    ("快速成长", "成长型", "high"),
    ("停滞", "成熟/停滞", None),
    ("未盈利", "未盈利/管线", None),
    ("管线", "未盈利/管线", None),
    ("困境反转", "困境反转", None),
    ("周期", "周期股", None),
    ("成长", "成长型", None),
]


def _is_hk_code(fill: dict) -> bool:
    """港股判定单源：fill.code 为 5 位数字即港股。"""
    return bool(re.fullmatch(r"\d{5}", str(fill.get("code") or "").strip()))


def _quote_ref(fill: dict):
    """读 quote.source_file 落盘 JSON；未声明、读不到或根节点非对象时返回 None。"""
    q = fill.get("quote")
    if not isinstance(q, dict) or not q.get("source_file"):
        return None
    try:
        with open(q["source_file"], encoding="utf-8") as f:
            ref = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
    return ref if isinstance(ref, dict) else None


def _scenario_by_key(scenarios, key):
    """按 key 取情景，大小写不敏感；返回匹配 dict 或 None。"""
    k = str(key or "").lower()
    for s in scenarios or []:
        if isinstance(s, dict) and str(s.get("key") or "").lower() == k:
            return s
    return None


def _normalize_stock_type(st):
    """stock_type 自由文本 → (标准型, 默认成长层, legacy 旧名)。"""
    st = str(st or "")
    for kw, std, tier in _TYPE_ALIASES:
        if kw in st:
            legacy = st if (std == "成长型" and kw in ("稳健成长", "快速成长")) else None
            return std, tier, legacy
    return None, None, None


def _resolve_type_tier(fill: dict, warns: list = None):
    """返回标准分型、实际成长层和旧名；成长型缺层时按 mid 处理。"""
    std, tier, legacy = _normalize_stock_type(fill.get("stock_type"))
    if std == "成长型":
        gt = str(fill.get("growth_tier") or "").strip().lower()
        if gt in ("high", "mid"):
            tier = gt
        elif tier is None:
            if warns is not None:
                warns.append("growth_tier 缺失：成长型须声明 high（扣非 CAGR>25%）/ mid 分层（v5.3.0），本报告按 mid 处理")
            tier = "mid"
    return std, tier, legacy


def _anchor_unanchored_type(fill: dict) -> bool:
    """估值带依赖历史 PE 时段锚的四型。"""
    st = str(fill.get("stock_type") or "")
    if any(k in st for k in ("周期", "稳定价值", "困境反转")):
        return True
    return "成长" in st and str(fill.get("growth_tier") or "").strip().lower() != "high"
