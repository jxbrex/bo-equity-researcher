#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""quality_inputs.py — 按报告日组装九维评分所需的可追溯财务输入。"""
from datetime import date, timedelta

import em_core as _C
from em_core import to_ts_code, RateLimitError
from em_finance import _compose_annual_row, _pick_latest_per_period, _em_f10, _nco_bad
from quality_rules import PROFILE_KIND, PROFILE_FLAGS, F_ITEM_IDS, requires_normalized_roic


def _day(value):
    text = str(value or "").replace("-", "")[:8]
    return text if len(text) == 8 and text.isdigit() else None


def _iso(value):
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


def _window(as_of, years=5):
    end = date.fromisoformat(_iso(as_of))
    start = end - timedelta(days=365 * years)
    return start.strftime("%Y%m%d"), end.strftime("%Y%m%d")


def _stmt(code, api, as_of, annual=True):
    beg, end = _window(as_of)
    try:
        rows = _C.ts_call(api, {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end})
    except RateLimitError:
        raise
    except Exception:
        return []
    if annual:
        rows = [r for r in rows if (r.get("end_date") or "").endswith("1231")]
    if api in ("income", "balancesheet"):
        rows = [r for r in rows if str(r.get("report_type")) in {"1", "4"}]
    return rows


def _visible(rows, as_of, key="ann_date"):
    visible, unknown = [], 0
    for row in rows:
        disclosed = _day(row.get(key))
        if not disclosed:
            unknown += 1
        elif disclosed <= as_of:
            visible.append(row)
    return visible, unknown


def _em_map(secucode, as_of):
    if not secucode:
        return {}
    try:
        rows = _em_f10(secucode, size=5, annual_only=True) or []
    except RateLimitError:
        raise
    except Exception:
        return {}
    out = {}
    for row in rows:
        disclosed = _day(row.get("NOTICE_DATE") or row.get("ANN_DATE") or row.get("UPDATE_DATE"))
        year = (row.get("REPORT_DATE_NAME") or row.get("REPORT_DATE") or "")[:4]
        if disclosed and disclosed <= as_of and year.isdigit():
            out[year] = row
    return out


def _annual_bundle(code, secucode, as_of):
    apis = ("income", "fina_indicator", "cashflow", "balancesheet")
    visible, unknown = {}, 0
    for api in apis:
        rows, missed = _visible(_stmt(code, api, as_of), as_of)
        visible[api], unknown = rows, unknown + missed
    em = _em_map(secucode, as_of)
    income = _pick_latest_per_period(visible["income"])[:5]
    ind_map = {r["end_date"]: r for r in _pick_latest_per_period(visible["fina_indicator"])}
    cf_map = {r["end_date"]: r for r in _pick_latest_per_period(visible["cashflow"])}
    bs_map = {r["end_date"]: r for r in _pick_latest_per_period(visible["balancesheet"])}
    rows, raw = [], {}
    for r in income:
        end = r["end_date"]
        raw[end] = {"income": r, "fina_indicator": ind_map.get(end) or {},
                    "cashflow": cf_map.get(end) or {}, "balancesheet": bs_map.get(end) or {}}
        rows.append(_compose_annual_row(r, ind_map.get(end) or {}, cf_map.get(end) or {},
                                        em.get(end[:4]) or {}))
    return rows, raw, unknown, bool(em)


def _latest_raw(code, as_of):
    latest = {}
    for api in ("income", "fina_indicator", "cashflow", "balancesheet"):
        rows, _ = _visible(_stmt(code, api, as_of, annual=False), as_of)
        latest[api] = _pick_latest_per_period(rows)[:1]
    if not latest["income"]:
        return None
    end = latest["income"][0]["end_date"]
    result = {api: (latest[api][0] if latest[api] and latest[api][0].get("end_date") == end else {})
              for api in latest} | {"end_date": end}
    result["latest_balancesheet"] = latest["balancesheet"][0] if latest["balancesheet"] else {}
    return result


def _share_series(code, as_of):
    beg, end = _window(as_of)
    try:
        rows = _C.ts_call("daily_basic", {"ts_code": to_ts_code(code), "start_date": beg, "end_date": end},
                          fields="ts_code,trade_date,total_share")
    except RateLimitError:
        raise
    except Exception:
        return []
    rows, _ = _visible(rows, as_of, "trade_date")
    return sorted(rows, key=lambda r: r["trade_date"])


def _share_before(rows, end_date):
    values = [r for r in rows if r.get("trade_date") <= end_date and r.get("total_share") is not None]
    return values[-1]["total_share"] if values else None


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _gt(value, threshold=0):
    value = _num(value)
    return None if value is None else value > threshold


def _improve(current, previous, strict=True):
    current, previous = _num(current), _num(previous)
    if current is None or previous is None:
        return None
    return current > previous if strict else current >= previous


def _debt(raw):
    bs = raw.get("balancesheet") or {}
    required = ("st_borr", "non_cur_liab_due_1y", "lt_borr", "bond_payable", "money_cap")
    if any(bs.get(key) is None for key in required):
        return None, None, None, None
    short_keys = ["st_borr", "non_cur_liab_due_1y"]
    if bs.get("st_bonds_payable") is not None:
        short_keys.append("st_bonds_payable")
    st = sum(_num(bs.get(key)) for key in short_keys)
    lt = sum(_num(bs.get(key)) for key in ("lt_borr", "bond_payable"))
    money = _num(bs.get("money_cap"))
    cover = money / st if st > 0 else 1e9
    return st, lt, money, cover


def _roa(raw):
    income, bs = raw.get("income") or {}, raw.get("balancesheet") or {}
    profit, assets = _num(income.get("n_income")), _num(bs.get("total_assets"))
    return profit / assets if profit is not None and assets else None


def _turnover(raw):
    income, bs = raw.get("income") or {}, raw.get("balancesheet") or {}
    revenue, assets = _num(income.get("total_revenue")), _num(bs.get("total_assets"))
    return revenue / assets if revenue is not None and assets else None


def _fmt_value(value, digits=1):
    return "未获取" if _num(value) is None else f"{_num(value):,.{digits}f}"


def _change_text(current, previous, unit="", digits=1, relative=False):
    if current is None and previous is None:
        return "未获取"
    previous_text = _fmt_value(previous, digits) + ("%" if unit == "%" and previous is not None else "")
    text = f"{previous_text} → {_fmt_value(current, digits)}{unit}"
    if current is None or previous is None:
        return text
    delta = ((current / previous - 1) * 100 if relative and previous
             else current - previous if not relative else None)
    if delta is None:
        return text
    delta_unit = "%" if relative else "pct" if unit == "%" else unit
    delta_digits = 2 if unit in ("%", " 倍", "亿股") else 1
    delta_text = f"{delta:+.{delta_digits}f}" if delta else f"{delta:.{delta_digits}f}"
    return f"{text}（{delta_text}{delta_unit}）"


def _f_item_evidence(rows, current, previous, current_raw, previous_raw, shares):
    if not current:
        return {"period": "", "items": {}}
    current_year = current["END_DATE"][:4]
    previous_year = previous["END_DATE"][:4] if previous else None
    period = f"{previous_year}→{current_year}年报" if previous_year else f"{current_year}年报"
    long_current = _debt(current_raw)[1] / 1e8 if current_raw and _debt(current_raw)[1] is not None else None
    long_previous = _debt(previous_raw)[1] / 1e8 if previous_raw and _debt(previous_raw)[1] is not None else None
    cover_current = _debt(current_raw)[3] if current_raw else None
    cover_previous = _debt(previous_raw)[3] if previous_raw else None
    share_current = _share_before(shares, current["END_DATE"])
    share_previous = _share_before(shares, previous["END_DATE"]) if previous else None
    share_current = share_current / 10000 if share_current is not None else None
    share_previous = share_previous / 10000 if share_previous is not None else None
    cash_values = [r["NCO_NETPROFIT"] for r in rows if r.get("NCO_NETPROFIT") is not None]
    if cover_current == 1e9 and cover_previous == 1e9:
        cover_text = "无短债"
    elif cover_current == 1e9 or cover_previous == 1e9:
        previous_text = ("无短债" if cover_previous == 1e9 else "未获取" if cover_previous is None
                         else _fmt_value(cover_previous, 2) + " 倍")
        current_text = ("无短债" if cover_current == 1e9 else "未获取" if cover_current is None
                        else _fmt_value(cover_current, 2) + " 倍")
        cover_text = f"{previous_text} → {current_text}"
    else:
        cover_text = _change_text(cover_current, cover_previous, " 倍", 2)
    items = {
        "profit_positive": (f"{_fmt_value(current.get('KCFJCXSYJLR') / 1e8)}亿元"
                            if current.get("KCFJCXSYJLR") is not None else "未获取"),
        "ocf_positive": (f"净额{_fmt_value(current.get('NETCASH_OPERATE_PK') / 1e8)}亿元"
                         if current.get("NETCASH_OPERATE_PK") is not None else "未获取"),
        "roa_improving": _change_text(_roa(current_raw) * 100 if current_raw and _roa(current_raw) is not None else None,
                                      _roa(previous_raw) * 100 if previous_raw and _roa(previous_raw) is not None else None,
                                      "%", 2),
        "cash_quality_ok": (f"{len(cash_values)}个有效年度最低 {min(cash_values):.2f} 倍（仅净利润为正年度）"
                            if cash_values else "未获取"),
        "long_debt_down": _change_text(long_current, long_previous, "亿元", 1, relative=True),
        "short_cover_improving": cover_text,
        "no_dilution": _change_text(share_current, share_previous, "亿股", 2, relative=True),
        "gross_margin_improving": _change_text(current.get("XSMLL"),
                                               previous.get("XSMLL") if previous else None, "%", 1),
        "asset_turnover_improving": _change_text(_turnover(current_raw) if current_raw else None,
                                                  _turnover(previous_raw) if previous_raw else None,
                                                  " 次", 3, relative=True),
    }
    return {"period": period, "items": items}


def _cash_runway(rows, raw, latest_raw=None):
    if not rows or not raw:
        return None
    bs = ((latest_raw.get("latest_balancesheet") or latest_raw.get("balancesheet"))
          if latest_raw else raw[max(raw)].get("balancesheet")) or {}
    cash = _num(bs.get("money_cap"))
    if cash is None and latest_raw:
        cash = _num((raw[max(raw)].get("balancesheet") or {}).get("money_cap"))
    ocf = _num(rows[0].get("NETCASH_OPERATE_PK"))
    return cash / (-ocf) * 12 if cash is not None and ocf is not None and ocf < 0 else None


def _coverage_value(coverage, key, value, unknown=False):
    coverage[key] = "ok" if value is not None else "date_unknown" if unknown else "missing"


def _profile_missing(profile):
    required = {"stock_type", "industry_profile", "growth_tier"}
    return (not isinstance(profile, dict) or required - set(profile)
            or not profile.get("stock_type") or not profile.get("industry_profile")
            or profile["industry_profile"] not in PROFILE_KIND)


def _base_result(as_of, profile):
    return {"as_of": _iso(as_of), "profile": profile, "1D": {}, "1F": {},
            "coverage": {}, "sources": [], "meta": {}}


def fetch_quality_inputs(code: str, secucode: str, as_of: str, profile: dict) -> dict:
    """按披露日组装评分输入；任何缺失都显式标记，不推断分型或数据。"""
    as_of = _day(as_of)
    if not as_of:
        raise ValueError("as_of 必须是 YYYY-MM-DD 或 YYYYMMDD")
    if _profile_missing(profile):
        result = _base_result(as_of, profile)
        result.update(status="profile_missing", coverage={"profile": "profile_missing"})
        return result
    kind = PROFILE_KIND[profile["industry_profile"]]
    if kind == "industry_checklist" or profile["industry_profile"] == "internet_platform":
        result = _base_result(as_of, profile)
        result.update(status="review_only",
                      coverage={"profile": "ok", "1D": "review_only", "1F": "review_only"})
        required = sorted(PROFILE_FLAGS[profile["industry_profile"]])
        result["1D"] = {"kind": kind, "required": required,
                        "red_flags": {name: None for name in required}}
        return result
    rows, raw, unknown, used_em = _annual_bundle(code, secucode, as_of)
    latest_raw = _latest_raw(code, as_of)
    shares = _share_series(code, as_of)
    result = _base_result(as_of, profile)
    result["sources"] = [{"type": "tushare", "apis": ["income", "fina_indicator", "cashflow",
                                                     "balancesheet", "daily_basic"], "as_of": _iso(as_of)}]
    if used_em:
        result["sources"].append({"type": "eastmoney_f10", "as_of": _iso(as_of)})
    result["coverage"]["profile"] = "ok"
    result["coverage"]["disclosure"] = "ok" if rows else "date_unknown"
    runway = _cash_runway(rows, raw, latest_raw)
    if kind == "survival_checklist":
        result["status"] = "ok" if runway is not None else "review_only"
        result["1D"] = {"kind": kind, "cash_runway_months": runway}
        result["1F"] = {"cash_runway_months": runway}
        _coverage_value(result["coverage"], "1D.cash_runway_months", runway, not rows)
        _coverage_value(result["coverage"], "1F.cash_runway_months", runway, not rows)
        return result
    current, previous = (rows[0] if rows else None), (rows[1] if len(rows) > 1 else None)
    current_raw = raw.get(current["END_DATE"]) if current else None
    liquidity_raw = latest_raw or current_raw
    previous_raw = raw.get(previous["END_DATE"]) if previous else None
    f_items = {
        "profit_positive": _gt(current.get("KCFJCXSYJLR")) if current else None,
        "ocf_positive": _gt(current.get("NETCASH_OPERATE_PK")) if current else None,
        "roa_improving": _improve(_roa(current_raw), _roa(previous_raw)) if current_raw and previous_raw else None,
        "cash_quality_ok": (not _nco_bad([r["NCO_NETPROFIT"] for r in rows if r.get("NCO_NETPROFIT") is not None], 2)
                            if len([r for r in rows if r.get("NCO_NETPROFIT") is not None]) >= 2 else None),
        "long_debt_down": (_debt(current_raw)[1] < _debt(previous_raw)[1]
                           if current_raw and previous_raw and
                           _debt(current_raw)[1] is not None and _debt(previous_raw)[1] is not None else None),
        "short_cover_improving": (_debt(current_raw)[3] >= _debt(previous_raw)[3]
                                  if current_raw and previous_raw and
                                  _debt(current_raw)[3] is not None and _debt(previous_raw)[3] is not None else None),
        "no_dilution": (_share_before(shares, current["END_DATE"]) <=
                        _share_before(shares, previous["END_DATE"]) * 1.001
                        if current and previous and _share_before(shares, current["END_DATE"]) is not None
                        and _share_before(shares, previous["END_DATE"]) is not None else None),
        "gross_margin_improving": (_improve(current.get("XSMLL"), previous.get("XSMLL"))
                                   if current and previous else None),
        "asset_turnover_improving": (_improve(_turnover(current_raw), _turnover(previous_raw))
                                     if current_raw and previous_raw else None),
    }
    f_item_evidence = _f_item_evidence(rows, current, previous, current_raw, previous_raw, shares)
    for name in F_ITEM_IDS:
        _coverage_value(result["coverage"], f"1D.f_items.{name}", f_items[name], not rows)
    st, lt, money, cover = _debt(liquidity_raw) if liquidity_raw else (None, None, None, None)
    assets = _num((liquidity_raw or {}).get("balancesheet", {}).get("total_assets"))
    debt_ratio = (st + lt) / assets if assets and st is not None and lt is not None else None
    ocf = _num(current.get("NETCASH_OPERATE_PK")) if current else None
    ocf_cover = ocf / st if ocf is not None and st else None
    liquidity = {"debt_ratio": debt_ratio, "short_cover": cover, "ocf_short_cover": ocf_cover}
    _coverage_value(result["coverage"], "1D.liquidity.debt_ratio", debt_ratio, not rows)
    _coverage_value(result["coverage"], "1D.liquidity.short_cover", cover, not rows)
    _coverage_value(result["coverage"], "1D.liquidity.ocf_short_cover", ocf_cover, not rows)
    if st == 0:
        result["coverage"]["1D.liquidity.ocf_short_cover"] = "not_applicable"
    red_flags = {}
    for key, field in (("receivables", "YSZKZZTS"), ("inventory", "CHZZTS")):
        values = [r.get(field) for r in rows if r.get(field) is not None]
        red_flags[key] = values[0] > values[-1] * 1.3 if len(values) >= 3 else None
        _coverage_value(result["coverage"], f"1D.red_flags.{key}", red_flags[key], not rows)
    roic = (liquidity_raw or {}).get("fina_indicator", {}).get("roic")
    roic_end = (liquidity_raw or {}).get("end_date") if roic is not None else None
    if roic is None and current:
        roic = current.get("ROIC")
        roic_end = current["END_DATE"]
    roic = _num(roic)
    if roic is not None:
        roic = roic / 100
    roic_latest = roic
    components = []
    if requires_normalized_roic(profile):
        for row in rows[:3]:
            value = _num(row.get("ROIC"))
            if value is not None:
                components.append(value / 100)
        roic = sorted(components)[1] if len(components) == 3 else None
        roic_months = 12
        roic_basis = "normalized"
    else:
        roic_months = int(roic_end[4:6]) if roic_end and roic_end[4:6].isdigit() else None
        roic_basis = "latest"
    result["1D"] = {"kind": "generic_f", "f_items": f_items, "f_item_evidence": f_item_evidence,
                    "liquidity": liquidity, "red_flags": red_flags}
    result["1F"] = {"roic": roic, "wacc": 0.08, "incremental_roic": None,
                    "roic_period_months": roic_months, "roic_basis": roic_basis,
                    "roic_latest": roic_latest, "roic_normalized_components": components}
    _coverage_value(result["coverage"], "1F.roic", roic, not rows)
    _coverage_value(result["coverage"], "1F.roic_period_months", roic_months,
                    roic is not None and not roic_end)
    core_values = list(f_items.values()) + [debt_ratio, cover, roic, roic_months] + list(red_flags.values())
    result["status"] = "ok" if all(value is not None for value in core_values) else "partial" if rows else "review_only"
    if current:
        result["meta"] = {"latest_end_date": current["END_DATE"], "latest_ann_date": current.get("ANN_DATE"),
                          "latest_parent_net_profit": current.get("PARENTNETPROFIT"),
                          "liquidity_end_date": latest_raw.get("end_date") if latest_raw else current["END_DATE"]}
    if requires_normalized_roic(profile):
        result["meta"]["roic_normalization"] = "median_3y"
    return result
