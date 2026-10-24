from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_strict_retest.json"


def send_telegram(msg):
  if not TOKEN or not CHAT:
    print("❌ Telegram TOKEN ਜਾਂ CHAT_ID ਨਹੀਂ ਮਿਲਿਆ।")
    return
  try:
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {"chat_id": CHAT, "text": msg, "parse_mode": "Markdown"}
    requests.post(url, json=payload, timeout=10)
  except Exception as e:
    print(f"❌ Telegram ਭੇਜਣ ਵਿੱਚ ਗਲਤੀ: {e}")


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
  print("🚀 MEXC ਐਕਸਚੇਂਜ ਪ੍ਰੀਮੀਅਮ ਸਕੈਨਿੰਗ ਸ਼ੁਰੂ ਹੋ ਗਈ ਹੈ...")
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

  # ਪੁਰਾਣੇ ਅਲਰਟ 4 ਦਿਨਾਂ ਬਾਅਦ ਕਲੀਅਰ ਕਰੋ
  alerted = {
      k: v
      for k, v in alerted.items()
      if datetime.fromisoformat(v) > now - timedelta(days=4)
  }

  print(
      f"🔍 {len(syms)} ਕੋਇਨਾਂ ਦਾ [1D Downtrend -> 4H CHOCH -> Lower TF Hold -> No"
      " Pump Yet] ਸਕੈਨ ਚੱਲ ਰਿਹਾ ਹੈ..."
  )
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_strict"
      if key in alerted:
        continue

      # -------------------------------------------------------------
      # 1. 1D (Daily) Timeframe Downtrend Check
      # -------------------------------------------------------------
      ohlcv_1d = exchange.fetch_ohlcv(sym, "1d", limit=60)
      if len(ohlcv_1d) < 30:
        continue

      df_1d = pd.DataFrame(ohlcv_1d, columns=["t", "o", "h", "l", "c", "v"])
      df_1d = df_1d.iloc[:-1]
      ema6_1d = df_1d["c"].ewm(span=6).mean()
      ema12_1d = df_1d["c"].ewm(span=12).mean()

      if (ema6_1d.iloc[-30:-5] < ema12_1d.iloc[-30:-5]).mean() < 0.45:
        continue  # 1D ਡਾਊਨਟਰੈਂਡ ਵਿੱਚ ਹੋਣਾ ਚਾਹੀਦਾ ਹੈ

      # -------------------------------------------------------------
      # 2. 4H Timeframe CHOCH Breakout Check
      # -------------------------------------------------------------
      ohlcv_4h = exchange.fetch_ohlcv(sym, "4h", limit=100)
      if len(ohlcv_4h) < 70:
        continue

      df_4h = pd.DataFrame(ohlcv_4h, columns=["t", "o", "h", "l", "c", "v"])
      df_4h = df_4h.iloc[:-1]
      close_4h, high_4h, open_4h, volume_4h = (
          df_4h["c"],
          df_4h["h"],
          df_4h["o"],
          df_4h["v"],
      )

      last_LH = df_4h.iloc[-60:-15]["h"].max()

      breakout_found = False
      for i in range(-6, -1):
        if (
            high_4h.iloc[i] > last_LH
            and close_4h.iloc[i] > open_4h.iloc[i]
            and volume_4h.iloc[i] > volume_4h.iloc[i - 20 : i].mean() * 1.8
        ):
          breakout_found = True
          break
      if not breakout_found:
        continue

      # -------------------------------------------------------------
      # 3. Lower TF (30m / 1h) Retest & Support Hold Check (No Big Pump Yet)
      # -------------------------------------------------------------
      ohlcv_lower = exchange.fetch_ohlcv(
          sym, "30m", limit=50
      )  -- ਵੀ 1h ਜਾਂ 30m ਵਰਤ ਸਕਦੇ ਹਾਂ
      if len(ohlcv_lower) < 40:
        continue

      df_lower = pd.DataFrame(
          ohlcv_lower, columns=["t", "o", "h", "l", "c", "v"]
      )
      df_lower = df_lower.iloc[:-1]

      c_low = df_lower["c"].iloc[-1]
      high_low = df_lower["h"]
      ema6_l = df_lower["c"].ewm(span=6).mean().iloc[-1]
      ema12_l = df_lower["c"].ewm(span=12).mean().iloc[-1]
      ema20_l = df_lower["c"].ewm(span=20).mean().iloc[-1]

      ema_max_l = max(ema6_l, ema12_l, ema20_l)
      ema_min_l = min(ema6_l, ema12_l, ema20_l)

      # ਪ੍ਰਾਈਸ 30m/1h ਦੇ EMA ਕਲੱਸਟਰ ਦੇ ਬਹੁਤ ਕਰੀਬ ਹੋਣੀ ਚਾਹੀਦੀ ਹੈ (ਹੋਲਡ ਕਰਦੀ ਹੋਈ)
      retest_dist = abs(c_low - ema_max_l) / ema_max_l * 100
      if retest_dist > 2.5:
        continue  # ਰੀਟੈਸਟ ਜ਼ੋਨ ਵਿੱਚ ਨਹੀਂ ਹੈ

      # ਸ਼ਰਤ: "Not Big Pump Yet" -> ਪਿਛਲੀਆਂ ਕੁਝ ਕੈਂਡਲਾਂ ਵਿੱਚ ਪ੍ਰਾਈਸ EMA ਤੋਂ ਬਹੁਤ ਉੱਪਰ ਨਾ ਗਈ ਹੋਵੇ (ਕੋਈ ਵੱਡਾ ਪੰਪ ਨਾ ਆਇਆ ਹੋਵੇ)
      recent_max_gain = (
          (high_low.iloc[-8:].max() - ema_min_l) / ema_min_l * 100
      )
      if (
          recent_max_gain > 7.0
      ):  # ਜੇ 7% ਤੋਂ ਵੱਧ ਪੰਪ ਆ ਚੁੱਕਿਆ ਹੈ, ਤਾਂ ਅਲਰਟ ਨਾ ਭੇਜੋ
        continue

      coin = sym.replace("/USDT:USDT", "")

      # ਟੈਲੀਗ੍ਰਾਮ ਅਲਰਟ ਸੁਨੇਹਾ
      msg = (
          f"🚨 **PRE-PUMP RETEST ALERT (POINT C)** 🚨\n\n"
          f"🪙 **ਕੋਇਨ:** `{coin}`\n"
          f"📉 **1D Trend:** Downtrend Base Verified\n"
          f"⚡ **4H Trend:** CHOCH Breakout Confirmed\n"
          f"🎯 **Lower TF (30m):** Holding EMA Support (No Pump Yet!)\n"
          f"💲 **Current Price:** `{c_low:.5f}`\n\n"
          f"⚡ *ਪ੍ਰਾਈਸ ਬਿਲਕੁਲ ਐਂਟਰੀ ਜ਼ੋਨ 'ਤੇ ਹੈ, ਵੱਡੇ ਪੰਪ ਤੋਂ ਪਹਿਲਾਂ ਚੈੱਕ ਕਰੋ!*"
      )

      send_telegram(msg)
      print(f"✅ ਪਰਫੈਕਟ ਪ੍ਰੀ-ਪੰਪ ਅਲਰਟ ਭੇਜਿਆ ਗਿਆ: {coin}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 ਸਕੈਨ ਪੂਰਾ ਹੋਇਆ। ਕੁੱਲ ਅਲਰਟ: {alert_count}")


if __name__ == "__main__":
  run_scanner()
