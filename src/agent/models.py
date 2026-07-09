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
    payout_floor_per_set: Decimal = Decimal("1")

    @property
    def cost_per_set(self) -> Decimal:
        return self.total_cost / self.n_sets

    @property
    def guaranteed_payout(self) -> Decimal:
        return self.n_sets * self.payout_floor_per_set

    @property
    def locked_profit(self) -> Decimal:
        return self.guaranteed_payout - self.total_cost
