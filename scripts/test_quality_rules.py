#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pytest

import quality_rules as qr


CTX = {"stock_type": "成长型", "growth_tier": "mid", "industry_profile": "generic",
       "report_date": "2026-10-24"}


def _custom(points=0, reason="测试理由", evidence="测试证据"):
    return {"id": "CUSTOM.TEST", "points": points, "reason": reason, "evidence": evidence}


def _moat(trend="stable", verified=True, rhetoric=False):
    return {"verified": verified, "rhetoric": rhetoric, "type": "cost",
            "replication": "对手需多年和大量资本", "evidence": "公开经营数据", "trend": trend}


def _moat_spec(count=2, trend="stable", pressure="警惕", custom=None):
    return {"moats": [_moat(trend=trend) for _ in range(count)], "pressure": pressure,
            "custom": custom or _custom()}


def _financial_spec(hits=9, cash=True, liquidity=None, red_flags=None, custom=None):
    names = ["profit_positive", "ocf_positive", "roa_improving", "cash_quality_ok",
             "long_debt_down", "short_cover_improving", "no_dilution",
             "gross_margin_improving", "asset_turnover_improving"]
    facts = {name: i < hits for i, name in enumerate(names)}
    facts["cash_quality_ok"] = cash
    return {"f_items": facts,
            "liquidity": liquidity or {"debt_ratio": 0.2, "short_cover": 2.0},
            "red_flags": (red_flags if red_flags is not None else
                          {"receivables": False, "inventory": False, "gross_margin_anomaly": False}),
            "custom": custom or _custom()}


def _return_spec(dividend=None, buyback=None, long_record=None, custom=None):
    return {"pledge_pct": 0, "reduction_pct": 0, "age": 60, "penalties": 0,
            "dividend": dividend, "buyback": buyback, "long_record": long_record,
            "custom": custom or _custom()}


def _capital_spec(roic=0.12, wacc=0.08, incremental=None, dupont_driver="净利率", custom=None):
    return {"roic": roic, "wacc": wacc, "incremental_roic": incremental,
            "roic_basis": "latest", "roic_period_months": 12,
            "dupont_driver": dupont_driver, "custom": custom or _custom()}


def test_stable_wide_moat_can_score_A():
    result = qr.evaluate_dimension("1C", _moat_spec(), CTX)
    assert result["status"] == "ok"
    assert result["band"] == "A"
    assert result["base"] == 9
    assert result["final"] == 9


def test_narrowing_moat_falls_to_C():
    result = qr.evaluate_dimension("1C", _moat_spec(trend="narrowing"), CTX)
    assert result["band"] == "C"
    assert result["final"] == 5


def test_unknown_moat_trend_is_capped_at_b():
    spec = _moat_spec(count=2)
    for moat in spec["moats"]:
        moat["trend"] = "unknown"
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7.9
    assert result["cap"] == 7.9


def test_mixed_moat_trends_are_capped_at_B_not_C():
    spec = _moat_spec(count=3)
    spec["moats"][0]["trend"] = "widening"
    spec["moats"][1]["trend"] = "widening"
    spec["moats"][2]["trend"] = "narrowing"
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7
    assert result["cap"] == 7.9


def test_moat_pressure_and_rhetoric_caps():
    pressured = _moat_spec(pressure="扛不住", custom=_custom(1))
    assert qr.evaluate_dimension("1C", pressured, CTX)["final"] == 7.9
    rhetoric = _moat_spec(custom=_custom(1))
    for moat in rhetoric["moats"]:
        moat["rhetoric"] = True
    assert qr.evaluate_dimension("1C", rhetoric, CTX)["final"] == 5.9


def test_mature_low_growth_alone_not_D():
    spec = {"stage": "mature", "growth": 2, "demand_decline_2y": False,
            "substitution_low": True, "structure_ok": True, "price_mechanism_ok": True,
            "policy": "neutral", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["band"] == "A"
    assert result["final"] == 9


def test_mature_demand_decline_is_D():
    spec = {"stage": "mature", "growth": 2, "demand_decline_2y": True,
            "substitution_low": False, "structure_ok": False, "price_mechanism_ok": False,
            "policy": "neutral", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["band"] == "D"
    assert result["final"] == 2


def test_growth_industry_uses_existing_thresholds():
    spec = {"stage": "growth", "growth": 16, "tam": 1200, "penetration": 20,
            "policy": "tailwind", "custom": _custom()}
    assert qr.evaluate_dimension("1A", spec, CTX)["final"] == 9


def test_growth_industry_missing_values_do_not_render_none():
    spec = {"stage": "growth", "growth": 16, "tam": None, "penetration": None,
            "policy": "tailwind"}
    result = qr.evaluate_dimension("1A", spec, CTX)
    evidence = result["rule_steps"][0]["evidence"]
    assert "None" not in evidence and evidence.count("未获取") == 2


def test_custom_cannot_cross_band_or_cap():
    result = qr.evaluate_dimension("1C", _moat_spec(count=1, custom=_custom(1)), CTX)
    assert result["band"] == "B"
    assert result["final"] == 7.9
    with pytest.raises(ValueError, match="±1"):
        qr.evaluate_dimension("1C", _moat_spec(custom=_custom(1.1)), CTX)


def test_custom_id_and_reason_enter_rule_steps():
    custom = _custom(-0.5, "清单外新风险", "公告与数据")
    result = qr.evaluate_dimension("1C", _moat_spec(custom=custom), CTX)
    assert result["final"] == 8.5
    assert result["rule_steps"][-1]["id"] == "CUSTOM.TEST"
    assert result["rule_steps"][-1]["evidence"] == "公告与数据"


def test_pre_cap_preserves_band_clamp_before_evidence_cap():
    steps = [{"id": "1C.PRESSURE.UNKNOWN", "evidence": "压力测试未知", "delta": 0}]
    result = qr._finish("1C", (0, 5.9), 5, steps, {"custom": _custom(1)}, cap=5.9)
    assert result["pre_cap"] == 5.9
    assert result["final"] == 5.9


def test_cash_quality_has_single_effect():
    cash_ok = qr.evaluate_dimension("1D", _financial_spec(hits=8, cash=True), CTX)
    cash_bad = qr.evaluate_dimension("1D", _financial_spec(hits=8, cash=False), CTX)
    assert cash_ok["band"] == "A"
    assert cash_bad["band"] == "B"
    assert cash_ok["final"] - cash_bad["final"] == 2
    assert sum(step.get("id") == "1D.CASH_QUALITY" for step in cash_bad["rule_steps"]) == 1
    with pytest.raises(ValueError, match="现金含量"):
        qr.evaluate_dimension("1D", _financial_spec(red_flags={"cash_quality": True}), CTX)


def test_fixed_red_flags_can_cross_band_then_custom_is_clamped():
    spec = _financial_spec(red_flags={"receivables": True, "inventory": True}, custom=_custom(1))
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["base"] == 9
    assert result["final"] == 7.9
    assert result["band"] == "B"


def test_immaterial_inventory_red_flag_requires_evidence():
    spec = _financial_spec(red_flags={"receivables": False, "inventory": True, "gross_margin_anomaly": False})
    spec["red_flag_materiality"] = {"inventory": False}
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["final"] == 8
    assert any(step["id"] == "1D.RED.INVENTORY" and step["delta"] == -1 for step in result["rule_steps"])


def test_immaterial_inventory_red_flag_with_evidence_is_not_deducted():
    spec = _financial_spec(red_flags={"receivables": False, "inventory": True, "gross_margin_anomaly": False})
    spec["red_flag_materiality"] = {"inventory": False}
    spec["red_flag_materiality_evidence"] = {"inventory": {
        "scale": "检修备件约占总资产0.1%", "source": "公司2025年报及原文红旗核查"}}
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["final"] == 9
    step = next(step for step in result["rule_steps"] if step["id"] == "1D.RED.INVENTORY.IMMATERIAL")
    assert step["delta"] == 0 and "0.1%" in step["evidence"]


def test_missing_red_flags_are_not_pass():
    spec = _financial_spec()
    del spec["red_flags"]
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["status"] == "missing"
    spec = _financial_spec(red_flags={"receivables": False, "inventory": False, "gross_margin_anomaly": False})
    del spec["red_flags"]["receivables"]
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["status"] == "missing"


def test_string_false_is_not_boolean_evidence():
    spec = {"stage": "mature", "growth": 2, "demand_decline_2y": "false",
            "substitution_low": True, "structure_ok": True, "price_mechanism_ok": True, "policy": "neutral"}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["status"] == "missing"
    spec = _moat_spec()
    spec["moats"][0]["verified"] = "false"
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["status"] == "missing"


def test_growth_g_checks_are_evidence_not_another_score():
    base = qr.evaluate_dimension("1D", _financial_spec(), CTX)
    spec = _financial_spec()
    spec["g_checks"] = {"rd_intensity_evidence": "研发投入占收入8%",
                        "capex_intensity_evidence": "资本开支占经营现金流40%"}
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["final"] == base["final"]
    steps = [step for step in result["rule_steps"] if step["id"].startswith("1D.G.")]
    assert len(steps) == 10
    assert all(step["delta"] == 0 for step in steps)
    assert "研发投入占收入8%" in steps[-2]["evidence"]
    assert "资本开支占经营现金流40%" in steps[-1]["evidence"]
    assert "g_score" not in result


def test_asset_turnover_only_changes_1d_once():
    base = qr.evaluate_dimension("1D", _financial_spec(hits=7), CTX)
    spec = _financial_spec(hits=7)
    spec["f_items"]["asset_turnover_improving"] = True
    better = qr.evaluate_dimension("1D", spec, CTX)
    assert better["final"] - base["final"] == 2
    assert sum(step["id"] == "1D.ASSET_TURNOVER_IMPROVING" for step in better["rule_steps"]) == 1
    assert qr.evaluate_dimension("1F", _capital_spec(), CTX)["final"] == 9


def test_f_items_in_one_causal_group_are_counted_once():
    spec = _financial_spec(hits=3, cash=False)
    spec["f_causal_groups"] = {"asset_injection": ["long_debt_down", "no_dilution"]}
    spec["f_causal_evidence"] = {"asset_injection": "同一资产注入同时带来承接债务与增发"
    }
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["final"] == 5
    step = next(step for step in result["rule_steps"] if step["id"] == "1D.F.HITS")
    assert "原始3/9" in step["evidence"]
    assert "归并后4/9" in step["evidence"]


def test_absolute_liquidity_uses_lower_band():
    spec = _financial_spec(liquidity={"debt_ratio": 0.6, "short_cover": 1.2})
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["band"] == "C"
    assert result["final"] == 5


def test_ocf_short_debt_exemption_raises_liquidity_one_band():
    spec = _financial_spec(liquidity={"debt_ratio": 0.6, "short_cover": 0.8,
                                      "ocf_short_cover": 2.1})
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7
    assert any(step["id"] == "1D.LIQUIDITY.OCF_EXEMPTION" for step in result["rule_steps"])


@pytest.mark.parametrize("liquidity,expected", [
    ({"debt_ratio": 0.6, "short_cover": 0.8, "ocf_short_cover": 2.0}, "C"),
    ({"debt_ratio": 0.2, "short_cover": 1.0, "ocf_short_cover": 3.0}, "B"),
    ({"debt_ratio": 0.6, "short_cover": 0.8, "ocf_short_cover": None}, "C"),
])
def test_ocf_short_debt_exemption_requires_strict_thresholds(liquidity, expected):
    result = qr.evaluate_dimension("1D", _financial_spec(liquidity=liquidity), CTX)
    assert result["band"] == expected
    assert not any(step["id"] == "1D.LIQUIDITY.OCF_EXEMPTION" for step in result["rule_steps"])


def test_dividend_only_changes_1E():
    dividend = {"payout_streak": 4, "fcf_covered": True}
    base = qr.evaluate_dimension("1E", _return_spec(), CTX)
    with_dividend = qr.evaluate_dimension("1E", _return_spec(dividend=dividend), CTX)
    assert with_dividend["final"] - base["final"] == 0.5
    capital_base = qr.evaluate_dimension("1F", _capital_spec(), CTX)
    capital = dict(_capital_spec(), dividend=dividend, buyback={"cancel": True})
    assert qr.evaluate_dimension("1F", capital, CTX)["final"] == capital_base["final"]


def test_incremental_roic_only_changes_1F():
    financial = _financial_spec()
    financial["incremental_roic"] = 0.04
    assert qr.evaluate_dimension("1D", financial, CTX)["final"] == 9
    positive = qr.evaluate_dimension("1F", _capital_spec(incremental=0.13), CTX)
    negative = qr.evaluate_dimension("1F", _capital_spec(incremental=0.04), CTX)
    assert positive["final"] == 10
    assert negative["final"] == 8


def test_roic_middle_and_leverage_cap():
    middle = qr.evaluate_dimension("1F", _capital_spec(roic=0.08), CTX)
    assert middle["base"] == 6
    assert middle["final"] == 6
    leveraged = qr.evaluate_dimension("1F", _capital_spec(roic=0.16, dupont_driver="杠杆"), CTX)
    assert leveraged["final"] == 7.9


def test_project_score_weights_profit_not_count():
    spec = {"projects": [{"name": "已投产", "stage": "已投产", "contribution": 0.8},
                         {"name": "规划中", "stage": "规划", "contribution": 0.2}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["base"] == pytest.approx(7.6)
    assert result["final"] == pytest.approx(7.6)


def test_no_project_visibility_requires_numbers_for_high_score():
    spec = {"visibility": [{"name": "会员", "level": "可量化扩张", "value": None,
                            "evidence": "只有叙事"}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["final"] <= 5


def test_growth_score_uses_verified_drivers_and_type_threshold():
    spec = {"growth_lo": 21, "growth_hi": 28, "driver_status": "已验证", "custom": _custom()}
    assert qr.evaluate_dimension("3A", spec, CTX)["final"] == 9
    high = dict(CTX, growth_tier="high")
    assert qr.evaluate_dimension("3A", spec, high)["band"] == "B"


def test_catalyst_requires_month():
    one = {"events": [{"name": "季报", "month": "2026-11", "revaluation": True}], "custom": _custom()}
    assert qr.evaluate_dimension("3C", one, CTX)["final"] == 7
    no_month = {"events": [{"name": "季报", "month": None, "revaluation": True},
                           {"name": "投产", "month": None, "revaluation": True}], "custom": _custom()}
    assert qr.evaluate_dimension("3C", no_month, CTX)["final"] == 5


def test_missing_input_is_not_neutral_score():
    result = qr.evaluate_dimension("1A", {"custom": _custom()}, CTX)
    assert result["status"] == "missing"
    assert result["final"] is None
    assert result["final"] != 5


def test_missing_dimension_never_reweights_total():
    result = qr.evaluate_dimensions({"1A": {"stage": "mature", "growth": 2,
                                             "demand_decline_2y": False,
                                             "substitution_low": True, "structure_ok": True,
                                             "price_mechanism_ok": True, "policy": "neutral"}}, CTX)
    assert result["complete"] is False
    assert result["quality"] is None
    assert result["dimensions"]["1D"]["status"] == "missing"


def test_rule_registry_covers_industry_profiles():
    expected = {"generic", "financial_bank", "financial_insurance", "financial_broker",
                "pharma_pipeline", "pharma_device", "pharma_cxo", "realestate_development",
                "internet_platform", "resources_upstream", "pre_profit", "turnaround"}
    assert expected <= set(qr.RULE_REGISTRY["profiles"])
    for profile in expected:
        assert qr.RULE_REGISTRY["profiles"][profile]["1D"]["kind"] != "generic_f" \
            if profile in {"financial_bank", "financial_insurance", "financial_broker",
                           "pharma_pipeline", "pre_profit", "turnaround"} else True


def test_rule_steps_have_stable_ids_and_evidence():
    result = qr.evaluate_dimension("1C", _moat_spec(), CTX)
    assert result["rule_steps"]
    assert all(step.get("id") and "evidence" in step for step in result["rule_steps"])


def test_small_profile_checklist_scales_by_item_count():
    context = dict(CTX, industry_profile="pre_profit")
    spec = {"industry_checks": {"cash_runway": False, "financing_gap": False}}
    result = qr.evaluate_dimension("1D", spec, context)
    assert result["band"] == "A"
    assert result["final"] == 9


def test_not_applicable_industry_check_is_excluded():
    context = dict(CTX, industry_profile="financial_insurance")
    spec = {"industry_checks": {"solvency": False, "combined_ratio": "not_applicable",
                                "reserve": False, "investment_assumption": False},
            "industry_check_evidence": {"combined_ratio": "纯寿险无财险综合成本率"}, "custom": _custom()}
    result = qr.evaluate_dimension("1D", spec, context)
    assert result["status"] == "ok"
    assert result["final"] == 9
    assert any(step["id"] == "1D.NOT_APPLICABLE" for step in result["rule_steps"])


def test_catalyst_ignores_events_beyond_12_months():
    spec = {"events": [{"name": "近期季报", "month": "2026-11", "revaluation": True},
                       {"name": "远期事件", "month": "2027-12", "revaluation": True}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3C", spec, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7


def test_empty_visibility_returns_low_not_crash():
    result = qr.evaluate_dimension("3B", {"visibility": [], "custom": _custom()}, CTX)
    assert result["band"] == "D"
    assert result["final"] == 2


def test_red_flag_unknown_is_missing_not_pass():
    result = qr.evaluate_dimension("1D", _financial_spec(red_flags={"receivables": None}), CTX)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_missing_concentration_is_capped_not_unscorable():
    spec = {"cost_quartile": 1, "upstream_self_supply": 0.6, "price_transmission": True,
            "bargaining_status": "正常", "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, CTX)
    assert result["status"] == "ok"
    assert result["band"] == "B"
    assert result["final"] <= 7.9
    assert any(step["id"] == "1B.CONCENTRATION.UNKNOWN" for step in result["rule_steps"])


def test_missing_age_is_warning_not_missing():
    spec = _return_spec()
    spec["age"] = None
    result = qr.evaluate_dimension("1E", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 6
    assert any(step["id"] == "1E.AGE.UNKNOWN" for step in result["rule_steps"])


def test_missing_self_supply_does_not_block_cost_quartile():
    spec = {"cost_quartile": 1, "price_transmission": False, "bargaining_status": "正常",
            "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, CTX)
    assert result["status"] == "ok"
    assert result["band"] == "B"
    assert result["final"] == 7
    assert any(step["id"] == "1B.SELF_SUPPLY.UNKNOWN" for step in result["rule_steps"])


def test_roic_inputs_must_use_decimal_units():
    with pytest.raises(ValueError, match="小数"):
        qr.evaluate_dimension("1F", _capital_spec(roic=18.3862, wacc=8, incremental=0.1), CTX)


def test_bool_long_record_is_missing_not_crash():
    spec = _return_spec(long_record=True)
    result = qr.evaluate_dimension("1E", spec, CTX)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_composite_custom_items_are_summed_and_traced():
    custom = [{"id": "CUSTOM.A", "points": -0.5, "reason": "负向事项", "evidence": "证据A"},
              {"id": "CUSTOM.B", "points": 0.5, "reason": "正向事项", "evidence": "证据B"}]
    result = qr.evaluate_dimension("1C", _moat_spec(custom=custom), CTX)
    assert result["final"] == 9
    ids = {step["id"] for step in result["rule_steps"]}
    assert {"CUSTOM.A", "CUSTOM.B"} <= ids
    too_large = [{"id": "CUSTOM.A", "points": 1, "reason": "事项A", "evidence": "证据A"},
                 {"id": "CUSTOM.B", "points": 0.5, "reason": "事项B", "evidence": "证据B"}]
    with pytest.raises(ValueError, match="±1"):
        qr.evaluate_dimension("1C", _moat_spec(custom=too_large), CTX)


def test_missing_pressure_is_capped_not_unscorable():
    spec = _moat_spec()
    spec.pop("pressure")
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["status"] == "ok"
    assert result["band"] == "B"
    assert result["final"] <= 7.9
    assert any(step["id"] == "1C.PRESSURE.UNKNOWN" for step in result["rule_steps"])


def test_unknown_pressure_is_capped_not_unscorable():
    result = qr.evaluate_dimension("1C", _moat_spec(pressure="unknown"), CTX)
    assert result["status"] == "ok"
    assert result["final"] <= 7.9
    assert any(step["id"] == "1C.PRESSURE.UNKNOWN" for step in result["rule_steps"])


def test_gross_margin_unknown_is_capped_not_unscorable():
    spec = _financial_spec(red_flags={"receivables": False, "inventory": False,
                                     "gross_margin_anomaly": None}, custom=_custom(1))
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["status"] == "ok"
    assert result["band"] == "B"
    assert result["final"] <= 7.9
    assert any(step["id"] == "1D.GROSS_MARGIN_PEER.UNKNOWN" for step in result["rule_steps"])


def test_string_numbers_are_normalized():
    growth = {"growth_lo": "15-30%", "growth_hi": "30%", "driver_status": "部分兑现", "custom": _custom()}
    result = qr.evaluate_dimension("3A", growth, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7
    industry = {"stage": "growth", "growth": "16%", "tam": "1,200亿", "penetration": "20%",
                "policy": "tailwind", "custom": _custom()}
    assert qr.evaluate_dimension("1A", industry, CTX)["final"] == 9
    governance = _return_spec(custom=_custom("-0.5"))
    governance["pledge_pct"] = "71%"
    assert qr.evaluate_dimension("1E", governance, CTX)["final"] == 4.5


def test_roic_percent_strings_are_decimals():
    result = qr.evaluate_dimension("1F", _capital_spec(roic="18.4%", wacc="8%", incremental="10%"), CTX)
    assert result["final"] == 9
    assert result["rule_steps"][0]["evidence"].startswith("覆盖2.300")


def test_dividend_streak_null_is_zero_not_typeerror():
    spec = _return_spec(dividend={"payout_streak": None, "growth_streak": None, "fcf_covered": True})
    result = qr.evaluate_dimension("1E", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 6


def test_payout_anchor_does_not_require_fcf_field():
    spec = _return_spec(dividend={"payout_streak": 3, "growth_streak": None, "fcf_covered": None})
    result = qr.evaluate_dimension("1E", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 6.5
    assert sum(step["id"] == "1E.DIVIDEND" for step in result["rule_steps"]) == 1


def test_interim_roic_is_annualized_before_wacc_comparison():
    spec = _capital_spec(roic=0.09)
    spec["roic_period_months"] = 6
    result = qr.evaluate_dimension("1F", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 9
    assert result["rule_steps"][0]["evidence"].startswith("覆盖2.250")


def test_cyclical_roic_requires_normalized_basis():
    spec = _capital_spec(roic=0.18)
    spec["roic_basis"] = "latest"
    context = dict(CTX, stock_type="周期股")
    result = qr.evaluate_dimension("1F", spec, context)
    assert result["status"] == "missing"
    spec["roic_basis"] = "normalized"
    spec["roic_normalized_components"] = [0.16, 0.18, 0.20]
    assert qr.evaluate_dimension("1F", spec, context)["status"] == "ok"


def test_financial_return_uses_normalized_return_and_coe():
    context = dict(CTX, stock_type="稳定价值/金融", industry_profile="financial_bank")
    spec = {"normalized_return": 0.12, "coe": 0.08, "return_metric": "ROE_NORMALIZED",
            "dupont_driver": "杠杆", "custom": _custom()}
    result = qr.evaluate_dimension("1F", spec, context)
    assert result["status"] == "ok"
    assert result["final"] == 7.9
    assert "ROE_NORMALIZED" in result["rule_steps"][0]["evidence"]


def test_financial_return_rejects_wacc_substitution():
    context = dict(CTX, stock_type="稳定价值/金融", industry_profile="financial_bank")
    result = qr.evaluate_dimension("1F", _capital_spec(roic=0.12, wacc=0.08), context)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_visibility_requires_profit_contribution_weights():
    spec = {"visibility": [{"name": "主业", "level": "可量化扩张", "value": 100},
                           {"name": "新业务", "level": "纯叙事", "value": None}], "custom": _custom()}
    with pytest.raises(ValueError, match="权重之和必须为1"):
        qr.evaluate_dimension("3B", spec, CTX)


def test_visibility_score_weights_profit_not_count():
    spec = {"visibility": [{"name": "主业", "level": "合约级", "value": 100, "contribution": 0.8},
                           {"name": "新业务", "level": "纯叙事", "value": None, "contribution": 0.2}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["base"] == pytest.approx(7.6)
    assert result["final"] == pytest.approx(7.6)


def test_non_narrative_visibility_requires_numeric_evidence():
    spec = {"visibility": [{"name": "平稳业务", "level": "趋势平缓", "value": None, "contribution": 1}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["final"] == 2
    assert result["cap"] == 5


def test_aggregate_records_invalid_dimension_without_masking_others():
    specs = {"1A": {"stage": "decline"},
             "3B": {"visibility": [{"name": "主业", "level": "可量化扩张", "value": 100},
                                    {"name": "新业务", "level": "纯叙事", "value": None}]}}
    result = qr.evaluate_dimensions(specs, CTX)
    assert result["complete"] is False
    assert result["quality"] is None
    assert result["dimensions"]["1A"]["status"] == "ok"
    assert result["dimensions"]["3B"]["status"] == "missing"
    assert "权重之和必须为1" in result["dimensions"]["3B"]["missing_reason"]


def test_project_primary_fallback_is_capped_without_weights():
    spec = {"projects": [{"name": "在产主矿", "stage": "已投产", "primary": True},
                         {"name": "远期矿", "stage": "规划"}], "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["base"] == 9
    assert result["final"] == 7.9
    assert result["cap"] == 7.9
    assert any(step["id"] == "3B.PRIMARY_FALLBACK" for step in result["rule_steps"])


def test_visibility_primary_fallback_does_not_count_optional_items():
    spec = {"visibility": [{"name": "主业", "level": "可量化扩张", "value": 100, "primary": True},
                           {"name": "远期业务", "level": "纯叙事", "value": None}], "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["final"] == 7
    assert result["cap"] == 7.9
    assert any(step["id"] == "3B.PRIMARY_FALLBACK" for step in result["rule_steps"])


def test_primary_fallback_requires_exactly_one_primary():
    spec = {"visibility": [{"name": "主业A", "level": "可量化扩张", "value": 100, "primary": True},
                           {"name": "主业B", "level": "合约级", "value": 80, "primary": True}],
            "custom": _custom()}
    with pytest.raises(ValueError, match="唯一利润主来源"):
        qr.evaluate_dimension("3B", spec, CTX)


def test_primary_fallback_still_requires_numeric_evidence():
    spec = {"visibility": [{"name": "平稳主业", "level": "趋势平缓", "value": None, "primary": True},
                           {"name": "远期业务", "level": "纯叙事", "value": None}], "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["final"] == 2
    assert result["cap"] == 5


def test_policy_aliases_and_mixed_policy_do_not_inflate_growth():
    spec = {"stage": "growth", "growth": 16, "tam": 1200, "penetration": 20,
            "policy": "positive", "custom": _custom()}
    assert qr.evaluate_dimension("1A", spec, CTX)["final"] == 9
    spec["policy"] = "mixed"
    assert qr.evaluate_dimension("1A", spec, CTX)["final"] == 5
    spec["policy"] = "未登记口径"
    assert qr.evaluate_dimension("1A", spec, CTX)["status"] == "missing"


def test_mature_mixed_policy_cannot_score_A():
    spec = {"stage": "mature", "growth": 2, "demand_decline_2y": False,
            "substitution_low": True, "structure_ok": True, "price_mechanism_ok": True,
            "policy": "mixed", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["band"] == "B"
    assert result["final"] == 7


def test_unknown_growth_driver_is_missing():
    spec = {"growth_lo": 15, "growth_hi": 20, "driver_status": "订单多重锁定", "custom": _custom()}
    result = qr.evaluate_dimension("3A", spec, CTX)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_negative_growth_is_D_even_when_driver_unverified():
    spec = {"growth_lo": -5, "growth_hi": -1, "driver_status": "未验证", "custom": _custom()}
    result = qr.evaluate_dimension("3A", spec, CTX)
    assert result["band"] == "D"
    assert result["final"] == 2


def test_policy_headwind_is_not_automatically_suppression():
    spec = {"stage": "growth", "growth": 16, "tam": 1200, "penetration": 20,
            "policy": "negative", "custom": _custom()}
    assert qr.evaluate_dimension("1A", spec, CTX)["final"] == 5
    spec["policy"] = "suppressed"
    assert qr.evaluate_dimension("1A", spec, CTX)["final"] == 2


def test_unknown_lifecycle_stage_is_missing():
    spec = {"stage": "mixed", "growth": 16, "tam": 1200, "penetration": 20,
            "policy": "neutral", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_high_growth_tier_chinese_alias_uses_25_percent_threshold():
    spec = {"growth_lo": 22, "growth_hi": 30, "driver_status": "已验证", "custom": _custom()}
    result = qr.evaluate_dimension("3A", spec, dict(CTX, growth_tier="高速层"))
    assert result["band"] == "B"
    assert result["final"] == 7


def test_growth_missing_tam_penetration_is_capped_not_unscorable():
    spec = {"stage": "growth", "growth": 10, "policy": "neutral", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 7
    assert result["cap"] == 7.9
    assert any(step["id"] == "1A.TOP_EVIDENCE.UNKNOWN" for step in result["rule_steps"])


def test_mature_substitution_unknown_is_capped_not_unscorable():
    spec = {"stage": "mature", "growth": 2, "demand_decline_2y": False,
            "substitution_low": None, "structure_ok": True, "price_mechanism_ok": True,
            "policy": "neutral", "custom": _custom()}
    result = qr.evaluate_dimension("1A", spec, CTX)
    assert result["status"] == "ok"
    assert result["final"] == 7
    assert result["cap"] == 7.9


def test_insurance_uses_industry_strength_axes():
    context = dict(CTX, industry_profile="financial_insurance")
    spec = {"cost_strength": "neutral", "pricing_strength": "strong", "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1, "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, context)
    assert result["band"] == "B"
    assert result["final"] == 7


def test_internet_two_strong_axes_can_score_A():
    context = dict(CTX, industry_profile="internet_platform")
    spec = {"cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1, "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, context)
    assert result["band"] == "A"
    assert result["final"] == 9


def test_industry_no_strong_axis_is_C():
    context = dict(CTX, industry_profile="financial_bank")
    spec = {"cost_strength": "weak", "pricing_strength": "neutral", "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1, "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, context)
    assert result["band"] == "C"
    assert result["final"] == 5


def test_industry_strength_rejects_unregistered_label():
    context = dict(CTX, industry_profile="financial_bank")
    spec = {"cost_quartile": 1, "price_transmission": True, "cost_strength": "行业领先",
            "pricing_strength": "strong", "bargaining_status": "正常", "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, context)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_primary_group_uses_weakest_core_item_only():
    spec = {"visibility": [{"name": "订单", "level": "合约级", "value": 100},
                           {"name": "产能", "level": "可量化扩张", "value": 50},
                           {"name": "远期期权", "level": "纯叙事", "value": None}],
            "primary_group": ["订单", "产能"], "custom": _custom()}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert result["final"] == 7
    assert result["cap"] == 7.9
    assert any(step["id"] == "3B.PRIMARY_GROUP" for step in result["rule_steps"])


def test_normalized_roic_requires_three_components_and_matching_median():
    spec = _capital_spec(roic=0.18)
    spec["roic_basis"] = "normalized"
    result = qr.evaluate_dimension("1F", spec, dict(CTX, stock_type="周期股"))
    assert result["status"] == "missing"
    spec["roic_normalized_components"] = [0.16, 0.18, 0.20]
    assert qr.evaluate_dimension("1F", spec, dict(CTX, stock_type="周期股"))["status"] == "ok"
    spec["roic"] = 0.17
    assert qr.evaluate_dimension("1F", spec, dict(CTX, stock_type="周期股"))["status"] == "missing"


def test_generic_cash_runway_does_not_replace_roic():
    result = qr.evaluate_dimension("1F", {"cash_runway_months": 36, "custom": _custom()}, CTX)
    assert result["status"] == "missing"
    assert result["final"] is None


def test_latest_roic_requires_explicit_period():
    spec = _capital_spec(roic=0.16)
    spec["roic_basis"] = "latest"
    del spec["roic_period_months"]
    result = qr.evaluate_dimension("1F", spec, CTX)
    assert result["status"] == "missing"


def test_f_causal_group_requires_evidence():
    spec = _financial_spec(hits=0)
    spec["f_causal_groups"] = {"all_items": list(__import__("quality_rules").F_ITEM_IDS)}
    with pytest.raises(ValueError, match="证据"):
        qr.evaluate_dimension("1D", spec, CTX)


def test_not_applicable_requires_item_evidence():
    context = dict(CTX, industry_profile="financial_insurance")
    spec = {"industry_checks": {"solvency": False, "combined_ratio": "not_applicable",
                                "reserve": False, "investment_assumption": False}, "custom": _custom()}
    result = qr.evaluate_dimension("1D", spec, context)
    assert result["status"] == "missing"


@pytest.mark.parametrize("evidence", [
    "规模很小",
    {"scale": "规模很小", "source": "公司年报"},
    {"scale": "约占总资产0.1%"},
])
def test_materiality_requires_numeric_scale_and_source(evidence):
    spec = _financial_spec(red_flags={"receivables": False, "inventory": True,
                                      "gross_margin_anomaly": False})
    spec["red_flag_materiality"] = {"inventory": False}
    spec["red_flag_materiality_evidence"] = {"inventory": evidence}
    result = qr.evaluate_dimension("1D", spec, CTX)
    assert result["final"] == 8


def test_moat_rejects_unregistered_trend():
    spec = _moat_spec(trend="UNKNOWN")
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["status"] == "missing"


def test_moat_rejects_invalid_pressure():
    result = qr.evaluate_dimension("1C", _moat_spec(pressure="未知"), CTX)
    assert result["status"] == "missing"


def test_moat_requires_replication_and_evidence():
    spec = _moat_spec()
    spec["moats"][0]["evidence"] = ""
    result = qr.evaluate_dimension("1C", spec, CTX)
    assert result["status"] == "missing"


@pytest.mark.parametrize("month", ["2027-12", "2025-12", "not-a-date"])
def test_only_out_of_window_catalysts_are_D(month):
    spec = {"events": [{"name": "唯一事件", "month": month, "revaluation": True}], "custom": _custom()}
    result = qr.evaluate_dimension("3C", spec, CTX)
    assert result["band"] == "D"
    assert result["final"] == 2


@pytest.mark.parametrize("key", ["projects", "visibility"])
def test_negative_contribution_is_rejected(key):
    if key == "projects":
        items = [{"name": "甲", "stage": "已投产", "contribution": 2},
                 {"name": "乙", "stage": "规划", "contribution": -1}]
    else:
        items = [{"name": "甲", "level": "合约级", "value": 100, "contribution": 2},
                 {"name": "乙", "level": "纯叙事", "value": None, "contribution": -1}]
    result = qr.evaluate_dimension("3B", {key: items, "custom": _custom()}, CTX)
    assert result["status"] == "missing"


@pytest.mark.parametrize("profile", ["generic", "financial_bank"])
def test_single_sided_concentration_is_D(profile):
    spec = {"cost_quartile": 1, "price_transmission": True, "bargaining_status": "实质丧失",
            "cost_strength": "strong", "pricing_strength": "strong",
            "customer_concentration": 1.0, "supplier_concentration": None, "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, dict(CTX, industry_profile=profile))
    assert result["band"] == "D"
    assert result["final"] == 2


def test_price_transmission_must_be_boolean():
    spec = {"cost_quartile": 1, "price_transmission": "false", "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1, "custom": _custom()}
    result = qr.evaluate_dimension("1B", spec, CTX)
    assert result["status"] == "missing"


def test_verification_event_within_window_is_direction():
    spec = {"events": [{"name": "季报验证", "month": "2026-11", "revaluation": False}],
            "custom": _custom()}
    result = qr.evaluate_dimension("3C", spec, CTX)
    assert result["band"] == "C"
    assert result["final"] == 5


def test_none_moat_trend_is_unknown_not_invalid():
    result = qr.evaluate_dimension("1C", _moat_spec(trend=None), CTX)
    assert result["status"] == "ok"
    assert result["final"] == 7.9
    assert result["cap"] == 7.9
