#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_gap.py — 9 市场预期差拆解图族（v5.1.5 自 charts_misc 拆出）：逐机构分布图（A 档）
与 B 档零轴偏离哑铃（build_gap_plot + _gap_plot_a/_gap_plot_b）、gap-notes 附注
（_gap_notes_html）与锚点注入（_inject_gap_chart）；轴线件 _gap_axis（v5.8.2 起复用基座
_pad_domain/_ticks 的 open_interval 口径，网格吸附专属逻辑仍在此）与 _gap_fmt/_px；
_gap_ticks 为基座 _open_ticks 别名。依赖 charts_base 与 scoring。"""

import math
import os
import re

from scoring import _num, _fmt, _esc
from charts_base import *

# ════════════════════ 8 市场预期差拆解 · 逐机构分布图 / B 档哑铃 ════════════════════

_GAP_CIRCLED = "①②③④⑤⑥"   # 行号（图行 / gap-notes 附注 / 图例共用一套编号）


def _px(v) -> str:
    """坐标格式化：保留 1 位小数、整数去尾（386.7 / 520），与 demo 定稿的写法一致。"""
    s = f"{float(v):.1f}"
    return s[:-2] if s.endswith(".0") else s


def _gap_fmt(v, pt: bool = False) -> str:
    """gap 图数值标签：比率型维度（pct_pt）保底一位小数（24 → 24.0），其余 %g 去尾零；
    非比率大数值（|v| ≥ 10000，如出货量原生单位）改千分位整数，防 %g 科学计数法上轴
    （审计 P2-3：_fmt(1234567)='1.23457e+06'）。"""
    s = f"{v:,.0f}" if not pt and abs(v) >= 10000 else _fmt(v)
    return s + ".0" if pt and "." not in s else s


def _gap_axis(lo0: float, hi0: float):
    """A 档行轴定域（v5.8.2 收编：垫域复用基座 _pad_domain、步长/开区间刻度复用 _ticks 的
    open_interval 口径——语义等价性由 artifacts/_v582 对照脚本的定域枚举逐项断言）：
    数据 ±10% 垫域（数据齐平时按 |hi0|×10% 与 1 取大）；步长取 {1,2,3,5}×10^k 中域内
    刻度 ≤5 个的最小档；域边就近吸到 step/4 量级网格（step 为 3/5×10^k 时网格取 10^k），
    随后保证数据点不贴边。返回 (lo, hi, step)。"""
    lo_p, hi_p = _pad_domain(lo0, hi0, 0.1, zero=max(abs(hi0) * 0.1, 1))
    _t, step = _ticks(lo_p, hi_p, 5, mults=(1, 2, 3, 5), open_interval=True, ret_step=True)
    # step 即 m×10^k 同表达式生成，按位等值反查吸附网格 mag（除法反推有浮点尾差风险）
    mag = None
    for m in (1, 2, 3, 5):
        for k in range(-20, 21):
            if m * 10.0 ** k == step:
                mag = {1: 0.25, 2: 0.5, 3: 1.0, 5: 1.0}[m] * 10.0 ** k
                break
        if mag is not None:
            break
    lo = math.floor(lo_p / mag + 0.5 + 1e-9) * mag
    hi = math.floor(hi_p / mag + 0.5 + 1e-9) * mag
    while lo >= lo0:   # 就近吸网格后仍须包住数据（点不落域边）
        lo -= mag
    while hi <= hi0:
        hi += mag
    return round(lo, 9), round(hi, 9), step


# v5.8.2：开区间刻度生成单源到基座 _open_ticks，此处仅保留模块内惯用名
_gap_ticks = _open_ticks


def build_gap_plot(fill: dict) -> str:
    """09 市场预期差拆解图（fill["gap_plot"] 可选字段，缺失/有效维度 <2 → 返回空串不告警，同 holders 惯例）。

    A 档（dims 带 street 逐机构明细）= 横向分布定位：一个点=一家机构近 180 天最新预测
    （灰=其他机构不标名 / 橙=major 头部外资标名 / 蓝=本文白描边压轴 / 黑◆=一致预期均值），
    右列=本文相对一致偏离 %（脚本算 ours/consensus−1）；street 整体缺失 → B 档偏离哑铃
    （灰点=卖方一致固定零轴，蓝点=本文，棒长∝相对偏离，定域 -10%~+15%）；部分行缺 street →
    仍按 A 档渲染，该行只画 本文/◆ 两点（行级退化）。
    dims: [{"name","ours","consensus","cover"?,"pct_pt"?,"reverse"?,"note"?,
            "street"?=[{"org"?,"v","major"?}]}]，name/ours/consensus 必填，consensus ≤0 的行剔除；
    cover 可省（默认按 street 家数「N 家覆盖」，无明细行「未见逐机构明细」）；pct_pt=比率型维度
    （数值保底一位小数，B 档行注追加原生 pct 点差）；reverse=反推口径维度（B 档行注/图源标注）。
    行数 2–6（超出取前 6）。
    防叠三层：① 与本文过近（<12px）的灰点钉轴，本文点白描边压轴压盖；② 灰点间距 <12px →
    一上一下对称泳道错位（±9px，簇起始向按值哈希，确定性）；③ 同值灰点合并为大点。
    ◆ 标签落位阶梯：轴下左 → 轴下右 → 省略与 ◆ 过近（≤30px）的刻度（等值刻度由 ◆ 标签承载）。"""
    gp = fill.get("gap_plot") or {}
    dims = []
    for d in gp.get("dims") or []:
        if not _gap_dim_ok(d):   # 行有效性唯一定义（charts_base，v5.1.2 起附注/校验同源）
            continue
        name = str(d.get("name") or "").strip()
        ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
        street = []
        for s in d.get("street") or []:
            if not isinstance(s, dict):
                continue
            v = _num(s.get("v"))
            if v is None:
                continue
            org = str(s.get("org") or "").strip()
            street.append({"v": v, "org": org, "major": bool(s.get("major")) and bool(org)})
        dims.append({"name": name, "ours": ours, "cons": cons, "street": street,
                     "cover": str(d.get("cover") or "").strip(),
                     "pt": bool(d.get("pct_pt")), "rev": bool(d.get("reverse"))})
    if len(dims) < 2:
        return ""
    dims = dims[:6]
    if any(d["street"] for d in dims):
        # P2（v5.5.1）：图注只显示基名——fill 若写绝对路径，原样嵌入会随报告外露本地路径
        src = str(gp.get("source_file") or "").strip()
        return _gap_plot_a(dims, os.path.basename(src) if src else "")
    return _gap_plot_b(dims)


def _gap_plot_a(dims: list, src_note: str = "") -> str:
    """A 档主形态：逐机构横向分布定位（demo v3 定稿版式：轴 x∈[280,840]、行距 70、右列 x=880）。
    src_note 非空（fill 的 gap_plot.source_file 基名）= 港股调研落盘源，图下来源注注明
    调研纪要落盘核对（v5.5.1；v5.7.3 起不再外露本地文件名与内部数据源编号）。"""
    n = len(dims)
    # 布局常数（v5.8.3 收拢：原散落于函数体各字面量，版式照 demo v3 定稿不动）：
    # W=画布宽、TOP=顶缘留白、ROW=行距（行基线=ROW+ROW*i）、X0/X1=行轴域、
    # LX=行标签列（右对齐）、RX=右列（本文相对一致偏离%）
    W, TOP, ROW, X0, X1, LX, RX = 1000, 30, 70, 280, 840, 240, 880
    parts = ['<span class="section-tag">卖方分布 vs 本文假设 · 逐机构定位</span>',
             _svg_open(W, TOP + ROW * n, "市场预期差机构分布图")]
    # 图例行（v5.8.2 收敛为 _legend_row glyph 数据列表：圆点/菱形/纯文字项；起点 57、
    # xround=True，坐标与间距逐项反推自定稿手写值；行末「本文 vs 一致」为右列头，保留手写）
    nums = "".join(_GAP_CIRCLED[i] for i in range(n))
    _legend_row(parts, [
        ("其他机构预测", {"k": "dot", "r": 5, "cx": 5, "fill": _C_SAND, "dx": 16, "gap": 41}),
        ("头部/外资机构（标名称）", {"k": "dot", "r": 5.5, "fill": _C_ORANGE, "dx": 12, "gap": 43.84}),
        ("本文假设", {"k": "dot", "r": 7, "fill": _C_BLUE, "stroke": _C_PAPER, "sw2": 2,
                      "dx": 13, "gap": 55}),
        ("一致预期（券商均值）", {"k": "diamond", "r": 6, "fill": _C_BLACK, "dx": 19, "gap": 7}),
        (f"行号 {nums} 对应图下附注 · 右列=本文相对一致偏离", {"k": "none", "dx": 0}),
    ], 57, xround=True, ty=16)
    parts.append(f'<text x="{RX}" y="32" font-size="11" fill="{_C_LABEL}">本文 vs 一致</text>')
    for i, d in enumerate(dims):
        ay = ROW + ROW * i
        pt = d["pt"]
        vals = [s["v"] for s in d["street"]] + [d["ours"], d["cons"]]
        lo, hi, step = _gap_axis(min(vals), max(vals))
        X = _lin_map(lo, hi, X0, X1)
        xc, x_ours = X(d["cons"]), X(d["ours"])
        parts.append(f'<text x="{LX}" y="{ay - 26}" text-anchor="end" font-size="12.5" font-weight="600" '
                     f'fill="{_C_INK}">{_GAP_CIRCLED[i]} {_esc(d["name"])}</text>')
        cover = d["cover"] or (f'{len(d["street"])} 家覆盖' if d["street"] else "未见逐机构明细")
        if i == 0:
            cover += " · 近 180 天研报"
        parts.append(f'<text x="{LX}" y="{ay - 12}" text-anchor="end" font-size="10.5" '
                     f'fill="{_C_LABEL}">{_esc(cover)}</text>')
        parts.append(f'<line x1="{X0}" y1="{ay}" x2="{X1}" y2="{ay}" stroke="{_C_AXIS}" stroke-width="1.2"/>')
        # 刻度：先省略与 ◆ 过近（≤30px）者（等值刻度由 ◆ 标签承载）
        ticks = [t for t in _gap_ticks(lo, hi, step) if abs(X(t) - xc) > 30]

        def _tick_rect(t):
            tw = _text_w(_gap_fmt(t, pt), 10.5)
            return X(t) - tw / 2, X(t) + tw / 2

        def _hit(rect):
            return any(rect[0] < tr[1] and tr[0] < rect[1] for tr in map(_tick_rect, ticks))

        # ◆ 标签落位阶梯：轴下左 → 轴下右 → 两侧皆撞则省略冲突刻度回轴下左
        cons_label = f"一致 {_gap_fmt(d['cons'], pt)}"
        lw = _text_w(cons_label, 10.5)
        left_rect = (xc - 12 - lw, xc - 12)
        if not _hit(left_rect):
            cons_anchor, cons_x = "end", xc - 12
        elif not _hit((xc + 10, xc + 10 + lw)):
            cons_anchor, cons_x = "start", xc + 10
        else:
            ticks = [t for t in ticks
                     if not (left_rect[0] < _tick_rect(t)[1] and _tick_rect(t)[0] < left_rect[1])]
            cons_anchor, cons_x = "end", xc - 12
        for t in ticks:
            parts.append(f'<text x="{_px(X(t))}" y="{ay + 16}" text-anchor="middle" font-size="10.5" '
                         f'fill="{_C_LABEL}">{_gap_fmt(t, pt)}</text>')
        # 灰点：同值合并大点 → 防叠①钉轴 / ②泳道错位
        groups = []
        for v in sorted(s["v"] for s in d["street"] if not s["major"]):
            if groups and v == groups[-1][0]:
                groups[-1][1] += 1
            else:
                groups.append([v, 1])
        lanes = [0.0] * len(groups)
        j = 0
        while j < len(groups):   # 相邻间距 <12px 的点连成簇；簇内非钉轴点 ≥2 才一上一下错位
            k = j + 1
            while k < len(groups) and X(groups[k][0]) - X(groups[k - 1][0]) < 12:
                k += 1
            free = [m for m in range(j, k) if abs(X(groups[m][0]) - x_ours) >= 12]
            if len(free) >= 2:
                dir0 = 1 if int(round(abs(groups[free[0]][0]) * 1000)) % 2 == 0 else -1
                for idx, m in enumerate(free):
                    lanes[m] = dir0 * (9 if idx % 2 == 0 else -9)
            j = k
        for (v, cnt), lane in zip(groups, lanes):
            r = 4.5 if cnt == 1 else min(4.5 + 1.5 * (cnt - 1), 7.5)
            parts.append(f'<circle cx="{_px(X(v))}" cy="{_px(ay + lane)}" r="{_px(r)}" fill="{_C_SAND}"/>')
        # 橙点（major 头部/外资）+ 具名标签；标签同行碰撞时移高一档（-16 → -24）；
        # 审计 P1-1/P1-2：lvl1 标签同样入册，且 lvl1（ay-24）与本文标签（ay-30）纵向带相交、
        # 跨带查 x 交叠；两档皆撞 → 标签降级为仅机构名（点永不删，定稿纪律）
        ours_label = f"本文 {_gap_fmt(d['ours'], pt)}"
        ours_rect = (x_ours - _text_w(ours_label, 11.5) / 2, x_ours + _text_w(ours_label, 11.5) / 2)
        bands = {0: [], 1: []}

        def _free(rect, lvl):
            pool = bands[lvl] + ([ours_rect] if lvl == 1 else [])
            return not any(rect[0] < b1 and b0 < rect[1] for b0, b1 in pool)

        for s in sorted((s for s in d["street"] if s["major"]), key=lambda s: s["v"]):
            x = X(s["v"])
            label = f'{s["org"]} {_gap_fmt(s["v"], pt)}'
            w = _text_w(label, 10.5)
            rect = (x - w / 2, x + w / 2)
            lvl = 0 if _free(rect, 0) else 1
            if lvl == 1 and not _free(rect, 1):
                label = s["org"]   # 降级仅机构名
                w = _text_w(label, 10.5)
                rect = (x - w / 2, x + w / 2)
                if not _free(rect, 1) and _free(rect, 0):
                    lvl = 0
            bands[lvl].append(rect)
            parts.append(f'<circle cx="{_px(x)}" cy="{ay}" r="5.5" fill="{_C_ORANGE}"/>'
                         f'<text x="{_px(x)}" y="{ay - (24 if lvl else 16)}" text-anchor="middle" '
                         f'font-size="10.5" font-weight="600" fill="{_C_BADGE_DEEP["badge-orange"]}">'
                         f'{_esc(label)}</text>')
        # 本文点压轴绘制（白描边压盖近点）+ ◆ 一致预期
        parts.append(f'<circle cx="{_px(x_ours)}" cy="{ay}" r="7.5" fill="{_C_BLUE}" '
                     f'stroke="{_C_PAPER}" stroke-width="2"/>'
                     f'<text x="{_px(x_ours)}" y="{ay - 30}" text-anchor="middle" font-size="11.5" '
                     f'font-weight="700" fill="{_C_BLUE}">本文 {_gap_fmt(d["ours"], pt)}</text>')
        parts.append(f'<polygon points="{_px(xc)},{_px(ay - 6.5)} {_px(xc + 6)},{ay} '
                     f'{_px(xc)},{_px(ay + 6.5)} {_px(xc - 6)},{ay}" fill="{_C_BLACK}"/>')
        anchor_attr = f' text-anchor="{cons_anchor}"' if cons_anchor == "end" else ""
        parts.append(f'<text x="{_px(cons_x)}" y="{ay + 22}"{anchor_attr} font-size="10.5" '
                     f'fill="{_C_STONE}">{_esc(cons_label)}</text>')
        pct = (d["ours"] / d["cons"] - 1) * 100
        parts.append(f'<text x="{RX}" y="{_px(ay + 4.5)}" font-size="13" font-weight="700" '
                     f'fill="{_C_INK}">{pct:+.1f}%</text>')
    parts.append(_svg_close())
    parts.append(_chart_source(
        "机构分布定位图",
        ('人工调研纪要（落盘核对）' if src_note else '券商研报明细与一致预期汇总')
        + '，近 180 天研报、同机构多份取最新',
        '一个点=一家机构近 180 天研报预测；'
        '沙=其他机构、橙=头部/外资（标名称）、蓝=本文、'
        '◆=一致预期均值；各维度独立原生单位轴，行内比较有效、跨行比偏离看右列；'
        '近点处理=本文点白描边压轴压盖（值接近时灰点露月牙）、灰点间对称泳道错位，'
        '◆ 标签与刻度冲突时右移或省略等值刻度'))
    return "".join(parts)


def _gap_plot_b(dims: list) -> str:
    """B 档兜底形态：零轴偏离哑铃（street 整体缺失时）——灰点=卖方一致预期（固定零轴），蓝点=本文，
    棒长∝相对偏离 %（定域 -10%~+15%，跨行可比）；reverse 维度行注/图源标「反推」口径。"""
    n = len(dims)
    # 布局常数（v5.8.3 收拢：原散落于函数体各字面量）：W=画布宽、ROW=行距、ROW0=行起点、
    # BOT=底缘留白、DOM=定域（%，截断同此）、X0/X1=轴域、TY=网格顶 y、LG=图例起点 x、
    # LX=行标签列（右对齐）、RX=右列（相对偏离%）
    W, ROW, ROW0, BOT, DOM = 1000, 62, 71, 38, (-10, 15)
    X0, X1, TY, LG, LX, RX = 290, 850, 30, 62, 255, 872
    y2 = ROW * n + BOT
    X = _lin_map(DOM[0], DOM[1], X0, X1)
    zx = X(0)
    has_rev = any(d["rev"] for d in dims)
    # 审计 P1-3：tag 的「（反推口径）」只在确有 reverse 行时输出（纯 B 档不误标）
    tag = "卖方一致预期 vs 本文假设 · 偏离拆解（反推口径）" if has_rev \
        else "卖方一致预期 vs 本文假设 · 偏离拆解"
    parts = [f'<span class="section-tag">{tag}</span>',
             _svg_open(W, y2 + 26, "市场预期差哑铃图（B 档）")]
    # 图例行（v5.8.2 收敛为 _legend_row glyph 数据列表，间距按手写坐标反推；末项为纯文字说明）
    _legend_row(parts, [
        ("卖方一致预期（零轴）", {"k": "dot", "r": 6, "fill": _C_SAND, "dx": 12, "gap": 38}),
        ("本文假设", {"k": "dot", "r": 7, "fill": _C_BLUE, "stroke": _C_PAPER, "sw2": 2,
                      "dx": 13, "gap": 51}),
        ("蓝点偏右=本文高于卖方，偏左=低于；棒长 ∝ 相对偏离幅度，跨行可比", {"k": "none", "dx": 0}),
    ], LG, xround=True, ty=16)
    # 定域网格刻度（v5.8.2 收编 _vgrid_ticks；预格式 -10% 等经 (值, 文本) 元组传入）；
    # 零轴线是 AXIS 色 700 字重的轴件（非网格），保留手写
    _vgrid_ticks(parts, X, ((-10, "-10%"), (-5, "-5%"), (5, "+5%"), (10, "+10%"), (15, "+15%")),
                 TY, y2, y2 + 16, xfmt=_px)
    parts.append(f'<line x1="{_px(zx)}" y1="{TY}" x2="{_px(zx)}" y2="{y2}" stroke="{_C_AXIS}" stroke-width="1.6"/>'
                 f'<text x="{_px(zx)}" y="{y2 + 16}" text-anchor="middle" font-size="11" font-weight="700" '
                 f'fill="{_C_STONE}">0</text>')
    parts.append(f'<text x="{RX}" y="34" font-size="11" fill="{_C_LABEL}">相对偏离</text>')
    clamped_any = False
    for i, d in enumerate(dims):
        cy = ROW0 + ROW * i
        pt = d["pt"]
        pct = (d["ours"] / d["cons"] - 1) * 100
        # 审计 P2-1：偏离超出定域（-10%~+15%）时点位被夹在边界——虚线棒+空心点作截断记号，
        # 数值仍以右列为准（点位视觉不得撒谎）
        clamped = pct < DOM[0] or pct > DOM[1]
        if clamped:
            clamped_any = True
        suffix = "%" if pt else ""
        parts.append(f'<text x="{LX}" y="{cy - 8}" text-anchor="end" font-size="12.5" font-weight="600" '
                     f'fill="{_C_INK}">{_GAP_CIRCLED[i]} {_esc(d["name"])}</text>')
        extra = []
        if pt:
            extra.append(f'{d["ours"] - d["cons"]:+g}pct')
        if d["rev"]:
            extra.append("反推")
        note = (f'卖方 {_gap_fmt(d["cons"], pt)}{suffix} → 本文 {_gap_fmt(d["ours"], pt)}{suffix}'
                + (f'（{"，".join(extra)}）' if extra else ""))
        parts.append(f'<text x="{LX}" y="{cy + 8}" text-anchor="end" font-size="10.5" '
                     f'fill="{_C_LABEL}">{_esc(note)}</text>')
        dx = X(max(DOM[0], min(DOM[1], round(pct, 1))))   # 定位与右列显示同值（所见即所量）
        dash = ' stroke-dasharray="4 3"' if clamped else ""
        parts.append(_arrow_dumbbell(zx, dx, cy, _C_BLUE, _px, dash=dash, hollow=clamped))
        parts.append(f'<text x="{RX}" y="{_px(cy + 4.5)}" font-size="13" font-weight="700" '
                     f'fill="{_C_INK}">{pct:+.1f}%</text>')
    parts.append(_svg_close())
    note = ('灰点=卖方一致预期（固定零轴），'
            '蓝点=本文；横轴=本文相对卖方偏离 %；比率型维度按相对偏离定位，原生差值（+1.5pct）写进行注')
    rev_nums = "".join(_GAP_CIRCLED[i] for i, d in enumerate(dims) if d["rev"])
    if rev_nums:
        note += f'；{rev_nums} 为反推口径——卖方未披露该维度假设，由一致净利/目标价反推'
    if clamped_any:
        note += '；虚线棒+空心蓝点=偏离超出 -10%~+15% 定域，按右列数值为准'
    parts.append(_chart_source("预期差哑铃图（B 档）", "卖方一致预期与本文假设（本报告整理）", note))
    return "".join(parts)


# ════════════════════ 9 章 · 券商态度变化（同一券商首末两份研报对比，v5.6.0）════════════════════


def _gh_delta(r: dict, kf: str, kt: str):
    """首末变化率（小数）；缺值或基期为 0 → None。"""
    v0, v1 = r.get(kf), r.get(kt)
    if v0 is None or v1 is None or not v0:
        return None
    return v1 / v0 - 1


def _gh_sort_key(r: dict):
    """排序键：np 幅度降序优先、无 np 行按 tp 幅度降序靠后。None（缺值）≠ 0（持平）——
    不能用 `or -9`：0.0 会被吞成 -9，持平行错排到下调行之后（v5.6.0 审核 #1）。"""
    d = _gh_delta(r, "npf", "npt")
    if d is not None:
        return (0, -d)
    d = _gh_delta(r, "tpf", "tpt")
    return (1, -(d if d is not None else -9))


def _gh_org_key(org: str) -> str:
    """机构名归一化（v5.8.1）：tushare org_name 存在「中金/中金公司」口径漂移，
    rows 与 tp_reports 同机构名可能不一致——去尾部公司后缀后比对（宁德 300750 复盘
    实证：归一前降级面板单点落行外补列）。括号注（如 (香港)）保留，区分境内外主体。"""
    s = org.strip()
    for suf in ("证券股份有限公司", "股份有限公司", "有限责任公司", "有限公司", "公司", "证券"):
        if s.endswith(suf):
            s = s[:-len(suf)]
            break
    return s


def _flat_ring(cx, cy) -> str:
    """「沙点+钢蓝环=持平」记号单源（v5.8.2：图例 ring glyph 与 _dumbbell 持平行此前
    在图例/_dumbbell 各手写一遍，收敛为本 helper 供 _dumbbell，图例走 _legend_row 同参数 ring）。
    坐标经 _px 去尾零（int 坐标原样输出，与手写逐字节一致）。"""
    return (f'<circle cx="{_px(cx)}" cy="{cy}" r="4" fill="{_C_SAND}"/>'
            f'<circle cx="{_px(cx)}" cy="{cy}" r="6.5" fill="none" stroke="{_C_BLUE}" '
            f'stroke-width="1.5"/>')


def build_gap_history(fill: dict) -> str:
    """9 章券商态度变化图（fill["gap_history"] 可选字段，缺失/无有效行 → 空串不告警）。

    形态（demo v2 变体 A 定稿）：哑铃两面板并排——左=净利预测首末对比（同预测年度）、
    右=目标价（研报区间中值）首末对比，两行共享机构行；沙点=较早研报、最新一份钢蓝=上调 /
    中灰=下调 / 沙色环=持平，箭头指向最新值；右列=两维度首末幅度与评级变化。
    rows: [{"org","yr"?,"d_from"?,"d_to"?,"np_from"?,"np_to"?,"tp_from"?,"tp_to"?,
            "rating_from"?,"rating_to"?}]——np 对 / tp 对至少居其一为有效行；行数取前 8
    （按净利变化幅度降序，无净利按目标价）；行日期 = 净利对比首末日期（无净利退目标价日期）。
    判词横条脚本复算（上调/下调/持平按变化率符号严格判，持平=完全相等），模型禁手写；
    计数口径=截断前全集（图内注明「图列前 N 家」）。
    v5.8.0 目标价面板降级（用户拍板形态）：tp 对全缺（无同券商两份可比）而
    gap_history.tp_reports 非空时，右面板按同一价值轴单点列示各券商最新目标价
    （点落左面板机构共享行，带数值与日期；行外券商右下文字补列），无箭头无首末幅度。"""
    gh = fill.get("gap_history") or {}
    rows = []
    for r in gh.get("rows") or []:
        if not isinstance(r, dict):
            continue
        org = str(r.get("org") or "").strip()
        npf, npt = _num(r.get("np_from")), _num(r.get("np_to"))
        tpf, tpt = _num(r.get("tp_from")), _num(r.get("tp_to"))
        if not org or ((npf is None or npt is None) and (tpf is None or tpt is None)):
            continue
        rows.append({"org": org, "yr": str(r.get("yr") or "").strip(),
                     "d_from": str(r.get("d_from") or "")[5:], "d_to": str(r.get("d_to") or "")[5:],
                     "npf": npf, "npt": npt, "tpf": tpf, "tpt": tpt,
                     "rf": str(r.get("rating_from") or "").strip(),
                     "rt": str(r.get("rating_to") or "").strip()})
    if not rows:
        return ""
    rows.sort(key=_gh_sort_key)
    rows_full = rows          # 判词横条计数口径=截断前全集（v5.8.0：横条「8家」与落盘 12 行打架实证）
    n_total = len(rows)
    rows = rows[:8]

    has_np = any(r["npf"] is not None for r in rows)
    has_tp = any(r["tpf"] is not None for r in rows)
    # v5.8.0 目标价面板降级（用户拍板形态）：无同券商两份可比时，各家最新目标价按同一
    # 价值轴单点列示——落在左面板机构共享行上（各家价格可比）；有目标价但不在左面板行
    # （无净利可比）的券商在右面板下方文字补列。数据=gap_history.tp_reports（落盘照抄键）
    tp_map = {}     # 归一化机构名 → {"tp","date","org"}（同券商多份取日期最新）
    if not has_tp:
        for r in gh.get("tp_reports") or []:
            if not isinstance(r, dict):
                continue
            org = str(r.get("org") or "").strip()
            tp, dte = _num(r.get("tp")), str(r.get("date") or "")
            key = _gh_org_key(org)
            # v5.8.1 审核实证：存量须存完整日期再比较（此前存 MM-DD 与完整日期混比，
            # '2' 恒大于 '0'/'1'，同券商多份恒被最旧一份覆盖）；渲染处再切片 MM-DD
            if key and tp is not None and (key not in tp_map or dte > tp_map[key]["date"]):
                tp_map[key] = {"tp": tp, "date": dte, "org": org}
    row_keys = {_gh_org_key(r["org"]) for r in rows}
    tp_dots = [(i, tp_map[_gh_org_key(r["org"])]) for i, r in enumerate(rows)
               if _gh_org_key(r["org"]) in tp_map]
    tp_extra = sorted(((v["org"], v) for k, v in tp_map.items() if k not in row_keys),
                      key=lambda kv: -kv[1]["tp"])
    n_extra_lines = (min(len(tp_extra), 6) + 2) // 3 if tp_extra else 0
    yrs = {r["yr"] for r in rows if r["yr"]}
    np_title = (f"① {next(iter(yrs))}E 归母净利预测（亿元）· 同预测年度对比" if len(yrs) == 1
                else "① 归母净利预测（亿元）· 各行同预测年度首末对比")
    n = len(rows)
    # 布局常数（v5.8.3 收拢：原散落于函数体各字面量）：W=画布宽、NP0/NP1=左（净利）面板轴域、
    # TP0/TP1=右（目标价）面板轴域、OX=机构列（右对齐）、RX=右列（首末幅度/评级变化）、
    # TY=面板标题行 y、GY=面板网格顶 y、LG=图例起点 x
    W, NP0, NP1, TP0, TP1, OX, RX, TY, GY, LG = 1000, 210, 470, 600, 860, 180, 895, 44, 56, 30
    cy0, step = 74, 32
    cy_last = cy0 + step * (n - 1)
    H = cy_last + 40 + (n_extra_lines * 15 + 6 if n_extra_lines else 0)
    parts = ['<span class="section-tag">券商态度变化 · 同一券商首末两份研报对比（近 180 天）</span>',
             _svg_open(W, H, "券商态度变化图")]
    # 图例（v5.8.2 收敛为 _legend_row glyph 数据列表；「持平」ring 双圈字形与 _dumbbell
    # 持平记号同一 _flat_ring 参数，此前两处手写）
    _legend_row(parts, [
        ("较早研报", {"k": "dot", "r": 4, "fill": _C_SAND, "dx": 10, "gap": 30}),
        ("最新 · 上调", {"k": "dot", "r": 5, "fill": _C_BLUE, "dx": 11, "gap": 17.36}),
        ("最新 · 下调", {"k": "dot", "r": 5, "fill": _C_STONE, "dx": 11, "gap": 17.36}),
        ("持平", {"k": "ring", "r_in": 4, "fill_in": _C_SAND, "r_out": 6.5,
                  "stroke": _C_BLUE, "sw2": 1.5, "dx": 12, "gap": 24}),
        ("箭头指向最新值 · 右列=首末幅度与评级变化", {"k": "none", "dx": 0}),
    ], LG, fs=10.5, xround=True, ty=14)
    tp_title = ("② 目标价（元）· 区间中值" if has_tp
                else "② 目标价（元）· 单份研报列示（无同券商两份可比）" if tp_map
                else "② 目标价：近 180 天无两份可比研报")
    parts.append(f'<text x="{NP0}" y="{TY}" font-size="12" font-weight="700" fill="{_C_BLACK}">'
                 f'{_esc(np_title) if has_np else "① 归母净利预测：无同机构同年度可比研报"}</text>')
    parts.append(f'<text x="{TP0}" y="{TY}" font-size="12" font-weight="700" fill="{_C_BLACK}">'
                 f'{tp_title}</text>')
    parts.append(f'<text x="{RX}" y="{TY}" font-size="10.5" fill="{_C_LABEL}">首末变化</text>')

    panels = []   # (面板左 x0, 面板右 x1, 旧值键, 新值键, 值域 min, 值域 max)
    if has_np:
        vals = [v for r in rows if r["npf"] is not None for v in (r["npf"], r["npt"])]
        panels.append((NP0, NP1, "npf", "npt", min(vals), max(vals)))
    if has_tp:
        vals = [v for r in rows if r["tpf"] is not None for v in (r["tpf"], r["tpt"])]
        panels.append((TP0, TP1, "tpf", "tpt", min(vals), max(vals)))
    mappers = []
    for x0, x1, kf, kt, vlo, vhi in panels:
        lo, hi, st = _gap_axis(vlo, vhi)
        X = _lin_map(lo, hi, x0, x1)
        mappers.append((x0, kf, kt, X))
        # 面板网格刻度（v5.8.2 收编 _vgrid_ticks：_px 坐标去尾零 + _gap_fmt 数值 + 9.5 字号）
        _vgrid_ticks(parts, X, _gap_ticks(lo, hi, st), GY, cy_last + 12, cy_last + 26,
                     fs=9.5, xfmt=_px, vfmt=_gap_fmt)
    # v5.8.0 降级面板的单点价值轴（与哑铃面板同款刻度，各家目标价横向可比）
    tp_X = None
    if tp_dots:
        lo, hi, st = _gap_axis(min(v["tp"] for _, v in tp_dots), max(v["tp"] for _, v in tp_dots))
        tp_X = _lin_map(lo, hi, TP0, TP1)
        _vgrid_ticks(parts, tp_X, _gap_ticks(lo, hi, st), GY, cy_last + 12, cy_last + 26,
                     fs=9.5, xfmt=_px, vfmt=_gap_fmt)

    def _dumbbell(x0, kf, kt, X, r, cy):
        v0, v1 = r[kf], r[kt]
        if v0 is None:
            return (f'<text x="{x0}" y="{cy + 3.5}" font-size="9.5" fill="{_C_SAND}">'
                    f'{"未给目标价" if kf == "tpf" else "无同年度对比"}</text>')
        a, b = X(v0), X(v1)
        if v0 == v1:
            return (_flat_ring(a, cy)
                    + f'<text x="{_px(a)}" y="{cy - 13}" text-anchor="middle" font-size="9.5" '
                      f'fill="{_C_LABEL}">{_gap_fmt(v0)} 持平</text>')
        up = v1 > v0
        col = _C_BLUE if up else _C_STONE
        # 哑铃几何（v5.8.2 收编基座 _arrow_dumbbell 参数化：r4/5.5 点、线宽 2、箭头尖距新点 4、
        # 箭长 8/翼半宽 3.5、无回缩、polygon 平底在前——口径差异全在参数，逐字节同原手写）
        s = _arrow_dumbbell(a, b, cy, col, _px, r_old=4, r_new=5.5, sw_new=1.5, lw=2,
                            setback=0, tip_off=4, wing=8, wing_half=3.5,
                            far_min=0, base_first=True)
        if up:   # 旧值标左、新值标右（外侧）
            s += (f'<text x="{_px(a - 8)}" y="{cy + 3.5}" text-anchor="end" font-size="9.5" '
                  f'fill="{_C_LABEL}">{_gap_fmt(v0)}</text>'
                  f'<text x="{_px(b + 9)}" y="{cy + 3.5}" font-size="10" font-weight="700" '
                  f'fill="{_C_INK}">{_gap_fmt(v1)}</text>')
        else:    # 下调：新值标左、旧值标右
            s += (f'<text x="{_px(b - 9)}" y="{cy + 3.5}" text-anchor="end" font-size="10" '
                  f'font-weight="700" fill="{_C_INK}">{_gap_fmt(v1)}</text>'
                  f'<text x="{_px(a + 8)}" y="{cy + 3.5}" font-size="9.5" '
                  f'fill="{_C_LABEL}">{_gap_fmt(v0)}</text>')
        return s

    for i, r in enumerate(rows):
        cy = cy0 + step * i
        parts.append(f'<text x="{OX}" y="{cy - 2}" text-anchor="end" font-size="11.5" '
                     f'font-weight="600" fill="{_C_INK}">{_esc(r["org"])}</text>')
        if r["d_from"] or r["d_to"]:
            parts.append(f'<text x="{OX}" y="{cy + 9}" text-anchor="end" font-size="9" '
                         f'fill="{_C_LABEL}">{_esc(r["d_from"])} → {_esc(r["d_to"])}</text>')
        for x0, kf, kt, X in mappers:
            parts.append(_dumbbell(x0, kf, kt, X, r, cy))
        # 右列：净利幅度 / 目标价幅度 + 评级变化
        dnp, dtp = _gh_delta(r, "npf", "npt"), _gh_delta(r, "tpf", "tpt")
        pct = " / ".join([f"{d * 100:+.1f}%" if d is not None else "—"
                          for d, has in ((dnp, has_np), (dtp, has_tp)) if has])
        ry = cy + (0 if (r["rf"] and r["rt"]) else 3.5)
        parts.append(f'<text x="{RX}" y="{_px(ry)}" font-size="11.5" font-weight="700" '
                     f'fill="{_C_INK}">{pct}</text>')
        if r["rf"] and r["rt"]:
            parts.append(f'<text x="{RX}" y="{cy + 10}" font-size="9" fill="{_C_STONE}">'
                         f'评级 {_esc(r["rf"])}→{_esc(r["rt"])}</text>')
    # v5.8.0 降级面板：单份目标价点落在左面板机构共享行（数值轴同上，各行可比）；
    # 有目标价但不在左面板行的券商，右面板下缘文字补列（3 家一行，至多 2 行）
    if tp_X is not None:
        for i, v in tp_dots:
            cy = cy0 + step * i
            x = tp_X(v["tp"])
            parts.append(f'<circle cx="{_px(x)}" cy="{cy}" r="5" fill="{_C_BLUE}" '
                         f'stroke="{_C_PAPER}" stroke-width="1.5"/>'
                         f'<text x="{_px(x)}" y="{cy - 10}" text-anchor="middle" font-size="10" '
                         f'font-weight="600" fill="{_C_INK}">{_gap_fmt(v["tp"])}</text>'
                         f'<text x="{_px(x)}" y="{cy + 14}" text-anchor="middle" font-size="8.5" '
                         f'fill="{_C_LABEL}">{_esc(v["date"][5:])}</text>')
    if tp_extra:
        seg = [f'{o} {_gap_fmt(v["tp"])}（{v["date"][5:]}）' for o, v in tp_extra[:6]]
        if len(tp_extra) > 6:
            seg[-1] += f' 等 {len(tp_extra)} 家'
        for li in range(n_extra_lines):
            chunk = seg[li * 3:(li + 1) * 3]
            if not chunk:
                break
            prefix = "另有目标价（无净利可比，补列）：" if li == 0 else ""
            parts.append(f'<text x="{TP0}" y="{cy_last + 44 + li * 15}" font-size="9.5" '
                         f'fill="{_C_LABEL}">{_esc(prefix + "；".join(chunk))}</text>')
    parts.append(_svg_close())

    # 判词横条（脚本复算，持平=首末完全相等；计数口径=截断前全集，图内注明列示范围）
    def _counts(kf, kt):
        u = d = f = 0
        for r in rows_full:
            dl = _gh_delta(r, kf, kt)
            if dl is None:
                continue
            u, d, f = u + (dl > 0), d + (dl < 0), f + (dl == 0)
        return u, d, f

    s_parts = [f"近 180 天 {n_total} 家券商有可比前后研报"
               + (f"（图列变化幅度前 {n} 家）" if n_total > n else "")]
    if has_np:
        u, d, f = _counts("npf", "npt")
        s_parts.append(f"净利预测 <b>上调 {u} 家 / 下调 {d} 家 / 持平 {f} 家</b>")
    if has_tp:
        u, d, f = _counts("tpf", "tpt")
        m = sum(1 for r in rows_full if r["tpf"] is not None)
        s_parts.append(f"目标价 <b>上调 {u} 家 / 下调 {d} 家 / 持平 {f} 家</b>（{m} 家给出）")
    elif tp_map:
        s_parts.append(f"目标价 {len(tp_map)} 家给出（无同券商两份可比，右面板按同一价值轴单点列示）")
    chg = [r for r in rows_full if r["rf"] and r["rt"]]
    if chg:
        seg = "；".join(f'{r["org"]} {r["rf"]}→{r["rt"]}' for r in chg[:4])
        s_parts.append(f"评级变化 {len(chg)} 家（{_esc(seg)}）")
    summary = ('<div class="layer-summary">' + s_parts[0]
               + ("：" + "；".join(s_parts[1:]) if len(s_parts) > 1 else "") + "。</div>")

    parts.append(_chart_source(
        "券商态度变化图", "券商研报明细（近 180 天首末两份，落盘核对）",
        '每行=一家券商'
        '近 180 天首末两份研报（按净利变化幅度降序，取前 8 家），沙点=较早一份、最新一份'
        '钢蓝=上调 / 中灰=下调 / 沙色环=持平（首末完全相等），箭头指向最新值；'
        '① 净利预测仅同预测年度首末对比，跨年预测不直接可比；② 目标价取研报区间中值；'
        '右列=两维度首末幅度与评级变化；仅覆盖 180 天内 ≥2 份研报的券商，'
        '目标价维度无同券商两份可比时，右面板按同一价值轴单点列示各券商最新目标价'
        '（共享左面板机构行），行外券商在右下补列；'
        '东财兜底路径与港股无逐份明细、不适用本图；'
        '评级变化=同一券商首末对比口径，与 12 章时机信号「近 90 天评级上/下调家数」'
        '（券商评级分布统计）口径不同，两处数字不要求互洽'))
    return "".join(parts) + summary


def _renumber_note(note: str, circled: str) -> str:
    """把附注文首（可隔 <b> 开标签）的圈号前缀改写为指定行号；无圈号前缀原样返回。
    v5.1.2：note 圈号本是填写方手写，行被剔除后手写编号失效——脚本按过滤后行序统一改写。"""
    # v5.1.2：前缀形态放宽为「任意标签/实体/空白」（热核 P2-1：<i>/<b style>/&nbsp; 开头
    # 的 note 此前不改写，剔除行后手写圈号与图行再次错位）
    return re.sub(r"^((?:\s|&nbsp;|<[^>]+>)*)[①-⑥]", rf"\g<1>{circled}", note, count=1)


def _gap_notes_html(gp: dict) -> str:
    """gap-notes 附注（图下编号注）：dims[].note 按图行序（①②… 与图行一一对应）+ text_dims 续编号
    文本项。v5.1.2：行过滤与图同源（_gap_dim_ok，cons≤0 行剔除、取前 6、有效行 <2 随图不生成），
    附注编号由脚本按过滤后行序改写（此前按原始数组取行前 6 且编号手写——剔除行后图①与注①
    错位，读者把 A 行的注读成 B 行的）。内容为填写方直写 HTML，脚本只包 <li>；
    无任何附注 → 空串。"""
    dims = [d for d in (gp.get("dims") or []) if _gap_dim_ok(d)][:6]
    if len(dims) < 2:
        return ""
    items = []
    for i, d in enumerate(dims):
        note = str(d.get("note") or "").strip()
        if note:
            items.append(f"<li>{_renumber_note(note, _GAP_CIRCLED[i])}</li>")
    for j, t in enumerate(gp.get("text_dims") or []):
        t = str(t or "").strip()
        if not t:
            continue
        if len(dims) + j < len(_GAP_CIRCLED):
            t = _renumber_note(t, _GAP_CIRCLED[len(dims) + j])
        else:
            # 无圈号可用（图行已占满 ①-⑥）：剥掉手写文首圈号，避免与图行撞号（热核 P2-3）
            t = re.sub(r"^((?:\s|&nbsp;|<[^>]+>)*)[①-⑥]", r"\g<1>", t, count=1)
        items.append(f"<li>{t}</li>")
    return '<ol class="gap-notes">' + "".join(items) + "</ol>" if items else ""


def _inject_gap_chart(gap_html: str, fill: dict) -> str:
    """9 预期差图锚点注入（与 _inject_l3_charts 同一注入机）：gap_html 里的 <!--GAP--> 注释
    原位替换为「图 + <ol class="gap-notes"> 附注 + 券商态度变化图（v5.6.0，gap_history
    已填时）」整体；锚点缺失但字段已填 → 垫第 9 章章首 + 告警（prepend——图是本章主体）；
    字段未填 → 锚点静默清除；有效维度 <2 → 图与附注同不生成（v5.1.2 起附注与图行同源，
    text_dims 一并丢弃；态度变化图独立于分布图，gap_history 有有效行即生成）。"""
    block = (build_gap_plot(fill) + _gap_notes_html(fill.get("gap_plot") or {})
             + build_gap_history(fill))
    return _inject_chart_anchors(
        gap_html,
        (("<!--GAP-->", block, "gap_plot"),),
        "gap_html", "第 9 章章首", "建议把锚点放到档位说明段之后", prepend=True)

