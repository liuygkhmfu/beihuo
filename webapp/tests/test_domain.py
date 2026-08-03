from datetime import date

import pytest

from webapp.domain import (
    DEFAULT_SCHEDULE,
    DEFAULT_SETTINGS,
    build_channel_plans,
    build_forecast,
    build_summary,
    calculate_recommendation,
    dynamic_daily_sales,
    recalculate_scenario_plan,
    schedule_context,
)


def product(**overrides):
    value = {
        "product_name": "测试商品",
        "msku": "TEST-001",
        "store_id": "STORE-1",
        "store_name": "测试店铺",
        "avg_7": 10,
        "avg_14": 8,
        "avg_30": 6,
        "fbt_total": 100,
        "fbt_sellable": 80,
        "fbt_in_transit": 50,
    }
    value.update(overrides)
    return value


def settings(**overrides):
    value = DEFAULT_SETTINGS.copy()
    value.update(overrides)
    return value


def test_dynamic_daily_sales_uses_50_30_20_weights():
    assert dynamic_daily_sales(product(), DEFAULT_SETTINGS) == pytest.approx(8.6)


def test_midweek_run_uses_the_next_monday_for_shipping():
    context = schedule_context(DEFAULT_SCHEDULE, date(2026, 7, 28))
    assert context["current"]["week_date"] == "2026-08-03"
    assert context["current"]["seasonal_coverage_days"] == 123.75
    assert context["next"]["seasonal_coverage_days"] == 135.875


def test_monday_run_uses_that_mondays_shipping_plan():
    context = schedule_context(DEFAULT_SCHEDULE, date(2026, 7, 27))
    assert context["current"]["week_date"] == "2026-07-27"
    assert context["current"]["seasonal_coverage_days"] == 111.625
    assert context["next"]["seasonal_coverage_days"] == 123.75


def test_august_31_schedule_uses_165_5625():
    item = next(
        entry
        for entry in DEFAULT_SCHEDULE
        if entry["week_date"] == "2026-08-31"
    )
    assert item["seasonal_coverage_days"] == 165.5625


def test_manual_scenario_reallocates_across_custom_time_nodes():
    recommendation = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )

    scenario = recalculate_scenario_plan(
        recommendation,
        DEFAULT_SETTINGS,
        date(2026, 7, 28),
        [
            {
                "id": "quick-1",
                "channel_key": "quick",
                "dispatch_date": "2026-08-03",
                "arrival_date": "2026-08-20",
            },
            {
                "id": "slow-1",
                "channel_key": "slow",
                "dispatch_date": "2026-08-10",
                "arrival_date": "2026-09-20",
            },
        ],
    )

    assert [node["id"] for node in scenario["nodes"]] == [
        "quick-1",
        "slow-1",
    ]
    assert scenario["nodes"][0]["quantity"] > 0
    assert scenario["nodes"][1]["quantity"] > 0
    assert scenario["planned_ship_total"] >= scenario["base_ship_total"]
    assert scenario["recommended_by_channel"]["quick"] > 0
    assert scenario["recommended_by_channel"]["slow"] > 0


def test_manual_scenario_uses_new_earlier_node_for_bridge_quantity():
    recommendation = calculate_recommendation(
        product(fbt_total=20, fbt_sellable=10, fbt_in_transit=0),
        settings(express_channel_enabled=True),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )

    scenario = recalculate_scenario_plan(
        recommendation,
        settings(express_channel_enabled=True),
        date(2026, 7, 28),
        [
            {
                "id": "express-1",
                "channel_key": "express",
                "dispatch_date": "2026-07-28",
                "arrival_date": "2026-08-03",
            },
            {
                "id": "quick-1",
                "channel_key": "quick",
                "dispatch_date": "2026-08-03",
                "arrival_date": "2026-09-01",
            },
        ],
    )

    assert scenario["nodes"][0]["channel_key"] == "express"
    assert scenario["nodes"][0]["quantity"] > 0
    assert scenario["normal_target_coverage_days"] == 6


def test_manual_scenario_blocks_nodes_after_receiving_cutoff():
    recommendation = calculate_recommendation(
        product(),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )

    scenario = recalculate_scenario_plan(
        recommendation,
        DEFAULT_SETTINGS,
        date(2026, 7, 28),
        [
            {
                "id": "slow-after-cutoff",
                "channel_key": "slow",
                "dispatch_date": "2026-11-20",
                "arrival_date": "2026-12-10",
            }
        ],
    )

    blocked = next(
        node
        for node in scenario["nodes"]
        if node["id"] == "slow-after-cutoff"
    )
    assert blocked["quantity"] == 0
    assert blocked["eligible_before_cutoff"] is False
    assert any(
        node.get("auto_generated") and node["quantity"] > 0
        for node in scenario["nodes"]
    )
    assert scenario["cutoff_blocked_qty"] == 0


def test_manual_locked_raise_reduces_other_channel_quantity():
    recommendation = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=500,
            fbt_sellable=500,
            fbt_in_transit=0,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    nodes = [
        {
            "id": "quick-1",
            "channel_key": "quick",
            "dispatch_date": "2026-08-03",
            "arrival_date": "2026-08-20",
        },
        {
            "id": "slow-1",
            "channel_key": "slow",
            "dispatch_date": "2026-08-03",
            "arrival_date": "2026-09-20",
        },
    ]
    baseline = recalculate_scenario_plan(
        recommendation,
        DEFAULT_SETTINGS,
        date(2026, 7, 28),
        nodes,
    )
    baseline_slow = next(
        node["quantity"]
        for node in baseline["nodes"]
        if node["id"] == "slow-1"
    )
    baseline_quick = next(
        node["quantity"]
        for node in baseline["nodes"]
        if node["id"] == "quick-1"
    )
    adjusted = recalculate_scenario_plan(
        recommendation,
        DEFAULT_SETTINGS,
        date(2026, 7, 28),
        [
            {
                **nodes[0],
                "quantity": 100,
                "quantity_locked": True,
            },
            nodes[1],
        ],
    )
    adjusted_quick = next(
        node for node in adjusted["nodes"] if node["id"] == "quick-1"
    )
    adjusted_slow = next(
        node for node in adjusted["nodes"] if node["id"] == "slow-1"
    )

    assert adjusted_quick["quantity"] == 100
    assert adjusted_quick["quantity_locked"] is True
    assert adjusted_slow["quantity"] == (
        baseline_slow - (100 - baseline_quick)
    )
    assert adjusted["planned_ship_total"] == baseline["planned_ship_total"]
    assert adjusted["stockout_protected"] is True


def test_manual_locked_reduction_adds_repeated_rescue_channel():
    enabled = settings(express_channel_enabled=True)
    recommendation = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=200,
            fbt_sellable=200,
            fbt_in_transit=0,
        ),
        enabled,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    scenario = recalculate_scenario_plan(
        recommendation,
        enabled,
        date(2026, 7, 28),
        [
            {
                "id": "express-locked",
                "channel_key": "express",
                "dispatch_date": "2026-08-03",
                "arrival_date": "2026-08-09",
                "quantity": 50,
                "quantity_locked": True,
            },
            {
                "id": "slow-1",
                "channel_key": "slow",
                "dispatch_date": "2026-08-03",
                "arrival_date": "2026-09-20",
            },
        ],
    )
    express_nodes = [
        node
        for node in scenario["nodes"]
        if node["channel_key"] == "express" and node["quantity"] > 0
    ]
    locked = next(
        node for node in express_nodes if node["id"] == "express-locked"
    )
    rescue = next(
        node for node in express_nodes if node.get("auto_generated")
    )

    assert locked["quantity"] == 50
    assert rescue["dispatch_date"] == "2026-08-10"
    assert rescue["quantity"] > 0
    assert scenario["stockout_protected"] is True
    assert scenario["uncovered_shortage_qty"] == 0


def test_manual_lock_reports_when_no_channel_can_prevent_stockout():
    recommendation = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=10,
            fbt_sellable=10,
            fbt_in_transit=0,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    scenario = recalculate_scenario_plan(
        recommendation,
        DEFAULT_SETTINGS,
        date(2026, 7, 28),
        [
            {
                "id": "quick-locked",
                "channel_key": "quick",
                "dispatch_date": "2026-08-03",
                "arrival_date": "2026-09-01",
                "quantity": 0,
                "quantity_locked": True,
            }
        ],
    )

    assert scenario["stockout_protected"] is False
    assert scenario["uncovered_shortage_qty"] > 0
    assert scenario["first_uncovered_date"] is not None


def test_all_regular_channels_share_one_inventory_ledger():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    # A Tuesday run uses the next Monday's 123.75-day seasonal base. In precise
    # mode the sailing wait replaces frequency, so only the 7 safety days remain.
    # Unknown-date transit stays in the seasonal total ledger, but cannot
    # suppress the time-sensitive quick-ship bridge.
    assert result["planned_dispatch_date"] == "2026-08-03"
    assert result["quick_qty"] == 385
    assert result["truck_qty"] == 0
    assert result["current_seasonal_coverage_days"] == 123.75
    assert result["current_total_coverage_days"] == 130.75
    assert result["current_gap"] == 975
    assert result["slow_qty"] == 590
    assert result["bridge_advanced_qty"] == 385
    assert result["planned_ship_total"] == 975
    assert result["next_buy_gap"] == 104


def test_stockout_risk_is_independent_from_air_toggle():
    result = calculate_recommendation(
        product(fbt_total=1000, fbt_sellable=10, fbt_in_transit=0),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert result["sellable_coverage_days"] == 1.2
    assert result["air_warning"] is True
    assert result["air_qty"] == 0
    assert result["quick_qty"] == 455
    assert result["planned_ship_total"] == 455
    assert result["risk"] == "critical"


def test_disabled_regular_channel_is_not_used_for_recommendations():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        settings(quick_channel_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert result["quick_qty"] == 0
    assert result["truck_qty"] == 385
    assert result["slow_qty"] == 590
    assert result["planned_ship_total"] == 975
    assert result["regular_fastest_channel"] == "truck"
    assert result["channel_signature"] == "truck,slow"
    assert next(
        plan for plan in result["channel_plans"] if plan["key"] == "quick"
    )["enabled"] is False


def test_disabled_air_channel_cannot_be_reenabled_by_emergency_toggle():
    result = calculate_recommendation(
        product(fbt_total=0, fbt_sellable=0, fbt_in_transit=480, fbt_all=480),
        settings(air_enabled=True, air_channel_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert result["air_enabled"] is False
    assert result["air_qty"] == 0
    assert result["channel_signature"] == "quick,truck,slow"


def test_current_stockout_marks_daily_sales_as_potentially_distorted():
    result = calculate_recommendation(
        product(fbt_sellable=0),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert "当前断货，动态日均可能被断货日压低" in result["data_flags"]


def test_clearance_product_keeps_data_but_has_no_shipping_or_buying_suggestion():
    result = calculate_recommendation(
        product(
            planning_status="clearance",
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )

    assert result["is_planning_excluded"] is True
    assert result["planning_status_label"] == "清仓"
    assert result["planned_ship_total"] == 0
    assert result["next_buy_gap"] == 0
    assert result["risk"] == "excluded"
    assert result["dynamic_daily"] > 0


def test_air_mode_reallocates_the_plan_before_regular_channels():
    disabled = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=480,
            fbt_all=480,
        ),
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    enabled_settings = settings(air_channel_enabled=True)
    enabled = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=480,
            fbt_all=480,
        ),
        enabled_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert (
        disabled["air_qty"],
        disabled["quick_qty"],
        disabled["truck_qty"],
        disabled["slow_qty"],
    ) == (
        0,
        540,
        0,
        288,
    )
    assert (
        enabled["air_qty"],
        enabled["quick_qty"],
        enabled["truck_qty"],
        enabled["slow_qty"],
    ) == (
        470,
        70,
        0,
        288,
    )
    assert enabled["air_warning"] is True
    assert enabled["air_too_late"] is True

    forecast = build_forecast(enabled, enabled_settings, date(2026, 7, 28))
    assert forecast["next_review_date"] == "2026-08-04"
    assert forecast["arrivals"][0] == {
        "date": "2026-08-26",
        "actual_date": "2026-08-12",
        "buffered_date": "2026-08-26",
        "channel": "空派 IE",
        "channel_key": "air",
        "quantity": 470,
        "kind": "planned",
    }


def test_air_mode_can_raise_total_ship_qty_for_an_emergency_bridge():
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=1000,
            fbt_sellable=0,
            fbt_in_transit=0,
            fbt_all=1000,
        ),
        settings(air_channel_enabled=True),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert result["current_gap"] == 308
    assert result["air_qty"] == 470
    assert result["quick_qty"] == 70
    assert result["slow_qty"] == 0
    assert result["planned_ship_total"] == 540


def test_express_and_air_form_separate_urgent_bridges():
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
            fbt_all=0,
        ),
        settings(
            express_channel_enabled=True,
            air_channel_enabled=True,
        ),
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )

    assert result["channel_signature"] == "express,air,quick,truck,slow"
    assert (
        result["express_qty"],
        result["air_qty"],
        result["quick_qty"],
        result["slow_qty"],
    ) == (290, 180, 70, 768)
    assert [
        detail["channel"] for detail in result["bridge_details"]
    ] == ["express", "air", "quick"]
    assert result["same_arrival_skips"] == [
        {
            "skipped_channel": "truck",
            "skipped_channel_label": "普船卡派",
            "selected_channel": "quick",
            "selected_channel_label": "快船",
            "arrival_date": "2026-09-07",
        }
    ]
    assert result["planned_ship_total"] == result["current_gap"]


def test_dated_ibr_arriving_before_quick_removes_the_air_bridge():
    enabled_settings = settings(air_channel_enabled=True)
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=50,
            fbt_sellable=50,
            fbt_in_transit=430,
        ),
        enabled_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        inbounds=[
            {
                "cargo_code": "IBR-DAY-20",
                "remaining_qty": 430,
                "expected_delivery_time": "2026-08-17",
            }
        ],
    )

    assert result["stockout_date"] == "2026-08-02"
    assert result["air_too_late"] is True
    assert result["air_required_qty"] == 0
    assert result["air_qty"] == 0

    forecast = build_forecast(result, enabled_settings, date(2026, 7, 28))
    inbound_node = forecast["dates"].index("2026-08-17")
    assert forecast["planned"][inbound_node] == forecast["baseline"][
        inbound_node
    ]


def test_disabling_air_ignores_a_stale_confirmed_air_quantity():
    disabled_settings = settings(air_enabled=False)
    result = calculate_recommendation(
        product(avg_7=10, avg_14=10, avg_30=10),
        disabled_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        decision={"confirmed_air_qty": 999},
    )

    forecast = build_forecast(result, disabled_settings, date(2026, 7, 28))

    assert not any(
        item["channel"] == "空派" for item in forecast["arrivals"]
    )
    air_arrival_index = forecast["dates"].index(
        result["air_planning_arrival_date"]
    )
    assert forecast["planned"][air_arrival_index] == forecast["baseline"][
        air_arrival_index
    ]


def test_air_mode_ignores_confirmed_quantities_saved_for_non_air_mode():
    enabled_settings = settings(air_channel_enabled=True)
    result = calculate_recommendation(
        product(
            avg_7=0.468,
            avg_14=0.468,
            avg_30=0.468,
            fbt_total=11,
            fbt_sellable=11,
            fbt_in_transit=0,
        ),
        enabled_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
        decision={
            "air_enabled": False,
            "confirmed_air_qty": None,
            "confirmed_quick_qty": 13,
            "confirmed_slow_qty": 35,
        },
    )

    assert (
        result["air_qty"],
        result["quick_qty"],
        result["truck_qty"],
        result["slow_qty"],
    ) == (11, 3, 0, 37)
    assert result["confirmed_air_qty"] is None
    assert result["confirmed_quick_qty"] is None
    assert result["confirmed_slow_qty"] is None
    assert result["decision_matches_mode"] is False


def test_pending_decision_does_not_override_recalculated_channel_split():
    result = calculate_recommendation(
        product(
            avg_7=0.468,
            avg_14=0.468,
            avg_30=0.468,
            fbt_total=11,
            fbt_sellable=11,
            fbt_in_transit=0,
        ),
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
        decision={
            "air_enabled": False,
            "confirmed_quick_qty": 13,
            "confirmed_slow_qty": 35,
            "review_status": "pending",
        },
    )

    assert (result["quick_qty"], result["truck_qty"], result["slow_qty"]) == (
        14,
        0,
        37,
    )
    assert result["confirmed_quick_qty"] is None
    assert result["confirmed_slow_qty"] is None
    assert result["decision_is_final"] is False


def test_matching_pending_decision_is_restored_as_draft_only():
    review_product = product(
        avg_7=0.468,
        avg_14=0.468,
        avg_30=0.468,
        fbt_total=11,
        fbt_sellable=11,
        fbt_in_transit=0,
    )
    current = calculate_recommendation(
        review_product,
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
    )
    draft_nodes = [
        {
            "id": "draft-quick",
            "channel_key": "quick",
            "quantity": 22,
        }
    ]
    result = calculate_recommendation(
        review_product,
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
        decision={
            "air_enabled": False,
            "channel_signature": current["decision_signature"],
            "timing_mode": "precise",
            "confirmed_quick_qty": 22,
            "confirmed_slow_qty": 26,
            "scenario_nodes": draft_nodes,
            "final_buy_qty": 17,
            "review_status": "pending",
        },
    )

    assert result["decision_matches_mode"] is True
    assert result["decision_is_final"] is False
    assert result["confirmed_quick_qty"] is None
    assert result["draft_scenario_nodes"] == draft_nodes
    assert result["draft_final_buy_qty"] == 17
    assert result["effective_quick_qty"] == result["quick_qty"]
    assert result["effective_quantity_source"] == "system"


def test_reviewed_decision_can_override_the_system_channel_split():
    review_product = product(
        avg_7=0.468,
        avg_14=0.468,
        avg_30=0.468,
        fbt_total=11,
        fbt_sellable=11,
        fbt_in_transit=0,
    )
    current = calculate_recommendation(
        review_product,
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
    )
    result = calculate_recommendation(
        review_product,
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
        decision={
            "air_enabled": False,
            "channel_signature": current["decision_signature"],
            "timing_mode": "precise",
            "air_service": "IP",
            "confirmed_quick_qty": 22,
            "confirmed_truck_qty": 0,
            "confirmed_slow_qty": 26,
            "final_buy_qty": 19,
            "review_status": "reviewed",
        },
    )

    forecast = build_forecast(result, DEFAULT_SETTINGS, date(2026, 7, 29))
    quick_index = forecast["dates"].index(
        result["quick_planning_arrival_date"]
    )
    baseline_at_quick = forecast["baseline"][quick_index]

    assert result["decision_is_final"] is True
    assert result["effective_quick_qty"] == 22
    assert result["effective_slow_qty"] == 26
    assert result["effective_planned_ship_total"] == 48
    assert result["effective_buy_qty"] == 19
    assert result["effective_quantity_source"] == "manual"
    summary = build_summary([result])
    assert summary["ship_total_qty"] == 48
    assert summary["buy_total_qty"] == 19
    assert forecast["planned"][quick_index] == pytest.approx(
        baseline_at_quick + 22
    )


def test_changed_arrival_settings_invalidate_a_reviewed_decision():
    review_product = product(
        avg_7=0.468,
        avg_14=0.468,
        avg_30=0.468,
        fbt_total=11,
        fbt_sellable=11,
        fbt_in_transit=0,
    )
    original_settings = settings(air_enabled=False)
    original = calculate_recommendation(
        review_product,
        original_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
    )
    changed = calculate_recommendation(
        review_product,
        settings(air_enabled=False, quick_safety_days=10),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
        decision={
            "air_enabled": False,
            "channel_signature": original["decision_signature"],
            "timing_mode": "precise",
            "confirmed_quick_qty": 22,
            "confirmed_truck_qty": 0,
            "confirmed_slow_qty": 26,
            "review_status": "reviewed",
        },
    )

    assert changed["decision_matches_mode"] is False
    assert changed["decision_is_final"] is False
    assert changed["confirmed_quick_qty"] is None


def test_in_transit_unknown_date_is_note_not_data_error():
    result = calculate_recommendation(
        product(fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert "50件在途无法放入到货时间线" in result["data_notes"]
    assert "50件在途无法放入到货时间线" not in result["data_flags"]


def test_all_inventory_can_be_in_transit_without_mapping_error():
    result = calculate_recommendation(
        product(
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=480,
            fbt_all=480,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert result["fbt_all"] == 480
    assert result["inventory_position"] == 480
    assert "当前FBT库存全部在途，尚未入仓" in result["data_notes"]
    assert "领星FBT合计与已入仓加在途不一致" not in result["data_flags"]


def test_fbt_source_total_mismatch_is_flagged():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_in_transit=50, fbt_all=999),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
    )
    assert "领星FBT合计与已入仓加在途不一致" in result["data_flags"]


def test_dated_ibr_inside_quick_window_reduces_quick_qty():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        inbounds=[
            {
                "cargo_code": "IBR-001",
                "remaining_qty": 50,
                "expected_delivery_time": "2026-08-20",
            }
        ],
    )
    assert result["quick_qty"] == 335
    assert result["truck_qty"] == 0
    assert result["slow_qty"] == 640
    assert result["dated_inbound_qty"] == 50
    assert result["unplaced_in_transit_qty"] == 0


def test_late_ibr_does_not_hide_the_quick_window_gap():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        inbounds=[
            {
                "cargo_code": "IBR-LATE",
                "remaining_qty": 50,
                "expected_delivery_time": "2026-09-30",
            }
        ],
    )
    assert result["quick_qty"] == 385
    assert result["tracked_inbound_qty"] == 50


def test_overdue_unreceived_ibr_remains_visible_but_does_not_enter_forecast():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 31),
        inbounds=[
            {
                "cargo_code": "IBR-OVERDUE",
                "remaining_qty": 50,
                "expected_delivery_time": "2026-07-30",
            }
        ],
    )
    assert len(result["inbounds"]) == 1
    assert result["inbounds"][0]["is_overdue"] is True
    assert result["inbounds"][0]["planning_qty"] == 0
    assert result["planning_inbounds"] == []
    assert result["overdue_inbound_qty"] == 50


def test_ibr_detail_cannot_raise_the_fbt_in_transit_total():
    result = calculate_recommendation(
        product(fbt_total=100, fbt_sellable=80, fbt_in_transit=50),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        inbounds=[
            {
                "cargo_code": "IBR-STALE",
                "remaining_qty": 100,
                "expected_delivery_time": "2026-08-20",
            }
        ],
    )
    assert result["tracked_inbound_qty"] == 100
    assert result["dated_inbound_qty"] == 50
    assert result["inventory_position"] == 150
    assert "快照差异" in " ".join(result["data_notes"])


def test_existing_ibr_raises_the_forecast_on_its_eta():
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=100,
            fbt_sellable=100,
            fbt_in_transit=50,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 7, 28),
        inbounds=[
            {
                "cargo_code": "IBR-FORECAST",
                "remaining_qty": 50,
                "expected_delivery_time": "2026-08-07",
            }
        ],
    )
    forecast = build_forecast(result, DEFAULT_SETTINGS, date(2026, 7, 28))
    eta_index = forecast["dates"].index("2026-08-07")
    assert forecast["baseline"][eta_index] == 50
    existing = next(
        item for item in forecast["arrivals"] if item["kind"] == "existing"
    )
    assert existing["cargo_code"] == "IBR-FORECAST"


def test_earlier_channel_bridges_inventory_safely_until_slow_arrival():
    result = calculate_recommendation(
        product(
            avg_7=0.468,
            avg_14=0.468,
            avg_30=0.468,
            fbt_total=11,
            fbt_sellable=11,
            fbt_in_transit=0,
        ),
        settings(air_enabled=False),
        DEFAULT_SCHEDULE,
        date(2026, 7, 29),
    )

    assert (result["quick_qty"], result["truck_qty"], result["slow_qty"]) == (
        14,
        0,
        37,
    )
    assert result["planned_ship_total"] == 51
    assert result["bridge_advanced_qty"] == 14

    forecast = build_forecast(result, DEFAULT_SETTINGS, date(2026, 7, 29))
    quick_index = forecast["dates"].index(
        result["quick_planning_arrival_date"]
    )
    slow_index = forecast["dates"].index(
        result["slow_planning_arrival_date"]
    )
    assert min(forecast["planned"][quick_index:slow_index]) >= forecast["safety"][0]


def test_cutoff_moves_late_channel_suggestion_to_an_earlier_channel():
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 10, 25),
    )
    assert result["slow_arrival_date"] >= DEFAULT_SETTINGS["receiving_cutoff"]
    assert result["slow_qty"] == 0
    assert result["quick_qty"] > 0
    assert "数量已前移到更早渠道" in " ".join(result["data_notes"])


def test_cutoff_blocks_channels_that_cannot_arrive_in_time():
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
        ),
        DEFAULT_SETTINGS,
        DEFAULT_SCHEDULE,
        date(2026, 11, 1),
    )
    assert result["air_qty"] == 0
    assert result["quick_qty"] == 0
    assert result["slow_qty"] == 0
    assert result["cutoff_blocked_qty"] > 0


def test_precise_mode_uses_cutoff_sailing_and_conservative_transit_upper_bound():
    plans = {
        item["key"]: item
        for item in build_channel_plans(
            settings(timing_mode="precise"), date(2026, 7, 30)
        )
    }

    assert plans["quick"]["cutoff_date"] == "2026-08-01"
    assert plans["quick"]["sailing_date"] == "2026-08-05"
    assert plans["quick"]["logistics_eta_date"] == "2026-08-24"
    assert plans["quick"]["base_arrival_date"] == "2026-08-24"
    assert plans["quick"]["arrival_date"] == "2026-08-31"
    assert plans["quick"]["target_coverage_days"] == 32
    assert plans["quick"]["applied_frequency_days"] == 0
    assert plans["slow"]["arrival_date"] == "2026-09-07"
    assert plans["quick"]["schedule_applied"] is True


def test_fixed_mode_uses_frequency_and_does_not_wait_for_the_sailing_date():
    plans = {
        item["key"]: item
        for item in build_channel_plans(
            settings(timing_mode="fixed"), date(2026, 7, 30)
        )
    }

    assert plans["quick"]["base_arrival_date"] == "2026-08-18"
    assert plans["quick"]["arrival_date"] == "2026-09-01"
    assert plans["quick"]["target_coverage_days"] == 33
    assert plans["quick"]["applied_frequency_days"] == 7
    assert plans["truck"]["arrival_date"] == "2026-08-31"
    assert plans["truck"]["target_coverage_days"] == 32
    assert plans["quick"]["schedule_applied"] is False


def test_each_channel_uses_its_own_safety_and_frequency_days():
    plans = {
        item["key"]: item
        for item in build_channel_plans(
            settings(
                timing_mode="fixed",
                quick_safety_days=3,
                quick_frequency_days=5,
                slow_safety_days=10,
                slow_frequency_days=2,
            ),
            date(2026, 7, 30),
        )
    }

    assert plans["quick"]["arrival_days"] == 27
    assert plans["quick"]["target_coverage_days"] == 27
    assert plans["quick"]["buffered_arrival_date"] == "2026-08-26"
    assert plans["slow"]["arrival_days"] == 37
    assert plans["slow"]["target_coverage_days"] == 37
    assert plans["slow"]["buffered_arrival_date"] == "2026-09-05"


def test_forecast_uses_buffered_channel_dates_as_the_formal_plan():
    custom_settings = settings(
        timing_mode="fixed",
        quick_safety_days=3,
        quick_frequency_days=5,
        slow_safety_days=10,
        slow_frequency_days=2,
    )
    result = calculate_recommendation(
        product(
            avg_7=10,
            avg_14=10,
            avg_30=10,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
        ),
        custom_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 30),
    )
    forecast = build_forecast(result, custom_settings, date(2026, 7, 30))
    quick_plan = next(
        plan for plan in result["channel_plans"] if plan["key"] == "quick"
    )
    quick_base = forecast["dates"].index(quick_plan["base_arrival_date"])
    quick_arrival = forecast["dates"].index(quick_plan["arrival_date"])

    assert forecast["planned_actual"][quick_base] > forecast["baseline"][
        quick_base
    ]
    assert forecast["planned"][quick_base] == forecast["baseline"][
        quick_base
    ]
    assert forecast["planned"][quick_arrival] > forecast["baseline"][
        quick_arrival
    ]
    assert forecast["planned_buffered"] == forecast["planned"]


def test_formal_nodes_reallocate_the_screenshot_gap_to_air():
    custom_settings = settings(
        timing_mode="fixed",
        air_channel_enabled=True,
        air_ip_max_days=5,
        air_safety_days=1,
        air_frequency_days=1,
        truck_channel_enabled=False,
    )
    result = calculate_recommendation(
        product(
            avg_7=1,
            avg_14=0.79,
            avg_30=0.83,
            fbt_total=0,
            fbt_sellable=0,
            fbt_in_transit=0,
        ),
        custom_settings,
        DEFAULT_SCHEDULE,
        date(2026, 7, 30),
    )
    forecast = build_forecast(result, custom_settings, date(2026, 7, 30))
    air_index = forecast["dates"].index(result["air_planning_arrival_date"])
    slow_index = forecast["dates"].index(result["slow_planning_arrival_date"])

    assert (result["air_qty"], result["quick_qty"], result["slow_qty"]) == (
        34,
        11,
        80,
    )
    assert result["planned_ship_total"] == 125
    assert min(forecast["planned"][air_index : slow_index + 1]) > 0


def test_sailing_weekdays_and_urgent_channels_are_independently_editable():
    plans = {
        item["key"]: item
        for item in build_channel_plans(
            settings(
                quick_cutoff_weekday=6,
                quick_sailing_weekday=0,
            ),
            date(2026, 7, 30),
        )
    }

    assert plans["express"]["label"] == "快递 IP"
    assert plans["express"]["base_arrival_date"] == "2026-08-03"
    assert plans["express"]["arrival_date"] == "2026-08-05"
    assert plans["air"]["label"] == "空派 IE"
    assert plans["air"]["base_arrival_date"] == "2026-08-08"
    assert plans["air"]["arrival_date"] == "2026-08-22"
    assert plans["quick"]["cutoff_date"] == "2026-08-02"
    assert plans["quick"]["sailing_date"] == "2026-08-03"
    assert plans["quick"]["base_arrival_date"] == "2026-08-22"
    assert plans["quick"]["arrival_date"] == "2026-08-29"
