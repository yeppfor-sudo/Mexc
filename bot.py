import os, ccxt, pandas as pd, numpy as np, requests, json, time, pytz
from datetime import datetime, timedelta
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')

HIST_FILE = "alerts_history.json"
PERF_FILE = "performance.json"
os.makedirs("charts", exist_ok=True)

TIMEFRAMES = {
    '4h': '4h', '6h': '6h', '8h': '8h', '12h': '12h',
    '1d': '1d', '3d': '3d', '5d': '5d', '7d': '7d'
}

def send_msg(text):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                  json={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"}, timeout=20)

def send_photo(path, caption):
    with open(path, 'rb') as f:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                      data={"chat_id": CHAT, "caption": caption, "parse_mode": "Markdown"},
                      files={"photo": f}, timeout=30)

def load_json(file):
    try:
        with open(file, 'r') as f: return json.load(f)
    except: return {}

def save_json(file, data):
    with open(file, 'w') as f: json.dump(data, f)

exchange = ccxt.mexc({'enableRateLimit': True})
exchange.load_markets()

# Resample function for non-standard TFs
def fetch_tf(symbol, tf):
    # base timeframe to fetch
    if tf in ['4h','6h','8h','12h']:
        # fetch 1h and resample
        ohlcv = exchange.fetch_ohlcv(symbol, '1h', limit=500)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True)
        df.set_index('time', inplace=True)
        rule = {'4h':'4h','6h':'6h','8h':'8h','12h':'12h'}[tf]
        df_r = df.resample(rule).agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'}).dropna()
        df_r.reset_index(inplace=True)
        df_r['t'] = df_r['time'].astype(int)//10**6
        return df_r
    else:
        # daily based
        ohlcv = exchange.fetch_ohlcv(symbol, '1d', limit=200)
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df['time'] = pd.to_datetime(df['t'], unit='ms', utc=True)
        if tf == '1d':
            return df
        df.set_index('time', inplace=True)
        rule = {'3d':'3D','5d':'5D','7d':'7D'}[tf]
        df_r = df.resample(rule).agg({'o':'first','h':'max','l':'min','c':'last','v':'sum'}).dropna()
        df_r.reset_index(inplace=True)
        df_r['t'] = df_r['time'].astype(int)//10**6
        return df_r

def check_setup(df):
    if len(df) < 60: return None
    df['ema20'] = df['c'].ewm(span=20).mean()
    df['ema_slope'] = df['ema20'].diff(5)
    
    # A: Downtrend - price below ema20 last 30 candles and ema slope down
    recent = df.iloc[-50:-10]
    if not (recent['c'] < recent['ema20']).sum() > 25: return None
    if not (recent['ema_slope'] < 0).sum() > 20: return None
    down_pct = (recent['c'].iloc[-1] - recent['c'].iloc[0]) / recent['c'].iloc[0]
    if down_pct > -0.05: return None # at least -5% down
    
    # B: Support - lowest low in that downtrend
    support_idx = recent['l'].idxmin()
    support_price = recent.loc[support_idx, 'l']
    support_time = recent.loc[support_idx, 'time']
    
    # C: Breakout - price breaks above recent swing high after support and above ema20
    after_support = df.loc[support_idx:].copy()
    if len(after_support) < 10: return None
    swing_high = after_support.iloc[:-5]['h'].max()  # high before last 5 candles
    breakout_df = after_support.iloc[-10:]
    breakout = breakout_df[breakout_df['c'] > swing_high]
    if breakout.empty: return None
    breakout_candle = breakout.iloc[0]
    if breakout_candle['c'] < breakout_candle['ema20']: return None
    
    # D: Retest and hold near EMA20 - current price retests ema20 and holds
    last = df.iloc[-1]
    last2 = df.iloc[-2]
    # distance to ema20 < 2.5%
    dist_ema = abs(last['c'] - last['ema20']) / last['ema20'] * 100
    dist_ema2 = abs(last2['c'] - last2['ema20']) / last2['ema20'] * 100
    if dist_ema > 3.0 and dist_ema2 > 3.0: return None
    if last['c'] < last['ema20'] * 0.99: return None # must hold above ema
    if last['l'] < last['ema20'] * 0.97: return None # wick not too deep
    
    # Long setup valid
    entry = float(last['c'])
    sl = float(min(support_price * 0.985, df.iloc[-5:]['l'].min() * 0.98))
    risk = entry - sl
    if risk <= 0 or risk/entry > 0.15: return None # risk too big
    
    tp1 = entry + risk * 2
    tp2 = entry + risk * 3
    rr = (tp1 - entry) / risk
    
    if rr < 1.8: return None
    
    return {
        'support': support_price,
        'swing_high': swing_high,
        'entry': entry,
        'sl': sl,
        'tp1': tp1,
        'tp2': tp2,
        'rr': rr,
        'ema20': float(last['ema20']),
        'breakout_price': float(breakout_candle['c'])
    }

def draw_chart(df, symbol, tf, setup):
    plt.figure(figsize=(12,6))
    view = df.tail(80).copy()
    x = range(len(view))
    # candles
    for i, row in view.iterrows():
        idx = list(view.index).index(i)
        color = 'green' if row['c'] >= row['o'] else 'red'
        plt.plot([idx, idx], [row['l'], row['h']], color=color, linewidth=1)
        plt.plot([idx, idx], [row['o'], row['c']], color=color, linewidth=4)
    
    plt.plot(x, view['ema20'], label='EMA20', color='orange', linewidth=1.5)
    plt.axhline(setup['support'], color='cyan', linestyle='--', label=f"Support {setup['support']:.6f}")
    plt.axhline(setup['entry'], color='white', label=f"Entry {setup['entry']:.6f}")
    plt.axhline(setup['sl'], color='red', linestyle='-', label=f"SL {setup['sl']:.6f}")
    plt.axhline(setup['tp1'], color='green', linestyle='-', label=f"TP1 {setup['tp1']:.6f} RR 1:2")
    plt.axhline(setup['tp2'], color='green', linestyle=':', label=f"TP2 {setup['tp2']:.6f} RR 1:3")
    
    # A B C D annotations like your screenshot
    plt.text(len(x)*0.1, view['h'].max()*0.99, 'A\nDowntrend', color='brown', fontsize=12, bbox=dict(facecolor='black', alpha=0.5))
    plt.text(len(x)*0.55, setup['support'], 'B\nSupport', color='cyan', fontsize=12, bbox=dict(facecolor='black', alpha=0.6))
    plt.text(len(x)*0.75, view['h'].max()*0.9, 'C\nBreakout', color='lime', fontsize=12, bbox=dict(facecolor='black', alpha=0.6))
    plt.text(len(x)*0.85, setup['ema20'], 'D\nRetest Hold EMA20', color='violet', fontsize=12, bbox=dict(facecolor='black', alpha=0.6))
    
    plt.title(f"{symbol} {tf} - Long Setup A->B->C->D EMA20 Hold | PKT {datetime.now(PKT).strftime('%Y-%m-%d %H:%M')}")
    plt.legend(loc='best')
    plt.grid(alpha=0.2)
    path = f"charts/{symbol.replace('/','')}_{tf}_{int(time.time())}.png"
    plt.tight_layout()
    plt.savefig(path, dpi=150, facecolor='black', edgecolor='white')
    plt.close()
    return path

# Main scan
history = load_json(HIST_FILE)
perf = load_json(PERF_FILE)
if not isinstance(perf, list): perf = []

now_pkt = datetime.now(PKT)
print(f"Scan Start PKT: {now_pkt} | Every 4h close: 1am,5am,9am,1pm,5pm,9pm")

# Monday weekly report
if now_pkt.weekday() == 0: # Monday
    if perf:
        total = len(perf)
        hits_tp = sum(1 for p in perf if p.get('result')=='TP')
        hits_sl = sum(1 for p in perf if p.get('result')=='SL')
        active = total - hits_tp - hits_sl
        acc = (hits_tp/total*100) if total>0 else 0
        report = f"📊 *Weekly Bot Performance Report*\nDate: {now_pkt.strftime('%Y-%m-%d')}\n\nTotal Alerts: {total}\n✅ TP Hit: {hits_tp}\n❌ SL Hit: {hits_sl}\n⏳ Active: {active}\n🎯 Accuracy: {acc:.2f}%\n\nBot running on PKT 4H closes 1AM,5AM,9AM,1PM,5PM,9PM"
        send_msg(report)

tickers = {}
try: tickers = exchange.fetch_tickers()
except: pass
symbols = [s for s in exchange.markets if s.endswith('/USDT:USDT')]
if tickers:
    symbols = [s for s in symbols if tickers.get(s,{}).get('quoteVolume',0) > 300_000]

symbols = symbols[:180] # limit for GitHub time
alerts_found = 0

for symbol in symbols:
    for tf in TIMEFRAMES:
        try:
            # Check 24h duplicate filter
            key = f"{symbol}_{tf}"
            last_alert = history.get(key, 0)
            if time.time() - last_alert < 24*3600:
                continue
            
            df = fetch_tf(symbol, tf)
            if len(df) < 60: continue
            df['ema20'] = df['c'].ewm(span=20).mean()
            
            setup = check_setup(df)
            if not setup: continue
            
            # Generate chart photo
            chart_path = draw_chart(df, symbol, tf, setup)
            
            caption = f"🚀 *LONG SETUP FOUND D - EMA20 HOLD*\n\n*Coin:* {symbol}\n*TF:* {tf} (PKT Scan)\n*Setup:* A Downtrend → B Support {setup['support']:.6f} → C Breakout {setup['breakout_price']:.6f} → D Retest EMA20 Hold\n\n*Entry:* `{setup['entry']:.6f}`\n*Stop Loss:* `{setup['sl']:.6f}`\n*Target 1:* `{setup['tp1']:.6f}` (RR 1:2)\n*Target 2:* `{setup['tp2']:.6f}` (RR 1:3)\n*R:R:* {setup['rr']:.2f}\n*EMA20:* {setup['ema20']:.6f}\n*Time PKT:* {now_pkt.strftime('%Y-%m-%d %I:%M %p')}\n\n⚠️ Hold near EMA20 as per your chart D"
            
            send_photo(chart_path, caption)
            
            # Save history
            history[key] = time.time()
            save_json(HIST_FILE, history)
            
            # Save performance
            perf.append({
                'symbol': symbol, 'tf': tf, 'time': str(now_pkt),
                'entry': setup['entry'], 'sl': setup['sl'], 'tp1': setup['tp1'],
                'result': 'ACTIVE'
            })
            save_json(PERF_FILE, perf)
            
            alerts_found += 1
            time.sleep(1)
            
        except Exception as e:
            print(f"Error {symbol} {tf}: {e}")
            continue

if alerts_found == 0:
    send_msg("*there is no chart please wait and patience*")

print(f"Done. Alerts: {alerts_found}")
