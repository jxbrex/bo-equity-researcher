#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""charts_base.py — SVG 图表基座（v4.9 从 charts.py 拆出）

内容：全站图表共用色板常量（_C_*，含模板 .mini-cell 底色 _C_PAPER_CELL 与徽章深色字典
_C_BADGE_DEEP）、数值/格式/几何工具（_fmt_px/_fmt_amt/_pad_domain/_lin_map/_text_w/_wrap_label/_ticks）、
情景字典（_SCENARIO_COLORS）、SVG 骨架 helper（_SVG_STYLE/_svg_open/_svg_close/
_vgrid_ticks/_hgrid_ticks/_legend_row/_anchor_fit/_anchor_clamp/_inject_chart_anchors）与回测新旧
对比共享行（_prev_track_rows）。
只依赖 scoring，被各图族模块与 validate.py 导入。"""

import math
import re
import sys

from scoring import _esc, _fmt, _num, _plain_text

# SVG 色板（全站图表共用暖灰/钢蓝色系，唯一权威处；改色只动这里）
_C_LABEL = "#6f695e"       # 轴刻度/灰字说明/虚线时点刻（v4.9 自 #8a8375 压深，小字对比度达标）
_C_GRID = "#ece7db"        # 细网格线
_C_AXIS = "#e0d7c3"        # 轴主线/细描边
_C_BLUE = "#4a6fa5"        # 钢蓝：目标公司/合理带/最新值/PE 发丝
_C_PAPER = "#fffdf9"       # 近白：白刻/描边/带内白字
_C_INK = "#3a362e"         # 深墨：名称文字/发丝线/图例
_C_BLACK = "#2b2620"       # 最重色：首变量名/当前值刻
_C_STONE = "#57524a"       # 中灰：散点同业标签/图例小字
_C_OLIVE = "#66604f"       # 散点图非目标点
_C_SAND = "#b3ab93"        # 暖沙：历史柱/连线曲线/中轴/图例块
_C_SAND_LT = "#ddd3bd"     # 浅沙：分带虚线/分位段
_C_TRACK = "#efe9db"       # 条底轨道/历史带底/面积填充
_C_PAPER_CELL = "#f7f2e7"  # 米纸格底：与模板 .mini-cell 底色一致（文字光晕描边 paint-order 防叠字）
_C_GOOD_LINE = "#c9bfa8"   # 7.0 良好线虚线
_C_YEAR_GRID = "#f0ebdf"   # 发丝图年份竖网格
# 评价色（好坏语义，绿好红坏不变）；股价涨跌方向色走模板 .up/.down（v4.9 起红涨绿跌）
_C_GREEN = "#6ba86b"       # 绿（评价）：有利/上调/乐观/质量好
_C_RED = "#c75b5b"         # 红（评价）：不利/下调/悲观/质量差
_C_ORANGE = "#c08a2e"      # 橙：中档/基础情景
# 徽章深色字典（跟随模板 .badge-* 加深系：白字/小字 AA 对比度；评分条色用，与 pastel 评价色区分）
_C_BADGE_DEEP = {"badge-green": "#4d804d", "badge-orange": "#96691a", "badge-red": "#b84a4a"}


def _fmt_px(v):
    """目标价/区间展示价（v4.10）：低价股两位小数（<10 元，如 5.88-6.47），其余整数。
    缘起：工行报告 7 元价位被 :.0f 压成 6-6/8-8/9-9 假无区间。统一用于三情景表/
    Hero 目标价区间卡/走廊图标签，同一份报告只此一种精度。"""
    return f"{v:.2f}" if abs(v) < 10 else f"{v:.0f}"


def _fmt_amt(v) -> str:
    """亿元金额标签：≥1000 带千位符，去尾零（1,156.0 → 1,156；56.8 → 56.8）。v4.8 业务构成图用。
    阈值口径注意（v5.8.3）：与 charts_period._pamt（≥100 取整）不同——本函数服务业务构成图
    （营收/毛利额，大额居多，百位以下取整丢信息），各图阈值是有意差异，勿对齐。"""
    if v is None:
        return "—"
    s = f"{float(v):,.1f}"
    return s[:-2] if s.endswith(".0") else s


def _var_key(name) -> str:
    """变量名比对键：剥 HTML + 去全部空白（驱动卡/龙卷风/校验同源，v5.1.1）。"""
    return re.sub(r"\s+", "", _plain_text(str(name or "")))


def _sensitivity_items(fill: dict) -> list:
    """sensitivity 有效行（name 非空 + impact 可解析为数值），按 |impact| 降序。
    「首行=第一变量」的唯一定义处（v5.1.1：此前龙卷风按 impact 排序加冕、校验却比 fill 数组
    第 0 项，两套「首行」让影石创新驱动卡与排序图各执一词静默过检）。"""
    items = []
    for s in fill.get("sensitivity") or []:
        if not isinstance(s, dict):
            continue
        imp = _num(s.get("impact"))
        name = str(s.get("name") or "").strip()
        if imp is None or not name:
            continue
        items.append({"name": name, "impact": abs(imp),
                      "delta": str(s.get("delta") or "").strip(),
                      "amount": str(s.get("amount") or "").strip()})
    items.sort(key=lambda r: -r["impact"])
    return items


def _first_var_name(fill: dict) -> str:
    """第一变量名（唯一定义，v5.1.1）：sensitivity 有效行 |impact| 降序首行；
    sensitivity 缺失/无有效行 → 回退 drivers 手标 first_var（无龙卷风形态兼容）；皆无 → ""。"""
    items = _sensitivity_items(fill)
    if items:
        return items[0]["name"]
    for d in fill.get("drivers") or []:
        if isinstance(d, dict) and d.get("first_var"):
            return str(d.get("name") or "").strip()
    return ""


def _gap_dim_ok(d) -> bool:
    """gap_plot 维度行有效性（v5.1.2：图行/附注/校验同源判定）：dict 且 name/ours/consensus
    可解析、consensus >0（≤0 行图内剔除——此前附注按原始数组取行，剔除后图①与注①错位）。"""
    if not isinstance(d, dict):
        return False
    name = str(d.get("name") or "").strip()
    ours, cons = _num(d.get("ours")), _num(d.get("consensus"))
    return bool(name) and ours is not None and cons is not None and cons > 0


def parse_stage_period(period: str):
    """cycle_stages period → ((年0,月0),(年1,月1))；解析失败/月份越界 → None。
    终点可写「至今/今/现在」→ (9999,12) 开口（渲染端夹取到序列末月；迈瑞 2026/01–至今实证，
    当前段是 analyst 最常写的开口形态，禁写会逼出手填未来月份）。
    渲染（季K图阶段分界）与 validate 校验的唯一权威（v5.1.3 单源教训：影石 first_var
    双定义矛盾同源修复）。容忍分隔符 / - . 与「年」，起止各取首个匹配。"""
    text = str(period or "").strip()
    ms = re.findall(r"(\d{4})\s*[/\-.年]\s*(\d{1,2})", text)
    if len(ms) >= 2:
        (y0, m0), (y1, m1) = (int(ms[0][0]), int(ms[0][1])), (int(ms[1][0]), int(ms[1][1]))
        if not (1 <= m0 <= 12 and 1 <= m1 <= 12):
            return None
        return (y0, m0), (y1, m1)
    if len(ms) == 1 and any(k in text for k in ("至今", "今", "现在")):
        y0, m0 = int(ms[0][0]), int(ms[0][1])
        if not (1 <= m0 <= 12):
            return None
        return (y0, m0), (9999, 12)
    return None


def _period_ratio(pt: dict, amt_k: str, goal_k: str = None, cons_k: str = None):
    """报告期完成度（v5.1.2，子弹图与判词对账同源）：分母=一致预期优先、缺则经营目标
    （与 charts_period.build_period_bullets 同一选取规则）；返回 累计÷分母，
    任一缺失或分母 ≤0 → None。"""
    v = _num(pt.get(amt_k))
    goal = _num(pt.get(goal_k)) if goal_k else None
    cons = _num(pt.get(cons_k)) if cons_k else None
    d = cons if cons is not None else goal
    # 累计 ≤0（亏损期）完成度无意义 → None（与子弹图「累计 ≤0 不标完成度」同源，热核审计修复）
    if v is None or v <= 0 or not d or d <= 0:
        return None
    return v / d


# 报告期判词四元组（v5.1.5 单源化：charts_period._period_verdict 渲染兜底与
# validate._check_period_track 四选一校验同源——此前 charts_misc 与 validate 各存一份）
_PERIOD_VERDICTS = ("超前", "正常", "滞后", "无法判定")


# 来源注内部黑话禁词（v5.7.3 统一权威，_chart_source 自检与 render_report 最终 HTML
# 门禁同源消费）：报告 .source 只回答读者关心的问题——数据从哪里来、哪些是估算/本报告
# 计算、口径是什么；内部实现名（抓取脚本/fill 字段名/E1-E6 编号）一律不得出现在来源注。
# 大小写不敏感（防 EM_FETCH 类绕过）；字段名带词边界（Shareholders 等正常词不误伤）。
_SOURCE_BANNED_RE = re.compile(
    r"脚本按|字段生成|照抄行"
    r"|(?<![A-Za-z0-9_])(?:em_fetch|extract_review|period_track|segments|growth_plot"
    r"|fin_trend|industry_chain|holders|gap_plot|gap_history|pe_history|price_history"
    r"|valuation_inputs|peers_plot|sensitivity|triggers|prev\.scenarios)(?![A-Za-z0-9_])"
    r"|(?<![A-Za-z0-9])E[1-6](?![0-9A-Za-z])", re.I)


def _chart_source(title: str, source: str, note: str = "") -> str:
    """脚本图注统一来源注（v5.7.3）：<span class="source chart-source">标题（数据来源：真实来源）：口径说明</span>。
    保留模板 .source 样式；chart-source 供 render_report 最终 HTML 门禁识别（脚本图注必含
    非空「数据来源：」）。source 必须是读者可核验的真实来源（公司定期报告/公开行情/券商一致
    预期/本报告计算等），空/空白来源直接 ValueError（空壳「数据来源：」等于没写）；
    title/source/note 先过 _SOURCE_BANNED_RE 自检，命中即 ValueError——
    新增图表把内部黑话写进图注时在开发期尽早失败。"""
    if not isinstance(source, str) or not source.strip():
        raise ValueError(f"图注来源必须是 strip 后非空的字符串（收到 {type(source).__name__}: "
                         f"{str(source)[:40]!r}）——chart-source 必须写读者可核验的真实来源"
                         "（公司定期报告/公开行情/券商一致预期/本报告计算等），空壳「数据来源：」等于没写")
    for label, text in (("标题", title), ("来源", source), ("口径说明", note)):
        m = _SOURCE_BANNED_RE.search(str(text))
        if m:
            raise ValueError(f"图注{label}含内部实现名「{m.group(0)}」：{str(text)[:80]}——"
                             "来源注面向读者，须写可核验的真实来源，"
                             "禁写抓取脚本名/fill 字段名/E1-E6 编号")
    src = f"{title}（数据来源：{source}）"
    if note:
        src += f"：{note}"
    return f'<span class="source chart-source">{src}</span>'



_SCENARIO_COLORS = {"pess": _C_RED, "base": _C_ORANGE, "opt": _C_GREEN}


def _prev_track_rows(prev: dict, quality, valuation, timing, quality_version=1) -> list:
    """三轨对比共享行；只有同版三轨质量分计算差值，旧单轨永远只可展示。
    quality_version 只管质量算法，估值与时机仍按原口径比较。"""
    rows = []
    previous_version = prev.get("quality_version") or 1
    for label, old, new in (("质量分", _num(prev.get("quality", prev.get("research"))), quality),
                            ("估值分", _num(prev.get("valuation")), valuation),
                            ("时机分", _num(prev.get("timing")), timing)):
        if old is None or new is None:
            continue
        comparable = (label != "质量分" or (previous_version != "legacy-single-track"
                                          and str(previous_version) == str(quality_version)))
        rows.append({"label": label, "old": old, "new": float(new), "comparable": comparable,
                     "d": float(new) - old if comparable else None})
    return rows


def _pad_domain(lo: float, hi: float, ratio: float, floor=None, zero=None):
    """值域向两端各扩 ratio 比例（防贴边）；floor 给下限（如 ROE 不为负）；
    zero 给非正跨度时的垫量（v5.8.2，_gap_axis 复用：数据齐平/倒序时按 |hi|×10% 与 1 取大；
    判定 pad<=0 与原 _gap_axis 的「span>0 用比例垫、否则用 zero」逐步等价）。"""
    pad = (hi - lo) * ratio
    if pad <= 0:
        pad = zero if zero is not None else 1
    lo -= pad
    hi += pad
    if floor is not None:
        lo = max(floor, lo)
    return lo, hi


def _lin_map(a: float, b: float, A: float, B: float):
    """线性映射：数值域 [a,b] → 像素域 [A,B]（a→A，b→B）。"""
    return lambda v: A + (v - a) / (b - a) * (B - A)


def _text_w(s: str, font_size: float) -> float:
    """粗估 SVG 文本像素宽（中文/全角≈1em、ASCII≈0.56em），用于标签避让与碰撞检测。"""
    return sum(1.0 if ord(ch) > 0x2E7F else 0.56 for ch in str(s)) * font_size


def _wrap_label(s: str, max_w: float, fs: float) -> list:
    """文本超宽时按视觉宽度对半折两行（断点取两侧宽度最均衡处）；未超宽原样返回 [s]。"""
    if _text_w(s, fs) <= max_w:
        return [s]
    best, best_diff = len(s) // 2, float("inf")
    for i in range(2, len(s) - 1):
        d = abs(_text_w(s[:i], fs) - _text_w(s[i:], fs))
        if d < best_diff:
            best, best_diff = i, d
    return [s[:best], s[best:]]


def _ticks(lo: float, hi: float, n: int = 5, mults=(1, 2, 2.5, 5, 10),
           open_interval: bool = False, ret_step: bool = False):
    """nice-number 刻度。步长取 mults 中首个 m×10^k：
    默认（闭区间）：m×10^k ≥ span/(n-1) 的首档，返回落在 [lo,hi] 内的步长整数倍刻度
    （取代旧版「等距后取整」，会产出 19/32/44/57/69 这类间隔观感不齐的读数）。
    open_interval=True（v5.8.2 收编 charts_gap 定标体系）：候选自 10^(⌊log10(span)⌋-1) 逐档
    试探，取开区间 (lo,hi) 内刻度数 ≤ n 的最小步长，返回开区间内倍数——原 _gap_axis 的
    步长选择/刻度生成与此逐行等价；ret_step=True 时返回 (刻度, 步长)。"""
    span = hi - lo
    if not span > 0:
        return [lo]
    if open_interval:
        step = None
        k0 = int(math.floor(math.log10(span))) - 1
        for k in range(k0, k0 + 8):
            for m in mults:
                st = m * 10.0 ** k
                cnt = math.ceil(hi / st - 1e-9) - (math.floor(lo / st + 1e-9) + 1)
                if cnt <= n:
                    step = st
                    break
            if step is not None:
                break
        out = _open_ticks(lo, hi, step)
        return (out, step) if ret_step else out
    raw = span / (n - 1)
    mag = 10 ** math.floor(math.log10(raw))
    step = mag
    for m in mults:
        if m * mag >= raw:
            step = m * mag
            break
    t = math.ceil(lo / step - 1e-9) * step
    out = []
    while t <= hi + 1e-9:
        out.append(round(t, 9))
        t += step
    return out


def _open_ticks(lo: float, hi: float, step: float) -> list:
    """严格落在开区间 (lo, hi) 内的 step 整数倍刻度（v5.8.2 收编 charts_gap._gap_ticks，
    原实现逐行等价；charts_gap 侧保留 _gap_ticks 名作为本函数别名）。"""
    out, k = [], math.floor(lo / step + 1e-9) + 1
    while k * step < hi - 1e-9:
        out.append(round(k * step, 9))
        k += 1
    return out





_SVG_STYLE = "width:100%;min-width:760px;height:auto;display:block;font-family:inherit;"


def _svg_open(w, h, label: str) -> str:
    """图表骨架开头：plot-wrap 容器 + viewBox + aria-label + 全站统一 style。"""
    return (f'<div class="plot-wrap"><svg viewBox="0 0 {w} {h}" role="img" '
            f'aria-label="{label}" style="{_SVG_STYLE}">')


def _svg_close() -> str:
    return '</svg></div>'


def _vgrid_ticks(parts: list, X, vals: list, y1, y2, ty, suffix: str = "", fs=11,
                 xfmt=None, vfmt=None, labels: bool = True) -> None:
    """竖向网格线 + 居中刻度文字（走廊/评分/PE带/业务构成/哑铃/B档/态度图多图共用）。
    y1/y2 为网格线纵坐标、ty 为刻度文字纵坐标，数值由调用方按各图布局给出；
    suffix 为刻度数字后的单位（如 x / %）；fs 刻度字号（v5.8.2，gap 图网格 9.5 收编）；
    xfmt/vfmt 坐标/数值格式化函数（缺省 :.1f/_fmt；gap 图传 _px 去尾零/_gap_fmt）；
    labels=False 只出刻度字不画网格线（v5.8.2，peers 散点横轴原即无竖网格线）。
    vals 元素可为 (值, 预格式文本) 元组——B 档定域刻度（-10,"-10%"）等，元组跳过 vfmt/suffix。"""
    xf = xfmt or (lambda v: f"{v:.1f}")
    vf = vfmt or _fmt
    for v in vals:
        if isinstance(v, tuple):
            v, lab = v
        else:
            lab = f"{vf(v)}{suffix}"
        gx = X(v)
        if labels:
            parts.append(f'<line x1="{xf(gx)}" y1="{y1}" x2="{xf(gx)}" y2="{y2}" stroke="{_C_GRID}" stroke-width="1"/>')
        parts.append(f'<text x="{xf(gx)}" y="{ty}" text-anchor="middle" font-size="{fs}" fill="{_C_LABEL}">{lab}</text>')


def _hgrid_ticks(parts: list, Y, vals: list, x1, x2, tx, suffix: str = "", fs: int = 11,
                 dy: int = 4, labels: bool = True, lines: bool = True) -> None:
    """横向网格线 + 右对齐刻度文字（股价发丝图/利润增长图/财务趋势面板三图共用）。
    x1/x2 为网格线横向范围、tx 为刻度文字右缘 x，数值由调用方按各图布局给出；
    suffix 为刻度数字后的单位（% 等）；labels=False 只画线不出字（财务趋势纯线面板网格随线域）；
    lines=False 只出字不画线（v5.8.2，peers 散点纵轴原即无横网格线）。"""
    for v in vals:
        gy = Y(v)
        if lines:
            parts.append(f'<line x1="{x1}" y1="{gy:.1f}" x2="{x2}" y2="{gy:.1f}" stroke="{_C_GRID}" stroke-width="1"/>')
        if labels:
            parts.append(f'<text x="{tx}" y="{gy + dy:.1f}" text-anchor="end" font-size="{fs}" fill="{_C_LABEL}">{_fmt(v)}{suffix}</text>')


def _arrow_dumbbell(xo, xn, cy, color, fmt, dash="", hollow=False,
                    r_old=6, r_new=7.5, sw_new=2, lw=3, setback=19,
                    tip_off=10, wing=9, wing_half=5.5, far_min=26,
                    base_first=False) -> str:
    """哑铃连线+箭头+两端点（13 章回测哑铃 / 9 章 B 档偏离哑铃 / 9 章态度变化图哑铃共用几何，
    v5.1.5 收敛；v5.8.2 参数化收编态度图内联哑铃——默认值=回测/B 档原口径不动，
    态度图传 r_old=4/r_new=5.5/sw_new=1.5/lw=2/setback=0/tip_off=4/wing=8/wing_half=3.5/
    far_min=0/base_first=True 逐字节复刻其手写差异）：
    两点距 <far_min 不画箭头（防叠）；连线末端回缩 setback*s；箭头尖距新点 tip_off*s、
    箭长 wing*s、翼半宽 wing_half；polygon 顶点序默认尖在前（回测/B 档），base_first=True
    平底在前（态度图）；端点：旧值/零轴=沙灰 r_old，新值/本文=r_new 钢蓝白描边
    （hollow=空心，偏离超定域的截断记号）。fmt=坐标格式化函数（调用方各持 .1f/_px 口径）。"""
    s = 1 if xn >= xo else -1
    far = abs(xn - xo) >= far_min
    out = [f'<line x1="{fmt(xo)}" y1="{fmt(cy)}" x2="{fmt(xn - setback * s) if far else fmt(xn)}" '
           f'y2="{fmt(cy)}" stroke="{color}" stroke-width="{lw}"{dash}/>']
    if far:
        tip = xn - tip_off * s
        back = tip - wing * s
        if base_first:
            pts = (f'{fmt(back)},{fmt(cy - wing_half)} {fmt(back)},{fmt(cy + wing_half)} '
                   f'{fmt(tip)},{fmt(cy)}')
        else:
            pts = (f'{fmt(tip)},{fmt(cy)} {fmt(back)},{fmt(cy - wing_half)} '
                   f'{fmt(back)},{fmt(cy + wing_half)}')
        out.append(f'<polygon points="{pts}" fill="{color}"/>')
    out.append(f'<circle cx="{fmt(xo)}" cy="{fmt(cy)}" r="{r_old}" fill="{_C_SAND}"/>')
    fill_c, stroke_c = (_C_PAPER, color) if hollow else (_C_BLUE, _C_PAPER)
    out.append(f'<circle cx="{fmt(xn)}" cy="{fmt(cy)}" r="{r_new}" fill="{fill_c}" '
               f'stroke="{stroke_c}" stroke-width="{sw_new}"/>')
    return "".join(out)


def _legend_row(parts: list, items: list, x, y: int = 8, fs: int = 11, sw: int = 13, sh: int = 9,
                rx: float = 2.5, dx: int = 18, gap: int = 22, tcolor: str = _C_LABEL,
                xround: bool = False, ty=None):
    """图例横排单行：逐项画「glyph + 标签文字」并水平推进，返回行末 x（下一项起点）。
    items 元素两种形态（v5.8.2 glyph 参数化：原仅支持矩形色块，致 gap/cycle/period/l1
    七处手写图例，本版收敛为数据列表）：
      (标签, 色块 fill) / (标签, fill, 额外属性) —— 矩形色块旧契约，输出与 v5.8.2 前逐字节一致；
      (标签, glyph 字典) —— k=rect(默认)/dot/line/vline/diamond/duo/ring/none 纯文字项，
        样式 fill/stroke/sw2(描边宽)/dash/lw(线宽)/fills(duo 双色)，
        几何 r/cx/len/ox/w/h/rx2/gy/y1/y2（glyph 锚点=行内当前 x；dot/line/diamond 的
        cy 缺省 ty-4，rect/duo 的 gy 缺省 y），项级覆盖 dx(文字偏移)/gap(后继间距)/tc(文字色)。
    xround=True 时 glyph 与文字的全部 x 输出取 :.0f（cycle/l1-segments 图例原手写即取整口径）。
    ty=文字基线（缺省 y + sh - 1）；标签由本函数转义、推进宽度按未转义文本量取。"""
    ty_ = (y + sh - 1) if ty is None else ty
    xf = (lambda v: f"{v:.0f}") if xround else (lambda v: f"{v}")
    for it in items:
        txt, spec = it[0], it[1]
        idx, igap, tc = dx, gap, tcolor
        if isinstance(spec, dict):
            idx = spec.get("dx", dx)
            igap = spec.get("gap", gap)
            tc = spec.get("tc", tcolor)
            k = spec.get("k", "rect")
            cy = spec.get("cy", ty_ - 4)
            if k == "rect":
                parts.append(f'<rect x="{xf(x)}" y="{spec.get("gy", y)}" width="{spec.get("w", sw)}" '
                             f'height="{spec.get("h", sh)}" rx="{spec.get("rx2", rx)}" '
                             f'fill="{spec["fill"]}"/>')
            elif k == "dot":
                stroke = (f' stroke="{spec["stroke"]}" stroke-width="{spec.get("sw2", 1.5)}"'
                          if spec.get("stroke") else "")
                parts.append(f'<circle cx="{xf(x + spec.get("cx", spec["r"]))}" cy="{cy}" '
                             f'r="{spec["r"]}" fill="{spec["fill"]}"{stroke}/>')
            elif k == "line":
                dash = f' stroke-dasharray="{spec["dash"]}"' if spec.get("dash") else ""
                parts.append(f'<line x1="{xf(x)}" y1="{cy}" x2="{xf(x + spec.get("len", 26))}" '
                             f'y2="{cy}" stroke="{spec["stroke"]}" '
                             f'stroke-width="{spec.get("lw", 1.6)}"{dash}/>')
            elif k == "vline":
                ox = spec.get("ox", 0)
                parts.append(f'<line x1="{xf(x + ox)}" y1="{spec["y1"]}" x2="{xf(x + ox)}" '
                             f'y2="{spec["y2"]}" stroke="{spec["stroke"]}" '
                             f'stroke-width="{spec.get("lw", 3)}"/>')
            elif k == "diamond":
                r = spec.get("r", 6)
                cx = x + spec.get("cx", r)
                parts.append(f'<polygon points="{xf(cx)},{cy - r} {xf(cx + r)},{cy} '
                             f'{xf(cx)},{cy + r} {xf(cx - r)},{cy}" fill="{spec["fill"]}"/>')
            elif k == "duo":
                w, h = spec.get("w", 12), spec.get("h", 9)
                g2, gy = spec.get("gap2", 2), spec.get("gy", y)
                parts.append(f'<rect x="{xf(x)}" y="{gy}" width="{w}" height="{h}" rx="{spec.get("rx2", rx)}" '
                             f'fill="{spec["fills"][0]}"/>'
                             f'<rect x="{xf(x + w + g2)}" y="{gy}" width="{w}" height="{h}" '
                             f'rx="{spec.get("rx2", rx)}" fill="{spec["fills"][1]}"/>')
            elif k == "ring":
                cx = x + spec.get("cx", 0)
                parts.append(f'<circle cx="{xf(cx)}" cy="{cy}" r="{spec["r_in"]}" fill="{spec["fill_in"]}"/>'
                             f'<circle cx="{xf(cx)}" cy="{cy}" r="{spec["r_out"]}" fill="none" '
                             f'stroke="{spec["stroke"]}" stroke-width="{spec.get("sw2", 1.5)}"/>')
            # k == "none"：纯文字说明项（无 glyph）
        else:
            extra = f' {it[2]}' if len(it) > 2 and it[2] else ""
            parts.append(f'<rect x="{xf(x)}" y="{y}" width="{sw}" height="{sh}" rx="{rx}" fill="{spec}"{extra}/>')
        parts.append(f'<text x="{xf(x + idx)}" y="{ty_}" font-size="{fs}" fill="{tc}">{_esc(txt)}</text>')
        x += idx + _text_w(txt, fs) + igap
    return x


def _anchor_fit(x: float, w: float, lo: float, hi: float, inset: float):
    """居中标签近边缘改对齐：左缘先查，越界改 start/end 且锚点内缩 inset
    （走廊现价标签 / PE 带当前值标签）。返回 (text-anchor, x)。"""
    if x - w / 2 < lo:
        return "start", max(x - inset, lo)
    if x + w / 2 > hi:
        return "end", min(x + inset, hi)
    return "middle", x


def _anchor_clamp(x: float, w: float, lo: float, hi: float):
    """居中标签近边缘改对齐：右缘先查，越界直接夹到 hi/lo 边界
    （走廊中枢标签 / 卖方一致带标签 / PE 带关键时点标签）。返回 (text-anchor, x)。"""
    if x + w / 2 > hi:
        return "end", hi
    if x - w / 2 < lo:
        return "start", lo
    return "middle", x


def _inject_chart_anchors(html: str, items: tuple, owner: str, tail: str, hint: str,
                          prepend: bool = False) -> str:
    """图表锚点注入（第 4 / 5 / 9 章共用）：items 为 (锚点注释, 图 HTML, 字段名) 序列，
    锚点在 → 原位替换；锚点缺失但字段已填 → 图追加到章末尾 + stderr 告警（prepend=True 时
    改为垫到片段开头，第 9 章预期差图用——图是本章主体，堆在结论框后不成章）；字段未填 →
    锚点静默清除（图返回空串）。owner=正文变量名、tail=追加位置描述、hint=锚点摆放建议，
    只用于告警文案。"""
    for anchor, chart_html, field in items:
        if anchor in html:
            html = html.replace(anchor, chart_html)
        elif chart_html:
            html = chart_html + "\n" + html if prepend else html + "\n" + chart_html
            print(f"⚠️ {owner} 缺 {anchor} 锚点：{field} 图已追加到{tail}（{hint}）", file=sys.stderr)
    return html


# 供图族模块 `from charts_base import *` 拉取全部基座符号（含下划线名，
# 免逐名漏列——v4.9 拆分初版曾漏 _C_INK 致 NameError）
__all__ = [
    "_C_LABEL", "_C_GRID", "_C_AXIS", "_C_BLUE", "_C_PAPER", "_C_INK", "_C_BLACK",
    "_C_STONE", "_C_OLIVE", "_C_SAND", "_C_SAND_LT", "_C_TRACK", "_C_PAPER_CELL",
    "_C_GOOD_LINE", "_C_YEAR_GRID", "_C_GREEN", "_C_RED", "_C_ORANGE", "_C_BADGE_DEEP",
    "_fmt_px", "_fmt_amt", "_SCENARIO_COLORS", "_prev_track_rows",
    "_var_key", "_sensitivity_items", "_first_var_name", "_gap_dim_ok", "_period_ratio",
    "parse_stage_period", "_PERIOD_VERDICTS", "_arrow_dumbbell",
    "_SOURCE_BANNED_RE", "_chart_source",
    "_pad_domain", "_lin_map", "_text_w", "_wrap_label", "_ticks", "_open_ticks",
    "_SVG_STYLE", "_svg_open", "_svg_close", "_vgrid_ticks", "_hgrid_ticks", "_legend_row",
    "_inject_chart_anchors", "_anchor_fit", "_anchor_clamp",
]
