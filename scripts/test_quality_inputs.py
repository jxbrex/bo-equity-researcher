#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import quality_inputs as qi


PROFILE = {"stock_type": "成长型", "industry_profile": "generic", "growth_tier": "mid",
           "peer_gross_margin_mean": 30, "gross_margin_explained": True}


def _rows(year, ann, profit=100, revenue=1000, assets=1000, share=100, ocf=120):
    return {
        "income": {"end_date": f"{year}1231", "ann_date": ann, "report_type": "1",
                   "n_income": profit, "n_income_attr_p": profit, "total_revenue": revenue},
        "fina_indicator": {"end_date": f"{year}1231", "ann_date": ann,
                           "profit_dedt": profit * 0.9, "roe": 10, "grossprofit_margin": 30,
                           "netprofit_margin": 10, "debt_to_assets": 50, "roic": 12,
                           "ar_turn": 10, "turn_days": 100},
        "cashflow": {"end_date": f"{year}1231", "ann_date": ann,
                     "n_cashflow_act": ocf, "c_pay_acq_const_fiolta": 50},
        "balancesheet": {"end_date": f"{year}1231", "ann_date": ann, "report_type": "1",
                         "total_assets": assets, "st_borr": 50, "non_cur_liab_due_1y": 10,
                         "lt_borr": 100, "bond_payable": 20, "money_cap": 300},
        "daily_basic": {"trade_date": f"{year}1230", "total_share": share},
    }


def _install(monkeypatch, rows):
    def fake_ts(api, params, fields=None):
        return rows.get(api, [])
    monkeypatch.setattr(qi._C, "ts_call", fake_ts)


def _bundle(*entries):
    out = {"income": [], "fina_indicator": [], "cashflow": [], "balancesheet": [], "daily_basic": []}
    for entry in entries:
        for api, row in entry.items():
            out[api].append(row)
    return out


def test_profile_is_explicit_not_inferred(monkeypatch):
    called = []
    monkeypatch.setattr(qi._C, "ts_call", lambda *args, **kwargs: called.append(1) or [])
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", {"stock_type": "成长型"})
    assert result["status"] == "profile_missing"
    assert result["coverage"]["profile"] == "profile_missing"
    assert not called


def test_as_of_excludes_future_disclosure(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260410", profit=999))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["meta"]["latest_end_date"] == "20241231"
    assert result["meta"]["latest_ann_date"] == "20250320"


def test_duplicate_period_uses_available_then_no_later_restatement(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260410", profit=999),
                   _rows(2025, "20260320", profit=100))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["meta"]["latest_ann_date"] == "20260320"
    assert result["meta"]["latest_parent_net_profit"] == 100


def test_restated_income_uses_latest_adjusted_row(monkeypatch):
    rows = [
        {"end_date": "20251231", "report_type": "1", "ann_date": "20260320", "total_revenue": 100},
        {"end_date": "20251231", "report_type": "4", "ann_date": "20260410", "total_revenue": 80},
    ]
    monkeypatch.setattr(qi._C, "ts_call", lambda *args, **kwargs: rows)
    visible, _ = qi._visible(qi._stmt("600000", "income", "20261231"), "20261231")
    selected = qi._pick_latest_per_period(visible)[0]
    assert selected["report_type"] == "4"
    assert selected["total_revenue"] == 80


def test_missing_ann_date_is_date_unknown_not_ok(monkeypatch):
    rows = _bundle(_rows(2025, None))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["status"] == "review_only"
    assert result["coverage"]["disclosure"] == "date_unknown"
    assert result["coverage"]["1D.f_items.profit_positive"] == "date_unknown"


def test_financial_profile_skips_generic_f(monkeypatch):
    called = []
    monkeypatch.setattr(qi._C, "ts_call", lambda *args, **kwargs: called.append(1) or [])
    profile = {"stock_type": "稳定价值/金融", "industry_profile": "financial_bank", "growth_tier": None}
    result = qi.fetch_quality_inputs("601398", None, "2026-04-01", profile)
    assert result["status"] == "review_only"
    assert result["1D"]["kind"] == "industry_checklist"
    assert "f_items" not in result["1D"]
    assert "npl_trend" in result["1D"]["required"]
    assert not called


def test_quality_inputs_have_source_and_coverage(monkeypatch):
    rows = _bundle(_rows(2023, "20240320", profit=80, revenue=800, assets=900, share=100),
                   _rows(2024, "20250320", profit=90, revenue=900, assets=1000, share=100),
                   _rows(2025, "20260320", profit=100, revenue=1100, assets=1100, share=100))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["status"] == "ok"
    assert result["sources"]
    assert result["coverage"]["1D.f_items.profit_positive"] == "ok"
    assert result["1D"]["f_items"]["profit_positive"] is True
    assert result["1D"]["f_items"]["ocf_positive"] is True
    assert result["1D"]["f_items"]["roa_improving"] is True
    assert result["1D"]["f_items"]["cash_quality_ok"] is True
    assert result["1D"]["f_items"]["long_debt_down"] is False
    assert result["1D"]["f_items"]["short_cover_improving"] is True
    assert result["1D"]["f_items"]["no_dilution"] is True
    assert result["1D"]["f_items"]["gross_margin_improving"] is False
    assert result["1D"]["f_items"]["asset_turnover_improving"] is True
    assert result["1F"]["roic"] == 0.12
    assert result["1F"]["wacc"] == 0.08


def test_missing_red_flag_inputs_make_partial(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["status"] == "partial"
    assert result["coverage"]["1D.red_flags.receivables"] == "missing"


def test_cash_runway_profile_has_no_generic_f(monkeypatch):
    rows = _bundle(_rows(2025, "20260320", ocf=-100))
    _install(monkeypatch, rows)
    profile = {"stock_type": "未盈利/管线", "industry_profile": "pre_profit", "growth_tier": None}
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", profile)
    assert result["status"] == "ok"
    assert result["1D"]["kind"] == "survival_checklist"
    assert result["1D"]["cash_runway_months"] == 36
    assert result["1F"]["cash_runway_months"] == 36
    assert "f_items" not in result["1D"]


def test_cash_runway_uses_latest_visible_cash_with_annual_burn(monkeypatch):
    annual = _rows(2025, "20260320", ocf=-100)
    quarter = _rows(2026, "20261020", ocf=200)
    for api, row in quarter.items():
        if api != "daily_basic":
            row["end_date"] = "20260930"
    quarter["balancesheet"]["money_cap"] = 600
    rows = _bundle(annual, quarter)
    _install(monkeypatch, rows)
    profile = {"stock_type": "困境反转", "industry_profile": "turnaround", "growth_tier": None}
    result = qi.fetch_quality_inputs("600000", None, "2026-10-23", profile)
    assert result["1D"]["cash_runway_months"] == 72
    assert result["1F"]["cash_runway_months"] == 72


def test_cash_runway_uses_latest_balance_sheet_not_income_period(monkeypatch):
    annual = _rows(2025, "20260320", ocf=-100)
    annual["balancesheet"]["money_cap"] = 100
    latest_income = _rows(2026, "20261020")["income"]
    latest_income["end_date"] = "20260930"
    latest_balance = _rows(2026, "20260820")["balancesheet"]
    latest_balance.update(end_date="20260630", money_cap=600)
    rows = _bundle(annual, {"income": latest_income, "balancesheet": latest_balance})
    _install(monkeypatch, rows)
    profile = {"stock_type": "困境反转", "industry_profile": "turnaround", "growth_tier": None}
    result = qi.fetch_quality_inputs("600000", None, "2026-10-23", profile)
    assert result["1D"]["cash_runway_months"] == 72
    assert result["1F"]["cash_runway_months"] == 72


def test_short_term_bond_is_included_in_liquidity_not_long_debt(monkeypatch):
    annual = _rows(2025, "20260320", profit=100, revenue=1000, assets=1000)
    quarter = _rows(2026, "20261020", profit=120, revenue=1200, assets=1200)
    for api, row in quarter.items():
        if api == "daily_basic":
            continue
        row["end_date"] = "20260930"
        if api == "balancesheet":
            row.update(st_borr=10, non_cur_liab_due_1y=0, st_bonds_payable=60,
                       lt_borr=20, bond_payable=0, money_cap=100, total_assets=500)
    rows = _bundle(annual, quarter)
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-10-23", PROFILE)
    assert result["1D"]["liquidity"]["short_cover"] == 100 / 70
    assert result["1D"]["liquidity"]["debt_ratio"] == 90 / 500


def test_liquidity_and_roic_prefer_latest_visible_quarter(monkeypatch):
    annual = _rows(2025, "20260320", profit=100, revenue=1000, assets=1000)
    quarter = _rows(2026, "20261020", profit=120, revenue=1200, assets=1200)
    for api, row in quarter.items():
        if api == "daily_basic":
            continue
        row["end_date"] = "20260930"
        if api == "fina_indicator":
            row["roic"] = 18.4
        if api == "cashflow":
            row["n_cashflow_act"] = 240
        if api == "balancesheet":
            row.update(st_borr=10, non_cur_liab_due_1y=0, lt_borr=20, bond_payable=0,
                       money_cap=100, total_assets=500)
    future = _rows(2026, "20261220", profit=999)
    for api, row in future.items():
        if api != "daily_basic":
            row["end_date"] = "20261231"
    rows = _bundle(annual, quarter, future)
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-10-23", PROFILE)
    assert result["1D"]["liquidity"]["short_cover"] == 10
    assert result["1D"]["liquidity"]["debt_ratio"] == 0.06
    assert result["1D"]["liquidity"]["ocf_short_cover"] == 12
    assert result["coverage"]["1D.liquidity.ocf_short_cover"] == "ok"
    assert result["1F"]["roic"] == 0.184
    assert result["1F"]["roic_period_months"] == 9
    assert result["1F"]["roic_basis"] == "latest"
    assert result["meta"]["liquidity_end_date"] == "20260930"


def test_roic_output_is_decimal_not_percent(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["1F"]["roic"] == 0.12


def test_cycle_roic_uses_median_of_last_three_visible_annual_values(monkeypatch):
    entries = []
    for year, ann, roic in ((2023, "20240320", 30), (2024, "20250320", 10), (2025, "20260320", 40)):
        entry = _rows(year, ann)
        entry["fina_indicator"]["roic"] = roic
        entries.append(entry)
    _install(monkeypatch, _bundle(*entries))
    profile = dict(PROFILE, stock_type="周期股", industry_profile="resources_upstream")
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", profile)
    assert result["1F"]["roic"] == 0.30
    assert result["1F"]["roic_latest"] == 0.40
    assert result["1F"]["roic_basis"] == "normalized"
    assert result["1F"]["roic_period_months"] == 12
    assert result["1F"]["roic_normalized_components"] == [0.40, 0.10, 0.30]
    assert result["meta"]["roic_normalization"] == "median_3y"


def test_cycle_roic_does_not_fall_back_to_latest_without_three_years(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    _install(monkeypatch, rows)
    profile = dict(PROFILE, stock_type="周期股", industry_profile="resources_upstream")
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", profile)
    assert result["1F"]["roic"] is None
    assert result["1F"]["roic_latest"] == 0.12
    assert result["1F"]["roic_basis"] == "normalized"
    assert result["1F"]["roic_normalized_components"] == [0.12, 0.12]


def test_roic_percentage_values_are_decimal(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    _install(monkeypatch, rows)
    for source, expected in ((0.5, 0.005), (1.0, 0.01), (-0.5, -0.005)):
        rows["fina_indicator"][1]["roic"] = source
        result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
        assert result["1F"]["roic"] == expected
        assert result["1F"]["roic_latest"] == expected


def test_cycle_roic_percentage_components_are_decimal(monkeypatch):
    entries = []
    for year, ann, roic in ((2023, "20240320", 0.5), (2024, "20250320", 1.0), (2025, "20260320", -0.5)):
        entry = _rows(year, ann)
        entry["fina_indicator"]["roic"] = roic
        entries.append(entry)
    _install(monkeypatch, _bundle(*entries))
    profile = dict(PROFILE, stock_type="周期股", industry_profile="resources_upstream")
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", profile)
    assert result["1F"]["roic"] == 0.005
    assert result["1F"]["roic_latest"] == -0.005
    assert result["1F"]["roic_normalized_components"] == [-0.005, 0.01, 0.005]


def test_duplicate_period_uses_latest_visible_row_for_every_statement(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    duplicates = _rows(2025, "20260320")
    duplicates["fina_indicator"]["roic"] = 10
    duplicates["cashflow"]["n_cashflow_act"] = 50
    duplicates["balancesheet"]["money_cap"] = 100
    for api in ("income", "fina_indicator", "cashflow", "balancesheet"):
        rows[api].append(duplicates[api])
    _install(monkeypatch, rows)
    composed = []
    real_compose = qi._compose_annual_row
    def capture(*args):
        row = real_compose(*args)
        composed.append(row)
        return row
    monkeypatch.setattr(qi, "_compose_annual_row", capture)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["1F"]["roic"] == 0.12
    assert result["1D"]["liquidity"]["short_cover"] == 5
    assert composed[0]["NETCASH_OPERATE_PK"] == 120


def test_internet_profile_does_not_emit_generic_red_flags(monkeypatch):
    called = []
    monkeypatch.setattr(qi._C, "ts_call", lambda *args, **kwargs: called.append(1) or [])
    profile = {"stock_type": "成长型", "industry_profile": "internet_platform", "growth_tier": "mid"}
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", profile)
    assert result["status"] == "review_only"
    assert set(result["1D"]["red_flags"]) == {"adjusted_profit_divergence", "investment_impairment", "goodwill"}
    assert "receivables" not in result["1D"]["red_flags"]
    assert not called


def test_incomplete_balance_sheet_is_unknown_not_zero_debt(monkeypatch):
    rows = _bundle(_rows(2024, "20250320"), _rows(2025, "20260320"))
    rows["balancesheet"] = [{"total_assets": 1000}]
    _install(monkeypatch, rows)
    result = qi.fetch_quality_inputs("600000", None, "2026-04-01", PROFILE)
    assert result["1D"]["f_items"]["long_debt_down"] is None
    assert result["coverage"]["1D.f_items.long_debt_down"] == "missing"
    assert result["1D"]["liquidity"]["debt_ratio"] is None
    assert result["coverage"]["1D.liquidity.debt_ratio"] == "missing"
