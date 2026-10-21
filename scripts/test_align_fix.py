#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_align_fix.py — fix_table_alignment 对齐机回归（无网络；pytest 唯一入口，无 __main__ 直跑契约）

覆盖 num/center 类修复、cell-best/cell-worst 高亮类存活、平票判左、prose 整列判左、
短占位格豁免、th rowspan 重建登记。
v5.8.2 自 test_render_charts.py 归位独立成域（纯搬迁：断言逐字沿用，print 噪音已清）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import render_report as R
from conftest import minimal_fill, render_fill

def test_table_alignment_keeps_highlight_class():
    """v4.9.1：fix_table_alignment 只动 num/center，td 上的 cell-best/cell-worst 高亮类存活。"""
    html = R.fix_table_alignment(
        '<table><tr><th>公司</th><th>PE(TTM)</th><th>ROE</th></tr>'
        '<tr><td style="color:#4a6fa5;font-weight:700;">测试股份</td><td class="cell-best">11</td>'
        '<td>14%</td></tr>'
        '<tr><td>同业甲</td><td class="cell-worst">25</td><td>9%</td></tr></table>')
    assert "cell-best num" in html, "数字列应追加 num 且保留 cell-best"
    assert "cell-worst num" in html, "数字列应追加 num 且保留 cell-worst"


def test_scenario_table_alignment_fixed():
    """v4.10：三情景表触发条件行随列右对齐（工行触发行不一致实证）——表头/时间维度/触发条件
    全部 num 类；scenario-table 豁免 fix_table_alignment（长文本触发的长文剥类不再介入）。"""
    html = render_fill(minimal_fill())
    assert '<th class="num">悲观情景</th>' in html, "情景列表头应 num 右对齐"
    assert '<td class="num">下行</td>' in html, "触发条件行应随列 num"
    assert '<td class="num">12个月</td>' in html, "时间维度行应随列 num"
    long_trig = "NIM 降至 1.22%、信用成本升至 0.65% 的长触发条件文本"
    html2 = R.fix_table_alignment(
        f'<table class="scenario-table"><tr><th>指标</th><th class="num">悲观情景</th></tr>'
        f'<tr><td>触发条件</td><td class="num">{long_trig}</td></tr></table>')
    assert f'<td class="num">{long_trig}</td>' in html2, "scenario-table 应豁免长文剥类"


def test_fix_alignment_tie_goes_left():
    """v4.10：fix_table_alignment 平票判左——文本为主的表整表左对齐不再锯齿
    （工行 09-11 预期差表「净息差判断」行实证）；数字占多数的列仍右对齐。"""
    tbl = ('<table><thead><tr><th>维度</th><th>中金</th><th>光大</th></tr></thead><tbody>'
           '<tr><td>净利</td><td>基本不变</td><td>3,757 亿</td></tr>'
           '<tr><td>息差判断</td><td>息差企稳</td><td>负债成本降幅趋缓</td></tr>'
           '<tr><td>评级</td><td>跑赢行业</td><td>买入</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert 'class="num"' not in html, "文本为主应整表左对齐"
    tbl3 = ('<table><thead><tr><th>维度</th><th>卖方</th></tr></thead><tbody>'
            '<tr><td>2026E 净利</td><td>3,757 亿</td></tr>'
            '<tr><td>增速</td><td>+2.7%</td></tr>'
            '<tr><td>息差判断</td><td>负债成本降幅趋缓</td></tr>'
            '<tr><td>评级</td><td>买入</td></tr></tbody></table>')
    html3 = R.fix_table_alignment(tbl3)
    assert '<th class="num">卖方</th>' not in html3, "平票列应判左（表头不加 num）"
    assert '>买入</td>' in html3, "平票列文字格不加 num"
    tbl2 = ('<table><thead><tr><th>公司</th><th>PE</th></tr></thead><tbody>'
            '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
            '<tr><td>丙</td><td>—</td></tr></tbody></table>')
    html2 = R.fix_table_alignment(tbl2)
    assert '<th class="num">PE</th>' in html2, "数字占多数的列仍应右对齐"


def test_fix_alignment_prose_column_goes_left():
    """v4.10.3：列内出现说明文格（_is_prose_cell）→ 整列判左，不再「数字多数决 → 逐格剥类」
    （同列 3 数字右 + 1 长文左的锯齿；香农芯创时机表实证）。无长文格时数字多数仍判右。"""
    tbl = ('<table><thead><tr><th>维度</th><th>说明</th></tr></thead><tbody>'
           '<tr><td>甲</td><td class="num">11</td></tr>'
           '<tr><td>乙</td><td class="num">25</td></tr>'
           '<tr><td>丙</td><td class="num">3,757 亿</td></tr>'
           '<tr><td>丁</td><td>负债成本降幅趋缓，息差企稳</td></tr>'
           '<tr><td>戊</td><td>买入</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert '<th class="num">说明</th>' not in html, "含长文格的列应整列判左"
    assert 'class="num"' not in html, "整列判左后数字格也不再右对齐"
    tbl_num = tbl.replace('<tr><td>丁</td><td>负债成本降幅趋缓，息差企稳</td></tr>', '')
    assert '<th class="num">说明</th>' in R.fix_table_alignment(tbl_num), \
        "无长文格时数字多数仍判右（对照支）"


def test_fix_alignment_short_placeholder_stays_num():
    """v4.10.3 审计收窄：短占位格（未披露/未获取到/不适用/—（上年亏损））不触发整列翻左——
    数字多数列仍判 num（原「超 2 字纯文字」阈值会让存量 66 份报告里 54 份的表被动过）。"""
    tbl = ('<table><thead><tr><th>公司</th><th>PE(TTM)</th></tr></thead><tbody>'
           '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
           '<tr><td>丙</td><td>16</td></tr><tr><td>丁</td><td>18</td></tr>'
           '<tr><td>戊</td><td>21</td></tr>'
           '<tr><td>己</td><td>未披露</td></tr>'
           '<tr><td>庚</td><td>未获取到</td></tr>'
           '<tr><td>辛</td><td>不适用</td></tr></tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert '<th class="num">PE(TTM)</th>' in html, "短占位格不应翻转整列"
    assert 'class="num">未披露' in html and 'class="num">不适用' in html, "占位格随列右对齐"
    tbl2 = ('<table><thead><tr><th>公司</th><th>PE(TTM)</th></tr></thead><tbody>'
            '<tr><td>甲</td><td>11</td></tr><tr><td>乙</td><td>25</td></tr>'
            '<tr><td>丙</td><td>16</td></tr><tr><td>丁</td><td>18</td></tr>'
            '<tr><td>戊</td><td>—（上年亏损）</td></tr></tbody></table>')
    assert '<th class="num">PE(TTM)</th>' in R.fix_table_alignment(tbl2), \
        "「—（上年亏损）」剥括号后 1 字，不翻列"


def test_fix_alignment_th_rowspan_registers():
    """v5.5.2 审计：重建循环 rowspan 登记原先只在 td 分支——<th rowspan="2"> 不占位导致
    其下数据行列位错位一格、num 列首格被剥右对齐；修法登记挪出 td 分支（与投票循环同口径）。"""
    tbl = ('<table><thead>'
           '<tr><th rowspan="2">项目</th><th class="num">本期</th><th class="num">上期</th></tr>'
           '<tr><td class="num">12.5</td><td class="num">10.2</td></tr>'
           '</thead><tbody>'
           '<tr><td>说明文字</td><td class="num">7.5</td><td class="num">6.8</td></tr>'
           '</tbody></table>')
    html = R.fix_table_alignment(tbl)
    assert '<td class="num">12.5</td>' in html, "跨行表头下首数据格应保住 num 右对齐"
    assert '<td class="num">10.2</td>' in html, "次数据格应保住 num 右对齐"
    assert '<th class="num">本期</th>' in html and '<th class="num">上期</th>' in html
