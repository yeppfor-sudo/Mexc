import os, ccxt, pandas as pd, time, requests, json
from datetime import datetime, timedelta

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")
ALERT_FILE="alerted.json"

def send_telegram(msg):
    url=f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try: requests.post(url, json={"chat_id":CHAT_ID,"text":msg}, timeout=10)
    except: pass

def load_alerted():
    try:
        if os.path.exists(ALERT_FILE):
            with open(ALERT_FILE,'r') as f: return json.load(f)
    except: pass
    return {}
def save_alerted(d):
    with open(ALERT_FILE,'w') as f: json.dump(d,f)

exchange=ccxt.mexc({'enableRateLimit':True})
exchange.load_markets()
symbols=[s for s in exchange.markets if s.endswith('/USDT:USDT')]

alerted=load_alerted()
now=datetime.utcnow()
alerted={k:v for k,v in alerted.items() if datetime.fromisoformat(v) > now - timedelta(hours=12)}

alerts=[]
for sym in symbols:
    try:
        if sym in alerted: continue
        ohlcv=exchange.fetch_ohlcv(sym,'4h',limit=100)
        if len(ohlcv)<80: continue
        df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df=df.iloc[:-1]
        c_, l_, o_, v_ = df['c'], df['l'], df['o'], df['v']
        c,l,o,v = c_.iloc[-1], l_.iloc[-1], o_.iloc[-1], v_.iloc[-1]

        # 1. CHOCH Swing High = Key Resistance
        swing_high = df.iloc[-80:-15]['h'].max()
        
        # 2. Breakout with 1.3x Volume (Oct 16 in your image)
        avg_vol = v_.iloc[-30:-5].mean()
        # Check breakout happened in last 15 candles with volume spike
        breakout_candles = df.iloc[-15:]
        breakout_vol_ok = (breakout_candles['v'] > avg_vol*1.3).any() and (breakout_candles['c'] > swing_high).any()
        if not breakout_vol_ok: continue

        # 3. NOW at Point B - Retest Support (right side of your image)
        retest = (l <= swing_high*1.015 and l >= swing_high*0.985)
        holding = c > swing_high
        pct = (c - swing_high)/swing_high*100
        if pct < -1 or pct > 3: continue # must be 0-3% above CHOCH

        # 4. Bull Close > Open (green candle in your circle)
        bull_close = c > o
        if not (retest and holding and bull_close): continue

        coin=sym.replace('/USDT:USDT','')
        msg=f"🎯 POINT B RETEST - ALERT HERE\nCoin:{coin} Price:{c:.5f}\nCHOCH:{swing_high:.5f} +{pct:.2f}%\nBreakout Vol 1.3x + Bull Close > Open\nSetup: Downtrend -> CHOCH Break -> Retest Support"
        alerts.append(msg)
        alerted[sym]=now.isoformat()
    except: continue

save_alerted(alerted)
for a in alerts[:20]:
    send_telegram(a)
    time.sleep(1)
print(f"Found {len(alerts)}")
