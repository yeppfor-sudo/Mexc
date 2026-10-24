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

EXCLUDE = ['STOCK','JPY','EUR','GBP','CHF','AUD','CAD','NZD']
syms=[s for s in exchange.markets if s.endswith('/USDT:USDT') and not any(x in s for x in EXCLUDE) and s.split('/')[0] not in EXCLUDE]

print(f"Checking {len(syms)} crypto only - CHOCH style")

alerted=load()
now=datetime.utcnow()
alerted={k:v for k,v in alerted.items() if datetime.fromisoformat(v) > now - timedelta(hours=4)}

TF_CONFIG = {'4h':12, '1d':15, '3d':18}

total=0
for TF, MAX_DIST in TF_CONFIG.items():
    print(f"\n--- TF: {TF} CHOCH+RETEST ---")
    cnt=0
    for sym in syms:
        try:
            key=f"{sym}_{TF}"
            if key in alerted: continue
            ohlcv=exchange.fetch_ohlcv(sym, TF, limit=100)
            if len(ohlcv)<80: continue
            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df=df.iloc[:-1]
            close, high, low, open_=df['c'], df['h'], df['l'], df['o']
            c=close.iloc[-1]
            
            ema6=close.ewm(span=6).mean()
            ema12=close.ewm(span=12).mean()
            ema20=close.ewm(span=20).mean()
            e6,e12,e20=ema6.iloc[-1],ema12.iloc[-1],ema20.iloc[-1]
            pe6,pe12,pe20=ema6.iloc[-2],ema12.iloc[-2],ema20.iloc[-2]

            # 1. DOWNTREND BEFORE (bearish 70% of last 30)
            down_bearish = (ema6.iloc[-35:-5] < ema12.iloc[-35:-5]).mean() > 0.7
            if not down_bearish: continue
            
            # 2. FIND LAST LOWER HIGH (CHOCH level) - highest high in downtrend
            # last downtrend swing high
            down_section = df.iloc[-60:-10]
            last_LH = down_section['h'].max()  # CHOCH level
            
            # 3. CHOCH - price broke above last lower high in last 10 candles
            broke = False
            choch_idx = -1
            for i in range(-10, -1):
                if close.iloc[i] > last_LH:
                    broke=True
                    choch_idx=i
                    break
            if not broke: continue
            
            # 4. RETEST - current price is near CHOCH level (retesting it)
            # price came back to test last_LH, within 3% above it
            retest_dist = (c - last_LH) / last_LH * 100
            if retest_dist < -2 or retest_dist > 5:  # must be near level
                continue
            
            # 5. ↗️ NOW FLIP BULLISH - EMA6 > EMA12 > EMA20 first time
            if not (e6>e12>e20 and not (pe6>pe12>pe20)): continue
            if not (close.iloc[-1] > open_.iloc[-1]): continue  # bullish candle
            
            # 6. No % bottom needed - CHOCH is enough

            coin=sym.replace('/USDT:USDT','')
            msg=f"↗️ CHOCH + RETEST [{TF}]\nCoin:{coin}\nPrice:{c:.6f}\nCHOCH Level:{last_LH:.6f}\nRetest: +{retest_dist:.1f}% | EMA6>12>20 flip\nEarly before pump!"
            send(msg)
            time.sleep(0.6)
            alerted[key]=now.isoformat()
            cnt+=1
            total+=1
            if cnt>=20: break
        except: continue
    print(f"Done {TF}: {cnt}")

save(alerted)
print(f"TOTAL CHOCH alerts: {total}")
