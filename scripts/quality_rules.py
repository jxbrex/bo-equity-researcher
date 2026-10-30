#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_rules.py — 九维规则化评分的纯函数研究原型。"""
import math
import re


_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _num(value):
    if isinstance(value, (int, float)):
        return float(value)
    match = _NUMBER_RE.search(str(value or "").replace("−", "-"))
    return float(match.group(0).replace(",", "")) if match else None


def _num_last(value):
    matches = _NUMBER_RE.findall(str(value or "").replace("−", "-"))
    return float(matches[-1].replace(",", "")) if matches else None


def _ratio(value):
    number = _num(value)
    if number is None:
        return None
    return number / 100 if isinstance(value, str) and "%" in value else number


BAND_BASE = {
    "A": (8.0, 10.0, 9.0),
    "B": (6.0, 7.9, 7.0),
    "C": (4.0, 5.9, 5.0),
    "D": (0.0, 3.9, 2.0),
}
_EXPLANATION_LOGIC = {
    "1A": "先判断生命周期，再按该阶段的需求、替代、格局、价格机制或成长指标定档",
    "1B": "按成本、价格传导、集中度与议价状态定档",
    "1C": "只计已验证且非话术的护城河，再结合趋势和压力测试定档",
    "1D": "九项趋势检查与流动性分别定档并取较低档，再执行红旗扣分",
    "1E": "从中性 6 分起，按质押、减持、继任、处罚及分红、回购、长期记录清单加减",
    "1F": "比较年化 ROIC 与 WACC，再结合增量 ROIC 和杠杆限制",
    "3A": "按未来增速下限与驱动兑现状态定档",
    "3B": "按利润贡献对项目阶段或可见度基础分加权",
    "3C": "只统计报告日起 12 个月内、月份明确且能引发重估的事件",
}


def _explain(result, band, basis, base_label=None, logic=None, cap_reason=None):
    label = base_label or f"{band}档代表分"
    base_note = ""
    has_adjustments = any(float(step.get("delta") or 0) != 0 for step in result["rule_steps"])
    if label == "A档代表分" and result["base"] == 9:
        if not has_adjustments and abs(result["final"] - 9) < 0.005:
            base_note = "9 是 A 档代表分，未获额外 +1，因此不是 10。"
        elif result["final"] >= 10:
            base_note = "A 档代表分 9，经实际 +1 调整后形成 10。"
    cap = result.get("cap")
    cap_note = ""
    if cap is not None and result["pre_cap"] > cap and abs(result["final"] - cap) < 0.005:
        cap_note = f"{cap_reason} {cap:.2f}" if cap_reason else f"证据上限 {cap:.2f}"
    if cap_note:
        basis += "；" + cap_note
    if base_note:
        basis += "；" + base_note
    result["explanation"] = {
        "logic": (logic or _EXPLANATION_LOGIC[result["key"]])
                 + "；再依次执行固定加减、档内 ±1 调整和硬上限。",
        "basis": basis,
        "base_label": label,
        "base_note": base_note,
        "cap_note": cap_note,
    }
    return result


DIM_KEYS = ("1A", "1B", "1C", "1D", "1E", "1F", "3A", "3B", "3C")
CRITICAL_KEYS = {"1C", "1D", "1E", "1F"}
BAND_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4}
F_ITEM_IDS = {
    "profit_positive": "1D.PROFIT_POSITIVE",
    "ocf_positive": "1D.OCF_POSITIVE",
    "roa_improving": "1D.ROA_IMPROVING",
    "cash_quality_ok": "1D.CASH_QUALITY",
    "long_debt_down": "1D.LONG_DEBT_DOWN",
    "short_cover_improving": "1D.SHORT_COVER_IMPROVING",
    "no_dilution": "1D.NO_DILUTION",
    "gross_margin_improving": "1D.GROSS_MARGIN_IMPROVING",
    "asset_turnover_improving": "1D.ASSET_TURNOVER_IMPROVING",
}
G_ITEM_IDS = {
    "ROA": "profit_positive", "CASH_ROA": "ocf_positive", "ACCRUAL": "cash_quality_ok",
    "LEVERAGE": "long_debt_down", "LIQUIDITY": "short_cover_improving",
    "NO_DILUTION": "no_dilution", "GROSS_MARGIN": "gross_margin_improving",
    "ASSET_TURNOVER": "asset_turnover_improving",
}
RULE_LABELS = {
    "1D.F.HITS": "九项财务检查", "1D.LIQUIDITY": "绝对流动性",
    "1D.GROSS_MARGIN_PEER.UNKNOWN": "同业毛利率对照",
    "1D.RED.RECEIVABLES": "应收恶化", "1D.RED.INVENTORY": "存货恶化",
    "1D.RED.GROSS_MARGIN_ANOMALY": "毛利率异常",
    "1D.G.ROA": "ROA", "1D.G.CASH_ROA": "现金 ROA", "1D.G.ACCRUAL": "应计质量",
    "1D.G.LEVERAGE": "财务杠杆", "1D.G.LIQUIDITY": "流动性",
    "1D.G.NO_DILUTION": "股本变化", "1D.G.GROSS_MARGIN": "毛利率",
    "1D.G.ASSET_TURNOVER": "资产周转", "1D.G.RD_INTENSITY_EVIDENCE": "研发强度证据",
    "1D.G.CAPEX_INTENSITY_EVIDENCE": "资本开支强度证据",
    "1D.CASH_RUNWAY": "现金跑道", "1F.CASH_RUNWAY": "现金跑道",
    "1E.PLEDGE": "质押", "1E.REDUCTION": "减持", "1E.SUCCESSION": "继任风险",
    "1E.PENALTIES": "监管处罚", "1F.INCREMENTAL_ROIC": "增量 ROIC",
}
GENERIC_RED_FLAGS = {"receivables", "inventory", "gross_margin_anomaly"}
PROFILE_FLAGS = {
    "generic": GENERIC_RED_FLAGS,
    "pharma_device": GENERIC_RED_FLAGS,
    "pharma_cxo": GENERIC_RED_FLAGS | {"order_cancellation", "price_war"},
    "resources_upstream": GENERIC_RED_FLAGS,
    "internet_platform": {"adjusted_profit_divergence", "investment_impairment", "goodwill"},
    "financial_bank": {"npl_trend", "provision_trend", "loan_migration", "cet1"},
    "financial_insurance": {"solvency", "combined_ratio", "reserve", "investment_assumption"},
    "financial_broker": {"proprietary_exposure", "net_capital", "credit_impairment", "leverage"},
    "pharma_pipeline": {"cash_runway", "capitalized_rd", "license_in", "clinical_disclosure"},
    "realestate_development": {"short_cover", "hidden_debt", "contract_liability", "capitalized_interest"},
    "pre_profit": {"cash_runway", "financing_gap"},
    "turnaround": {"cash_runway", "catalyst", "normal_anchor"},
}
PROFILE_KIND = {
    "generic": "generic_f", "pharma_device": "generic_f", "pharma_cxo": "generic_f",
    "resources_upstream": "generic_f", "internet_platform": "generic_f",
    "financial_bank": "industry_checklist", "financial_insurance": "industry_checklist",
    "financial_broker": "industry_checklist", "pharma_pipeline": "survival_checklist",
    "realestate_development": "industry_checklist", "pre_profit": "survival_checklist",
    "turnaround": "survival_checklist",
}
FINANCIAL_PROFILES = {"financial_bank", "financial_insurance", "financial_broker"}
SPECIAL_1B_PROFILES = FINANCIAL_PROFILES | {"internet_platform", "pharma_cxo"}
RULE_REGISTRY = {
    "profiles": {
        profile: {"1B": {"kind": "two_strength_axes" if profile in SPECIAL_1B_PROFILES else "value_chain"},
                  "1D": {"kind": PROFILE_KIND[profile], "red_flags": sorted(PROFILE_FLAGS[profile]),
                          "required": sorted(F_ITEM_IDS) if PROFILE_KIND[profile] == "generic_f" else []},
                  "1F": {"kind": "cash_runway" if PROFILE_KIND[profile] == "survival_checklist"
                         else "financial_return" if profile in FINANCIAL_PROFILES else "roic"}}
        for profile in PROFILE_KIND
    },
    "rules": {rule_id: {"home": "1D"} for rule_id in F_ITEM_IDS.values()},
}


def _missing(key, reason="必需事实缺失"):
    return {"key": key, "status": "missing", "band": None, "base": None,
            "rule_steps": [{"id": f"{key}.MISSING", "evidence": reason, "delta": None}],
            "custom": None, "cap": None, "final": None, "critical": False,
            "missing_reason": reason}


def _band_for_score(value):
    if value >= 8:
        return "A"
    if value >= 6:
        return "B"
    if value >= 4:
        return "C"
    return "D"


def _custom(spec):
    custom = spec.get("custom") or {}
    if isinstance(custom, list):
        items = [item for item in custom if item is not None]
        if any(not isinstance(item, dict) for item in items):
            raise ValueError("复合调整必须逐项填写 id、理由和证据")
        raw_points = [_num(item.get("points", 0) or 0) for item in items]
        if any(value is None for value in raw_points):
            raise ValueError("调整值必须为数字")
        points = sum(raw_points)
        if not math.isfinite(points) or abs(points) > 1:
            raise ValueError("分析师调整只能在 ±1 内")
        for item in items:
            if item.get("points") and (not item.get("id") or not item.get("reason") or not item.get("evidence")):
                raise ValueError("清单外调整必须填写 id、理由和证据")
        return {"id": "CUSTOM.COMPOSITE", "points": points,
                "reason": "；".join(str(item.get("reason", "")) for item in items),
                "evidence": "；".join(str(item.get("evidence", "")) for item in items),
                "items": items}, points
    points = _num(custom.get("points", 0) or 0)
    if points is None or not math.isfinite(points) or abs(points) > 1:
        raise ValueError("分析师调整只能在 ±1 内")
    if points and (not custom.get("id") or not custom.get("reason") or not custom.get("evidence")):
        raise ValueError("清单外调整必须填写 id、理由和证据")
    return custom, float(points)


def _finish(key, band, base, steps, spec, cap=None, status="ok"):
    custom, points = _custom(spec)
    fixed = sum(float(step.get("delta") or 0) for step in steps)
    pre = base + fixed
    if band in BAND_BASE:
        current_band = _band_for_score(pre)
        lo, hi, _ = BAND_BASE[current_band]
    else:
        current_band = "CUSTOM"
        lo, hi = band
    pre_cap = min(hi, max(lo, pre + points))
    final = pre_cap
    if cap is not None:
        final = min(final, cap)
    if band in BAND_BASE:
        current_band = _band_for_score(final)
    if points or custom.get("items"):
        if custom.get("items"):
            steps.extend({"id": item.get("id") or f"{key}.CUSTOM", "evidence": item.get("evidence", ""),
                          "reason": item.get("reason", ""), "delta": float(item.get("points", 0) or 0)}
                         for item in custom["items"])
        else:
            steps.append({"id": custom.get("id") or f"{key}.CUSTOM", "evidence": custom.get("evidence", ""),
                          "reason": custom.get("reason", ""), "delta": points})
    return {"key": key, "status": status, "band": current_band if band in BAND_BASE else "CUSTOM",
            "base": round(base, 2), "rule_steps": steps, "custom": custom or None,
            "pre_cap": round(pre_cap, 2), "cap": cap, "final": round(final, 2),
            "critical": key in CRITICAL_KEYS and final < 4}


def _required(mapping, keys, key):
    missing = [name for name in keys if name not in mapping or mapping[name] is None]
    return _missing(key, "缺少: " + ", ".join(missing)) if missing else None


POLICY_ALIASES = {
    "tailwind": "tailwind", "顺风": "tailwind", "positive": "tailwind", "favorable": "tailwind",
    "friendly": "tailwind", "supportive": "tailwind",
    "neutral": "neutral", "中性": "neutral", "中性偏暖": "neutral", "偏暖": "neutral",
    "mixed": "mixed", "中性偏紧": "mixed", "偏负": "mixed", "偏空": "mixed", "unfavorable": "mixed",
    "negative": "mixed", "suppressed": "negative", "打压": "negative",
}


def _eval_1a(spec, context):
    stage = spec.get("stage")
    if not stage:
        return _missing("1A", "缺少生命周期阶段")
    if stage not in ("mature", "成熟期", "decline", "衰退期", "growth", "成长期"):
        return _missing("1A", "未知生命周期阶段")
    raw_policy = spec.get("policy")
    policy = POLICY_ALIASES.get(str(raw_policy or "").lower())
    if raw_policy is not None and policy is None:
        return _missing("1A", "未知政策口径")
    policy_text = {"tailwind": "政策顺风", "neutral": "政策中性", "mixed": "政策中性偏紧",
                   "negative": "政策明确打压"}.get(policy, "政策口径未获取")
    if stage in ("mature", "成熟期"):
        missing = _required(spec, ("demand_decline_2y", "structure_ok", "price_mechanism_ok", "policy"), "1A")
        if missing:
            return missing
        for name in ("demand_decline_2y", "substitution_low", "structure_ok", "price_mechanism_ok"):
            if spec.get(name) is not None and not isinstance(spec[name], bool):
                return _missing("1A", f"{name} 必须为布尔值")
        substitution_unknown = spec.get("substitution_low") is None
        if spec["demand_decline_2y"] or policy == "negative":
            band = "D"
        elif (spec["substitution_low"] and spec["structure_ok"] and spec["price_mechanism_ok"]
              and policy != "mixed"):
            band = "A"
        elif spec["structure_ok"] and (spec["substitution_low"] or substitution_unknown):
            band = "B"
        else:
            band = "C"
        steps = [{"id": "1A.MATURE.CHECK", "evidence": "需求/替代/格局/价格机制", "delta": 0}]
        if substitution_unknown:
            steps.append({"id": "1A.SUBSTITUTION.UNKNOWN", "evidence": "替代威胁未获取，最高只能落B档", "delta": 0})
        substitution = spec.get("substitution_low")
        facts = [
            "需求连续两年衰退" if spec["demand_decline_2y"] else "需求未连续两年衰退",
            "替代威胁未知" if substitution_unknown else "替代威胁低" if substitution else "替代威胁不低",
            "格局良好" if spec["structure_ok"] else "格局不佳",
            "价格机制正常" if spec["price_mechanism_ok"] else "价格机制不正常",
            policy_text,
        ]
        reasons = {
            "A": "替代低、格局与价格机制正常且政策非偏紧 → A 档",
            "B": "格局良好且替代威胁低或未知 → B 档",
            "C": "未满足 A/B 档条件 → C 档",
            "D": "需求连续两年衰退或政策明确打压 → D 档",
        }
        result = _finish("1A", band, BAND_BASE[band][2], steps, spec,
                         cap=7.9 if substitution_unknown else None)
        return _explain(result, band, "、".join(facts) + "；" + reasons[band])
    if stage in ("decline", "衰退期"):
        band = "D"
        result = _finish("1A", band, BAND_BASE[band][2],
                         [{"id": "1A.LIFECYCLE.DECLINE", "evidence": "衰退期", "delta": 0}], spec)
        return _explain(result, band, "生命周期为衰退期 → D 档")
    missing = _required(spec, ("growth", "policy"), "1A")
    if missing:
        return missing
    growth, tam, penetration = _num(spec["growth"]), _num(spec.get("tam")), _num(spec.get("penetration"))
    top_missing = [name for name in ("tam", "penetration") if spec.get(name) is None]
    if growth is None or (spec.get("tam") is not None and tam is None) \
            or (spec.get("penetration") is not None and penetration is None):
        return _missing("1A", "行业增速/TAM/渗透率格式无法解析")
    if growth < 0 or policy == "negative":
        band = "D"
    elif policy == "mixed":
        band = "C"
    elif not top_missing and growth > 15 and tam >= 1000 and penetration < 30 and policy == "tailwind":
        band = "A"
    elif growth >= 5:
        band = "B"
    else:
        band = "C"
    tam_txt = "未获取" if tam is None else f"{tam:g}"
    penetration_txt = "未获取" if penetration is None else f"{penetration:g}%"
    steps = [{"id": "1A.GROWTH.CHECK", "evidence": f"增速{growth}%/TAM{tam_txt}/渗透率{penetration_txt}", "delta": 0}]
    if top_missing:
        steps.append({"id": "1A.TOP_EVIDENCE.UNKNOWN", "evidence": "缺" + "/".join(top_missing) + "，最高只能落B档", "delta": 0})
    result = _finish("1A", band, BAND_BASE[band][2], steps, spec, cap=7.9 if top_missing else None)
    reasons = {
        "A": "增速>15%、TAM≥1000 亿元、渗透率<30%且政策顺风 → A 档",
        "B": "增速≥5%，但未同时满足 A 档全部条件 → B 档",
        "C": "增速<5%或政策中性偏紧 → C 档",
        "D": "负增长或政策明确打压 → D 档",
    }
    tam_basis = "未获取" if tam is None else f"{tam:g} 亿元"
    basis = (f"行业增速 {growth:g}%、TAM {tam_basis}、渗透率 {penetration_txt}、{policy_text}；"
             + reasons[band])
    return _explain(result, band, basis)


def _eval_industry_1b(spec, context):
    keys = ("cost_strength", "pricing_strength", "bargaining_status")
    missing = _required(spec, keys, "1B")
    if missing:
        return missing
    cost, pricing = spec["cost_strength"], spec["pricing_strength"]
    if cost not in ("strong", "neutral", "weak") or pricing not in ("strong", "neutral", "weak"):
        return _missing("1B", "未知成本或定价强度")
    concentration_unknown = (spec.get("customer_concentration") is None
                             or spec.get("supplier_concentration") is None)
    customer = _ratio(spec.get("customer_concentration"))
    supplier = _ratio(spec.get("supplier_concentration"))
    concentrated = any(value is not None and value > 0.5 for value in (customer, supplier))
    if concentrated and spec["bargaining_status"] == "实质丧失":
        band = "D"
    else:
        strong = (cost == "strong") + (pricing == "strong")
        band = "A" if strong == 2 else "B" if strong == 1 else "C"
    steps = [{"id": "1B.INDUSTRY_AXES",
              "evidence": f"{context.get('industry_profile')}/成本{cost}/定价{pricing}", "delta": 0}]
    if concentration_unknown:
        steps.append({"id": "1B.CONCENTRATION.UNKNOWN", "evidence": "客户或供应商集中度未知", "delta": 0})
    result = _finish("1B", band, BAND_BASE[band][2], steps, spec,
                     cap=7.9 if concentration_unknown else None)
    labels = {"strong": "强", "neutral": "中性", "weak": "弱"}
    strong = (cost == "strong") + (pricing == "strong")
    reason = ("集中度>50%且议价权实质丧失 → D 档" if band == "D" else
              {2: "两强 → A 档", 1: "一强 → B 档", 0: "不强 → C 档"}[strong])
    customer_text = "未知" if customer is None else f"{customer:.0%}"
    supplier_text = "未知" if supplier is None else f"{supplier:.0%}"
    basis = (f"成本{labels[cost]}、定价{labels[pricing]}；{reason}；"
             f"客户/供应商集中度 {customer_text}/{supplier_text}")
    return _explain(result, band, basis,
                    logic="比较成本与定价强弱，并核查集中度和议价状态")


def _eval_1b(spec, context):
    if context.get("industry_profile") in SPECIAL_1B_PROFILES:
        return _eval_industry_1b(spec, context)
    keys = ("cost_quartile", "price_transmission", "bargaining_status")
    missing = _required(spec, keys, "1B")
    if missing:
        return missing
    if not isinstance(spec["price_transmission"], bool):
        return _missing("1B", "price_transmission 必须为布尔值")
    concentration_unknown = (spec.get("customer_concentration") is None
                             or spec.get("supplier_concentration") is None)
    customer = _ratio(spec.get("customer_concentration"))
    supplier = _ratio(spec.get("supplier_concentration"))
    concentrated = any(value is not None and value > 0.5 for value in (customer, supplier))
    cost_quartile = spec["cost_quartile"]
    if isinstance(cost_quartile, str):
        cost_quartile = {"第一四分位": 1, "第一": 1, "第二四分位": 2, "第二": 2,
                         "第三四分位": 3, "第三": 3, "第四四分位": 4, "第四": 4}.get(cost_quartile, cost_quartile)
    if concentrated and spec["bargaining_status"] == "实质丧失":
        band = "D"
    else:
        self_supply = _ratio(spec.get("upstream_self_supply")) or 0
        cost_strong = cost_quartile == 1 or self_supply > 0.5
        price_strong = bool(spec["price_transmission"])
        band = "A" if cost_strong and price_strong else "B" if cost_strong or price_strong else "C"
    steps = [{"id": "1B.VALUE_CHAIN", "evidence": "成本/传导/集中度/议价状态", "delta": 0}]
    if spec.get("upstream_self_supply") is None:
        steps.append({"id": "1B.SELF_SUPPLY.UNKNOWN", "evidence": "上游自给率未获取，改用成本曲线分位", "delta": 0})
    if concentration_unknown:
        steps.append({"id": "1B.CONCENTRATION.UNKNOWN", "evidence": "客户或供应商集中度未知", "delta": 0})
    result = _finish("1B", band, BAND_BASE[band][2], steps, spec,
                     cap=7.9 if concentration_unknown else None)
    cost_strong = cost_quartile == 1 or (_ratio(spec.get("upstream_self_supply")) or 0) > 0.5
    price_strong = bool(spec["price_transmission"])
    facts = f"成本{'强' if cost_strong else '不强'}、价格{'可传导' if price_strong else '难以传导'}"
    if band == "D":
        reason = "集中度>50%且议价权实质丧失 → D 档"
    elif band == "A":
        reason = "成本与价格传导双强 → A 档"
    elif band == "B":
        reason = "成本或价格传导仅一端强 → B 档"
    else:
        reason = "成本与价格传导均不强 → C 档"
    customer_text = "未知" if customer is None else f"{customer:.0%}"
    supplier_text = "未知" if supplier is None else f"{supplier:.0%}"
    basis = f"{facts}；{reason}；客户/供应商集中度 {customer_text}/{supplier_text}"
    if spec.get("upstream_self_supply") is None:
        basis += "；上游自给率未获取，按成本曲线分位"
    return _explain(result, band, basis)


def _eval_1c(spec, context):
    moats = spec.get("moats")
    pressure = spec.get("pressure")
    if moats is None:
        return _missing("1C", "缺少护城河清单")
    for moat in moats:
        if not isinstance(moat.get("verified"), bool) or not isinstance(moat.get("rhetoric"), bool):
            return _missing("1C", "护城河 verified/rhetoric 必须为布尔值")
    valid = [m for m in moats if m.get("verified") and not m.get("rhetoric")]
    for moat in valid:
        if any(not isinstance(moat.get(field), str) or not moat[field].strip()
               for field in ("type", "replication", "evidence")):
            return _missing("1C", "有效护城河缺少类型、复制成本或证据")
        if moat.get("trend") not in (None, "widening", "stable", "narrowing", "unknown"):
            return _missing("1C", "未登记护城河趋势")
    if pressure not in (None, "unknown", "扛得住", "警惕", "扛不住"):
        return _missing("1C", "未登记压力测试结论")
    rhetoric_only = not valid and bool(moats)
    narrowing = any(m.get("trend") == "narrowing" for m in valid)
    has_stable_or_widening = any(m.get("trend") in ("stable", "widening") for m in valid)
    if narrowing and not has_stable_or_widening:
        band = "C"
    elif narrowing:
        band = "B"
    elif len(valid) >= 2:
        band = "A"
    elif len(valid) == 1:
        band = "B"
    elif rhetoric_only:
        band = "C"
    else:
        band = "D"
    cap = 5.9 if rhetoric_only else 7.9 if pressure == "扛不住" else None
    if narrowing and has_stable_or_widening:
        cap = 7.9 if cap is None else min(cap, 7.9)
    if spec.get("inverse_position") and len(valid) <= 1:
        cap = 7.9 if cap is None else min(cap, 7.9)
    if any(moat.get("trend") in (None, "unknown") for moat in valid):
        cap = 7.9 if cap is None else min(cap, 7.9)
    steps = [{"id": "1C.MOAT.COUNT", "evidence": f"有效护城河{len(valid)}条", "delta": 0}]
    for i, moat in enumerate(valid, 1):
        steps.append({"id": f"1C.MOAT.{i}", "evidence": moat.get("evidence", ""),
                      "trend": moat.get("trend"), "delta": 0})
    if pressure == "扛不住":
        steps.append({"id": "1C.PRESSURE.FAIL", "evidence": "压力测试扛不住", "delta": 0})
    elif pressure in (None, "unknown"):
        steps.append({"id": "1C.PRESSURE.UNKNOWN", "evidence": "未取得压力测试，最高只能落B档", "delta": 0})
        cap = 7.9 if cap is None else min(cap, 7.9)
    result = _finish("1C", band, BAND_BASE[band][2], steps, spec, cap=cap)
    trend_names = {"widening": "变宽", "stable": "稳定", "narrowing": "变窄", "unknown": "未知", None: "未知"}
    trends = "/".join(trend_names[moat.get("trend")] for moat in valid) if valid else "无有效护城河"
    pressure_text = "未获取" if pressure is None else "未知" if pressure == "unknown" else pressure
    reasons = {
        "A": "≥2 条且无变窄趋势 → A 档",
        "B": "1 条有效护城河，或存在混合变窄趋势 → B 档",
        "C": "仅话术或有效护城河全部变窄 → C 档",
        "D": "无有效护城河 → D 档",
    }
    basis = f"有效护城河 {len(valid)} 条；趋势：{trends}；压力测试：{pressure_text}；{reasons[band]}"
    return _explain(result, band, basis)


def _ocf_liquidity_exemption(liquidity):
    ratio = liquidity.get("ocf_short_cover")
    return liquidity["short_cover"] < 1 and ratio is not None and ratio > 2


def _liquidity_band(liquidity):
    debt, cover = liquidity["debt_ratio"], liquidity["short_cover"]
    if debt > 0.7 and cover < 1:
        band = "D"
    elif debt < 0.3 and cover >= 1.5:
        band = "A"
    elif debt <= 0.5 and cover >= 1:
        band = "B"
    else:
        band = "C"
    if _ocf_liquidity_exemption(liquidity):
        return {"D": "C", "C": "B", "B": "A", "A": "A"}[band]
    return band


def _eval_generic_f(spec, profile, context=None):
    items = spec.get("f_items")
    liquidity = spec.get("liquidity")
    if not items:
        return _missing("1D", "缺少F式清单")
    missing_values = [name for name in F_ITEM_IDS if not isinstance(items.get(name), bool)]
    if missing_values:
        return _missing("1D", "F项缺失或未知: " + ", ".join(missing_values))
    if not liquidity or liquidity.get("debt_ratio") is None or liquidity.get("short_cover") is None:
        return _missing("1D", "缺少绝对流动性")
    flags = spec.get("red_flags") or {}
    allowed = PROFILE_FLAGS[profile]
    unknown = set(flags) - allowed
    if "cash_quality" in unknown:
        raise ValueError("现金含量已并入F项，禁止重复扣分")
    if unknown:
        raise ValueError(f"未登记的1D红旗项: {sorted(unknown)}")
    missing_flags = [name for name in allowed if name != "gross_margin_anomaly"
                     and not isinstance(flags.get(name), bool)]
    if missing_flags:
        return _missing("1D", "红旗项缺失或未知: " + ", ".join(sorted(missing_flags)))
    if "gross_margin_anomaly" in flags and flags["gross_margin_anomaly"] is not None \
            and not isinstance(flags["gross_margin_anomaly"], bool):
        return _missing("1D", "毛利率异常红旗须为布尔值或 null")
    gross_unknown = "gross_margin_anomaly" not in flags or flags["gross_margin_anomaly"] is None
    raw_hits = sum(items[name] for name in F_ITEM_IDS)
    hits = raw_hits
    misses = {name for name in F_ITEM_IDS if not items[name]}
    seen = set()
    group_steps = []
    for group, names in (spec.get("f_causal_groups") or {}).items():
        names = set(names)
        if names - set(F_ITEM_IDS):
            raise ValueError(f"未登记的F因果项: {sorted(names - set(F_ITEM_IDS))}")
        if seen & names:
            raise ValueError(f"同一F项不得重复归组: {sorted(seen & names)}")
        seen |= names
        evidence = (spec.get("f_causal_evidence") or {}).get(group)
        if not isinstance(evidence, str) or not evidence.strip():
            raise ValueError(f"F因果组 {group} 缺少归并证据")
        group_misses = misses & names
        if group_misses:
            hits += len(group_misses) - 1
            group_steps.append({"id": f"1D.CAUSAL_GROUP.{group}",
                                "evidence": f"{evidence.strip()}；同一因果链只计一次: {sorted(group_misses)}",
                                "delta": 0})
    trend_band = "A" if hits >= 8 else "B" if hits >= 6 else "C" if hits >= 4 else "D"
    liquidity_band = _liquidity_band(liquidity)
    band = trend_band if BAND_ORDER[trend_band] >= BAND_ORDER[liquidity_band] else liquidity_band
    steps = [{"id": F_ITEM_IDS[name], "evidence": str(items[name]), "delta": 0}
             for name in F_ITEM_IDS]
    steps.extend(group_steps)
    if "成长" in str((context or {}).get("stock_type") or ""):
        for name, f_name in G_ITEM_IDS.items():
            value = items.get(f_name)
            steps.append({"id": f"1D.G.{name}", "evidence": str(value) if value is not None else "未核实", "delta": 0})
        for name in ("rd_intensity_evidence", "capex_intensity_evidence"):
            evidence = (spec.get("g_checks") or {}).get(name)
            steps.append({"id": f"1D.G.{name.upper()}",
                          "evidence": evidence or "未核实", "delta": 0})
    hit_evidence = f"原始{raw_hits}/9，因果归并后{hits}/9" if hits != raw_hits else f"命中{hits}/9"
    steps.append({"id": "1D.F.HITS", "evidence": hit_evidence, "delta": 0})
    steps.append({"id": "1D.LIQUIDITY", "evidence": str(liquidity), "delta": 0})
    if _ocf_liquidity_exemption(liquidity):
        steps.append({"id": "1D.LIQUIDITY.OCF_EXEMPTION",
                      "evidence": f"经营现金流/短债={liquidity['ocf_short_cover']:.2f}>2，流动性上调一档",
                      "delta": 0})
    elif liquidity["short_cover"] < 1 and liquidity.get("ocf_short_cover") is None:
        steps.append({"id": "1D.LIQUIDITY.OCF_UNKNOWN",
                      "evidence": "经营现金流/短债未知，不适用豁免", "delta": 0})
    materiality = spec.get("red_flag_materiality") or {}
    materiality_evidence = spec.get("red_flag_materiality_evidence") or {}
    for name, hit in flags.items():
        if hit and materiality.get(name) is False:
            evidence = materiality_evidence.get(name)
            scale = evidence.get("scale") if isinstance(evidence, dict) else None
            source = evidence.get("source") if isinstance(evidence, dict) else None
            if (isinstance(scale, str) and _NUMBER_RE.search(scale)
                    and isinstance(source, str) and source.strip()):
                text = f"{scale.strip()}（{source.strip()}）"
                steps.append({"id": f"1D.RED.{name.upper()}.IMMATERIAL",
                              "evidence": text, "delta": 0})
            else:
                steps.append({"id": f"1D.RED.{name.upper()}",
                              "evidence": "不具重大性但缺规模与来源证据，按红旗扣1分", "delta": -1})
        elif hit:
            steps.append({"id": f"1D.RED.{name.upper()}", "evidence": str(hit), "delta": -1})
    if gross_unknown:
        steps.append({"id": "1D.GROSS_MARGIN_PEER.UNKNOWN", "evidence": "同业毛利率对照缺失，最高只能落B档", "delta": 0})
    result = _finish("1D", band, BAND_BASE[band][2], steps, spec,
                     cap=7.9 if gross_unknown else None)
    trend_reason = {"A": "通过 8—9 项 → A 档", "B": "通过 6—7 项 → B 档",
                    "C": "通过 4—5 项 → C 档", "D": "通过 0—3 项 → D 档"}[trend_band]
    if _ocf_liquidity_exemption(liquidity):
        liquidity_reason = (f"短债覆盖<1，但经营现金流/短债 {liquidity['ocf_short_cover']:.2f}>2，"
                            f"上调一档为 {liquidity_band} 档")
    else:
        liquidity_reason = {
            "A": "有息负债率<30%且短债覆盖≥1.5 → A 档",
            "B": "有息负债率≤50%且短债覆盖≥1 → B 档",
            "C": "其余负债率与短债覆盖组合 → C 档",
            "D": "有息负债率>70%且短债覆盖<1 → D 档",
        }[liquidity_band]
    merged = f"（因果归并前 {raw_hits}/9 项）" if hits != raw_hits else ""
    basis = (f"九项检查通过 {hits}/9 项{merged}，{trend_reason}，即趋势轨 {trend_band} 档；"
             f"有息负债率 {liquidity['debt_ratio']:.2%}、短债覆盖 {liquidity['short_cover']:.2f} 倍，"
             f"{liquidity_reason}，即流动性轨 {liquidity_band} 档；取较低档为 {band} 档")
    return _explain(result, band, basis)


def _eval_industry_checklist(spec, profile):
    flags = spec.get("industry_checks")
    if not flags:
        return _missing("1D", "缺少行业检查清单")
    required = [name for name in sorted(PROFILE_FLAGS[profile]) if flags.get(name) != "not_applicable"]
    not_applicable = [name for name in sorted(PROFILE_FLAGS[profile]) if flags.get(name) == "not_applicable"]
    evidence_map = spec.get("industry_check_evidence") or {}
    missing_evidence = [name for name in not_applicable
                        if not isinstance(evidence_map.get(name), str) or not evidence_map[name].strip()]
    if missing_evidence:
        return _missing("1D", "不适用缺少逐项依据: " + ", ".join(missing_evidence))
    missing = [name for name in required if not isinstance(flags.get(name), bool)]
    if missing:
        return _missing("1D", "行业检查缺失或未知: " + ", ".join(missing))
    if not required:
        return _missing("1D", "全部行业检查均不适用，未提供替代输入")
    good = sum(not flags[name] for name in required)
    total = len(required)
    band = ("A" if good == total else "B" if good == total - 1
            else "C" if good == total - 2 and total > 2 else "D")
    steps = [{"id": f"1D.{profile.upper()}.{name.upper()}",
              "evidence": str(flags[name]), "delta": 0} for name in required]
    if not_applicable:
        steps.append({"id": "1D.NOT_APPLICABLE",
                      "evidence": "；".join(f"{name}: {evidence_map[name].strip()}"
                                           for name in not_applicable), "delta": 0})
    result = _finish("1D", band, BAND_BASE[band][2], steps, spec)
    reason = ("全部适用项通过 → A 档" if band == "A" else
              "仅 1 项未通过 → B 档" if band == "B" else
              "2 项未通过 → C 档" if band == "C" else "其余结果 → D 档")
    basis = f"行业检查通过 {good}/{total} 项；{reason}"
    if not_applicable:
        basis += f"；另有 {len(not_applicable)} 项有依据地判为不适用"
    return _explain(result, band, basis, logic="按本行业专项清单的通过与未通过项定档")


def _eval_survival_checklist(spec, profile):
    if spec.get("industry_checks") is not None:
        return _eval_industry_checklist(spec, profile)
    runway = spec.get("cash_runway_months")
    if runway is None:
        return _missing("1D", "缺少现金跑道或行业检查清单")
    band = "A" if runway >= 24 else "B" if runway >= 18 else "C" if runway >= 12 else "D"
    result = _finish("1D", band, BAND_BASE[band][2],
                     [{"id": "1D.CASH_RUNWAY", "evidence": f"{runway}个月", "delta": 0}], spec)
    reason = {"A": "≥24 个月 → A 档", "B": "18—24 个月 → B 档",
              "C": "12—18 个月 → C 档", "D": "<12 个月 → D 档"}[band]
    return _explain(result, band, f"现金跑道 {runway:.2f} 个月；{reason}",
                    logic="按现金可维持经营的月数定档")


def _eval_1d(spec, context):
    profile = context.get("industry_profile") or "generic"
    if profile not in PROFILE_KIND:
        return _missing("1D", f"未登记行业profile: {profile}")
    kind = PROFILE_KIND[profile]
    if kind == "generic_f":
        return _eval_generic_f(spec, profile, context)
    if kind == "industry_checklist":
        return _eval_industry_checklist(spec, profile)
    return _eval_survival_checklist(spec, profile)


def _eval_1e(spec, context):
    required = ("pledge_pct", "reduction_pct", "penalties")
    missing = _required(spec, required, "1E")
    if missing:
        return missing
    steps = []
    age = _num(spec.get("age"))
    if age is None:
        steps.append({"id": "1E.AGE.UNKNOWN", "evidence": "年龄未获取，不据此加扣分", "delta": 0})
    pledge, reduction = _ratio(spec["pledge_pct"]), _ratio(spec["reduction_pct"])
    if pledge is None or reduction is None:
        return _missing("1E", "质押或减持比例格式无法解析")
    if pledge > 0.7:
        steps.append({"id": "1E.PLEDGE", "evidence": str(pledge), "delta": -1})
    elif pledge > 0.5:
        steps.append({"id": "1E.PLEDGE", "evidence": str(pledge), "delta": -0.5})
    if reduction > 0.02:
        steps.append({"id": "1E.REDUCTION", "evidence": str(reduction), "delta": -1})
    elif reduction > 0.005:
        steps.append({"id": "1E.REDUCTION", "evidence": str(reduction), "delta": -0.5})
    if (age or 0) > 68 and not spec.get("succession_plan"):
        steps.append({"id": "1E.SUCCESSION", "evidence": str(age), "delta": -0.5})
    if spec["penalties"]:
        steps.append({"id": "1E.PENALTIES", "evidence": str(spec["penalties"]), "delta": -1})
    positive = 0
    dividend = spec.get("dividend") or {}
    payout_streak = _num(dividend.get("payout_streak")) or 0
    growth_streak = _num(dividend.get("growth_streak")) or 0
    if payout_streak >= 3 or growth_streak >= 5:
        positive += 0.5
        steps.append({"id": "1E.DIVIDEND", "evidence": str(dividend), "delta": 0.5})
    buyback = spec.get("buyback") or {}
    if buyback.get("cancel"):
        positive += 0.5
        steps.append({"id": "1E.BUYBACK", "evidence": str(buyback), "delta": 0.5})
    raw_record = spec.get("long_record")
    if isinstance(raw_record, bool):
        if raw_record:
            return _missing("1E", "长期资本配置记录缺少具体类型")
        record = {}
    else:
        record = raw_record or {}
    if record.get("dividend_growth") or record.get("low_buyback"):
        positive += 1
        steps.append({"id": "1E.LONG_RECORD", "evidence": str(record), "delta": 1})
    if record.get("ma_roic"):
        raise ValueError("并购ROIC只归1F，禁止在1E重复加分")
    if positive > 2:
        positive = 2
    if positive and not any(step["id"] == "1E.POSITIVE_CAP" for step in steps):
        steps.append({"id": "1E.POSITIVE_CAP", "evidence": f"正向合计{positive}", "delta": 0})
    result = _finish("1E", "D", 6.0, steps, spec, cap=9.0)
    basis = (f"中性 6 分起；本次质押 {pledge:.2%}、近 12 个月减持 {reduction:.2%}、"
             f"重大处罚：{'有' if spec['penalties'] else '无'}；再按清单实际命中加减，"
             "正向清单最高 +2，最终最高 9")
    return _explain(result, "D", basis, base_label="中性起点")


def _eval_financial_1f(spec, profile):
    metric = spec.get("return_metric")
    allowed = {"ROTCE", "ROE_NORMALIZED"} if profile == "financial_bank" else {"ROE_NORMALIZED"}
    if metric not in allowed:
        return _missing("1F", "金融1F缺少确定的正常化ROE/ROTCE口径")
    normalized, coe = _ratio(spec.get("normalized_return")), _ratio(spec.get("coe"))
    if ((normalized is not None and abs(normalized) > 1) or (coe is not None and coe > 1)):
        raise ValueError("正常化回报与股权成本必须使用小数口径")
    if normalized is None or coe is None or coe <= 0:
        return _missing("1F", "缺少正常化回报/股权成本或股权成本非正")
    coverage = normalized / coe
    if coverage >= 1.5:
        band, base = "A", 9.0
    elif coverage >= 1.0:
        band, base = (5.0, 7.0), 6.0
    else:
        band, base = "D", 2.0
    steps = [{"id": "1F.NORMALIZED_RETURN_COE",
              "evidence": f"{metric}覆盖{coverage:.3f}", "delta": 0}]
    cap = 4.0 if coverage < 1 else 7.9 if spec.get("dupont_driver") == "杠杆" else None
    result = _finish("1F", band, base, steps, spec, cap=cap)
    band_name = "A" if band == "A" else "D" if band == "D" else "B"
    reason = ("覆盖≥1.5 → A 档，基础分 9" if band_name == "A" else
              "1.0≤覆盖<1.5 → 基础分 6（仅覆盖资金成本）" if band_name == "B" else
              "覆盖<1.0 → D 档，基础分 2，档位边界最高 3.9")
    metric_label = {"ROE_NORMALIZED": "正常化 ROE", "ROTCE": "正常化 ROTCE"}[metric]
    basis = f"{metric_label} {normalized:.2%}、COE {coe:.2%}；覆盖 {coverage:.3f} 倍；{reason}"
    cap_reason = ("回报覆盖不足 1.0，规则上限" if coverage < 1 else
                  "杠杆主驱动，规则上限" if cap is not None else None)
    return _explain(result, band_name, basis,
                    base_label="回报覆盖基础分" if band_name == "B" else None,
                    logic="比较正常化 ROE/ROTCE 与股权成本 COE，再结合杠杆限制",
                    cap_reason=cap_reason)


def requires_normalized_roic(context):
    return ("周期" in str(context.get("stock_type") or "")
            or context.get("industry_profile") == "resources_upstream")


def _eval_1f(spec, context):
    profile = context.get("industry_profile") or "generic"
    if profile in FINANCIAL_PROFILES:
        return _eval_financial_1f(spec, profile)
    runway = spec.get("cash_runway_months")
    if PROFILE_KIND[profile] == "survival_checklist" and runway is not None and spec.get("roic") is None:
        band = "A" if runway >= 24 else "B" if runway >= 18 else "C" if runway >= 12 else "D"
        result = _finish("1F", band, BAND_BASE[band][2],
                         [{"id": "1F.CASH_RUNWAY", "evidence": f"{runway}个月", "delta": 0}], spec)
        reason = {"A": "≥24 个月 → A 档", "B": "18—24 个月 → B 档",
                  "C": "12—18 个月 → C 档", "D": "<12 个月 → D 档"}[band]
        return _explain(result, band, f"现金跑道 {runway:.2f} 个月；{reason}",
                        logic="生存型公司按现金可维持经营的月数定档")
    roic, wacc = _ratio(spec.get("roic")), _ratio(spec.get("wacc"))
    incremental = _ratio(spec.get("incremental_roic"))
    if ((roic is not None and abs(roic) > 1) or (wacc is not None and wacc > 1)
            or (incremental is not None and abs(incremental) > 1)):
        raise ValueError("ROIC、WACC与增量ROIC必须使用小数口径，不得混用百分数")
    if roic is None or wacc is None or wacc <= 0:
        return _missing("1F", "缺少ROIC/WACC或WACC非正")
    basis = spec.get("roic_basis") or "latest"
    if basis not in ("latest", "normalized"):
        return _missing("1F", "未知ROIC口径")
    if requires_normalized_roic(context) and basis != "normalized":
        return _missing("1F", "周期股必须使用正常化ROIC，不能用最新累计期回报替代")
    components = []
    if basis == "normalized":
        raw_components = spec.get("roic_normalized_components")
        if not isinstance(raw_components, list) or len(raw_components) != 3:
            return _missing("1F", "正常化ROIC须保留最近三个完整年度组成")
        components = [_ratio(value) for value in raw_components]
        if any(value is None or abs(value) > 1 for value in components):
            raise ValueError("三年ROIC组成必须为小数口径且绝对值不大于1")
        median = sorted(components)[1]
        if abs(roic - median) > 1e-6:
            return _missing("1F", "正常化ROIC与三个年度组成的中位数不一致")
    months = 12 if basis == "normalized" else _num(spec.get("roic_period_months"))
    if months not in (3, 6, 9, 12):
        return _missing("1F", "ROIC报告期须为3/6/9/12个月")
    annual_roic = roic if basis == "normalized" else roic * 12 / months
    coverage = annual_roic / wacc
    if coverage >= 1.5:
        band, base = "A", 9.0
    elif coverage >= 1.0:
        band, base = (5.0, 7.0), 6.0
    else:
        band, base = "D", 2.0
    steps = [{"id": "1F.ROIC_WACC", "evidence": f"覆盖{coverage:.3f}（年化ROIC {annual_roic:.2%}）", "delta": 0}]
    if components:
        steps.append({"id": "1F.ROIC_COMPONENTS", "evidence": str(components), "delta": 0})
    if incremental is not None:
        delta = 1 if incremental > 1.5 * wacc else -1 if incremental < wacc else 0
        steps.append({"id": "1F.INCREMENTAL_ROIC", "evidence": str(incremental), "delta": delta})
    cap = 7.9 if spec.get("dupont_driver") == "杠杆" else 4.0 if coverage < 1 else None
    result = _finish("1F", band, base, steps, spec, cap=cap)
    band_name = "A" if band == "A" else "D" if band == "D" else "B"
    reason = ("覆盖≥1.5 → A 档，基础分 9" if band_name == "A" else
              "1.0≤覆盖<1.5 → 基础分 6（仅覆盖资金成本）" if band_name == "B" else
              "覆盖<1.0 → D 档，基础分 2，档位边界最高 3.9")
    reader_basis = (f"年化 ROIC {annual_roic:.2%}、WACC {wacc:.2%}；"
                    f"覆盖 {coverage:.3f} 倍；{reason}")
    if components:
        reader_basis += "；三年 ROIC：" + "/".join(f"{value:.2%}" for value in components)
    cap_reason = ("杠杆主驱动，规则上限" if spec.get("dupont_driver") == "杠杆" else
                  "回报覆盖不足 1.0，规则上限" if coverage < 1 else None)
    return _explain(result, band_name, reader_basis,
                    base_label="回报覆盖基础分" if band_name == "B" else None,
                    cap_reason=cap_reason)


def _eval_3a(spec, context):
    required = ("growth_lo", "growth_hi", "driver_status")
    missing = _required(spec, required, "3A")
    if missing:
        return missing
    threshold = 25 if context.get("growth_tier") in ("high", "高速层", "高速", "快速成长") else 20
    lo, hi, driver = _num(spec["growth_lo"]), _num_last(spec["growth_hi"]), spec["driver_status"]
    if lo is None or hi is None:
        return _missing("3A", "增速区间格式无法解析")
    if driver not in ("已验证", "部分兑现", "未验证"):
        return _missing("3A", "未知驱动兑现状态")
    if lo > threshold and driver == "已验证":
        band = "A"
    elif lo >= 10 and driver in ("已验证", "部分兑现"):
        band = "B"
    elif lo >= 0:
        band = "C"
    else:
        band = "D"
    result = _finish("3A", band, BAND_BASE[band][2],
                     [{"id": "3A.GROWTH", "evidence": f"下限{lo}%/驱动{driver}/阈值{threshold}%", "delta": 0}], spec)
    reasons = {
        "A": f"增速下限>{threshold}%且驱动已验证 → A 档",
        "B": "增速下限≥10%且驱动已验证或部分兑现 → B 档",
        "C": "增速下限≥0，但未满足 A/B 档条件 → C 档",
        "D": "增速下限<0 → D 档",
    }
    return _explain(result, band, f"增速下限 {lo:.1f}%、驱动{driver}、A 档阈值 {threshold}%；{reasons[band]}")


def _eval_primary_group(items, names, scores, steps, spec, projects_mode):
    if not isinstance(names, (list, tuple)) or not names:
        raise ValueError("组合主来源必须列明核心条目")
    names = set(names)
    selected = [item for item in items if item.get("name") in names]
    if len(selected) != len(names):
        raise ValueError("组合主来源条目与清单不一致")
    key = "stage" if projects_mode else "level"
    base, cap, weakest = None, 7.9, None
    for item in selected:
        marker = item.get(key)
        if marker not in scores:
            kind = "项目阶段" if projects_mode else "可见度层级"
            return _missing("3B", f"未知{kind}: {marker}")
        score = scores[marker]
        if not projects_mode and marker != "纯叙事" and item.get("value") is None:
            score = 2
            cap = 5.0
        if base is None or score < base:
            base, weakest = score, item
    steps.append({"id": "3B.PRIMARY_GROUP",
                  "evidence": f"组合最弱项{weakest.get('name')}/{weakest.get(key)}/最高7.9", "delta": 0})
    result = _finish("3B", _band_for_score(base), base, steps, spec, cap=cap)
    basis = (f"组合最弱项「{weakest.get('name')}」：{weakest.get(key)} {base:g} 分；"
             "利润权重缺失或合计不为 1，按组合最弱核心项定基础分")
    if cap == 5.0 and base == 2:
        basis += "；非纯叙事项缺少数值，缺数值上限 5 与缺权重上限 7.9 取更严者，本次未触及上限"
    return _explain(result, _band_for_score(base), basis, base_label="组合主来源基础分",
                    logic="缺少完整利润贡献权重时，按组合主来源中最弱核心项定基础分")


def _invalid_contributions(items, default=0):
    for item in items:
        value = _num(item.get("contribution", default))
        if value is None or not math.isfinite(value) or not 0 <= value <= 1:
            return True
    return False


def _eval_3b_items(spec, items, marker_key, scores, default_weight, projects_mode):
    steps = []
    kind = "项目" if projects_mode else "可见度"
    if _invalid_contributions(items, default_weight):
        return _missing("3B", f"{kind}利润贡献权重必须为0-1有限数")
    total = sum(float(item.get("contribution", default_weight)) for item in items)
    if abs(total - 1) > 0.01:
        if spec.get("primary_group") is not None:
            if any(item.get("primary") is True for item in items):
                raise ValueError("主来源与组合主来源不得同时指定")
            return _eval_primary_group(items, spec["primary_group"], scores, steps, spec, projects_mode)
        primaries = [item for item in items if item.get("primary") is True]
        if not primaries:
            raise ValueError(f"{kind}利润贡献权重之和必须为1")
        if len(primaries) != 1:
            raise ValueError("缺权重时必须标记唯一利润主来源")
        primary = primaries[0]
        marker = primary.get(marker_key)
        if marker not in scores:
            marker_kind = "项目阶段" if projects_mode else "可见度层级"
            return _missing("3B", f"未知{marker_kind}: {marker}")
        base = scores[marker]
        cap = 7.9
        if not projects_mode and marker != "纯叙事" and primary.get("value") is None:
            base, cap = 2, 5.0
        steps.append({"id": "3B.PRIMARY_FALLBACK",
                      "evidence": f"{primary.get('name')}/{marker}/缺权重最高7.9", "delta": 0})
        result = _finish("3B", _band_for_score(base), base, steps, spec, cap=cap)
        basis = (f"唯一利润主来源「{primary.get('name')}」：{marker} {base:g} 分；"
                 "利润权重缺失或合计不为 1，按主来源定基础分")
        if cap == 5.0 and base == 2:
            basis += "；非纯叙事项缺少数值，缺数值上限 5 与缺权重上限 7.9 取更严者，本次未触及上限"
        return _explain(result, _band_for_score(base), basis, base_label="主来源基础分",
                        logic="缺少完整利润贡献权重时，按唯一明确的利润主来源定基础分")
    base = 0
    cap = None
    basis_parts = []
    for item in items:
        marker = item.get(marker_key)
        if marker not in scores:
            marker_kind = "项目阶段" if projects_mode else "可见度层级"
            return _missing("3B", f"未知{marker_kind}: {marker}")
        score = scores[marker]
        if not projects_mode and marker != "纯叙事" and item.get("value") is None:
            score, cap = 2, 5.0
        weight = float(item.get("contribution", default_weight))
        base += score * weight
        basis_parts.append(f"{item.get('name', kind)}：{marker} {score:g} 分×{weight:.0%}")
        if projects_mode:
            step_id = f"3B.PROJECT.{item.get('name', len(steps))}"
            evidence = f"{marker}/权重{weight}"
        else:
            step_id = f"3B.VISIBILITY.{item.get('name', len(steps))}"
            evidence = f"{marker}/权重{weight}/数值{item.get('value')}"
        steps.append({"id": step_id, "evidence": evidence, "delta": 0})
    result = _finish("3B", _band_for_score(base), base, steps, spec, cap=cap)
    basis = "；".join(basis_parts) + f"；按利润贡献加权基础分 {base:.2f}"
    return _explain(result, _band_for_score(base), basis,
                    base_label="项目加权基础分" if projects_mode else "可见度加权基础分")


def _eval_3b(spec, context):
    projects = spec.get("projects")
    visibility = spec.get("visibility")
    if projects is None and visibility is None:
        return _missing("3B", "缺少项目或可见度清单")
    if projects is not None:
        if not projects:
            return _missing("3B", "项目清单为空")
        scores = {"已投产": 9, "试生产": 9, "在建": 7, "审批中": 5, "资金未落实": 5, "规划": 2, "意向": 2}
        return _eval_3b_items(spec, projects, "stage", scores, 0, True)
    if not visibility:
        result = _finish("3B", "D", 2.0, [], spec)
        return _explain(result, "D", "无项目或可见度条目 → D 档",
                        logic="无项目或可见度条目时直接落 D 档")
    scores = {"合约级": 9, "可量化扩张": 7, "趋势平缓": 5, "纯叙事": 2}
    default_weight = 1 if len(visibility) == 1 else 0
    return _eval_3b_items(spec, visibility, "level", scores, default_weight, False)


def _eval_3c(spec, context):
    events = spec.get("events")
    report_date = context.get("report_date")
    if events is None:
        return _missing("3C", "缺少催化剂清单")
    try:
        report_year, report_month = map(int, report_date[:7].split("-"))
    except (AttributeError, TypeError, ValueError):
        return _missing("3C", "缺少有效报告日期")
    valid, directional = [], False
    for event in events:
        month = event.get("month") or ""
        if not month:
            directional = True
            continue
        try:
            year, mon = map(int, month.split("-"))
            if not 1 <= mon <= 12:
                continue
        except (AttributeError, TypeError, ValueError):
            continue
        distance = (year - report_year) * 12 + mon - report_month
        if 0 <= distance <= 12:
            if event.get("revaluation"):
                valid.append(event)
            else:
                directional = True
    band = "A" if len(valid) >= 2 else "B" if len(valid) == 1 else "C" if directional else "D"
    steps = [{"id": "3C.EVENT_COUNT", "evidence": f"明确月份重估事件{len(valid)}个", "delta": 0}]
    result = _finish("3C", band, BAND_BASE[band][2], steps, spec, cap=5.9 if band == "C" else None)
    reasons = {
        "A": "12 个月内 ≥2 个 → A 档",
        "B": "12 个月内 1 个 → B 档",
        "C": "仅有方向性事件（未确认重估或月份不可验证）→ C 档，最高 5.9",
        "D": "无窗口内明确月份的重估事件 → D 档",
    }
    return _explain(result, band, f"明确月份重估事件 {len(valid)} 个；{reasons[band]}")


def evaluate_dimension(key: str, spec: dict, context: dict) -> dict:
    """按唯一规则注册表评价一个维度；不读取自由文本判断。"""
    if key not in DIM_KEYS:
        raise ValueError(f"未知评分维度: {key}")
    handlers = {"1A": _eval_1a, "1B": _eval_1b, "1C": _eval_1c, "1D": _eval_1d,
                "1E": _eval_1e, "1F": _eval_1f, "3A": _eval_3a, "3B": _eval_3b, "3C": _eval_3c}
    return handlers[key](spec or {}, context or {})


def evaluate_dimensions(score_inputs: dict, context: dict) -> dict:
    """逐维计算；缺必需维时不返回质量分，也绝不重归一化权重。"""
    dimensions = {}
    for key in DIM_KEYS:
        if key not in score_inputs:
            dimensions[key] = _missing(key)
            continue
        try:
            dimensions[key] = evaluate_dimension(key, score_inputs[key], context)
        except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
            dimensions[key] = _missing(key, str(exc))
    complete = all(result["status"] == "ok" for result in dimensions.values())
    critical = [{"key": key, "score": dimensions[key]["final"]}
                for key in sorted(CRITICAL_KEYS) if dimensions[key]["critical"]]
    quality = None
    weights = (context or {}).get("weights")
    layer_share = (context or {}).get("layer_share")
    if complete and weights and layer_share:
        l1 = sum(dimensions[key]["final"] * float(weights[key]) for key in DIM_KEYS[:6]) / 100
        l3 = sum(dimensions[key]["final"] * float(weights[key]) for key in DIM_KEYS[6:]) / 100
        quality = round((l1 * float(layer_share["L1"]) + l3 * float(layer_share["L3"])) / 100, 2)
    return {"dimensions": dimensions, "critical_weaknesses": critical,
            "complete": complete, "quality": quality}
