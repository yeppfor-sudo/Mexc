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
        if close.iloc[-15:].max() <= swing_high: continue
        if not (e6>e12>e20): continue
        touched = (l <= e12*1.015 and l >= e12*0.96) or (l <= e20*1.03 and l >= e20*0.93)
        if touched and c>e12 and c>o:
            coin=sym.replace('/USDT:USDT','')
            msg=f"🚀 LONG 4H CHOCH+EMA HOLD\nCoin:{coin}\nPrice:{c}\nEMA12:{e12:.6f} EMA20:{e20:.6f}\nSetup:Down->CHOCH->{swing_high:.4f} Break->EMA HOLD"
            alerts.append(msg)
        time.sleep(0.07)
    except: continue

for a in alerts[:20]:
    send_telegram(a)
    time.sleep(1)
print(f"Done, found {len(alerts)}")
