# Polymarket Live Paper Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local paper broker that simulates Polymarket orders from fresh live CLOB books while preserving the repository's read-only safety invariant.

**Architecture:** The live loop fetches one fresh `BookSnapshot` per tick via `PolymarketCli.get_books()`. Strategies produce entry proposals; the broker converts accepted proposals to local orders, matches IOC orders against that same fresh snapshot, records an order/fill audit trail, and opens local portfolio positions. The broker never calls Polymarket itself and never uses cached books for live fills.

**Tech Stack:** Python 3.13, stdlib dataclasses/sqlite3/datetime/decimal, `pyyaml`, `pytest`, existing `PolymarketCli` wrapper.

## Global Constraints

- Live mode must fetch current order books from `PolymarketCli.get_books()` immediately before broker matching.
- The broker must not fill from cached books from a previous tick.
- Every broker match stores `source="polymarket_cli"` and `fetched_at`.
- Only `src/agent/cli.py` may import `subprocess`; no wallet/private-key/auth/signing path may be introduced.
- All prices, sizes, cash, proceeds, and PnL use `Decimal` and are persisted as strings.
- Polling is near-real-time through `poll_interval_seconds`; WebSocket ingestion is out of scope.

---

### Task 1: Fresh Snapshot And Fill Engine

**Files:**
- Create: `src/agent/market_data.py`
- Create: `src/agent/fill_engine.py`
- Test: `tests/test_fill_engine.py`

**Interfaces:**
- Produces: `BookSnapshot(fetched_at: datetime, source: str, books: dict[str, OrderBook])`
- Produces: `SimulatedFill(token_id: str, label: str, qty: Decimal, avg_price: Decimal, amount: Decimal)`
- Produces: `simulate_buy_leg(book: OrderBook, label: str, qty: Decimal) -> SimulatedFill | None`
- Produces: `simulate_sell_leg(book: OrderBook, label: str, qty: Decimal) -> SimulatedFill | None`
- Produces: `simulate_basket_buy(result_set: ResultSet, books: dict[str, OrderBook], qty: Decimal) -> tuple[SimulatedFill, ...] | None`

- [ ] **Step 1: Write failing tests**

Create `tests/test_fill_engine.py` with tests:

```python
from datetime import datetime, timezone
from decimal import Decimal

from agent.fill_engine import simulate_basket_buy, simulate_buy_leg, simulate_sell_leg
from agent.market_data import BookSnapshot
from agent.models import BookLevel, OrderBook, Outcome, ResultSet


def book(token_id):
    return OrderBook(
        token_id,
        bids=[BookLevel(Decimal("0.50"), Decimal("5")), BookLevel(Decimal("0.40"), Decimal("10"))],
        asks=[BookLevel(Decimal("0.55"), Decimal("5")), BookLevel(Decimal("0.60"), Decimal("10"))],
    )


def test_book_snapshot_records_live_source():
    snapshot = BookSnapshot(datetime(2026, 7, 9, tzinfo=timezone.utc), "polymarket_cli", {"1": book("1")})
    assert snapshot.source == "polymarket_cli"
    assert snapshot.books["1"].best_ask.price == Decimal("0.55")


def test_simulate_buy_leg_walks_asks():
    fill = simulate_buy_leg(book("1"), "Yes", Decimal("6"))
    assert fill.avg_price == Decimal("3.35") / Decimal("6")
    assert fill.amount == Decimal("3.35")


def test_simulate_sell_leg_walks_bids():
    fill = simulate_sell_leg(book("1"), "Yes", Decimal("6"))
    assert fill.avg_price == Decimal("2.90") / Decimal("6")
    assert fill.amount == Decimal("2.90")


def test_simulate_basket_buy_requires_all_legs():
    rs = ResultSet("s", "Pair", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    assert simulate_basket_buy(rs, {"1": book("1")}, Decimal("1")) is None
```

- [ ] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_fill_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.fill_engine'` or `agent.market_data`.

- [ ] **Step 3: Implement minimal code**

Add dataclasses and depth-walking helpers in `src/agent/market_data.py` and `src/agent/fill_engine.py`.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_fill_engine.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/market_data.py src/agent/fill_engine.py tests/test_fill_engine.py
git commit -m "feat: add live snapshot fill engine"
```

### Task 2: Paper Broker Order Lifecycle

**Files:**
- Create: `src/agent/paper_broker.py`
- Test: `tests/test_paper_broker.py`

**Interfaces:**
- Consumes: `BookSnapshot`, `simulate_basket_buy`, `Portfolio`
- Produces: `PaperOrder`, `BrokerOrderResult`, `BrokerMatchReport`, `PaperBroker`
- Produces: `PaperBroker.submit_order(order: PaperOrder) -> BrokerOrderResult`
- Produces: `PaperBroker.match_open_orders(snapshot: BookSnapshot, now: datetime | None = None) -> BrokerMatchReport`

- [ ] **Step 1: Write failing tests**

Create tests for:

```python
def test_ioc_basket_order_fills_from_fresh_polymarket_snapshot(tmp_path): ...
def test_ioc_order_rejects_missing_fresh_leg_book(tmp_path): ...
def test_stale_snapshot_does_not_fill_order(tmp_path): ...
def test_cost_above_limit_rejects_order(tmp_path): ...
```

The first test constructs a `Portfolio`, submits a buy basket order for qty `10`,
matches against a `BookSnapshot(source="polymarket_cli")`, and asserts:

```python
assert report.filled == 1
assert portfolio.summary().open_positions == 1
assert portfolio.cash() == Decimal("990.3")
```

- [ ] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_paper_broker.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'agent.paper_broker'`.

- [ ] **Step 3: Implement broker dataclasses and schema**

`paper_broker.py` creates `paper_orders`, `paper_order_legs`, and
`paper_order_fills` tables on the same sqlite connection used by `Portfolio`.
It records order status transitions and fill audit data.

- [ ] **Step 4: Implement matching**

IOC basket buy orders fill only when:
- `snapshot.source == "polymarket_cli"`;
- `now - snapshot.fetched_at <= max_book_age`;
- every leg has a fresh book;
- all legs have enough ask depth;
- `total_cost <= max_total_cost`;
- `Portfolio.can_open(..., strategy, bucket_usd)` passes.

- [ ] **Step 5: Verify green**

Run: `.venv/bin/python -m pytest tests/test_paper_broker.py tests/test_portfolio.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent/paper_broker.py tests/test_paper_broker.py
git commit -m "feat: add local paper broker"
```

### Task 3: Strategy Proposals Become Paper Orders

**Files:**
- Modify: `src/agent/strategies/__init__.py`
- Modify: `src/agent/paper_broker.py`
- Test: `tests/test_paper_broker.py`

**Interfaces:**
- Consumes: `EntryProposal(strategy: str, purchase: SetPurchase, reason: str)`
- Produces: `PaperOrder.from_entry_proposal(proposal: EntryProposal, time_in_force: str = "ioc") -> PaperOrder`

- [ ] **Step 1: Write failing test**

Add:

```python
def test_order_from_entry_proposal_preserves_strategy_and_limits():
    proposal = EntryProposal("implication", purchase, "edge=0.03")
    order = PaperOrder.from_entry_proposal(proposal)
    assert order.strategy == "implication"
    assert order.target_qty == purchase.n_sets
    assert order.max_total_cost == purchase.total_cost
    assert order.result_set is purchase.result_set
```

- [ ] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_paper_broker.py::test_order_from_entry_proposal_preserves_strategy_and_limits -q`
Expected: FAIL with missing classmethod.

- [ ] **Step 3: Implement converter**

Implement `PaperOrder.from_entry_proposal` in `paper_broker.py`.

- [ ] **Step 4: Verify green**

Run: `.venv/bin/python -m pytest tests/test_paper_broker.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/agent/paper_broker.py tests/test_paper_broker.py
git commit -m "feat: convert strategy proposals to paper orders"
```

### Task 4: Live Agent Integration

**Files:**
- Modify: `src/agent/agent.py`
- Modify: `src/agent/report.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: `BookSnapshot`, `PaperBroker`, existing `CompleteSetStrategy`
- Produces: one fresh snapshot per tick and live report line with `source=polymarket_cli` and `fetched_at=...`

- [ ] **Step 1: Write failing integration test**

Add a test that uses fake CLI books, calls the live tick path, and asserts:

```python
assert summary.open_positions == 1
assert fake_cli.get_books_calls == 1
assert "source=polymarket_cli" in captured_output
```

- [ ] **Step 2: Verify red**

Run: `.venv/bin/python -m pytest tests/test_agent.py::test_tick_routes_complete_set_through_paper_broker -q`
Expected: FAIL because `tick()` still opens positions directly.

- [ ] **Step 3: Refactor tick**

`tick()` should:
- fetch fresh books once;
- create `BookSnapshot(fetched_at=now, source="polymarket_cli", books=books)`;
- create/receive `PaperBroker`;
- convert proposals to `PaperOrder`;
- match IOC orders against the same snapshot;
- mark to market from the same books.

- [ ] **Step 4: Preserve v1 smoke behavior**

Run: `PYTHONPATH=src .venv/bin/python -m agent.agent --config <(sed 's#db_path: virtual_ledger.db#db_path: /tmp/polymarket-agent-paper-broker-ledger.db#' config.yaml) --once`
Expected: prints `source=polymarket_cli` and exits 0.

- [ ] **Step 5: Verify full suite**

Run: `.venv/bin/python -m pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/agent/agent.py src/agent/report.py tests/test_agent.py
git commit -m "feat: route live ticks through paper broker"
```
