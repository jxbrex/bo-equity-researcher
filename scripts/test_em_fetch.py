#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_em_fetch.py — em_fetch.py 无网络单元测试（自包含、全 assert）

覆盖：
1. secid_of / to_ts_code 市场映射一致性（A股沪/深、北交所、B股、港股5位、非法输入报错）
2. 闰日路径：_ttm_cutoff 在 2/29 不炸
3. 同比文字化：_yoy 分母≤0 时返回 扭亏/转亏/减亏/增亏
4. 429 硬停：mock 掉 curl，断言 429 → RateLimitError 且不重试同一 URL、不回落 urllib

运行: python test_em_fetch.py（scripts 目录下）；或 pytest 收集（v4.10.2 起各区为独立 def test_* 用例）
"""
import os
import sys
import tempfile
import time
from datetime import date

import em_core
import em_fetch as em


def test_01_market_map():
    """1. 市场映射一致性"""

    # A股沪市（60/68 开头）
    assert em.secid_of("600989") == ("1.600989", "600989.SH", False)
    assert em_core.to_ts_code("600989") == "600989.SH"
    assert em.secid_of("688981") == ("1.688981", "688981.SH", False)
    # A股深市（00/30 开头，默认分支）
    assert em.secid_of("000528") == ("0.000528", "000528.SZ", False)
    assert em_core.to_ts_code("000528") == "000528.SZ"
    assert em.secid_of("300750") == ("0.300750", "300750.SZ", False)
    # 北交所（43/83/87/88/92 开头）：两边都必须是 BJ，secid 前缀 0.
    for bj in ("430047", "830799", "871245", "880001", "920001"):
        assert em.secid_of(bj) == (f"0.{bj}", f"{bj}.BJ", False), bj
        assert em_core.to_ts_code(bj) == f"{bj}.BJ", bj
    # B股（9 开头 → 沪市；200 开头深B → 深市默认分支）
    assert em.secid_of("900901") == ("1.900901", "900901.SH", False)
    assert em_core.to_ts_code("900901") == "900901.SH"
    assert em.secid_of("200002") == ("0.200002", "200002.SZ", False)
    # 港股 5 位
    assert em.secid_of("06082") == ("116.06082", "06082.HK", True)
    assert em_core.to_ts_code("06082") == "06082.HK"
    assert em.secid_of("00700") == ("116.00700", "00700.HK", True)
    # 带后缀输入：secid_of 剥后缀重判，to_ts_code 原样透传
    assert em.secid_of("600989.SH") == ("1.600989", "600989.SH", False)
    assert em_core.to_ts_code("600989.SH") == "600989.SH"
    assert em.secid_of("06082.HK") == ("116.06082", "06082.HK", True)
    # 非法输入：非纯数字或长度非 5/6 → 两边都报 ValueError，不静默按深市处理
    for bad in ("abc", "12345x", "1234567", "", "123", "60098A"):
        for fn in (em.secid_of, em_core.to_ts_code):
            try:
                fn(bad)
                raise AssertionError(f"{fn.__name__}({bad!r}) 应报 ValueError")
            except ValueError:
                pass
    print("1. 市场映射一致性 通过")



def test_02_leap_day():
    """2. 闰日路径"""

    # 2024-02-29 是闰日：旧写法 replace(year=2023) 会 ValueError，新写法必须正常
    assert em_core._ttm_cutoff(date(2024, 2, 29)) == "20230301"
    assert em_core._ttm_cutoff(date(2026, 8, 26)) == "20250826"
    print("2. 闰日路径 通过")



def test_03_yoy_text():
    """3. 同比文字化"""

    assert em_core._yoy(5, -3) == "扭亏"        # pre<0, cur>0
    assert em_core._yoy(-5, 10) == "转亏"       # pre>0, cur<0
    assert em_core._yoy(-3, -5) == "减亏"       # pre<0, 亏损收窄
    assert em_core._yoy(-6, -5) == "增亏"       # pre<0, 亏损扩大
    assert abs(em_core._yoy(110, 100) - 10.0) < 1e-9   # 正常正分母 → 数值百分比
    assert em_core._yoy(5, 0) is None           # pre==0 无意义
    assert em_core._yoy(None, 5) is None
    assert em_core._yoy(5, None) is None
    # 渲染：文字原样、数值走百分比
    assert em.yoy_text("扭亏") == "扭亏"
    assert em.yoy_text(10.0) == "10.0%"
    assert em.yoy_text(None) == "—"
    print("3. 同比文字化 通过")



def test_04_rate_limit_hardstop():
    """4. 429 硬停（无网络，mock curl/urllib）"""

    calls = {"curl": 0, "urllib": 0}


    class _FakeProc:
        """模拟 curl 返回 HTTP 429（-w 追加的状态码行）"""
        returncode = 0
        stdout = b'{"error": "too many requests"}\n429'
        stderr = b""


    _orig_run = em_core.subprocess.run
    _orig_urllib = em_core._get_via_urllib


    def _fake_run(*a, **k):
        calls["curl"] += 1
        return _FakeProc()


    def _fake_urllib(url):
        calls["urllib"] += 1
        return b"{}"


    em_core.subprocess.run = _fake_run
    em_core._get_via_urllib = _fake_urllib
    try:
        # get() 遇到 429：抛 RateLimitError，且不重试同一 URL、不回落 urllib
        try:
            em_core.get("http://example.invalid/x")
            raise AssertionError("429 应抛 RateLimitError")
        except em.RateLimitError:
            pass
        assert calls["curl"] == 1, f"429 禁止同 URL 原样重试（curl 被调了 {calls['curl']} 次）"
        assert calls["urllib"] == 0, "429 不应回落 urllib 重打"

        # 5xx 同样硬停
        class _Fake500(_FakeProc):
            stdout = b"<html>bad gateway</html>\n502"

        calls["curl"] = 0
        em_core.subprocess.run = lambda *a, **k: (calls.__setitem__("curl", calls["curl"] + 1), _Fake500())[1]
        try:
            em_core.get("http://example.invalid/y")
            raise AssertionError("502 应抛 RateLimitError")
        except em.RateLimitError:
            pass
        assert calls["curl"] == 1

        # 正常 200：去掉状态码行后返回 JSON
        class _Fake200(_FakeProc):
            stdout = b'{"data": {"x": 1}}\n200'

        em_core.subprocess.run = lambda *a, **k: _Fake200()
        assert em_core.get("http://example.invalid/ok") == {"data": {"x": 1}}

        # 网络层错误（连接失败）维持原逻辑：curl 失败 → urllib 兜底
        em_core.subprocess.run = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 连接失败"))
        em_core._get_via_urllib = lambda url: b'{"ok": true}'
        assert em_core.get("http://example.invalid/net") == {"ok": True}
    finally:
        em_core.subprocess.run = _orig_run
        em_core._get_via_urllib = _orig_urllib
    print("4. 429 硬停 通过")



def test_05_stale_code_guard():
    """5. 陈旧档拦截（无网络，mock get）"""
    import em_market

    _orig_get = em_core.get
    try:
        # 北交所旧代码（已切换 920 段）：东财返回全零 + 名称含「已切换」→ 必须报错
        em_core.get = lambda url: {"data": {"f43": 0, "f57": "832982", "f58": "锦波生物(已切换)",
                                            "f116": 0, "f162": 0, "f167": 0, "f168": 0, "f170": 0}}
        try:
            em_market._em_quote("0.832982")
            raise AssertionError("已切换标的全零行情必须抛 ValueError")
        except ValueError as e:
            assert "920" in str(e), "报错应提示北交所 920 新代码段"
        # 正常标的：有价格有市值 → 不拦
        em_core.get = lambda url: {"data": {"f43": 12099, "f57": "920982", "f58": "锦波生物",
                                            "f116": 1.39e10, "f162": 2473, "f167": 683,
                                            "f168": 103, "f170": -14}}
        q = em_market._em_quote("0.920982")
        assert q["名称"] == "锦波生物" and q["最新价"] == 120.99
    finally:
        em_core.get = _orig_get
    print("5. 陈旧档拦截 通过")



def test_06_token_alarm():
    """6. token 缺失硬告警（无网络，mock ts_call）"""
    # 神华事故教训：RuntimeError（token 未配置/接口报错）曾被裸 except 静默吞掉 → 白走降级链。
    # 收窄后：OSError 静默、RuntimeError 必须打印 ⚠️ 到 stderr。
    import io
    import contextlib

    _orig_ts = em_core.ts_call
    try:
        def _boom(*a, **k):
            raise RuntimeError("tushare token 未配置（mock）")

        em_core.ts_call = _boom
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            assert em.fetch_audit("600989") is None
            assert em.fetch_debt("600989") is None
            g = em.fetch_governance("600989")
            assert g["pledge"] is None and g["trades"] == []
            assert em.fetch_disclosure("600989") is None
        err = buf.getvalue()
        assert err.count("⚠️") >= 5, f"4 函数 6 个取数点的 RuntimeError 应逐条告警，实际 {err.count('⚠️')} 条"
        assert "token 未配置" in err, "告警应含原因"

        # OSError（网络层）仍静默
        em_core.ts_call = lambda *a, **k: (_ for _ in ()).throw(ConnectionError("mock 断网"))
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            assert em.fetch_audit("600989") is None
        assert "⚠️" not in buf.getvalue(), "网络层错误不应告警（静默走降级）"
    finally:
        em_core.ts_call = _orig_ts
    print("6. token 缺失硬告警 通过")



def test_07_disk_cache():
    """7. 磁盘缓存（无网络，mock urlopen + 临时目录）"""
    import json as _json
    import tempfile as _tmp

    _orig_dir, _orig_no = em_core._CACHE_DIR, em_core._NO_CACHE
    em_core._CACHE_DIR = _tmp.mkdtemp()
    em_core._NO_CACHE = False


    class _Resp:
        def __init__(self, payload):
            self._p = _json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return self._p


    _net = {"n": 0}
    _orig_open = em_core.urllib.request.urlopen
    _orig_token = em_core._tushare_token
    em_core._tushare_token = lambda: "test-token"
    em_core.urllib.request.urlopen = lambda *a, **k: (_net.__setitem__("n", _net["n"] + 1),
                                                 _Resp({"code": 0, "data": {"fields": ["a"],
                                                                            "items": [[1]]}}))[1]
    try:
        params = {"ts_code": "600989.SH", "start_date": "20200101"}
        em_core._TS_CACHE.clear()
        r1 = em_core.ts_call("daily_basic", params)
        em_core._TS_CACHE.clear()  # 清进程缓存：第二发必须命中磁盘
        r2 = em_core.ts_call("daily_basic", params)
        assert r1 == r2 == [{"a": 1}]
        assert _net["n"] == 1, f"磁盘缓存应省去第二次网络请求，实际 {_net['n']} 次"

        # TTL 过期（行情档 2h）→ 重新请求
        f = os.listdir(em_core._CACHE_DIR)[0]
        stale = os.path.join(em_core._CACHE_DIR, f)
        old = time.time() - 3 * 3600
        os.utime(stale, (old, old))
        em_core._TS_CACHE.clear()
        em_core.ts_call("daily_basic", params)
        assert _net["n"] == 2, "过期缓存应重新取数"

        # EM_FETCH_NO_CACHE 旁路：新鲜缓存也不读
        em_core._NO_CACHE = True
        em_core._TS_CACHE.clear()
        em_core.ts_call("daily_basic", params)
        assert _net["n"] == 3, "NO_CACHE 旁路必须强制走网络"
    finally:
        em_core.urllib.request.urlopen = _orig_open
        em_core._tushare_token = _orig_token
        em_core._CACHE_DIR, em_core._NO_CACHE = _orig_dir, _orig_no
        em_core._TS_CACHE.clear()
    print("7. 磁盘缓存（命中 / TTL 过期重取 / NO_CACHE 旁路）通过")



def test_08_mainbz_gross_profit():
    """8. E6 毛利额回填 + 维度合计行剔除（无网络，mock ts_call）"""
    # v4.8：fetch_mainop 各分部带 GROSS_PROFIT——tushare 取 bz_profit，缺则 收入−成本。
    # v4.10.3：fina_mainbz 额外返回的维度合计行（bz_item="产品"）必须剔除，且分母取该合计行金额
    # （=营业收入）——计入分母致占比腰斩（香农芯创 46.8% 实为 93.7%）；层级 payload 下用
    # sum(明细) 做分母会重复计数（东方电气 1.86x / 工商银行 3.66x 实证）。
    _orig_ts8 = em_core.ts_call
    try:
        em_core.ts_call = lambda api, params=None, fields="": [
            {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10, "bz_cost": 9e9,
             "bz_profit": 6e9},
            {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9, "bz_cost": 4e9,
             "bz_profit": None},   # 缺 bz_profit → 应按 收入−成本 回填 1e9
            {"end_date": "20251231", "bz_item": "烯烃", "bz_sales": 1.5e10, "bz_cost": 9e9,
             "bz_profit": 6e9},   # 与第一行同收入同成本 → 同源改名残留，应去重
            {"end_date": "20251231", "bz_item": "产品", "bz_sales": 2e10, "bz_cost": 1.3e10,
             "bz_profit": None},  # 维度合计行（= 前两行之和）→ 应剔除、不入返回
        ] if api == "fina_mainbz" else []
        mo = em.fetch_mainop("600989.SH")
        assert len(mo) == 2, f"同收入同成本重复条目应去重且合计行应剔除，实际 {len(mo)} 行"
        assert all(x["ITEM_NAME"] != "产品" for x in mo), "维度合计行不得进入返回"
        assert mo[0]["GROSS_PROFIT"] == 6e9, "bz_profit 应直接透传"
        assert mo[1]["GROSS_PROFIT"] == 1e9, "缺 bz_profit 应按 收入−成本 回填"
        # 扁平 payload：合计行恰为其余行之和，占比 0.75/0.25（含合计行未剔除时 0.375/0.125）
        assert abs(mo[0]["MBI_RATIO"] - 0.75) < 1e-9, "占比=分部收入÷合计行金额"
        assert abs(mo[1]["MBI_RATIO"] - 0.25) < 1e-9

        # 层级 payload（审计 P0-1 真 bug）：父级小计行与子级明细并存时 sum(明细) ≠ 合计行——
        # 分母必须取被剔除的合计行（=营业收入），否则各占比被放大 sum(明细)/合计行 倍
        em_core.ts_call = lambda api, params=None, fields="": [
            {"end_date": "20251231", "bz_item": "能源装备制造", "bz_sales": 2e10,
             "bz_cost": 1.3e10, "bz_profit": 7e9},   # 父级小计（保留：展示层另案）
            {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10,
             "bz_cost": 9e9, "bz_profit": 6e9},
            {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9,
             "bz_cost": 4e9, "bz_profit": 1e9},
            {"end_date": "20251231", "bz_item": "产品", "bz_sales": 2e10,
             "bz_cost": None, "bz_profit": None},        # 合计行=营业收入（分母）
        ] if api == "fina_mainbz" else []
        mo2 = em.fetch_mainop("600875.SH")
        assert len(mo2) == 3, f"层级 payload 应只剔合计行、保留父/子行，实际 {len(mo2)} 行"
        assert all(x["ITEM_NAME"] != "产品" for x in mo2), "维度合计行不得进入返回"
        ratios = {x["ITEM_NAME"]: x["MBI_RATIO"] for x in mo2}
        assert abs(ratios["能源装备制造"] - 1.0) < 1e-9, "父级小计÷合计行=1.0"
        assert abs(ratios["烯烃产品"] - 0.75) < 1e-9, "分母应为合计行 2e10（非 sum(明细)=4e10）"
        assert abs(ratios["焦化产品"] - 0.25) < 1e-9
    finally:
        em_core.ts_call = _orig_ts8
    print("8. E6 毛利额回填 通过")



def test_09_pe_band_timing():
    """9. PE 带 P25/P75 与时机素材（无网络，mock ts_call）"""
    _orig_ts9 = em_core.ts_call
    try:
        # 100 个交易日 pe_ttm = 1..100（单调，分位点可精确断言）
        rows_db = [{"trade_date": f"2025{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "pe_ttm": float(i + 1),
                    "pb": 1.5} for i in range(100)]
        em_core.ts_call = lambda api, params=None, fields="": rows_db if api == "daily_basic" else []
        band = em.fetch_pe_pb_band("600989")
        assert band["pe_p25"] == 25.0 and band["pe_p75"] == 75.0, \
            f"P25/P75 应为 25/75，实际 {band['pe_p25']}/{band['pe_p75']}"
        assert band["pe_min"] == 1.0 and band["pe_max"] == 100.0

        # 时机素材：300 个交易日 close = 1..300（递增）→ MA60/MA120/52周高低可精确断言
        import em_market
        em_market._A_DAILY_CACHE.clear()  # 从 miss 起跑，断言不受其它用例残留影响
        _dcalls = []

        def _ts9_daily(api, params=None, fields=""):
            if api == "daily":
                _dcalls.append(params)
                return rows_d
            return []

        rows_d = [{"trade_date": f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "close": float(i + 1)}
                  for i in range(300)]
        em_core.ts_call = _ts9_daily
        tm = em.fetch_timing_material("600989", False)
        assert tm["ma60"] == 270.5 and tm["ma120"] == 240.5, f"实际 {tm}"
        assert tm["high_52w"] == 300.0 and tm["low_52w"] == 51.0, "52周窗口=最后250个交易日"
        assert tm["n"] == 300
        # v4.10.3 Step 5：timing 走 _a_daily_series 后，首次 miss 回填 _A_DAILY_CACHE
        # （旧实现只读不回填），同进程二次调用命中缓存、不再发 daily
        assert len(_dcalls) == 1 and em_market._A_DAILY_CACHE.get("600989.SH") is not None
        em.fetch_timing_material("600989", False)
        assert len(_dcalls) == 1, f"二次调用应命中缓存，实际发 daily {len(_dcalls)} 次"
        # 数据不足 60 日 → None（新股不硬画）；须先清掉上面的回填才能走到该分支
        em_market._A_DAILY_CACHE.clear()
        em_core.ts_call = lambda api, params=None, fields="": rows_d[:30] if api == "daily" else []
        assert em.fetch_timing_material("600989", False) is None
    finally:
        em_core.ts_call = _orig_ts9
    print("9. PE 带 P25/P75 + 时机素材 通过")



def test_10_hk_daily_reversed():
    """9b. 港股日线倒序回归（v4.9.1 补充修订三）"""
    # tushare hk_daily 返回倒序（新→旧），_hk_daily_series 缓存前统一升序；否则 timing 的
    # MA60/52周窗口吃到最旧数据（美图 01357 实证：MA60/52周高低算在 2020 年数据上）。
    import em_market
    _orig_ts9b = em_core.ts_call
    try:
        # 300 个交易日 close=1..300 递增（日期升序时），按 tushare 真实形态倒序（新→旧）给出
        rows_hk = [{"trade_date": f"2026{(i // 28) + 1:02d}{(i % 28) + 1:02d}", "close": float(i + 1)}
                   for i in range(300)][::-1]
        em_core.ts_call = lambda api, params=None, fields="": rows_hk if api == "hk_daily" else []
        em_market._HK_DAILY_CACHE.pop("01357.HK", None)
        tm = em.fetch_timing_material("01357", True)
        assert tm["ma60"] == 270.5 and tm["ma120"] == 240.5, f"倒序未纠：实际 {tm}"
        assert tm["high_52w"] == 300.0 and tm["low_52w"] == 51.0, f"52周窗口=最新250个交易日，实际 {tm}"
        assert tm["price"] == 300.0 and tm["n"] == 300
        # 升序不破坏既有消费方：月线聚合仍取每月最后交易日收盘，输出升序
        km = em.fetch_kline_monthly("116.01357", 1, True)
        assert km[-1]["close"] == 300.0 and km[0]["date"] < km[-1]["date"], f"实际 {km[:1]}…{km[-1:]}"
        # 失败哨兵：ts_call 抛异常 → 进程内后续调用不再发网络（1次/小时限流下三连撞防护，
        # 2026-09-06 美图 01357 实测：首调限流后 E2/timing 重试全撞墙）
        calls = []
        def _boom(api, params=None, fields=""):
            calls.append(api)
            raise RuntimeError("频率超限")
        em_core.ts_call = _boom
        em_market._HK_DAILY_CACHE.pop("99999.HK", None)
        assert em.fetch_timing_material("99999", True) is None
        assert em.fetch_timing_material("99999", True) is None
        assert calls == ["hk_daily"], f"哨兵未生效：{calls}"
    finally:
        em_core.ts_call = _orig_ts9b
        em_market._HK_DAILY_CACHE.pop("01357.HK", None)
        em_market._HK_DAILY_CACHE.pop("99999.HK", None)
    print("9b. 港股日线倒序回归 + 失败哨兵 通过")



def test_11_monthly_pe_backfill():
    """10. E2 月线月末 PE(TTM) 回填（无网络，mock ts_call）"""
    # v4.8.1：fetch_kline_monthly A股 tushare 路径按月附 pe（月末交易日 pe_ttm，与 PE 带同参命中缓存）；
    # daily_basic 不可用 → 静默降级为仅 close（price_history 图自动只画股价线）
    _orig_ts10 = em_core.ts_call
    try:
        rows_m = [{"trade_date": "20260131", "close": 10.0},
                  {"trade_date": "20260228", "close": 11.0},
                  {"trade_date": "20260331", "close": 12.0}]
        rows_f = [{"trade_date": "20260131", "adj_factor": 1.0},
                  {"trade_date": "20260228", "adj_factor": 1.0},
                  {"trade_date": "20260331", "adj_factor": 1.0}]
        rows_db = [{"trade_date": "20260131", "pe_ttm": 15.0, "pb": 1.2},
                   {"trade_date": "20260228", "pe_ttm": 16.0, "pb": 1.2},
                   {"trade_date": "20260331", "pe_ttm": 17.0, "pb": 1.2}]

        def _ts10(api, params=None, fields=""):
            return {"monthly": rows_m, "adj_factor": rows_f, "daily_basic": rows_db}.get(api, [])
        em_core.ts_call = _ts10
        kl = em.fetch_kline_monthly("1.600989", 1, False)
        assert [k.get("pe") for k in kl] == [15.0, 16.0, 17.0], f"月末 PE 应回填，实际 {kl}"

        def _ts10b(api, params=None, fields=""):
            if api in ("monthly", "adj_factor"):
                return {"monthly": rows_m, "adj_factor": rows_f}[api]
            raise RuntimeError("daily_basic 不可用")
        em_core.ts_call = _ts10b
        kl2 = em.fetch_kline_monthly("1.600989", 1, False)
        assert all("pe" not in k for k in kl2) and [k["close"] for k in kl2] == [10.0, 11.0, 12.0], \
            f"daily_basic 失败应静默降级为仅 close，实际 {kl2}"
    finally:
        em_core.ts_call = _orig_ts10
    print("10. E2 月线月末 PE(TTM) 回填 通过")



def test_12_fields_third_param():
    """11. fetch_pe_pb_band 的 fields 必须走第三参（v4.8.3 回归）"""
    # 实证背景：fetch_pe_pb_band 曾把 fields 塞进 params——ts_call 键归一化会剔除 params 里的
    # fields（键尾为空串），与 E2 月末 PE 回填（第三参、键尾为字段串）永远不同键，透明缓存
    # 失效→重复请求，且请求不带 fields→全字段拉 5 年 daily_basic。
    _calls11 = []
    _orig_ts11 = em_core.ts_call
    def _ts11(api, params=None, fields=""):
        _calls11.append((api, dict(params or {}), fields))
        return [{"trade_date": "20260102", "pe_ttm": 15.0, "pb": 1.2}] * 30
    em_core.ts_call = _ts11
    try:
        em.fetch_pe_pb_band("600989")
        db = [(p, f) for (a, p, f) in _calls11 if a == "daily_basic"]
        assert db, "fetch_pe_pb_band 应调用 daily_basic"
        (params11, fields11), = db
        assert "fields" not in params11, "fields 不得塞进 params（被键归一化剔除→缓存永不命中）"
        assert fields11 == "ts_code,trade_date,pe_ttm,pb", f"fields 应走第三参，实际 {fields11!r}"
    finally:
        em_core.ts_call = _orig_ts11
    print("11. fetch_pe_pb_band fields 归一化 通过")




def test_13_holders_quarterly():
    """13. E4 季度序列（v4.11.0）：只取季末近 12 期 + 最新点；同截止日去重保留后写行；
    非季末披露点不进序列；环比在干净序列上重算（天齐 2026-07 月内四期 / 上游同日双行实证）。"""
    import em_owner

    def _mk(d, n):
        return {"end_date": d, "holder_num": n}

    qs = ["20230331", "20230630", "20230930", "20231231", "20240331", "20240630",
          "20240930", "20241231", "20250331", "20250630", "20250930", "20251231", "20260331"]
    rows = [_mk("20230101", 50)]                       # 非季末且最旧：应被排除
    rows += [_mk(d, 100 + i * 10) for i, d in enumerate(qs)]
    rows += [_mk("20250630", 618)]                     # 同截止日双行：保留后写行
    rows += [_mk("20260831", 700)]                     # 最新非季末点：追加
    _orig = em_core.ts_call
    try:
        em_core.ts_call = lambda name, params, **k: rows
        q = em_owner.fetch_holders_quarterly("002466")
    finally:
        em_core.ts_call = _orig
    dates = [r["END_DATE"] for r in q]
    assert dates[0] == "20230630", f"近 12 期截断应从 20230630 起，实际 {dates[0]}"
    assert "20230331" not in dates and "20230101" not in dates
    assert dates.count("20250630") == 1, "同截止日应去重为一行"
    assert q[-1]["END_DATE"] == "20260831", "最新非季末点应追加为末点"
    by = {r["END_DATE"]: r for r in q}
    assert by["20250630"]["HOLDER_NUM"] == 618, "去重应保留后写行"
    # 环比在干净序列上重算：20250630 前值=上季末 20250331(180) → 618/180-1 ≈ +243.3%
    assert by["20250630"]["HOLDER_NUM_RATIO"] == round((618 / 180 - 1) * 100, 1)
    assert q[0]["HOLDER_NUM_RATIO"] is None, "首点无前值，环比应为 None"
    print("13. holders 季度序列 通过")




def test_14_monthly_ohlc():
    """14. E2 月线 OHLC（v4.11.0）：A股 OHLC 随 close 同因子前复权；缺键行仅 close（不炸链路）；
    港股日线聚合月线 OHLC（首行缺键由首个带 OHLC 行补齐）。"""
    import em_market
    # A股：monthly 带 OHLC + adj_factor 2.0→4.0（前复权 ×0.5 统一到最新因子）
    monthly_rows = [
        {"trade_date": "20250131", "open": 20.0, "high": 22.0, "low": 19.0, "close": 21.0},
        {"trade_date": "20250228", "high": 24.0, "low": 20.5, "close": 23.0},  # 缺 open → 仅 close
    ]
    fac = [{"trade_date": "20250131", "adj_factor": "2.0"},
           {"trade_date": "20250228", "adj_factor": "4.0"}]
    _orig = em_core.ts_call
    try:
        def _ts(name, params, **k):
            return {"monthly": monthly_rows, "adj_factor": fac}.get(name, [])
        em_core.ts_call = _ts
        kl = em_market.fetch_kline_monthly("1.600989", 1, False)
    finally:
        em_core.ts_call = _orig
    assert kl[0]["open"] == 10.0 and kl[0]["high"] == 11.0 and kl[0]["low"] == 9.5,         f"OHLC 应同因子前复权，实际 {kl[0]}"
    assert kl[0]["close"] == 10.5
    assert "open" not in kl[1] and kl[1]["close"] == 23.0, "缺 open 的行应仅 close（因子 4/4=1 不降权）"
    # 港股：日线聚合 OHLC + 首行缺键补齐
    import em_market as emm
    hk_rows = [
        {"trade_date": "20260202", "close": 10.0},                                   # 缺 OHLC
        {"trade_date": "20260205", "open": 10.2, "high": 12.0, "low": 9.8, "close": 11.0},
        {"trade_date": "20260227", "open": 11.0, "high": 13.0, "low": 10.8, "close": 12.5},
    ]
    _orig2 = emm._hk_daily_series
    try:
        emm._hk_daily_series = lambda ts: hk_rows
        hk = emm.fetch_kline_monthly("116.01357", 1, True)
    finally:
        emm._hk_daily_series = _orig2
    assert hk[-1]["open"] == 10.2 and hk[-1]["high"] == 13.0 and hk[-1]["low"] == 9.8         and hk[-1]["close"] == 12.5, f"港股聚合/补齐不符：{hk[-1]}"
    print("14. 月线 OHLC（前复权/缺键回退/港股聚合补齐）通过")


def test_15_e4_empty_hints():
    """15. E4 降级提示（v4.11.1，审核 D6）：A股户数全空 → 降级提示行（对齐 E3/E5/E6 纪律）；
    主序列有数据但季度序列 <3 期 → 提示 holders 图不生成。"""
    import em_fetch
    _o1, _o2 = em_fetch.fetch_holders, em_fetch.fetch_holders_quarterly
    try:
        em_fetch.fetch_holders = lambda code: []
        em_fetch.fetch_holders_quarterly = lambda code: []
        out = "\n".join(em_fetch._sec_e4("600000", False))
        assert "未获取到股东户数数据" in out and "请降级" in out, \
            f"A股全空应有降级提示，实际：{out!r}"
        em_fetch.fetch_holders = lambda code: [
            {"END_DATE": "2026-06-30", "HOLDER_NUM": 100, "HOLDER_NUM_RATIO": None}]
        em_fetch.fetch_holders_quarterly = lambda code: [
            {"END_DATE": "2026-06-30", "HOLDER_NUM": 100, "HOLDER_NUM_RATIO": None}]
        out = "\n".join(em_fetch._sec_e4("600000", False))
        assert "季度序列不足 3 期" in out, f"季度序列 <3 期应提示，实际：{out!r}"
    finally:
        em_fetch.fetch_holders, em_fetch.fetch_holders_quarterly = _o1, _o2
    print("15. E4 空数据降级提示 通过")


def test_16_consensus_detail():
    """16. E5 逐机构明细（v4.11.1，gap_plot 数据源）：同机构 180 天内多份取最新、
    np 万元→亿换算、目标价明细取 (min+max)/2、180 天外研报排除。"""
    import em_owner
    rows = [
        {"org_name": "野村", "report_date": "20260830", "quarter": "2026Q4",
         "np": 9520000, "eps": 2.1, "min_price": 30, "max_price": 32, "rating": "买入"},
        {"org_name": "野村", "report_date": "20260701", "quarter": "2026Q4", "np": 9000000},
        {"org_name": "摩根士丹利", "report_date": "20260812", "quarter": "2026Q4",
         "np": 8780000, "eps": 2.0},
        {"org_name": "老券商", "report_date": "20250101", "quarter": "2026Q4", "np": 1000000},
    ]
    _orig = em_core.ts_call
    try:
        em_core.ts_call = lambda name, params, **k: rows
        c = em_owner.fetch_consensus("600938")
    finally:
        em_core.ts_call = _orig
    d = c["detail"]["2026"]
    assert len(d) == 2, f"180 天外研报应排除、同机构应去重，实际 {d}"
    by = {x["org"]: x for x in d}
    assert by["野村"]["np"] == 952.0, f"万元→亿且取最新（0830 覆盖 0701），实际 {by['野村']}"
    assert "老券商" not in by
    assert c["aim_detail"][0]["tp"] == 31.0, f"目标价明细应取 (30+32)/2，实际 {c['aim_detail']}"
    print("16. E5 逐机构明细 通过")


def test_17_period_track():
    """17. 报告期进度（v5.0 第 3 章数据源，无网络 mock ts_call）：
    A股中报——累计四值+同比、单季拆分 Q2=H1−Q1、近三年同期占比带；
    A股年报期——is_annual 且无占比带、Q4=年报−前三季；港股中报——hk_income 降级口径。"""
    inc = [
        {"end_date": "20260630", "report_type": "1", "total_revenue": 200e8, "n_income_attr_p": 30e8},
        {"end_date": "20260331", "report_type": "1", "total_revenue": 90e8, "n_income_attr_p": 12e8},
        {"end_date": "20250630", "report_type": "1", "total_revenue": 180e8, "n_income_attr_p": 25e8},
        {"end_date": "20250331", "report_type": "1", "total_revenue": 80e8, "n_income_attr_p": 10e8},
        {"end_date": "20251231", "report_type": "1", "total_revenue": 400e8, "n_income_attr_p": 50e8},
        {"end_date": "20240630", "report_type": "1", "total_revenue": 150e8, "n_income_attr_p": 20e8},
        {"end_date": "20241231", "report_type": "1", "total_revenue": 380e8, "n_income_attr_p": 45e8},
        {"end_date": "20230630", "report_type": "1", "total_revenue": 140e8, "n_income_attr_p": 18e8},
        {"end_date": "20231231", "report_type": "1", "total_revenue": 350e8, "n_income_attr_p": 40e8},
    ]
    cf = [{"end_date": "20260630", "n_cashflow_act": 35e8},
          {"end_date": "20250630", "n_cashflow_act": 28e8}]
    ind = [{"end_date": "20260630", "profit_dedt": 28e8, "grossprofit_margin": 40.0},
           {"end_date": "20250630", "profit_dedt": 23e8}]
    _orig = em_core.ts_call
    import em_finance
    _orig_f10 = em_finance._em_f10
    try:
        # v5.8.4：F10 通道一并打桩返空——v5.8.0 整期前移分支在真实 F10（或磁盘缓存）期次
        # 领先 mock 数据时会点火（三季报披露季 test_17 因此变红）；前移/补齐/兜底由 test_18 专项覆盖
        em_finance._em_f10 = lambda *a, **k: []
        em_core.ts_call = lambda api, params=None, fields="": {
            "income": inc, "cashflow": cf, "fina_indicator": ind}.get(api, [])
        t = em.fetch_period_track("600989", "600989.SH")
        assert t["period"] == "2026中报" and t["is_annual"] is False
        assert (t["rev"], t["np"], t["np_dedt"], t["ocf"], t["gm"]) == (200.0, 30.0, 28.0, 35.0, 40.0)
        assert abs(t["rev_yoy"] - (200 / 180 - 1) * 100) < 0.01 and abs(t["np_yoy"] - 20.0) < 0.01
        assert t["np_dedt_yoy"] is not None and t["ocf_yoy"] is not None
        # 单季拆分：2026Q2 = H1−Q1 = (200−90, 30−12)；2025Q2 = (180−80, 25−10)
        assert (t["sq_label"], t["sq_rev"], t["sq_np"]) == ("2026Q2", 110.0, 18.0)
        assert (t["sq_prev_label"], t["sq_prev_rev"], t["sq_prev_np"]) == ("2025Q2", 100.0, 15.0)
        assert abs(t["sq_rev_yoy"] - 10.0) < 0.01 and abs(t["sq_np_yoy"] - 20.0) < 0.01
        # 占比带：净利 18/40=45.0、20/45≈44.4、25/50=50.0；营收 140/350=40.0、150/380≈39.5、180/400=45.0
        assert t["band_np"] == [44.4, 50.0] and t["band_rev"] == [39.5, 45.0], \
            f"实际 {t['band_np']}/{t['band_rev']}"
        assert t["band_years"] == [2023, 2024, 2025]

        # 年报期：最新 20251231 → is_annual、band None、Q4=年报−前三季
        inc2 = [r for r in inc if r["end_date"] <= "20251231"] + \
               [{"end_date": "20250930", "report_type": "1", "total_revenue": 300e8,
                 "n_income_attr_p": 40e8}]
        em_core.ts_call = lambda api, params=None, fields="": {
            "income": inc2, "cashflow": [], "fina_indicator": []}.get(api, [])
        # F7：secucode=None——夹具自足（fina_indicator 空 → np_dedt/gm 为 None 会触发
        # F10 字段级补齐触网，离线必红）；F10 补齐与兜底路径由 test_18 专项 mock 覆盖
        t2 = em.fetch_period_track("600989")
        assert t2["is_annual"] is True and t2["band_np"] is None and t2["band_rev"] is None
        assert (t2["sq_label"], t2["sq_rev"], t2["sq_np"]) == ("2025Q4", 100.0, 10.0)

        # 港股中报：hk_income 降级口径（无扣非/现金流），占比带用 0630÷1231
        hk = [
            {"end_date": "20260630", "total_revenue": 50e8, "n_income_attr_p": 8e8},
            {"end_date": "20250630", "total_revenue": 45e8, "n_income_attr_p": 7e8},
            {"end_date": "20251231", "total_revenue": 100e8, "n_income_attr_p": 15e8},
            {"end_date": "20240630", "total_revenue": 40e8, "n_income_attr_p": 6e8},
            {"end_date": "20241231", "total_revenue": 90e8, "n_income_attr_p": 13e8},
            {"end_date": "20230630", "total_revenue": 38e8, "n_income_attr_p": 5.5e8},
            {"end_date": "20231231", "total_revenue": 85e8, "n_income_attr_p": 12e8},
        ]
        em_core.ts_call = lambda api, params=None, fields="": hk if api == "hk_income" else []
        t3 = em.fetch_hk_period_track("06082")
        assert t3["period"] == "2026中报" and t3["rev"] == 50.0 and t3["np"] == 8.0
        assert t3["np_dedt"] is None and t3["ocf"] is None
        assert t3["band_np"] == [45.8, 46.7], f"实际 {t3['band_np']}"
    finally:
        em_core.ts_call = _orig
        em_finance._em_f10 = _orig_f10
    print("17. 报告期进度（中报/年报期/港股）通过")


def test_18_period_track_f10_fallback():
    """18. F10 兜底与字段级补齐（无网络 mock _em_f10/ts_call）：
    tushare 全空 → 东财 F10 混合期行兜底产出正确 period/sq/band；
    v5.8.0 F10 期次领先（披露当晚 F10 更快）→ 整章前移 F10 口径并带 src 标记，
    新期行营收/归母缺失则放弃前移、且不跨期借字段；期次一致 → 字段级补齐；
    F12——某年 np/rev 皆无有效样本 → band_years 不收录该年。"""
    import em_finance
    f10_rows = [
        {"REPORT_DATE": "2026-06-30", "TOTALOPERATEREVE": 200e8, "PARENTNETPROFIT": 30e8,
         "KCFJCXSYJLR": 28e8, "NETCASH_OPERATE_PK": 35e8, "XSMLL": 40.0},
        {"REPORT_DATE": "2026-03-31", "TOTALOPERATEREVE": 90e8, "PARENTNETPROFIT": 12e8},
        {"REPORT_DATE": "2025-06-30", "TOTALOPERATEREVE": 180e8, "PARENTNETPROFIT": 25e8},
        {"REPORT_DATE": "2025-03-31", "TOTALOPERATEREVE": 80e8, "PARENTNETPROFIT": 10e8},
        {"REPORT_DATE": "2025-12-31", "TOTALOPERATEREVE": 400e8, "PARENTNETPROFIT": 50e8},
        {"REPORT_DATE": "2024-06-30", "TOTALOPERATEREVE": 150e8, "PARENTNETPROFIT": 20e8},
        {"REPORT_DATE": "2024-12-31", "TOTALOPERATEREVE": 380e8, "PARENTNETPROFIT": 45e8},
        {"REPORT_DATE": "2023-06-30", "TOTALOPERATEREVE": 140e8, "PARENTNETPROFIT": 18e8},
        {"REPORT_DATE": "2023-12-31", "TOTALOPERATEREVE": 350e8, "PARENTNETPROFIT": 40e8},
    ]
    _o1, _o2 = em_core.ts_call, em_finance._em_f10
    try:
        # tushare 全空 → F10 混合期行兜底
        em_core.ts_call = lambda api, params=None, fields="": []
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: f10_rows[:size]
        t = em_finance.fetch_period_track("600989", "600989.SH")
        assert t["period"] == "2026中报" and (t["rev"], t["np"]) == (200.0, 30.0)
        assert t["np_dedt"] == 28.0 and t["gm"] == 40.0
        assert (t["sq_label"], t["sq_rev"], t["sq_np"]) == ("2026Q2", 110.0, 18.0)
        assert t["band_np"] == [44.4, 50.0] and t["band_years"] == [2023, 2024, 2025]

        # v5.8.0：tushare 最新 2026一季，F10 最新行 2026中报（披露当晚 F10 更快）→
        # 整章前移 F10 口径并带 src 标记（旧 F8「期次不一致不借新期字段」的守卫语义
        # 由前移分支取代：不再把新期字段借进旧期，而是整期换成 F10 新期口径）
        inc = [{"end_date": "20260331", "report_type": "1", "total_revenue": 90e8,
                "n_income_attr_p": 12e8}]
        em_core.ts_call = lambda api, params=None, fields="": {"income": inc}.get(api, [])
        t2 = em_finance.fetch_period_track("600989", "600989.SH")
        assert t2["period"] == "2026中报" and t2.get("src") == "em_f10", \
            f"F10 期次领先应整章前移 F10 口径，实际 {t2['period']}/{t2.get('src')}"
        assert t2["np_dedt"] == 28.0 and t2["gm"] == 40.0
        # F10 新期行营收/归母缺失 → 放弃前移退回 tushare 旧期，且仍不跨期借字段
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: [
            {"REPORT_DATE": "2026-06-30", "XSMLL": 40.0}]
        t2b = em_finance.fetch_period_track("600989", "600989.SH")
        assert t2b["period"] == "2026一季" and t2b.get("src") is None
        assert t2b["np_dedt"] is None and t2b["gm"] is None, \
            f"前移放弃后不得跨期借字段，实际 {t2b['np_dedt']}/{t2b['gm']}"
        # 期次一致 → 正常借（F10 最新行同为 2026一季 → 补齐 np_dedt/gm）
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: [
            {"REPORT_DATE": "2026-03-31", "KCFJCXSYJLR": 11e8, "XSMLL": 41.0}]
        t3 = em_finance.fetch_period_track("600989", "600989.SH")
        assert t3["np_dedt"] == 11.0 and t3["gm"] == 41.0 and t3.get("src") is None

        # F12：2024 全年 np/rev 皆缺 → 两条带都不收录 2024，band_years 不再虚挂
        rows2 = [dict(r) for r in f10_rows]
        for r in rows2:
            if r["REPORT_DATE"] == "2024-12-31":
                r["PARENTNETPROFIT"] = None
                r["TOTALOPERATEREVE"] = None
        em_core.ts_call = lambda api, params=None, fields="": []
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: rows2[:size]
        t4 = em_finance.fetch_period_track("600989", "600989.SH")
        assert t4["band_years"] == [2023, 2025], f"实际 {t4['band_years']}"
        assert t4["band_np"] == [45.0, 50.0], f"实际 {t4['band_np']}"
    finally:
        em_core.ts_call, em_finance._em_f10 = _o1, _o2
    print("18. F10 兜底/字段级补齐期次校验/band_years 收录口径 通过")


def test_18b_period_track_dup_merge():
    """18b. 同报告期重复行字段级合并（v5.8.0，中国巨石 20250630 实证）：fina_indicator
    同 end_date 重复行字段互缺，dict 直推后行整行覆盖会把 profit_dedt 有效值洗成 None
    → 扣非同比/单季扣非对比双 null；_merge_by_period 非 None 优先合并后应正常产出。"""
    inc = [
        {"end_date": "20260630", "report_type": "1", "total_revenue": 200e8, "n_income_attr_p": 30e8},
        {"end_date": "20260331", "report_type": "1", "total_revenue": 90e8, "n_income_attr_p": 12e8},
        {"end_date": "20250630", "report_type": "1", "total_revenue": 180e8, "n_income_attr_p": 25e8},
        {"end_date": "20250331", "report_type": "1", "total_revenue": 80e8, "n_income_attr_p": 10e8},
    ]
    ind = [{"end_date": "20260630", "profit_dedt": 28e8},
           {"end_date": "20260331", "profit_dedt": 12e8},
           {"end_date": "20250630", "profit_dedt": 23e8},
           {"end_date": "20250630", "profit_dedt": None},   # 重复空行（后行整行覆盖即事故）
           {"end_date": "20250331", "profit_dedt": 11e8}]
    _orig = em_core.ts_call
    try:
        em_core.ts_call = lambda api, params=None, fields="": {
            "income": inc, "cashflow": [], "fina_indicator": ind}.get(api, [])
        t = em.fetch_period_track("600989")   # secucode=None：夹具自足不触 F10
        assert t["np_dedt"] == 28.0
        assert abs(t["np_dedt_yoy"] - (28 / 23 - 1) * 100) < 0.01, f"实际 {t['np_dedt_yoy']}"
        assert t["sq_dedt"] == 16.0 and t["sq_prev_dedt"] == 12.0, \
            f"实际 {t['sq_dedt']}/{t['sq_prev_dedt']}"
        assert abs(t["sq_dedt_yoy"] - (16 / 12 - 1) * 100) < 0.01
    finally:
        em_core.ts_call = _orig
    print("18b. 同报告期重复行字段级合并 通过")


def test_19_growth_sigma_parity():
    """19. v5.2.0：scoring.growth_sigma 与 em_finance._growth_sigma 双副本 parity 钉住
    （数值/None/亏损基数路径等价；归一宽严差异是刻意的——docstring 互指，
    脏字符串路径不纳入本用例）。"""
    from scoring import growth_sigma
    from em_finance import _growth_sigma
    for vals in ([75, 79, 83, 86, 88], [10, -5, 8, 12, 15], [55.27, 74.46, 91.65],
                 [None, 100, 110, 121, 133], [1, 2, 3], []):
        assert growth_sigma(vals) == _growth_sigma(vals), f"parity 漂移: {vals}"
    print("19. growth_sigma 双副本 parity 通过")



def test_20_latest_quarter_yoy_year_guard():
    """20. 最新季度同比基数年份守卫（审计 #2，无网络 mock ts_call）：同比找基数只比 end_date
    月日、不校年份——缺 2024 三季报时会把 2023Q3 当去年同期，同比静默错两年；修法后缺期
    输出 None，补齐后同比恢复正确值。"""
    import em_finance
    _orig_ts20 = em_core.ts_call
    try:
        # 缺 2024Q3：序列里最近的前期是 2023Q3（月日相同但年份差 2）→ 不得当基数
        rows_missing = [
            {"end_date": "20250930", "ann_date": "20251030", "report_type": "1", "n_income_attr_p": 120e8},
            {"end_date": "20250630", "ann_date": "20250828", "report_type": "1", "n_income_attr_p": 80e8},
            {"end_date": "20250331", "ann_date": "20250428", "report_type": "1", "n_income_attr_p": 50e8},
            {"end_date": "20230930", "ann_date": "20231027", "report_type": "1", "n_income_attr_p": 100e8},
        ]
        em_core.ts_call = lambda api, params=None, fields="": rows_missing if api == "income" else []
        q = em_finance._ts_latest_quarter("600989")
        assert q["PARENTNETPROFITTZ"] is None, \
            f"缺去年同期时同比应为 None（不得拿两年前同期当基数），实际 {q['PARENTNETPROFITTZ']}"
        # 补齐 2024Q3（利润 60e8，与 2023Q3 的 100e8 区分）：同比=120/60-1=100%
        rows_full = rows_missing + [
            {"end_date": "20240930", "ann_date": "20241030", "report_type": "1", "n_income_attr_p": 60e8}]
        em_core.ts_call = lambda api, params=None, fields="": rows_full if api == "income" else []
        q2 = em_finance._ts_latest_quarter("600989")
        assert abs(q2["PARENTNETPROFITTZ"] - 100.0) < 0.01, \
            f"补齐去年同期后同比应按 2024Q3 基数算 100%，实际 {q2['PARENTNETPROFITTZ']}（疑似仍拿 2023Q3 当基数）"
    finally:
        em_core.ts_call = _orig_ts20
    print("20. 最新季度同比基数年份守卫 通过")



def test_21_mainop_hier_gp_ratio():
    """21. E6 毛利占比分母取合计行口径（审计 #3，无网络 mock ts_call/_sec_e6）：
    层级 payload（父级小计+子级明细并存）下 sum(明细毛利) 重复计数（工商银行型合计可达
    366%）——分母必须用被剔除合计行的毛利（fetch_mainop 带出 _TOTAL_GP）；无 _TOTAL_GP
    （东财兜底形态）退回 sum(GROSS_PROFIT)。父+子并存时全行合计>100% 是层级 payload 固有
    形态，同 test_08 已钉的 MBI_RATIO 口径（父级=100%、子级合计≈100%）。"""
    import re
    _orig_ts21 = em_core.ts_call
    try:
        # 合计行毛利 7e9（=父级小计；子级为其分解 6e9+1e9）——sum(明细)=14e9 重复计数
        em_core.ts_call = lambda api, params=None, fields="": [
            {"end_date": "20251231", "bz_item": "能源装备制造", "bz_sales": 2e10,
             "bz_cost": 1.3e10, "bz_profit": 7e9},   # 父级小计（保留展示）
            {"end_date": "20251231", "bz_item": "烯烃产品", "bz_sales": 1.5e10,
             "bz_cost": 9e9, "bz_profit": 6e9},
            {"end_date": "20251231", "bz_item": "焦化产品", "bz_sales": 5e9,
             "bz_cost": 4e9, "bz_profit": 1e9},
            {"end_date": "20251231", "bz_item": "产品", "bz_sales": 2e10,
             "bz_cost": None, "bz_profit": 7e9},   # 维度合计行（毛利应随返回带出）
        ] if api == "fina_mainbz" else []
        mo = em.fetch_mainop("600875.SH")
        assert getattr(mo, "_TOTAL_GP", None) == 7e9, "合计行毛利（bz_profit）应随返回带出"
        lines = em._sec_e6("600875.SH", False)
        txt = "\n".join(lines)
        # 分母=合计行毛利 7e9：父级 100.0%、子级 85.7%/14.3%（旧实现分母 14e9 → 父级 50.0%，红）
        assert "能源装备制造" in txt and "毛利占比100.0%" in txt, \
            f"父级小计应占合计行毛利 100%，实际:\n{txt}"
        assert "毛利占比85.7%" in txt and "毛利占比14.3%" in txt, f"子级占比应对齐合计行口径:\n{txt}"
        pcts = dict(re.findall(r"^(.+?): .*?（毛利占比([\d.]+)%）", txt, re.M))
        assert abs(float(pcts["烯烃产品"]) + float(pcts["焦化产品"]) - 100.0) < 0.2, \
            f"子级明细毛利占比合计应≈100%，实际 {pcts}"

        # 无 _TOTAL_GP（东财兜底形态）→ 退回 sum(GROSS_PROFIT)：1.5e9/5e8 → 75%/25%
        _orig_fm = em.fetch_mainop
        try:
            em.fetch_mainop = lambda sec: [
                {"REPORT_DATE": "2025-12-31", "REPORT_NAME": "2025年报", "MAINOP_TYPE": "2",
                 "ITEM_NAME": "A", "MAIN_BUSINESS_INCOME": 3e9, "MBI_RATIO": 0.6,
                 "GROSS_RPOFIT_RATIO": 0.5, "GROSS_PROFIT": 1.5e9},
                {"REPORT_DATE": "2025-12-31", "REPORT_NAME": "2025年报", "MAINOP_TYPE": "2",
                 "ITEM_NAME": "B", "MAIN_BUSINESS_INCOME": 2e9, "MBI_RATIO": 0.4,
                 "GROSS_RPOFIT_RATIO": 0.25, "GROSS_PROFIT": 5e8},
            ]
            txt2 = "\n".join(em._sec_e6("600989.SH", False))
            assert "毛利占比75.0%" in txt2 and "毛利占比25.0%" in txt2, \
                f"无 _TOTAL_GP 应退回 sum(明细毛利) 作分母，实际:\n{txt2}"
        finally:
            em.fetch_mainop = _orig_fm
    finally:
        em_core.ts_call = _orig_ts21
    print("21. E6 毛利占比合计行分母 通过")



def test_22_out_atomic_write():
    """22. --out 原子落盘（审计 #8，无网络 mock summarize/json.dump）：照抄 em_cache.dc_write
    模式——先写 PID 后缀 tmp 再 os.replace；成功落盘不留 .tmp，json.dump 中途抛异常时目标
    文件不被截断（旧实现直接 open(out) 写，中断留半个 JSON）。"""
    _orig_sv, _orig_cap, _orig_argv = em.summarize, dict(em._CAPTURE), sys.argv
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "quote.json")
        try:
            em.summarize = lambda *a, **k: "ok"
            em._CAPTURE.clear()
            em._CAPTURE.update({"price": 10.5})
            sys.argv = ["em_fetch.py", "600989", f"--out={out}"]
            em.main()
            assert os.path.exists(out), "落盘文件应存在"
            import json as _json
            payload = _json.loads(open(out, encoding="utf-8").read())
            assert payload["price"] == 10.5 and payload["source"] == "em_fetch.py", f"实际 {payload}"
            assert not [p for p in os.listdir(d) if p.endswith(".tmp")], \
                f"成功落盘后不得残留 .tmp：{os.listdir(d)}"

            # 失败路径：json.dump 抛异常 → 异常外溢且目标文件保留原内容不被截断
            open(out, "w", encoding="utf-8").write('{"sentinel": true}')
            _orig_dump = em.json.dump
            def _boom(obj, fp, **kw):
                raise IOError("磁盘已满")
            em.json.dump = _boom
            try:
                try:
                    em.main()
                    raise AssertionError("json.dump 抛异常应原样外溢")
                except IOError:
                    pass
                assert open(out, encoding="utf-8").read() == '{"sentinel": true}', \
                    "写盘中断不得截断/污染目标文件"
            finally:
                em.json.dump = _orig_dump
        finally:
            em.summarize = _orig_sv
            sys.argv = _orig_argv
            em._CAPTURE.clear()
            em._CAPTURE.update(_orig_cap)
    print("22. --out 原子落盘 通过")



def test_23_forensic_fields_third_param():
    """23. fetch_forensic 的 fina_indicator fields 必须走第三参（审计 #小4，无网络 mock ts_call）：
    fields 塞进 params 会被 ts_call 键归一化剔除（键尾空串）→ 实际全字段拉取
    （em_market.fetch_pe_pb_band 同款 bug 有注释记录）；income 行不带毛利率时必走该分支。"""
    import em_finance
    inc = [
        {"end_date": "20251231", "ann_date": "20260328", "report_type": "1",
         "total_revenue": 400e8, "n_income": 50e8, "n_income_attr_p": 48e8,
         "sell_exp": 10e8, "admin_exp": 8e8, "comp_type": "1"},   # 无 grossprofit_margin → 触发 fina_indicator 补毛利率分支
        {"end_date": "20241231", "ann_date": "20250328", "report_type": "1",
         "total_revenue": 350e8, "n_income": 45e8, "n_income_attr_p": 43e8,
         "sell_exp": 9e8, "admin_exp": 7e8, "comp_type": "1"},
    ]
    bs = [
        {"end_date": "20251231", "report_type": "1", "total_assets": 1000e8, "accounts_receiv": 40e8,
         "total_cur_assets": 300e8, "fix_assets": 200e8, "total_liab": 400e8},
        {"end_date": "20241231", "report_type": "1", "total_assets": 900e8, "accounts_receiv": 35e8,
         "total_cur_assets": 280e8, "fix_assets": 180e8, "total_liab": 380e8},
    ]
    cf = [
        {"end_date": "20251231", "n_cashflow_act": 60e8, "depr_fa_coga_dpba": 15e8},
        {"end_date": "20241231", "n_cashflow_act": 55e8, "depr_fa_coga_dpba": 14e8},
    ]
    ind = [{"end_date": "20251231", "grossprofit_margin": 40.0},
           {"end_date": "20241231", "grossprofit_margin": 38.0}]
    calls = []
    _orig_ts23 = em_core.ts_call
    def _ts23(api, params=None, fields=""):
        calls.append((api, dict(params or {}), fields))
        return {"income": inc, "balancesheet": bs, "cashflow": cf,
                "fina_indicator": ind}.get(api, [])
    try:
        em_core.ts_call = _ts23
        lines = em_finance.fetch_forensic("600989")
        fi = [(p, f) for (a, p, f) in calls if a == "fina_indicator"]
        assert fi, "income 无毛利率时 fetch_forensic 应调 fina_indicator 补齐"
        (params23, fields23), = fi
        assert "fields" not in params23, "fields 不得塞进 params（被键归一化剔除→全字段拉取）"
        assert fields23 == "ts_code,end_date,grossprofit_margin", \
            f"fields 应走第三参，实际 {fields23!r}"
        assert any("M-Score" in l for l in lines), f"应产出 M-Score 行，实际 {lines}"
    finally:
        em_core.ts_call = _orig_ts23
    print("23. fetch_forensic fields 第三参 通过")



def test_24_memo_falsy_contract():
    """24. em_core.memo 缓存契约（零测试补漏，无网络）：falsy 返回值（[]）是合法缓存值——
    第二次命中缓存且 loader 只调一次；loader 抛异常——不回填（缓存无键）且异常原样外溢。"""
    calls = []
    cache = {}
    assert em_core.memo(cache, "k", lambda: calls.append(1) or []) == []
    assert em_core.memo(cache, "k", lambda: calls.append(2) or ["新值"]) == [], \
        "falsy 结果已入缓存：第二次调用必须命中缓存返回 []"
    assert calls == [1], f"loader 应只调一次，实际 {calls}"
    boom = RuntimeError("net down")
    def _loader():
        raise boom
    try:
        em_core.memo(cache, "bad", _loader)
        raise AssertionError("loader 异常应原样外溢")
    except RuntimeError as e:
        assert e is boom, "异常对象应原样外溢（不被包装/吞掉）"
    assert "bad" not in cache, "失败不入缓存（缓存不得有键）"
    print("24. memo falsy 缓存契约 通过")



def test_25_daily_basic_latest():
    """25. em_core._daily_basic_latest 取最新行（零测试补漏，无网络 mock ts_call）：
    乱序返回时取 trade_date 最大行；空/None trade_date 行先过滤再取 max（None 陷阱）。"""
    rows = [
        {"trade_date": "20260930", "close": 10.0, "pe_ttm": 15.0},
        {"trade_date": "", "close": 99.0},            # 空日期行：须过滤，不得参与 max
        {"trade_date": None, "close": 98.0},          # None 日期行：同上
        {"trade_date": "20261008", "close": 12.0, "pe_ttm": 14.0},
        {"trade_date": "20261001", "close": 11.0},
    ]
    _orig_ts25 = em_core.ts_call
    try:
        em_core.ts_call = lambda api, params=None, fields="": rows
        row = em_core._daily_basic_latest("600989")
        assert row["trade_date"] == "20261008" and row["close"] == 12.0, \
            f"应取日期最大行，实际 {row}"
    finally:
        em_core.ts_call = _orig_ts25
    print("25. _daily_basic_latest 最新行 通过")


def test_26_consensus_history():
    """26. E5 券商态度变化（v5.9.0 口径重构，gap_history 数据源，无网络 mock ts_call）：
    同一券商最新一份（限近 180 天）vs 上一份（不限时间——窗口外上一份纳入对比）；
    最新一份在 180 天外 → 不出行；np 仅同预测年度对比（跨年不出 np，退 tp 日期）；
    tp 取两份区间中值（缺一不比）；评级仅记变化；日期 ISO 化；排序头部/外资优先、
    组内按 np 变化幅度降序。日期全部相对化（timedelta），防窗口腐烂。"""
    import em_owner
    from datetime import date, timedelta
    _d = lambda n: (date.today() - timedelta(days=n)).strftime("%Y%m%d")
    _iso = lambda n: (date.today() - timedelta(days=n)).isoformat()
    rows = [
        # 中金：两份同年 np 930→952、目标价 118→135、评级不变（不记）；
        # 另有「中金公司」名义的最新一份（口径漂移应合并为同一券商，v5.9.0 宁德探针实证）——
        # 合并后最新=_d(5)（中金公司名义）、上一份=_d(30)（中金名义）：np 952→960、tp 135→133
        {"org_name": "中金", "report_date": _d(100), "quarter": "2026Q4",
         "np": 9300000, "min_price": 115, "max_price": 121, "rating": "买入"},
        {"org_name": "中金", "report_date": _d(30), "quarter": "2026Q4",
         "np": 9520000, "min_price": 130, "max_price": 140, "rating": "买入"},
        {"org_name": "中金公司", "report_date": _d(5), "quarter": "2026Q4",
         "np": 9600000, "min_price": 128, "max_price": 138, "rating": "买入"},
        # 大摩：两份 np 下调、评级变化
        {"org_name": "摩根士丹利", "report_date": _d(90), "quarter": "2026Q4",
         "np": 9050000, "rating": "增持"},
        {"org_name": "摩根士丹利", "report_date": _d(40), "quarter": "2026Q4",
         "np": 8780000, "rating": "中性"},
        # 华泰：跨年预测（上一份 2025Q4 / 最新 2026Q4）→ 无同年可比不出 np，仅 tp 105→115
        {"org_name": "华泰", "report_date": _d(120), "quarter": "2025Q4",
         "np": 8000000, "min_price": 100, "max_price": 110},
        {"org_name": "华泰", "report_date": _d(14), "quarter": "2026Q4",
         "np": 9080000, "min_price": 112, "max_price": 118},
        # 中信建投：上一份在 180 天外（400 天前）——旧口径整行滤掉，v5.9.0 起纳入
        {"org_name": "中信建投", "report_date": _d(400), "quarter": "2026Q4", "np": 5000000},
        {"org_name": "中信建投", "report_date": _d(10), "quarter": "2026Q4", "np": 5500000},
        # 浙商（非头部/外资）：np +100% 大变化——排序仍排全部头部/外资之后
        {"org_name": "浙商", "report_date": _d(80), "quarter": "2026Q4", "np": 1000000},
        {"org_name": "浙商", "report_date": _d(20), "quarter": "2026Q4", "np": 2000000},
        # 野村：单份 → 无上一份，不出行
        {"org_name": "野村", "report_date": _d(25), "quarter": "2026Q4", "np": 9520000},
        # 老券商：最新一份也在 180 天外（200 天前）→ 态度非当前，不出行
        {"org_name": "老券商", "report_date": _d(400), "quarter": "2026Q4", "np": 800000},
        {"org_name": "老券商", "report_date": _d(200), "quarter": "2026Q4", "np": 900000},
    ]
    _orig = em_core.ts_call
    try:
        em_core.ts_call = lambda name, params, **k: rows
        c = em_owner.fetch_consensus("600938")
    finally:
        em_core.ts_call = _orig
    hist = {h["org"]: h for h in c["history"]}
    assert "野村" not in hist, f"单份机构不应出行：{hist}"
    assert "老券商" not in hist, f"最新一份在 180 天外不应出行：{hist}"
    zj = hist["中金公司"]     # 漂移合并后展示名=最新一份的原始机构名
    assert "中金" not in {h["org"] for h in c["history"] if h["org"] != "中金公司"}, \
        f"漂移不应拆出独立「中金」行：{[h['org'] for h in c['history']]}"
    assert (zj["yr"], zj["np_from"], zj["np_to"]) == ("2026", 952.0, 960.0), \
        f"合并后最新=_d(5)、上一份=_d(30)：{zj}"
    assert (zj["tp_from"], zj["tp_to"]) == (135.0, 133.0), f"tp 应取两份区间中值：{zj}"
    assert (zj["d_from"], zj["d_to"]) == (_iso(30), _iso(5)), f"日期应 ISO 化：{zj}"
    assert "rating_from" not in zj, f"评级不变不应记录：{zj}"
    ms = hist["摩根士丹利"]
    assert (ms["rating_from"], ms["rating_to"]) == ("增持", "中性"), f"实际 {ms}"
    ht = hist["华泰"]
    assert "np_from" not in ht, f"跨年预测不应比 np：{ht}"
    assert (ht["tp_from"], ht["tp_to"]) == (105.0, 115.0), f"实际 {ht}"
    assert (ht["d_from"], ht["d_to"]) == (_iso(120), _iso(14)), f"应退 tp 日期：{ht}"
    zx = hist["中信建投"]
    assert (zx["np_from"], zx["np_to"]) == (500.0, 550.0), f"180 天外上一份应纳入对比：{zx}"
    assert zx["d_from"] == _iso(400) and zx["d_from"][:4] != zx["d_to"][:4], \
        f"上一份跨年应带全称日期：{zx}"
    order = [h["org"] for h in c["history"]]
    assert order == ["中信建投", "中金公司", "摩根士丹利", "华泰", "浙商"], \
        f"应头部/外资优先、组内按 np 幅度降序（浙商 +100% 仍排最后）：{order}"
    print("26. E5 券商态度变化 通过")


def test_27_tp_reports_hint():
    """27. E5 目标价研报清单提示行（v5.8.1，宁德 300750 复盘漏抄断链实证；v5.8.3 渲染就绪行
    下沉 em_owner.fetch_consensus——stub 渲染键直测 _sec_e5 出行门禁，渲染文案真调数据层钉住）：
    tp_reports_line 非空时摘要须出「目标价研报清单」照抄键提示（按 机构+目标价 去重、家/份计数、
    日期 MM-DD）；清单行 None 或 tp_reports 键缺失时不出行（tp_reports 落盘不受影响）；
    落盘 _CAPTURE 原样带 tp_reports。"""
    hist = [{"org": "中金公司", "yr": "2026", "d_from": "2026-04-25", "d_to": "2026-07-26",
             "np_from": 959.8, "np_to": 959.8}]
    hist_line = ("券商态度变化（gap_history 照抄行，1 家，同一券商最新一份vs上一份·"
                 "最新限180天内/上一份不限/头部外资优先）: "
                 "中金公司 2026E净利959.8(04-25)→959.8(07-26)")
    tp_reps = [{"org": "群益证券(香港)", "date": "2026-09-29", "tp": 390.0},
               {"org": "群益证券(香港)", "date": "2026-09-29", "tp": 390.0},
               {"org": "中金公司", "date": "2026-09-13", "tp": 500.0}]
    tp_line = ("目标价研报清单（gap_history.tp_reports 照抄键，2 家/3 份，降级面板数据源）: "
               "群益证券(香港)390(09-29)·中金公司500(09-13)")
    c = {"_src": "tushare", "orgs": 44, "n_reports": 181,
         "years": {"2026": {"np": [952.0], "eps": []}},
         "history": hist, "history_line": hist_line,
         "tp_reports": tp_reps, "tp_reports_line": tp_line,
         "detail_lines": [], "aim_line": None,
         "aim": [390.0, 500.0], "ratings": {"买入": 30}}
    _orig = em.fetch_consensus
    em._CAPTURE.pop("gap_history", None)
    try:
        em.fetch_consensus = lambda code: c
        out = "\n".join(em._sec_e5("300750", False))
    finally:
        em.fetch_consensus = _orig
    assert "券商态度变化" in out and "中金公司 2026E净利959.8(04-25)→959.8(07-26)" in out,         f"态度变化行应出行: {out}"
    assert "目标价研报清单" in out, f"应出提示行: {out}"
    assert "2 家/3 份" in out, f"家/份计数应按去重后/原始: {out}"
    assert "群益证券(香港)390(09-29)" in out and "中金公司500(09-13)" in out, f"去重列示: {out}"
    assert out.count("群益证券(香港)") == 1, f"同机构同价重复条目应去重: {out}"
    gh = em._CAPTURE.get("gap_history") or {}
    assert gh.get("tp_reports") == tp_reps, f"落盘应原样带 tp_reports: {gh}"
    assert gh.get("rows") == hist, f"落盘应原样带 rows: {gh}"
    assert "东财汇总" not in out and "[降级：" not in out, "tushare 成功路径不得出现东财降级提示"
    assert em._CAPTURE.get("e5_source") == "tushare", "成功来源标记须随 --out 捕获"
    # 清单行 None（条目全缺 tp 的清单形态）→ 不出行，但 tp_reports 仍落盘
    c2 = dict(c, tp_reports_line=None)
    try:
        em.fetch_consensus = lambda code: c2
        out2 = "\n".join(em._sec_e5("300750", False))
    finally:
        em.fetch_consensus = _orig
    assert "目标价研报清单" not in out2, f"全缺 tp 不应出行: {out2}"
    gh2 = em._CAPTURE.get("gap_history") or {}
    assert gh2.get("tp_reports") == tp_reps, "tp_reports 落盘不随行取消"
    # 键缺失 → 不出行
    c3 = dict(c)
    del c3["tp_reports_line"]
    try:
        em.fetch_consensus = lambda code: c3
        out3 = "\n".join(em._sec_e5("300750", False))
    finally:
        em.fetch_consensus = _orig
    assert "目标价研报清单" not in out3, f"键缺失不应出行: {out3}"

    # v5.8.3：渲染键真值由 fetch_consensus 产出——真调数据层钉文案（去重/计数/格式化在此层）
    # v5.9.0：日期相对化（防窗口腐烂）；history_line 钉新口径文案（最新vs上一份/头部外资优先）
    import em_owner
    from datetime import date, timedelta
    _d = lambda n: (date.today() - timedelta(days=n)).strftime("%Y%m%d")
    _mm = lambda n: f"{_d(n)[4:6]}-{_d(n)[6:8]}"
    _iso = lambda n: (date.today() - timedelta(days=n)).isoformat()
    _sd = lambda a, b: _mm(a) if _d(a)[:4] == _d(b)[:4] else _iso(a)  # 跨年带全称（同数据层）
    rows = [
        {"org_name": "野村", "report_date": _d(30), "quarter": "2026Q4",
         "np": 9520000, "eps": 2.1, "min_price": 30, "max_price": 32, "rating": "买入"},
        {"org_name": "野村", "report_date": _d(90), "quarter": "2026Q4", "np": 9000000},
        {"org_name": "摩根士丹利", "report_date": _d(60), "quarter": "2026Q4",
         "np": 8780000, "eps": 2.0},
        {"org_name": "老券商", "report_date": _d(400), "quarter": "2026Q4", "np": 1000000},
    ]
    _orig_ts = em_core.ts_call
    try:
        em_core.ts_call = lambda name, params, **k: rows
        c4 = em_owner.fetch_consensus("600938")
    finally:
        em_core.ts_call = _orig_ts
    assert c4["history_line"] == \
        (f"券商态度变化（gap_history 照抄行，1 家，同一券商最新一份vs上一份·"
         f"最新限180天内/上一份不限/头部外资优先）: 野村 2026E净利900({_sd(90, 30)})→952({_mm(30)})"), \
        f"实际 {c4['history_line']}"
    assert c4["detail_lines"] == [
        f"2026E 净利明细（gap_plot 照抄行，2 家，按值降序）: 野村952({_mm(30)})·摩根士丹利878({_mm(60)})"], \
        f"实际 {c4['detail_lines']}"
    assert c4["aim_line"] == \
        f"目标价明细（gap_plot 照抄行，1 家，(研报下限+上限)/2）: 野村31({_mm(30)})", \
        f"实际 {c4['aim_line']}"
    assert c4["tp_reports_line"] == \
        f"目标价研报清单（gap_history.tp_reports 照抄键，1 家/1 份，降级面板数据源）: 野村31({_mm(30)})", \
        f"实际 {c4['tp_reports_line']}"
    print("27. E5 目标价研报清单提示行 通过")



def test_32_e5_em_fallback_visible():
    """32. E5 东财降级必须可见：report_rc 错误进日志，摘要说明无逐份研报与报告写法。"""
    import contextlib
    import io
    import em_owner

    em_row = {
        "RATING_ORG_NUM": 20, "RATING_BUY_NUM": 17, "RATING_ADD_NUM": 3,
        "RATING_NEUTRAL_NUM": 0, "DEC_AIMPRICEMIN": 51.0, "DEC_AIMPRICEMAX": 59.78,
        "YEAR1": 2025, "YEAR_MARK1": "A", "EPS1": 3.0,
        "YEAR2": 2026, "YEAR_MARK2": "E", "EPS2": 3.1,
        "YEAR3": 2027, "YEAR_MARK3": "E", "EPS3": 3.2,
        "INDUSTRY_BOARD": "煤炭", "CONCEPTINDEX_BOARD": "",
    }
    orig_ts, orig_em = em_core.ts_call, em_owner._em_consensus
    orig_cap = dict(em._CAPTURE)
    err = io.StringIO()

    def _quota(*args, **kwargs):
        raise RuntimeError("tushare report_rc: 小时额度耗尽")

    try:
        em_core.ts_call = _quota
        em_owner._em_consensus = lambda code: dict(em_row)
        em._CAPTURE.clear()
        with contextlib.redirect_stderr(err):
            out = "\n".join(em._sec_e5("601088", False))
        captured = dict(em._CAPTURE)
    finally:
        em_core.ts_call = orig_ts
        em_owner._em_consensus = orig_em
        em._CAPTURE.clear()
        em._CAPTURE.update(orig_cap)

    log = err.getvalue()
    assert all(s in log for s in ("⚠️", "report_rc", "小时额度耗尽")), \
        f"report_rc 原始错误应进 stderr: {log}"
    assert all(s in out for s in ("东财汇总", "无逐份研报", "gap_history", "gap_html", "未生成")), \
        f"东财降级摘要应说明图缺省原因与报告写法: {out}"
    assert "gap_history" not in captured, "东财汇总不得虚构券商态度变化数据"
    assert captured.get("e5_source") == "em", "东财来源标记须随 --out 捕获供报告缺省校验"
    print("32. E5 东财降级可见性 通过")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"OK {t.__name__}")
    print(f"全部 {len(tests)} 项测试通过")

def test_18c_dupont_factors():
    """18c. 杜邦四因子（v5.8.0，mock _em_f10）：最新期 vs 去年同期（同 mmdd 年−1）；
    四值缺一 → {}；去年同期缺 → 仅本期无 prev 键。"""
    import em_finance
    f10 = [
        {"REPORT_DATE": "2026-09-30", "ROEJQ": 16.11, "XSJLL": 30.36, "TOAZZL": 0.3127,
         "QYCS": 1.7029},
        {"REPORT_DATE": "2026-06-30", "ROEJQ": 9.06, "XSJLL": 27.14, "TOAZZL": 0.1988,
         "QYCS": 1.6632},
        {"REPORT_DATE": "2025-09-30", "ROEJQ": 8.32, "XSJLL": 19.22, "TOAZZL": 0.2577,
         "QYCS": 1.6501},
    ]
    _o = em_finance._em_f10
    try:
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: f10
        d = em_finance.fetch_dupont_factors("600176.SH")
        assert d["period"] == "2026三季" and d["roe"] == 16.1 and d["nm"] == 30.4
        assert d["turn"] == 0.313 and d["em"] == 1.7, f"实际 {d}"
        assert d["prev"]["roe"] == 8.3 and d["prev"]["turn"] == 0.258
        # 去年同期缺 → 仅本期、无 prev 键
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: f10[:1]
        d2 = em_finance.fetch_dupont_factors("600176.SH")
        assert "prev" not in d2 and d2["roe"] == 16.1
        # 四值缺一 → {}
        em_finance._em_f10 = lambda secucode, size=12, annual_only=False: [
            {"REPORT_DATE": "2026-09-30", "ROEJQ": 16.11, "XSJLL": None}]
        assert em_finance.fetch_dupont_factors("600176.SH") == {}
    finally:
        em_finance._em_f10 = _o
    print("18c. 杜邦四因子（本期+去年同期/缺期降级）通过")



def test_28_rate_limit_passthrough():
    """v5.8.2：段级 except / 数据层裸 except / summarize 边界不再吞 RateLimitError——
    东财取数抛限流时穿透至 main 硬停（退 2）；generic Exception 仍走降级文本（行为不破）。"""
    import em_finance
    import em_market

    def _boom(*a, **k):
        raise em.RateLimitError("HTTP 429（限流/服务端错误，硬停不重试）: mock")

    # ① 段级：E2 取数抛限流 → _sec_e2 不吞成 [失败: …]
    _orig_kl = em.fetch_kline_monthly
    em.fetch_kline_monthly = _boom
    try:
        try:
            em._sec_e2("1.600989", 5, False)
            raise AssertionError("段级 except 不应吞 RateLimitError")
        except em.RateLimitError:
            pass
        # ② summarize 边界：线程池内穿透，边界兜底不吞；其余段 stub 掉避免真实网络
        _stubs = {n: getattr(em, n) for n in ("_sec_e1", "_sec_e3", "_sec_quality",
                                              "_sec_e4", "_sec_forecast", "_sec_gov",
                                              "_sec_e5", "_sec_e6")}
        for n in _stubs:
            setattr(em, n, lambda *a, **k: [])
        em._sec_e3 = lambda *a, **k: ([], None)   # 真返回结构：(e3_out, annual) 元组
        try:
            try:
                em.summarize("600989", 5)
                raise AssertionError("summarize 边界不应吞 RateLimitError")
            except em.RateLimitError:
                pass
        finally:
            for n, fn in _stubs.items():
                setattr(em, n, fn)
    finally:
        em.fetch_kline_monthly = _orig_kl

    # ③ generic Exception 仍降级成 [失败: …]（既有行为不破：只有限流穿透）
    def _net_err(*a, **k):
        raise ConnectionError("mock 网络失败")
    em.fetch_kline_monthly = _net_err
    try:
        out = em._sec_e2("1.600989", 5, False)
        assert any("[失败:" in l for l in out), "generic 错误应降级成 [失败: …] 文本"
    finally:
        em.fetch_kline_monthly = _orig_kl

    # ④ 数据层裸 except：东财 F10 限流穿透 _ts_annual_em_map
    _orig_get = em_core.get
    em_finance._EM_F10_CACHE.pop("600989.SH", None)   # memo 命中即不调 loader，先清同 secucode 缓存
    em_core.get = _boom
    try:
        try:
            em_finance._ts_annual_em_map("600989.SH", 5)
            raise AssertionError("数据层裸 except 不应吞 RateLimitError")
        except em.RateLimitError:
            pass
    finally:
        em_core.get = _orig_get

    # ⑤ 港股 fetch_quote：东财行情侧限流穿透，hk_daily 哨兵侧（既定降级）不动
    _orig_ts = em_core.ts_call
    _orig_hk = dict(em_market._HK_DAILY_CACHE)
    em_core.ts_call = lambda *a, **k: []    # hk_daily 空 → 哨兵 RuntimeError，缓存读取侧照旧吞
    em_core.get = _boom                      # 东财行情限流
    try:
        try:
            em_market.fetch_quote("116.00700", True)
            raise AssertionError("港股 fetch_quote 东财分支不应吞 RateLimitError")
        except em.RateLimitError:
            pass
    finally:
        em_core.ts_call = _orig_ts
        em_core.get = _orig_get
        em_market._HK_DAILY_CACHE.clear()
        em_market._HK_DAILY_CACHE.update(_orig_hk)
    # ⑥ E5：report_rc 失败后东财一致预期 429，必须穿透 _sec_e5（真实调用链表征测试）
    import em_owner
    _orig_ts_e5, _orig_em_e5 = em_core.ts_call, em_owner._em_consensus

    def _ts_e5_error(*args, **kwargs):
        raise RuntimeError("tushare report_rc: mock 小时额度耗尽")

    em_core.ts_call = _ts_e5_error
    em_owner._em_consensus = _boom
    try:
        try:
            em._sec_e5("601088", False)
            raise AssertionError("E5 东财一致预期 429 不应被吞成无覆盖")
        except em.RateLimitError:
            pass
    finally:
        em_core.ts_call = _orig_ts_e5
        em_owner._em_consensus = _orig_em_e5
    print("28. 限流穿透（段级/summarize 边界/数据层/港股东财分支/E5）通过")



def test_29_summarize_clears_capture():
    """29. summarize 入口 _CAPTURE.clear()（v5.8.2 审计修复，无网络段级 stub）：第一次调用
    写入的 consensus_eps 残留键不得污染第二次输出——原 _sec_e5 东财降级路径先捕获存根、
    再按 "consensus_eps" in _CAPTURE 决定是否标注「已换算落盘」行；stub 镜像该条件行为。"""
    _orig = {n: getattr(em, n) for n in ("_sec_e1", "_sec_e3", "_sec_quality", "_sec_e2",
                                         "_sec_e4", "_sec_forecast", "_sec_gov", "_sec_e6")}
    _orig_e5, _orig_cap = em._sec_e5, dict(em._CAPTURE)
    _note = "（当年 EPS 均值已按 ×总股本 换算落盘 consensus_np——第 3 章完成度分母照抄源）"

    def _fake_e5(*a, **k):
        if _fake_e5.calls == 0:   # 仅第一次调用写入捕获键（模拟东财降级路径落存根）
            em._CAPTURE["consensus_eps"] = {"year": 2026, "eps": 1.5, "orgs": 8}
        _fake_e5.calls += 1
        return ["## E5 一致预期\n" + (_note if "consensus_eps" in em._CAPTURE else "")]

    _fake_e5.calls = 0
    try:
        for n in _orig:
            setattr(em, n, lambda *a, **k: [])
        em._sec_e3 = lambda *a, **k: ([], None)   # 真返回结构：(e3_out, annual) 元组
        em._sec_e5 = _fake_e5
        em._CAPTURE.clear()

        out1 = em.summarize("600989", 5)
        assert _note in out1, "第一次调用 stub 写入捕获键后应出现换算标注"
        assert "consensus_eps" in em._CAPTURE, "第一次调用后残留键应留在 _CAPTURE"

        out2 = em.summarize("600989", 5)   # 第二次 stub 不再写键：残留即误标注
        assert _note not in out2, f"第二次输出被第一次残留键污染:\n{out2}"
        assert "consensus_eps" not in em._CAPTURE, "入口清空后不得残留上一次捕获键"
    finally:
        for n, fn in _orig.items():
            setattr(em, n, fn)
        em._sec_e5 = _orig_e5
        em._CAPTURE.clear()
        em._CAPTURE.update(_orig_cap)
    print("29. summarize 清 _CAPTURE（二次调用无残留污染）通过")


def test_30_quality_v2_summary_out_and_legacy_unchanged():
    import contextlib
    import io
    import json

    calls = []
    payload = {"status": "ok", "as_of": "2026-10-24", "profile": {},
               "1D": {"f_items": {"profit_positive": True}}, "1F": {},
               "coverage": {}, "sources": [], "meta": {}}
    original = em.summarize, em._C._tushare_token, sys.argv, dict(em._CAPTURE)
    marker = object()
    original_fetch = getattr(em, "fetch_quality_inputs", marker)
    def fake_summary(*args):
        em._CAPTURE.clear()
        em._CAPTURE["price"] = 10.5
        return "旧摘要"
    def fake_quality(code, secucode, as_of, profile):
        calls.append((code, secucode, as_of, profile))
        return dict(payload, as_of=as_of, profile=profile)
    try:
        em.summarize = fake_summary
        em._C._tushare_token = lambda: "configured"
        em.fetch_quality_inputs = fake_quality
        with tempfile.TemporaryDirectory() as d:
            out_path = os.path.join(d, "quote.json")
            sys.argv = ["em_fetch.py", "600000", "--quality-v2", "--stock-type=成长型",
                        "--growth-tier=mid", "--industry-profile=generic", f"--out={out_path}"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                em.main()
            output = buf.getvalue()
            assert "旧摘要" in output and "quality_inputs" in output
            assert '"profit_positive": true' in output
            saved = json.load(open(out_path, encoding="utf-8"))
            assert saved["quality_inputs"]["1D"]["f_items"]["profit_positive"] is True
            assert calls[0][0:2] == ("600000", "600000.SH")
            assert calls[0][3] == {"stock_type": "成长型", "growth_tier": "mid",
                                   "industry_profile": "generic"}
            sys.argv = ["em_fetch.py", "600000"]
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                em.main()
            assert buf.getvalue() == "旧摘要\n"
            assert len(calls) == 1
    finally:
        em.summarize, em._C._tushare_token, sys.argv, _ = original
        em._CAPTURE.clear()
        em._CAPTURE.update(original[3])
        if original_fetch is marker:
            del em.fetch_quality_inputs
        else:
            em.fetch_quality_inputs = original_fetch
    print("30. 质量v2摘要落盘与旧命令不变 通过")


def test_32_timing_indicator_known_series():
    import em_market as market

    rows = [{"trade_date": f"2026{i:04d}", "open": float(i),
             "high": float(i + 1), "low": float(i - 1),
             "close": float(i), "vol": float(100 + i)} for i in range(1, 141)]
    facts = market.compute_technical_facts(rows)
    assert facts["rsi14"] == 100.0
    assert facts["atr14_pct"] == 1.43
    assert facts["macd"] == {"dif": 6.999718, "dea": 6.999585, "hist": 0.000266}
    assert market.compute_technical_facts(rows[:35])["macd"] == {
        "dif": 6.105711, "dea": 5.811164, "hist": 0.589094}
    assert facts["volume_ratio_20"] == 1.05
    assert facts["ma60_slope_20d_pct"] == 22.1
    assert facts["ma120_slope_20d_pct"] == 33.06
    assert facts["position_52w_pct"] == 100.0
    assert facts["as_of"] == "20260140"

    up_then_down = [1, 2, 3, 4, 5, 6, 7, 8, 7, 6, 5, 4, 3, 2, 1]
    rsi_rows = [dict(row, close=float(close)) for row, close in zip(rows, up_then_down)]
    assert market.compute_technical_facts(rsi_rows)["rsi14"] == 50.0
    short = market.compute_technical_facts(rows[:13])
    assert short["rsi14"] is None and short["atr14_pct"] is None
    missing_windows = market.compute_technical_facts(rows[:60])
    assert missing_windows["ma60_slope_20d_pct"] is None
    assert missing_windows["ma120_slope_20d_pct"] is None
    zero_volume = market.compute_technical_facts([dict(row, vol=0) for row in rows])
    assert zero_volume["volume_ratio_20"] is None
    flat = market.compute_technical_facts([dict(row, close=10) for row in rows])
    assert flat["position_52w_pct"] is None and flat["rsi14"] == 50.0


def test_33_consensus_levels_and_fetch_reuse():
    import em_market as market

    monthly = [{"date": "2020-12-31", "close": 20, "high": 22, "low": 18},
               {"date": "2023-06-30", "close": 10, "high": 12, "low": 9},
               {"date": "2024-01-31", "close": 15, "high": 16, "low": 14}]
    levels = market.consensus_price_levels(monthly)
    assert levels["close_high"] == 15 and levels["close_low"] == 10
    assert levels["intraday_high"] == 16 and levels["intraday_low"] == 9
    assert levels["months"] == 2 and levels["window_years"] == 3
    assert levels["close_high"] != levels["intraday_high"]
    assert market.consensus_price_levels([]) is None
    partial = market.consensus_price_levels([monthly[1], dict(monthly[2], high=None)])
    assert partial["intraday_high"] is None and partial["ohlc_months"] == 1

    rows = [{"trade_date": f"2026{i:04d}", "open": float(i), "high": float(i + 1),
             "low": float(i - 1), "close": float(i), "vol": 100}
            for i in range(1, 141)]
    original = market._a_daily_series
    try:
        market._a_daily_series = lambda _code: rows
        result = market.fetch_timing_material("600000", monthly_rows=monthly)
    finally:
        market._a_daily_series = original
    for key in ("price", "ma60", "ma120", "high_52w", "low_52w", "n",
                "technical", "consensus_levels"):
        assert key in result
    assert result["price"] == 140 and result["technical"]["rsi14"] == 100.0
    assert result["consensus_levels"]["close_high"] == 15


def test_34_timing_evidence_written_with_null_unavailable(monkeypatch, tmp_path):
    import json

    monkeypatch.setattr(em, "_CAPTURE", {})
    def fake_summary(*_args):
        em._CAPTURE.update({"code": "600000", "timing": {
            "price": 10, "technical": {"rsi14": 55.0},
            "consensus_levels": {"close_high": 15, "close_low": 8}}})
        return "摘要"

    monkeypatch.setattr(em, "summarize", fake_summary)
    monkeypatch.setattr(em._C, "_tushare_token", lambda: "configured")
    monkeypatch.setattr(sys, "argv", ["em_fetch.py", "600000", f"--out={tmp_path}/quote.json"])
    em.main()
    evidence_path = tmp_path / f"_timing_600000_{date.today().isoformat()}.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["technical"]["rsi14"] == 55.0
    assert evidence["consensus_levels"]["close_high"] == 15
    assert evidence["chips"] == {"average_cost": None, "profit_ratio": None}
    assert set(evidence["capital"]) == {"main_net_inflow", "southbound", "margin"}
    assert all(value is None for value in evidence["capital"].values())


def test_35_summarize_reuses_same_monthly_rows(monkeypatch):
    monkeypatch.setattr(em, "_CAPTURE", {})
    monthly = [{"date": "2024-01-31", "close": 15, "high": 16, "low": 14}]
    fetch_calls = []
    consumers = []
    monkeypatch.setattr(em, "fetch_kline_monthly",
                        lambda *_args: fetch_calls.append(1) or monthly)
    monkeypatch.setattr(em, "_sec_e1",
                        lambda _s, _h, _p, monthly_rows=None: consumers.append(monthly_rows) or [])
    monkeypatch.setattr(em, "_sec_e2",
                        lambda _s, _y, _h, monthly_rows=None: consumers.append(monthly_rows) or [])
    monkeypatch.setattr(em, "_sec_e3", lambda *_args: ([], []))
    for name in ("_sec_quality", "_sec_e4", "_sec_forecast", "_sec_gov", "_sec_e5", "_sec_e6"):
        monkeypatch.setattr(em, name, lambda *_args: [])
    em.summarize("600000", 5)
    assert fetch_calls == [1]
    assert consumers == [monthly, monthly]


def test_31_quality_v2_profile_missing():
    import contextlib
    import io
    import quality_inputs

    original = em.summarize, em._C._tushare_token, sys.argv, dict(em._CAPTURE)
    marker = object()
    original_fetch = getattr(em, "fetch_quality_inputs", marker)
    try:
        em.summarize = lambda *args: "旧摘要"
        em._C._tushare_token = lambda: "configured"
        em.fetch_quality_inputs = quality_inputs.fetch_quality_inputs
        sys.argv = ["em_fetch.py", "600000", "--quality-v2"]
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            em.main()
        assert "profile_missing" in buf.getvalue()
    finally:
        em.summarize, em._C._tushare_token, sys.argv, _ = original
        em._CAPTURE.clear()
        em._CAPTURE.update(original[3])
        if original_fetch is marker:
            del em.fetch_quality_inputs
        else:
            em.fetch_quality_inputs = original_fetch
    print("31. 质量v2缺profile显式降级 通过")
