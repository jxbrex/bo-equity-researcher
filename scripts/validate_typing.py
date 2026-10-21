#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_typing.py — 分型判据校验域（v5.8.3 自 validate.py 按域拆分）。

内容：typing_v2 校验组（枚举标准化/型↔层占比对账/扣非 CAGR 对账/typing_evidence
必填键/撞车白名单/weights 完整性）及 _bar_values/_hist_cagr/_cagr_adj_reasons
与分型常量（_TYPE_LAYER/_GROWTH_LAYER/_TYPE_EVIDENCE_KEYS/_TYPE_NONDEFAULT_WEIGHTS
/_CAGR_ADJ_*）。_normalize_stock_type/_resolve_type_tier 为跨域公共层（validate.py）。
契约：raise = 硬拒渲染；warns.append = 软告警。
"""
import re
from scoring import (
    _num)
from validate import (
    _is_hk_code,
    _normalize_stock_type,
    _resolve_type_tier)


_TYPE_LAYER = {"周期股": (70, 30), "稳定价值": (85, 15), "未盈利/管线": (75, 25),
               "困境反转": (70, 30), "成熟/停滞": (80, 20)}


_GROWTH_LAYER = {"high": (60, 40), "mid": (70, 30)}


_TYPE_EVIDENCE_KEYS = {
    "周期股": ("commodity_link", "volatility_fact", "comparable_periods"),
    "成长型": ("cagr_hist", "driver_nature", "shock_history"),
    "成熟/停滞": ("cagr_hist", "growth_narrative", "three_exclusions"),
    "稳定价值": ("franchise", "dividend_streak"),
    "未盈利/管线": ("loss_reason", "milestones"),
    "困境反转": ("normal_anchor", "catalyst_timeline", "cash_runway"),
}


_TYPE_NONDEFAULT_WEIGHTS = ("稳定价值", "未盈利/管线", "困境反转", "成熟/停滞")  # 层内权重非默认的型


def _bar_values(fill, key):
    """fin_trend 中 name 含 key 且 values 非空的柱 values（标准 4 面板之净利面板）。"""
    ft = fill.get("fin_trend") or {}
    for p in ft.get("panels") or []:
        for b in p.get("bars") or []:
            if key in str((b or {}).get("name") or ""):
                vals = (b or {}).get("values") or []
                if vals:
                    return vals
    return None


def _hist_cagr(fill, key="扣非"):
    """fin_trend 复算历史 CAGR（v5.4.0 改扣非口径）：years + panels 内 name 含 key 的
    bar 的 values（**与 years 等长且全可解析**、首尾正数、≥3 点）；数据不足/口径异常
    （不等长/含非数字/含负值）→ None——回落人工判定，不给门禁喂错窗口。
    归母柱不再作对账基准——一次性损益会把正常化路径算歪，口径例外由 cagr_adjustments 承接。"""
    ft = fill.get("fin_trend") or {}
    years = [str(y) for y in (ft.get("years") or [])]
    vals = _bar_values(fill, key)
    # v5.4.0 审计 P0-2：柱值与 years 不等长时 zip 静默截断 → CAGR 算错窗口（本数驱动拒渲染门禁）
    if not vals or len(vals) != len(years):
        return None
    nums = [_num(v) for v in vals]
    if len(nums) < 3 or any(v is None or v <= 0 for v in nums):
        return None  # <3 年/含非数字或非正值（亏损年、口径异常）→ 跳过对账（甘李/快手实证）
    y0 = re.sub(r"\D", "", years[0])[:4]
    y1 = re.sub(r"\D", "", years[-1])[:4]
    span = (int(y1) - int(y0)) if (y0 and y1) else (len(nums) - 1)
    if span < 1:
        return None
    return (nums[-1] / nums[0]) ** (1 / span) - 1


# v5.4.0 口径例外明细四键（typing_evidence.cagr_adjustments 每项必须齐全且非空）
_CAGR_ADJ_KEYS = ("year", "item", "amount", "reason")


# 例外 c 的触发词（v5.4.0 审计收窄）：去掉裸「调整」——「目标价调整」等无关说法不得触发
# 强制明细门禁；只认口径语义的词形（剔除/口径调整/重述/正常化/经调整）。
_CAGR_ADJ_KEYWORDS = ("剔除", "口径调整", "重述", "正常化", "经调整")


def _cagr_adj_reasons(fill: dict, te: dict) -> list:
    """cagr_adjustments 强制的三条例外（v5.4.0 口径收口）：
    a 港股 5 位代码（经调整口径）；b 扣非柱不可用（无柱/不等长/含非数字或非正值/有效年 <3）；
    c cagr_hist 含 _CAGR_ADJ_KEYWORDS（剔除/口径调整/重述/正常化/经调整，不含裸「调整」）。
    三条皆不成立 → 空列表（默认扣非口径直接复算）。"""
    reasons = []
    if _is_hk_code(fill):
        reasons.append("港股 5 位代码（经调整口径）")
    if _hist_cagr(fill) is None:
        reasons.append("扣非柱不可用（无扣非柱/不等长/含非数字或非正值/有效年 <3）")
    hist = str(te.get("cagr_hist") or "")
    kw = [k for k in _CAGR_ADJ_KEYWORDS if k in hist]
    if kw:
        reasons.append(f"cagr_hist 含口径调整词「{'/'.join(kw)}」")
    return reasons


def _check_typing_v2(fill: dict, warns: list) -> None:
    """分型判据 v2 校验组（v5.3.0）：枚举标准化（无法映射拒渲染）+ 型↔层占比对账 +
    成长层 CAGR 对账 + typing_evidence 必填键 + 撞车白名单（非白名单拒渲染）+
    weights 完整性（半填拒渲染）。首版软约束项均在文案注明，观察一轮后升级。
    v5.4.0：CAGR 对账改扣非口径；分型要求 cagr_hist 键时三条例外（港股 5 位代码 /
    扣非柱不可用 / cagr_hist 含口径调整词）任一命中 → cagr_adjustments 四键明细缺失或
    结构不全即拒渲染；明细齐备 → 按声明调整口径处理（人工判定）不复算（③扣非不可用
    分支经此到达——无明细时已被门禁先行拒渲染）。te/ok_adj 一次算清，对账与门禁共用。"""
    st_raw = str(fill.get("stock_type") or "")
    std, tier, legacy = _normalize_stock_type(st_raw)
    if not std:
        raise ValueError(
            f"stock_type={st_raw!r} 无法映射六型枚举（v5.3.0 判据 v2）："
            "周期股 / 稳定价值[子类] / 成长型（配 growth_tier）/ 成熟·停滞 / 未盈利·管线 / 困境反转；"
            "旧名「稳健/快速成长」请改为「成长型」+growth_tier")
    if legacy:
        warns.append(f"stock_type 旧名 {legacy!r}：v5.3.0 两型已合并为「成长型」，"
                     f"本报告按映射 成长型·{tier} 层处理——请改用新名 + growth_tier（首版软约束）")

    te = fill.get("typing_evidence") or {}
    need = _TYPE_EVIDENCE_KEYS.get(std) or ()
    # v5.4.0 口径收口：明细结构一次判定（对账跳过与强制门禁共用同一 ok_adj，
    # 残件如 [{}] 不再「非空即算数」静默关掉对账）
    adj = te.get("cagr_adjustments")
    ok_adj = (isinstance(adj, list) and bool(adj)
              and all(isinstance(a, dict)
                      and all(a.get(k) not in (None, "") and str(a.get(k)).strip() for k in _CAGR_ADJ_KEYS)
                      for a in adj))

    if std == "成长型":
        # v5.8.2：成长层解析收敛 _resolve_type_tier 单源（缺 tier 告警+默认 mid 随之）
        _, tier, _ = _resolve_type_tier(fill, warns)
        if ok_adj:
            # ① 明细齐备 → 人工判定（按声明调整口径），脚本不复算扣非 CAGR
            warns.append("growth_tier 对账按声明调整口径处理（人工判定）：typing_evidence.cagr_adjustments 非空，"
                         "脚本不复算扣非 CAGR——分层以声明为准，调整明细已入账")
            cagr = None
        else:
            # ② 扣非柱复算（口径例外走 ①；扣非不可用/不等长 → None——成长型此时无明细，
            # 已被下方门禁先拒渲染，故「人工判定」只经 ① 到达）
            cagr = _hist_cagr(fill)
        if cagr is not None:
            if tier == "high" and cagr < 0.20:
                warns.append(f"growth_tier=high 但 fin_trend 扣非 CAGR={cagr * 100:.1f}%"
                             "（高速层门槛 >25%，缓冲带 ±5pct 外）：分层与财务事实不符——"
                             "口径异常请在 typing_evidence.cagr_hist/cagr_adjustments 注明正常化依据")
            elif tier == "mid" and cagr > 0.30:
                warns.append(f"growth_tier=mid 但 fin_trend 扣非 CAGR={cagr * 100:.1f}%"
                             "（中速层 5-25%，缓冲带 ±5pct 外）：应归高速层（60:40 + 高速层权重），请复核")

    want = _GROWTH_LAYER.get(tier) if std == "成长型" else _TYPE_LAYER.get(std)
    ls_raw = fill.get("layer_share") or {}
    if want and ls_raw:
        l1 = _num(ls_raw.get("L1"))
        if l1 is not None and (int(l1), int(100 - l1)) != want:
            warns.append(f"layer_share {l1:g}:{100 - l1:g} 与 {std}{'·' + tier if std == '成长型' else ''} "
                         f"映射 {want[0]}:{want[1]} 不符（v5.3.0 型↔占比对账，首版软约束）")
    elif want and want != (70, 30):
        warns.append(f"{std} 层占比应为 {want[0]}:{want[1]}，未填 layer_share 将按默认 70:30 计算，分数可能错误")
    if (std in _TYPE_NONDEFAULT_WEIGHTS or (std == "成长型" and tier == "high")) and not fill.get("weights"):
        warns.append(f"{std}{'·高速层' if std == '成长型' else ''} 层内权重非默认，未填 weights——脚本将用基础权重计算，分数可能错误")

    miss = [k for k in need if not te.get(k)]
    if miss:
        warns.append(f"typing_evidence 缺键 {miss}（{std} 判据答案结构化，v5.3.0 首版软约束，观察一轮后升拒渲染）")
    # v5.4.0 口径收口：正常化口径须落明细——三条例外任一命中即强制 cagr_adjustments
    if "cagr_hist" in need:
        reasons = _cagr_adj_reasons(fill, te)
        if reasons and not ok_adj:
            raise ValueError(
                "typing_evidence.cagr_adjustments 缺失或结构不全（命中：" + "；".join(reasons) + "）："
                "正常化口径不成立时历史 CAGR 必须逐条给出调整明细——"
                '格式 [{"year":2024,"item":"处置子公司股权收益","amount":-6.2,"reason":"一次性损益剔除"}]'
                "（四键 year/item/amount/reason 齐全且非空，amount 单位亿元；v5.4.0 口径收口，拒渲染）")
        if ok_adj and not reasons:
            warns.append("typing_evidence.cagr_adjustments 已填但三条例外（港股 / 扣非柱不可用 / "
                         "cagr_hist 口径调整词）均不成立：默认扣非口径可直接复算，多余明细易成口径漂移口"
                         "——请删除该键（确需调整则把理由写进 cagr_hist）")

    tc = fill.get("typing_clash")
    if tc:
        w_std, _, _ = _normalize_stock_type(tc.get("with"))
        if not w_std or {std, w_std} != {"周期股", "成长型"}:
            raise ValueError(
                f"typing_clash.with={tc.get('with')!r} 非白名单共存对（仅 周期股×成长型）："
                "高成本撞车（涉红灯豁免或占比跳变 ≥15pct）必须消歧，禁止共存声明（v5.3.0）")
        cc = re.sub(r"<[^>]+>", "", str(tc.get("cross_check") or "")).strip()
        if len(cc) < 30:
            warns.append("typing_clash.cross_check <30 字：对照方法目标价互证/背离说明不足")

    w = fill.get("weights") or {}
    if w:
        has_l1 = any(k in w for k in ("1A", "1B", "1C", "1D", "1E", "1F"))
        has_l3 = any(k in w for k in ("3A", "3B", "3C"))
        if has_l1 != has_l3:
            raise ValueError("weights 半填：L1（1A-1F）与 L3（3A-3C）只填一层，另一层将静默回落默认权重拼算"
                             "（冰轮 2026-09-13 实证，侥幸零影响非设计）——两层必须同填或同不填（v5.3.0）")
