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

EXCLUDE = ['STOCK','JPY','EUR','GBP','CHF','AUD','CAD','NZD','HKD','SGD','CNH','TRY','BRL','ZAR','MXN','INR','RUB','KRW']
syms=[]
for s in exchange.markets:
    if not s.endswith('/USDT:USDT'): continue
    if any(x in s for x in EXCLUDE): continue
    base=s.split('/')[0]
    if base in EXCLUDE: continue
    syms.append(s)

print(f"Checking {len(syms)} crypto pairs only (no STOCK/FOREX)")

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
        df=df.iloc[:-1]
        close,low,open_,vol=df['c'],df['l'],df['o'],df['v']
        c,l,o=close.iloc[-1],low.iloc[-1],open_.iloc[-1]
        ema6=close.ewm(span=6).mean()
        ema12=close.ewm(span=12).mean()
        ema20=close.ewm(span=20).mean()
        e6,e12,e20=ema6.iloc[-1],ema12.iloc[-1],ema20.iloc[-1]
        pe6,pe12,pe20=ema6.iloc[-2],ema12.iloc[-2],ema20.iloc[-2]

        down_bearish = (ema6.iloc[-30:-5] < ema12.iloc[-30:-5]).mean() > 0.7
        if not down_bearish: continue
        swing_low=df.iloc[-60:-5]['l'].min()
        dist = (c - swing_low)/swing_low*100 if swing_low>0 else 100
        if dist <0 or dist>12: continue
        squeeze = abs(e6 - e20)/e20 < 0.025
        if not squeeze and abs(pe6 - pe20)/pe20 >=0.03: continue
        if not (e6>e12>e20 and not (pe6>pe12>pe20)): continue
        if not (c>o): continue

        coin=sym.replace('/USDT:USDT','')
        msg=f"🚀 BOTTOM SQUEEZE\nCoin:{coin} Price:{c:.6f}\nLow:{swing_low:.6f} +{dist:.1f}%\nEMA6>{coin} squeeze flip"
        alerts.append(msg)
        alerted[sym]=now.isoformat()
    except: continue

save(alerted)
for a in alerts[:20]:
    send(a)
    time.sleep(1)
print(f"Done {len(alerts)} crypto only")
