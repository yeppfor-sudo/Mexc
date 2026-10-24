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

EXCLUDE = ['STOCK','JPY','EUR','GBP','CHF','AUD','CAD','NZD','HKD','SGD']
syms=[s for s in exchange.markets if s.endswith('/USDT:USDT') and not any(x in s for x in EXCLUDE) and s.split('/')[0] not in EXCLUDE]

alerted=load()
now=datetime.utcnow()
# keep alerts 24h for low TF, 7 days for high TF
alerted={k:v for k,v in alerted.items() if datetime.fromisoformat(v) > now - timedelta(days=7)}

# === ALL TIMEFRAMES ===
TF_CONFIG = {
    '1m':  {'enabled': True, 'max_alerts': 5},   # scalping
    '5m':  {'enabled': True, 'max_alerts': 5},
    '15m': {'enabled': True, 'max_alerts': 10},
    '1h':  {'enabled': True, 'max_alerts': 15},
    '4h':  {'enabled': True, 'max_alerts': 20},  # your WET example
    '1d':  {'enabled': True, 'max_alerts': 20},
    '3d':  {'enabled': True, 'max_alerts': 15},
    '1W':  {'enabled': True, 'max_alerts': 10},  # weekly = big pump
}

total=0
for TF, cfg in TF_CONFIG.items():
    if not cfg['enabled']: continue
    print(f"\n--- TF: {TF} ---")
    cnt=0
    for sym in syms:
        try:
            key=f"{sym}_{TF}"
            if key in alerted: continue

            ohlcv=exchange.fetch_ohlcv(sym, TF, limit=100)
            if len(ohlcv)<80: continue

            df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
            df=df.iloc[:-1]
            close, open_ = df['c'], df['o']
            c=close.iloc[-1]

            ema6=close.ewm(span=6).mean()
            ema12=close.ewm(span=12).mean()
            ema20=close.ewm(span=20).mean()
            e6,e12,e20=ema6.iloc[-1],ema12.iloc[-1],ema20.iloc[-1]
            pe6,pe12,pe20=ema6.iloc[-2],ema12.iloc[-2],ema20.iloc[-2]

            # 1. Downtrend - 70% bearish last 30 candles
            if (ema6.iloc[-35:-5] < ema12.iloc[-35:-5]).mean() <= 0.7: continue

            # 2. Last LH = CHOCH Level (same as WET marking)
            last_LH=df.iloc[-60:-10]['h'].max()

            # 3. CHOCH break in last 10
            broke=False
            for i in range(-10, -1):
                if close.iloc[i] > last_LH:
                    broke=True
                    break
            if not broke: continue

            # 4. Retest - your ↗️ zone
            # For 1m need tighter (2%), for Weekly wider (8%)
            max_retest = 2 if TF=='1m' else 3 if TF=='5m' else 5 if TF in ['15m','1h','4h'] else 8
            retest_dist=(c - last_LH)/last_LH*100
            if retest_dist < -3 or retest_dist > max_retest: continue

            # 5. EMA flip
            if not (e6>e12>e20 and not (pe6>pe12>pe20)): continue
            if not (close.iloc[-1] > open_.iloc[-1]): continue

            coin=sym.replace('/USDT:USDT','')
            
            # Timeframe emoji
            tf_emoji = "⚡" if TF in ['1m','5m'] else "🔥" if TF in ['15m','1h'] else "↗️" if TF=='4h' else "💎" if TF in ['1d','3d'] else "🌙"
            
            msg=(
                f"{tf_emoji} CHOCH + RETEST [{TF}]\n"
                f"Coin:{coin}\n"
                f"Price:{c:.6f}\n"
                f"CHOCH Level:{last_LH:.6f}\n"
                f"Retest:{retest_dist:+.1f}% | EMA flip\n"
                f"Buy Zone!"
            )
            send(msg)
            time.sleep(0.4)
            alerted[key]=now.isoformat()
            cnt+=1
            total+=1
            if cnt>=cfg['max_alerts']: break

        except: continue
    print(f"Done {TF}: {cnt}")

save(alerted)
print(f"\nTOTAL ALL TF: {total}")

# For 1m only check top volume coins to avoid ban
if TF in ['1m','5m']:
    tickers=exchange.fetch_tickers()
    top=sorted([(s, tickers[s]['quoteVolume']) for s in syms if s in tickers], key=lambda x: x[1], reverse=True)[:100]
    scan_syms=[x[0] for x in top]
else:
    scan_syms=syms
