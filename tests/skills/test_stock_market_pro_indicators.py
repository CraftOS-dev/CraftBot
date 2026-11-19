"""skills/stock-market-pro/scripts/yf.py indicators against TA-Lib reference values."""

import importlib.util
import math
import sys
import types
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("fin_primitives")

SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills"
    / "stock-market-pro"
    / "scripts"
    / "yf.py"
)


def _load():
    # The script imports charting/terminal packages at module level; the indicator
    # functions only need pandas and fin-primitives, so stub the rest when absent.
    for name in ("yfinance", "plotille", "mplfinance"):
        if name not in sys.modules:
            try:
                importlib.import_module(name)
            except ImportError:
                sys.modules[name] = types.ModuleType(name)
    pytest.importorskip("matplotlib")
    pytest.importorskip("rich")
    spec = importlib.util.spec_from_file_location("stock_market_pro_yf", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


yf_script = _load()

CLOSE = [
    101.2,
    100.8,
    101.7,
    102.0,
    101.3,
    102.5,
    102.1,
    103.0,
    103.3,
    102.6,
    103.8,
    103.4,
    104.3,
    104.6,
    103.9,
    105.1,
    104.7,
    105.6,
    105.9,
    105.2,
    106.4,
    106.0,
    106.9,
    107.2,
    106.5,
    105.4,
    105.9,
    105.1,
    104.8,
    105.4,
    104.3,
    104.8,
    104.0,
    103.7,
    104.3,
    103.2,
    103.7,
    102.9,
    102.6,
    103.2,
]
HIGH = [
    101.5,
    101.2,
    102.2,
    102.6,
    101.6,
    102.9,
    102.6,
    103.6,
    103.6,
    103.0,
    104.3,
    104.0,
    104.6,
    105.0,
    104.4,
    105.7,
    105.0,
    106.0,
    106.4,
    105.8,
    106.7,
    106.4,
    107.4,
    107.8,
    106.8,
    105.8,
    106.4,
    105.7,
    105.1,
    105.8,
    104.8,
    105.4,
    104.3,
    104.1,
    104.8,
    103.8,
    104.0,
    103.3,
    103.1,
    103.8,
]
LOW = [
    100.8,
    100.3,
    101.1,
    101.6,
    100.8,
    101.9,
    101.7,
    102.5,
    102.7,
    102.2,
    103.3,
    102.8,
    103.9,
    104.1,
    103.3,
    104.7,
    104.2,
    105.0,
    105.5,
    104.7,
    105.8,
    105.6,
    106.4,
    106.6,
    106.1,
    104.9,
    105.3,
    104.7,
    104.3,
    104.8,
    103.9,
    104.3,
    103.4,
    103.3,
    103.8,
    102.6,
    103.3,
    102.4,
    102.0,
    102.8,
]
IDX = pd.date_range("2024-01-01", periods=len(CLOSE), freq="B")


def test_rsi_matches_talib():
    rsi = yf_script.calc_rsi(pd.Series(CLOSE, index=IDX))
    assert rsi.iloc[:14].isna().all()
    # talib.RSI(close, 14) with TA-Lib 0.6: bar 14 = 64.51612903225808, last = 45.822427428823396
    assert math.isclose(rsi.iloc[14], 64.51612903225808, rel_tol=1e-12)
    assert math.isclose(rsi.iloc[-1], 45.822427428823396, rel_tol=1e-12)


def test_atr_matches_talib():
    df = pd.DataFrame({"High": HIGH, "Low": LOW, "Close": CLOSE}, index=IDX)
    atr = yf_script.calc_atr(df)
    # talib.ATR(high, low, close, 14): first value at bar 14 (1.1999999999999997), last 1.1830924418269704
    assert atr.iloc[:14].isna().all()
    assert math.isclose(atr.iloc[14], 1.1999999999999997, rel_tol=1e-12)
    assert math.isclose(atr.iloc[-1], 1.1830924418269704, rel_tol=1e-12)


def test_short_input_is_empty_not_wrong():
    assert yf_script.calc_rsi(pd.Series(CLOSE[:10], index=IDX[:10])).isna().all()
