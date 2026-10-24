import os, ccxt, pandas as pd, time, requests, json
from datetime import datetime, timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT=os.getenv("CHAT_ID")
FILE="alerted.json"

def send(msg):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":msg}, timeout=10)
    except: pass

def load():
    try:
        if os.path.exists(FILE):
            with open(FILE,'r') as f: return json.load(f)
    except: pass
    return {}
def save(d):
    with open(FILE,'w') as f: json.dump(d,f)

exchange=ccxt.mexc({'enableRateLimit':True})
exchange.load_markets()
syms=[s for s in exchange.markets if s.endswith('/USDT:USDT')]

alerted=load()
now=datetime.utcnow()
alerted={k:v for k,v in alerted.items() if datetime.fromisoformat(v) > now - timedelta(hours=4)}

alerts=[]
for sym in syms:
    try:
        if sym in alerted: continue
        ohlcv=exchange.fetch_ohlcv(sym,'4h',limit=100)
        if len(ohlcv)<80: continue
        df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df=df.iloc[:-1] # closed candle - change to df for real-time
        close,low,open_,vol=df['c'],df['l'],df['o'],df['v']
        c,l,o=close.iloc[-1],low.iloc[-1],open_.iloc[-1]
        ema6=close.ewm(span=6).mean()
        ema12=close.ewm(span=12).mean()
        ema20=close.ewm(span=20).mean()
        e6,e12,e20=ema6.iloc[-1],ema12.iloc[-1],ema20.iloc[-1]
        pe6,pe12,pe20=ema6.iloc[-2],ema12.iloc[-2],ema20.iloc[-2]

        # 1. DOWNTREND before: EMA bearish for last 20 candles
        down_bearish = (ema6.iloc[-30:-5] < ema12.iloc[-30:-5]).mean() > 0.7
        if not down_bearish: continue

        # 2. BOTTOM: Price near recent swing low (within 12% above 60-candle low)
        swing_low=df.iloc[-60:-5]['l'].min()
        if swing_low==0: continue
        dist = (c - swing_low)/swing_low*100
        if dist < 0 or dist > 12: continue  # still at bottom

        # 3. EMA SQUEEZE at bottom: EMA6,12,20 very tight (within 2%)
        squeeze = abs(e6 - e20)/e20 < 0.025 and abs(e12 - e20)/e20 < 0.02
        if not squeeze: 
            # also allow just crossed - still tight last candle
            squeeze_prev = abs(pe6 - pe20)/pe20 < 0.03
            if not squeeze_prev: continue

        # 4. BULLISH FLIP NOW: EMA6 > EMA12 > EMA20 (your green arrow)
        bullish_now = (e6 > e12 > e20)
        bearish_before = not (pe6 > pe12 > pe20)  # previous was NOT bullish = first flip
        if not (bullish_now and bearish_before): continue

        # 5. BULL CANDLE + VOLUME building
        bull_candle = c > o
        avg_vol=vol.iloc[-20:-1].mean()
        vol_build = vol.iloc[-1] > avg_vol*1.1  # volume starting to grow
        if not bull_candle: continue

        coin=sym.replace('/USDT:USDT','')
        msg=f"🚀 BOTTOM EMA SQUEEZE FLIP\nCoin:{coin} Price:{c:.6f}\nLow:{swing_low:.6f} +{dist:.1f}%\nEMA6:{e6:.6f} >12:{e12:.6f} >20:{e20:.6f}\nSetup: Down->Squeeze->Bull Flip (YOUR STYLE)"
        alerts.append(msg)
        alerted[sym]=now.isoformat()
        time.sleep(0.05)
    except: continue

save(alerted)
for a in alerts[:20]:
    send(a)
    time.sleep(1)
print(f"Found {len(alerts)} coins at bottom squeeze")
