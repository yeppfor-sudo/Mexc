import os, ccxt, pandas as pd, requests, time
from datetime import datetime

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID") or "8300651267"

def send_telegram(msg):
    if not TELEGRAM_TOKEN: 
        print(msg)
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except: pass

print("Starting 4H CHOCH + EMA Hold Scanner")
exchange = ccxt.mexc({'enableRateLimit': True, 'options': {'defaultType': 'swap'}})
exchange.load_markets()
symbols = [s for s in exchange.symbols if '/USDT:USDT' in s]

alerts=[]
for sym in symbols:
    try:
        ohlcv = exchange.fetch_ohlcv(sym, '4h', limit=200)
        if len(ohlcv)<100: continue
        df = pd.DataFrame(ohlcv, columns=['ts','o','h','l','c','v'])
        df = df.iloc[:-1]
        close, low, high = df['c'], df['l'], df['h']
        ema6 = close.ewm(span=6).mean()
        ema12 = close.ewm(span=12).mean()
        ema20 = close.ewm(span=20).mean()
        c, l, o = close.iloc[-1], low.iloc[-1], df['o'].iloc[-1]
        e6,e12,e20 = ema6.iloc[-1], ema12.iloc[-1], ema20.iloc[-1]
        down = df.iloc[-70:-10]
        down_pct = (down['c'] < down['c'].ewm(span=20).mean()).mean()*100
        if down_pct < 65: continue
                    swing_high = down['h'].max()
            # --- FIX: Only fresh CHOCH ---
            recent_max = close.iloc[-15:].max()
            if recent_max <= swing_high: 
                continue
            # Check if breakout happened in LAST 2 candles (fresh)
            broke_now = c > swing_high
            broke_2ago = close.iloc[-2] > swing_high
            broke_3ago = close.iloc[-3] > swing_high
            # If it broke more than 2 candles ago, it's OLD - skip
            if not broke_now:
                continue
            if broke_2ago and broke_3ago:
                # Already broke 2 candles ago - old alert, skip
                continue
            # Don't alert if already pumped 12% above CHOCH (too late)
            if c > swing_high * 1.12:
                continue
            
            if not (e6>e12>e20): continue
            touched = (l <= e12*1.015 and l >= e12*0.985) or (l <= e20*1.015 and l >= e20*0.985)
            if touched and c>e12 and c>o:
                coin=sym.replace('/USDT:USDT','').replace('/USDT','')
                # Price must be close to CHOCH level, not far
                choch_dist = (c - swing_high)/swing_high * 100
                msg=f"🚀 LONG 4H CHOCH+EMA HOLD\nCoin:{coin} Price:{c:.6f} \nSetup:Down->{swing_high:.6f} Break->EMA HOLD | Fresh:{choch_dist:.1f}%"
                alerts.append(msg)
        time.sleep(0.07)
    except: continue

for a in alerts[:20]:
    send_telegram(a)
    time.sleep(1)
print(f"Done, found {len(alerts)}")
