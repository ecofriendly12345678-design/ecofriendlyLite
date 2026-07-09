"""Virtual ledger backed by SQLite. Money stored as Decimal strings (TEXT).
This is where risk limits are enforced: duplicate set, cash, concurrency."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from agent.models import Opportunity, SetPurchase

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS positions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  opened_at TEXT NOT NULL,
  set_id TEXT NOT NULL,
  description TEXT NOT NULL,
  kind TEXT NOT NULL,
  n_sets TEXT NOT NULL,
  total_cost TEXT NOT NULL,
  guaranteed_payout TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open'
);
CREATE TABLE IF NOT EXISTS fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  position_id INTEGER NOT NULL REFERENCES positions(id),
  token_id TEXT NOT NULL,
  label TEXT NOT NULL,
  qty TEXT NOT NULL,
  avg_price TEXT NOT NULL,
  cost TEXT NOT NULL,
  last_mid TEXT
);
CREATE TABLE IF NOT EXISTS opportunities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  seen_at TEXT NOT NULL,
  set_id TEXT NOT NULL,
  description TEXT NOT NULL,
  cost_per_set TEXT NOT NULL,
  edge TEXT NOT NULL,
  acted INTEGER NOT NULL,
  reason TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  at TEXT NOT NULL,
  cash TEXT NOT NULL,
  positions_value TEXT NOT NULL,
  total_equity TEXT NOT NULL,
  unrealized_pnl TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class Summary:
    cash: Decimal
    positions_value: Decimal
    total_equity: Decimal
    unrealized_pnl: Decimal
    guaranteed_pnl: Decimal
    open_positions: int


class Portfolio:
    def __init__(self, db_path: str, starting_capital: Decimal):
        self._conn = sqlite3.connect(db_path)
        self._conn.executescript(_SCHEMA)
        row = self._conn.execute(
            "SELECT value FROM meta WHERE key='starting_capital'").fetchone()
        if row is None:
            self._conn.execute(
                "INSERT INTO meta(key, value) VALUES ('starting_capital', ?)",
                (str(starting_capital),))
            self._conn.commit()
            self._starting = starting_capital
        else:
            self._starting = Decimal(row[0])  # reopen: stored value wins

    def cash(self) -> Decimal:
        # Sum in Decimal, never SQLite REAL — money math stays exact.
        rows = self._conn.execute(
            "SELECT total_cost FROM positions WHERE status='open'").fetchall()
        spent = sum((Decimal(r[0]) for r in rows), Decimal("0"))
        return self._starting - spent

    def has_open_position(self, set_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM positions WHERE set_id=? AND status='open' LIMIT 1",
            (set_id,)).fetchone()
        return row is not None

    def _open_count(self) -> int:
        return self._conn.execute(
            "SELECT COUNT(*) FROM positions WHERE status='open'").fetchone()[0]

    def can_open(self, total_cost: Decimal, set_id: str,
                 max_concurrent: int) -> tuple[bool, str]:
        if self.has_open_position(set_id):
            return False, f"already have an open position on {set_id}"
        if self._open_count() >= max_concurrent:
            return False, f"max concurrent positions reached ({max_concurrent})"
        if total_cost > self.cash():
            return False, f"insufficient cash ({self.cash()}) for cost {total_cost}"
        return True, "ok"

    def open_position(self, purchase: SetPurchase) -> int:
        rs = purchase.result_set
        # `with conn:` = one transaction — commits on success, rolls back on
        # any exception. Without it, a failure between the position INSERT and
        # its fills INSERTs would leave an orphan row that the NEXT unrelated
        # commit silently persists, durably corrupting the ledger.
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO positions(opened_at, set_id, description, kind, n_sets,"
                " total_cost, guaranteed_payout, status)"
                " VALUES (?,?,?,?,?,?,?, 'open')",
                (_now(), rs.set_id, rs.description, rs.kind, str(purchase.n_sets),
                 str(purchase.total_cost), str(purchase.guaranteed_payout)))
            pid = cur.lastrowid
            for f in purchase.fills:
                self._conn.execute(
                    "INSERT INTO fills(position_id, token_id, label, qty, avg_price,"
                    " cost, last_mid) VALUES (?,?,?,?,?,?,?)",
                    (pid, f.token_id, f.label, str(f.qty), str(f.avg_price),
                     str(f.cost), str(f.avg_price)))
        return pid

    def record_opportunity(self, opp: Opportunity, acted: bool, reason: str) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO opportunities(seen_at, set_id, description, cost_per_set,"
                " edge, acted, reason) VALUES (?,?,?,?,?,?,?)",
                (_now(), opp.result_set.set_id, opp.result_set.description,
                 str(opp.cost), str(opp.edge), int(acted), reason))

    def _compute(self, mids: dict[str, Decimal] | None) -> Summary:
        cash = self.cash()
        value = Decimal("0")
        guaranteed = Decimal("0")
        cost_total = Decimal("0")
        with self._conn:
            positions = self._conn.execute(
                "SELECT id, total_cost, guaranteed_payout FROM positions"
                " WHERE status='open'").fetchall()
            for pid, total_cost, gpay in positions:
                cost_total += Decimal(total_cost)
                guaranteed += Decimal(gpay)
                for fid, tid, qty, last_mid in self._conn.execute(
                        "SELECT id, token_id, qty, last_mid FROM fills"
                        " WHERE position_id=?", (pid,)).fetchall():
                    mid = (mids or {}).get(tid)
                    if mid is not None:
                        self._conn.execute(
                            "UPDATE fills SET last_mid=? WHERE id=?", (str(mid), fid))
                    else:
                        mid = Decimal(last_mid) if last_mid is not None else Decimal("0")
                    value += Decimal(qty) * mid
        return Summary(
            cash=cash,
            positions_value=value,
            total_equity=cash + value,
            unrealized_pnl=value - cost_total,
            guaranteed_pnl=guaranteed - cost_total,
            open_positions=len(positions),
        )

    def mark_to_market(self, mids: dict[str, Decimal]) -> Summary:
        s = self._compute(mids)
        with self._conn:
            self._conn.execute(
                "INSERT INTO snapshots(at, cash, positions_value, total_equity,"
                " unrealized_pnl) VALUES (?,?,?,?,?)",
                (_now(), str(s.cash), str(s.positions_value), str(s.total_equity),
                 str(s.unrealized_pnl)))
        return s

    def summary(self) -> Summary:
        return self._compute(None)
