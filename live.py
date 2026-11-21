"""Forward test LIVE virtual (paper trading futures) — jalan terus di background.

Strategi SAMA PERSIS dengan backtest.py: EMA 12/26 crossover di candle 1 jam,
SL 1,5%, TP 3%, leverage 3x, risiko $10/trade, stop buka trade kalau total
kerugian sudah -$100. Harga live dari Binance US (publik, tanpa key).

Polling harga tiap 60 detik; sinyal crossover dicek tiap candle 1 jam tutup.
Tiap trade pura-pura dicatat ke trades.csv, ringkasan ke summary.json.

Jalankan di background:
    nohup python3 live.py > live.log 2>&1 &
Berhenti: Ctrl+C atau kill PID — ringkasan tetap tersimpan.
"""

import csv
import json
import os
import signal
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from common import (
    ASSETS, BANKROLL_START, EMA_FAST, EMA_SLOW, LEVERAGE,
    MAX_TOTAL_LOSS_USD, RISK_PER_TRADE_USD,
    fees_usd, get_klines, get_prices, margin_required_usd,
    pnl_gross_usd, position_notional_usd, sl_price, tp_price,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TRADES_CSV = os.path.join(BASE_DIR, "trades.csv")
SUMMARY_JSON = os.path.join(BASE_DIR, "summary.json")
POLL_SECONDS = 60

FIELDNAMES = ["asset", "side", "entry", "sl", "tp", "notional", "margin",
              "leverage", "open_time", "exit", "exit_time", "reason",
              "pnl_usd", "status"]


def log(msg):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(os.path.join(BASE_DIR, "live.log"), "a") as f:
        f.write(line + "\n")


def load_state():
    """Pulihkan kas + posisi open dari file (kalau ada)."""
    cash = BANKROLL_START
    realized = 0.0
    positions = {}
    if os.path.exists(TRADES_CSV):
        with open(TRADES_CSV) as f:
            for row in csv.DictReader(f):
                if row["status"] == "closed":
                    realized += float(row["pnl_usd"])
                else:
                    positions[row["asset"]] = {
                        "asset": row["asset"], "side": row["side"],
                        "entry": float(row["entry"]), "sl": float(row["sl"]),
                        "tp": float(row["tp"]),
                        "notional": float(row["notional"]),
                        "margin": float(row["margin"]),
                        "leverage": int(row["leverage"]),
                        "open_time": int(row["open_time"]),
                    }
        cash = BANKROLL_START + realized
    return cash, realized, positions


def save_trades(all_trades):
    with open(TRADES_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        for t in all_trades:
            w.writerow({k: t.get(k, "") for k in FIELDNAMES})


def save_summary(cash, realized, positions, all_trades):
    closed = [t for t in all_trades if t["status"] == "closed"]
    wins = sum(1 for t in closed if float(t["pnl_usd"]) > 0)
    summary = {
        "modal_virtual_usd": BANKROLL_START,
        "kas_virtual_usd": round(cash, 2),
        "total_pnl_virtual_usd": round(realized, 2),
        "total_trade_selesai": len(closed),
        "menang": wins,
        "kalah": len(closed) - wins,
        "win_rate_pct": round(100 * wins / len(closed), 1) if closed else 0.0,
        "posisi_open": len(positions),
        "open": {a: {"side": p["side"], "entry": p["entry"],
                     "sl": p["sl"], "tp": p["tp"]}
                 for a, p in positions.items()},
        "aturan_max_loss_100_tercapai": bool(realized <= -MAX_TOTAL_LOSS_USD),
        "diperbarui": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    }
    with open(SUMMARY_JSON, "w") as f:
        json.dump(summary, f, indent=2)
    return summary


def last_closed_candle(symbol):
    """Candle 1 jam terakhir yang SUDAH tutup + EMA di titik itu."""
    df = pd.DataFrame(get_klines(symbol, limit=100))
    df["ema_fast"] = df["close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=EMA_SLOW, adjust=False).mean()
    closed = df.iloc[:-1]  # candle terakhir masih jalan, belum tutup
    last = closed.iloc[-1]
    prev = closed.iloc[-2]
    crossed_up = prev["ema_fast"] <= prev["ema_slow"] and last["ema_fast"] > last["ema_slow"]
    crossed_down = prev["ema_fast"] >= prev["ema_slow"] and last["ema_fast"] < last["ema_slow"]
    return int(last["open_time"]), crossed_up, crossed_down


def main():
    cash, realized, positions = load_state()
    all_trades = []
    if os.path.exists(TRADES_CSV):
        with open(TRADES_CSV) as f:
            all_trades = list(csv.DictReader(f))

    log(f"MULAI forward test live — modal virtual ${BANKROLL_START}, "
        f"trade ${RISK_PER_TRADE_USD}, leverage {LEVERAGE}x, "
        f"kas ${cash:.2f}, posisi open {len(positions)}")
    log("Aturan: EMA 12/26 crossover 1h; SL 1,5%; TP 3%; stop buka trade "
        "kalau total rugi -$100.")

    # candle tutup terakhir per aset (buat deteksi candle baru)
    last_candle = {}
    for symbol in ASSETS:
        try:
            t, _, _ = last_closed_candle(symbol)
            last_candle[symbol] = t
        except Exception as e:
            log(f"  GAGAL ambil candle awal {symbol}: {e}")
            last_candle[symbol] = 0

    running = True

    def stop(signum, frame):
        nonlocal running
        log("Dihentikan. Menyimpan ringkasan...")
        running = False

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    while running:
        try:
            prices = get_prices(ASSETS)
        except Exception as e:
            log(f"  GAGAL ambil harga: {e}")
            time.sleep(POLL_SECONDS)
            continue

        # --- 1. cek SL / TP posisi open pada harga live ---
        for asset in list(positions):
            if asset not in prices:
                continue
            pos = positions[asset]
            price = prices[asset]
            hit_sl = hit_tp = False
            if pos["side"] == "long":
                hit_sl = price <= pos["sl"]
                hit_tp = price >= pos["tp"]
            else:
                hit_sl = price >= pos["sl"]
                hit_tp = price <= pos["tp"]
            if hit_sl or hit_tp:
                exit_price = pos["sl"] if hit_sl else pos["tp"]
                reason = "SL" if hit_sl else "TP"
                gross = pnl_gross_usd(pos["side"], pos["entry"], exit_price,
                                      pos["notional"])
                pnl = gross - fees_usd(pos["notional"])
                cash += pnl
                realized += pnl
                for t in all_trades:
                    if t["asset"] == asset and t["status"] == "open":
                        t.update({"exit": exit_price,
                                  "exit_time": int(time.time() * 1000),
                                  "reason": reason,
                                  "pnl_usd": round(pnl, 2),
                                  "status": "closed"})
                del positions[asset]
                save_trades(all_trades)
                log(f"  TUTUP {asset} {pos['side']} @{exit_price:.2f} ({reason}) "
                    f"pnl ${pnl:+.2f} (kas ${cash:.2f})")

        # --- 2. cek candle baru: sinyal crossover ---
        for symbol in ASSETS:
            try:
                t, crossed_up, crossed_down = last_closed_candle(symbol)
            except Exception as e:
                log(f"  GAGAL cek candle {symbol}: {e}")
                continue
            if t == last_candle.get(symbol):
                continue  # belum ada candle baru
            last_candle[symbol] = t
            price = prices.get(symbol)
            if price is None:
                continue

            pos = positions.get(symbol)
            if pos is not None and ((pos["side"] == "long" and crossed_down)
                                    or (pos["side"] == "short" and crossed_up)):
                gross = pnl_gross_usd(pos["side"], pos["entry"], price,
                                      pos["notional"])
                pnl = gross - fees_usd(pos["notional"])
                cash += pnl
                realized += pnl
                for tr in all_trades:
                    if tr["asset"] == symbol and tr["status"] == "open":
                        tr.update({"exit": price,
                                   "exit_time": int(time.time() * 1000),
                                   "reason": "reverse",
                                   "pnl_usd": round(pnl, 2),
                                   "status": "closed"})
                del positions[symbol]
                save_trades(all_trades)
                log(f"  TUTUP {symbol} {pos['side']} @{price:.2f} (reverse) "
                    f"pnl ${pnl:+.2f} (kas ${cash:.2f})")
                pos = None

            if symbol not in positions and (crossed_up or crossed_down):
                if realized <= -MAX_TOTAL_LOSS_USD:
                    log(f"  SKIP {symbol}: total rugi sudah -${abs(realized):.2f} "
                        "(aturan max -$100)")
                    continue
                margin = margin_required_usd()
                reserved = sum(p["margin"] for p in positions.values())
                if cash - reserved < margin:
                    log(f"  SKIP {symbol}: kas bebas ${cash - reserved:.2f} "
                        f"< margin ${margin:.2f}")
                    continue
                side = "long" if crossed_up else "short"
                entry = price
                new_pos = {
                    "asset": symbol, "side": side, "entry": entry,
                    "sl": sl_price(side, entry), "tp": tp_price(side, entry),
                    "notional": position_notional_usd(), "margin": margin,
                    "leverage": LEVERAGE,
                    "open_time": int(time.time() * 1000),
                }
                positions[symbol] = new_pos
                all_trades.append({**new_pos, "exit": "", "exit_time": "",
                                   "reason": "", "pnl_usd": "", "status": "open"})
                save_trades(all_trades)
                log(f"  BUKA {symbol} {side} @{entry:.2f} "
                    f"SL {new_pos['sl']:.2f} TP {new_pos['tp']:.2f} "
                    f"(margin ${margin:.2f})")

        save_summary(cash, realized, positions, all_trades)
        time.sleep(POLL_SECONDS)

    save_summary(cash, realized, positions, all_trades)
    log("SELESAI. Ringkasan: " + json.dumps(
        {"kas": round(cash, 2), "pnl": round(realized, 2),
         "posisi_open": len(positions)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
