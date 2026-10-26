#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_audit.py — 照抄对账/落盘防伪校验域（v5.8.3 自 validate.py 按域拆分）。

内容：quote 防伪链（price_date/quote_consistency/quote_present/consensus_np）、timing_facts 技术/筹码/资金对账、
quality_inputs 双向照抄/profile/披露日对账、gap_plot 分布图与 street 落盘源、
gap_history 态度变化、dupont 杜邦乘积链、period_track 第 3 章照抄对账、growth_consistency 增速换算对账，
及 _strict_num/_req_strict/_tol_floor/_audit_pairs 等比对工具
（_quote_ref 为跨域公共层，见 validate.py）。
契约：raise = 硬拒渲染；warns.append = 软告警。
"""
import json, re
from scoring import (
    _num,
    _fmt,
    _plain_text,
    _quality_context,
    _quality_version)
from charts_base import (
    _gap_dim_ok,
    _period_ratio,
    _PERIOD_VERDICTS)
from charts_gap import _gh_sort_key
from validate import (
    _is_hk_code,
    _quote_ref,
    _scenario_by_key)


def _check_price_date(fill: dict) -> None:
    """price/date 校验：缺失/非法即拒渲染。"""
    # price 缺失/非数字、date 格式非法在此拦截（友好报错先于估值计算结果的所有使用方）
    if _num(fill.get("price")) is None:
        raise ValueError(f"price 缺失或无法解析为数字: {fill.get('price')!r}"
                         f"（Hero 指标卡与估值三情景计算都依赖现价）")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(fill.get("date") or "")):
        raise ValueError(f"date 格式非法: {fill.get('date')!r}（必须严格 YYYY-MM-DD）")


def _strict_num(v):
    """防伪比对专用严格解析：仅接受 int/float 或纯数字字符串，
    夹带任何文字（如「18.6（H股口径）」）返回 None——防伪强度不应由解析层宽松度决定。"""
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    return float(s) if re.fullmatch(r"-?\d+(\.\d+)?", s) else None


def _req_strict(owner: str, key: str, raw):
    """防伪字段存在即须为纯数字：有值但严格解析失败 → 拒渲染（夹带文字即防伪链疑点）。"""
    v = _strict_num(raw)
    if raw is not None and str(raw).strip() and v is None:
        raise ValueError(f"{owner}.{key} 不是纯数字: {raw!r}——防伪比对字段禁止夹带文字"
                         f"（如「18.6（H股口径）」），口径注请写进 .source 说明后重渲")
    return v


def _check_quote_consistency(fill: dict, warns: list) -> None:
    """quote 防伪（神华 601088 现价造假事故修复）：fill 声明 quote.source_file 时，
    读 em_fetch --out 落盘 JSON，比对 price/pe_ttm，偏差 >1% 拒渲染（与估值分四件套同级）。
    fill 侧一律严格解析（_strict_num），夹带文字即拒；quote 字段缺失不拒（存量 fill 兼容），
    由 _check_quote_present 走告警。"""
    q = fill.get("quote")
    if q is None:
        return
    if not isinstance(q, dict) or not q.get("source_file"):
        raise ValueError('quote 字段需为 {"source_file": "em_fetch --out 落盘路径", "date": "YYYY-MM-DD"}')
    src = q["source_file"]
    try:
        with open(src, encoding="utf-8") as f:
            ref = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise ValueError(f"quote.source_file 读取失败: {src}（{e}）——防伪链断裂不能静默放行，"
                         f"请重跑 em_fetch --out 落盘后再渲染")
    for fill_key, ref_key in (("price", "price"), ("pe_ttm", "pe_ttm")):
        fv, rv = _req_strict("fill", fill_key, fill.get(fill_key)), _num(ref.get(ref_key))
        if fv is None or rv is None or rv == 0:
            continue
        if abs(fv - rv) / abs(rv) > 0.01:
            raise ValueError(f"{fill_key} 与 E1 落盘值不一致: fill={fv:g} vs {src}={rv:g}"
                             f"（偏差 {abs(fv - rv) / abs(rv) * 100:.1f}% > 1%）——现价类数字禁止手填，"
                             f"以 em_fetch --out 落盘值为准修正后重渲")
    # v4.8 四件套扩展比对（方向一防伪链闭环：神华是「真碎片+假框架」整套自洽，
    # 只比 price/pe_ttm 两个点不够，估值分输入必须同源）
    vi = fill.get("valuation_inputs") or {}
    if not vi.get("metric_label"):  # 行业口径（P/NAV、P/rNPV 等）下 pe 语义非 PE(TTM)，跳过
        vpe, rpe = _req_strict("valuation_inputs", "pe_ttm", vi.get("pe_ttm")), _num(ref.get("pe_ttm"))
        if vpe is not None and rpe:
            if abs(vpe - rpe) / abs(rpe) > 0.01:
                raise ValueError(f"valuation_inputs.pe_ttm 与 E1 落盘值不一致: fill={vpe:g} vs "
                                 f"{src}={rpe:g}（偏差 {abs(vpe - rpe) / abs(rpe) * 100:.1f}% > 1%）"
                                 f"——估值分输入与现价同级防伪，以落盘值为准修正后重渲")
        # 合理带完全落在历史极值带之外 = 校准逻辑或取数必有一假（完全无交集才拦，部分重叠正常）
        band, hb = vi.get("pe_band") or [], ref.get("pe_band") or []
        if len(band) >= 2 and len(hb) >= 2:
            blo = _req_strict("valuation_inputs", "pe_band[0]", band[0])
            bhi = _req_strict("valuation_inputs", "pe_band[1]", band[1])
            hlo, hhi = _num(hb[0]), _num(hb[1])
            if None not in (blo, bhi, hlo, hhi) and (bhi < hlo or blo > hhi):
                raise ValueError(f"valuation_inputs.pe_band [{_fmt(blo)},{_fmt(bhi)}] 与 E1 落盘历史带 "
                                 f"[{_fmt(hlo)},{_fmt(hhi)}] 完全无交集——合理带须来自历史时段匹配校准，"
                                 f"越界即防伪链疑点，请核对 pe_band 取数与校准逻辑后重渲")
    # risk_free / div_yield 偏差 >0.3pct 告警不拒（允许手工估算/税后折算，但必须可见）
    for k in ("risk_free", "div_yield"):
        fv, rv = _req_strict("valuation_inputs", k, vi.get(k)), _num(ref.get(k))
        if fv is None or rv is None:
            continue
        if k == "div_yield" and ref.get("market") != "A股":
            continue  # 港股通/红筹税后折算差异天然 >0.3pct，不做机械比对
        if abs(fv - rv) > 0.3:
            warns.append(f"valuation_inputs.{k}（{fv:g}）与 E1 落盘值（{rv:g}）偏差 >0.3pct"
                         f"——若为手工估算或税后折算口径，请在 .source 注明")


def _check_score_ranges(fill: dict) -> None:
    """分数范围（0-10）越界是硬错误。"""
    for field in ("scores", "timing_scores"):
        raw = fill.get(field)
        if raw is not None and not isinstance(raw, dict):
            raise ValueError(f"{field} 需为对象（{{维度: 0-10 分值}}），实际: {type(raw).__name__}")
        for k, v in (raw or {}).items():
            if field == "timing_scores" and v is None:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise ValueError(f"{field}.{k} 不是数字: {v!r}")
            if not (0 <= fv <= 10):
                raise ValueError(f"{field}.{k} = {fv} 超出 0-10 范围")


def _check_timing_facts(fill: dict, warns: list) -> None:
    """技术事实对 quote 落盘；筹码/资金事实对独立证据文件。"""
    facts = fill.get("timing_facts")
    quote_timing = (_quote_ref(fill) or {}).get("timing") or {}
    if not facts:
        if quote_timing.get("technical"):
            warns.append("timing_facts 未回填：quote 已有技术与三年区间数据，事实卡不可见")
        return
    if not isinstance(facts, dict):
        raise ValueError("timing_facts 必须为对象")
    for key in ("technical", "consensus_levels"):
        if facts.get(key) is not None and not isinstance(facts[key], dict):
            raise ValueError(f"timing_facts.{key} 必须为对象或 null")
    technical = facts.get("technical") or {}
    if technical.get("macd") is not None and not isinstance(technical["macd"], dict):
        raise ValueError("timing_facts.technical.macd 必须为对象或 null")

    def compare(owner, actual, expected):
        if isinstance(actual, dict):
            for key, value in actual.items():
                compare(f"{owner}.{key}", value, (expected or {}).get(key))
            return
        if actual is None:
            return
        if _strict_num(actual) is None:
            if actual != expected:
                warns.append(f"{owner} 与落盘值不一致")
            return
        value = _req_strict(owner, "", actual)
        reference = _strict_num(expected)
        if reference is None:
            warns.append(f"{owner} 无落盘技术证据可核对，请重跑 em_fetch --out")
        elif abs(value - reference) > max(0.005, abs(reference) * 0.01):
            warns.append(f"{owner}={value:g} 与落盘值 {reference:g} 不一致，禁手估")

    if facts.get("technical"):
        compare("timing_facts.technical", facts["technical"], quote_timing.get("technical"))
    elif quote_timing.get("technical"):
        warns.append("timing_facts 缺技术字段：quote 已有数据但未回填")
    if facts.get("consensus_levels"):
        compare("timing_facts.consensus_levels", facts["consensus_levels"],
                quote_timing.get("consensus_levels"))
    if not (facts.get("chips") or facts.get("capital")):
        return
    src = str(facts.get("source_file") or "").strip()
    if not src:
        raise ValueError("timing_facts.source_file 缺失：筹码/资金事实须引用独立证据文件")
    try:
        with open(src, encoding="utf-8") as handle:
            evidence = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"timing_facts.source_file 读取失败: {src}（{exc}）") from None
    if not isinstance(evidence, dict):
        raise ValueError("timing_facts.source_file 证据根节点必须为对象")
    if str(evidence.get("code")) != str(fill.get("code")) or evidence.get("date") != fill.get("date"):
        raise ValueError("timing_facts.source_file 的 code/date 与 fill 不一致")
    for group in ("chips", "capital"):
        records = facts.get(group) or {}
        if not isinstance(records, dict):
            raise ValueError(f"timing_facts.{group} 必须为对象")
        for key, record in records.items():
            reference = (evidence.get(group) or {}).get(key)
            if record is None:
                if isinstance(reference, dict) and reference.get("value") is not None:
                    warns.append(f"timing_facts.{group}.{key} 已有证据但被改空，禁止隐藏事实")
                continue
            if not isinstance(record, dict):
                raise ValueError(f"timing_facts.{group}.{key} 必须为对象或 null")
            if not isinstance(reference, dict):
                warns.append(f"timing_facts.{group}.{key} 在证据文件中缺记录")
                continue
            for field in ("source", "query", "date"):
                if not str(record.get(field) or "").strip():
                    raise ValueError(f"timing_facts.{group}.{key} 缺 {field}")
                if record.get(field) != reference.get(field):
                    warns.append(f"timing_facts.{group}.{key}.{field} 与证据文件不一致")
            if record.get("unit") != reference.get("unit"):
                warns.append(f"timing_facts.{group}.{key}.unit 与证据文件不一致")
            if _strict_num(record.get("value")) != _strict_num(reference.get("value")):
                warns.append(f"timing_facts.{group}.{key} 数值与证据文件不一致")


def _check_gap_plot(fill: dict, calc: dict, warns: list) -> None:
    """gap_plot 分布图字段校验（v4.11.1 落地时补设计；字段可选，缺失不查）。
    硬拒：dim 缺 name/ours/consensus 或不可解析（非法字段值不放行）。
    告警：consensus ≤0 行被图剔除、有效维度 <2（图不生成）、dims >6、street 同机构多点、
    「目标价」维度 ours 与脚本中枢价失配（镜像 thesis 一致性 2%/0.1 口径）。
    org 名真实性无法机械校验——由 fill-schema「照抄 E5 明细行、禁编造」条款 + 附注来源兜底。"""
    gp = fill.get("gap_plot")
    if gp is None:
        return
    if not isinstance(gp, dict):
        raise ValueError(f"gap_plot 字段需为对象（{{\"dims\": [...]}}），实际: {type(gp).__name__}")
    dims = gp.get("dims") or []
    if not dims:
        warns.append("gap_plot.dims 为空：分布图不会生成——无数据请整字段删除（同 holders 惯例）")
        return
    effective = 0
    cmap = {r["key"]: r["mid"] for r in (calc or {}).get("rows", [])}
    base_mid = cmap.get("base")
    for i, d in enumerate(dims):
        if not isinstance(d, dict):
            raise ValueError(f"gap_plot.dims[{i}] 不是对象：每行需 {{name, ours, consensus, ...}}")
        name = str(d.get("name") or "").strip()
        ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
        if not name or ours is None or cons is None:
            raise ValueError(f"gap_plot.dims[{i}] 缺 name/ours/consensus 或不可解析：{d!r}")
        if cons <= 0:
            warns.append(f"gap_plot.dims[{i}]「{name}」consensus={cons:g} ≤0：该行图内剔除")
            continue
        effective += 1
        seen_orgs = []
        for s in (d.get("street") or []):
            if not isinstance(s, dict):
                # 热核审计 P1-1：street 元素非对象与 dims 非法行同标准——不放行
                raise ValueError(f"gap_plot.dims[{i}]「{name}」street 元素需为对象 "
                                 f'（{{"org","v","major"?}}），实际: {s!r}')
            if s.get("org"):
                seen_orgs.append(str(s["org"]))
        dup = sorted({o for o in seen_orgs if seen_orgs.count(o) > 1})
        if dup:
            warns.append(f"gap_plot.dims[{i}]「{name}」street 同机构多点: {dup}"
                         f"——一家机构 180 天内只取最新一份研报，请去重")
        if "目标价" in name and base_mid is not None and base_mid > 0:
            if abs(ours - base_mid) > 0.1 and abs(ours - base_mid) / base_mid > 0.02:
                warns.append(f"gap_plot「{name}」本文值 {ours:g} 与 valuation 基础情景中枢 "
                             f"{base_mid:.2f} 偏差 >2%：本文假设点与三情景口径须一致")
    # v5.1.2：「净利」维度对账——consensus 照抄落盘 consensus_np.np_avg（>1% 告警）；
    # ours 与 valuation 基础情景 profit 一致（>2% 告警，镜像目标价维度口径）
    ref = _quote_ref(fill)
    cnp = (ref or {}).get("consensus_np") or {}
    np_avg = _num(cnp.get("np_avg"))
    _base_sc = _scenario_by_key((fill.get("valuation") or {}).get("scenarios"), "base")
    base_profit = _num(_base_sc.get("profit")) if _base_sc else None
    for d in dims:
        if not _gap_dim_ok(d):
            continue
        nm_ = str(d.get("name") or "")
        if "净利" not in nm_:
            continue
        yr = re.search(r"20\d{2}", nm_)
        cnp_yr = _num(cnp.get("year"))   # 落盘 year 非整数串时跳过比对（热核 P1-3）
        yr_i = int(yr.group(0)) if yr else None
        cons, ours = _num(d.get("consensus")), _num(d.get("ours"))
        if (np_avg and cnp_yr and yr_i and yr_i == int(cnp_yr)
                and cons and abs(cons - np_avg) / abs(np_avg) > 0.01):
            warns.append(f"gap_plot「{nm_}」consensus（{cons:g} 亿）与落盘 consensus_np.np_avg"
                         f"（{np_avg:g} 亿）偏差 >1%：一致预期照抄 E5 落盘、禁手估（v5.1.2）")
        # ours 只比对预测年（带 E）维度——历史年实绩本就不该等于当年假设（热核 P1-1）
        if (base_profit and ours and "E" in nm_ and yr_i and (not cnp_yr or yr_i == int(cnp_yr))
                and abs(ours - base_profit) / abs(base_profit) > 0.02):
            warns.append(f"gap_plot「{nm_}」ours（{ours:g} 亿）与 valuation 基础情景净利"
                         f"（{base_profit:g} 亿）偏差 >2%：本文假设两处应一致（v5.1.2）")
    if dims and effective < 2:
        warns.append(f"gap_plot 有效数值维度仅 {effective} 个 <2：分布图不会生成（准入规则）")
    if len(dims) > 6:
        warns.append(f"gap_plot.dims 共 {len(dims)} 行 >6：图内只画前 6 行，其余请挪 text_dims 附注")


# v5.8.2：照抄对账容差单源（原 5 处逐字复制收敛）——相对 1%、下限 0.005，基准为落盘值
def _tol_floor(rv: float) -> float:
    """照抄对账容差：max(相对 1%, 绝对下限 0.005)（基准为落盘值 rv）。"""
    return max(abs(rv) * 0.01, 0.005)


def _audit_pairs(warns: list, pairs, fmt, *, miss=None, rv_none: bool = True) -> None:
    """照抄对账逐键比对骨架（v5.8.2 单源，gap_history/dupont 四键循环同款收敛）：
    pairs 为 (键名, fill 值, 落盘值) 三元组清单；超容差按 fmt(键, fv, rv) 告警；
    miss 非空时 fill 缺值而落盘有值按 miss(键, rv) 补「漏抄」；
    rv_none=False 时落盘缺值不告警（dupont.prev 口径）。
    告警文案逐字由各调用点自带——五处文案本就不完全相同（street 池比对、tp_reports 无
    落盘值展示、dupont.prev 无容差尾巴等），此处只收敛循环与容差，不强行统一文案。"""
    for label, fv, rv in pairs:
        if fv is None:
            if rv is not None and miss is not None:
                warns.append(miss(label, rv))
            continue
        if rv is None:
            if rv_none:
                warns.append(fmt(label, fv, rv))
            continue
        if abs(fv - rv) > _tol_floor(rv):
            warns.append(fmt(label, fv, rv))


def _check_gap_plot_street_source(fill: dict, warns: list) -> None:
    """v5.5.1 F2 gap_plot.street 落盘第二照抄源（首版软告警，不拒——升拒登记 handoff）。
    纪律：street 逐机构数值必须照抄落盘。A 股走 em_fetch E5「净利明细/目标价明细」行（无
    source_file，存量合法用法不告警）；港股 E5（tushare report_rc）无逐机构明细，须把调研
    得到的逐机构预测先落盘为 `_street_{code}_{date}.json` 并由 `gap_plot.source_file` 指向，
    street 照抄其数值（小米 01810 2026-10-07 实证：六家机构数字无合规路径入图）。
    告警范围：① 港股（5 位代码）street 非空而无 source_file（手填嫌疑）；② source_file
    读不到 / 结构非法 / 缺 source / 维度无记录 / 记录缺机构名或日期 / 数值对不上。"""
    gp = fill.get("gap_plot")
    if not isinstance(gp, dict):
        return
    street_dims = [d for d in (gp.get("dims") or [])
                   if _gap_dim_ok(d) and any(isinstance(s, dict) and _num(s.get("v")) is not None
                                             for s in (d.get("street") or []))]
    if not street_dims:
        return
    src = str(gp.get("source_file") or "").strip()
    if not src:
        if _is_hk_code(fill):
            warns.append("gap_plot.street 无落盘源（港股标的）：E5 落盘对港股无逐机构明细，"
                         "street 来源须先落盘为 `_street_{code}_{date}.json` 并由 "
                         "gap_plot.source_file 指向（调研得到的机构名/数值/日期/来源四要素），"
                         "street 照抄其数值——否则视为手填（fill-schema「gap_plot」节）")
        return
    try:
        with open(src, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        warns.append(f"gap_plot.source_file 读取失败: {src}（{e}）——street 逐机构数值无落盘源"
                     f"可对账，请核对路径后重渲")
        return
    recs = doc.get("dims") if isinstance(doc, dict) else None
    if not isinstance(recs, dict):
        warns.append(f"gap_plot.source_file 结构非法: {src}——须为 "
                     '{"source":"调研来源说明","dims":{"维度名":[{"org","v","date"}]}}'
                     "（契约见 fill-schema「gap_plot」节）")
        return
    if not str(doc.get("source") or "").strip():
        warns.append(f"gap_plot.source_file 缺 source（调研来源说明）: {src}——"
                     "四要素（机构名/数值/日期/来源）缺一即无法追溯出处")
    for d in street_dims:
        name = str(d.get("name") or "").strip()
        rows = recs.get(name)
        if not isinstance(rows, list):
            warns.append(f"gap_plot「{name}」street 在 source_file 中无对应维度记录: {src}"
                         f"——维度名须与落盘源 dims 的键完全一致")
            continue
        bad = [r for r in rows if not isinstance(r, dict) or not str(r.get("org") or "").strip()
               or not str(r.get("date") or "").strip()]
        if bad:
            warns.append(f"gap_plot「{name}」source_file 有 {len(bad)} 条记录缺机构名/日期: {src}"
                         f"——四要素（机构名/数值/日期/来源）缺一不可追溯")
        for s in d["street"]:
            v = _num(s.get("v"))
            if v is None:
                continue
            org = str(s.get("org") or "").strip()
            # P1-2：署名非空 → 只与落盘同机构记录比（防张冠李戴：数值撞上别家机构不算对账成功）；
            # 同 org 多条任一命中即通过（对应「同机构取最新」口径）；未具名点退全池数值比对
            pool = [_num(r.get("v")) for r in rows if isinstance(r, dict)
                    and (not org or str(r.get("org") or "").strip() == org)]
            pool = [x for x in pool if x is not None]
            if not any(abs(v - rv) <= _tol_floor(rv) for rv in pool):
                shown = "、".join(f"{x:g}" for x in pool) or "无"
                warns.append(f"gap_plot「{name}」street {org or '未具名'} {v:g} 在 source_file 中"
                             f"无对应记录（同机构落盘值 {shown}）: {src}——"
                             f"street 须照抄落盘源、禁手填（容差：相对 1%，下限 0.005）")


def _check_gap_history(fill: dict, warns: list) -> None:
    """v5.6.0 gap_history（券商态度变化图）校验（首版软告警，不拒——升拒登记 handoff）。
    ① 结构：rows 元素须为 dict、org 非空、np 对/tp 对至少居其一（无效行渲染端静默剔除，
    此处提示等于白填）；② 照抄对账：fill 行须与 quote.source_file 落盘的 gap_history.rows
    同机构同值（容差：相对 1%，下限 0.005，同 street 款）——fill 有行而落盘无 gap_history
    → 手填嫌疑告警（提示重跑 em_fetch --out）；③ 行内 yr 不一致（混预测年度）→ 提示；
    ④ 东财来源且 gap_history 缺失时，gap_html 必须有态度变化图缺省说明（软告警）。
    数值解析用 scoring._num（全仓对账同一尺子，v5.6.0 审核 #3）。"""
    gh = fill.get("gap_history")
    if gh is None:
        if (_quote_ref(fill) or {}).get("e5_source") == "em":
            gap_html = fill.get("gap_html") or ""
            has_note = ("券商态度变化" in gap_html
                        and any(s in gap_html for s in ("未生成", "不生成", "无法生成"))
                        and ("东财" in gap_html or "report_rc" in gap_html))
            if not has_note:
                warns.append("E5 东财降级：券商态度变化图无逐份研报数据源，gap_html 未写明"
                             "缺省说明——请标注「券商态度变化图未生成」及原因")
        return
    if not isinstance(gh, dict):
        raise ValueError(f'gap_history 字段需为对象（{{"rows": [...]}}），实际: {type(gh).__name__}')
    rows = gh.get("rows") or []
    if not rows:
        warns.append("gap_history.rows 为空：态度变化图不会生成——无数据请整字段删除（同 holders 惯例）")
        return
    yrs = set()
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise ValueError(f"gap_history.rows[{i}] 不是对象：每行需 "
                             f'{{org, np_from, np_to / tp_from, tp_to, ...}}')
        org = str(r.get("org") or "").strip()
        np_ok = _num(r.get("np_from")) is not None and _num(r.get("np_to")) is not None
        tp_ok = _num(r.get("tp_from")) is not None and _num(r.get("tp_to")) is not None
        if not org or not (np_ok or tp_ok):
            warns.append(f"gap_history.rows[{i}]（{org or '未具名'}）org 缺失或 np/tp 对均不可解析："
                         f"该行图内剔除")
            continue
        if str(r.get("yr") or "").strip():
            yrs.add(str(r["yr"]).strip())
    if len(yrs) > 1:
        warns.append(f"gap_history.rows 预测年度不一致（{sorted(yrs)}）：图题将退化为"
                     f"「各行同预测年度两份对比」——建议只保留同年度行")

    ref = _quote_ref(fill)
    if ref is None:
        warns.append("gap_history 已填但 quote.source_file 缺失或读不到：态度变化数值无落盘源"
                     "可核对——应照抄 em_fetch E5「券商态度变化」行（--out 落盘 gap_history）")
        return
    ref_rows = {str(h.get("org") or "").strip(): h
                for h in ((ref.get("gap_history") or {}).get("rows") or [])
                if isinstance(h, dict)}
    if not ref_rows:
        warns.append("gap_history 已填但落盘 JSON 无 gap_history.rows：E5 未产出可比行"
                     "（近 180 天无券商最新研报，或历史上无上一份可比）或 fill 手填"
                     "——请重跑 em_fetch --out 核对")
        return
    for r in rows:
        if not isinstance(r, dict):
            continue
        org = str(r.get("org") or "").strip()
        if not org:
            continue
        h = ref_rows.get(org)
        if h is None:
            warns.append(f"gap_history「{org}」在落盘 gap_history.rows 中无对应机构——"
                         f"须照抄 E5「券商态度变化」行、禁手填")
            continue
        # v5.8.2：逐键照抄对账收敛 _audit_pairs 单源（漏抄/不一致文案逐字保留）
        _audit_pairs(warns,
                     [(k, _num(r.get(k)), _num(h.get(k)))
                      for k in ("np_from", "np_to", "tp_from", "tp_to")],
                     lambda k, fv, rv: (f"gap_history「{org}」{k}={fv:g} 与落盘值不一致"
                                        f"（落盘 {rv if rv is None else round(rv, 4)}）——照抄禁手改"
                                        f"（容差：相对 1%，下限 0.005）"),
                     miss=lambda k, rv: f"gap_history「{org}」{k} 漏抄（落盘 {rv:g}）")

    # v5.8.0：tp_reports（目标价面板降级「研报一览」数据源）——结构检查 + 落盘同源对账
    tp = gh.get("tp_reports")
    if tp is not None:
        if not isinstance(tp, list):
            raise ValueError(f"gap_history.tp_reports 字段需为数组，实际: {type(tp).__name__}")
        ref_tp = ((ref or {}).get("gap_history") or {}).get("tp_reports") or []
        if tp and not ref_tp:
            warns.append("gap_history.tp_reports 已填但落盘 JSON 无该键：手填嫌疑——"
                         "请重跑 em_fetch --out 落盘后照抄")
        ref_set = {(str(x.get("org") or "").strip(), str(x.get("date") or "").strip()):
                   _num(x.get("tp")) for x in ref_tp if isinstance(x, dict)}
        for i, x in enumerate(tp):
            if not isinstance(x, dict):
                raise ValueError(f"gap_history.tp_reports[{i}] 不是对象：每行需 {{org, date, tp}}")
            org = str(x.get("org") or "").strip()
            fv = _num(x.get("tp"))
            if not org or fv is None:
                warns.append(f"gap_history.tp_reports[{i}]（{org or '未具名'}）org/tp 不可解析："
                             f"该行图内剔除")
                continue
            rv = ref_set.get((org, str(x.get("date") or "").strip()))
            # v5.8.2：容差收敛 _tol_floor 单源（ref_tp 空时不逐行告警的守卫逐字保留）
            if ref_tp and (rv is None or abs(fv - rv) > _tol_floor(rv)):
                warns.append(f"gap_history.tp_reports「{org} {x.get('date')}」tp={fv:g} "
                             f"与落盘值不一致——照抄禁手改（容差：相对 1%，下限 0.005）")

    # v5.8.1：反向漏抄告警——落盘有目标价研报清单而 fill 缺/空 tp_reports 且 rows 无 tp 对时，
    # 渲染端降级面板静默退化为「无两份可比研报」纯文字（宁德 300750 复盘 2026-10-21 实证）
    if not tp:
        ref_tp_miss = ((ref or {}).get("gap_history") or {}).get("tp_reports") or []
        # v5.8.1 审核实证：判定须与渲染端同源——rows 先按「np 幅度降序、无 np 按 tp 幅度」
        # 排序取前 8 再判 tp 对；全量扫描会在「≥9 家可比且 tp 对落在第 9 名后」时漏报。
        # v5.8.2：排序键同源 import charts_gap._gh_sort_key（v5.8.1 内联复制已删——渲染端
        # 排序策略一变校验端即失准，正是本校验要防的失效模式）；行 dict 键名与渲染端对齐
        # （v5.9.0：补 org 键——排序键新增头部/外资优先（org_tier.is_tier1），缺 org 即
        # KeyError 且口径与渲染端分裂）
        parsed = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            npf, npt = _num(r.get("np_from")), _num(r.get("np_to"))
            tpf, tpt = _num(r.get("tp_from")), _num(r.get("tp_to"))
            if (npf is None or npt is None) and (tpf is None or tpt is None):
                continue
            parsed.append({"org": str(r.get("org") or ""), "npf": npf, "npt": npt,
                           "tpf": tpf, "tpt": tpt})
        parsed.sort(key=_gh_sort_key)
        has_tp_pair = any(t["tpf"] is not None for t in parsed[:8])
        if ref_tp_miss and not has_tp_pair:
            warns.append(f"gap_history.tp_reports 漏抄：落盘有 {len(ref_tp_miss)} 份目标价"
                         "研报清单（降级面板数据源）而 fill 未照抄——rows 无 tp 对时右面板"
                         "将退化为「无两份可比研报」纯文字；请照抄落盘同名子键")


def _check_dupont(fill: dict, warns: list) -> None:
    """v5.8.0 dupont（4.6 杜邦乘积链）校验：① 结构——roe/nm/turn/em 四因子缺一图不生成
    （此处提示等于白填）；verdict 为唯一手填槽位，缺失或过短告警。② 照抄对账——fill 四因子
    （含 prev 去年同期）与 quote.source_file 落盘 dupont 同值（容差：相对 1%，下限 0.005，
    同 street 款）；fill 已填而落盘无 dupont 键 → 手填嫌疑告警（提示重跑 em_fetch --out）。"""
    d = fill.get("dupont")
    if d is None:
        return
    if not isinstance(d, dict):
        raise ValueError(f"dupont 字段需为对象，实际: {type(d).__name__}")
    for k in ("roe", "nm", "turn", "em"):
        if _num(d.get(k)) is None:
            warns.append(f"dupont.{k} 不可解析：四因子缺一乘积链不生成——照抄 em_fetch「杜邦因子」行")
    pv = d.get("prev")
    if pv is not None and not isinstance(pv, dict):
        raise ValueError(f"dupont.prev 字段需为对象，实际: {type(pv).__name__}")
    verdict = re.sub(r"<[^>]+>", "", str(d.get("verdict") or "")).strip()
    if len(verdict) < 20:
        warns.append("dupont.verdict 缺失或 <20 字：乘积链只给数字，归因结论句"
                     "（哪个因子是主驱动、与 4.4 毛利率归因是否一致）必须写")
    ref = _quote_ref(fill)
    if ref is None:
        warns.append("dupont 已填但 quote.source_file 缺失或读不到：杜邦因子无落盘源可核对——"
                     "应照抄 em_fetch「杜邦因子」行（--out 落盘 dupont）")
        return
    ref_d = ref.get("dupont")
    if not isinstance(ref_d, dict):
        warns.append("dupont 已填但落盘 JSON 无 dupont 键：手填嫌疑——请重跑 em_fetch --out 后照抄")
        return
    # v5.8.2：逐键照抄对账收敛 _audit_pairs 单源（本处无漏抄分支：fv 缺失静默跳过）
    _audit_pairs(warns,
                 [(k, _num(d.get(k)), _num(ref_d.get(k))) for k in ("roe", "nm", "turn", "em")],
                 lambda k, fv, rv: (f"dupont.{k}={fv:g} 与落盘值不一致"
                                    f"（落盘 {rv if rv is None else round(rv, 4)}）——照抄禁手改"
                                    f"（容差：相对 1%，下限 0.005）"))
    ref_prev = ref_d.get("prev")
    if isinstance(ref_prev, dict):
        # v5.8.2：同款收敛（落盘缺值不告警 = rv_none=False；漏抄文案带「去年同期」尾巴逐字保留）
        _audit_pairs(warns,
                     [(k, _num((pv or {}).get(k)), _num(ref_prev.get(k)))
                      for k in ("roe", "nm", "turn", "em")],
                     lambda k, fv, rv: (f"dupont.prev.{k}={fv:g} 与落盘值不一致（落盘 {round(rv, 4)}）"
                                        f"——照抄禁手改"),
                     miss=lambda k, rv: f"dupont.prev.{k} 漏抄（落盘 {rv:g}）：去年同期四因子请完整回填",
                     rv_none=False)


def _check_consensus_np(fill: dict, warns: list) -> None:
    """v5.0 机制二（乐观税门禁）交叉校验：valuation_inputs.consensus_np（当年卖方一致预期
    归母净利均值，亿元）必须照抄 em_fetch --out 落盘 JSON 的 consensus_np.np_avg——
    偏差 >1% 拒渲染；fill 有值落盘无键 → 拒渲染（手估嫌疑）；落盘有 fill 无 → 软告警
    （漏抄，乐观税未检）；双向皆缺 → 通过。读取套路复用 _check_period_track 同款
    （quote.source_file 落盘 JSON；落盘读不到时降级跳过比对——主键门禁已管）。"""
    vi = fill.get("valuation_inputs") or {}
    raw = vi.get("consensus_np")
    fc = _strict_num(raw)
    if raw is not None and str(raw).strip() and fc is None:
        raise ValueError(f"valuation_inputs.consensus_np 不是纯数字: {raw!r}——照抄字段禁止夹带文字"
                         f"（亿元；口径注请写进 .source 说明后重渲）")
    ref = _quote_ref(fill)   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
    rc = _num(((ref or {}).get("consensus_np") or {}).get("np_avg")) if ref is not None else None
    if fc is None and rc is None:
        return
    if fc is None:
        warns.append(f"valuation_inputs.consensus_np 漏抄（落盘 consensus_np.np_avg={rc:g}）："
                     f"乐观税未检——照抄 em_fetch --out 落盘值回填后重渲"
                     f"（无卖方覆盖标的落盘无此键，不在此列）")
        return
    if rc is None:
        if ref is None:
            warns.append("valuation_inputs.consensus_np 已填但 quote.source_file 缺失或读不到："
                         "无法交叉校验（quote 门禁已管主键，本条不重复硬拒）")
            return
        raise ValueError(f"valuation_inputs.consensus_np 落盘无值而 fill 填了 {fc:g}："
                         f"E5 未覆盖标的禁止手估一致预期——以 em_fetch --out 落盘为准修正后重渲")
    dev = abs(fc - rc)
    bad = abs(fc) > 0.005 if rc == 0 else dev / abs(rc) > 0.01
    if bad:
        pct = f"（偏差 {dev / abs(rc) * 100:.1f}% > 1%）" if rc else ""
        raise ValueError(f"valuation_inputs.consensus_np 与 em_fetch 落盘值不一致: fill={fc:g} vs "
                         f"落盘 consensus_np.np_avg={rc:g}{pct}——一致预期照抄落盘禁手改，"
                         f"以落盘值为准修正后重渲")


def _check_growth_consistency(fill: dict, warns: list) -> None:
    """v5.1.2：growth_plot 增速与落盘一致预期/valuation 基础情景换算对账（条件不齐静默跳过）——
    基数=fin_trend「归母净利」柱末年值（标准 4 面板之一）；落盘 np_avg÷基数−1 vs
    fcst.np_consensus（>2pct 告警）；base.profit÷基数−1 应落在 [np_lo−2, np_hi+2]（越界告警）。
    合并年份区间（如 2026-27E）的 np_consensus 是累计增速，不套用上一年度的单年换算公式。
    基数 ≤0（亏损期）换算无意义，跳过。"""
    ft = fill.get("fin_trend") or {}
    gp = fill.get("growth_plot") or {}
    years = [str(y) for y in (ft.get("years") or [])]
    base_np = None
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        for b in p.get("bars") or []:
            nm = str((b or {}).get("name") or "")
            if "归母净利" in nm and "扣非" not in nm:
                vals = [_num(x) for x in (b.get("values") or [])]
                if vals and len(vals) == len(years) and None not in vals:
                    base_np = vals[-1]
    fcst = [f for f in (gp.get("fcst") or []) if isinstance(f, dict)]
    if base_np is None or base_np <= 0 or not years or not fcst:
        return
    m_y = re.fullmatch(r"20\d{2}", years[-1])
    if not m_y:
        return
    last_year = int(m_y.group(0))
    cnp = (_quote_ref(fill) or {}).get("consensus_np") or {}
    np_avg = _num(cnp.get("np_avg"))
    _base_sc = _scenario_by_key((fill.get("valuation") or {}).get("scenarios"), "base")
    base_profit = _num(_base_sc.get("profit")) if _base_sc else None
    for f in fcst:
        ym = re.search(r"20\d{2}", str(f.get("y") or ""))
        if not ym or int(ym.group(0)) != last_year + 1:
            continue
        cnp_yr = _num(cnp.get("year"))
        cumulative_year = re.search(r"20\d{2}\s*[-–—/]\s*(?:20)?\d{2}E\b", str(f.get("y") or ""))
        if not cumulative_year and np_avg and cnp_yr and int(cnp_yr) == last_year + 1:
            g_cons = (np_avg / base_np - 1) * 100
            npc = _num(f.get("np_consensus"))
            if npc is not None and abs(npc - g_cons) > 2:
                warns.append(f"growth_plot {f['y']} np_consensus（{npc:g}%）与落盘一致预期换算增速"
                             f"（{g_cons:.1f}%＝np_avg {np_avg:g}亿÷上年归母净利 {base_np:g}亿−1）差 "
                             f"{abs(npc - g_cons):.1f}pct > 2pct：一致预期照抄 E5 落盘（v5.1.2）")
        if base_profit:
            g_base = (base_profit / base_np - 1) * 100
            lo, hi = _num(f.get("np_lo")), _num(f.get("np_hi"))
            if lo is not None and hi is not None and not (lo - 2 <= g_base <= hi + 2):
                warns.append(f"valuation 基础情景换算增速（{g_base:.1f}%）越出 growth_plot 本文区间 "
                             f"[{lo:g}, {hi:g}]（容差 ±2pct）：5 章图与 7 章情景应口径一致（v5.1.2）")


def _check_quote_present(fill: dict, warns: list) -> None:
    """quote 缺失门禁（v4.11.1 升级，审核 D5）：fill date ≥ 2026-09-02（v4.8 引入 quote 之日）
    缺 quote → 拒渲染（不填 quote 即可绕过现价防伪的静默口被关上）；此前日期的存量 fill
    → 维持告警豁免。quote 存在但不一致已在 _check_quote_consistency 拒渲染。"""
    if fill.get("quote"):
        return
    if str(fill.get("date") or "") >= "2026-09-02":
        raise ValueError("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪"
                         "（神华 601088 现价造假事故修复项）——v4.8 起的新报告必须在 em_fetch 时加 "
                         "--out 落盘，并在 fill 回填 quote.source_file 后重渲"
                         "（2026-09-02 前的存量 fill 仅告警豁免）")
    warns.append("quote 字段缺失：现价/PE(TTM) 无 em_fetch --out 落盘防伪（神华 601088 事故修复项）"
                 "——新报告应在 em_fetch 时加 --out 落盘，并在 fill 回填 quote.source_file")


# ---------------- v5.0 第 3 章「最新报告期透视」period_track 校验 ----------------
_PERIOD_LABEL_KEYS = ("period", "sq_label", "sq_prev_label")


_PERIOD_NUM_KEYS = ("rev", "np", "np_dedt", "ocf", "sq_rev", "sq_np", "sq_prev_rev", "sq_prev_np",
                    "sq_dedt", "sq_prev_dedt", "sq_ocf", "sq_prev_ocf")


_PERIOD_YOY_KEYS = ("rev_yoy", "np_yoy", "np_dedt_yoy", "ocf_yoy", "sq_rev_yoy", "sq_np_yoy",
                    "sq_dedt_yoy", "sq_ocf_yoy")


_PERIOD_BAND_KEYS = ("band_np", "band_rev")


def _period_time_pct(period: str):
    """报告期 → 时间进度（中报/H1/上半年 .50 / 一季 .25 / 三季 .75）；无法解析 → None。
    不写裸「半年」——「近半年」类表述会误命中（热核 P1-2：conftest 的 2026一季/三季 标签
    曾认不出，对账对一季/三季期整体失效）。"""
    if re.search(r"中报|H1|上半年", period, re.I):
        return 0.5
    if re.search(r"一季报|一季度|一季|Q1|1季报", period, re.I):
        return 0.25
    if re.search(r"三季报|三季度|三季|Q3|3季报", period, re.I):
        return 0.75
    return None


def _check_period_track(fill: dict, warns: list) -> None:
    """v5.0 第 3 章 period_track 校验（quote 防伪同款纪律：照抄 em_fetch --out 落盘，禁手估）。
    硬拒：fill 有 period_track 而落盘无该键（v5.5.1 港股 5 位代码文案分派——hk_income 无权限时
    period_track 永不落盘，真实出路是删除 fill 字段而非重跑 em_fetch；拒渲染本身不变）；
    照抄字段与落盘不一致（标签/文字同比完全一致，
    数值偏差 >1%；fill 有值而落盘 None=手估嫌疑）；consensus_np 与落盘 np_avg 失配；
    verdict_* 非四选一；goal_* 非正数。
    软告警：落盘有 period_track 而 fill 未回填（第 3 章缺席）；quote 缺失/落盘读不到
    （主键门禁 _check_quote_consistency/_check_quote_present 已管，不重复硬拒）；
    fill None 而落盘有值（漏抄，章内容缩水）；判词缺失（渲染兜底「无法判定」）；
    年报期填 industry/forecast/note（整章消失不渲染）；note_html 纯文本 >120 字。
    数值容差与 quote 同款（相对 1%）；百分数类字段（yoy/节奏带）叠加 0.1 绝对容差——
    fill 按一位小数照抄落盘原始 float，小值四舍五入会被纯相对容差误伤。"""
    pt = fill.get("period_track")
    if pt is not None and not isinstance(pt, dict):
        raise ValueError(f"period_track 字段需为对象，实际: {type(pt).__name__}")
    ref = _quote_ref(fill)   # 落盘读不到：_check_quote_consistency 已硬拒，这里降级跳过比对
    ref_pt = (ref or {}).get("period_track")
    if pt and ref is None:
        warns.append("period_track 已填但 quote.source_file 缺失或读不到：第 3 章数据无法交叉校验"
                     "（quote 门禁已管主键，本条不重复硬拒）——请重跑 em_fetch --out 落盘并回填 quote 后重渲")
    if pt and ref is not None and not isinstance(ref_pt, dict):
        hk = _is_hk_code(fill)
        body = ("港股标的 em_fetch 依赖 tushare hk_income 权限，无权限时 period_track 永不落盘"
                if hk else
                "第 3 章数据必须照抄 em_fetch --out 落盘的 period_track 照抄行，禁手估")
        tail = ("——请删除 fill 的 period_track（第 3 章整章缺席为港股预期形态），勿重跑 em_fetch；"
                "港股财报数据请走降级路径（优先妙想 MCP mx_hk_finance_data 直查）核对后写正文，禁手估"
                if hk else
                "（神华现价造假同款防伪纪律）——请重跑 em_fetch --out 落盘，"
                "或删除 fill 的 period_track 后重渲")
        raise ValueError("fill.period_track 已填但 em_fetch 落盘 JSON 无 period_track 键："
                         + body + tail)
    if not pt and isinstance(ref_pt, dict):
        warns.append("em_fetch 落盘含 period_track 但 fill 未回填：第 3 章「最新报告期透视」将缺席"
                     "——请照抄落盘 period_track 行回填（年报期 is_annual=true 整章消失属预期，可忽略本条）")
    if pt and isinstance(ref_pt, dict):
        # 交叉比对（fill vs 落盘 period_track；报错带字段名/期望值/实际值/修复指向）
        def _mismatch(key, fv, rv, extra=""):
            raise ValueError(f"period_track.{key} 与 em_fetch 落盘值不一致: fill={fv!r} vs 落盘={rv!r}{extra}"
                             "——第 3 章数据照抄 em_fetch --out 落盘 period_track 照抄行，禁手改；"
                             "以落盘值为准修正后重渲")

        def _close(fv, rv, pct=False):
            """数值容差：相对 1%（quote 同款；落盘 0 时按两位小数精度 0.005 亿绝对容差）；
            pct=True（百分数字段）叠加 0.1pct 绝对容差（一位小数照抄的四舍五入）。"""
            if rv == 0:
                return abs(fv) <= 0.005
            return abs(fv - rv) / abs(rv) <= 0.01 or (pct and abs(fv - rv) <= 0.1)

        def _copy_missing(key, rv):
            warns.append(f"period_track.{key} 漏抄（落盘={rv!r}）：照抄行请完整回填")

        for key in _PERIOD_LABEL_KEYS:
            fv, rv = pt.get(key), ref_pt.get(key)
            if fv is None and rv is None:
                continue
            if fv is None or not str(fv).strip():
                _copy_missing(key, rv)
                continue
            if rv is None or str(fv).strip() != str(rv).strip():
                _mismatch(key, fv, rv)
        # F5：is_annual 进交叉校验——年报期整章消失是硬约束，布尔不等即拒渲染（不容改写）
        if bool(pt.get("is_annual")) != bool(ref_pt.get("is_annual")):
            _mismatch("is_annual", pt.get("is_annual"), ref_pt.get("is_annual"),
                      "（年报期整章消失是硬约束）")
        for key in _PERIOD_NUM_KEYS:
            raw = pt.get(key)
            fv = _strict_num(raw)
            if raw is not None and str(raw).strip() and fv is None:
                raise ValueError(f"period_track.{key} 不是纯数字: {raw!r}——照抄字段禁止夹带文字"
                                 f"（亿元两位小数；口径注请写进 note_html 后重渲）")
            rv = _num(ref_pt.get(key))
            if fv is None and rv is None:
                continue
            if fv is None:
                _copy_missing(key, rv)
                continue
            if rv is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {fv:g}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            if not _close(fv, rv):
                _mismatch(key, fv, rv, f"（偏差 {abs(fv - rv) / abs(rv) * 100:.1f}% > 1%）")
        for key in _PERIOD_YOY_KEYS:
            raw, rv_raw = pt.get(key), ref_pt.get(key)
            fv, rv = _strict_num(raw), _strict_num(rv_raw)
            if raw is None and rv_raw is None:
                continue
            if raw is None or not str(raw).strip():
                _copy_missing(key, rv_raw)
                continue
            if rv_raw is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {raw!r}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            if fv is not None and rv is not None:
                if not _close(fv, rv, pct=True):
                    _mismatch(key, fv, rv, f"（偏差 {abs(fv - rv):.2f}pct > 容差）")
            elif str(raw).strip() != str(rv_raw).strip():
                # 文字同比（扭亏/转亏/减亏/增亏）要求完全一致
                _mismatch(key, raw, rv_raw, "（文字同比要求完全一致）")
        for key in _PERIOD_BAND_KEYS:
            fb, rb = pt.get(key), ref_pt.get(key)
            if fb is None and rb is None:
                continue
            if fb is None:
                _copy_missing(key, rb)
                continue
            if rb is None:
                raise ValueError(f"period_track.{key} 落盘无值而 fill 填了 {fb!r}："
                                 f"落盘没有的数据禁止手估填入——以 em_fetch --out 落盘为准修正后重渲")
            fl = [_strict_num(x) for x in fb] if isinstance(fb, (list, tuple)) else []
            rl = [_strict_num(x) for x in rb] if isinstance(rb, (list, tuple)) else []
            if len(fl) < 2 or len(rl) < 2 or None in fl or None in rl:
                raise ValueError(f"period_track.{key} 结构非法: fill={fb!r} vs 落盘={rb!r}"
                                 f"（节奏带为 [下限%, 上限%] 两个纯数字）")
            for i in (0, 1):
                if not _close(fl[i], rl[i], pct=True):
                    _mismatch(f"{key}[{i}]", fl[i], rl[i])
        fy, ry = pt.get("band_years"), ref_pt.get("band_years")
        if fy is None and ry is None:
            pass
        elif fy is None:
            _copy_missing("band_years", ry)
        else:
            # 类型守卫与上方 band 守卫（isinstance(fb, (list, tuple))）对齐：字符串按字符迭代
            # 会把 "2023" 拆成 [2,0,2,3]、空串与空列表假相等——非数组一律按不一致拒
            if not isinstance(fy, (list, tuple)):
                same_years = False
            else:
                try:
                    same_years = [int(x) for x in fy] == [int(x) for x in (ry or [])]
                except (TypeError, ValueError):
                    same_years = False
            if not same_years:
                _mismatch("band_years", fy, ry)
        # consensus_np：fill 照抄的是落盘 consensus_np.np_avg（E5 当年净利均值）
        raw_c = pt.get("consensus_np")
        fc = _strict_num(raw_c)
        if raw_c is not None and str(raw_c).strip() and fc is None:
            raise ValueError(f"period_track.consensus_np 不是纯数字: {raw_c!r}——照抄字段禁止夹带文字")
        rc = _num(((ref or {}).get("consensus_np") or {}).get("np_avg"))
        if fc is not None and rc is None:
            raise ValueError(f"period_track.consensus_np 落盘无值而 fill 填了 {fc:g}：E5 未覆盖标的"
                             f"禁止手估一致预期——以 em_fetch --out 落盘为准修正后重渲")
        if fc is None and rc is not None:
            _copy_missing("consensus_np", f"consensus_np.np_avg={rc:g}")
        if fc is not None and rc is not None and not _close(fc, rc):
            _mismatch("consensus_np", fc, rc,
                      f"（偏差 {abs(fc - rc) / abs(rc) * 100:.1f}% > 1%，对照落盘 consensus_np.np_avg）")
    if pt:
        is_annual = bool(pt.get("is_annual"))
        for vk, ak in (("verdict_rev", "rev"), ("verdict_np", "np"), ("verdict_dedt", "np_dedt")):
            v = str(pt.get(vk) or "").strip()
            if v:
                if v not in _PERIOD_VERDICTS:
                    raise ValueError(f"period_track.{vk} 取值非法: {v!r}——判词四选一："
                                     f"{'/'.join(_PERIOD_VERDICTS)}（模型按节奏带+完成度判定）")
            elif not is_annual and _num(pt.get(ak)) is not None:
                warns.append(f"period_track.{vk} 未填：章内该指标判词将显示「无法判定」（判词四选一 "
                             f"{'/'.join(_PERIOD_VERDICTS)}，由模型按节奏带与完成度判定）")
        # v5.1.2：判词与完成度机械对账（分母与子弹图同源：一致预期优先、缺则经营目标）
        t_pct = _period_time_pct(str(pt.get("period") or ""))
        if t_pct is not None and not is_annual:
            for vk, ak, gk, ck in (("verdict_rev", "rev", "goal_rev", None),
                                   ("verdict_np", "np", "goal_np", "consensus_np")):
                v = str(pt.get(vk) or "").strip()
                r = _period_ratio(pt, ak, gk, ck)
                if not v or r is None:
                    continue
                if v == "超前" and r < t_pct - 0.15:
                    warns.append(f"period_track.{vk}=超前 但完成度 {r * 100:.0f}% 低于时间进度 "
                                 f"{t_pct * 100:.0f}%−15pct（分母=一致预期/经营目标，与子弹图同源；"
                                 "判词与数据矛盾请复核，v5.1.2）")
                if v == "滞后" and r > t_pct + 0.15:
                    warns.append(f"period_track.{vk}=滞后 但完成度 {r * 100:.0f}% 高于时间进度 "
                                 f"{t_pct * 100:.0f}%+15pct（分母=一致预期/经营目标，与子弹图同源；"
                                 "判词与数据矛盾请复核，v5.1.2）")
        for gk in ("goal_rev", "goal_np"):
            raw = pt.get(gk)
            if raw is None or not str(raw).strip():
                continue
            gv = _strict_num(raw)
            if gv is None or gv <= 0:
                raise ValueError(f"period_track.{gk} 必须为正数（亿元；年报「经营计划」段披露口径，"
                                 f"未披露请填 null），实际: {raw!r}")
        if is_annual:
            extra = [k for k in ("industry_html", "forecast_html", "note_html", "summary_html")
                     if str(pt.get(k) or "").strip()]
            if extra:
                warns.append(f"period_track.is_annual=true（年报期第 3 章整章消失）：{'/'.join(extra)} "
                             f"已填内容不会渲染——年报期请省略这些字段，或留待下一季报期使用")
        note_len = len(_plain_text(str(pt.get("note_html") or "")))
        if note_len > 120:
            warns.append(f"period_track.note_html 纯文本 {note_len} 字 > 120：口径提示定位 ≤3 句，"
                         f"展开论证归各章")
        summary_len = len(_plain_text(str(pt.get("summary_html") or "")))
        if summary_len > 100:
            warns.append(f"period_track.summary_html 纯文本 {summary_len} 字 > 100：进度小结定位 ≤2 句，"
                         f"展开论证归 4.4/5.1/9 章")


def _check_quality_inputs(fill: dict, warns: list) -> None:
    if _quality_version(fill) != 2:
        return
    ref = _quote_ref(fill) or {}
    package = ref.get("quality_inputs")
    if not isinstance(package, dict):
        warns.append("v2 quote 落盘缺 quality_inputs：请用 em_fetch --quality-v2 与三个 profile 参数重取，"
                     "机械输入目前无法照抄对账")
        return
    report_date = str(fill.get("date") or "").replace("-", "")

    def _day(value):
        digits = re.sub(r"\D", "", str(value or ""))
        return digits[:8] if len(digits) >= 8 else None

    as_of = _day(package.get("as_of"))
    if as_of is None:
        warns.append("quality_inputs.as_of 缺失或非法：无法证明取数截止日期")
    elif as_of > report_date:
        raise ValueError(f"quality_inputs.as_of={as_of} 在报告日之后（{report_date}），拒渲染")
    elif as_of < report_date:
        warns.append(f"quality_inputs.as_of={as_of} 早于报告日 {report_date}：请核对是否使用了陈旧输入")
    latest_ann = _day((package.get("meta") or {}).get("latest_ann_date"))
    if latest_ann and latest_ann > report_date:
        raise ValueError(f"quality_inputs 最新披露日 {latest_ann} 在报告日之后（{report_date}），拒渲染")
    for source in package.get("sources") or []:
        source_date = _day((source or {}).get("as_of"))
        if source_date and source_date > report_date:
            raise ValueError(f"quality_inputs 来源日期 {source_date} 在报告日之后（{report_date}），拒渲染")
    profile = package.get("profile")
    if not isinstance(profile, dict) or package.get("status") == "profile_missing":
        raise ValueError("quality_inputs profile_missing：必须显式提供 stock_type/growth_tier/industry_profile")
    actual = _quality_context(fill)
    for key in ("stock_type", "industry_profile", "growth_tier"):
        if (profile.get(key) or None) != (actual.get(key) or None):
            raise ValueError(f"fill 与落盘 quality_inputs.profile.{key} 不一致："
                             f"{actual.get(key)!r} vs {profile.get(key)!r}")
    score_inputs = fill.get("score_inputs") or {}
    fields = {"1D": ("f_items", "liquidity", "red_flags", "cash_runway_months"),
              "1F": ("roic", "wacc", "incremental_roic", "roic_period_months",
                     "roic_basis", "cash_runway_months")}

    def _compare(path, fill_value, ref_value):
        if fill_value is None and ref_value is not None:
            warns.append(f"quality_inputs.{path} 漏抄（落盘 {ref_value!r}）")
        elif fill_value is not None and ref_value is None:
            warns.append(f"quality_inputs.{path} 落盘缺失/未取到，但 fill 已有 {fill_value!r}："
                         "请补替代来源与证据，不得冒充机械照抄")
        elif fill_value is not None and fill_value != ref_value:
            warns.append(f"quality_inputs.{path} 与落盘不一致：fill={fill_value!r} vs 落盘={ref_value!r}")

    for dim, keys in fields.items():
        for key in keys:
            fv = (score_inputs.get(dim) or {}).get(key)
            rv = (package.get(dim) or {}).get(key)
            if isinstance(fv, dict) or isinstance(rv, dict):
                for child in sorted(set((fv or {}).keys()) | set((rv or {}).keys())):
                    _compare(f"{dim}.{key}.{child}", (fv or {}).get(child), (rv or {}).get(child))
            else:
                _compare(f"{dim}.{key}", fv, rv)
