#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_position.py — render_report 决策层回归：仓位临界档透明化/乐观税门禁/赔率∞地板分级/估值锚纪律域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from scoring import (
    _position_steps, _edge_info, build_edge_upgrade_rows,
)
from conftest import (
    minimal_fill, full_fill, _calc, expect_valueerror, validate_stderr,
    write_fill, render_fill, v2_fill, render_v2_fill,
)


def test_v2_critical_weaknesses_only_core_dimensions():
    for key in ("1C", "1D", "1E", "1F", "3A", "3C"):
        fill = v2_fill()
        spec = fill["score_inputs"][key]
        if key == "1C":
            spec["moats"] = []
        elif key == "1D":
            spec["f_items"] = {name: False for name in spec["f_items"]}
        elif key == "1E":
            spec.update(pledge_pct=0.8, reduction_pct=0.03, age=70, penalties=1,
                        succession_plan=False, dividend={}, buyback={})
        elif key == "1F":
            spec["roic"] = 0.01
        elif key == "3A":
            spec.update(growth_lo=-1, growth_hi=-0.5, driver_status="未验证")
        else:
            spec["events"] = []
        sc = R.compute_scores(fill)
        assert sc["dimension_results"][key]["final"] < 4
        expected = [key] if key in ("1C", "1D", "1E", "1F") else []
        assert [item["key"] for item in sc["critical_weaknesses"]] == expected


def test_critical_weakness_downgrades_each_core_once():
    for key in ("1C", "1D", "1E", "1F"):
        label, steps, _slot, _crit = _position_steps(
            7.5, 8.5, 5.0, _calc(), "", critical=[{"key": key, "score": 3.5}])
        assert label == "标准仓 ≤10%（重仓 ≤20%·关键短板）"
        assert sum("关键短板降档" in step for step in steps) == 1
        assert key in next(step for step in steps if "关键短板降档" in step)


def test_critical_applies_last_and_preserves_other_terminal_states():
    label, steps, _slot, _crit = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="net_cash"), "",
        critical=[{"key": "1D", "score": 3.5}])
    assert label == "轻仓 ≤5%（标准仓 ≤10%·关键短板）"
    assert steps[0].startswith("赔率调节") and "关键短板降档" in steps[-1]
    for quality, valuation, red_flag, expected in (
            (4.5, 4.5, "", "不建议参与"), (7.5, 3.0, "", "观察池"),
            (7.5, 8.5, "审计非标", "不建议参与")):
        label, steps, _slot, _crit = _position_steps(
            quality, valuation, 3.5 if expected == "不建议参与" and not red_flag else 5.0,
            _calc(dispersion=0.95 if expected == "不建议参与" and not red_flag else 0.55),
            red_flag, critical=[{"key": "1D", "score": 3.5}])
        assert label == expected
        assert not any("关键短板降档" in step for step in steps)


def test_v2_render_applies_critical_without_capping_quality():
    fill = v2_fill()
    fill["score_inputs"]["1C"]["moats"] = []
    sc = R.compute_scores(fill)
    assert sc["quality"] == 7.74 and sc["dimension_results"]["1C"]["final"] == 2
    html = render_v2_fill(fill)
    assert "观察池（轻仓 ≤5%·关键短板）" in html
    assert "质量分不变" in html and "1C" in html
    decision = html.split("最终仓位结论：", 1)[1].split("</div>", 1)[0]
    assert "不建议参与" not in decision
    assert "badge badge-orange badge-lg\">观察池" in decision


# ---------------- v5.0 决策层三机制（临界档透明化 / 乐观税门禁 / 赔率∞地板分级） ----------------
def test_position_steps_edge_critical():
    """v5.0 机制一（临界档透明化）：距最近边界 ≤0.3 → 有效分压到边界下侧（相邻两档孰低），
    上浮类调节（时机≥6/离散度<40%/赔率∞）一律冻结、下调照常；slot_txt 带临界说明。"""
    # q=7.2 临界（距 7.0 边界 0.2）→ 降档落 10 档（中上·好价格）；三条上浮路径全冻结
    label, steps, slot, crit = _position_steps(
        7.2, 8.5, 7.0, _calc(dispersion=0.30, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%", f"临界降档+上浮冻结应止步标准仓，实际 {label}"
    assert [c["track"] for c in crit] == ["质量"] and abs(crit[0]["dist"] - 0.2) < 1e-9
    assert "档位临界：质量分 7.20 距 7.0 边界 0.20，按相邻两档孰低降档执行" in slot
    assert sum("上浮冻结" in s for s in steps) == 3, f"三条上浮路径应全冻结：{steps}"
    assert "重仓" not in label
    # q=7.0 恰在边界（dist=0）→ 同样降档
    label, steps, slot, crit = _position_steps(7.0, 8.5, 5.0, _calc(), "")
    assert label == "标准仓 ≤10%" and crit and crit[0]["dist"] == 0.0
    # v=8.2 临界 → 落「中上·合理偏便宜」5 档（质量 5.5-7 行 × 估值 6-8 列）
    label, steps, slot, crit = _position_steps(6.0, 8.2, 5.0, _calc(), "")
    assert label == "轻仓 ≤5%" and [c["track"] for c in crit] == ["估值"]
    assert "估值分 8.20 距 8.0 边界 0.20" in slot
    # 临界 + 时机 3.5 → 下调照常（10 档 → 5 档），无冻结噪音
    label, steps, slot, crit = _position_steps(7.2, 8.5, 3.5, _calc(), "")
    assert label == "轻仓 ≤5%", f"下调照常应落轻仓，实际 {label}"
    assert any("下调一档" in s for s in steps) and not any("上浮冻结" in s for s in steps)
    # 非临界对照：7.5×8.5 直落重仓，crit 为空
    label, steps, slot, crit = _position_steps(7.5, 8.5, 5.0, _calc(), "")
    assert label == "重仓 ≤20%" and crit == []
    # 双轨同时临界：7.2×8.2 → 双双降档（中上·合理偏便宜 5 档）
    label, steps, slot, crit = _position_steps(7.2, 8.2, 5.0, _calc(), "")
    assert label == "轻仓 ≤5%" and len(crit) == 2


def test_position_steps_odds_floor_gate():
    """v5.0 机制三（调节链侧）：赔率 ∞ 上浮一档仅硬地板=net_cash 享受；dividend 软地板
    记「估值分 +1 封顶 7.5，调节链不上浮」；floor 缺失不上浮（防御，validate 已硬拒）。"""
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="net_cash"), "")
    assert label == "标准仓 ≤10%"
    assert steps == ["赔率调节：赔率 ∞（悲观仍正收益） → 上浮一档（轻仓 ≤5%→标准仓 ≤10%）"], steps
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None, floor_type="dividend"), "")
    assert label == "轻仓 ≤5%"
    assert steps == ["赔率 ∞（软地板=保底分红折现）：估值分 +1 封顶 7.5，调节链不上浮"], steps
    label, steps, _s, _c = _position_steps(
        4.5, 4.5, 5.0, _calc(dispersion=0.50, odds=None), "")
    assert label == "轻仓 ≤5%" and steps == ["矩阵落位直接生效，无调节项触发"], steps


def test_optimism_tax_gate():
    """v5.0 机制二（乐观税门禁）：base 净利 ÷ 一致预期 > 1.15 且非 A 档 → 中枢分封顶 6
    重算总分；A 档解封；缺 consensus_np 跳过（tax=None）；过程卡三态标注。"""
    calc = R.compute_valuation(minimal_fill())   # base 情景 profit=100
    inputs = {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7}
    # ratio = 100/80 = 1.25 > 1.15，gap_tier=B → 中枢 7.0 封顶 6 → 总分 6×.4+3.5×.25+5×.25+6×.1=5.1
    vc = R.compute_valuation_score(calc, dict(inputs, consensus_np=80), gap_tier="B")
    assert vc["tax"]["capped"] is True and vc["tax"]["exempt"] is False
    assert abs(vc["tax"]["ratio"] - 1.25) < 1e-9
    assert vc["central_s"] == 6.0 and vc["score"] == 5.1
    # A 档解封（去空格大写判定）：不封顶，分数回 5.5
    vc_a = R.compute_valuation_score(calc, dict(inputs, consensus_np=80), gap_tier=" a ")
    assert vc_a["tax"]["exempt"] is True and vc_a["tax"]["capped"] is False
    assert vc_a["central_s"] == 7.0 and vc_a["score"] == 5.5
    # ratio ≤ 1.15 不触发（1.10 → 不封不免注）
    vc_lo = R.compute_valuation_score(calc, dict(inputs, consensus_np=91), gap_tier="B")
    assert vc_lo["tax"]["capped"] is False and vc_lo["central_s"] == 7.0
    # 缺 consensus_np → tax=None 跳过
    vc_n = R.compute_valuation_score(calc, inputs)
    assert vc_n["tax"] is None and vc_n["score"] == 5.5
    # F16：consensus_np 键存在但 ≤0（亏损预期）→ legend 单列，与「无卖方覆盖」区分
    card_neg = R.build_valuation_process_card(calc, vc_n, dict(inputs, consensus_np=-5))
    assert "一致预期为负/零，乐观税不适用" in card_neg and "无卖方覆盖" not in card_neg
    card_zero = R.build_valuation_process_card(calc, vc_n, dict(inputs, consensus_np=0))
    assert "一致预期为负/零，乐观税不适用" in card_zero
    # 过程卡标注三态
    card = R.build_valuation_process_card(calc, vc, dict(inputs, consensus_np=80))
    assert "乐观税封顶 6" in card and "1.25" in card and "A 档" in card
    card_a = R.build_valuation_process_card(calc, vc_a, dict(inputs, consensus_np=80))
    assert "乐观税已检" in card_a and "A 档解封" in card_a
    card_n = R.build_valuation_process_card(calc, vc_n, inputs)
    assert "乐观税未检：无卖方覆盖" in card_n
    # mcap 口径：base 无 profit → tax=None，legend 标市值口径
    mcalc = {"central": 0.05, "central_raw": 0.05, "odds": 1.0, "dispersion": 0.5,
             "mode": "mcap", "horizon": "12个月",
             "rows": [{"key": "pess", "low": 7.0}, {"key": "base", "profit": None}]}
    vc_m = R.compute_valuation_score(mcalc, dict(inputs, consensus_np=80), gap_tier="B")
    assert vc_m["tax"] is None
    assert "乐观税未检：市值口径无净利可比" in R.build_valuation_process_card(mcalc, vc_m, inputs)


def test_floor_uplift_grading():
    """v5.0 机制三（估值分侧）：赔率 ∞ 上浮分级——net_cash 硬地板 max(score,8.0)；
    dividend 软地板 +1 封顶 7.5（保送不减分）；floor 缺失不上浮；过程卡赔率行与 legend 标注。"""
    inputs = {"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": 1.7}
    # 底分：中枢 5%→6.0×0.4 + 赔率∞→10×0.25 + 合理倍数 5.0×0.25 + 股息 6.0×0.1 = 6.75→6.8
    base_calc = {"central": 0.05, "central_raw": 0.05, "odds": None, "dispersion": 0.5,
                 "horizon": "12个月",
                 "rows": [{"key": "pess", "low": 10.5}, {"key": "base", "profit": 100}]}
    vc = R.compute_valuation_score(
        dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5,
                                    "evidence": "净现金125亿÷总股本10亿"}), inputs)
    assert vc["score"] == 8.0
    assert vc["floor_uplift"] == {"type": "net_cash", "before": 6.8, "after": 8.0}
    vc2 = R.compute_valuation_score(
        dict(base_calc, pess_floor={"type": "dividend", "value": 10.6,
                                    "evidence": "保底分红0.7元/股×15年折现"}), inputs)
    assert vc2["score"] == 7.5 and vc2["floor_uplift"]["type"] == "dividend"
    vc3 = R.compute_valuation_score(base_calc, inputs)
    assert vc3["score"] == 6.8 and vc3["floor_uplift"] is None
    # 过程卡赔率分行地板信息 + legend 上浮说明（软地板注明调节链不上浮）
    calc_hard = dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5,
                                            "evidence": "净现金125亿÷总股本10亿"})
    calc_soft = dict(base_calc, pess_floor={"type": "dividend", "value": 10.6,
                                            "evidence": "保底分红0.7元/股×15年折现"})
    card = R.build_valuation_process_card(calc_hard, vc, inputs)
    assert "悲观下限 10.5 ≥ 现价" in card and "硬地板=净现金/股 12.5：净现金125亿÷总股本10亿" in card
    assert "上浮至 8" in card
    card2 = R.build_valuation_process_card(calc_soft, vc2, inputs)
    assert "软地板=保底分红折现/股 10.6" in card2 and "调节链不上浮" in card2
    # F14：floor.type 空白/大小写归一（compute_valuation 透传层，三处消费口径同源）
    f_nc = minimal_fill()
    f_nc["valuation"]["scenarios"][0]["floor"] = {"type": " Net_Cash ", "value": 6.5,
                                                  "evidence": "净现金65亿÷总股本10亿"}
    assert R.compute_valuation(f_nc)["pess_floor"]["type"] == "net_cash"
    # F15：floor.evidence / metric_label 进过程卡前逐段 _esc（不双重转义、不裸注入）
    ev = '净现金 A&B <实测> "引号"'
    calc_ev = dict(base_calc, pess_floor={"type": "net_cash", "value": 12.5, "evidence": ev})
    card_ev = R.build_valuation_process_card(calc_ev, vc, inputs)
    assert "A&amp;B &lt;实测&gt; &quot;引号&quot;" in card_ev and ev not in card_ev, \
        "evidence 应转义一次且不双重转义"
    card_ml = R.build_valuation_process_card(base_calc, vc3, dict(inputs, metric_label="PE<b>"))
    assert "PE&lt;b&gt;" in card_ml


def test_odds_floor_validate():
    """v5.0 机制三（校验侧 _check_odds_floor）：悲观下限 ≥ 现价（赔率 ∞）时——无 floor 拒 /
    type 非法拒 / evidence 空拒 / floor.value < 下限×0.99 拒 / 合规硬软地板过；
    赔率有限时 floor 软告警（无作用可删）。"""
    def odds_inf_fill(floor=None):
        f = minimal_fill()
        # 悲观下限 = 110×9.5/100 = 10.45 ≥ 现价 10；中枢 11 ≤ base 中枢 11，不触倒挂
        f["valuation"]["scenarios"][0] = {"key": "pess", "label": "悲观", "trigger": "下行",
                                          "profit": 110, "pe": [9.5, 10.5]}
        if floor:
            f["valuation"]["scenarios"][0]["floor"] = floor
        f["thesis_html"] = f["thesis_html"].replace(
            '<span class="scenario-pess">7.2</span>', '<span class="scenario-pess">11</span>')
        return f
    expect_valueerror(odds_inf_fill(), "赔率 ∞ 无地板应拒渲染")
    expect_valueerror(odds_inf_fill({"type": "净资产", "value": 11, "evidence": "x"}),
                      "floor.type 非法应拒")
    expect_valueerror(odds_inf_fill({"type": "net_cash", "value": 11, "evidence": ""}),
                      "floor.evidence 空应拒")
    expect_valueerror(odds_inf_fill({"type": "net_cash", "value": 10.0,
                                     "evidence": "净现金100亿÷总股本10亿"}),
                      "地板值 10.0 < 悲观下限 10.45×0.99 应拒")
    ok = odds_inf_fill({"type": "net_cash", "value": 10.5, "evidence": "净现金105亿÷总股本10亿"})
    R.validate_content(ok, R.compute_valuation(ok))   # 硬地板合规 → 过
    ok2 = odds_inf_fill({"type": "dividend", "value": 10.5, "evidence": "保底分红0.7元/股×15年折现"})
    R.validate_content(ok2, R.compute_valuation(ok2))  # 软地板合规 → 过
    # 赔率有限（下限 < 现价）+ floor → 软告警不拒
    f = minimal_fill()
    f["valuation"]["scenarios"][0]["floor"] = {"type": "net_cash", "value": 6.5,
                                               "evidence": "净现金65亿÷总股本10亿"}
    out = validate_stderr(f)
    assert "floor" in out and "无作用" in out, "赔率有限时 floor 应软告警"
    # F17：floor 写在 base/opt → 软告警不拒（floor 是悲观情景子键，写错位置不生效）
    f = minimal_fill()
    f["valuation"]["scenarios"][1]["floor"] = {"type": "net_cash", "value": 6.5,
                                               "evidence": "净现金65亿÷总股本10亿"}
    out = validate_stderr(f)
    assert "floor" in out and "写错位置不生效" in out, "floor 写错位置应软告警"
    # F17：相等边界（悲观下限 == 现价）报错文案用「不低于（≥）」而非「高于」
    f_eq = minimal_fill()
    f_eq["valuation"]["scenarios"][0] = {"key": "pess", "label": "悲观", "trigger": "下行",
                                         "profit": 100, "pe": [10, 11]}  # 下限=100×10÷100=10 == 现价
    f_eq["thesis_html"] = f_eq["thesis_html"].replace(
        '<span class="scenario-pess">7.2</span>', '<span class="scenario-pess">10.5</span>')
    try:
        R.validate_content(f_eq, R.compute_valuation(f_eq))
        raise AssertionError("下限等于现价且无地板应拒")
    except ValueError as e:
        assert "不低于" in str(e) and "≥" in str(e), f"文案应改「不低于（≥）」，实际 {e}"


def test_consensus_np_cross_check():
    """v5.0 机制二（校验侧 _check_consensus_np）：valuation_inputs.consensus_np 照抄落盘
    consensus_np.np_avg——一致过 / 偏差 >1% 拒 / fill 有值落盘无键拒（手估嫌疑）/
    落盘有 fill 无软告警（漏抄，乐观税未检）/ 双向皆缺过。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "consensus_np": {"year": 2026, "np_avg": 100.0, "orgs": 12}},
                         d, name="em_ref.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["consensus_np"] = 100.5   # 0.5% 偏差 → 过
        R.validate_content(f, R.compute_valuation(f))
        f = minimal_fill(quote=q)
        f["valuation_inputs"]["consensus_np"] = 105.0   # 5% 偏差 → 拒
        expect_valueerror(f, "consensus_np 与落盘偏差>1% 应拒")
        # fill 有值落盘无键 → 拒（手估嫌疑）
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref2.json")
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"})
        f["valuation_inputs"]["consensus_np"] = 100.0
        expect_valueerror(f, "落盘无 consensus_np 键而 fill 手填应拒")
        # 落盘有 fill 无 → 软告警（漏抄，乐观税未检）
        out = validate_stderr(minimal_fill(quote=q))
        assert "consensus_np" in out and "漏抄" in out, "落盘有 fill 无应软告警"
        # 双向皆缺 → 通过且无告警
        out2 = validate_stderr(minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}))
        assert "consensus_np" not in out2, "双向皆缺不应告警"


def test_edge_upgrade_rows():
    """v5.0 机制一：build_edge_upgrade_rows 输出——每条临界轨一条 pending 灰态 trig
    （升档路径 + 复核证据），块首 section-tag；空 crit 返回空串。"""
    crit, q_eff, v_eff = _edge_info(7.2, 8.5)
    assert len(crit) == 1 and q_eff < 7.0 and v_eff == 8.5
    html = build_edge_upgrade_rows(crit)
    assert "档位临界升档路径（脚本生成）" in html
    assert "档位临界升档复核：质量分 7.20（距 7.0 边界 0.20）" in html
    assert "复核期质量分 ≥7.31" in html and "复核证据" in html
    assert 'trig-dot pending' in html and '<span class="trig-status pending">待验证</span>' in html
    assert build_edge_upgrade_rows([]) == ""
    # 下侧临界（6.8 距 7.0 为 0.2）：有效分压边界下侧但档位归属不变（行为等价孰低）
    crit2, q_eff2, _v2 = _edge_info(6.8, 5.0)
    assert len(crit2) == 1 and crit2[0]["bound"] == 7.0
    assert 6.8 < q_eff2 < 7.0
    assert "质量分 6.80（距 7.0 边界 0.20）" in build_edge_upgrade_rows(crit2)


def test_position_card_edge_badge():
    """v5.0 机制一：三轨判定卡临界轨 sub 追加「档位临界」橙徽章 + 距离说明；非临界不带。"""
    html = R.build_position_card(quality=7.2, valuation=8.5,
                                 timing=5.0, calc=_calc(), red_flag="")
    assert '<span class="badge badge-orange">档位临界</span>' in html
    assert "距 7.0 边界 0.20，按降档执行" in html
    assert "标准仓 ≤10%" in html, "临界降档应落中上·好价格 10 档"
    html2 = R.build_position_card(quality=7.5, valuation=8.5,
                                  timing=5.0, calc=_calc(), red_flag="")
    assert "档位临界" not in html2, "非临界不应带徽章"
    html3 = R.build_position_card(quality=6.0, valuation=8.2,
                                  timing=5.0, calc=_calc(), red_flag="")
    assert "距 8.0 边界 0.20，按降档执行" in html3, "估值轨临界徽章"


def test_edge_upgrade_mounted_in_ch14():
    """v5.0 机制一：升档路径行挂 14 章跟踪仪表盘（TRIGGERS_HTML 拼接）；红灯熔断时不挂
    （仓位未走矩阵）。minimal_fill 质量分恰 7.00（dist 0）→ 渲染必出临界行。"""
    html = render_fill(minimal_fill())
    s14 = html.split('id="s14"', 1)[1]
    assert "档位临界升档路径（脚本生成）" in s14
    assert "档位临界升档复核：质量分 7.00（距 7.0 边界 0.00）" in s14
    f = minimal_fill(red_flag="测试红灯占位",
                     position_html="<p>不建议参与。" + "时机判定与决策逻辑。" * 12 + "</p>")
    html2 = render_fill(f)
    assert "档位临界升档路径" not in html2, "红灯熔断时不得挂临界升档行"


def test_net_cash_floor_edge_exemption():
    """F3 机制碰撞修复：net_cash 硬地板上浮恰落 8.0 → 估值轨豁免临界判定（落点是机制产物
    非测量噪声）——票面 8.0 不挂临界徽章、矩阵按 8.0 落 ≥8 列、赔率 ∞ 上浮不冻结；
    对照：不传 floor_uplift 旧行为仍判临界；dividend 软地板落 7.5 行为不变；
    质量轨临界+估值轨豁免组合只质量降档。"""
    calc = _calc(dispersion=0.50, odds=None, floor_type="net_cash")
    fu = {"type": "net_cash", "before": 6.8, "after": 8.0}
    # 底分 6.8 上浮 8.0 + 质量 7.5 → 矩阵直落「好公司·好价格」重仓，crit 空、无徽章
    label, steps, slot, crit = _position_steps(7.5, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label == "重仓 ≤20%" and crit == [], f"豁免后应直落重仓，实际 {label}/{crit}"
    assert "档位临界" not in slot
    # 对照：不传 floor_uplift（旧行为）→ 恰落 8.0 判临界，降档 10 档 + 上浮冻结
    label2, steps2, slot2, crit2 = _position_steps(7.5, 8.0, 5.0, calc, "")
    assert label2 == "标准仓 ≤10%" and [c["track"] for c in crit2] == ["估值"]
    assert "估值分 8.00 距 8.0 边界 0.00" in slot2
    # 质量轨临界 + 估值轨豁免 → 只质量降档（中上·好价格 10 档）
    label3, _s3, slot3, crit3 = _position_steps(7.2, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label3 == "标准仓 ≤10%" and [c["track"] for c in crit3] == ["质量"]
    assert "估值分 8.00 距" not in slot3, "估值轨豁免后不挂临界说明"
    # dividend 软地板落 7.5 → 不豁免（本就不临界），落 6-7.9 列行为不变
    fu_d = {"type": "dividend", "before": 6.8, "after": 7.5}
    label4, _s4, _sl4, crit4 = _position_steps(7.5, 7.5, 5.0, _calc(odds=None, floor_type="dividend"),
                                               "", floor_uplift=fu_d)
    assert label4 == "标准仓 ≤10%" and crit4 == []
    # 赔率 ∞ 上浮生效轨迹（不被没收）：质量 4.5 落轻仓 → 硬地板上浮标准仓
    label5, steps5, _sl5, _c5 = _position_steps(4.5, 8.0, 5.0, calc, "", floor_uplift=fu)
    assert label5 == "标准仓 ≤10%"
    assert any("赔率调节" in s and "上浮一档" in s for s in steps5), f"上浮轨迹应出现：{steps5}"
    # _edge_info 直测：豁免后 crit 空且有效分保持 8.0（矩阵按 ≥8 列落位）
    crit_e, _q_e, v_eff_e = _edge_info(7.5, 8.0, fu)
    assert crit_e == [] and v_eff_e == 8.0
    # 卡片口径（build_position_card 透传 floor_uplift）：票面 8.0 无临界徽章、落重仓
    html = R.build_position_card(quality=7.5, valuation=8.0,
                                 timing=5.0, calc=calc, red_flag="", floor_uplift=fu)
    assert "档位临界" not in html and "重仓 ≤20%" in html


def test_position_edge_true_min():
    """临界孰低必须两侧实算（热核审计发现）：矩阵质量 5.5 行非单调（v<6 时上侧=观察池、
    下侧=质地一般 5），只算压边界一侧会把观察池抬成轻仓——违反「降档不抬档」。"""
    # 5.5 边界 + v<6：原落位观察池，压边界后 5 → 孰低=观察池（修复前误抬轻仓）
    label, steps, slot, crit = _position_steps(5.6, 5.0, 5.0, None, "")
    assert label == "观察池" and "中上·差价格" in slot and "观察池" in slot, \
        f"孰低应保观察池，实际 {label}/{slot}"
    assert [c["track"] for c in crit] == ["质量"] and "孰低" in slot
    # 同边界 + v≥8：原 10、压边界 5 → 孰低=5（正常降档方向不受影响）
    label2, _s2, _sl2, _c2 = _position_steps(5.6, 8.5, 5.0, None, "")
    assert label2 == "轻仓 ≤5%", f"实际 {label2}"
    # 下侧临界（6.8 近 7.0）：两侧同行，落位不变
    label3, _s3, _sl3, crit3 = _position_steps(6.8, 8.5, 5.0, None, "")
    assert label3 == "标准仓 ≤10%" and [c["track"] for c in crit3] == ["质量"]
    # 4.0 边界上侧（4.15）：原轻仓 5、压边界 0 → 孰低=不建议参与（设计内陡降，钉住）
    label4, _s4, _sl4, _c4 = _position_steps(4.15, 5.0, 5.0, None, "")
    assert label4 == "不建议参与", f"实际 {label4}"
    # 非临界对照（5.9 距 5.5 为 0.4）：观察池、无临界
    label5, _s5, _sl5, crit5 = _position_steps(5.9, 5.0, 5.0, None, "")
    assert label5 == "观察池" and crit5 == []


def test_anchor_discipline():
    """v5.1.0 估值锚纪律门禁（增量证据锁死 + 回滚条款前置）。
    full_fill 合规形态：上版 base PE 11-13x ≠ 本版 10-12x，附基本面证据 → 通过。"""
    # 合规基线：full_fill 本身应通过（台账+证据清单渲染路径的 golden 覆盖）
    R.validate_content(full_fill(), R.compute_valuation(full_fill()))
    # ① 回测模式 prev.scenarios 缺失 → 拒
    f = full_fill()
    f["prev"] = {"date": "2026-08-08", "quality": 6.4, "valuation": 5.0, "timing": 4.8,
                 "target_range": "9-11"}
    expect_valueerror(f, "回测模式 prev.scenarios 缺失应拒")
    # ② PE 带移动但无 pe_band_evidence → 拒
    f = full_fill()
    del f["valuation"]["pe_band_evidence"]
    expect_valueerror(f, "PE 带移动但无增量证据应拒")
    # ③ 证据仅有价格类 → 拒（纯价格证据不构成移动理由）
    f = full_fill()
    f["valuation"]["pe_band_evidence"] = [{"type": "价格", "note": "股价一个月下跌 16.6%"}]
    expect_valueerror(f, "纯价格证据应拒")
    f["valuation"]["pe_band_evidence"] = [{"type": "卖方观点", "note": "券商集体下修目标价"}]
    expect_valueerror(f, "纯卖方观点应拒")
    # ④ type 非法 / note 空 → 拒
    f = full_fill()
    f["valuation"]["pe_band_evidence"] = [{"type": "直觉", "note": "感觉要跌"}]
    expect_valueerror(f, "非法 type 应拒")
    f["valuation"]["pe_band_evidence"] = [{"type": "基本面", "note": "  "}]
    expect_valueerror(f, "空 note 应拒")
    # ⑤ PE 带与上版一致：填了证据 → 拒（画蛇添足）；不填 → 过
    same_prev = [{"scenario": "悲观情景", "归母净利": "75 亿", "PE": "8-10x",
                  "目标价": "6-7.5 元"},
                 {"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                  "目标价": "9.5-11.4 元"},
                 {"scenario": "乐观情景", "归母净利": "110 亿", "PE": "12-14x",
                  "目标价": "13.2-15.4 元"}]
    f = full_fill(prev={"date": "2026-08-08", "quality": 6.4, "valuation": 5.0,
                        "timing": 4.8, "target_range": "9-11", "scenarios": same_prev})
    expect_valueerror(f, "PE 带与上版一致但填了证据应拒")
    f = full_fill(prev={"date": "2026-08-08", "quality": 6.4, "valuation": 5.0,
                        "timing": 4.8, "target_range": "9-11", "scenarios": same_prev})
    del f["valuation"]["pe_band_evidence"]
    R.validate_content(f, R.compute_valuation(f))   # 不抛即过
    # ⑥ 重构偏离 >15%：无 rollback_html → 拒；有 → 过
    f = full_fill()
    f["pe_history"]["p25"], f["pe_history"]["p75"] = 20.0, 30.0  # 中枢25 vs pe_band中枢11 → -56%
    expect_valueerror(f, "重构偏离 >15% 无 rollback_html 应拒")
    f = full_fill()
    f["pe_history"]["p25"], f["pe_history"]["p75"] = 20.0, 30.0
    f["valuation"]["rollback_html"] = "回滚条件：煤价中枢回升至 900 元/吨上方 → PE 带回滚至历史带"
    R.validate_content(f, R.compute_valuation(f))   # 不抛即过
    # ⑦ 首版（无 prev）与市值口径不受门禁约束
    R.validate_content(minimal_fill(), R.compute_valuation(minimal_fill()))
