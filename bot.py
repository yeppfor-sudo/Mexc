import os
import time
import json
import ccxt
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CACHE_FILE = "alerted_pairs.json"
COOLDOWN_HOURS = 24

def send_telegram_alert(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("Telegram alert sent successfully.")
    except Exception as e:
        print(f"Failed to send Telegram alert: {e}")

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    save_cache({})
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Failed to save cache: {e}")

def aggregate_candles(daily_ohlcv, period_days):
    if not daily_ohlcv:
        return []
    aggregated = []
    for i in range(0, len(daily_ohlcv), period_days):
        chunk = daily_ohlcv[i:i + period_days]
        if not chunk:
            continue
        timestamp = chunk[0][0]
        open_price = chunk[0][1]
        high_price = max(c[2] for c in chunk)
        low_price = min(c[3] for c in chunk)
        close_price = chunk[-1][4]
        volume = sum(c[5] for c in chunk)
        aggregated.append([timestamp, open_price, high_price, low_price, close_price, volume])
    return aggregated

def analyze_tf_candles(symbol, tf_name, ohlcv):
    if len(ohlcv) < 30:
        return None

    # Previous closed candle (index -2)
    prev_candle = ohlcv[-2]
    p_open, p_high, p_low, p_close, p_vol = prev_candle[1], prev_candle[2], prev_candle[3], prev_candle[4], prev_candle[5]

    # Solid Candle Filter (Bullish body >= 60% of total range)
    body_size = p_close - p_open
    total_range = p_high - p_low
    if total_range == 0:
        return None
    
    is_bullish = body_size > 0
    body_ratio = body_size / total_range
    if not is_bullish or body_ratio < 0.6:
        return None

    # Volume Spike Filter (> 1.5x average of past 20 closed candles)
    history_vols = [c[5] for c in ohlcv[-22:-2]]
    if len(history_vols) < 20:
        return None
    avg_vol = sum(history_vols) / len(history_vols)
    if avg_vol == 0 or p_vol < avg_vol * 1.5:
        return None

    # Falling Wedge Structure Detection
    pattern_candles = ohlcv[-27:-2]
    if len(pattern_candles) < 20:
        return None

    highs = [c[2] for c in pattern_candles]
    lows = [c[3] for c in pattern_candles]

    half = len(highs) // 2
    fh_high_avg = sum(highs[:half]) / half
    sh_high_avg = sum(highs[half:]) / (len(highs) - half)
    fh_low_avg = sum(lows[:half]) / half
    sh_low_avg = sum(lows[half:]) / (len(lows) - half)

    is_falling_highs = sh_high_avg < fh_high_avg
    is_falling_lows = sh_low_avg < fh_low_avg
    is_contracting = (highs[-1] - lows[-1]) < (highs[0] - lows[0])

    if not (is_falling_highs and is_falling_lows and is_contracting):
        return None

    local_resistance = max(highs[-10:])
    if p_close <= local_resistance:
        return None

    # Risk / Reward Calculation (Min 1:2)
    sl = min(lows[-10:])
    risk = p_close - sl
    if risk <= 0:
        return None

    tp = p_close + (risk * 2.5)
    rr_ratio = (tp - p_close) / risk
    if rr_ratio < 2.0:
        return None

    return {
        "timeframe": tf_name,
        "entry": p_close,
        "sl": sl,
        "tp": tp,
        "rr": rr_ratio,
        "body_ratio": body_ratio,
        "vol_ratio": p_vol / avg_vol
    }

def main():
    print("Initializing MEXC Exchange perpetual connection...")
    exchange = ccxt.mexc({
        'options': {'defaultType': 'swap'},
        'enableRateLimit': True
    })

    try:
        exchange.load_markets()
    except Exception as e:
        print(f"Failed to load markets: {e}")
        return

    symbols = [s for s in exchange.markets if s.endswith('/USDT') and exchange.markets[s]['linear'] and exchange.markets[s]['swap']]
    print(f"Found {len(symbols)} USDT perpetual pairs to scan.")

    cache = load_cache()
    current_time = time.time()

    cache = {sym: t for sym, t in cache.items() if (current_time - t) / 3600 < COOLDOWN_HOURS}

    timeframes_to_check = [
        ("Daily (1D)", 1),
        ("3-Day (3D)", 3),
        ("Weekly (1W)", 7)
    ]

    for symbol in symbols:
        if symbol in cache:
            if (current_time - cache[symbol]) / 3600 < COOLDOWN_HOURS:
                continue

        try:
            daily_ohlcv = exchange.fetch_ohlcv(symbol, '1d', limit=100)
            if len(daily_ohlcv) < 50:
                continue

            for tf_label, days_per_candle in timeframes_to_check:
                if days_per_candle == 1:
                    tf_ohlcv = daily_ohlcv
                else:
                    tf_ohlcv = aggregate_candles(daily_ohlcv, days_per_candle)

                setup = analyze_tf_candles(symbol, tf_label, tf_ohlcv)
                if setup:
                    message = (
                        f"🚀 *MEXC Perpetual Long Setup*\n\n"
                        f"🔹 *Pair:* `{symbol}`\n"
                        f"⏱ *Timeframe:* `{setup['timeframe']}` (Previous Closed Candle)\n"
                        f"📊 *Pattern:* Falling Wedge Breakout\n\n"
                        f"🎯 *Entry Price:* `{setup['entry']:.4f}`\n"
                        f"🛑 *Stop Loss (SL):* `{setup['sl']:.4f}`\n"
                        f"✅ *Take Profit (TP):* `{setup['tp']:.4f}`\n"
                        f"⚖️ *Risk / Reward:* `1:{setup['rr']:.2f}`\n\n"
                        f"💡 *Why Long It:*\n"
                        f"• **Falling Wedge Breakout:** Price decisively broke above upper wedge resistance, ending the descending consolidation channel.\n"
                        f"• **Solid Candle Confirmation:** Closed with a powerful bullish body ({setup['body_ratio']*100:.1f}% of total range), confirming strong buyer commitment.\n"
                        f"• **Volume Expansion:** Breakout volume surged to {setup['vol_ratio']:.1f}x the 20-period average, validating heavy institutional accumulation."
                    )

                    send_telegram_alert(message)
                    cache[symbol] = current_time
                    save_cache(cache)
                    time.sleep(0.5)
                    break

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue

if __name__ == "__main__":
    main()
