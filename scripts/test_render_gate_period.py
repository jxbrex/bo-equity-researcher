#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_period.py — render_report 第 3 章与业务线敏感性回归：B5 readthrough(3B 数字义务)/B6 折现率参考带/period_track 校验与渲染域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import (
    minimal_fill, _dim, expect_valueerror, validate_stderr, write_fill,
    render_fill, period_fill, _LONG_TEXT, _PERIOD_REF_KEYS,
)

# ---------------- v5.5.0 B5 3B 无项目型数字义务 / B6 折现率参考带 ----------------
_L3_BLOCK = ('<div class="dim-block"><div class="dim-header">'
             '<span class="dim-name">5.2 项目确定性</span><span class="dim-weight">35%</span>'
             '<span class="score-line" style="margin-left:auto;margin-bottom:0;">'
             '<span class="badge badge-green">7.0</span></span></div>'
             '<p>{t}</p>'
             '<p><strong>评分：</strong>7.0——基准 6.5，按利润贡献加权后 +0.5。</p></div>')


def _l3_fill(text, **over):
    """B5 夹具：l3_html 首块写 5.2 项目确定性文本（其余块用通用长文本凑地板）。"""
    l3 = _L3_BLOCK.format(t=text) + "".join(_dim(_LONG_TEXT) for _ in range(2))
    return minimal_fill(l3_html=l3, **over)


def test_readthrough_3b_narrative_warn():
    """v5.5.0 B5：无项目型 3B ≥6.5 且 5.2 块**正文**（剥标题/徽章/评分末拍）无数字 → 软告警；
    正文带数字放行；非无项目型（无关键词）不查；3B <6.5 不查。
    热核审计 P0：评分末拍是 schema 强制段且必含分值数字——不剥则门禁在合规报告上恒不触发。"""
    narrative = ("无项目型的存量扩张逻辑：公司为行业龙头，客户粘性强、转换成本高，"
                 "收入结构持续优化，渠道壁垒稳固，可见度长期偏高。")
    f = _l3_fill(narrative)
    f["scores"]["3B"] = 7.0
    assert "无项目型 ≥6.5" in validate_stderr(f), "schema 形态（带评分末拍）论据无数字应告警"
    # 正文带指标 + 数值 → 放行
    f2 = _l3_fill("无项目型的存量扩张：两融余额 1,240 亿、环比 +6%，保有客户 3,120 万，"
                  "续约率 92%，存量指标趋势向上且口径可复核。")
    f2["scores"]["3B"] = 7.0
    assert "无项目型 ≥6.5" not in validate_stderr(f2), "带指标+数值应放行"
    # 有项目型（无关键词）→ 不查
    f3 = _l3_fill("在建产能：计划 2026Q2 投产，资金到位、审批齐全，滑期风险小于一年，"
                  "投产即为利润贡献主体。")
    f3["scores"]["3B"] = 7.5
    assert "无项目型 ≥6.5" not in validate_stderr(f3), "有项目型（无关键词）不查"
    # 3B < 6.5 → 不查
    f4 = _l3_fill(narrative)
    f4["scores"]["3B"] = 6.0
    assert "无项目型 ≥6.5" not in validate_stderr(f4), "3B <6.5 不查"
    # 剥段口径自证：dim-header 带附加类 / 评分末拍带属性时仍能正确剥净
    f5 = _l3_fill(narrative)
    f5["scores"]["3B"] = 7.0
    f5["l3_html"] = f5["l3_html"].replace('<div class="dim-header">',
                                          '<div class="dim-header extra" data-x="1">')
    f5["l3_html"] = f5["l3_html"].replace('<p><strong>评分：</strong>',
                                          '<p class="score-beat"><strong>评分：</strong>')
    assert "无项目型 ≥6.5" in validate_stderr(f5), "容忍型剥离：附加类/属性下仍应告警"


def test_discount_rate_band_warn():
    """v5.5.0 B6：`dcf.wacc` 与国债距离超参考带 +2pct → 软告警（**WACC sanity 粗筛**，非 r 带执法）；
    各分型带内/恰等号线放行、超带告警；未盈利·管线/困境反转跳过；不可解析跳过。
    热核审计 P1：银行带 9%（非金融带 8.2 会告警、银行带 9.2 放行）——能判别银行行确实生效。"""
    KW = "与国债距离超参考带"
    dcf0 = {"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
            "net_cash": "120亿", "implied_g": "0.5", "verdict": "长" * 45}

    def w(st, pct, **over):
        return minimal_fill(stock_type=st, dcf=dict(dcf0, wacc=pct), **over)

    # 稳定价值（非金融）线上限 4.5+2+1.7 = 8.2%
    assert KW in validate_stderr(w("稳定价值（非金融）", "10%")), "超带应告警"
    assert KW not in validate_stderr(w("稳定价值（非金融）", "8.2%")), "恰等号线应放行"
    assert KW in validate_stderr(w("稳定价值（非金融）", "8.3%")), "越线一线应告警"
    # 银行带 5.5+2+1.7 = 9.2%
    assert KW not in validate_stderr(w("稳定价值/金融（银行）", "9%")), "银行 9% 应放行（非金融带会误告）"
    assert KW in validate_stderr(w("稳定价值/金融（银行）", "10%")), "银行 10% 超带应告警"
    # 保险/券商带 7.3+2+1.7 = 11.0%
    for st in ("稳定价值/金融（保险）", "稳定价值/金融（券商）", "稳定价值（证券）"):
        assert KW not in validate_stderr(w(st, "10%")), f"{st} 10% 沿高贝塔带放行"
        assert KW in validate_stderr(w(st, "12%")), f"{st} 12% 超带应告警"
    # 成长型 6+2+1.7 = 9.7%｜周期股 7+2+1.7 = 10.7%｜成熟·停滞 4.5+2+1.7 = 8.2%
    assert KW not in validate_stderr(w("成长型", "9.5%"))
    assert KW in validate_stderr(w("成长型", "10%"))
    assert KW not in validate_stderr(w("周期股", "10%")), "周期股 10% 边缘放行（云铝实证）"
    assert KW in validate_stderr(w("周期股", "11%"))
    assert KW not in validate_stderr(w("成熟/停滞", "8.2%"))
    assert KW in validate_stderr(w("成熟/停滞", "9%"))
    # 跳过面：未盈利·管线 / 困境反转（无股权成本锚）、wacc 不可解析、risk_free 不可解析
    for st in ("未盈利/管线", "困境反转"):
        assert KW not in validate_stderr(w(st, "30%")), f"{st} 跳过"
    assert KW not in validate_stderr(w("稳定价值（非金融）", "—")), "wacc 占位跳过"
    f = w("稳定价值（非金融）", "12%",
          valuation_inputs={"pe_ttm": 11, "pe_band": [10, 12], "div_yield": 2, "risk_free": "—"})
    assert KW not in validate_stderr(f), "risk_free 不可解析跳过"


def test_dcf_param_parse_warn():
    """v5.5.0 P1：dcf 参数型三键（wacc/growth_5y/g_perp）非空但不可解析 → 告警
    （对齐 value/implied_g 的 v5.1.2 先例）；「—」占位跳过；wacc <1 提示疑为小数口径。"""
    dcf0 = {"value": 12.5, "fcf0": "95亿", "growth_5y": "5%", "g_perp": "2.5%", "wacc": "8.5%",
            "net_cash": "120亿", "implied_g": "0.5", "verdict": "长" * 45}
    f = minimal_fill(dcf=dict(dcf0, wacc="八五"))
    assert "dcf.wacc「八五」非空但不可解析为数值" in validate_stderr(f)
    f2 = minimal_fill(dcf=dict(dcf0, growth_5y="未定"))
    assert "dcf.growth_5y「未定」非空但不可解析为数值" in validate_stderr(f2)
    f3 = minimal_fill(dcf=dict(dcf0, g_perp="待定"))
    assert "dcf.g_perp「待定」非空但不可解析为数值" in validate_stderr(f3)
    f4 = minimal_fill(dcf=dict(dcf0, wacc="—", growth_5y="—", g_perp="—"))
    out4 = validate_stderr(f4)
    assert "不可解析为数值" not in out4, "「—」占位应跳过"
    f5 = minimal_fill(dcf=dict(dcf0, wacc="0.085"))
    assert "疑为小数口径" in validate_stderr(f5), "wacc <1 应提示小数口径"
    f6 = minimal_fill(dcf=dict(dcf0, wacc="8.5%"))
    assert "疑似为小数口径" not in validate_stderr(f6) and "疑为小数口径" not in validate_stderr(f6)


# ---------------- v5.0 第 3 章「最新报告期透视」校验与渲染 ----------------
def test_period_track_cross_check():
    """v5.0 period_track 落盘交叉校验（quote 防伪同款纪律）：一致过 / 数值偏差>1% 拒 /
    照抄字段夹带文字拒 / 落盘无 period_track 键拒 / 文字同比完全一致 / fill 有值落盘 None
    （手估嫌疑）拒 / consensus_np 失配拒 / 漏抄软告警 / quote 缺失软告警。"""
    f = period_fill()
    R.validate_content(f, R.compute_valuation(f))  # 一致 → 过
    f = period_fill()
    f["period_track"]["np"] = 120.0
    expect_valueerror(f, "period_track.np 与落盘不一致应拒")
    f = period_fill()
    f["period_track"]["sq_ocf"] = 999.0
    expect_valueerror(f, "period_track.sq_ocf（v5.0.1 新增照抄键）与落盘不一致应拒")
    f = period_fill()
    f["period_track"]["rev"] = "301.98（H股口径）"
    expect_valueerror(f, "照抄字段夹带文字应拒")
    f = period_fill()
    f["period_track"]["consensus_np"] = 150.0
    expect_valueerror(f, "consensus_np 与落盘 np_avg 不一致应拒")
    with tempfile.TemporaryDirectory() as d:
        # 落盘无 period_track 键 → 拒（禁手估，神华同款）
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref.json")
        f = period_fill(quote={"source_file": ref, "date": "2026-08-27"})
        expect_valueerror(f, "落盘无 period_track 键应拒")
        # 文字同比：完全一致过 / 不一致拒
        pt_ref = {"period": "2026中报", "is_annual": False, "rev": 10.0, "np": 5.2,
                  "np_yoy": "扭亏", "sq_label": None, "band_years": []}
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0, "period_track": pt_ref},
                          d, name="em_ref2.json")
        pt = dict(pt_ref, goal_np=200.0)
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}, period_track=pt)
        R.validate_content(f, R.compute_valuation(f))  # 文字一致 → 过
        f["period_track"]["np_yoy"] = "转亏"
        expect_valueerror(f, "文字同比不完全一致应拒")
        # fill 有值而落盘 None（手估嫌疑）→ 拒
        f = minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"},
                         period_track=dict(pt, np_dedt=9.99))
        expect_valueerror(f, "落盘无值 fill 手估应拒")
        # 落盘有 period_track 而 fill 未回填 → 软告警不拒
        out = validate_stderr(minimal_fill(quote={"source_file": ref2, "date": "2026-08-27"}))
        assert "第 3 章" in out and "将缺席" in out, "落盘有 fill 无应软告警"
    # 漏抄（fill None 落盘有值）→ 软告警不拒
    f = period_fill()
    f["period_track"]["np_dedt"] = None
    out = validate_stderr(f)
    assert "漏抄" in out and "np_dedt" in out, "漏抄字段应软告警"
    # F5：is_annual 进交叉校验——fill 篡改 true→false 拒渲染（年报期整章消失是硬约束）
    f = period_fill("annual")
    f["period_track"]["is_annual"] = False
    try:
        R.validate_content(f, R.compute_valuation(f))
        raise AssertionError("is_annual 篡改应拒但未拒")
    except ValueError as e:
        assert "is_annual" in str(e), f"应报 is_annual 不一致，实际: {e}"
    # quote 缺失（存量日期软门禁）→ 无法交叉校验软告警，不拒
    f = period_fill()
    del f["quote"]
    assert "无法交叉校验" in validate_stderr(f), "quote 缺失应软告警不拒"


def test_period_track_verdict_goal_gate():
    """v5.0：verdict_* 非四选一拒 / 缺失软告警（渲染兜底无法判定）；goal_* 非正数或夹带
    文字拒；年报期填 industry/forecast/note 软告警不拒；note_html 纯文本 >120 字软告警。"""
    f = period_fill()
    f["period_track"]["verdict_np"] = "超预期"
    expect_valueerror(f, "判词非法取值应拒")
    f = period_fill()
    del f["period_track"]["verdict_np"]
    out = validate_stderr(f)
    assert "verdict_np 未填" in out and "无法判定" in out, "判词缺失应软告警"
    f = period_fill()
    f["period_track"]["goal_np"] = -5
    expect_valueerror(f, "经营目标负数应拒")
    f = period_fill()
    f["period_track"]["goal_np"] = "约200亿"
    expect_valueerror(f, "经营目标夹带文字应拒")
    # 年报期填内容 → 软告警不拒；verdict 缺失不告警（整章消失，判词无意义）
    f = period_fill("annual")
    f["period_track"]["note_html"] = "年报口径提示一句。"
    out = validate_stderr(f)
    assert "整章消失" in out and "不会渲染" in out, "年报期填内容应软告警"
    assert "verdict_" not in validate_stderr(period_fill("annual")), "年报期判词缺失不告警"
    f = period_fill()
    f["period_track"]["note_html"] = "口径提示超长" * 25
    out = validate_stderr(f)
    assert "note_html" in out and "> 120" in out, "note_html 超长应软告警"
    f = period_fill()
    f["period_track"]["summary_html"] = "小结超长" * 30
    out = validate_stderr(f)
    assert "summary_html" in out and "> 100" in out, "summary_html 超长应软告警"


def test_period_chapter_render():
    """v5.0.1 第 3 章渲染：TOC 与章节同生共灭（锚件=累计一览卡）；小结条/一览卡/子弹图/
    单季双联图落位；双分母缺失 → 子弹图无参照行整图缺席、章节靠一览卡存活；
    四项金额全缺 → 整章消失（TOC 同灭）。"""
    html = render_fill(period_fill())
    assert 'href="#s3"' in html and 'id="s3"' in html, "has_period 时 TOC 与章节同生"
    assert "进度小结" in html and "本期累计一览" in html, "小结条与一览卡落位"
    assert 'aria-label="报告期进度子弹图"' in html and 'aria-label="单季同比对比图"' in html
    assert "经营目标 200 亿 · 已完成 48.6%" in html and "一致预期 165 亿 · 已完成 58.9%" in html, \
        "双分母刻度带完成度"
    assert "节奏带（按" in html, "节奏带注"
    for frag in ("营业收入（亿元）", "经营现金流（亿元）", "归母净利（亿元）", "扣非净利（亿元）"):
        assert frag in html, f"单季双联四组缺 {frag}"
    s3_blk = html.split('id="s3"', 1)[1].split('id="s4"', 1)[0]
    assert "<table" not in s3_blk, "v5.0.1 绝对额表已删除（信息并入一览卡与子弹图刻度）"
    assert html.find('id="s3"') < html.find('id="s4"'), "第 3 章应插在原 s3（现 s4）之前"
    # 年报期：TOC 与章节同灭
    html_a = render_fill(period_fill("annual"))
    assert 'href="#s3"' not in html_a and 'id="s3"' not in html_a, "年报期整章消失"
    # 双分母缺失：子弹图无参照行整图缺席（不画空轨道），章节靠一览卡存活（TOC 不死链）
    f = period_fill()
    f["period_track"]["goal_np"] = None
    f["period_track"]["consensus_np"] = None
    html2 = render_fill(f)
    assert 'id="s3"' in html2 and 'href="#s3"' in html2 and "本期累计一览" in html2
    assert 'aria-label="报告期进度子弹图"' not in html2, "无全年参照不画子弹图"
    assert "一致预期 165 亿" not in html2 and "经营目标 200 亿" not in html2
    # 四项金额全缺 → 一览卡空串 → 整章消失（TOC 同灭，无死链）
    f = period_fill()
    f["period_track"] = {"period": "2026中报", "is_annual": False}
    html3 = render_fill(f)
    assert 'id="s3"' not in html3 and 'href="#s3"' not in html3, "四值全缺整章消失"


def test_period_charts_shapes():
    """v5.0.1 图函数形态：小结条徽章合成与 summary_html 直通 / 一览卡四卡与全缺空串 /
    子弹图仅画有参照行（无分母行跳过并图注点名、扣非永不入图）/ 刻度带完成度 /
    缺判词兜底无法判定 / 单季双联四组与 Q1 退化单柱 / 缺 sq_label 或四组全 None 返回空串。"""
    from charts_period import (build_period_summary, build_period_kpi,
                             build_period_bullets, build_period_sqplot)
    h1 = period_fill("h1")["period_track"]
    # 小结条：徽章合成 + 无参照点名 + summary_html 手填句直通
    s = build_period_summary(h1)
    assert "进度小结" in s and ">超前</span>" in s and ">正常</span>" in s
    assert "完成卖方一致预期 58.9%" in s, "summary_html 手填句直通"
    assert "营业收入、扣非净利无金额化全年参照" in s and "经营现金流不设判词" in s
    assert build_period_summary({"ocf": 10.0}) == "", "无判词指标且无手填句 → 空串"
    # 一览卡：四卡齐全、缺值标—、全缺空串
    k = build_period_kpi(h1)
    assert k.count("metric-card") == 4 and "92.10" in k and "+49.7%" in k
    k2 = build_period_kpi({"rev": 10.0})
    assert k2.count("metric-card") == 4 and ">—<" in k2, "缺值卡标—"
    assert build_period_kpi({"rev": None, "np": None, "np_dedt": None, "ocf": None}) == ""
    # 子弹图：仅归母行（goal/cons 在），营业收入不画行、扣非永不入图
    b = build_period_bullets(h1)
    assert ">归母净利</text>" in b and ">营业收入</text>" not in b and ">扣非净利</text>" not in b
    assert "经营目标 200 亿 · 已完成 48.6%" in b and "一致预期 165 亿 · 已完成 58.9%" in b
    assert "营业收入无金额化全年参照" in b, "跳过行图注点名"
    assert ">超前</text>" in b
    assert build_period_bullets({"np_dedt": 21.47}) == "", "扣非无分母口径不画"
    assert build_period_bullets({"rev": 100.0}) == "", "营收无 goal_rev 不画"
    assert build_period_bullets({"rev": None, "np": None, "np_dedt": None}) == ""
    # 缺判词 → 无法判定兜底
    b2 = build_period_bullets({"np": 5.0, "consensus_np": 100.0})
    assert ">无法判定</text>" in b2
    # 单季双联：四组齐（收入/现金流左联，归母/扣非右联）
    svg = build_period_sqplot(h1)
    for frag in ("营业收入（亿元）", "经营现金流（亿元）", "归母净利（亿元）", "扣非净利（亿元）",
                 "收入与经营现金流", "归母与扣非", "+40.8%", "+84.9%", "+65.7%", "+50.1%",
                 "2025Q2", "2026Q2"):
        assert frag in svg, f"双联图缺 {frag}"
    # Q1 退化单柱
    q1 = build_period_sqplot(period_fill("q1")["period_track"])
    assert "2025Q1" not in q1 and "累计即单季" in q1, "Q1 期应退化单柱"
    # 空串门禁
    assert build_period_sqplot({"sq_rev": 1}) == "", "缺 sq_label 返回空串"
    assert build_period_sqplot({"sq_label": "2026Q2", "sq_rev": None, "sq_np": None,
                                "sq_dedt": None, "sq_ocf": None}) == ""
    # 整联缺席：只剩收入/现金流 → 右联标题缺席（联标题以 </text> 收尾，与图注措辞区分）
    svg2 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": 10.0, "sq_ocf": 5.0,
                                "sq_prev_label": "2025Q2", "sq_prev_rev": 8.0,
                                "sq_prev_ocf": 4.0})
    assert ">收入与经营现金流</text>" in svg2 and ">归母与扣非</text>" not in svg2


def test_period_track_key_drift():
    """period_track 键集漂移守卫（v5.1.5）：生产端（em_finance._PERIOD_TRACK_KEYS 常量与
    _period_track_calc 实际产出）、校验端（validate 四组键 + is_annual/band_years）、落盘参照
    （conftest._PERIOD_REF_KEYS）三处必须对齐——任一处加键忘同步即红
    （end_date/gm 为生产端内部键，不入参照）。"""
    import em_finance
    import validate as V
    ref = set(_PERIOD_REF_KEYS)
    assert set(em_finance._PERIOD_TRACK_KEYS) - {"end_date", "gm"} == ref, \
        "生产端常量 vs 落盘参照键集漂移"
    vkeys = (set(V._PERIOD_LABEL_KEYS) | set(V._PERIOD_NUM_KEYS) | set(V._PERIOD_YOY_KEYS)
             | set(V._PERIOD_BAND_KEYS) | {"is_annual", "band_years"})
    assert vkeys == ref, "校验端四组键 vs 落盘参照键集漂移"
    rows = [{"ED": "20260630", "TOTALOPERATEREVE": 1e8, "PARENTNETPROFIT": 1e7,
             "KCFJCXSYJLR": None, "NETCASH_OPERATE_PK": None, "XSMLL": None}]
    assert set(em_finance._period_track_calc(rows)) == set(em_finance._PERIOD_TRACK_KEYS), \
        "常量与 _period_track_calc 实际产出键集漂移"


def test_period_charts_negative_domain():
    """F1/F2 负值域修复（v5.0.1 适配）：子弹图——归母亏损（有参照）/全负/零值/负一致预期渲染
    不炸且语义正确（负值条自零轴左伸、负分母不画节奏带且图注标不适用、域退化兜底不除零、
    累计或分母 ≤0 不标完成度）；单季双联——双负（减亏/增亏季）/单负（最新季负）不炸、
    柱体在 viewBox 内。"""
    import re as _re
    from charts_period import build_period_bullets, build_period_sqplot
    # ① 归母亏损（np<0，有经营目标参照）：不炸；负值条标签存在；正值分母刻度与节奏带照常
    pt = {"np": -2.0, "np_yoy": "转亏", "goal_np": 100.0, "consensus_np": 165.0,
          "band_np": [39.9, 52.1], "verdict_np": "滞后"}
    b = build_period_bullets(pt)
    assert b and 'aria-label="报告期进度子弹图"' in b
    assert "-2 亿" in b and "转亏" in b, "负值条与文字同比应渲染"
    assert "一致预期 165 亿" in b and "节奏带（按" in b, "分母刻度与节奏带不受影响"
    # ② 全行负值（有参照才画）：域含 0、条自零轴左伸（不夹成 2px 细条钉零位）、不除零
    b2 = build_period_bullets({"np": -50.0, "goal_np": 100.0})
    assert b2, "负值应渲染"
    assert "-50 亿" in b2 and 'width="2.0"' not in b2, "负值条不得被夹成 2px 细条"
    # ③ 零值：域退化兜底 lo+1.0，不炸
    b3 = build_period_bullets({"np": 0.0, "goal_np": 100.0})
    assert b3 and 'aria-label="报告期进度子弹图"' in b3
    # ④ 负一致预期：节奏带不画、图注标「分母为负…节奏带不适用」；负刻度在画布内
    b4 = build_period_bullets({"np": -5.0, "consensus_np": -50.0, "band_np": [40.0, 55.0]})
    assert "分母为负" in b4 and "节奏带不适用" in b4, "负分母应出图注"
    assert "节奏带（按" not in b4, "负分母不得换算节奏带"
    assert "一致预期 -50 亿" in b4, "负一致预期刻度应在负域内画出"
    # 累计或分母 ≤0 → 完成度无意义不标
    assert "已完成" not in b and "已完成" not in b4, "累计/分母 ≤0 不标完成度"
    # F2：双负（增亏/减亏季）与单负（最新季负）不炸、所有 rect 在 viewBox 内
    sq1 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": -10.0, "sq_np": -3.0,
                               "sq_prev_label": "2025Q2", "sq_prev_rev": -8.0,
                               "sq_prev_np": -5.0, "sq_np_yoy": "减亏"})
    assert sq1 and "减亏" in sq1, "双负季应渲染"
    sq2 = build_period_sqplot({"sq_label": "2026Q2", "sq_rev": 100.0, "sq_np": -3.0,
                               "sq_prev_label": "2025Q2", "sq_prev_rev": 90.0,
                               "sq_prev_np": 5.0, "sq_np_yoy": "转亏"})
    assert sq2 and "转亏" in sq2
    for svg, W, H in ((sq1, 1000, 268), (sq2, 1000, 268)):
        for m in _re.finditer(r'<rect x="([\d.-]+)" y="([\d.-]+)" width="([\d.-]+)" '
                              r'height="([\d.-]+)"', svg):
            x, y, w, h = (float(m.group(i)) for i in (1, 2, 3, 4))
            assert -1 <= x and x + w <= W + 1, f"rect 横向越界: {m.group(0)}"
            assert -1 <= y and y + h <= H + 1, f"rect 纵向越界: {m.group(0)}"


def test_cycle_stages_period_warn():
    """v5.1.3：period 解析不出起止月份 → 软告警「季K图阶段分界不落该段」
    （与渲染同源 parse_stage_period；合法格式如 2023/01–2023/12、2023-01~2024-06 放行）。"""
    base = [{"name": "阶段一", "period": "2023/01–2023/12", "current": False},
            {"name": "阶段二", "period": "2024-01~2024-12", "current": False},
            {"name": "阶段三", "period": "2025/01-2025/12", "current": False},
            {"name": "阶段四", "period": "2026/01–至今", "current": True}]
    out = validate_stderr(minimal_fill(cycle_stages=base))
    assert "阶段分界不落该段" not in out, "合法 period 不应告警"
    bad = [dict(base[0], period="去年至今"), base[1],
           dict(base[2], period="2025/13–2026/01"), base[3]]   # 无数字/月份越界；current 在阶段四
    out2 = validate_stderr(minimal_fill(cycle_stages=bad))
    assert out2.count("阶段分界不落该段") == 2, "非法 period（无数字/月份越界）应各告警一条"


def test_period_track_hk_deadend_message():
    """v5.5.1 F1：港股（5 位代码）period_track 硬拒点文案。港股 em_fetch 依赖 tushare
    hk_income 权限，无权限时 period_track 永不落盘，报错须指向「删除 fill 的 period_track」
    而非重跑 em_fetch（小米 01810 2026-10-07 实证：拦得对、文案误导）。
    拒渲染本身不变（防伪链不动），A 股文案保持原样。"""
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_ref.json")
        q = {"source_file": ref, "date": "2026-08-27"}
        # A 股：既有文案（重跑 em_fetch --out 落盘 或 删除 fill 的 period_track）
        f = period_fill(quote=q)
        try:
            R.validate_content(f, R.compute_valuation(f))
            raise AssertionError("A 股落盘无 period_track 键应拒渲染")
        except ValueError as e:
            assert "重跑 em_fetch --out 落盘" in str(e), f"A 股文案应保持原样，实际: {e}"
            assert "港股" not in str(e), f"A 股文案不应提港股，实际: {e}"
        # 港股：仍拒渲染（防伪链不动），文案改指港股真实出路
        fh = minimal_fill(code="01810", quote=q,
                          period_track={"period": "2026中报", "rev": 100.0})
        try:
            R.validate_content(fh, R.compute_valuation(fh))
            raise AssertionError("港股落盘无 period_track 键仍应拒渲染（防伪链不动）")
        except ValueError as e:
            m = str(e)
            assert "hk_income" in m and "删除" in m, f"港股文案应指向删字段，实际: {m}"
            assert "勿重跑" in m, f"港股文案应劝止重跑 em_fetch，实际: {m}"


def test_period_track_band_years_type_guard():
    """#小1: band_years 传字符串按字符迭代误比对（空串曾与空列表假相等漏网、
    "2023" 被拆成 [2,0,2,3]）——与 band 守卫对齐：非数组一律按不一致拒。"""
    f = period_fill("annual")
    f["period_track"]["band_years"] = ""   # 落盘为 []：修复前 []==[] 假相等漏网
    expect_valueerror(f, "band_years 空字符串应拒", kw="period_track.band_years")
    f = period_fill("h1")
    f["period_track"]["band_years"] = "2023-2025"
    expect_valueerror(f, "band_years 字符串应拒", kw="period_track.band_years")
