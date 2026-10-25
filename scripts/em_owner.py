#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_owner.py — E4-E6 股东/预期/主营取数族（stock-deep-analysis skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：E4 股东户数（tushare stk_holdernumber 优先，东财兜底）、E5 一致预期（tushare report_rc
研报聚合 / 东财 RPT_WEB_RESPREDICT 兜底）、E6 主营构成（tushare fina_mainbz 产品优先取，
东财兜底）。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_market/em_finance/em_misc 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
import sys
from datetime import date

import em_core as _C
from em_core import (to_ts_code, _fmt_date, _em_dc, _win_years, yi, RateLimitError)
from org_tier import is_tier1, norm_org


# ---------------- E4 股东户数 ----------------
def _em_holders(code: str) -> list:
    return _em_dc("RPT_HOLDERNUMLATEST", f'(SECURITY_CODE="{code}")', 8)


def _holder_rows(code: str) -> list:
    """拉取 stk_holdernumber、滤 holder_num 缺失行、按 end_date 升序（旧→新）。
    v5.8.2：fetch_holders / fetch_holders_quarterly 原各自重复此段，收拢为一处；
    end_date 缺失行不在此剔除——fetch_holders 历史上保留，quarterly 自行再滤。"""
    rows = _C.ts_call("stk_holdernumber", {"ts_code": to_ts_code(code)})
    rows = [r for r in rows if r.get("holder_num")]
    if not rows:
        raise RuntimeError("stk_holdernumber 空返回")
    rows.sort(key=lambda x: x.get("end_date") or "")
    return rows


def _ratio_walk(rows: list) -> list:
    """旧→新序上自算环比（对前一期户数）并组装输出 dict——两 E4 函数原逐字重复段，
    v5.8.2 收拢。"""
    out = []
    prev = None
    for r in rows:
        num = r.get("holder_num")
        ratio = round((num / prev - 1) * 100, 1) if (prev and num) else None
        out.append({"END_DATE": r.get("end_date"), "HOLDER_NUM": num,
                    "HOLDER_NUM_RATIO": ratio})
        prev = num
    return out


def fetch_holders(code: str) -> list:
    """E4 股东户数（东财键名同构）。tushare stk_holdernumber 优先（变动比自算），东财兜底。"""
    try:
        return list(reversed(_ratio_walk(_holder_rows(code))))[:8]
    except Exception:
        return _em_holders(code)


_QEND = ("0331", "0630", "0930", "1231")  # 月日四位数字（YYYYMMDD 切片比对）


def fetch_holders_quarterly(code: str) -> list:
    """E4 季度口径户数序列（v4.11.0，天齐实证）：月内多期/不定期披露点间隔不一，等距排布
    时间轴失真——只取季末（定期报告口径）近 12 期，间隔均匀可回溯；若最新披露新于末季末
    （如 8 月互动易新披露），追加为末点。环比按保留序列自算。返回旧→新。"""
    try:
        rows = [r for r in _holder_rows(code) if r.get("end_date")]
        if not rows:
            raise RuntimeError("stk_holdernumber 空返回")
        qrows = [r for r in rows
                 if "".join(ch for ch in r["end_date"] if ch.isdigit())[4:8] in _QEND]
        # 同截止日多行（上游偶发近似重复，天齐 20240930/20260630 双行且户数略不同实证）→
        # 去重保留后写行且先于截断（窗口按干净序列取近 12 个季末）；变动比在干净序列上重算
        qrows = list({r["end_date"]: r for r in qrows}.values())
        q = qrows[-12:]
        latest = rows[-1]
        if not q or latest["end_date"] > q[-1]["end_date"]:
            q = q + [latest]
        return _ratio_walk(q)
    except Exception:
        return []


# ---------------- E5 一致预期 ----------------
def _em_consensus(code: str) -> dict:
    data = _em_dc("RPT_WEB_RESPREDICT", f'(SECURITY_CODE="{code}")', 1)
    return data[0] if data else {}


def _org_history(hist_rows: dict, name_map: dict = None) -> list:
    """gap_history 数据源：同一券商「最新一份 vs 上一份」研报对比行（v5.9.0 口径重构——
    原 v5.6.0「近 180 天内 ≥2 份首末对比」废止：「半年前一份 → 今天一份」这类最有价值的
    变化曾被窗口整行滤掉，而 tushare report_rc 返回全历史（v5.9.0 探针实证最早 2019 年）。
    口径：最新一份 d1 = 该券商近 180 天内最新研报日期（180 天内无 → 不出行，保「当前态度」
    语义）；上一份 d0 = d1 之前最近一份，不限时间（np 同预测年度约束自带时间过滤——跨期
    太远年份对不上时 np 自动不比）。np 对比取 d0/d1 都有该年度 np 的年度（当年优先，否则
    最大年）；tp 取 d0/d1 两份区间中值（缺一不比）；评级仅记变化。行日期 = np 对比日期
    （np 缺失退 tp 日期）。排序：头部/外资券商（org_tier.is_tier1）优先，组内按 np 变化
    幅度降序（无 np 按 tp）。输出 ISO 日期。
    hist_rows 键须为归一化机构名（org_tier.norm_org——「中金/中金公司」口径漂移不合并会
    把同一券商拆成两行幻影对比，v5.9.0 宁德 300750 探针实证）；name_map = 归一化名 →
    最新一份研报的原始机构名（展示用）。"""
    cur_yr = str(date.today().year)
    cutoff = date.today().toordinal() - 180

    def _iso(rd):
        return f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) == 8 else rd

    def _ord(rd):
        try:
            return date(int(rd[:4]), int(rd[4:6]), int(rd[6:8])).toordinal()
        except Exception:
            return -1

    out = []
    for org, rows in hist_rows.items():
        dates = sorted({rd for rd, *_ in rows if rd and _ord(rd) > 0})
        d1 = next((d for d in reversed(dates) if _ord(d) >= cutoff), None)
        if d1 is None:          # 近 180 天无最新研报 → 态度非当前，不出行
            continue
        prev = [d for d in dates if d < d1]
        if not prev:            # 历史上无上一份 → 无可比，不出行
            continue
        d0 = prev[-1]
        entry = {"org": (name_map or {}).get(org, org)}
        yrs = [y for y in {yr for _, yr, np_, *_ in rows if yr and np_ is not None}
               if any(rd == d0 and yr == y and np_ is not None for rd, yr, np_, *_ in rows)
               and any(rd == d1 and yr == y and np_ is not None for rd, yr, np_, *_ in rows)]
        if yrs:
            y = cur_yr if cur_yr in yrs else max(yrs)
            v0 = next(np_ for rd, yr, np_, *_ in rows if rd == d0 and yr == y)
            v1 = next(np_ for rd, yr, np_, *_ in rows if rd == d1 and yr == y)
            entry.update(yr=y, d_from=_iso(d0), d_to=_iso(d1), np_from=v0, np_to=v1)
        tps = {rd: tp for rd, _, _, tp, _ in rows if rd in (d0, d1) and tp is not None}
        if d0 in tps and d1 in tps:
            entry.update(tp_from=tps[d0], tp_to=tps[d1])
            entry.setdefault("d_from", _iso(d0))
            entry.setdefault("d_to", _iso(d1))
        rts = {rd: rt for rd, *_, rt in rows if rd in (d0, d1) and rt}
        if d0 in rts and d1 in rts and rts[d0] != rts[d1]:
            entry.update(rating_from=rts[d0], rating_to=rts[d1])
        if "np_from" in entry or "tp_from" in entry:
            out.append(entry)

    def _delta(e, k1, k2):
        return (e[k2] / e[k1] - 1) if k1 in e and k2 in e and e[k1] else -9

    out.sort(key=lambda e: (not is_tier1(e["org"]), -_delta(e, "np_from", "np_to"),
                            -_delta(e, "tp_from", "tp_to"), e["org"]))
    return out


def _cap_note(cap: int, total: int) -> str:
    """截断家数声明（审计 P2-3：截断时家数声明与行内条数不得矛盾；v5.8.3 自 _sec_e5
    cnt_note 三处同构计算下沉单源）。"""
    return f"前 {cap} 家/共 {total} 家" if total > cap else f"{total} 家"


def _e5_render_ready(detail: dict, aim_detail: list, history: list, tp_reports: list) -> dict:
    """E5 渲染就绪行（v5.8.3 自 _sec_e5 下沉的数据变换）：逐机构明细/目标价明细/券商态度
    变化/目标价研报清单四行的截断、家数声明与 "·".join 格式化在此一次算好，_sec_e5 瘦身为
    纯拼接。截断口径与落盘一致：明细 20 家、history/tp_reports 落盘 12 家、清单去重后 8 家；
    清单按（机构,目标价）去重、份数=截断后原始份数；条目全缺目标价时清单行 None（不出行）。
    摘要行文案逐字同旧 _sec_e5 内联实现。"""
    detail_lines = []
    for yr in sorted(detail or {}):
        det = detail[yr]
        seg = "·".join(f"{d['org']}{d['np']:g}({d['date'][4:6]}-{d['date'][6:8]})"
                       for d in det[:20])
        detail_lines.append(f"{yr}E 净利明细（gap_plot 照抄行，{_cap_note(20, len(det))}，"
                            f"按值降序）: {seg}")
    aim_line = None
    if aim_detail:
        seg = "·".join(f"{d['org']}{d['tp']:g}({d['date'][4:6]}-{d['date'][6:8]})"
                       for d in aim_detail[:20])
        aim_line = (f"目标价明细（gap_plot 照抄行，{_cap_note(20, len(aim_detail))}，"
                    f"(研报下限+上限)/2）: {seg}")
    history_line = None
    if history:
        def _sd(h):  # 上一份日期跨年带全称（MM-DD→MM-DD 跨年歧义，v5.9.0 上一份不限窗口）
            return (h["d_from"][5:] if h["d_from"][:4] == h["d_to"][:4] else h["d_from"])
        segs = []
        for h in history[:12]:
            seg = h["org"]
            if "np_from" in h:
                seg += (f" {h['yr']}E净利{h['np_from']:g}({_sd(h)})"
                        f"→{h['np_to']:g}({h['d_to'][5:]})")
            if "tp_from" in h:
                seg += f"·目标价{h['tp_from']:g}→{h['tp_to']:g}"
            if "rating_from" in h:
                seg += f"·评级{h['rating_from']}→{h['rating_to']}"
            segs.append(seg)
        history_line = (f"券商态度变化（gap_history 照抄行，{_cap_note(12, len(history))}，"
                        f"同一券商最新一份vs上一份·最新限180天内/上一份不限/头部外资优先）: "
                        + "；".join(segs))
    tp_reports_line = None
    if tp_reports:
        tp12 = tp_reports[:12]
        seen, uniq = set(), []
        for t in tp12:
            if not isinstance(t, dict) or t.get("tp") is None:
                continue
            k = (str(t.get("org") or "").strip(), t.get("tp"))
            if k not in seen:
                seen.add(k)
                uniq.append(t)
        if uniq:
            tseg = "·".join(f"{t.get('org')}{t['tp']:g}"
                            f"({str(t.get('date') or '')[5:]})" for t in uniq[:8])
            n_orgs = len({str(t.get("org") or "").strip() for t in uniq})
            tp_reports_line = (f"目标价研报清单（gap_history.tp_reports 照抄键，"
                               f"{n_orgs} 家/{len(tp12)} 份，降级面板数据源）: {tseg}")
    return {"detail_lines": detail_lines, "aim_line": aim_line,
            "history_line": history_line, "tp_reports_line": tp_reports_line}


def fetch_consensus(code: str) -> dict:
    """E5 一致预期。tushare report_rc（券商盈利预测明细）优先；东财 RPT_WEB_RESPREDICT 兜底。
    返回带 _src 标记的 dict。tushare 返回全历史研报（v5.9.0 探针实证最早 2019 年）：
    一致预期聚合（家数/分年度净利与EPS均值/目标价区间/逐机构明细）仍限近 180 天，
    gap_history 对比（_org_history）用全历史——上一份不限窗口。"""
    try:
        rows = _C.ts_call("report_rc", {"ts_code": to_ts_code(code)})
        if not rows:
            raise RuntimeError("report_rc 空返回")
        cutoff = date.today().toordinal() - 180
        recent = []
        for r in rows:
            try:
                rd = date(int(r["report_date"][:4]), int(r["report_date"][4:6]), int(r["report_date"][6:8]))
                if rd.toordinal() >= cutoff:
                    recent.append(r)
            except Exception:
                continue
        if not recent:
            raise RuntimeError("report_rc 近180天无研报")
        orgs = {r.get("org_name") for r in recent if r.get("org_name")}
        # 单次循环聚合：按预测年度的净利/EPS（quarter 形如 2026Q4 → 2026）、目标价区间、评级分布
        years, prices, ratings = {}, [], {}
        latest_by_org = {}   # v4.11.1（gap_plot 落地）：(yr, org) → 最新研报行，供 E5 逐机构明细
        aim_by_org = {}      # org → 最新含目标价研报行
        tp_reports = []      # v5.8.0：180 天内全部含目标价研报（org/date/tp 中值，日期倒序）——
                             # 态度变化图目标价面板「无同券商可比两份」时的研报一览降级数据源
        for r in recent:
            q = str(r.get("quarter") or "")
            yr = q[:4] if len(q) >= 4 else ""
            org = (r.get("org_name") or "").strip()
            rd = str(r.get("report_date") or "")
            if yr.isdigit():
                slot = years.setdefault(yr, {"np": [], "eps": []})
                if r.get("np") is not None:
                    slot["np"].append(float(r["np"]) / 1e4)  # report_rc np 单位万元 → 亿
                if r.get("eps") is not None:
                    slot["eps"].append(float(r["eps"]))
                if org and r.get("np") is not None:
                    k = (yr, org)
                    if k not in latest_by_org or rd > latest_by_org[k]["report_date"]:
                        latest_by_org[k] = r
            if r.get("min_price") and r.get("max_price"):
                prices.append((float(r["min_price"]), float(r["max_price"])))
                if org:
                    tp_reports.append({"org": org,
                                       "date": (f"{rd[:4]}-{rd[4:6]}-{rd[6:8]}" if len(rd) == 8 else rd),
                                       "tp": round((float(r["min_price"]) + float(r["max_price"])) / 2, 2)})
                if org and (org not in aim_by_org or rd > aim_by_org[org]["report_date"]):
                    aim_by_org[org] = r
            rt = (r.get("rating") or "").strip()
            if rt:
                ratings[rt] = ratings.get(rt, 0) + 1
        # 逐机构明细（同机构 180 天内多份取最新）：np 万元→亿；目标价=(min+max)/2
        detail = {}
        for (yr, org), r in latest_by_org.items():
            detail.setdefault(yr, []).append({"org": org, "np": round(float(r["np"]) / 1e4, 1),
                                              "date": r.get("report_date", "")})
        for v in detail.values():
            v.sort(key=lambda x: -x["np"])
        aim_detail = [{"org": org, "tp": round((float(r["min_price"]) + float(r["max_price"])) / 2, 2),
                       "date": r.get("report_date", "")}
                      for org, r in sorted(aim_by_org.items(),
                                           key=lambda kv: -(float(kv[1]["min_price"])
                                                            + float(kv[1]["max_price"])))]
        hist_rows = {}       # gap_history 数据源：归一化机构名 → [(rd, yr, np亿, tp中值, rating)]。
        # v5.9.0 起收集全历史（非 180 天 recent）——对比口径「最新一份 vs 上一份」的上一份
        # 不限窗口（tushare report_rc 返回全历史，v5.9.0 探针实证最早 2019 年）；
        # 键用 norm_org 归一化名合并口径漂移（「中金/中金公司」拆两行幻影对比，宁德探针实证），
        # hist_name 记录各归一化名最新研报的原始机构名供展示
        hist_name = {}
        for r in rows:
            org = (r.get("org_name") or "").strip()
            rd = str(r.get("report_date") or "")
            if org and rd:
                key = norm_org(org)
                if key not in hist_name or rd > hist_name[key][0]:
                    hist_name[key] = (rd, org)
                q = str(r.get("quarter") or "")
                _tp = (round((float(r["min_price"]) + float(r["max_price"])) / 2, 2)
                       if r.get("min_price") and r.get("max_price") else None)
                _np = round(float(r["np"]) / 1e4, 1) if r.get("np") is not None else None
                hist_rows.setdefault(key, []).append(
                    (rd, q[:4] if len(q) >= 4 else "", _np, _tp,
                     (r.get("rating") or "").strip()))
        hist = _org_history(hist_rows, {k: v[1] for k, v in hist_name.items()})
        tp_sorted = sorted(tp_reports, key=lambda x: x["date"], reverse=True)
        return {"_src": "tushare", "orgs": len(orgs), "n_reports": len(recent),
                "years": years, "detail": detail, "aim_detail": aim_detail,
                "history": hist,
                "tp_reports": tp_sorted,
                "aim": (min(p[0] for p in prices), max(p[1] for p in prices)) if prices else None,
                "ratings": ratings,
                # v5.8.3：渲染就绪行（detail_lines/aim_line/history_line/tp_reports_line）——
                # 原 _sec_e5 的截断/去重/计数/格式化在此产出，_sec_e5 只拼接
                **_e5_render_ready(detail, aim_detail, hist, tp_sorted)}
    except RateLimitError:
        raise  # v5.8.2 硬停纪律：东财一致预期限流不吞成「无覆盖」，穿透至 main 退 2
    except Exception as e:
        _C._ts_quiet("E5 一致预期（tushare report_rc）", e)
        d = _em_consensus(code)
        if d:
            d["_src"] = "em"
        return d


# ---------------- E6 主营构成 ----------------
# fina_mainbz 维度合计行的 bz_item 取值（v4.10.3）：除产品/行业/地区三大维度名外，
# 兼容「合计」「主营业务」两种可能的表头写法。
_MAINBZ_TOTAL_NAMES = {"产品", "行业", "地区", "合计", "主营业务"}


class _MainopRows(list):
    """fetch_mainop 的返回类型（list 子类，行为与 list 完全一致）：剔除合计行时把合计行
    毛利挂在 _TOTAL_GP 属性上带出（审计 #3）——层级 payload 下父级小计+子级明细并存，
    sum(明细毛利) 会重复计数（工商银行型毛利占比合计可达 366%），毛利占比分母必须用
    合计行口径；无合计行（含东财兜底路径）时属性不存在，消费方退回 sum(GROSS_PROFIT)。"""


def _em_mainop(secucode: str) -> list:
    try:
        return _em_dc("RPT_F10_FN_MAINOP", f'(SECUCODE="{secucode}")', 20, "REPORT_DATE")
    except Exception:
        return []


def _mainop_norm_em(rows: list) -> list:
    """东财 E6 原始行补 GROSS_PROFIT（毛利额，元）：优先原始字段 MAIN_BUSINESS_RPOFIT，
    缺失用 收入×毛利率 折算（GROSS_RPOFIT_RATIO 为小数口径，见 data-sources.md E6 节）。
    同收入同毛利率的重复条目（同源改名残留）一并去重，留先发行。"""
    seen = set()
    deduped = []
    for r in rows:
        sig = (r.get("MAIN_BUSINESS_INCOME"), r.get("GROSS_RPOFIT_RATIO"))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(r)
    rows = deduped
    for r in rows:
        gp = r.get("MAIN_BUSINESS_RPOFIT")
        if gp is None:
            inc, gpr = r.get("MAIN_BUSINESS_INCOME"), r.get("GROSS_RPOFIT_RATIO")
            if inc is not None and gpr is not None:
                try:
                    r["GROSS_PROFIT"] = float(inc) * float(gpr)
                except (TypeError, ValueError):
                    pass
            continue
        try:
            r["GROSS_PROFIT"] = float(gp)
        except (TypeError, ValueError):
            pass
    return rows


def fetch_mainop(secucode: str) -> list:
    """E6 主营构成（东财键名同构）。tushare fina_mainbz 优先（产品P→行业D次序），东财兜底。
    v4.8 起各分部带 GROSS_PROFIT（毛利额，元）：tushare 取 bz_profit（缺则 收入−成本），
    东财取 MAIN_BUSINESS_RPOFIT（缺则 收入×毛利率 折算）。分部净利润无公开数据源，
    业务构成图的利润口径一律为毛利。v4.10.3 起剔除 fina_mainbz 的维度合计行（见下）；
    剔除时合计行毛利经 _TOTAL_GP 属性随返回带出（审计 #3，层级 payload 毛利占比分母）。"""
    code, _ = secucode.split(".")
    try:
        ts = to_ts_code(code)
        beg, end = _win_years(2)
        rng = {"start_date": beg, "end_date": end}
        rows = None
        mainop_type = None
        for tp, mt in (("P", "2"), ("D", "1")):  # 产品优先，地区当行业位展示
            got = _C.ts_call("fina_mainbz", {"ts_code": ts, "type": tp, **rng})
            if got:
                rows, mainop_type = got, mt
                break
        if not rows:
            raise RuntimeError("fina_mainbz 空返回")
        latest_ed = max(r.get("end_date") or "" for r in rows)
        items = [r for r in rows if r.get("end_date") == latest_ed]
        # 源头重复条目去重（2026-09-02 宝丰实证：fina_mainbz 会同时返回「烯烃产品」与「烯烃」两行，
        # 收入/成本完全一致——同源改名跟踪残留。签名=（收入,成本）全等即同一条业务线，留先发行）
        seen_sig, deduped = set(), []
        for r in items:
            sig = (r.get("bz_sales"), r.get("bz_cost"))
            if sig in seen_sig:
                continue
            seen_sig.add(sig)
            deduped.append(r)
        if len(deduped) < len(items):
            print(f"注：fina_mainbz 重复条目已去重 {len(items)}→{len(deduped)}"
                  f"（同收入同成本，同源改名残留）", file=sys.stderr)
        items = deduped
        # 维度合计行剔除（v4.10.3，2026-09-12 香农芯创 300475 实证）：fina_mainbz 在明细行之外
        # 额外返回一行 bz_item=维度名（产品/行业/地区）的合计行——留在分母里会让所有 MBI_RATIO
        # 腰斩（香农芯创占比 46.8% 实为 93.7%）。分母取**该合计行金额**：合计行=维度汇总，经
        # income.total_revenue 交叉验证精确等于营业收入；扁平 payload 它恰为其余行之和，但层级
        # payload（父级小计与子级明细并存，东方电气 1.86x / 工商银行 3.66x / 山东黄金 1.13x 实证）
        # sum(明细) 会重复计数，故不能用明细和当初数。
        dropped = [r for r in items if str(r.get("bz_item") or "").strip() in _MAINBZ_TOTAL_NAMES]
        if dropped:
            items = [r for r in items
                     if str(r.get("bz_item") or "").strip() not in _MAINBZ_TOTAL_NAMES]
            desc = "；".join(f'{str(r.get("bz_item") or "").strip()}，{yi(r.get("bz_sales"))} 亿'
                            for r in dropped)
            print(f"注：fina_mainbz 已剔除维度合计行（{desc}，其值作分母）", file=sys.stderr)
            total = max((float(r["bz_sales"]) for r in dropped if r.get("bz_sales")), default=None)
            # 合计行毛利随返回带出（审计 #3，_MainopRows._TOTAL_GP）：毛利占比分母用合计行
            # 口径（bz_profit，缺则 收入−成本）——层级 payload 下 sum(明细毛利) 会重复计数；
            # 锚定销售额最大的合计行（与 total 同锚）
            anchor = max((r for r in dropped if r.get("bz_sales")),
                         key=lambda r: float(r["bz_sales"]), default=None)
            total_gp = None
            if anchor is not None:
                if anchor.get("bz_profit") is not None:
                    total_gp = float(anchor["bz_profit"])
                elif anchor.get("bz_cost") is not None:
                    total_gp = float(anchor["bz_sales"]) - float(anchor["bz_cost"])
        else:
            total = sum(float(r["bz_sales"]) for r in items if r.get("bz_sales")) or None
            total_gp = None
        out = _MainopRows()
        for r in items:
            sales = float(r["bz_sales"]) if r.get("bz_sales") else None
            cost = float(r["bz_cost"]) if r.get("bz_cost") else None
            gp = None
            if r.get("bz_profit") is not None:
                gp = float(r["bz_profit"])
            elif sales is not None and cost is not None:
                gp = sales - cost
            out.append({
                "REPORT_DATE": _fmt_date(latest_ed),
                "REPORT_NAME": f"{latest_ed[:4]}年报" if latest_ed.endswith("1231") else latest_ed,
                "MAINOP_TYPE": mainop_type,
                "ITEM_NAME": r.get("bz_item"),
                "MAIN_BUSINESS_INCOME": sales,
                "MBI_RATIO": (sales / total if (sales and total) else None),
                "GROSS_RPOFIT_RATIO": ((sales - cost) / sales if (sales and cost is not None) else None),
                "GROSS_PROFIT": gp,
            })
        if total_gp is not None:
            out._TOTAL_GP = total_gp
        return out
    except Exception:
        return _mainop_norm_em(_em_mainop(secucode))
