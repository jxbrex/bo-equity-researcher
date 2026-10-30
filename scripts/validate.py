#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate.py — fill 内容校验调度入口。

五个 validate_* 域模块只依赖 validate_common 与各自的上游工具；
本文件只按固定顺序调用域校验，不再持有公共工具或兼容再导出层。
"""
import sys


# 域校验导入；实际调用顺序见 _validate_content_impl，逐字不变。

from validate_audit import (
    _check_price_date,
    _check_quote_consistency,
    _check_score_ranges,
    _check_timing_facts,
    _check_gap_plot,
    _check_gap_plot_street_source,
    _check_gap_history,
    _check_dupont,
    _check_consensus_np,
    _check_growth_consistency,
    _check_quote_present,
    _check_quality_inputs,
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
    _check_research_actions,
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
from validate_typing import _check_typing_v2
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
    _check_timing_facts(fill, warns)

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
    _check_research_actions(fill, warns)
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


def validate_content(fill: dict, calc: dict = None, sc: dict = None) -> list:
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
    return warns
