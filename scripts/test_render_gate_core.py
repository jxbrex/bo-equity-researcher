#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_core.py — render_report 门禁/校验回归：仓位卡/估值/quote 防伪/拒渲染/写作纪律与内容告警域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import re
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from scoring import (
    _position_steps, _quality_verdict, _valuation_verdict,
)
from conftest import (
    minimal_fill, mcap_fill, _dim, _calc, expect_valueerror, capture_stderr,
    validate_stderr, write_fill, render_fill, _L1_GOV_BLOCK, _LONG_TEXT, v2_fill,
    prepare_v2_quote, render_v2_fill,
)

def test_missing_timing_is_visible_and_does_not_change_position():
    fill = minimal_fill(timing_scores={"筹码面": None, "技术面": 5.0})
    sc = R.compute_scores(fill)
    assert sc["timing"] is None
    html = render_fill(fill)
    assert '时机分 <span class="tv">数据不足</span>' in html
    baseline = R.compute_scores(minimal_fill())
    baseline_calc = R.compute_valuation(minimal_fill())
    baseline_vc = R.compute_valuation_score(baseline_calc, minimal_fill()["valuation_inputs"], "B")
    expected_card = R.build_position_card(baseline["quality"], baseline_vc["score"], baseline["timing"],
                                         baseline_calc, "")
    expected_label = expected_card.split('badge-lg">', 1)[1].split("</span>", 1)[0]
    assert f'badge-lg">{expected_label}</span>' in html
    assert "时机分调节" not in html
    assert "≥6 好时机" not in html.split("三轨判定与仓位结论", 1)[1]
    card = R.build_position_card(4.5, 4.5, None, _calc(dispersion=0.5), "")
    assert "数据不足" in card and 'badge-lg">轻仓 ≤5%</span>' in card
    v2 = v2_fill()
    v2["timing_scores"] = {"筹码面": 5.0}
    assert R.compute_scores(v2)["timing"] is None
    assert "数据不足" in render_v2_fill(v2)
    for invalid in ({}, {"筹码面": "数据不足", "技术面": 5.0}):
        try:
            R.compute_scores(minimal_fill(timing_scores=invalid))
            raise AssertionError(f"非法时机输入不应静默放行: {invalid}")
        except ValueError:
            pass


def test_p0_low_quality_not_observation_pool():
    """P0 回归：quality <4 时最终仓位结论必须是「不建议参与」。"""
    html = R.build_position_card(quality=3.5, valuation=5.0,
                                 timing=5.0, calc=None, red_flag="")
    assert "不建议参与" in html, "质量<4 应得「不建议参与」"
    assert "观察池" not in html, "质量<4 不得落入观察池分支"


def test_uplift_cap_blocks_heavy_from_light():
    """上浮封顶：质地一般（4.5×4.5，非临界——v5.0 机制一：原 4.27/4.3 距 4.0 边界 ≤0.3
    属临界会降档冻结上浮）落轻仓，时机+离散度+赔率三连浮
    合计净效应 ≤1 档 → 最终标准仓 ≤10%，绝不允许重仓 ≤20%。"""
    html = R.build_position_card(quality=4.5, valuation=4.5,
                                 timing=7.0, calc=_calc(dispersion=0.30, odds=None,
                                                        floor_type="net_cash"),
                                 red_flag="")
    assert "矩阵落位：质量 4.50 × 估值 4.5 → 质地一般 → 轻仓 ≤5%" in html, \
        "落位文案缺失"
    assert "标准仓 ≤10%" in html, f"应止步标准仓，实际：{html}"
    assert "重仓 ≤20%" not in html, "轻仓不得被调节目测推成重仓"
    assert "上浮封顶" in html, "被拦的上浮项应在轨迹中说明"


def test_down_floors_at_zero():
    """下调兜底：轻仓落位 + 高离散度降一档到 0 后，继续下调必须兜底在 0，
    不得经 Python 负索引回卷成重仓 ≤20%；时机只作展示，不参与这条链。"""
    html = R.build_position_card(quality=4.5, valuation=4.5,
                                 timing=3.5, calc=_calc(dispersion=0.95),
                                 red_flag="")
    assert "不建议参与" in html, "两连降至底应为「不建议参与」（0 兜底）"
    assert "重仓" not in html, "负索引回卷会把兜底档错误显示为重仓"


def test_matrix_direct_entry_to_heavy_untouched():
    """好公司·好价格（≥7 × ≥8）矩阵直落重仓不受封顶误伤；此时调节全被
    封顶/顶格拦截且不产生噪音条目以外的误导。"""
    html = R.build_position_card(quality=7.5, valuation=8.5,
                                 timing=5.0, calc=_calc(),
                                 red_flag="")
    assert "重仓 ≤20%" in html, "矩阵直落重仓必须保留"


def test_scenario_lookup_by_key():
    """scenarios 含多余 key 且排在 base 前：中枢必须仍按 base 计算。"""
    fill = minimal_fill()
    fill["valuation"]["scenarios"] = [
        {"key": "pess", "label": "悲观", "profit": 80, "pe": [8, 10]},
        {"key": "xtra", "label": "干扰", "profit": 1, "pe": [1, 1]},   # 极值，取错即暴露
        {"key": "base", "label": "基础", "profit": 100, "pe": [10, 12]},
        {"key": "opt", "label": "乐观", "profit": 120, "pe": [12, 14]},
    ]
    calc = R.compute_valuation(fill)
    assert abs(calc["central_raw"] - (11 / 10 - 1)) < 1e-9, \
        f"中枢应来自 base 情景（中值 11），实际 {calc['central_raw']}"


def test_horizon_from_base_scenario():
    """horizon 只写在 base 情景级时，年化按 base 的时长（2 年 = 24 个月）。"""
    fill = minimal_fill()
    del fill["valuation"]["horizon"]
    fill["valuation"]["scenarios"][1]["horizon"] = "2年"
    calc = R.compute_valuation(fill)
    assert calc["months"] == 24.0, f"应按 base 情景 horizon 年化（24 个月），实际 {calc['months']}"


def test_new_report_requires_single_shared_horizon():
    with tempfile.TemporaryDirectory() as d:
        f = prepare_v2_quote(v2_fill(date="2026-10-26"), d)
        f["valuation"]["scenarios"][2]["horizon"] = "18个月"
        expect_valueerror(f, kw="三情景期限不一致")
        f = prepare_v2_quote(v2_fill(date="2026-10-26"), d)
        f["valuation"]["scenarios"][1]["horizon"] = "12-24个月"
        expect_valueerror(f, kw="区间期限")
        f = prepare_v2_quote(v2_fill(date="2026-10-26"), d)
        f["valuation"]["scenarios"][1]["horizon"] = "12"
        f["cycle_html"] = "<p>估值周期分析。</p>"
        expect_valueerror(f, kw="年/月")
        f = prepare_v2_quote(v2_fill(date="2026-10-26"), d)
        f["valuation"]["scenarios"][1]["horizon"] = "1年"
        f["cycle_html"] = "<p>估值周期分析。</p>"
        R.validate_content(f, R.compute_valuation(f))  # 1年=12个月，允许同月数不同写法


def test_legacy_mixed_horizon_warns_without_rejection():
    f = minimal_fill(date="2026-08-27")
    f["valuation"]["scenarios"][2]["horizon"] = "18-24个月"
    out = validate_stderr(f)
    assert "区间期限" in out and "旧报告" in out, f"旧报告应给兼容性警告而非拒渲染：{out}"


def test_cycle_chapter_required_for_growth_high_and_mature():
    with tempfile.TemporaryDirectory() as d:
        f = prepare_v2_quote(v2_fill(date="2026-10-26", growth_tier="high"), d)
        f["cycle_html"] = ""
        expect_valueerror(f, kw="第 11 章")
    out = validate_stderr(minimal_fill(stock_type="成熟/停滞")
                          | {"cycle_html": ""})
    assert "cycle_html 缺失" in out and "第 11 章" in out, f"成熟/停滞缺章应给兼容警告：{out}"


def test_rejections():
    expect_valueerror(minimal_fill(yellow_deductions=[{"label": "x", "points": -0.5}]),
                      "黄灯负扣分")
    f = minimal_fill(); f["red_deductions"] = [{"item": "x", "points": -1}]
    expect_valueerror(f, "红旗负扣分")
    f = minimal_fill(); f["valuation"]["scenarios"][0]["pe"] = [10, 8]
    expect_valueerror(f, "PE 区间倒挂")
    f = minimal_fill(); del f["timing_scores"]["技术面"]
    assert R.compute_scores(f)["timing"] is None, "缺任一子维应显示数据不足，不按 0 或中性分合成"
    f = minimal_fill(); del f["yellow_deductions"]
    expect_valueerror(f, "yellow_deductions 缺键")
    f = minimal_fill(); f["date"] = "2026/08/27"
    expect_valueerror(f, "date 格式非法")
    f = minimal_fill(); f["price"] = "未知"
    expect_valueerror(f, "price 非数字")


def test_quote_consistency():
    """quote 防伪（神华事故修复）：一致过 / 偏差>1% 拒 / 源文件读不到拒 / 缺 quote 仅告警不拒。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="_em_quote.json")
        f = minimal_fill(quote={"source_file": ref, "date": "2026-08-27"})
        R.validate_content(f, R.compute_valuation(f))  # 一致 → 过
        f["price"] = "10.05"  # 0.5% 偏差 → 仍过
        R.validate_content(f, R.compute_valuation(f))
        f["price"] = "10.5"  # 5% 偏差 → 拒
        expect_valueerror(f, "price 与落盘值偏差>1%")
        f = minimal_fill(quote={"source_file": os.path.join(d, "不存在.json"),
                                "date": "2026-08-27"})
        expect_valueerror(f, "quote.source_file 读不到")
        # 缺 quote → 不拒（告警走 stderr）
        g = minimal_fill()
        R.validate_content(g, R.compute_valuation(g))


def test_peers_caliber_warn():
    """peers_plot 口径一致性：目标点 PE 与 valuation_inputs.pe_ttm 偏差 >30% → 告警（不拒渲染）。"""
    fill = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 20, "target": True},  # vs pe_ttm 11 → 偏差 82%
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    assert "偏差 >30%" in validate_stderr(fill), "口径偏差 >30% 应告警"
    fill2 = minimal_fill(peers_plot={"points": [
        {"name": "测试股份", "roe": 20, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 15, "pe": 18}]})
    assert "偏差 >30%" not in validate_stderr(fill2), "口径一致不应告警"


def test_writing_discipline_warns():
    """v4.7.1 写作纪律告警：四拍挤段 / 三年并排 / pe_history 无第 11 章承载。"""
    # 四拍挤段：同一 <p> 含 ≥2 个拍名 → 告警
    l1 = ('<div class="dim-block"><p><strong>判词：</strong>矿山服务龙头，海外占比 72% 是核心阿尔法。'
          '<strong>论据：</strong>2025 年报海外毛利 31.2 亿（+24%），续约率 91%（年报 P17）。'
          '<strong>评分：</strong>8.0——护城河在长期服务协议锁定，铜价下行期续约率是唯一先行指标。</p></div>')
    fill4beat = minimal_fill(l1_html="".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                                                  "行业地位稳固，具备长期参考价值。") for _ in range(5)) + l1)
    assert "四拍挤段" in validate_stderr(fill4beat), "四拍挤段应告警"
    l1_ok = "".join(_dim("该维度分析：公司基本面稳健，数据支撑充分，论据详实可靠，"
                         "行业地位稳固，具备长期参考价值。") for _ in range(6))
    assert "四拍挤段" not in validate_stderr(minimal_fill(l1_html=l1_ok)), "分段的四拍不应告警"
    # 三年并排：连续三个年份 th / td 内年份:数值堆叠 → 告警
    peers = ('<table><thead><tr><th>指标</th><th>2023</th><th>2024</th><th>2025</th></tr></thead>'
             '<tbody><tr><td>ROE变化</td><td>8.0</td><td>15.2</td><td>30.8</td></tr></tbody></table>'
             '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in validate_stderr(minimal_fill(peers_html=peers)), "三年并排应告警"
    peers_stacked = ('<table><thead><tr><th>指标</th><th>3年走势</th></tr></thead>'
                     '<tbody><tr><td>归母净利</td><td>2023: 8.0，2024: 15.2，2025: 30.8</td></tr></tbody></table>'
                     '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" in validate_stderr(minimal_fill(peers_html=peers_stacked)), "td 内年份堆叠应告警"
    peers_ok = ('<table><thead><tr><th>公司</th><th>ROE变化</th></tr></thead>'
                '<tbody><tr><td>同业甲</td><td>8.0→30.8（大升）</td></tr></tbody></table>'
                '<span class="source">来源：mx 批量</span>')
    assert "三年数字并排" not in validate_stderr(minimal_fill(peers_html=peers_ok)), "起→终格式不应告警"
    # pe_history 与第 11 章绑定：cycle_html 缺失 → 告警；填了 → 不告警
    ph = {"hist_lo": 13.7, "hist_hi": 83.2}
    assert "cycle_html 缺失" in validate_stderr(minimal_fill(pe_history=ph)), "pe_history 无第 11 章承载应告警"
    fill_ok = minimal_fill(pe_history=ph, cycle_html='<p>周期阶段分析正文，非空即渲染整章。</p>')
    assert "cycle_html 缺失" not in validate_stderr(fill_ok), "cycle_html 已填不应告警"


def test_quote_four_piece():
    """v4.8 防伪链四件套扩展：valuation_inputs.pe_ttm 偏差>1% 拒；pe_band 完全越界历史带拒；
    risk_free 偏差>0.3pct 告警不拒；港股 div_yield 不比对。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0, "pe_band": [8.0, 20.0],
                          "risk_free": 1.7, "div_yield": 2.0, "market": "A股"},
                         d, name="_em_quote.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        # 一致 → 过
        f = minimal_fill(quote=q)
        R.validate_content(f, R.compute_valuation(f))
        # valuation_inputs.pe_ttm 偏差 9% → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_ttm"] = 12.0
        expect_valueerror(f, "valuation_inputs.pe_ttm 与落盘值偏差>1%")
        # pe_band [30,40] 完全落在历史带 [8,20] 之外 → 拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [30, 40]
        expect_valueerror(f, "pe_band 完全越界历史带")
        # pe_band 部分重叠 → 过
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["pe_band"] = [15, 25]
        R.validate_content(f, R.compute_valuation(f))
        # risk_free 偏差 0.8pct → 告警不拒
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["risk_free"] = 2.5
        out = validate_stderr(f)  # 不拒
        assert "risk_free" in out and ">0.3pct" in out, "risk_free 偏差应告警"
        # 港股 div_yield 偏差不做机械比对（税后折算差异天然大）
        write_fill({"price": 10.0, "pe_ttm": 11.0, "market": "港股"}, d, name="_em_quote.json")
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["div_yield"] = 3.5
        assert "div_yield" not in validate_stderr(f), "港股 div_yield 不应机械比对"


def test_position_steps_direct():
    """v4.9：仓位决策链已抽成纯函数 _position_steps——直接测决策分支
    （红灯熔断 / 中枢为负 / 直落重仓 / 上浮封顶 / 0 兜底 / 观察池下调）。
    v5.0：返回值扩为 4 元组（+crit 档位临界列表）；分支覆盖改用非临界分数
    （原 7.2/4.27/4.3/5.8 均落在 ±0.3 临界带，临界分支见 test_position_steps_edge_critical）。"""
    # 红灯熔断：后续调节不再适用
    label, steps, slot, crit = _position_steps(7.5, 8.5, _calc(odds=None), "财务造假嫌疑")
    assert label == "不建议参与" and slot is None and "红灯熔断" in steps[0] and not crit
    # 中枢为负拦截器（不落矩阵）
    label, steps, slot, crit = _position_steps(7.5, 8.5, _calc(), "")
    assert label == "重仓 ≤20%" and "矩阵落位" in slot, "无红灯无负中枢应走矩阵直落"
    label, steps, slot, crit = _position_steps(7.5, 8.5, {"central_raw": -0.1, "central": -0.1}, "")
    assert label == "回避（中枢为负，等价格）" and slot is None and "中枢为负" in steps[0]
    # 上浮封顶：质地一般轻仓 + 时机/离散/赔率三连浮仍止步标准仓
    label, steps, slot, crit = _position_steps(4.5, 4.5, _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%" and "上浮封顶" in "".join(steps)
    # 下调 0 兜底：两次下调不得回卷
    label, steps, slot, crit = _position_steps(4.5, 4.5, _calc(dispersion=0.95), "")
    assert label == "不建议参与" and "重仓" not in "".join(steps)
    # 观察池：中上质地 + 差价格；离散度极端 → 下调不建议参与
    label, steps, slot, crit = _position_steps(5.9, 5.0, None, "")
    assert label == "观察池" and "观察池" in slot
    label, steps, slot, crit = _position_steps(5.9, 5.0, _calc(dispersion=0.95), "")
    assert label == "不建议参与" and "观察池下调" in "".join(steps)
    # 与卡片渲染同源：build_position_card 输出含同一结论（行为零变更冒烟）
    html = R.build_position_card(4.5, 4.5, 7.0,
                                 _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert "标准仓 ≤10%" in html


def test_try_up_wording_nailed():
    """v4.10.2 热核审计钉死：try_up 离散度/赔率两条上浮路径的轨迹文案逐字断言。
    背景：try_up 收敛曾把赔率分支「）→ 上浮一档」（无空格）归一为「） → 上浮一档」
    （有空格）——1 字节漂移，因该分支零断言零快照覆盖而溜过。此处把两条路径
    （离散度/赔率）的成功上浮文案逐字钉死，上浮分支统一「detail → 上浮一档」写法。
    时机分已退出仓位，不再产生上浮或下调轨迹。"""
    # 时机不再进入仓位：不升也不降，只保留矩阵落位
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, _calc(), "")
    assert label == "轻仓 ≤5%"
    assert steps == ["矩阵落位直接生效，无调节项触发"], steps
    # 离散度上浮成功
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, _calc(dispersion=0.30), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["离散度调节：离散度 30.0% < 40% → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    # 赔率 ∞ 上浮成功（归一化前此分支无空格，本轮有意归一——见 handoff 审计修补段）
    label, steps, _slot, _crit = _position_steps(4.5, 4.5, _calc(dispersion=0.50, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["赔率调节：赔率 ∞（悲观仍正收益） → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps


def test_verdict_word_boundaries():
    """v4.10.2：hero 判词分档边界——hero 副标直接消费 _quality_verdict/_valuation_verdict，
    此前只有 golden 快照覆盖 7.0/5.5 两个点，边界档逐点钉死。"""
    q_cases = [(3.99, "回避"), (4.0, "一般"), (5.49, "一般"), (5.5, "中上"), (6.99, "中上"), (7.0, "好公司")]
    for score, word in q_cases:
        assert _quality_verdict(score) == word, f"质量分 {score} 应为「{word}」，实际「{_quality_verdict(score)}」"
    v_cases = [(3.99, "贵"), (4.0, "合理无安全边际"), (5.99, "合理无安全边际"),
               (6.0, "合理偏便宜"), (7.99, "合理偏便宜"), (8.0, "深度安全边际")]
    for score, word in v_cases:
        assert _valuation_verdict(score) == word, f"估值分 {score} 应为「{word}」，实际「{_valuation_verdict(score)}」"


def test_hero_band_claims_warns():
    """v4.9 Hero 文案引用分位/历史带概念时的数据支撑告警：
    无 p25/p75 支撑 / 极性矛盾 → 告警；概念齐备且无矛盾 → 不告警。
    v5.4.0：p25/p75 与合理带中枢偏离 >15% 即触发双尺回滚门禁（拒渲染），
    本用例只关心 Hero 文案，换数后的 fixture 统一配 rollback_html。"""
    def _rb(f):
        f["valuation"]["rollback_html"] = "回滚条件：连续两季扣非同比转正 → PE 带回滚至历史带"
        return f

    # 引「分位」但 pe_history 无 p25/p75 → 告警（数据支撑缺失）
    out = validate_stderr(minimal_fill(pe_sub="PE 处近 5 年低分位"))
    assert "分位" in out and "未填 p25/p75" in out, "引用分位而缺 p25/p75 应告警"
    # 有 p25/p75 但极性矛盾：现价 PE 高于 P75 却说低分位
    ph = {"hist_lo": 5, "hist_hi": 30, "p25": 8, "p75": 10, "label": "近5年"}
    out = validate_stderr(_rb(minimal_fill(pe_sub="现价 PE 处于低分位", pe_history=ph)))
    assert "低分位" in out and "矛盾" in out, "低分位说法与高于 P75 的现价应告警"
    # 极性正确（现价 < P25 说低分位）→ 不告警（p25 20/p75 30 偏离合理带 → 配回滚条款）
    out = validate_stderr(_rb(minimal_fill(pe_sub="现价 PE 处于低分位",
                                           pe_history={"p25": 20, "p75": 30})))
    assert "分位" not in out, "低分位说法与低于 P25 的现价不应告警"
    # 引用历史带但 pe_history 无 hist_lo/hist_hi → 告警
    out = validate_stderr(_rb(minimal_fill(pe_sub="PE 高于历史带上沿", pe_history={"p25": 8, "p75": 10})))
    assert "历史带" in out and "hist_lo" in out, "引用历史带而缺极值字段应告警"
    # 无概念字面 → 不告警
    out = validate_stderr(minimal_fill())
    assert "分位" not in out and "历史带" not in out


def test_conclusion_structure_warns():
    """v4.9.1 补充修订二：conclusion_html 四卡结构——缺卡 / 乱序 → 告警；四卡顺序正确 → 不告警。
    校验按纯文本关键词，对容器形式不敏感（旧四段 <p> 写法同样检出，但新规范为 .concl-grid 卡）。"""
    body = "（数据证据支撑充分，论据详实可靠，具备参考价值。）" * 6

    def card(head, ref):
        return (f'<div class="concl-card"><div class="concl-head">{head}</div>{body}'
                f'<div class="concl-ref">详见 {ref}</div></div>')

    four = ('<div class="concl-grid">' + card("关键优势", '<a href="#s4">4 公司本质</a>')
            + card("关键弱点", '<a href="#s6">6 风险评估</a>')
            + card("当前市场认知", '<a href="#s9">9 市场预期差</a>')
            + card("核心投资逻辑", '<a href="#s8">8 估值与安全边际</a>') + '</div>')
    assert "缺卡" not in validate_stderr(minimal_fill(conclusion_html=four)), "四卡齐全不应告警"
    three = four.replace(card("当前市场认知", '<a href="#s9">9 市场预期差</a>'), "")
    out = validate_stderr(minimal_fill(conclusion_html=three))
    assert "缺卡" in out and "当前市场认知" in out, "缺卡应告警并点名缺失卡头"
    mixed = ('<div class="concl-grid">' + card("核心投资逻辑", "8") + card("关键优势", "4")
             + card("关键弱点", "6") + card("当前市场认知", "9") + '</div>')
    out = validate_stderr(minimal_fill(conclusion_html=mixed))
    assert "顺序错误" in out, "四卡乱序应告警"


def test_review_miss_diagnostics_warns():
    """v4.9 复盘「未命中」缺诊断方向：含未命中而无规律/反例字样 → 告警。"""
    prev = {"date": "2026-08-08", "quality": 7.0, "valuation": 5.5,
            "timing": 5.0, "target_range": "10-12",
            # v5.1.0：回测模式 prev.scenarios 必填；base PE 与本版一致（10-12x）不触发移动校验
            "scenarios": [{"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                           "目标价": "9.5-11.4 元"}]}
    tbl = '<table><tr><td>假设</td></tr></table><span class="source">数据来源：测试</span>'
    miss_key = "未提「规律/反例」"  # 告警文案关键字（与用户正文的「规律/反例」区分）
    out = validate_stderr(minimal_fill(prev=prev, review_html=tbl + "判定：未命中"))
    assert miss_key in out, "含未命中而无规律/反例字样应告警"
    out2 = validate_stderr(minimal_fill(prev=prev,
                                        review_html=tbl + "判定：未命中——本次属原规律失效的现场反例"))
    assert miss_key not in out2, "已写明规律失效/反例方向不应告警"


def test_peers_roe_outlier_warns():
    """v4.9 peers_plot ROE 量级倒挂：目标点 ROE 脱离同业量级 → 告警；同量级 → 不告警。
    v5.4.0：散点同业须在 peers_html 表内或有 peers_meta 声明（表图一致拒渲染），
    本用例的「同业乙」走 peers_meta 声明路径。"""
    meta = "同行业、同规模筛选；同业乙口径不一已剔出"
    # 目标 ROE 2% vs 同业 12-15% → 倒挂告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 2, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    out = validate_stderr(fill)
    assert "ROE" in out and "脱离同业量级" in out, "目标 ROE 明显低于同业应告警"
    # 目标 ROE 34 vs 同业 12-15 → 倒挂告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 34, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" in validate_stderr(fill)
    # 目标 14 vs 同业 12-15 → 不告警
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 14, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" not in validate_stderr(fill)


def test_peers_column_without_support_warns():
    """v4.10.3：peers 趋势表某列超半数格为「—」且未在同业结论框引用 → 告警
    （fill-schema「无引用=删列」的可判定落地）；结论框引用该列、或数据补齐 ≥ 半数 → 放行。"""
    thr = ('<div class="table-scroll"><table class="freeze-first">'
           '<tr><th>公司</th><th>净利现金含量 3 年</th><th>PE(TTM)</th></tr>'
           '<tr><td>测试股份</td><td>—</td><td>11</td></tr>'
           '<tr><td>同业甲</td><td>—</td><td>25</td></tr>'
           '<tr><td>同业乙</td><td>0.9</td><td>16</td></tr></table></div>'
           '<div class="conclusion-box"><strong>结论：</strong>规模与估值见上表。</div>'
           '<span class="source">数据来源：测试。</span>')
    out = validate_stderr(minimal_fill(peers_html=thr))
    assert "净利现金含量" in out and "无对比支撑" in out, "超半数缺失且未引用应告警"
    cited = thr.replace("规模与估值见上表", "净利现金含量仅同业乙可得")
    assert "无对比支撑" not in validate_stderr(minimal_fill(peers_html=cited)), \
        "结论框已引用该列不应告警"
    filled = thr.replace('<td>测试股份</td><td>—</td>', '<td>测试股份</td><td>0.8</td>')
    assert "无对比支撑" not in validate_stderr(minimal_fill(peers_html=filled)), \
        "可得数据 ≥ 半数不应告警"


def test_backtest_triggers_warning():
    """v4.9.1：回测模式（prev 已填）triggers 缺失 → 告警（旧触发条件核对由状态条承载，
    dash_html 不再手写核对表）；triggers 已填 → 无此告警。
    v4.10.3：全 pending 视同未核对（状态条条件渲染后一条也不显示）→ 同样告警。"""
    prev = {"date": "2026-08-05", "quality": 7.0, "valuation": 6.0, "timing": 5.0,
            "target_range": "10-12"}
    out = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>")))
    assert "triggers 未填" in out, "prev 已填而 triggers 缺失应告警"
    out2 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "hit"}])))
    assert "triggers 未填" not in out2, "triggers 已填不应再告警"
    out3 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "pending"}])))
    assert "视同未核对" in out3, "全 pending 视同未核对，应告警"
    out4 = capture_stderr(lambda: R._check_backtest_flags(
        minimal_fill(prev=prev, review_html="<p>复盘。</p>",
                     triggers=[{"cond": "提价兑现", "status": "pending"},
                               {"cond": "销量转正", "status": "miss"}])))
    assert "视同未核对" not in out4 and "triggers 未填" not in out4, "含 hit/miss 不应告警"


def test_governance_strip_compact_warns():
    """v4.9.1 补充修订二：4.5 治理块单行化——trig-strip 块内 <p> 恰为 2（判词+评分）→ 不告警；
    trig 行后另起 <p> 正文（>2 个 <p>）→ 告警；4.5 未用 trig-strip 的存量写法 → 不打扰。"""

    def l1_with_35(inner):
        dims = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
                 '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
        return "".join(dims) + ('<div class="dim-block"><div class="dim-header">'
                                '<span class="dim-name">4.5 治理与资本配置</span></div>'
                                + inner + '</div>')

    trig = ('<div class="trig"><span class="trig-dot hit"></span>'
            '<span class="trig-cond">股权与控制权</span>'
            '<span class="trig-mt">控股股东持股 34.2%，无质押冻结</span>'
            '<span class="trig-status hit">正面</span></div>')
    compact = ('<p><strong>判词：</strong>股权集中、激励充分，论据详实可靠具备参考价值。</p>'
               f'<div class="trig-strip">{trig}{trig}</div>'
               '<p><strong>评分：</strong>7.5——基准 7.0，激励到位 +0.5；关联交易关注 −0.0。</p>')
    assert "恰为 2" not in validate_stderr(minimal_fill(l1_html=l1_with_35(compact))), "紧凑形态不应告警"
    loose = compact.replace('</div><p><strong>评分',
                            f'</div><p>补充正文一段，论据详实可靠具备参考价值和数据支撑。</p>{trig}'
                            '<p><strong>评分')
    out = validate_stderr(minimal_fill(l1_html=l1_with_35(loose)))
    assert "恰为 2" in out, "trig 行后另起 <p> 正文应告警"
    legacy = ('<p>公司治理正文一段，未用分块列示的存量写法，论据详实可靠具备参考价值与数据支撑。'
              '治理结构稳定，激励到位，分红持续。</p>')
    assert "恰为 2" not in validate_stderr(minimal_fill(l1_html=l1_with_35(legacy))), "未用 trig-strip 不打扰"

    # 补充修订四：4.3 护城河 / 5.3 催化剂同款 <p> 恰为 2 规则
    def dim_with(name, inner):
        return ('<div class="dim-block"><div class="dim-header">'
                f'<span class="dim-name">{name}</span></div>' + inner + '</div>')
    dims5 = [('<div class="dim-block"><p>该维度分析：公司基本面稳健，数据支撑充分，'
              '论据详实可靠，行业地位稳固，具备长期参考价值。</p></div>')] * 5
    assert "恰为 2" not in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("4.3 商业模式与护城河", compact))), "4.3 紧凑形态不应告警"
    assert "恰为 2" in validate_stderr(minimal_fill(
        l1_html="".join(dims5) + dim_with("4.3 商业模式与护城河", loose))), "4.3 另起正文应告警"
    l3_43 = ("".join(dims5[:2]) + dim_with("5.3 催化剂", loose))
    assert "恰为 2" in validate_stderr(minimal_fill(l3_html=l3_43)), "5.3 另起正文应告警"


def test_peers_orientation_warns():
    """v4.9.1 补充修订二：同业表公司强制行标题——目标公司蓝 style 落 <th> 表头（公司列旧方向）
    → 告警；标在行首格（<td>）→ 不告警。"""
    col_form = ('<table><thead><tr><th>指标</th>'
                '<th style="color:#4a6fa5;font-weight:700;">测试股份</th><th>同业甲</th></tr></thead>'
                '<tbody><tr><td>PE(TTM)</td><td>11</td><td>25</td></tr></tbody></table>'
                '<span class="source">来源：mx 批量</span>')
    assert "公司=行" in validate_stderr(minimal_fill(peers_html=col_form)), "公司列旧方向应告警"
    assert "公司=行" not in validate_stderr(minimal_fill()), "行标题形态不应告警"


def test_l4_order_table_form():
    """v4.10：黄灯四类顺序检查覆盖扣分表形态（<td>a …</td>）——跳号（b→c）放行，乱序告警。"""
    ordered = ('<table><tbody>'
               '<tr><td>b 行业与政策环境</td><td>x</td></tr>'
               '<tr><td>c 盈利与财务质量</td><td>y</td></tr></tbody></table>')
    assert capture_stderr(lambda: R._check_l4_order(ordered)) == "", "跳号但有序应放行"
    messy = ordered.replace("<td>b 行业", "<td>c 行业").replace("<td>c 盈利", "<td>b 盈利")
    assert "a→b→c→d" in capture_stderr(lambda: R._check_l4_order(messy)), "乱序应告警"


def test_peers_bestworst_warn():
    """v4.10：同业当前指标表零 cell-best/cell-worst 标注 → 告警（工行 09-11 两表零标注实证）。"""
    bare = ('<div class="table-scroll"><table class="freeze-first">'
            '<tr><th>公司</th><th>PE(TTM)</th></tr>'
            '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td><td>11</td></tr>'
            '<tr><td>同业甲</td><td>25</td></tr></table></div>'
            '<span class="source">数据来源：测试</span>')
    assert "cell-best" in validate_stderr(minimal_fill(peers_html=bare)), "零标注应告警"
    assert "cell-best" not in validate_stderr(minimal_fill()), "fixture 自带标注不应告警"
    # v4.11.0 逐列检查（天齐 09-13 实证：7 列只标 4 列，零标注告警不触发）——数值列缺标注按列名告警
    partial = ('<div class="table-scroll"><table class="freeze-first">'
               '<tr><th>公司</th><th class="num">PE(TTM)</th><th class="num">ROE</th></tr>'
               '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td>'
               '<td class="cell-best num">11</td><td class="num">14%</td></tr>'
               '<tr><td>同业甲</td><td class="cell-worst num">25</td><td class="num">9%</td></tr>'
               '</table></div><span class="source">数据来源：测试</span>')
    err = validate_stderr(minimal_fill(peers_html=partial))
    assert "缺最优/最差标注" in err and "ROE" in err, "ROE 列裸奔应按列名告警"


def test_peers_roe_outlier_with_documented_one_off_does_not_warn():
    meta = ("同行业、同规模筛选；同业乙口径不一已剔出；目标公司 ROE 取 2025 年报加权口径，"
            "含一次性收益，扣非口径另列，与同业年报口径对照")
    fill = minimal_fill(peers_meta=meta, peers_plot={"points": [
        {"name": "测试股份", "roe": 34, "pe": 11, "target": True},
        {"name": "同业甲", "roe": 12, "pe": 18},
        {"name": "同业乙", "roe": 15, "pe": 20}]})
    assert "脱离同业量级" not in validate_stderr(fill)


def test_peers_directionless_columns_with_units_respect_meta_note():
    peers_html = ('<div class="table-scroll"><table><tr><th>公司</th><th>现价（元）</th>'
                  '<th>总市值（亿）</th><th>PE(TTM)</th></tr>'
                  '<tr><td>测试股份</td><td>10</td><td>100</td><td class="cell-best">11</td></tr>'
                  '<tr><td>同业甲</td><td>20</td><td>200</td><td class="cell-worst">25</td></tr>'
                  '</table></div><span class="source">数据来源：测试</span>')
    out = validate_stderr(minimal_fill(
        peers_meta="现价/总市值为事实列，不标方向性极值", peers_html=peers_html))
    assert "缺最优/最差标注" not in out


def test_peers_plot_array_form_rejected():
    """peers_plot 数组简写废止（v5.1.5，与 fill-schema「直接给数组亦可」删除同步）：
    传裸数组 → 拒渲染。"""
    expect_valueerror(minimal_fill(peers_plot=[{"name": "同业甲", "roe": 15, "pe": 18}]),
                      kw="数组简写已废止")


def test_governance_deduct_row_warn():
    """v4.11.0：4.5 治理块评分段含扣分项时，trig 行必须有 miss「扣分」状态行
    （天齐 09-13 实证：评分段写「折价配售摊薄 −0.3」，四个方块却无一扣分档，结论断层）。"""
    gov = _L1_GOV_BLOCK
    deducted = gov.replace("关联交易关注项不扣分但列入 14 章跟踪",
                           "扣分项（H 股折价配售摊薄 −0.3）")
    l1 = "".join(_dim(_LONG_TEXT) for _ in range(5)) + deducted
    err = validate_stderr(minimal_fill(l1_html=l1))
    assert "无「扣分」状态" in err, "评分段有扣分项、块内无扣分行 → 应告警"
    fixed = deducted.replace('<span class="trig-status miss">关注</span>',
                             '<span class="trig-status miss">扣分</span>')
    err2 = validate_stderr(minimal_fill(l1_html="".join(_dim(_LONG_TEXT) for _ in range(5)) + fixed))
    assert "无「扣分」状态" not in err2, "块内有扣分行后应放行"
    assert "无「扣分」状态" not in validate_stderr(minimal_fill()), "fixture 无扣分项不应告警"


def test_holders_dup_date_warn():
    """v4.11.0：holders 重复截止日 → 告警（E4 上游偶发双行且变动值不一致，天齐 20260710 实证）。"""
    dup = [{"date": "2026-07-10", "num": 345304, "chg": 0.0},
           {"date": "2026-07-10", "num": 345304, "chg": -1.7},
           {"date": "2026-07-20", "num": 358804, "chg": 3.9},
           {"date": "2026-07-31", "num": 360077, "chg": 0.4}]
    assert "重复截止日" in validate_stderr(minimal_fill(holders=dup)), "重复截止日应告警"
    assert "重复截止日" not in validate_stderr(minimal_fill()), "fixture 无重复不应告警"


def test_price_history_pe_warn():
    """v4.10：price_history 的 pe 缺失告警（v4.11.0 起口径=有效 <12 点，图门槛同步）——
    提示照抄 E2 全序列月末 PE（工行 09-11 报告 12 点全缺、图只剩股价线实证）。"""
    ph = {"label": "近12个月", "series": [{"m": f"2025-{m:02d}", "close": 7.5} for m in range(1, 13)]}
    assert "月末 PE" in validate_stderr(minimal_fill(price_history=ph)), "pe 全缺应告警"
    ph2 = {"label": "近12个月",
           "series": [{"m": f"2025-{m:02d}", "close": 7.5, "pe": 7.6} for m in range(1, 13)]}
    assert "月末 PE" not in validate_stderr(minimal_fill(price_history=ph2)), "pe 齐全不应告警"
    # v4.11.0：门槛放宽为 ≥12 点（亏损期断线属诚实形态）——68 点 29 有效不再告警
    ph3 = {"label": "近5年", "series": [
        {"m": f"{2021 + i // 12}-{i % 12 + 1:02d}", "close": 40.0,
         "pe": (15.0 if 16 <= i < 40 or i >= 62 else None)} for i in range(68)]}
    assert sum(1 for p in ph3["series"] if p["pe"]) == 30
    assert "月末 PE" not in validate_stderr(minimal_fill(price_history=ph3)), \
        "30/68 点有效（≥12）不应再告警"


def test_l4_form_gates():
    """v4.10：L4 固定形态硬门禁——缺 pm-grid 三联卡拒渲染（旧 danger-card 单段形态打回）；
    黄灯扣分明细表行数 ≠ yellow_deductions 条数拒渲染（工行 09-11 照抄旧形态实证）。"""
    f = minimal_fill()
    f["l4_html"] = ('<div class="danger-card"><strong>损失预演：</strong>单段长文旧形态，'
                    '故事与重合度与清单外风险糊在一个段落里。</div>')
    expect_valueerror(f, kw="损失预演三联卡")
    f2 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5},
                                         {"label": "y", "points": 0.5}])
    f2["l4_html"] = (f2["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>a 交易与股东行为</td><td>无</td><td>0</td></tr>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '<tr><td>c 盈利与财务质量</td><td>y</td><td class="num">0.5</td></tr>'
                     '<tr><td>d 经营与公司治理</td><td>无</td><td>0</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    expect_valueerror(f2, kw="只列 points>0")
    f3 = minimal_fill(yellow_deductions=[{"label": "x", "points": 0.5}])
    f3["l4_html"] = (f3["l4_html"] + '<div class="table-scroll"><table><tbody>'
                     '<tr><td>b 行业与政策环境</td><td>x</td><td class="num">0.5</td></tr>'
                     '</tbody></table></div><span class="source">数据来源：测试</span>')
    R.validate_content(f3, R.compute_valuation(f3))  # 匹配形态不拒即通过


def test_negative_profit_central_no_crash():
    """v4.11.1（审核 D1）：负利润 base + 2年 horizon → 中枢不年化、保持实数，不崩 TypeError；
    中枢为负拦截器照常生效；validate 对负 profit 告警不拒。"""
    f = minimal_fill()
    f["valuation"]["horizon"] = "2年"
    for s in f["valuation"]["scenarios"]:
        s["profit"] = {"pess": -80, "base": -50, "opt": -20}[s["key"]]
    calc = R.compute_valuation(f)
    assert isinstance(calc["central"], float), f"负中枢不得年化为复数：{calc['central']!r}"
    assert calc["central"] < -1, f"central_raw=-6（-50×11/10/10−1），实际 {calc['central']}"
    label, steps, _slot, _crit = _position_steps(6.0, 5.0, calc, "")
    assert "中枢为负" in label, f"负中枢应走拦截器，实际 {label}"
    f["thesis_html"] = "<p>困境反转论点：产能出清后正常化利润回归，本句仅作测试占位文本。</p>"
    warns = validate_stderr(f)
    assert "profit=-50" in warns and "口径" in warns, "负 profit 应有口径提示告警（不拒渲染）"


def test_cross_scenario_inversion_rejected():
    """v4.11.1（审核 D2）：三情景中枢跨档倒挂（pess>base 或 base>opt）→ 拒渲染；
    负离散度不得被决策链当作「低不确定性」上浮（校验漏网时的第二道防线）。"""
    f = minimal_fill()
    # pess 315 / base 105 / opt 63（profit 填反方向）
    for s, p in zip(f["valuation"]["scenarios"], (30, 10, 6)):
        s["profit"] = p
        s["pe"] = [100, 110]
    expect_valueerror(f, "跨档倒挂")
    calc = {"central_raw": 0.5, "central": 0.5, "dispersion": -25.2, "odds": 1.5}
    html = R.build_position_card(quality=6.0, valuation=6.5,
                                 timing=5.0, calc=calc, red_flag="")
    assert "离散度调节" not in html, "负离散度不得触发上浮（审核 D2 防线二）"


def test_dim_blocks_by_dim_name():
    """v4.11.1（审核 D3）：dim-block 乱序时按 dim-name 编号映射维度——
    4.3 块写最前，极端分 1C=8.5 的证据校验仍须命中 4.3 块（旧位置 zip 会错配到 1A 漏检）。"""
    f = minimal_fill()
    f["scores"]["1C"] = 8.5
    thin_txt = "护城河论据较薄但越过地板线，此处补充字数" + "据" * 13   # 块总长 45（含头部11字）：过 40 地板、踩 <50 极端分门槛

    def _named(num, name, txt):
        return (f'<div class="dim-block"><div class="dim-header">'
                f'<span class="dim-name">{num} {name}</span></div><p>{txt}</p></div>')
    long_txt = "该维度分析：论据与数据充分，行业地位稳固，具备长期参考价值，结论可靠。"
    f["l1_html"] = (_named("4.3", "商业模式与护城河", thin_txt)
                    + _named("4.1", "赛道与宏观", long_txt) + _named("4.2", "产业链位置", long_txt)
                    + _named("4.4", "财务健康", long_txt) + _named("4.5", "治理与资本配置", long_txt)
                    + _named("4.6", "资本回报质量", long_txt))
    err = validate_stderr(f)
    assert "4.3 商业模式与护城河 得分 8.5（极端分）" in err, \
        f"乱序下极端分校验应命中 4.3 块，实际 stderr：{err[:400]}"


def test_quote_present_date_gate():
    """v4.11.1（审核 D5）：date ≥ 2026-09-02（v4.8 引入 quote）缺 quote → 拒渲染；
    此前存量 fill → 维持告警（豁免）。"""
    f = minimal_fill()
    f["date"] = "2026-09-13"
    expect_valueerror(f, "新报告缺 quote 应拒渲染")
    g = minimal_fill()  # date=2026-08-27 存量
    err = validate_stderr(g)
    assert "quote 字段缺失" in err, "存量 fill 缺 quote 应走告警豁免"


def test_dim_block_extra_class_tolerated():
    """v4.11.1（审核 D8）：class="dim-block extra" 附加类形态仍计入块数，不误触发 <6 拒渲染。"""
    f = minimal_fill()
    f["l1_html"] = f["l1_html"].replace('<div class="dim-block">',
                                        '<div class="dim-block extra">', 1)
    R.validate_content(f, R.compute_valuation(f))  # 不拒即通过


def test_scenario_dup_key_rejected():
    """F6：valuation.scenarios key 重复即拒渲染——双 pess 曾绕过地板门禁
    （next() 首个 vs by_key 末个口径分裂）；重复 key 没有合法语义。"""
    f = minimal_fill()
    f["valuation"]["scenarios"].append({"key": "PESS", "label": "悲观B", "trigger": "x",
                                        "profit": 70, "pe": [7, 9]})
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("双 pess 应拒但未拒")
    except ValueError as e:
        assert "key 重复" in str(e), f"应报 key 重复，实际: {e}"


# ---------------- 审计加固：类型守卫 / 负权重 / 覆盖告警 / 冗余告警清理 ----------------
def test_scenario_pe_string_rejected():
    """#1: 情景 pe/mcap 传字符串 "12-16" 不得按字符切片静默错算（pe_lo=1/pe_hi=2）——
    归空数组后走既有「缺 PE 区间/缺净利假设」拒渲染路径；四件套 pe_band 字符串同理（None）。"""
    f = minimal_fill()
    f["valuation"]["scenarios"][1]["pe"] = "12-16"
    expect_valueerror(f, "pe 字符串应拒渲染", kw="缺 PE 区间")
    f = mcap_fill()
    f["valuation"]["scenarios"][0]["mcap"] = "640-800"
    expect_valueerror(f, "mcap 字符串应拒渲染", kw="缺净利假设")
    # 四件套侧：pe_band 字符串按字符切片会静默错算（"12-16" → 带 [1,2]），应视为无效带
    calc = R.compute_valuation(minimal_fill())
    vi = {"pe_ttm": 11, "pe_band": "12-16", "div_yield": 2, "risk_free": 1.7}
    assert R.compute_valuation_score(calc, vi) is None, "pe_band 字符串应视为无效带（None）"


def test_negative_weights_rejected():
    """#4: 层内权重/layer_share 只校总和=100 拦不住负值（正负可凑够 100 静默错分）——
    负权重/负占比须显式拒渲染。"""
    # 1B -10、1C +22 → L1 总和仍恰 = 100，但含负权重
    f = minimal_fill(weights={"1B": -10, "1C": 42})
    expect_valueerror(f, "负层内权重应拒", kw="层内权重含负值")
    f = minimal_fill(layer_share={"L1": 120, "L3": -20})  # 总和仍 = 100
    expect_valueerror(f, "负 layer_share 应拒", kw="layer_share 含负值")


def test_zero_crossing_pe_band_friendly_reject():
    """#5: 合理带跨 0（[-5,5]，中点为 0）→ _map_warranted 的 pe_ttm÷中点 除零——
    与 _dev_vs_hist 口径对齐视为无效带（None），render 层转友好 ValueError，不得裸崩。"""
    fill = minimal_fill(valuation_inputs={"pe_ttm": 11, "pe_band": [-5, 5],
                                          "div_yield": 2, "risk_free": 1.7})
    calc = R.compute_valuation(fill)
    assert R.compute_valuation_score(calc, fill["valuation_inputs"]) is None, \
        "跨 0 带应视为无效带（None），不得进入 _map_warranted 除零"
    try:
        render_fill(fill)
    except ValueError as e:
        assert "估值分无法计算" in str(e), f"应友好拒渲染，实际: {e}"
        return
    raise AssertionError("跨 0 带应拒渲染但未拒")


def test_archive_overwrite_warns():
    """#9: 同日重渲时归档 os.replace 静默覆盖上版 fill/quote——补覆盖告警，
    与 _write_html 的输出覆盖告警对称。"""
    fill = minimal_fill()
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "out.html")
        p = write_fill(fill, d, name="_fill_t.json")
        err1 = capture_stderr(lambda: R.render(p, out))
        assert "归档文件已存在" not in err1, "首次渲染无既有归档，不应告警"
        p = write_fill(fill, d, name="_fill_t.json")   # 首次渲染后源 fill 已被移入归档，重写再渲
        err2 = capture_stderr(lambda: R.render(p, out))
        assert "归档文件已存在" in err2, f"同日二次渲染归档覆盖应告警，实际 stderr: {err2}"


def test_cn_placeholder_gate():
    """#11: fill 正文【待填】类中文占位符硬拒渲染；a-d 字母开头的黄灯类别标注
    （【b 行业与政策环境】）是合法引用，放行。"""
    f = minimal_fill(l1_html="".join(_dim(_LONG_TEXT) for _ in range(5))
                     + _dim(_LONG_TEXT + "【待填】") + _L1_GOV_BLOCK)
    expect_valueerror(f, "中文占位符应拒", kw="残留中文占位符")
    f2 = minimal_fill(l1_html="".join(_dim(_LONG_TEXT) for _ in range(5))
                      + _dim(_LONG_TEXT + "【b 行业与政策环境】已逐项核查") + _L1_GOV_BLOCK)
    R.validate_content(f2, R.compute_valuation(f2))  # 合法豁免引用 → 放行


def test_internal_codes_warn():
    """#11: 正文泄漏框架内部代号（L1/L3/L4/1D）→ 告警改用章节编号/名称。"""
    l1 = ("".join(_dim(_LONG_TEXT) for _ in range(5))
          + _dim(_LONG_TEXT + "，详见 L1。") + _L1_GOV_BLOCK)
    out = validate_stderr(minimal_fill(l1_html=l1))
    assert "内部代号" in out, f"正文出现 L1 应告警，实际 stderr: {out}"
    assert "内部代号" not in validate_stderr(minimal_fill()), "fixture 正文无代号不应告警"


def test_thesis_info_floor_warn():
    """#11: thesis 只塞三个 span 价（信息量地板）→ 告警不能只写目标价。"""
    th = ('<span class="scenario-pess">7.2</span>/<span class="scenario-base">11</span>'
          '/<span class="scenario-opt">15.6</span>')
    out = validate_stderr(minimal_fill(thesis_html=th))
    assert "信息量不足" in out, f"纯三价 thesis 应告警，实际 stderr: {out}"
    th_ok = ("论点：测试公司具备长期竞争优势与稳定现金流，论据：近三年盈利持续增长"
             "且资产负债表稳健，三情景目标价 "
             '<span class="scenario-pess">7.2</span>/<span class="scenario-base">11</span>'
             '/<span class="scenario-opt">15.6</span> 元，结论：逢低布局。')
    assert "信息量不足" not in validate_stderr(minimal_fill(thesis_html=th_ok)), \
        "论点+论据+三价+结论齐备不应告警"


def test_object_fields_reject_arrays():
    """#14: 对象型字段（scores/layer_share/timing_weights）传数组 → 友好 ValueError，
    不得 AttributeError 裸崩。"""
    f = minimal_fill(scores=["1A", 7])
    try:
        R.validate_content(f, None)
    except ValueError as e:
        assert "scores" in str(e) and "需为对象" in str(e), f"报错文案不符: {e}"
    else:
        raise AssertionError("scores 传数组应拒渲染")
    expect_valueerror(minimal_fill(layer_share=["L1", "L3"]), "layer_share 数组应拒",
                      kw="layer_share 需为对象")
    expect_valueerror(minimal_fill(timing_weights=["筹码面", 50]), "timing_weights 数组应拒",
                      kw="timing_weights 需为对象")


def test_missing_thesis_warns():
    """#小2: thesis_html 缺失 → 告警 Hero 一句话结论为空（timing_scores/yellow_deductions
    缺项由 compute_scores 硬拒，不再 soft 告警重复，文案矛盾已除）。"""
    out = validate_stderr(minimal_fill(thesis_html=""))
    assert "thesis_html 缺失" in out, f"thesis 缺失应告警，实际 stderr: {out}"


def test_position_card_legend_single_source():
    """v5.8.2：仓位卡估值图例与判词口径一致——用户报告实际展示「4-5.9 合理」与
    _valuation_verdict「合理无安全边际」不符；图例单源常量 _Q_LEGEND/_V_LEGEND。"""
    import scoring
    html = R.build_position_card(quality=5.0, valuation=5.0,
                                 timing=5.0, calc=None, red_flag="")
    assert "4-5.9 合理无安全边际" in html, f"估值图例应与判词口径一致: {html}"
    assert "4-5.9 合理 /" not in html, "旧错误文案不得再出现"
    assert scoring._Q_LEGEND in html and scoring._V_LEGEND in html, "图例须引用单源常量"
    # 估值过程卡 legend 同源常量（第三份字面拷贝已收编）
    mcalc = {"central": 0.05, "central_raw": 0.05, "odds": 1.0, "dispersion": 0.5,
             "mode": "mcap", "horizon": "12个月",
             "rows": [{"key": "pess", "low": 7.0}, {"key": "base", "profit": None}]}
    inputs = {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7}
    vc_m = R.compute_valuation_score(mcalc, dict(inputs, consensus_np=80), gap_tier="B")
    card = R.build_valuation_process_card(mcalc, vc_m, inputs)
    assert f"估值分档位：{scoring._V_LEGEND}" in card, "过程卡图例须与常量逐字一致"


def test_v1_old_fill_still_renders_without_v2_marker():
    html = render_fill(minimal_fill())
    assert 'data-quality-version="1"' in html
    assert "评分 v2" not in html
    assert "风险评估（红/黄灯）— 质量轨门禁" in html
    assert "扣 0.0 分" in html
    assert "黄灯扣分：无" in html
    assert '<div class="s-sub">好公司</div>\n          \n        </div>' not in html


def test_new_date_requires_explicit_quality_version():
    expect_valueerror(minimal_fill(date="2026-10-24"), "quality_version", kw="quality_version")


def test_v2_rejects_handwritten_scores():
    fill = v2_fill()
    fill["scores"] = {key: 7 for key in ("1A", "1B", "1C", "1D", "1E", "1F", "3A", "3B", "3C")}
    expect_valueerror(fill, "手写 scores", kw="手写")


def test_v2_rejects_red_deductions():
    fill = v2_fill()
    fill["red_deductions"] = [{"item": "重复扣分", "points": 1}]
    expect_valueerror(fill, "red_deductions", kw="red_deductions")


def test_v2_missing_required_dimension_is_rejected():
    fill = v2_fill()
    del fill["score_inputs"]["1D"]
    expect_valueerror(fill, "1D", kw="1D")


def _visible_text(html):
    return re.sub(r"<[^>]+>", "", html)


def test_v2_render_injects_machine_version_and_readable_rule_details():
    html = render_v2_fill(v2_fill())
    text = _visible_text(html)
    assert 'data-quality-version="2"' in html
    assert "评分 v2" not in text
    assert 'data-dim="1A"' in html
    assert "1A.MATURE.CHECK" not in text
    assert "1F.ROIC_WACC" not in text
    assert "badge badge-green" in html
    assert "<!--SCORE_BADGE-->" not in html
    assert "<!--SCORE_DETAIL-->" not in html


def test_score_detail_explains_effective_cap_in_chinese():
    result = {"base": 9.0, "cap": 7.9, "final": 7.9, "rule_steps": [
        {"id": "1B.VALUE_CHAIN", "evidence": "成本/传导/集中度/议价状态", "delta": 0},
        {"id": "1B.CONCENTRATION.UNKNOWN", "evidence": "客户或供应商集中度未知", "delta": 0},
    ]}
    html = R._build_score_detail("1B", result, {})
    summary = _visible_text(re.search(r"<summary>(.*?)</summary>", html, re.S).group(1))
    assert "最终 7.90" in summary
    assert "定档起点 9.00" in summary
    assert "证据上限 7.90" in summary
    assert "客户或供应商集中度未知" in _visible_text(html)
    assert "1B.VALUE_CHAIN" not in _visible_text(html)
    assert 'data-rule-id="1B.CONCENTRATION.UNKNOWN"' in html


def test_score_detail_combines_regular_adjustments_in_summary():
    result = {"base": 6.0, "cap": 9.0, "final": 7.0, "rule_steps": [
        {"id": "1E.DIVIDEND", "evidence": "3", "delta": 0.5},
        {"id": "1E.BUYBACK", "evidence": "True", "delta": 0.5},
    ]}
    html = R._build_score_detail("1E", result, {})
    summary = _visible_text(re.search(r"<summary>(.*?)</summary>", html, re.S).group(1))
    assert "规则调整 +1.00" in summary
    assert summary.count("规则调整") == 1
    assert _visible_text(html).count("+0.50") == 2


def test_score_detail_shows_deduction_and_formats_financial_checks():
    spec = {
        "f_items": {"profit_positive": True, "ocf_positive": True, "roa_improving": False,
                    "cash_quality_ok": True, "long_debt_down": False,
                    "short_cover_improving": True, "no_dilution": True,
                    "gross_margin_improving": False, "asset_turnover_improving": True},
        "liquidity": {"debt_ratio": 0.35074714637536947, "short_cover": 0.6398691244981521,
                      "ocf_short_cover": 0.45615386649391765},
    }
    result = {"base": 5.0, "cap": 7.9, "final": 4.0, "rule_steps": [
        {"id": "1D.F.HITS", "evidence": "命中6/9", "delta": 0},
        {"id": "1D.LIQUIDITY", "evidence": str(spec["liquidity"]), "delta": 0},
        {"id": "1D.RED.RECEIVABLES", "evidence": "True", "delta": -1},
        {"id": "1D.GROSS_MARGIN_PEER.UNKNOWN", "evidence": "同业毛利率对照缺失，最高只能落B档", "delta": 0},
    ]}
    html = R._build_score_detail("1D", result, spec)
    summary = _visible_text(re.search(r"<summary>(.*?)</summary>", html, re.S).group(1))
    text = _visible_text(html)
    assert "最终 4.00" in summary and "应收恶化 −1.00" in summary
    assert "证据上限" not in summary
    assert "通过 6/9 项" in text
    for label in ("ROA 未改善", "长期有息负债未下降", "毛利率未改善"):
        assert label in text
    assert "有息负债/总资产 35.07%" in text
    assert "货币资金/短债 0.64 倍" in text
    assert "经营现金流/短债 0.46 倍" in text
    for raw in ("True", "False", "debt_ratio", "F.HITS", "LIQUIDITY"):
        assert raw not in text
    assert 'data-rule-id="1D.RED.RECEIVABLES"' in html


def test_score_detail_formats_cash_runway_to_two_decimals():
    result = {"base": 9.0, "cap": None, "final": 9.0,
              "rule_steps": [{"id": "1D.CASH_RUNWAY", "evidence": "59.52249294240183个月", "delta": 0}]}
    html = R._build_score_detail("1D", result, {"cash_runway_months": 59.52249294240183})
    assert "59.52 个月" in _visible_text(html)
    assert "59.52249294240183" not in _visible_text(html)


def test_score_detail_keeps_negative_adjustments_visible_when_combining():
    result = {"base": 6.0, "cap": 9.0, "final": 7.0, "rule_steps": [
        {"id": "1E.REDUCTION", "evidence": "0.03", "delta": -1},
        {"id": "1E.DIVIDEND", "evidence": "3", "delta": 0.5},
        {"id": "1E.BUYBACK", "evidence": "True", "delta": 0.5},
        {"id": "1E.LONG_RECORD", "evidence": "True", "delta": 1},
    ]}
    html = R._build_score_detail("1E", result, {})
    summary = _visible_text(re.search(r"<summary>(.*?)</summary>", html, re.S).group(1))
    assert "规则调整 +2.00" in summary
    assert "减持 −1.00" in summary


def test_score_detail_shows_raw_and_merged_financial_check_counts():
    spec = {"f_items": {
        "profit_positive": True, "ocf_positive": True, "roa_improving": True,
        "cash_quality_ok": True, "long_debt_down": True, "short_cover_improving": False,
        "no_dilution": False, "gross_margin_improving": False, "asset_turnover_improving": False,
    }}
    result = {"base": 7, "cap": None, "final": 7, "rule_steps": [
        {"id": "1D.F.HITS", "evidence": "原始5/9，因果归并后6/9", "delta": 0},
    ]}
    text = _visible_text(R._build_score_detail("1D", result, spec))
    assert "通过 6/9 项（因果归并前 5/9 项）" in text
    assert "原始未通过" in text


def test_score_detail_formats_normalized_roic_numeric_strings():
    result = {"base": 9, "cap": None, "final": 9, "rule_steps": [
        {"id": "1F.ROIC_COMPONENTS", "evidence": "['0.07', '0.10', '0.12']", "delta": 0},
    ]}
    text = _visible_text(R._build_score_detail(
        "1F", result, {"roic_normalized_components": ["0.07", "0.10", "0.12"]}))
    assert "7.00% / 10.00% / 12.00%" in text


@pytest.mark.parametrize("key,rule_id,evidence,delta,expected", [
    ("1D", "1D.G.ROA", "True", 0, "ROA：通过"),
    ("1F", "1F.INCREMENTAL_ROIC", "0.18", 1, "增量 ROIC：18.00%"),
    ("1D", "1D.CASH_RUNWAY", "59.52249294240183个月", 0, "现金跑道：59.52 个月"),
    ("1E", "1E.SUCCESSION", "70", -0.5, "继任风险：负责人 70 岁，未披露继任安排"),
])
def test_score_detail_names_supplemental_observations(key, rule_id, evidence, delta, expected):
    result = {"base": 6, "cap": None, "final": 6 + delta,
              "rule_steps": [{"id": rule_id, "evidence": evidence, "delta": delta}]}
    assert expected in _visible_text(R._build_score_detail(key, result, {}))


def test_score_summary_uses_chinese_red_flag_names():
    fill = v2_fill()
    fill["score_inputs"]["1D"]["red_flags"]["receivables"] = True
    text = _visible_text(render_v2_fill(fill))
    assert "红旗扣分 1.0：应收恶化" in text
    assert "True" not in text and "False" not in text


def test_score_detail_does_not_blame_evidence_cap_for_band_clamp():
    result = {"base": 5, "pre_cap": 5.9, "cap": 5.9, "final": 5.9,
              "custom": {"id": "CUSTOM.TEST"}, "rule_steps": [
                  {"id": "1C.PRESSURE.UNKNOWN", "evidence": "压力测试未知，最高只能落B档", "delta": 0},
                  {"id": "CUSTOM.TEST", "evidence": "补充判断", "delta": 1},
              ]}
    html = R._build_score_detail("1C", result, {})
    summary = _visible_text(re.search(r"<summary>(.*?)</summary>", html, re.S).group(1))
    assert "证据上限" not in summary
    assert "档位边界限制" in summary


def test_peers_meta_mere_metric_mention_does_not_waive_direction_warning():
    peers_html = ('<div class="table-scroll"><table><tr><th>公司</th><th>PE(TTM)</th><th>ROE</th></tr>'
                  '<tr><td>测试股份</td><td>11</td><td class="cell-best">34</td></tr>'
                  '<tr><td>同业甲</td><td>25</td><td class="cell-worst">12</td></tr>'
                  '</table></div><span class="source">数据来源：测试</span>')
    out = validate_stderr(minimal_fill(peers_meta="PE 是估值指标，需结合盈利质量", peers_html=peers_html))
    assert "缺最优/最差标注" in out and "PE(TTM)" in out


def test_risk_register_hides_internal_rule_id_from_readers():
    fill = v2_fill()
    fill["score_inputs"]["1D"]["red_flags"]["receivables"] = True
    fill["risk_items"] = [{"name": "应收恶化", "status": "hit", "evidence": "周转天数连续上升",
                            "impact": "quality", "home": "1D", "trigger": "周转天数继续上升",
                            "source": "公司公告", "rule_id": "1D.RED.RECEIVABLES"}]
    html = R.build_risk_register(fill)
    assert "4.4 财务健康" in _visible_text(html)
    assert "1D.RED" not in _visible_text(html)
    assert 'data-rule-id="1D.RED.RECEIVABLES"' in html


def test_v2_red_flags_stay_in_1d_and_two_hits_require_warning():
    fill = v2_fill()
    fill["score_inputs"]["1D"]["red_flags"].update(receivables=True, inventory=True)
    sc = R.compute_scores(fill)
    assert sc["red_total"] == 2
    assert sc["dimension_results"]["1D"]["final"] == 7
    assert sc["dimension_results"]["1C"]["final"] == 9
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "利润真实性存疑", kw="利润真实性存疑")
        fill["conclusion_html"] = "利润真实性存疑：应收与存货连续恶化。" + fill["conclusion_html"]
        R.validate_content(fill, R.compute_valuation(fill), sc)


def test_v2_extreme_score_requires_counter_evidence():
    fill = v2_fill()
    del fill["score_inputs"]["1C"]["counter_evidence"]
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "反方证据", kw="反方证据")


def test_v2_archive_index_contains_version_and_score_metadata():
    import json
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(v2_fill(), d)
        path = write_fill(fill, d)
        R.render(path, out_path=os.path.join(d, "out.html"))
        row = json.loads(open(os.path.join(d, "_archive", "_index.jsonl"), encoding="utf-8").readline())
        assert row["quality_version"] == 2
        assert row["scores"]["1F"] == 9
        assert row["weights"]["1F"] == 20
        assert row["layer_share"] == {"L1": 70, "L3": 30}


def test_v2_industry_red_flags_derive_warning_without_second_deduction():
    fill = v2_fill(industry_profile="financial_bank")
    fill["score_inputs"]["1D"] = {
        "kind": "industry_checklist",
        "industry_checks": {"npl_trend": True, "provision_trend": True,
                            "loan_migration": False, "cet1": False},
    }
    fill["score_inputs"]["1B"] = {
        "cost_strength": "strong", "pricing_strength": "neutral", "bargaining_status": "正常",
        "customer_concentration": 0.1, "supplier_concentration": 0.1,
    }
    fill["score_inputs"]["1F"] = {
        "return_metric": "ROE_NORMALIZED", "normalized_return": 0.12, "coe": 0.08,
        "dupont_driver": "净利率",
    }
    sc = R.compute_scores(fill)
    assert len(sc["financial_red_flags"]) == 2
    assert sc["red_total"] == 0
    with tempfile.TemporaryDirectory() as d:
        fill = prepare_v2_quote(fill, d)
        expect_valueerror(fill, "利润真实性存疑", kw="利润真实性存疑")
        fill["conclusion_html"] = "利润真实性存疑：资产质量两项恶化。" + fill["conclusion_html"]
        fill["score_inputs"]["1F"]["counter_evidence"] = "资产质量恶化可能拖累未来资本回报"
        R.validate_content(fill, R.compute_valuation(fill), sc)


def test_fixed_web_guidance_contract():
    template_path = os.path.join(os.path.dirname(R.__file__), "..", "assets", "report-template.html")
    template = open(template_path, encoding="utf-8").read()
    for marker in (
        "text-wrap: balance",
        "text-wrap: pretty",
        "prefers-reduced-motion: no-preference",
        "@supports (content-visibility: auto)",
        "content-visibility: visible",
    ):
        assert marker in template, f"固定 Web 契约锚点缺失：{marker}"
    html = render_fill(minimal_fill())
    assert ('<div class="table-scroll" tabindex="0" role="region" '
            'aria-label="数据表格（可横向滚动）">') in html
