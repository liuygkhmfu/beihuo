from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .domain import DEFAULT_SCHEDULE, DEFAULT_SETTINGS


DB_FILE = Path(__file__).resolve().parent / "data" / "tk_replenishment.db"


class Repository:
    def __init__(self, db_file: Path = DB_FILE) -> None:
        db_file.parent.mkdir(parents=True, exist_ok=True)
        self.db_file = db_file
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_file)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS raw_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    collected_at TEXT NOT NULL,
                    source_date TEXT NOT NULL,
                    store_count INTEGER NOT NULL,
                    product_count INTEGER NOT NULL,
                    payload TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS season_schedule (
                    week_date TEXT PRIMARY KEY,
                    target_days REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS decisions (
                    msku TEXT NOT NULL,
                    store_id TEXT NOT NULL,
                    week_date TEXT NOT NULL,
                    air_enabled INTEGER,
                    channel_signature TEXT,
                    timing_mode TEXT,
                    air_service TEXT,
                    confirmed_express_qty REAL,
                    confirmed_air_qty REAL,
                    confirmed_quick_qty REAL,
                    confirmed_truck_qty REAL,
                    confirmed_slow_qty REAL,
                    scenario_nodes TEXT NOT NULL DEFAULT '[]',
                    final_buy_qty REAL,
                    executed_unsynced_qty REAL NOT NULL DEFAULT 0,
                    review_status TEXT NOT NULL DEFAULT 'pending',
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (msku, store_id, week_date)
                );

                CREATE TABLE IF NOT EXISTS purchase_plan_configs (
                    season_year INTEGER PRIMARY KEY,
                    completed_month INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS purchase_plan_overrides (
                    season_year INTEGER NOT NULL,
                    sku_key TEXT NOT NULL,
                    adopted_daily REAL,
                    extra_days REAL NOT NULL DEFAULT 0,
                    final_qty REAL,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (season_year, sku_key)
                );

                CREATE TABLE IF NOT EXISTS shipment_records (
                    cargo_code TEXT PRIMARY KEY,
                    cargo_id TEXT NOT NULL DEFAULT '',
                    store_id TEXT NOT NULL DEFAULT '',
                    store_name TEXT NOT NULL DEFAULT '',
                    order_status TEXT NOT NULL DEFAULT '',
                    order_status_name TEXT NOT NULL DEFAULT '',
                    ship_status TEXT NOT NULL DEFAULT '',
                    shipping_warehouse TEXT NOT NULL DEFAULT '',
                    create_time TEXT,
                    delivery_time TEXT,
                    expected_delivery_time TEXT,
                    actual_delivery_time TEXT,
                    shipping_list_codes TEXT NOT NULL DEFAULT '[]',
                    source_updated_at TEXT NOT NULL,
                    raw_payload TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS shipment_items (
                    cargo_code TEXT NOT NULL,
                    store_id TEXT NOT NULL DEFAULT '',
                    msku TEXT NOT NULL,
                    sku TEXT NOT NULL DEFAULT '',
                    product_name TEXT NOT NULL DEFAULT '',
                    image_url TEXT NOT NULL DEFAULT '',
                    declaration_qty REAL NOT NULL DEFAULT 0,
                    shipment_qty REAL NOT NULL DEFAULT 0,
                    signed_qty REAL NOT NULL DEFAULT 0,
                    normal_qty REAL NOT NULL DEFAULT 0,
                    defective_qty REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (cargo_code, store_id, msku)
                );

                CREATE TABLE IF NOT EXISTS shipping_orders (
                    shipping_list_code TEXT PRIMARY KEY,
                    status TEXT NOT NULL DEFAULT '',
                    status_name TEXT NOT NULL DEFAULT '',
                    logistics_provider TEXT NOT NULL DEFAULT '',
                    logistics_channel TEXT NOT NULL DEFAULT '',
                    logistics_type TEXT NOT NULL DEFAULT '',
                    create_time TEXT,
                    delivery_time TEXT,
                    arrival_time TEXT,
                    expected_arrival_time TEXT,
                    actual_due_time TEXT,
                    actual_delivery_time TEXT,
                    order_logistics_status TEXT NOT NULL DEFAULT '',
                    tracking_numbers TEXT NOT NULL DEFAULT '[]',
                    cargo_codes TEXT NOT NULL DEFAULT '[]',
                    source_updated_at TEXT NOT NULL,
                    raw_payload TEXT NOT NULL DEFAULT '{}'
                );

                CREATE TABLE IF NOT EXISTS shipment_overrides (
                    cargo_code TEXT PRIMARY KEY,
                    carrier TEXT NOT NULL DEFAULT '',
                    tracking_number TEXT NOT NULL DEFAULT '',
                    expected_delivery_date TEXT,
                    note TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS arrival_imports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT NOT NULL,
                    file_hash TEXT NOT NULL UNIQUE,
                    default_store_id TEXT NOT NULL DEFAULT '',
                    imported_at TEXT NOT NULL,
                    row_count INTEGER NOT NULL DEFAULT 0,
                    batch_count INTEGER NOT NULL DEFAULT 0,
                    matched_count INTEGER NOT NULL DEFAULT 0,
                    unmatched_count INTEGER NOT NULL DEFAULT 0,
                    conflict_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS arrival_batches (
                    id TEXT PRIMARY KEY,
                    cargo_code TEXT NOT NULL DEFAULT '',
                    store_id TEXT NOT NULL DEFAULT '',
                    batch_label TEXT NOT NULL DEFAULT '',
                    shipment_date TEXT,
                    departure_date TEXT,
                    port_arrival_date TEXT,
                    expected_signed_date TEXT,
                    actual_signed_date TEXT,
                    expected_receive_date TEXT,
                    actual_receive_date TEXT,
                    is_fully_received INTEGER NOT NULL DEFAULT 0,
                    carrier TEXT NOT NULL DEFAULT '',
                    tracking_number TEXT NOT NULL DEFAULT '',
                    status_note TEXT NOT NULL DEFAULT '',
                    route_note TEXT NOT NULL DEFAULT '',
                    metric_f TEXT,
                    metric_g TEXT,
                    metric_h TEXT,
                    source_import_id INTEGER,
                    source_row_start INTEGER NOT NULL DEFAULT 0,
                    source_row_end INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS arrival_items (
                    id TEXT PRIMARY KEY,
                    batch_id TEXT NOT NULL,
                    source_row INTEGER NOT NULL DEFAULT 0,
                    raw_sku TEXT NOT NULL DEFAULT '',
                    matched_store_id TEXT NOT NULL DEFAULT '',
                    matched_msku TEXT NOT NULL DEFAULT '',
                    matched_sku TEXT NOT NULL DEFAULT '',
                    product_name TEXT NOT NULL DEFAULT '',
                    shipment_qty REAL NOT NULL DEFAULT 0,
                    match_status TEXT NOT NULL DEFAULT 'unmatched',
                    match_method TEXT NOT NULL DEFAULT '',
                    conflict_note TEXT NOT NULL DEFAULT '',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS product_aliases (
                    store_id TEXT NOT NULL DEFAULT '',
                    alias_sku TEXT NOT NULL,
                    canonical_msku TEXT NOT NULL,
                    canonical_sku TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT 'manual',
                    confirmed_at TEXT NOT NULL,
                    PRIMARY KEY (store_id, alias_sku)
                );

                CREATE TABLE IF NOT EXISTS product_planning_statuses (
                    store_id TEXT NOT NULL,
                    msku TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (store_id, msku)
                );

                CREATE TABLE IF NOT EXISTS product_group_settings (
                    store_id TEXT NOT NULL,
                    canonical_msku TEXT NOT NULL,
                    execution_msku TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (store_id, canonical_msku)
                );

                CREATE INDEX IF NOT EXISTS idx_shipment_items_product
                ON shipment_items(store_id, msku);

                CREATE INDEX IF NOT EXISTS idx_arrival_batches_cargo
                ON arrival_batches(cargo_code, store_id);

                CREATE INDEX IF NOT EXISTS idx_arrival_items_batch
                ON arrival_items(batch_id, is_active);
                """
            )
            decision_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(decisions)").fetchall()
            }
            if "confirmed_air_qty" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN confirmed_air_qty REAL"
                )
            if "confirmed_express_qty" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN confirmed_express_qty REAL"
                )
            if "air_enabled" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN air_enabled INTEGER"
                )
            if "timing_mode" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN timing_mode TEXT"
                )
            if "channel_signature" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN channel_signature TEXT"
                )
            if "air_service" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN air_service TEXT"
                )
            if "confirmed_truck_qty" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions ADD COLUMN confirmed_truck_qty REAL"
                )
            if "scenario_nodes" not in decision_columns:
                connection.execute(
                    "ALTER TABLE decisions "
                    "ADD COLUMN scenario_nodes TEXT NOT NULL DEFAULT '[]'"
                )
            override_columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(shipment_overrides)"
                ).fetchall()
            }
            for column in (
                "departure_date",
                "port_arrival_date",
                "expected_receive_date",
                "actual_signed_date",
                "actual_receive_date",
            ):
                if column not in override_columns:
                    connection.execute(
                        f"ALTER TABLE shipment_overrides ADD COLUMN {column} TEXT"
                    )
            for key, value in DEFAULT_SETTINGS.items():
                connection.execute(
                    "INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            connection.execute(
                "DELETE FROM settings WHERE key = 'fbt_receiving_buffer_days'"
            )
            connection.execute(
                "DELETE FROM settings "
                "WHERE key = 'arrival_tracking_receiving_buffer_days'"
            )
            for item in DEFAULT_SCHEDULE:
                connection.execute(
                    "INSERT OR IGNORE INTO season_schedule(week_date, target_days) VALUES (?, ?)",
                    (item["week_date"], item["seasonal_coverage_days"]),
                )

    def save_snapshot(self, payload: dict[str, Any]) -> dict[str, Any]:
        collected_at = payload["collected_at"]
        source_date = payload["source_date"]
        stores = payload.get("stores", [])
        products = payload.get("products", [])
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO raw_snapshots(
                    collected_at, source_date, store_count, product_count, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    collected_at,
                    source_date,
                    len(stores),
                    len(products),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            snapshot_id = cursor.lastrowid
            self._upsert_shipment_data(connection, payload)
        result = dict(payload)
        result["snapshot_id"] = snapshot_id
        return result

    def _upsert_shipment_data(
        self, connection: sqlite3.Connection, payload: dict[str, Any]
    ) -> None:
        synced_at = str(payload.get("collected_at") or datetime.now().isoformat())
        for shipment in payload.get("shipments", []):
            cargo_code = str(shipment.get("cargo_code") or "").strip()
            if not cargo_code:
                continue
            connection.execute(
                """
                INSERT INTO shipment_records(
                    cargo_code, cargo_id, store_id, store_name, order_status,
                    order_status_name, ship_status, shipping_warehouse,
                    create_time, delivery_time, expected_delivery_time,
                    actual_delivery_time, shipping_list_codes,
                    source_updated_at, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cargo_code) DO UPDATE SET
                    cargo_id=excluded.cargo_id,
                    store_id=excluded.store_id,
                    store_name=excluded.store_name,
                    order_status=excluded.order_status,
                    order_status_name=excluded.order_status_name,
                    ship_status=excluded.ship_status,
                    shipping_warehouse=excluded.shipping_warehouse,
                    create_time=excluded.create_time,
                    delivery_time=excluded.delivery_time,
                    expected_delivery_time=excluded.expected_delivery_time,
                    actual_delivery_time=excluded.actual_delivery_time,
                    shipping_list_codes=excluded.shipping_list_codes,
                    source_updated_at=excluded.source_updated_at,
                    raw_payload=excluded.raw_payload
                """,
                (
                    cargo_code,
                    str(shipment.get("cargo_id") or ""),
                    str(shipment.get("store_id") or ""),
                    str(shipment.get("store_name") or ""),
                    str(shipment.get("order_status") or ""),
                    str(shipment.get("order_status_name") or ""),
                    str(shipment.get("ship_status") or ""),
                    str(shipment.get("shipping_warehouse") or ""),
                    shipment.get("create_time"),
                    shipment.get("delivery_time"),
                    shipment.get("expected_delivery_time"),
                    shipment.get("actual_delivery_time"),
                    json.dumps(
                        shipment.get("shipping_list_codes", []), ensure_ascii=False
                    ),
                    synced_at,
                    json.dumps(shipment, ensure_ascii=False),
                ),
            )
            for item in shipment.get("items", []):
                msku = str(item.get("msku") or "").strip()
                if not msku:
                    continue
                connection.execute(
                    """
                    INSERT INTO shipment_items(
                        cargo_code, store_id, msku, sku, product_name, image_url,
                        declaration_qty, shipment_qty, signed_qty, normal_qty,
                        defective_qty
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(cargo_code, store_id, msku) DO UPDATE SET
                        sku=excluded.sku,
                        product_name=excluded.product_name,
                        image_url=excluded.image_url,
                        declaration_qty=excluded.declaration_qty,
                        shipment_qty=excluded.shipment_qty,
                        signed_qty=excluded.signed_qty,
                        normal_qty=excluded.normal_qty,
                        defective_qty=excluded.defective_qty
                    """,
                    (
                        cargo_code,
                        str(shipment.get("store_id") or ""),
                        msku,
                        str(item.get("sku") or ""),
                        str(item.get("product_name") or ""),
                        str(item.get("image_url") or ""),
                        float(item.get("declaration_qty") or 0),
                        float(item.get("shipment_qty") or 0),
                        float(item.get("signed_qty") or 0),
                        float(item.get("normal_qty") or 0),
                        float(item.get("defective_qty") or 0),
                    ),
                )

        for order in payload.get("shipping_orders", []):
            code = str(order.get("shipping_list_code") or "").strip()
            if not code:
                continue
            connection.execute(
                """
                INSERT INTO shipping_orders(
                    shipping_list_code, status, status_name,
                    logistics_provider, logistics_channel, logistics_type,
                    create_time, delivery_time, arrival_time,
                    expected_arrival_time, actual_due_time,
                    actual_delivery_time, order_logistics_status,
                    tracking_numbers, cargo_codes, source_updated_at, raw_payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(shipping_list_code) DO UPDATE SET
                    status=excluded.status,
                    status_name=excluded.status_name,
                    logistics_provider=excluded.logistics_provider,
                    logistics_channel=excluded.logistics_channel,
                    logistics_type=excluded.logistics_type,
                    create_time=excluded.create_time,
                    delivery_time=excluded.delivery_time,
                    arrival_time=excluded.arrival_time,
                    expected_arrival_time=excluded.expected_arrival_time,
                    actual_due_time=excluded.actual_due_time,
                    actual_delivery_time=excluded.actual_delivery_time,
                    order_logistics_status=excluded.order_logistics_status,
                    tracking_numbers=excluded.tracking_numbers,
                    cargo_codes=excluded.cargo_codes,
                    source_updated_at=excluded.source_updated_at,
                    raw_payload=excluded.raw_payload
                """,
                (
                    code,
                    str(order.get("status") or ""),
                    str(order.get("status_name") or ""),
                    str(order.get("logistics_provider") or ""),
                    str(order.get("logistics_channel") or ""),
                    str(order.get("logistics_type") or ""),
                    order.get("create_time"),
                    order.get("delivery_time"),
                    order.get("arrival_time"),
                    order.get("expected_arrival_time"),
                    order.get("actual_due_time"),
                    order.get("actual_delivery_time"),
                    str(order.get("order_logistics_status") or ""),
                    json.dumps(order.get("tracking_numbers", []), ensure_ascii=False),
                    json.dumps(order.get("cargo_codes", []), ensure_ascii=False),
                    synced_at,
                    json.dumps(order, ensure_ascii=False),
                ),
            )

    def latest_snapshot(self) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, payload FROM raw_snapshots ORDER BY id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        payload = json.loads(row["payload"])
        payload["snapshot_id"] = row["id"]
        return payload

    def get_product_match_catalog(self) -> list[dict[str, Any]]:
        snapshot = self.latest_snapshot() or {}
        catalog: dict[tuple[str, str], dict[str, Any]] = {}
        for product in snapshot.get("products", []):
            store_id = str(product.get("store_id") or "")
            msku = str(product.get("msku") or "").strip()
            if not msku:
                continue
            catalog[(store_id, msku)] = {
                "store_id": store_id,
                "store_name": str(product.get("store_name") or ""),
                "msku": msku,
                "sku": str(product.get("sku") or ""),
                "product_name": str(product.get("product_name") or ""),
            }
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT i.store_id, r.store_name, i.msku, i.sku, i.product_name
                FROM shipment_items i
                LEFT JOIN shipment_records r ON r.cargo_code = i.cargo_code
                """
            ).fetchall()
        for row in rows:
            item = dict(row)
            key = (str(item["store_id"] or ""), str(item["msku"] or ""))
            catalog.setdefault(key, item)
        return list(catalog.values())

    def get_shipment_match_context(self) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            records = connection.execute(
                "SELECT cargo_code, store_id, store_name FROM shipment_records"
            ).fetchall()
            item_rows = connection.execute(
                """
                SELECT cargo_code, store_id, msku, sku, product_name
                FROM shipment_items
                """
            ).fetchall()
        context = {
            row["cargo_code"]: {
                "store_id": row["store_id"],
                "store_name": row["store_name"],
                "items": [],
            }
            for row in records
        }
        for row in item_rows:
            context.setdefault(
                row["cargo_code"],
                {"store_id": row["store_id"], "store_name": "", "items": []},
            )["items"].append(dict(row))
        return context

    def get_product_aliases(self) -> dict[tuple[str, str], dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM product_aliases").fetchall()
        return {
            (str(row["store_id"] or ""), str(row["alias_sku"] or "").upper()): dict(
                row
            )
            for row in rows
        }

    def get_arrival_import_by_hash(self, file_hash: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM arrival_imports WHERE file_hash = ?", (file_hash,)
            ).fetchone()
        return dict(row) if row else {}

    def save_arrival_import(
        self,
        filename: str,
        file_hash: str,
        default_store_id: str,
        batches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        imported_at = datetime.now().isoformat(timespec="seconds")
        counts = {"matched": 0, "unmatched": 0, "conflict": 0}
        row_count = 0
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO arrival_imports(
                    filename, file_hash, default_store_id, imported_at,
                    row_count, batch_count, matched_count, unmatched_count,
                    conflict_count
                ) VALUES (?, ?, ?, ?, 0, 0, 0, 0, 0)
                """,
                (filename, file_hash, default_store_id, imported_at),
            )
            import_id = int(cursor.lastrowid)
            for batch in batches:
                connection.execute(
                    """
                    INSERT INTO arrival_batches(
                        id, cargo_code, store_id, batch_label, shipment_date,
                        departure_date, port_arrival_date, expected_signed_date,
                        actual_signed_date, expected_receive_date,
                        actual_receive_date, is_fully_received, carrier,
                        tracking_number, status_note, route_note, metric_f,
                        metric_g, metric_h, source_import_id, source_row_start,
                        source_row_end, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?
                    )
                    ON CONFLICT(id) DO UPDATE SET
                        cargo_code=COALESCE(NULLIF(excluded.cargo_code, ''), cargo_code),
                        store_id=COALESCE(NULLIF(excluded.store_id, ''), store_id),
                        batch_label=COALESCE(NULLIF(excluded.batch_label, ''), batch_label),
                        shipment_date=COALESCE(excluded.shipment_date, shipment_date),
                        departure_date=COALESCE(excluded.departure_date, departure_date),
                        port_arrival_date=COALESCE(excluded.port_arrival_date, port_arrival_date),
                        expected_signed_date=COALESCE(excluded.expected_signed_date, expected_signed_date),
                        actual_signed_date=COALESCE(excluded.actual_signed_date, actual_signed_date),
                        expected_receive_date=COALESCE(excluded.expected_receive_date, expected_receive_date),
                        actual_receive_date=COALESCE(excluded.actual_receive_date, actual_receive_date),
                        is_fully_received=MAX(is_fully_received, excluded.is_fully_received),
                        carrier=COALESCE(NULLIF(excluded.carrier, ''), carrier),
                        tracking_number=COALESCE(NULLIF(excluded.tracking_number, ''), tracking_number),
                        status_note=COALESCE(NULLIF(excluded.status_note, ''), status_note),
                        route_note=COALESCE(NULLIF(excluded.route_note, ''), route_note),
                        metric_f=COALESCE(excluded.metric_f, metric_f),
                        metric_g=COALESCE(excluded.metric_g, metric_g),
                        metric_h=COALESCE(excluded.metric_h, metric_h),
                        source_import_id=excluded.source_import_id,
                        source_row_start=excluded.source_row_start,
                        source_row_end=excluded.source_row_end,
                        updated_at=excluded.updated_at
                    """,
                    (
                        batch["id"],
                        batch.get("cargo_code", ""),
                        batch.get("store_id", ""),
                        batch.get("batch_label", ""),
                        batch.get("shipment_date"),
                        batch.get("departure_date"),
                        batch.get("port_arrival_date"),
                        batch.get("expected_signed_date"),
                        batch.get("actual_signed_date"),
                        batch.get("expected_receive_date"),
                        batch.get("actual_receive_date"),
                        1 if batch.get("is_fully_received") else 0,
                        batch.get("carrier", ""),
                        batch.get("tracking_number", ""),
                        batch.get("status_note", ""),
                        batch.get("route_note", ""),
                        None
                        if batch.get("metric_f") is None
                        else str(batch.get("metric_f")),
                        None
                        if batch.get("metric_g") is None
                        else str(batch.get("metric_g")),
                        None
                        if batch.get("metric_h") is None
                        else str(batch.get("metric_h")),
                        import_id,
                        int(batch.get("source_row_start") or 0),
                        int(batch.get("source_row_end") or 0),
                        imported_at,
                    ),
                )
                for item in batch.get("items", []):
                    row_count += 1
                    status = str(item.get("match_status") or "unmatched")
                    counts[status] = counts.get(status, 0) + 1
                    connection.execute(
                        """
                        INSERT INTO arrival_items(
                            id, batch_id, source_row, raw_sku, matched_store_id,
                            matched_msku, matched_sku, product_name,
                            shipment_qty, match_status, match_method,
                            conflict_note, is_active, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        ON CONFLICT(id) DO UPDATE SET
                            batch_id=excluded.batch_id,
                            source_row=excluded.source_row,
                            raw_sku=excluded.raw_sku,
                            matched_store_id=excluded.matched_store_id,
                            matched_msku=excluded.matched_msku,
                            matched_sku=excluded.matched_sku,
                            product_name=excluded.product_name,
                            shipment_qty=excluded.shipment_qty,
                            match_status=excluded.match_status,
                            match_method=excluded.match_method,
                            conflict_note=excluded.conflict_note,
                            is_active=1,
                            updated_at=excluded.updated_at
                        """,
                        (
                            item["id"],
                            batch["id"],
                            int(item.get("source_row") or 0),
                            item.get("raw_sku", ""),
                            item.get("matched_store_id", ""),
                            item.get("matched_msku", ""),
                            item.get("matched_sku", ""),
                            item.get("product_name", ""),
                            float(item.get("shipment_qty") or 0),
                            status,
                            item.get("match_method", ""),
                            item.get("conflict_note", ""),
                            imported_at,
                        ),
                    )
            connection.execute(
                """
                UPDATE arrival_imports
                SET row_count = ?, batch_count = ?, matched_count = ?,
                    unmatched_count = ?, conflict_count = ?
                WHERE id = ?
                """,
                (
                    row_count,
                    len(batches),
                    counts.get("matched", 0),
                    counts.get("unmatched", 0),
                    counts.get("conflict", 0),
                    import_id,
                ),
            )
        return {
            "id": import_id,
            "filename": filename,
            "file_hash": file_hash,
            "default_store_id": default_store_id,
            "imported_at": imported_at,
            "row_count": row_count,
            "batch_count": len(batches),
            "matched_count": counts.get("matched", 0),
            "unmatched_count": counts.get("unmatched", 0),
            "conflict_count": counts.get("conflict", 0),
            "duplicate": False,
            "message": (
                f"已导入{len(batches)}个货件、{row_count}条商品明细，"
                f"自动匹配{counts.get('matched', 0)}条"
            ),
        }

    def get_arrival_batches(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            batch_rows = connection.execute(
                """
                SELECT * FROM arrival_batches
                ORDER BY COALESCE(shipment_date, '9999-12-31'), cargo_code, id
                """
            ).fetchall()
            item_rows = connection.execute(
                """
                SELECT * FROM arrival_items
                WHERE is_active = 1
                ORDER BY batch_id, source_row, id
                """
            ).fetchall()
        items_by_batch: dict[str, list[dict[str, Any]]] = {}
        for row in item_rows:
            items_by_batch.setdefault(row["batch_id"], []).append(dict(row))
        result = []
        for row in batch_rows:
            batch = dict(row)
            batch["is_fully_received"] = bool(batch["is_fully_received"])
            batch["items"] = items_by_batch.get(batch["id"], [])
            result.append(batch)
        return result

    def update_arrival_matches(self, batches: list[dict[str, Any]]) -> None:
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            for batch in batches:
                if batch.get("store_id"):
                    connection.execute(
                        "UPDATE arrival_batches SET store_id = ?, updated_at = ? WHERE id = ?",
                        (batch["store_id"], updated_at, batch["id"]),
                    )
                for item in batch.get("items", []):
                    connection.execute(
                        """
                        UPDATE arrival_items
                        SET matched_store_id = ?, matched_msku = ?,
                            matched_sku = ?, product_name = ?,
                            match_status = ?, match_method = ?,
                            conflict_note = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (
                            item.get("matched_store_id", ""),
                            item.get("matched_msku", ""),
                            item.get("matched_sku", ""),
                            item.get("product_name", ""),
                            item.get("match_status", "unmatched"),
                            item.get("match_method", ""),
                            item.get("conflict_note", ""),
                            updated_at,
                            item["id"],
                        ),
                    )

    def get_arrival_tracking_summary(self) -> dict[str, Any]:
        with self._connect() as connection:
            latest = connection.execute(
                "SELECT * FROM arrival_imports ORDER BY id DESC LIMIT 1"
            ).fetchone()
            counts = connection.execute(
                """
                SELECT
                    COUNT(*) AS item_count,
                    SUM(CASE WHEN match_status = 'matched' THEN 1 ELSE 0 END) AS matched_count,
                    SUM(CASE WHEN match_status = 'unmatched' THEN 1 ELSE 0 END) AS unmatched_count,
                    SUM(CASE WHEN match_status = 'conflict' THEN 1 ELSE 0 END) AS conflict_count
                FROM arrival_items
                WHERE is_active = 1
                """
            ).fetchone()
        result = dict(counts) if counts else {}
        result.update(
            {
                "latest_import": dict(latest) if latest else None,
                "item_count": int(result.get("item_count") or 0),
                "matched_count": int(result.get("matched_count") or 0),
                "unmatched_count": int(result.get("unmatched_count") or 0),
                "conflict_count": int(result.get("conflict_count") or 0),
            }
        )
        return result

    def save_product_alias(
        self, item_id: str, store_id: str, canonical_msku: str
    ) -> dict[str, Any]:
        candidates = [
            item
            for item in self.get_product_match_catalog()
            if str(item.get("msku") or "") == canonical_msku
            and (not store_id or str(item.get("store_id") or "") == store_id)
        ]
        if len(candidates) != 1:
            raise ValueError("没有找到唯一的目标MSKU，请同时确认店铺")
        candidate = candidates[0]
        now = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT raw_sku FROM arrival_items WHERE id = ?", (item_id,)
            ).fetchone()
            if not row:
                raise KeyError("没有找到待关联的到货明细")
            alias_sku = str(row["raw_sku"] or "").strip().upper()
            effective_store = str(candidate.get("store_id") or store_id)
            connection.execute(
                """
                INSERT INTO product_aliases(
                    store_id, alias_sku, canonical_msku, canonical_sku,
                    source, confirmed_at
                ) VALUES (?, ?, ?, ?, 'manual', ?)
                ON CONFLICT(store_id, alias_sku) DO UPDATE SET
                    canonical_msku=excluded.canonical_msku,
                    canonical_sku=excluded.canonical_sku,
                    confirmed_at=excluded.confirmed_at
                """,
                (
                    effective_store,
                    alias_sku,
                    canonical_msku,
                    str(candidate.get("sku") or ""),
                    now,
                ),
            )
            connection.execute(
                """
                UPDATE arrival_items
                SET matched_store_id = ?, matched_msku = ?, matched_sku = ?,
                    match_status = 'matched', match_method = '人工别名',
                    conflict_note = '', updated_at = ?
                WHERE raw_sku = ? AND (matched_store_id = '' OR matched_store_id = ?)
                """,
                (
                    effective_store,
                    canonical_msku,
                    str(candidate.get("sku") or ""),
                    now,
                    row["raw_sku"],
                    effective_store,
                ),
            )
        return {
            "item_id": item_id,
            "store_id": effective_store,
            "alias_sku": alias_sku,
            "canonical_msku": canonical_msku,
            "canonical_sku": str(candidate.get("sku") or ""),
        }

    def get_settings(self) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        settings = DEFAULT_SETTINGS.copy()
        settings.update({row["key"]: json.loads(row["value"]) for row in rows})
        return settings

    def get_product_planning_statuses(
        self,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT store_id, msku, status, updated_at
                FROM product_planning_statuses
                """
            ).fetchall()
        return {
            (str(row["store_id"]), str(row["msku"])): dict(row)
            for row in rows
        }

    def get_product_group_settings(
        self,
    ) -> dict[tuple[str, str], dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT store_id, canonical_msku, execution_msku, updated_at
                FROM product_group_settings
                """
            ).fetchall()
        return {
            (
                str(row["store_id"]),
                str(row["canonical_msku"]).upper(),
            ): dict(row)
            for row in rows
        }

    def save_product_group_execution(
        self,
        store_id: str,
        canonical_msku: str,
        execution_msku: str,
    ) -> dict[str, Any]:
        store_id = str(store_id or "").strip()
        canonical_msku = str(canonical_msku or "").strip()
        execution_msku = str(execution_msku or "").strip()
        if not store_id or not canonical_msku or not execution_msku:
            raise ValueError("店铺、商品组和执行MSKU不能为空")
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO product_group_settings(
                    store_id, canonical_msku, execution_msku, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(store_id, canonical_msku) DO UPDATE SET
                    execution_msku=excluded.execution_msku,
                    updated_at=excluded.updated_at
                """,
                (
                    store_id,
                    canonical_msku.upper(),
                    execution_msku,
                    updated_at,
                ),
            )
        return {
            "store_id": store_id,
            "canonical_msku": canonical_msku,
            "execution_msku": execution_msku,
            "updated_at": updated_at,
        }

    def save_product_planning_status(
        self,
        store_id: str,
        msku: str,
        status: str,
    ) -> dict[str, Any]:
        return self.save_product_planning_statuses(
            [{"store_id": store_id, "msku": msku, "status": status}]
        )[0]

    def save_product_planning_statuses(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not items:
            raise ValueError("请选择需要标记的商品")

        normalized: dict[tuple[str, str], dict[str, str]] = {}
        for item in items:
            store_id = str(item.get("store_id") or "").strip()
            msku = str(item.get("msku") or "").strip()
            status = str(item.get("status") or "active").strip().lower()
            if not store_id or not msku:
                raise ValueError("店铺和MSKU不能为空")
            if status not in {"active", "clearance", "delisted"}:
                raise ValueError("产品状态只能是正常补货、清仓或下架")
            normalized[(store_id, msku)] = {
                "store_id": store_id,
                "msku": msku,
                "status": status,
            }

        updated_at = datetime.now().isoformat(timespec="seconds")
        saved = [
            {**item, "updated_at": updated_at}
            for item in normalized.values()
        ]
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO product_planning_statuses(
                    store_id, msku, status, updated_at
                ) VALUES (?, ?, ?, ?)
                ON CONFLICT(store_id, msku) DO UPDATE SET
                    status=excluded.status,
                    updated_at=excluded.updated_at
                """,
                [
                    (
                        item["store_id"],
                        item["msku"],
                        item["status"],
                        item["updated_at"],
                    )
                    for item in saved
                ],
            )
        return saved

    def save_settings(self, values: dict[str, Any]) -> dict[str, Any]:
        allowed = set(DEFAULT_SETTINGS)
        updates = {key: value for key, value in values.items() if key in allowed}
        candidate = self.get_settings()
        candidate.update(updates)
        channel_keys = (
            "express_channel_enabled",
            "air_channel_enabled",
            "quick_channel_enabled",
            "truck_channel_enabled",
            "slow_channel_enabled",
        )
        for key in channel_keys:
            candidate[key] = bool(candidate[key])
            if key in updates:
                updates[key] = candidate[key]
        if not any(
            candidate[key]
            for key in (
                "quick_channel_enabled",
                "truck_channel_enabled",
                "slow_channel_enabled",
            )
        ):
            raise ValueError("至少需要启用一个常规物流渠道")
        if not candidate["air_channel_enabled"]:
            candidate["air_enabled"] = False
            updates["air_enabled"] = False
        if candidate["timing_mode"] not in {"precise", "fixed"}:
            raise ValueError("时效计算模式只能是精准船期或固定频率")
        for prefix in (
            "express_transit",
            "air_transit",
            "quick_transit",
            "truck_transit",
            "slow_transit",
        ):
            minimum = float(candidate[f"{prefix}_min_days"])
            maximum = float(candidate[f"{prefix}_max_days"])
            if minimum <= 0 or maximum < minimum:
                raise ValueError(f"{prefix}时效范围无效")
        for channel in ("quick", "truck", "slow"):
            for suffix in ("cutoff_weekday", "sailing_weekday"):
                weekday = int(candidate[f"{channel}_{suffix}"])
                if weekday < 0 or weekday > 6:
                    raise ValueError("截单和开船星期必须在周一至周日之间")
        buffer_keys = [
            f"{channel}_{kind}_days"
            for channel in ("express", "air", "quick", "truck", "slow")
            for kind in ("safety", "frequency")
        ]
        for key in (
            "safety_days",
            "frequency_days",
            *buffer_keys,
        ):
            if float(candidate[key]) < 0:
                raise ValueError(f"{key}不能小于0")
        if abs(
            float(candidate["weight_7"])
            + float(candidate["weight_14"])
            + float(candidate["weight_30"])
            - 1.0
        ) > 0.0001:
            raise ValueError("动态日均权重合计必须为100%")
        datetime.strptime(str(candidate["receiving_cutoff"]), "%Y-%m-%d")

        with self._connect() as connection:
            for key, value in updates.items():
                connection.execute(
                    """
                    INSERT INTO settings(key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value
                    """,
                    (key, json.dumps(value, ensure_ascii=False)),
                )
        return self.get_settings()

    def get_schedule(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT week_date, target_days FROM season_schedule ORDER BY week_date"
            ).fetchall()
        return [
            {
                "week_date": row["week_date"],
                "seasonal_coverage_days": row["target_days"],
            }
            for row in rows
        ]

    def save_schedule(self, schedule: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cleaned = sorted(
            [
                {
                    "week_date": str(item["week_date"]),
                    "seasonal_coverage_days": float(
                        item.get("seasonal_coverage_days", item.get("target_days"))
                    ),
                }
                for item in schedule
            ],
            key=lambda item: item["week_date"],
        )
        if not cleaned:
            raise ValueError("旺季周计划不能为空")
        with self._connect() as connection:
            connection.execute("DELETE FROM season_schedule")
            connection.executemany(
                "INSERT INTO season_schedule(week_date, target_days) VALUES (?, ?)",
                [
                    (item["week_date"], item["seasonal_coverage_days"])
                    for item in cleaned
                ],
            )
        return self.get_schedule()

    def get_purchase_plan_config(self, season_year: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT season_year, completed_month, updated_at
                FROM purchase_plan_configs
                WHERE season_year = ?
                """,
                (int(season_year),),
            ).fetchone()
        return dict(row) if row else {}

    def save_purchase_plan_config(
        self, season_year: int, completed_month: int
    ) -> dict[str, Any]:
        season_year = int(season_year)
        completed_month = int(completed_month)
        if completed_month not in {0, 7, 8, 9, 10, 11, 12}:
            raise ValueError("已完成备货月份只能选择首次完整备货或7月至12月")
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO purchase_plan_configs(
                    season_year, completed_month, updated_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(season_year) DO UPDATE SET
                    completed_month=excluded.completed_month,
                    updated_at=excluded.updated_at
                """,
                (season_year, completed_month, updated_at),
            )
        return self.get_purchase_plan_config(season_year)

    def get_purchase_plan_overrides(
        self, season_year: int
    ) -> dict[str, dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT season_year, sku_key, adopted_daily, extra_days,
                       final_qty, note, updated_at
                FROM purchase_plan_overrides
                WHERE season_year = ?
                """,
                (int(season_year),),
            ).fetchall()
        return {str(row["sku_key"]): dict(row) for row in rows}

    def save_purchase_plan_overrides(
        self, season_year: int, items: list[dict[str, Any]]
    ) -> dict[str, dict[str, Any]]:
        season_year = int(season_year)
        updated_at = datetime.now().isoformat(timespec="seconds")
        cleaned: list[tuple[Any, ...]] = []
        reset_keys: list[tuple[int, str]] = []
        for item in items:
            sku_key = str(item.get("sku_key") or item.get("sku") or "").strip().upper()
            if not sku_key:
                raise ValueError("备货商品缺少SKU")
            adopted_daily = item.get("adopted_daily")
            final_qty = item.get("final_qty")
            extra_days = float(item.get("extra_days") or 0)
            if adopted_daily in ("", None):
                adopted_daily = None
            else:
                adopted_daily = float(adopted_daily)
            if final_qty in ("", None):
                final_qty = None
            else:
                final_qty = float(final_qty)
            if adopted_daily is not None and adopted_daily < 0:
                raise ValueError(f"{sku_key}采用日均不能小于0")
            if extra_days < 0:
                raise ValueError(f"{sku_key}人工增加天数不能小于0")
            if final_qty is not None and final_qty < 0:
                raise ValueError(f"{sku_key}最终备货量不能小于0")
            note = str(item.get("note") or "").strip()
            if (
                adopted_daily is None
                and extra_days == 0
                and final_qty is None
                and not note
            ):
                reset_keys.append((season_year, sku_key))
                continue
            cleaned.append(
                (
                    season_year,
                    sku_key,
                    adopted_daily,
                    extra_days,
                    final_qty,
                    note,
                    updated_at,
                )
            )
        with self._connect() as connection:
            if reset_keys:
                connection.executemany(
                    """
                    DELETE FROM purchase_plan_overrides
                    WHERE season_year = ? AND sku_key = ?
                    """,
                    reset_keys,
                )
            if cleaned:
                connection.executemany(
                    """
                    INSERT INTO purchase_plan_overrides(
                        season_year, sku_key, adopted_daily, extra_days,
                        final_qty, note, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(season_year, sku_key) DO UPDATE SET
                        adopted_daily=excluded.adopted_daily,
                        extra_days=excluded.extra_days,
                        final_qty=excluded.final_qty,
                        note=excluded.note,
                        updated_at=excluded.updated_at
                    """,
                    cleaned,
                )
        return self.get_purchase_plan_overrides(season_year)

    @staticmethod
    def _decision_from_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        try:
            result["scenario_nodes"] = json.loads(
                result.get("scenario_nodes") or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            result["scenario_nodes"] = []
        return result

    def get_decisions(self, week_date: str) -> dict[tuple[str, str], dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM decisions WHERE week_date = ?", (week_date,)
            ).fetchall()
        return {
            (row["store_id"], row["msku"]): self._decision_from_row(row)
            for row in rows
        }

    def get_decision(
        self, msku: str, store_id: str, week_date: str
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM decisions
                WHERE msku = ? AND store_id = ? AND week_date = ?
                """,
                (msku, store_id, week_date),
            ).fetchone()
        return self._decision_from_row(row) if row else {}

    def save_decision(
        self,
        msku: str,
        store_id: str,
        week_date: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        current = self.get_decision(msku, store_id, week_date)
        merged = {
            "air_enabled": values.get(
                "air_enabled", current.get("air_enabled")
            ),
            "timing_mode": values.get(
                "timing_mode", current.get("timing_mode")
            ),
            "channel_signature": values.get(
                "channel_signature", current.get("channel_signature")
            ),
            "air_service": values.get(
                "air_service", current.get("air_service")
            ),
            "confirmed_express_qty": values.get(
                "confirmed_express_qty",
                current.get("confirmed_express_qty"),
            ),
            "confirmed_air_qty": values.get(
                "confirmed_air_qty", current.get("confirmed_air_qty")
            ),
            "confirmed_quick_qty": values.get(
                "confirmed_quick_qty", current.get("confirmed_quick_qty")
            ),
            "confirmed_truck_qty": values.get(
                "confirmed_truck_qty", current.get("confirmed_truck_qty")
            ),
            "confirmed_slow_qty": values.get(
                "confirmed_slow_qty", current.get("confirmed_slow_qty")
            ),
            "scenario_nodes": values.get(
                "scenario_nodes", current.get("scenario_nodes", [])
            ),
            "final_buy_qty": values.get("final_buy_qty", current.get("final_buy_qty")),
            "executed_unsynced_qty": values.get(
                "executed_unsynced_qty", current.get("executed_unsynced_qty", 0)
            ),
            "review_status": values.get(
                "review_status", current.get("review_status", "pending")
            ),
            "note": values.get("note", current.get("note", "")),
            "updated_at": datetime.now().isoformat(timespec="seconds"),
        }
        if not isinstance(merged["scenario_nodes"], list):
            raise ValueError("情景发货节点必须是列表")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO decisions(
                    msku, store_id, week_date, air_enabled, channel_signature, timing_mode,
                    air_service, confirmed_express_qty, confirmed_air_qty, confirmed_quick_qty,
                    confirmed_truck_qty, confirmed_slow_qty, scenario_nodes, final_buy_qty,
                    executed_unsynced_qty, review_status, note, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(msku, store_id, week_date) DO UPDATE SET
                    air_enabled=excluded.air_enabled,
                    channel_signature=excluded.channel_signature,
                    timing_mode=excluded.timing_mode,
                    air_service=excluded.air_service,
                    confirmed_express_qty=excluded.confirmed_express_qty,
                    confirmed_air_qty=excluded.confirmed_air_qty,
                    confirmed_quick_qty=excluded.confirmed_quick_qty,
                    confirmed_truck_qty=excluded.confirmed_truck_qty,
                    confirmed_slow_qty=excluded.confirmed_slow_qty,
                    scenario_nodes=excluded.scenario_nodes,
                    final_buy_qty=excluded.final_buy_qty,
                    executed_unsynced_qty=excluded.executed_unsynced_qty,
                    review_status=excluded.review_status,
                    note=excluded.note,
                    updated_at=excluded.updated_at
                """,
                (
                    msku,
                    store_id,
                    week_date,
                    (
                        int(bool(merged["air_enabled"]))
                        if merged["air_enabled"] is not None
                        else None
                    ),
                    merged["channel_signature"],
                    merged["timing_mode"],
                    merged["air_service"],
                    merged["confirmed_express_qty"],
                    merged["confirmed_air_qty"],
                    merged["confirmed_quick_qty"],
                    merged["confirmed_truck_qty"],
                    merged["confirmed_slow_qty"],
                    json.dumps(
                        merged["scenario_nodes"],
                        ensure_ascii=False,
                    ),
                    merged["final_buy_qty"],
                    merged["executed_unsynced_qty"],
                    merged["review_status"],
                    merged["note"],
                    merged["updated_at"],
                ),
            )
        return self.get_decision(msku, store_id, week_date)

    def get_shipments(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            records = connection.execute(
                "SELECT * FROM shipment_records ORDER BY create_time DESC, cargo_code"
            ).fetchall()
            item_rows = connection.execute(
                "SELECT * FROM shipment_items ORDER BY cargo_code, msku"
            ).fetchall()
            order_rows = connection.execute("SELECT * FROM shipping_orders").fetchall()
            override_rows = connection.execute(
                "SELECT * FROM shipment_overrides"
            ).fetchall()

        items_by_cargo: dict[str, list[dict[str, Any]]] = {}
        for row in item_rows:
            item = dict(row)
            item["received_qty"] = float(item["normal_qty"]) + float(
                item["defective_qty"]
            )
            item["unsigned_qty"] = max(
                0.0, float(item["shipment_qty"]) - float(item["signed_qty"])
            )
            item["awaiting_receive_qty"] = max(
                0.0, float(item["signed_qty"]) - item["received_qty"]
            )
            item["remaining_qty"] = max(
                0.0, float(item["shipment_qty"]) - item["received_qty"]
            )
            items_by_cargo.setdefault(item["cargo_code"], []).append(item)

        orders = {row["shipping_list_code"]: dict(row) for row in order_rows}
        overrides = {row["cargo_code"]: dict(row) for row in override_rows}
        result: list[dict[str, Any]] = []
        for row in records:
            shipment = dict(row)
            shipment["shipping_list_codes"] = json.loads(
                shipment["shipping_list_codes"] or "[]"
            )
            shipment["items"] = items_by_cargo.get(shipment["cargo_code"], [])
            related_orders = [
                orders[code]
                for code in shipment["shipping_list_codes"]
                if code in orders
            ]
            tracking_numbers: list[str] = []
            for order in related_orders:
                for value in json.loads(order["tracking_numbers"] or "[]"):
                    if value and value not in tracking_numbers:
                        tracking_numbers.append(value)
            override = overrides.get(shipment["cargo_code"], {})
            primary_order = related_orders[0] if related_orders else {}
            shipment.update(
                {
                    "shipping_list_code": (
                        shipment["shipping_list_codes"][0]
                        if shipment["shipping_list_codes"]
                        else ""
                    ),
                    "logistics_provider": str(
                        primary_order.get("logistics_provider") or ""
                    ),
                    "logistics_channel": str(
                        primary_order.get("logistics_channel") or ""
                    ),
                    "logistics_type": str(primary_order.get("logistics_type") or ""),
                    "order_logistics_status": str(
                        primary_order.get("order_logistics_status") or ""
                    ),
                    "tracking_numbers": tracking_numbers,
                    "carrier": str(
                        override.get("carrier")
                        or primary_order.get("logistics_provider")
                        or ""
                    ),
                    "tracking_number": str(
                        override.get("tracking_number")
                        or (tracking_numbers[0] if tracking_numbers else "")
                    ),
                    "manual_expected_delivery_date": override.get(
                        "expected_delivery_date"
                    ),
                    "manual_departure_date": override.get("departure_date"),
                    "manual_port_arrival_date": override.get("port_arrival_date"),
                    "manual_expected_receive_date": override.get(
                        "expected_receive_date"
                    ),
                    "manual_actual_signed_date": override.get(
                        "actual_signed_date"
                    ),
                    "manual_actual_receive_date": override.get(
                        "actual_receive_date"
                    ),
                    "manual_note": str(override.get("note") or ""),
                    "manual_updated_at": override.get("updated_at"),
                    "shipping_order": primary_order,
                }
            )
            result.append(shipment)
        return result

    def save_shipment_override(
        self, cargo_code: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        cargo_code = cargo_code.strip()
        if not cargo_code:
            raise ValueError("货件单号不能为空")
        expected_date = values.get("expected_delivery_date") or None
        date_values = {
            "expected_delivery_date": expected_date,
            "departure_date": values.get("departure_date") or None,
            "port_arrival_date": values.get("port_arrival_date") or None,
            "expected_receive_date": values.get("expected_receive_date") or None,
            "actual_signed_date": values.get("actual_signed_date") or None,
            "actual_receive_date": values.get("actual_receive_date") or None,
        }
        for value in date_values.values():
            if value:
                datetime.strptime(str(value), "%Y-%m-%d")
        updated_at = datetime.now().isoformat(timespec="seconds")
        with self._connect() as connection:
            exists = connection.execute(
                "SELECT 1 FROM shipment_records WHERE cargo_code = ?", (cargo_code,)
            ).fetchone()
            if not exists:
                arrival = connection.execute(
                    """
                    SELECT id FROM arrival_batches
                    WHERE cargo_code = ? OR id = ?
                    """,
                    (cargo_code, cargo_code),
                ).fetchone()
                if not arrival:
                    raise KeyError(f"没有找到货件：{cargo_code}")
                connection.execute(
                    """
                    UPDATE arrival_batches
                    SET carrier = ?, tracking_number = ?, departure_date = ?,
                        port_arrival_date = ?, expected_receive_date = ?,
                        actual_signed_date = ?, actual_receive_date = ?,
                        status_note = COALESCE(NULLIF(?, ''), status_note),
                        is_fully_received = CASE
                            WHEN ? IS NOT NULL THEN 1 ELSE is_fully_received
                        END,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(values.get("carrier") or ""),
                        str(values.get("tracking_number") or ""),
                        date_values["departure_date"],
                        date_values["port_arrival_date"],
                        date_values["expected_receive_date"],
                        date_values["actual_signed_date"],
                        date_values["actual_receive_date"],
                        str(values.get("note") or ""),
                        date_values["actual_receive_date"],
                        updated_at,
                        arrival["id"],
                    ),
                )
                return next(
                    row
                    for row in self.get_arrival_batches()
                    if row["id"] == arrival["id"]
                )
            connection.execute(
                """
                INSERT INTO shipment_overrides(
                    cargo_code, carrier, tracking_number,
                    expected_delivery_date, note, updated_at, departure_date,
                    port_arrival_date, expected_receive_date,
                    actual_signed_date, actual_receive_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cargo_code) DO UPDATE SET
                    carrier=excluded.carrier,
                    tracking_number=excluded.tracking_number,
                    expected_delivery_date=excluded.expected_delivery_date,
                    note=excluded.note,
                    updated_at=excluded.updated_at,
                    departure_date=excluded.departure_date,
                    port_arrival_date=excluded.port_arrival_date,
                    expected_receive_date=excluded.expected_receive_date,
                    actual_signed_date=excluded.actual_signed_date,
                    actual_receive_date=excluded.actual_receive_date
                """,
                (
                    cargo_code,
                    str(values.get("carrier") or ""),
                    str(values.get("tracking_number") or ""),
                    date_values["expected_delivery_date"],
                    str(values.get("note") or ""),
                    updated_at,
                    date_values["departure_date"],
                    date_values["port_arrival_date"],
                    date_values["expected_receive_date"],
                    date_values["actual_signed_date"],
                    date_values["actual_receive_date"],
                ),
            )
        return next(
            row for row in self.get_shipments() if row["cargo_code"] == cargo_code
        )
