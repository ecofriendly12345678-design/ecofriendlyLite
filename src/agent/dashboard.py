"""Tiny local dashboard server for the SQLite paper ledger."""
from __future__ import annotations

import argparse
import json
import sqlite3
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
HTML_PATH = ROOT / "dashboard.html"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone()
    return row is not None


def _rows(conn: sqlite3.Connection, sql: str, params=()) -> list[dict[str, Any]]:
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def _decimal_str(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _normalize_money(row: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    out = dict(row)
    for field in fields:
        if out.get(field) is not None:
            out[field] = _decimal_str(Decimal(str(out[field])))
    return out


def _starting_capital(conn: sqlite3.Connection) -> str:
    if not _table_exists(conn, "meta"):
        return "0"
    row = conn.execute(
        "SELECT value FROM meta WHERE key='starting_capital'"
    ).fetchone()
    return row["value"] if row is not None else "0"


def _compute_cash_and_guaranteed(conn: sqlite3.Connection) -> tuple[str, str, int]:
    if not _table_exists(conn, "positions"):
        return "0", "0", 0

    cash = Decimal(_starting_capital(conn))
    guaranteed = Decimal("0")
    open_positions = 0
    for row in conn.execute(
        "SELECT status, total_cost, proceeds, guaranteed_payout FROM positions"
    ).fetchall():
        total_cost = Decimal(row["total_cost"])
        cash -= total_cost
        if row["status"] == "closed" and row["proceeds"] is not None:
            cash += Decimal(row["proceeds"])
        if row["status"] == "open":
            open_positions += 1
            guaranteed += Decimal(row["guaranteed_payout"]) - total_cost
    return _decimal_str(cash), _decimal_str(guaranteed), open_positions


def _summary(conn: sqlite3.Connection) -> dict[str, Any]:
    cash, guaranteed_pnl, open_positions = _compute_cash_and_guaranteed(conn)
    summary = {
        "cash": cash,
        "positions_value": "0",
        "total_equity": cash,
        "unrealized_pnl": "0",
        "guaranteed_pnl": guaranteed_pnl,
        "open_positions": open_positions,
    }
    if _table_exists(conn, "snapshots"):
        row = conn.execute(
            "SELECT cash, positions_value, total_equity, unrealized_pnl "
            "FROM snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is not None:
            summary.update(_normalize_money(
                dict(row),
                ("cash", "positions_value", "total_equity", "unrealized_pnl"),
            ))
            summary["cash"] = cash
            summary["guaranteed_pnl"] = guaranteed_pnl
            summary["open_positions"] = open_positions
    return summary


def load_dashboard_state(db_path: str) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        orders = []
        if _table_exists(conn, "paper_orders"):
            orders = _rows(
                conn,
                "SELECT id, created_at, updated_at, strategy, side, kind, set_id, "
                "description, target_qty, max_total_cost, min_total_proceeds, "
                "time_in_force, status, reject_reason, last_match_source, "
                "last_match_fetched_at FROM paper_orders ORDER BY id DESC LIMIT 100",
            )

        fills = []
        if _table_exists(conn, "paper_order_fills"):
            fills = _rows(
                conn,
                "SELECT id, order_id, token_id, label, qty, avg_price, amount, side, "
                "source, fetched_at, filled_at FROM paper_order_fills "
                "ORDER BY id DESC LIMIT 200",
            )

        positions = []
        if _table_exists(conn, "positions"):
            positions = _rows(
                conn,
                "SELECT id, opened_at, set_id, description, kind, strategy, n_sets, "
                "total_cost, guaranteed_payout, status, closed_at, proceeds, "
                "realized_pnl, close_reason FROM positions ORDER BY id DESC LIMIT 100",
            )

        equity_curve = []
        if _table_exists(conn, "snapshots"):
            equity_curve = [
                _normalize_money(
                    row,
                    ("cash", "positions_value", "total_equity", "unrealized_pnl"),
                )
                for row in _rows(
                    conn,
                    "SELECT at, cash, positions_value, total_equity, unrealized_pnl "
                    "FROM (SELECT * FROM snapshots ORDER BY id DESC LIMIT 200) "
                    "ORDER BY id ASC",
                )
            ]

        return {
            "summary": _summary(conn),
            "orders": orders,
            "fills": fills,
            "positions": positions,
            "equity_curve": equity_curve,
        }
    finally:
        conn.close()


class DashboardHandler(BaseHTTPRequestHandler):
    db_path = "virtual_ledger.db"

    def do_GET(self) -> None:  # noqa: N802 - stdlib hook
        if self.path in {"/", "/dashboard.html"}:
            self._send_bytes(HTML_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if self.path == "/api/state":
            payload = json.dumps(load_dashboard_state(self.db_path)).encode()
            self._send_bytes(payload, "application/json; charset=utf-8")
            return
        self.send_error(404)

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        return

    def _send_bytes(self, body: bytes, content_type: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local Polymarket paper dashboard")
    parser.add_argument("--db", default="virtual_ledger.db")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)

    DashboardHandler.db_path = args.db
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"dashboard: {url} (db={args.db})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopping dashboard.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
