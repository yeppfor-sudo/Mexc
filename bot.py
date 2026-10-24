from datetime import datetime, timedelta, timezone
import json
import os
import time
import ccxt
import pandas as pd
import requests

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
STATE_FILE = "alerted_4h_perfect_retest.json"


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
  print("🚀 MEXC ਐਕਸਚੇਂਜ ਸਕੈਨਿੰਗ ਸ਼ੁਰੂ ਹੋ ਗਈ ਹੈ...")
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

  TF = "4h"
  print(
      f"🔍 {len(syms)} ਕੋਇਨਾਂ ਦਾ 4 ਘੰਟੇ (4h) ਟਾਈਮਫ੍ਰੇਮ ਸਕੈਨ ਕੀਤਾ ਜਾ ਰਿਹਾ ਹੈ..."
  )
  alert_count = 0

  for sym in syms:
    try:
      key = f"{sym}_{TF}"
      if key in alerted:
        continue

      ohlcv = exchange.fetch_ohlcv(sym, TF, limit=120)
      if len(ohlcv) < 90:
        continue

      df = pd.DataFrame(ohlcv, columns=["t", "o", "h", "l", "c", "v"])
      df = df.iloc[:-1]  # ਮੌਜੂਦਾ ਚੱਲ ਰਹੀ ਕੈਂਡਲ ਛੱਡੋ

      close, open_, high, low, volume = (
          df["c"],
          df["o"],
          df["h"],
          df["l"],
          df["v"],
      )

      # EMA ਕੈਲਕੁਲੇਸ਼ਨ (6, 12, 20)
      ema6 = close.ewm(span=6).mean()
      ema12 = close.ewm(span=12).mean()
      ema20 = close.ewm(span=20).mean()

      e6, e12, e20 = ema6.iloc[-1], ema12.iloc[-1], ema20.iloc[-1]

      # 1. ਪਿਛਲਾ ਬੇਸ/ਡਾਊਨਟਰੈਂਡ ਚੈੱਕ
      base_check = (ema6.iloc[-50:-15] < ema12.iloc[-50:-15]).mean()
      if base_check < 0.50:
        continue

      # 2. CHOCH ਲੈਵਲ (ਸਵਿੰਗ ਹਾਈ)
      last_LH = df.iloc[-65:-15]["h"].max()

      # 3. ਵਾਲਿਊਮ ਸਪਾਈਕ ਨਾਲ CHOCH ਬ੍ਰੇਕਆਉਟ
      breakout_found = False
      breakout_idx = -1

      for i in range(-6, -1):
        h_i, c_i, o_i, v_i = (
            high.iloc[i],
            close.iloc[i],
            open_.iloc[i],
            volume.iloc[i],
        )
        avg_v = volume.iloc[i - 25 : i].mean()

        if h_i > last_LH and c_i > o_i and v_i > avg_v * 1.8:
          breakout_found = True
          breakout_idx = i
          break

      if not breakout_found:
        continue

      # 4. Zone A / Point C 'ਤੇ ਰੀਟੈਸਟ ਚੈੱਕ (ਰੈੱਡ ਕੈਂਡਲ ਅਤੇ ਘੱਟ ਵਾਲਿਊਮ)
      c_last = close.iloc[-1]
      ema_max = max(e6, e12, e20)

      retest_dist = abs(c_last - ema_max) / ema_max * 100
      if retest_dist > 3.2:
        continue

      breakout_vol = volume.iloc[breakout_idx]
      current_vol = volume.iloc[-1]
      if current_vol > breakout_vol * 0.70:
        continue

      if not (e6 > e12 > e20):
        continue

      coin = sym.replace("/USDT:USDT", "")

      # ਟੈਲੀਗ੍ਰਾਮ ਮੈਸੇਜ
      msg = (
          f"🚨 **4H CHOCH + ZONE A (POINT C) RETEST** 🚨\n\n"
          f"🪙 **ਕੋਇਨ:** `{coin}`\n"
          f"💲 **ಪ್ರਾਈਸ (Zone A):** `{c_last:.5f}`\n"
          f"📐 **CHOCH ਲੈਵਲ:** `{last_LH:.5f}`\n"
          f"📊 **ਪੈਟਰਨ:** ਬ੍ਰੇਕਆਉਟ ਤੋਂ ਬਾਅਦ ਰੀਟੈਸਟ/ਹੋਲਡ (Point C)!\n"
          f"⚡ *ਵੱਡੇ ਪੰਪ ਤੋਂ ਪਹਿਲਾਂ ਦੀ ਸਹੀ ਐਂਟਰੀ ਜ਼ੋਨ!*"
      )

      send_telegram(msg)
      print(f"✅ ਅਲਰਟ ਭੇਜਿਆ ਗਿਆ: {coin} ਪ੍ਰਾਈਸ: {c_last}")
      alerted[key] = now.isoformat()
      alert_count += 1
      time.sleep(0.5)

    except Exception as e:
      continue

  save_state(alerted)
  print(f"🏁 ਸਕੈਨ ਪੂਰਾ ਹੋਇਆ। ਕੁੱਲ ਅਲਰਟ: {alert_count}")


if __name__ == "__main__":
  run_scanner()
