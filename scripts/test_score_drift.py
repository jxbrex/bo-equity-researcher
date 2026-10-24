#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_score_drift.py — score_drift 离线回归测试（无网络，pytest 与直接运行均可）

覆盖（审计#小6：score_drift 整模块零测试，其 P50/P80 输出直接喂养机制一临界宽度
±0.3 的阈值决策，错了会静默带偏评分纪律）：
- _pctile 固定输入（乱序内部排序、空序列、q 边界）
- pair_deltas：同股相邻两版配对入样、跨命名代配对隔离跳过（纯函数，构造假 info 直测）
- scan_infos：真实三代命名文件名解析分组 + 「像报告但解析失败」显性计数
"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_drift as sd


def test_pctile_fixed_inputs():
    """线性插值分位钉死五个固定输入：空序列 None；乱序输入内部排序后取值；
    q=0 / 0.5 / 0.8（插值）/ 1（上限）。"""
    assert sd._pctile([], 0.5) is None
    xs = [0.5, 0.1, 0.4, 0.2, 0.3]  # 乱序
    assert sd._pctile(xs, 0) == 0.1
    assert sd._pctile(xs, 0.5) == 0.3
    assert abs(sd._pctile(xs, 0.8) - 0.42) < 1e-12   # 0.4 + (0.5-0.4)*0.2
    assert sd._pctile(xs, 1) == 0.5
    assert xs == [0.5, 0.1, 0.4, 0.2, 0.3], "内部排序不得改动调用方入参"


def _info(q, v, d, version=None):
    info = {"quality": q, "valuation": v, "date": d}
    if version is not None:
        info["quality_version"] = version
    return info


def test_pair_deltas_pairs_and_cross_gen_skip():
    """同版三轨报告才可配对；跨命名代及两份旧单轨报告均隔离。"""
    by_code = {
        "600309": [_info(6.0, 7.0, "2026-06-01"), _info(6.3, 7.2, "2026-07-01"),
                   _info(6.5, None, "2026-08-01")],
        "00700": [_info(6.9, None, "2026-07-15"), _info(7.0, None, "2026-08-15")],
    }
    dq, dv, pairs, cross_gen = sd.pair_deltas(by_code)
    assert pairs == 1, f"配对数: {pairs}"
    assert cross_gen == 2, f"跨代隔离数: {cross_gen}"
    assert dq == [pytest.approx(0.3)], f"质量分差样本: {dq}"
    assert dv == [pytest.approx(0.2)], f"估值分差样本: {dv}"


def test_pair_deltas_separates_quality_versions():
    by_code = {"600309": [
        _info(6.0, 7.0, "2026-06-01", 1), _info(6.8, 7.2, "2026-07-01", 2),
        _info(7.0, 7.4, "2026-08-01", 2), _info(7.1, 7.5, "2026-09-01", 2),
    ]}
    dq, dv, pairs, cross_gen = sd.pair_deltas(by_code)
    assert pairs == 2 and cross_gen == 1
    assert dq == [pytest.approx(0.2), pytest.approx(0.1)]
    assert dv == [pytest.approx(0.2), pytest.approx(0.2), pytest.approx(0.1)]


def test_pair_deltas_skips_none_quality():
    """quality 为 None 的文件名不进配对序列（单文件不成对、也不产生差值）。"""
    by_code = {"600309": [_info(None, None, "2026-06-01"), _info(6.0, 7.0, "2026-07-01")]}
    dq, dv, pairs, cross_gen = sd.pair_deltas(by_code)
    assert (dq, dv, pairs, cross_gen) == ([], [], 0, 0)


def test_scan_infos_parses_and_counts_unparsed():
    """文件名分组与报告内版本标记同时生效；旧单轨只识别、不配漂移。"""
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, "万华化学-600309-6.74-7.4-2026-08-01.html"),
                  "w", encoding="utf-8") as f:
            f.write('<div class="hero-track quality" data-quality-version="2"><div class="s-value">6.74</div></div>')
        open(os.path.join(d, "中国神华_601088_6.72_2026-08-07.html"), "w").close()
        open(os.path.join(d, "神秘600309报告.html"), "w").close()
        open(os.path.join(d, "随手笔记.html"), "w").close()
        by_code, skipped = sd.scan_infos(d)
    assert sorted(by_code) == ["600309", "601088"], f"分组: {sorted(by_code)}"
    assert by_code["600309"][0]["quality_version"] == 2
    assert by_code["601088"][0]["valuation"] is None
    assert by_code["601088"][0]["quality_version"] == "legacy-single-track"
    assert skipped == 1, f"解析失败计数: {skipped}"


if __name__ == "__main__":
    test_pctile_fixed_inputs()
    print("OK _pctile 固定输入（空序列/乱序/q 边界/不改入参）")
    test_pair_deltas_pairs_and_cross_gen_skip()
    print("OK pair_deltas 配对入样 + 跨代隔离计数")
    test_pair_deltas_separates_quality_versions()
    print("OK pair_deltas 质量版本隔离")
    test_pair_deltas_skips_none_quality()
    print("OK pair_deltas 跳过 quality=None")
    test_scan_infos_parses_and_counts_unparsed()
    print("OK scan_infos 三代命名分组 + 解析失败显性计数")
    print("全部 5 项测试通过")
