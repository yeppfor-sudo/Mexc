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
STATE_FILE = "alerted_4h.json"


def send_telegram(msg):
  if not TOKEN or not CHAT:
    print("❌ Telegram TOKEN or CHAT_ID missing in environment variables.")
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
  print(f"🔍 Scanning {len(syms)} pairs on Timeframe: {TF}...")
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_{TF}"
      if key in alerted:
        continue

      # Fetch OHLCV data for 4h timeframe
      ohlcv = exchange.fetch_ohlcv(sym, TF, limit=100)
      if len(ohlcv) < 70:
        continue

      df = pd.DataFrame(ohlcv, columns=["t", "o", "h", "l", "c", "v"])
      df = df.iloc[
          :-1
      ]  # Drop the active/incomplete candle to avoid false triggers
      close, open_ = df["c"], df["o"]
      c = close.iloc[-1]

      # Calculate EMAs (Matching your chart: EMA 6, EMA 12, EMA 20)
      ema6 = close.ewm(span=6).mean()
      ema12 = close.ewm(span=12).mean()
      ema20 = close.ewm(span=20).mean()

      e6, e12, e20 = ema6.iloc[-1], ema12.iloc[-1], ema20.iloc[-1]
      pe6, pe12, pe20 = ema6.iloc[-2], ema12.iloc[-2], ema20.iloc[-2]

      # 1. Prior Downtrend Check: EMA6 was predominantly below EMA12 in the structural base
      downtrend_check = (
          ema6.iloc[-40:-10] < ema12.iloc[-40:-10]
      ).mean()
      if downtrend_check < 0.65:
        continue

      # 2. Find Last Lower High (CHOCH Level)
      last_LH = df.iloc[-55:-12]["h"].max()

      # 3. CHOCH Break Check: Price broke above last LH within recent candles
      broke = False
      for i in range(-12, -1):
        if close.iloc[i] > last_LH:
          broke = True
          break
      if not broke:
        continue

      # 4. Retest on Zone 'A': Checking if price pulled back near the breakout level or EMA support
      retest_dist = (c - last_LH) / last_LH * 100
      # Zone A retest tolerance: between -2% and +4% from the breakout/support line
      if retest_dist < -2.5 or retest_dist > 5.0:
        continue

      # 5. Bullish Confirmation & EMA Bullish Cross at Zone A
      if not (e6 > e12 > e20):
        continue
      if not (close.iloc[-1] > open_.iloc[-1]):
        continue  # Must be a green candle showing reaction off Zone A

      coin = sym.replace("/USDT:USDT", "")

      # Construct Alert Message
      msg = (
          f"🚨 **4H CHOCH + RETEST [ZONE A]** 🚨\n\n"
          f"🪙 **Coin:** `{coin}`\n"
          f"💲 **Current Price:** `{c:.5f}`\n"
          f"📐 **CHOCH Level:** `{last_LH:.5f}`\n"
          f"🎯 **Retest Distance:** `{retest_dist:+.2f}%`\n"
          f"📈 **Status:** EMA Bullish Alignment Confirmed at Zone A!\n"
          f"⚡ *Prepare for potential pump execution!*"
      )

      send_telegram(msg)
      print(f"✅ Alert sent for {coin} at price {c}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)  # Rate limit protection

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 Scan complete. Total alerts sent: {alert_count}")


if __name__ == "__main__":
  run_scanner()
