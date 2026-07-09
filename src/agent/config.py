"""Load and validate config.yaml. Money fields become Decimal (parsed from str)."""
from __future__ import annotations

from dataclasses import dataclass, field
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
class StrategyConfig:
    enabled: bool
    bucket_usd: Decimal
    relations_file: str | None = None
    params: dict[str, object] = field(default_factory=dict)


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
    strategies: dict[str, StrategyConfig] = field(default_factory=dict)


def _dec(raw: object, field: str) -> Decimal:
    try:
        return Decimal(str(raw))
    except InvalidOperation as e:
        raise ValueError(f"config field {field!r} is not a valid number: {raw!r}") from e


def _bool(raw: object) -> bool:
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _load_strategies(data: dict, virtual_capital: Decimal) -> dict[str, StrategyConfig]:
    defaults = {
        "complete_set": StrategyConfig(True, virtual_capital),
        "implication": StrategyConfig(False, Decimal("0"), relations_file="implications.yaml"),
        "momentum": StrategyConfig(False, Decimal("0")),
    }
    raw = data.get("strategies") or {}
    if not isinstance(raw, dict):
        raise ValueError("config field 'strategies' must be a mapping")
    unknown = set(raw) - set(defaults)
    if unknown:
        raise ValueError(f"unknown strategy config sections: {sorted(unknown)}")

    strategies: dict[str, StrategyConfig] = {}
    for name, default in defaults.items():
        section = raw.get(name) or {}
        if not isinstance(section, dict):
            raise ValueError(f"strategies.{name} must be a mapping")
        params = section.get("params", default.params)
        if not isinstance(params, dict):
            raise ValueError(f"strategies.{name}.params must be a mapping")
        relations_file = section.get("relations_file", default.relations_file)
        strategies[name] = StrategyConfig(
            enabled=_bool(section.get("enabled", default.enabled)),
            bucket_usd=_dec(
                section.get("bucket_usd", default.bucket_usd),
                f"strategies.{name}.bucket_usd",
            ),
            relations_file=str(relations_file) if relations_file is not None else None,
            params=dict(params),
        )
    return strategies


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

    virtual_capital = _dec(data["virtual_capital_usd"], "virtual_capital_usd")
    return Config(
        virtual_capital_usd=virtual_capital,
        poll_interval_seconds=float(data["poll_interval_seconds"]),
        min_edge=_dec(data["min_edge"], "min_edge"),
        est_fee=_dec(data["est_fee"], "est_fee"),
        max_notional_per_trade_usd=_dec(data["max_notional_per_trade_usd"], "max_notional_per_trade_usd"),
        max_concurrent_positions=int(data["max_concurrent_positions"]),
        sanity_min_mid_sum=_dec(data["sanity_min_mid_sum"], "sanity_min_mid_sum"),
        db_path=str(data["db_path"]),
        watchlist=tuple(entries),
        strategies=_load_strategies(data, virtual_capital),
    )
