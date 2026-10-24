#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — fill 内容校验总入口（v5.8.3 起为薄入口 + 跨域公共层）

v5.8.3 按域拆分为 validate_audit / validate_valuation / validate_html /
validate_typing / validate_charts 五个域模块（纯搬迁，零行为变化）：
本文件保留 validate_content/_validate_content_impl 调度清单（调用顺序逐字不变）、
跨域共用的公共 helper（下方）与全部 re-export——render_report 与测试的既有
import 路径零改动可用。

内容：全部 _check_* 硬校验与告警项、validate_content 总开关。
只依赖 scoring/charts_base 的常量与工具，不依赖主模块运行时状态；
告警直接打印 stderr（与拆分前行为一致）。
v4.10.2 归位出清：_tag_timing_table → align_fix.py；_check_l4_order/build_prev_strip
→ render_report.py（前者被 render 单点调用，后者为 Hero 片段构建，均非本模块校验职责）。
"""
import json
import re
import sys

from charts_gap import _gh_sort_key  # v5.8.2 同源 import：漏抄判定排序口径与渲染端单源

# ============================================================================
# 跨域公共层（被 ≥2 个域模块消费；单域 helper 随各域模块搬迁，见各模块 docstring）
# ============================================================================

# 正文 HTML 字段全集（写作纪律/代号泄漏/.rev 高亮检查用）
_HTML_FIELDS = ("thesis_html", "conclusion_html", "p0_html", "l1_html", "l3_html", "l4_html",
                "valuation_html", "gap_html", "peers_html", "dash_html", "position_html", "review_html")


# 可含数据表的章节字段（source 来源标注检查用；thesis 不含表，剔除）
_HTML_TABLE_FIELDS = _HTML_FIELDS[1:]


# 分型判据 v2（v5.3.0）常量表——判据全文见 scoring.md「分型判据（v2）」节
_TYPE_ALIASES = [  # 顺序敏感：先具体后笼统（「稳定价值」先于「成长」，「稳健/快速成长」先于裸「成长」）
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
    """港股判定单源（v5.5.1 收口，此前 `re.fullmatch(r"\\d{5}", …)` 散三处）：
    fill.code 为 5 位数字即港股（A 股/北交所/指数为 6 位或 4 位，不命中）。
    消费点：period_track 硬拒文案、gap_plot street 无落盘源门、cagr_adjustments 例外。"""
    return bool(re.fullmatch(r"\d{5}", str(fill.get("code") or "").strip()))


def _quote_ref(fill: dict):
    """读 quote.source_file 落盘 JSON（各照抄/对账校验共用入口，v5.1.2）；未声明/读不到 → None。
    quote 防伪主校验（_check_quote_consistency）读不到会拒渲染，这里只做降级返回。"""
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
    """v5.8.2：按 key 取情景（大小写不敏感比较，返回匹配 dict 或 None）。
    校验端对 key 一律 .lower() 归一（_check_valuation_scenarios / compute_valuation 同规），
    但存量 fill 可能写大写 "Base"（_archive 旧档，硬拒会破坏旧 fill 重渲）——对账取数
    不得因大小写静默跳过，统一经本 helper 取情景，五处对账口径一致。"""
    k = str(key or "").lower()
    for s in scenarios or []:
        if isinstance(s, dict) and str(s.get("key") or "").lower() == k:
            return s
    return None


def _normalize_stock_type(st):
    """stock_type 自由文本 → (标准型, 默认成长层, legacy 旧名)；无法映射 → (None, None, None)。"""
    st = str(st or "")
    for kw, std, tier in _TYPE_ALIASES:
        if kw in st:
            legacy = st if (std == "成长型" and kw in ("稳健成长", "快速成长")) else None
            return std, tier, legacy
    return None, None, None


def _resolve_type_tier(fill: dict, warns: list = None):
    """标准分型 + 生效成长层解析单源（v5.8.2，typing_v2/ pe_history 禁填/ dcf 三处复制收敛）。
    返回 (std, tier, legacy)：growth_tier 合法值（high/mid）只在「成长型」下覆盖别名默认层
    （与 typing_v2 原口径一致；另两处只消费「是否 high」判定，非成长型的层值无消费点）。
    成长型缺 tier 分两口径：warns 非空 → 告警并按 mid 处理（typing_v2）；
    warns 为 None → 静默按 mid 兜底（另两处原为 None，「== high」/「!= high」判定等价）。"""
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
    """估值带依赖历史 PE 时段锚的四型（v5.4.0 单源判定，校验盲飞与 calib 时段数共用）：
    周期股 / 稳定价值 / 困境反转 / 成长型·中速层（growth_tier ≠ high）。
    成熟·停滞走 PE 绝对带 + 股息率锚、未盈利·管线走 rNPV/P/S，不在此列。"""
    st = str(fill.get("stock_type") or "")
    if any(k in st for k in ("周期", "稳定价值", "困境反转")):
        return True
    return "成长" in st and str(fill.get("growth_tier") or "").strip().lower() != "high"


# ============================================================================
# 域模块 re-export（import 即再导出；调用顺序见 _validate_content_impl，逐字不变）
# ============================================================================

from validate_audit import (
    _check_price_date,
    _check_quote_consistency,
    _check_score_ranges,
    _check_gap_plot,
    _check_gap_plot_street_source,
    _check_gap_history,
    _check_dupont,
    _check_consensus_np,
    _check_growth_consistency,
    _check_quote_present,
    _check_quality_inputs,
    _PERIOD_LABEL_KEYS,
    _PERIOD_NUM_KEYS,
    _PERIOD_YOY_KEYS,
    _PERIOD_BAND_KEYS,
    _check_period_track)
from validate_valuation import (
    _check_valuation_inputs,
    _check_valuation_scenarios,
    _check_odds_floor,
    _check_anchor_discipline,
    _check_anchor_blind_fly,
    _check_thesis_consistency,
    _check_hero_cross,
    _check_hero_band_claims,
    _check_dcf)
from validate_html import (
    _check_red_flag_breaker,
    _check_content_floor,
    _check_thesis_price_tags,
    _check_thesis_info_floor,
    _check_peers_plot_target,
    _check_peers_selection,
    _check_timing_table_cells,
    _check_v2_counter_evidence,
    _check_dim_blocks,
    _check_internal_codes,
    _check_writing_discipline,
    _check_required_fields,
    _check_conclusion_structure,
    _check_governance_strip,
    _check_peers_orientation,
    _check_peers_bestworst,
    _check_peers_column_support,
    _check_l4_form,
    _check_cn_placeholder,
    _check_red_flag_conclusion,
    _check_handwritten_dupes)
from validate_typing import (
    _hist_cagr,
    _check_typing_v2)
from validate_charts import (
    _check_chart_fields,
    _check_ch11_binding,
    _check_prev_fields,
    _check_prev_charts,
    _check_optional_charts,
    _check_price_history_pe,
    _check_review_miss_diagnostics,
    _check_slot_widths,
    _check_threshold_coverage,
    _check_driver_cards,
    _check_sensitivity_units,
    _check_sensitivity_coverage,
    _check_cycle_stages,
    _check_cycle_position,
    _check_earnings_stability)


def _validate_content_impl(fill: dict, calc: dict, warns: list, sc: dict = None) -> None:
    """validate_content 的执行主体（拆出是为了硬拒前 flush 告警，见包装函数）。"""
    _check_price_date(fill)
    _check_quote_consistency(fill, warns)
    _check_score_ranges(fill)

    _check_valuation_inputs(fill)
    _check_valuation_scenarios(fill, warns)
    _check_odds_floor(fill, warns, calc)  # v5.0 机制三：赔率 ∞ 须配悲观地板证据（floor）
    _check_consensus_np(fill, warns)    # v5.0 机制二：乐观税一致预期照抄交叉校验
    _check_anchor_discipline(fill, warns)  # v5.1.0 估值锚纪律：增量证据锁死+回滚条款前置（v5.4.0 双尺）
    _check_anchor_blind_fly(fill, warns)   # v5.4.0：无历史分位可对账 → 校验盲飞告警
    _check_chart_fields(fill)
    _check_quote_present(fill, warns)   # v4.11.1（审核 D5）：date ≥ 2026-09-02 缺 quote 拒渲染
    _check_quality_inputs(fill, warns)  # v2：机械输入双向照抄、profile 与披露日对账
    _check_gap_plot(fill, calc, warns)  # v4.11.1：gap_plot 分布图字段校验（可选字段，缺失不查）
    _check_gap_plot_street_source(fill, warns)  # v5.5.1 F2：street 落盘第二照抄源（软告警）
    _check_gap_history(fill, warns)     # v5.6.0：gap_history 态度变化照抄对账（软告警）
    _check_dupont(fill, warns)          # v5.8.0：dupont 杜邦乘积链照抄对账（软告警）

    _check_red_flag_breaker(fill)
    _check_red_flag_conclusion(fill, sc)  # v5.1.2：红旗 ≥2 项 → 首卡首句存疑句硬门禁
    _check_thesis_consistency(fill, calc)
    _check_content_floor(fill)
    _check_l4_form(fill, warns)
    _check_cn_placeholder(fill)

    _check_typing_v2(fill, warns)
    _check_thesis_price_tags(fill, warns)
    _check_thesis_info_floor(fill, warns)
    _check_hero_band_claims(fill, warns)
    _check_peers_plot_target(fill, warns)
    _check_peers_selection(fill, warns)   # v5.4.0：表图一致（硬）+ 尺子一致/peer≥3/rationale/PE 交叉
    _check_hero_cross(fill, warns)        # v5.1.2：Hero 与估值结构化字段互查
    _check_growth_consistency(fill, warns)  # v5.1.2：growth_plot 换算对账
    _check_timing_table_cells(fill, warns)
    _check_v2_counter_evidence(fill, sc)
    _check_dim_blocks(fill, warns, sc)
    _check_internal_codes(fill, warns)
    _check_ch11_binding(fill, warns)      # v5.8.2 表驱动：pe_history/price_history/cycle_stages 挂第 11 章
    _check_writing_discipline(fill, warns)
    _check_conclusion_structure(fill, warns)
    _check_governance_strip(fill, warns)
    _check_peers_orientation(fill, warns)
    _check_peers_bestworst(fill, warns)
    _check_peers_column_support(fill, warns)
    _check_price_history_pe(fill, warns)
    _check_prev_fields(fill, warns)
    _check_prev_charts(fill, warns)   # v5.5.1 F3：复盘「旧有新无」结构对照（软告警）
    _check_review_miss_diagnostics(fill, warns)
    _check_required_fields(fill, warns)
    _check_optional_charts(fill, warns)
    _check_driver_cards(fill, warns)      # v4.11.3：P0 驱动卡字段（drivers/driver_verdict）
    _check_sensitivity_units(fill, warns)  # v5.1.1：sensitivity.delta 量纲规范
    _check_sensitivity_coverage(fill, warns)  # v5.5.0 B4：大分部（gp_pct ≥15）覆盖硬闸
    _check_slot_widths(fill, warns)       # v5.1.2：槽位契约补闸（trigger/chips 长度）
    _check_handwritten_dupes(fill, warns)  # v5.1.2：手写表与脚本生成并存检测
    _check_threshold_coverage(fill, warns)  # v5.1.2：4.3 阈值 14 章承载
    _check_cycle_stages(fill, warns)      # v4.11.3：周期阶段卡字段（cycle_stages）
    _check_dcf(fill, warns)               # v4.11.3：DCF 双卡字段（dcf）
    _check_cycle_position(fill, warns)    # v5.2.0：当前周期位置刻度条（cycle_position，首版软告警）
    _check_earnings_stability(fill, warns)  # v5.2.0：盈利波动性软锚（sigma 照抄比对，软告警）
    _check_period_track(fill, warns)      # v5.0：3 章 period_track（照抄落盘交叉校验/判词四选一/年报期整章消失）


def validate_content(fill: dict, calc: dict = None, sc: dict = None) -> None:
    """内容级校验（成稿前自动复核，借鉴 equity-research 检查器思路）。
    硬错误（拒渲染）：分数越界、valuation_inputs 缺失、valuation 三情景字段不全、
    fin_trend/growth_plot 必填图字段缺失或结构非法（v4.9）、
    红灯熔断缺"不建议参与"、thesis 手写价与脚本计算值不一致、内容地板（空心章节）、
    表格缺来源标注；其余 → stderr 告警（P1），模型看到即修正。
    calc 为 compute_valuation 结果（thesis 一致性校验用）。
    v4.11.1（热核审计 P2-1）：硬拒前先 flush 已积累告警——否则负 profit/存量 quote 豁免等
    提示会随异常湮灭，模型修 fill 丢上下文。"""
    if sc is None and fill.get("quality_version") == 2:
        from scoring import compute_scores
        sc = compute_scores(fill)
    warns = []
    try:
        _validate_content_impl(fill, calc, warns, sc)
    except ValueError:
        for w in warns:
            print(f"⚠️ 内容校验: {w}", file=sys.stderr)
        raise
    for w in warns:
        print(f"⚠️ 内容校验: {w}", file=sys.stderr)
