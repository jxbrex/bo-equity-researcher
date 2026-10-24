#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_calibration.py — score_calibration 纯函数回归测试（无网络；pytest 与直接运行均可）

覆盖：文件名解析接线（owner=extract_review.parse_report_name，两代命名）、分桶边界、同股去重口径。
v4.10.2：顶层断言收编为 def test_*（原 import 时执行，pytest 下零收集，失败表现为 collection error）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import score_calibration as sc


def test_parse_report_name_wiring():
    """文件名解析已合并至 extract_review.parse_report_name（score_calibration 经 import 复用），
    此处验证接线与两代命名口径（返回值由 (code, date) 元组改为 dict，断言随之改写）。"""
    r = sc.parse_report_name("万华化学-600309-6.74-7.4-复盘-2026-08-26.html")
    assert r["code"] == "600309" and r["date"] == "2026-08-26" and r["is_review"] is True
    r = sc.parse_report_name("中兴通讯-000063-4.92-2.3-2026-08-24.html")
    assert r["code"] == "000063" and r["date"] == "2026-08-24" and r["is_review"] is False
    r = sc.parse_report_name("腾讯控股-00700-6.93-8.2-复盘-2026-08-23.html")
    assert r["code"] == "00700" and r["date"] == "2026-08-23"
    r = sc.parse_report_name("中国神华_601088_6.72_2026-08-07.html")
    assert r["code"] == "601088" and r["date"] == "2026-08-07"
    assert r["valuation"] is None and r["quality"] == 6.72  # 旧 _ 命名：保留单轨综合分原值，不当 v1 质量分
    assert sc.parse_report_name("随手笔记.html") is None
    assert sc.parse_report_name("无日期-600989-6.0-5.0.html") is None


def test_bucket_of_edges():
    """分桶边界：阈值点归属（与决策矩阵口径：左闭右开）。"""
    assert sc.bucket_of(3.99, sc.Q_BUCKETS) == "质量<4 回避"
    assert sc.bucket_of(4.0, sc.Q_BUCKETS) == "质量4-5.5 一般"
    assert sc.bucket_of(7.0, sc.Q_BUCKETS) == "质量≥7 好公司"
    assert sc.bucket_of(8.0, sc.V_BUCKETS) == "估值≥8 深度安全边际"
    assert sc.bucket_of(7.99, sc.V_BUCKETS) == "估值6-8 偏便宜"
    assert sc.bucket_of(None, sc.V_BUCKETS) is None


def test_dedup_earliest():
    """同股去重：取最早一份。"""
    reps = [{"code": "00700", "rep_date": "2026-08-23"},
            {"code": "00700", "rep_date": "2026-08-14"},
            {"code": "600989", "rep_date": "2026-08-19"}]
    got = sc.dedup_earliest(reps)
    assert len(got) == 2
    assert next(r for r in got if r["code"] == "00700")["rep_date"] == "2026-08-14"


def test_collect_reports_walks_subdirs():
    """审计#16：报告放子目录时不得静默漏样本（与 extract_review/score_drift 递归口径一致）。
    正文提取 monkeypatch 掉——本用例只测扫描递归，文件名解析走真实 parse_report_name。"""
    import tempfile
    real_extract = sc.E.extract
    sc.E.extract = lambda path: {"prev": {"quality": 6.7, "valuation": 7.4, "date": "2026-08-01",
                                          "quality_version": 2}, "code": "600309"}
    try:
        with tempfile.TemporaryDirectory() as d:
            sub = os.path.join(d, "2026-08")
            os.makedirs(sub)
            with open(os.path.join(sub, "万华化学-600309-6.74-7.4-2026-08-01.html"),
                      "w", encoding="utf-8") as f:
                f.write("<html/>")
            reps = sc.collect_reports(d)
    finally:
        sc.E.extract = real_extract
    assert len(reps) == 1, f"子目录样本被漏: {reps}"
    assert reps[0]["code"] == "600309" and reps[0]["quality"] == 6.7
    assert reps[0]["quality_version"] == 2


def test_fetch_index_return_string_close():
    """审计#17：tushare 字符串 close 必须正常算出基准收益——缺失 float() 时
    字符串除法 TypeError 被外层 except 吞成 None，A 股超额收益整列静默丢失。"""
    real_ts = sc._ts
    sc._ts = lambda api_name, params: [
        {"trade_date": "20260801", "close": "4000.0"},
        {"trade_date": "20260829", "close": "4400.0"},
    ]
    sc._INDEX_CACHE.clear()  # 防同键缓存污染本用例
    try:
        ret = sc.fetch_index_return("A", "20260801", "20260829")
    finally:
        sc._ts = real_ts
        sc._INDEX_CACHE.clear()
    assert abs(ret - 0.1) < 1e-12, f"字符串 close 基准收益算错: {ret}"


def test_calibration_main_separates_quality_versions():
    import contextlib
    import io

    reps = [
        {"file": "v1.html", "code": "600001", "company": "甲", "rep_date": "2026-01-01",
         "quality": 6.0, "valuation": 5.0, "timing": 5.0, "price": 10, "quality_version": 1},
        {"file": "v2.html", "code": "600002", "company": "乙", "rep_date": "2026-01-02",
         "quality": 8.0, "valuation": 6.0, "timing": 5.0, "price": 10, "quality_version": 2},
        {"file": "legacy.html", "code": "600003", "company": "丙", "rep_date": "2024-01-02",
         "quality": 9.0, "valuation": None, "timing": None, "price": 10,
         "quality_version": "legacy-single-track", "legacy": True},
    ]
    real = sc.collect_reports, sc.fetch_return, sc.fetch_index_return, sys.argv
    sc.collect_reports = lambda _directory: [dict(r) for r in reps]
    sc.fetch_return = lambda code, _start, _today: {
        "ret": 0.1 if code == "600001" else 0.2, "n_days": 30, "entry_date": "20260102"}
    sc.fetch_index_return = lambda *_args: 0.0
    sys.argv = ["score_calibration.py", "测试"]
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            sc.main()
    finally:
        sc.collect_reports, sc.fetch_return, sc.fetch_index_return, sys.argv = real
    out = buf.getvalue()
    sections = out.split("## 分桶统计——")
    v1 = next(section for section in sections if section.startswith("v1"))
    v2 = next(section for section in sections if section.startswith("v2"))
    assert "| 质量≥7 好公司 | 0 |" in v1
    assert "| 质量≥7 好公司 | 1 |" in v2
    assert "估值分 × 实际收益" not in v1
    assert "估值分 × 实际收益" not in v2
    valuation = [section for section in sections if section.startswith("估值（跨质量版本）")]
    assert len(valuation) == 2
    assert all("估值分 × 实际收益" in section for section in valuation)
    assert not any(section.startswith("vlegacy") for section in sections)


if __name__ == "__main__":
    test_parse_report_name_wiring()
    print("OK parse_report_name 接线（owner=extract_review，两代命名 + 非报告排除）")
    test_bucket_of_edges()
    print("OK bucket_of（边界左闭右开 / None 不入桶）")
    test_dedup_earliest()
    print("OK dedup_earliest（同股取最早，独立窗口）")
    test_collect_reports_walks_subdirs()
    print("OK collect_reports 子目录递归扫描")
    test_fetch_index_return_string_close()
    print("OK fetch_index_return 字符串 close 不丢基准收益")
    test_calibration_main_separates_quality_versions()
    print("OK score_calibration 按质量版本分桶")
    print("全部 6 项测试通过")
