#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
em_market.py — 行情 / 月K 取数族（Bo-EquityResearcher skill 取数分块之一，v4.10.3 自 em_data 拆分）

职责：E1 行情（tushare daily_basic 优先、东财 push2 兜底）、E2 月线（tushare 前复权 / 港股日线
聚合，东财 kline 兜底）、PE/PB 历史分位带、时机素材（MA60/MA120/52 周高低、技术指标、
三年价格区间）与 A 股资金事实（moneyflow/margin_detail）。进程内日线序列缓存
_HK_DAILY_CACHE/_A_DAILY_CACHE 随本块持有（E1 与 E2 共用同一次拉取）。

与其他块的边界（重要）：
- 只依赖 em_core.py，绝不 import 其他取数块（em_finance/em_owner/em_misc 同理）。
- 传输函数一律以 `_C.ts_call` / `_C.get` 模块属性形式调用（迟绑定——测试按 em_core 命名空间
  rebind 传输函数与缓存配置须即时传导）；静态 from-import 只用于无 rebind 依赖的纯工具
  （代码映射 / 格式化 / 取数窗口）与跨块共享 helper。
"""
import sys
from bisect import bisect_right
from datetime import date

import em_core as _C
from em_core import (to_ts_code, memo, _r2, _fmt_date, _daily_basic_latest, _win_days, _win_years,
                     RateLimitError)


_HK_DAILY_CACHE = {}
_A_DAILY_CACHE = {}  # A股日线序列缓存：fetch_quote(单日涨跌) 与 fetch_timing_material(430天MA) 共用一次拉取


def _hk_daily_series(ts_code: str) -> list:
    """港股日线序列（按 trade_date 升序）。hk_daily 限流实测 1次/小时（会员级，2026-09-06 复测），单次拉全量缓存复用：
    E1 取最新价、E2 聚合月线共用同一次调用，避免同脚本内二次调用被限流。
    tushare 返回倒序（新→旧），缓存前统一升序——timing 的 MA/52 周窗口依赖尾部切片。
    失败写空哨兵：1次/小时限流下同进程重试必撞墙，消费方命中哨兵即走各自降级。"""
    def _load():
        beg, end = _win_years(6)
        try:
            rows = _C.ts_call("hk_daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        except Exception:
            rows = []
        return sorted((r for r in rows if r.get("trade_date")), key=lambda x: x["trade_date"])
    rows = memo(_HK_DAILY_CACHE, ts_code, _load)
    if not rows:
        raise RuntimeError("hk_daily 空返回或已失败（哨兵）")
    return rows


def _a_daily_series(ts_code: str) -> list:
    """A股日线序列（近 430 天）。fetch_quote 单日 pct_chg 与 fetch_timing_material 的
    MA60/MA120/52周高低都出自本序列：E1 内 quote 先于 timing 执行，由 quote 首拉、timing 复用，
    原单日+430天两次请求合一。默认字段拉取（daily 全字段含 pct_chg，不传 fields）。"""
    def _load():
        beg, end = _win_days(430)
        rows = _C.ts_call("daily", {"ts_code": ts_code, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("daily 空返回")
        return rows
    return memo(_A_DAILY_CACHE, ts_code, _load)


def _em_quote(secid: str, is_hk: bool = False) -> dict:
    fields = "f43,f57,f58,f116,f162,f167,f168,f170"
    url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields={fields}"
    d = _C.get(url).get("data") or {}
    # 实测缩放差异：A股 价格÷100 比率÷100；港股 价格÷1000 比率÷100（f162=0 表示PE缺失非真0）
    price_div = 1000 if is_hk else 100
    ratio_div = 100
    div_p = lambda v: None if v in (None, "-") else v / price_div
    div_r = lambda v: None if v in (None, "-") else v / ratio_div
    pe = div_r(d.get("f162"))
    name = d.get("f58") or ""
    # 陈旧档拦截：已切换/退市标的东财返回零值（价格 0 + 市值 0），直接报错给可操作建议，
    # 避免零值静默流入报告（北交所旧代码 832982 实测返回「锦波生物(已切换)」全零，2026-08-30）
    if "已切换" in name or (not div_p(d.get("f43")) and not d.get("f116")):
        raise ValueError(
            f"东财行情显示 {name or secid} 已切换代码或已退市（无有效报价）："
            f"北交所旧代码（43/83/87/88 段）2025-10 起已切换 920 段新代码，请改用新代码重试；"
            f"其他情形请人工核查证券状态")
    return {
        "名称": d.get("f58"), "代码": d.get("f57"),
        "最新价": div_p(d.get("f43")), "涨跌幅%": div_r(d.get("f170")),
        "总市值亿": f"{(d.get('f116') or 0) / 1e8:,.1f}" if d.get("f116") else None,
        "PE_TTM": None if pe == 0 else pe,   # 港股 f162=0 = 缺失
        "PB": div_r(d.get("f167")),
        "换手率%": div_r(d.get("f168")),
    }


def fetch_pe_pb_band(code: str) -> dict:
    """A股 PE(TTM)/PB 历史分位（tushare daily_basic）。失败返回 None。"""
    try:
        beg, end = _win_years(5)
        # fields 必须走第三参（塞 params 会被键归一化剔除→缓存键与 E2 月末PE回填不一致、
        # 且请求全字段拉 5 年，v4.8.3 修复实证）
        rows = _C.ts_call("daily_basic", {"ts_code": to_ts_code(code),
                                       "start_date": beg, "end_date": end},
                       fields="ts_code,trade_date,pe_ttm,pb")
        if not rows:
            raise RuntimeError("daily_basic 空返回")
        # 行按日期倒序只排一次：pe/pb 派生与 latest 扫描共用 rows_desc（原三处遍历各自 sorted）；
        # pe/pb 的数值升序为分位/bisect 所必需，与日期序无法合并
        rows_desc = sorted(rows, key=lambda x: x.get("trade_date") or "", reverse=True)
        pes = sorted(float(r["pe_ttm"]) for r in rows_desc
                     if r.get("pe_ttm") is not None and float(r["pe_ttm"]) > 0)
        pbs = sorted(float(r["pb"]) for r in rows_desc
                     if r.get("pb") is not None and float(r["pb"]) > 0)
        if len(pes) < 20:
            raise RuntimeError(f"daily_basic 有效样本不足({len(pes)})")
        latest_pe, latest_pb = None, None
        for r in rows_desc:  # 已按日期倒序，最先遇见的有效值即最新
            if latest_pe is None and r.get("pe_ttm") and float(r["pe_ttm"]) > 0:
                latest_pe = float(r["pe_ttm"])
            if latest_pb is None and r.get("pb") and float(r["pb"]) > 0:
                latest_pb = float(r["pb"])
            if latest_pe and latest_pb:
                break
        def pctile(vals, cur):
            if cur is None:
                return None
            return round(bisect_right(vals, cur) / len(vals) * 100)
        # 分位点（v4.8：供 pe_history 图 P25-P75 分位区；索引取 (n-1)*q 整部位）
        n = len(pes)
        pe_p25, pe_p75 = pes[int((n - 1) * 0.25)], pes[int((n - 1) * 0.75)]
        return {"n": n, "years": 5,
                "pe_min": pes[0], "pe_max": pes[-1], "pe_cur": latest_pe, "pe_pct": pctile(pes, latest_pe),
                "pe_p25": pe_p25, "pe_p75": pe_p75,
                "pb_min": pbs[0], "pb_max": pbs[-1], "pb_cur": latest_pb, "pb_pct": pctile(pbs, latest_pb)}
    except RateLimitError:
        raise  # v5.8.2 硬停纪律：限流不吞成「无分位带」降级，穿透至 main 退 2
    except Exception:
        return None


def fetch_quote(secid: str, is_hk: bool = False) -> dict:
    """E1 行情。tushare 优先（PE 为标准 TTM 口径，东财 f162 动态口径失真问题规避），东财兜底。"""
    code = secid.split(".")[-1]
    if is_hk:
        # tushare 港股只有价格（hk_daily 无估值字段）：价格取缓存序列最新值，市值/PB/换手取东财
        price, chg, td = None, None, None
        try:
            rows = _hk_daily_series(f"{code}.HK")
            r = max(rows, key=lambda x: x.get("trade_date") or "")
            price, chg = r.get("close"), r.get("pct_chg")
            td = r.get("trade_date")
        except Exception:
            pass
        try:
            base = _em_quote(secid, True)
        except RateLimitError:
            raise  # v5.8.2 硬停纪律：东财行情限流穿透；hk_daily 缓存读取侧哨兵语义不动（下例外）
        except Exception:
            base = {"名称": code, "代码": code, "最新价": None, "涨跌幅%": None,
                    "总市值亿": None, "PE_TTM": None, "PB": None, "换手率%": None}
        return {"名称": base.get("名称") or code, "代码": code,
                "最新价": price if price is not None else base.get("最新价"),
                "涨跌幅%": chg if chg is not None else base.get("涨跌幅%"),
                "总市值亿": base.get("总市值亿"), "PE_TTM": base.get("PE_TTM"),
                "PB": base.get("PB"), "换手率%": base.get("换手率%"),
                "数据日期": td or "东财实时"}
    try:
        ts = to_ts_code(code)
        r = _daily_basic_latest(code)
        name = code
        try:
            sb = _C.ts_call("stock_basic", {"ts_code": ts, "fields": "ts_code,name"})
            if sb:
                name = sb[0].get("name") or code
        except Exception:
            pass
        chg = None
        try:
            # 单日 pct_chg 取自 430 天日线序列缓存（fetch_timing_material 同源），
            # 免单独发单日 daily 请求（同一 E1 段内 quote→timing 先后触发，两请求合一）
            row = {x.get("trade_date"): x for x in _a_daily_series(ts)}.get(r["trade_date"]) or {}
            chg = row.get("pct_chg")
        except Exception:
            pass
        return {"名称": name, "代码": code, "最新价": r.get("close"), "涨跌幅%": _r2(chg),
                "总市值亿": (f"{(r.get('total_mv') or 0) / 1e4:,.1f}" if r.get("total_mv") else None),  # 万元→亿
                "PE_TTM": _r2(r.get("pe_ttm")), "PB": _r2(r.get("pb")),
                "换手率%": _r2(r.get("turnover_rate")), "数据日期": r.get("trade_date")}
    except Exception:
        return _em_quote(secid, False)


# ---------------- E2 月线 ----------------
def kline_url(secid: str, klt: int, beg: str, end: str) -> str:
    """push2his K线 URL 拼装（klt=周期：101 日 / 103 月；fqt=1 前复权）——
    _em_kline_monthly 与 score_calibration._em_kline_daily 共用，口径唯一
    （跨模块消费，v5.1.5 起去下划线改公开名）。"""
    return (f"https://push2his.eastmoney.com/api/qt/stock/kline/get?secid={secid}"
            f"&fields1=f1,f2,f3&fields2=f51,f53&klt={klt}&fqt=1&beg={beg}&end={end}")


def _em_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    beg, end = _win_years(years, "20991231")
    url = kline_url(secid, 103, beg, end)
    d = _C.get(url).get("data") or {}
    out = []
    # 换算差异（实测）：A股K线 ×100（2331=23.31）；港股K线为真实价（53.600），无需换算
    div = 1 if is_hk else 100
    for k in (d.get("klines") or []):
        p = k.split(",")
        out.append({"date": p[0], "close": float(p[1]) / div})
    # 缩放校准：push2his 返回缩放行为不稳定（两次实测：×100 与原始价都出现过），
    # 用 E1 最新价反推——偏差>50% 且 ×100 后吻合则补救
    try:
        ref = fetch_quote(secid, is_hk).get("最新价")
        if ref and out:
            latest = out[-1]["close"]
            if latest and abs(latest - ref) / ref > 0.5 and abs(latest * 100 - ref) / ref < 0.2:
                out = [{**k, "close": round(k["close"] * 100, 2)} for k in out]
    except Exception:
        pass
    return out


def fetch_kline_monthly(secid: str, years: int, is_hk: bool = False) -> list:
    """E2 月线（前复权）。tushare 优先（monthly+adj_factor 复权；港股 hk_daily 聚合），东财兜底。"""
    code = secid.split(".")[-1]
    try:
        ts = to_ts_code(code)
        beg, end = _win_years(years)
        if is_hk:
            # 港股无月线接口：缓存日线按 YYYYMM 聚合（取每月最后交易日收盘），港股不做复权
            rows = _hk_daily_series(ts)
            cutoff = f"{date.today().year - years}01"
            if not any(r["trade_date"][:6] >= cutoff for r in rows):
                raise RuntimeError("hk_daily 聚合为空")
            # v4.11.0：聚合同步产出月线 OHLC（季K 蜡烛四值；开=当月首日、高/低=月内极值、收=月末）；
            # 日线行缺 OHLC 任一键 → 该月仅 close（图回退发丝线，不炸链路）
            ohlc = {}
            for r in rows:
                ym = r["trade_date"][:6]
                if ym < cutoff:
                    continue
                slot = ohlc.setdefault(ym, {"o": None, "h": None, "l": None, "c": None, "d": None})
                try:
                    o, h, l, c = (float(r[k]) for k in ("open", "high", "low", "close"))
                except (KeyError, TypeError, ValueError):
                    try:
                        o, h, l, c = None, None, None, float(r["close"])
                    except (KeyError, TypeError, ValueError):
                        continue
                if slot["d"] is None:
                    slot.update(o=o, h=h, l=l, c=c, d=r["trade_date"])
                else:
                    if o is not None:
                        if slot["o"] is None:
                            slot.update(o=o, h=h, l=l)   # 首个带 OHLC 的行补齐（首行缺键不再丢整月）
                        else:
                            slot["h"], slot["l"] = max(slot["h"], h), min(slot["l"], l)
                    if r["trade_date"] >= slot["d"]:
                        slot["c"], slot["d"] = c, r["trade_date"]
            out = []
            for _, v in sorted(ohlc.items()):
                e = {"date": _fmt_date(v["d"]), "close": round(v["c"], 3)}
                if v["o"] is not None:
                    e.update(open=round(v["o"], 3), high=round(v["h"], 3), low=round(v["l"], 3))
                out.append(e)
            return out
        rows = _C.ts_call("monthly", {"ts_code": ts, "start_date": beg, "end_date": end})
        if not rows:
            raise RuntimeError("monthly 空返回")
        fac = _C.ts_call("adj_factor", {"ts_code": ts, "start_date": beg, "end_date": end})
        if not fac:
            raise RuntimeError("adj_factor 空返回，无法前复权，兜底东财")
        fmap = {f["trade_date"]: float(f["adj_factor"]) for f in fac if f.get("adj_factor")}
        latest_f = fmap[max(fmap)]
        out = []
        for r in sorted(rows, key=lambda x: x["trade_date"]):
            c = float(r["close"])
            try:
                o, h, l = (float(r[k]) for k in ("open", "high", "low"))
            except (KeyError, TypeError, ValueError):
                o = h = l = None   # 缺 OHLC 任一键 → 该月仅 close（图回退发丝线）
            f = fmap.get(r["trade_date"])
            if f and latest_f:
                c = c * f / latest_f   # 前复权
                if o is not None:
                    o, h, l = (v * f / latest_f for v in (o, h, l))
            e = {"date": _fmt_date(r["trade_date"]), "close": round(c, 2)}
            if o is not None:
                e.update(open=round(o, 2), high=round(h, 2), low=round(l, 2))
            out.append(e)
        # v4.8.1：月度 PE(TTM) 回填（供 price_history 图，替代模型手工「月收×总股本÷TTM净利」）。
        # 与 fetch_pe_pb_band 同参同字段（kline-years=5 时窗口亦同），命中透明缓存不增发请求；
        # 失败静默跳过（仅 close，图降级单线）
        try:
            pe_map = {r["trade_date"]: float(r["pe_ttm"])
                      for r in _C.ts_call("daily_basic", {"ts_code": ts, "start_date": beg, "end_date": end},
                                       fields="ts_code,trade_date,pe_ttm,pb")
                      if r.get("trade_date") and r.get("pe_ttm") and float(r["pe_ttm"]) > 0}
            for k, r in zip(out, sorted(rows, key=lambda x: x["trade_date"])):
                pe = pe_map.get(r["trade_date"])
                if pe:
                    k["pe"] = round(pe, 1)
        except Exception:
            pass
        return out
    except Exception:
        return _em_kline_monthly(secid, years, is_hk)


def _rsi_wilder(closes, period=14):
    if len(closes) < period + 1:
        return None
    changes = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(change, 0) for change in changes]
    losses = [max(-change, 0) for change in changes]
    gain = sum(gains[:period]) / period
    loss = sum(losses[:period]) / period
    for up, down in zip(gains[period:], losses[period:]):
        gain = (gain * (period - 1) + up) / period
        loss = (loss * (period - 1) + down) / period
    if loss == 0:
        return 100.0 if gain > 0 else 50.0
    return 100 - 100 / (1 + gain / loss)


def _atr_wilder(rows, period=14):
    ranges = []
    for i, row in enumerate(rows):
        try:
            high, low = float(row["high"]), float(row["low"])
            current = float(row["close"])
            previous = float(rows[i - 1]["close"]) if i else current
            ranges.append(max(high - low, abs(high - previous), abs(low - previous)))
        except (KeyError, TypeError, ValueError):
            ranges.append(None)
    if len(ranges) < period or any(value is None for value in ranges[-period:]):
        return None
    atr = sum(ranges[:period]) / period
    for value in ranges[period:]:
        if value is not None:
            atr = (atr * (period - 1) + value) / period
    return atr


def _macd(closes, fast=12, slow=26, signal=9):
    """DIF 在第 26 个有效收盘价形成，DEA 从该值起算；柱=2×(DIF−DEA)。"""
    def next_ema(values, period):
        alpha = 2 / (period + 1)
        ema = values[0]
        return [ema := value * alpha + ema * (1 - alpha) for value in values[1:]]

    if len(closes) < slow:
        return {"dif": None, "dea": None, "hist": None}
    fast_line, slow_line = next_ema(closes, fast), next_ema(closes, slow)
    dif = [a - b for a, b in zip(fast_line, slow_line)]
    dea = next_ema(dif[slow - 2:], signal)
    return {"dif": round(dif[-1], 6), "dea": round(dea[-1], 6),
            "hist": round(2 * (dif[-1] - dea[-1]), 6)}


def _ma_slope(closes, window, lag=20):
    if len(closes) < window + lag:
        return None
    current = sum(closes[-window:]) / window
    previous = sum(closes[-window - lag:-lag]) / window
    return round((current / previous - 1) * 100, 2) if previous else None


def compute_technical_facts(rows):
    """由同一日线 OHLCV 序列计算事实，不给出买卖信号，也不参与评分。"""
    rows = sorted((row for row in rows or []
                   if row.get("trade_date") and row.get("close") is not None),
                  key=lambda row: row["trade_date"])
    closes = [float(row["close"]) for row in rows]
    result = {"as_of": rows[-1]["trade_date"] if rows else None,
              "sample_days": len(rows), "rsi14": None, "atr14_pct": None,
              "macd": _macd(closes), "volume_ratio_20": None,
              "ma60_slope_20d_pct": _ma_slope(closes, 60),
              "ma120_slope_20d_pct": _ma_slope(closes, 120),
              "position_52w_pct": None}
    rsi = _rsi_wilder(closes)
    if rsi is not None:
        result["rsi14"] = round(rsi, 2)
    atr = _atr_wilder(rows)
    if atr is not None and closes[-1] > 0:
        result["atr14_pct"] = round(atr / closes[-1] * 100, 2)
    if len(rows) >= 21:
        volumes = []
        for row in rows[-21:-1]:
            try:
                volumes.append(float(row["vol"]))
            except (KeyError, TypeError, ValueError):
                volumes.append(None)
        base = sum(volumes) / 20 if all(value is not None for value in volumes) else None
        try:
            latest_volume = float(rows[-1]["vol"])
        except (KeyError, TypeError, ValueError):
            latest_volume = None
        if base and latest_volume is not None:
            result["volume_ratio_20"] = round(latest_volume / base, 2)
    window = closes[-250:]
    if window and max(window) > min(window):
        result["position_52w_pct"] = round(
            (window[-1] - min(window)) / (max(window) - min(window)) * 100, 2)
    return result


def consensus_price_levels(monthly_rows, years=3):
    """历史月末/盘中价格区间；不是券商目标价，也不构成价位预测。"""
    rows = []
    for row in monthly_rows or []:
        try:
            day = date.fromisoformat(str(row["date"])[:10])
            rows.append((day, row))
        except (KeyError, TypeError, ValueError):
            continue
    if not rows:
        return None
    rows.sort(key=lambda item: item[0])
    latest = rows[-1][0]
    try:
        cutoff = latest.replace(year=latest.year - years)
    except ValueError:
        cutoff = latest.replace(year=latest.year - years, day=28)
    selected = [row for day, row in rows if day >= cutoff]
    closes = [float(row["close"]) for row in selected]
    ohlc = [row for row in selected
            if row.get("high") is not None and row.get("low") is not None]
    complete = len(ohlc) == len(selected)
    return {"window_years": years, "start_date": str(selected[0]["date"])[:10],
            "end_date": str(selected[-1]["date"])[:10], "months": len(selected),
            "ohlc_months": len(ohlc), "close_high": max(closes), "close_low": min(closes),
            "intraday_high": max(float(row["high"]) for row in ohlc) if complete else None,
            "intraday_low": min(float(row["low"]) for row in ohlc) if complete else None}


def fetch_timing_material(code: str, is_hk: bool = False, monthly_rows=None):
    """原有价格/均线键不变，新增 technical 与月线 consensus_levels。"""
    try:
        rows = (_hk_daily_series(f"{code}.HK") if is_hk
                else _a_daily_series(to_ts_code(code)))
        rows = sorted((r for r in rows if r.get("trade_date") and r.get("close") is not None),
                      key=lambda x: x["trade_date"])
        closes = [float(r["close"]) for r in rows]
        if len(closes) < 60:
            return None

        def _ma(n):
            return round(sum(closes[-n:]) / n, 2) if len(closes) >= n else None
        win = closes[-250:]
        return {"price": round(closes[-1], 2), "ma60": _ma(60), "ma120": _ma(120),
                "high_52w": round(max(win), 2), "low_52w": round(min(win), 2),
                "n": len(closes), "technical": compute_technical_facts(rows),
                "consensus_levels": consensus_price_levels(monthly_rows)}
    except Exception as e:
        print(f"⚠️ fetch_timing_material({code}): {e}", file=sys.stderr)
        return None


def fetch_capital_material(code: str) -> dict:
    out = {"main_net_inflow": None, "southbound": None, "margin": None}
    ts = to_ts_code(code)
    beg, end = _win_days(15)

    def _latest(rows, required):
        rows = [r for r in rows if r.get("trade_date")]
        if not rows:
            raise RuntimeError("空返回")
        row = max(rows, key=lambda r: r["trade_date"])
        if any(row.get(key) is None for key in required):
            raise RuntimeError("必要字段缺失")
        return row

    try:
        rows = _C.ts_call("moneyflow", {"ts_code": ts, "start_date": beg, "end_date": end})
        r = _latest(rows, ("buy_lg_amount", "buy_elg_amount", "sell_lg_amount", "sell_elg_amount"))
        net = (float(r["buy_lg_amount"]) + float(r["buy_elg_amount"])
               - float(r["sell_lg_amount"]) - float(r["sell_elg_amount"])) / 1e4
        out["main_net_inflow"] = {
            "value": round(net, 4), "unit": "亿元", "date": _fmt_date(r["trade_date"]),
            "source": "Tushare moneyflow（大单+特大单）",
            "query": f"moneyflow {ts} {beg}-{end}"}
    except Exception as e:
        _C._ts_quiet("fetch_capital_material moneyflow", e)
    try:
        rows = _C.ts_call("margin_detail", {"ts_code": ts, "start_date": beg, "end_date": end})
        r = _latest(rows, ("rzye",))
        record = {
            "value": round(float(r["rzye"]) / 1e8, 4), "unit": "亿元",
            "date": _fmt_date(r["trade_date"]), "source": "Tushare margin_detail",
            "query": f"margin_detail {ts} {beg}-{end}"}
        if r.get("rqye") is not None:
            record["note"] = f"融券余额 {float(r['rqye']) / 1e4:.2f} 万元"
        out["margin"] = record
    except Exception as e:
        _C._ts_quiet("fetch_capital_material margin_detail", e)
    return out
