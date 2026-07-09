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


def test_default_strategy_config_when_missing(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(VALID)
    cfg = load_config(str(p))

    assert cfg.strategies["complete_set"].enabled is True
    assert cfg.strategies["complete_set"].bucket_usd == cfg.virtual_capital_usd
    assert cfg.strategies["implication"].enabled is False
    assert cfg.strategies["momentum"].enabled is False


def test_load_strategy_config(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        VALID
        + """
strategies:
  complete_set:
    enabled: true
    bucket_usd: 500
  implication:
    enabled: true
    bucket_usd: 300
    relations_file: implications.yaml
  momentum:
    enabled: false
    bucket_usd: 200
    params:
      lookback_minutes: 60
"""
    )
    cfg = load_config(str(p))

    assert cfg.strategies["complete_set"].bucket_usd == Decimal("500")
    assert cfg.strategies["implication"].enabled is True
    assert cfg.strategies["implication"].relations_file == "implications.yaml"
    assert cfg.strategies["momentum"].params == {"lookback_minutes": 60}


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
