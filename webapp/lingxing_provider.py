from __future__ import annotations

import ast
import asyncio
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "APIs"


class LingxingDataError(RuntimeError):
    pass


def _first_value(value: Any) -> str:
    if isinstance(value, list):
        return str(value[0]).strip() if value else ""
    if isinstance(value, str) and value.strip().startswith("["):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return str(parsed[0]).strip() if parsed else ""
        except json.JSONDecodeError:
            pass
    return str(value or "").strip()


def _legacy_credentials() -> tuple[str, str] | None:
    script = API_DIR / "main.py"
    if not script.exists():
        return None
    tree = ast.parse(script.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Name) or node.func.id != "OpenApiBase":
            continue
        if len(node.args) < 3:
            continue
        values = []
        for argument in node.args[:3]:
            values.append(argument.value if isinstance(argument, ast.Constant) else None)
        if values[0] == "https://openapi.lingxing.com" and values[1] and values[2]:
            return str(values[1]), str(values[2])
    return None


def get_credentials() -> tuple[str, str]:
    app_id = os.environ.get("LINGXING_APP_ID")
    app_secret = os.environ.get("LINGXING_APP_SECRET")
    if app_id and app_secret:
        return app_id, app_secret
    legacy = _legacy_credentials()
    if legacy:
        return legacy
    raise LingxingDataError(
        "缺少领星密钥。请设置 LINGXING_APP_ID 和 LINGXING_APP_SECRET。"
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _date_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[:10]


class LingxingProvider:
    def __init__(self) -> None:
        if str(API_DIR) not in sys.path:
            sys.path.insert(0, str(API_DIR))
        from openapi import OpenApiBase

        app_id, app_secret = get_credentials()
        self.api = OpenApiBase(
            "https://openapi.lingxing.com", app_id, app_secret
        )

    async def _request(
        self, token: str, path: str, body: dict[str, Any]
    ) -> Any:
        for attempt in range(4):
            response = await self.api.request(
                token, path, "POST", req_body=body
            )
            if response.code == 0:
                return response.data
            if response.code == 3001008 and attempt < 3:
                await asyncio.sleep(1.0 * (attempt + 1))
                continue
            details = getattr(response, "error_details", None) or []
            raise LingxingDataError(
                f"领星接口失败：{path}，code={response.code}，详情={details}"
            )
        raise LingxingDataError(f"领星接口多次重试失败：{path}")

    async def _shops(self, token: str) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        length = 200
        while True:
            data = await self._request(
                token,
                "/pb/mp/shop/v2/getSellerList",
                {
                    "offset": offset,
                    "length": length,
                    "platform_code": [10011],
                    "is_sync": 1,
                    "status": 1,
                },
            )
            items = data.get("list", [])
            records.extend(items)
            if len(items) < length:
                break
            offset += length
        return records

    async def _listings(
        self, token: str, store_id: str
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        length = 1000
        while True:
            data = await self._request(
                token,
                "/basicOpen/multiplatform/tiktok/list",
                {
                    "offset": offset,
                    "length": length,
                    "storeIds": [store_id],
                    "platformStatus": ["ACTIVATE"],
                },
            )
            items = data.get("list", [])
            records.extend(items)
            if len(items) < length:
                break
            offset += length
        return records

    async def _fbt(
        self, token: str, store_id: str
    ) -> dict[str, dict[str, float]]:
        totals: dict[str, dict[str, float]] = defaultdict(
            lambda: {
                "total": 0.0,
                "sellable": 0.0,
                "in_transit": 0.0,
                "all": 0.0,
            }
        )
        offset = 0
        length = 200
        while True:
            data = await self._request(
                token,
                "/basicOpen/multiplatform/fbt/stockSearch/v2",
                {
                    "offset": offset,
                    "length": length,
                    "storeIds": [store_id],
                },
            )
            items = data.get("page", {}).get("records", [])
            for item in items:
                msku = str(item.get("goodReferenceCode") or "").strip()
                if not msku:
                    continue
                totals[msku]["total"] += _number(
                    item.get("totalInventoryQuantity")
                )
                totals[msku]["sellable"] += _number(
                    item.get("availableQuantity")
                )
                totals[msku]["in_transit"] += _number(
                    item.get("inTransitQuantity")
                )
                totals[msku]["all"] += _number(item.get("totalQuantity"))
            if len(items) < length:
                break
            offset += length
        return dict(totals)

    async def _sales(
        self, token: str, store_id: str, days: int, as_of: date
    ) -> dict[str, float]:
        end_date = as_of - timedelta(days=1)
        start_date = end_date - timedelta(days=days - 1)
        page = 1
        length = 1000
        totals: dict[str, float] = defaultdict(float)
        while True:
            data = await self._request(
                token,
                "/basicOpen/platformStatisticsV2/saleStat/pageList",
                {
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "data_type": "3",
                    "result_type": "1",
                    "date_unit": "4",
                    "page": page,
                    "length": length,
                    "sids": [store_id],
                },
            )
            items = data if isinstance(data, list) else []
            for item in items:
                msku = _first_value(item.get("msku"))
                if msku:
                    totals[msku] += _number(item.get("volumeTotal"))
            if len(items) < length:
                break
            page += 1
        return dict(totals)

    async def _fbt_shipments(
        self, token: str, store_ids: list[str], as_of: date
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        length = 200
        start_date = as_of - timedelta(days=400)
        while True:
            data = await self._request(
                token,
                "/basicOpen/fbtShipment/cargo/list",
                {
                    "offset": offset,
                    "length": length,
                    "storeIdList": store_ids,
                    "timeType": 0,
                    "startTime": start_date.isoformat(),
                    "endTime": as_of.isoformat(),
                },
            )
            items = data.get("list", []) if isinstance(data, dict) else []
            records.extend(items)
            if len(items) < length:
                break
            offset += length

        normalized: list[dict[str, Any]] = []
        for record in records:
            cargo_code = str(record.get("cargoCode") or "").strip()
            if not cargo_code:
                continue
            item_totals: dict[str, dict[str, Any]] = {}
            for item in record.get("orderGoodList") or []:
                msku = str(item.get("msku") or "").strip()
                if not msku:
                    continue
                current = item_totals.setdefault(
                    msku,
                    {
                        "msku": msku,
                        "sku": str(item.get("sku") or ""),
                        "product_name": str(item.get("productName") or msku),
                        "image_url": str(item.get("imageUrl") or ""),
                        "declaration_qty": 0.0,
                        "shipment_qty": 0.0,
                        "signed_qty": 0.0,
                        "normal_qty": 0.0,
                        "defective_qty": 0.0,
                    },
                )
                current["declaration_qty"] += _number(
                    item.get("declarationQuantity")
                )
                current["shipment_qty"] += _number(item.get("shipmentQuantity"))
                current["signed_qty"] += _number(item.get("signedQuantity"))
                current["normal_qty"] += _number(item.get("normalQuantity"))
                current["defective_qty"] += _number(item.get("defectiveQuantity"))

            shipping_codes = []
            for info in record.get("shippingInfo") or []:
                value = str(info.get("shippingListCode") or "").strip()
                if value and value not in shipping_codes:
                    shipping_codes.append(value)
            normalized.append(
                {
                    "cargo_id": str(record.get("id") or ""),
                    "cargo_code": cargo_code,
                    "store_id": str(record.get("storeId") or ""),
                    "store_name": str(record.get("storeName") or ""),
                    "order_status": str(record.get("orderStatus") or ""),
                    "order_status_name": str(record.get("orderStatusName") or ""),
                    "ship_status": str(record.get("shipStatus") or ""),
                    "shipping_warehouse": str(
                        record.get("shippingWarehouse") or ""
                    ),
                    "create_time": _date_text(record.get("createTime")),
                    "delivery_time": _date_text(record.get("deliveryTime")),
                    "expected_delivery_time": _date_text(
                        record.get("expectedDeliveryTime")
                    ),
                    "actual_delivery_time": _date_text(
                        record.get("actualDeliveryTime")
                    ),
                    "shipping_list_codes": shipping_codes,
                    "items": list(item_totals.values()),
                }
            )
        return normalized

    async def _shipping_orders(
        self, token: str, store_ids: list[str], as_of: date
    ) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        offset = 0
        length = 200
        start_date = as_of - timedelta(days=400)
        while True:
            data = await self._request(
                token,
                "/basicOpen/multiplatform/query/shippingList",
                {
                    "platformCodes": ["10011"],
                    "offset": offset,
                    "length": length,
                    "timeField": 1,
                    "startTime": start_date.isoformat(),
                    "endTime": as_of.isoformat(),
                    "storeIds": store_ids,
                    "isDelete": 0,
                },
            )
            items = data.get("list", []) if isinstance(data, dict) else []
            records.extend(items)
            total = int(_number(data.get("total"))) if isinstance(data, dict) else 0
            offset += len(items)
            if not items or len(items) < length or (total and offset >= total):
                break

        normalized: list[dict[str, Any]] = []
        for record in records:
            code = str(record.get("shippingListCode") or "").strip()
            if not code:
                continue
            cargo_codes: list[str] = []
            for item in record.get("goodExtDetails") or []:
                cargo_code = str(item.get("cargoCode") or "").strip()
                if cargo_code and cargo_code not in cargo_codes:
                    cargo_codes.append(cargo_code)
            tracking_numbers: list[str] = []
            for item in record.get("logisticsDetails") or []:
                tracking = str(item.get("trackingNumber") or "").strip()
                if tracking and tracking not in tracking_numbers:
                    tracking_numbers.append(tracking)
            normalized.append(
                {
                    "shipping_list_code": code,
                    "status": str(record.get("shippingListStatus") or ""),
                    "status_name": str(
                        record.get("shippingListStatusDesc") or ""
                    ),
                    "logistics_provider": str(
                        record.get("logisticsProviderName") or ""
                    ),
                    "logistics_channel": str(
                        record.get("logisticsChannelName") or ""
                    ),
                    "logistics_type": str(record.get("logisticsTypeName") or ""),
                    "create_time": _date_text(record.get("gmtCreate")),
                    "delivery_time": _date_text(record.get("deliveryTime")),
                    "arrival_time": _date_text(record.get("arrivalTime")),
                    "expected_arrival_time": _date_text(
                        record.get("expectedArrivalTime")
                    ),
                    "actual_due_time": _date_text(record.get("actualDueTime")),
                    "actual_delivery_time": _date_text(
                        record.get("actualDeliveryTime")
                    ),
                    "order_logistics_status": str(
                        record.get("orderLogisticsStatus") or ""
                    ),
                    "tracking_numbers": tracking_numbers,
                    "cargo_codes": cargo_codes,
                }
            )
        return normalized

    async def collect(self, as_of: date | None = None) -> dict[str, Any]:
        as_of = as_of or date.today()
        token_response = await self.api.generate_access_token()
        token = token_response.access_token
        shops = await self._shops(token)
        if not shops:
            raise LingxingDataError("领星没有返回启用中的 TikTok 店铺。")

        products: list[dict[str, Any]] = []
        normalized_shops = []
        for shop in shops:
            store_id = str(shop.get("store_id") or "")
            if not store_id:
                continue
            store_name = str(shop.get("store_name") or store_id)
            normalized_shops.append(
                {
                    "store_id": store_id,
                    "sid": str(shop.get("sid") or ""),
                    "store_name": store_name,
                    "site_code": str(shop.get("country_code") or ""),
                }
            )
            # 领星对短时间并发请求有限流，按业务步骤串行拉取更稳定。
            listing_rows = await self._listings(token, store_id)
            fbt = await self._fbt(token, store_id)
            sales_7 = await self._sales(token, store_id, 7, as_of)
            sales_14 = await self._sales(token, store_id, 14, as_of)
            sales_30 = await self._sales(token, store_id, 30, as_of)

            for item in listing_rows:
                msku = str(item.get("msku") or "").strip()
                if not msku:
                    continue
                stock = fbt.get(
                    msku,
                    {
                        "total": 0.0,
                        "sellable": 0.0,
                        "in_transit": 0.0,
                        "all": 0.0,
                    },
                )
                products.append(
                    {
                        "product_name": str(item.get("pname") or msku),
                        "msku": msku,
                        "sku": str(item.get("sku") or ""),
                        "store_name": str(item.get("storeName") or store_name),
                        "store_id": store_id,
                        "site_code": str(item.get("siteCode") or ""),
                        "category": str(item.get("categoryName") or ""),
                        "product_status": str(
                            item.get("platformStatus") or "ACTIVATE"
                        ),
                        "image_url": str(item.get("imgUrl") or ""),
                        "tiktok_available": _number(
                            item.get("usableInventory")
                        ),
                        "tiktok_wait_outbound": _number(
                            item.get("waitOutboundQuantity")
                        ),
                        "sales_7": sales_7.get(msku, 0.0),
                        "sales_14": sales_14.get(msku, 0.0),
                        "sales_30": sales_30.get(msku, 0.0),
                        "avg_7": sales_7.get(msku, 0.0) / 7,
                        "avg_14": sales_14.get(msku, 0.0) / 14,
                        "avg_30": sales_30.get(msku, 0.0) / 30,
                        "fbt_total": stock["total"],
                        "fbt_sellable": stock["sellable"],
                        "fbt_in_transit": stock["in_transit"],
                        "fbt_all": stock["all"],
                    }
                )

        store_ids = [shop["store_id"] for shop in normalized_shops]
        shipments = await self._fbt_shipments(token, store_ids, as_of)
        shipping_orders = await self._shipping_orders(token, store_ids, as_of)

        return {
            "collected_at": datetime.now().isoformat(timespec="seconds"),
            "source_date": as_of.isoformat(),
            "stores": normalized_shops,
            "products": products,
            "shipments": shipments,
            "shipping_orders": shipping_orders,
            "source": "领星OpenAPI",
        }
