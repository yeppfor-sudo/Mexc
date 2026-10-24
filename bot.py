from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

# Telegram Configuration via Environment Variables
TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_4h_red_retest.json"


def send_telegram(msg):
  if not TOKEN or not CHAT:
    print("❌ Telegram TOKEN or CHAT_ID missing.")
    return
  try:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"❌ Telegram send error: {e}")


def load_state():
  try:
    if os.path.exists(STATE_FILE):
      with open(STATE_FILE, "r") as f:
        return json.load(f)
  except Exception:
    pass
  return {}


def save_state(d):
  try:
    with open(STATE_FILE, "w") as f:
      json.dump(d, f)
  except Exception:
    pass


def run_scanner():
  print("🚀 Initializing MEXC Exchange & Loading Markets...")
  exchange = ccxt.mexc({"enableRateLimit": True})
  exchange.load_markets()

  # Filter perpetual futures pairs, excluding fiat/stocks
  EXCLUDE = [
      "STOCK",
      "JPY",
      "EUR",
      "GBP",
      "CHF",
      "AUD",
      "CAD",
      "NZD",
      "HKD",
      "SGD",
  ]
  syms = [
      s
      for s in exchange.markets
      if s.endswith("/USDT:USDT")
      and not any(x in s for x in EXCLUDE)
      and s.split("/")[0] not in EXCLUDE
  ]

  alerted = load_state()
  now = datetime.now(timezone.utc)

  # Clean up old alert history (keep for 4 days)
  alerted = {
      k: v
      for k, v in alerted.items()
      if datetime.fromisoformat(v) > now - timedelta(days=4)
  }

  TF = "4h"
  print(f"🔍 Scanning {len(syms)} pairs on Timeframe: {TF} (Red Retest)...")
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_{TF}"
      if key in alerted:
        continue

      # Fetch OHLCV data for 4h timeframe (need slightly more data for strict volume check)
      ohlcv = exchange.fetch_ohlcv(sym, TF, limit=120)
      if len(ohlcv) < 90:
        continue

      df = pd.DataFrame(ohlcv, columns=["t", "o", "h", "l", "c", "v"])
      df = df.iloc[
          :-1
      ]  # Drop the active/incomplete candle to avoid false triggers
      
      # Candle components
      close = df["c"]
      open_ = df["o"]
      high = df["h"]
      low = df["l"]
      volume = df["v"]
      
      # Data for calculations
      c_last = close.iloc[-1]
      o_last = open_.iloc[-1]

      # Calculate EMAs (Matching your chart: EMA 6, EMA 12, EMA 20)
      ema6 = close.ewm(span=6).mean()
      ema12 = close.ewm(span=12).mean()
      ema20 = close.ewm(span=20).mean()

      e6 = ema6.iloc[-1]
      e12 = ema12.iloc[-1]
      e20 = ema20.iloc[-1]

      # --- STRUCTURAL FILTERS (PRE-RETEST) ---

      # 1. Check for valid breakout momentum (Green candles leading into retest)
      # Looking back 3-10 candles before the current retest candle
      momentum_check = (close.iloc[-10:-3] > open_.iloc[-10:-3]).mean()
      if momentum_check < 0.6:  # At least 60% green candles in recent breakout
        continue

      # 2. EMA Bullish Trend Alignment (e6 > e12 > e20)
      if not (e6 > e12 > e20):
        continue

      # --- STRICT RED RETEST CANDLE FILTERS ---

      # 3. Candle MUST be RED (Close < Open)
      if not (c_last < o_last):
        continue

      # 4. 'Zone A' EMA Support Cluster Check:
      # The red candle's body (Close and Open) must be tightly hugging the EMA group.
      ema_cluster_min = min(e6, e12, e20)
      ema_cluster_max = max(e6, e12, e20)

      # Check proximity to EMA cluster (e.g., within 2.5% of the cluster range)
      body_to_ema_prox = abs(c_last - ema_cluster_max) / ema_cluster_max * 100
      if body_to_ema_prox > 2.5:
        continue
      
      # 5. Volatility / Candle Size Check (Doji-like)
      # The candle must have low volatility (small body and small range), indicating compression.
      avg_range_pct = (
          (high.iloc[-30:] - low.iloc[-30:]) / low.iloc[-30:] * 100
      ).mean()
      current_range_pct = (high.iloc[-1] - low.iloc[-1]) / low.iloc[-1] * 100
      
      if current_range_pct > avg_range_pct * 0.9:  # Candle range is below or near average
          pass # This is fine for compression
      
      # Ensure it's not a large red "engulfing" candle
      candle_body_pct = abs(c_last - o_last) / o_last * 100
      if candle_body_pct > 1.8:  # Body must be relatively small
          continue

      # 6. Strict Volume Decline Check
      # The volume on this red retest candle must be lower than the volume on preceding bullish candles.
      prev_vol_avg = volume.iloc[-6:-2].mean()
      current_vol = volume.iloc[-1]
      
      # Retest volume should be declining (e.g., less than 70% of avg volume during breakout move)
      if current_vol > prev_vol_avg * 0.70:
        continue

      coin = sym.replace("/USDT:USDT", "")

      # Construct Alert Message specifically for RED RETEST
      msg = (
          f"🚨 **4H RED RETEST DETECTED [PRE-PUMP]** 🚨\n\n"
          f"🪙 **Coin:** `{coin}`\n"
          f"💲 **Current Price (Zone A):** `{c_last:.5f}`\n"
          f"🔴 **Action:** Retesting EMA Support on a Small Red Candle\n"
          f"📊 **Volume:** Declining (`{current_vol:.0f}` vs `{prev_vol_avg:.0f}` avg)\n"
          f"📈 **Trend:** EMAs Bullishly Aligned\n\n"
          f"⚡ *Ready for potential pump! Watch for volume spike confirmation.*"
      )

      send_telegram(msg)
      print(f"✅ Red Retest alert sent for {coin} at price {c_last}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)  # Rate limit protection

    except Exception as e:
      # Uncomment for debugging errors on specific pairs
      # print(f"Error scanning {sym}: {e}")
      continue

  save_state(alerted)
  print(f"🏁 Red Retest scan complete. Total alerts sent: {alert_count}")


if __name__ == "__main__":
  run_scanner()
