from __future__ import annotations

import math
from datetime import date, datetime, timedelta
from typing import Any


DEFAULT_SETTINGS: dict[str, Any] = {
    "air_enabled": False,
    "air_channel_enabled": False,
    "express_channel_enabled": False,
    "quick_channel_enabled": True,
    "truck_channel_enabled": True,
    "slow_channel_enabled": True,
    "timing_mode": "precise",
    "express_transit_min_days": 3,
    "express_transit_max_days": 4,
    "air_transit_min_days": 7,
    "air_transit_max_days": 9,
    # Legacy single-channel fields remain readable during upgrade.
    "air_service": "IP",
    "air_ip_min_days": 3,
    "air_ip_max_days": 4,
    "air_ie_min_days": 7,
    "air_ie_max_days": 9,
    "quick_transit_min_days": 12,
    "quick_transit_max_days": 19,
    "quick_cutoff_weekday": 5,
    "quick_sailing_weekday": 2,
    "truck_transit_min_days": 15,
    "truck_transit_max_days": 18,
    "truck_cutoff_weekday": 5,
    "truck_sailing_weekday": 3,
    "slow_transit_min_days": 22,
    "slow_transit_max_days": 25,
    "slow_cutoff_weekday": 5,
    "slow_sailing_weekday": 3,
    "express_safety_days": 1,
    "express_frequency_days": 1,
    "air_safety_days": 7,
    "air_frequency_days": 7,
    "quick_safety_days": 7,
    "quick_frequency_days": 7,
    "truck_safety_days": 7,
    "truck_frequency_days": 7,
    "slow_safety_days": 7,
    "slow_frequency_days": 7,
    # Legacy defaults remain readable so existing databases and integrations
    # can upgrade without losing their previous global buffer values.
    "safety_days": 7,
    "frequency_days": 7,
    "weight_7": 0.5,
    "weight_14": 0.3,
    "weight_30": 0.2,
    "receiving_cutoff": "2026-12-01",
    "warning_delta_days": 20,
    "critical_delta_days": 30,
}


DEFAULT_SCHEDULE = [
    {"week_date": "2026-06-22", "seasonal_coverage_days": 25.5},
    {"week_date": "2026-06-29", "seasonal_coverage_days": 44.0},
    {"week_date": "2026-07-06", "seasonal_coverage_days": 62.5},
    {"week_date": "2026-07-13", "seasonal_coverage_days": 81.0},
    {"week_date": "2026-07-20", "seasonal_coverage_days": 99.5},
    {"week_date": "2026-07-27", "seasonal_coverage_days": 111.625},
    {"week_date": "2026-08-03", "seasonal_coverage_days": 123.75},
    {"week_date": "2026-08-10", "seasonal_coverage_days": 135.875},
    {"week_date": "2026-08-17", "seasonal_coverage_days": 148.0},
    {"week_date": "2026-08-24", "seasonal_coverage_days": 160.125},
    {"week_date": "2026-08-31", "seasonal_coverage_days": 165.5625},
    {"week_date": "2026-09-07", "seasonal_coverage_days": 171.0},
    {"week_date": "2026-09-14", "seasonal_coverage_days": 176.4375},
    {"week_date": "2026-09-21", "seasonal_coverage_days": 181.875},
    {"week_date": "2026-09-28", "seasonal_coverage_days": 187.3125},
    {"week_date": "2026-10-05", "seasonal_coverage_days": 192.75},
]


def parse_date(value: str | date | None) -> date:
    if isinstance(value, date):
        return value
    if value:
        return datetime.strptime(value, "%Y-%m-%d").date()
    return date.today()


def round_quantity(value: float) -> int:
    return max(0, math.ceil(value - 1e-9))


def dynamic_daily_sales(product: dict[str, Any], settings: dict[str, Any]) -> float:
    return max(
        0.0,
        float(product.get("avg_7") or 0) * float(settings["weight_7"])
        + float(product.get("avg_14") or 0) * float(settings["weight_14"])
        + float(product.get("avg_30") or 0) * float(settings["weight_30"]),
    )


def _channel_buffer_days(
    settings: dict[str, Any], channel_key: str
) -> tuple[float, float]:
    safety = max(
        0.0,
        float(
            settings.get(
                f"{channel_key}_safety_days",
                settings.get("safety_days", 7),
            )
        ),
    )
    frequency = max(
        0.0,
        float(
            settings.get(
                f"{channel_key}_frequency_days",
                settings.get("frequency_days", 7),
            )
        ),
    )
    return safety, frequency


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PLANNING_STATUS_LABELS = {
    "active": "正常补货",
    "clearance": "清仓",
    "delisted": "下架",
}
URGENT_CHANNEL_KEYS = ("express", "air")
REGULAR_CHANNEL_KEYS = ("quick", "truck", "slow")
CHANNEL_KEYS = (*URGENT_CHANNEL_KEYS, *REGULAR_CHANNEL_KEYS)


def _next_weekday_on_or_after(current_date: date, weekday: int) -> date:
    target = max(0, min(6, int(weekday)))
    return current_date + timedelta(days=(target - current_date.weekday()) % 7)


def _next_sailing_after(cutoff_date: date, weekday: int) -> date:
    target = max(0, min(6, int(weekday)))
    offset = (target - cutoff_date.weekday()) % 7
    if offset == 0:
        offset = 7
    return cutoff_date + timedelta(days=offset)


def _scheduled_channel_plan(
    *,
    key: str,
    label: str,
    current_date: date,
    settings: dict[str, Any],
    transit_min_key: str,
    transit_max_key: str,
    cutoff_key: str,
    sailing_key: str,
) -> dict[str, Any]:
    transit_min = max(0, int(settings[transit_min_key]))
    transit_max = max(transit_min, int(settings[transit_max_key]))
    cutoff_weekday = max(0, min(6, int(settings[cutoff_key])))
    sailing_weekday = max(0, min(6, int(settings[sailing_key])))
    safety_days, frequency_days = _channel_buffer_days(settings, key)
    timing_mode = str(settings.get("timing_mode") or "precise")

    cutoff_date = _next_weekday_on_or_after(current_date, cutoff_weekday)
    sailing_date = _next_sailing_after(cutoff_date, sailing_weekday)
    if timing_mode == "precise":
        logistics_eta = sailing_date + timedelta(days=transit_max)
        schedule_applied = True
    else:
        logistics_eta = current_date + timedelta(days=transit_max)
        schedule_applied = False
    base_arrival_date = logistics_eta
    applied_frequency_days = 0.0 if timing_mode == "precise" else frequency_days
    final_buffer_days = safety_days + applied_frequency_days
    arrival_date = base_arrival_date + timedelta(
        days=math.ceil(final_buffer_days)
    )
    arrival_days = max(0, (arrival_date - current_date).days)
    target_coverage_days = float(arrival_days)
    planning_arrival_days = arrival_days
    planning_arrival_date = arrival_date

    return {
        "key": key,
        "label": label,
        "transit_min_days": transit_min,
        "transit_max_days": transit_max,
        "cutoff_weekday": cutoff_weekday,
        "cutoff_weekday_name": WEEKDAY_NAMES[cutoff_weekday],
        "sailing_weekday": sailing_weekday,
        "sailing_weekday_name": WEEKDAY_NAMES[sailing_weekday],
        "cutoff_date": cutoff_date.isoformat(),
        "sailing_date": sailing_date.isoformat(),
        "logistics_eta_date": logistics_eta.isoformat(),
        "base_arrival_date": base_arrival_date.isoformat(),
        "arrival_date": arrival_date.isoformat(),
        "arrival_days": arrival_days,
        "planning_arrival_date": planning_arrival_date.isoformat(),
        "planning_arrival_days": planning_arrival_days,
        "buffered_arrival_date": planning_arrival_date.isoformat(),
        "target_coverage_days": round(target_coverage_days, 3),
        "safety_days": safety_days,
        "frequency_days": frequency_days,
        "applied_frequency_days": applied_frequency_days,
        "schedule_applied": schedule_applied,
    }


def build_channel_plans(
    settings: dict[str, Any], as_of: str | date | None
) -> list[dict[str, Any]]:
    current_date = parse_date(as_of)

    def unscheduled_plan(
        *,
        key: str,
        label: str,
        service: str,
        transit_min_key: str,
        transit_max_key: str,
        count_from_next_day: bool,
    ) -> dict[str, Any]:
        safety_days, frequency_days = _channel_buffer_days(settings, key)
        transit_min = max(0, int(settings[transit_min_key]))
        transit_max = max(transit_min, int(settings[transit_max_key]))
        logistics_eta = current_date + timedelta(days=transit_max)
        base_arrival = logistics_eta
        # 快递和空派都没有固定船期，两种模式均保留发货频率。
        final_buffer_days = safety_days + frequency_days
        arrival = base_arrival + timedelta(
            days=math.ceil(final_buffer_days)
        )
        arrival_days = max(0, (arrival - current_date).days)
        return {
            "key": key,
            "label": label,
            "service": service,
            "transit_min_days": transit_min,
            "transit_max_days": transit_max,
            "cutoff_weekday": None,
            "cutoff_weekday_name": "",
            "sailing_weekday": None,
            "sailing_weekday_name": "",
            "cutoff_date": None,
            "sailing_date": None,
            "logistics_eta_date": logistics_eta.isoformat(),
            "base_arrival_date": base_arrival.isoformat(),
            "arrival_date": arrival.isoformat(),
            "arrival_days": arrival_days,
            "planning_arrival_date": arrival.isoformat(),
            "planning_arrival_days": arrival_days,
            "buffered_arrival_date": arrival.isoformat(),
            "target_coverage_days": round(float(arrival_days), 3),
            "safety_days": safety_days,
            "frequency_days": frequency_days,
            "applied_frequency_days": frequency_days,
            "schedule_applied": False,
            "count_from_next_day": count_from_next_day,
        }

    plans = [
        unscheduled_plan(
            key="express",
            label="快递 IP",
            service="IP",
            transit_min_key="express_transit_min_days",
            transit_max_key="express_transit_max_days",
            count_from_next_day=False,
        ),
        unscheduled_plan(
            key="air",
            label="空派 IE",
            service="IE",
            transit_min_key="air_transit_min_days",
            transit_max_key="air_transit_max_days",
            count_from_next_day=True,
        ),
        _scheduled_channel_plan(
            key="quick",
            label="快船",
            current_date=current_date,
            settings=settings,
            transit_min_key="quick_transit_min_days",
            transit_max_key="quick_transit_max_days",
            cutoff_key="quick_cutoff_weekday",
            sailing_key="quick_sailing_weekday",
        ),
        _scheduled_channel_plan(
            key="truck",
            label="普船卡派",
            current_date=current_date,
            settings=settings,
            transit_min_key="truck_transit_min_days",
            transit_max_key="truck_transit_max_days",
            cutoff_key="truck_cutoff_weekday",
            sailing_key="truck_sailing_weekday",
        ),
        _scheduled_channel_plan(
            key="slow",
            label="COSCO慢船",
            current_date=current_date,
            settings=settings,
            transit_min_key="slow_transit_min_days",
            transit_max_key="slow_transit_max_days",
            cutoff_key="slow_cutoff_weekday",
            sailing_key="slow_sailing_weekday",
        ),
    ]
    for plan in plans:
        plan["enabled"] = bool(
            settings.get(f"{plan['key']}_channel_enabled", True)
        )
    return plans


def schedule_context(
    schedule: list[dict[str, Any]], as_of: str | date | None
) -> dict[str, Any]:
    current_date = parse_date(as_of)
    ordered = sorted(schedule, key=lambda item: item["week_date"])
    if not ordered:
        raise ValueError("旺季周计划不能为空")

    current_index = len(ordered) - 1
    for index, item in enumerate(ordered):
        if parse_date(item["week_date"]) >= current_date:
            current_index = index
            break

    current = ordered[current_index]
    next_item = ordered[min(current_index + 1, len(ordered) - 1)]
    previous = ordered[max(current_index - 1, 0)]
    return {
        "previous": previous,
        "current": current,
        "next": next_item,
        "current_index": current_index,
    }


def _fully_received(inbound: dict[str, Any]) -> bool:
    status = " ".join(
        [
            str(inbound.get("order_status_name") or ""),
            str(inbound.get("ship_status") or ""),
        ]
    )
    return "已全部接收" in status or float(inbound.get("remaining_qty") or 0) <= 0


def _prepare_inbounds(
    inbounds: list[dict[str, Any]],
    current_date: date,
    cutoff: date,
) -> tuple[list[dict[str, Any]], float, float, float]:
    active: list[dict[str, Any]] = []
    active_total = 0.0
    placed_total = 0.0
    overdue_total = 0.0
    for source in inbounds:
        remaining = max(0.0, float(source.get("remaining_qty") or 0))
        if remaining <= 0 or _fully_received(source):
            continue
        active_total += remaining
        eta_value = (
            source.get("manual_expected_delivery_date")
            or source.get("expected_delivery_time")
            or source.get("arrival_time")
            or source.get("expected_arrival_time")
        )
        eta = parse_date(eta_value) if eta_value else None
        is_overdue = bool(eta and eta < current_date)
        is_after_cutoff = bool(eta and eta >= cutoff)
        if eta and not is_overdue and not is_after_cutoff:
            placed_total += remaining
        elif is_overdue:
            overdue_total += remaining
        active.append(
            {
                **source,
                "remaining_qty": round(remaining, 2),
                "eta_date": eta.isoformat() if eta else None,
                "is_overdue": is_overdue,
                "is_after_cutoff": is_after_cutoff,
            }
        )
    return active, active_total, placed_total, overdue_total


def _receipts_by_day(
    active_inbounds: list[dict[str, Any]],
    current_date: date,
    coverage_days: float,
) -> float:
    horizon = current_date + timedelta(days=int(coverage_days))
    return sum(
        float(item.get("planning_qty", item["remaining_qty"]))
        for item in active_inbounds
        if item.get("eta_date")
        and not item.get("is_overdue")
        and not item.get("is_after_cutoff")
        and parse_date(item["eta_date"]) <= horizon
    )


def _first_stockout(
    start_inventory: float,
    daily: float,
    active_inbounds: list[dict[str, Any]],
    current_date: date,
    horizon_days: int,
) -> date | None:
    if daily <= 0:
        return None
    arrivals: dict[int, float] = {}
    for item in active_inbounds:
        if (
            not item.get("eta_date")
            or item.get("is_overdue")
            or item.get("is_after_cutoff")
        ):
            continue
        offset = (parse_date(item["eta_date"]) - current_date).days
        if 0 <= offset <= horizon_days:
            arrivals[offset] = arrivals.get(offset, 0.0) + float(
                item.get("planning_qty", item["remaining_qty"])
            )
    inventory = start_inventory
    for day_offset in range(horizon_days + 1):
        inventory += arrivals.get(day_offset, 0.0)
        if inventory <= 0:
            return current_date + timedelta(days=day_offset)
        inventory -= daily
    return None


def _required_bridge_qty(
    start_inventory: float,
    daily: float,
    active_inbounds: list[dict[str, Any]],
    current_date: date,
    bridge_start_days: int,
    bridge_end_days: int,
    safety_days: float,
    earlier_planned_arrivals: dict[int, float] | None = None,
) -> int:
    if daily <= 0 or bridge_start_days > bridge_end_days:
        return 0
    arrivals: dict[int, float] = {}
    for item in active_inbounds:
        if (
            not item.get("eta_date")
            or item.get("is_overdue")
            or item.get("is_after_cutoff")
        ):
            continue
        offset = (parse_date(item["eta_date"]) - current_date).days
        if 0 <= offset <= bridge_end_days:
            arrivals[offset] = arrivals.get(offset, 0.0) + float(
                item.get("planning_qty", item["remaining_qty"])
            )
    for offset, quantity in (earlier_planned_arrivals or {}).items():
        if 0 <= offset <= bridge_end_days:
            arrivals[offset] = arrivals.get(offset, 0.0) + float(quantity)

    cumulative_arrivals = 0.0
    safety_stock = daily * safety_days
    required = 0.0
    # The next channel is available on bridge_end_days, so the earlier channel
    # only needs to protect inventory through the previous day.
    for day_offset in range(bridge_end_days):
        cumulative_arrivals += arrivals.get(day_offset, 0.0)
        if day_offset < bridge_start_days:
            continue
        baseline = start_inventory - daily * day_offset + cumulative_arrivals
        required = max(required, safety_stock - baseline)
    return round_quantity(required)


def _required_air_bridge_qty(
    start_inventory: float,
    daily: float,
    active_inbounds: list[dict[str, Any]],
    current_date: date,
    air_lead_days: int,
    quick_lead_days: int,
    safety_days: float,
) -> int:
    return _required_bridge_qty(
        start_inventory,
        daily,
        active_inbounds,
        current_date,
        air_lead_days,
        quick_lead_days,
        safety_days,
    )


def _optimize_inventory_balance(
    *,
    start_inventory: float,
    daily: float,
    active_inbounds: list[dict[str, Any]],
    current_date: date,
    nodes: list[dict[str, Any]],
    target_ship_total: int,
    horizon_days: int,
) -> dict[str, Any]:
    """Solve manual shipment edits against one daily inventory equation.

    For every day t:
        inventory(t) = sellable + confirmed_receipts(t)
                       + locked_shipments(t) + adjustable_shipments(t)
                       - daily_sales * t

    Locked quantities are equality constraints. Adjustable quantities are
    minimized while keeping inventory non-negative and meeting the total
    shipment target. Later arrivals and slower channels are preferred when
    several choices can protect the same day.
    """
    eligible_nodes = [
        node for node in nodes if node.get("eligible_before_cutoff", True)
    ]
    allocation = {node["id"]: 0 for node in nodes}
    locked_nodes = [
        node for node in eligible_nodes if node.get("quantity_locked")
    ]
    flexible_nodes = [
        node for node in eligible_nodes if not node.get("quantity_locked")
    ]
    for node in locked_nodes:
        allocation[node["id"]] = round_quantity(node.get("requested_quantity", 0))

    inbound_by_day: dict[int, float] = {}
    for item in active_inbounds:
        if (
            not item.get("eta_date")
            or item.get("is_overdue")
            or item.get("is_after_cutoff")
        ):
            continue
        offset = (parse_date(item["eta_date"]) - current_date).days
        if 0 <= offset <= horizon_days:
            inbound_by_day[offset] = inbound_by_day.get(offset, 0.0) + float(
                item.get("planning_qty", item.get("remaining_qty", 0))
            )

    channel_preference = {
        "express": 0,
        "air": 1,
        "quick": 2,
        "truck": 3,
        "slow": 4,
    }

    def node_preference(node: dict[str, Any]) -> tuple[int, int, int]:
        return (
            0 if node.get("auto_generated") else 1,
            int(node["planning_arrival_days"]),
            channel_preference.get(node["channel_key"], -1),
        )

    cumulative_inbound = 0.0
    first_uncovered_day: int | None = None
    uncovered_shortage_qty = 0
    daily_requirements: list[dict[str, Any]] = []
    for day_offset in range(max(0, horizon_days) + 1):
        cumulative_inbound += inbound_by_day.get(day_offset, 0.0)
        shipment_receipts = sum(
            allocation[node["id"]]
            for node in eligible_nodes
            if int(node["planning_arrival_days"]) <= day_offset
        )
        projected = (
            start_inventory
            + cumulative_inbound
            + shipment_receipts
            - daily * day_offset
        )
        deficit = round_quantity(-projected)
        if deficit <= 0:
            continue
        candidates = [
            node
            for node in flexible_nodes
            if int(node["planning_arrival_days"]) <= day_offset
        ]
        if not candidates:
            if first_uncovered_day is None:
                first_uncovered_day = day_offset
            uncovered_shortage_qty = max(uncovered_shortage_qty, deficit)
            continue
        selected = max(candidates, key=node_preference)
        allocation[selected["id"]] += deficit
        daily_requirements.append(
            {
                "date": (current_date + timedelta(days=day_offset)).isoformat(),
                "node_id": selected["id"],
                "channel": selected["channel_key"],
                "required_qty": deficit,
            }
        )

    locked_ship_total = sum(allocation[node["id"]] for node in locked_nodes)
    allocated_total = sum(allocation.values())
    remaining_target = max(0, target_ship_total - allocated_total)
    target_candidates = [
        node
        for node in flexible_nodes
        if int(node["planning_arrival_days"]) <= horizon_days
    ]
    target_blocked_qty = 0
    if remaining_target > 0 and target_candidates:
        selected = max(target_candidates, key=node_preference)
        allocation[selected["id"]] += remaining_target
    elif remaining_target > 0:
        target_blocked_qty = remaining_target

    planned_ship_total = sum(allocation.values())
    return {
        "allocation": allocation,
        "planned_ship_total": planned_ship_total,
        "locked_ship_total": locked_ship_total,
        "auto_adjusted_total": planned_ship_total - locked_ship_total,
        "uncovered_shortage_qty": uncovered_shortage_qty,
        "first_uncovered_date": (
            (current_date + timedelta(days=first_uncovered_day)).isoformat()
            if first_uncovered_day is not None
            else None
        ),
        "target_blocked_qty": target_blocked_qty,
        "stockout_protected": uncovered_shortage_qty <= 0,
        "daily_requirements": daily_requirements,
    }


def calculate_recommendation(
    product: dict[str, Any],
    settings: dict[str, Any],
    schedule: list[dict[str, Any]],
    as_of: str | date | None,
    decision: dict[str, Any] | None = None,
    inbounds: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    decision = decision or {}
    inbounds = inbounds or []
    current_date = parse_date(as_of)
    planning_status = str(product.get("planning_status") or "active").lower()
    if planning_status not in PLANNING_STATUS_LABELS:
        planning_status = "active"
    is_planning_excluded = planning_status in {"clearance", "delisted"}
    context = schedule_context(schedule, current_date)
    daily = dynamic_daily_sales(product, settings)
    cutoff = parse_date(settings["receiving_cutoff"])
    planned_dispatch_date = max(
        current_date,
        parse_date(context["current"]["week_date"]),
    )
    channel_plans = build_channel_plans(settings, planned_dispatch_date)
    # Midweek runs calculate the coming Monday's shipment. Arrival offsets must
    # still be measured from today because inventory keeps selling before then.
    for plan in channel_plans:
        plan["planned_dispatch_date"] = planned_dispatch_date.isoformat()
        plan["arrival_days"] = max(
            0,
            (parse_date(plan["arrival_date"]) - current_date).days,
        )
        plan["planning_arrival_days"] = max(
            0,
            (parse_date(plan["planning_arrival_date"]) - current_date).days,
        )
        plan["target_coverage_days"] = round(
            float(plan["planning_arrival_days"]),
            3,
        )
    plans_by_key = {item["key"]: item for item in channel_plans}

    fbt_total = max(0.0, float(product.get("fbt_total") or 0))
    fbt_sellable = max(0.0, float(product.get("fbt_sellable") or 0))
    fbt_in_transit = max(0.0, float(product.get("fbt_in_transit") or 0))
    calculated_fbt_all = fbt_total + fbt_in_transit
    source_fbt_all = max(
        0.0, float(product.get("fbt_all", calculated_fbt_all) or 0)
    )
    executed_unsynced = max(0.0, float(decision.get("executed_unsynced_qty") or 0))
    (
        active_inbounds,
        tracked_inbound_qty,
        raw_dated_inbound_qty,
        overdue_inbound_qty,
    ) = _prepare_inbounds(inbounds, current_date, cutoff)
    # FBT在途是数量总账，IBR只负责给这笔总量分配到货日期。
    # 旧IBR可能尚未标记“全部接收”，明细合计会大于当前FBT在途，不能反抬总账。
    dated_scale = (
        min(1.0, fbt_in_transit / raw_dated_inbound_qty)
        if raw_dated_inbound_qty > 0
        else 0.0
    )
    for inbound in active_inbounds:
        inbound["planning_qty"] = round(
            float(inbound["remaining_qty"]) * dated_scale
            if inbound.get("eta_date")
            and not inbound.get("is_overdue")
            and not inbound.get("is_after_cutoff")
            else 0.0,
            4,
        )
    dated_inbound_qty = sum(
        float(inbound["planning_qty"]) for inbound in active_inbounds
    )
    inventory_position = calculated_fbt_all + executed_unsynced
    unplaced_in_transit_qty = max(0.0, fbt_in_transit - dated_inbound_qty)

    channel_enabled = {
        key: bool(plans_by_key[key].get("enabled", True))
        for key in CHANNEL_KEYS
    }
    channel_signature = ",".join(
        key for key in CHANNEL_KEYS if channel_enabled[key]
    )
    # 渠道卡片上的“参与建议”是唯一启停入口；air_enabled仅保留兼容旧决策。
    express_enabled = channel_enabled["express"]
    air_enabled = channel_enabled["air"]
    decision_air_enabled = bool(decision.get("air_enabled", False))
    timing_mode = str(settings.get("timing_mode") or "precise")
    decision_signature = "|".join(
        [
            f"channels={channel_signature}",
            f"mode={timing_mode}",
            f"dispatch={planned_dispatch_date.isoformat()}",
            f"seasonal={float(context['current']['seasonal_coverage_days']):.4f}",
            f"cutoff={cutoff.isoformat()}",
            *[
                (
                    f"{key}@{plans_by_key[key]['planning_arrival_date']}"
                    f":s{float(plans_by_key[key]['safety_days']):g}"
                    f":f{float(plans_by_key[key]['applied_frequency_days']):g}"
                )
                for key in CHANNEL_KEYS
                if channel_enabled[key]
            ],
        ]
    )
    decision_channel_signature = str(
        decision.get("channel_signature") or ""
    )
    decision_matches_mode = bool(decision) and (
        decision_air_enabled == air_enabled
        and str(decision.get("timing_mode") or "") == timing_mode
        and decision_channel_signature == decision_signature
    )
    decision_is_final = decision_matches_mode and decision.get(
        "review_status"
    ) in {"reviewed", "executed"}
    current_seasonal_coverage_days = float(
        context["current"]["seasonal_coverage_days"]
    )
    next_seasonal_coverage_days = float(context["next"]["seasonal_coverage_days"])

    regular_plans = [
        plans_by_key[key]
        for key in REGULAR_CHANNEL_KEYS
        if channel_enabled[key]
    ]
    if not regular_plans:
        raise ValueError("至少需要启用一个常规物流渠道")
    priority = {"quick": 0, "truck": 1, "slow": 2}
    ordered_regular_plans = sorted(
        regular_plans,
        key=lambda item: (
            int(item["planning_arrival_days"]),
            priority[item["key"]],
        ),
    )
    fastest_regular = ordered_regular_plans[0]
    seasonal_regular = ordered_regular_plans[-1]
    safety_buffer_days = float(seasonal_regular["safety_days"])
    dispatch_interval_days = float(
        seasonal_regular["applied_frequency_days"]
    )
    normal_safety_buffer_days = float(fastest_regular["safety_days"])
    normal_dispatch_interval_days = float(
        fastest_regular["applied_frequency_days"]
    )
    review_interval_days = float(fastest_regular["frequency_days"])
    # The slowest enabled regular channel carries the remaining seasonal
    # quantity, so its independently configured buffers extend the schedule.
    current_total_coverage_days = (
        current_seasonal_coverage_days
        + safety_buffer_days
        + dispatch_interval_days
    )
    next_total_coverage_days = (
        next_seasonal_coverage_days
        + safety_buffer_days
        + dispatch_interval_days
    )
    normal_target_coverage_days = float(
        fastest_regular["target_coverage_days"]
    )
    sellable_coverage_days = fbt_sellable / daily if daily > 0 else None
    normal_target_units = daily * normal_target_coverage_days
    current_target_units = daily * current_total_coverage_days
    next_target_units = daily * next_total_coverage_days

    normal_receipts = _receipts_by_day(
        active_inbounds, current_date, normal_target_coverage_days
    )
    normal_available = fbt_total + executed_unsynced + normal_receipts
    base_normal_qty = round_quantity(normal_target_units - normal_available)
    current_gap = round_quantity(current_target_units - inventory_position)
    regular_ship_total = max(base_normal_qty, current_gap)
    stockout_date = _first_stockout(
        fbt_sellable,
        daily,
        active_inbounds,
        current_date,
        max(
            180,
            max(0, (cutoff - current_date).days),
        ),
    )
    fastest_regular_arrival = parse_date(
        fastest_regular["planning_arrival_date"]
    )
    requires_faster_than_regular = bool(
        stockout_date and stockout_date < fastest_regular_arrival
    )
    cutoff_blocked_qty = 0
    allocation = {key: 0 for key in CHANNEL_KEYS}
    required_by_channel = {key: 0 for key in CHANNEL_KEYS}
    priority = {
        "express": 0,
        "air": 1,
        "quick": 2,
        "truck": 3,
        "slow": 4,
    }
    eligible_urgent = [
        plans_by_key[key]
        for key in URGENT_CHANNEL_KEYS
        if channel_enabled[key]
        and parse_date(plans_by_key[key]["arrival_date"]) < cutoff
        and parse_date(plans_by_key[key]["arrival_date"])
        < fastest_regular_arrival
    ]
    eligible_regular = [
        item
        for item in ordered_regular_plans
        if parse_date(item["arrival_date"]) < cutoff
    ]
    ordered_eligible_plans = sorted(
        [*eligible_urgent, *eligible_regular],
        key=lambda item: (
            int(item["planning_arrival_days"]),
            priority[item["key"]],
        ),
    )
    # 同一天到货没有拆分价值，只保留优先级更高的一个渠道。
    unique_eligible_plans: list[dict[str, Any]] = []
    seen_arrival_days: dict[int, dict[str, Any]] = {}
    same_arrival_skips: list[dict[str, Any]] = []
    for item in ordered_eligible_plans:
        arrival_days = int(item["planning_arrival_days"])
        if arrival_days in seen_arrival_days:
            selected = seen_arrival_days[arrival_days]
            same_arrival_skips.append(
                {
                    "skipped_channel": item["key"],
                    "skipped_channel_label": item["label"],
                    "selected_channel": selected["key"],
                    "selected_channel_label": selected["label"],
                    "arrival_date": item["planning_arrival_date"],
                }
            )
            continue
        seen_arrival_days[arrival_days] = item
        unique_eligible_plans.append(item)
    eligible_plans = unique_eligible_plans
    bridge_details: list[dict[str, Any]] = []
    earlier_arrivals: dict[int, float] = {}
    remaining_ship_qty = regular_ship_total

    if eligible_plans:
        for index, plan in enumerate(eligible_plans[:-1]):
            next_plan = eligible_plans[index + 1]
            required = _required_bridge_qty(
                fbt_sellable,
                daily,
                active_inbounds,
                current_date,
                int(plan["planning_arrival_days"]),
                int(next_plan["planning_arrival_days"]),
                float(plan["safety_days"]),
                earlier_arrivals,
            )
            # 时间缺口必须由更早渠道补足；需要时允许桥接量抬高本次总量。
            allocated = required
            allocation[plan["key"]] += allocated
            required_by_channel[plan["key"]] = required
            remaining_ship_qty = max(0, remaining_ship_qty - allocated)
            if allocated > 0:
                arrival_offset = int(plan["planning_arrival_days"])
                earlier_arrivals[arrival_offset] = (
                    earlier_arrivals.get(arrival_offset, 0.0) + allocated
                )
            bridge_details.append(
                {
                    "channel": plan["key"],
                    "channel_label": plan["label"],
                    "next_channel": next_plan["key"],
                    "next_channel_label": next_plan["label"],
                    "required_qty": required,
                    "allocated_qty": allocated,
                }
            )
        allocation[eligible_plans[-1]["key"]] += remaining_ship_qty
        remaining_ship_qty = 0
    else:
        cutoff_blocked_qty += remaining_ship_qty
        remaining_ship_qty = 0

    express_qty = allocation["express"]
    air_qty = allocation["air"]
    quick_qty = allocation["quick"]
    truck_qty = allocation["truck"]
    slow_qty = allocation["slow"]
    express_required_qty = required_by_channel["express"]
    air_required_qty = required_by_channel["air"]
    bridge_advanced_qty = sum(
        allocation[item["key"]] for item in eligible_plans[:-1]
    )

    next_buy_gap = round_quantity(
        next_target_units
        - inventory_position
        - express_qty
        - air_qty
        - quick_qty
        - truck_qty
        - slow_qty
    )

    inventory_position_coverage_days = (
        inventory_position / daily if daily > 0 else None
    )
    sellable_stockout_date = (
        current_date + timedelta(days=max(0, math.floor(sellable_coverage_days)))
        if sellable_coverage_days is not None
        else None
    )
    urgent_warning = requires_faster_than_regular
    fastest_urgent = min(
        eligible_urgent,
        key=lambda item: int(item["planning_arrival_days"]),
        default=None,
    )
    urgent_too_late = bool(
        urgent_warning
        and stockout_date is not None
        and (
            fastest_urgent is None
            or stockout_date
            < parse_date(fastest_urgent["planning_arrival_date"])
        )
    )
    air_warning = urgent_warning
    air_too_late = urgent_too_late

    data_flags: list[str] = []
    data_notes: list[str] = []
    if daily <= 0:
        data_flags.append("近30天无有效销量")
    elif fbt_sellable <= 0:
        data_flags.append("当前断货，动态日均可能被断货日压低")
    if fbt_sellable > fbt_total:
        data_flags.append("FBT可售大于FBT已入仓库存")
    if abs(source_fbt_all - calculated_fbt_all) > 0.01:
        data_flags.append("领星FBT合计与已入仓加在途不一致")
    if unplaced_in_transit_qty > 0:
        data_notes.append(
            f"{round_quantity(unplaced_in_transit_qty)}件在途无法放入到货时间线"
        )
    if tracked_inbound_qty > 0 and abs(tracked_inbound_qty - fbt_in_transit) > 0.01:
        data_notes.append("IBR未签收量与FBT在途总数存在快照差异")
    if fbt_total == 0 and fbt_in_transit > 0:
        data_notes.append("当前FBT库存全部在途，尚未入仓")
    if overdue_inbound_qty > 0:
        data_notes.append(
            f"{round_quantity(overdue_inbound_qty)}件已过预计到货日但未全部接收"
        )
    if air_too_late:
        data_notes.append("按当前可售推算，即使最快加急渠道也存在断货窗口")
    if bridge_advanced_qty > 0:
        data_notes.append(
            f"{bridge_advanced_qty}件分配到更早的最终预计到货渠道，"
            "用于衔接后续到货并保留安全库存"
        )
    if cutoff_blocked_qty > 0:
        data_notes.append(
            f"{cutoff_blocked_qty}件无法在停止收货日前安排现有渠道"
        )
    ineligible_labels = [
        item["label"]
        for item in ordered_regular_plans
        if parse_date(item["arrival_date"]) >= cutoff
    ]
    if ineligible_labels and cutoff_blocked_qty <= 0:
        data_notes.append(
            f"{'、'.join(ineligible_labels)}晚于停止收货日，数量已前移到更早渠道"
        )
    disabled_labels = [
        plans_by_key[key]["label"]
        for key in CHANNEL_KEYS
        if not channel_enabled[key]
    ]
    if disabled_labels:
        data_notes.append(
            f"{'、'.join(disabled_labels)}已在参数设置中停用，不参与本周建议"
        )
    for item in same_arrival_skips:
        data_notes.append(
            f"{item['skipped_channel_label']}与"
            f"{item['selected_channel_label']}同为"
            f"{item['arrival_date']}最终到货，当前按渠道优先级由"
            f"{item['selected_channel_label']}承接"
        )
    if not product.get("product_name"):
        data_flags.append("商品名称缺失")

    if daily <= 0:
        risk = "no_sales"
        risk_rank = 4
    elif air_warning or cutoff_blocked_qty > 0:
        risk = "critical"
        risk_rank = 0
    elif express_qty > 0 or air_qty > 0 or quick_qty > 0:
        risk = "urgent"
        risk_rank = 1
    elif truck_qty > 0 or slow_qty > 0:
        risk = "attention"
        risk_rank = 2
    else:
        risk = "healthy"
        risk_rank = 3

    recommended_by_channel = {
        "express": express_qty,
        "air": air_qty,
        "quick": quick_qty,
        "truck": truck_qty,
        "slow": slow_qty,
    }
    enriched_channel_plans = [
        {
            **plan,
            "eligible_before_cutoff": (
                bool(plan.get("enabled", True))
                and parse_date(plan["arrival_date"]) < cutoff
            ),
            "recommended_qty": recommended_by_channel[plan["key"]],
        }
        for plan in channel_plans
    ]
    result = {
        **product,
        "planning_status": planning_status,
        "planning_status_label": PLANNING_STATUS_LABELS[planning_status],
        "is_planning_excluded": is_planning_excluded,
        "planned_dispatch_date": planned_dispatch_date.isoformat(),
        "dynamic_daily": round(daily, 3),
        "fbt_all": round(source_fbt_all, 2),
        "fbt_unavailable": round(max(0, fbt_total - fbt_sellable), 2),
        "executed_unsynced_qty": round(executed_unsynced, 2),
        "inventory_position": round(inventory_position, 2),
        "sellable_coverage_days": (
            round(sellable_coverage_days, 1)
            if sellable_coverage_days is not None
            else None
        ),
        "inventory_position_coverage_days": (
            round(inventory_position_coverage_days, 1)
            if inventory_position_coverage_days is not None
            else None
        ),
        "stockout_date": stockout_date.isoformat() if stockout_date else None,
        "sellable_stockout_date": (
            sellable_stockout_date.isoformat() if sellable_stockout_date else None
        ),
        "express_enabled": express_enabled,
        "air_enabled": air_enabled,
        "channel_signature": channel_signature,
        "decision_signature": decision_signature,
        "timing_mode": timing_mode,
        "air_service": "IE",
        "channel_plans": enriched_channel_plans,
        "express_arrival_date": plans_by_key["express"]["arrival_date"],
        "express_planning_arrival_date": plans_by_key["express"][
            "planning_arrival_date"
        ],
        "air_arrival_date": plans_by_key["air"]["arrival_date"],
        "air_planning_arrival_date": plans_by_key["air"][
            "planning_arrival_date"
        ],
        "quick_arrival_date": (
            plans_by_key["quick"]["arrival_date"]
            if channel_enabled["quick"]
            else None
        ),
        "quick_planning_arrival_date": (
            plans_by_key["quick"]["planning_arrival_date"]
            if channel_enabled["quick"]
            else None
        ),
        "truck_arrival_date": (
            plans_by_key["truck"]["arrival_date"]
            if channel_enabled["truck"]
            else None
        ),
        "truck_planning_arrival_date": (
            plans_by_key["truck"]["planning_arrival_date"]
            if channel_enabled["truck"]
            else None
        ),
        "slow_arrival_date": (
            plans_by_key["slow"]["arrival_date"]
            if channel_enabled["slow"]
            else None
        ),
        "slow_planning_arrival_date": (
            plans_by_key["slow"]["planning_arrival_date"]
            if channel_enabled["slow"]
            else None
        ),
        "regular_fastest_channel": fastest_regular["key"],
        "regular_fastest_channel_label": fastest_regular["label"],
        "seasonal_channel": seasonal_regular["key"],
        "seasonal_channel_label": seasonal_regular["label"],
        "normal_target_coverage_days": round(normal_target_coverage_days, 3),
        "quick_target_coverage_days": round(normal_target_coverage_days, 3),
        "normal_safety_buffer_days": normal_safety_buffer_days,
        "normal_dispatch_interval_days": normal_dispatch_interval_days,
        "review_interval_days": review_interval_days,
        "safety_buffer_days": safety_buffer_days,
        "dispatch_interval_days": dispatch_interval_days,
        "current_seasonal_coverage_days": current_seasonal_coverage_days,
        "next_seasonal_coverage_days": next_seasonal_coverage_days,
        "current_total_coverage_days": current_total_coverage_days,
        "next_total_coverage_days": next_total_coverage_days,
        "express_required_qty": express_required_qty,
        "air_required_qty": air_required_qty,
        "normal_target_units": round(normal_target_units, 2),
        "quick_target_units": round(normal_target_units, 2),
        "current_target_units": round(current_target_units, 2),
        "next_target_units": round(next_target_units, 2),
        "normal_available": round(normal_available, 2),
        "quick_available": round(normal_available, 2),
        "base_normal_qty": base_normal_qty,
        "base_quick_qty": base_normal_qty,
        "bridge_details": bridge_details,
        "same_arrival_skips": same_arrival_skips,
        "bridge_advanced_qty": bridge_advanced_qty,
        "express_qty": express_qty,
        "air_qty": air_qty,
        "quick_qty": quick_qty,
        "truck_qty": truck_qty,
        "slow_qty": slow_qty,
        "planned_ship_total": (
            express_qty + air_qty + quick_qty + truck_qty + slow_qty
        ),
        "current_gap": current_gap,
        "next_buy_gap": next_buy_gap,
        "tracked_inbound_qty": round(tracked_inbound_qty, 2),
        "dated_inbound_qty": round(dated_inbound_qty, 2),
        "unplaced_in_transit_qty": round(unplaced_in_transit_qty, 2),
        "overdue_inbound_qty": round(overdue_inbound_qty, 2),
        "cutoff_blocked_qty": cutoff_blocked_qty,
        "inbounds": active_inbounds,
        "planning_inbounds": [
            item
            for item in active_inbounds
            if item.get("eta_date")
            and not item.get("is_overdue")
            and not item.get("is_after_cutoff")
            and float(item.get("planning_qty") or 0) > 0
        ],
        "final_buy_qty": (
            decision.get("final_buy_qty") if decision_is_final else None
        ),
        "confirmed_express_qty": (
            decision.get("confirmed_express_qty")
            if decision_is_final and express_enabled
            else None
        ),
        "confirmed_air_qty": (
            decision.get("confirmed_air_qty")
            if decision_is_final and air_enabled
            else None
        ),
        "confirmed_quick_qty": (
            decision.get("confirmed_quick_qty")
            if decision_is_final and channel_enabled["quick"]
            else None
        ),
        "confirmed_truck_qty": (
            decision.get("confirmed_truck_qty")
            if decision_is_final and channel_enabled["truck"]
            else None
        ),
        "confirmed_slow_qty": (
            decision.get("confirmed_slow_qty")
            if decision_is_final and channel_enabled["slow"]
            else None
        ),
        "confirmed_scenario_nodes": (
            decision.get("scenario_nodes", [])
            if decision_is_final
            else []
        ),
        "draft_scenario_nodes": (
            decision.get("scenario_nodes", [])
            if decision_matches_mode
            and decision.get("review_status", "pending") == "pending"
            else []
        ),
        "draft_final_buy_qty": (
            decision.get("final_buy_qty")
            if decision_matches_mode
            and decision.get("review_status", "pending") == "pending"
            else None
        ),
        "decision_air_enabled": (
            decision_air_enabled if decision else None
        ),
        "decision_timing_mode": decision.get("timing_mode") if decision else None,
        "decision_air_service": decision.get("air_service") if decision else None,
        "decision_matches_mode": decision_matches_mode,
        "decision_is_final": decision_is_final,
        "review_status": (
            decision.get("review_status", "pending")
            if decision_matches_mode
            else "pending"
        ),
        "note": decision.get("note", ""),
        "decision_updated_at": (
            decision.get("updated_at") if decision_matches_mode else None
        ),
        "air_warning": air_warning,
        "air_too_late": air_too_late,
        "urgent_warning": urgent_warning,
        "urgent_too_late": urgent_too_late,
        "urgent_fastest_channel": (
            fastest_urgent["key"] if fastest_urgent else None
        ),
        "urgent_fastest_channel_label": (
            fastest_urgent["label"] if fastest_urgent else None
        ),
        "risk": risk,
        "risk_rank": risk_rank,
        "data_flags": data_flags,
        "data_notes": data_notes,
    }
    for channel_key in CHANNEL_KEYS:
        confirmed_qty = result.get(f"confirmed_{channel_key}_qty")
        result[f"effective_{channel_key}_qty"] = (
            confirmed_qty
            if confirmed_qty is not None
            else result.get(f"{channel_key}_qty", 0)
        )
    result["effective_planned_ship_total"] = sum(
        float(result[f"effective_{channel_key}_qty"] or 0)
        for channel_key in CHANNEL_KEYS
    )
    result["effective_next_buy_gap"] = round_quantity(
        next_target_units
        - inventory_position
        - result["effective_planned_ship_total"]
    )
    result["effective_buy_qty"] = (
        float(result["final_buy_qty"])
        if decision_is_final and result["final_buy_qty"] is not None
        else result["effective_next_buy_gap"]
    )
    result["effective_quantity_source"] = (
        "manual" if decision_is_final else "system"
    )
    if is_planning_excluded:
        result["suppressed_recommendation"] = {
            "express_qty": result["express_qty"],
            "air_qty": result["air_qty"],
            "quick_qty": result["quick_qty"],
            "truck_qty": result["truck_qty"],
            "slow_qty": result["slow_qty"],
            "planned_ship_total": result["planned_ship_total"],
            "next_buy_gap": result["next_buy_gap"],
        }
        for key in (
            "express_required_qty",
            "air_required_qty",
            "base_normal_qty",
            "base_quick_qty",
            "bridge_advanced_qty",
            "express_qty",
            "air_qty",
            "quick_qty",
            "truck_qty",
            "slow_qty",
            "planned_ship_total",
            "current_gap",
            "next_buy_gap",
            "cutoff_blocked_qty",
        ):
            result[key] = 0
        for key in (
            "confirmed_express_qty",
            "confirmed_air_qty",
            "confirmed_quick_qty",
            "confirmed_truck_qty",
            "confirmed_slow_qty",
            "final_buy_qty",
            "effective_express_qty",
            "effective_air_qty",
            "effective_quick_qty",
            "effective_truck_qty",
            "effective_slow_qty",
            "effective_planned_ship_total",
            "effective_next_buy_gap",
            "effective_buy_qty",
        ):
            result[key] = 0
        result["bridge_details"] = []
        result["air_warning"] = False
        result["air_too_late"] = False
        result["urgent_warning"] = False
        result["urgent_too_late"] = False
        result["risk"] = "excluded"
        result["risk_rank"] = 5
        result["channel_plans"] = [
            {**plan, "recommended_qty": 0}
            for plan in result["channel_plans"]
        ]
        result["data_notes"] = [
            *result["data_notes"],
            f"商品已标记为{PLANNING_STATUS_LABELS[planning_status]}，不参与发货和备货建议",
        ]
    return result


def recalculate_scenario_plan(
    recommendation: dict[str, Any],
    settings: dict[str, Any],
    as_of: str | date | None,
    nodes: list[dict[str, Any]],
    executed_unsynced_qty: float | None = None,
) -> dict[str, Any]:
    """Reallocate one product across user-selected dispatch/arrival nodes."""
    current_date = parse_date(as_of)
    cutoff = parse_date(settings["receiving_cutoff"])
    daily = max(0.0, float(recommendation.get("dynamic_daily") or 0))
    raw_executed_unsynced = (
        recommendation.get("executed_unsynced_qty") or 0
        if executed_unsynced_qty is None
        else executed_unsynced_qty
    )
    executed_unsynced = max(0.0, float(raw_executed_unsynced))
    fbt_total = max(0.0, float(recommendation.get("fbt_total") or 0))
    fbt_sellable = max(
        0.0,
        float(recommendation.get("fbt_sellable") or 0),
    )
    fbt_in_transit = max(
        0.0,
        float(recommendation.get("fbt_in_transit") or 0),
    )
    inventory_position = fbt_total + fbt_in_transit + executed_unsynced

    normalized_nodes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, source in enumerate(nodes):
        channel_key = str(source.get("channel_key") or "").strip().lower()
        if channel_key not in CHANNEL_KEYS:
            raise ValueError(f"未知物流渠道：{channel_key or '空'}")

        dispatch_date = parse_date(
            source.get("dispatch_date")
            or recommendation.get("planned_dispatch_date")
            or current_date
        )
        if dispatch_date < current_date:
            raise ValueError("情景发货日期不能早于当前计算日期")

        plan = next(
            item
            for item in build_channel_plans(settings, dispatch_date)
            if item["key"] == channel_key
        )
        if not plan.get("enabled", True):
            raise ValueError(f"{plan['label']}已在参数设置中停用")

        requested_arrival = str(source.get("arrival_date") or "").strip()
        if requested_arrival:
            arrival_date = parse_date(requested_arrival)
            if arrival_date < dispatch_date:
                raise ValueError("预计入仓日不能早于计划发货日")
            plan.update(
                {
                    "arrival_date": arrival_date.isoformat(),
                    "planning_arrival_date": arrival_date.isoformat(),
                    "buffered_arrival_date": arrival_date.isoformat(),
                    "base_arrival_date": arrival_date.isoformat(),
                    "logistics_eta_date": arrival_date.isoformat(),
                    "manual_arrival_override": True,
                }
            )
        else:
            arrival_date = parse_date(plan["planning_arrival_date"])
            plan["manual_arrival_override"] = False

        node_id = str(source.get("id") or f"scenario-{index + 1}").strip()
        if not node_id or node_id in seen_ids:
            node_id = f"scenario-{index + 1}"
        while node_id in seen_ids:
            node_id = f"{node_id}-{index + 1}"
        seen_ids.add(node_id)

        arrival_days = max(0, (arrival_date - current_date).days)
        requested_quantity = round_quantity(
            max(0.0, float(source.get("quantity") or 0))
        )
        quantity_locked = bool(source.get("quantity_locked", False))
        normalized_nodes.append(
            {
                **plan,
                "id": node_id,
                "channel_key": channel_key,
                "planned_dispatch_date": dispatch_date.isoformat(),
                "dispatch_date": dispatch_date.isoformat(),
                "planning_arrival_date": arrival_date.isoformat(),
                "arrival_date": arrival_date.isoformat(),
                "planning_arrival_days": arrival_days,
                "arrival_days": arrival_days,
                "eligible_before_cutoff": arrival_date < cutoff,
                "requested_quantity": requested_quantity,
                "quantity_locked": quantity_locked,
                "auto_generated": bool(source.get("auto_generated", False)),
                "quantity": requested_quantity if quantity_locked else 0,
            }
        )

    normalized_nodes.sort(
        key=lambda item: (
            int(item["planning_arrival_days"]),
            CHANNEL_KEYS.index(item["channel_key"]),
            item["id"],
        )
    )
    eligible_nodes = [
        item for item in normalized_nodes if item["eligible_before_cutoff"]
    ]

    active_inbounds = list(recommendation.get("inbounds") or [])
    if eligible_nodes:
        normal_target_coverage_days = float(
            eligible_nodes[0]["planning_arrival_days"]
        )
    else:
        normal_target_coverage_days = float(
            recommendation.get("normal_target_coverage_days") or 0
        )
    normal_receipts = _receipts_by_day(
        active_inbounds,
        current_date,
        normal_target_coverage_days,
    )
    normal_available = fbt_total + executed_unsynced + normal_receipts
    normal_target_units = daily * normal_target_coverage_days
    base_normal_qty = round_quantity(normal_target_units - normal_available)
    current_target_units = max(
        0.0,
        float(recommendation.get("current_target_units") or 0),
    )
    current_gap = round_quantity(current_target_units - inventory_position)
    base_ship_total = max(base_normal_qty, current_gap)

    # User nodes define the visible plan. Missing enabled channels at the same
    # dispatch date, plus one review interval later, are kept as hidden rescue
    # candidates. They are returned only when the balance equation needs them.
    represented = {
        (node["channel_key"], node["dispatch_date"])
        for node in normalized_nodes
    }
    dispatch_dates = {
        parse_date(
            recommendation.get("planned_dispatch_date") or current_date
        )
    }
    dispatch_dates.update(
        parse_date(node["dispatch_date"]) for node in normalized_nodes
    )
    review_interval = max(
        1,
        math.ceil(float(recommendation.get("review_interval_days") or 7)),
    )
    dispatch_dates.update(
        item + timedelta(days=review_interval)
        for item in list(dispatch_dates)
    )
    auto_candidates: list[dict[str, Any]] = []
    for dispatch_date in sorted(dispatch_dates):
        for plan in build_channel_plans(settings, dispatch_date):
            signature = (plan["key"], dispatch_date.isoformat())
            arrival_date = parse_date(plan["planning_arrival_date"])
            if (
                not plan.get("enabled", True)
                or signature in represented
                or arrival_date >= cutoff
            ):
                continue
            arrival_days = max(0, (arrival_date - current_date).days)
            auto_candidates.append(
                {
                    **plan,
                    "id": (
                        f"auto-{plan['key']}-"
                        f"{dispatch_date.isoformat()}"
                    ),
                    "channel_key": plan["key"],
                    "planned_dispatch_date": dispatch_date.isoformat(),
                    "dispatch_date": dispatch_date.isoformat(),
                    "planning_arrival_date": arrival_date.isoformat(),
                    "arrival_date": arrival_date.isoformat(),
                    "planning_arrival_days": arrival_days,
                    "arrival_days": arrival_days,
                    "eligible_before_cutoff": True,
                    "requested_quantity": 0,
                    "quantity_locked": False,
                    "auto_generated": True,
                    "manual_arrival_override": False,
                    "quantity": 0,
                }
            )
    optimization_nodes = [*normalized_nodes, *auto_candidates]
    horizon_days = max(
        1,
        min(
            365,
            math.ceil(
                max(
                    normal_target_coverage_days,
                    float(
                        recommendation.get("current_total_coverage_days")
                        or 0
                    ),
                )
            ),
        ),
    )
    optimized = _optimize_inventory_balance(
        start_inventory=fbt_sellable,
        daily=daily,
        active_inbounds=active_inbounds,
        current_date=current_date,
        nodes=optimization_nodes,
        target_ship_total=base_ship_total,
        horizon_days=horizon_days,
    )
    allocation = optimized["allocation"]
    positive_auto_nodes = [
        node
        for node in auto_candidates
        if allocation.get(node["id"], 0) > 0
    ]
    visible_normalized_nodes = [
        node
        for node in normalized_nodes
        if not (
            node.get("auto_generated")
            and not node.get("quantity_locked")
            and allocation.get(node["id"], 0) <= 0
        )
    ]
    enriched_nodes = [
        {
            **node,
            "quantity": allocation.get(node["id"], 0),
        }
        for node in [*visible_normalized_nodes, *positive_auto_nodes]
    ]
    enriched_nodes.sort(
        key=lambda item: (
            int(item["planning_arrival_days"]),
            CHANNEL_KEYS.index(item["channel_key"]),
            item["id"],
        )
    )
    nodes_by_id = {node["id"]: node for node in optimization_nodes}
    bridge_details = [
        {
            **detail,
            "channel_label": nodes_by_id[detail["node_id"]]["label"],
            "allocated_qty": detail["required_qty"],
        }
        for detail in optimized["daily_requirements"]
    ]
    blocked_locked_qty = sum(
        int(node["requested_quantity"])
        for node in normalized_nodes
        if node.get("quantity_locked")
        and not node["eligible_before_cutoff"]
    )
    cutoff_blocked_qty = (
        int(optimized["target_blocked_qty"]) + blocked_locked_qty
    )
    recommended_by_channel = {key: 0 for key in CHANNEL_KEYS}
    for node in enriched_nodes:
        recommended_by_channel[node["channel_key"]] += int(node["quantity"])
    planned_ship_total = int(optimized["planned_ship_total"])
    next_buy_gap = round_quantity(
        float(recommendation.get("next_target_units") or 0)
        - inventory_position
        - planned_ship_total
    )

    notes: list[str] = []
    if not normalized_nodes:
        notes.append("尚未添加发货节点")
    blocked_nodes = [
        node for node in normalized_nodes if not node["eligible_before_cutoff"]
    ]
    if blocked_nodes:
        notes.append(
            f"{len(blocked_nodes)}个节点晚于停止收货日，不参与数量分配"
        )
    if cutoff_blocked_qty > 0:
        notes.append(
            f"{cutoff_blocked_qty}件无法在停止收货日前安排到有效节点"
        )
    if optimized["uncovered_shortage_qty"] > 0:
        notes.append(
            f"最早在{optimized['first_uncovered_date']}仍缺"
            f"{optimized['uncovered_shortage_qty']}件；现有启用渠道均无法及时到达"
        )
    if positive_auto_nodes:
        notes.append(
            f"系统为迎合人工固定量，自动新增{len(positive_auto_nodes)}个接力节点"
        )

    return {
        "nodes": enriched_nodes,
        "recommended_by_channel": recommended_by_channel,
        "normal_target_coverage_days": round(
            normal_target_coverage_days,
            3,
        ),
        "normal_target_units": round(normal_target_units, 2),
        "normal_available": round(normal_available, 2),
        "base_normal_qty": base_normal_qty,
        "current_gap": current_gap,
        "base_ship_total": base_ship_total,
        "planned_ship_total": planned_ship_total,
        "locked_ship_total": optimized["locked_ship_total"],
        "auto_adjusted_total": optimized["auto_adjusted_total"],
        "stockout_protected": optimized["stockout_protected"],
        "uncovered_shortage_qty": optimized["uncovered_shortage_qty"],
        "first_uncovered_date": optimized["first_uncovered_date"],
        "next_buy_gap": next_buy_gap,
        "inventory_position": round(inventory_position, 2),
        "bridge_details": bridge_details,
        "cutoff_blocked_qty": cutoff_blocked_qty,
        "notes": notes,
    }


def build_forecast(
    recommendation: dict[str, Any],
    settings: dict[str, Any],
    as_of: str | date | None,
) -> dict[str, Any]:
    current_date = parse_date(as_of)
    cutoff = parse_date(settings["receiving_cutoff"])
    horizon_days = max(120, min(180, (cutoff - current_date).days + 14))
    daily = float(recommendation["dynamic_daily"])
    start_inventory = float(recommendation["fbt_sellable"])

    confirmed_express = recommendation.get("confirmed_express_qty")
    confirmed_air = recommendation.get("confirmed_air_qty")
    confirmed_quick = recommendation.get("confirmed_quick_qty")
    confirmed_truck = recommendation.get("confirmed_truck_qty")
    confirmed_slow = recommendation.get("confirmed_slow_qty")
    quantities = {
        "express": (
            (
                float(confirmed_express)
                if confirmed_express is not None
                else float(recommendation["express_qty"])
            )
            if recommendation.get("express_enabled")
            else 0.0
        ),
        "air": (
            (
                float(confirmed_air)
                if confirmed_air is not None
                else float(recommendation["air_qty"])
            )
            if recommendation.get("air_enabled")
            else 0.0
        ),
        "quick": (
            float(confirmed_quick)
            if confirmed_quick is not None
            else float(recommendation["quick_qty"])
        ),
        "truck": (
            float(confirmed_truck)
            if confirmed_truck is not None
            else float(recommendation["truck_qty"])
        ),
        "slow": (
            float(confirmed_slow)
            if confirmed_slow is not None
            else float(recommendation["slow_qty"])
        ),
    }
    saved_scenario_nodes = recommendation.get("confirmed_scenario_nodes") or []
    if saved_scenario_nodes:
        planned_channels = [
            {
                **node,
                "key": node.get("channel_key") or node.get("key"),
                "quantity": float(node.get("quantity") or 0),
                "actual_day_offset": max(
                    0,
                    (
                        parse_date(
                            node.get("arrival_date")
                            or node["planning_arrival_date"]
                        )
                        - current_date
                    ).days,
                ),
                "day_offset": max(
                    0,
                    (
                        parse_date(node["planning_arrival_date"])
                        - current_date
                    ).days,
                ),
            }
            for node in saved_scenario_nodes
            if float(node.get("quantity") or 0) > 0
        ]
    else:
        planned_channels = [
            {
                **plan,
                "quantity": quantities[plan["key"]],
                "actual_day_offset": max(
                    0,
                    (
                        parse_date(
                            plan.get("base_arrival_date")
                            or plan["arrival_date"]
                        )
                        - current_date
                    ).days,
                ),
                "day_offset": max(
                    0,
                    (
                        parse_date(plan["planning_arrival_date"])
                        - current_date
                    ).days,
                ),
            }
            for plan in recommendation.get("channel_plans", [])
            if quantities.get(plan["key"], 0) > 0
        ]

    dates: list[str] = []
    baseline: list[float] = []
    planned: list[float] = []
    planned_actual: list[float] = []
    safety: list[float] = []
    target: list[float] = []
    existing_arrivals = [
        {
            "date": item["eta_date"],
            "channel": "往期IBR",
            "quantity": round_quantity(
                float(item.get("planning_qty", item["remaining_qty"]))
            ),
            "kind": "existing",
            "cargo_code": item.get("cargo_code", ""),
            "tracking_number": item.get("tracking_number", ""),
        }
        for item in recommendation.get("inbounds", [])
        if item.get("eta_date")
        and not item.get("is_overdue")
        and not item.get("is_after_cutoff")
        and float(item.get("planning_qty", item["remaining_qty"])) > 0
    ]
    existing_by_day: dict[int, float] = {}
    for item in existing_arrivals:
        offset = (parse_date(item["date"]) - current_date).days
        if offset >= 0:
            existing_by_day[offset] = existing_by_day.get(offset, 0.0) + float(
                item["quantity"]
            )
    cumulative_existing = 0.0

    for day_offset in range(horizon_days + 1):
        point_date = current_date + timedelta(days=day_offset)
        cumulative_existing += existing_by_day.get(day_offset, 0.0)
        base_value = start_inventory - daily * day_offset + cumulative_existing
        planned_value = base_value
        actual_value = base_value
        for channel in planned_channels:
            if day_offset >= channel["day_offset"]:
                planned_value += channel["quantity"]
            if day_offset >= channel["actual_day_offset"]:
                actual_value += channel["quantity"]

        dates.append(point_date.isoformat())
        baseline.append(round(base_value, 2))
        planned.append(round(planned_value, 2))
        planned_actual.append(round(actual_value, 2))
        safety.append(
            round(
                daily
                * float(recommendation["normal_safety_buffer_days"]),
                2,
            )
        )
        target.append(round(float(recommendation["current_target_units"]), 2))

    arrivals = existing_arrivals
    for channel in planned_channels:
        arrivals.append(
            {
                "date": channel["planning_arrival_date"],
                "actual_date": channel.get("base_arrival_date")
                or channel["arrival_date"],
                "buffered_date": channel["planning_arrival_date"],
                "channel": channel["label"],
                "channel_key": channel["key"],
                "quantity": round_quantity(channel["quantity"]),
                "kind": "planned",
            }
        )

    return {
        "dates": dates,
        "baseline": baseline,
        "planned": planned,
        "planned_actual": planned_actual,
        "planned_buffered": planned,
        "safety": safety,
        "target": target,
        "arrivals": arrivals,
        "channel_plans": planned_channels,
        "next_review_date": (
            current_date
            + timedelta(
                days=math.ceil(
                    float(recommendation["normal_dispatch_interval_days"])
                    if recommendation.get("review_interval_days") is None
                    else float(recommendation["review_interval_days"])
                )
            )
        ).isoformat(),
        "cutoff_date": cutoff.isoformat(),
        "in_transit_unknown": recommendation["unplaced_in_transit_qty"],
        "note": (
            "蓝线已计入有预计到货日的往期IBR；没有日期的在途只参与总账，"
            "不会提前抬高库存曲线。橙线在蓝线基础上叠加本次建议，"
            "渠道时效范围统一取最慢值；安全+频率模式把两项缓冲都加入"
            "最终到货日，精准船期模式则用截单和开船等待替代海运发货频率。"
        ),
    }


def build_summary(products: list[dict[str, Any]]) -> dict[str, Any]:
    planning_products = [
        item for item in products if not item.get("is_planning_excluded")
    ]
    fastest_days = min(
        (
            float(item.get("normal_target_coverage_days") or 0)
            for item in planning_products
            if float(item.get("normal_target_coverage_days") or 0) > 0
        ),
        default=36,
    )
    mid_days = max(fastest_days, 60)
    coverage = {
        f"少于{round_quantity(fastest_days)}天": 0,
        f"{round_quantity(fastest_days)}-{round_quantity(mid_days)}天": 0,
        f"{round_quantity(mid_days)}-90天": 0,
        "90天以上": 0,
        "无有效销量": 0,
    }
    for item in planning_products:
        days = item["sellable_coverage_days"]
        if days is None:
            coverage["无有效销量"] += 1
        elif days < fastest_days:
            coverage[f"少于{round_quantity(fastest_days)}天"] += 1
        elif days < mid_days:
            coverage[
                f"{round_quantity(fastest_days)}-{round_quantity(mid_days)}天"
            ] += 1
        elif days < 90:
            coverage[f"{round_quantity(mid_days)}-90天"] += 1
        else:
            coverage["90天以上"] += 1

    return {
        "product_count": len(products),
        "planning_product_count": len(planning_products),
        "excluded_product_count": len(products) - len(planning_products),
        "ship_sku_count": sum(
            1
            for item in planning_products
            if float(
                item.get(
                    "effective_planned_ship_total",
                    item.get("planned_ship_total", 0),
                )
                or 0
            ) > 0
        ),
        "ship_total_qty": sum(
            float(
                item.get(
                    "effective_planned_ship_total",
                    item.get("planned_ship_total", 0),
                )
                or 0
            )
            for item in planning_products
        ),
        "express_enabled": any(
            item["express_enabled"] for item in planning_products
        ),
        "express_sku_count": sum(
            1
            for item in planning_products
            if float(item.get("effective_express_qty", item["express_qty"]) or 0)
            > 0
        ),
        "express_total_qty": sum(
            float(item.get("effective_express_qty", item["express_qty"]) or 0)
            for item in planning_products
        ),
        "air_enabled": any(item["air_enabled"] for item in planning_products),
        "air_sku_count": sum(
            1
            for item in planning_products
            if float(item.get("effective_air_qty", item["air_qty"]) or 0) > 0
        ),
        "air_total_qty": sum(
            float(item.get("effective_air_qty", item["air_qty"]) or 0)
            for item in planning_products
        ),
        "quick_total_qty": sum(
            float(item.get("effective_quick_qty", item["quick_qty"]) or 0)
            for item in planning_products
        ),
        "truck_total_qty": sum(
            float(item.get("effective_truck_qty", item["truck_qty"]) or 0)
            for item in planning_products
        ),
        "slow_total_qty": sum(
            float(item.get("effective_slow_qty", item["slow_qty"]) or 0)
            for item in planning_products
        ),
        "air_warning_count": sum(
            1 for item in planning_products if item["air_warning"]
        ),
        "urgent_total_qty": sum(
            float(item.get("effective_express_qty", item["express_qty"]) or 0)
            + float(item.get("effective_air_qty", item["air_qty"]) or 0)
            for item in planning_products
        ),
        "urgent_sku_count": sum(
            1
            for item in planning_products
            if float(item.get("effective_express_qty", item["express_qty"]) or 0)
            > 0
            or float(item.get("effective_air_qty", item["air_qty"]) or 0) > 0
        ),
        "buy_sku_count": sum(
            1
            for item in planning_products
            if float(
                item.get("effective_buy_qty", item.get("next_buy_gap", 0)) or 0
            )
            > 0
        ),
        "buy_total_qty": sum(
            float(
                item.get("effective_buy_qty", item.get("next_buy_gap", 0)) or 0
            )
            for item in planning_products
        ),
        "data_issue_count": sum(
            1 for item in planning_products if item["data_flags"]
        ),
        "coverage": coverage,
    }
