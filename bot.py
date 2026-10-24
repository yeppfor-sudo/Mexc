from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_4h_strict.json"


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

  # Prune alerts older than 4 days
  alerted = {
      k: v
      for k, v in alerted.items()
      if datetime.fromisoformat(v) > now - timedelta(days=4)
  }

  TF = "4h"
  print(f"🔍 Scanning {len(syms)} pairs on Timeframe: {TF} (Strict Mode)...")
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_{TF}"
      if key in alerted:
        continue

      ohlcv = exchange.fetch_ohlcv(sym, TF, limit=100)
      if len(ohlcv) < 80:
        continue

      df = pd.DataFrame(ohlcv, columns=["t", "o", "h", "l", "c", "v"])
      df = df.iloc[:-1]  # Drop active candle
      close, open_, volume = df["c"], df["o"], df["v"]
      c = close.iloc[-1]

      # EMAs matching your charts (6, 12, 20)
      ema6 = close.ewm(span=6).mean()
      ema12 = close.ewm(span=12).mean()
      ema20 = close.ewm(span=20).mean()

      e6, e12, e20 = ema6.iloc[-1], ema12.iloc[-1], ema20.iloc[-1]

      # 1. Base / Downtrend validation (Extended sideways/downward base before breakout)
      base_check = (ema6.iloc[-45:-15] < ema12.iloc[-45:-15]).mean()
      if base_check < 0.60:
        continue

      # 2. CHOCH Level (Major swing high of the base structure)
      last_LH = df.iloc[-60:-12]["h"].max()

      # 3. CHOCH Break Check (Must have broken above last LH recently)
      broke = False
      break_idx = -1
      for i in range(-15, -1):
        if close.iloc[i] > last_LH:
          broke = True
          break_idx = i
          break
      if not broke:
        continue

      # 4. Zone A Retest Validation: Price pulled back to test the EMA support / breakout level
      # Current price must be near the EMA cluster (Zone A)
      ema_cluster_min = min(e6, e12, e20)
      ema_cluster_max = max(e6, e12, e20)

      # Price should be testing around Zone A (near EMAs or breakout level)
      retest_dist_ema = abs(c - ema_cluster_min) / ema_cluster_min * 100
      if retest_dist_ema > 3.5:  # Must be tightly hugging the EMAs at Zone A
        continue

      # 5. Volume Confirmation (Crucial for filtering fake charts)
      # Current or recent breakout volume must be significantly higher than average base volume
      avg_vol = volume.iloc[-30:-5].mean()
      current_vol = volume.iloc[-1]
      if (
          current_vol < avg_vol * 1.8
      ):  # Requires notable volume increase like your charts
        continue

      # 6. Bullish Confirmation Candle at Zone A
      if not (e6 > e12 > e20):
        continue  # EMAs must be bullishly aligned
      if not (close.iloc[-1] > open_.iloc[-1]):
        continue  # Must be a green reaction candle

      coin = sym.replace("/USDT:USDT", "")

      msg = (
          f"🚨 **4H CHOCH + ZONE A RETEST [VERIFIED]** 🚨\n\n"
          f"🪙 **Coin:** `{coin}`\n"
          f"💲 **Price:** `{c:.5f}`\n"
          f"📐 **CHOCH Level:** `{last_LH:.5f}`\n"
          f"🟢 **Zone A:** Retesting EMA Support Cluster\n"
          f"📊 **Volume Surge Confirmed!**\n"
          f"⚡ *Ready for potential vertical pump!*"
      )

      send_telegram(msg)
      print(f"✅ Verified alert sent for {coin} at price {c}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 Strict scan complete. Total verified alerts sent: {alert_count}")


if __name__ == "__main__":
  run_scanner()
