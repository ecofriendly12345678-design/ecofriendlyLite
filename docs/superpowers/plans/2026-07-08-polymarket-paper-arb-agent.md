# Polymarket Real-Time Paper-Trading Arb Agent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python agent that polls a small watchlist of real Polymarket markets via the `polymarket` CLI, detects complete-set arbitrage (Σ best-asks < $1), simulates order-book-aware fills, and tracks P&L in a local SQLite virtual ledger — 100% read-only against Polymarket.

**Architecture:** Every network access goes through `cli.py` (subprocess → `polymarket -o json`). Pure-logic modules (`scanner.py`, `fills.py`) operate on parsed domain models. `portfolio.py` owns the SQLite ledger and risk limits. `agent.py` is the real-time polling loop. Spec: `docs/superpowers/specs/2026-07-08-polymarket-paper-arb-agent-design.md`.

**Tech Stack:** Python 3.13, stdlib (`subprocess`, `sqlite3`, `decimal`, `dataclasses`, `argparse`), `pyyaml`, `pytest`. The `polymarket` CLI v0.1.4 (installed at `/opt/homebrew/bin/polymarket`).

## Global Constraints

- **Read-only invariant:** the ONLY module that may import `subprocess` is `src/agent/cli.py`, and it may only invoke the allowlisted read-only subcommands: `markets`, `events`, `clob book`, `clob books`, `clob midpoints`. Guarded by `tests/test_safety.py`.
- **All money math uses `decimal.Decimal`** — never float. Parse API strings directly into `Decimal`.
- **Token ID canonical form is the decimal string.** Gamma may return hex (`0x...`); CLOB responses key by decimal. Normalize at parse time via `models.normalize_token_id`.
- **Ground truth about CLI JSON (verified live 2026-07-08, v0.1.4):**
  - `markets list/get` → Market objects where `clobTokenIds`, `outcomes`, `outcomePrices` are **JSON-encoded strings** (e.g. `"[\"Yes\",\"No\"]"`), NOT arrays. Token IDs may be hex.
  - `events list/get` → Event objects: `{id, title, slug, negRisk: bool, markets: [Market, ...], active, closed}`.
  - `clob book TOKEN` → `{market, asset_id, bids: [{price: str, size: str}], asks: [...], ...}` where **asks are sorted descending (best ask LAST) and bids ascending (best bid LAST)**; `asset_id` is decimal. Parser must sort, never trust order.
  - `clob books "T1,T2"` → JSON list of book objects.
  - `clob midpoints "T1,T2"` → dict keyed by decimal token id → price string.
  - Errors → `{"error": "..."}` on stdout, exit code 1.
- Python venv at `.venv/`; run tests with `.venv/bin/python -m pytest`; run the agent with `.venv/bin/python -m agent.agent` (pytest `pythonpath = ["src"]`, agent run uses `PYTHONPATH=src`).
- Project root: `/Users/shenyi/polymarket-agent`. Commit after every task.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`, `src/agent/__init__.py`, `tests/__init__.py`, `tests/test_scaffold.py`

**Interfaces:**
- Produces: importable package `agent`; working pytest invocation used by all later tasks.

- [ ] **Step 1: Create venv and install deps**

```bash
cd /Users/shenyi/polymarket-agent
python3 -m venv .venv
.venv/bin/pip install --quiet pytest pyyaml
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "polymarket-paper-agent"
version = "0.1.0"
description = "Real-time paper-trading arbitrage agent for Polymarket (read-only, simulated fills)"
requires-python = ">=3.11"
dependencies = ["pyyaml"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]
```

- [ ] **Step 3: Create package + failing smoke test**

`src/agent/__init__.py`:
```python
"""Polymarket paper-trading arb agent. Read-only against Polymarket; fills are simulated."""
```

`tests/__init__.py`: empty file.

`tests/test_scaffold.py`:
```python
def test_package_imports():
    import agent  # noqa: F401
```

- [ ] **Step 4: Run test**

Run: `.venv/bin/python -m pytest tests/test_scaffold.py -v`
Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ tests/
git commit -m "chore: scaffold python project with pytest"
```

---

### Task 2: Domain models (`models.py`)

**Files:**
- Create: `src/agent/models.py`
- Test: `tests/test_models.py`

**Interfaces:**
- Produces (all later tasks consume these exact names):
  - `normalize_token_id(raw: str) -> str` — hex or decimal string → canonical decimal string. Raises `ValueError` on garbage.
  - `@dataclass(frozen=True) BookLevel(price: Decimal, size: Decimal)`
  - `@dataclass OrderBook(token_id: str, bids: list[BookLevel], asks: list[BookLevel])` with `classmethod from_json(data: dict) -> OrderBook` (normalizes token id, sorts bids desc / asks asc so **index 0 is always best**), properties `best_bid`, `best_ask` (→ `BookLevel | None`), `midpoint` (→ `Decimal | None`, None when either side empty).
  - `@dataclass(frozen=True) Outcome(token_id: str, label: str)`
  - `@dataclass(frozen=True) ResultSet(set_id: str, description: str, kind: str, outcomes: tuple[Outcome, ...])` — `kind` ∈ {"binary", "neg_risk_event"}; `token_ids` property → `list[str]`.
  - `@dataclass(frozen=True) Opportunity(result_set: ResultSet, asks: dict[str, Decimal], cost: Decimal, edge: Decimal)` — `edge = 1 - cost`.
  - `@dataclass(frozen=True) Fill(token_id: str, label: str, qty: Decimal, avg_price: Decimal, cost: Decimal)`
  - `@dataclass(frozen=True) SetPurchase(result_set: ResultSet, n_sets: Decimal, fills: tuple[Fill, ...], total_cost: Decimal)` with properties `cost_per_set` (= total_cost / n_sets), `guaranteed_payout` (= n_sets × 1), `locked_profit` (= n_sets − total_cost).

- [ ] **Step 1: Write failing tests**

`tests/test_models.py`:
```python
from decimal import Decimal

from agent.models import (
    BookLevel,
    Fill,
    Opportunity,
    OrderBook,
    Outcome,
    ResultSet,
    SetPurchase,
    normalize_token_id,
)


def test_normalize_token_id_decimal_passthrough():
    assert normalize_token_id("12345") == "12345"


def test_normalize_token_id_hex_to_decimal():
    assert normalize_token_id("0xff") == "255"
    assert normalize_token_id("0xFF") == "255"


def test_normalize_token_id_real_hex():
    raw = "0xd8b6c36e23f1e9363cbee5692794deb1faa3a8e95fa3255f01d53fbb68c68b43"
    out = normalize_token_id(raw)
    assert out == str(int(raw, 16))


def test_normalize_token_id_garbage_raises():
    import pytest
    with pytest.raises(ValueError):
        normalize_token_id("not-a-token")


def _sample_book_json():
    # Mirrors live CLI output: asks DESCENDING (best last), bids ASCENDING (best last)
    return {
        "market": "0xabc",
        "asset_id": "255",
        "asks": [
            {"price": "0.99", "size": "100"},
            {"price": "0.60", "size": "50"},
            {"price": "0.55", "size": "10"},
        ],
        "bids": [
            {"price": "0.01", "size": "200"},
            {"price": "0.50", "size": "20"},
        ],
    }


def test_orderbook_from_json_sorts_best_first():
    book = OrderBook.from_json(_sample_book_json())
    assert book.token_id == "255"
    assert book.asks[0] == BookLevel(Decimal("0.55"), Decimal("10"))
    assert book.bids[0] == BookLevel(Decimal("0.50"), Decimal("20"))


def test_orderbook_best_and_midpoint():
    book = OrderBook.from_json(_sample_book_json())
    assert book.best_ask.price == Decimal("0.55")
    assert book.best_bid.price == Decimal("0.50")
    assert book.midpoint == Decimal("0.525")


def test_orderbook_empty_side_midpoint_none():
    data = _sample_book_json()
    data["bids"] = []
    book = OrderBook.from_json(data)
    assert book.best_bid is None
    assert book.midpoint is None


def test_orderbook_from_json_hex_asset_id():
    data = _sample_book_json()
    data["asset_id"] = "0xff"
    assert OrderBook.from_json(data).token_id == "255"


def test_result_set_token_ids():
    rs = ResultSet(
        set_id="0xcond",
        description="Test?",
        kind="binary",
        outcomes=(Outcome("1", "Yes"), Outcome("2", "No")),
    )
    assert rs.token_ids == ["1", "2"]


def test_set_purchase_derived_values():
    rs = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    fills = (
        Fill("1", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),
        Fill("2", "No", Decimal("10"), Decimal("0.42"), Decimal("4.2")),
    )
    sp = SetPurchase(rs, Decimal("10"), fills, Decimal("9.7"))
    assert sp.cost_per_set == Decimal("0.97")
    assert sp.guaranteed_payout == Decimal("10")
    assert sp.locked_profit == Decimal("0.3")


def test_opportunity_fields():
    rs = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    opp = Opportunity(rs, {"1": Decimal("0.55"), "2": Decimal("0.42")},
                      Decimal("0.97"), Decimal("0.03"))
    assert opp.edge == Decimal("0.03")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: FAIL (ModuleNotFoundError / ImportError)

- [ ] **Step 3: Implement `src/agent/models.py`**

```python
"""Domain models. All prices/sizes are Decimal; token ids are canonical decimal strings."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


def normalize_token_id(raw: str) -> str:
    """Convert a hex (0x...) or decimal token id string to a canonical decimal string."""
    s = raw.strip()
    if s.lower().startswith("0x"):
        return str(int(s, 16))
    return str(int(s))  # raises ValueError on garbage


@dataclass(frozen=True)
class BookLevel:
    price: Decimal
    size: Decimal


@dataclass
class OrderBook:
    token_id: str
    bids: list[BookLevel]  # sorted best-first: descending price
    asks: list[BookLevel]  # sorted best-first: ascending price

    @classmethod
    def from_json(cls, data: dict) -> OrderBook:
        """Parse CLI `clob book` JSON. The API sorts asks descending and bids
        ascending (best at the END); we normalize to best-first and never
        trust incoming order."""
        def levels(raw: list[dict]) -> list[BookLevel]:
            return [BookLevel(Decimal(l["price"]), Decimal(l["size"])) for l in raw]

        bids = sorted(levels(data.get("bids") or []), key=lambda l: l.price, reverse=True)
        asks = sorted(levels(data.get("asks") or []), key=lambda l: l.price)
        return cls(token_id=normalize_token_id(data["asset_id"]), bids=bids, asks=asks)

    @property
    def best_bid(self) -> BookLevel | None:
        return self.bids[0] if self.bids else None

    @property
    def best_ask(self) -> BookLevel | None:
        return self.asks[0] if self.asks else None

    @property
    def midpoint(self) -> Decimal | None:
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2


@dataclass(frozen=True)
class Outcome:
    token_id: str
    label: str


@dataclass(frozen=True)
class ResultSet:
    """A complete set of mutually exclusive outcomes that pays exactly $1 at resolution."""
    set_id: str        # market conditionId, or "event:<id>" for neg-risk events
    description: str
    kind: str          # "binary" | "neg_risk_event"
    outcomes: tuple[Outcome, ...]

    @property
    def token_ids(self) -> list[str]:
        return [o.token_id for o in self.outcomes]


@dataclass(frozen=True)
class Opportunity:
    result_set: ResultSet
    asks: dict[str, Decimal]  # token_id -> best ask used in the signal
    cost: Decimal             # sum of best asks for one full set
    edge: Decimal             # 1 - cost


@dataclass(frozen=True)
class Fill:
    token_id: str
    label: str
    qty: Decimal
    avg_price: Decimal
    cost: Decimal


@dataclass(frozen=True)
class SetPurchase:
    result_set: ResultSet
    n_sets: Decimal
    fills: tuple[Fill, ...]
    total_cost: Decimal

    @property
    def cost_per_set(self) -> Decimal:
        return self.total_cost / self.n_sets

    @property
    def guaranteed_payout(self) -> Decimal:
        return self.n_sets

    @property
    def locked_profit(self) -> Decimal:
        return self.n_sets - self.total_cost
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_models.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/models.py tests/test_models.py
git commit -m "feat: domain models with token-id normalization and book-order fix"
```

---

### Task 3: Config (`config.py` + `config.yaml`)

**Files:**
- Create: `src/agent/config.py`, `config.yaml`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) WatchlistEntry(type: str, ref: str)` — `type` ∈ {"binary", "event"}.
  - `@dataclass(frozen=True) Config(virtual_capital_usd: Decimal, poll_interval_seconds: float, min_edge: Decimal, est_fee: Decimal, max_notional_per_trade_usd: Decimal, max_concurrent_positions: int, sanity_min_mid_sum: Decimal, db_path: str, watchlist: tuple[WatchlistEntry, ...])`
  - `load_config(path: str) -> Config` — raises `ValueError` on missing/invalid fields.

- [ ] **Step 1: Write failing tests**

`tests/test_config.py`:
```python
from decimal import Decimal

import pytest

from agent.config import Config, WatchlistEntry, load_config

VALID = """\
virtual_capital_usd: 1000
poll_interval_seconds: 5
min_edge: 0.01
est_fee: 0.00
max_notional_per_trade_usd: 50
max_concurrent_positions: 10
sanity_min_mid_sum: 0.95
db_path: virtual_ledger.db
watchlist:
  - type: binary
    ref: some-market-slug
  - type: event
    ref: "12345"
"""


def test_load_valid_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(VALID)
    cfg = load_config(str(p))
    assert cfg.virtual_capital_usd == Decimal("1000")
    assert cfg.min_edge == Decimal("0.01")
    assert cfg.poll_interval_seconds == 5.0
    assert cfg.watchlist == (
        WatchlistEntry("binary", "some-market-slug"),
        WatchlistEntry("event", "12345"),
    )


def test_money_fields_are_decimal(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(VALID)
    cfg = load_config(str(p))
    assert isinstance(cfg.min_edge, Decimal)
    assert isinstance(cfg.est_fee, Decimal)
    assert isinstance(cfg.max_notional_per_trade_usd, Decimal)


def test_missing_field_raises(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("min_edge: 0.01\n")
    with pytest.raises(ValueError):
        load_config(str(p))


def test_bad_watchlist_type_raises(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(VALID.replace("type: binary", "type: bogus"))
    with pytest.raises(ValueError):
        load_config(str(p))
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `src/agent/config.py`**

```python
"""Load and validate config.yaml. Money fields become Decimal (parsed from str)."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

import yaml

_REQUIRED = [
    "virtual_capital_usd", "poll_interval_seconds", "min_edge", "est_fee",
    "max_notional_per_trade_usd", "max_concurrent_positions",
    "sanity_min_mid_sum", "db_path", "watchlist",
]
_WATCHLIST_TYPES = {"binary", "event"}


@dataclass(frozen=True)
class WatchlistEntry:
    type: str
    ref: str


@dataclass(frozen=True)
class Config:
    virtual_capital_usd: Decimal
    poll_interval_seconds: float
    min_edge: Decimal
    est_fee: Decimal
    max_notional_per_trade_usd: Decimal
    max_concurrent_positions: int
    sanity_min_mid_sum: Decimal
    db_path: str
    watchlist: tuple[WatchlistEntry, ...]


def _dec(raw: object, field: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except InvalidOperation as e:
        raise ValueError(f"config field {field!r} is not a valid number: {raw!r}") from e


def load_config(path: str) -> Config:
    with open(path) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config file {path} is not a YAML mapping")
    missing = [k for k in _REQUIRED if k not in data]
    if missing:
        raise ValueError(f"config missing required fields: {missing}")

    entries = []
    for i, item in enumerate(data["watchlist"]):
        wtype = str(item.get("type", ""))
        ref = str(item.get("ref", ""))
        if wtype not in _WATCHLIST_TYPES:
            raise ValueError(f"watchlist[{i}].type must be one of {_WATCHLIST_TYPES}, got {wtype!r}")
        if not ref:
            raise ValueError(f"watchlist[{i}].ref is required")
        entries.append(WatchlistEntry(wtype, ref))

    return Config(
        virtual_capital_usd=_dec(data["virtual_capital_usd"], "virtual_capital_usd"),
        poll_interval_seconds=float(data["poll_interval_seconds"]),
        min_edge=_dec(data["min_edge"], "min_edge"),
        est_fee=_dec(data["est_fee"], "est_fee"),
        max_notional_per_trade_usd=_dec(data["max_notional_per_trade_usd"], "max_notional_per_trade_usd"),
        max_concurrent_positions=int(data["max_concurrent_positions"]),
        sanity_min_mid_sum=_dec(data["sanity_min_mid_sum"], "sanity_min_mid_sum"),
        db_path=str(data["db_path"]),
        watchlist=tuple(entries),
    )
```

- [ ] **Step 4: Write `config.yaml` (project root)**

```yaml
# Polymarket paper-trading arb agent — user config
virtual_capital_usd: 1000        # starting virtual cash
poll_interval_seconds: 5
min_edge: 0.01                   # act only if a full set is ≥1¢ under $1
est_fee: 0.00                    # fee/slippage buffer subtracted from edge
max_notional_per_trade_usd: 50
max_concurrent_positions: 10
sanity_min_mid_sum: 0.95         # skip sets whose midpoints sum below this (likely non-exhaustive)
db_path: virtual_ledger.db
watchlist:
  # Filled with live markets during the smoke-test task (Task 10).
  - type: binary
    ref: new-rhianna-album-before-gta-vi-926
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_config.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/config.py config.yaml tests/test_config.py
git commit -m "feat: config loading with Decimal money fields and watchlist validation"
```

---

### Task 4: CLI wrapper (`cli.py`)

**Files:**
- Create: `src/agent/cli.py`, `tests/fake_polymarket.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `models.normalize_token_id`.
- Produces:
  - `class CliError(Exception)` with attributes `message: str`, `argv: list[str]`.
  - `class PolymarketCli:`
    - `__init__(self, binary: str | list[str] = "polymarket", timeout: float = 30.0)` — `binary` may be a list (used by tests to substitute a fake).
    - `get_market(self, ref: str) -> dict` — `markets get <ref>`.
    - `get_event(self, ref: str) -> dict` — `events get <ref>`.
    - `get_books(self, token_ids: list[str]) -> dict[str, dict]` — `clob books`, chunked ≤ 20 ids per call; returns map canonical-decimal-token-id → raw book dict. Tokens missing from the response are absent from the map.
    - `get_midpoints(self, token_ids: list[str]) -> dict[str, str]` — chunked; canonical ids.
  - Behavior: appends `-o json`; nonzero exit OR `{"error": ...}` payload OR bad JSON OR timeout → raises `CliError`.

- [ ] **Step 1: Write the fake binary for tests**

`tests/fake_polymarket.py` (a stand-in executed as `python tests/fake_polymarket.py <args>`; behavior driven by env var `FAKE_MODE`):
```python
"""Fake `polymarket` binary for tests. FAKE_MODE selects canned behavior."""
import json
import os
import sys

MODE = os.environ.get("FAKE_MODE", "ok")

BOOK_255 = {
    "market": "0xabc", "asset_id": "255",
    "asks": [{"price": "0.99", "size": "100"}, {"price": "0.55", "size": "10"}],
    "bids": [{"price": "0.50", "size": "20"}],
}
BOOK_256 = {
    "market": "0xabc", "asset_id": "256",
    "asks": [{"price": "0.42", "size": "30"}],
    "bids": [{"price": "0.40", "size": "15"}],
}


def main() -> int:
    args = sys.argv[1:]
    if MODE == "error_json":
        print(json.dumps({"error": "Status: error(404 Not Found)"}))
        return 1
    if MODE == "error_exit_only":
        print(json.dumps({"anything": True}))
        return 1
    if MODE == "bad_json":
        print("this is not json")
        return 0
    if MODE == "hang":
        import time
        time.sleep(60)
        return 0

    # MODE == "ok": route by subcommand
    if args[:2] == ["markets", "get"]:
        print(json.dumps({"id": "540817", "question": "Q?", "slug": args[2]}))
    elif args[:2] == ["events", "get"]:
        print(json.dumps({"id": args[2], "title": "E", "negRisk": True, "markets": []}))
    elif args[:2] == ["clob", "books"]:
        ids = [t.strip() for t in args[2].split(",")]
        out = []
        if "255" in ids or "0xff" in ids:
            out.append(BOOK_255)
        if "256" in ids:
            out.append(BOOK_256)
        print(json.dumps(out))
    elif args[:2] == ["clob", "midpoints"]:
        print(json.dumps({"255": "0.525", "256": "0.41"}))
    else:
        print(json.dumps({"error": f"unknown args {args}"}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Write failing tests**

`tests/test_cli.py`:
```python
import os
import sys

import pytest

from agent.cli import CliError, PolymarketCli

FAKE = [sys.executable, os.path.join(os.path.dirname(__file__), "fake_polymarket.py")]


def make(mode: str = "ok", timeout: float = 30.0) -> PolymarketCli:
    os.environ["FAKE_MODE"] = mode
    return PolymarketCli(binary=FAKE, timeout=timeout)


def teardown_function():
    os.environ.pop("FAKE_MODE", None)


def test_get_market():
    assert make().get_market("some-slug")["slug"] == "some-slug"


def test_get_event():
    assert make().get_event("123")["negRisk"] is True


def test_get_books_keyed_by_canonical_id():
    books = make().get_books(["255", "256"])
    assert set(books) == {"255", "256"}
    assert books["255"]["asset_id"] == "255"


def test_get_books_normalizes_hex_input():
    books = make().get_books(["0xff"])
    assert "255" in books


def test_get_books_chunks_large_requests():
    # 45 ids -> 3 subprocess calls (chunk size 20). The fake returns only
    # books it knows; the point is that no call gets >20 ids (fake would
    # blow up on absurd argv? -> assert via returned data still correct).
    ids = ["255", "256"] + [str(1000 + i) for i in range(43)]
    books = make().get_books(ids)
    assert set(books) == {"255", "256"}


def test_get_midpoints():
    mids = make().get_midpoints(["255", "256"])
    assert mids["255"] == "0.525"


def test_error_json_raises():
    with pytest.raises(CliError, match="404"):
        make("error_json").get_market("x")


def test_nonzero_exit_raises():
    with pytest.raises(CliError):
        make("error_exit_only").get_market("x")


def test_bad_json_raises():
    with pytest.raises(CliError, match="JSON"):
        make("bad_json").get_market("x")


def test_timeout_raises():
    with pytest.raises(CliError, match="[Tt]ime"):
        make("hang", timeout=1.0).get_market("x")
```

- [ ] **Step 3: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 4: Implement `src/agent/cli.py`**

```python
"""The ONLY module allowed to talk to the `polymarket` binary (read-only subcommands).

Read-only invariant: this wrapper exposes exactly: markets get, events get,
clob books, clob midpoints — nothing that signs, spends, or transacts.
(Word choice in this file is constrained by tests/test_safety.py.)
"""
from __future__ import annotations

import json
import subprocess
from typing import Any

from agent.models import normalize_token_id

_CHUNK = 20  # max token ids per batch call


class CliError(Exception):
    def __init__(self, message: str, argv: list[str]):
        super().__init__(f"{message} (argv: {' '.join(argv)})")
        self.message = message
        self.argv = argv


class PolymarketCli:
    def __init__(self, binary: str | list[str] = "polymarket", timeout: float = 30.0):
        self._binary = [binary] if isinstance(binary, str) else list(binary)
        self._timeout = timeout

    def _run(self, *args: str) -> Any:
        argv = [*self._binary, "-o", "json", *args]
        try:
            proc = subprocess.run(
                argv, capture_output=True, text=True, timeout=self._timeout
            )
        except subprocess.TimeoutExpired:
            raise CliError(f"Timed out after {self._timeout}s", argv) from None
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError:
            raise CliError(
                f"Invalid JSON from CLI (exit={proc.returncode}): "
                f"{proc.stdout[:200]!r} stderr={proc.stderr[:200]!r}", argv
            ) from None
        if isinstance(data, dict) and "error" in data:
            raise CliError(str(data["error"]), argv)
        if proc.returncode != 0:
            raise CliError(f"CLI exited {proc.returncode}", argv)
        return data

    def get_market(self, ref: str) -> dict:
        return self._run("markets", "get", ref)

    def get_event(self, ref: str) -> dict:
        return self._run("events", "get", ref)

    def get_books(self, token_ids: list[str]) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for i in range(0, len(token_ids), _CHUNK):
            chunk = token_ids[i : i + _CHUNK]
            result = self._run("clob", "books", ",".join(chunk))
            for book in result:
                out[normalize_token_id(book["asset_id"])] = book
        return out

    def get_midpoints(self, token_ids: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for i in range(0, len(token_ids), _CHUNK):
            chunk = token_ids[i : i + _CHUNK]
            result = self._run("clob", "midpoints", ",".join(chunk))
            for tid, mid in result.items():
                out[normalize_token_id(tid)] = mid
        return out
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_cli.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/cli.py tests/test_cli.py tests/fake_polymarket.py
git commit -m "feat: read-only polymarket CLI wrapper with chunked batches and error handling"
```

---

### Task 5: Scanner (`scanner.py`)

**Files:**
- Create: `src/agent/scanner.py`
- Test: `tests/test_scanner.py`

**Interfaces:**
- Consumes: `models.{ResultSet, Outcome, Opportunity, OrderBook, normalize_token_id}`.
- Produces:
  - `result_set_from_market(market: dict) -> ResultSet | None` — parse a gamma Market dict (binary). Returns None if not tradeable: `active` is not True, `closed` is True, `enableOrderBook` is False, or outcomes/token counts ≠ 2. **Handles JSON-encoded-string `clobTokenIds`/`outcomes`.** `set_id` = `conditionId`, kind="binary".
  - `result_set_from_event(event: dict) -> ResultSet | None` — parse a gamma Event dict. Returns None unless `negRisk` is True and ≥ 2 tradeable member markets. One Outcome per member market: token = **first** entry of that market's `clobTokenIds` (the YES token), label = `groupItemTitle` or `question`. `set_id` = `f"event:{id}"`, kind="neg_risk_event".
  - `find_opportunities(sets: list[ResultSet], books: dict[str, OrderBook], min_edge: Decimal, est_fee: Decimal, sanity_min_mid_sum: Decimal) -> list[Opportunity]` — for each set: skip if any outcome's book missing or has no ask; skip if Σ midpoints < sanity_min_mid_sum (likely non-exhaustive set — midpoint missing on any leg also skips); emit Opportunity when `1 - Σ best_asks > min_edge + est_fee`.

- [ ] **Step 1: Write failing tests**

`tests/test_scanner.py`:
```python
import json
from decimal import Decimal

from agent.models import OrderBook
from agent.scanner import (
    find_opportunities,
    result_set_from_event,
    result_set_from_market,
)


def market_json(cond="0xcond1", yes="101", no="102", active=True, closed=False):
    return {
        "conditionId": cond,
        "question": "Will it happen?",
        "slug": "will-it-happen",
        "active": active,
        "closed": closed,
        "enableOrderBook": True,
        "clobTokenIds": json.dumps([yes, no]),
        "outcomes": json.dumps(["Yes", "No"]),
    }


def book(token, best_ask, best_bid, depth="1000"):
    return OrderBook.from_json({
        "asset_id": token,
        "asks": [{"price": best_ask, "size": depth}],
        "bids": [{"price": best_bid, "size": depth}],
    })


def test_result_set_from_market_binary():
    rs = result_set_from_market(market_json())
    assert rs is not None
    assert rs.kind == "binary"
    assert rs.set_id == "0xcond1"
    assert [o.label for o in rs.outcomes] == ["Yes", "No"]
    assert rs.token_ids == ["101", "102"]


def test_result_set_from_market_hex_tokens_normalized():
    rs = result_set_from_market(market_json(yes="0xff", no="0x100"))
    assert rs.token_ids == ["255", "256"]


def test_result_set_from_market_rejects_closed():
    assert result_set_from_market(market_json(closed=True)) is None
    assert result_set_from_market(market_json(active=False)) is None


def test_result_set_from_event_neg_risk():
    ev = {
        "id": "500", "title": "Who wins?", "negRisk": True,
        "markets": [
            {**market_json(cond="0xc1", yes="201", no="202"), "groupItemTitle": "Alice"},
            {**market_json(cond="0xc2", yes="203", no="204"), "groupItemTitle": "Bob"},
            {**market_json(cond="0xc3", yes="205", no="206"), "groupItemTitle": "Carol"},
        ],
    }
    rs = result_set_from_event(ev)
    assert rs is not None
    assert rs.kind == "neg_risk_event"
    assert rs.set_id == "event:500"
    # one outcome per market, YES token only
    assert rs.token_ids == ["201", "203", "205"]
    assert [o.label for o in rs.outcomes] == ["Alice", "Bob", "Carol"]


def test_result_set_from_event_rejects_non_negrisk():
    assert result_set_from_event({"id": "1", "negRisk": False, "markets": []}) is None


def test_find_opportunity_cheap_set_flagged():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.42", "0.40")}
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95"))
    assert len(opps) == 1
    assert opps[0].cost == Decimal("0.97")
    assert opps[0].edge == Decimal("0.03")


def test_find_opportunity_fair_set_ignored():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.45", "0.44")}
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95"))
    assert opps == []


def test_find_opportunity_three_outcome_event():
    ev = {
        "id": "500", "title": "Who wins?", "negRisk": True,
        "markets": [
            {**market_json(cond="0xc1", yes="201", no="202"), "groupItemTitle": "A"},
            {**market_json(cond="0xc2", yes="203", no="204"), "groupItemTitle": "B"},
            {**market_json(cond="0xc3", yes="205", no="206"), "groupItemTitle": "C"},
        ],
    }
    rs = result_set_from_event(ev)
    books = {
        "201": book("201", "0.30", "0.29"),
        "203": book("203", "0.30", "0.29"),
        "205": book("205", "0.35", "0.34"),
    }
    opps = find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.90"))
    assert len(opps) == 1
    assert opps[0].cost == Decimal("0.95")


def test_find_opportunity_fee_eats_edge():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53"), "102": book("102", "0.42", "0.40")}
    # edge 0.03 but min_edge 0.02 + fee 0.02 = 0.04 threshold -> no opp
    opps = find_opportunities([rs], books, Decimal("0.02"), Decimal("0.02"), Decimal("0.95"))
    assert opps == []


def test_find_opportunity_missing_book_skipped():
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.55", "0.53")}  # 102 missing
    assert find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95")) == []


def test_sanity_guard_rejects_low_mid_sum():
    # mids sum to 0.55+0.10=0.65 < 0.95 -> likely non-exhaustive, skip even though asks sum < 1
    rs = result_set_from_market(market_json())
    books = {"101": book("101", "0.56", "0.54"), "102": book("102", "0.11", "0.09")}
    assert find_opportunities([rs], books, Decimal("0.01"), Decimal("0"), Decimal("0.95")) == []
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_scanner.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `src/agent/scanner.py`**

```python
"""Arb signal: a complete set of mutually exclusive outcomes pays exactly $1.
If the sum of best asks for the full set is < $1 - threshold - fee, buying
the set locks a profit. Pure logic over parsed data; no I/O here."""
from __future__ import annotations

import json
from decimal import Decimal

from agent.models import Opportunity, OrderBook, Outcome, ResultSet, normalize_token_id

ONE = Decimal("1")


def _json_list(raw: object) -> list:
    """Gamma encodes list fields as JSON strings, e.g. '["Yes","No"]'."""
    if isinstance(raw, str):
        return json.loads(raw)
    if isinstance(raw, list):
        return raw
    return []


def _tradeable(market: dict) -> bool:
    return (
        market.get("active") is True
        and market.get("closed") is not True
        and market.get("enableOrderBook") is not False
    )


def result_set_from_market(market: dict) -> ResultSet | None:
    if not _tradeable(market):
        return None
    try:
        tokens = [normalize_token_id(t) for t in _json_list(market.get("clobTokenIds"))]
    except (ValueError, json.JSONDecodeError):
        return None
    labels = _json_list(market.get("outcomes"))
    if len(tokens) != 2 or len(labels) != 2:
        return None
    cond = market.get("conditionId")
    if not cond:
        return None
    return ResultSet(
        set_id=str(cond),
        description=str(market.get("question") or market.get("slug") or cond),
        kind="binary",
        outcomes=tuple(Outcome(t, str(l)) for t, l in zip(tokens, labels)),
    )


def result_set_from_event(event: dict) -> ResultSet | None:
    """Neg-risk event -> one set of every member market's YES token.

    Caveat (why the sanity guard exists): buying every listed outcome pays $1
    only if the listed outcomes are exhaustive. Mutual exclusivity is
    guaranteed by neg-risk mechanics; exhaustiveness is not (candidates can
    be added). find_opportunities() therefore also requires Σ midpoints to be
    close to $1 before trusting a cheap-set signal."""
    if event.get("negRisk") is not True:
        return None
    outcomes: list[Outcome] = []
    for market in event.get("markets") or []:
        if not _tradeable(market):
            continue
        try:
            tokens = [normalize_token_id(t) for t in _json_list(market.get("clobTokenIds"))]
        except (ValueError, json.JSONDecodeError):
            continue
        if not tokens:
            continue
        label = str(market.get("groupItemTitle") or market.get("question") or tokens[0])
        outcomes.append(Outcome(tokens[0], label))  # first token = YES
    if len(outcomes) < 2:
        return None
    return ResultSet(
        set_id=f"event:{event.get('id')}",
        description=str(event.get("title") or event.get("slug") or event.get("id")),
        kind="neg_risk_event",
        outcomes=tuple(outcomes),
    )


def find_opportunities(
    sets: list[ResultSet],
    books: dict[str, OrderBook],
    min_edge: Decimal,
    est_fee: Decimal,
    sanity_min_mid_sum: Decimal,
) -> list[Opportunity]:
    opps: list[Opportunity] = []
    for rs in sets:
        asks: dict[str, Decimal] = {}
        mid_sum = Decimal("0")
        complete = True
        for tid in rs.token_ids:
            book = books.get(tid)
            if book is None or book.best_ask is None or book.midpoint is None:
                complete = False
                break
            asks[tid] = book.best_ask.price
            mid_sum += book.midpoint
        if not complete:
            continue
        if mid_sum < sanity_min_mid_sum:
            continue  # set priced far below $1 -> likely non-exhaustive, not an arb
        cost = sum(asks.values(), Decimal("0"))
        edge = ONE - cost
        if edge > min_edge + est_fee:
            opps.append(Opportunity(result_set=rs, asks=asks, cost=cost, edge=edge))
    return opps
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_scanner.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/scanner.py tests/test_scanner.py
git commit -m "feat: arb scanner for binary markets and neg-risk events with exhaustiveness guard"
```

---

### Task 6: Fill simulator (`fills.py`)

**Files:**
- Create: `src/agent/fills.py`
- Test: `tests/test_fills.py`

**Interfaces:**
- Consumes: `models.{OrderBook, BookLevel, ResultSet, Fill, SetPurchase}`.
- Produces:
  - `walk_book(asks: list[BookLevel], qty: Decimal) -> Decimal | None` — total cost to buy `qty` walking best-first ask levels; `None` if cumulative depth < qty. `qty <= 0` → `None`.
  - `plan_set_purchase(result_set: ResultSet, books: dict[str, OrderBook], max_cost_per_set: Decimal, max_notional: Decimal) -> SetPurchase | None` — find the LARGEST n_sets such that (a) every leg has depth, (b) total cost ≤ max_notional, (c) cost_per_set ≤ max_cost_per_set. Candidate quantities = cumulative-depth breakpoints of every leg's ask book, plus the notional cap; evaluated descending; first feasible wins. Missing book/leg → None.

- [ ] **Step 1: Write failing tests**

`tests/test_fills.py`:
```python
from decimal import Decimal

from agent.fills import plan_set_purchase, walk_book
from agent.models import BookLevel, OrderBook, Outcome, ResultSet


def levels(*pairs):
    return [BookLevel(Decimal(p), Decimal(s)) for p, s in pairs]


def book(token, ask_pairs, bid_pairs=(("0.01", "1"),)):
    return OrderBook(
        token_id=token,
        asks=levels(*ask_pairs),
        bids=levels(*bid_pairs),
    )


RS = ResultSet("s", "d", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))


def test_walk_book_single_level():
    cost = walk_book(levels(("0.55", "100")), Decimal("10"))
    assert cost == Decimal("5.5")


def test_walk_book_multiple_levels():
    # 10 @ 0.50 + 5 @ 0.60 = 5.00 + 3.00 = 8.00
    cost = walk_book(levels(("0.50", "10"), ("0.60", "20")), Decimal("15"))
    assert cost == Decimal("8.00")


def test_walk_book_insufficient_depth():
    assert walk_book(levels(("0.50", "10")), Decimal("11")) is None


def test_walk_book_zero_qty():
    assert walk_book(levels(("0.50", "10")), Decimal("0")) is None


def test_plan_set_purchase_happy_path():
    books = {
        "1": book("1", (("0.55", "100"),)),
        "2": book("2", (("0.42", "100"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    assert sp is not None
    # Depth allows 100 sets (cost 97 > notional 50), so sizing falls to the
    # notional-capped candidate: floor(50 / 0.97, 0.01) = 51.54 sets.
    assert sp.n_sets == Decimal("51.54")
    assert sp.total_cost <= Decimal("50")
    assert sp.cost_per_set == Decimal("0.97")
    assert sp.locked_profit > 0


def test_plan_set_purchase_walks_depth_until_edge_gone():
    # Leg1: 10 @ 0.55 then 0.70; leg2: plentiful @ 0.42.
    # 10 sets: per-set 0.97 <= 0.99 OK. 20 sets: leg1 = 10*0.55+10*0.70=12.5,
    # leg2 = 20*0.42=8.4 -> per-set (12.5+8.4)/20 = 1.045 > 0.99 -> only 10 sets.
    books = {
        "1": book("1", (("0.55", "10"), ("0.70", "1000"))),
        "2": book("2", (("0.42", "1000"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("10000"))
    assert sp is not None
    assert sp.n_sets == Decimal("10")
    assert sp.cost_per_set == Decimal("0.97")


def test_plan_set_purchase_thin_book_sizes_down():
    books = {
        "1": book("1", (("0.55", "0.5"),)),   # half a share available
        "2": book("2", (("0.42", "0.5"),)),
    }
    # only 0.5 sets fillable; cost 0.485 -> feasible mini-purchase is allowed
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    assert sp is not None
    assert sp.n_sets == Decimal("0.5")


def test_plan_set_purchase_no_feasible_size():
    # Best asks already sum above cap -> None
    books = {
        "1": book("1", (("0.60", "100"),)),
        "2": book("2", (("0.45", "100"),)),
    }
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_plan_set_purchase_missing_leg():
    books = {"1": book("1", (("0.55", "100"),))}
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_plan_set_purchase_empty_asks():
    books = {
        "1": book("1", ()),
        "2": book("2", (("0.42", "100"),)),
    }
    assert plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50")) is None


def test_fills_metadata():
    books = {
        "1": book("1", (("0.55", "100"),)),
        "2": book("2", (("0.42", "100"),)),
    }
    sp = plan_set_purchase(RS, books, Decimal("0.99"), Decimal("50"))
    by_token = {f.token_id: f for f in sp.fills}
    assert by_token["1"].label == "Yes"
    assert by_token["1"].qty == sp.n_sets
    assert by_token["1"].avg_price == Decimal("0.55")
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_fills.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `src/agent/fills.py`**

```python
"""Order-book-aware fill simulation. Walk real ask depth level by level so the
paper P&L reflects what a real taker order would actually pay."""
from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from agent.models import BookLevel, Fill, OrderBook, ResultSet, SetPurchase


def walk_book(asks: list[BookLevel], qty: Decimal) -> Decimal | None:
    """Total cost to buy `qty` shares walking best-first asks. None if depth < qty."""
    if qty <= 0:
        return None
    remaining = qty
    cost = Decimal("0")
    for level in asks:
        take = min(remaining, level.size)
        cost += take * level.price
        remaining -= take
        if remaining == 0:
            return cost
    return None  # insufficient depth


def _breakpoints(asks: list[BookLevel]) -> list[Decimal]:
    """Cumulative-depth breakpoints of one ask book."""
    out, cum = [], Decimal("0")
    for level in asks:
        cum += level.size
        out.append(cum)
    return out


def plan_set_purchase(
    result_set: ResultSet,
    books: dict[str, OrderBook],
    max_cost_per_set: Decimal,
    max_notional: Decimal,
) -> SetPurchase | None:
    """Largest feasible n_sets with total cost <= max_notional and
    cost per set <= max_cost_per_set. Candidates are every leg's depth
    breakpoints plus the notional-capped quantity; first feasible
    (descending) wins. Deterministic and O(levels^2), fine for CLOB books."""
    legs: list[tuple[str, str, list[BookLevel]]] = []
    for outcome in result_set.outcomes:
        book = books.get(outcome.token_id)
        if book is None or not book.asks:
            return None
        legs.append((outcome.token_id, outcome.label, book.asks))

    candidates: set[Decimal] = set()
    for _, _, asks in legs:
        candidates.update(_breakpoints(asks))
    best_ask_sum = sum(asks[0].price for _, _, asks in legs)
    if best_ask_sum > 0:
        # Notional-capped qty at best prices. Floor to 0.01 shares so the
        # inexact division can never round up past the notional cap.
        capped = (max_notional / best_ask_sum).quantize(
            Decimal("0.01"), rounding=ROUND_DOWN
        )
        candidates.add(capped)

    for qty in sorted(candidates, reverse=True):
        if qty <= 0:
            continue
        leg_costs: list[tuple[str, str, Decimal]] = []
        feasible = True
        for tid, label, asks in legs:
            cost = walk_book(asks, qty)
            if cost is None:
                feasible = False
                break
            leg_costs.append((tid, label, cost))
        if not feasible:
            continue
        total = sum(c for _, _, c in leg_costs)
        if total > max_notional:
            continue
        if total / qty > max_cost_per_set:
            continue
        fills = tuple(
            Fill(token_id=tid, label=label, qty=qty, avg_price=cost / qty, cost=cost)
            for tid, label, cost in leg_costs
        )
        return SetPurchase(
            result_set=result_set, n_sets=qty, fills=fills, total_cost=total
        )
    return None
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_fills.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/fills.py tests/test_fills.py
git commit -m "feat: depth-walking fill simulator with breakpoint-based set sizing"
```

---

### Task 7: Virtual ledger (`portfolio.py`)

**Files:**
- Create: `src/agent/portfolio.py`
- Test: `tests/test_portfolio.py`

**Interfaces:**
- Consumes: `models.{SetPurchase, Opportunity}`, `config.Config`.
- Produces:
  - `@dataclass(frozen=True) Summary(cash: Decimal, positions_value: Decimal, total_equity: Decimal, unrealized_pnl: Decimal, guaranteed_pnl: Decimal, open_positions: int)`
  - `class Portfolio:`
    - `__init__(self, db_path: str, starting_capital: Decimal)` — creates tables if absent; persists starting capital in a `meta` table on first run and **reuses the stored value on reopen** (restart-safe).
    - `cash(self) -> Decimal` — starting capital − Σ open position costs.
    - `has_open_position(self, set_id: str) -> bool`
    - `can_open(self, total_cost: Decimal, set_id: str, max_concurrent: int) -> tuple[bool, str]` — False with reason when: duplicate set_id, insufficient cash, or open-position count ≥ max_concurrent.
    - `open_position(self, purchase: SetPurchase) -> int` — inserts position + per-leg fills atomically, returns position id.
    - `record_opportunity(self, opp: Opportunity, acted: bool, reason: str) -> None`
    - `mark_to_market(self, mids: dict[str, Decimal]) -> Summary` — position current value = Σ leg qty × mid (leg's last-known mid reused if token absent — store `last_mid` per fill on each MTM); writes a snapshot row; returns Summary.
    - `summary(self) -> Summary` — same math, no snapshot write.
  - DB tables: `meta(key TEXT PRIMARY KEY, value TEXT)`, `positions(id, opened_at, set_id, description, kind, n_sets, total_cost, guaranteed_payout, status)`, `fills(id, position_id, token_id, label, qty, avg_price, cost, last_mid)`, `opportunities(id, seen_at, set_id, description, cost_per_set, edge, acted, reason)`, `snapshots(id, at, cash, positions_value, total_equity, unrealized_pnl)`. All money columns TEXT (Decimal-string).

- [ ] **Step 1: Write failing tests**

`tests/test_portfolio.py`:
```python
from decimal import Decimal

from agent.models import Fill, Opportunity, Outcome, ResultSet, SetPurchase
from agent.portfolio import Portfolio


def make_purchase(set_id="0xc1", cost="9.7"):
    rs = ResultSet(set_id, "Test?", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    fills = (
        Fill("1", "Yes", Decimal("10"), Decimal("0.55"), Decimal("5.5")),
        Fill("2", "No", Decimal("10"), Decimal("0.42"), Decimal("4.2")),
    )
    return SetPurchase(rs, Decimal("10"), fills, Decimal(cost))


def make_opp(set_id="0xc1"):
    rs = ResultSet(set_id, "Test?", "binary", (Outcome("1", "Yes"), Outcome("2", "No")))
    return Opportunity(rs, {"1": Decimal("0.55"), "2": Decimal("0.42")},
                       Decimal("0.97"), Decimal("0.03"))


def db(tmp_path):
    return str(tmp_path / "ledger.db")


def test_fresh_portfolio_cash(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    assert p.cash() == Decimal("1000")


def test_open_position_reduces_cash(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    assert p.cash() == Decimal("990.3")


def test_duplicate_set_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert not ok
    assert "open position" in reason


def test_insufficient_cash_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("5"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert not ok
    assert "cash" in reason.lower()


def test_max_concurrent_blocked(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase("0xc1"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc2", 1)
    assert not ok
    assert "concurrent" in reason.lower()


def test_can_open_happy(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    ok, reason = p.can_open(Decimal("9.7"), "0xc1", 10)
    assert ok


def test_mark_to_market_reconciles(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())  # cost 9.7 for 10 sets
    s = p.mark_to_market({"1": Decimal("0.60"), "2": Decimal("0.42")})
    # value = 10*0.60 + 10*0.42 = 10.2; cash = 990.3; equity = 1000.5
    assert s.positions_value == Decimal("10.2")
    assert s.cash == Decimal("990.3")
    assert s.total_equity == Decimal("1000.5")
    assert s.unrealized_pnl == Decimal("0.5")
    # guaranteed: 10 sets pay $10 at resolution, cost 9.7 -> +0.3
    assert s.guaranteed_pnl == Decimal("0.3")


def test_mark_to_market_missing_mid_uses_last(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.open_position(make_purchase())
    p.mark_to_market({"1": Decimal("0.60"), "2": Decimal("0.42")})
    s = p.mark_to_market({"1": Decimal("0.65")})  # token 2 missing -> last mid 0.42
    assert s.positions_value == Decimal("10.7")


def test_restart_preserves_state(tmp_path):
    path = db(tmp_path)
    p1 = Portfolio(path, Decimal("1000"))
    p1.open_position(make_purchase())
    p2 = Portfolio(path, Decimal("999999"))  # new starting capital ignored on reopen
    assert p2.cash() == Decimal("990.3")
    assert p2.has_open_position("0xc1")


def test_record_opportunity(tmp_path):
    p = Portfolio(db(tmp_path), Decimal("1000"))
    p.record_opportunity(make_opp(), acted=False, reason="edge below threshold")
    import sqlite3
    rows = sqlite3.connect(db(tmp_path)).execute(
        "SELECT set_id, acted, reason FROM opportunities").fetchall()
    assert rows == [("0xc1", 0, "edge below threshold")]
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `src/agent/portfolio.py`**

```python
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
        self._conn.commit()
        return pid

    def record_opportunity(self, opp: Opportunity, acted: bool, reason: str) -> None:
        self._conn.execute(
            "INSERT INTO opportunities(seen_at, set_id, description, cost_per_set,"
            " edge, acted, reason) VALUES (?,?,?,?,?,?,?)",
            (_now(), opp.result_set.set_id, opp.result_set.description,
             str(opp.cost), str(opp.edge), int(acted), reason))
        self._conn.commit()

    def _compute(self, mids: dict[str, Decimal] | None) -> Summary:
        cash = self.cash()
        value = Decimal("0")
        guaranteed = Decimal("0")
        cost_total = Decimal("0")
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
        self._conn.commit()
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
        self._conn.execute(
            "INSERT INTO snapshots(at, cash, positions_value, total_equity,"
            " unrealized_pnl) VALUES (?,?,?,?,?)",
            (_now(), str(s.cash), str(s.positions_value), str(s.total_equity),
             str(s.unrealized_pnl)))
        self._conn.commit()
        return s

    def summary(self) -> Summary:
        return self._compute(None)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/test_portfolio.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/agent/portfolio.py tests/test_portfolio.py
git commit -m "feat: SQLite virtual ledger with risk limits and restart-safe state"
```

---

### Task 8: Safety guard test

**Files:**
- Test: `tests/test_safety.py`

**Interfaces:**
- Consumes: source tree layout (`src/agent/*.py`).

- [ ] **Step 1: Write the test (should pass immediately if invariants hold)**

`tests/test_safety.py`:
```python
"""Structural read-only guarantee: the agent can never place a real order.

Two invariants:
1. Only cli.py may import subprocess (it is the single gateway to the binary).
2. cli.py must not contain any trading/wallet/on-chain subcommand string.
"""
import pathlib
import re

SRC = pathlib.Path(__file__).parent.parent / "src" / "agent"

FORBIDDEN_IN_CLI = [
    "create-order", "market-order", "post-orders", "cancel",
    "approve", "ctf", "wallet", "bridge", "create-api-key",
    "delete-api-key", "update-balance",
]


def test_only_cli_module_uses_subprocess():
    offenders = []
    for path in SRC.glob("*.py"):
        if path.name == "cli.py":
            continue
        text = path.read_text()
        if re.search(r"^\s*(import subprocess|from subprocess)", text, re.M):
            offenders.append(path.name)
    assert offenders == [], f"subprocess outside cli.py: {offenders}"


def test_cli_module_has_no_write_subcommands():
    text = (SRC / "cli.py").read_text()
    hits = [w for w in FORBIDDEN_IN_CLI if w in text]
    assert hits == [], f"forbidden subcommand strings in cli.py: {hits}"
```

- [ ] **Step 2: Run test**

Run: `.venv/bin/python -m pytest tests/test_safety.py -v`
Expected: PASS (if it fails, fix the offending module — do NOT edit the test)

- [ ] **Step 3: Commit**

```bash
git add tests/test_safety.py
git commit -m "test: structural read-only safety guard"
```

---

### Task 9: Report + agent loop (`report.py`, `agent.py`)

**Files:**
- Create: `src/agent/report.py`, `src/agent/agent.py`
- Test: `tests/test_agent.py`

**Interfaces:**
- Consumes: everything above — exact names from Tasks 2–7.
- Produces:
  - `report.render_summary(s: Summary) -> str` — one-line status: `cash=$X | positions=N | value=$Y | equity=$Z | uPnL=$A | lockedPnL=$B`.
  - `report.render_opportunity(opp: Opportunity, acted: bool, reason: str) -> str`
  - `agent.build_result_sets(cli: PolymarketCli, watchlist: tuple[WatchlistEntry, ...]) -> list[ResultSet]` — resolves each entry via `get_market`/`get_event` + scanner parsers; skips (with a warning print) entries that fail.
  - `agent.tick(cli, sets, portfolio, cfg) -> Summary` — one full cycle: fetch books for all tokens → parse to OrderBook → find_opportunities → for each opp: record + risk-check (`can_open`) + `plan_set_purchase` (max_cost_per_set = `1 - cfg.min_edge - cfg.est_fee`) → open_position → mark_to_market using book-derived midpoints → return Summary.
  - `agent.main(argv: list[str] | None = None) -> int` — argparse: `--config config.yaml`, `--once` (single tick), `--refresh-every N` (rebuild result sets every N ticks, default 60). Loop: tick, print report lines, sleep `poll_interval_seconds`. Catches `CliError`/unexpected exceptions per tick: print + continue (KeyboardInterrupt exits cleanly).
  - Entry point: `python -m agent.agent` (uses `if __name__ == "__main__": raise SystemExit(main())`).

- [ ] **Step 1: Write failing tests**

`tests/test_agent.py`:
```python
import json
from decimal import Decimal

from agent.agent import build_result_sets, tick
from agent.config import Config, WatchlistEntry
from agent.portfolio import Portfolio


class FakeCli:
    """In-memory PolymarketCli double: same method names/signatures."""

    def __init__(self, markets=None, events=None, books=None):
        self.markets = markets or {}
        self.events = events or {}
        self.books = books or {}

    def get_market(self, ref):
        return self.markets[ref]

    def get_event(self, ref):
        return self.events[ref]

    def get_books(self, token_ids):
        return {t: self.books[t] for t in token_ids if t in self.books}

    def get_midpoints(self, token_ids):
        raise AssertionError("mids must derive from books, not extra CLI calls")


def market_json(cond="0xc1", yes="101", no="102"):
    return {
        "conditionId": cond, "question": "Q?", "slug": "q",
        "active": True, "closed": False, "enableOrderBook": True,
        "clobTokenIds": json.dumps([yes, no]),
        "outcomes": json.dumps(["Yes", "No"]),
    }


def raw_book(token, ask, bid, size="1000"):
    return {"asset_id": token,
            "asks": [{"price": ask, "size": size}],
            "bids": [{"price": bid, "size": size}]}


def cfg(tmp_path, min_edge="0.01"):
    return Config(
        virtual_capital_usd=Decimal("1000"),
        poll_interval_seconds=0.01,
        min_edge=Decimal(min_edge),
        est_fee=Decimal("0"),
        max_notional_per_trade_usd=Decimal("50"),
        max_concurrent_positions=10,
        sanity_min_mid_sum=Decimal("0.90"),
        db_path=str(tmp_path / "ledger.db"),
        watchlist=(WatchlistEntry("binary", "q"),),
    )


def test_build_result_sets_binary(tmp_path):
    cli = FakeCli(markets={"q": market_json()})
    sets = build_result_sets(cli, (WatchlistEntry("binary", "q"),))
    assert len(sets) == 1
    assert sets[0].token_ids == ["101", "102"]


def test_build_result_sets_skips_failures(tmp_path, capsys):
    class Boom(FakeCli):
        def get_market(self, ref):
            raise RuntimeError("api down")
    sets = build_result_sets(Boom(), (WatchlistEntry("binary", "q"),))
    assert sets == []


def test_tick_opens_position_on_arb(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.open_positions == 1
    assert s.guaranteed_pnl > 0
    assert portfolio.has_open_position("0xc1")


def test_tick_no_arb_no_position(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.46", "0.44")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.open_positions == 0


def test_tick_does_not_reopen_same_set(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    tick(cli, sets, portfolio, c)
    s2 = tick(cli, sets, portfolio, c)
    assert s2.open_positions == 1  # still exactly one


def test_tick_mtm_reconciles(tmp_path):
    c = cfg(tmp_path)
    cli = FakeCli(
        markets={"q": market_json()},
        books={"101": raw_book("101", "0.55", "0.53"),
               "102": raw_book("102", "0.42", "0.40")},
    )
    sets = build_result_sets(cli, c.watchlist)
    portfolio = Portfolio(c.db_path, c.virtual_capital_usd)
    s = tick(cli, sets, portfolio, c)
    assert s.total_equity == s.cash + s.positions_value
```

- [ ] **Step 2: Run tests to verify failure**

Run: `.venv/bin/python -m pytest tests/test_agent.py -v`
Expected: FAIL (ImportError)

- [ ] **Step 3: Implement `src/agent/report.py`**

```python
"""Plain-text rendering for the loop. No business logic here."""
from __future__ import annotations

from agent.models import Opportunity
from agent.portfolio import Summary


def _fmt(d) -> str:
    return f"${d:,.2f}"


def render_summary(s: Summary) -> str:
    return (
        f"cash={_fmt(s.cash)} | positions={s.open_positions} | "
        f"value={_fmt(s.positions_value)} | equity={_fmt(s.total_equity)} | "
        f"uPnL={_fmt(s.unrealized_pnl)} | lockedPnL={_fmt(s.guaranteed_pnl)}"
    )


def render_opportunity(opp: Opportunity, acted: bool, reason: str) -> str:
    mark = "TRADED" if acted else "SKIP"
    return (
        f"[{mark}] {opp.result_set.kind} {opp.result_set.description[:60]!r} "
        f"cost/set={opp.cost} edge={opp.edge} ({reason})"
    )
```

- [ ] **Step 4: Implement `src/agent/agent.py`**

```python
"""Real-time polling loop. One tick = fetch books -> scan -> risk-check ->
simulate fills -> ledger -> mark-to-market -> report."""
from __future__ import annotations

import argparse
import time
from decimal import Decimal

from agent import report
from agent.cli import CliError, PolymarketCli
from agent.config import Config, WatchlistEntry, load_config
from agent.fills import plan_set_purchase
from agent.models import OrderBook, ResultSet
from agent.portfolio import Portfolio, Summary
from agent.scanner import find_opportunities, result_set_from_event, result_set_from_market


def build_result_sets(cli, watchlist: tuple[WatchlistEntry, ...]) -> list[ResultSet]:
    sets: list[ResultSet] = []
    for entry in watchlist:
        try:
            if entry.type == "binary":
                rs = result_set_from_market(cli.get_market(entry.ref))
            else:
                rs = result_set_from_event(cli.get_event(entry.ref))
        except Exception as e:  # noqa: BLE001 - one bad entry must not kill the loop
            print(f"warn: watchlist entry {entry.ref!r} failed: {e}")
            continue
        if rs is None:
            print(f"warn: watchlist entry {entry.ref!r} is not tradeable, skipping")
            continue
        sets.append(rs)
    return sets


def tick(cli, sets: list[ResultSet], portfolio: Portfolio, cfg: Config) -> Summary:
    all_tokens = sorted({t for rs in sets for t in rs.token_ids})
    raw_books = cli.get_books(all_tokens)
    books = {tid: OrderBook.from_json(b) for tid, b in raw_books.items()}

    opps = find_opportunities(
        sets, books, cfg.min_edge, cfg.est_fee, cfg.sanity_min_mid_sum
    )
    for opp in opps:
        ok, reason = portfolio.can_open(
            cfg.max_notional_per_trade_usd, opp.result_set.set_id,
            cfg.max_concurrent_positions,
        )
        if not ok:
            portfolio.record_opportunity(opp, acted=False, reason=reason)
            print(report.render_opportunity(opp, False, reason))
            continue
        purchase = plan_set_purchase(
            opp.result_set, books,
            max_cost_per_set=Decimal("1") - cfg.min_edge - cfg.est_fee,
            max_notional=min(cfg.max_notional_per_trade_usd, portfolio.cash()),
        )
        if purchase is None:
            portfolio.record_opportunity(opp, acted=False, reason="insufficient depth")
            print(report.render_opportunity(opp, False, "insufficient depth"))
            continue
        portfolio.open_position(purchase)
        reason = (f"bought {purchase.n_sets} sets @ {purchase.cost_per_set} "
                  f"locked={purchase.locked_profit}")
        portfolio.record_opportunity(opp, acted=True, reason=reason)
        print(report.render_opportunity(opp, True, reason))

    mids = {tid: b.midpoint for tid, b in books.items() if b.midpoint is not None}
    return portfolio.mark_to_market(mids)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Polymarket paper-trading arb agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--once", action="store_true", help="run a single tick")
    parser.add_argument("--refresh-every", type=int, default=60,
                        help="rebuild result sets every N ticks")
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    cli = PolymarketCli()
    portfolio = Portfolio(cfg.db_path, cfg.virtual_capital_usd)

    print(f"watchlist: {len(cfg.watchlist)} entries; paper capital "
          f"${cfg.virtual_capital_usd}; poll every {cfg.poll_interval_seconds}s "
          f"(read-only, fills are simulated)")
    sets = build_result_sets(cli, cfg.watchlist)
    if not sets:
        print("error: no tradeable sets in watchlist")
        return 1
    print(f"tracking {len(sets)} result sets, "
          f"{sum(len(rs.outcomes) for rs in sets)} outcome tokens")

    n = 0
    while True:
        try:
            summary = tick(cli, sets, portfolio, cfg)
            print(report.render_summary(summary))
        except CliError as e:
            print(f"warn: tick failed: {e}")
        except KeyboardInterrupt:
            print("\nstopping.")
            return 0
        except Exception as e:  # noqa: BLE001 - loop must survive surprises
            print(f"error: unexpected failure in tick: {e!r}")
        if args.once:
            return 0
        n += 1
        if n % args.refresh_every == 0:
            sets = build_result_sets(cli, cfg.watchlist) or sets
        try:
            time.sleep(cfg.poll_interval_seconds)
        except KeyboardInterrupt:
            print("\nstopping.")
            return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests (all suites — integration must not break earlier modules)**

Run: `.venv/bin/python -m pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/agent/agent.py src/agent/report.py tests/test_agent.py
git commit -m "feat: real-time polling loop with per-tick error isolation"
```

---

### Task 10: Live smoke test + real watchlist + README

**Files:**
- Modify: `config.yaml` (real watchlist entries)
- Create: `README.md`

**Interfaces:**
- Consumes: the installed `polymarket` binary and everything built above.

- [ ] **Step 1: Pick live watchlist entries (read-only CLI calls)**

```bash
# High-volume active binary markets:
polymarket -o json markets list --limit 10 --active true --closed false --order volume_num \
  | python3 -c "import json,sys; [print(m['slug'], '|', m['question'][:60]) for m in json.load(sys.stdin)]"
# An active neg-risk event (prefer one that is NOT same-day sports, so it stays alive):
polymarket -o json events list --limit 20 --active true --closed false --order volume \
  | python3 -c "import json,sys; [print(e['id'], '| negRisk:', e.get('negRisk'), '|', e['title'][:60]) for e in json.load(sys.stdin) if e.get('negRisk')]"
```

Update `config.yaml` watchlist with 2–3 binary slugs and 1–2 event ids from the output.

- [ ] **Step 2: Single-tick smoke run**

Run: `cd /Users/shenyi/polymarket-agent && PYTHONPATH=src .venv/bin/python -m agent.agent --once`
Expected: prints watchlist/tracking lines, zero or more `[SKIP]/[TRADED]` lines, one summary line; exit 0. `virtual_ledger.db` created with ≥1 snapshot row.

- [ ] **Step 3: Verify ledger reconciliation**

```bash
.venv/bin/python - <<'EOF'
import sqlite3
conn = sqlite3.connect("virtual_ledger.db")
print("snapshots:", conn.execute("SELECT COUNT(*) FROM snapshots").fetchone()[0])
print("opportunities:", conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0])
for row in conn.execute("SELECT at, cash, positions_value, total_equity FROM snapshots ORDER BY id DESC LIMIT 3"):
    print(row)
EOF
```
Expected: snapshot rows exist; equity = cash + positions_value.

- [ ] **Step 4: Short live loop run (~30s)**

Run: `PYTHONPATH=src timeout 30 .venv/bin/python -m agent.agent || true`
Expected: several summary lines ~5s apart, no crashes/tracebacks.

- [ ] **Step 5: Write `README.md`**

```markdown
# Polymarket Paper-Trading Arb Agent

Real-time **paper-trading** agent: watches real Polymarket order books via the
[`polymarket` CLI](https://github.com/Polymarket/polymarket-cli), detects
complete-set arbitrage (sum of best asks for a full set of mutually exclusive
outcomes < $1), simulates depth-aware fills, and tracks P&L in a local SQLite
virtual ledger.

**100% read-only.** No wallet, no private key, no real orders — structurally
enforced by `tests/test_safety.py`.

## Setup

```bash
brew tap Polymarket/polymarket-cli https://github.com/Polymarket/polymarket-cli
brew install polymarket
python3 -m venv .venv && .venv/bin/pip install pytest pyyaml
```

## Run

```bash
PYTHONPATH=src .venv/bin/python -m agent.agent           # real-time loop
PYTHONPATH=src .venv/bin/python -m agent.agent --once    # single tick
.venv/bin/python -m pytest                               # tests
```

Edit `config.yaml` to set the watchlist (market slugs / event ids), virtual
capital, edge threshold, and poll interval.

## How it works

One tick: fetch books for every watched outcome token (batched) → flag sets
whose best asks sum below `$1 − min_edge − est_fee` (with a Σ-midpoints
sanity guard against non-exhaustive event sets) → walk real book depth to
size the paper fill → record in the ledger → mark-to-market from book mids.

## Expectations

True risk-free arbs are rare and small on a liquid venue; the point of this
agent is a correct detection/execution loop, learning market mechanics, and
measuring how often edge appears. Watch near-misses by lowering `min_edge`.
```

- [ ] **Step 6: Full test suite + commit**

Run: `.venv/bin/python -m pytest -v`
Expected: all PASS

```bash
git add config.yaml README.md
git commit -m "feat: live watchlist, README, smoke-tested against real markets"
```

---

## Verification checklist (spec §9 acceptance criteria → tests)

1. Scanner flags $0.97 set / ignores $1.00 → `test_scanner.py::test_find_opportunity_cheap_set_flagged`, `test_find_opportunity_fair_set_ignored`, 3-outcome $0.95 → `test_find_opportunity_three_outcome_event`. ✓
2. Fill simulator multi-level avg price + thin-book rejection → `test_fills.py::test_plan_set_purchase_walks_depth_until_edge_gone`, `test_walk_book_insufficient_depth`. ✓
3. Safety: no write subcommands → `test_safety.py`. ✓
4. Live read-only smoke + ledger reconciliation → Task 10 steps 2–4. ✓
