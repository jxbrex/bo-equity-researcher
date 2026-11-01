#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_calibration.py — 评分统计校准：三轨分与目标价 vs 固定期限实际表现

用法:
    python score_calibration.py [报告目录]     # 默认 D:\\个股深度分析

流程：扫描目录 HTML 报告 → extract_review 提取锚点 → 报告日收盘后 20/60/120/250 个
实际交易日的前复权收益与同期基准（港股走东财前复权日 K+恒指）→ 按质量分/估值分分桶。
目标价兑现使用名义收盘价，与分数收益校准分开。

判读纪律（防过度解读，写在输出里）：
- 未到期只标「未到期」，绝不用最新收盘代替；股票与基准同起止交易日。
- 样本同源（同一市场 regime），同股多份窗口重叠，给去重口径。
- 每桶独立兑现样本 <10 只列计数；显著性结论需要 30+ 独立样本，每月复跑积累。
"""
import os
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_review as E
from extract_review import parse_report_name, norm_code  # 文件名解析/代码归一唯一 owner（合并口径）
import em_core
import em_fetch as em
# debt: stdout/stderr UTF-8 reconfigure 靠 extract_review/em_fetch 的 import 副作用保障；
# 若改为不 import 它们，需自带 reconfigure 块
# v5.8.3：ts_call/get/to_ts_code 经 em_fetch re-export 的兼容别名已收敛（em_fetch 内零裸用），
# 此处直接打 em_core 命名空间；em.kline_url/em.secid_of 仍在 em_fetch 取数块 re-export 清单。

DEFAULT_DIR = r"D:\个股深度分析"
SHORT_WINDOW = 20  # 交易日

# 分桶边界（与决策矩阵口径对齐：质量 <4 回避 / 4-5.5 一般 / 5.5-7 中上 / ≥7 好公司；
# 估值 <4 贵 / 4-6 合理 / 6-8 合理偏便宜 / ≥8 深度安全边际）
Q_BUCKETS = [(0, 4, "质量<4 回避"), (4, 5.5, "质量4-5.5 一般"),
             (5.5, 7, "质量5.5-7 中上"), (7, 11, "质量≥7 好公司")]
V_BUCKETS = [(0, 4, "估值<4 贵"), (4, 6, "估值4-6 合理"),
             (6, 8, "估值6-8 偏便宜"), (8, 11, "估值≥8 深度安全边际")]


def bucket_of(v, buckets):
    """分值 → 桶标签；None 不入桶。"""
    if v is None:
        return None
    for lo, hi, label in buckets:
        if lo <= v < hi:
            return label
    return None


def collect_reports(directory: str) -> list:
    """递归扫描报告并保留 quality_version；旧单轨综合分只入明细，不冒充质量分。"""
    reps = []
    for root, dirs, files in os.walk(directory):
        E.prune_scan_dirs(dirs)
        for fn in sorted(files):
            if not fn.lower().endswith(".html"):
                continue
            info = parse_report_name(fn)
            if not info:
                if E._looks_like_report(fn):
                    print(f"[跳过: 文件名无法解析 {fn}]", file=sys.stderr)
                continue
            code, rep_date = info["code"], info["date"]
            path = os.path.join(root, fn)
            try:
                ext = E.extract(path)
            except Exception as e:
                print(f"跳过 {fn}（提取失败: {e}）", file=sys.stderr)
                continue
            prev = ext.get("prev") or {}
            q, v = prev.get("quality"), prev.get("valuation")
            version = prev.get("quality_version") or (1 if info["valuation"] is not None else "legacy-single-track")
            code = norm_code(ext.get("code") or code)
            if version == "legacy-single-track":
                legacy_quality = info["quality"] if info["quality"] is not None else q
                if legacy_quality is None:
                    print(f"跳过 {fn}（未提取到旧版单轨综合分）", file=sys.stderr)
                    continue
                reps.append({"file": fn, "code": code, "company": ext.get("company") or fn,
                             "rep_date": prev.get("date") or rep_date,
                             "quality": legacy_quality, "valuation": None, "timing": None,
                             "price": ext.get("price"), "target_range": prev.get("target_range"),
                             "legacy": True, "quality_version": version})
                continue
            reps.append({"file": fn, "code": code, "company": ext.get("company") or fn,
                         "rep_date": prev.get("date") or rep_date,
                         "quality": q, "valuation": v, "timing": prev.get("timing"),
                         "price": ext.get("price"), "target_range": prev.get("target_range"),
                         "quality_version": version})
    return reps


def _ts(api_name: str, params: dict) -> list:
    """ts_call 限流包装：tushare 分钟级频次限制（如 hk_daily 1次/分）命中时睡 62s 重试一次。"""
    try:
        return em_core.ts_call(api_name, params)
    except RuntimeError as e:
        if "频率超限" in str(e) or "频次" in str(e):
            print(f"  tushare 限流，62s 后重试 {api_name}...", file=sys.stderr)
            time.sleep(62)
            return em_core.ts_call(api_name, params)
        raise


HORIZONS = (20, 60, 120, 250)


def _em_kline_daily(secid: str, start: str, end: str, adjusted: bool = True) -> list:
    """东财日 K（klt=101；adjusted 控制 fqt）→ [{trade_date, close, adj_close}]。
    港股日线走此通道（tushare hk_daily 限 1次/小时，批量校准不可用）。"""
    url = em.kline_url(secid, 101, start, end)
    if not adjusted:
        url = url.replace("fqt=1", "fqt=0")
    d = em_core.get(url).get("data") or {}
    return [{"trade_date": k.split(",")[0].replace("-", ""),
             "close": float(k.split(",")[1]), "adj_close": float(k.split(",")[1])}
            for k in (d.get("klines") or [])]


def _daily_adj_rows(code: str, start: str, end: str, is_hk: bool) -> list:
    """日线 + 复权因子合成行 [{trade_date, close, adj_close}]；港股另取名义价 Join。"""
    if is_hk:
        secid = em.secid_of(code)[0]
        rows = _em_kline_daily(secid, start, end, True)
        nominal = {r["trade_date"]: r["close"] for r in _em_kline_daily(secid, start, end, False)}
        return [dict(r, close=nominal[r["trade_date"]]) for r in rows if r["trade_date"] in nominal]
    ts = em_core.to_ts_code(code)
    rows = _ts("daily", {"ts_code": ts, "start_date": start, "end_date": end})
    adj = {r["trade_date"]: float(r["adj_factor"]) for r in
           _ts("adj_factor", {"ts_code": ts, "start_date": start, "end_date": end})
           if r.get("adj_factor") is not None}
    return [{"trade_date": r["trade_date"], "close": float(r["close"]),
             "adj_close": float(r["close"]) * adj.get(r["trade_date"], 1.0)}
            for r in rows if r.get("close") is not None]


def fetch_return(code: str, rep_date: str, today: str) -> dict:
    """报告日收盘（≤报告日最近交易日）→ 各固定期限的前复权收益与名义收盘价。
    单次宽窗口取数；期限不足只标未到期，绝不用最新收盘回填。"""
    is_hk = len(code) == 5
    d0 = rep_date.replace("-", "")
    year, month = int(d0[:4]), int(d0[4:6])
    start = f"{year - 1}1201" if month == 1 else f"{year}{month - 1:02d}01"
    rows = _daily_adj_rows(code, start, today, is_hk)
    rows.sort(key=lambda r: r["trade_date"])  # tushare 返回倒序，统一升序
    if not rows:
        raise RuntimeError("日线空返回")
    entry = None
    for r in rows:
        if r["trade_date"] <= d0:
            entry = r  # ≤报告日最后一个交易日
    if entry is None:
        raise RuntimeError(f"报告日 {rep_date} 前无交易数据")
    entry_idx = rows.index(entry)
    terms = {}
    for horizon in HORIZONS:
        exit_idx = entry_idx + horizon
        if exit_idx >= len(rows):
            terms[horizon] = {"matured": False, "exit_date": None, "ret": None, "price": None}
            continue
        exit_ = rows[exit_idx]
        terms[horizon] = {"matured": True, "exit_date": exit_["trade_date"],
                          "ret": exit_["adj_close"] / entry["adj_close"] - 1,
                          "price": exit_["close"]}
    return {"entry_date": entry["trade_date"], "terms": terms}


_INDEX_CACHE = {}


def fetch_index_return(market: str, start_td: str, end_td: str) -> float:
    """基准同期收益：A股→沪深300（前复权不需要，指数无分红调整口径），港股→恒生指数。"""
    key = (market, start_td, end_td)
    if key in _INDEX_CACHE:
        return _INDEX_CACHE[key]
    if market == "HK":
        # 恒生指数走东财日 K（指数无复权，fqt=0；tushare index_global 频次同样受限）
        rows = _em_kline_daily("100.HSI", start_td, end_td)
        rows = [{"trade_date": r["trade_date"], "close": r["adj_close"]} for r in rows]
    else:
        rows = _ts("index_daily", {"ts_code": "000300.SH",
                                   "start_date": start_td, "end_date": end_td})
    if not rows:
        raise RuntimeError("指数数据空返回")
    rows = sorted(rows, key=lambda r: r["trade_date"])
    start_row = next((r for r in rows if r["trade_date"] == start_td), None)
    end_row = next((r for r in rows if r["trade_date"] == end_td), None)
    if start_row is None or end_row is None:
        raise RuntimeError(f"基准缺少精确起止交易日: {start_td} / {end_td}")
    base = float(start_row["close"])
    last = float(end_row["close"])
    ret = last / base - 1
    _INDEX_CACHE[key] = ret
    return ret


def dedup_earliest(reps: list) -> list:
    """同股去重口径：每股只保留最早一份（窗口最长、相互独立）。"""
    seen = {}
    for r in reps:
        if r["code"] not in seen or r["rep_date"] < seen[r["code"]]["rep_date"]:
            seen[r["code"]] = r
    return list(seen.values())


MIN_MATURED_N = 10


def _bucket_table(reps: list, key: str, buckets, title: str) -> list:
    lines = [f"\n### {title}\n", "| 桶 | n | 平均收益 | 中位收益 | 胜率 | 平均超额 |",
             "|---|---|---|---|---|---|"]
    for lo, hi, label in buckets:
        members = [r for r in reps if bucket_of(r.get(key), buckets) == label]
        if not members:
            lines.append(f"| {label} | 0 | — | — | — | — |")
            continue
        rets = sorted(r["ret"] for r in members)
        exc = [r["excess"] for r in members if r.get("excess") is not None]
        n = len(members)
        if n < MIN_MATURED_N:
            lines.append(f"| {label} | {n} | 样本不足 | — | — | — |")
            continue
        med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
        win = sum(1 for x in rets if x > 0) / n
        row = f"| {label} | {n} | {sum(rets) / n:+.1%} | {med:+.1%} | {win:.0%} | "
        if len(exc) >= MIN_MATURED_N:
            row += f"{sum(exc) / len(exc):+.1%} |"
        elif not exc:
            row += "— |"
        else:
            row += "样本不足 |"
        lines.append(row)
    return lines


def _target_bounds(value):
    if not value:
        return None
    try:
        lo, hi = str(value).replace("–", "-").split("-", 1)
        low, high = float(lo.strip()), float(hi.strip().split()[0].rstrip("元"))
    except (TypeError, ValueError):
        return None
    return (low, high) if low <= high else None


def _target_table(reps: list) -> list:
    members = [r for r in reps if r.get("target_dev") is not None]
    n = len(members)
    lines = ["\n### 目标价兑现（名义收盘价，独立于分数收益校准）\n",
             "| n | 命中率 | 平均偏差 | 判读 |", "|---|---|---|---|"]
    if n < MIN_MATURED_N:
        lines.append(f"| {n} | — | — | 样本不足 n<{MIN_MATURED_N}，不做显著性结论 |")
    else:
        hit = sum(1 for r in members if r["target_hit"]) / n
        dev = sum(r["target_dev"] for r in members) / n
        lines.append(f"| {n} | {hit:.0%} | {dev:+.1%} | 描述性结果，仍需更多独立样本 |")
    return lines


def _evaluate_horizon(rep: dict, horizon: int) -> dict:
    term = rep["terms"][horizon]
    if not term["matured"]:
        return None
    result = rep.copy()
    result.update(ret=term["ret"], n_days=horizon, exit_date=term["exit_date"], price=term["price"])
    mkt = "HK" if len(rep["code"]) == 5 else "A"
    try:
        result["excess"] = term["ret"] - fetch_index_return(mkt, rep["entry_date"], term["exit_date"])
    except Exception:
        result["excess"] = None
    bounds = _target_bounds(rep.get("target_range"))
    if bounds:
        low, high = bounds
        result["target_hit"] = low <= term["price"] <= high
        result["target_dev"] = term["price"] / ((low + high) / 2) - 1
    return result


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    today = date.today().strftime("%Y%m%d")
    reps = collect_reports(directory)
    print(f"# 评分校准：{directory} 共 {len(reps)} 份有效报告（固定期限，{today} 数据截止）\n")

    ok, fail = [], 0
    for r in reps:
        try:
            r.update(fetch_return(r["code"], r["rep_date"], today))
            r["evaluated"] = {h: result for h in HORIZONS if (result := _evaluate_horizon(r, h))}
            ok.append(r)
        except Exception as e:
            fail += 1
            print(f"跳过 {r['file']}（收益计算失败: {e}）", file=sys.stderr)
    print(f"收益计算成功 {len(ok)} 份，失败 {fail} 份；未到期桶只标未到期，不回填最新价\n")

    print("## 明细（按报告日排序；每格=收益/超额/目标偏差）\n")
    print("| 公司 | 代码 | 报告日 | 质量 | 估值 | 时机 | 20日 | 60日 | 120日 | 250日 | 备注 |")
    print("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in sorted(ok, key=lambda x: x["rep_date"]):
        cells = []
        for horizon in HORIZONS:
            term = r["evaluated"].get(horizon)
            if not term:
                cells.append("未到期")
                continue
            exc = f"{term['excess']:+.1%}" if term.get("excess") is not None else "—"
            dev = f"{term['target_dev']:+.1%}" if term.get("target_dev") is not None else "—"
            cells.append(f"{term['ret']:+.1%}/{exc}/{dev}")
        note = "旧版单轨综合分，仅展示不入桶" if r.get("legacy") else ""
        print(f"| {r['company']} | {r['code']} | {r['rep_date']} | {r['quality']} | "
              f"{r['valuation']} | {r['timing']} | {' | '.join(cells)} | {note} |")

    for horizon in HORIZONS:
        group = [r["evaluated"][horizon] for r in ok if horizon in r["evaluated"]]
        ok_b = [r for r in group if not r.get("legacy")]
        for version in sorted({r.get("quality_version", 1) for r in ok_b}, key=str):
            version_reps = [r for r in ok_b if r.get("quality_version", 1) == version]
            for label, members in (("全口径（同股多份都计入，窗口有重叠）", version_reps),
                                   ("去重口径（同股仅取最早一份，独立窗口）", dedup_earliest(version_reps))):
                print(f"\n## 分桶统计——v{version}｜{label}｜{horizon}交易日")
                for line in _bucket_table(members, "quality", Q_BUCKETS, "质量分 × 实际收益"):
                    print(line)
        for label, members in (("全口径（同股多份都计入，窗口有重叠）", ok_b),
                               ("去重口径（同股仅取最早一份，独立窗口）", dedup_earliest(ok_b))):
            print(f"\n## 分桶统计——估值（跨质量版本）｜{label}｜{horizon}交易日")
            for line in _bucket_table(members, "valuation", V_BUCKETS, "估值分 × 实际收益"):
                print(line)
        for line in _target_table(group):
            print(line)

    print("\n---\n判读纪律：样本同 regime，窗口按各自期限对齐；每桶独立兑现样本 <10 只列计数，"
          "显著性结论仍需 30+ 独立样本，每月复跑积累。")


if __name__ == "__main__":
    main()
