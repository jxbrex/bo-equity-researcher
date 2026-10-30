#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_charts.py — 图字段与复盘结构校验域（v5.8.3 自 validate.py 按域拆分）。

内容：fin_trend/growth_plot 必填图、可选图纪律（segments/chain/holders/triggers）、
复盘模式（prev_fields/prev_charts/review_miss_diagnostics + .rev 高亮扫描）、
price_history PE 覆盖、cycle_stages/cycle_position 周期卡、earnings_stability、
driver_cards/sensitivity 量纲与覆盖、槽位宽度、4.3 阈值承载、第 11 章绑定告警，
及 _disp_w/_parse_pe_range/_series_month_pe/_prev_chart_facts/_big_segments 工具。
契约：raise = 硬拒渲染；warns.append = 软告警。
"""
import re
from scoring import (
    _num,
    _plain_text,
    growth_sigma)
from charts_base import (
    _sensitivity_items,
    _var_key,
    _gap_dim_ok,
    _YOY_TEXT,
    parse_stage_period)
from charts_cycle import _pe_band_ok
from validate_common import (
    _HTML_FIELDS,
    _quote_ref,
    _resolve_type_tier,
    _anchor_unanchored_type)


# 回测高亮扫描：cycle_html 同属可挂 .rev 的正文；peers_meta 是纯文本（渲染时转义）单列改写提示。
_REV_HTML_FIELDS = _HTML_FIELDS + ("cycle_html",)


_CROSS_VERSION_RE = re.compile(
    r"较上版|上一版|(?<!以)上版|旧报告|旧警戒线|(?<!新)旧版|旧锚|原假设|被证伪|被验证|"
    r"新增重大变量|新增重大风险|清单外新增风险|本版复盘修正")


_REV_ELEMENT_RE = re.compile(
    r"<([A-Za-z][\w:]*)\b[^>]*?\sclass\s*=\s*[\"'][^\"']*\brev\b[^\"']*[\"'][^>]*>.*?</\1>",
    re.I | re.S)


_REV_CLASS_RE = re.compile(r"\sclass\s*=\s*[\"'][^\"']*\brev\b[^\"']*[\"']", re.I)


def _check_chart_fields(fill: dict) -> None:
    """v4.9 必填图字段硬校验：fin_trend（4.4 小图墙，替手写年表）/ growth_plot（5.1 增长图）。
    两字段数据均来自标准采集（E3 年表 / E5 一致预期），缺失=空心趋势章节 → 拒渲染。
    growth_plot 豁免：stock_type 含「未盈利/管线」，或 fin_trend 最新归母净利 ≤0（预测增速无意义）。"""
    ft = fill.get("fin_trend")
    if not isinstance(ft, dict):
        raise ValueError('fin_trend 为必填字段（v4.9 起 4.4 财务健康年表由脚本图墙替代）：'
                         '{"years":["2021",...,"2025"], "panels":[{"title":"营收 × 毛利率",'
                         '"bars":[{"name":"营收","unit":"亿","values":[...]}], '
                         '"lines":[{"name":"毛利率","pct":true,"values":[...]}]}, ...]}'
                         '——数据照抄 em_fetch E3 年表，禁手估')
    years = ft.get("years") or []
    if len(years) < 3:
        raise ValueError(f"fin_trend.years 仅 {len(years)} 年 < 3：趋势图墙至少 3 个年度点（建议 5 年）")
    ok = []
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        bars_ok = [b for b in p.get("bars") or []
                   if b.get("name") and len(b.get("values") or []) == len(years)
                   and all(_num(v) is not None for v in b.get("values") or [])]
        lines_ok = [ln for ln in p.get("lines") or []
                    if ln.get("name") and len(ln.get("values") or []) == len(years)
                    and all(_num(v) is not None for v in ln.get("values") or [])]
        if bars_ok or lines_ok:
            ok.append(p)
    if len(ok) < 3:
        raise ValueError(f"fin_trend.panels 有效面板 {len(ok)} < 3（标准 4 面板（v4.9.1）：营收×毛利率 / "
                         f"归母净利+扣非净利×净利率×ROE / 经营现金流+自由现金流×现金含量（阈值0.7) / "
                         f"应收+存货周转天数（纯双线）；每面板 1-2 柱或 1-2 线、柱线至少其一，"
                         f"values 与 years 等长且全为数字）")
    latest_np = None
    for p in ft.get("panels") or []:
        if not isinstance(p, dict):
            continue
        for b in p.get("bars") or []:
            name = str((b or {}).get("name") or "")
            if "归母净利" in name and "扣非" not in name:
                values = [_num(v) for v in (b.get("values") or [])]
                if values and len(values) == len(years) and None not in values:
                    latest_np = values[-1]
    growth_optional = latest_np is not None and latest_np <= 0
    st = str(fill.get("stock_type") or "")
    if "未盈利" not in st and "管线" not in st and not growth_optional:
        gp = fill.get("growth_plot")
        if not isinstance(gp, dict):
            raise ValueError('growth_plot 为必填字段（最新年亏损时豁免，正文用利润金额情景）：'
                             '{"hist":[{"y":"2023","rev":…,"np":…}, ...≥3年], '
                             '"fcst":[{"y":"2026E","np_lo":…,"np_hi":…}, ...]}'
                             '——历史取 E3 同比；无卖方覆盖时 np_consensus 省略')
        hist_ok = [h for h in gp.get("hist") or []
                   if h.get("y") and (_num(h.get("np")) is not None
                                      or str(h.get("np") or "").strip() in _YOY_TEXT)]
        fcst_ok = [f for f in gp.get("fcst") or []
                   if f.get("y") and _num(f.get("np_lo")) is not None and _num(f.get("np_hi")) is not None
                   and _num(f.get("np_hi")) >= _num(f.get("np_lo"))]
        if len(hist_ok) < 3:
            raise ValueError(f"growth_plot.hist 有效年 {len(hist_ok)} < 3（需 y + 数字增速或扭亏等文字；rev 可省）")
        if not fcst_ok:
            raise ValueError("growth_plot.fcst 无有效年（需 y + np_lo ≤ np_hi；np_consensus 在无覆盖时可省）")


# v5.8.2：第 11 章绑定告警表驱动（3 处同骨架收敛）——「{字段} 已填但 cycle_html 缺失」
# 告警文案后缀逐处不同，由各规格自带；此处只收敛「字段已填 + cycle_html 缺失 → 告警」骨架
_CH11_BINDINGS = (
    ("pe_history",
     lambda fill: (fill.get("pe_history") or {}).get("hist_lo") is not None,
     "PE 历史带图挂第 11 章，整章被删后图不显示——周期/成长/稳定价值/成熟·停滞/困境反转"
     "应写第 11 章，或删除 pe_history"),
    ("price_history",
     lambda fill: bool((fill.get("price_history") or {}).get("series")),
     "股价/PE 发丝图挂第 11 章，整章被删后图不显示——与 pe_history 同规则（v4.7.1 绑定关系）"),
    ("cycle_stages",
     lambda fill: bool(fill.get("cycle_stages")),
     "阶段卡挂第 11 章条件块内，整章不渲染则卡无处显示（同 pe_history/price_history 绑定规则）"),
)


def _check_ch11_binding(fill: dict, warns: list) -> None:
    """第 11 章绑定告警（v5.8.2 表驱动）：图字段已填但 cycle_html 缺失 → 图/卡无处显示。
    触发谓词逐处保留原口径——pe_history 认 hist_lo 非 None（空串也算已填）、
    price_history 认 series 真值（空列表不算）、cycle_stages 认列表非空。"""
    if (fill.get("cycle_html") or "").strip():
        return
    std, _tier, _legacy = _resolve_type_tier(fill)
    if std in ("周期股", "成长型", "稳定价值", "成熟/停滞", "困境反转"):
        msg = (f"cycle_html 缺失：{std} 第 11 章周期分析为必做"
               "（成长型含高速/中速层、成熟·停滞均按此口径），请补 cycle_html 或调整分型")
        if str(fill.get("date") or "") >= "2026-10-26":
            raise ValueError(msg)
        warns.append(msg)
        return
    for key, triggered, msg in _CH11_BINDINGS:
        if triggered(fill):
            warns.append(f"{key} 已填但 cycle_html 缺失：{msg}")


def _check_prev_fields(fill: dict, warns: list) -> None:
    """prev 内部字段校验（回测模式锚点缺项会静默显示 "?"/"—"）。"""
    if fill.get("prev"):
        pv = fill["prev"]
        required = ["date", "quality", "valuation", "timing", "target_range"]
        if pv.get("quality_version") == "legacy-single-track":
            required.remove("valuation")
        for k in required:
            if not pv.get(k):
                warns.append(f"prev.{k} 缺失：回测对比条该行将显示缺省值，请补全上版锚点")
        # 复盘高亮校验：评分变化/被证伪假设/新增变量应挂 .rev（全文 <3 处说明漏标）
        rev_n = sum(len(_REV_CLASS_RE.findall(fill.get(name) or ""))
                    for name in _REV_HTML_FIELDS)
        if rev_n < 3:
            warns.append(f"回测模式下 .rev 高亮过少（全文仅 {rev_n} 处 < 3）："
                         f"评分变化/被证伪假设/新增变量应标注（fill-schema 的 .rev 规则）")
        # 明确跨版信号漏标（review_html 专属对比不扫；普通「新增产能」不触发）
        unmarked = []
        for name in _REV_HTML_FIELDS:
            if name == "review_html":
                continue
            text = _REV_ELEMENT_RE.sub("", fill.get(name) or "")
            hits = list(dict.fromkeys(_CROSS_VERSION_RE.findall(text)))
            if hits:
                unmarked.append(f"{name}（{'、'.join(hits)}）")
        meta_hits = list(dict.fromkeys(_CROSS_VERSION_RE.findall(fill.get("peers_meta") or "")))
        if meta_hits:
            unmarked.append(f"peers_meta（{'、'.join(meta_hits)}）")
        if unmarked:
            warns.append(f"回测模式跨版表述未挂 .rev：{'；'.join(unmarked)}"
                         "——HTML 字段请在对应表述外包 <span class=\"rev\">…</span>；"
                         "peers_meta 为纯文本，请改写掉跨版措辞")
        # 关键假设变更表（防评分漂移，backtest.md 6.6 硬性要求）
        rv = fill.get("review_html") or ""
        if rv and ("<table" not in rv or "假设" not in rv):
            warns.append("review_html 缺关键假设变更表：R 章节必须含相邻两版三情景假设对比表"
                         "（假设未变也要显式写明），见 backtest.md 6.6")


def _prev_chart_facts(fill: dict) -> dict:
    """本版图字段事实（v5.5.1 F3 结构对照右侧，判定与渲染同源）：
    gap_plot=有效维度（_gap_dim_ok，取前 6）≥2 才落图；fin_trend_panels=有效面板数
    （bars/lines 名非空且 values 与 years 等长全数字，同 build_fin_trend）；growth_fcst_years=
    有效预测年数（同 build_growth_plot）；pe_history=可生成性（v5.5.1 P1-1：调
    charts_cycle._pe_band_ok 单源，键不齐/域非法即不落图——此前只看字段非空，缺键减配漏检）。"""
    gp = fill.get("gap_plot") or {}
    gap_dims = [d for d in (gp.get("dims") or []) if _gap_dim_ok(d)][:6]
    ft = fill.get("fin_trend") or {}
    years = [str(y) for y in (ft.get("years") or [])]

    def _series_ok(seq):
        return [x for x in seq if isinstance(x, dict) and str(x.get("name") or "").strip()
                and len(x.get("values") or []) == len(years)
                and all(_num(v) is not None for v in x.get("values") or [])]

    panels = sum(1 for p in (ft.get("panels") or []) if isinstance(p, dict)
                 and (_series_ok(p.get("bars") or []) or _series_ok(p.get("lines") or [])))
    fcst_n = sum(1 for f in ((fill.get("growth_plot") or {}).get("fcst") or [])
                 if isinstance(f, dict) and str(f.get("y") or "").strip()
                 and _num(f.get("np_lo")) is not None and _num(f.get("np_hi")) is not None
                 and _num(f.get("np_hi")) >= _num(f.get("np_lo")))
    return {"gap_plot": len(gap_dims) >= 2, "fin_trend_panels": panels,
            "growth_fcst_years": fcst_n, "pe_history": _pe_band_ok(fill)}


def _review_chart_note(fill, aliases):
    text = _plain_text(fill.get("review_html") or "")
    actions = ("减配", "少画", "不再绘制", "不再生成", "不生成", "未生成", "不画",
               "删除", "仅画", "只画", "缺省", "降级")
    reasons = ("原因", "口径", "避免", "未获取", "缺少", "禁填", "无法", "无情景",
               "失真", "规则", "锚不住", "替代", "不可比", "不足")
    return any(any(alias in sentence for alias in aliases)
               and any(action in sentence for action in actions)
               and any(reason in sentence for reason in reasons)
               for sentence in re.split(r"[。；;]", text))


def _cycle_anchor_fallback_documented(fill):
    text = _plain_text(fill.get("cycle_html") or "")
    return ("未标校准锚" in text
            and any(word in text for word in ("失真", "不可比", "不可用"))
            and any(word in text for word in ("改用", "替代"))
            and any(word in text for word in ("同业锚", "正常化", "市值", "rNPV")))


def _check_prev_charts(fill: dict, warns: list) -> None:
    """v5.5.1 F3 复盘模式「旧有新无」结构对照（软告警，升拒登记 handoff）：prev.charts 照抄
    上版 fill 的图字段事实，本版逐项对照——上版有而本版不生成/变少即告警，减配要求写进
    review_html。小米 01810 2026-10-07 实证：gap_plot 消失、fin_trend 少 panel、
    growth_plot.fcst 少年份、pe_history 消失全程零告警，只能靠肉眼发现。"""
    pv = fill.get("prev")
    if not isinstance(pv, dict):
        return
    pc = pv.get("charts")
    if not isinstance(pc, dict):
        warns.append("prev.charts 未填：复盘模式须照抄上版 fill 的图字段事实"
                     '（{"gap_plot": true, "fin_trend_panels": 4, "growth_fcst_years": 2, '
                     '"pe_history": true}），否则本版相对上版的图形减配（gap_plot 消失 / '
                     "fin_trend 少 panel / growth_plot.fcst 少年份 / pe_history 消失）无人对照"
                     "——请回填上版事实后重渲（fill-schema「prev」节）")
        return
    now = _prev_chart_facts(fill)
    why = "——若为有意减配，请在 review_html 写明减配理由与替代数据来源；否则补齐"
    if pc.get("gap_plot") and not now["gap_plot"] and not _review_chart_note(fill, ("逐机构定位", "预期差图")):
        warns.append(f"复盘减配：上版 gap_plot 逐机构定位图已生成（prev.charts.gap_plot=true）"
                     f"而本版不生成（维度不足 2 行）{why}（v5.5.1 结构对照）")
    was_p = _num(pc.get("fin_trend_panels"))
    if (was_p is not None and now["fin_trend_panels"] < was_p
            and not _review_chart_note(fill, ("财务趋势图", "图墙"))):
        warns.append(f"复盘减配：上版 fin_trend 有效面板 {was_p:g} 个而本版 {now['fin_trend_panels']} 个"
                     f"{why}（第 4.4 章图墙少画）")
    was_f = _num(pc.get("growth_fcst_years"))
    if (was_f is not None and now["growth_fcst_years"] < was_f
            and not _review_chart_note(fill, ("利润增长图",))):
        warns.append(f"复盘减配：上版 growth_plot.fcst 预测年 {was_f:g} 个而本版 "
                     f"{now['growth_fcst_years']} 个{why}（第 5.1 章利润增长图缩短）")
    std, tier, _legacy = _resolve_type_tier(fill)
    pe_forbidden = (std == "成长型" and tier == "high") or std == "未盈利/管线"
    if (pc.get("pe_history") and not now["pe_history"] and not pe_forbidden
            and not _review_chart_note(fill, ("PE 历史带", "PE历史带"))):
        warns.append(f"复盘减配：上版 pe_history（第 11 章 PE 历史带图）已生成而本版不生成"
                     f"（字段缺失或 hist_lo/hist_hi/pe_ttm/pe_band 键不齐）{why}")


def _check_optional_charts(fill: dict, warns: list) -> None:
    """v4.8 可选图字段纪律：业务构成占比和 / 产业链两端 / 户数期数。
    v5.4.1：pe_history 禁填（成长型·高速层 / 未盈利·管线 → 软告警，fill-schema 填写条件）。
    （发丝图/pe_history/阶段卡的第 11 章绑定告警迁 _check_ch11_binding 表驱动，v5.8.2）"""
    seg = fill.get("segments") or {}
    items = seg.get("items") or []
    if items:
        # v5.1.2：合计口径与渲染同源——渲染只画 name+rev_pct 齐全的行（charts_l1），
        # 缺名/缺占比的行不落图，其占比不得计入「≈100%」判定
        drawn = [it for it in items
                 if isinstance(it, dict) and str(it.get("name") or "").strip()
                 and _num(it.get("rev_pct")) is not None]
        if len(drawn) < len(items):
            warns.append(f"segments 有 {len(items) - len(drawn)} 行缺 name 或 rev_pct：该行不落图，"
                         "占比缺口会在图上去向不明，请补齐或删除")
        s = sum(_num(it.get("rev_pct")) or 0 for it in drawn)
        if abs(s - 100) > 5:
            warns.append(f"segments 收入占比合计 {s:.1f}% 偏离 100%：请核对是否漏列分部"
                         f"（E6 各分部占比之和应≈100%，若有「其他」项请补列）；"
                         f"若 E6 含按产品/地区双维数据，占比减半多为未剔合计行所致，请回 E6 原文核对")
    # v4.9：period 只放短时段标签（青啤实证把整段口径清洗说明塞进 period，图标题变 70 字怪物）
    period = str(seg.get("period") or "")
    if len(period) > 8:
        warns.append(f"segments.period「{period[:12]}…」共 {len(period)} 字 > 8：period 只放时段标签"
                     f"（如 2026中报），口径/清洗说明请挪到 segments.note（渲染为图注小字）")
    if any(k in period for k in ("口径", "源为", "合计行", "剔除", "重算")):
        warns.append("segments.period 含口径/来源字样：请挪到 segments.note 字段，period 只放时段标签")
    ch = fill.get("industry_chain") or {}
    if ch and (not ch.get("upstream") or not ch.get("downstream")):
        warns.append("industry_chain 上游/下游缺一：链条图需两端各至少 1 个行业，缺端图不生成")
    # price_history 发丝图与第 11 章绑定 → 迁 _check_ch11_binding 表驱动（v5.8.2）
    # v5.4.1：pe_history 禁填告警（fill-schema 填写条件长期只写在文档里、零校验）——
    # 成长型·高速层（含旧名「快速成长」）与 未盈利/管线：历史区间锚不住合理带，禁填本字段
    if fill.get("pe_history"):
        # v5.8.2：分型+生效层解析收敛 _resolve_type_tier 单源（本处静默口径：缺 tier 按 mid 兜底，
        # 「== high」判定与原 None 等价）
        std_ph, tier_ph, _leg_ph = _resolve_type_tier(fill)
        if (std_ph == "成长型" and tier_ph == "high") or std_ph == "未盈利/管线":
            shows = f"{std_ph}·高速层" if std_ph == "成长型" else std_ph
            warns.append(f"pe_history 已填但本分型（{shows}）禁填：历史区间锚不住合理带"
                         "（fill-schema 填写条件：周期股/成长型·中速层/成熟·停滞/稳定价值/困境反转"
                         "按数据可得性填；成长型·高速层/未盈利·管线禁填——第 11 章时段表仍可写，"
                         "但本字段删除，估值带改用远期 PE 折现或 rNPV/P/S）")
    holders = fill.get("holders") or []
    # v5.1.2：有效点口径与渲染同源——渲染先滤 num 可解析且带日期的行（charts_misc）
    h_valid = [p for p in holders if isinstance(p, dict) and _num(p.get("num")) is not None
               and str(p.get("date") or "").strip()]
    if holders and len(h_valid) < 3:
        warns.append("holders 有效点 <3（num 可解析且带日期）：户数趋势图不生成"
                     "（E4 默认返回近 8 期，请回填 ≥3 期）")
    # v4.11.0：同一截止日多行告警（E4 上游偶发重复，天齐 20260710 双行且变动值不一致实证；
    # 图内已去重保留后写行，此处提示模型核对哪一行为准）。审计修订：去重键按数字序列归一
    #（"20260710" 与 "2026-07-10" 同日）；去重后 <3 期时图不生成，与图门槛同口径告警
    hdates = ["".join(ch for ch in str((p or {}).get("date") or "") if ch.isdigit())
              for p in h_valid]
    dup = sorted({d for d in hdates if d and hdates.count(d) > 1})
    if dup:
        warns.append(f"holders 存在重复截止日：{'、'.join(dup)}——图内已去重（保留后写行），"
                     f"请核对 E4 原始输出哪一行的变动值为准")
    if len(h_valid) >= 3 and len({d for d in hdates if d}) < 3:
        warns.append("holders 去重后有效期数 <3：户数趋势图不生成（与图内去重门槛同口径）")
    # v4.9：触发条件状态条字段纪律
    trg = fill.get("triggers") or []
    if trg:
        bad = [t for t in trg
               if str((t or {}).get("status") or "pending").strip().lower() not in ("hit", "miss", "pending")]
        if bad:
            warns.append(f"triggers 含非法 status（{len(bad)} 条）：只接受 hit/miss/pending，非法值按 pending 渲染")
        if len(trg) > 8:
            warns.append(f"triggers 共 {len(trg)} 条 > 8：状态条宜 3-6 条，过多稀释跟踪焦点")
        # v5.1.2：hit/miss 行 target「阈值｜实际值」核对（状态语义色正确性不再全靠自觉）
        for t in trg:
            if not isinstance(t, dict):
                continue
            st_ = str(t.get("status") or "pending").strip().lower()
            if st_ not in ("hit", "miss"):
                continue
            tgt = str(t.get("target") or "")
            cond = str(t.get("cond") or "")[:8]
            if "实际" not in tgt:
                warns.append(f"triggers[{cond}] status={st_} 但 target 未写实际值"
                             "（回测核对行格式「阈值｜实际值」，v5.1.2）")
                continue
            m = re.search(r"([≥≤<>])\s*(\d+(?:\.\d+)?)\s*%?\s*[｜|]\s*实际\s*(\d+(?:\.\d+)?)", tgt)
            if m:
                op, thr, act = m.group(1), float(m.group(2)), float(m.group(3))
                hit = act >= thr if op in ("≥", ">") else act <= thr
                if ("hit" if hit else "miss") != st_:
                    warns.append(f"triggers[{cond}] status={st_} 与 target「{tgt}」矛盾："
                                 f"实际 {act:g} {'满足' if hit else '不满足'}阈值 {op}{thr:g}（v5.1.2）")


def _check_price_history_pe(fill: dict, warns: list) -> None:
    """v4.10：price_history 的 pe 过半缺失 → 图只画股价线而标题仍挂 PE(TTM)（图文不符）。
    A 股 E2 月线自带月末 PE(TTM) 序列应照抄——工行 09-11 报告 12 个点 pe 全缺实证。
    v4.11.0：告警口径随图门槛改为「有效 pe <12 点」（图的 PE 线门槛同步放宽——亏损期
    PE 无定义是诚实断线，照抄 E2 全序列后过半缺失不再误杀；天齐 09-13 实证 29/68 点有效）。"""
    ph = fill.get("price_history") or {}
    series = ph.get("series") or []
    if not series:
        return
    # 审计 P1-2：有效口径与图同——点数按 m/close 可解析、pe 经 _num 解析
    #（"—"/"" 等占位字符串旧口径会被计为有效 → 图文不符从缝隙漏过）
    valid = [p for p in series if isinstance(p, dict) and p.get("m") and _num(p.get("close")) is not None]
    n_pe = sum(1 for p in valid if _num(p.get("pe")) is not None)
    if len(valid) >= 12 and n_pe < 12:
        warns.append(f"price_history 的 pe 字段仅 {n_pe}/{len(valid)} 点有效（<12 点）："
                     "PE(TTM) 折线将不生成——A股 E2 月线「全序列」行自带月末 PE(TTM)，逐点照抄即可"
                     "（禁手估；亏损期缺 PE 属正常断线，无需补齐）；"
                     "港股或数据确实不可得时请在图注/正文注明口径")


def _check_review_miss_diagnostics(fill: dict, warns: list) -> None:
    """复盘「未命中」判定缺诊断方向告警（v4.9，backtest.md 6.6 复盘纪律）：
    review_html 含「未命中」但未提「规律/反例」——未命中的旧假设必须写明是规律失效还是
    新反例（区分假设本身错 vs 触发条件变化），否则教训无法沉淀。"""
    rv = fill.get("review_html") or ""
    if "未命中" in rv and "规律" not in rv and "反例" not in rv:
        warns.append("review_html 含「未命中」判定但未提「规律/反例」：判定未命中的旧假设应写明"
                     "是规律失效还是本次反例（区分假设本身错 vs 触发条件变化），见 backtest.md 6.6 复盘纪律")


def _disp_w(s: str) -> int:
    """显示宽度：CJK/全角计 2、ASCII 计 1——槽位契约的宽度口径（纯字符数对中英混排
    过紧：「PE 25x→17.2x」26 字符实际只占 ~36 宽，单行可读）。"""
    return sum(2 if ord(c) > 0x2E7F else 1 for c in s)


def _check_slot_widths(fill: dict, warns: list) -> None:
    """v5.1.2：槽位契约补闸——scenario.trigger ≤15 字 / drivers.chips 档值 ≤12 字
    （fill-schema 槽位契约表早已声明，此前无检查；工行 24 字 trigger 撑爆表格实证可复发）。"""
    for s in (fill.get("valuation") or {}).get("scenarios") or []:
        if not isinstance(s, dict):
            continue
        trg = str(s.get("trigger") or "").strip()
        if len(trg) > 15:
            warns.append(f"scenario[{s.get('key')}] trigger {len(trg)} 字 > 15（槽位契约：短语——"
                         "三情景表触发条件行随列右对齐，长句换行难看，工行 24 字实证）")
    for d in fill.get("drivers") or []:
        if not isinstance(d, dict):
            continue
        tag = _plain_text(str(d.get("name") or "")).strip() or "?"
        for c in d.get("chips") or []:
            if isinstance(c, dict) and not c.get("unit") and len(str(c.get("value") or "")) > 12:
                warns.append(f"drivers[{tag[:8]}] chips 档值「{c.get('value')}」> 12 字"
                             "（槽位契约：三情景锚短值）")


def _check_threshold_coverage(fill: dict, warns: list) -> None:
    """v5.1.2：4.3 护城河压力测试给出的阈值须在 14 章 triggers/dash_html 有对应行
    （fill-schema 既定「给了阈值的 14 章必须有对应行，否则删阈值句」——此前只写在文档里）。
    4.3 dim-block 内阈值数字串在 triggers+dash_html 找不到 → 告警；年/季度语境不视为阈值。"""
    l1 = fill.get("l1_html") or ""
    m43 = re.search(r"dim-name[^>]*>\s*4\.3", l1)
    if not m43:
        return
    nxt = re.search(r"dim-name", l1[m43.end():])
    block = l1[m43.start(): m43.end() + (nxt.start() if nxt else len(l1))]
    targets = str(fill.get("triggers") or "") + (fill.get("dash_html") or "")
    missing = []
    for mm in re.finditer(
            r"(?:≥|≤|大于|小于|跌破|突破|升至|降至|超过|低于|高于|超)\s*(\d+(?:\.\d+)?)"
            r"\s*(%|pct|亿|元|万户|万人|倍|x)?", block):
        year_context = re.match(r"(?:年|[Qq][1-4](?!\d))", block[mm.end():].lstrip())
        if mm.group(2) is None and re.fullmatch(r"(?:19|20)\d{2}", mm.group(1)) and year_context:
            continue
        if not re.search(r"(?<![\d.])" + re.escape(mm.group(1)) + r"(?![\d.])", targets):
            missing.append(mm.group(0).strip())
    if missing:
        warns.append(f"4.3 压力测试阈值 {sorted(set(missing))[:4]} 在 14 章 triggers/dash_html "
                     "无对应行：给了阈值的必须在 14 章可跟踪，否则删阈值句"
                     "（fill-schema 既定，v5.1.2 起告警）")


def _check_driver_cards(fill: dict, warns: list) -> None:
    """v4.11.3：P0 驱动卡字段校验（drivers/driver_verdict，软告警迁移期——缺失不拒）。
    drivers 1-2 项、chips 恰 悲观/基础/乐观 三情景档（+可选 unit）、name ≤12 字、
    note 显示宽 ≤300（≈3 行；宁德时代融合版备注 137 字实测可读，原 90 字过紧
    已放宽——宽度口径：CJK 计 2、ASCII 计 1）；
    v5.1.1：第一变量改由脚本按 sensitivity |impact| 降序加冕（与龙卷风图同源，
    charts_base._first_var_name；影石创新驱动卡手标与排序图各执一词、校验比数组
    第 0 项放过矛盾实证）——sensitivity 有有效行时首行无同名驱动卡 → 拒渲染，
    手标 first_var 与加冕不一致 → 告警（手标忽略）；sensitivity 缺失时回退手标、仍须恰 1 个；
    p0_html 仍手写「为什么…第一变量」info-card → 重复告警。"""
    drivers = [d for d in fill.get("drivers") or [] if isinstance(d, dict)]
    if not drivers:
        warns.append("drivers 字段未填：v4.11.3 起 P0 驱动卡由 drivers/driver_verdict 字段承载"
                     "（1-2 个关键驱动：name/elastic/note/chips 三情景锚；p0_html 不再手写"
                     "「为什么 X 是第一变量」info-card——判词由 driver_verdict 承载）")
        return
    if len(drivers) > 2:
        warns.append(f"drivers 共 {len(drivers)} 项（应 1-2 个）：只保留对利润弹性最大的 1-2 个驱动")
    firsts = [d for d in drivers if d.get("first_var")]
    for d in drivers:
        tag = _plain_text(str(d.get("name") or "")).strip() or "?"
        short = tag[:8] + ("…" if len(tag) > 8 else "")
        if len(tag) > 12:
            warns.append(f"drivers[{short}] name {len(tag)} 字 > 12（槽位契约：变量名只放一个概念，"
                         "驱动因素写 note 不进名字）")
        note_w = _disp_w(_plain_text(str(d.get("note") or "")).strip())
        if note_w > 300:
            warns.append(f"drivers[{short}] note 显示宽 {note_w} > 300（槽位契约：≈3 行上限，"
                         "当前值+撕扯力量压缩表述，展开论证住正文）")
        scen = [c for c in d.get("chips") or []
                if isinstance(c, dict) and not c.get("unit")]
        labels = [str(c.get("label") or "").strip() for c in scen]
        if labels != ["悲观", "基础", "乐观"]:
            warns.append(f"drivers[{short}] chips 情景档为 {labels}（应恰为 悲观/基础/乐观 三档，"
                         "+可选 unit 标签）")
    if not str(fill.get("driver_verdict") or "").strip():
        warns.append("driver_verdict 未填：「为什么 X 是第一变量」判词缺失"
                     "（弹性对比+不确定性不对称一句，卡下横条承载）")
    sens_items = _sensitivity_items(fill)
    if sens_items:
        crowned = sens_items[0]["name"]
        ck = _var_key(crowned)
        if not any(_var_key(d.get("name")) == ck for d in drivers):
            raise ValueError(
                f"sensitivity 首行（|impact| 降序）「{crowned}」在 drivers 中无同名驱动卡："
                "第一变量必须是 1-2 张驱动卡之一（v5.1.1 起拒渲染——驱动卡角标与龙卷风图"
                "由脚本同源加冕；对齐变量名或修正 impact 后重渲）")
        for d in firsts:
            if _var_key(d.get("name")) != ck:
                warns.append(f"drivers 手标 first_var「{d.get('name')}」与 sensitivity 首行（|impact| 降序）"
                             f"「{crowned}」不一致：v5.1.1 起第一变量由脚本按 sensitivity 加冕，"
                             "手标忽略（可删 first_var 键）")
    elif len(firsts) != 1:
        warns.append(f"drivers 的 first_var 应恰为 1 个（当前 {len(firsts)} 个）：第一变量只有一个"
                     "（sensitivity 缺失时角标与判词前缀仍由手标承载）")
    if re.search(r'<div class="info-card"><strong>为什么', fill.get("p0_html") or ""):
        warns.append("p0_html 仍含手写「为什么…」info-card：v4.11.3 起由 driver_verdict 判词横条承载，"
                     "请删除手写块（drivers 已填）")


def _check_sensitivity_units(fill: dict, warns: list) -> None:
    """v5.1.1：sensitivity.delta 量纲规范——变量自身变动幅度必须带单位：比例写 ±10%、
    百分点写 ±1pct（毛利率/利差类变量的变动是百分点，与脚本按 impact 生成的净利影响 %
    区分；影石创新报告同屏混排 1pct 与 20%、读者无从分辨两种量纲实证）。delta 非空但
    不合规 → 告警。"""
    for s in _sensitivity_items(fill):
        d = s["delta"]
        if d and not re.fullmatch(r"±?\d+(\.\d+)?([~–-]\d+(\.\d+)?)?(pct|%)", d.replace(" ", "")):
            warns.append(f"sensitivity[{s['name'][:8]}] delta「{d}」量纲不规范：变动幅度须带单位——"
                         "比例写 ±10%、百分点写 ±1pct（条端/坐标轴的净利影响 % 由脚本按 impact 生成）")


def _big_segments(fill: dict) -> list:
    """segments 大分部（v5.5.0 B4）：gp_pct 可解析且 ≥15 的项 → [(分部名, gp_pct)]。
    gp_pct 缺失/不可解析的项跳过（口径=毛利占比，与 segments 利润口径同源）——
    缺行名单由 _check_sensitivity_coverage 单独软告警（摘除 gp_pct 可能绕过覆盖闸；
    公开披露确无毛利口径时保留收入行并留空，不得为消告警删行）。"""
    out = []
    for it in (fill.get("segments") or {}).get("items") or []:
        if not isinstance(it, dict):
            continue
        nm = str(it.get("name") or "").strip()
        gp = _num(it.get("gp_pct"))
        if nm and gp is not None and gp >= 15:
            out.append((nm, gp))
    return out


def _check_sensitivity_coverage(fill: dict, warns: list) -> None:
    """v5.5.0 B4：sensitivity 业务线覆盖硬闸（拒渲染）——利润池里的大分部（gp_pct ≥15）
    必须逐条落 `sensitivity_meta.coverage`：补变量（`var`，须与 sensitivity 变量名同源）
    或写好带数字的排除理由（`excluded`）。
    漏圈实证：小米 61% 毛利池（互联网服务+IoT）无变量、三花汽零 37.5% 被一句话打包、
    格林美第三大利润源无变量（27 份存量 fill 平均只圈 3 个变量）。
    跳过口径：segments 缺失/无大分部 → 硬闸整条跳过；gp_pct 缺失的分部不参与——但**只要
    segments.items 非空就有行缺 gp_pct，一律软告警**（缺失可能绕过覆盖闸，缺行不得静默；
    公开披露确无毛利口径时保留收入行并留空，不得为消告警删行）。"""
    seg_items = [it for it in (fill.get("segments") or {}).get("items") or [] if isinstance(it, dict)]
    no_gp = [str(it.get("name") or "").strip() or "（未命名）" for it in seg_items
             if _num(it.get("gp_pct")) is None]
    if no_gp:
        head = "、".join(no_gp[:5]) + ("…" if len(no_gp) > 5 else "")
        warns.append(f"segments 有 {len(no_gp)} 行缺 gp_pct（{head}）：覆盖闸只对 gp_pct 可解析且 "
                     "≥15 的分部生效——缺 gp_pct 可能绕过覆盖闸，请补毛利占比（E6 回填）；"
                     "若该分部确无公开毛利口径，保留该行、毛利留空，并在 segments.note 写明原因"
                     "（v5.5.0 B4）")
    big = _big_segments(fill)
    if not big:
        return
    meta = fill.get("sensitivity_meta")
    cov_raw = meta.get("coverage") if isinstance(meta, dict) else None
    cov = [c for c in (cov_raw or []) if isinstance(c, dict)] if isinstance(cov_raw, list) else []
    sens = {_var_key(s["name"]): s["name"] for s in _sensitivity_items(fill)}
    if not sens:
        # sensitivity 全缺 → coverage 的 var 无从映射（有大分部就必须有 sensitivity+coverage）
        raise ValueError("sensitivity 字段缺失或无可解析行，但 segments 存在大分部（"
                         + "、".join(f"{n} gp {g:g}%" for n, g in big)
                         + "）：估值敏感性与业务线覆盖是同一件事的两面——大分部必须落到 sensitivity"
                           "（≥1 个变量）并在 sensitivity_meta.coverage 逐条登记"
                           "（var 补变量 / excluded 写带数字的排除理由），否则利润池的最大块没有敏感性读数"
                           "（v5.5.0 B4）")
    cov_by_seg = {}
    for c in cov:
        cov_by_seg.setdefault(_var_key(c.get("segment")), c)
    # ① 大分部未登记 → 拒
    missing = [(n, g) for n, g in big if _var_key(n) not in cov_by_seg]
    if missing:
        detail = "、".join(f"{n}（毛利占比 {g:g}%）" for n, g in missing)
        raise ValueError(f"sensitivity_meta.coverage 未覆盖大分部：{detail}——利润池 ≥15% 的分部"
                         f"必须逐条登记：补变量 `{{\"segment\":\"…\",\"var\":\"…\"}}`（var 须与 "
                         f"sensitivity 的 name 一致）或写带数字的排除理由 "
                         f"`{{\"segment\":\"…\",\"excluded\":\"±X% → 净利 ±Y%，不足以改变情景结论\"}}`"
                         f"（v5.5.0 B4 拒渲染；若该分部口径不该拆，请修 segments 后再渲）")
    # ② 条目本身：var/excluded 恰居其一 + var 非瞎指 + excluded 带数字
    for c in cov:
        seg_nm = str(c.get("segment") or "").strip() or "（未命名分部）"
        has_var = bool(str(c.get("var") or "").strip())
        has_ex = bool(str(c.get("excluded") or "").strip())
        if has_var == has_ex:
            raise ValueError(f"sensitivity_meta.coverage[{seg_nm}] 的 var 与 excluded "
                             f"{'双填' if has_var else '双缺'}：二者恰居其一——补变量用 var，"
                             f"排除用 excluded（写带数字的理由）（v5.5.0 B4 拒渲染）")
        if has_var and _var_key(c.get("var")) not in sens:
            raise ValueError(f"sensitivity_meta.coverage[{seg_nm}].var「{c.get('var')}」"
                             f"不在 sensitivity 变量集合（现有："
                             f"{'/'.join(sens.values()) or '空'}）：coverage 只能指向已入图的变量，"
                             f"瞎指等于把分部挂到不存在的读数上（v5.5.0 B4 拒渲染）")
        if has_ex and not re.search(r"\d", str(c.get("excluded"))):
            raise ValueError(f"sensitivity_meta.coverage[{seg_nm}].excluded 无数字："
                             f"排除理由必须带量级（如「±10% 收入 → 净利 ±3%，不足以改变情景结论」）"
                             f"——「影响不大」类定性说法等于没排除（v5.5.0 B4 拒渲染）")
    # ③ 引用了不存在的分部名 → 软告警（登记方向错误）
    seg_names = {_var_key(it.get("name")) for it in (fill.get("segments") or {}).get("items") or []
                 if isinstance(it, dict)}
    ghosts = [str(c.get("segment") or "").strip() for c in cov
              if _var_key(c.get("segment")) and _var_key(c.get("segment")) not in seg_names]
    if ghosts:
        warns.append(f"sensitivity_meta.coverage 引用了 segments 中不存在的分部：{'、'.join(ghosts)}"
                     f"——coverage 的 segment 名须与 segments.items[].name 同源（v5.5.0 B4）")


def _parse_pe_range(text):
    """cycle_stages.pe 声明区间解析：「60–216x」/「10-16」/「12x」→ (低, 高)（容 en dash/
    连字符/波浪号）；单值 → (v, v)；无数字 → None。先剔除四位年份——「2021 年 60x」
    的 2021 不是区间端点（热核审计 P2）。"""
    text = re.sub(r"(?:19|20)\d{2}", " ", str(text or ""))
    vals = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)[:2]]
    if not vals:
        return None
    return (vals[0], vals[0]) if len(vals) == 1 else (min(vals), max(vals))


def _series_month_pe(series):
    """price_history.series → [(年, 月, pe)]（m 可解析「YYYY-MM」才入列；pe 缺失记 None）。"""
    out = []
    for p in series or []:
        if not isinstance(p, dict):
            continue
        m = str(p.get("m") or "").strip()
        if len(m) >= 7 and m[:4].isdigit() and m[5:7].isdigit():
            out.append((int(m[:4]), int(m[5:7]), _num(p.get("pe"))))
    return out


def _check_cycle_stages(fill: dict, warns: list) -> None:
    """v4.11.3：周期阶段卡字段校验（cycle_stages，软告警迁移期——缺失不拒）。
    3-6 项、name ≤8 字、driver 显示宽 ≤48（灭孤字契约；宽度口径：CJK 计 2、ASCII 计 1）、
    period 必填；
    v5.1.2：条数/本轮判定与渲染同源——渲染跳过缺 name/period 的项
    （charts_misc.build_cycle_stages），被跳过的项单独告警不落图；
    current 恰 1 个升级为拒渲染（0 或 ≥2 个「本轮」徽章同屏即事实矛盾；
    本轮由分析师划段标注，脚本不加冕）；字段已填而 cycle_html 缺失的绑定告警与 pe_history
    同款，已迁 _check_ch11_binding 表驱动（v5.8.2）；
    cycle_html 手写阶段表与字段的关系：字段未填 → 迁移告警；并存 → 重复告警；
    v5.1.3：period 格式校验——解析不出起止月份软告警「季K图阶段分界不落该段」
    （格式 YYYY/MM–YYYY/MM；与渲染同源 parse_stage_period，单源防漂移）；
    v5.4.0：校准锚（calib）三校验（全部软告警）——①calib:true 项须含 similarity/discount；
    ②分型属四型（周期/稳定价值/困境反转/成长·中速层）时 calib 项须 ≥2（v5.4.1 起含 0 个：
    0 个走「未标注校准锚（calib）」专用文案，非四型不告警）；
    ③窗口内对账：calib 时段落在 price_history 月份窗口内 → 窗口实测 PE 极值与声明区间
    端点比对（相对偏差 >25% 告警），窗口外/序列无 pe 跳过，全部未核验 → 汇总告警一条。"""
    stages = [s for s in fill.get("cycle_stages") or [] if isinstance(s, dict)]
    hand_table = re.search(r"<th[^>]*>\s*阶段\s*</th>", fill.get("cycle_html") or "")
    if not stages:
        if hand_table:
            warns.append("cycle_html 含手写阶段拆解表：v4.11.3 起请迁移 cycle_stages 字段"
                         "（name/period/pe/price/driver 显示宽 ≤48/current 恰 1 个），手写表格写法废止")
        return
    valid = [s for s in stages
             if str(s.get("name") or "").strip() and str(s.get("period") or "").strip()]
    for s in stages:
        if str(s.get("name") or "").strip() and str(s.get("period") or "").strip():
            continue
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        warns.append(f"cycle_stages[{tag[:6]}] 缺 name 或 period：该项不落图（渲染跳过、"
                     "序号按落图项重排），请补齐或删除")
    if not valid:
        warns.append("cycle_stages 全部项缺 name 或 period：无一落图（渲染整体跳过），"
                     "请补齐或整字段删除（热核审计：此时 current 计数无意义，不硬拒）")
        if hand_table:
            warns.append("cycle_html 手写阶段表与 cycle_stages 字段并存（内容重复）：请删除手写表格")
        return
    if not 3 <= len(valid) <= 6:
        warns.append(f"cycle_stages 有效项 {len(valid)} 个（应 3-6 个阶段；缺 name/period 的项不落图）")
    curs = [s for s in valid if s.get("current")]
    if len(curs) != 1:
        raise ValueError(f"cycle_stages 的 current 应恰为 1 个（有效项中当前 {len(curs)} 个）："
                         "「本轮」只有一个——0 个或 2 个以上徽章同屏即事实矛盾（v5.1.2 起拒渲染）")
    for s in stages:
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        short = tag[:6] + ("…" if len(tag) > 6 else "")
        period = str(s.get("period") or "").strip()
        if period and parse_stage_period(period) is None:
            warns.append(f"cycle_stages[{short}] period「{period[:14]}」解析不出起止月份："
                         "季K图阶段分界不落该段（格式 YYYY/MM–YYYY/MM）")
        if len(tag) > 8:
            warns.append(f"cycle_stages[{short}] name {len(tag)} 字 > 8（槽位契约）")
        driver_w = _disp_w(_plain_text(str(s.get("driver") or "")).strip())
        if driver_w > 48:
            warns.append(f"cycle_stages[{short}] driver 显示宽 {driver_w} > 48（槽位契约：超长必孤字折行，"
                         "压缩表述——demo 阶段 02「杀」字独占行实证；宽度口径：CJK 计 2、ASCII 计 1）")
    # cycle_stages 与第 11 章绑定 → 迁 _check_ch11_binding 表驱动（v5.8.2）
    if hand_table:
        warns.append("cycle_html 手写阶段表与 cycle_stages 字段并存（内容重复）：请删除手写表格")
    # v5.4.0 校准锚（calib）三校验（全部软告警；非四型 / 无有效项不受影响）
    calibs = [s for s in valid if s.get("calib")]
    for s in calibs:
        tag = _plain_text(str(s.get("name") or "")).strip() or "?"
        short = tag[:6] + ("…" if len(tag) > 6 else "")
        miss_keys = [k for k in ("similarity", "discount") if not str(s.get(k) or "").strip()]
        if miss_keys:
            warns.append(f"cycle_stages[{short}] calib:true 缺 {'/'.join(miss_keys)}：校准时段须写明"
                         "与当前时段的相似性（similarity：增速/规模/宏观背景）与规模折价（discount："
                         "当前利润更大时 PE 应更低）——否则「为何拿这几段校准」无据（v5.4.0 软约束）")
    # v5.4.1：四型零标记不再静默豁免（一个 calib 都不标 = 软约束失去观察意义）
    if _anchor_unanchored_type(fill) and len(calibs) < 2 and not _cycle_anchor_fallback_documented(fill):
        if calibs:
            warns.append(f"cycle_stages 校准锚（calib:true）仅 {len(calibs)} 个（应 ≥2）：估值带校准"
                         "依赖 ≥2 个可比历史时段（scoring.md「三情景构建」PE 时段匹配）——"
                         "请在阶段卡标注 ≥2 个 calib 时段（首版软约束，观察一轮后升拒渲染）")
        else:
            warns.append("cycle_stages 未标注校准锚（calib）：本分型（估值带依赖历史 PE 时段锚）"
                         "的估值带须有 ≥2 个校准时段——在对应阶段加 \"calib\":true 并写 "
                         "similarity/discount（渲染「校准锚」角标；首版软约束，观察一轮后升拒渲染）")
    if calibs:
        pts = _series_month_pe((fill.get("price_history") or {}).get("series"))
        verified = 0
        for s in calibs:
            span = parse_stage_period(str(s.get("period") or "").strip())
            if span is None or not pts:
                continue   # period 解析失败已单独告警；无序列无从对账
            (y0, m0), (y1, m1) = span
            if (y1, m1) == (9999, 12):   # 「至今」开口 → 夹取到序列末月（与渲染同源规则）
                y1, m1 = max((y, m) for y, m, _pe in pts)
            inwin = [pe for y, m, pe in pts if (y0, m0) <= (y, m) <= (y1, m1)]
            pes = [pe for pe in inwin if pe is not None]
            dec = _parse_pe_range(s.get("pe"))
            if not inwin or not pes or dec is None:
                continue   # 窗口外 / 序列无 pe / 未写 PE 区间 → 跳过（不计入已核验）
            verified += 1
            lo, hi = dec
            bad = []
            if lo and abs(min(pes) - lo) / lo > 0.25:
                bad.append(f"下限 {lo:g}x vs 实测最低 {min(pes):g}x")
            if hi and abs(max(pes) - hi) / hi > 0.25:
                bad.append(f"上限 {hi:g}x vs 实测最高 {max(pes):g}x")
            if bad:
                tag = _plain_text(str(s.get("name") or "")).strip() or "?"
                short = tag[:6] + ("…" if len(tag) > 6 else "")
                warns.append(f"cycle_stages[{short}] calib 时段 PE 声明与 price_history 同窗口实测"
                             f"端点偏差 >25%（{'；'.join(bad)}）：校准时段声明须与取数窗口同源"
                             f"（E2 月线月末 PE）——请核对阶段 pe 或校准时段划段")
        if not verified:
            warns.append("cycle_stages 的 calib 时段均在取数窗口外（或窗口内无 PE 序列/未写 PE 区间）："
                         "校准声明未核验——请核对 price_history.series 的月份覆盖与阶段 pe 声明")


def _check_cycle_position(fill: dict, warns: list) -> None:
    """v5.2.0：当前周期位置刻度条（cycle_position，首版软告警——观察一轮后再升拒渲染）。
    周期股（stock_type 含「周期」）且 cycle_html 存在 → 字段必答且五键齐全
    （stage/price_pctile/capacity/stock_spread/implication——「上行期」无刻度的云铝实证）；
    stage 与 cycle_stages 本轮项不一致 → 告警（当前阶段只许一个说法）。"""
    cp = fill.get("cycle_position")
    is_cyc = "周期" in str(fill.get("stock_type") or "")
    has_cycle_html = bool(str(fill.get("cycle_html") or "").strip())
    if not isinstance(cp, dict) or not cp:
        if is_cyc and has_cycle_html:
            warns.append("cycle_position 未填：周期股当前位置刻度条为必答（v5.2.0）——五键："
                         "stage/price_pctile/capacity/stock_spread/implication；"
                         "首版软约束，下轮升拒渲染")
        return
    for k in ("stage", "price_pctile", "capacity", "stock_spread", "implication"):
        if not str(cp.get(k) or "").strip():
            warns.append(f"cycle_position.{k} 缺失：阶段名 + 三件套刻度 + 位置含义句须五键齐全")
    curs = [s for s in (fill.get("cycle_stages") or [])
            if isinstance(s, dict) and s.get("current")
            # 与 _check_cycle_stages/渲染同源：缺 name/period 的项不落图，不参与本轮比对
            and str(s.get("name") or "").strip() and str(s.get("period") or "").strip()]
    stage = str(cp.get("stage") or "").strip()
    if curs and stage:
        cur_name = _plain_text(str(curs[0].get("name") or "")).strip()
        if cur_name and cur_name not in stage and stage not in cur_name:
            warns.append(f"cycle_position.stage「{stage[:12]}」与 cycle_stages 本轮「{cur_name[:12]}」"
                         "不一致：当前阶段只许一个说法")


def _check_earnings_stability(fill: dict, warns: list) -> None:
    """盈利波动性软锚：优先对 quote 落盘的全精度 σ；旧 quote 才按展示柱复算。"""
    es = fill.get("earnings_stability")
    if not isinstance(es, dict) or not es:
        return
    sig = _num(es.get("sigma"))
    if sig is None:
        warns.append("earnings_stability.sigma 缺失或非数字：照抄 E3「扣非增速波动」行"
                     "（E3 行标「不适用/数据不足」时整字段勿填）")
        return
    if not str(es.get("verdict") or "").strip():
        warns.append("earnings_stability.verdict 缺失：4.6 判词引用处须有一句定性结论")
    quote_es = (_quote_ref(fill) or {}).get("earnings_stability") or {}
    ref = _num(quote_es.get("sigma"))
    if ref is not None:
        if abs(ref - sig) > 0.15:
            warns.append(f"earnings_stability.sigma（{sig:g}）与 quote 落盘 σ"
                         f"（{ref:g}）偏差 >0.15pct：照抄 E3 行，禁手算")
        return
    ft = fill.get("fin_trend") or {}
    dedt_bar = next((b for p in ft.get("panels") or [] if isinstance(p, dict)
                     for b in p.get("bars") or []
                     if isinstance(b, dict) and "扣非" in str(b.get("name") or "")), None)
    if dedt_bar is None:
        warns.append("earnings_stability 已填但 fin_trend 无扣非柱可复算：请人工核对 E3 行照抄值")
        return
    ref, n_g, _drop = growth_sigma(dedt_bar.get("values"))
    if ref is None:
        warns.append("earnings_stability 已填但 fin_trend 扣非柱复算不可用（增速点 <3 或亏损基数）："
                     "请人工核对 E3 行照抄值")
    elif abs(ref - sig) > 0.15:
        warns.append(f"earnings_stability.sigma（{sig:g}）与 fin_trend 扣非柱复算 σ"
                     f"（{ref:g}，{n_g} 个增速点）偏差 >0.15pct：照抄 E3 行，禁手算")
