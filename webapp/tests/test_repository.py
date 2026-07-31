from datetime import datetime

import pytest

from webapp.repository import Repository
from webapp.service import build_shipments


def shipment_snapshot():
    return {
        "collected_at": datetime.now().isoformat(timespec="seconds"),
        "source_date": "2026-07-29",
        "source": "测试",
        "stores": [{"store_id": "STORE-1", "store_name": "测试店铺"}],
        "products": [],
        "shipments": [
            {
                "cargo_id": "1",
                "cargo_code": "IBR-001",
                "store_id": "STORE-1",
                "store_name": "测试店铺",
                "order_status": "2",
                "order_status_name": "运输中",
                "ship_status": "已发货",
                "shipping_warehouse": "FBT-US",
                "create_time": "2026-07-01",
                "delivery_time": "2026-07-02",
                "expected_delivery_time": "2026-07-20",
                "actual_delivery_time": None,
                "shipping_list_codes": ["SP-001"],
                "items": [
                    {
                        "msku": "TEST-001",
                        "sku": "SKU-001",
                        "product_name": "测试商品",
                        "shipment_qty": 100,
                        "signed_qty": 40,
                        "declaration_qty": 100,
                        "normal_qty": 40,
                        "defective_qty": 0,
                    }
                ],
            }
        ],
        "shipping_orders": [
            {
                "shipping_list_code": "SP-001",
                "status": "2",
                "status_name": "已发货",
                "logistics_provider": "UPS",
                "logistics_channel": "快船",
                "logistics_type": "海运",
                "delivery_time": "2026-07-02",
                "arrival_time": "2026-07-20",
                "tracking_numbers": ["1ZTEST"],
                "cargo_codes": ["IBR-001"],
            }
        ],
    }


def test_shipment_snapshot_is_persisted_and_marked_overdue(tmp_path):
    repository = Repository(tmp_path / "test.db")
    repository.save_snapshot(shipment_snapshot())
    data = build_shipments(repository, "2026-07-29")
    assert data["summary"]["active_count"] == 1
    assert data["summary"]["overdue_count"] == 1
    shipment = data["shipments"][0]
    assert shipment["remaining_qty"] == 60
    assert shipment["tracking_number"] == "1ZTEST"
    assert shipment["status"] == "overdue"


def test_manual_tracking_override_changes_effective_eta(tmp_path):
    repository = Repository(tmp_path / "test.db")
    repository.save_snapshot(shipment_snapshot())
    repository.save_shipment_override(
        "IBR-001",
        {
            "carrier": "FedEx",
            "tracking_number": "FEDEX-NEW",
            "expected_delivery_date": "2026-08-02",
            "note": "货代更新",
        },
    )
    shipment = build_shipments(repository, "2026-07-29")["shipments"][0]
    assert shipment["carrier"] == "FedEx"
    assert shipment["tracking_number"] == "FEDEX-NEW"
    assert shipment["expected_delivery_date"] == "2026-08-02"
    assert shipment["status"] == "in_transit"


def test_settings_require_at_least_one_regular_channel(tmp_path):
    repository = Repository(tmp_path / "test.db")
    with pytest.raises(ValueError, match="至少需要启用一个常规物流渠道"):
        repository.save_settings(
            {
                "quick_channel_enabled": False,
                "truck_channel_enabled": False,
                "slow_channel_enabled": False,
            }
        )


def test_disabling_air_channel_also_turns_off_emergency_air(tmp_path):
    repository = Repository(tmp_path / "test.db")
    repository.save_settings({"air_enabled": True})
    saved = repository.save_settings({"air_channel_enabled": False})
    assert saved["air_channel_enabled"] is False
    assert saved["air_enabled"] is False


def test_each_channel_buffer_setting_is_saved_independently(tmp_path):
    repository = Repository(tmp_path / "test.db")
    saved = repository.save_settings(
        {
            "quick_safety_days": 3,
            "quick_frequency_days": 5,
            "slow_safety_days": 10,
            "slow_frequency_days": 2,
        }
    )

    assert saved["quick_safety_days"] == 3
    assert saved["quick_frequency_days"] == 5
    assert saved["slow_safety_days"] == 10
    assert saved["slow_frequency_days"] == 2


def test_product_planning_status_is_saved_by_store_and_msku(tmp_path):
    repository = Repository(tmp_path / "test.db")
    saved = repository.save_product_planning_status(
        "STORE-1", "TEST-001", "clearance"
    )

    assert saved["status"] == "clearance"
    statuses = repository.get_product_planning_statuses()
    assert statuses[("STORE-1", "TEST-001")]["status"] == "clearance"

    with pytest.raises(ValueError, match="产品状态只能"):
        repository.save_product_planning_status(
            "STORE-1", "TEST-001", "unknown"
        )


def test_product_planning_statuses_are_saved_in_one_batch(tmp_path):
    repository = Repository(tmp_path / "test.db")

    saved = repository.save_product_planning_statuses(
        [
            {
                "store_id": "STORE-1",
                "msku": "TEST-001",
                "status": "clearance",
            },
            {
                "store_id": "STORE-1",
                "msku": "TEST-002",
                "status": "delisted",
            },
        ]
    )

    assert [item["status"] for item in saved] == [
        "clearance",
        "delisted",
    ]
    statuses = repository.get_product_planning_statuses()
    assert statuses[("STORE-1", "TEST-001")]["status"] == "clearance"
    assert statuses[("STORE-1", "TEST-002")]["status"] == "delisted"

    with pytest.raises(ValueError, match="产品状态只能"):
        repository.save_product_planning_statuses(
            [
                {
                    "store_id": "STORE-1",
                    "msku": "TEST-003",
                    "status": "active",
                },
                {
                    "store_id": "STORE-1",
                    "msku": "TEST-004",
                    "status": "unknown",
                },
            ]
        )
    assert ("STORE-1", "TEST-003") not in (
        repository.get_product_planning_statuses()
    )


def test_decision_saves_manual_scenario_nodes_as_json(tmp_path):
    repository = Repository(tmp_path / "test.db")
    nodes = [
        {
            "id": "quick-1",
            "channel_key": "quick",
            "dispatch_date": "2026-08-03",
            "planning_arrival_date": "2026-08-20",
            "quantity": 120,
        }
    ]

    saved = repository.save_decision(
        "TEST-001",
        "STORE-1",
        "2026-08-03",
        {
            "scenario_nodes": nodes,
            "confirmed_quick_qty": 120,
            "review_status": "reviewed",
        },
    )

    assert saved["scenario_nodes"] == nodes
    decisions = repository.get_decisions("2026-08-03")
    assert decisions[("STORE-1", "TEST-001")]["scenario_nodes"] == nodes
