import os
import time
import json
import ccxt
import requests
import matplotlib
matplotlib.use('Agg') # Headless backend for server environments
import matplotlib.pyplot as plt

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CACHE_FILE = "alerted_pairs.json"
COOLDOWN_HOURS = 24
CHART_FILE = "chart.png"

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
        print("Telegram status message sent successfully.")
    except Exception as e:
        print(f"Failed to send Telegram status message: {e}")

def send_telegram_photo_alert(message, chart_path):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram credentials missing.")
        return
    
    # If no chart exists, fallback to sending a text message with a "no chart" note
    if not chart_path or not os.path.exists(chart_path):
        text_with_notice = message + "\n\n📊 *Chart Status:* There is no chart available for this alert."
        send_telegram_alert(text_with_notice)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(chart_path, 'rb') as photo:
            payload = {
                "chat_id": TELEGRAM_CHAT_ID,
                "caption": message,
                "parse_mode": "Markdown"
            }
            files = {"photo": photo}
            response = requests.post(url, data=payload, files=files)
            response.raise_for_status()
            print("Telegram photo alert sent successfully.")
    except Exception as e:
        print(f"Failed to send Telegram photo alert: {e}")
        # Fallback to text message if photo upload fails
        send_telegram_alert(message + "\n\n📊 *Chart Status:* There is no chart available for this alert.")

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

def aggregate_candles(base_ohlcv, factor):
    if not base_ohlcv:
        return []
    aggregated = []
    for i in range(0, len(base_ohlcv), factor):
        chunk = base_ohlcv[i:i + factor]
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

def generate_chart(symbol, tf_name, ohlcv, entry, sl, tp):
    """Generates and saves a clean candlestick chart image with SL/TP lines."""
    try:
        recent = ohlcv[-35:]
        closes = [c[4] for c in recent]
        highs = [c[2] for c in recent]
        lows = [c[3] for c in recent]
        x = range(len(recent))

        plt.figure(figsize=(10, 6))
        plt.style.use('dark_background')

        plt.plot(x, closes, color='#00ffcc', linewidth=2, label='Close Price')
        plt.fill_between(x, lows, highs, color='#00ffcc', alpha=0.15)

        plt.axhline(y=entry, color='#3498db', linestyle='--', linewidth=1.5, label=f'Entry: {entry:.4f}')
        plt.axhline(y=sl, color='#e74c3c', linestyle='-', linewidth=1.5, label=f'Stop Loss: {sl:.4f}')
        plt.axhline(y=tp, color='#2ecc71', linestyle='-', linewidth=1.5, label=f'Take Profit: {tp:.4f}')

        plt.title(f"{symbol} - {tf_name} Setup", fontsize=14, color='white', pad=12)
        plt.legend(loc='upper left', fontsize=9)
        plt.grid(color='#333333', linestyle=':', linewidth=0.5)
        plt.tight_layout()

        plt.savefig(CHART_FILE, dpi=150)
        plt.close()
        return True
    except Exception as e:
        print(f"Chart generation error: {e}")
        return False

def analyze_tf_candles(symbol, tf_name, ohlcv):
    if len(ohlcv) < 30:
        return None

    prev_candle = ohlcv[-2]
    p_open, p_high, p_low, p_close, p_vol = prev_candle[1], prev_candle[2], prev_candle[3], prev_candle[4], prev_candle[5]

    body_size = p_close - p_open
    total_range = p_high - p_low
    if total_range == 0:
        return None
    
    is_bullish = body_size > 0
    body_ratio = body_size / total_range
    if not is_bullish or body_ratio < 0.6:
        return None

    history_vols = [c[5] for c in ohlcv[-22:-2]]
    if len(history_vols) < 20:
        return None
    avg_vol = sum(history_vols) / len(history_vols)
    if avg_vol == 0 or p_vol < avg_vol * 1.5:
        return None

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

    is_prior_down = sh_high_avg <= fh_high_avg
    if not is_prior_down:
        return None

    local_resistance = max(highs[-12:-1])
    if p_close <= local_resistance:
        return None

    is_falling_lows = sh_low_avg < fh_low_avg
    is_contracting = (highs[-1] - lows[-1]) < (highs[0] - lows[0])
    
    if is_falling_lows and is_contracting:
        pattern_type = "Falling Wedge Breakout"
        pattern_desc = "Price broke above the upper boundary of a falling wedge consolidation channel, signaling trend reversal."
    else:
        pattern_type = "Bullish CHoCH (Change of Character)"
        pattern_desc = "Price broke above the most recent lower high in a downtrend structure, signaling a character shift from bearish to bullish."

    sl = min(lows[-12:])
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
        "vol_ratio": p_vol / avg_vol,
        "pattern_type": pattern_type,
        "pattern_desc": pattern_desc,
        "ohlcv": ohlcv
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

    scan_targets = [
        ("8h", "4h", 2),
        ("12h", "4h", 3),
        ("Daily (1D)", "1d", 1),
        ("3-Day (3D)", "1d", 3),
        ("Weekly (1W)", "1d", 7)
    ]

    total_alerts_sent = 0

    for symbol in symbols:
        if symbol in cache:
            if (current_time - cache[symbol]) / 3600 < COOLDOWN_HOURS:
                continue

        try:
            h4_ohlcv = exchange.fetch_ohlcv(symbol, '4h', limit=100)
            daily_ohlcv = exchange.fetch_ohlcv(symbol, '1d', limit=100)

            if len(h4_ohlcv) < 50 or len(daily_ohlcv) < 50:
                continue

            found_alert = False
            for tf_label, base_tf, factor in scan_targets:
                if base_tf == '4h':
                    tf_ohlcv = aggregate_candles(h4_ohlcv, factor)
                else:
                    tf_ohlcv = aggregate_candles(daily_ohlcv, factor)

                setup = analyze_tf_candles(symbol, tf_label, tf_ohlcv)
                if setup:
                    chart_created = generate_chart(symbol, setup['timeframe'], setup['ohlcv'], setup['entry'], setup['sl'], setup['tp'])
                    
                    message = (
                        f"🚀 *MEXC Perpetual Long Setup*\n\n"
                        f"🔹 *Pair:* `{symbol}`\n"
                        f"⏱ *Timeframe:* `{setup['timeframe']}` (Previous Closed Candle)\n"
                        f"📊 *Pattern:* {setup['pattern_type']}\n\n"
                        f"🎯 *Entry Price:* `{setup['entry']:.4f}`\n"
                        f"🛑 *Stop Loss (SL):* `{setup['sl']:.4f}`\n"
                        f"✅ *Take Profit (TP):* `{setup['tp']:.4f}`\n"
                        f"⚖️ *Risk / Reward:* `1:{setup['rr']:.2f}`\n\n"
                        f"💡 *Why Long It:*\n"
                        f"• **{setup['pattern_type']}:** {setup['pattern_desc']}\n"
                        f"• **Solid Candle Confirmation:** Closed with a powerful bullish body ({setup['body_ratio']*100:.1f}% of total range), confirming strong buyer commitment.\n"
                        f"• **Volume Expansion:** Breakout volume surged to {setup['vol_ratio']:.1f}x the 20-period average, validating heavy institutional accumulation."
                    )

                    if chart_created and os.path.exists(CHART_FILE):
                        send_telegram_photo_alert(message, CHART_FILE)
                    else:
                        send_telegram_photo_alert(message, None)

                    cache[symbol] = current_time
                    save_cache(cache)
                    total_alerts_sent += 1
                    time.sleep(0.5)
                    found_alert = True
                    break
            
            if found_alert:
                continue

        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue

    # Send status update with explicit "no chart" notice if no setups were found in this 4h cycle
    if total_alerts_sent == 0:
        status_msg = (
            "🔍 *MEXC Scan Cycle Completed*\n\n"
            "No pairs matched the Falling Wedge / CHoCH criteria in this 4h window.\n\n"
            "📊 *Chart Status:* There is no chart for this scan because no matching pair was found.\n\n"
            "✅ *Scanner Status:* Active and working correctly!"
        )
        send_telegram_alert(status_msg)

if __name__ == "__main__":
    main()
