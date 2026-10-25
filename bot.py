from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_ema20_cooldown.json"


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
  print(
      "🚀 Starting MEXC Scanner (1D Downtrend -> 1h CHOCH -> EMA 20 Retest Hold)"
      "..."
  )
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

  # Rule: Only alert a pair once in 24h
  alerted = {
      k: v
      for k, v in alerted.items()
      if datetime.fromisoformat(v) > now - timedelta(hours=24)
  }

  print(f"🔍 Scanning {len(syms)} pairs...")
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_ema20_retest"
      if key in alerted:
        continue  # Skip if already alerted in the last 24 hours

      # -------------------------------------------------------------
      # RULE 1: 1D (Daily) Timeframe Downtrend Check
      # -------------------------------------------------------------
      ohlcv_1d = exchange.fetch_ohlcv(sym, "1d", limit=50)
      if len(ohlcv_1d) < 30:
        continue

      df_1d = pd.DataFrame(ohlcv_1d, columns=["t", "o", "h", "l", "c", "v"])
      df_1d = df_1d.iloc[:-1]
      ema20_1d = df_1d["c"].ewm(span=20).mean()
      ema50_1d = df_1d["c"].ewm(span=50).mean()

      # Macro downtrend structure
      if (ema20_1d.iloc[-25:-5] < ema50_1d.iloc[-25:-5]).mean() < 0.45:
        continue

      # -------------------------------------------------------------
      # RULE 2: 1h Timeframe CHOCH Breakout Check
      # -------------------------------------------------------------
      ohlcv_1h = exchange.fetch_ohlcv(sym, "1h", limit=100)
      if len(ohlcv_1h) < 60:
        continue

      df_1h = pd.DataFrame(ohlcv_1h, columns=["t", "o", "h", "l", "c", "v"])
      df_1h = df_1h.iloc[:-1]
      close_1h, high_1h, open_1h, volume_1h = (
          df_1h["c"],
          df_1h["h"],
          df_1h["o"],
          df_1h["v"],
      )

      # Swing high for 1h CHOCH level
      last_LH = df_1h.iloc[-50:-10]["h"].max()

      breakout_found = False
      for i in range(-8, -1):
        if (
            high_1h.iloc[i] > last_LH
            and close_1h.iloc[i] > open_1h.iloc[i]
            and volume_1h.iloc[i] > volume_1h.iloc[i - 20 : i].mean() * 1.5
        ):
          breakout_found = True
          break
      if not breakout_found:
        continue

      # -------------------------------------------------------------
      # RULE 3: Lower TF (15m/30m) Retest & EMA 20 Support Hold Check
      # -------------------------------------------------------------
      ohlcv_lower = exchange.fetch_ohlcv(sym, "15m", limit=50)
      if len(ohlcv_lower) < 40:
        continue

      df_lower = pd.DataFrame(
          ohlcv_lower, columns=["t", "o", "h", "l", "c", "v"]
      )
      df_lower = df_lower.iloc[:-1]

      c_low = df_lower["c"].iloc[-1]
      high_low = df_lower["h"]
      
      # Calculate standard MEXC EMAs (6, 12, 20) on lower timeframe
      ema6_l = df_lower["c"].ewm(span=6).mean().iloc[-1]
      ema12_l = df_lower["c"].ewm(span=12).mean().iloc[-1]
      ema20_l = df_lower["c"].ewm(span=20).mean().iloc[-1]

      # Price must be holding tightly right around the EMA 20 support line
      ema20_distance = abs(c_low - ema20_l) / ema20_l * 100
      if ema20_distance > 2.5:
        continue  # Price is too far from EMA 20 support

      # Short-term bullish indicator alignment (EMA 6 > EMA 12 over EMA 20)
      if not (ema6_l > ema12_l):
        continue

      # -------------------------------------------------------------
      # RULE 4: Not a Big Pump Yet Check
      # -------------------------------------------------------------
      recent_max_gain = (
          (high_low.iloc[-10:].max() - ema20_l) / ema20_l * 100
      )
      if recent_max_gain > 5.0:
        continue  # Avoid chasing if already pumped > 5%

      coin = sym.replace("/USDT:USDT", "")

      # Telegram Alert Message
      msg = (
          f"🚨 **LONG SETUP: 1H CHOCH + EMA 20 RETEST** 🚨\n\n"
          f"🪙 **Coin:** `{coin}`\n"
          f"📉 **1D Trend:** Downtrend Base Verified\n"
          f"⚡ **1h Trend:** CHOCH Breakout Confirmed\n"
          f"🎯 **Lower TF (15m):** Holding EMA 20 Support (No Big Pump Yet!)\n"
          f"💲 **Current Price:** `{c_low:.5f}`\n"
          f"📊 **EMA 20 Level:** `{ema20_l:.5f}`\n\n"
          f"💡 *Ready for Long entry setup!* (24h Cooldown Active)"
      )

      send_telegram(msg)
      print(f"✅ Alert sent for {coin} at price {c_low} resting on EMA 20")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 Scan complete. Total alerts sent: {alert_count}")


if __name__ == "__main__":
  run_scanner()
