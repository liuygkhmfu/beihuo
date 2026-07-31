from __future__ import annotations

from datetime import date
from typing import Any

from .arrival_tracking import expected_receive_from_tracking
from .domain import (
    build_forecast,
    build_summary,
    calculate_recommendation,
    parse_date,
    recalculate_scenario_plan,
    schedule_context,
)
from .product_groups import (
    aggregate_product_groups,
    canonical_msku,
    product_group_key,
)
from .repository import Repository


class NoSnapshotError(RuntimeError):
    pass


def _shipment_views(
    repository: Repository, as_of: str | date | None
) -> list[dict[str, Any]]:
    current_date = parse_date(as_of)
    arrival_batches = repository.get_arrival_batches()
    tracking_dates = [
        parse_date(item["shipment_date"])
        for item in arrival_batches
        if item.get("shipment_date")
    ]
    tracking_start_date = min(tracking_dates) if tracking_dates else None
    arrivals_by_cargo = {
        item["cargo_code"]: item
        for item in arrival_batches
        if item.get("cargo_code")
    }
    views: list[dict[str, Any]] = []
    for source in repository.get_shipments():
        arrival = arrivals_by_cargo.pop(source["cargo_code"], {})
        order = source.get("shipping_order") or {}
        expected_signed_date = (
            source.get("manual_port_arrival_date")
            or arrival.get("actual_signed_date")
            or arrival.get("expected_signed_date")
            or arrival.get("port_arrival_date")
        )
        imported_receive_date = (
            expected_receive_from_tracking(arrival)
            if arrival
            else None
        )
        automatic_receive_date = None
        departure_floor = source.get("delivery_time") or source.get("create_time")
        for candidate in (
            source.get("expected_delivery_time"),
            order.get("arrival_time"),
            order.get("expected_arrival_time"),
        ):
            if not candidate:
                continue
            if departure_floor and parse_date(candidate) < parse_date(departure_floor):
                continue
            automatic_receive_date = candidate
            break
        expected_receive_date = (
            source.get("manual_expected_receive_date")
            or imported_receive_date
            or source.get("manual_expected_delivery_date")
            or automatic_receive_date
        )
        actual_signed_date = (
            source.get("manual_actual_signed_date")
            or arrival.get("actual_signed_date")
        )
        actual_receive_date = (
            source.get("manual_actual_receive_date")
            or arrival.get("actual_receive_date")
        )
        arrival_items = {
            str(item.get("matched_msku") or ""): item
            for item in arrival.get("items", [])
            if item.get("matched_msku")
        }
        items = []
        for item in source.get("items", []):
            reported_shipment_qty = float(item.get("shipment_qty") or 0)
            signed_qty = float(item.get("signed_qty") or 0)
            received_qty = float(item.get("received_qty") or 0)
            shipment_qty = max(reported_shipment_qty, signed_qty, received_qty)
            imported_item = arrival_items.get(str(item.get("msku") or ""), {})
            items.append(
                {
                    "cargo_code": source["cargo_code"],
                    "store_id": str(item.get("store_id") or source.get("store_id") or ""),
                    "store_name": source.get("store_name", ""),
                    "msku": str(item.get("msku") or ""),
                    "sku": str(item.get("sku") or ""),
                    "product_name": str(item.get("product_name") or ""),
                    "image_url": str(item.get("image_url") or ""),
                    "declaration_qty": float(item.get("declaration_qty") or 0),
                    "shipment_qty": shipment_qty,
                    "reported_shipment_qty": reported_shipment_qty,
                    "signed_qty": signed_qty,
                    "received_qty": received_qty,
                    "unsigned_qty": max(0.0, shipment_qty - signed_qty),
                    "awaiting_receive_qty": max(0.0, signed_qty - received_qty),
                    "remaining_qty": max(0.0, shipment_qty - received_qty),
                    "arrival_item_id": imported_item.get("id", ""),
                    "raw_sku": imported_item.get("raw_sku", ""),
                    "match_status": imported_item.get("match_status", ""),
                    "match_method": imported_item.get("match_method", ""),
                }
            )
        remaining_qty = sum(item["remaining_qty"] for item in items)
        shipment_qty = sum(item["shipment_qty"] for item in items)
        signed_qty = sum(item["signed_qty"] for item in items)
        received_qty = sum(item["received_qty"] for item in items)
        unsigned_qty = sum(item["unsigned_qty"] for item in items)
        awaiting_receive_qty = sum(item["awaiting_receive_qty"] for item in items)
        status_text = " ".join(
            [
                str(source.get("order_status_name") or ""),
                str(source.get("ship_status") or ""),
            ]
        )
        has_shipment_qty = shipment_qty > 0
        is_received = bool(
            "已全部接收" in status_text
            or arrival.get("is_fully_received")
            or actual_receive_date
            or (shipment_qty > 0 and received_qty >= shipment_qty)
        )
        if is_received and remaining_qty > 0:
            for item in items:
                item["source_signed_qty"] = item["signed_qty"]
                item["source_received_qty"] = item["received_qty"]
                item["signed_qty"] = item["shipment_qty"]
                item["received_qty"] = item["shipment_qty"]
                item["unsigned_qty"] = 0.0
                item["awaiting_receive_qty"] = 0.0
                item["remaining_qty"] = 0.0
            signed_qty = shipment_qty
            received_qty = shipment_qty
            unsigned_qty = 0.0
            awaiting_receive_qty = 0.0
            remaining_qty = 0.0
        source_shipment_date = source.get("delivery_time") or source.get("create_time")
        is_archived = bool(
            tracking_start_date
            and not is_received
            and not arrival
            and remaining_qty > 0
            and source_shipment_date
            and parse_date(source_shipment_date) < tracking_start_date
        )
        is_overdue = bool(
            not is_received
            and not is_archived
            and has_shipment_qty
            and expected_receive_date
            and parse_date(expected_receive_date) < current_date
        )
        is_shipped = bool(
            source.get("delivery_time")
            or "已发货" in status_text
            or str(order.get("status") or "") == "2"
        )
        if is_received:
            status_code = "received"
            status_name = "已全部接收"
        elif is_archived:
            status_code = "archived"
            status_name = "历史归档"
        elif not has_shipment_qty:
            status_code = "empty"
            status_name = "无发货量"
        elif is_overdue:
            status_code = "overdue"
            status_name = "逾期未接收"
        elif awaiting_receive_qty > 0 or actual_signed_date:
            status_code = "awaiting_receive"
            status_name = "已签收待FBT接收"
        elif is_shipped:
            status_code = "in_transit"
            status_name = "运输中"
        else:
            status_code = "pending"
            status_name = "待发货"
        views.append(
            {
                "cargo_code": source["cargo_code"],
                "shipping_list_code": source.get("shipping_list_code", ""),
                "store_id": source.get("store_id", ""),
                "store_name": source.get("store_name", ""),
                "shipping_warehouse": source.get("shipping_warehouse", ""),
                "order_status_name": source.get("order_status_name", ""),
                "ship_status": source.get("ship_status", ""),
                "status": status_code,
                "status_name": status_name,
                "is_received": is_received,
                "is_archived": is_archived,
                "is_overdue": is_overdue,
                "source_kind": "api",
                "is_api_synced": True,
                "create_time": source.get("create_time"),
                "delivery_time": source.get("delivery_time"),
                "departure_date": (
                    source.get("manual_departure_date")
                    or arrival.get("departure_date")
                    or source.get("delivery_time")
                ),
                "port_arrival_date": (
                    source.get("manual_port_arrival_date")
                    or arrival.get("port_arrival_date")
                ),
                "expected_signed_date": expected_signed_date,
                "actual_signed_date": actual_signed_date,
                "expected_receive_date": expected_receive_date,
                "actual_receive_date": actual_receive_date,
                "expected_delivery_date": expected_receive_date,
                "actual_delivery_time": source.get("actual_delivery_time"),
                "logistics_provider": source.get("logistics_provider", ""),
                "logistics_channel": source.get("logistics_channel", ""),
                "logistics_type": source.get("logistics_type", ""),
                "order_logistics_status": source.get("order_logistics_status", ""),
                "carrier": source.get("carrier") or arrival.get("carrier", ""),
                "tracking_number": source.get("tracking_number")
                or arrival.get("tracking_number", ""),
                "tracking_numbers": source.get("tracking_numbers", []),
                "manual_expected_delivery_date": source.get(
                    "manual_expected_delivery_date"
                ),
                "manual_note": source.get("manual_note", ""),
                "manual_updated_at": source.get("manual_updated_at"),
                "source_updated_at": source.get("source_updated_at"),
                "batch_label": arrival.get("batch_label", ""),
                "status_note": arrival.get("status_note", ""),
                "route_note": arrival.get("route_note", ""),
                "metric_f": arrival.get("metric_f"),
                "metric_g": arrival.get("metric_g"),
                "metric_h": arrival.get("metric_h"),
                "arrival_batch_id": arrival.get("id", ""),
                "shipment_qty": round(shipment_qty, 2),
                "signed_qty": round(signed_qty, 2),
                "received_qty": round(received_qty, 2),
                "unsigned_qty": round(unsigned_qty, 2),
                "awaiting_receive_qty": round(awaiting_receive_qty, 2),
                "remaining_qty": round(remaining_qty, 2),
                "items": items,
            }
        )

    catalog = {
        (str(item.get("store_id") or ""), str(item.get("msku") or "")): item
        for item in repository.get_product_match_catalog()
    }
    for arrival in arrivals_by_cargo.values():
        items = []
        for item in arrival.get("items", []):
            product = catalog.get(
                (
                    str(item.get("matched_store_id") or arrival.get("store_id") or ""),
                    str(item.get("matched_msku") or ""),
                ),
                {},
            )
            shipment_qty = float(item.get("shipment_qty") or 0)
            signed_qty = shipment_qty if arrival.get("actual_signed_date") else 0.0
            received_qty = shipment_qty if arrival.get("is_fully_received") else 0.0
            items.append(
                {
                    "cargo_code": arrival.get("cargo_code", ""),
                    "store_id": item.get("matched_store_id")
                    or arrival.get("store_id", ""),
                    "store_name": product.get("store_name", ""),
                    "msku": item.get("matched_msku") or item.get("raw_sku", ""),
                    "sku": item.get("matched_sku", ""),
                    "raw_sku": item.get("raw_sku", ""),
                    "product_name": item.get("product_name", ""),
                    "image_url": "",
                    "declaration_qty": shipment_qty,
                    "shipment_qty": shipment_qty,
                    "signed_qty": signed_qty,
                    "received_qty": received_qty,
                    "unsigned_qty": max(0.0, shipment_qty - signed_qty),
                    "awaiting_receive_qty": max(0.0, signed_qty - received_qty),
                    "remaining_qty": max(0.0, shipment_qty - received_qty),
                    "arrival_item_id": item.get("id", ""),
                    "match_status": item.get("match_status", ""),
                    "match_method": item.get("match_method", ""),
                }
            )
        shipment_qty = sum(item["shipment_qty"] for item in items)
        signed_qty = sum(item["signed_qty"] for item in items)
        received_qty = sum(item["received_qty"] for item in items)
        expected_receive_date = expected_receive_from_tracking(arrival)
        is_received = bool(arrival.get("is_fully_received"))
        is_overdue = bool(
            not is_received
            and expected_receive_date
            and parse_date(expected_receive_date) < current_date
        )
        if is_received:
            status_code, status_name = "received", "已全部接收"
        elif is_overdue:
            status_code, status_name = "overdue", "逾期未接收"
        elif arrival.get("actual_signed_date"):
            status_code, status_name = "awaiting_receive", "已签收待FBT接收"
        else:
            status_code, status_name = "manual_pending", "待领星同步"
        views.append(
            {
                "cargo_code": arrival.get("cargo_code") or arrival["id"],
                "shipping_list_code": "",
                "store_id": arrival.get("store_id", ""),
                "store_name": next(
                    (item["store_name"] for item in items if item["store_name"]), ""
                ),
                "shipping_warehouse": "",
                "order_status_name": "人工到货跟踪表",
                "ship_status": "",
                "status": status_code,
                "status_name": status_name,
                "is_received": is_received,
                "is_archived": False,
                "is_overdue": is_overdue,
                "source_kind": "manual",
                "is_api_synced": False,
                "create_time": arrival.get("shipment_date"),
                "delivery_time": arrival.get("shipment_date"),
                "departure_date": arrival.get("departure_date"),
                "port_arrival_date": arrival.get("port_arrival_date"),
                "expected_signed_date": arrival.get("expected_signed_date"),
                "actual_signed_date": arrival.get("actual_signed_date"),
                "expected_receive_date": expected_receive_date,
                "actual_receive_date": arrival.get("actual_receive_date"),
                "expected_delivery_date": expected_receive_date,
                "actual_delivery_time": None,
                "logistics_provider": "",
                "logistics_channel": "",
                "logistics_type": "",
                "order_logistics_status": "",
                "carrier": arrival.get("carrier", ""),
                "tracking_number": arrival.get("tracking_number", ""),
                "tracking_numbers": [],
                "manual_expected_delivery_date": None,
                "manual_note": arrival.get("status_note", ""),
                "manual_updated_at": arrival.get("updated_at"),
                "source_updated_at": arrival.get("updated_at"),
                "batch_label": arrival.get("batch_label", ""),
                "status_note": arrival.get("status_note", ""),
                "route_note": arrival.get("route_note", ""),
                "metric_f": arrival.get("metric_f"),
                "metric_g": arrival.get("metric_g"),
                "metric_h": arrival.get("metric_h"),
                "arrival_batch_id": arrival.get("id", ""),
                "shipment_qty": round(shipment_qty, 2),
                "signed_qty": round(signed_qty, 2),
                "received_qty": round(received_qty, 2),
                "unsigned_qty": round(max(0.0, shipment_qty - signed_qty), 2),
                "awaiting_receive_qty": round(
                    max(0.0, signed_qty - received_qty), 2
                ),
                "remaining_qty": round(max(0.0, shipment_qty - received_qty), 2),
                "items": items,
            }
        )
    views.sort(
        key=lambda item: (
            {
                "overdue": 0,
                "awaiting_receive": 1,
                "in_transit": 2,
                "manual_pending": 3,
                "pending": 4,
                "empty": 5,
                "archived": 6,
                "received": 7,
            }.get(
                item["status"], 6
            ),
            item["expected_receive_date"] or "9999-12-31",
            item["cargo_code"],
        )
    )
    return views


def _inbound_index(
    shipments: list[dict[str, Any]],
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    index: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for shipment in shipments:
        if (
            shipment["is_received"]
            or shipment.get("is_archived")
            or not shipment.get("is_api_synced", True)
        ):
            continue
        for item in shipment["items"]:
            if item["remaining_qty"] <= 0:
                continue
            inbound = {
                **item,
                "order_status_name": shipment["order_status_name"],
                "ship_status": shipment["ship_status"],
                "shipping_list_code": shipment["shipping_list_code"],
                "delivery_time": shipment["delivery_time"],
                "expected_delivery_time": shipment["expected_delivery_date"],
                "arrival_time": shipment["expected_delivery_date"],
                "tracking_number": shipment["tracking_number"],
                "carrier": shipment["carrier"],
                "manual_expected_delivery_date": shipment[
                    "manual_expected_delivery_date"
                ],
                "status": shipment["status"],
            }
            index.setdefault(
                product_group_key(item["store_id"], item["msku"]),
                [],
            ).append(inbound)
    return index


def _decision_for_product_group(
    decisions: dict[tuple[str, str], dict[str, Any]],
    product: dict[str, Any],
) -> dict[str, Any]:
    store_id = str(product.get("store_id") or "")
    keys = {
        str(product.get("decision_msku") or ""),
        str(product.get("execution_msku") or ""),
        *(str(item) for item in product.get("member_mskus", [])),
    }
    candidates = [
        decisions[(store_id, key)]
        for key in keys
        if key and (store_id, key) in decisions
    ]
    return max(
        candidates,
        key=lambda item: str(item.get("updated_at") or ""),
        default={},
    )


def build_shipments(
    repository: Repository, as_of: str | date | None = None
) -> dict[str, Any]:
    snapshot = repository.latest_snapshot()
    current_date = parse_date(
        as_of or (snapshot["source_date"] if snapshot else date.today())
    )
    shipments = _shipment_views(repository, current_date)
    active = [
        item
        for item in shipments
        if not item["is_received"]
        and not item.get("is_archived")
        and item["remaining_qty"] > 0
    ]
    return {
        "as_of": current_date.isoformat(),
        "summary": {
            "shipment_count": len(shipments),
            "active_count": len(active),
            "overdue_count": sum(1 for item in active if item["is_overdue"]),
            "missing_eta_count": sum(
                1 for item in active if not item["expected_receive_date"]
            ),
            "missing_tracking_count": sum(
                1 for item in active if not item["tracking_number"]
            ),
            "active_remaining_qty": round(
                sum(item["remaining_qty"] for item in active), 2
            ),
            "awaiting_receive_qty": round(
                sum(item["awaiting_receive_qty"] for item in active), 2
            ),
            "manual_only_count": sum(
                1 for item in active if not item.get("is_api_synced", True)
            ),
            "archived_count": sum(
                1 for item in shipments if item.get("is_archived")
            ),
        },
        "arrival_tracking": repository.get_arrival_tracking_summary(),
        "reconciliation_issues": [
            {
                "item_id": item["id"],
                "batch_id": batch["id"],
                "cargo_code": batch.get("cargo_code", ""),
                "store_id": batch.get("store_id", ""),
                "raw_sku": item.get("raw_sku", ""),
                "product_name": item.get("product_name", ""),
                "shipment_qty": item.get("shipment_qty", 0),
                "match_status": item.get("match_status", "unmatched"),
                "conflict_note": item.get("conflict_note", ""),
            }
            for batch in repository.get_arrival_batches()
            for item in batch.get("items", [])
            if item.get("match_status") != "matched"
        ],
        "match_products": repository.get_product_match_catalog(),
        "shipments": shipments,
    }


def build_dashboard(
    repository: Repository, as_of: str | date | None = None
) -> dict[str, Any]:
    snapshot = repository.latest_snapshot()
    if not snapshot:
        raise NoSnapshotError("还没有领星数据快照，请先点击“拉取领星数据”。")

    current_date = parse_date(as_of or snapshot["source_date"])
    settings = repository.get_settings()
    schedule = repository.get_schedule()
    context = schedule_context(schedule, current_date)
    week_date = context["current"]["week_date"]
    decisions = repository.get_decisions(week_date)
    product_statuses = repository.get_product_planning_statuses()
    group_settings = repository.get_product_group_settings()
    shipment_data = build_shipments(repository, current_date)
    inbound_index = _inbound_index(shipment_data["shipments"])
    grouped_products = aggregate_product_groups(
        snapshot["products"],
        product_statuses,
        group_settings,
    )

    products = []
    for product in grouped_products:
        products.append(
            calculate_recommendation(
                product,
                settings,
                schedule,
                current_date,
                _decision_for_product_group(decisions, product),
                inbound_index.get(
                    product_group_key(
                        product["store_id"],
                        product["canonical_msku"],
                    ),
                    [],
                ),
            )
        )
    products.sort(
        key=lambda item: (
            item["risk_rank"],
            item["stockout_date"] or "9999-12-31",
            -item["dynamic_daily"],
            item["msku"],
        )
    )

    return {
        "as_of": current_date.isoformat(),
        "snapshot": {
            "snapshot_id": snapshot["snapshot_id"],
            "source": snapshot["source"],
            "source_date": snapshot["source_date"],
            "collected_at": snapshot["collected_at"],
            "stores": snapshot["stores"],
            "product_count": len(grouped_products),
            "raw_product_count": len(snapshot["products"]),
            "merged_group_count": sum(
                item.get("is_grouped", False) for item in grouped_products
            ),
        },
        "settings": settings,
        "schedule": schedule,
        "schedule_context": context,
        "summary": build_summary(products),
        "shipment_summary": shipment_data["summary"],
        "products": products,
    }


def build_product_detail(
    repository: Repository,
    msku: str,
    store_id: str,
    as_of: str | date | None = None,
) -> dict[str, Any]:
    dashboard = build_dashboard(repository, as_of)
    product = next(
        (
            item
            for item in dashboard["products"]
            if item["store_id"] == store_id
            and (
                item["msku"] == msku
                or item.get("canonical_msku", "").upper()
                == canonical_msku(msku).upper()
                or msku in item.get("member_mskus", [])
            )
        ),
        None,
    )
    if not product:
        raise KeyError(f"没有找到商品：{msku}")
    return {
        "as_of": dashboard["as_of"],
        "product": product,
        "forecast": build_forecast(
            product, dashboard["settings"], dashboard["as_of"]
        ),
        "shipments": product.get("inbounds", []),
        "settings": dashboard["settings"],
        "schedule_context": dashboard["schedule_context"],
        "snapshot": dashboard["snapshot"],
    }


def build_manual_scenario(
    repository: Repository,
    store_id: str,
    msku: str,
    nodes: list[dict[str, Any]],
    as_of: str | date | None = None,
    executed_unsynced_qty: float | None = None,
) -> dict[str, Any]:
    detail = build_product_detail(repository, msku, store_id, as_of)
    scenario = recalculate_scenario_plan(
        detail["product"],
        detail["settings"],
        detail["as_of"],
        nodes,
        executed_unsynced_qty,
    )
    return {
        "as_of": detail["as_of"],
        "product_group_id": detail["product"].get("product_group_id"),
        "scenario": scenario,
    }
