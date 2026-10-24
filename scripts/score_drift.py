#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""score_drift.py — 同股两版报告的三轨分漂移分布（机制一临界宽度 ±0.3 的实测校准，v5.2.0）

用法:
    python score_drift.py [报告目录]     # 默认 D:\\个股深度分析

口径与判读纪律：
- 扫描目录内三代报告并读取 quality_version，按代码分组、日期排序；仅同质量版本的三轨报告
  相邻配对计算 |Δ质量分|；本轮估值算法未改，|Δ估值分| 允许跨质量版本配对；
  旧单轨综合分与跨版本质量分一律隔离。
- 配对差 = 真实信息变化 + 评分噪声的合量，是「总分漂移」的上界代理——用于校准机制一
  临界宽度（±0.3 初始值，scoring.md 承诺「按 archive 漂移实测校准」），不是纯噪声测量。
- 阈值判读：两轨 P80 取大者 < 0.2 → 支持收窄到 ±0.2（±0.1 低于单维度评分粒度
  0.12-0.2，形同虚设，不建议）；≥0.2 → 维持 ±0.3 有实测依据。样本 <10 对只描述不下结论。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import extract_review as E
# debt: stdout/stderr UTF-8 reconfigure 靠 extract_review 的 import 副作用保障（同 score_calibration）

DEFAULT_DIR = r"D:\个股深度分析"


def _pctile(xs, q):
    """线性插值分位；空序列返回 None。"""
    if not xs:
        return None
    xs = sorted(xs)
    k = (len(xs) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def scan_infos(directory: str):
    """扫描目录并读取报告内质量版本，返回代码分组与无法解析计数。"""
    by_code, skipped_unparsed = {}, 0
    for root, dirs, files in os.walk(directory):
        E.prune_scan_dirs(dirs)
        for fn in sorted(files):
            info = E.parse_report_name(fn)
            if info:
                path = os.path.join(root, fn)
                with open(path, encoding="utf-8", errors="replace") as f:
                    info["quality_version"] = E.detect_quality_version(f.read(), path)
                by_code.setdefault(E.norm_code(info["code"]), []).append(info)
            elif E._looks_like_report(fn):
                skipped_unparsed += 1
    return by_code, skipped_unparsed


def pair_deltas(by_code: dict):
    """质量仅同版配对；估值跨质量版本仍配对；旧单轨不计算质量漂移。"""
    dq, dv, pairs, cross_gen = [], [], 0, 0
    for _code, rs in sorted(by_code.items()):
        rs = sorted((r for r in rs if r["quality"] is not None), key=lambda r: r["date"])
        for a, b in zip(rs, rs[1:]):
            va = a.get("quality_version") or ("legacy-single-track" if a["valuation"] is None else 1)
            vb = b.get("quality_version") or ("legacy-single-track" if b["valuation"] is None else 1)
            if va == "legacy-single-track" or vb == "legacy-single-track":
                cross_gen += 1
                continue
            if str(va) != str(vb):
                cross_gen += 1
                if a["valuation"] is not None and b["valuation"] is not None:
                    dv.append(abs(b["valuation"] - a["valuation"]))
                continue
            pairs += 1
            dq.append(abs(b["quality"] - a["quality"]))
            if a["valuation"] is not None and b["valuation"] is not None:
                dv.append(abs(b["valuation"] - a["valuation"]))
    return dq, dv, pairs, cross_gen


def main():
    directory = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DIR
    by_code, skipped_unparsed = scan_infos(directory)
    dq, dv, pairs, cross_gen = pair_deltas(by_code)
    print(f"目录: {directory}")
    print(f"股票数: {len(by_code)}｜同股相邻两版配对: {pairs}"
          f"（质量分样本 {len(dq)} / 估值分样本 {len(dv)}；跨代配对隔离 {cross_gen} 对；"
          f"像报告但文件名无法解析跳过 {skipped_unparsed} 个）")
    for name, xs in (("质量分", dq), ("估值分", dv)):
        if xs:
            print(f"|Δ{name}|: P50={_pctile(xs, .5):.2f} P80={_pctile(xs, .8):.2f} "
                  f"max={max(xs):.2f} 均值={sum(xs) / len(xs):.2f}")
    if pairs < 10:
        print("样本 <10 对：只描述不下结论——机制一临界宽度维持 ±0.3，待样本积累。")
    else:
        p80 = max(_pctile(dq, .8) or 0, _pctile(dv, .8) or 0)
        if p80 < 0.2:
            print(f"P80={p80:.2f} < 0.2：实测支持收窄到 ±0.2（±0.1 低于单维度评分粒度，不建议）。")
        else:
            print(f"P80={p80:.2f} ≥ 0.2：维持 ±0.3 有实测依据。")


if __name__ == "__main__":
    main()
