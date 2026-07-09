"""Local paper broker backed by live Polymarket book snapshots."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from agent.fill_engine import SimulatedFill, simulate_basket_buy
from agent.market_data import BookSnapshot
from agent.models import Fill, ResultSet, SetPurchase
from agent.portfolio import Portfolio
from agent.strategies import EntryProposal

_SCHEMA = """
CREATE TABLE IF NOT EXISTS paper_orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  strategy TEXT NOT NULL,
  side TEXT NOT NULL,
  kind TEXT NOT NULL,
  set_id TEXT NOT NULL,
  description TEXT NOT NULL,
  target_qty TEXT NOT NULL,
  max_total_cost TEXT,
  min_total_proceeds TEXT,
  time_in_force TEXT NOT NULL,
  status TEXT NOT NULL,
  reject_reason TEXT,
  last_match_source TEXT,
  last_match_fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS paper_order_legs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES paper_orders(id),
  token_id TEXT NOT NULL,
  label TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS paper_order_fills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id INTEGER NOT NULL REFERENCES paper_orders(id),
  token_id TEXT NOT NULL,
  label TEXT NOT NULL,
  qty TEXT NOT NULL,
  avg_price TEXT NOT NULL,
  amount TEXT NOT NULL,
  side TEXT NOT NULL,
  source TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  filled_at TEXT NOT NULL
);
"""


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class PaperOrder:
    id: int | None
    strategy: str
    side: str
    kind: str
    result_set: ResultSet
    target_qty: Decimal
    max_total_cost: Decimal | None
    min_total_proceeds: Decimal | None
    time_in_force: str
    status: str
    created_at: datetime
    updated_at: datetime

    @classmethod
    def from_entry_proposal(
        cls,
        proposal: EntryProposal,
        time_in_force: str = "ioc",
        created_at: datetime | None = None,
    ) -> PaperOrder:
        now = created_at or _now()
        purchase = proposal.purchase
        return cls(
            id=None,
            strategy=proposal.strategy,
            side="buy",
            kind="basket",
            result_set=purchase.result_set,
            target_qty=purchase.n_sets,
            max_total_cost=purchase.total_cost,
            min_total_proceeds=None,
            time_in_force=time_in_force,
            status="submitted",
            created_at=now,
            updated_at=now,
        )


@dataclass(frozen=True)
class BrokerOrderResult:
    order_id: int
    status: str
    message: str


@dataclass(frozen=True)
class BrokerMatchReport:
    filled: int
    rejected: int
    skipped: int
    messages: tuple[str, ...]


class PaperBroker:
    def __init__(
        self,
        portfolio: Portfolio,
        max_concurrent_positions: int,
        strategy_buckets: dict[str, Decimal],
        max_book_age_seconds: int | float,
    ):
        self._portfolio = portfolio
        self._conn = portfolio._conn
        self._conn.executescript(_SCHEMA)
        self._max_concurrent = max_concurrent_positions
        self._strategy_buckets = dict(strategy_buckets)
        self._max_book_age = timedelta(seconds=float(max_book_age_seconds))
        self._orders: dict[int, PaperOrder] = {}

    def submit_order(self, order: PaperOrder) -> BrokerOrderResult:
        created = order.created_at.isoformat()
        updated = order.updated_at.isoformat()
        rs = order.result_set
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO paper_orders(created_at, updated_at, strategy, side,"
                " kind, set_id, description, target_qty, max_total_cost,"
                " min_total_proceeds, time_in_force, status) VALUES"
                " (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    created,
                    updated,
                    order.strategy,
                    order.side,
                    order.kind,
                    rs.set_id,
                    rs.description,
                    str(order.target_qty),
                    str(order.max_total_cost) if order.max_total_cost is not None else None,
                    str(order.min_total_proceeds)
                    if order.min_total_proceeds is not None else None,
                    order.time_in_force,
                    "open",
                ),
            )
            order_id = cur.lastrowid
            for outcome in rs.outcomes:
                self._conn.execute(
                    "INSERT INTO paper_order_legs(order_id, token_id, label)"
                    " VALUES (?,?,?)",
                    (order_id, outcome.token_id, outcome.label),
                )
        opened = self._replace(order, id=order_id, status="open")
        self._orders[order_id] = opened
        return BrokerOrderResult(order_id, "open", "submitted")

    def cancel_order(self, order_id: int, reason: str) -> BrokerOrderResult:
        order = self._orders.get(order_id)
        if order is None:
            raise ValueError(f"order {order_id} does not exist")
        self._update_status(order_id, "canceled", reason)
        self._orders[order_id] = self._replace(order, status="canceled", updated_at=_now())
        return BrokerOrderResult(order_id, "canceled", reason)

    def open_orders(self) -> list[PaperOrder]:
        return [
            o for o in self._orders.values()
            if o.status in {"open", "submitted", "partially_filled"}
        ]

    def match_open_orders(
        self,
        snapshot: BookSnapshot,
        now: datetime | None = None,
    ) -> BrokerMatchReport:
        at = now or _now()
        messages: list[str] = []
        filled = rejected = skipped = 0

        if snapshot.source != "polymarket_cli":
            count = len(self.open_orders())
            return BrokerMatchReport(
                filled=0,
                rejected=0,
                skipped=count,
                messages=tuple(f"skip: non-live source {snapshot.source}" for _ in range(count)),
            )
        if at - snapshot.fetched_at > self._max_book_age:
            count = len(self.open_orders())
            return BrokerMatchReport(
                filled=0,
                rejected=0,
                skipped=count,
                messages=tuple("skip: stale book snapshot" for _ in range(count)),
            )

        for order in list(self.open_orders()):
            result = self._match_one(order, snapshot, at)
            messages.append(result.message)
            if result.status == "filled":
                filled += 1
            elif result.status == "rejected":
                rejected += 1
            else:
                skipped += 1
        return BrokerMatchReport(filled, rejected, skipped, tuple(messages))

    def _match_one(
        self,
        order: PaperOrder,
        snapshot: BookSnapshot,
        now: datetime,
    ) -> BrokerOrderResult:
        assert order.id is not None
        if order.side != "buy" or order.kind != "basket":
            return self._reject(order, "unsupported order type")
        missing = [tid for tid in order.result_set.token_ids if tid not in snapshot.books]
        if missing:
            return self._reject(order, f"missing fresh book for token {missing[0]}")

        simulated = simulate_basket_buy(order.result_set, snapshot.books, order.target_qty)
        if simulated is None:
            return self._reject(order, "insufficient depth")
        total_cost = sum((fill.amount for fill in simulated), Decimal("0"))
        if order.max_total_cost is not None and total_cost > order.max_total_cost:
            return self._reject(order, "cost exceeds max_total_cost")

        ok, reason = self._portfolio.can_open(
            total_cost,
            order.result_set.set_id,
            self._max_concurrent,
            strategy=order.strategy,
            bucket_usd=self._strategy_buckets.get(order.strategy),
        )
        if not ok:
            return self._reject(order, reason)

        purchase = SetPurchase(
            result_set=order.result_set,
            n_sets=order.target_qty,
            fills=tuple(self._to_portfolio_fill(fill) for fill in simulated),
            total_cost=total_cost,
        )
        self._portfolio.open_position(purchase, strategy=order.strategy)
        self._record_fills(order, simulated, snapshot, now)
        self._update_status(
            order.id,
            "filled",
            None,
            source=snapshot.source,
            fetched_at=snapshot.fetched_at,
        )
        self._orders[order.id] = self._replace(order, status="filled", updated_at=now)
        return BrokerOrderResult(order.id, "filled", f"filled order {order.id}")

    def _reject(self, order: PaperOrder, reason: str) -> BrokerOrderResult:
        assert order.id is not None
        self._update_status(order.id, "rejected", reason)
        self._orders[order.id] = self._replace(order, status="rejected", updated_at=_now())
        return BrokerOrderResult(order.id, "rejected", reason)

    def _record_fills(
        self,
        order: PaperOrder,
        fills: tuple[SimulatedFill, ...],
        snapshot: BookSnapshot,
        now: datetime,
    ) -> None:
        assert order.id is not None
        with self._conn:
            for fill in fills:
                self._conn.execute(
                    "INSERT INTO paper_order_fills(order_id, token_id, label, qty,"
                    " avg_price, amount, side, source, fetched_at, filled_at)"
                    " VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        order.id,
                        fill.token_id,
                        fill.label,
                        str(fill.qty),
                        str(fill.avg_price),
                        str(fill.amount),
                        order.side,
                        snapshot.source,
                        snapshot.fetched_at.isoformat(),
                        now.isoformat(),
                    ),
                )

    def _update_status(
        self,
        order_id: int,
        status: str,
        reason: str | None,
        source: str | None = None,
        fetched_at: datetime | None = None,
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE paper_orders SET status=?, reject_reason=?, updated_at=?,"
                " last_match_source=COALESCE(?, last_match_source),"
                " last_match_fetched_at=COALESCE(?, last_match_fetched_at)"
                " WHERE id=?",
                (
                    status,
                    reason,
                    _now().isoformat(),
                    source,
                    fetched_at.isoformat() if fetched_at is not None else None,
                    order_id,
                ),
            )

    @staticmethod
    def _to_portfolio_fill(fill: SimulatedFill) -> Fill:
        return Fill(
            token_id=fill.token_id,
            label=fill.label,
            qty=fill.qty,
            avg_price=fill.avg_price,
            cost=fill.amount,
        )

    @staticmethod
    def _replace(order: PaperOrder, **changes) -> PaperOrder:
        data = order.__dict__.copy()
        data.update(changes)
        return PaperOrder(**data)
