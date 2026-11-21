"""Backtest strategi futures virtual pada 30 hari terakhir (timeframe 1 jam).

Strategi: trend-following EMA 12/26 crossover.
- EMA12 motong ke atas EMA26  -> LONG
- EMA12 motong ke bawah EMA26 -> SHORT
- Entry di close candle sinyal; SL 1,5%, TP 3%; maks 1 posisi per aset.
- Risiko $10/trade, notional $666,67, leverage 3x, margin $222,22.
- Fee taker 0,05% per sisi. Kalau total kerugian sudah -$100, stop buka trade.

Jalankan:  python3 backtest.py
Hasil:    backtest_trades.csv, backtest_summary.json, dan ringkasan di layar.
"""

import csv
import json
import os
from datetime import datetime, timezone

import pandas as pd

from common import (
    ASSETS, BANKROLL_START, EMA_FAST, EMA_SLOW, LEVERAGE,
    MAX_TOTAL_LOSS_USD, RISK_PER_TRADE_USD, SL_PCT, TP_PCT,
    fees_usd, get_klines, margin_required_usd, pnl_gross_usd,
    position_notional_usd, sl_price, tp_price,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DAYS = 30
CANDLES = DAYS * 24  # 720 candle 1 jam


def load_frame(symbol):
    klines = get_klines(symbol, limit=1000)
    df = pd.DataFrame(klines)
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    return df


def backtest_asset(symbol):
    """Jalankan backtest untuk satu aset. Kembalikan (trades, open_positions)."""
    df = load_frame(symbol)
    start = len(df) - CANDLES  # hanya 30 hari terakhir yang dihitung
    cash = BANKROLL_START
    realized = 0.0
    reserved_margin = 0.0
    trades = []
    position = None  # dict: side, entry, sl, tp, notional, margin, open_time

    for i in range(start, len(df)):
        row = df.iloc[i]
        prev = df.iloc[i - 1]

        # --- 1. cek SL / TP dulu pada candle ini (pakai high/low) ---
        if position is not None:
            hit_sl = hit_tp = False
            if position["side"] == "long":
                hit_sl = row["low"] <= position["sl"]
                hit_tp = row["high"] >= position["tp"]
            else:
                hit_sl = row["high"] >= position["sl"]
                hit_tp = row["low"] <= position["tp"]
            # kalau SL dan TP sama-sama kesenggol di satu candle, SL dulu
            # (aturan konservatif: yang rugi dihitung duluan).
            if hit_sl or hit_tp:
                exit_price = position["sl"] if hit_sl else position["tp"]
                reason = "SL" if hit_sl else "TP"
                gross = pnl_gross_usd(position["side"], position["entry"],
                                      exit_price, position["notional"])
                pnl = gross - fees_usd(position["notional"])
                cash += pnl
                realized += pnl
                reserved_margin -= position["margin"]
                trades.append({**position, "exit": exit_price,
                               "exit_time": int(row["open_time"]),
                               "reason": reason, "pnl_usd": round(pnl, 2),
                               "status": "closed"})
                position = None
                continue  # candle ini sudah dipakai menutup; jangan buka baru

        # --- 2. sinyal crossover di close candle ini ---
        crossed_up = prev["ema_fast"] <= prev["ema_slow"] and row["ema_fast"] > row["ema_slow"]
        crossed_down = prev["ema_fast"] >= prev["ema_slow"] and row["ema_fast"] < row["ema_slow"]

        if position is not None and ((position["side"] == "long" and crossed_down)
                                     or (position["side"] == "short" and crossed_up)):
            # tren berbalik: tutup di close, alasan "reverse"
            gross = pnl_gross_usd(position["side"], position["entry"],
                                  row["close"], position["notional"])
            pnl = gross - fees_usd(position["notional"])
            cash += pnl
            realized += pnl
            reserved_margin -= position["margin"]
            trades.append({**position, "exit": row["close"],
                           "exit_time": int(row["open_time"]),
                           "reason": "reverse", "pnl_usd": round(pnl, 2),
                           "status": "closed"})
            position = None

        if position is None and (crossed_up or crossed_down):
            if realized <= -MAX_TOTAL_LOSS_USD:
                continue  # total kerugian sudah -$100: berhenti buka trade
            margin = margin_required_usd()
            if cash - reserved_margin < margin:
                continue  # kas bebas tidak cukup buat margin
            side = "long" if crossed_up else "short"
            entry = row["close"]
            position = {
                "asset": symbol, "side": side, "entry": entry,
                "sl": sl_price(side, entry), "tp": tp_price(side, entry),
                "notional": position_notional_usd(), "margin": margin,
                "open_time": int(row["open_time"]),
                "leverage": LEVERAGE,
            }
            reserved_margin += margin

    open_positions = []
    if position is not None:
        last_close = float(df.iloc[-1]["close"])
        unreal = pnl_gross_usd(position["side"], position["entry"],
                               last_close, position["notional"])
        open_positions.append({**position, "last_price": last_close,
                               "unrealized_pnl_usd": round(unreal, 2)})

    return trades, open_positions, float(cash), float(realized)


def main():
    all_trades, all_open = [], []
    cash_total = BANKROLL_START
    realized_total = 0.0
    per_asset = {}

    for symbol in ASSETS:
        trades, open_pos, cash, realized = backtest_asset(symbol)
        all_trades.extend(trades)
        all_open.extend(open_pos)
        # kas dihitung per aset dari modal awal yang sama; untuk laporan
        # gabungan, PnL dijumlahkan, bukan kas per aset.
        realized_total += realized
        wins = sum(1 for t in trades if t["pnl_usd"] > 0)
        per_asset[symbol] = {
            "trades": len(trades),
            "menang": wins,
            "kalah": len(trades) - wins,
            "pnl_usd": round(float(realized), 2),
            "posisi_open": len(open_pos),
        }
        print(f"{symbol}: {len(trades)} trade, {wins} menang, "
              f"PnL ${realized:+.2f}, open {len(open_pos)}")

    total = len(all_trades)
    wins = sum(1 for t in all_trades if t["pnl_usd"] > 0)
    losses = [float(t["pnl_usd"]) for t in all_trades if t["pnl_usd"] < 0]
    wins_list = [float(t["pnl_usd"]) for t in all_trades if t["pnl_usd"] > 0]
    realized_total = float(realized_total)
    equity = BANKROLL_START + realized_total
    peak = BANKROLL_START
    max_dd = 0.0
    running = BANKROLL_START
    for t in sorted(all_trades, key=lambda x: x["exit_time"]):
        running += t["pnl_usd"]
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    summary = {
        "periode": f"{DAYS} hari terakhir, timeframe 1h, data Binance US (spot sbg proxy harga futures)",
        "strategi": f"EMA {EMA_FAST}/{EMA_SLOW} crossover, SL {SL_PCT*100:.1f}%, TP {TP_PCT*100:.1f}%, leverage {LEVERAGE}x",
        "modal_virtual_usd": BANKROLL_START,
        "risiko_per_trade_usd": RISK_PER_TRADE_USD,
        "total_trade": total,
        "menang": wins,
        "kalah": total - wins,
        "win_rate_pct": round(100 * wins / total, 1) if total else 0.0,
        "total_pnl_virtual_usd": round(realized_total, 2),
        "kas_virtual_usd": round(equity, 2),
        "posisi_masih_open": len(all_open),
        "unrealized_pnl_open_usd": round(sum(o["unrealized_pnl_usd"] for o in all_open), 2),
        "rata_rata_menang_usd": round(sum(wins_list) / len(wins_list), 2) if wins_list else 0.0,
        "rata_rata_kalah_usd": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "max_drawdown_usd": round(max_dd, 2),
        "aturan_max_loss_100_tercapai": bool(realized_total <= -MAX_TOTAL_LOSS_USD),
        "per_aset": per_asset,
    }

    trades_path = os.path.join(BASE_DIR, "backtest_trades.csv")
    with open(trades_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["asset", "side", "entry", "sl", "tp",
                                          "notional", "margin", "leverage",
                                          "open_time", "exit", "exit_time",
                                          "reason", "pnl_usd", "status"])
        w.writeheader()
        for t in all_trades:
            w.writerow({k: t.get(k, "") for k in w.fieldnames})

    with open(os.path.join(BASE_DIR, "backtest_summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    print("\n=== RINGKASAN BACKTEST ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\nTrade tersimpan: {trades_path}")


if __name__ == "__main__":
    main()
