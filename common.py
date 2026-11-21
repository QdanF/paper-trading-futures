"""Aturan + util bersama untuk paper trading futures virtual.

UANG VIRTUAL SAJA. Tidak ada uang asli, tidak ada API key, tidak ada order
ke exchange mana pun. Harga diambil dari API publik Binance US (tanpa key).
"""

import json
import requests

# ---------------------------------------------------------------- aturan mizan
BANKROLL_START = 1000.0        # modal virtual USD
RISK_PER_TRADE_USD = 10.0      # risiko maks per trade
MAX_TOTAL_LOSS_USD = 100.0     # total kerugian maks, lalu berhenti buka trade
LEVERAGE = 3                   # leverage tetap 3x (maks yang diizinkan 3-5x)
SL_PCT = 0.015                 # stop-loss 1,5% dari harga entry
TP_PCT = 0.030                 # take-profit 3% (risk:reward 1:2)
TAKER_FEE_PCT = 0.0005         # fee taker 0,05% per sisi, dari notional
ASSETS = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
TIMEFRAME = "1h"
EMA_FAST = 12
EMA_SLOW = 26

BINANCE_US = "https://api.binance.us"


def position_notional_usd():
    """Notional per trade, dihitung dari risiko: $10 / 1,5% = $666,67."""
    return RISK_PER_TRADE_USD / SL_PCT


def margin_required_usd():
    """Margin yang dikunci per trade pada leverage 3x."""
    return position_notional_usd() / LEVERAGE


def fees_usd(notional):
    """Fee masuk + keluar (0,05% x 2) dari notional."""
    return 2 * TAKER_FEE_PCT * notional


def pnl_gross_usd(side, entry, exit_price, notional):
    """PnL kotor (belum fee) dalam USD."""
    if side == "long":
        ret = (exit_price - entry) / entry
    else:
        ret = (entry - exit_price) / entry
    return notional * ret


def sl_price(side, entry):
    return entry * (1 - SL_PCT) if side == "long" else entry * (1 + SL_PCT)


def tp_price(side, entry):
    return entry * (1 + TP_PCT) if side == "long" else entry * (1 - TP_PCT)


# ---------------------------------------------------------------- data publik
def get_klines(symbol, interval=TIMEFRAME, limit=1000):
    """Ambil candle dari Binance US (publik, tanpa key)."""
    r = requests.get(
        f"{BINANCE_US}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit},
        timeout=15,
    )
    r.raise_for_status()
    rows = r.json()
    return [
        {
            "open_time": int(x[0]),
            "open": float(x[1]),
            "high": float(x[2]),
            "low": float(x[3]),
            "close": float(x[4]),
            "volume": float(x[5]),
        }
        for x in rows
    ]


def get_price(symbol):
    """Harga terakhir satu simbol dari Binance US (publik, tanpa key)."""
    r = requests.get(
        f"{BINANCE_US}/api/v3/ticker/price",
        params={"symbol": symbol},
        timeout=10,
    )
    r.raise_for_status()
    return float(r.json()["price"])


def get_prices(symbols):
    out = {}
    for s in symbols:
        try:
            out[s] = get_price(s)
        except Exception:
            pass
    return out
