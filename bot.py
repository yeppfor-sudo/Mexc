# FINAL - ONLY CRYPTO + EARLY M CATCHER
import os, ccxt, pandas as pd, time, requests, json
from datetime import datetime, timedelta

TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT=os.getenv("CHAT_ID")

def send(msg):
    requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":msg}, timeout=10)

exchange=ccxt.mexc({'enableRateLimit':True})
exchange.load_markets()

EXCLUDE=['STOCK','JPY','EUR','GBP']
syms=[s for s in exchange.markets if s.endswith('/USDT:USDT') and not any(x in s for x in EXCLUDE) and s.split('/')[0] not in EXCLUDE]

print(f"Checking {len(syms)} crypto only")

for sym in syms:
    try:
        ohlcv=exchange.fetch_ohlcv(sym,'4h',limit=80)
        df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        df=df.iloc[:-1] # no current candle
        close=df['c']
        e6=close.ewm(span=6).mean().iloc[-1]
        e12=close.ewm(span=12).mean().iloc[-1]
        e20=close.ewm(span=20).mean().iloc[-1]
        pe6=close.ewm(span=6).mean().iloc[-2]
        pe12=close.ewm(span=12).mean().iloc[-2]
        pe20=close.ewm(span=20).mean().iloc[-2]
        
        swing_low=df.iloc[-60:-5]['l'].min()
        c=close.iloc[-1]
        dist=(c-swing_low)/swing_low*100
        
        # THIS WOULD HAVE CAUGHT M AT 0.78
        if dist<2 or dist>20: continue  # allow up to 20% from low like M
        if not (e6>e12>e20 and not (pe6>pe12>pe20)): continue # first flip
        
        coin=sym.replace('/USDT:USDT','')
        send(f"🚀 BOTTOM SQUEEZE\nCoin:{coin} Price:{c:.5f}\nLow:{swing_low:.5f} +{dist:.1f}%\nLike your M chart - early!")
        time.sleep(1)
    except: continue
