#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_render_gate_source.py — render_report 来源与照抄对账回归：gap_history/gap_plot street 落盘源/pe_history 禁填/prev 复盘锚/最终 HTML 来源注硬门禁域（无网络；pytest 唯一入口，无 __main__ 直跑契约）

v5.8.2 自 test_render_gate.py 按域拆分（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import re
import sys
import tempfile
from html import unescape as _html_unescape

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validate import _is_hk_code
from conftest import (
    minimal_fill, full_fill, expect_valueerror, validate_stderr, write_fill,
    render_fill, period_fill,
)

# v5.8.2：gap_history 照抄行共用构造（test_gap_history_gate/tp_reports_gate 逐字复用、
# handwritten_dupe 为其行子集）——单源防漂移
_GH_ROW = {"org": "中金公司", "yr": "2026", "d_from": "2026-06-30", "d_to": "2026-09-28",
           "np_from": 930.0, "np_to": 952.0}


def test_timing_facts_evidence_cross_check():
    technical = {"rsi14": 55.0, "atr14_pct": 2.4, "volume_ratio_20": 1.2}
    levels = {"start_date": "2023-08-27", "end_date": "2026-08-27",
              "close_high": 15, "close_low": 8, "intraday_high": 16, "intraday_low": 7,
              "months": 36, "ohlc_months": 36, "window_years": 3}
    chip = {"value": 11.2, "unit": "元", "date": "2026-08-27",
            "source": "妙想", "query": "平均成本"}
    with tempfile.TemporaryDirectory() as d:
        quote = write_fill({"price": 10, "pe_ttm": 11,
                            "timing": {"technical": technical, "consensus_levels": levels}},
                           d, "_ref_quote.json")
        evidence = write_fill({"code": "600000", "date": "2026-08-27",
                               "chips": {"average_cost": chip}, "capital": {}},
                              d, "_timing_600000_2026-08-27.json")
        facts = {"source_file": evidence, "technical": technical, "consensus_levels": levels,
                 "chips": {"average_cost": chip}, "capital": {}}
        fill = minimal_fill(quote={"source_file": quote}, timing_facts=facts)
        assert "timing_facts" not in validate_stderr(fill)
        assert "技术、筹码与资金事实" in render_fill(fill)
        bad = minimal_fill(quote={"source_file": quote},
                           timing_facts={**facts, "technical": dict(technical, rsi14=60)})
        assert "rsi14" in validate_stderr(bad)
        bad = minimal_fill(quote={"source_file": quote},
                           timing_facts={**facts, "chips": {"average_cost": dict(chip, value=12)}})
        assert "average_cost" in validate_stderr(bad)
        bad = minimal_fill(quote={"source_file": quote},
                           timing_facts={**facts, "chips": {"average_cost": None}})
        assert "average_cost" in validate_stderr(bad)
        bad = minimal_fill(quote={"source_file": quote},
                           timing_facts={**facts, "source_file": "missing.json"})
        expect_valueerror(bad, "缺失证据文件", kw="timing_facts.source_file")
        no_quote = minimal_fill(timing_facts=facts)
        assert "技术" in validate_stderr(no_quote)


def test_timing_facts_rejects_invalid_container_types():
    expect_valueerror(minimal_fill(timing_facts={"technical": "invalid"}),
                      "非法技术字段", kw="timing_facts.technical")
    with tempfile.TemporaryDirectory() as d:
        evidence = write_fill({"code": "600000", "date": "2026-08-27",
                               "chips": {"average_cost": {"value": 11.2}}, "capital": {}},
                              d, "_timing_600000_2026-08-27.json")
        facts = {"source_file": evidence, "chips": {"average_cost": "invalid"}}
        expect_valueerror(minimal_fill(timing_facts=facts), "非法单项记录",
                          kw="timing_facts.chips.average_cost")


def test_pe_history_banned_types():
    """v5.4.1：pe_history 禁填告警（fill-schema 填写条件此前只写在文档里、零校验）——
    成长型·高速层（含旧名「快速成长」）与未盈利/管线填了 → 软告警；
    周期股 / 成长型·中速层 / 成熟·停滞 / 稳定价值 / 困境反转填了 → 不告警；未填永不告警。"""
    ph = {"hist_lo": 13.7, "hist_hi": 83.2, "label": "近5年"}
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="成长型", growth_tier="high"))
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="快速成长（强周期属性）")), "旧名快速成长同样命中"
    assert "pe_history 已填但本分型" in validate_stderr(
        minimal_fill(pe_history=ph, stock_type="未盈利/管线"))
    for over in ({"stock_type": "成长型", "growth_tier": "mid"}, {"stock_type": "周期股"},
                 {"stock_type": "成熟/停滞"}, {"stock_type": "稳定价值/金融（银行）"},
                 {"stock_type": "困境反转"}):
        assert "pe_history 已填但本分型" not in validate_stderr(minimal_fill(pe_history=ph, **over)), \
            f"{over} 允许填 pe_history，不应告警"
    assert "pe_history 已填但本分型" not in validate_stderr(
        minimal_fill(stock_type="成长型", growth_tier="high"))


def test_gap_plot_street_source_gate():
    """v5.5.1 F2：gap_plot.street 落盘第二照抄源（首版软告警，不拒）——港股 street 非空而
    无 source_file → 告警（E5 对港股无逐机构明细，防手填）；source_file 读不到 / 结构非法 /
    数值对不上 → 告警；数值对得上 → 静默；A 股无 source_file 不告警（存量合法用法=
    street 直接照抄 E5「净利明细/目标价明细」行）。"""
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750,
             "street": [{"org": "国泰海通", "v": 1830}]},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120,
             "street": [{"org": "花旗", "v": 1180}]}]
    # 港股无 source_file → 告警（指向 _street_ 落盘路径）
    out = validate_stderr(minimal_fill(code="01810", gap_plot={"dims": dims}))
    assert "gap_plot.street 无落盘源" in out and "_street_" in out, "港股 street 无源应告警"
    # A 股无 source_file → 静默（不误伤存量照抄 E5 行的合法用法）
    assert "gap_plot.street 无落盘源" not in validate_stderr(
        minimal_fill(code="600000", gap_plot={"dims": dims})), "A 股 street 无源不应告警"
    with tempfile.TemporaryDirectory() as d:
        ok = write_fill(
            {"source": "2026-10-07 六家机构电话调研纪要",
             "dims": {"2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830,
                                                "date": "2026-09-28"}],
                      "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_01810_10-07.json")
        # 数值对得上 → 静默
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": ok}))
        assert "无对应记录" not in out and "读取失败" not in out and "结构非法" not in out \
            and "四要素" not in out, "street 数值可在落盘源中找到时不应告警"
        # 数值对不上 → 告警（文案须写明真实容差口径）
        bad = [dict(dims[0], street=[{"org": "国泰海通", "v": 1500}]), dims[1]]
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": bad, "source_file": ok}))
        assert "无对应记录" in out, "street 数值与落盘源对不上应告警"
        assert "容差" in out and "0.005" in out, "告警文案应写明容差口径（1%，下限 0.005）"
        # 维度在落盘源中缺键 → 告警
        one = write_fill({"source": "调研", "dims": {}}, d, name="_street_01810_10-08.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": one}))
        assert "无对应维度记录" in out, "落盘源缺维度键应告警"
        # 结构非法（缺 dims 对象）→ 告警
        bad_struct = write_fill([{"org": "花旗", "v": 1180}], d, name="_street_bad.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": bad_struct}))
        assert "结构非法" in out, "落盘源缺 dims 对象应告警"
        # 记录缺机构名/日期（四要素不全）→ 告警
        noorg = write_fill(
            {"source": "调研", "dims": {"2026E 出货量（万台）": [{"v": 1830}],
                                        "2026E 均价（元）": [{"org": "花旗", "v": 1180,
                                                              "date": "2026-10-01"}]}},
            d, name="_street_01810_10-09.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": noorg}))
        assert "四要素" in out, "记录缺机构名/日期应告警"
        # 落盘源缺 source（文件级来源说明）→ 告警
        nosrc = write_fill(
            {"dims": {"2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830,
                                               "date": "2026-09-28"}],
                      "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_01810_10-10.json")
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": dims, "source_file": nosrc}))
        assert "缺 source" in out, "落盘源缺 source（来源说明）应告警"
        # 文件读不到 → 告警不拒
        out = validate_stderr(minimal_fill(
            code="01810",
            gap_plot={"dims": dims, "source_file": os.path.join(d, "不存在.json")}))
        assert "gap_plot.source_file 读取失败" in out, "source_file 读不到应告警"
        # 图下来源注：注明调研纪要落盘核对（v5.7.3 起不外露本地文件名与内部数据源编号）
        html = render_fill(minimal_fill(code="01810",
                                        gap_plot={"dims": dims, "source_file": ok}))
        assert "人工调研纪要（落盘核对）" in html, \
            "有 source_file 时图注应注明调研纪要落盘核对口径"
        assert os.path.basename(ok) not in html and ok not in html, \
            "图注不得暴露本地文件名或全路径"
    assert "券商研报明细与一致预期汇总" in render_fill(minimal_fill(gap_plot={"dims": dims})), \
        "无 source_file 时图注写券商研报明细口径"


def test_gap_plot_street_org_match():
    """v5.5.1 P1-2：street 对账按机构名匹配（防张冠李戴）——fill 写「摩根士丹利 1830」而落盘
    是「国泰海通 1830」→ 告警（数值相同也不算）；同 org 对得上 → 静默；同 org 多条任一命中
    → 静默（同机构取最新口径）；org 缺失（未具名点）→ 退全池数值比对。"""
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750,
             "street": [{"org": "国泰海通", "v": 1830}]},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120,
             "street": [{"org": "花旗", "v": 1180}]}]
    with tempfile.TemporaryDirectory() as d:
        src = write_fill(
            {"source": "调研", "dims": {
                "2026E 出货量（万台）": [{"org": "国泰海通", "v": 1830, "date": "2026-09-28"},
                                        {"org": "国泰海通", "v": 1810, "date": "2026-08-15"},
                                        {"org": "中金", "v": 1850, "date": "2026-09-20"}],
                "2026E 均价（元）": [{"org": "花旗", "v": 1180, "date": "2026-10-01"}]}},
            d, name="_street_org.json")
        # 张冠李戴：数值与落盘中某条相同，但署名机构对不上 → 告警
        wrong = [dict(dims[0], street=[{"org": "摩根士丹利", "v": 1830}]), dims[1]]
        out = validate_stderr(minimal_fill(code="01810",
                                           gap_plot={"dims": wrong, "source_file": src}))
        assert "无对应记录" in out and "摩根士丹利" in out, \
            "机构名对不上应告警（数值相同也不能算对账成功）"
        # 同 org 命中（同机构多条取其一）→ 静默
        same = [dict(dims[0], street=[{"org": "国泰海通", "v": 1810}]), dims[1]]
        assert "无对应记录" not in validate_stderr(
            minimal_fill(code="01810", gap_plot={"dims": same, "source_file": src})), \
            "同机构数值命中应静默"
        # org 缺失（未具名点）→ 退全池数值比对，不误报
        noorg = [dict(dims[0], street=[{"v": 1830}]), dims[1]]
        assert "无对应记录" not in validate_stderr(
            minimal_fill(code="01810", gap_plot={"dims": noorg, "source_file": src})), \
            "未具名点应退全池数值比对"


def test_is_hk_code_single_source():
    """v5.5.1 P1-3：港股判定收单源 `_is_hk_code`（5 位数字）——period_track 硬拒文案、
    gap_plot street 无源门、cagr_adjustments 例外三处共用同一判定。"""
    assert _is_hk_code({"code": "01810"}) and _is_hk_code({"code": " 00700 "})
    for code in ("600000", "000001", "830799", "399001", "0181", "018100", None, ""):
        assert not _is_hk_code({"code": code}), f"{code!r} 不应判为港股"


def test_prev_charts_structure_warn():
    """v5.5.1 F3：复盘模式「旧有新无」结构对照（软告警）——prev.charts 缺失提醒回填；
    gap_plot 旧有本无 / fin_trend 有效面板变少 / growth_plot.fcst 年少 / pe_history 有→无
    逐项各一条（文案要求 review_html 写明减配理由）；本版补齐 → 该项静默；无 prev → 静默。"""
    # prev 无 charts → 提醒回填；无 prev → 全程静默
    f_no = full_fill()
    del f_no["prev"]["charts"]
    assert "prev.charts 未填" in validate_stderr(f_no), "prev 有而 charts 缺失应告警提醒回填"
    assert "prev.charts" not in validate_stderr(minimal_fill()), "无 prev 应全程静默"
    # 上版 gap_plot 已生成、本版无 → 告警；本版补齐（有效维度 ≥2）→ 该项静默
    dims = [{"name": "2026E 出货量（万台）", "ours": 1800, "consensus": 1750},
            {"name": "2026E 均价（元）", "ours": 1150, "consensus": 1120}]
    f = full_fill()
    f["prev"]["charts"] = {"gap_plot": True}
    out = validate_stderr(f)
    assert "复盘减配" in out and "gap_plot" in out and "review_html" in out, "上版有图本版无应告警"
    f2 = full_fill()
    f2["prev"]["charts"] = {"gap_plot": True}
    f2["gap_plot"] = {"dims": dims}
    assert "复盘减配" not in validate_stderr(f2), "本版补齐图后该项应静默"
    # fin_trend 有效面板 4 → 3
    f = full_fill()
    f["prev"]["charts"] = {"fin_trend_panels": 4}
    f["fin_trend"]["panels"] = f["fin_trend"]["panels"][:3]
    out = validate_stderr(f)
    assert "复盘减配" in out and "fin_trend" in out and "4" in out and "3" in out, \
        "面板变少应告警"
    # growth_plot.fcst 有效年 2 → 1
    f = full_fill()
    f["prev"]["charts"] = {"growth_fcst_years": 2}
    out = validate_stderr(f)
    assert "复盘减配" in out and "fcst" in out, "预测年少应告警"
    # pe_history 有 → 无
    f = full_fill()
    f["prev"]["charts"] = {"pe_history": True}
    del f["pe_history"]
    out = validate_stderr(f)
    assert "复盘减配" in out and "pe_history" in out, "pe_history 有→无应告警"
    # 本版比上版「变多」→ 静默（只报减配，不报增配）
    f = full_fill()
    f["prev"]["charts"] = {"fin_trend_panels": 2, "growth_fcst_years": 1}
    assert "复盘减配" not in validate_stderr(f), "本版比上版图多不应告警"
    # 四项齐平（本版与上版一致）→ 无减配告警
    f = full_fill()
    f["prev"]["charts"] = {"gap_plot": False, "fin_trend_panels": 4,
                           "growth_fcst_years": 1, "pe_history": True}
    assert "复盘减配" not in validate_stderr(f), "与上版齐平不应告警"


def test_prev_charts_pe_history_keys():
    """v5.5.1 P1-1：prev.charts.pe_history 判定与渲染同源（charts_cycle._pe_band_ok 单源）——
    本版 pe_history 只剩 hist_lo（缺 hist_hi，build_pe_band 不落图）而 prev.charts.pe_history=true
    → 告警（此前只看字段非空，缺键减配漏检）；hist_lo/hist_hi + valuation_inputs 的
    pe_ttm/pe_band 五键齐备 → 静默。"""
    f = full_fill()
    f["prev"]["charts"] = {"pe_history": True}
    f["pe_history"] = {"hist_lo": 13.7}          # 缺 hist_hi → 图不生成
    out = validate_stderr(f)
    assert "复盘减配" in out and "pe_history" in out, "pe_history 缺键导致图不生成应告警"
    f2 = full_fill()
    f2["prev"]["charts"] = {"pe_history": True}
    assert "复盘减配" not in validate_stderr(f2), "五键齐备应静默"


def test_prev_fields_warns():
    """#11: prev 锚点缺项（quality/valuation/timing/target_range）+ review_html 无
    关键假设变更表 → 告警到 stderr。"""
    prev = {"date": "2026-08-08",
            # base 带与本版一致（10-12x）→ 不触发锚移动硬拒，单测 _check_prev_fields
            "scenarios": [{"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                           "目标价": "9.5-11.4 元"}]}
    out = validate_stderr(minimal_fill(prev=prev, review_html="<p>复盘文字，无表格。</p>"))
    for kw in ("prev.quality 缺失", "prev.valuation 缺失", "缺关键假设变更表"):
        assert kw in out, f"应告警含「{kw}」，实际 stderr: {out}"
    out_ok = validate_stderr(full_fill())
    assert "prev.quality 缺失" not in out_ok and "缺关键假设变更表" not in out_ok, \
        "full_fill 锚点齐备、review 有假设表，不应告警"


def test_prev_cross_version_unmarked_warns_by_field():
    """v5.7.2：回测模式下非 review 章节含明确跨版表述但未挂 .rev → 分字段告警；
    已标 rev（含 rev num 多类）与普通「新增产能」业务文字不得误报。"""
    prev = {"date": "2026-08-08", "quality": 7.0, "valuation": 6.0, "timing": 5.0,
            "target_range": "10-12",
            "scenarios": [{"scenario": "基础情景", "归母净利": "95 亿", "PE": "10-12x",
                           "目标价": "9.5-11.4 元"}]}
    review = ('<table><tr><td>假设变更对比</td></tr></table><span class="source">数据来源：测试</span>'
              '<span class="rev">甲</span><span class="rev">乙</span>')
    f = minimal_fill(prev=prev, review_html=review)
    f["thesis_html"] += "Q3单季低于旧报告30亿警戒线。"
    f["cycle_html"] = "较上版规律修正：单期户数暴增不是顶部充分条件。" * 4
    f["peers_meta"] = "同业剔除依据沿用旧报告对比结论。"
    f["dash_html"] += '<span data-class="rev">旧报告对照口径</span>'
    f["p0_html"] += "α-烯烃一期新增125万吨产能。"
    f["gap_html"] += "适用于 3.10 及以上版本。"
    f["valuation_html"] += "新旧版本口径一致。"
    f["position_html"] += '<span class="rev num">较上版时机分下调</span>'

    out = validate_stderr(f)
    lines = [ln for ln in out.splitlines() if "跨版表述未挂 .rev" in ln]
    assert len(lines) == 1, f"应只有一条分字段告警，实际 stderr: {out}"
    line = lines[0]
    for kw in ("thesis_html（旧报告）", "cycle_html（较上版）", "peers_meta（旧报告）",
               "dash_html（旧报告）"):
        assert kw in line, f"告警应点名 {kw}，实际: {line}"
    for absent in ("p0_html", "gap_html", "valuation_html", "position_html", "review_html"):
        assert absent not in line, f"{absent} 不应误报，实际: {line}"
    assert "高亮过少" not in out, "class='rev num' 也应计入全文高亮数"


def test_gap_history_gate():
    """v5.6.0：gap_history 照抄对账（首版软告警）——落盘一致静默 / 偏差>1% 告警 /
    机构落盘无告警 / 落盘无 gap_history 键告警 / quote.source_file 缺失告警 /
    预测年度混杂告警 / 空 rows 告警 / 非 dict 行拒渲染。"""
    row = dict(_GH_ROW, tp_from=118.0, tp_to=135.0)
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "gap_history": {"rows": [row]}}, d, name="em_gh.json")
        q = {"source_file": ref, "date": "2026-10-14"}
        out = validate_stderr(minimal_fill(quote=q, gap_history={"rows": [dict(row)]}))
        assert "gap_history" not in out, f"照抄一致不应告警，实际: {out}"
        out = validate_stderr(minimal_fill(
            quote=q, gap_history={"rows": [dict(row, np_to=990.0)]}))
        assert "np_to" in out and "不一致" in out, f"偏差>1% 应告警: {out}"
        out = validate_stderr(minimal_fill(
            quote=q, gap_history={"rows": [dict(row, org="中信证券")]}))
        assert "无对应机构" in out, f"落盘无该机构应告警: {out}"
        out = validate_stderr(minimal_fill(quote=q, gap_history={"rows": [
            dict(row), dict(row, org="国泰海通", yr="2027", np_from=940.0, np_to=965.0)]}))
        assert "预测年度不一致" in out and "无对应机构" in out, f"混年+缺机构应告警: {out}"
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0}, d, name="em_gh2.json")
        out = validate_stderr(minimal_fill(
            quote={"source_file": ref2, "date": "2026-10-14"},
            gap_history={"rows": [dict(row)]}))
        assert "落盘 JSON 无 gap_history.rows" in out, f"落盘无键应告警: {out}"
    out = validate_stderr(minimal_fill(gap_history={"rows": [dict(row)]}))
    assert "无落盘源可核对" in out, f"缺 source_file 应告警: {out}"
    out = validate_stderr(minimal_fill(gap_history={"rows": []}))
    assert "rows 为空" in out, f"空 rows 应提示: {out}"
    expect_valueerror(minimal_fill(gap_history={"rows": ["junk"]}), "非 dict 行应拒渲染")
    expect_valueerror(minimal_fill(gap_history=["junk"]), "gap_history 非对象应拒渲染")


def test_gap_history_em_source_note_gate():
    """v5.10.1：东财降级且无逐份研报时，gap_html 缺省说明不得静默漏写；
    有说明通过，tushare 成功来源不误报。"""
    with tempfile.TemporaryDirectory() as d:
        em_ref = write_fill({"price": 10.0, "pe_ttm": 11.0, "e5_source": "em"},
                            d, name="em_gh_em.json")
        q = {"source_file": em_ref, "date": "2026-10-25"}
        out = validate_stderr(minimal_fill(quote=q))
        assert "E5 东财降级" in out and "gap_html" in out, \
            f"东财来源且缺省说明漏写应告警: {out}"
        note = "<!--GAP--><p>券商态度变化图未生成：东财汇总无逐份研报。</p>"
        out = validate_stderr(minimal_fill(quote=q, gap_html=note))
        assert "E5 东财降级" not in out, f"已写缺省说明不应告警: {out}"
        ts_ref = write_fill({"price": 10.0, "pe_ttm": 11.0, "e5_source": "tushare"},
                            d, name="em_gh_ts.json")
        out = validate_stderr(minimal_fill(
            quote={"source_file": ts_ref, "date": "2026-10-25"}))
        assert "E5 东财降级" not in out, f"tushare 成功来源不应误报: {out}"


def test_gap_history_tp_reports_gate():
    """v5.8.1：tp_reports 反向漏抄告警（宁德 300750 复盘 2026-10-21 实证）——
    落盘有目标价研报清单而 fill 缺 tp_reports 且 rows 无 tp 对 → 告警；
    fill 照抄 / 落盘无清单 / rows 自带 tp 对（降级面板非必需）→ 不告警。"""
    row = dict(_GH_ROW)
    tp_reps = [{"org": "中金公司", "date": "2026-09-13", "tp": 500.0},
               {"org": "群益证券(香港)", "date": "2026-09-29", "tp": 390.0}]
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "gap_history": {"rows": [row], "tp_reports": tp_reps}},
                         d, name="em_ghtp.json")
        q = {"source_file": ref, "date": "2026-10-21"}
        out = validate_stderr(minimal_fill(quote=q, gap_history={"rows": [dict(row)]}))
        assert "tp_reports 漏抄" in out, f"落盘有清单而 fill 未抄应告警: {out}"
        out = validate_stderr(minimal_fill(quote=q, gap_history={
            "rows": [dict(row)], "tp_reports": [dict(x) for x in tp_reps]}))
        assert "漏抄" not in out, f"照抄一致不应告警: {out}"
        out = validate_stderr(minimal_fill(quote=q, gap_history={
            "rows": [dict(row, tp_from=490.0, tp_to=500.0)]}))
        assert "漏抄" not in out, f"rows 有 tp 对时降级面板非必需，不应告警: {out}"
        ref2 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "gap_history": {"rows": [row]}}, d, name="em_ghtp2.json")
        out = validate_stderr(minimal_fill(
            quote={"source_file": ref2, "date": "2026-10-21"},
            gap_history={"rows": [dict(row)]}))
        assert "漏抄" not in out, f"落盘无清单不应告警: {out}"
        # v5.8.1 审核实证：判定与渲染同源（排序后前 8 判 tp 对）——8 行 np 对 +
        # tp 对落第 9 行，fill 漏抄 tp_reports 时必须告警（全量扫描会漏报）
        rows9 = [{"org": f"券商{c}", "yr": "2026", "d_from": "2026-05-10",
                  "d_to": "2026-08-24", "np_from": 50 + i, "np_to": 60 + i}
                 for i, c in enumerate("ABCDEFGH")]
        rows9.append({"org": "券商I", "yr": "2026", "d_from": "2026-05-10",
                      "d_to": "2026-08-24", "tp_from": 40.0, "tp_to": 45.0})
        ref3 = write_fill({"price": 10.0, "pe_ttm": 11.0,
                           "gap_history": {"rows": rows9, "tp_reports": tp_reps}},
                          d, name="em_ghtp3.json")
        out = validate_stderr(minimal_fill(
            quote={"source_file": ref3, "date": "2026-10-21"},
            gap_history={"rows": [dict(r) for r in rows9]}))
        assert "tp_reports 漏抄" in out, f"tp 对在第 9 名后、fill 漏抄应告警: {out}"


def test_gap_history_handwritten_dupe():
    """v5.6.0：gap_history 图会生成时，gap_html 手写同内容变化表 → 告警；
    无 gap_history 或表不含变化关键词 → 不告警。"""
    rows = [dict(_GH_ROW)]
    tbl = ('<table><tr><th>券商</th><th>净利首末变化</th></tr>'
           '<tr><td>中金</td><td>上调 930→952</td></tr></table><span class="source">数据来源：E5</span>')
    out = validate_stderr(minimal_fill(
        gap_history={"rows": rows}, gap_html="<!--GAP--><p>档位 A：已检索到具体券商研报假设（妙想+tushare，查询日 2026-10-14），分歧集中在 2026E 净利的出货量假设上，本文基础情景处于一致预期区间内部偏上，证伪时向下修正至一致均值。</p>" + tbl))
    assert "手写券商态度变化表" in out, f"图+手写表并存应告警: {out}"
    out = validate_stderr(minimal_fill(gap_html="<!--GAP--><p>档位 A：已检索到具体券商研报假设（妙想+tushare，查询日 2026-10-14），分歧集中在 2026E 净利的出货量假设上，本文基础情景处于一致预期区间内部偏上，证伪时向下修正至一致均值。</p>" + tbl))
    assert "手写券商态度变化表" not in out, f"无 gap_history 不应告警: {out}"
    plain = ('<table><tr><th>维度</th><th>分歧</th></tr><tr><td>量</td><td>未披露</td></tr></table>'
             '<span class="source">数据来源：E5</span>')
    out = validate_stderr(minimal_fill(
        gap_history={"rows": rows}, gap_html="<!--GAP--><p>档位 A：已检索到具体券商研报假设（妙想+tushare，查询日 2026-10-14），分歧集中在 2026E 净利的出货量假设上，本文基础情景处于一致预期区间内部偏上，证伪时向下修正至一致均值。</p>" + plain))
    assert "手写券商态度变化表" not in out, f"无关表不应误伤: {out}"


# ---------------- v5.7.3 来源注根治：最终 HTML 内部黑话硬门禁 ----------------
# 读者可见来源注（class token 含 source 的 span）禁用内部实现名。测试侧硬编码本清单，
# 与实现侧（charts_base）各自独立维护——防实现正则退化时测试同步失明（假绿）。
_SRC_BANNED = (
    "脚本按", "字段生成", "照抄行", "em_fetch", "extract_review",
    "period_track", "segments", "growth_plot", "fin_trend", "industry_chain",
    "holders", "gap_plot", "gap_history", "pe_history", "price_history",
    "valuation_inputs", "peers_plot", "sensitivity", "triggers", "prev.scenarios",
)


_SRC_BANNED_E = re.compile(r"(?<![A-Za-z0-9])E[1-6](?![0-9A-Za-z])")  # E1-E6 内部数据源编号


def _source_spans(html):
    """抽取最终 HTML 全部 class token 含 source 的 <span>：[(class 属性值, 剥标签+unescape 纯文本)]。
    深度感知配对 </span>——嵌套 span 不截断尾巴（非贪婪正则会在内层 </span> 提前收口，
    给黑话留逃逸口）；class 属性大小写不敏感、单/双引号/无引号（HTML5 合法）均可；
    注释对读者不可见，扫描副本剔除 <!--...-->。与实现侧 render_report._iter_source_spans
    各自独立编写，防同源退化假绿。"""
    out = []
    scan = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    for m in re.finditer(r'<span\b[^>]*?\bclass\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))[^>]*>',
                         scan, flags=re.I):
        classes = (m.group(1) or m.group(2) or m.group(3) or "").split()
        if "source" not in [c.lower() for c in classes]:
            continue
        depth = 1
        for t in re.finditer(r'<span\b[^>]*>|</span\s*>', scan[m.end():], flags=re.I):
            depth += 1 if not t.group(0).startswith("</") else -1
            if depth == 0:
                inner = scan[m.end():m.end() + t.start()]
                out.append((" ".join(classes),
                            _html_unescape(re.sub(r"<[^>]+>", "", inner))))
                break
    return out


def test_final_html_source_caption_gate():
    """v5.7.3：最终 HTML 所有 .source 来源注不得含内部实现名（脚本按/em_fetch/E1-E6/
    fill 字段名等）；脚本生成图注（.chart-source）必须含非空「数据来源：」真实来源。
    防线在 _fill_template 之后——validate_content 在图表注入前执行，看不到脚本图注，
    只有最终 HTML 能同时罩住脚本注入图注与手写 HTML 片段。"""
    for name, fill in (("period_h1", period_fill("h1")), ("full_fill", full_fill())):
        html = render_fill(fill, name=f"_fill_srcgate_{name}.json")
        spans = _source_spans(html)
        assert spans, f"{name}：最终 HTML 应含 .source 来源注"
        for classes, text in spans:
            for w in _SRC_BANNED:
                assert w not in text, f"{name} 来源注含内部实现名「{w}」：{text[:80]}"
            assert not _SRC_BANNED_E.search(text), \
                f"{name} 来源注含内部数据源编号 E1-E6：{text[:80]}"
            if "chart-source" in classes.split():
                m = re.search(r"数据来源：([^；;）)]*)", text)
                assert m and re.search(r"\w", m.group(1)), \
                    f"{name} 脚本图注缺非空「数据来源：」真实来源：{text[:80]}"
    # 测试侧抽取器自证：嵌套 span 的 .source 必须取到配对 </span> 前的完整文本（含尾巴），
    # 不被内层 </span> 截断
    html_n = render_fill(minimal_fill(
        p0_html='<p>关键驱动分析。</p>'
                '<span class="source">数据来源：测试 <span>补充</span> 尾巴可见</span>'),
        name="_fill_srcnest.json")
    assert any("尾巴可见" in t for _c, t in _source_spans(html_n)), \
        "嵌套 span 的来源注尾巴必须完整抽取"


def test_final_html_source_gate_rejects_jargon():
    """v5.7.3 负向：手写 HTML 片段塞内部黑话 .source → 渲染必须拒绝并点名命中词与片段；
    手写 .chart-source 缺非空「数据来源：」→ 同样拒绝。"""
    bad = minimal_fill(p0_html='<p>关键驱动分析。</p>'
                               '<span class="source">脚本按 demo 字段生成</span>')
    try:
        render_fill(bad, name="_fill_srcneg1.json")
    except ValueError as e:
        assert "内部实现名" in str(e) and "脚本按" in str(e), \
            f"报错应点名命中词与片段: {e}"
    else:
        raise AssertionError("手写片段含内部黑话 .source，渲染未被拒绝")
    bad2 = minimal_fill(p0_html='<p>关键驱动分析。</p>'
                                '<span class="source chart-source">测试图（公司年报数据整理）</span>')
    try:
        render_fill(bad2, name="_fill_srcneg2.json")
    except ValueError as e:
        assert "数据来源：" in str(e), f"chart-source 缺「数据来源：」应拒: {e}"
    else:
        raise AssertionError("chart-source 缺非空「数据来源：」，渲染未被拒绝")


def test_chart_source_helper_selfcheck():
    """v5.7.3 复核修复①③：_chart_source 空/空白来源必须 ValueError（空壳「数据来源：」逃逸）；
    title/source/note 三向禁词自检，命中即拒。"""
    from charts_base import _chart_source
    s = _chart_source("测试图", "公司定期报告", "口径说明")
    assert s == '<span class="source chart-source">测试图（数据来源：公司定期报告）：口径说明</span>', s
    for tag, args in (("空来源", ("测试图", "")),
                      ("空白来源", ("测试图", "   ")),
                      ("None 来源", ("测试图", None)),
                      ("非字符串来源", ("测试图", 123)),
                      ("列表来源", ("测试图", ["公司年报"])),
                      ("标题黑话", ("脚本按 x 生成", "公司年报")),
                      ("来源黑话", ("测试图", "em_fetch E3 年表")),
                      ("口径黑话", ("测试图", "公司年报", "来自 period_track"))):
        try:
            _chart_source(*args)
        except ValueError as e:
            assert "来源" in str(e), f"{tag} 报错文案应含来源说明: {e}"
        else:
            raise AssertionError(f"_chart_source {tag} 未拒：{args}")


def test_final_html_source_gate_evasion():
    """v5.7.3 复核修复②③+追加：门禁绕过八连——空来源壳 / class 单引号 / CLASS 大写 /
    class 无引号（HTML5 合法写法）/ 嵌套 span 尾巴藏黑话 / HTML 实体（em&#95;fetch）/
    大小写（EM_FETCH）/ .source span 未闭合（fail-closed，不静默扫余量）——渲染一律拒；
    Shareholders 类正常词（holders 词边界）与 HTML 注释内黑话（对读者不可见）不误伤。"""
    base = '<p>关键驱动分析。</p>'
    for tag, frag in (
        ("空来源壳", '<span class="source chart-source">测试图（数据来源：）</span>'),
        ("class 单引号", "<span class='source'>脚本按 demo 字段生成</span>"),
        ("CLASS 大写", '<span CLASS="source">脚本按 demo 字段生成</span>'),
        ("class 无引号", '<span class=source>脚本按 demo 字段生成</span>'),
        ("嵌套尾巴", '<span class="source">正常来源 <span>内嵌</span>脚本按 藏尾巴</span>'),
        ("实体绕过", '<span class="source">数据来自 em&#95;fetch 抓取</span>'),
        ("大小写绕过", '<span class="source">数据来自 EM_FETCH 抓取</span>'),
        ("未闭合", '<div><span class="source">脚本按 demo 字段生成'),
    ):
        try:
            render_fill(minimal_fill(p0_html=base + frag), name="_fill_evasion.json")
        except ValueError as e:
            assert "来源注" in str(e) or "数据来源：" in str(e), f"{tag} 报错文案: {e}"
        else:
            raise AssertionError(f"{tag} 绕过未被拒：{frag}")
    ok = minimal_fill(p0_html=base + '<span class="source">Shareholders 户数披露数据</span>')
    assert "Shareholders" in render_fill(ok, name="_fill_evasion_ok.json"), \
        "Shareholders 正常词不应被 holders 禁词误伤"
    commented = minimal_fill(p0_html=base + '<!-- <span class="source">脚本按 demo</span> -->')
    assert "关键驱动分析" in render_fill(commented, name="_fill_evasion_cmt.json"), \
        "HTML 注释内的来源注黑话对读者不可见，不应触发门禁"


def test_final_html_source_gate_banned_words_exhaustive():
    """v5.7.3 复核③：禁词表退化假绿防线——最终渲染负向参数化遍历测试侧完整 _SRC_BANNED
    （20 词）+ E1/E6 边界代表，逐个放进 .source 走真实 render_fill，每个都必须 ValueError。
    测试侧清单独立硬编码（上方 _SRC_BANNED），与实现侧 charts_base._SOURCE_BANNED_RE 互不同源。"""
    for w in _SRC_BANNED + ("E1", "E6"):
        frag = f'<span class="source">数据来源标注 {w} 测试</span>'
        try:
            render_fill(minimal_fill(p0_html='<p>关键驱动分析。</p>' + frag),
                        name="_fill_banned.json")
        except ValueError as e:
            assert "来源注释含内部实现名" in str(e), f"「{w}」报错文案不符: {e}"
        else:
            raise AssertionError(f"禁词「{w}」放进 .source 渲染未被拒——禁词表疑似退化")


def test_gap_history_prose_dupe():
    """v5.8.0：gap_history 图会生成时，gap_html 散文罗列对比数字（≥2 组「数值→数值亿」+
    上/下调表述）→ 告警（中国巨石复盘佐证段实证）；无 gap_history / 纯结论句 → 不告警。
    v5.9.0：告警文案「首末数字」→「对比数字」（口径重构；「首末」语境词仍留作手写旧措辞防线）。"""
    rows = [{"org": "中金公司", "yr": "2026", "d_from": "2026-06-30", "d_to": "2026-09-28",
             "np_from": 930.0, "np_to": 952.0}]
    head = ("<!--GAP--><p>档位 A：已检索到具体券商研报假设（妙想+tushare，查询日 2026-10-14），"
            "分歧集中在 2026E 净利的出货量假设上，本文基础情景处于一致预期区间内部偏上，"
            "证伪时向下修正至一致均值。</p>")
    prose = ("<p><strong>券商态度变化佐证：</strong>近180天同一券商首末研报对比，全线上调——"
             "东吴57.6→82.3亿（05-10→08-24）、国投59.8→84.0亿、长江63.1→84.7亿——"
             "市场自己在向乐观方向修正。</p>")
    out = validate_stderr(minimal_fill(gap_history={"rows": rows}, gap_html=head + prose))
    assert "散文罗列券商对比数字" in out, f"散文罗列应告警: {out}"
    out = validate_stderr(minimal_fill(gap_html=head + prose))
    assert "散文罗列券商对比数字" not in out, f"无 gap_history 不应告警: {out}"
    clean = "<p>佐证：市场在向乐观方向修正，本文谨慎是对价格外推的结构性保留。</p>"
    out = validate_stderr(minimal_fill(gap_history={"rows": rows}, gap_html=head + clean))
    assert "散文罗列券商对比数字" not in out, f"纯结论句不应误伤: {out}"
    # v5.8.1 审核实证：A 档假设分行列写（无 首末/态度变化/佐证 语境词）不应误伤
    assume = ("<ul><li>净利——东吴（05-10）：57.6→82.3亿（上调）；国投（06-02）："
              "59.8→84.0亿（上调）</li></ul>")
    out = validate_stderr(minimal_fill(gap_history={"rows": rows}, gap_html=head + assume))
    assert "散文罗列券商对比数字" not in out, f"A 档假设列写不应误伤: {out}"


def test_gh_sort_key_single_source():
    """v5.8.2：validate 漏抄判定的排序键与渲染端同源——validate 直接 import
    charts_gap._gh_sort_key（v5.8.1 的内联复制已删，渲染端排序策略再变时校验端跟随）。"""
    import charts_gap
    import validate
    assert validate._gh_sort_key is charts_gap._gh_sort_key, \
        "校验端排序键必须与渲染端是同一函数对象（同源 import，禁内联复制）"


def test_scenario_key_case_insensitive_reconciliation():
    """v5.8.2：情景 key 大小写不敏感对账——大写 "Base" 不再让 gap_plot 净利维度
    ours 对账与 growth_consistency 对账静默跳过（存量 fill 合法：_archive 旧档可含大写 key）。"""
    # ① gap_plot「净利」维度 ours 对账：base key 大写、profit=100、ours=50（偏差>2%）→ 应告警
    f = minimal_fill()
    for s in f["valuation"]["scenarios"]:
        if s["key"] == "base":
            s["key"] = "Base"
    f["gap_plot"] = {"dims": [{"name": "2027E 净利", "ours": 50, "consensus": 52}]}
    out = validate_stderr(f)
    assert "ours" in out and "基础情景净利" in out, f"大写 Base key 不应对账静默: {out}"
    # 对照：小写 key 同样告警（口径一致，排除恒真）
    for s in f["valuation"]["scenarios"]:
        if s["key"] == "Base":
            s["key"] = "base"
    out = validate_stderr(f)
    assert "ours" in out and "基础情景净利" in out, f"小写 base key 应告警: {out}"
    # ours 与 base.profit 一致 → 不告警（告警确实由对账触发，非恒真）
    f["gap_plot"] = {"dims": [{"name": "2027E 净利", "ours": 100, "consensus": 102}]}
    for s in f["valuation"]["scenarios"]:
        if s["key"] == "base":
            s["key"] = "Base"
    out = validate_stderr(f)
    assert "基础情景净利" not in out, f"一致不应告警: {out}"

    # ② growth_consistency：base key 大写、profit=100 vs 归母净利基数 100 → 换算增速 0%，
    # 越出 fcst 区间 [5,10]±2pct → 应告警「基础情景换算增速」（修复前精确匹配静默跳过）；
    # np_consensus=20 与落盘换算增速 20% 对齐（np_avg 120÷100−1），排除 np_consensus 告警干扰
    f2 = minimal_fill()
    for s in f2["valuation"]["scenarios"]:
        if s["key"] == "base":
            s["key"] = "Base"
    for p in f2["fin_trend"]["panels"]:
        for b in p.get("bars") or []:
            if b.get("name") == "归母净利":
                b["values"][-1] = 100          # 末年 93→100：g_base=100/100−1=0%，越出 [5,10]±2
    f2["growth_plot"] = {"hist": [
        {"y": "2022", "rev": 10.0, "np": 12.5},
        {"y": "2023", "rev": 9.1, "np": 11.1},
        {"y": "2024", "rev": 4.2, "np": 5.0},
        {"y": "2025", "rev": 4.0, "np": 4.8}],
        "fcst": [{"y": "2026E", "np_lo": 5, "np_hi": 10, "np_consensus": 20}]}
    with tempfile.TemporaryDirectory() as d:
        ref = write_fill({"price": 10.0, "pe_ttm": 11.0,
                          "consensus_np": {"np_avg": 120, "year": 2026}}, d, name="em_cnp.json")
        f2["quote"] = {"source_file": ref, "date": "2026-10-21"}
        out = validate_stderr(f2)
    assert "基础情景换算增速" in out, f"大写 Base key 不应对账静默: {out}"
