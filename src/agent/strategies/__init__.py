"""Strategy plugin contracts for v2.

Strategies are pure over already-fetched books. The live loop and backtester
can drive the same protocol by changing only TickContext.now/books.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Mapping, Protocol

from agent.models import Fill, OrderBook, SetPurchase


@dataclass(frozen=True)
class TickContext:
    now: datetime
    config_section: Mapping[str, Any]


@dataclass(frozen=True)
class EntryProposal:
    strategy: str
    purchase: SetPurchase
    reason: str


@dataclass(frozen=True)
class ExitProposal:
    position_id: int
    sell_fills: tuple[Fill, ...]
    reason: str


@dataclass(frozen=True)
class PositionLeg:
    token_id: str
    qty: Decimal
    avg_price: Decimal


@dataclass(frozen=True)
class OpenPosition:
    id: int
    strategy: str
    set_id: str
    opened_at: str
    n_sets: Decimal
    total_cost: Decimal
    legs: tuple[PositionLeg, ...]


class StrategyProtocol(Protocol):
    name: str

    def required_tokens(self) -> list[str]:
        ...

    def propose_entries(
        self, books: dict[str, OrderBook], ctx: TickContext,
    ) -> list[EntryProposal]:
        ...

    def propose_exits(
        self,
        books: dict[str, OrderBook],
        open_positions: list[OpenPosition],
        ctx: TickContext,
    ) -> list[ExitProposal]:
        ...


def decimal_config(ctx: TickContext, key: str) -> Decimal:
    return Decimal(str(ctx.config_section[key]))
