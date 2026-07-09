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
