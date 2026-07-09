# Polymarket Live Paper Broker Design

- Date: 2026-07-09
- Status: approved for implementation planning
- Branch: `codex/v2-agent-scaffold`
- Builds on: v2 strategy scaffold commit `d2c8cdd`

## 1. Goal

Build a local paper broker that makes the agent feel connected to a trading
platform while remaining 100% read-only against Polymarket.

The broker uses live Polymarket CLOB order books as the market-data source,
simulates order lifecycle and fills locally, and records orders/fills/positions
in SQLite. It must never submit, cancel, approve, sign, bridge, or otherwise
perform a real transaction.

## 2. Hard Constraints

- **Live data only in live mode:** every live tick fetches current order books
  from `PolymarketCli.get_books()` immediately before matching orders.
- **No stale fills:** the broker may not fill an order from cached books from a
  previous tick. If the current tick has no fresh book for a token, that order
  remains open or is rejected according to its time-in-force.
- **Source attribution:** every broker matching cycle stores `fetched_at`,
  `source="polymarket_cli"`, and the token ids included in the book batch.
- **Read-only invariant:** only `src/agent/cli.py` may import `subprocess`, and
  it may expose only read-only Polymarket CLI commands. `tests/test_safety.py`
  remains the structural guard.
- **No wallet material:** no private key, wallet config, auth token, API key, or
  signing path is introduced.
- **Decimal money math:** all prices, sizes, cash, proceeds, and PnL remain
  `Decimal` strings in code and SQLite.
- **Polling is near-real-time:** v2 broker uses fresh data on each poll interval
  (`poll_interval_seconds`). It is not a WebSocket system yet. If sub-second
  updates are required later, a separate market-data adapter can be added
  without changing broker semantics.

## 3. Non-Goals

- Real Polymarket order placement.
- Maker queue priority, exchange matching latency, or cancel/replace race
  simulation.
- Full-market scanning.
- WebSocket ingestion.
- Using LLMs to infer implication relations.

## 4. Architecture

### Market Data

`PolymarketCli` remains the only live external adapter. The live loop collects
required tokens from enabled strategies and open broker orders, then calls:

```python
raw_books = cli.get_books(token_ids)
books = {tid: OrderBook.from_json(raw) for tid, raw in raw_books.items()}
snapshot = BookSnapshot(
    fetched_at=datetime.now(timezone.utc),
    source="polymarket_cli",
    books=books,
)
```

The broker consumes this `BookSnapshot`. It never calls the CLI itself, which
keeps I/O at the loop boundary and makes tests deterministic.

### Paper Broker

New module: `src/agent/paper_broker.py`

Primary interface:

```python
class PaperBroker:
    def submit_order(self, order: PaperOrder) -> BrokerOrderResult: ...
    def cancel_order(self, order_id: int, reason: str) -> BrokerOrderResult: ...
    def match_open_orders(self, snapshot: BookSnapshot) -> BrokerMatchReport: ...
    def open_orders(self) -> list[PaperOrderView]: ...
```

The broker owns order lifecycle. It validates risk through `Portfolio`, matches
orders against fresh books, records fills, and opens/closes portfolio positions.

### Fill Engine

New pure module: `src/agent/fill_engine.py`

Responsibilities:

- buy simulation: walk asks best-first;
- sell simulation: walk bids best-first;
- basket simulation: all legs use the same requested quantity;
- return exact fills plus reject/partial reason.

The existing `fills.walk_book()` and `plan_set_purchase()` remain available for
v1 compatibility, but new broker code should call the fill engine so buy and
sell paths share one vocabulary.

## 5. Order Model

### Order Types

v2 starts with basket marketable orders because complete-set and implication
strategies both buy baskets:

```python
PaperOrder(
    id: int | None,
    strategy: str,
    side: "buy" | "sell",
    kind: "basket",
    result_set: ResultSet,
    target_qty: Decimal,
    max_total_cost: Decimal | None,
    min_total_proceeds: Decimal | None,
    time_in_force: "ioc" | "gtc",
    status: "submitted" | "open" | "partially_filled" | "filled" | "canceled" | "rejected",
    created_at: datetime,
    updated_at: datetime,
)
```

Default v2a behavior is `time_in_force="ioc"` for arbitrage entries. If the
current live book cannot fill the full basket within constraints, the broker
rejects the order. v2b momentum exits may use partial fills conservatively.

### Fill Semantics

- Buy orders walk `OrderBook.asks`.
- Sell orders walk `OrderBook.bids`.
- The fill price is the depth-weighted average price.
- Basket buy for complete-set/implication must fill every leg for the same
  `target_qty`; otherwise it is rejected in v2a.
- All fills store the matching cycle's `fetched_at` timestamp and
  `source="polymarket_cli"`.

## 6. SQLite Tables

Add:

```sql
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
```

Existing `positions`, `fills`, and `exit_fills` remain the portfolio ledger.
Broker fills are the order-execution audit trail; portfolio rows are the
position/equity view.

## 7. Live Tick Flow

1. Build enabled strategies from config.
2. Collect required tokens from strategies and any open broker orders.
3. Fetch live books from `PolymarketCli.get_books(token_ids)`.
4. Create a `BookSnapshot` with `fetched_at=now`.
5. First call `broker.match_open_orders(snapshot)`.
6. Ask strategies for entry/exit proposals using the same fresh books.
7. Convert accepted proposals to `PaperOrder`s.
8. Submit orders to broker.
9. For IOC orders, match immediately against the same `BookSnapshot`.
10. Mark portfolio to market from the same books.
11. Print a report that includes data source, fetch time, order counts, fills,
    rejects, cash, equity, and PnL.

If step 3 fails, the tick does not match orders. The agent logs the failure and
tries again next tick.

## 8. Freshness Rules

- `BookSnapshot.fetched_at` is set after successful CLI response parsing.
- Matching requires `snapshot.source == "polymarket_cli"`.
- Matching requires every order leg to have a book in `snapshot.books`.
- A config field `max_book_age_seconds` defaults to
  `poll_interval_seconds * 2`. If `now - fetched_at` exceeds this, broker
  matching is skipped.
- Backtests and unit tests may use `source="fixture"` or `source="backtest"`,
  but the live agent must print and persist `source="polymarket_cli"`.

## 9. Error Handling

- Missing book for any v2a basket leg: reject IOC order with
  `missing fresh book for token <id>`.
- Insufficient depth: reject IOC order with `insufficient depth`.
- Cost above order limit: reject IOC order with `cost exceeds max_total_cost`.
- Bucket/cash/concurrency risk failure: reject before matching and record the
  portfolio reason.
- CLI failure: do not match; keep GTC orders open; no fresh-data claim is made.

## 10. Acceptance Criteria

1. Structural safety tests still prove only `cli.py` can spawn subprocesses and
   no write/trading CLI strings exist.
2. Broker unit tests show buy basket IOC orders fill from fresh live-style
   snapshots and reject when any leg book is missing.
3. Broker tests show stale snapshots cannot fill orders.
4. Portfolio tests show broker-filled orders create positions with strategy
   labels and correct cash.
5. Agent integration test shows a complete-set proposal becomes a paper order,
   then a filled portfolio position, using one fresh snapshot.
6. Live smoke command prints `source=polymarket_cli` and a current
   `fetched_at` timestamp.
7. `python -m pytest` passes.

## 11. Implementation Order

1. Add `BookSnapshot`, broker order dataclasses, and fill engine tests.
2. Implement `fill_engine.py` for buy/sell depth walking.
3. Add broker SQLite schema and order lifecycle methods.
4. Wire broker-filled entries into `Portfolio.open_position`.
5. Refactor `agent.tick()` to build one fresh snapshot per tick and route
   strategy proposals through `PaperBroker`.
6. Add live smoke reporting for source and fetch timestamp.
