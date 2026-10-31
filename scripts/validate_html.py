#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""validate_html.py — 正文 HTML 纪律校验域（v5.8.3 自 validate.py 按域拆分）。

内容：内容地板/空心章节、dim-block 地板与极端分证据、写作纪律、结论四卡、
治理条单行化、同业五查（plot_target/selection/orientation/bestworst/column_support）、
thesis 价格标注与信息量、L4 形态、中文占位符、内部代号泄漏、手写表并存检测、
红灯熔断/结论存疑、必填字段，及表格切分三生成器/dim-block 切分/列名归一等工具。
契约：raise = 硬拒渲染；warns.append = 软告警。
"""
import re
from scoring import (
    DIMS,
    _num,
    _plain_text,
    _LABEL_REFUSE,
    _cn_placeholders,
    _quality_version)
from charts_base import (
    _C_BLUE,
    _sensitivity_items,
    _gap_dim_ok)
from validate_common import (
    _HTML_FIELDS,
    _HTML_TABLE_FIELDS,
    _quote_ref,
    _scenario_by_key)


# v4.11.1（审核 D8）：dim-block 切块正则容忍附加类（class="dim-block extra"），
# 三处消费方（内容地板/维度块校验/治理条）收敛同一 helper，口径唯一
_DIM_BLOCK_RE = r'<div class="dim-block(?=[\s"])\s*[^>]*>'


# v5.5.0 B5：dim-block 正文体 = 剥「标题行（含编号与分值徽章）」+「评分末拍」，同样容忍附加类/属性
# （两者都自带数字，不剥则「正文有无数字」的判定恒为真——合规报告上永不触发，B5 曾空转）
_DIM_HEADER_RE = re.compile(r'<div\b[^>]*class="[^"]*\bdim-header\b[^"]*"[^>]*>.*?</div>\s*', re.S)


_SCORE_BEAT_RE = re.compile(r'<p\b[^>]*>\s*<strong\b[^>]*>\s*评分(?:依据)?\s*[：:]\s*</strong>.*?</p>\s*', re.S)


def _split_dim_blocks(frag: str) -> list:
    """切出全部 dim-block 片段（不含首段前导部分）。附加类形态（dim-block xxx）一并识别。"""
    return re.split(_DIM_BLOCK_RE, frag or "")[1:]


def _dim_body_text(blk: str) -> str:
    """dim-block 正文体纯文本（剥标题行与评分末拍）——B5 数字义务判定的取数口径。"""
    return _plain_text(_SCORE_BEAT_RE.sub("", _DIM_HEADER_RE.sub("", blk or "")))


def _check_red_flag_breaker(fill: dict) -> None:
    """红灯熔断：red_flag 非空 → position_html 必须包含「不建议参与」。"""
    red_flag = (fill.get("red_flag") or "").strip()
    pos_html = fill.get("position_html") or ""
    if red_flag and _LABEL_REFUSE not in _plain_text(pos_html):
        raise ValueError(f"红灯熔断：red_flag「{red_flag}」非空，position_html 必须包含「{_LABEL_REFUSE}」结论")


def _check_content_floor(fill: dict) -> None:
    """内容地板（空心章节一律拒渲染）+ 表格来源标注数必须 ≥ 表格数。"""
    concl_len = len(_plain_text(fill.get("conclusion_html")))
    if concl_len < 120:
        raise ValueError(f"conclusion_html 纯文本仅 {concl_len} 字 < 120：核心结论四卡不能为空洞"
                         f"（v4.9.1 补充修订四：四卡 ul 短列表化，地板由 200 下调）")
    for name, need in (("l1_html", 6), ("l3_html", 3)):
        # 与下方字数地板同口径（_split_dim_blocks），避免 class="dim-block x" 之类写法两口径打架
        n = len(_split_dim_blocks(fill.get(name) or ""))
        if n < need:
            raise ValueError(f"{name} 仅 {n} 个 dim-block < {need}：每个评分维度必须各有一个维度块")
    if "<table" not in (fill.get("peers_html") or ""):
        raise ValueError("peers_html 不含 <table>：同业对比必须有数据表")
    pos_html = fill.get("position_html") or ""
    pos_len = len(_plain_text(pos_html))
    if pos_len < 100:
        raise ValueError(f"position_html 纯文本仅 {pos_len} 字 < 100：仓位决策四步不能为空洞")
    # 含表格的章节字段：source 来源标注数必须 ≥ 表格数
    for name in _HTML_TABLE_FIELDS:
        frag = fill.get(name) or ""
        n_tbl = frag.count("<table")
        n_src = sum("source" in (m.group(1) or m.group(2) or m.group(3) or "").lower().split()
                    for m in re.finditer(
                        r'(?<![-\w:])class\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))', frag, flags=re.I))
        if n_tbl and n_src < n_tbl:
            raise ValueError(f"{name} 含 {n_tbl} 张数据表但只有 {n_src} 个 `.source` 来源标注："
                             f"每张表下方必须有来源标注——在缺口表格下方补 "
                             f'<span class="source">数据来源：…</span> 后重新渲染'
                             f"（报错后禁止绕过脚本手写全文 HTML，只能修 fill 重渲）")


def _check_thesis_price_tags(fill: dict, warns: list) -> None:
    """thesis 三情景价格标注完整性。"""
    th = fill.get("thesis_html", "")
    if th and not any(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        # 价格形态只认带「元」的数字组（含 15.7/37.5/61.8 元 斜杠组）——年份区间
        # 「2023-2025」、数量区间「3-5 家」「10%-15%」不带元，不误拒（热核 P0-1）
        price_nums = 0
        for pm in re.finditer(r"(\d+(?:\.\d+)?(?:\s*[-–~/]\s*\d+(?:\.\d+)?)*)\s*元", th):
            price_nums += len(re.findall(r"\d+(?:\.\d+)?", pm.group(1)))
        if price_nums >= 2:
            raise ValueError("thesis_html 含价格形态但三情景 span（scenario-pess/base/opt）全缺："
                             "手写价绕过了与 valuation 的一致性硬校验（v5.1.2 起拒渲染）——"
                             "三价必须写入 span 由脚本对账")
    if th and not all(c in th for c in ("scenario-pess", "scenario-base", "scenario-opt")):
        warns.append("thesis_html 缺三情景价格标注（scenario-pess/base/opt span 未齐）")


def _check_thesis_info_floor(fill: dict, warns: list) -> None:
    """thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格。"""
    # thesis 信息量地板：Hero 一句话是全文提纲挈领，不能只塞三个价格
    # （中兴 2026-08-24 实证：thesis 只有"12个月目标价：悲观/基础/乐观"）
    th = fill.get("thesis_html", "")
    th_txt_len = len(_plain_text(th))
    if th_txt_len:
        th_no_price = re.sub(r'<span\b[^>]*class="[^"]*\bscenario-(?:pess|base|opt)\b[^"]*"[^>]*>.*?</span>',
                             "", th, flags=re.I | re.S)
        th_rest = len(_plain_text(th_no_price))
        if th_txt_len < 60 or th_rest < 20:
            warns.append(f"thesis_html 信息量不足（纯文本 {th_txt_len} 字，剥掉三情景价后仅 {th_rest} 字）："
                         f"一句话结论 = 论点 + 关键证据 + 三情景价 + 研究结论，不能只塞目标价")


def _check_peers_plot_target(fill: dict, warns: list) -> None:
    """peers_plot 目标公司标记 + 目标点 PE/ROE 与数据口径一致性告警（不拒渲染）。"""
    pp = fill.get("peers_plot")
    if pp is not None and not isinstance(pp, dict):
        raise ValueError("peers_plot 必须为 {points, pe_bands, roe_bands} 对象，数组简写已废止")
    pts = (pp or {}).get("points") or []
    if pts:
        # v5.1.2：比对对象与渲染同源——渲染只画 roe/pe 可解析的点（charts_scenario），
        # 不可解析的 target 点不落图（此前拿原始数组第一个 target 点比对）
        tg_all = [p for p in pts if isinstance(p, dict) and p.get("target")]
        tg = [p for p in tg_all
              if _num(p.get("roe")) is not None and _num(p.get("pe")) is not None]
        if not tg_all:
            warns.append("peers_plot 没有 target=true 的目标公司点")
        else:
            if len(tg_all) > 1:
                warns.append(f"peers_plot 共 {len(tg_all)} 个 target=true 点（应恰 1 个）："
                             "图中会出现多个钢蓝目标点，请只保留目标公司")
            if not tg:
                warns.append("peers_plot 目标点 roe/pe 均不可解析：图中无蓝色目标点"
                             "（渲染丢弃），请核对 target 点数据")
            elif fill.get("company") and str(fill.get("company")) not in str(tg[0].get("name", "")):
                warns.append(f"peers_plot 目标点名称「{tg[0].get('name')}」与公司名「{fill.get('company')}」不一致")
        # 口径一致性（赤峰 2026-09-02 实证：图中目标点用 A 股 PE 23.58x，正文用 H 股 18.6x）
        if tg:
            tpe = _num(tg[0].get("pe"))
            vpe = _num((fill.get("valuation_inputs") or {}).get("pe_ttm"))
            if tpe and vpe and abs(tpe - vpe) / abs(vpe) > 0.3:
                warns.append(f"peers_plot 目标公司 PE（{tpe:g}）与 valuation_inputs.pe_ttm（{vpe:g}）偏差 >30%："
                             f"请确认口径一致（A/H 股、IFRS/经调整、TTM/预测），确需混排在 peers_meta 注明")
            # ROE 量级倒挂（v4.9）：fill 无独立 ROE 参照源可比对（E1 落盘无 roe、正文为文字），
            # 只对「目标点 ROE 明显脱离同业量级」这类机械异常告警——目标比最弱同业还低一半、
            # 或比最强同业高一倍，几乎必是口径不一（年报 vs TTM/加权、不同年份）或取数错误
            troe = _num(tg[0].get("roe"))
            peers_roe = [_num(p.get("roe")) for p in pts
                         if isinstance(p, dict) and not p.get("target")
                         and _num(p.get("roe")) is not None and _num(p.get("roe")) > 0]
            if troe is not None and troe > 0 and len(peers_roe) >= 2:
                p_lo, p_hi = min(peers_roe), max(peers_roe)
                meta = str(fill.get("peers_meta") or "")
                explained = ("目标" in meta and "ROE" in meta
                             and any(word in meta for word in ("一次性", "非经常性", "扣非"))
                             and any(word in meta for word in ("年报", "TTM", "加权", "静态", "经调整")))
                if (troe < p_lo / 2 or troe > p_hi * 2) and not explained:
                    warns.append(f"peers_plot 目标公司 ROE（{troe:g}%）脱离同业量级（同业 {p_lo:g}-{p_hi:g}%）"
                                 f"——ROE 口径疑似不一（年报/加权/TTM、不同年份）或取数错误，请核对")


def _peers_name_key(s: str) -> str:
    """同业名归一（表图一致比对键，v5.4.0 热核审计）：去括号注（（…）/(…)）、空白（含全角）
    与尾部交易所标记（-U 未盈利/-W 同股不同权/-SW 二次上市等）——「宁德时代（CATL）」
    ≡「宁德时代」、「百济神州-U」≡「百济神州」（恒瑞 2026-09-19 存量实证：表图两处同一家
    公司带了没带 -U 后缀）；近似名不互相放行——此前双向子串匹配会把「比亚迪」与
    「比亚迪电子」当同一家，是硬门禁的假阴性口。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", str(s or ""))
    s = re.sub(r"[\s\u3000]+", "", s)
    return re.sub(r"-(?:SW|WD|U|W|S)$", "", s, flags=re.I)


# v5.8.2：HTML 表格切分骨架单源（5 处 <table> 切分、6 处行/格切分复制收敛）——
# 统一口径：整表文本 / 行内容（tr 内部）/ 格内容（cell 内部），全部 re.I | re.S
_TBL_SPLIT_RE = re.compile(r"<table\b[^>]*>.*?</table>", re.I | re.S)


_TR_SPLIT_RE = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.I | re.S)


_TD_SPLIT_RE = re.compile(r"<t[hd]\b[^>]*>(.*?)</t[hd]>", re.I | re.S)


def _iter_tables(html: str):
    """逐表切出整表文本（生成器）——<table> 切分单源（v5.8.2）。
    bestworst 处的旧捕获组写法 group(0)==group(1)（组括号罩住全模式），
    整表文本即等价承载，捕获组语义不丢失。"""
    return (m.group(0) for m in _TBL_SPLIT_RE.finditer(html or ""))


def _iter_rows(tbl: str):
    """表内逐行切出行内容（生成器）——口径同各 <tr> 切分：元素为 tr 内部文本。
    需要下标/len 的调用点自行 list() 物化。"""
    return (m.group(1) for m in _TR_SPLIT_RE.finditer(tbl or ""))


def _row_cells(tr: str):
    """行内逐格切出格内容（生成器）——口径同各 <t[hd]> 切分：元素为 cell 内部文本。
    唯一消费格属性（cell-best/cell-worst 写在 <td …> 属性串）的 bestworst 处保留其
    专属双捕获正则不并入本 helper（v5.8.2——不为统一而改语义）。"""
    return (m.group(1) for m in _TD_SPLIT_RE.finditer(tr or ""))


def _check_peers_selection(fill: dict, warns: list) -> None:
    """v5.4.0 peer 选取硬化（五条，与 peers_plot/peers_meta/peers_html 三方对账）：
    ⑨表图一致（**拒渲染**）：peers_plot 非 target 点必须出现在 peers_html **非 matrix-table
      的表**的行首格（名字归一后精确相等），或名点写进 peers_meta（= 已声明剔出理由）；
      未声明的名字 → 拒渲染，target 点豁免。九宫格兜底表（行=ROE 档、公司名在单元格里）
      不作名字来源、且渲染器会删除它——peers_html 只剩 matrix-table 时整条检查跳过
      （审计 P0-1：同存路径此前把九宫格行首档位名当公司名 → 误拒）。
    ⑩尺子一致（告警）：target 点 roe 与 fin_trend 的 ROE 线末值 >3pct 且 peers_meta 无
      「口径词（TTM/加权/经调整/静态）+ 点名目标」双命中的注明 → 告警。
    ⑪peer ≥3（告警）：非 target 有效点（name+roe+pe 可解析）<3 → 告警；peers_meta 已写明
      凑不齐原因（含「仅/凑不齐/可比公司不足」）→ 抑制（与「meta 注明后可忽略」惯例一致）。
    ⑫rationale（软告警）：有 peer 章节实体（peers_plot 或非占位 peers_meta）时即检查——
      peers_meta 须含两把尺（同行业/同规模/同商业模式 ≥2 种）+ 排除语（排除/未选/剔出），
      缺一告警（占位「—」由 _check_required_fields 的占位告警兜底，不重复报）。
    ⑬PE 交叉（软告警）：valuation base 情景 pe 下限高于全部非 target 点 pe → 须溢价论证。
    数据缺失的分支一律跳过（不误报）。"""
    meta = str(fill.get("peers_meta") or "")
    pp = fill.get("peers_plot")
    pts = (pp or {}).get("points") or [] if isinstance(pp, dict) else []
    # ⑨ 表图一致（硬）：非 matrix-table 表内公司名集合（归一）+ peers_meta 声明名单
    if pts:
        tbl_names, n_plain = set(), 0
        for tbl in _iter_tables(fill.get("peers_html") or ""):
            if "matrix-table" in tbl:
                continue
            n_plain += 1
            for tr in _iter_rows(tbl):
                cells = list(_row_cells(tr))
                key = _peers_name_key(_plain_text(cells[0])) if cells else ""
                if key:
                    tbl_names.add(key)
        if n_plain:
            undeclared = []
            for p in pts:
                if not isinstance(p, dict) or p.get("target"):
                    continue
                nm = str(p.get("name") or "").strip()
                if not nm or nm in meta or _peers_name_key(nm) in tbl_names:
                    continue
                undeclared.append(nm)
            if undeclared:
                raise ValueError("peers_plot 点位未出现在 peers_html 表格、peers_meta 亦无声明："
                                 + "、".join(undeclared)
                                 + "——表图一致纪律（v5.4.0，拒渲染）：散点图每家同业必须在当前指标表/"
                                   "趋势表有一行，或在 peers_meta 点名说明未列/剔出理由"
                                   "（target 点豁免；matrix-table 九宫格不作名字来源）")
    # ⑩ 尺子一致（告警）：散点图 ROE vs fin_trend ROE 线末值
    tg = [p for p in pts if isinstance(p, dict) and p.get("target")
          and _num(p.get("roe")) is not None]
    roe_ref = None
    for p in (fill.get("fin_trend") or {}).get("panels") or []:
        if not isinstance(p, dict):
            continue
        for ln in p.get("lines") or []:
            if isinstance(ln, dict) and "ROE" in str(ln.get("name") or ""):
                vals = [_num(v) for v in (ln.get("values") or [])]
                if vals and vals[-1] is not None:
                    roe_ref = vals[-1]
                    break
        if roe_ref is not None:
            break
    if tg and roe_ref is not None:
        troe = _num(tg[0].get("roe"))
        # 口径注明须「口径词 + 点名目标」双命中（热核审计 P2：裸「口径」是万能逃生口——
        # 只在偏离存在时才需要注明，而偏离的正当理由必然指向目标公司的特殊口径）
        co = str(fill.get("company") or "")
        calib_noted = (re.search(r"TTM|加权|经调整|静态", meta)
                       and bool((co and co in meta) or "目标" in meta))
        if abs(troe - roe_ref) > 3 and not calib_noted:
            warns.append(f"peers_plot 目标点 ROE（{troe:g}%）与 fin_trend ROE 线末值（{roe_ref:g}%）"
                         f"绝对差 {abs(troe - roe_ref):.1f}pct > 3pct：两处口径须一致——"
                         f"在 peers_meta 注明目标公司口径（含 TTM/加权/经调整/静态并点名目标公司）"
                         f"或改齐数据后重渲")
    # ⑪ peer ≥3（告警）：有效同业点计数（peers_meta 已写明凑不齐原因 → 抑制，同「注明后可忽略」惯例）
    peer_pts = [p for p in pts if isinstance(p, dict) and not p.get("target")
                and str(p.get("name") or "").strip()
                and _num(p.get("roe")) is not None and _num(p.get("pe")) is not None]
    if pts and len(peer_pts) < 3 and not re.search(r"仅|凑不齐|可比公司不足", meta):
        warns.append(f"peers_plot 有效同业点仅 {len(peer_pts)} 家（<3）：同业对比至少 3 家可比公司"
                     f"（表与散点同源）——凑不齐请在 peers_meta 写明原因（如「可比公司仅 2 家」）")
    # ⑫ rationale（软告警）：三选二 + 排除语；有 peer 章节实体即检查（占位「—」由占位告警兜底）
    if pts or meta.strip() not in ("", "—"):
        kinds = [k for k in ("同行业", "同规模", "同商业模式") if k in meta]
        if len(kinds) < 2 or not re.search(r"排除|未选|剔出", meta):
            warns.append(f"peers_meta 选取理由不完整（现含 {'/'.join(kinds) or '无'}；"
                         f"{'有' if re.search(r'排除|未选|剔出', meta) else '缺'}排除语）："
                         f"须含「同行业/同规模/同商业模式」≥2 种 + 「排除/未选/剔出」说明"
                         f"（为何不选近邻标的）")
    # ⑬ PE 交叉（软告警）：基础带下限高于全部同业 PE
    base_pe = None
    _base_sc = _scenario_by_key((fill.get("valuation") or {}).get("scenarios"), "base")
    if _base_sc:
        pe = _base_sc.get("pe") or []
        base_pe = _num(pe[0]) if len(pe) >= 1 else None
    peer_pes = [_num(p.get("pe")) for p in pts
                if isinstance(p, dict) and not p.get("target") and _num(p.get("pe")) is not None]
    premium_explained = re.search(r"溢价来源[：:]\s*\S", _plain_text(fill.get("valuation_html") or ""))
    if base_pe is not None and peer_pes and base_pe > max(peer_pes) and not premium_explained:
        warns.append(f"valuation 基础情景 PE 下限（{base_pe:g}x）高于全部同业散点 PE"
                     f"（最高 {max(peer_pes):g}x）：基础带高于全部同业，须溢价论证"
                     f"（在 valuation_html 写明溢价来源：护城河/成长差/资产质量）")


def _report_rule_problem(fill: dict, warns: list, message: str) -> None:
    if str(fill.get("date") or "") >= "2026-10-26":
        raise ValueError(message)
    warns.append(f"旧 fill 兼容：{message}")


def _check_timing_table_cells(fill: dict, warns: list) -> None:
    """时机判定小表单元格超长告警（长句塞格会溢出横向滚动；长解释应挪到表下 .source 行）。
    v5.1.2：小表「筹码面/技术面」得分 vs timing_scores 数值比对（>0.1 告警）；技术面信号中的
    现价/MA60/MA120/52 周高低 数值与方向词 vs quote 落盘 timing（神华假 MA60 修复闭环——信号取自落盘、
    禁手估，数值偏差 >1% 或方向矛盾告警；自由文本全量语义比对不做）。"""
    pos_html = fill.get("position_html") or ""
    for tbl in _iter_tables(pos_html):
        if "技术面" not in tbl or "筹码面" not in tbl:
            continue
        for cell in _row_cells(tbl):
            if len(_plain_text(cell)) > 40:
                warns.append("时机判定小表存在 >40 字单元格：只写短语（≤15 字/条），"
                             "长解释与降级说明挪到表下 .source 行（fill-schema 固定 4 行 3 列格式）")
                break
        # 缺子维时整轨缺分；小表该行与合计都不得保留中性数值
        ts = fill.get("timing_scores") or {}
        dims = ("筹码面", "技术面")
        missing_total = any(ts.get(dim) is None for dim in dims)
        for tr in _iter_rows(tbl):
            cells = [_plain_text(c) for c in _row_cells(tr)]
            if len(cells) < 2:
                continue
            if "合计" in cells[0]:
                if missing_total and re.search(r"\d", cells[1]):
                    _report_rule_problem(fill, warns, "时机判定小表合计在缺子维时仍写数值分，"
                                                      "总分必须为数据不足")
                continue
            for dim in dims:
                if dim in cells[0]:
                    sm = re.search(r"\d+(?:\.\d+)?", cells[1])
                    ref_s = _num(ts.get(dim))
                    if sm and ref_s is None:
                        _report_rule_problem(fill, warns, f"时机判定小表「{dim}」缺数据却仍写数值分，"
                                                           "应改为数据不足")
                    elif sm and ref_s is not None and abs(float(sm.group(0)) - ref_s) > 0.1:
                        warns.append(f"时机判定小表「{dim}」得分（{sm.group(0)}）与 timing_scores"
                                     f"（{ref_s:g}）不一致（>0.1）：两处应同源（v5.1.2）")
        # v5.1.2：信号数字/方向 vs 落盘 timing（神华假 MA60 同源修复闭环）
        # v5.1.5（热核 P0-1，文档虚言闭合）：52 周高低补入比对（fill-schema/SKILL 承诺的
        # 技术面信号四件套此前只查三键）——「52周高低 高/低」合并写法（照抄 E1 时机素材行
        # 形态）与「52周高 X」「52周低 X」分拆写法都认；方向词比对仍只做 MA60/MA120
        ref_t = (_quote_ref(fill) or {}).get("timing") or {}
        rp = _num(ref_t.get("price"))
        txt = _plain_text(tbl)
        for hi_s, lo_s in re.findall(r"52周高低\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*[/／]\s*(\d+(?:\.\d+)?)", txt):
            for lbl, v_s, rv2 in (("52周高", hi_s, _num(ref_t.get("high_52w"))),
                                  ("52周低", lo_s, _num(ref_t.get("low_52w")))):
                if rv2 and abs(float(v_s) - rv2) / rv2 > 0.01:
                    warns.append(f"时机小表信号 {lbl}={v_s} 与落盘值 {rv2:g} 偏差 >1%："
                                 "技术面信号一律取自 quote 落盘 timing、禁手估（v5.1.2）")
        for label, rv in (("现价", rp), ("MA60", _num(ref_t.get("ma60"))),
                          ("MA120", _num(ref_t.get("ma120"))),
                          ("52周高", _num(ref_t.get("high_52w"))),
                          ("52周低", _num(ref_t.get("low_52w")))):
            if not rv:
                continue
            pat = ("52周高(?!低)" if label == "52周高" else label) + r"\s*[:：=]?\s*(\d+(?:\.\d+)?)"
            for nm_ in re.findall(pat, txt):
                if abs(float(nm_) - rv) / rv > 0.01:
                    warns.append(f"时机小表信号 {label}={nm_} 与落盘值 {rv:g} 偏差 >1%："
                                 "技术面信号一律取自 quote 落盘 timing、禁手估（v5.1.2）")
            if label not in ("MA60", "MA120") or not rp:
                continue
            up = re.search(r"(站上|突破|收复|高于|上穿).{0,6}" + label, txt, re.S) or \
                re.search(label + r".{0,4}(上方|之上)", txt, re.S)
            down = re.search(r"(跌破|失守|低于|下穿).{0,6}" + label, txt, re.S) or \
                re.search(label + r".{0,4}(下方|之下)", txt, re.S)

            def _now(m):
                """命中词所在句不含翻转/过去时标记才算现在时叙述（热核 P1-5：
                「9 月曾跌破 MA60，现已收复」与落盘现价>MA60 一致，不应误报）。"""
                for seg in re.split(r"[，。；、]", txt):
                    if m.group(0) in seg:
                        return not re.search(r"曾|收复|回升|重返|现已", seg)
                return True
            if up and rp < rv and _now(up):
                warns.append(f"时机小表信号「{label} 上方/站上」与落盘矛盾：现价 {rp:g} < "
                             f"{label} {rv:g}（v5.1.2）")
            if down and rp > rv and _now(down):
                warns.append(f"时机小表信号「{label} 下方/跌破」与落盘矛盾：现价 {rp:g} > "
                             f"{label} {rv:g}（v5.1.2）")


def _check_research_actions(fill: dict, warns: list) -> None:
    """新报告不给加减仓或分批节奏；旧正文保留但显示兼容提示。"""
    for field in ("dash_html", "position_html", "thesis_html"):
        text = _plain_text(fill.get(field) or "")
        matched = False
        for term in ("加仓", "减仓", "满仓", "清仓", "分批"):
            for match in re.finditer(term, text):
                prefix = text[max(0, match.start() - 8):match.start()]
                negated = (prefix.endswith(("不", "禁止", "不得", "勿", "避免", "不宜", "不采用", "不建议"))
                           or re.search(r"不触发[^，。；、]{0,4}$", prefix))
                if not negated:
                    matched = True
                    break
            if matched:
                break
        if matched:
            _report_rule_problem(fill, warns,
                f"{field} 含交易节奏：研究动作只能写复核、证伪或重估，"
                "不写加仓/减仓/分批买卖")


def _check_v2_counter_evidence(fill: dict, sc: dict = None) -> None:
    if not sc or sc.get("quality_version") != 2:
        return
    missing = []
    for key, result in (sc.get("dimension_results") or {}).items():
        score = result.get("final")
        if score is None or not (score >= 8 or score <= 3):
            continue
        evidence = (sc.get("score_inputs", {}).get(key) or {}).get("counter_evidence")
        if not evidence or len(str(evidence).strip()) < 4:
            missing.append(f"{key} 得分 {score:g} 属于极端分，必须提供可观察反方证据")
    if missing:
        raise ValueError("\n".join(missing))


def _check_dim_blocks(fill: dict, warns: list, sc: dict = None) -> None:
    """dim-block 内容地板（纯文本 <40 字拒渲染 / <80 字告警）与极端分证据校验。"""
    # dim-block 内容地板（deepseek 中兴/豪威"每块一句话凑数"缩水实证）：
    # 纯文本 <40 字 → 拒渲染（连一条论据都写不出）；<80 字 → 告警。
    # 同循环保留极端分证据校验：≥8 或 ≤3 的维度，dim-block 纯文本 <50 字 → 告警（极端分须配量化依据）
    # v4.11.1（审核 D3）：维度识别废位置 zip——乱序块会被错配（极端分门槛被静默绕过）；
    # 改与 _check_governance_strip 同口径，从 dim-name 提取 `\d\.\d` 编号映射 DIMS；
    # 提取不到编号 → 按位置兜底并告警（写法漂移可见，不静默）
    if _quality_version(fill) == 2:
        missing_beats = []
        for field in ("l1_html", "l3_html"):
            for blk in _split_dim_blocks(fill.get(field) or ""):
                name_match = re.search(r'dim-name[^>]*>\s*(\d\.\d[^<]*)', blk)
                name = name_match.group(1).strip() if name_match else "未命名维度"
                text = _dim_body_text(blk)
                missing = []
                if not re.search(r"判词\s*[：:]", text):
                    missing.append("判词")
                if not re.search(r"\d", text):
                    missing.append("量化论据")
                if not re.search(r"对比\s*[：:]", text):
                    missing.append("对比")
                if missing:
                    missing_beats.append(f"{name} 缺 {'/'.join(missing)}")
        if missing_beats:
            message = ("九维正文三要素缺失：" + "；".join(missing_beats)
                       + "——每块须有判词、量化论据和明确对比，评分依据详情不计入正文")
            if str(fill.get("date") or "") >= "2026-10-31":
                raise ValueError(message)
            warns.append(message)

    thin_reject, thin_warn = [], []
    for field, layer in (("l1_html", "L1"), ("l3_html", "L3")):
        blocks = _split_dim_blocks(fill.get(field) or "")
        dims = [d for d in DIMS if d[1] == layer]
        by_num = {d[2].split()[0]: d for d in dims}   # "4.1 赛道与宏观" → "4.1"
        fallback = 0
        for pos, blk in enumerate(blocks):
            m = re.search(r'dim-name[^>]*>\s*(\d\.\d)', blk)
            if m and m.group(1) in by_num:
                key, name = by_num[m.group(1)][0], by_num[m.group(1)][2]
            elif pos < len(dims):
                key, name = dims[pos][0], dims[pos][2]
                fallback += 1
            else:
                key, name = None, f"第 {pos + 1} 块"
            blen = len(_plain_text(blk))
            if blen < 40:
                thin_reject.append(f"{name} 仅 {blen} 字")
            elif blen < 80:
                thin_warn.append(f"{name} 仅 {blen} 字")
            if key is None:
                continue
            if sc and sc.get("quality_version") == 2:
                sv = (sc.get("dimension_results") or {}).get(key, {}).get("final")
            else:
                sv = (fill.get("scores") or {}).get(key)
            if sv is None:
                continue
            sv = float(sv)
            if (sv >= 8 or sv <= 3) and blen < 50:
                warns.append(f"{name} 得分 {sv:g}（极端分）但 dim-block 纯文本仅 {blen} 字 < 50："
                             f"≥8 或 ≤3 必须配具体量化依据")
            # v5.5.0 B5：无项目型 3B 高分（≥6.5）要求可见度证据带数字（指标+数值）——
            # 无项目型实测塌缩（86% 落 6.0-7.0），纯叙事给高分是档位失效的入口。
            # 取数口径=正文体（剥标题/徽章/评分末拍，见 _dim_body_text）：三者都自带数字，
            # 不剥则判定恒为真、门禁空转（v5.5.0 热核审计 P0）
            if key == "3B" and sv >= 6.5:
                btxt = _dim_body_text(blk)
                if re.search(r"无项目型|无重资产|存量扩张", btxt) and not re.search(r"\d", btxt):
                    warns.append(f"{name} 得分 {sv:g}（无项目型 ≥6.5）但 5.2 块正文"
                                 "（剥标题/徽章/评分末拍）无任何数字：可见度打分须带数字——"
                                 "合约级=已签约/在手订单额/合同负债，存量扩张=两融余额/保有客户/"
                                 "会员/ARR/订单 backlog 的指标值；纯叙事只能落 <5.0 档"
                                 "（scoring.md 3B 无项目型四档，v5.5.0 B5）")
        if fallback:
            warns.append(f"{field} 有 {fallback} 个 dim-block 未从 dim-name 提取到有效编号，"
                         f"已按位置兜底匹配——dim-name 请写「编号+名称」规范形态（如 4.1 赛道与宏观），"
                         f"乱序块的极端分证据校验依赖编号识别")
    if thin_reject:
        raise ValueError("dim-block 内容地板：" + "；".join(thin_reject)
                         + "（纯文本 <40 字）：每个维度块至少写出论据+数据，不能只写一句判语")
    if thin_warn:
        warns.append("dim-block 内容偏薄（纯文本 <80 字）：" + "；".join(thin_warn)
                     + "——每个维度块应有论据、数据与判词，薄块请补写后重渲")


def _check_internal_codes(fill: dict, warns: list) -> None:
    """框架内部代号泄漏检查：正文引用只准用章节编号/名称（L1/L3/L4/1D 代号禁入正文）。"""
    # "L1:L3" 占比记法是分型声明的合法写法，先剥离再检查
    for name in _HTML_FIELDS:
        txt = _plain_text(fill.get(name) or "").replace("L1:L3", "")
        hits = sorted(set(re.findall(r"(?<![A-Za-z0-9])(?:L[134]|1D)(?![A-Za-z0-9])", txt)))
        if hits:
            warns.append(f"{name} 正文出现框架内部代号 {'/'.join(hits)}："
                         f"请改用章节编号/名称（第 4 章 / 4.4 / 第 6 章风险评估）")


def _check_writing_discipline(fill: dict, warns: list) -> None:
    """v4.7.1 写作纪律告警（东方电气反馈）：四拍挤段 / 3 年趋势三年并排。
    （pe_history 无第 11 章承载告警已迁 _check_ch11_binding 表驱动，v5.8.2）"""
    # 三要素可并入既有段落；评分末拍仍须独立，避免手写评分与正文论证混成一段。
    beats = ("判词：", "论据：", "对比：", "评分：", "评分依据：")
    for name in ("l1_html", "l3_html"):
        for pm in re.finditer(r"<p[^>]*>(.*?)</p>", fill.get(name) or "", flags=re.S):
            hits = sum(1 for b in beats if b in pm.group(1))
            if ("评分：" in pm.group(1) or "评分依据：" in pm.group(1)) and hits >= 2:
                warns.append(f"{name} 存在四拍挤段（单段含 {hits} 个拍名）："
                             f"评分末拍应独立成段；判词/论据/对比可并入既有段落")
                break  # 每字段报一次即可
    # 3 年趋势表只写 起→终（方向词）：三年数字并排反而看不出趋势
    peers = fill.get("peers_html") or ""
    if "<table" in peers:
        yseq = []
        for tm in re.finditer(r"<th[^>]*>(.*?)</th>", peers, flags=re.S):
            t = re.sub(r"<[^>]+>", "", tm.group(1)).strip()
            yseq.append(bool(re.fullmatch(r"20\d{2}年?", t)))
        stacked = any(len(re.findall(r"20\d{2}\s*[：:]", cdm.group(1))) >= 2
                      for cdm in re.finditer(r"<td[^>]*>(.*?)</td>", peers, flags=re.S))
        if any(yseq[i] and yseq[i + 1] and yseq[i + 2] for i in range(len(yseq) - 2)) or stacked:
            warns.append("3 年趋势表疑似三年数字并排：应写「起→终（方向词）」"
                         "（如 8.0→30.8（大升），方向词按指标语义着色），见 fill-schema 趋势表规则")
    # pe_history 图已挂第 11 章（v4.7.1）→ 「已填但 cycle_html 缺失」告警迁 _check_ch11_binding
    # 表驱动（v5.8.2，与 price_history/cycle_stages 同骨架单源）


def _check_required_fields(fill: dict, warns: list) -> None:
    """fill-schema 标 ✓ 但渲染器原零校验的必填字段缺失告警（v5.8.2 合并 _check_missing_required_warns：
    thesis_html 与 misc 各字段单源）。全部软告警不拒——缺失只会让对应章节标题/指标卡
    显示空白或占位符（yellow_deductions 缺项由 compute_scores 硬拒；时机缺子维显示数据不足，不在此列）。"""
    th = fill.get("thesis_html", "")
    if not th.strip():
        warns.append("thesis_html 缺失：Hero 一句话结论为空")
    for name in ("valuation_method", "stock_type", "gap_tier", "peers_meta", "next_review"):
        if not str(fill.get(name) or "").strip() or fill.get(name) == "—":
            warns.append(f"{name} 缺失或为占位符：对应章节标题/meta 将为空白")
    if not (fill.get("subtitle") or "").strip():
        warns.append("subtitle 缺失：Hero 副标题为空")
    elif "报告日期" in fill["subtitle"]:
        warns.append("subtitle 含「报告日期」：模板 Hero 会自动追加报告日期，subtitle 请勿再写日期")
    # v5.1.2：Hero 指标卡 ✓ 必填字段缺失告警（渲染层有 —/默认值兜底，不拒但不该静默）
    for name in ("pe_ttm", "mcap", "horizon", "price_sub_html", "mcap_sub", "pe_sub"):
        if name == "horizon":
            # horizon 契约允许只放 valuation 级或情景级（_check_valuation_scenarios 明文），
            # 顶层缺失但下两级有值时不告警（热核 P2-6：两处契约打架）
            _v = fill.get("valuation") or {}
            if (str(_v.get("horizon") or "").strip()
                    or any(str(s.get("horizon") or "").strip()
                           for s in _v.get("scenarios") or [] if isinstance(s, dict))):
                continue
        if not str(fill.get(name) or "").strip():
            warns.append(f"Hero {name} 缺失：指标卡对应位置将显示空白或默认值（fill-schema 标 ✓ 必填）")
    tsub = str(fill.get("target_sub_html") or "")
    if re.search(r"\d+(?:\.\d+)?\s*(?:%|元)", tsub):
        warns.append("target_sub_html 含具体百分比/价格数字：目标价区间由脚本按 valuation 覆盖，"
                     "覆盖后手写数字与卡面失配——空间说明只写定性（v5.1.2）")


def _check_conclusion_structure(fill: dict, warns: list) -> None:
    """conclusion_html 四卡结构（fill-schema 1 核心结论；v4.9.1 补充修订二起 .concl-grid
    2×2 卡网格，顺序固定）：①关键优势→②关键弱点→③当前市场认知→④核心投资逻辑。
    缺卡或乱序 → 告警不拒（纯文本关键词校验，对容器形式不敏感；
    评分数字在 Hero/section-meta 已呈现，正文不重复）。"""
    txt = _plain_text(fill.get("conclusion_html") or "")
    if len(txt) < 20:
        return  # 内容地板已在 _check_content_floor 拒渲染，这里防空
    keys = ("关键优势", "关键弱点", "当前市场认知", "核心投资逻辑")
    pos = [txt.find(k) for k in keys]
    missing = [k for k, p in zip(keys, pos) if p < 0]
    if missing:
        warns.append(f"conclusion_html 缺卡：{'/'.join(missing)}——四卡固定（.concl-grid 内四张 "
                     f".concl-card，.concl-head 卡头）：①关键优势→②关键弱点→③当前市场认知→④核心投资逻辑"
                     f"（见 fill-schema「核心结论四卡骨架」）")
    elif pos != sorted(pos):
        warns.append("conclusion_html 四卡顺序错误：应为 ①关键优势→②关键弱点→"
                     "③当前市场认知→④核心投资逻辑")


def _check_governance_strip(fill: dict, warns: list) -> None:
    """v4.9.1 补充修订二：4.5 治理与资本配置分块单行化——整块 <p> 恰为 2 个
    （判词段 + 评分末拍段）；trig 行后另起 <p> 正文 → 告警（论据应内联进 .trig-mt）。
    未用 trig-strip 的旧存量 fill 不打扰。
    补充修订四：同款清单推广到 4.3 护城河 / 5.3 催化剂（5.2 为可选形态不强制），
    <p> 恰为 2 规则同步覆盖（5.3 评分段可省，校验只看 >2）。"""
    for field, tags in (("l1_html", ("4.3", "4.5")), ("l3_html", ("5.3",))):
        for blk in _split_dim_blocks(fill.get(field) or ""):
            # 审计 P1-3：tag 从 dim-name 提取（旧「子串命中」会被块内正文提及的 4.3 截胡，
            # 导致 4.5 块被当成 4.3、扣分校验整段跳过）
            _m = re.search(r'dim-name[^>]*>\s*(\d\.\d)', blk)
            tag = _m.group(1) if _m and _m.group(1) in tags else None
            if tag is None or "trig-strip" not in blk:
                continue
            np = len(re.findall(r"<p[ >]", blk))
            if np > 2:
                warns.append(f"{tag} 维度块含 {np} 个 <p>（应恰为 2：判词段+评分末拍段）："
                             f"trig 行后不要另起 <p> 正文，论据压进 .trig-mt 一句内联（fill-schema 条款）")
            # v4.11.0（天齐 09-13 实证）：评分末拍写了扣分项但 trig 行无一「扣分」状态——
            # 方块只剩正面/中性，扣分结论断层。审计修订：扣分项识别容忍写法漂移
            #（嵌套括号/全角减号 − – －/无「扣分项（」前缀的裸负分），扣分行识别容忍 class 顺序
            # 与「已扣分/减分」文案；「不扣分」句整体豁免
            if (tag == "4.5"
                    and re.search(r"扣分[\s\S]{0,24}?[−\-–－]\s*\.?\d", blk)
                    and not re.search(r"不扣分", blk)
                    and not re.search(r'<span class="[^"]*\bmiss\b[^"]*"[^>]*>\s*(已)?[扣减]分', blk)):
                warns.append("4.5 治理块评分段含扣分项，但 trig 行无「扣分」状态："
                             "扣分结论也要写进方块——miss 红行状态文案写「扣分」（「关注」=不扣分仅跟踪，两者不得混用）")


def _check_peers_orientation(fill: dict, warns: list) -> None:
    """v4.9.1 补充修订二：同业两表公司强制行标题——目标公司蓝色加粗应标在行首格；
    蓝 style 落在 <th> 表头 = 误写成「公司=列」旧方向 → 告警。"""
    peers = fill.get("peers_html") or ""
    if re.search(r"<th[^>]*style\s*=\s*[\"'][^\"']*color\s*:\s*" + re.escape(_C_BLUE), peers, flags=re.I):
        warns.append("peers_html 目标公司蓝色加粗落在 <th> 表头（写成了公司=列旧方向）："
                     "当前指标表与趋势表应公司=行标题，目标公司蓝色加粗标在行首格（fill-schema peers 规则）")


def _check_peers_bestworst(fill: dict, warns: list) -> None:
    """v4.10：同业当前指标表每列最优/最差标注（cell-best/cell-worst）缺失告警——
    工行 09-11 报告两表零标注实证（软规则无门禁就不会被遵守）。matrix-table 兜底形态不适用。
    v4.11.0 升级为逐列检查（天齐 09-13 实证：全表 7 列只标了 4 列，市值/PE最佳/26H1 同比
    整列裸奔但零标注告警不触发）——当前指标表每个数值列至少一个 best/worst 标注，
    缺列按列名告警（方向性确实无意义的列如市值，在 peers_meta 说明后可忽略本告警）。"""
    peers = fill.get("peers_html") or ""
    if "<table" not in peers:
        return
    if "cell-best" not in peers and "cell-worst" not in peers:
        warns.append("peers_html 当前指标表无 cell-best/cell-worst 最优/最差标注："
                     "每列按指标方向性各标一格（低为优：PE/PB/负债率；高为优：ROE/增速等），"
                     "规则见 fill-schema「表格」节")
        return
    # 审计 P1-6：matrix-table 兜底只跳过它自己那张表（旧逻辑「peers 含 matrix-table 即整段跳过」
    # 会让当前指标表的逐列检查失效——多表并存实证）
    # v5.8.2：切分收敛 _iter_tables 单源（旧捕获组 group(0)==group(1)，整表文本等价承载）
    tbl = next((t for t in _iter_tables(peers) if "matrix-table" not in t), None)
    if not tbl:
        return
    rows = list(_iter_rows(tbl))
    if len(rows) < 2:
        return
    # 格属性+内容双捕获：全仓唯一消费 attrs（cell-best/cell-worst 判定）处，保留不并入 _row_cells
    cells_of = [re.findall(r"<t[hd]\b([^>]*)>(.*?)</t[hd]>", r, flags=re.I | re.S) for r in rows]
    headers = [re.sub(r"<[^>]+>", "", c).strip() for _, c in cells_of[0]]
    marked, numeric = set(), set()
    for cells in cells_of[1:]:
        for ci, (attrs, content) in enumerate(cells):
            if "cell-best" in attrs or "cell-worst" in attrs:
                marked.add(ci)
            if re.search(r"\d", re.sub(r"<[^>]+>", "", content)):
                numeric.add(ci)
    missing = [headers[ci] if ci < len(headers) else f"第{ci + 1}列"
               for ci in sorted(numeric - marked) if ci > 0]
    # 审计 P1-9：方向性无意义列（如市值）在 peers_meta 注明后抑制对应列告警
    #（fill-schema 承诺「注明即可」的实现侧——此前文档写了、实现没做，每份规范报告会稳定误报市值列）
    meta = _plain_text(fill.get("peers_meta") or "")
    waivers = ("无方向", "不标方向", "不标最优", "不标最差", "不作最优", "不作最差",
               "不判断优劣", "不评优劣", "事实列", "仅列示", "仅参考")
    sentences = re.split(r"[。；;]", meta)

    def waived(column):
        key = _peers_col_key(column)
        return any(key and key in _peers_col_key(sentence)
                   and any(word in sentence for word in waivers) for sentence in sentences)

    missing = [c for c in missing if not waived(c)]
    if missing:
        warns.append(f"peers_html 当前指标表数值列缺最优/最差标注：{'、'.join(missing)}"
                     f"——每列按方向性至少标一格（低为优：PE/PB/负债率；高为优：ROE/增速等）；"
                     f"方向性无意义的列（如市值）在 peers_meta 注明后可忽略")


def _check_peers_column_support(fill: dict, warns: list) -> None:
    """v4.10.3：peers 趋势表「无对比支撑」列告警——承接 fill-schema「无引用=删列」硬规则
    （长久只写在文档里、无校验执行）：某列超半数单元格为「—」（或空）且该列名未在同业结论框
    （.conclusion-box）中被提及 → 该列撑不起对比，应补 peers 数据或在结论框引用，否则删列。
    字符串级实现（正则切表/切格，不引解析库）；无 <table> 或该表不足 2 行时跳过。"""
    peers = fill.get("peers_html") or ""
    if "<table" not in peers:
        return
    boxes = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", " ".join(
        re.findall(r'<div class="conclusion-box".*?</div>', peers, flags=re.I | re.S)))
    for ti, tbl in enumerate(_iter_tables(peers), 1):
        trs = list(_iter_rows(tbl))
        if len(trs) < 2:
            continue
        heads = [_plain_text(h).strip() for h in _row_cells(trs[0])]
        if len(heads) < 2:
            continue
        rows = [list(_row_cells(tr)) for tr in trs[1:]]
        for j in range(1, len(heads)):   # 首列=公司名，不查
            vals = [(_plain_text(r[j]).strip() if j < len(r) else "") for r in rows]
            if not vals:
                continue
            miss = sum(1 for v in vals if not v or v.startswith("—"))
            if miss * 2 <= len(vals):
                continue   # 可得数据 ≥ 半数，正常列
            key = _peers_col_key(heads[j])
            if key and key in boxes:
                continue   # 已在结论框引用
            warns.append(f"peers_html 趋势表「{heads[j]}」列 {miss}/{len(vals)} 格为「—」"
                         f"且未在同业结论框引用（表{ti} 第{j + 1}列）：该列无对比支撑——"
                         f"补 peers 数据或在结论框引用，否则删列（fill-schema 趋势表硬要求）")


def _peers_col_key(s: str) -> str:
    """趋势表列名归一（供列-引用比对）：去括号注与「3 年」类期限、只留中英文数字核。"""
    s = re.sub(r"[（(][^）)]*[）)]", "", s or "")
    s = re.sub(r"\d+\s*年?|年", "", s)
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]", "", s)


def _check_l4_form(fill: dict, warns: list) -> None:
    """两版均保留损失预演三联卡；v1 核对黄灯扣分表，v2 核对风险登记锚点与旧文案。"""
    l4 = fill.get("l4_html") or ""
    if "pm-grid" not in l4:
        raise ValueError("l4_html 缺损失预演三联卡（.pm-grid 固定骨架，v4.10 起）："
                         "禁止退回单段 danger-card 长文——骨架见 fill-schema「损失预演三联卡骨架」")
    if _quality_version(fill) == 2:
        if "黄灯扣分" in l4:
            raise ValueError("v2 的 l4_html 不得保留黄灯扣分文案，请改用 risk_items 与 RISK_REGISTER 锚点")
        if l4.count("<!--RISK_REGISTER-->") != 1:
            raise ValueError("v2 的 l4_html 必须且只能有一个 <!--RISK_REGISTER--> 锚点")
        return
    yellow = fill.get("yellow_deductions") or []
    # v5.1.2：行检出放宽（容忍 <tr>/<td> 带属性——原紧邻形态漏检走降级）+ 逐项数值比对
    row_ms = list(re.finditer(r"<tr[^>]*>\s*<td[^>]*>\s*[abcd][\s　].*?</tr>", l4, re.S))
    # 分母=points>0 的条目（零扣分类别不入表是契约正典，0 分合法——热核 P1-4）
    pos_y = [y for y in yellow if isinstance(y, dict) and (_num(y.get("points")) or 0) > 0]
    if row_ms and len(row_ms) != len(pos_y):
        raise ValueError(f"l4_html 黄灯扣分明细表 {len(row_ms)} 行与 yellow_deductions 正扣分 "
                         f"{len(pos_y)} 条不一致："
                         "只列 points>0 的类别行（零扣分类别不入表，表末一句「其余类别已核查无扣分」兜底），"
                         "每行扣分须与 yellow_deductions 对应")
    if row_ms and len(row_ms) == len(pos_y):
        row_pts = []
        for rm in row_ms:
            nm_ = re.search(r'class="num"[^>]*>\s*([\d.]+)', rm.group(0))
            row_pts.append(round(float(nm_.group(1)), 3) if nm_ else None)
        y_pts = sorted(round(_num(y.get("points")), 3) for y in pos_y)
        if None in row_pts:
            warns.append("l4_html 黄灯表扣分单元格未检出数值（class=num）：逐项数值比对降级，"
                         "请人工核对与 yellow_deductions 一致（v5.1.2）")
        elif sorted(row_pts) != y_pts:
            raise ValueError(f"l4_html 黄灯表扣分值 {sorted(row_pts)} 与 yellow_deductions {y_pts} 不一致："
                             "表与字段数值多重集一致（脚本按 yellow_deductions 扣分，v5.1.2 起拒渲染）")
    if not row_ms and pos_y:
        warns.append(f"l4_html 黄灯扣分明细未检出表格形态（<td>a-d 类别行），但有 "
                     f"{len(yellow)} 条 yellow_deductions——请用扣分表正典形态"
                     f"（fill-schema「L4 黄灯扣分明细」）")


def _check_cn_placeholder(fill: dict) -> None:
    """fill 正文字段中文占位符硬校验（与渲染后 _check_leftover 同口径的前置版，v4.10.2）：
    【待填】类残留提前到校验期拦截——--check 与 render 对 fill 问题拦截面一致，
    不再出现「check 退出 0 但 render 才炸」。黄灯类别标注（【b 行业与政策环境】这类
    以单个 a-d 字母开头的）是合法引用，不算占位符；fill 里的字面 {{KEY}} 合法
    （渲染时实体化显示），不在此查。"""
    for name in _HTML_FIELDS:
        hits = _cn_placeholders(fill.get(name))
        if hits:
            raise ValueError(f"{name} 残留中文占位符: {sorted(set(hits))}——请填写实际内容后重渲")


def _check_red_flag_conclusion(fill: dict, sc: dict = None) -> None:
    """v5.1.2：红旗命中 ≥2 项（red_deductions 条数，1D 红旗扣分明细）→ conclusion_html
    首卡首句必须含「利润真实性存疑」（fill-schema:61 长期承诺、此前零实现——多红旗报告
    静默缺失全文最强的利润真实性警示）。与 red_flag→「不建议参与」同强度：拒渲染。"""
    red = (sc.get("financial_red_flags") if sc and sc.get("quality_version") == 2
           else fill.get("red_deductions")) or []
    if len(red) < 2:
        return
    concl = fill.get("conclusion_html") or ""
    parts = concl.split("concl-head", 2)
    first_card = "concl-head".join(parts[:2]) if len(parts) > 2 else concl
    if "利润真实性存疑" not in first_card:
        raise ValueError(f"红旗命中 {len(red)} 项 ≥2：conclusion_html 首卡必须含「利润真实性存疑」"
                         "（fill-schema 既定要求，v5.1.2 起执行）——盈利质量红旗多项命中时，"
                         "结论必须先于一切优点声明存疑")


def _check_handwritten_dupes(fill: dict, warns: list) -> None:
    """v5.1.2：手写表与脚本生成并存检测（v4.11.3 三处手写迁移模式的补全——当时只堵了
    为什么卡/阶段表/DCF 表，其余四种同类形态无检测，图与表同屏各说各话）：
    ① p0_html 手写敏感性表（sensitivity 已填）；② valuation_html 手写三情景表/三指标卡；
    ③ l1_html 手写多年年表（fin_trend 已填）；④ gap_html 手写逐机构对照表（gap_plot 图会生成）。"""
    p0 = fill.get("p0_html") or ""
    if _sensitivity_items(fill) and "<table" in p0 and re.search(r"敏感|变量.{0,6}影响|弹性", p0):
        warns.append("p0_html 仍含手写敏感性表：sensitivity 字段已填、龙卷风图替代表，请删除手写表")
    vh = fill.get("valuation_html") or ""
    if "scenario-table" in vh:
        warns.append("valuation_html 含手写三情景表（scenario-table）：情景表由脚本按 valuation "
                     "生成，请删除手写表")
    if "metric-row" in vh and re.search(r"年化中枢|赔率|离散度", vh):
        warns.append("valuation_html 含手写三指标卡（年化中枢/赔率/离散度）：指标卡由脚本生成，"
                     "请删除手写卡")
    l1 = fill.get("l1_html") or ""
    if fill.get("fin_trend") and "<table" in l1:
        for tbl in _iter_tables(l1):
            if len(set(re.findall(r"20\d{2}", tbl))) >= 4 and tbl.count("<tr") >= 3:
                warns.append("l1_html 含多年年表（≥4 个年份列）：fin_trend 图墙已替代表"
                             "（v4.9 起禁写手写年表），请删除")
                break
    gp_dims = [d for d in ((fill.get("gap_plot") or {}).get("dims") or []) if _gap_dim_ok(d)]
    gh = fill.get("gap_html") or ""
    if len(gp_dims) >= 2 and "<table" in gh and re.search(r"机构|卖方", gh):
        warns.append("gap_html 含逐机构对照表：v4.11.1 起由 gap_plot 图承载（文字信息进 note "
                     "附注），请删除手写对照表")
    # v5.6.0：gap_history 图会生成时，gap_html 禁手写同内容变化表（同一券商两份对比，
    # v5.9.0 口径=最新一份 vs 上一份）
    if (fill.get("gap_history") or {}).get("rows") and "<table" in gh \
            and re.search(r"首末|态度变化|上调.{0,4}下调", gh):
        warns.append("gap_html 含手写券商态度变化表：v5.6.0 起由 gap_history 图承载"
                     "（图+判词横条自动生成），请删除手写表")
    # v5.8.0：散文罗列同禁——≥2 组「数值→数值亿」对比数字 + 上调/下调表述即与图重复
    # （中国巨石复盘实证：佐证段与图完全同源，且手写「12家」与横条「8家」口径打架）；
    # 佐证只写方向性结论与本文相对位置，数值留给图与判词横条。
    # v5.8.1 审核实证：须加佐证域关键词门槛（首末/态度变化/佐证）——A 档卖方假设分行列写
    # （「净利——东吴（05-10）：57.6→82.3亿（上调）」）合法含 ≥2 组箭头数字，无门槛会误伤
    # （v5.9.0：「首末」语境词保留——防的正是手写旧口径措辞，「态度变化/佐证」不变）
    if (fill.get("gap_history") or {}).get("rows"):
        n_arrows = len(re.findall(r"\d+(?:\.\d+)?\s*→\s*\d+(?:\.\d+)?\s*亿", gh))
        if n_arrows >= 2 and re.search(r"上调|下调", gh) \
                and re.search(r"首末|态度变化|佐证", gh):
            warns.append("gap_html 散文罗列券商对比数字（≥2 组「→」幅度+上/下调表述）："
                         "与券商态度变化图内容重复——只写方向性结论与本文相对位置，"
                         "两份对比数值由图与判词横条承载")
