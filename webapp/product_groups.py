from __future__ import annotations

import re
from typing import Any


US_SUFFIX_PATTERN = re.compile(r"-US$", re.IGNORECASE)
SUM_FIELDS = (
    "sales_7",
    "sales_14",
    "sales_30",
    "avg_7",
    "avg_14",
    "avg_30",
    "fbt_total",
    "fbt_sellable",
    "fbt_in_transit",
    "tiktok_available",
    "tiktok_wait_outbound",
)


def canonical_msku(value: Any) -> str:
    msku = str(value or "").strip()
    return US_SUFFIX_PATTERN.sub("", msku)


def product_group_key(store_id: Any, msku: Any) -> tuple[str, str]:
    return (
        str(store_id or "").strip(),
        canonical_msku(msku).upper(),
    )


def group_member_mskus(
    products: list[dict[str, Any]],
    store_id: Any,
    msku: Any,
) -> list[str]:
    target = product_group_key(store_id, msku)
    members = {
        str(product.get("msku") or "").strip()
        for product in products
        if product_group_key(product.get("store_id"), product.get("msku"))
        == target
        and str(product.get("msku") or "").strip()
    }
    return sorted(
        members,
        key=lambda item: (
            item.upper().endswith("-US"),
            item.upper(),
        ),
    )


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _is_active_listing(product: dict[str, Any]) -> bool:
    status = str(product.get("product_status") or "").strip().upper()
    return status not in {
        "DEACTIVATE",
        "DEACTIVATED",
        "DELETE",
        "DELETED",
        "INACTIVE",
        "OFFLINE",
    }


def select_execution_product(
    members: list[dict[str, Any]],
    configured_msku: str | None = None,
) -> dict[str, Any]:
    configured_upper = str(configured_msku or "").strip().upper()
    if configured_upper:
        configured = next(
            (
                item
                for item in members
                if str(item.get("msku") or "").strip().upper()
                == configured_upper
            ),
            None,
        )
        if configured:
            return configured

    def score(item: dict[str, Any]) -> tuple[Any, ...]:
        sales = sum(
            _number(item.get(field))
            for field in ("sales_7", "sales_14", "sales_30")
        )
        if sales <= 0:
            sales = sum(
                _number(item.get(field))
                for field in ("avg_7", "avg_14", "avg_30")
            )
        inventory = sum(
            _number(item.get(field))
            for field in ("fbt_total", "fbt_in_transit")
        )
        msku = str(item.get("msku") or "").strip()
        return (
            int(_is_active_listing(item)),
            int(sales > 0),
            sales,
            int(msku.upper().endswith("-US")),
            inventory,
            msku.upper(),
        )

    return max(members, key=score)


def _planning_status_for_group(
    members: list[dict[str, Any]],
    statuses: dict[tuple[str, str], dict[str, Any]],
    store_id: str,
    canonical: str,
) -> tuple[str, str | None]:
    member_mskus = {
        str(member.get("msku") or "").strip() for member in members
    }
    records = [
        record
        for (record_store, record_msku), record in statuses.items()
        if record_store == store_id
        and (
            record_msku in member_mskus
            or canonical_msku(record_msku).upper() == canonical.upper()
        )
    ]
    if not records:
        return "active", None
    latest = max(records, key=lambda item: str(item.get("updated_at") or ""))
    return (
        str(latest.get("status") or "active"),
        str(latest.get("updated_at") or "") or None,
    )


def aggregate_product_groups(
    products: list[dict[str, Any]],
    statuses: dict[tuple[str, str], dict[str, Any]] | None = None,
    group_settings: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    statuses = statuses or {}
    group_settings = group_settings or {}
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for product in products:
        msku = str(product.get("msku") or "").strip()
        if not msku:
            continue
        key = product_group_key(product.get("store_id"), msku)
        # Exact duplicate listing rows must not double inventory or sales.
        grouped.setdefault(key, {})[msku.upper()] = product

    result: list[dict[str, Any]] = []
    for (store_id, canonical_upper), member_index in grouped.items():
        members = list(member_index.values())
        canonical = canonical_msku(members[0].get("msku"))
        setting = group_settings.get((store_id, canonical_upper), {})
        execution = select_execution_product(
            members,
            str(setting.get("execution_msku") or ""),
        )
        member_mskus = sorted(
            (str(item.get("msku") or "").strip() for item in members),
            key=lambda item: (
                item.upper().endswith("-US"),
                item.upper(),
            ),
        )
        status, status_updated_at = _planning_status_for_group(
            members,
            statuses,
            store_id,
            canonical,
        )
        combined = dict(execution)
        for field in SUM_FIELDS:
            combined[field] = sum(_number(item.get(field)) for item in members)
        combined["fbt_all"] = (
            combined["fbt_total"] + combined["fbt_in_transit"]
        )

        sku_values = {
            str(item.get("sku") or "").strip()
            for item in members
            if str(item.get("sku") or "").strip()
        }
        combined.update(
            {
                "store_id": store_id,
                "msku": str(execution.get("msku") or canonical),
                "execution_msku": str(
                    execution.get("msku") or canonical
                ),
                "decision_msku": canonical,
                "canonical_msku": canonical,
                "product_group_id": f"{store_id}|{canonical_upper}",
                "sku": (
                    next(iter(sku_values))
                    if len(sku_values) == 1
                    else str(execution.get("sku") or canonical)
                ),
                "member_mskus": member_mskus,
                "member_count": len(member_mskus),
                "is_grouped": len(member_mskus) > 1,
                "group_members": [
                    {
                        "msku": str(item.get("msku") or ""),
                        "sku": str(item.get("sku") or ""),
                        "product_name": str(
                            item.get("product_name") or ""
                        ),
                        "avg_7": _number(item.get("avg_7")),
                        "avg_14": _number(item.get("avg_14")),
                        "avg_30": _number(item.get("avg_30")),
                        "fbt_total": _number(item.get("fbt_total")),
                        "fbt_sellable": _number(
                            item.get("fbt_sellable")
                        ),
                        "fbt_in_transit": _number(
                            item.get("fbt_in_transit")
                        ),
                    }
                    for item in sorted(
                        members,
                        key=lambda item: str(
                            item.get("msku") or ""
                        ).upper(),
                    )
                ],
                "planning_status": status,
                "planning_status_updated_at": status_updated_at,
                "group_sku_conflict": len(sku_values) > 1,
            }
        )
        result.append(combined)
    return result
