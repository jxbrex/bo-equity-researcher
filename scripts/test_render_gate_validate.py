#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_validate.py — render_report 内容校验回归：*_validate 校验组 + sensitivity 业务线覆盖硬闸（B4）域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import (
    minimal_fill, expect_valueerror, validate_stderr, write_fill,
    _period_ref_file, v2_fill, prepare_v2_quote, render_v2_fill,
)

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
        fin_trend={"years": ["2023", "2024", "2025"], "panels": [
            {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
            {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
            {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
        growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                              {"y": "2025", "np": 12.0}],
                     "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10, "np_consensus": 15}]}))
    assert "np_consensus" in warns and "基础情景换算增速" in warns


def test_growth_consensus_skips_cumulative_year_ranges():
    for label in ("2026-27E", "2026-2027E"):
        fill = minimal_fill(
            quote={"source_file": _period_ref_file("v512_g", {"consensus_np": 120})},
            fin_trend={"years": ["2023", "2024", "2025"], "panels": [
                {"title": "盈利", "bars": [{"name": "归母净利", "unit": "亿", "values": [80.0, 90.0, 100.0]}]},
                {"title": "营收", "bars": [{"name": "营收", "unit": "亿", "values": [800.0, 900.0, 1000.0]}]},
                {"title": "毛利", "lines": [{"name": "毛利率", "pct": True, "values": [29.0, 30.0, 31.0]}]}]},
            growth_plot={"hist": [{"y": "2023", "np": 10.0}, {"y": "2024", "np": 11.0},
                                  {"y": "2025", "np": 12.0}],
                         "fcst": [{"y": label, "np_lo": -50, "np_hi": 100, "np_consensus": 56.9}]})
        out = validate_stderr(fill)
        assert "np_consensus" not in out and "基础情景换算增速" not in out


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


def test_risk_register_four_impacts_and_unknown_is_not_pass():
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
    assert "质量" in html and "估值" in html and "时机" in html and "仅跟踪" in html
    assert "未核实" in html
    assert "通过" not in html
    assert "风险事实" in html and "证据与当前值" in html and "影响去向" in html and "跟踪指标" in html


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
    assert "风险事实" in html and "证据与当前值" in html and "影响去向" in html
    assert "flag-hero-card" in html and "pm-grid" in html
    assert "黄灯扣分" not in html
    assert "公司公告" in html
    assert "1D.RED.RECEIVABLES" in html
    assert "<!--RISK_REGISTER-->" not in html
    assert "统一风险登记" in html
    output = capsys.readouterr().out
    assert "无独立风险扣分" in output
    assert "黄灯" not in output


def _quality_payload(fill):
    import copy
    fields = {"1D": ("f_items", "liquidity", "red_flags", "cash_runway_months"),
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


def test_v2_preflight_rejects_single_quoted_data_dim():
    fill = v2_fill()
    fill["l1_html"] = fill["l1_html"].replace('data-dim="1A"', "data-dim='1A'")
    with tempfile.TemporaryDirectory() as d:
        path = write_fill(prepare_v2_quote(fill, d), d)
        try:
            R._preflight(path)
        except ValueError as exc:
            assert "data-dim" in str(exc) and "1A" in str(exc)
        else:
            raise AssertionError("预检应拒绝单引号 data-dim，而不是等到正式渲染才失败")


def test_risk_rule_id_requires_actual_negative_fact():
    fill = _with_red_flag(v2_fill(risk_items=[
        _risk_item(name="盈利为负", rule_id="1D.PROFIT_POSITIVE", evidence="本期净利润为负")]))
    assert "未实际命中" in _risk_error(fill)
    fill["score_inputs"]["1D"]["f_items"]["profit_positive"] = False
    html = R.build_risk_register(fill)
    assert "盈利为负" in html
