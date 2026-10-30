#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_score.py — 评分类图族（v4.9 从 charts.py 拆出）：07 九维评分分布横条（build_score_bars）/ 02 敏感性龙卷风（build_sensitivity_tornado）。依赖 charts_base 与 scoring。"""

import re

from scoring import DIMS, LAYER_NAMES, badge_class, _dim_verdict, _fmt, _esc
from quality_rules import F_ITEM_IDS, RULE_LABELS
from charts_base import *


_F_LABELS = {
    "profit_positive": "利润为正", "ocf_positive": "经营现金流为正", "roa_improving": "ROA 改善",
    "cash_quality_ok": "现金含量合格", "long_debt_down": "长期有息负债下降",
    "short_cover_improving": "短债覆盖改善", "no_dilution": "无股本稀释",
    "gross_margin_improving": "毛利率改善", "asset_turnover_improving": "资产周转改善",
}
_F_MISS = {
    "profit_positive": "利润为负", "ocf_positive": "经营现金流为负", "roa_improving": "ROA 未改善",
    "cash_quality_ok": "现金含量不合格", "long_debt_down": "长期有息负债未下降",
    "short_cover_improving": "短债覆盖未改善", "no_dilution": "存在股本稀释",
    "gross_margin_improving": "毛利率未改善", "asset_turnover_improving": "资产周转未改善",
}
_PROFILE_LABELS = {
    "pharma_cxo": "医药 CXO", "pharma_device": "医药器械", "resources_upstream": "上游资源",
    "internet_platform": "平台互联网", "financial_bank": "银行", "financial_insurance": "保险",
    "financial_broker": "券商", "realestate_development": "开发地产", "generic": "通用",
}


def _delta_text(value):
    return f"{float(value):+.2f}".replace("-", "−")


def _score_label(step):
    rule_id = str(step.get("id") or "")
    if rule_id.startswith("1D.RED."):
        return RULE_LABELS.get(rule_id, "财务风险")
    if "CUSTOM" in rule_id:
        return "清单外调整"
    return RULE_LABELS.get(rule_id, "")


def _score_text(key, step, spec):
    rule_id = str(step.get("id") or "")
    evidence = str(step.get("evidence") or "")
    if rule_id in ("1D.CASH_RUNWAY", "1F.CASH_RUNWAY"):
        return f"{float(evidence.removesuffix('个月')):.2f} 个月"
    if rule_id == "1D.F.HITS":
        items = spec.get("f_items") or {}
        if not items:
            return evidence.replace("命中", "通过", 1)
        merged = re.fullmatch(r"原始(\d+)/9，因果归并后(\d+)/9", evidence)
        hits = sum(items.get(name) is True for name in F_ITEM_IDS)
        misses = [_F_MISS[name] for name in F_ITEM_IDS if items.get(name) is False]
        unknown = [_F_LABELS[name] for name in F_ITEM_IDS if not isinstance(items.get(name), bool)]
        text = (f"通过 {merged.group(2)}/9 项（因果归并前 {merged.group(1)}/9 项）" if merged
                else f"通过 {hits}/{len(F_ITEM_IDS)} 项")
        if misses:
            text += "；原始未通过：" if merged else "；未通过："
            text += "、".join(misses)
        if unknown:
            text += "；未核实：" + "、".join(unknown)
        return text
    if rule_id == "1D.LIQUIDITY":
        values = spec.get("liquidity") or {}
        pct = lambda v: "未获取" if v is None else f"{v:.2%}"
        ratio = lambda v: "未获取" if v is None else f"{v:.2f} 倍"
        return (f"有息负债/总资产 {pct(values.get('debt_ratio'))}；"
                f"货币资金/短债 {ratio(values.get('short_cover'))}；"
                f"经营现金流/短债 {ratio(values.get('ocf_short_cover'))}")
    if rule_id == "1E.DIVIDEND":
        values = spec.get("dividend") or {}
        parts = [f"连续分红 {values['payout_streak']} 年" if values.get("payout_streak") is not None else "",
                 f"分红增长连续 {values['growth_streak']} 年" if values.get("growth_streak") is not None else ""]
        return "；".join(part for part in parts if part) or "长期分红记录"
    if rule_id == "1E.BUYBACK":
        return "注销式回购：" + ("是" if (spec.get("buyback") or {}).get("cancel") else "否")
    if rule_id == "1E.LONG_RECORD":
        values = spec.get("long_record") or {}
        names = {"dividend_growth": "持续分红增长", "low_buyback": "低价回购"}
        return "；".join(label for name, label in names.items() if values.get(name)) or "长期资本配置记录"
    if rule_id == "1F.ROIC_COMPONENTS":
        values = spec.get("roic_normalized_components") or []
        return "近三年 ROIC：" + " / ".join(f"{float(v):.2%}" for v in values)
    if rule_id == "1F.INCREMENTAL_ROIC":
        return f"{float(evidence):.2%}"
    if rule_id == "1E.PLEDGE":
        return f"质押比例 {float(step.get('evidence')):.2%}"
    if rule_id == "1E.REDUCTION":
        return f"减持比例 {float(step.get('evidence')):.2%}"
    if rule_id == "1E.SUCCESSION":
        return f"负责人 {float(evidence):g} 岁，未披露继任安排"
    if rule_id == "1E.PENALTIES":
        return "存在监管处罚"
    if rule_id.startswith("1D.CAUSAL_GROUP."):
        return evidence.split("；同一因果链", 1)[0] + "；同一因果链只计一次"
    if rule_id.startswith("1D.RED.") and evidence in ("True", "False"):
        return "已核实" if evidence == "True" else "未核实"
    if evidence in ("True", "False"):
        return "通过" if evidence == "True" else "未通过"
    for code, label in _PROFILE_LABELS.items():
        evidence = evidence.replace(code, label)
        evidence = evidence.replace("成本strong", "成本强").replace("定价strong", "定价强")
        evidence = evidence.replace("成本neutral", "成本中性").replace("定价neutral", "定价中性")
        evidence = evidence.replace("成本weak", "成本弱").replace("定价weak", "定价弱")
    return evidence


def _score_group(key, step):
    rule_id = str(step.get("id") or "")
    evidence = str(step.get("evidence") or "")
    if step.get("delta"):
        return "加减分"
    if key == "1D" and rule_id.startswith("1D.G."):
        return "补充观察"
    if "UNKNOWN" in rule_id or any(word in evidence for word in ("最高只能", "未获取", "未知", "缺失")):
        return "数据缺口与限制"
    return "规则明细"


def _build_score_detail(key, result, spec):
    steps = result.get("rule_steps") or []
    custom = result.get("custom") or {}
    custom_ids = {custom.get("id")} | {item.get("id") for item in custom.get("items", [])}
    custom_ids.discard(None)
    explanation = result.get("explanation") or {}
    base_label = explanation.get("base_label") or ""
    final = result.get("final")
    explanation_body = ""
    if final is None:
        summary = "数据不足"
    else:
        base = float(result.get("base") or 0)
        rule_steps = [s for s in steps if s.get("id") not in custom_ids]
        total_delta = sum(float(s.get("delta") or 0) for s in steps)
        has_adjustments = any(float(s.get("delta") or 0) != 0 for s in steps)
        before_limit = base + total_delta
        pre_cap = float(result.get("pre_cap", before_limit))
        band_limited = abs(pre_cap - before_limit) >= 0.005
        cap = result.get("cap")
        cap_active = (cap is not None and pre_cap > cap and abs(final - cap) < 0.005)
        base_part = f"基础分 {base:.2f}" + (f"（{base_label}）" if base_label else "")
        parts = [f"最终 {final:.2f}", base_part]
        for step in rule_steps:
            if step.get("delta"):
                label = _score_label(step)
                if label:
                    parts.append(f"{label} {_delta_text(step['delta'])}")
        regular_deltas = [float(s["delta"]) for s in rule_steps
                          if s.get("delta") and not _score_label(s)]
        regular_positive = sum(value for value in regular_deltas if value > 0)
        regular_negative = sum(value for value in regular_deltas if value < 0)
        if regular_positive:
            parts.append(f"规则调整 {_delta_text(regular_positive)}")
        if regular_negative:
            parts.append(f"规则减分 {_delta_text(regular_negative)}")
        custom_delta = sum(float(s.get("delta") or 0) for s in steps if s.get("id") in custom_ids)
        if custom_delta:
            parts.append(f"清单外调整 {_delta_text(custom_delta)}")
        if has_adjustments and abs(total_delta) < 0.005:
            parts.append("调整相互抵消")
        elif not has_adjustments:
            if abs(final - base) < 0.005 and not band_limited and not cap_active:
                parts.append("无加减分，最终分=基础分")
            else:
                parts.append("无加减分")
        if band_limited:
            parts.append("档位边界限制")
        if cap_active:
            cap_note = explanation.get("cap_note")
            if cap_note:
                parts.append(cap_note)
            else:
                reason_step = next((s for s in reversed(steps)
                                    if "UNKNOWN" in str(s.get("id")) or "最高" in str(s.get("evidence"))), None)
                reason = f"（{_score_text(key, reason_step, spec)}）" if reason_step else ""
                parts.append(f"证据上限 {cap:.2f}{reason}")
        summary = "｜".join(parts)
        logic = explanation.get("logic") or ""
        basis = explanation.get("basis") or ""
        explanation_body = "".join(
            f'<section class="score-group"><h4>{title}</h4><p>{_esc(text)}</p></section>'
            for title, text in (("评分逻辑", logic), ("定档依据", basis)) if text)
    groups = {"加减分": [], "规则明细": [], "数据缺口与限制": [], "补充观察": []}
    for step in steps:
        rule_id = str(step.get("id") or "")
        if rule_id in F_ITEM_IDS.values():
            continue
        text = _score_text(key, step, spec)
        label = _score_label(step)
        prefix = f"{label}：" if label else ""
        delta = step.get("delta")
        delta_html = (f'<strong class="{"bad" if delta < 0 else "good"}">{_delta_text(delta)}</strong>'
                      if delta else "")
        item = (f'<li data-rule-id="{_esc(rule_id)}"><span>{_esc(prefix + text)}</span>'
                f'{delta_html}</li>')
        groups[_score_group(key, step)].append(item)
    body = "".join(f'<section class="score-group"><h4>{title}</h4><ul>{"".join(items)}</ul></section>'
                   for title, items in groups.items() if items)
    return (f'<details class="score-detail"><summary><span class="score-final">{_esc(summary)}</span>'
            f'<span class="score-detail-toggle">查看评分依据</span></summary>'
            f'<div class="score-groups">{explanation_body}{body}</div></details>')


def build_score_bars(sc: dict) -> str:
    """06 质量分汇总·九维评分横条图：条长=维度得分（0-10 定域，跨报告可比），条色=徽章档，
    条端=得分，最右列=层内权重；按层分组（公司本质/未来预期），虚线=7.0 良好线。
    数据全部来自 compute_scores（adj_scores/weights，与汇总表同一份口径）。"""
    adj, weights, ls = sc.get("adj_scores") or {}, sc.get("weights") or {}, sc["layer_share"]
    if not adj:
        return ""
    W = 1000
    NL, BAR_A, BAR_B = 200, 210, 820  # 名称列右缘 / 条形起点（0 分） / 条形终点（10 分）
    WT_X = 965                        # 权重·加权列右缘
    T, ROW_H, BAR_H, GROUP_GAP = 34, 32, 18, 26
    H = T + 9 * ROW_H + GROUP_GAP + 36
    X = _lin_map(0, 10, BAR_A, BAR_B)
    # v4.9：评分条色跟随模板徽章加深系（白字/小字 AA 对比度），与 pastel 评价色（大面积填充）区分
    # （色值字典 _C_BADGE_DEEP 在 charts_base 常量区，改色只动那里）

    parts = ['<span class="section-tag">评分分布</span>',
             _svg_open(W, H, "九维评分分布")]
    _vgrid_ticks(parts, X, _ticks(0, 10, 6), T - 8, H - 30, H - 14)
    gx7 = X(7.0)
    parts.append(f'<line x1="{gx7:.1f}" y1="{T - 8}" x2="{gx7:.1f}" y2="{H - 30}" stroke="{_C_GOOD_LINE}" stroke-width="1.2" stroke-dasharray="5 4"/>')
    parts.append(f'<text x="{gx7:.1f}" y="{T - 14}" text-anchor="middle" font-size="10.5" fill="{_C_LABEL}">良好线 7.0</text>')
    y = T
    for layer in ("L1", "L3"):
        dims = [d for d in DIMS if d[1] == layer]
        parts.append(f'<text x="0" y="{y - 8}" font-size="11" font-weight="600" fill="{_C_LABEL}">'
                     f'{LAYER_NAMES[layer]} · 占质量分 {ls[layer]:.0f}%</text>')
        for key, _l, name, _dw in dims:
            s = float(adj.get(key, 0))
            w = float(weights.get(key, 0))
            cy = y + 2
            color = _C_BADGE_DEEP[badge_class(s)]
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{BAR_B - BAR_A}" height="{BAR_H}" rx="5" fill="{_C_TRACK}"/>')
            parts.append(f'<rect x="{BAR_A}" y="{cy}" width="{max((BAR_B - BAR_A) * s / 10.0, 3):.1f}" '
                         f'height="{BAR_H}" rx="5" fill="{color}"/>')
            parts.append(f'<text x="{NL - 10}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                         f'fill="{_C_INK}">{_esc(name)}</text>')
            parts.append(f'<text x="{BAR_A + max((BAR_B - BAR_A) * s / 10.0, 3) + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" '
                         f'font-size="12" font-weight="700" fill="{color}">{s:.1f} {_dim_verdict(s)}</text>')
            parts.append(f'<text x="{WT_X}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="11" '
                         f'fill="{_C_LABEL}">{w:g}% · {s * w / 100:.2f}</text>')
            y += ROW_H
        y += GROUP_GAP
    parts.append(_svg_close())
    parts.append(_chart_source(
        "评分分布", "本报告评分模型输出（维度得分×层内权重加权）",
        '条长=维度得分（0-10 定域），'
        '条色=徽章档（≥7 绿 / 4-6.9 橙 / &lt;4 红），条端=得分与判词，右列=层内权重 · 加权得分，'
        '虚线=7.0 良好线'))
    return "".join(parts)


def build_sensitivity_tornado(fill: dict) -> str:
    """02 关键利润驱动·敏感性龙卷风（fill["sensitivity"] 可选字段）：变量 ±10% 变动对归母净利
    影响幅度（%）的双向条，红=不利方向、绿=有利方向，排序=弹性大小（首行=第一变量）。
    sensitivity: [{"name":"矿产金售价（金价）","impact":20,"delta":"±10%","amount":"约±9-10亿元"}, ...]
    （impact 取绝对值；delta/amount 可选——填了即在变量名下展示「变动幅度 → 金额影响」，
    信息覆盖旧敏感性表，填了本字段 P0 就不必再手写敏感性表。delta 量纲规范 v5.1.1：
    变量自身变动幅度须带单位——比例写 ±10%、百分点写 ±1pct，与条端/坐标轴的净利影响 % 区分）。
    有效行过滤与 |impact| 降序由 charts_base._sensitivity_items 承载（v5.1.1 起校验/驱动卡同源，
    首行加冕不再各算各的）。字段缺失 → 返回空串。"""
    items = _sensitivity_items(fill)
    if not items:
        return ""
    has_detail = any(it["delta"] or it["amount"] for it in items)
    W = 1000
    # v4.8.2：变量名列宽度自适应——先组文本行并用 _text_w 量宽，超 388px 的长名折两行；
    # NL/X0/HALF 随最长行宽动态取值，长变量名不再越出画布左缘被裁
    rows = [[[it["name"] + ("（第一变量）" if i == 0 else "")],
             " → ".join(x for x in (it["delta"], it["amount"]) if x)] for i, it in enumerate(items)]
    max_w = max([_text_w(r[0][0], 13.0) for r in rows]
                + [_text_w(r[1], 11.0) for r in rows if r[1]])
    if max_w > 388:
        rows = [[_wrap_label(nm, 388, 13.0), det] for [nm], det in rows]
        max_w = max([_text_w(t, 13.0) for r in rows for t in r[0]]
                    + [_text_w(r[1], 11.0) for r in rows if r[1]])
    NL = min(max(max_w + 12, 230), 400)      # 变量名列右缘
    if NL <= 230:
        X0, HALF = 600, 300                  # 短名布局与 v4.8.1 一致（W 与全站图表统一 1000）
    else:
        X0 = min(NL + 370, 700)              # 中轴右移给名称让位
        HALF = min(300, X0 - NL - 63, 950 - X0)  # 条幅收缩，两侧 ±xx% 标签不出界
    any_wrap = any(len(r[0]) > 1 for r in rows)
    T, BAR_H = 30, 17
    ROW_H = (58 if any_wrap else 44) if has_detail else (48 if any_wrap else 36)
    H = T + len(items) * ROW_H + 38
    imax = items[0]["impact"]
    k = HALF / imax if imax else 1.0
    parts = ['<span class="section-tag">敏感性排序</span>',
             _svg_open(W, H, "敏感性龙卷风")]
    axis_y = T + len(items) * ROW_H + 4
    for v in _ticks(0, imax, 4):
        for sign in (-1, 1):
            gx = X0 + sign * v * k
            parts.append(f'<line x1="{gx:.1f}" y1="{T - 6}" x2="{gx:.1f}" y2="{axis_y}" stroke="{_C_GRID}" stroke-width="1"/>')
            lbl = f'{"+" if sign > 0 else "−"}{_fmt(v)}%' if v > 0 else "0"
            if v > 0 or sign > 0:
                parts.append(f'<text x="{gx:.1f}" y="{axis_y + 16}" text-anchor="middle" font-size="11" fill="{_C_LABEL}">{lbl}</text>')
    parts.append(f'<line x1="{X0}" y1="{T - 6}" x2="{X0}" y2="{axis_y}" stroke="{_C_SAND}" stroke-width="1.2"/>')
    for i, it in enumerate(items):
        cy = T + i * ROW_H + (ROW_H - BAR_H) / 2
        w = it["impact"] * k
        first = (i == 0)
        nm_lines, detail = rows[i]
        # 名称/detail 行组：相对条心垂直居中堆叠（行距 15），长名折行后同样居中
        lines = [(t, "13", 700 if first else 400, _C_BLACK if first else _C_INK) for t in nm_lines]
        if detail:
            lines.append((detail, "11", 400, _C_LABEL))
        y0 = cy + BAR_H / 2 + 4.5 - (len(lines) - 1) * 15 / 2
        for li, (t, fs, fw, fc) in enumerate(lines):
            parts.append(f'<text x="{NL:.1f}" y="{y0 + li * 15:.1f}" text-anchor="end" font-size="{fs}" '
                         f'font-weight="{fw}" fill="{fc}">{_esc(t)}</text>')
        parts.append(f'<rect x="{X0 - w:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="{_C_RED}"/>')
        parts.append(f'<rect x="{X0:.1f}" y="{cy:.1f}" width="{w:.1f}" height="{BAR_H}" fill="{_C_GREEN}"/>')
        parts.append(f'<text x="{X0 - w - 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" text-anchor="end" font-size="12" '
                     f'font-weight="700" fill="{_C_RED}">−{_fmt(it["impact"])}%</text>')
        parts.append(f'<text x="{X0 + w + 8:.1f}" y="{cy + BAR_H / 2 + 4.5:.1f}" font-size="12" '
                     f'font-weight="700" fill="{_C_GREEN}">+{_fmt(it["impact"])}%</text>')
    parts.append(_svg_close())
    parts.append(_chart_source(
        "敏感性龙卷风", "本报告假设与估算（变量变动对归母净利影响）",
        '条长/条端/坐标轴=变量变动'
        '对归母净利的影响幅度 %（估算绝对值），红=不利方向、绿=有利方向，'
        '左列=变量自身变动幅度（pct=百分点、%=比例）→ 金额影响，'
        '排序=弹性大小（首行=第一变量）；填了敏感性字段后，P0 不必再写敏感性表'))
    return "".join(parts)
