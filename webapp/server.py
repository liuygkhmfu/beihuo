from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import threading
import webbrowser
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .arrival_tracking import (
    import_arrival_workbook,
    reconcile_saved_arrivals,
)
from .exporter import (
    build_arrival_tracking_export,
    build_export,
    build_purchase_export,
)
from .lingxing_provider import LingxingDataError, LingxingProvider
from .product_groups import canonical_msku, group_member_mskus
from .purchase import build_purchase_plan
from .repository import Repository
from .service import (
    NoSnapshotError,
    build_dashboard,
    build_product_detail,
    build_shipments,
)


STATIC_ROOT = Path(__file__).resolve().parent / "static"
repository = Repository()


def _expand_product_status_items(
    items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    snapshot = repository.latest_snapshot() or {}
    products = snapshot.get("products", [])
    expanded = []
    for item in items:
        store_id = str(item.get("store_id") or "")
        msku = str(item.get("msku") or "")
        status = str(item.get("status") or "active")
        members = group_member_mskus(products, store_id, msku) or [msku]
        expanded.extend(
            {
                "store_id": store_id,
                "msku": member_msku,
                "status": status,
            }
            for member_msku in members
        )
    return expanded


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "TKReplenishment/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        print("[%s] %s" % (self.log_date_time_string(), format % args))

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        if length > 2 * 1024 * 1024:
            raise ValueError("请求内容过大")
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _read_multipart(self) -> tuple[str, bytes, dict[str, str]]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            raise ValueError("没有收到上传文件")
        if length > 15 * 1024 * 1024:
            raise ValueError("上传文件不能超过15MB")
        content_type = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in content_type:
            raise ValueError("请使用表单方式上传Excel文件")
        raw = self.rfile.read(length)
        message = BytesParser(policy=policy.default).parsebytes(
            (
                f"Content-Type: {content_type}\r\n"
                "MIME-Version: 1.0\r\n\r\n"
            ).encode("utf-8")
            + raw
        )
        filename = ""
        content = b""
        fields: dict[str, str] = {}
        for part in message.iter_parts():
            field_name = part.get_param("name", header="content-disposition")
            part_filename = part.get_filename()
            payload = part.get_payload(decode=True) or b""
            if part_filename:
                filename = Path(part_filename).name
                content = payload
            elif field_name:
                fields[str(field_name)] = payload.decode(
                    part.get_content_charset() or "utf-8", errors="replace"
                )
        if not filename or not content:
            raise ValueError("没有识别到上传的Excel文件")
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("目前只支持.xlsx格式")
        return filename, content, fields

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404, "Not found")
            return
        content = path.read_bytes()
        mime, _ = mimetypes.guess_type(path.name)
        self.send_response(200)
        self.send_header(
            "Content-Type",
            (mime or "application/octet-stream")
            + ("; charset=utf-8" if (mime or "").startswith("text/") else ""),
        )
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route = parsed.path
        query = parse_qs(parsed.query)
        try:
            if route == "/api/health":
                self._json({"ok": True, "service": "TK补货决策台"})
                return
            if route == "/api/dashboard":
                as_of = query.get("as_of", [None])[0]
                self._json({"ok": True, "data": build_dashboard(repository, as_of)})
                return
            if route == "/api/product":
                as_of = query.get("as_of", [None])[0]
                msku = query.get("msku", [""])[0]
                store_id = query.get("store_id", [""])[0]
                self._json(
                    {
                        "ok": True,
                        "data": build_product_detail(
                            repository, msku, store_id, as_of
                        ),
                    }
                )
                return
            if route == "/api/settings":
                self._json(
                    {
                        "ok": True,
                        "settings": repository.get_settings(),
                        "schedule": repository.get_schedule(),
                    }
                )
                return
            if route == "/api/shipments":
                as_of = query.get("as_of", [None])[0]
                self._json(
                    {"ok": True, "data": build_shipments(repository, as_of)}
                )
                return
            if route == "/api/purchase-plan":
                as_of = query.get("as_of", [None])[0]
                self._json(
                    {"ok": True, "data": build_purchase_plan(repository, as_of)}
                )
                return
            if route == "/api/purchase-plan/export":
                as_of = query.get("as_of", [None])[0]
                purchase_plan = build_purchase_plan(repository, as_of)
                body = build_purchase_export(purchase_plan)
                filename = "TK备货.xlsx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename*=UTF-8''" + quote(filename),
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/export":
                as_of = query.get("as_of", [None])[0]
                dashboard = build_dashboard(repository, as_of)
                body = build_export(
                    dashboard, build_shipments(repository, dashboard["as_of"])
                )
                filename = f"{dashboard['as_of']}_TK补货建议.xlsx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename*=UTF-8''" + quote(filename),
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route == "/api/arrival-tracking/export":
                as_of = query.get("as_of", [None])[0]
                shipment_data = build_shipments(repository, as_of)
                body = build_arrival_tracking_export(shipment_data)
                filename = f"{shipment_data['as_of']}_到货跟踪.xlsx"
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
                self.send_header(
                    "Content-Disposition",
                    "attachment; filename*=UTF-8''" + quote(filename),
                )
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if route in ("/", "/index.html"):
                self._serve_file(STATIC_ROOT / "index.html")
                return

            candidate = (STATIC_ROOT / unquote(route.lstrip("/"))).resolve()
            try:
                candidate.relative_to(STATIC_ROOT.resolve())
            except ValueError:
                self.send_error(403)
                return
            self._serve_file(candidate)
        except NoSnapshotError as exc:
            self._json({"ok": False, "error": str(exc), "needs_pull": True}, 422)
        except KeyError as exc:
            self._json({"ok": False, "error": str(exc)}, 404)
        except Exception as exc:
            self._json({"ok": False, "error": f"服务异常：{exc}"}, 500)

    def do_POST(self) -> None:
        route = urlparse(self.path).path
        try:
            if route == "/api/arrival-tracking/import":
                filename, content, fields = self._read_multipart()
                result = import_arrival_workbook(
                    repository,
                    content,
                    filename,
                    fields.get("store_id", ""),
                )
                self._json(
                    {
                        "ok": True,
                        "import": result,
                        "data": build_shipments(repository, fields.get("as_of")),
                    }
                )
                return
            payload = self._read_json()
            if route == "/api/pull-latest":
                provider = LingxingProvider()
                snapshot = asyncio.run(provider.collect())
                saved = repository.save_snapshot(snapshot)
                reconcile_saved_arrivals(repository)
                dashboard = build_dashboard(
                    repository, payload.get("as_of") or saved["source_date"]
                )
                self._json({"ok": True, "data": dashboard})
                return
            if route == "/api/settings":
                settings = repository.save_settings(payload.get("settings", {}))
                self._json({"ok": True, "settings": settings})
                return
            if route == "/api/schedule":
                schedule = repository.save_schedule(payload.get("schedule", []))
                self._json({"ok": True, "schedule": schedule})
                return
            if route == "/api/purchase-plan":
                as_of = str(payload.get("as_of") or "")
                season_year = int(payload["season_year"])
                repository.save_purchase_plan_config(
                    season_year, int(payload["completed_month"])
                )
                repository.save_purchase_plan_overrides(
                    season_year, payload.get("items", [])
                )
                self._json(
                    {
                        "ok": True,
                        "data": build_purchase_plan(repository, as_of or None),
                    }
                )
                return
            if route == "/api/decision":
                decision_msku = canonical_msku(payload["msku"])
                decision = repository.save_decision(
                    decision_msku,
                    str(payload["store_id"]),
                    str(payload["week_date"]),
                    payload,
                )
                self._json({"ok": True, "decision": decision})
                return
            if route == "/api/shipment-override":
                shipment = repository.save_shipment_override(
                    str(payload["cargo_code"]), payload
                )
                self._json({"ok": True, "shipment": shipment})
                return
            if route == "/api/product-alias":
                alias = repository.save_product_alias(
                    str(payload["item_id"]),
                    str(payload.get("store_id") or ""),
                    str(payload["canonical_msku"]),
                )
                self._json(
                    {
                        "ok": True,
                        "alias": alias,
                        "data": build_shipments(repository, payload.get("as_of")),
                    }
                )
                return
            if route == "/api/product-status":
                if isinstance(payload.get("items"), list):
                    product_statuses = (
                        repository.save_product_planning_statuses(
                            _expand_product_status_items(payload["items"])
                        )
                    )
                    self._json(
                        {
                            "ok": True,
                            "product_statuses": product_statuses,
                        }
                    )
                    return
                product_statuses = repository.save_product_planning_statuses(
                    _expand_product_status_items(
                        [
                            {
                                "store_id": str(payload["store_id"]),
                                "msku": str(payload["msku"]),
                                "status": str(payload["status"]),
                            }
                        ]
                    )
                )
                self._json(
                    {
                        "ok": True,
                        "product_status": product_statuses[0],
                        "product_statuses": product_statuses,
                    }
                )
                return
            if route == "/api/product-group":
                store_id = str(payload["store_id"])
                canonical = canonical_msku(payload["canonical_msku"])
                execution_msku = str(payload["execution_msku"])
                snapshot = repository.latest_snapshot() or {}
                members = group_member_mskus(
                    snapshot.get("products", []),
                    store_id,
                    canonical,
                )
                if execution_msku not in members:
                    raise ValueError("执行MSKU必须属于当前商品组")
                group_setting = repository.save_product_group_execution(
                    store_id,
                    canonical,
                    execution_msku,
                )
                self._json(
                    {
                        "ok": True,
                        "product_group": group_setting,
                    }
                )
                return
            self._json({"ok": False, "error": "接口不存在"}, 404)
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
        except LingxingDataError as exc:
            self._json({"ok": False, "error": str(exc)}, 422)
        except Exception as exc:
            self._json({"ok": False, "error": f"服务异常：{exc}"}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="TK补货决策工作台")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), DashboardHandler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"TK补货决策工作台已启动：{url}")
    print("按 Ctrl+C 停止服务。")
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
