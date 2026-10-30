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


def test_3b_items_shared_weighted_engine():
    items = [{"name": "甲", "stage": "已投产", "contribution": 0.5},
             {"name": "乙", "stage": "在建", "contribution": 0.5}]
    result = qr._eval_3b_items({}, items, "stage", {"已投产": 9, "在建": 7}, 0, True)
    assert result["status"] == "ok"
    assert result["final"] == 8
    assert len(result["rule_steps"]) == 2


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


def _assert_reader_explanation(result, final, base_label, basis_parts, logic_part):
    explanation = result.get("explanation") or {}
    assert result["final"] == final
    assert explanation.get("base_label") == base_label
    basis = explanation.get("basis") or ""
    for part in basis_parts:
        assert part in basis
    assert logic_part in (explanation.get("logic") or "")


@pytest.mark.parametrize("key,spec,final,base_label,basis_parts,logic_part", [
    ("1A", {"stage": "mature", "demand_decline_2y": False, "substitution_low": True,
            "structure_ok": True, "price_mechanism_ok": True, "policy": "neutral"},
     9, "A档代表分", ["需求未连续两年衰退", "替代威胁低", "格局良好", "价格机制正常", "A 档"], "生命周期"),
    ("1B", {"cost_quartile": 1, "upstream_self_supply": 0.6, "price_transmission": True,
            "bargaining_status": "正常", "customer_concentration": 0.1, "supplier_concentration": 0.1},
     9, "A档代表分", ["成本强", "价格可传导", "双强", "A 档"], "集中度"),
    ("1C", _moat_spec(), 9, "A档代表分",
     ["有效护城河 2 条", "≥2 条", "压力测试：警惕", "A 档"], "趋势和压力测试"),
    ("1D", _financial_spec(hits=7), 7, "B档代表分",
     ["通过 7/9 项", "趋势轨 B 档", "流动性轨 A 档", "取较低档为 B 档"], "红旗扣分"),
    ("1E", _return_spec(), 6, "中性起点", ["中性 6 分起"], "清单加减"),
    ("1F", _capital_spec(roic=0.08), 6, "回报覆盖基础分",
     ["年化 ROIC 8.00%", "WACC 8.00%", "覆盖 1.000 倍", "1.0≤覆盖<1.5", "基础分 6"], "增量 ROIC"),
    ("3A", {"growth_lo": 21, "growth_hi": 28, "driver_status": "已验证"},
     9, "A档代表分", ["增速下限 21.0%", ">20%", "驱动已验证", "A 档"], "增速下限"),
    ("3B", {"projects": [{"name": "甲", "stage": "已投产", "contribution": 0.5},
                         {"name": "乙", "stage": "在建", "contribution": 0.5}]},
     8, "项目加权基础分", ["已投产 9 分×50%", "在建 7 分×50%", "加权基础分 8.00"], "利润贡献"),
    ("3C", {"events": [{"name": "季报", "month": "2026-11", "revaluation": True},
                       {"name": "投产", "month": "2026-12", "revaluation": True}]},
     9, "A档代表分", ["明确月份重估事件 2 个", "≥2 个", "A 档"], "12 个月"),
])
def test_reader_explanation_covers_nine_core_dimensions(
        key, spec, final, base_label, basis_parts, logic_part):
    result = qr.evaluate_dimension(key, spec, CTX)
    _assert_reader_explanation(result, final, base_label, basis_parts, logic_part)


@pytest.mark.parametrize("key,spec,context,final,base_label,basis_parts", [
    ("1A", {"stage": "growth", "growth": 16, "tam": 1200, "penetration": 20, "policy": "tailwind"},
     CTX, 9, "A档代表分", ["行业增速 16%", "TAM 1200 亿元", "渗透率 20%", "政策顺风", "A 档"]),
    ("1A", {"stage": "decline"}, CTX, 2, "D档代表分", ["衰退期", "D 档"]),
    ("1B", {"cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1},
     dict(CTX, industry_profile="internet_platform"), 9, "A档代表分", ["成本强、定价强", "两强", "A 档"]),
    ("1D", {"industry_checks": {"solvency": False, "combined_ratio": "not_applicable",
                                "reserve": False, "investment_assumption": False},
            "industry_check_evidence": {"combined_ratio": "纯寿险无财险综合成本率"}},
     dict(CTX, industry_profile="financial_insurance"), 9, "A档代表分",
     ["行业检查通过 3/3 项", "全部适用项通过", "A 档"]),
    ("1D", {"cash_runway_months": 36}, dict(CTX, industry_profile="pre_profit"), 9, "A档代表分",
     ["现金跑道 36.00 个月", "≥24 个月", "A 档"]),
    ("1F", {"normalized_return": 0.12, "coe": 0.08, "return_metric": "ROE_NORMALIZED",
            "dupont_driver": "净利率"},
     dict(CTX, industry_profile="financial_bank"), 9, "A档代表分",
     ["正常化 ROE 12.00%", "COE 8.00%", "覆盖 1.500 倍", "A 档"]),
    ("1F", {"cash_runway_months": 36}, dict(CTX, industry_profile="pre_profit"), 9, "A档代表分",
     ["现金跑道 36.00 个月", "≥24 个月", "A 档"]),
])
def test_reader_explanation_uses_actual_branch_rules(
        key, spec, context, final, base_label, basis_parts):
    result = qr.evaluate_dimension(key, spec, context)
    _assert_reader_explanation(result, final, base_label, basis_parts, "")


@pytest.mark.parametrize("spec,final,base_label,basis_parts", [
    ({"visibility": [{"name": "主业", "level": "合约级", "value": 100, "contribution": 0.8},
                     {"name": "新业务", "level": "纯叙事", "value": None, "contribution": 0.2}]},
     7.6, "可见度加权基础分", ["合约级 9 分×80%", "纯叙事 2 分×20%", "加权基础分 7.60"]),
    ({"projects": [{"name": "在产主矿", "stage": "已投产", "primary": True},
                   {"name": "远期矿", "stage": "规划"}]},
     7.9, "主来源基础分", ["在产主矿", "已投产 9 分", "利润权重缺失或合计不为 1", "证据上限 7.90"]),
    ({"visibility": [{"name": "订单", "level": "合约级", "value": 100},
                     {"name": "产能", "level": "可量化扩张", "value": 50},
                     {"name": "远期期权", "level": "纯叙事", "value": None}],
      "primary_group": ["订单", "产能"]},
     7, "组合主来源基础分", ["组合最弱项", "可量化扩张 7 分", "利润权重缺失或合计不为 1"]),
])
def test_reader_explanation_distinguishes_3b_weighting_and_fallbacks(
        spec, final, base_label, basis_parts):
    result = qr.evaluate_dimension("3B", spec, CTX)
    _assert_reader_explanation(result, final, base_label, basis_parts, "利润贡献")


@pytest.mark.parametrize("spec,context", [
    (_capital_spec(roic=0.16, dupont_driver="杠杆"), CTX),
    ({"normalized_return": 0.12, "coe": 0.08, "return_metric": "ROE_NORMALIZED",
      "dupont_driver": "杠杆"}, dict(CTX, industry_profile="financial_bank")),
])
def test_leverage_cap_is_a_rule_limit_not_an_evidence_gap(spec, context):
    result = qr.evaluate_dimension("1F", spec, context)
    explanation = result.get("explanation") or {}
    assert result["final"] == 7.9
    assert "杠杆主驱动，规则上限 7.90" in explanation.get("cap_note", "")
    assert "证据上限" not in explanation.get("basis", "")


@pytest.mark.parametrize("key,spec", [
    ("1C", _moat_spec(count=1, pressure="unknown")),
    ("1D", _financial_spec(hits=4, red_flags={
        "receivables": False, "inventory": False, "gross_margin_anomaly": None})),
])
def test_inactive_cap_is_not_written_as_a_score_reduction(key, spec):
    result = qr.evaluate_dimension(key, spec, CTX)
    explanation = result.get("explanation") or {}
    assert not explanation.get("cap_note")
    assert "最高 7.9" not in explanation.get("basis", "")


def test_low_return_explains_actual_d_band_boundary():
    result = qr.evaluate_dimension("1F", _capital_spec(roic=0.06, wacc=0.09), CTX)
    basis = result["explanation"]["basis"]
    assert "最高 3.9" in basis
    assert "最高 4" not in basis


def test_primary_fallback_separates_bad_weights_and_missing_numeric_value():
    spec = {"visibility": [{"name": "订单", "level": "合约级", "value": None, "primary": True},
                           {"name": "远期", "level": "纯叙事", "value": None}]}
    result = qr.evaluate_dimension("3B", spec, CTX)
    basis = result["explanation"]["basis"]
    assert "利润权重缺失或合计不为 1" in basis
    assert "缺数值上限 5" in basis and "本次未触及上限" in basis


def test_primary_fallback_mentions_non_unit_weight_total():
    spec = {"projects": [{"name": "甲", "stage": "已投产", "contribution": 0.51, "primary": True},
                         {"name": "乙", "stage": "在建", "contribution": 0.51}]}
    result = qr.evaluate_dimension("3B", spec, CTX)
    assert "利润权重缺失或合计不为 1" in result["explanation"]["basis"]


def test_high_growth_b_band_keeps_a_threshold_in_basis():
    spec = {"growth_lo": 23, "growth_hi": 30, "driver_status": "已验证"}
    result = qr.evaluate_dimension("3A", spec, dict(CTX, growth_tier="high"))
    assert result["band"] == "B"
    assert "A 档阈值 25%" in result["explanation"]["basis"]


@pytest.mark.parametrize("key,spec,context,expected,forbidden", [
    ("1A", {"stage": "decline"}, CTX, "生命周期为衰退期", "行业连续收缩"),
    ("1D", _financial_spec(), CTX, "通过 8—9 项 → A 档", "未通过 0—1 项"),
    ("1C", _moat_spec(), CTX, "无变窄趋势 → A 档", "未因全部变窄降档"),
    ("3B", {"visibility": []}, CTX, "直接落 D 档", "纯叙事"),
    ("3C", {"events": [{"name": "季报验证", "month": "2026-11", "revaluation": False}]}, CTX,
     "未确认重估或月份不可验证", "仅有方向性事件、月份不可验证"),
    ("1B", {"cost_strength": "strong", "pricing_strength": "strong", "bargaining_status": "实质丧失",
            "customer_concentration": 1.0, "supplier_concentration": None},
     dict(CTX, industry_profile="financial_bank"), "客户/供应商集中度 100%/未知", "；两强"),
    ("1B", {"cost_quartile": 2, "price_transmission": False, "bargaining_status": "正常",
            "customer_concentration": 0.1, "supplier_concentration": 0.1}, CTX,
     "上游自给率未获取，按成本曲线分位", None),
    ("1F", {"normalized_return": 0.12, "coe": 0.08, "return_metric": "ROE_NORMALIZED"},
     dict(CTX, industry_profile="financial_bank"), "正常化 ROE 12.00%", "ROE_NORMALIZED 12.00%"),
])
def test_reader_explanation_avoids_branch_misstatements(key, spec, context, expected, forbidden):
    result = qr.evaluate_dimension(key, spec, context)
    explanation = result["explanation"]
    combined = explanation["logic"] + explanation["basis"]
    assert expected in combined
    if forbidden:
        assert forbidden not in combined
