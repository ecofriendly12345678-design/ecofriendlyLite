# Polymarket Paper-Trading Arb Agent

Real-time **paper-trading** agent: watches real Polymarket order books via the
[`polymarket` CLI](https://github.com/Polymarket/polymarket-cli), detects
complete-set arbitrage (sum of best asks for a full set of mutually exclusive
outcomes < $1), simulates depth-aware fills, and tracks P&L in a local SQLite
virtual ledger.

**100% read-only.** No wallet, no private key, no real orders — structurally
enforced by `tests/test_safety.py` (only `cli.py` may spawn the binary, and it
exposes read-only subcommands only).

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
PYTHONPATH=src .venv/bin/python -m agent.dashboard       # live local dashboard
.venv/bin/python -m pytest                               # tests
```

Edit `config.yaml` to set the watchlist (market slugs / event ids), virtual
capital, edge threshold, poll interval, and strategy buckets.

## How it works

One tick: fetch books for every watched outcome token (batched, with
per-token fallback if a batch fails) → flag sets whose best asks sum below
`$1 − min_edge − est_fee` (with a Σ-midpoints sanity guard against
non-exhaustive event sets) → size the paper fill by bisection against real
book depth (largest quantity satisfying the notional cap and per-set cost
cap) → risk-gate on actual cost (per-strategy dedupe, concurrency, cash) →
record in the ledger → mark-to-market from book mids.

## Expectations

True risk-free arbs are rare and small on a liquid venue; the point of this
agent is a correct detection/execution loop, learning market mechanics, and
measuring how often edge appears. Watch near-misses by lowering `min_edge`.

## v2 scaffold

The v2 strategy layer is being introduced behind the existing v1 loop.
`complete_set` remains enabled by default. `implication` is disabled until
`implications.yaml` contains manually verified A-implies-B relations with
matching resolution terms. `momentum` stays disabled until v2b backtests
validate parameters.

## Dashboard

Run the local dashboard server, then open `http://127.0.0.1:8765`:

```bash
PYTHONPATH=src .venv/bin/python -m agent.dashboard --db virtual_ledger.db
```

The page polls the local SQLite ledger every two seconds and shows paper orders,
fills, positions, cash, equity, and P&L. It does not connect to Polymarket and
does not place orders.

## Design docs

- Spec: `docs/superpowers/specs/2026-07-08-polymarket-paper-arb-agent-design.md`
- Plan: `docs/superpowers/plans/2026-07-08-polymarket-paper-arb-agent.md`
- v2 (implication arb + momentum): `docs/superpowers/specs/2026-07-08-v2-implication-momentum-design.md`
