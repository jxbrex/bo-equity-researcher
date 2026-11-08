#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_validate.py — render_report 内容校验回归：*_validate 校验组 + sensitivity 业务线覆盖硬闸（B4）域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import re
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import (
    minimal_fill, expect_valueerror, validate_stderr, write_fill,
    _period_ref_file, v2_fill, prepare_v2_quote, render_v2_fill,
)

def test_validate_domain_modules_standalone_import():
    import subprocess

    failures = {}
    scripts_dir = os.path.dirname(os.path.abspath(__file__))
    for name in ("validate_audit", "validate_charts", "validate_html",
                 "validate_typing", "validate_valuation"):
        result = subprocess.run([sys.executable, "-c", f"import {name}"], cwd=scripts_dir,
                                capture_output=True, text=True, encoding="utf-8", errors="replace",
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        if result.returncode:
            failures[name] = (result.stderr or result.stdout).strip().splitlines()[-1]
    assert not failures, failures


def test_validate_warns_reach_stderr():
    """v4.9 validate 告警路径：触发告警的 fill → stderr 有「内容校验」前缀输出。"""
    fill = minimal_fill(subtitle="测试行业 · 报告日期：2026-01-01")
    out = validate_stderr(fill)
    assert "⚠️ 内容校验" in out, "告警路径必须打印到 stderr"
    assert "subtitle 含「报告日期」" in out, "具体告警文案应到达 stderr"


def test_gap_plot_validate():
    """v4.11.1：gap_plot 校验——非法行（缺 name/ours/consensus）拒渲染；
    有效维度 <2 / 同机构多点 / 目标价与脚本中枢失配 → 告警。"""
    f = minimal_fill()
    f["gap_plot"] = {"dims": [{"name": "2026E 归母净利（亿元）", "ours": 110, "consensus": 100}]}
    err = validate_stderr(f)
    assert "有效数值维度仅 1 个" in err, "有效维度 <2 应告警（图不生成）"
    f["gap_plot"] = {"dims": [{"name": "x", "consensus": 100}]}
    expect_valueerror(f, "gap_plot 行缺 ours 应拒渲染")
    f["gap_plot"] = {"dims": [
        {"name": "目标价·12个月（元）", "ours": 30, "consensus": 26,
         "street": [{"org": "野村", "v": 31}, {"org": "野村", "v": 30}]},
        {"name": "2026E 归母净利（亿元）", "ours": 110, "consensus": 100},
        {"name": "废行", "ours": 1, "consensus": 0}]}
    err = validate_stderr(f)
    assert "同机构多点" in err, "street 同机构多点应告警"
    assert "口径须一致" in err, "目标价与 valuation 中枢失配应告警"
    assert "≤0" in err, "consensus ≤0 行剔除应告警"


def test_driver_cards_validate():
    """v4.11.3 驱动卡校验：缺失告警；chips 非三情景档告警；p0_html 手写「为什么…」info-card
    且 drivers 已填 → 重复告警。v5.1.1：第一变量改由脚本按 sensitivity |impact| 降序加冕——
    首行无同名驱动卡 → 拒渲染（原「不同名」告警升级；校验曾比数组第 0 项而图按 impact 排序，
    影石创新矛盾静默穿过实证）；加冕与手标 first_var 不一致 → 告警（手标忽略）。"""
    warns = validate_stderr(minimal_fill())
    assert "drivers 字段未填" in warns
    good_chips = [{"label": "悲观", "value": "1"}, {"label": "基础", "value": "2"},
                  {"label": "乐观", "value": "3"}]
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "金价", "elastic": "x", "chips": [{"label": "高", "value": "1"}]}],
        driver_verdict="v"))
    assert "chips 情景档" in warns
    # 首行无同名卡 → 拒渲染（数组第 0 项同名不算数：按 |impact| 降序首行为准）
    expect_valueerror(minimal_fill(
        drivers=[{"name": "金价", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v", sensitivity=[{"name": "铜价", "impact": 10}]), "首行无同名驱动卡",
        kw="无同名驱动卡")
    expect_valueerror(minimal_fill(
        drivers=[{"name": "毛利率", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v",
        sensitivity=[{"name": "毛利率", "impact": 15}, {"name": "收入增速", "impact": 20}]),
        "数组第 0 项同名但 impact 非最大仍拒", kw="无同名驱动卡")
    # 加冕名在卡中、手标与加冕不一致 → 告警不拒
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "毛利率", "first_var": True, "elastic": "x", "chips": good_chips},
                 {"name": "收入增速", "elastic": "x", "chips": good_chips}],
        driver_verdict="v",
        sensitivity=[{"name": "毛利率", "impact": 15}, {"name": "收入增速", "impact": 20}]))
    assert "手标" in warns and "加冕" in warns
    warns = validate_stderr(minimal_fill(
        p0_html='<div class="info-card"><strong>为什么X是第一变量</strong></div>',
        drivers=[{"name": "金价", "first_var": True, "elastic": "x", "chips": good_chips}],
        driver_verdict="v"))
    assert "info-card" in warns and "为什么" in warns


def test_sensitivity_units_validate():
    """v5.1.1：sensitivity.delta 量纲规范——比例 ±10% / 百分点 ±1pct 合规；裸数字或
    文字单位 → 告警（条端/坐标轴净利影响 % 由脚本按 impact 生成）。"""
    warns = validate_stderr(minimal_fill(sensitivity=[
        {"name": "毛利率", "impact": 15, "delta": "±1pct"},
        {"name": "收入增速", "impact": 20, "delta": "±10%"}]))
    assert "量纲不规范" not in warns
    warns = validate_stderr(minimal_fill(sensitivity=[
        {"name": "毛利率", "impact": 15, "delta": "1个百分点"},
        {"name": "量", "impact": 8, "delta": "10"}]))
    assert warns.count("量纲不规范") == 2


def test_hero_cross_validate():
    """v5.1.2：Hero 与估值结构化字段互查——顶层 pe_ttm vs valuation_inputs.pe_ttm >1% 拒
    （metric_label 豁免）；horizon 不一致告警；mcap vs price×shares >5% 告警；
    Hero ✓ 字段缺失告警；target_sub_html 含具体数字告警。"""
    warns = validate_stderr(minimal_fill())
    assert "horizon 顶层" not in warns and "price×shares" not in warns
    expect_valueerror(minimal_fill(pe_ttm="11.5"), "Hero pe_ttm 与四件套偏差 >1%", kw="Hero pe_ttm")
    warns = validate_stderr(minimal_fill(horizon="24个月"))
    assert "horizon 顶层" in warns
    warns = validate_stderr(minimal_fill(mcap="1200"))
    assert "price×shares" in warns
    f = minimal_fill()
    del f["pe_ttm"]
    warns = validate_stderr(f)
    assert "Hero pe_ttm 缺失" in warns
    warns = validate_stderr(minimal_fill(target_sub_html="较现价 +21%"))
    assert "target_sub_html 含具体" in warns


def test_dupont_basis_consistency_gate(tmp_path):
    """v0.16.0：dupont basis 门禁——fill 与落盘 dupont 同口径放行（皆无 basis=旧累计 legacy，
    或皆 basis="ttm"）；一侧有一侧无/两侧不同 → 拒渲染（禁新旧口径混填出混合乘积链）。"""
    def _ref(dupont):
        return write_fill({"price": 10.0, "pe_ttm": 11.0, "dupont": dupont},
                          str(tmp_path), name="dup_quote.json")

    verdict = "净利率是主驱动（贡献约六成），与 4.4 毛利率归因一致——基础测试判词。"
    ttm = {"basis": "ttm", "period": "2026三季", "prev_period": "2025三季",
           "roe": 16.1, "nm": 30.4, "turn": 0.313, "em": 1.70,
           "prev": {"roe": 8.3, "nm": 19.2, "turn": 0.258, "em": 1.65},
           "verdict": verdict}
    legacy = {k: v for k, v in ttm.items() if k != "basis"}
    # 双 legacy / 双 ttm → 放行（basis 不告警）
    warns = validate_stderr(minimal_fill(quote={"source_file": _ref(legacy)}, dupont=legacy))
    assert "dupont basis" not in warns
    warns = validate_stderr(minimal_fill(quote={"source_file": _ref(ttm)}, dupont=ttm))
    assert "dupont basis" not in warns
    # fill ttm vs 落盘 legacy → 拒；反向亦然
    expect_valueerror(minimal_fill(quote={"source_file": _ref(legacy)}, dupont=ttm),
                      "fill ttm 落盘 legacy 混用应拒", kw="dupont basis")
    expect_valueerror(minimal_fill(quote={"source_file": _ref(ttm)}, dupont=legacy),
                      "fill legacy 落盘 ttm 混用应拒", kw="dupont basis")
    # 落盘无 dupont 键（旧 quote 落盘）→ 既有「手填嫌疑」软告警路径不破
    warns = validate_stderr(minimal_fill(quote={"source_file": _ref(None)}, dupont=ttm))
    assert "落盘 JSON 无 dupont 键" in warns


def test_gap_growth_consensus_validate():
    """v5.1.2：gap_plot 净利维度（consensus 对落盘 np_avg、ours 对 base.profit）与
    growth_plot 换算对账（np_consensus 对落盘换算增速、base.profit 换算增速越界）。"""
    ref = _period_ref_file("v512_gap", {"consensus_np": 905})
    warns = validate_stderr(minimal_fill(
        quote={"source_file": ref},
        gap_plot={"dims": [
            {"name": "2026E 归母净利（亿元）", "ours": 90, "consensus": 870},
            {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]}))
    assert "np_avg" in warns and "基础情景净利" in warns
    # 合规路径：年份不一致（2027E vs 落盘 2026）静默跳过；一致不告警
    warns = validate_stderr(minimal_fill(
        quote={"source_file": ref},
        gap_plot={"dims": [
            {"name": "2027E 归母净利（亿元）", "ours": 100, "consensus": 870},
            {"name": "2026E 归母净利（亿元）", "ours": 100, "consensus": 905},
            {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]}))
    assert "gap_plot「" not in warns
    # growth_plot：np_avg=120 ÷ 上年归母净利 100 − 1 = 20% vs np_consensus 15% → 差 5pct 告警；
    # base.profit=100 → 换算 0% 越出本文区间 [5,10]（容差 ±2pct）→ 告警
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_g", {"consensus_np": 120})},
        gap_plot={"dims": [
            {"name": "2026E 归母净利（亿元）", "ours": 100, "consensus": 120},
            {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]},
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
            {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
            {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10, "np_consensus": 15}]}))
    assert "np_consensus" in warns and "基础情景换算增速" in warns


def test_growth_consensus_rejects_unverifiable_cumulative_year_ranges():
    for label in ("2026-27E", "2026-2027E"):
        fill = minimal_fill(
            quote={"source_file": _period_ref_file("v512_g", {"consensus_np": 120})},
            fin_trend={"years": ["2023", "2024", "2025"], "panels": [
                {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
                {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
                {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
            growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                                  {"y": "2025", "np": 12.0}],
                         "fcst": [{"y": label, "np_lo": -50, "np_hi": 10, "np_consensus": 56.9}]})
        fill["valuation"]["scenarios"][1]["profit"] = 200
        fill["valuation"]["scenarios"][2]["profit"] = 300
        from validate_audit import _check_growth_consistency
        warns = []
        _check_growth_consistency(fill, warns)
        out = "\n".join(warns)
        assert "无法按单年一致预期对账" in out and "基础情景换算增速" not in out


def test_trigger_decidability_examples():
    from validate_charts import _check_trigger_decidability
    for text in ("需求高企", "毛利率承压", "出货失速", "储能超级周期"):
        fill = {"valuation": {"scenarios": [{"key": "base", "trigger": text}]}}
        warns = []
        _check_trigger_decidability(fill, warns)
        assert any("可判定" in w for w in warns), text
    for text in ("DRAM 合约价环比转负", "汽车月交付站稳 4.5 万辆", "存储涨价持续至 2027Q1",
                 "库存环比去化", "产品价格上涨", "新机发布"):
        fill = {"valuation": {"scenarios": [{"key": "base", "trigger": text}]}}
        warns = []
        _check_trigger_decidability(fill, warns)
        assert not warns, (text, warns)


def test_growth_forecast_year_coverage_and_merged_shape():
    from validate_audit import _check_growth_consistency

    def make(label):
        return minimal_fill(
            fin_trend={"years": ["2023", "2024", "2025"], "panels": [
                {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]}]},
            growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                                  {"y": "2025", "np": 12.0}],
                         "fcst": [{"y": label, "np_lo": -50, "np_hi": 50}]})

    for label in ("2026E", "2027E", "2026-27E", "2026-2027E"):
        warns = []
        _check_growth_consistency(make(label), warns)
        assert not any("未覆盖" in w or "合并行" in w or "基础情景换算增速" in w
                       for w in warns), (label, warns)
    for label, expected in (("2028E", "未覆盖"), ("2025-27E", "合并行"), ("2026-28E", "合并行")):
        warns = []
        _check_growth_consistency(make(label), warns)
        assert any(expected in w for w in warns), (label, expected, warns)


def test_gap_prose_multi_org_single_paragraph():
    from validate_html import _check_gap_prose_form
    orgs = {"dims": [{"street": [{"org": "中金"}, {"org": "交银国际"}, {"org": "国泰海通"}]}]}
    body = ("中金（08-29）预计利润上修，交银国际（08-31）给出更高价格，"
            "国泰海通（09-04）强调产能释放，三组券商研报假设与本文逐项比较，"
            "包含数字、日期、预测区间和分歧来源。") * 4
    fill = minimal_fill(gap_tier="A", gap_plot=orgs, gap_html=f"<p>{body}</p>")
    warns = []
    _check_gap_prose_form(fill, warns)
    assert any("多机构" in w for w in warns), warns

    good = minimal_fill(gap_tier="A", gap_plot=orgs,
                        gap_html="<ul><li>中金（08-29）假设</li><li>交银国际（08-31）假设</li>"
                                 "<li>国泰海通（09-04）假设</li></ul>")
    warns = []
    _check_gap_prose_form(good, warns)
    assert not warns, warns

    event_text = ("公司（08-29）披露中报，（09-30）发布分红，（10-01）公告产能进展，"
                  "均为公司事件时间线，上述事项符合预期。") * 4
    event = minimal_fill(gap_tier="A", gap_html=f"<p>{event_text}</p>")
    warns = []
    _check_gap_prose_form(event, warns)
    assert not warns, warns


def test_growth_consensus_requires_verifiable_source_and_presence():
    base = minimal_fill(
        quote={"source_file": _period_ref_file("v512_g_present", {"consensus_np": 120})},
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
            {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
            {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10, "np_consensus": None}]})
    assert "落盘有一致预期但 growth_plot 漏填" in validate_stderr(base)
    base["quote"] = {"source_file": _period_ref_file("v512_g_absent", {"consensus_np": None})}
    base["growth_plot"]["fcst"][0]["np_consensus"] = 20
    assert "不得用单篇旧研报" in validate_stderr(base)


def test_growth_negative_base_gates_numeric_growth():
    from validate_audit import _check_growth_consistency
    for label in ("2024A", "2024年报"):
        fill = {"date": "2026-10-31",
                "fin_trend": {"years": ["2023年报", "2024年报", "2025年报"], "panels": [
                    {"bars": [{"name": "归母净利", "values": [-0.5, 0.4, 0.5]}]}]},
                "growth_plot": {"hist": [{"y": label, "np": 100}], "fcst": []}}
        try:
            _check_growth_consistency(fill, [])
        except ValueError as exc:
            assert "禁止填数字同比增速" in str(exc)
        else:
            raise AssertionError("年份后缀不得绕过负基数门禁")
    fill["growth_plot"] = {"hist": [], "fcst": [{"y": "2026E", "np_lo": 100, "np_hi": 200}]}
    fill["fin_trend"]["panels"][0]["bars"][0]["values"] = [-2.0, -1.0, -0.5]
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "最新年亏损" in str(exc)
    else:
        raise AssertionError("最新年亏损时不得输出预测增速")
    fill["date"] = "2026-10-30"
    warns = []
    _check_growth_consistency(fill, warns)
    assert warns and "最新年亏损" in warns[0]


def test_l4_yellow_points_validate():
    """v5.1.2：L4 黄灯表逐项数值比对——行数一致但扣分值不一致 → 拒渲染；行检出容忍带属性。"""
    tbl = ('<div class="pm-grid"><div>a</div><div>b</div><div>c</div></div>'
           '<div class="table-scroll"><table><thead><tr><th>类别</th><th>风险</th><th>扣分</th></tr></thead>'
           '<tbody><tr class="x"><td>a 交易与股东行为</td><td>减持</td><td class="num">0.5</td>'
           '<td>据公告</td></tr></tbody></table></div><span class="source">数据来源：x</span>')
    warns = validate_stderr(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.5}]))
    assert "扣分值" not in warns
    expect_valueerror(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.8}]), "逐项数值不一致",
        kw="多重集")
    # 热核 P0-2：points 不可解析不崩——pos_y 过滤后行数不符按「正扣分 0 条」拒（报错可定位）；
    # P1-4：0 分条目不啝分母；表侧 class=num 缺失 → 降级告警不拒
    expect_valueerror(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": None}]),
        "points 不可解析", kw="points 缺失或不可解析")
    warns = validate_stderr(minimal_fill(
        l4_html=tbl, yellow_deductions=[{"label": "减持", "points": 0.5},
                                        {"label": "零分项", "points": 0}]))
    assert "多重集" not in warns
    warns = validate_stderr(minimal_fill(
        l4_html=tbl.replace('<td class="num">0.5</td>', '<td>0.5</td>'),
        yellow_deductions=[{"label": "减持", "points": 0.5}]))
    assert "降级" in warns


def test_thesis_baretext_validate():
    """v5.1.2：thesis 三 span 全缺且含价格形态 → 拒渲染（手写价绕行一致性硬校验）。
    热核 P0-1：价格形态只认带「元」的数字组——年份/数量/百分比区间不带元，不误拒。"""
    expect_valueerror(minimal_fill(
        thesis_html="好公司但坏价格，三情景目标价 15.7/37.5/61.8 元，年化中枢 -10.9%，回避。"),
        "三 span 全缺含价格形态", kw="全缺")
    warns = validate_stderr(minimal_fill(thesis_html="只是定性判断，没有价格，文字量足够撑过地板就行。"))
    assert "绕行" not in warns
    # P0-1 回归：年份区间/数量区间/百分比区间/单个现价数字，不得误拒
    warns = validate_stderr(minimal_fill(
        thesis_html="公司 2023-2025 营收复合增速 20%，覆盖 3-5 家核心客户，市占率 10%-15%，"
                    "当前股价 11 元，估值不便宜，继续观望等待更好的价格出现。"))
    assert "绕行" not in warns
    # 带元的区间=价格形态，仍拒
    expect_valueerror(minimal_fill(
        thesis_html="基本面稳健但估值偏高，等 25-29 元观察区再介入，当前回避为宜。"),
        "带元区间仍拒", kw="全缺")


def test_thesis_feedback_requires_research_not_trade_conclusion():
    out = validate_stderr(minimal_fill())
    messages = [line for line in out.splitlines() if "thesis_html 信息量不足" in line]
    assert len(messages) == 1
    assert "研究结论" in messages[0]
    assert "操作结论" not in messages[0]


def test_triggers_target_validate():
    """v5.1.2：triggers hit/miss 行 target 核对——缺「实际值」告警；阈值方向矛盾告警。"""
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "metric": "26H2 毛利率", "target": "≥46%", "status": "hit"}]))
    assert "未写实际值" in warns
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 44.1%", "status": "hit"}]))
    assert "矛盾" in warns
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 47.2%", "status": "hit"}]))
    assert "矛盾" not in warns and "未写实际值" not in warns
    # miss 方向矛盾（阈值满足却标 miss）同样检出
    warns = validate_stderr(minimal_fill(triggers=[
        {"cond": "提价兑现", "target": "≥46%｜实际 47.2%", "status": "miss"}]))
    assert "矛盾" in warns


def _timing_table(chip, technical, total):
    return ('<table><thead><tr><th>维度</th><th>得分</th><th>命中信号</th></tr></thead>'
            f'<tbody><tr><td>筹码面</td><td>{chip}</td><td>证据与来源</td></tr>'
            f'<tr><td>技术面</td><td>{technical}</td><td>同源日线</td></tr>'
            f'<tr><td>合计</td><td>{total}</td><td>独立参考，不调节仓位</td></tr></tbody></table>'
            '<span class="source">数据来源：公开行情与股东户数披露</span>')


def test_timing_table_rejects_numeric_scores_when_missing():
    bad = v2_fill(date="2026-10-26")
    bad["timing_scores"] = None
    bad["position_html"] = _timing_table("5.0", "5.0", "5.0") + "研究复核与估值证伪。" * 8
    try:
        render_v2_fill(bad)
    except ValueError as exc:
        assert "数据不足" in str(exc), str(exc)
    else:
        raise AssertionError("缺总分仍写 5.0 应拒渲染")

    bad["timing_scores"] = {"筹码面": None, "技术面": 5.0}
    bad["position_html"] = _timing_table("数据不足", "5.0", "5.0") + "研究复核与估值证伪。" * 8
    try:
        render_v2_fill(bad)
    except ValueError as exc:
        assert "合计" in str(exc) and "数据不足" in str(exc), str(exc)
    else:
        raise AssertionError("缺子维时合计行也不得写数值分")

    good = v2_fill(date="2026-10-26")
    good["cycle_html"] = "<p>估值周期分析。</p>"
    good["timing_scores"] = {"筹码面": None, "技术面": 5.0}
    good["position_html"] = _timing_table("数据不足", "5.0", "数据不足") + "研究复核与估值证伪。" * 8
    html = render_v2_fill(good)
    assert '时机分 <span class="tv">数据不足</span>' in html
    assert "合计</td><td>数据不足" in html
    legacy = minimal_fill(timing_scores=None,
                          position_html=_timing_table("5.0", "5.0", "5.0") + "研究复核与估值证伪。" * 8)
    assert "兼容" in validate_stderr(legacy)


def test_new_report_rejects_trade_cadence():
    bad = v2_fill(date="2026-10-26")
    bad["dash_html"] = bad["dash_html"].replace("加仓至标配", "复核估值假设")
    bad["dash_html"] = bad["dash_html"].replace("复核估值假设", "加仓至标配")
    try:
        render_v2_fill(bad)
    except ValueError as exc:
        assert "dash_html" in str(exc) and "研究动作" in str(exc), str(exc)
    else:
        raise AssertionError("新报告不应继续输出加仓动作")

    bad = v2_fill(date="2026-10-26")
    bad["dash_html"] = bad["dash_html"].replace("加仓至标配", "复核估值假设")
    bad["position_html"] = "建议分批建仓。研究复核与估值证伪条件。" * 8
    try:
        render_v2_fill(bad)
    except ValueError as exc:
        assert "position_html" in str(exc) and "研究动作" in str(exc), str(exc)
    else:
        raise AssertionError("新报告不应输出分批买卖节奏")

    bad["position_html"] = "研究复核与估值证伪条件。" * 10
    bad["thesis_html"] += "<p>建议分批买入</p>"
    try:
        render_v2_fill(bad)
    except ValueError as exc:
        assert "thesis_html" in str(exc) and "研究动作" in str(exc), str(exc)
    else:
        raise AssertionError("Hero 不应输出分批买卖节奏")

    good = v2_fill(date="2026-10-26")
    good["cycle_html"] = "<p>估值周期分析。</p>"
    good["dash_html"] = good["dash_html"].replace("加仓至标配", "复核估值假设")
    good["position_html"] = "禁止分批；研究复核与估值证伪条件。" * 8
    good["thesis_html"] = "不采用分批节奏，" + good["thesis_html"]
    render_v2_fill(good)
    good["position_html"] = "技术面不触发加减仓建议。研究复核与估值证伪条件。" * 8
    render_v2_fill(good)
    for phrase in ("策略是不断加仓", "策略是不仅加仓"):
        bad = v2_fill(date="2026-10-26", cycle_html="<p>估值周期分析。</p>")
        bad["dash_html"] = bad["dash_html"].replace("加仓至标配", "复核估值假设")
        bad["position_html"] = phrase + "。研究复核与估值证伪条件。" * 8
        try:
            render_v2_fill(bad)
        except ValueError as exc:
            assert "研究动作" in str(exc), str(exc)
        else:
            raise AssertionError(f"真实交易建议必须拒绝：{phrase}")
    legacy = minimal_fill(position_html="加仓并分批建仓。" + "研究复核与估值证伪条件。" * 8,
                          dash_html="加仓至标配")
    warnings = validate_stderr(legacy)
    assert "兼容" in warnings
    assert warnings.count("position_html 含交易节奏") == 1


def test_timing_table_validate():
    """v5.1.2：时机小表得分 vs timing_scores（>0.1 告警）；信号数值/方向 vs 落盘 timing。"""
    tbl = ('<p>时机判定：筹码面改善、技术面偏弱，仓位维持观察池不变，决策逻辑见下表与正文。</p>'
           '<table><thead><tr><th>维度</th><th>得分</th><th>命中信号与加减</th></tr></thead>'
           '<tbody><tr><td>筹码面</td><td>6.0</td><td>户数下降 +1</td></tr>'
           '<tr><td>技术面</td><td>4.0</td><td>现价 10.5 站上 MA60 9.8</td></tr>'
           '<tr><td>合计</td><td>5.3</td><td>独立参考，不调节仓位</td></tr></tbody></table>'
           '<span class="source">时机信号：quote 落盘 timing（现价/MA60/MA120/52 周高低），'
           '筹码面数据：E4 股东户数，均取自 em_fetch 落盘输出。</span>'
           '<div class="info-card"><strong>决策逻辑：</strong>质量分好公司但估值无安全边际，'
           '时机仅作独立参考，维持观察池，等估值回到合理带下沿再评估。</div>')
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                     "high_52w": 12.0, "low_52w": 8.0}}, d, "_ref_t.json")
        # 筹码面 6.0 vs timing_scores 5 → 告警；现价 10.5 vs 落盘 10.0 差 5% → 告警；
        # 「站上 MA60」与 10.0 > 9.9 不矛盾 → 无方向告警
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl))
        assert "「筹码面」得分" in warns and "现价=10.5" in warns
        assert "上方/站上" not in warns
        # 方向矛盾：现价 10.0 < MA120 12.0 却写「站上 MA120」→ 告警
        tbl2 = tbl.replace("现价 10.5 站上 MA60 9.8", "现价 10.0 站上 MA120")
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "timing": {"price": 10.0, "ma60": 9.9, "ma120": 12.0,
                                      "high_52w": 13.0, "low_52w": 8.0}}, d, "_ref_t2.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref2}, position_html=tbl2))
        assert "上方/站上" in warns


def test_timing_table_52w_cross_validate():
    """P0-1 文档虚言闭合：时机小表 52 周高低信号 vs 落盘 timing（fill-schema/SKILL 承诺
    技术面信号取自落盘，此前只比对现价/MA60/MA120）——合并写法「52周高低 高/低」与
    分拆写法「52周低 X」同口径 >1% 告警。"""
    tbl = ('<p>时机判定：筹码面改善、技术面偏弱，仓位维持观察池不变，决策逻辑见下表与正文。</p>'
           '<table><thead><tr><th>维度</th><th>得分</th><th>命中信号与加减</th></tr></thead>'
           '<tbody><tr><td>筹码面</td><td>5.0</td><td>户数下降 +1</td></tr>'
           '<tr><td>技术面</td><td>5.0</td><td>现价 10.0 站上 MA60 9.9；52周高低 12.0/8.0</td></tr>'
           '<tr><td>合计</td><td>5.0</td><td>独立参考，不调节仓位</td></tr></tbody></table>'
           '<span class="source">时机信号：quote 落盘 timing（现价/MA60/MA120/52 周高低）。</span>'
           '<div class="info-card"><strong>决策逻辑：</strong>质量分好公司但估值无安全边际，'
           '时机仅作独立参考，维持观察池，等估值回到合理带下沿再评估。</div>')
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                     "high_52w": 12.0, "low_52w": 8.0}}, d, "_ref_52w.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl))
        assert "52周高" not in warns and "52周低" not in warns, "一致不应告警"
        # 合并写法高值偏差：12.0 vs 落盘 15.0 → 告警
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "timing": {"price": 10.0, "ma60": 9.9, "ma120": 9.5,
                                      "high_52w": 15.0, "low_52w": 8.0}}, d, "_ref_52w2.json")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref2}, position_html=tbl))
        assert "52周高=12.0" in warns and "禁手估" in warns, "合并写法高值偏差应告警"
        # 分拆写法低值偏差：「52周低 7.0」vs 落盘 8.0 → 告警
        tbl2 = tbl.replace("52周高低 12.0/8.0", "52周低 7.0")
        warns = validate_stderr(minimal_fill(quote={"source_file": ref}, position_html=tbl2))
        assert "52周低=7.0" in warns, "分拆写法低值偏差应告警"


def test_period_verdict_cross_validate():
    """v5.1.2：period_track 判词 vs 完成度机械对账（分母=一致预期优先、时间进度按报告期）。"""
    pt = {"period": "2026中报", "is_annual": False, "np": 30, "consensus_np": 100,
          "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv", pt)}, period_track=dict(pt)))
    assert "超前 但完成度" in warns
    pt2 = {"period": "2026中报", "is_annual": False, "np": 60, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv2", pt2)}, period_track=dict(pt2)))
    assert "超前 但完成度" not in warns
    # 一季/三季标签同样生效（热核 P1-2：此前认不出项目自家标签）
    pt3 = {"period": "2026一季", "is_annual": False, "np": 5, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv3", pt3)}, period_track=dict(pt3)))
    assert "超前 但完成度" in warns
    # 亏损期累计 ≤0 → 完成度无意义静默跳过（热核 P1，_period_ratio 返回 None）
    pt4 = {"period": "2026中报", "is_annual": False, "np": -5, "consensus_np": 100,
           "verdict_np": "超前"}
    warns = validate_stderr(minimal_fill(
        quote={"source_file": _period_ref_file("v512_pv4", pt4)}, period_track=dict(pt4)))
    assert "超前 但完成度" not in warns


def _l1_with_43(body_43: str) -> str:
    """6 个规范 dim-name 的 l1_html，4.3 块正文由参数给定。"""
    plain = "该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，行业地位稳固，具备长期参考价值。"
    out = []
    for nm in ("4.1 赛道与宏观", "4.2 产业链位置", "4.3 商业模式与护城河", "4.4 财务健康",
               "4.5 治理与资本配置", "4.6 资本回报质量"):
        body = body_43 if nm.startswith("4.3") else plain
        out.append(f'<div class="dim-block"><div class="dim-header"><span class="dim-name">{nm}</span>'
                   f'</div><p>{body}</p></div>')
    return "".join(out)


def test_handwritten_dupes_validate():
    """v5.1.2：手写表与脚本生成并存检测——p0 敏感性表 / valuation 三情景表与指标卡 /
    l1 多年年表 / gap 机构对照表，均已由字段或脚本承载。"""
    warns = validate_stderr(minimal_fill(
        p0_html=('<span class="section-tag">分型：周期股</span><p>识别特征一段，周期定位与弹性来源。</p>'
                 '<table><thead><tr><th>变量</th><th>净利影响</th></tr></thead>'
                 '<tbody><tr><td>金价</td><td>±20%</td></tr></tbody></table>'
                 '<span class="source">数据来源：x</span>'),
        sensitivity=[{"name": "金价", "impact": 20, "delta": "±10%"},
                     {"name": "产量", "impact": 13}]))
    assert "手写敏感性表" in warns
    warns = validate_stderr(minimal_fill(
        valuation_html=('<div class="table-scroll"><table class="scenario-table">'
                        '<thead><tr><th>指标</th></tr></thead><tbody><tr><td>x</td></tr></tbody>'
                        '</table></div><span class="source">数据来源：x</span>')))
    assert "手写三情景表" in warns
    warns = validate_stderr(minimal_fill(
        valuation_html=('<div class="metric-row"><div class="metric-card"><div class="label">年化中枢'
                        '</div></div></div><p>校准逻辑说明一段。</p>')))
    assert "手写三指标卡" in warns
    warns = validate_stderr(minimal_fill(l1_html=_l1_with_43(
        '护城河分析一段。'
        '<table><thead><tr><th>指标</th><th>2021</th><th>2022</th><th>2023</th><th>2024</th>'
        '<th>2025</th></tr></thead><tbody><tr><td>营收</td><td>1</td><td>2</td><td>3</td>'
        '<td>4</td><td>5</td></tr><tr><td>净利</td><td>1</td><td>2</td><td>3</td><td>4</td>'
        '<td>5</td></tr></tbody></table><span class="source">数据来源：x</span>')))
    assert "手写年表" in warns
    warns = validate_stderr(minimal_fill(
        gap_plot={"dims": [{"name": "2026E 归母净利（亿元）", "ours": 100, "consensus": 100},
                           {"name": "2026E 目标价（元）", "ours": 11, "consensus": 10}]},
        gap_html=('<table><thead><tr><th>机构</th><th>预测</th></tr></thead>'
                  '<tbody><tr><td>野村</td><td>952</td></tr></tbody></table>'
                  '<span class="source">数据来源：x</span>')))
    assert "逐机构对照表" in warns


def test_red_flag_conclusion_validate():
    """v5.1.2：红旗 ≥2 项 → conclusion 首卡首句必须含「利润真实性存疑」（拒渲染）。"""
    red2 = [{"item": "现金含量连续2年<0.7", "points": 0.5},
            {"item": "应收增速远超营收", "points": 0.5}]
    expect_valueerror(minimal_fill(red_deductions=red2), "首卡首句存疑句", kw="利润真实性存疑")
    f = minimal_fill(red_deductions=red2)
    f["conclusion_html"] = f["conclusion_html"].replace(
        "关键优势</div>", "关键优势</div>利润真实性存疑，", 1)
    validate_stderr(f)  # 不拒即通过


def test_slot_widths_validate():
    """v5.1.2：槽位契约补闸——scenario.trigger >15 字 / drivers.chips 档值 >12 字告警。"""
    warns = validate_stderr(minimal_fill(valuation={
        "shares": 100, "horizon": "12个月", "scenarios": [
            {"key": "pess", "label": "悲观", "trigger": "下", "profit": 80, "pe": [8, 10]},
            {"key": "base", "label": "基础", "trigger": "NIM 降至 1.22%、信用成本升至 0.65%",
             "profit": 100, "pe": [10, 12]},
            {"key": "opt", "label": "乐观", "trigger": "上", "profit": 120, "pe": [12, 14]}]}))
    assert "trigger" in warns and "字 > 15" in warns
    warns = validate_stderr(minimal_fill(
        drivers=[{"name": "金价", "elastic": "x",
                  "chips": [{"label": "悲观", "value": "800"}, {"label": "基础", "value": "900"},
                            {"label": "乐观", "value": "1,000"},
                            {"label": "悲观另注", "value": "这是一个超过十二字的档值啊"}]}],
        driver_verdict="v", sensitivity=[{"name": "金价", "impact": 20}]))
    assert "chips 档值" in warns


def test_threshold_coverage_validate():
    """v5.1.2：4.3 压力测试阈值须在 14 章 triggers/dash_html 有对应行，否则告警。"""
    l1 = _l1_with_43("护城河压力测试：若市占率跌破 15% 则逻辑失效，需要持续跟踪该指标变化。")
    warns = validate_stderr(minimal_fill(l1_html=l1))
    assert "无对应行" in warns
    warns = validate_stderr(minimal_fill(l1_html=l1, dash_html=(
        '<div class="table-scroll"><table class="dash-table"><thead><tr><th>指标</th><th>当前值</th>'
        '<th>触发阈值</th></tr></thead><tbody><tr><td>市占率</td><td>17%</td><td>跌破 15%</td></tr>'
        '</tbody></table></div><span class="source">数据来源：x</span>')))
    assert "无对应行" not in warns


def test_threshold_coverage_ignores_bare_years():
    for text in ("订单降至2025年水平、渗透率低于2021年水平", "行业估值低于2016Q3水平"):
        l1 = _l1_with_43(f"压力测试：{text}时复核，并同步检查订单与现金流变化。")
        warns = validate_stderr(minimal_fill(l1_html=l1))
        assert "压力测试阈值" not in warns, f"年份/季度不应被当成跟踪阈值：{warns}"


def test_threshold_coverage_keeps_real_numeric_thresholds():
    cases = (("毛利率降至25%", "25%"), ("产能超过200", "200"),
             ("产能低于2000吨", "2000"), ("订单降至2025万吨", "2025"),
             ("营收低于2000", "2000"))
    for text, value in cases:
        warns = validate_stderr(minimal_fill(l1_html=_l1_with_43(
            f"压力测试：{text}时复核，并同步检查订单、资本开支与现金流变化。")))
        assert "压力测试阈值" in warns and value in warns, f"真实阈值 {value} 不应被漏报"


def test_cycle_stages_validate():
    """v4.11.3 阶段卡校验：手写阶段表迁移告警；driver 超宽告警。
    v5.1.2：current ≠1（与渲染同源的有效项口径）→ 拒渲染；缺 name/period 项告警不落图；
    字段已填但 cycle_html 缺失 → 告警（阶段卡挂第 11 章条件块内）。"""
    warns = validate_stderr(minimal_fill(cycle_html='<table><tr><th>阶段</th></tr></table>'))
    assert "迁移 cycle_stages" in warns
    expect_valueerror(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021", "current": True},
        {"name": "b", "period": "2022", "current": True},
        {"name": "c", "period": "2023"}]), "current 恰 1 个", kw="恰为 1 个")
    expect_valueerror(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021"},
        {"name": "b", "period": "2022"},
        {"name": "c", "period": "2023"}]), "0 个 current 同拒", kw="恰为 1 个")
    warns = validate_stderr(minimal_fill(cycle_stages=[
        {"name": "a", "period": "2021", "current": True},
        {"name": "b", "current": True},
        {"name": "c", "period": "2023", "driver": "长" * 30},
        {"name": "d", "period": "2024"}]))
    assert "不落图" in warns and "> 48" in warns and "cycle_html 缺失" in warns


def test_cycle_position_validate():
    """v5.2.0 周期位置刻度条校验（首版软告警）：周期股+cycle_html 缺 cycle_position → 告警；
    缺键 → 逐键告警；stage 与 cycle_stages 本轮不一致 → 告警；无 cycle_html 不告警。"""
    warns = validate_stderr(minimal_fill(cycle_html="<p>周期分析。</p>"))
    assert "cycle_position 未填" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_position={"stage": "上行期后段", "price_pctile": "铝价分位 70%"}))
    assert "cycle_position.capacity" in warns and "cycle_position.implication" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_stages=[{"name": "出清", "period": "2022", "current": True},
                      {"name": "复苏", "period": "2023"},
                      {"name": "上行", "period": "2024"}],
        cycle_position={"stage": "下行末段", "price_pctile": "a", "capacity": "b",
                        "stock_spread": "c", "implication": "d"}))
    assert "不一致" in warns
    warns = validate_stderr(minimal_fill(
        cycle_html="<p>x</p>",
        cycle_stages=[{"name": "出清", "period": "2022", "current": True},
                      {"name": "复苏", "period": "2023"},
                      {"name": "上行", "period": "2024"}],
        cycle_position={"stage": "出清末段", "price_pctile": "a", "capacity": "b",
                        "stock_spread": "c", "implication": "d"}))
    assert "不一致" not in warns
    assert "cycle_position" not in validate_stderr(minimal_fill())


def test_earnings_stability_validate():
    """v5.2.0 盈利波动性软锚校验（软告警）：sigma 与 fin_trend 扣非柱复算（夹具 σ=1.4）
    偏差 >0.15pct → 告警；verdict 缺失 → 告警；一致且键齐 → 不告警。
    热核修复补齐边界：sigma 缺失分支 / 无扣非柱 / 复算不可用（亏损基数致增速点不足）
    均不得静默放过；字符串 sigma 经 _num 归一不误报。"""
    warns = validate_stderr(minimal_fill(earnings_stability={"sigma": 15, "verdict": "x"}))
    assert "偏差 >0.15pct" in warns
    warns = validate_stderr(minimal_fill(earnings_stability={"sigma": 1.4}))
    assert "verdict 缺失" in warns
    warns = validate_stderr(minimal_fill(
        earnings_stability={"sigma": 1.4, "peer_median": None, "verdict": "波动低"}))
    assert "earnings_stability" not in warns
    # sigma 缺失分支
    warns = validate_stderr(minimal_fill(earnings_stability={"verdict": "x"}))
    assert "sigma 缺失" in warns
    # 字符串 sigma（"1.4" 经 _num 归一）不误报
    warns = validate_stderr(minimal_fill(
        earnings_stability={"sigma": "1.4", "verdict": "波动低"}))
    assert "偏差 >0.15pct" not in warns and "sigma 缺失" not in warns
    # 无扣非柱 → 「无法复算」告警（不静默放过）
    f0 = minimal_fill()
    ft = f0["fin_trend"]
    ft["panels"] = [p for p in ft["panels"]
                    if not any("扣非" in b.get("name", "") for b in p.get("bars", []))]
    warns = validate_stderr(minimal_fill(
        fin_trend=ft, earnings_stability={"sigma": 1.4, "verdict": "波动低"}))
    assert "无扣非柱可复算" in warns
    # 亏损基数致增速点 <3 → 复算不可用告警
    f1 = minimal_fill()
    ft1 = f1["fin_trend"]
    for p in ft1["panels"]:
        for b in p.get("bars", []):
            if "扣非" in b.get("name", ""):
                b["values"] = [10, -5, -8, 12, 13]
    warns = validate_stderr(minimal_fill(
        fin_trend=ft1, earnings_stability={"sigma": 9.9, "verdict": "波动低"}))
    assert "复算不可用" in warns


def test_earnings_stability_prefers_full_precision_quote():
    fill = minimal_fill(earnings_stability={"sigma": 13.9, "verdict": "波动适中"})
    for panel in fill["fin_trend"]["panels"]:
        for bar in panel.get("bars", []):
            if "扣非" in bar.get("name", ""):
                bar["values"] = [4.6, 6.1, 10.3, 15.7, 23.2]
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": fill["price"], "pe_ttm": fill["pe_ttm"],
                          "earnings_stability": {"sigma": 13.9, "n_g": 4, "dropped": 0}},
                         d, name="_em_quote.json")
        fill["quote"] = {"source_file": ref, "date": fill["date"]}
        out = validate_stderr(fill)
        assert "earnings_stability.sigma" not in out and "偏差 >0.15pct" not in out
        fill["earnings_stability"]["sigma"] = 14.2
        assert "偏差 >0.15pct" in validate_stderr(fill)


def test_growth_consistency_checks_later_years_from_gap_ours():
    from validate_audit import _check_growth_consistency

    def make_fill(lo, hi):
        fill = minimal_fill(growth_plot={
            "hist": [{"y": "2023", "np": 69.1}, {"y": "2024", "np": 53.6},
                     {"y": "2025", "np": 47.7}],
            "fcst": [{"y": "2026E", "np_lo": -70, "np_hi": 70},
                     {"y": "2027E", "np_lo": lo, "np_hi": hi}]},
            gap_plot={"dims": [
                {"name": "2026E归母净利（亿元）", "ours": 34, "consensus": 33.65},
                {"name": "2027E归母净利（亿元）", "ours": 39, "consensus": 39.84}]})
        for scenario in fill["valuation"]["scenarios"]:
            if scenario["key"] == "base":
                scenario["profit"] = 34
        return fill

    for lo, hi, expected in ((-12, 35, False), (28, 97, True)):
        warns = []
        _check_growth_consistency(make_fill(lo, hi), warns)
        assert ("2027E" in "\n".join(warns) and "本文利润路径" in "\n".join(warns)) == expected
    fill = make_fill(28, 97)
    fill["gap_plot"]["dims"].pop(0)
    warns = []
    _check_growth_consistency(fill, warns)
    assert "本文利润路径" not in "\n".join(warns)
    fill = make_fill(-12, 35)
    fill["gap_plot"]["dims"].insert(1, {"name": "2026E目标价（元）", "ours": 11})
    warns = []
    _check_growth_consistency(fill, warns)
    assert "本文利润路径" not in "\n".join(warns)


def test_dcf_validate():
    """v4.11.3 DCF 校验：稳健成长缺 dcf 告警；缺键告警；valuation_html 手写 DCF 表重复告警。
    v5.4.1：分型改归一判定——「成长型」+ mid / 未声明 high 与旧名「稳健成长股」同样命中，
    「成长型」+ high 走远期 PE 折现不强制。"""
    warns = validate_stderr(minimal_fill(stock_type="稳健成长股"))
    assert "dcf 字段未填" in warns
    for over in ({"stock_type": "成长型", "growth_tier": "mid"},      # v5.3.0 新名 + 中速层
                 {"stock_type": "成长型"}):                            # 未声明 growth_tier（按 mid）
        assert "dcf 字段未填" in validate_stderr(minimal_fill(**over)), f"{over} 缺 dcf 应告警"
    assert "dcf 字段未填" not in validate_stderr(
        minimal_fill(stock_type="成长型", growth_tier="high")), "高速层走远期 PE 折现，不强制 dcf"
    warns = validate_stderr(minimal_fill(dcf={"value": 12}))
    assert "缺键" in warns
    warns = validate_stderr(minimal_fill(
        dcf={"value": 12, "fcf0": "1", "growth_5y": "1", "g_perp": "1", "wacc": "1",
             "net_cash": "1", "implied_g": "1", "verdict": "长" * 50},
        valuation_html='<table><tr><th>DCF三行</th></tr></table>'
                       '<span class="source">数据来源：测试</span>'))  # 表须带来源标注，否则先撞内容地板硬拒
    assert "手写 DCF 表" in warns


def test_dcf_stable_value_required_warn():
    """P0-6（用户拍板补校验）：稳定价值（非金融）缺 dcf → 告警（fill-schema/SKILL 承诺的
    零执行闭合）；stock_type 含「金融」（银行/保险走 PB-ROE/DDM，scoring.md）→ 豁免。"""
    warns = validate_stderr(minimal_fill(stock_type="稳定价值（非金融）"))
    assert "dcf 字段未填" in warns and "稳定价值" in warns, "非金融稳定价值缺 dcf 应告警"
    warns = validate_stderr(minimal_fill(stock_type="稳定价值（金融）"))
    assert "dcf 字段未填" not in warns, "金融类稳定价值股应豁免"
    # v5.5.0 P1：子类词表单源（_fin_subclass）——证券与银行/保险同豁免，与 B6 参考带同口径
    for st in ("稳定价值（证券）", "稳定价值/金融（券商）", "稳定价值/金融（保险）"):
        assert "dcf 字段未填" not in validate_stderr(minimal_fill(stock_type=st)), f"{st} 应豁免"


def test_dcf_mature_stagnant_required_warn():
    out = validate_stderr(minimal_fill(stock_type="成熟/停滞"))
    assert "dcf 字段未填" in out and "成熟/停滞" in out, f"成熟/停滞分型表要求 DCF，但当前漏检：{out}"


# ---------------- v5.5.0 B4 sensitivity 业务线覆盖硬闸 ----------------
_SEG_ITEMS = [{"name": "手机", "rev_pct": 60.0, "gp_pct": 55.0},
              {"name": "互联网服务", "rev_pct": 25.0, "gp_pct": 30.0},
              {"name": "其他", "rev_pct": 15.0, "gp_pct": 8.0}]   # 8% < 15 → 不参与覆盖


def _cov_fill(**over):
    """B4 夹具：两个大分部（手机 55% / 互联网服务 30%）+ 一条 sensitivity 变量。"""
    base = minimal_fill(
        segments={"period": "2025年报", "by": "产品", "items": _SEG_ITEMS},
        sensitivity=[{"name": "手机毛利率", "impact": 12, "delta": "±1pct"}],
        drivers=[{"name": "手机毛利率", "elastic": "±1pct → 净利 ±12%",
                  "chips": [{"label": "悲观", "value": "30"}, {"label": "基础", "value": "33"},
                            {"label": "乐观", "value": "35"}]}],
        sensitivity_meta={"coverage": [
            {"segment": "手机", "var": "手机毛利率"},
            {"segment": "互联网服务", "excluded": "ARPU 稳定，±10% 收入 → 净利 ±3%，不足以改变情景结论"}]},
    )
    base.update(over)
    return base


def test_sensitivity_coverage_gate():
    """v5.5.0 B4：sensitivity_meta.coverage 覆盖硬闸（拒渲染）——gp_pct ≥15 的大分部必须
    逐条登记（var 或带数字的 excluded）；双填/双缺、var 瞎指、excluded 无数字均拒；
    合规放行；segments 缺失/无大分部整条跳过。"""
    R.validate_content(_cov_fill(), R.compute_valuation(_cov_fill()))   # 合规 → 过
    # 大分部未登记 → 拒（报错列出分部名与 gp_pct）
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [{"segment": "手机", "var": "手机毛利率"}]}
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("大分部未覆盖应拒")
    except ValueError as e:
        assert "未覆盖大分部" in str(e), f"拒渲染来源不符：{e}"
        assert "互联网服务（毛利占比 30%）" in str(e), "报错须列出未覆盖分部及其 gp_pct"
    # var + excluded 双填 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率", "excluded": "±10% → 净利 ±3%"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "双填应拒", kw="双填")
    # 双缺 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [{"segment": "手机"},
                                          {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "双缺应拒", kw="双缺")
    # var 瞎指（不在 sensitivity 集合）→ 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "不存在的变量"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"}]}
    expect_valueerror(f, "var 瞎指应拒", kw="不在 sensitivity 变量集合")
    # excluded 无数字 → 拒
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率"},
        {"segment": "互联网服务", "excluded": "影响不大，不单独入图"}]}
    expect_valueerror(f, "排除理由无数字应拒", kw="excluded 无数字")
    # sensitivity 全缺 + 有大分部 → 拒
    f = _cov_fill()
    f.pop("sensitivity")
    expect_valueerror(f, "sensitivity 全缺应拒", kw="sensitivity 字段缺失")
    # coverage 引用不存在的分部 → 软告警
    f = _cov_fill()
    f["sensitivity_meta"] = {"coverage": [
        {"segment": "手机", "var": "手机毛利率"},
        {"segment": "互联网服务", "excluded": "±10% → 净利 ±3%"},
        {"segment": "不存在的分部", "excluded": "±10% → 净利 ±2%"}]}
    assert "引用了 segments 中不存在的分部" in validate_stderr(f)
    # segments 缺失 / 大分部全无（gp_pct 均 <15）→ 整条跳过
    R.validate_content(minimal_fill(), R.compute_valuation(minimal_fill()))
    small = minimal_fill(segments={"items": [{"name": "A", "rev_pct": 60, "gp_pct": 12},
                                             {"name": "B", "rev_pct": 40, "gp_pct": 9}]})
    R.validate_content(small, R.compute_valuation(small))
    # v5.5.0 P1：有行缺 gp_pct → 软告警；诚实缺失不得建议删行、不得破坏收入合计
    f = _cov_fill()
    f["segments"]["items"][0].pop("gp_pct")
    f["segments"]["note"] = "该分部公开披露无毛利口径，毛利字段留空"
    out = validate_stderr(f)
    assert "行缺 gp_pct" in out and "绕过覆盖闸" in out, "缺 gp_pct 应软告警"
    assert "或删该行" not in out, "缺毛利不得建议删除收入占比行"
    assert all(s in out for s in ("保留该行", "毛利留空", "segments.note")), \
        f"告警应给出诚实缺失的保留+留空+口径注路径: {out}"
    assert "收入占比合计" not in out, f"完整收入分母不应触发合计告警: {out}"
    R.validate_content(f, R.compute_valuation(f))
    # 全部行都缺 gp_pct（硬闸无从生效）→ 同样告警、仍不拒
    allno = minimal_fill(segments={"items": [{"name": "A", "rev_pct": 60},
                                             {"name": "B", "rev_pct": 40}]})
    out2 = validate_stderr(allno)
    assert "行缺 gp_pct" in out2, "全行缺 gp_pct 也应告警"
    R.validate_content(allno, R.compute_valuation(allno))


def _risk_item(name="应收恶化", rule_id="1D.RED.RECEIVABLES", home="1D", status="hit",
               impact="quality", evidence="应收周转连续恶化", trigger="周转天数继续上升", source="公司公告"):
    return {"name": name, "status": status, "evidence": evidence, "impact": impact,
            "home": home, "trigger": trigger, "source": source, "rule_id": rule_id}


def _with_red_flag(fill):
    fill["score_inputs"]["1D"]["red_flags"]["receivables"] = True
    return fill


def _risk_error(fill):
    try:
        R.build_risk_register(fill)
    except ValueError as exc:
        return str(exc)
    raise AssertionError("风险登记应拒绝但未拒绝")


def test_risk_register_groups_cards_by_status_without_impact_or_trigger():
    fill = _with_red_flag(v2_fill(risk_items=[
        _risk_item(),
        _risk_item(name="估值过高", rule_id=None, home="valuation", status="watch", impact="valuation",
                   evidence="PE高于历史区间", trigger="PE继续上升", source="公开行情"),
        _risk_item(name="筹码未核实", rule_id=None, home="timing", status="unknown", impact="timing",
                   evidence="股东户数数据未获取", trigger="等待披露", source="定期报告"),
        _risk_item(name="原材料上涨", rule_id=None, home="dashboard", status="watch", impact="monitor",
                   evidence="原料价格上涨", trigger="继续涨价", source="行业数据"),
    ]))
    html = R.build_risk_register(fill)
    assert 'class="risk-group risk-group-hit"' in html
    assert 'class="risk-group risk-group-watch"' in html
    assert 'class="risk-group risk-group-unknown"' in html
    assert re.search(r"当前命中\s*<span>1</span>", html)
    assert re.search(r"持续观察\s*<span>2</span>", html)
    assert re.search(r"尚未核实\s*<span>1</span>", html)
    assert 'class="risk-card-list primary"' in html
    assert 'data-rule-id="1D.RED.RECEIVABLES"' in html
    assert "应收周转连续恶化" in html and "公司公告" in html
    assert "未核实" in html and "通过" not in html
    assert "PE继续上升" not in html and "继续涨价" not in html
    assert "质量｜" not in html and "估值｜" not in html
    assert "风险事实" not in html and "影响去向" not in html and "跟踪指标" not in html


def test_risk_register_empty_state_has_no_cards():
    html = R.build_risk_register(v2_fill())
    assert "本期未登记风险；这不代表风险已经排除" in html
    assert 'class="risk-card' not in html


def test_risk_duplicate_rule_id_is_rejected():
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(), _risk_item(name="应收再恶化")]))
    assert "不得重复" in _risk_error(fill)


def test_risk_rule_id_must_match_dimension_and_registry():
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(rule_id="1C.MOAT.COUNT", home="1D")]))
    assert "home" in _risk_error(fill)
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(rule_id="1D.NOT_EXIST")]))
    assert "RULE_REGISTRY" in _risk_error(fill)


def test_risk_multiple_hits_require_review_not_red_flag():
    fill = _with_red_flag(v2_fill(risk_items=[
        _risk_item(),
        _risk_item(name="赛道承压", rule_id="1A.MATURE.CHECK", home="1A"),
        _risk_item(name="产业链承压", rule_id="1B.VALUE_CHAIN", home="1B"),
        _risk_item(name="护城河承压", rule_id="1C.MOAT.COUNT", home="1C"),
    ]))
    assert "red_review" in _risk_error(fill)
    fill["red_review"] = "复核完成：不升级红灯"
    html = R.build_risk_register(fill)
    assert "复核完成：不升级红灯" in html
    assert R.compute_scores(fill)["red_flag"] == ""


def test_risk_register_rejects_invalid_enums():
    for field, value in (("status", "passed"), ("impact", "quality_and_valuation"), ("home", "2A")):
        fill = _with_red_flag(v2_fill(risk_items=[_risk_item(**{field: value})]))
        assert field in _risk_error(fill)


def test_risk_register_requires_display_fields():
    for field in ("name", "evidence", "trigger", "source"):
        fill = _with_red_flag(v2_fill(risk_items=[_risk_item(**{field: ""})]))
        assert field in _risk_error(fill)


def test_risk_quality_hit_requires_rule_id():
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(rule_id=None)]))
    assert "rule_id" in _risk_error(fill)


def test_risk_quality_rule_must_be_in_actual_score_chain():
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(rule_id="1D.RED.INVENTORY")]))
    assert "得分链" in _risk_error(fill)


def test_risk_custom_rule_registry_is_per_report():
    fill = v2_fill(risk_items=[_risk_item(name="客户集中", rule_id="1C.CUSTOM.CUSTOMER", home="1C")])
    fill["score_inputs"]["1C"]["custom"] = {
        "id": "1C.CUSTOM.CUSTOMER", "points": -1, "reason": "客户集中", "evidence": "第一大客户占60%"}
    assert "客户集中" in R.build_risk_register(fill)
    fill["score_inputs"]["1C"].pop("custom")
    assert "RULE_REGISTRY" in _risk_error(fill)


def test_rule_registry_uses_shared_quality_catalog():
    import quality_rules
    import scoring
    assert scoring.RULE_REGISTRY is quality_rules.RULE_REGISTRY


def test_v2_l4_requires_register_anchor():
    fill = v2_fill()
    fill["l4_html"] = fill["l4_html"].replace("<!--RISK_REGISTER-->", "")
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, kw="RISK_REGISTER")


def test_v2_l4_rejects_legacy_deduction_copy():
    fill = v2_fill()
    fill["l4_html"] = fill["l4_html"].replace("<!--RISK_REGISTER-->", "<p>黄灯扣分：无</p>")
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, kw="黄灯扣分")


def test_v2_rejects_yellow_deductions():
    fill = v2_fill(yellow_deductions=[{"label": "旧黄灯", "points": 0.5}])
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "yellow_deductions", kw="yellow_deductions")


def test_red_flag_still_breaks_rendering():
    fill = v2_fill(red_flag="审计非标")
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "不建议参与", kw="不建议参与")
    fill["position_html"] = "<p>不建议参与：审计非标，红灯一票否决。</p>" + fill["position_html"]
    html = render_v2_fill(fill)
    assert "不建议参与" in html


def test_risk_register_error_is_caught_by_preflight():
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item(), _risk_item(name="应收再恶化")]))
    with tempfile.TemporaryDirectory() as d:
        path = write_fill(prepare_v2_quote(fill, d), d)
        try:
            R._preflight(path)
        except ValueError as exc:
            assert "不得重复" in str(exc)
        else:
            raise AssertionError("预检应拦截重复风险规则")


def test_v2_risk_register_render_preserves_hero_and_premortem(capsys):
    fill = _with_red_flag(v2_fill(risk_items=[_risk_item()]))
    html = render_v2_fill(fill)
    assert "risk-card-list primary" in html and "如何识别" in html
    assert "风险事实" not in html and "影响去向" not in html and "周转天数继续上升" not in html
    assert "flag-hero-card" in html and "pm-grid" in html
    assert "黄灯扣分" not in html
    assert "公司公告" in html
    assert "1D.RED.RECEIVABLES" in html
    assert "<!--RISK_REGISTER-->" not in html
    assert "统一风险登记" in html
    assert "原黄灯（非致命风险）不在本章另行扣分" in html
    assert "第 4/5 章" in html and "第 7 章" in html
    assert "是否扣分以规则为准" in html
    output = capsys.readouterr().out
    assert "无独立风险扣分" in output
    assert "黄灯" not in output


def _quality_payload(fill):
    import copy
    fields = {"1D": ("f_items", "f_item_evidence", "liquidity", "red_flags", "cash_runway_months"),
              "1F": ("roic", "wacc", "incremental_roic", "roic_period_months",
                     "roic_basis", "cash_runway_months")}
    score_inputs = fill["score_inputs"]
    return {"as_of": fill["date"], "status": "ok",
            "profile": {"stock_type": fill["stock_type"],
                        "industry_profile": fill["industry_profile"],
                        "growth_tier": fill.get("growth_tier")},
            "1D": {key: copy.deepcopy(score_inputs["1D"][key]) for key in fields["1D"]
                   if key in score_inputs["1D"]},
            "1F": {key: copy.deepcopy(score_inputs["1F"][key]) for key in fields["1F"]
                   if key in score_inputs["1F"]},
            "coverage": {}, "sources": [{"type": "tushare", "as_of": fill["date"]}],
            "meta": {"latest_ann_date": fill["date"].replace("-", "")}}


def _prepare_quality_quote(fill, d, payload=None):
    ref = write_fill({"price": fill["price"], "pe_ttm": fill["pe_ttm"],
                      "quality_inputs": payload or _quality_payload(fill)}, d, name="_em_quality.json")
    fill["quote"] = {"source_file": ref, "date": fill["date"]}
    return fill


def test_quality_inputs_two_way_copy_checks():
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(v2_fill(), d)
        assert "quality_inputs" not in validate_stderr(fill)
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1F"]["incremental_roic"] = 0.20
        fill = _prepare_quality_quote(fill, d, payload)
        assert "漏抄" in validate_stderr(fill)
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1F"]["roic"] = None
        fill = _prepare_quality_quote(fill, d, payload)
        assert "落盘缺失" in validate_stderr(fill)
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["liquidity"]["short_cover"] = 99
        payload["1F"]["roic_basis"] = "normalized"
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
        assert "不一致" in out and "short_cover" in out and "roic_basis" in out


def test_quality_inputs_skips_retired_gross_margin_only_for_new_reports():
    from validate_audit import _check_quality_inputs

    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill(date="2026-11-04")
        fill["score_inputs"]["1D"]["red_flags"].pop("gross_margin_anomaly")
        payload = _quality_payload(fill)
        payload["1D"]["red_flags"]["gross_margin_anomaly"] = True
        fill = _prepare_quality_quote(fill, d, payload)
        warns = []
        _check_quality_inputs(fill, warns)
        assert not any("gross_margin_anomaly" in warning for warning in warns)

    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["red_flags"]["gross_margin_anomaly"] = True
        fill = _prepare_quality_quote(fill, d, payload)
        warns = []
        _check_quality_inputs(fill, warns)
        assert any("gross_margin_anomaly" in warning and "不一致" in warning
                   for warning in warns)


@pytest.mark.parametrize("status,impact", [("watch", "quality"), ("hit", "monitor")])
def test_retired_gross_margin_risk_rule_is_rejected_for_any_status(status, impact):
    fill = v2_fill()
    sc = R.compute_scores(fill)
    fill["date"] = "2026-11-04"
    fill["score_inputs"]["1D"]["red_flags"].pop("gross_margin_anomaly")
    item = _risk_item(name="毛利率高于同业", rule_id="1D.RED.GROSS_MARGIN_ANOMALY",
                      status=status, impact=impact)
    if impact == "monitor":
        item["unscored_reason"] = "试图以仅跟踪名义保留退役规则"
    fill["risk_items"] = [item]
    with pytest.raises(ValueError, match="毛利率异常规则已退役"):
        R.build_risk_register(fill, sc)


def test_retired_gross_margin_watch_remains_compatible_before_change_date():
    fill = v2_fill()
    fill["risk_items"] = [_risk_item(name="毛利率高于同业",
                                     rule_id="1D.RED.GROSS_MARGIN_ANOMALY", status="watch")]
    assert "毛利率高于同业" in R.build_risk_register(fill)


def test_f_item_evidence_is_allowed_and_copied_from_quote():
    fill = v2_fill()
    fill["score_inputs"]["1D"]["f_item_evidence"] = {
        "period": "2024→2025年报",
        "items": {"profit_positive": "645.1亿元"},
    }
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(fill, d)
        out = validate_stderr(fill)
    assert "f_item_evidence" not in out


def test_f_item_evidence_cannot_use_parent_manual_evidence_to_skip_copy_check():
    fill = v2_fill()
    spec = fill["score_inputs"]["1D"]
    spec["f_item_evidence"] = {"period": "2024→2025年报",
                               "items": {"profit_positive": "645.1亿元"}}
    spec["manual_evidence"] = {
        "f_item_evidence.period": {"source": "公司年报", "note": "手工补期间"},
        "f_item_evidence.items": {"source": "公司年报", "note": "手工补整组数字"},
    }
    with tempfile.TemporaryDirectory() as d:
        payload = _quality_payload(fill)
        payload["1D"].pop("f_item_evidence")
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
    assert "f_item_evidence" in out and "落盘缺失" in out


def test_quality_inputs_manual_evidence_only_covers_missing_leaf_values():
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["f_items"]["long_debt_down"] = None
        fill["score_inputs"]["1D"]["manual_evidence"] = {
            "f_items.long_debt_down": {"source": "2025 年报资产负债表", "note": "两年长期有息负债逐项对照"}}
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
        assert "quality_inputs.1D.f_items.long_debt_down" not in out
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["f_items"]["long_debt_down"] = None
        fill["score_inputs"]["1D"]["manual_evidence"] = {
            "f_items.long_debt_down": {"source": "2025 年报资产负债表", "note": ""}}
        fill = _prepare_quality_quote(fill, d, payload)
        assert "quality_inputs.1D.f_items.long_debt_down" in validate_stderr(fill)
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["f_items"]["long_debt_down"] = None
        fill["score_inputs"]["1D"]["manual_evidence"] = {
            "f_items": {"source": "2025 年报", "note": "父级说明不得放行"}}
        fill = _prepare_quality_quote(fill, d, payload)
        assert "quality_inputs.1D.f_items.long_debt_down" in validate_stderr(fill)
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        payload = _quality_payload(fill)
        payload["1D"]["liquidity"]["short_cover"] = 4.176949825639379
        fill["score_inputs"]["1D"]["liquidity"]["short_cover"] = 60
        fill["score_inputs"]["1D"]["manual_evidence"] = {
            "liquidity.short_cover": {"source": "估算说明", "note": "不得覆盖机械值"}}
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
        assert "不一致" in out and "short_cover" in out


def test_manual_evidence_closes_unobtained_f_item_evidence_leaf():
    names = ["profit_positive", "ocf_positive", "roa_improving", "cash_quality_ok",
             "long_debt_down", "short_cover_improving", "no_dilution",
             "gross_margin_improving", "asset_turnover_improving"]

    def _case(fill_value, fact_text, manual, ref_fact="未获取"):
        fill = v2_fill()
        spec = fill["score_inputs"]["1D"]
        spec["f_item_evidence"] = {
            "period": "2024→2025年报",
            "items": {name: ("未获取" if name == "long_debt_down" else "100.0 → 90.0亿元（-10.0%）")
                      for name in names}}
        payload = _quality_payload(fill)
        payload["1D"]["f_items"]["long_debt_down"] = None
        payload["1D"]["f_item_evidence"]["items"]["long_debt_down"] = ref_fact
        spec["f_items"]["long_debt_down"] = fill_value
        spec["f_item_evidence"]["items"]["long_debt_down"] = fact_text
        if manual:
            spec["manual_evidence"] = manual
        with tempfile.TemporaryDirectory() as d:
            fill = _prepare_quality_quote(fill, d, payload)
            return validate_stderr(fill)

    bool_evidence = {"source": "2025 年报资产负债表", "note": "应付债券余额为0，长期有息负债逐项核对"}
    fact_evidence = {"source": "2025 年报资产负债表", "note": "应付债券为0，长期借款 8.0 → 6.0亿元"}
    # 人工补入布尔与实际证据文本（叶级 source+note）：告警关闭
    out = _case(True, "0.0 → 0.0亿元（0.0%）",
                {"f_items.long_debt_down": bool_evidence,
                 "f_item_evidence.items.long_debt_down": fact_evidence})
    assert "quality_inputs.1D.f_items.long_debt_down" not in out
    assert "quality_inputs.1D.f_item_evidence.items.long_debt_down" not in out
    # 只改布尔值、证据仍“未获取”：证据断链告警
    out = _case(True, "未获取", {"f_items.long_debt_down": bool_evidence})
    assert "1D.f_items.long_debt_down" in out and "未获取" in out
    # 补了文本但缺叶级 source+note：仍告警
    out = _case(True, "0.0 → 0.0亿元（0.0%）", {"f_item_evidence.items": fact_evidence})
    assert "quality_inputs.1D.f_item_evidence.items.long_debt_down" in out
    # 落盘已有实际数值时不得覆盖冲突值
    out = _case(True, "0.0 → 0.0亿元（0.0%）",
                {"f_item_evidence.items.long_debt_down": fact_evidence},
                ref_fact="100.0 → 90.0亿元（-10.0%）")
    assert "quality_inputs.1D.f_item_evidence.items.long_debt_down" in out
    assert "不一致" in out


def test_f_items_bool_filled_but_fact_unobtained_with_whitespace_warns():
    """债务布尔断链检查：事实「未获取」带首尾空白时也必须告警（统一 strip 比较）。"""
    fill = v2_fill()
    spec = fill["score_inputs"]["1D"]
    names = ["profit_positive", "ocf_positive", "roa_improving", "cash_quality_ok",
             "long_debt_down", "short_cover_improving", "no_dilution",
             "gross_margin_improving", "asset_turnover_improving"]
    spec["f_item_evidence"] = {
        "period": "2024→2025年报",
        "items": {name: ("  未获取  " if name == "long_debt_down" else "100.0 → 90.0亿元（-10.0%）")
                  for name in names}}
    payload = _quality_payload(fill)
    payload["1D"]["f_item_evidence"]["items"]["long_debt_down"] = "  未获取  "
    spec["f_items"]["long_debt_down"] = True
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
    assert "1D.f_items.long_debt_down" in out and "仍为未获取" in out


def test_quality_inputs_profile_and_future_dates_are_rejected():
    fill = v2_fill()
    payload = _quality_payload(fill)
    fill["industry_profile"] = "pharma_device"
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(fill, d, payload)
        expect_valueerror(fill, kw="industry_profile")
    fill = v2_fill()
    payload = _quality_payload(fill)
    payload["as_of"] = "2026-10-25"
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(fill, d, payload)
        expect_valueerror(fill, kw="报告日之后")
    fill = v2_fill()
    payload = _quality_payload(fill)
    payload["meta"]["latest_ann_date"] = "20261025"
    with tempfile.TemporaryDirectory() as d:
        fill = _prepare_quality_quote(fill, d, payload)
        expect_valueerror(fill, kw="报告日之后")


def test_missing_quality_inputs_package_warns():
    fill = v2_fill()
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": fill["price"], "pe_ttm": fill["pe_ttm"]}, d, name="_em_quote.json")
        fill["quote"] = {"source_file": ref, "date": fill["date"]}
        out = validate_stderr(fill)
    assert "quality_inputs" in out and "--quality-v2" in out


def test_v2_preflight_accepts_single_quoted_data_dim():
    fill = v2_fill()
    for key in ("1A", "1B", "1C", "1D", "1E", "1F", "3A", "3B", "3C"):
        field = "l1_html" if key.startswith("1") else "l3_html"
        fill[field] = fill[field].replace(f'data-dim="{key}"', f"data-dim='{key}'")
    html = render_v2_fill(fill)
    assert "SCORE_BADGE" not in html and "SCORE_DETAIL" not in html
    assert html.count('class="badge') >= 9


def test_v2_preflight_rejects_malformed_data_dim():
    for malformed in ("data-dim=1A", 'data-dim="1A>'):
        fill = v2_fill()
        fill["l1_html"] = fill["l1_html"].replace('data-dim="1A"><', malformed + '<')
        with tempfile.TemporaryDirectory() as d:
            path = write_fill(prepare_v2_quote(fill, d), d)
            try:
                R._preflight(path)
            except ValueError as exc:
                assert "data-dim" in str(exc) and "1A" in str(exc)
            else:
                raise AssertionError("无引号或未闭合 data-dim 必须拒绝")


def test_v2_preflight_aggregates_counter_evidence_and_anchor_errors():
    fill = v2_fill()
    fill["score_inputs"]["1A"].pop("counter_evidence")
    fill["score_inputs"]["1C"].pop("counter_evidence")
    fill["l1_html"] = fill["l1_html"].replace('data-dim="1B"', 'data-dim-x="1B"')
    with tempfile.TemporaryDirectory() as d:
        path = write_fill(prepare_v2_quote(fill, d), d)
        try:
            R._preflight(path)
        except ValueError as exc:
            message = str(exc)
            assert all(key in message for key in ("1A", "1C", "1B", "data-dim"))
        else:
            raise AssertionError("组合错误必须一次全部报告")


def test_risk_rule_id_requires_actual_negative_fact():
    fill = _with_red_flag(v2_fill(risk_items=[
        _risk_item(name="盈利为负", rule_id="1D.PROFIT_POSITIVE", evidence="本期净利润为负")]))
    assert "未实际命中" in _risk_error(fill)
    fill["score_inputs"]["1D"]["f_items"]["profit_positive"] = False
    html = R.build_risk_register(fill)
    assert "盈利为负" in html


def test_quality_inputs_normalized_roic_does_not_compare_latest_period_fields():
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        spec = fill["score_inputs"]["1F"]
        spec.update(roic=0.07065, roic_basis="normalized",
                    roic_normalized_components=[0.07065, 0.0821, 0.06869])
        spec.pop("roic_period_months")
        payload = _quality_payload(fill)
        payload["1F"].update(roic=-0.022456, roic_basis="latest", roic_period_months=9)
        fill = _prepare_quality_quote(fill, d, payload)
        out = validate_stderr(fill)
        assert "quality_inputs.1F.roic " not in out
        assert "quality_inputs.1F.roic_basis" not in out
        assert "quality_inputs.1F.roic_period_months" not in out


def test_peers_waiver_accepts_existing_chinese_wording():
    fill = minimal_fill(
        peers_meta="市值列不作最优最差标注。",
        peers_html=('<div class="table-scroll"><table><tr><th>公司</th><th>市值(亿)</th>'
                    '<th>PE(TTM)</th></tr><tr><td>测试股份</td><td>100</td>'
                    '<td class="cell-best">11</td></tr><tr><td>同业甲</td><td>48.4</td>'
                    '<td class="cell-worst">25</td></tr></table></div>'
                    '<span class="source">数据来源：公开行情</span>'))
    assert "数值列缺最优/最差标注" not in validate_stderr(fill)


def test_v2_dimension_requires_judgment_evidence_and_comparison():
    fill = v2_fill(date="2026-11-01")
    start = fill["l1_html"].index('<div class="dim-block" data-dim="1A">')
    end = fill["l1_html"].index('<div class="dim-block" data-dim="1B">')
    fill["l1_html"] = (fill["l1_html"][:start]
                       + '<div class="dim-block" data-dim="1A"><div class="dim-header">'
                         '<span class="dim-name">4.1 赛道与宏观</span><!--SCORE_BADGE--></div>'
                         '<p>行业收入增长 20%，仅罗列行业叙事，没有判词与对比，但这段文字足够长以避免触发其他字数门禁。</p><!--SCORE_DETAIL--></div>'
                       + fill["l1_html"][end:])
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "九维正文四要素", kw="四要素")


def test_growth_consensus_year_cannot_be_omitted_for_new_report():
    fill = minimal_fill(
        date="2026-10-31",
        quote={"source_file": _period_ref_file("v0122_consensus_year", {"consensus_np": 120})},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2027E", "np_lo": 12, "np_hi": 20}]})
    from validate_audit import _check_growth_consistency
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "一致预期" in str(exc) and "2026E" in str(exc)
    else:
        raise AssertionError("落盘有 2026 共识而预测图整年缺失，应拒渲染")


def test_quality_inputs_normalized_roic_still_checks_matching_normalized_payload():
    with tempfile.TemporaryDirectory() as d:
        fill = v2_fill()
        spec = fill["score_inputs"]["1F"]
        spec.update(roic=0.07065, roic_basis="normalized",
                    roic_normalized_components=[0.07065, 0.0821, 0.06869],
                    roic_period_months=12)
        payload = _quality_payload(fill)
        payload["1F"].update(roic_basis="normalized", roic_latest=0.1,
                             roic_normalized_components=[0.07065, 0.0821, 0.06869])
        fill = _prepare_quality_quote(fill, d, payload)
        assert "quality_inputs.1F.roic" not in validate_stderr(fill)
        payload["1F"]["roic"] = 0.09
        fill = _prepare_quality_quote(fill, d, payload)
        assert "quality_inputs.1F.roic 与落盘不一致" in validate_stderr(fill)


def test_growth_consensus_empty_row_does_not_satisfy_required_year():
    fill = minimal_fill(
        date="2026-10-31",
        quote={"source_file": _period_ref_file("v0122_empty_consensus", {"consensus_np": 120})},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E"}, {"y": "2027E", "np_lo": 12, "np_hi": 20}]})
    from validate_audit import _check_growth_consistency
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "一致预期" in str(exc) and "2026E" in str(exc)
    else:
        raise AssertionError("空壳 2026E 行不得绕过共识缺年门禁")


def test_growth_base_scenario_uses_only_own_profit_path():
    fill = minimal_fill(
        date="2026-10-31",
        quote={"source_file": _period_ref_file("v0122_base_next_year", {"consensus_np": 120})},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_consensus": 20},
                              {"y": "2027E", "np_lo": 5, "np_hi": 10}]})
    fill["valuation"]["scenarios"][1]["profit"] = 200
    from validate_audit import _check_growth_consistency
    warns = []
    _check_growth_consistency(fill, warns)
    out = "\n".join(warns)
    assert "基础情景换算增速" not in out and "本文利润路径" not in out, \
        "缺本文利润年份证据时不得拿卖方一致预期作分母"

    fill["gap_plot"] = {"dims": [
        {"name": "2026E归母净利（亿元）", "ours": 120, "consensus": 120},
        {"name": "2027E归母净利（亿元）", "ours": 200, "consensus": 240}]}
    warns = []
    _check_growth_consistency(fill, warns)
    out = "\n".join(warns)
    assert "本文利润路径" in out and "66.7" in out, \
        "相邻本文利润齐全时才应按200/120−1校验2027区间"


def _byd_growth_fill():
    fill = minimal_fill(
        quote={"source_file": _period_ref_file("byd_growth_year", {"consensus_np": 407.6})},
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿",
                                      "values": [300.4, 402.5, 326.2]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 80.7}, {"y": "2024", "np": 34.0},
                              {"y": "2025", "np": -19.0}],
                     "fcst": [{"y": "2026E", "np_lo": -10, "np_hi": 5, "np_consensus": 24.95},
                              {"y": "2027E", "np_lo": 10, "np_hi": 35}]},
        gap_plot={"dims": [
            {"name": "2026E归母净利（亿元）", "ours": 330, "consensus": 407.6},
            {"name": "2027E归母净利（亿元）", "ours": 400, "consensus": 528.36}]})
    fill["valuation"]["scenarios"][1]["profit"] = 400
    return fill


def test_growth_consistency_uses_base_profit_year():
    from validate_audit import _check_growth_consistency
    fill = _byd_growth_fill()
    warns = []
    _check_growth_consistency(fill, warns)
    out = "\n".join(warns)
    assert "基础情景换算增速" not in out and "本文利润路径" not in out, \
        "2027基础利润不得错配到2026，也不得使用卖方407.6作分母"

    fill["growth_plot"]["fcst"][1]["np_lo"] = 0
    fill["growth_plot"]["fcst"][1]["np_hi"] = 10
    warns = []
    _check_growth_consistency(fill, warns)
    out = "\n".join(warns)
    assert "本文利润路径" in out and "21.2" in out


def test_growth_score_3a_matches_only_base_year_single_row():
    from validate_audit import _check_growth_consistency
    fill = _byd_growth_fill()
    fill["quality_version"] = 2
    fill["score_inputs"] = {"3A": {"growth_lo": 10, "growth_hi": 30}}
    warns = []
    _check_growth_consistency(fill, warns)
    assert "3A 增速区间" in "\n".join(warns), "2027[10,35]与3A[10,30]应提示不一致"

    fill["growth_plot"]["fcst"][1]["np_hi"] = 30
    warns = []
    _check_growth_consistency(fill, warns)
    assert "3A 增速区间" not in "\n".join(warns), "2026区间不参与2027的3A对照"

    fill["growth_plot"]["fcst"] = [
        {"y": "2026E", "np_consensus": 24.95},
        {"y": "2026-27E", "np_lo": 10, "np_hi": 30}]
    warns = []
    _check_growth_consistency(fill, warns)
    assert "3A 增速区间" in "\n".join(warns), "合并行不得冒充基础年份的单年区间"


def test_growth_score_3a_skips_when_base_year_unknown():
    from validate_audit import _check_growth_consistency
    warns = []
    _check_growth_consistency(v2_fill(), warns)
    assert "3A 增速区间" not in "\n".join(warns), "缺利润年份证据不得扩大既有v2告警面"


def test_growth_score_3a_accepts_string_quality_version():
    from validate_audit import _check_growth_consistency
    fill = _byd_growth_fill()
    fill["quality_version"] = "2"
    fill["score_inputs"] = {"3A": {"growth_lo": 10, "growth_hi": 30}}
    warns = []
    _check_growth_consistency(fill, warns)
    assert "3A 增速区间" in "\n".join(warns)


def _yifeng_growth_fill():
    fill = minimal_fill(
        date="2026-11-03", quality_version=2,
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿",
                                      "values": [14.1, 15.3, 16.78]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 13.59}, {"y": "2024", "np": 8.3},
                              {"y": "2025", "np": 9.8}],
                     "fcst": [{"y": "2026E", "np_lo": 4.3, "np_hi": 16.8}]},
        gap_plot={"dims": [{"name": "2026E归母净利（亿元）", "ours": 18.9, "consensus": 19.09}]},
        score_inputs={"3A": {"growth_lo": 4.3, "growth_hi": 16.8}})
    for scenario, profit in zip(fill["valuation"]["scenarios"], (17.5, 18.9, 19.6)):
        scenario["profit"] = profit
    return fill


def _new_growth_view_fill():
    fill = _yifeng_growth_fill()
    fill["date"] = "2026-11-04"
    fill["valuation"]["profit_year"] = 2026
    fill["score_inputs"]["3A"] = {"driver_status": "部分兑现"}
    fill["growth_plot"]["fcst"] = [{"y": "2026E"}]
    fill["gap_plot"]["dims"] = [{"name": "2026E归母净利（亿元）", "consensus": 19.09}]
    return fill


def test_growth_view_derives_next_year_single_source():
    from scoring import normalize_growth_fill
    fill = _new_growth_view_fill()
    before = repr(fill)
    normalized = normalize_growth_fill(fill)
    assert normalized["score_inputs"]["3A"]["growth_lo"] == 4.3
    assert normalized["score_inputs"]["3A"]["growth_hi"] == 16.8
    assert normalized["growth_plot"]["fcst"][0]["np_lo"] == 4.3
    assert normalized["growth_plot"]["fcst"][0]["np_hi"] == 16.8
    assert normalized["gap_plot"]["dims"][0]["ours"] == 18.9
    assert repr(fill) == before, "规范化不得修改原始 fill"


def test_growth_view_scenario_changes_update_derived_consumers():
    from scoring import normalize_growth_fill
    boundary = _new_growth_view_fill()
    boundary["valuation"]["scenarios"][0]["profit"] = 17.6
    normalized = normalize_growth_fill(boundary)
    assert normalized["score_inputs"]["3A"]["growth_lo"] == 4.9
    assert normalized["growth_plot"]["fcst"][0]["np_lo"] == 4.9

    base = _new_growth_view_fill()
    base["valuation"]["scenarios"][1]["profit"] = 19.0
    normalized = normalize_growth_fill(base)
    assert normalized["gap_plot"]["dims"][0]["ours"] == 19.0


def test_growth_view_rejects_manual_derived_fields_for_new_report():
    from scoring import normalize_growth_fill
    cases = [
        ("score_inputs.3A.growth_lo", lambda f: f["score_inputs"]["3A"].update(growth_lo=4.2908)),
        ("growth_plot.fcst.2026E.np_lo", lambda f: f["growth_plot"]["fcst"][0].update(np_lo=4.2908)),
        ("gap_plot.dims.2026E.ours", lambda f: f["gap_plot"]["dims"][0].update(ours=18.9)),
    ]
    for path, mutate in cases:
        fill = _new_growth_view_fill()
        mutate(fill)
        try:
            normalize_growth_fill(fill)
        except ValueError as exc:
            assert path in str(exc) and "删除重复字段" in str(exc)
        else:
            raise AssertionError(f"新报告手填可派生字段应拒绝：{path}")


def test_growth_view_normalization_is_idempotent():
    from scoring import normalize_growth_fill
    normalized = normalize_growth_fill(_new_growth_view_fill())
    assert normalize_growth_fill(normalized) == normalized


def test_growth_view_legacy_manual_fields_remain_supported():
    from scoring import normalize_growth_fill
    fill = _yifeng_growth_fill()
    fill["valuation"]["profit_year"] = 2026
    fill["score_inputs"]["3A"]["growth_lo"] = 10
    fill["gap_plot"]["dims"][0]["ours"] = 18.8
    normalized = normalize_growth_fill(fill)
    assert normalized["score_inputs"]["3A"]["growth_lo"] == 10
    assert normalized["gap_plot"]["dims"][0]["ours"] == 18.8


def test_growth_view_later_year_does_not_invent_single_year_growth():
    from scoring import normalize_growth_fill
    fill = _new_growth_view_fill()
    fill["valuation"]["profit_year"] = 2027
    fill["score_inputs"]["3A"].update(growth_lo=10, growth_hi=30)
    fill["growth_plot"]["fcst"] = [{"y": "2026-27E", "np_lo": 10, "np_hi": 35}]
    fill["gap_plot"]["dims"] = [{"name": "2027E归母净利（亿元）", "consensus": 19.09}]
    normalized = normalize_growth_fill(fill)
    assert normalized["score_inputs"]["3A"]["growth_lo"] == 10
    assert normalized["growth_plot"]["fcst"][0] == {"y": "2026-27E", "np_lo": 10, "np_hi": 35}
    assert normalized["gap_plot"]["dims"][0]["ours"] == 18.9


def test_growth_view_nonpositive_or_missing_actual_does_not_invent_growth():
    from scoring import normalize_growth_fill
    for actual in (0, -1, None):
        fill = _new_growth_view_fill()
        if actual is None:
            fill["fin_trend"] = {}
        else:
            fill["fin_trend"]["panels"][0]["bars"][0]["values"][-1] = actual
        normalized = normalize_growth_fill(fill)
        assert "growth_lo" not in normalized["score_inputs"]["3A"]
        assert "np_lo" not in normalized["growth_plot"]["fcst"][0]


def test_growth_view_mcap_and_missing_profit_year_boundaries():
    from scoring import normalize_growth_fill
    mcap = _new_growth_view_fill()
    mcap["valuation"].pop("profit_year")
    for scenario in mcap["valuation"]["scenarios"]:
        scenario.pop("profit")
        scenario.pop("pe")
        scenario["mcap"] = [100, 120]
    normalized = normalize_growth_fill(mcap)
    assert "profit_year" not in normalized["valuation"]

    missing = _new_growth_view_fill()
    missing["valuation"].pop("profit_year")
    try:
        normalize_growth_fill(missing)
    except ValueError as exc:
        assert "valuation.profit_year" in str(exc)
    else:
        raise AssertionError("新利润口径报告缺 profit_year 应明确拒绝")


def test_growth_view_mixed_currency_does_not_derive():
    from scoring import normalize_growth_fill
    fill = _new_growth_view_fill()
    fill["currency"] = "港元"
    normalized = normalize_growth_fill(fill)
    assert "growth_lo" not in normalized["score_inputs"]["3A"]
    assert "np_lo" not in normalized["growth_plot"]["fcst"][0]
    assert normalized["gap_plot"]["dims"][0]["ours"] == 18.9


def test_growth_cumulative_scenario_range_checked_when_profit_path_known():
    from validate_audit import _check_growth_consistency
    fill = _byd_growth_fill()
    fill["date"] = "2026-11-04"
    fill["quality_version"] = 2
    fill["valuation"]["profit_year"] = 2027
    for scenario, profit in zip(fill["valuation"]["scenarios"], (280, 400, 480)):
        scenario["profit"] = profit
    fill["growth_plot"]["fcst"] = [
        {"y": "2026E", "np_consensus": 24.95},
        {"y": "2026-27E", "np_lo": 10, "np_hi": 35},
    ]
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "累计增速" in str(exc) and "47.1" in str(exc)
    else:
        raise AssertionError("合并年度区间未覆盖三情景累计增速应拒绝")

    fill["growth_plot"]["fcst"][1].update(np_lo=-15, np_hi=48)
    warns = []
    _check_growth_consistency(fill, warns)
    assert "累计增速" not in "\n".join(warns)


def test_growth_cumulative_row_missing_bounds_gets_readable_rejection():
    from validate_audit import _check_growth_consistency
    fill = _byd_growth_fill()
    fill["date"] = "2026-11-04"
    fill["valuation"]["profit_year"] = 2027
    fill["growth_plot"]["fcst"] = [{"y": "2026-27E"}]
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "np_lo/np_hi" in str(exc) and "累计区间" in str(exc)
    except TypeError as exc:
        raise AssertionError(f"缺区间应给可读 ValueError，而非 TypeError: {exc}")
    else:
        raise AssertionError("合并行缺累计区间必须拒绝")


def test_growth_view_rejects_non_four_digit_profit_year():
    from scoring import normalize_growth_fill
    for invalid in ("2026E", "2026-27"):
        fill = _new_growth_view_fill()
        fill["valuation"]["profit_year"] = invalid
        try:
            normalize_growth_fill(fill)
        except ValueError as exc:
            assert "profit_year" in str(exc) and "四位年度" in str(exc)
        else:
            raise AssertionError(f"非法 profit_year 应拒绝：{invalid}")


def test_growth_plot_labels_interval_midpoint_not_base_central():
    from charts_misc import build_growth_plot
    fill = _yifeng_growth_fill()
    fill["growth_plot"]["fcst"][0]["np_consensus"] = 13.73
    html = build_growth_plot(fill)
    assert "区间中点−一致预期" in html
    assert "本文中枢−一致预期" not in html


def test_growth_score_3a_mismatch_rejected_for_new_report():
    from validate_audit import _check_growth_consistency
    fill = _yifeng_growth_fill()
    fill["score_inputs"]["3A"].update(growth_lo=10, growth_hi=14)
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "3A 增速区间" in str(exc)
    else:
        raise AssertionError("新报告的3A与增长图不一致不得只告警")


def test_growth_plot_cannot_narrow_to_match_score():
    from validate_audit import _check_growth_consistency
    fill = _yifeng_growth_fill()
    fill["growth_plot"]["fcst"][0].update(np_lo=10, np_hi=14)
    fill["score_inputs"]["3A"].update(growth_lo=10, growth_hi=14)
    try:
        _check_growth_consistency(fill, [])
    except ValueError as exc:
        assert "三情景" in str(exc) and "收窄" in str(exc)
    else:
        raise AssertionError("不得通过收窄增长图来迎合3A评分区间")


def test_growth_three_way_consistency_and_legacy_boundaries():
    from validate_audit import _check_growth_consistency
    warns = []
    _check_growth_consistency(_yifeng_growth_fill(), warns)
    out = "\n".join(warns)
    assert "3A 增速区间" not in out and "三情景" not in out

    legacy = _yifeng_growth_fill()
    legacy["date"] = "2026-11-02"
    legacy["score_inputs"]["3A"].update(growth_lo=10, growth_hi=14)
    warns = []
    _check_growth_consistency(legacy, warns)
    assert "3A 增速区间" in "\n".join(warns)

    unknown_year = _yifeng_growth_fill()
    unknown_year["gap_plot"] = None
    unknown_year["score_inputs"]["3A"].update(growth_lo=10, growth_hi=14)
    warns = []
    _check_growth_consistency(unknown_year, warns)
    assert "3A 增速区间" not in "\n".join(warns)

    nonpositive = _yifeng_growth_fill()
    nonpositive["fin_trend"]["panels"][0]["bars"][0]["values"][-1] = 0
    nonpositive["growth_plot"]["fcst"] = []
    warns = []
    _check_growth_consistency(nonpositive, warns)
    assert "3A 增速区间" not in "\n".join(warns)


@pytest.mark.parametrize("fragment, tag", [
    ("<p>质押比例<strong>1.72%</strong%；实控人</p>", "strong"),
    ("<p><strong>未闭合</p>", "strong"),
    ("<p><strong>甲<em>乙</strong></em></p>", "em"),
])
def test_inline_html_balance_rejects_malformed_tags(fragment, tag):
    fill = minimal_fill(p0_html=fragment)
    with pytest.raises(ValueError) as exc:
        R.validate_content(fill, R.compute_valuation(fill))
    message = str(exc.value)
    assert "p0_html" in message and "行内 HTML" in message
    assert tag in message


def test_inline_html_balance_accepts_closed_nested_and_void_tags():
    fill = minimal_fill(
        p0_html="<p>质押比例<strong>1.72%</strong>%；"
                "<span>正常<em>嵌套</em></span><br>后文</p>")
    R.validate_content(fill, R.compute_valuation(fill))


def test_final_dimensions_reuse_four_element_contract():
    from validate_html import check_final_dimensions
    fill = v2_fill(date="2026-11-01", cycle_html="<p>估值周期位置与可比时段分析。</p>")
    html = render_v2_fill(fill)
    sc = R.compute_scores(fill)
    check_final_dimensions(html, fill, sc)

    missing = re.sub(r"<p><strong>论据：</strong>.*?</p>", "", html, count=1, flags=re.S)
    try:
        check_final_dimensions(missing, fill, sc)
    except ValueError as exc:
        assert "4.1" in str(exc) and "论据" in str(exc)
    else:
        raise AssertionError("最终 HTML 缺独立论据段必须拒绝")

    duplicated = html.replace("<p><strong>判词：", "<p><strong>判词：", 1)
    first = duplicated.index("<p><strong>判词：")
    end = duplicated.index("</p>", first) + 4
    duplicated = duplicated[:end] + duplicated[first:end] + duplicated[end:]
    try:
        check_final_dimensions(duplicated, fill, sc)
    except ValueError as exc:
        assert "4.1" in str(exc) and "判词" in str(exc)
    else:
        raise AssertionError("最终 HTML 重复判词段必须拒绝")


def test_final_review_chart_gap_uses_existing_reason_rules():
    from validate_charts import check_final_review_charts
    fill = _byd_growth_fill()
    fill["date"] = "2026-11-04"
    fill["prev"] = {"charts": {"price_history": True}}
    fill["review_html"] = ""
    try:
        check_final_review_charts(fill)
    except ValueError as exc:
        assert "price_history" in str(exc) and "减配" in str(exc)
    else:
        raise AssertionError("新复盘旧图减少且无原因应拒绝")

    fill["review_html"] = "<p>股价季K不生成：高速成长禁填且全历史区间失真，改用可比时段。</p>"
    check_final_review_charts(fill)
    fill["review_html"] = ""
    fill["date"] = "2026-11-03"
    check_final_review_charts(fill)


def test_preflight_aggregates_independent_content_errors():
    fill = v2_fill(date="2026-11-02")
    fill["position_html"] += "<p>建议加仓。</p>"
    fill["score_inputs"]["1F"].pop("counter_evidence")
    comparison = "<p><strong>对比：</strong>公司波动高于同业 10% 的基准，反方证据仍需保留。</p>"
    head, found, tail = fill["l3_html"].rpartition(comparison)
    assert found
    fill["l3_html"] = head + tail
    with tempfile.TemporaryDirectory() as d:
        path = write_fill(prepare_v2_quote(fill, d), d)
        try:
            R._preflight(path)
        except ValueError as exc:
            message = str(exc)
            assert "position_html 含交易节奏" in message
            assert "1F 得分" in message and "反方证据" in message
            assert "5.3 催化剂" in message and "对比基准" in message
        else:
            raise AssertionError("组合正文错误必须拒绝并一次报全")


def _growth_profit_fill(profit):
    fill = minimal_fill(
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿",
                                      "values": [80.0, 90.0, 100.0]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10}]})
    fill["valuation"]["scenarios"][1]["profit"] = profit
    return fill


def test_growth_base_year_allows_zero_and_negative_profit():
    from validate_audit import _check_growth_consistency
    for profit in (0, -50):
        fill = _growth_profit_fill(profit)
        fill["gap_plot"] = {"dims": [{"name": "2026E归母净利（亿元）", "ours": profit, "consensus": 100}]}
        warns = []
        _check_growth_consistency(fill, warns)
        assert "基础情景换算增速" in "\n".join(warns), f"基础利润{profit}不得静默跳过校验"


def test_growth_gap_dims_filter_and_order_invariance():
    from validate_audit import _check_growth_consistency
    dims = [
        {"name": "2026E归母净利（亿元）", "ours": 100, "consensus": 110},
        {"name": "2026E扣非净利（亿元）", "ours": 90, "consensus": 95},
        {"name": "2026E净利率（%）", "ours": 8, "consensus": 9}]
    outputs = []
    for ordered in (dims, list(reversed(dims))):
        fill = _growth_profit_fill(100)
        fill["gap_plot"] = {"dims": ordered}
        warns = []
        _check_growth_consistency(fill, warns)
        outputs.append("\n".join(warns))
    assert all("基础情景换算增速" in out for out in outputs), \
        "扣非/净利率不得污染归母路径或让告警随顺序消失"
    assert outputs[0] == outputs[1]


def test_segments_gross_profit_share_total_is_checked():
    from validate_charts import _check_optional_charts
    fill = minimal_fill(segments={"items": [
        {"name": "A", "rev_pct": 50, "gross_profit": 60, "gp_pct": 60},
        {"name": "B", "rev_pct": 50, "gross_profit": 40, "gp_pct": 50}]})
    warns = []
    _check_optional_charts(fill, warns)
    assert "毛利占比合计" in "\n".join(warns)


def test_v2_four_beats_is_warning_for_legacy_fill():
    fill = v2_fill()
    fill["l1_html"] = fill["l1_html"].replace("<strong>对比：</strong>", "<strong>历史：</strong>", 1)
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        out = validate_stderr(fill)
        assert "四要素" in out


def test_profile_contract_covers_all_profiles_and_rejects_unknown_keys():
    from validate_audit import _check_quality_profile_contract
    from quality_rules import PROFILE_KIND
    for profile, kind in PROFILE_KIND.items():
        fill = v2_fill(date="2026-11-01", industry_profile=profile)
        fill["score_inputs"]["1D"] = {"kind": kind, "counter_evidence": "反方证据", "note": "补充说明"}
        warns = []
        _check_quality_profile_contract(fill, warns)
        assert warns == [], (profile, warns)
        fill["score_inputs"]["1D"]["bogus"] = True
        try:
            _check_quality_profile_contract(fill, [])
        except ValueError as exc:
            assert "bogus" in str(exc) and profile in str(exc)
        else:
            raise AssertionError(f"{profile} 未登记键应拒渲染")


def test_profile_contract_rejects_generic_industry_checks_but_warns_legacy():
    from validate_audit import _check_quality_profile_contract
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1D"]["industry_checks"] = {"order_cancellation": True}
    try:
        _check_quality_profile_contract(fill, [])
    except ValueError as exc:
        assert "industry_checks" in str(exc)
    else:
        raise AssertionError("通用 F 错用 industry_checks 应拒渲染")
    fill["date"] = "2026-10-24"
    warns = []
    _check_quality_profile_contract(fill, warns)
    assert "industry_checks" in "\n".join(warns)


def test_profile_contract_rejects_unknown_industry_flag():
    from validate_audit import _check_quality_profile_contract
    fill = v2_fill(date="2026-11-01", industry_profile="financial_bank")
    fill["score_inputs"]["1D"] = {
        "industry_checks": {"npl_trend": True, "provision_trend": False,
                            "loan_migration": False, "cet1": False, "npl_tend": True}}
    try:
        _check_quality_profile_contract(fill, [])
    except ValueError as exc:
        assert "npl_tend" in str(exc)
    else:
        raise AssertionError("未登记行业 flag 应拒渲染")


def test_profile_contract_causal_group_guard():
    from validate_audit import _check_quality_profile_contract
    from quality_rules import F_ITEM_IDS
    fill = v2_fill(date="2026-11-01")
    spec = fill["score_inputs"]["1D"]
    spec["f_items"] = {name: False for name in F_ITEM_IDS}
    spec["f_causal_groups"] = {"all_items": list(F_ITEM_IDS)}
    spec["f_causal_evidence"] = {"all_items": "公司2025年报披露同一事件影响9项"}
    try:
        _check_quality_profile_contract(fill, [])
    except ValueError as exc:
        assert "全部九项" in str(exc)
    else:
        raise AssertionError("全部九项合并应拒渲染")
    spec["f_causal_groups"] = {"asset_injection": ["long_debt_down", "no_dilution"]}
    spec["f_causal_evidence"] = {"asset_injection": "公司2025年报披露同一资产注入增加债务10亿元并增发"}
    warns = []
    _check_quality_profile_contract(fill, warns)
    assert warns == []


def test_score_detail_industry_flags_use_risk_semantics_and_labels():
    import quality_rules as qr
    spec = {"industry_checks": {"npl_trend": True, "provision_trend": False,
                                "loan_migration": False, "cet1": False}}
    result = qr.evaluate_dimension("1D", spec, {"industry_profile": "financial_bank",
                                                "report_date": "2026-11-01"})
    text = R._build_score_detail("1D", result, spec)
    assert "不良贷款趋势：未通过（风险命中）" in text
    assert "拨备覆盖趋势：通过（风险未命中）" in text


def test_immaterial_red_flag_is_visible_but_not_a_conclusion_warning():
    fill = v2_fill(date="2026-11-01")
    spec = fill["score_inputs"]["1D"]
    spec["red_flags"]["receivables"] = True
    spec["red_flag_materiality"] = {"receivables": False}
    spec["red_flag_materiality_evidence"] = {
        "receivables": {"scale": "涉及应收0.8亿元", "source": "公司2025年报"}}
    sc = R.compute_scores(fill)
    assert sc["financial_red_flags"] == []
    text = R._build_score_detail("1D", sc["dimension_results"]["1D"], spec)
    assert "应收恶化：命中但不扣分" in text


def test_cash_quality_joins_profit_authenticity_warning_with_legacy_migration():
    from validate_html import _check_red_flag_conclusion
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1D"]["f_items"]["cash_quality_ok"] = False
    fill["score_inputs"]["1D"]["red_flags"]["receivables"] = True
    sc = R.compute_scores(fill)
    assert len(sc["financial_red_flags"]) == 2
    try:
        _check_red_flag_conclusion(fill, sc, [])
    except ValueError as exc:
        assert "利润真实性存疑" in str(exc)
    else:
        raise AssertionError("现金含量与应收双命中应要求结论警示")
    fill["date"] = "2026-10-24"
    warns = []
    _check_red_flag_conclusion(fill, sc, warns)
    assert "利润真实性存疑" in "\n".join(warns)


def test_industry_warning_uses_financial_risk_wording_and_accepts_legacy_phrase():
    from validate_html import _check_red_flag_conclusion
    fill = v2_fill(date="2026-11-01", industry_profile="financial_bank")
    fill["score_inputs"]["1D"] = {
        "industry_checks": {"npl_trend": True, "provision_trend": True,
                            "loan_migration": False, "cet1": False}}
    fill["score_inputs"]["1B"] = {
        "cost_strength": "strong", "pricing_strength": "neutral", "bargaining_status": "正常",
        "customer_concentration": 0.1, "supplier_concentration": 0.1}
    fill["score_inputs"]["1F"] = {
        "return_metric": "ROE_NORMALIZED", "normalized_return": 0.12, "coe": 0.08,
        "dupont_driver": "净利率"}
    sc = R.compute_scores(fill)
    assert sc["red_total"] == 0 and len(sc["financial_red_flags"]) == 2
    try:
        _check_red_flag_conclusion(fill, sc, [])
    except ValueError as exc:
        assert "财务风险多项命中" in str(exc)
    else:
        raise AssertionError("行业双命中应要求财务风险警示")
    for phrase in ("财务风险多项命中", "利润真实性存疑"):
        fill["conclusion_html"] = phrase + "：资产质量两项恶化。" + fill["conclusion_html"]
        _check_red_flag_conclusion(fill, sc, [])
        fill["conclusion_html"] = fill["conclusion_html"].replace(phrase + "：资产质量两项恶化。", "", 1)


def test_internet_red_flag_summary_uses_chinese_label_not_bool():
    fill = v2_fill(industry_profile="internet_platform")
    fill["score_inputs"]["1B"] = {
        "cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "正常",
        "customer_concentration": 0.1, "supplier_concentration": 0.1}
    fill["score_inputs"]["1D"]["red_flags"] = {
        "adjusted_profit_divergence": True, "investment_impairment": False, "goodwill": False}
    sc = R.compute_scores(fill)
    assert sc["red_deductions"][0]["item"] == "经调整利润偏离"
    summary = R.build_score_summary(sc)
    assert "经调整利润偏离" in summary and "True" not in summary


def _risk_check(fill, home, rule_id, should_pass):
    fill["risk_items"] = [_risk_item(name="测试风险", rule_id=rule_id, home=home,
                                    evidence="与当前结构化事实一致的风险证据")]
    if should_pass:
        assert "测试风险" in R.build_risk_register(fill)
    else:
        assert "未实际命中" in _risk_error(fill)


def test_risk_active_checks_all_nine_dimensions():
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1A"]["demand_decline_2y"] = True
    _risk_check(fill, "1A", "1A.MATURE.CHECK", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1A", "1A.MATURE.CHECK", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1B"].update(cost_quartile=2, price_transmission=False)
    _risk_check(fill, "1B", "1B.VALUE_CHAIN", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1B", "1B.VALUE_CHAIN", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1C"]["moats"] = fill["score_inputs"]["1C"]["moats"][:1]
    _risk_check(fill, "1C", "1C.MOAT.COUNT", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1C", "1C.MOAT.COUNT", False)
    fill["score_inputs"]["1C"]["moats"][0]["trend"] = "narrowing"
    _risk_check(fill, "1C", "1C.MOAT.1", True)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1D"]["f_items"]["profit_positive"] = False
    _risk_check(fill, "1D", "1D.PROFIT_POSITIVE", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1D", "1D.PROFIT_POSITIVE", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1E"]["penalties"] = True
    _risk_check(fill, "1E", "1E.PENALTIES", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1E", "1E.DIVIDEND", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1F"]["roic"] = 0.04
    _risk_check(fill, "1F", "1F.ROIC_WACC", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "1F", "1F.ROIC_WACC", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["3A"].update(growth_lo=-1, driver_status="未验证")
    _risk_check(fill, "3A", "3A.GROWTH", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "3A", "3A.GROWTH", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["3B"] = {"visibility": [
        {"name": "机场与线上渠道", "level": "趋势平缓", "contribution": 1, "value": "Q3收入-4.66%"}]}
    _risk_check(fill, "3B", "3B.VISIBILITY.机场与线上渠道", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "3B", "3B.PROJECT.核心项目", False)

    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["3C"]["events"] = fill["score_inputs"]["3C"]["events"][:1]
    _risk_check(fill, "3C", "3C.EVENT_COUNT", True)
    fill = v2_fill(date="2026-11-01")
    _risk_check(fill, "3C", "3C.EVENT_COUNT", False)


def test_risk_active_rejects_positive_custom_and_not_applicable():
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1C"]["custom"] = {
        "id": "1C.CUSTOM.TEST", "points": 1, "reason": "额外优势", "evidence": "公开证据"}
    _risk_check(fill, "1C", "1C.CUSTOM.TEST", False)
    fill["score_inputs"]["1C"]["custom"]["points"] = -1
    _risk_check(fill, "1C", "1C.CUSTOM.TEST", True)

    fill = v2_fill(date="2026-11-01", industry_profile="financial_insurance")
    fill["score_inputs"]["1B"] = {
        "cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "正常",
        "customer_concentration": 0.1, "supplier_concentration": 0.1}
    fill["score_inputs"]["1F"] = {
        "return_metric": "ROE_NORMALIZED", "normalized_return": 0.12, "coe": 0.08,
        "dupont_driver": "净利率"}
    fill["score_inputs"]["1D"] = {
        "industry_checks": {"solvency": False, "combined_ratio": "not_applicable",
                            "reserve": False, "investment_assumption": False},
        "industry_check_evidence": {"combined_ratio": "纯寿险无财险综合成本率"}}
    _risk_check(fill, "1D", "1D.NOT_APPLICABLE", False)


def test_risk_active_covers_every_industry_checklist_profile():
    from quality_rules import PROFILE_FLAGS, PROFILE_KIND
    for profile in ("financial_bank", "financial_insurance", "financial_broker",
                    "realestate_development", "pharma_pipeline", "pre_profit", "turnaround"):
        fill = v2_fill(date="2026-11-01", industry_profile=profile)
        if PROFILE_KIND[profile] == "industry_checklist" and profile.startswith("financial_"):
            fill["score_inputs"]["1B"] = {
                "cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "正常",
                "customer_concentration": 0.1, "supplier_concentration": 0.1}
            fill["score_inputs"]["1F"] = {
                "return_metric": "ROE_NORMALIZED", "normalized_return": 0.12, "coe": 0.08,
                "dupont_driver": "净利率"}
        flags = {name: False for name in PROFILE_FLAGS[profile]}
        flag = sorted(flags)[0]
        flags[flag] = True
        fill["score_inputs"]["1D"] = {"industry_checks": flags}
        rule_id = f"1D.{profile.upper()}.{flag.upper()}"
        _risk_check(fill, "1D", rule_id, True)
        flags[flag] = False
        _risk_check(fill, "1D", rule_id, False)


def test_risk_active_runway_requires_no_secured_financing():
    for secured, expected in ((False, True), (True, False), (None, False)):
        fill = v2_fill(date="2026-11-01", industry_profile="pre_profit")
        fill["score_inputs"]["1D"] = {"cash_runway_months": 12, "financing_secured": secured}
        _risk_check(fill, "1D", "1D.CASH_RUNWAY", expected)
    fill = v2_fill(date="2026-11-01", industry_profile="pre_profit")
    fill["score_inputs"]["1D"] = {"cash_runway_months": 30, "financing_secured": False}
    _risk_check(fill, "1D", "1D.CASH_RUNWAY", False)


def test_risk_active_legacy_fill_warns_instead_of_rejecting():
    fill = v2_fill(date="2026-10-24")
    fill["risk_items"] = [_risk_item(name="资本回报低于资本成本", rule_id="1F.ROIC_WACC", home="1F")]
    warns = []
    html = R.build_risk_register(fill, warns=warns)
    assert "资本回报低于资本成本" in html and "未实际命中" in "\n".join(warns)


def test_monitor_hit_requires_unscored_reason():
    fill = v2_fill(date="2026-11-01", risk_items=[
        _risk_item(name="观察性风险", rule_id=None, home="dashboard", impact="monitor")])
    assert "unscored_reason" in _risk_error(fill)
    fill["risk_items"][0]["unscored_reason"] = "尚未达到任何评分阈值，仅作后续验证"
    html = R.build_risk_register(fill)
    assert "未计分原因：尚未达到任何评分阈值，仅作后续验证" in html
    fill["date"] = "2026-10-24"
    fill["risk_items"][0].pop("unscored_reason")
    warns = []
    R.build_risk_register(fill, warns=warns)
    assert "unscored_reason" in "\n".join(warns)


def test_catalyst_revaluation_requires_expectation_gap_and_observable():
    from validate_audit import _check_catalyst_evidence
    fill = v2_fill(date="2026-11-01")
    for event in fill["score_inputs"]["3C"]["events"]:
        event.pop("expectation_gap", None)
        event.pop("observable", None)
    try:
        _check_catalyst_evidence(fill, [])
    except ValueError as exc:
        assert "expectation_gap" in str(exc) and "observable" in str(exc)
    else:
        raise AssertionError("重估催化缺证据应拒渲染")
    for index, event in enumerate(fill["score_inputs"]["3C"]["events"]):
        event["expectation_gap"] = f"市场尚未计入第{index + 1}个项目的盈利贡献"
        event["observable"] = "按期投产并产生可核验收入后上调正常化利润"
    warns = []
    _check_catalyst_evidence(fill, warns)
    assert warns == []
    fill["score_inputs"]["3C"]["events"].append({
        "name": "年报验证", "month": "2027-03", "revaluation": False,
        "evidence": "公司定期报告披露计划"})
    _check_catalyst_evidence(fill, warns)
    assert warns == []


def test_catalyst_evidence_legacy_warns_and_all_profiles_share_gate():
    from validate_audit import _check_catalyst_evidence
    from quality_rules import PROFILE_KIND
    fill = v2_fill()
    for event in fill["score_inputs"]["3C"]["events"]:
        event.pop("expectation_gap", None)
        event.pop("observable", None)
    warns = []
    _check_catalyst_evidence(fill, warns)
    assert "expectation_gap" in "\n".join(warns)
    for profile in PROFILE_KIND:
        fill = v2_fill(date="2026-11-01", industry_profile=profile)
        for event in fill["score_inputs"]["3C"]["events"]:
            event.pop("expectation_gap", None)
            event.pop("observable", None)
        try:
            _check_catalyst_evidence(fill, [])
        except ValueError as exc:
            assert "expectation_gap" in str(exc)
        else:
            raise AssertionError(f"{profile} 不应绕过催化剂证据门禁")


def test_nested_weights_are_rejected_for_new_fill_and_warn_legacy():
    from validate_typing import _check_typing_v2
    nested = {"L1": {"1A": 14, "1B": 12, "1C": 18, "1D": 14, "1E": 20, "1F": 22},
              "L3": {"3A": 40, "3B": 35, "3C": 25}}
    fill = v2_fill(date="2026-11-01", weights=nested)
    try:
        _check_typing_v2(fill, [])
    except ValueError as exc:
        assert "平铺" in str(exc) and "L1" in str(exc)
    else:
        raise AssertionError("嵌套权重应拒渲染")
    fill["date"] = "2026-10-24"
    warns = []
    _check_typing_v2(fill, warns)
    assert "平铺" in "\n".join(warns)


def test_layer_share_rejects_unknown_keys():
    from validate_typing import _check_typing_v2
    fill = v2_fill(date="2026-11-01", layer_share={"L1": 70, "L3": 30, "L4": 0})
    try:
        _check_typing_v2(fill, [])
    except ValueError as exc:
        assert "layer_share" in str(exc) and "L4" in str(exc)
    else:
        raise AssertionError("layer_share 未知键应拒渲染")


def test_nondefault_types_require_weights_and_layer_share():
    from validate_typing import _check_typing_v2
    cases = [
        ("稳定价值/金融（银行）", "financial_bank", {"L1": 85, "L3": 15}, None),
        ("成熟/停滞", "generic", {"L1": 80, "L3": 20}, None),
        ("未盈利/管线", "pre_profit", {"L1": 75, "L3": 25}, None),
        ("困境反转", "turnaround", {"L1": 70, "L3": 30}, None),
        ("成长型", "generic", {"L1": 60, "L3": 40}, "high"),
    ]
    for stock_type, profile, layer_share, tier in cases:
        fill = v2_fill(date="2026-11-01", stock_type=stock_type, industry_profile=profile,
                       growth_tier=tier, layer_share=layer_share)
        fill.pop("weights", None)
        try:
            _check_typing_v2(fill, [])
        except ValueError as exc:
            assert "weights" in str(exc)
        else:
            raise AssertionError(f"{stock_type} 缺 weights 应拒渲染")
    fill = v2_fill(date="2026-11-01", stock_type="成熟/停滞", industry_profile="generic",
                   weights={"1A": 20, "1B": 10, "1C": 20, "1D": 18, "1E": 16, "1F": 16,
                            "3A": 30, "3B": 35, "3C": 35})
    fill.pop("layer_share", None)
    try:
        _check_typing_v2(fill, [])
    except ValueError as exc:
        assert "layer_share" in str(exc)
    else:
        raise AssertionError("非默认层占比缺失应拒渲染")


def test_default_type_does_not_require_weight_overrides():
    from validate_typing import _check_typing_v2
    fill = v2_fill(date="2026-11-01", stock_type="周期股", industry_profile="generic")
    fill.pop("weights", None)
    fill.pop("layer_share", None)
    warns = []
    _check_typing_v2(fill, warns)
    assert "weights" not in "\n".join(warns)


def test_missing_consensus_wording_does_not_claim_no_sell_side_coverage():
    fill = minimal_fill()
    calc = R.compute_valuation(fill)
    inputs = dict(fill["valuation_inputs"])
    vc = R.compute_valuation_score(calc, inputs)
    card = R.build_valuation_process_card(calc, vc, inputs)
    assert "未取得可核验的一致预期均值" in card
    assert "无卖方覆盖" not in card


def test_runway_is_counted_once_when_checklist_and_months_coexist():
    fill = v2_fill(industry_profile="pre_profit")
    fill["score_inputs"]["1D"] = {
        "industry_checks": {"cash_runway": True, "financing_gap": False},
        "cash_runway_months": 12, "financing_secured": False}
    sc = R.compute_scores(fill)
    assert sum(item["item"] == "现金跑道不足" for item in sc["financial_red_flags"]) == 1


def test_f_hits_uses_causal_adjusted_count_for_risk_activity():
    fill = v2_fill(date="2026-11-01")
    for name in ("long_debt_down", "no_dilution"):
        fill["score_inputs"]["1D"]["f_items"][name] = False
    fill["score_inputs"]["1D"]["f_causal_groups"] = {
        "asset_injection": ["long_debt_down", "no_dilution"]}
    fill["score_inputs"]["1D"]["f_causal_evidence"] = {
        "asset_injection": "公司2025年报披露同一资产注入增加债务10亿元并增发"}
    assert R.compute_scores(fill)["adj_scores"]["1D"] == 9
    _risk_check(fill, "1D", "1D.F.HITS", False)


def test_growth_negative_is_active_even_without_tam_and_penetration():
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1A"] = {"stage": "growth", "growth": -5, "policy": "neutral",
                                  "tam": None, "penetration": None}
    _risk_check(fill, "1A", "1A.GROWTH.CHECK", True)


def test_mature_policy_aliases_are_normalized_for_risk_activity():
    for policy in ("偏负", "suppressed"):
        fill = v2_fill(date="2026-11-01")
        fill["score_inputs"]["1A"]["policy"] = policy
        _risk_check(fill, "1A", "1A.MATURE.CHECK", True)


def test_value_chain_double_weak_is_active_without_concentration():
    fill = v2_fill(date="2026-11-01")
    fill["score_inputs"]["1B"].update(cost_quartile=4, price_transmission=False,
                                      customer_concentration=None, supplier_concentration=None)
    _risk_check(fill, "1B", "1B.VALUE_CHAIN", True)


def test_non_mapping_weights_raise_value_error_during_scoring():
    fill = v2_fill(weights=["1A"])
    try:
        R.compute_scores(fill)
    except ValueError as exc:
        assert "平铺" in str(exc)
    else:
        raise AssertionError("列表权重应给出 ValueError 而非裸 AttributeError")


def _four_element_block():
    return ("<div class=\"dim-block\" data-dim='1A'><div class='dim-header'>"
            "<span class='dim-name'>4.1 赛道与宏观</span><!--SCORE_BADGE--></div>"
            "<p><strong>判词：</strong>行业处于成熟期，政策只能提供需求下限。</p>"
            "<p><strong>论据：</strong>2026年1-9月行业销售额同比+14.9%（海口海关）。</p>"
            "<p><strong>对比：</strong>Q3增速+2.4%，低于前九月累计+14.9%，较上版放缓。</p>"
            "<p><strong>评分：</strong>总量成熟且替代不低，未满足A/B档条件。</p>"
            "<!--SCORE_DETAIL--></div>")


def test_four_elements_allow_concise_but_specific_content():
    from validate_html import _check_dim_blocks
    fill = v2_fill(date="2026-11-01", l1_html=_four_element_block(), l3_html="")
    warns = []
    _check_dim_blocks(fill, warns)
    assert "四要素" not in "\n".join(warns)


def test_four_elements_reject_missing_and_generic_content():
    from validate_html import _check_dim_blocks
    cases = [
        ("判词", "<p><strong>判词：</strong>2026年行业增长14.9%。</p>", "判词"),
        ("论据缺失", "", "论据"),
        ("空论据", "<p><strong>论据：</strong>。</p>", "量化论据"),
        ("泛论据", "<p><strong>论据：</strong>行业增长。</p>", "量化论据"),
        ("泛对比", "<p><strong>对比：</strong>行业情况。</p>", "对比基准"),
        ("泛评分", "<p><strong>评分：</strong>见评分依据。</p>", "评分理由"),
    ]
    for name, replacement, expected in cases:
        block = _four_element_block()
        if name == "判词":
            block = block.replace("<p><strong>判词：</strong>行业处于成熟期，政策只能提供需求下限。</p>", replacement)
        elif name == "论据缺失":
            block = block.replace("<p><strong>论据：</strong>2026年1-9月行业销售额同比+14.9%（海口海关）。</p>", replacement)
        elif name == "空论据" or name == "泛论据":
            block = block.replace("<p><strong>论据：</strong>2026年1-9月行业销售额同比+14.9%（海口海关）。</p>", replacement)
        elif name == "泛对比":
            block = block.replace("<p><strong>对比：</strong>Q3增速+2.4%，低于前九月累计+14.9%，较上版放缓。</p>", replacement)
        else:
            block = block.replace("<p><strong>评分：</strong>总量成熟且替代不低，未满足A/B档条件。</p>", replacement)
        fill = v2_fill(date="2026-11-01", l1_html=block, l3_html="")
        try:
            _check_dim_blocks(fill, [])
        except ValueError as exc:
            assert expected in str(exc), (name, str(exc))
        else:
            raise AssertionError(f"{name} 不应通过四要素校验")


def test_four_elements_legacy_fill_gets_migration_warning():
    from validate_html import _check_dim_blocks
    fill = v2_fill(date="2026-10-24", l1_html=_four_element_block(), l3_html="")
    fill["l1_html"] = fill["l1_html"].replace(
        "<p><strong>论据：</strong>2026年1-9月行业销售额同比+14.9%（海口海关）。</p>", "")
    fill["l1_html"] = fill["l1_html"].replace(
        "<p><strong>评分：</strong>总量成熟且替代不低，未满足A/B档条件。</p>", "")
    warns = []
    _check_dim_blocks(fill, warns)
    assert "四要素" in "\n".join(warns)
