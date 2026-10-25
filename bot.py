from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_sl_tp_cooldown.json"


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
      "🚀 Starting MEXC Scanner (Downtrend -> CHOCH -> EMA 20 Retest + SL/TP/RR)"
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
      key = f"{sym}_sl_tp_retest"
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

      # Resistance level (1h CHOCH Swing High)
      resistance_level = df_1h.iloc[-50:-10]["h"].max()

      breakout_found = False
      for i in range(-8, -1):
        if (
            high_1h.iloc[i] > resistance_level
            and close_1h.iloc[i] > open_1h.iloc[i]
            and volume_1h.iloc[i] > volume_1h.iloc[i - 20 : i].mean() * 1.5
        ):
          breakout_found = True
          break
      if not breakout_found:
        continue

      # -------------------------------------------------------------
      # RULE 3: Lower TF (15m) Retest & EMA 20 Support Hold Check
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
      low_low = df_lower["l"]

      ema6_l = df_lower["c"].ewm(span=6).mean().iloc[-1]
      ema12_l = df_lower["c"].ewm(span=12).mean().iloc[-1]
      ema20_l = df_lower["c"].ewm(span=20).mean().iloc[-1]

      # Support level (Recent lower timeframe swing low)
      support_level = low_low.iloc[-15:].min()

      # Distance to EMA 20 support hold
      ema20_distance = abs(c_low - ema20_l) / ema20_l * 100
      if ema20_distance > 2.5:
        continue

      if not (ema6_l > ema12_l):
        continue

      # -------------------------------------------------------------
      # RULE 4: Not a Big Pump Yet Check
      # -------------------------------------------------------------
      recent_max_gain = (
          (high_low.iloc[-10:].max() - ema20_l) / ema20_l * 100
      )
      if recent_max_gain > 5.0:
        continue

      # -------------------------------------------------------------
      # TRADE MANAGEMENT: SL, TP, and R:R Calculation
      # -------------------------------------------------------------
      entry_price = c_low

      # Stop Loss placed slightly below the recent support / swing low
      stop_loss = min(support_level * 0.99, ema20_l * 0.985)
      if stop_loss >= entry_price:
        stop_loss = entry_price * 0.97  # Fallback safety buffer

      risk = entry_price - stop_loss

      # Target set aiming towards resistance or targeting a 1:2.5 minimum R:R
      target_price = max(resistance_level, entry_price + (risk * 2.5))

      reward = target_price - entry_price
      rr_ratio = reward / risk if risk > 0 else 0.0

      coin = sym.replace("/USDT:USDT", "")

      # Telegram Alert Message with SL, TP, and R:R
      msg = (
          f"🚨 **LONG SETUP: CHOCH + EMA 20 RETEST** 🚨\n\n"
          f"🪙 **Coin:** `{coin}`\n"
          f"📉 **1D Trend:** Downtrend Base Verified\n"
          f"⚡ **1h Trend:** CHOCH Breakout Confirmed\n"
          f"🎯 **Lower TF (15m):** Holding EMA 20 Support\n\n"
          f"📊 **Levels & Risk Management:**\n"
          f"💲 **Entry Price:** `{entry_price:.5f}`\n"
          f"🛡️ **Support (S):** `{support_level:.5f}`\n"
          f"🚀 **Resistance (R):** `{resistance_level:.5f}`\n"
          f"🛑 **Stop Loss (SL):** `{stop_loss:.5f}`\n"
          f"🎯 **Target (TP):** `{target_price:.5f}`\n"
          f"⚖️ **Risk-to-Reward (R:R):** `1:{rr_ratio:.2f}`\n\n"
          f"💡 *Pre-pump retest zone detected!* (24h Cooldown Active)"
      )

      send_telegram(msg)
      print(f"✅ Alert sent for {coin} | Entry: {entry_price} | R:R 1:{rr_ratio:.2f}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 Scan complete. Total alerts sent: {alert_count}")


if __name__ == "__main__":
  run_scanner()
