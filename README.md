# Paper Trading Futures Kripto — UANG VIRTUAL SAJA

Latihan trading futures BTC/ETH/SOL dengan modal virtual $1.000, untuk
membuktikan dulu di virtual apakah aturannya bisa untung — sebelum mizan
bicara uang real. **Tidak ada uang asli, tidak ada API key, tidak ada order
ke exchange mana pun.** Harga hanya dibaca dari API publik Binance US
(tanpa key).

## Aturan mizan (dipakai apa adanya)

| Aturan | Nilai |
|---|---|
| Modal virtual | $1.000 |
| Aset | BTCUSDT, ETHUSDT, SOLUSDT |
| Leverage | 3x tetap (maks yang diizinkan 3–5x) |
| Stop-loss | SELALU nyala, 1,5% dari harga entry |
| Take-profit | 3% (risk:reward 1:2) |
| Risiko per trade | $10 → notional $666,67, margin $222,22 |
| Total kerugian maks | -$100, lalu berhenti buka trade baru |
| Fee | taker 0,05% per sisi (masuk + keluar) |

## Strategi (trend-following, EMA crossover)

- Timeframe 1 jam, EMA 12 vs EMA 26 pada candle yang SUDAH tutup.
- EMA12 motong ke atas EMA26 → LONG. Motong ke bawah → SHORT.
- Entry di harga penutupan candle sinyal (backtest) / harga live saat
  candle tutup (forward test). Maks 1 posisi per aset.
- Posisi ditutup kalau: kena SL, kena TP, atau EMA berbalik arah
  (alasan "reverse").
- Kalau SL dan TP sama-sama kesenggol dalam satu candle, SL dihitung
  duluan (aturan konservatif).

## Cara jalanin

```bash
cd ~/workspace/paper-trading-futures
python3 backtest.py          # backtest 30 hari terakhir, timeframe 1h
nohup python3 live.py > live-out.log 2>&1 &   # forward test live di background
```

`live.py` polling harga tiap 60 detik, cek SL/TP pada harga live, dan
cek sinyal tiap ada candle 1 jam yang baru tutup. Berhenti kapan saja
dengan kill PID — ringkasan tetap tersimpan, dan proses bisa dinyalakan
lagi (state pulih dari `trades.csv` / `summary.json`).

## Hasil backtest — 30 hari terakhir, timeframe 1h

Data: Binance US, 22 Okt – 21 Nov 2026 (720 candle per aset).

| | |
|---|---|
| Total trade virtual | **56** |
| Menang / kalah | **18 / 38** |
| Win rate | **32,1%** |
| Total PnL virtual | **-$26,11** (modal $1.000 → kas $973,89) |
| Rata-rata menang | +$15,40 |
| Rata-rata kalah | -$7,99 |
| Max drawdown | $123,33 (peak-to-trough, lihat batasan) |
| Aturan max loss -$100 | TIDAK tercapai (total rugi hanya -$26,11) |

Per aset: BTC 25 trade, PnL -$7,46 · ETH 15 trade, PnL -$39,74 ·
SOL 16 trade, PnL +$21,10.

**Baca jujur:** strategi ini RUGI di 30 hari terakhir — kecil (-2,6%),
tapi rugi. Win rate 32% tidak cukup menutup kerugian karena rata-rata
menang (+$15,40) hanya ~2x rata-rata kalah (-$7,99) sementara yang
menang cuma 1 dari 3 trade. Ini BUKAN bukti strategi ini selalu rugi
(56 trade itu sampel kecil, dan 30 hari terakhir mungkin sedang
sideways/choppy sehingga trend-following kena whipsaw), tapi juga BUKAN
bukti strategi ini untung. Jangan pakai uang asli berdasarkan ini.
Forward test live akan memberi bukti lebih banyak.

## Forward test live

- Mulai: **21 Nov 2026 11:54 WIB**, status: JALAN di background
  (PID tercatat saat start; cek dengan `pgrep -af live.py`).
- Saat laporan ini ditulis: 0 trade, kas $1.000, 0 posisi open
  (sinyal baru muncul kalau ada candle 1 jam yang tutup dengan
  crossover — tidak setiap menit ada trade).
- File: `trades.csv` (tiap trade pura-pura), `summary.json` (ringkasan
  berjalan), `live.log` (log jalan).

## File-file

| File | Isi |
|---|---|
| `common.py` | Aturan mizan + ambil data publik Binance US + hitung PnL/SL/TP |
| `backtest.py` | Backtest 30 hari → `backtest_trades.csv`, `backtest_summary.json` |
| `live.py` | Forward test live → `trades.csv`, `summary.json`, `live.log` |
| `backtest_trades.csv` | 56 trade backtest |
| `backtest_summary.json` | Ringkasan backtest |
| `trades.csv` / `summary.json` | Hasil forward test live (berjalan) |

## Batasan jujur — baca ini dulu

1. **Harga spot dipakai sebagai proxy harga futures.** Binance US
   tidak punya futures, dan Binance.com diblokir dari VM ini (HTTP 451).
   Funding rate futures TIDAK disimulasikan.
2. **Tidak ada slippage.** Order diasumsikan terisi penuh persis di
   harga sinyal / SL / TP. Di market beneran, harga eksekusi bisa lebih
   buruk.
3. **Backtest cek SL/TP pakai high/low candle 1 jam.** Urutan sentuhan
   di dalam satu candle tidak diketahui — diasumsikan SL dulu kalau
   keduanya kesenggol.
4. **Drawdown $123,33 melebihi batas -$100** dalam hitungan
   peak-to-trough, karena aturan stop -$100 dihitung dari total kerugian
   terealisasi (yang tidak pernah sampai -$100). Drawdown sementara
   bisa lebih dalam dari batas itu.
5. **Sampel kecil.** 30 hari / 56 trade bukan bukti kuat ke arah mana
   pun. Forward test berhari-hari memberi bukti lebih banyak.
6. **Proses background mati kalau VM restart.** State pulih otomatis
   dari file saat dinyalakan lagi, tapi ada jeda sampai ada yang
   menyalakannya.
7. **Kenapa tidak pakai freqtrade:** freqtrade sudah terpasang
   (`~/workspace/freqtrade/`) tapi konfigurasinya spot di Binance US,
   dan futures-nya butuh exchange ber-futures (Binance.com diblokir
   dari VM ini). Jadi sim kecil ini yang dipakai.
8. **Sim Polymarket tidak disentuh** — itu sim terpisah, masih jalan
   sendiri di `~/workspace/polymarket-sim/`.
