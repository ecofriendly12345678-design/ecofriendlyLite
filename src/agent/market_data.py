"""Market-data snapshots consumed by paper execution.

The live agent creates these from freshly fetched Polymarket CLOB books. Tests
and backtests may construct them from fixtures, but live fills require
``source == "polymarket_cli"`` in the broker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from agent.models import OrderBook


@dataclass(frozen=True)
class BookSnapshot:
    fetched_at: datetime
    source: str
    books: dict[str, OrderBook]
