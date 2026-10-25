import os
import time
import json
import ccxt
import requests

# Configuration from Environment Variables (GitHub Secrets)
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
    return {}

def save_cache(cache):
    try:
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f)
    except Exception as e:
        print(f"Failed to save cache: {e}")

def is_cooldown_active(cache, symbol):
    if symbol in cache:
        last_alert_time = cache[symbol]
        elapsed_hours = (time.time() - last_alert_time) / 3600
        if elapsed_hours < COOLDOWN_HOURS:
            return True
    return False

def analyze_market():
    print("Initializing MEXC Exchange perpetual connection...")
    exchange = ccxt.mexc({
        'options': {
            'defaultType': 'swap',  # Perpetual Futures
        },
        'enableRateLimit': True
    })

    try:
        exchange.load_markets()
    except Exception as e:
        print(f"Failed to load markets: {e}")
        return

    # Filter USDT perpetual contracts
    symbols = [s for s in exchange.markets if s.endswith('/USDT') and exchange.markets[s]['linear'] and exchange.markets[s]['swap']]
    print(f"Found {len(symbols)} USDT perpetual pairs to scan.")

    cache = load_cache()
    current_time = time.time()

    # Prune old cache entries older than 24h
    cache = {sym: t for sym, t in cache.items() if (current_time - t) / 3600 < COOLDOWN_HOURS}

    timeframe = '1h'  # Change timeframe here if needed (e.g., '4h', '1d')

    for symbol in symbols:
        if is_cooldown_active(cache, symbol):
            continue

        try:
            ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=40)
            if len(ohlcv) < 30:
                continue

            opens = [x[1] for x in ohlcv]
            highs = [x[2] for x in ohlcv]
            lows = [x[3] for x in ohlcv]
            closes = [x[4] for x in ohlcv]
            volumes = [x[5] for x in ohlcv]

            current_close = closes[-1]
            current_open = opens[-1]
            current_high = highs[-1]
            current_low = lows[-1]
            current_vol = volumes[-1]

            # 1. Solid Candle Filter (Bullish body >= 60% of total candle range)
            body_size = current_close - current_open
            total_range = current_high - current_low
            if total_range == 0:
                continue
            
            is_bullish = body_size > 0
            body_ratio = body_size / total_range
            if not is_bullish or body_ratio < 0.6:
                continue

            # 2. Volume Spike Filter (> 1.5x average of past 20 candles)
            avg_vol = sum(volumes[-21:-1]) / 20
            if current_vol < avg_vol * 1.5:
                continue

            # 3. Falling Wedge Structure Detection
            recent_highs = highs[-30:-1]
            recent_lows = lows[-30:-1]
            
            half = len(recent_highs) // 2
            first_half_high_avg = sum(recent_highs[:half]) / half
            second_half_high_avg = sum(recent_highs[half:]) / (len(recent_highs) - half)
            
            first_half_low_avg = sum(recent_lows[:half]) / half
            second_half_low_avg = sum(recent_lows[half:]) / (len(recent_lows) - half)

            # Highs and lows should be sloping downwards (converging wedge pattern)
            is_falling_highs = second_half_high_avg < first_half_high_avg
            is_falling_lows = second_half_low_avg < first_half_low_avg

            if not (is_falling_highs and is_falling_lows):
                continue

            # Breakout confirmation: Price breaks above recent local resistance high
            local_resistance = max(recent_highs[-10:])
            if current_close <= local_resistance:
                continue

            # 4. Risk / Reward Calculation (Min 1:2)
            sl = min(recent_lows[-10:])  # Stop loss placed below wedge low
            risk = current_close - sl
            if risk <= 0:
                continue

            # Targeting a structured R:R of at least 1:2.5
            tp = current_close + (risk * 2.5)
            rr_ratio = (tp - current_close) / risk

            if rr_ratio < 2.0:
                continue  # Skip setups failing the minimum 1:2 R:R constraint

            # Construct Telegram Alert Message
            message = (
                f"🚀 *MEXC Perpetual Long Setup*\n\n"
                f"🔹 *Pair:* `{symbol}`\n"
                f"⏱ *Timeframe:* `{timeframe}`\n"
                f"📊 *Pattern:* Falling Wedge Breakout\n\n"
                f"🎯 *Entry Price:* `{current_close:.4f}`\n"
                f"🛑 *Stop Loss (SL):* `{sl:.4f}`\n"
                f"✅ *Take Profit (TP):* `{tp:.4f}`\n"
                f"⚖️ *Risk / Reward:* `1:{rr_ratio:.2f}`\n\n"
                f"💡 *Why Long:* Strong bullish breakout candle ({body_ratio*100:.1f}% solid body) "
                f"successfully pierced upper wedge resistance alongside a volume surge "
                f"({current_vol / avg_vol:.1f}x average volume), confirming buyer dominance and trend continuation."
            )

            send_telegram_alert(message)
            cache[symbol] = current_time
            save_cache(cache)
            
            time.sleep(0.4) # Rate limit padding

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue

if __name__ == "__main__":
    analyze_market()

def load_cache():
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    # Automatically create the cache file if it doesn't exist yet
    save_cache({})
    return {}
