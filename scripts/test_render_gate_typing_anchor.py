#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_typing_anchor.py — render_report 分型与锚回归：typing v2 判据/双尺锚纪律/校准锚(calib)/口径收口(cagr_adjustments)/peer 选取硬化域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import (
    minimal_fill, mcap_fill, expect_valueerror, validate_stderr,
    v2_fill, render_v2_fill,
)


def test_typing_v2_stock_type_enum():
    """v5.3.0 判据 v2：stock_type 枚举标准化——标准值放行、旧名映射告警、无法映射拒渲染。"""
    assert "无法映射六型" not in validate_stderr(minimal_fill()), "默认值周期股应放行"
    s = validate_stderr(minimal_fill(stock_type="稳健成长股"))
    assert "旧名" in s and "成长型" in s, "稳健成长股应映射成长型并告警旧名"
    s2 = validate_stderr(minimal_fill(stock_type="快速成长（强周期属性）"))
    assert "旧名" in s2 and "high" in s2, "快速成长应映射成长型·high 层"
    expect_valueerror(minimal_fill(stock_type="烟蒂股"), "无法映射六型")


def test_typing_v2_layer_share_mismatch():
    """型↔层占比对账（首版软约束）：稳定价值填 70:30 → 告警；85:15 → 不告警。"""
    f = minimal_fill(stock_type="稳定价值/金融（银行）", layer_share={"L1": 70, "L3": 30})
    assert "映射 85:15 不符" in validate_stderr(f), "稳定价值 70:30 应告警占比不符"
    f2 = minimal_fill(stock_type="稳定价值/金融（银行）", layer_share={"L1": 85, "L3": 15})
    assert "映射 85:15 不符" not in validate_stderr(f2), "85:15 不应告警"
    f3 = minimal_fill(stock_type="成熟/停滞", layer_share={"L1": 70, "L3": 30})
    assert "映射 80:20 不符" in validate_stderr(f3), "成熟/停滞 70:30 应告警占比不符"


def test_typing_v2_growth_tier_cagr():
    """成长层 CAGR 对账（v5.4.0 改扣非口径）：按 fin_trend 扣非柱复算，跨层（缓冲带 ±5pct 外）
    → 告警；归母柱不再作对账基准。"""
    # 默认扣非柱 [75,79,83,86,88]，CAGR≈4.1%：high 声明 → 告警；mid 声明 → 不告警（4.1% 近中速层下沿）
    f_high = minimal_fill(stock_type="成长型", growth_tier="high")
    assert "分层与财务事实不符" in validate_stderr(f_high), "扣非 CAGR 4.1% 声明 high 应告警"
    f_mid = minimal_fill(stock_type="成长型", growth_tier="mid")
    assert "应归高速层" not in validate_stderr(f_mid), "扣非 CAGR 4.1% 声明 mid 不应告警归高速层"
    # 扣非柱改 [10,15,22,33,50]（CAGR≈49.5%）：mid 声明 → 告警应归高速层
    f_fast = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_fast["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f_fast), "扣非 CAGR 49.5% 声明 mid 应告警归高速层"
    # 归母柱改飞不再影响对账（扣非柱未动 → 不告警）
    f_rm = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_rm["fin_trend"]["panels"][1]["bars"][0]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" not in validate_stderr(f_rm), "归母柱不再作对账基准"
    # 扣非 CAGR 20.4%（中速层缓冲带内：5-25% +5pct）→ 不告警
    f_in = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_in["fin_trend"]["panels"][1]["bars"][1]["values"] = [100, 120, 145, 175, 210]
    assert "应归高速层" not in validate_stderr(f_in), "扣非 CAGR 20.4% 在中速层缓冲带内应放行"
    # 扣非 CAGR 30.5%（>30% 上沿）→ 告警应归高速层
    f_over = minimal_fill(stock_type="成长型", growth_tier="mid")
    f_over["fin_trend"]["panels"][1]["bars"][1]["values"] = [100, 130, 170, 220, 290]
    assert "应归高速层" in validate_stderr(f_over), "扣非 CAGR 30.5% 越中速层上沿应告警"


def test_typing_v2_evidence_keys():
    """typing_evidence 按型必填键（首版软约束）：缺失 → 告警；填齐 → 不告警。"""
    assert "typing_evidence 缺键" in validate_stderr(minimal_fill()), "未填 typing_evidence 应告警"
    te = {"commodity_link": "利润随电解铝价格波动（归因：商品价格）",
          "volatility_fact": "峰谷回撤 63%", "comparable_periods": "2015-2016 底部、2021-2022 顶部"}
    assert "typing_evidence 缺键" not in validate_stderr(minimal_fill(typing_evidence=te)), "周期股三键齐全不应告警"


def test_typing_v2_clash_whitelist():
    """撞车白名单：周期股×成长型可声明共存（cross_check ≥30 字）；其他对拒渲染。"""
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_clash={"with": "周期股", "primary_reason": "量增主导",
                                   "cross_check": "对照方法目标价 20-24 元，与主型结论方向一致，差异在倍数选择。"})
    assert "非白名单共存对" not in validate_stderr(f), "白名单对应放行"
    expect_valueerror(minimal_fill(stock_type="成长型", growth_tier="mid",
                                   typing_clash={"with": "困境反转", "cross_check": "x" * 40}),
                      "非白名单共存对")
    f3 = minimal_fill(stock_type="周期股", typing_clash={"with": "成长型", "cross_check": "太短"})
    assert "cross_check <30 字" in validate_stderr(f3), "cross_check 不足 30 字应告警"


def test_typing_v2_weights_half_filled():
    """weights 半填拒渲染（冰轮实证）：L1/L3 只填一层 → 拒；两层同填 → 放行。"""
    expect_valueerror(minimal_fill(weights={"1A": 12, "1B": 12, "1C": 20, "1D": 16, "1E": 20, "1F": 20}),
                      "weights 半填")
    f = minimal_fill(weights={"1A": 12, "1B": 12, "1C": 20, "1D": 16, "1E": 20, "1F": 20,
                              "3A": 40, "3B": 35, "3C": 25})
    assert "weights 半填" not in validate_stderr(f), "两层同填不应告警"


def test_hist_cagr_guard():
    """P0-2（v5.4.0 审计）：_hist_cagr 的扣非柱值必须与 years 等长且全可解析，否则 None——
    zip 静默截断会把 CAGR 窗口算错，而本数驱动拒渲染门禁（明细缺失即拒）。"""
    from validate_typing import _hist_cagr
    assert _hist_cagr(minimal_fill()) is not None    # 夹具扣非柱 [75,79,83,86,88] / 5 年
    short = minimal_fill()
    short["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79]           # 短柱
    assert _hist_cagr(short) is None, "柱短于 years 应 None（不得截断算窗口）"
    long_ = minimal_fill()
    long_["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79, 83, 86, 88, 90]   # 长柱
    assert _hist_cagr(long_) is None, "柱长于 years 应 None"
    bad = minimal_fill()
    bad["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, 79, 83, "—", 88]       # 含非数字
    assert _hist_cagr(bad) is None, "含非数字应 None"
    neg = minimal_fill()
    neg["fin_trend"]["panels"][1]["bars"][1]["values"] = [75, -5, 83, 86, 88]         # 含非正值
    assert _hist_cagr(neg) is None, "含非正值（跨亏年）应 None"
    few = minimal_fill()
    few["fin_trend"]["years"] = ["2024", "2025"]
    few["fin_trend"]["panels"] = [{"title": "x", "bars": [{"name": "扣非净利", "values": [80, 88]}],
                                   "lines": [{"name": "净利率", "values": [1, 2]}]} for _ in range(3)]
    assert _hist_cagr(few) is None, "<3 年应 None"


def test_typing_v2_cagr_negative_skips():
    """v5.4.0 拆分（P1-7：原用例走的是明细分支，属假绿）：
    a helper 级不可用 → None（见 test_hist_cagr_guard）；
    b 含非正值 + 有明细 → 人工判定（不复算、不出跨层告警）；
    c 含非正值 + 无明细 → 拒渲染（例外 b 触发）。"""
    # b 有明细 → 人工判定
    f = minimal_fill(stock_type="成长型", growth_tier="high",
                     typing_evidence={"cagr_hist": "近5年 CAGR 中枢 18%",
                                      "cagr_adjustments": [{"year": 2022, "item": "资产减值",
                                                            "amount": -5, "reason": "一次性减值剔除"}]})
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [80, -5, 90, 95, 100]
    out = validate_stderr(f)
    assert "分层与财务事实不符" not in out, "含负值序列应跳过对账、不得告警"
    assert "人工判定" in out, "有明细应标人工判定"
    # c 无明细 → 拒渲染
    f2 = minimal_fill(stock_type="成长型", growth_tier="high")
    f2["fin_trend"]["panels"][1]["bars"][1]["values"] = [80, -5, 90, 95, 100]
    expect_valueerror(f2, "扣非跨亏年无明细应拒", kw="扣非柱不可用")


def test_typing_v2_mature_not_stagnation():
    """v5.3.0 热核修正：裸「成熟」别名已删——「成熟成长股」应映射成长型而非成熟/停滞。"""
    s = validate_stderr(minimal_fill(stock_type="成熟成长股"))
    assert "无法映射六型" not in s, "成熟成长股应可映射（成长型）"
    assert "growth_tier 缺失" in s, "应按成长型分支处理（缺 growth_tier 告警）"


# ---------------- v5.4.0 A1 双尺锚纪律 / 校准锚（calib） ----------------
def test_anchor_dual_ruler_gate():
    """v5.4.0 双尺门禁：合理带（valuation_inputs.pe_band）与基础情景带（base 情景 pe）任一
    中枢偏离 pe_history P25-P75 中枢 >15% → rollback_html 必填（**首版无 prev 同样生效**）；
    一尺越界一尺不越、或两尺越界但异号 → 拒渲染（引「纪律四：禁止评分用旧尺、目标价用新尺」）；
    两尺同向同越界 = 一致重构，补回滚条款即放行。"""
    rb = "回滚条件：连续两季扣非同比转正 → PE 带回滚至历史带"
    # 首版双尺同向同越界（中枢 11 vs 25 → −56%）+ 无回滚条款 → 拒
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    expect_valueerror(f, "首版重构偏离无 rollback_html 应拒", kw="rollback_html 缺失")
    f["valuation"]["rollback_html"] = rb
    R.validate_content(f, R.compute_valuation(f))   # 补回滚条款 → 过
    # 双尺混用①：一尺越界一尺不越 → 拒（历史中枢 12；合理带中枢 24 → +100%；基础情景中枢 11 → −8%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f["valuation_inputs"]["pe_band"] = [22, 26]
    expect_valueerror(f, "一尺越界一尺不越应拒", kw="纪律四")
    # 双尺混用②：两尺都越界但偏离异号 → 拒（历史中枢 15；合理带 +60%、基础情景 −27%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 14.0, "p75": 16.0}
    f["valuation_inputs"]["pe_band"] = [22, 26]
    expect_valueerror(f, "双尺异号应拒", kw="方向相反")
    # 两尺皆可算但都不越界 → 放行（合理带与基础情景中枢同为 11，历史中枢 12 → −8.3%）
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    R.validate_content(f, R.compute_valuation(f))
    # 一尺可算一尺不可算：可算的越界 → 拒（未越界的那把尺不参与判定，文案注明「不可算」）
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    f["valuation_inputs"]["pe_band"] = []      # 合理带尺输入缺失
    expect_valueerror(f, "单尺越界应拒", kw="不可算")
    # 一尺可算（未越界）一尺不可算：不判混用、不要求回滚
    f = minimal_fill()
    f["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f["valuation_inputs"]["pe_band"] = []
    R.validate_content(f, R.compute_valuation(f))
    # 15% 边界：dev = 4.6/4−1 = 14.999…%（浮点恰不越界）→ 放行；略高一线（4.7/4−1 = 17.5%）→ 拒
    f = minimal_fill()
    f["price"], f["mcap"] = "30", "3000"
    f["pe_history"] = {"p25": 4.0, "p75": 4.0}
    f["valuation_inputs"]["pe_band"] = [4.5, 4.7]
    for sc, pe in zip(f["valuation"]["scenarios"], ([2.5, 2.7], [4.5, 4.7], [7.3, 7.5])):
        sc["pe"] = pe
    f["thesis_html"] = ('测试论点与关键证据。三情景目标价 '
                        '<span class="scenario-pess">2.08</span>/'
                        '<span class="scenario-base">4.6</span>/'
                        '<span class="scenario-opt">8.88</span> 元，结论：观察。')
    R.validate_content(f, R.compute_valuation(f))
    f2 = minimal_fill()
    f2["price"], f2["mcap"] = "30", "3000"
    f2["pe_history"] = {"p25": 4.0, "p75": 4.0}
    f2["valuation_inputs"]["pe_band"] = [4.6, 4.8]
    for sc, pe in zip(f2["valuation"]["scenarios"], ([2.5, 2.7], [4.6, 4.8], [7.3, 7.5])):
        sc["pe"] = pe
    expect_valueerror(f2, "越界须配回滚条款", kw="rollback_html 缺失")
    # 市值口径（metric_label + mcap 情景）双尺皆不可算 → 豁免
    R.validate_content(mcap_fill(), R.compute_valuation(mcap_fill()))
    # 尺子声明文案点名偏离的尺：两尺 → 「两者」；单尺 → 只点该尺
    from scoring import build_regime_note
    f = minimal_fill()
    f["pe_history"] = {"p25": 20.0, "p75": 30.0}
    note = build_regime_note(f)
    assert "合理带与基础情景带两者" in note and "下移 56%" in note, f"实际：{note}"
    f_band = minimal_fill()
    f_band["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f_band["valuation_inputs"]["pe_band"] = [22, 26]
    n_band = build_regime_note(f_band)
    assert "合理带中枢" in n_band and "基础情景带" not in n_band, f"实际：{n_band}"
    f_base = minimal_fill()
    f_base["pe_history"] = {"p25": 11.0, "p75": 13.0}
    f_base["valuation_inputs"]["pe_band"] = [11, 13]
    f_base["valuation"]["scenarios"][1]["pe"] = [9.5, 10.5]
    n_base = build_regime_note(f_base)
    assert "基础情景带中枢" in n_base and "合理带" not in n_base, f"实际：{n_base}"
    assert build_regime_note(minimal_fill()) == "", "两尺皆无输入 → 空串"


def test_anchor_blind_fly_warn():
    """v5.4.0 校验盲飞：依赖历史 PE 时段锚的四型（周期/稳定价值/困境反转/成长·中速层）
    既无 metric_label 又缺 p25/p75 → 告警要求写明降级取数路径；有分位 / 行业口径 / 非四型 → 不告警。"""
    assert "校验盲飞" in validate_stderr(minimal_fill()), "周期股缺 p25/p75 应告警"
    assert "校验盲飞" not in validate_stderr(minimal_fill(pe_history={"p25": 10, "p75": 12}))
    assert "校验盲飞" not in validate_stderr(mcap_fill()), "市值口径 metric_label → 豁免"
    for st, gt in (("成熟/停滞", None), ("成长型", "high"), ("未盈利/管线", None)):
        f = minimal_fill(stock_type=st) if gt is None else minimal_fill(stock_type=st, growth_tier=gt)
        assert "校验盲飞" not in validate_stderr(f), f"{st}/{gt} 不属四型，不应告警"
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="成长型", growth_tier="mid")), \
        "成长型·中速层属四型，缺分位应告警"
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="稳定价值/金融（银行）"))
    assert "校验盲飞" in validate_stderr(minimal_fill(stock_type="困境反转"))


# ---------------- v5.4.0 A1 校准锚（calib）三校验 ----------------
_CALIB_MONTHS = [{"m": f"2021-{m:02d}", "close": 10.0, "pe": float(10 + m)} for m in range(1, 13)]


def _calib_fill(stages, **over):
    """calib 用例夹具：price_history 窗口 2021-01..2021-12（pe 11..22）+ cycle_html 在位。"""
    return minimal_fill(cycle_html="<p>周期分析。</p>",
                        price_history={"label": "近1年", "series": _CALIB_MONTHS},
                        cycle_stages=stages, **over)


_CALIB_STAGE = {"name": "校准段", "period": "2021/01–2021/12", "pe": "11–22x", "calib": True,
                "similarity": "增速 20%、渗透率低（可比）", "discount": "规模相当，无折价"}


def test_calib_keys_and_count_warn():
    """v5.4.0 校准锚①②：calib:true 缺 similarity/discount → 告警；四型 calib <2 → 告警；
    四型 calib ≥2 且键齐、窗口内对账通过 → 三条 calib 校验全不告警。"""
    stages = [dict(_CALIB_STAGE),  # 仅 1 个 calib
              {"name": "当前段", "period": "2022/01–至今", "current": True},
              {"name": "过渡段", "period": "2022/01–2022/06"}]
    out = validate_stderr(_calib_fill(stages))
    assert "校准锚（calib:true）仅 1 个" in out, "四型 calib <2 应告警"
    assert "缺 similarity" not in out, "键齐不应告警"
    bad = [dict(_CALIB_STAGE, similarity="", discount=None), stages[1], stages[2]]
    out2 = validate_stderr(_calib_fill(bad))
    assert "缺 similarity/discount" in out2, "缺两键应告警"
    # 非四型（成熟/停滞）calib 仅 1 个 → 不告警数量
    out3 = validate_stderr(_calib_fill(stages, stock_type="成熟/停滞"))
    assert "校准锚（calib:true）仅 1 个" not in out3, "非四型不受 ≥2 约束"
    # 正例：四型 calib=2、键齐、窗口内对账通过 → 三条校验全不告警
    good = [_CALIB_STAGE,
            dict(_CALIB_STAGE, name="校准段二", period="2021/06–2021/12", pe="16–22x"),
            {"name": "当前段", "period": "2022/01–至今", "current": True}]
    out4 = validate_stderr(_calib_fill(good))
    assert ("校准锚（calib:true）仅" not in out4 and "缺 similarity" not in out4
            and "端点偏差" not in out4 and "声明未核验" not in out4), f"正例不应告警：{out4}"
    for st in ("稳定价值/金融（银行）", "困境反转", "成长型"):
        over = {"growth_tier": "mid"} if st == "成长型" else {}
        out5 = validate_stderr(_calib_fill(good, stock_type=st, **over))
        assert "校准锚（calib:true）仅" not in out5, f"{st} calib=2 不应告警数量"
    # v5.4.1：四型零标记不再静默豁免（0 个 → 独立文案）；非四型 0 个 → 不告警
    zero = [{"name": "段一", "period": "2021/01–2021/12"}, stages[1], stages[2]]
    out6 = validate_stderr(_calib_fill(zero))
    assert "未标注校准锚（calib）" in out6, "四型 0 个 calib 应告警"
    assert "校准锚（calib:true）仅" not in out6, "0 个走专用文案"
    out7 = validate_stderr(_calib_fill(zero, stock_type="成熟/停滞"))
    assert "未标注校准锚" not in out7 and "校准锚（calib:true）仅" not in out7, "非四型 0 个不应告警"


def test_calib_history_distortion_fallback_is_allowed():
    stages = [{"name": "段一", "period": "2021/01–2021/12"},
              {"name": "当前段", "period": "2022/01–至今", "current": True},
              {"name": "过渡段", "period": "2022/01–2022/06"}]
    f = _calib_fill(stages, stock_type="困境反转")
    f["cycle_html"] = ("<p>历史 PE 带严重失真且重组前后不可比，未标校准锚（calib）；"
                        "改用同业锚与正常化利润，此为降级取数路径的显式声明。</p>")
    assert "未标注校准锚（calib）" not in validate_stderr(f)


def test_calib_window_recon_warn():
    """v5.4.0 校准锚③：calib 时段落在 price_history 窗口内 → 声明区间与窗口实测 PE 极值
    端点偏差 >25% 告警（上限方向同）；恰 25% 边界放行；未写 pe 键/窗口外 → 跳过；
    全部未核验 → 「声明未核验」汇总告警一条。"""
    cur = {"name": "当前段", "period": "2022/01–至今", "current": True}
    other = {"name": "过渡段", "period": "2022/01–2022/06"}
    ok = [dict(_CALIB_STAGE, pe="10–24x"), cur, other]          # 实测 11–22 → 容差内
    out = validate_stderr(_calib_fill(ok))
    assert "端点偏差 >25%" not in out and "声明未核验" not in out, f"容差内不应告警：{out}"
    off = [dict(_CALIB_STAGE, pe="30–40x"), cur, other]         # 实测 11 → 下限偏差 63%
    out2 = validate_stderr(_calib_fill(off))
    assert "端点偏差 >25%" in out2 and "下限 30x vs 实测最低 11x" in out2
    up = [dict(_CALIB_STAGE, pe="10–12x"), cur, other]          # 实测最高 22 → 上限偏差 83%
    out3 = validate_stderr(_calib_fill(up))
    assert "上限 12x vs 实测最高 22x" in out3, "上限方向同样要对账"
    # 恰 25%：|11−8.8|/8.8 = 0.25、|22−17.6|/17.6 = 0.25（浮点恰不越界）→ 放行
    edge = [dict(_CALIB_STAGE, pe="8.8–17.6x"), cur, other]
    out4 = validate_stderr(_calib_fill(edge))
    assert "端点偏差" not in out4 and "声明未核验" not in out4, f"恰 25% 应放行：{out4}"
    # 未写 pe 键 → 跳过对账（不计已核验 → 汇总告警）
    nope_pe = [dict(_CALIB_STAGE, pe=""), cur, other]
    out5 = validate_stderr(_calib_fill(nope_pe))
    assert "端点偏差" not in out5 and "声明未核验" in out5
    # 窗口外（2020 年不在序列内）→ 全部未核验
    outwin = [dict(_CALIB_STAGE, period="2020/01–2020/12"), cur, other]
    out6 = validate_stderr(_calib_fill(outwin))
    assert "均在取数窗口外" in out6 and "声明未核验" in out6
    # 无 pe 序列（price_history 缺 pe）→ 同样未核验
    nope = minimal_fill(cycle_html="<p>x</p>",
                        price_history={"label": "近1年",
                                       "series": [{"m": m["m"], "close": m["close"]}
                                                  for m in _CALIB_MONTHS]},
                        cycle_stages=[_CALIB_STAGE, cur, other])
    assert "均在取数窗口外" in validate_stderr(nope), "窗口内无 pe → 未核验"
    # 年份守卫（热核审计 P2）：pe 含四位年份不得吞为区间端点（「2021 年 10–24x」按 10–24 解析）
    yr = [dict(_CALIB_STAGE, pe="2021 年 10–24x"), cur, other]
    out7 = validate_stderr(_calib_fill(yr))
    assert "端点偏差" not in out7, f"年份不得吞为区间端点：{out7}"


# ---------------- v5.4.0 A2 口径收口（cagr_adjustments / 扣非对账） ----------------
def test_cagr_adjustments_gate():
    """v5.4.0 A2：三条例外（a 港股 5 位代码 / b 扣非柱不可用 / c cagr_hist 含调整词）任一
    命中且 cagr_adjustments 非空四键明细缺失 → 拒渲染；三条例外均不成立却填写 → 软告警。"""
    ok = [{"year": 2024, "item": "处置子公司股权收益", "amount": -6.2, "reason": "一次性损益剔除"}]
    te = {"cagr_hist": "近5年 CAGR 中枢 18%", "driver_nature": "量增", "shock_history": "无"}
    # a 港股 5 位代码
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082", typing_evidence=dict(te))
    expect_valueerror(f, "港股缺 cagr_adjustments 应拒", kw="港股 5 位代码")
    f["typing_evidence"]["cagr_adjustments"] = ok
    R.validate_content(f, R.compute_valuation(f))   # 补齐明细 → 过
    # b 扣非柱不可用（删扣非柱）
    f = minimal_fill(stock_type="成长型", growth_tier="mid", typing_evidence=dict(te))
    del f["fin_trend"]["panels"][1]["bars"][1]
    expect_valueerror(f, "扣非柱不可用应拒", kw="扣非柱不可用")
    # c cagr_hist 含口径调整词
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_hist="近5年 CAGR 中枢 18%（剔除一次性损益后）"))
    expect_valueerror(f, "cagr_hist 调整词触发应拒", kw="口径调整词")
    # 结构不全（缺 reason）→ 同拒
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082",
                     typing_evidence=dict(te, cagr_adjustments=[
                         {"year": 2024, "item": "处置收益", "amount": -6.2}]))
    expect_valueerror(f, "四键不全应拒", kw="结构不全")
    # 成熟/停滞 同样要求 cagr_hist 键 → 同规则生效
    f = minimal_fill(stock_type="成熟/停滞", code="06082",
                     typing_evidence={"growth_narrative": "叙事消亡", "three_exclusions": "三条均成立",
                                      "cagr_hist": "近5年 CAGR 2%"})
    expect_valueerror(f, "成熟/停滞港股缺明细应拒", kw="港股 5 位代码")
    # c 关键词收窄（P1-5）：含「目标价调整」不触发门禁，无明细也放行
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_hist="近5年 CAGR 中枢 18%（目标价调整后）"))
    R.validate_content(f, R.compute_valuation(f))
    # [{}] 残件 + 无例外命中 → 既不判「多填」（ok_adj=False）、也不拒；且不对账静默关掉
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_adjustments=[{}]))
    out = validate_stderr(f)
    assert "均不成立" not in out, "残件不得走「多填」软告警"
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f), "残件不得静默关掉复算对账"
    # [{}] 残件 + 例外命中（港股）→ 拒（结构不全），而非「多填」告警
    f = minimal_fill(stock_type="成长型", growth_tier="mid", code="06082",
                     typing_evidence=dict(te, cagr_adjustments=[{}]))
    expect_valueerror(f, "残件应拒", kw="结构不全")
    # 三条例外均不成立却填明细 → 软告警（防口径漂移）
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence=dict(te, cagr_adjustments=ok))
    assert "均不成立" in validate_stderr(f), "无例外却填明细应软告警"


def test_growth_tier_cagr_adjustments_manual():
    """v5.4.0 A2 ①：cagr_adjustments 非空 → 按声明调整口径（人工判定），脚本不复算
    ——扣非 CAGR 再离谱也不出跨层告警。"""
    f = minimal_fill(stock_type="成长型", growth_tier="mid",
                     typing_evidence={"cagr_hist": "近5年 CAGR 中枢 18%（含并购口径调整）",
                                      "cagr_adjustments": [{"year": 2022, "item": "并购摊销",
                                                            "amount": -3, "reason": "口径调整"}]})
    f["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]   # 扣非 CAGR 49.5%
    out = validate_stderr(f)
    assert "应归高速层" not in out, "有调整明细应跳过脚本复算"
    assert "人工判定" in out, "应标注人工判定"
    # 无明细时同一序列 → 跨层告警（对账基准=扣非柱）
    f2 = minimal_fill(stock_type="成长型", growth_tier="mid")
    f2["fin_trend"]["panels"][1]["bars"][1]["values"] = [10, 15, 22, 33, 50]
    assert "应归高速层" in validate_stderr(f2), "无明细须复算并告警"


# ---------------- v5.4.0 A3 peer 选取硬化 ----------------
_PEER_PLOT_CLEAN = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
                    {"name": "同业甲", "roe": 12, "pe": 18}]


_PEERS_META_OK = "同行业（煤化工）、同规模（市值 800-1,500 亿）筛选；同业丙口径不一剔出"


# 仅 matrix-table 的 peers_html（九宫格兜底形态：行=ROE 档、公司名在单元格里）
_MATRIX_ONLY_HTML = ('<div class="table-scroll"><table class="matrix-table">'
                     '<tr><th>PE 低</th><th>PE 中</th><th>PE 高</th></tr>'
                     '<tr><th>ROE 高</th><td>测试股份(14%/11x)</td><td>—</td><td>—</td></tr>'
                     '<tr><th>ROE 中</th><td>—</td><td>同业甲(12%/18x)</td><td>同业丙(15%/20x)</td></tr>'
                     '<tr><th>ROE 低</th><td>—</td><td>—</td><td>—</td></tr></table></div>'
                     '<span class="source">数据来源：测试</span>')


def test_peers_table_plot_consistency():
    """v5.4.0 ⑨表图一致（拒渲染）：散点图非 target 点必须在 peers_html **非 matrix-table 表**的
    行首格内（名字归一后精确相等），或在 peers_meta 点名声明；未声明 → 拒渲染；target 点豁免。
    审计 P0-1：matrix-table 九宫格行首格是 ROE 档位名、公司名在单元格里——不作名字来源；
    peers_html 只剩 matrix-table 时整条跳过（渲染器反正会删手写九宫格）。"""
    pts = _PEER_PLOT_CLEAN + [{"name": "同业丙", "roe": 15, "pe": 20}]
    expect_valueerror(minimal_fill(peers_plot={"points": pts}),
                      "表外同业未声明应拒", kw="表图一致")
    f = minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": pts})
    R.validate_content(f, R.compute_valuation(f))   # peers_meta 声明后者 → 过
    # 表内同业（同业甲）无需声明；target 点豁免
    f2 = minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": _PEER_PLOT_CLEAN})
    R.validate_content(f2, R.compute_valuation(f2))
    # P0-1：plot + matrix-table 同存（无普通指标表）→ 整条跳过，不误拒
    f3 = minimal_fill(peers_html=_MATRIX_ONLY_HTML, peers_plot={"points": pts})
    R.validate_content(f3, R.compute_valuation(f3))
    # 同存且另有普通表 → 普通表才是名字来源：只出现在九宫格里的同业丙仍拒
    f4 = minimal_fill(peers_html=_MATRIX_ONLY_HTML + minimal_fill()["peers_html"],
                      peers_plot={"points": pts})
    expect_valueerror(f4, "九宫格不作名字来源", kw="表图一致")
    # P1-12：名字归一后精确相等（括号注可去，「比亚迪」≠「比亚迪电子」——近似名仍拒）
    f5 = minimal_fill(peers_meta=_PEERS_META_OK,
                      peers_plot={"points": _PEER_PLOT_CLEAN
                                  + [{"name": "同业甲（A股）", "roe": 12, "pe": 18}]})
    R.validate_content(f5, R.compute_valuation(f5))   # 括号注归一后 = 表内「同业甲」→ 过
    tbl = minimal_fill()["peers_html"].replace("同业甲", "比亚迪电子")
    f6 = minimal_fill(peers_html=tbl, peers_meta=_PEERS_META_OK,
                      peers_plot={"points": _PEER_PLOT_CLEAN + [{"name": "比亚迪", "roe": 15, "pe": 20}]})
    expect_valueerror(f6, "近似名不得互相放行", kw="表图一致")
    # 交易所标记归一：表内「百济神州-U」≡ 图内「百济神州」（恒瑞 2026-09-19 存量实证）
    tbl7 = minimal_fill()["peers_html"].replace("同业甲", "百济神州-U")
    f7 = minimal_fill(peers_html=tbl7, peers_meta=_PEERS_META_OK,
                      peers_plot={"points": [_PEER_PLOT_CLEAN[0],
                                             {"name": "百济神州", "roe": 5, "pe": 38}]})
    R.validate_content(f7, R.compute_valuation(f7))


def test_peers_ruler_consistency_warn():
    """v5.4.0 ⑩尺子一致：target 点 ROE 与 fin_trend ROE 线末值绝对差 >3pct 且
    peers_meta 无「口径词+点名目标」双命中 → 告警；双命中注明 → 放行；
    裸口径词不点名目标 → 仍告警（热核审计 P2：堵万能逃生口）。"""
    meta_plain = "同行业（煤化工）、同规模（市值 800-1,500 亿）筛选；纯焦化标的排除"
    pts = [{"name": "测试股份", "roe": 20, "pe": 11, "target": True},
           {"name": "同业甲", "roe": 12, "pe": 18}]
    out = validate_stderr(minimal_fill(peers_meta=meta_plain, peers_plot={"points": pts}))
    assert "> 3pct" in out and "fin_trend ROE 线末值" in out, "ROE 两处口径差应告警"
    out2 = validate_stderr(minimal_fill(peers_meta=meta_plain + "；目标公司 ROE 取加权口径",
                                        peers_plot={"points": pts}))
    assert "> 3pct" not in out2, "口径词+点名目标应放行"
    out3 = validate_stderr(minimal_fill(peers_meta=meta_plain + "；ROE 取加权口径",
                                        peers_plot={"points": pts}))
    assert "> 3pct" in out3, "裸口径词不点名目标不放行"
    # 数据缺（fin_trend 无 ROE 线）→ 跳过
    f = minimal_fill(peers_meta=meta_plain, peers_plot={"points": pts})
    f["fin_trend"]["panels"][1]["lines"] = f["fin_trend"]["panels"][1]["lines"][:1]
    assert "> 3pct" not in validate_stderr(f), "无 ROE 参照应跳过"


def test_peers_min_three_warn():
    """v5.4.0 ⑪peer ≥3：非 target 有效点 <3 → 告警；peers_meta 已写明凑不齐原因
    （含「仅/凑不齐/可比公司不足」）→ 抑制（与「meta 注明后可忽略」惯例一致）。"""
    assert "有效同业点仅 1 家" in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": _PEER_PLOT_CLEAN}))
    # 写明凑不齐 → 抑制
    assert "有效同业点仅" not in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK + "；可比公司仅 2 家（凑不齐 3 家）",
                     peers_plot={"points": _PEER_PLOT_CLEAN}))
    # 未写原因（哪怕 meta 完整）→ 仍告警
    assert "有效同业点仅" in validate_stderr(
        minimal_fill(peers_meta="同行业、同规模筛选；纯焦化标的排除",
                     peers_plot={"points": _PEER_PLOT_CLEAN}))
    pts = _PEER_PLOT_CLEAN + [{"name": "同业丙", "roe": 15, "pe": 20},
                              {"name": "同业丁", "roe": 16, "pe": 21}]
    meta = _PEERS_META_OK + "；同业丁未选（业务结构差异大）"
    assert "有效同业点仅" not in validate_stderr(
        minimal_fill(peers_meta=meta, peers_plot={"points": pts}))


def test_peers_rationale_warn():
    """v5.4.0 ⑫rationale：有 peer 章节实体（peers_plot 或非占位 peers_meta）时即检查——
    须含「同行业/同规模/同商业模式」≥2 种 + 排除语（排除/未选/剔出），缺一告警；
    占位「—」/空 meta 且无 peers_plot → 交给占位告警，不重复报 rationale。"""
    assert "选取理由不完整" in validate_stderr(minimal_fill(peers_meta="同行业筛选"))
    assert "选取理由不完整" in validate_stderr(minimal_fill(peers_meta="同行业、同规模筛选"))
    assert "选取理由不完整" not in validate_stderr(
        minimal_fill(peers_meta="同行业、同规模筛选；纯焦化标的排除"))
    # 默认态（meta="—"、无 peers_plot）：只有占位告警，不出现 rationale 告警
    default_out = validate_stderr(minimal_fill())
    assert "peers_meta 缺失或为占位符" in default_out and "选取理由不完整" not in default_out
    # 有 peers_plot 但 meta 占位 → rationale 不再静默失效（此前 `if meta:` 直接跳过）
    assert "选取理由不完整" in validate_stderr(
        minimal_fill(peers_plot={"points": _PEER_PLOT_CLEAN}))


def test_peers_pe_cross_warn():
    """v5.4.0 ⑬PE 交叉（软告警）：valuation 基础情景 PE 下限 > 全部非 target 点 PE → 溢价论证提醒。"""
    low = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
           {"name": "同业甲", "roe": 12, "pe": 8}]
    assert "高于全部同业" in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": low}))
    high = [{"name": "测试股份", "roe": 14, "pe": 11, "target": True},
            {"name": "同业甲", "roe": 12, "pe": 30}]
    assert "高于全部同业" not in validate_stderr(
        minimal_fill(peers_meta=_PEERS_META_OK, peers_plot={"points": high}))
