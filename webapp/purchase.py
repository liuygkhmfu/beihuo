from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
import math
from typing import Any

from .domain import parse_date
from .repository import Repository
from .service import build_dashboard


PURCHASE_MONTHS = [
    {"month": 7, "label": "7月", "multiplier": 1.0},
    {"month": 8, "label": "8月", "multiplier": 1.0},
    {"month": 9, "label": "9月", "multiplier": 1.5},
    {"month": 10, "label": "10月", "multiplier": 1.5},
    {"month": 11, "label": "11月", "multiplier": 2.25},
    {"month": 12, "label": "12月", "multiplier": 3.375},
]


def round_purchase_daily(value: Any) -> float:
    return float(
        Decimal(str(value or 0)).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )
    )


def default_completed_month(month: int) -> int:
    if month < 7:
        return 0
    return min(month, 12)


def purchase_month_plan(completed_month: int) -> list[dict[str, Any]]:
    result = []
    for source in PURCHASE_MONTHS:
        equivalent_days = float(source["multiplier"]) * 30
        result.append(
            {
                **source,
                "equivalent_days": equivalent_days,
                "is_completed": bool(
                    completed_month and int(source["month"]) <= completed_month
                ),
            }
        )
    return result


def remaining_equivalent_days(completed_month: int) -> float:
    return round(
        sum(
            item["equivalent_days"]
            for item in purchase_month_plan(completed_month)
            if not item["is_completed"]
        ),
        4,
    )


def _sku(product: dict[str, Any]) -> str:
    sku = str(product.get("sku") or "").strip()
    if sku:
        return sku
    msku = str(product.get("msku") or "").strip()
    return msku[:-3] if msku.upper().endswith("-US") else msku


def _aggregate_products(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for product in products:
        if product.get("is_planning_excluded"):
            continue
        sku = _sku(product)
        sku_key = sku.upper()
        if not sku_key:
            continue
        current = grouped.setdefault(
            sku_key,
            {
                "sku_key": sku_key,
                "sku": sku,
                "product_name": str(product.get("product_name") or ""),
                "image_url": str(product.get("image_url") or ""),
                "dynamic_daily": 0.0,
                "mskus": [],
                "stores": [],
            },
        )
        current["dynamic_daily"] += float(product.get("dynamic_daily") or 0)
        member_mskus = product.get("member_mskus") or [
            str(product.get("msku") or "")
        ]
        store_name = str(product.get("store_name") or "")
        for msku in member_mskus:
            msku = str(msku or "")
            if msku and msku not in current["mskus"]:
                current["mskus"].append(msku)
        if store_name and store_name not in current["stores"]:
            current["stores"].append(store_name)
        if not current["product_name"] and product.get("product_name"):
            current["product_name"] = str(product["product_name"])
        if not current["image_url"] and product.get("image_url"):
            current["image_url"] = str(product["image_url"])
    return sorted(grouped.values(), key=lambda item: item["sku_key"])


def build_purchase_plan(
    repository: Repository, as_of: str | None = None
) -> dict[str, Any]:
    dashboard = build_dashboard(repository, as_of)
    current_date = parse_date(dashboard["as_of"])
    season_year = current_date.year
    config = repository.get_purchase_plan_config(season_year)
    completed_month = int(
        config.get("completed_month", default_completed_month(current_date.month))
    )
    month_plan = purchase_month_plan(completed_month)
    remaining_days = remaining_equivalent_days(completed_month)
    overrides = repository.get_purchase_plan_overrides(season_year)

    items = []
    for product in _aggregate_products(dashboard["products"]):
        dynamic_daily = round_purchase_daily(product["dynamic_daily"])
        if dynamic_daily <= 0:
            continue
        override = overrides.get(product["sku_key"], {})
        daily_override = override.get("adopted_daily")
        rounded_daily_override = (
            round_purchase_daily(daily_override)
            if daily_override is not None
            else None
        )
        adopted_daily = (
            rounded_daily_override
            if rounded_daily_override is not None
            else dynamic_daily
        )
        extra_days = float(override.get("extra_days") or 0)
        system_qty = math.ceil(
            max(0.0, adopted_daily * (remaining_days + extra_days))
        )
        final_override = override.get("final_qty")
        final_qty = (
            math.ceil(max(0.0, float(final_override)))
            if final_override is not None
            else system_qty
        )
        items.append(
            {
                **product,
                "dynamic_daily": dynamic_daily,
                "daily_override": rounded_daily_override,
                "adopted_daily": adopted_daily,
                "remaining_days": remaining_days,
                "extra_days": round(extra_days, 3),
                "system_qty": system_qty,
                "final_override": (
                    float(final_override) if final_override is not None else None
                ),
                "final_qty": final_qty,
                "note": str(override.get("note") or ""),
                "has_manual_adjustment": bool(
                    daily_override is not None
                    or extra_days > 0
                    or final_override is not None
                    or override.get("note")
                ),
            }
        )

    total_days = round(
        sum(item["equivalent_days"] for item in month_plan), 4
    )
    summary = {
        "sku_count": len(items),
        "positive_sku_count": sum(item["final_qty"] > 0 for item in items),
        "dynamic_daily_total": round_purchase_daily(
            sum(item["dynamic_daily"] for item in items)
        ),
        "system_qty_total": sum(item["system_qty"] for item in items),
        "final_qty_total": sum(item["final_qty"] for item in items),
        "manual_adjustment_count": sum(
            item["has_manual_adjustment"] for item in items
        ),
    }
    return {
        "as_of": dashboard["as_of"],
        "season_year": season_year,
        "completed_month": completed_month,
        "total_equivalent_days": total_days,
        "remaining_equivalent_days": remaining_days,
        "month_plan": month_plan,
        "summary": summary,
        "items": items,
        "snapshot": dashboard["snapshot"],
        "calculation_note": (
            "剩余旺季目标量 =（剩余旺季等效天数 + 人工增加天数）× 采用日均；"
            "本版不扣FBT库存、FBT在途和历史采购。"
        ),
    }
