import os, ccxt, pandas as pd, requests, json, matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime, timedelta

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
FILE = "alerted.json"

def send_with_chart(msg, image_path):
    try:
        with open(image_path, 'rb') as photo:
            requests.post(f"https://api.telegram.org/bot{TOKEN}/sendPhoto",
                          data={"chat_id": CHAT, "caption": msg},
                          files={"photo": photo}, timeout=15)
    except:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      json={"chat_id": CHAT, "text": msg}, timeout=10)

def load():
    try:
        if os.path.exists(FILE):
            with open(FILE,'r') as f: return json.load(f)
    except: pass
    return {}

def save(d):
    with open(FILE,'w') as f: json.dump(d,f)

def make_chart(df, ema20, coin, path):
    plt.figure(figsize=(10,5))
    for i in range(len(df)-30, len(df)):
        r = df.iloc[i]
        col = 'green' if r['c'] > r['o'] else 'red'
        plt.plot([i,i],[r['l'],r['h']], color=col, linewidth=1)
        plt.plot([i,i],[r['o'],r['c']], color=col, linewidth=5)
    plt.plot(range(len(df)-30, len(df)), ema20.iloc[-30:], color='orange', linewidth=1.5, label='EMA20')
    plt.scatter([len(df)-1],[df.iloc[-1]['c']], color='yellow', s=150, edgecolors='black', zorder=5)
    plt.title(f"{coin} 1m BREAKOUT")
    plt.grid(True, alpha=0.3)
    plt.legend()
    plt.tight_layout()
    plt.savefig(path, dpi=150)
    plt.close()

exchange = ccxt.mexc({'enableRateLimit': True})
exchange.load_markets()

tickers = {}
try: tickers = exchange.fetch_tickers()
except: pass

all_syms = [s for s in exchange.markets if s.endswith('/USDT:USDT')]
filtered = [s for s in all_syms if s in tickers and tickers[s].get('quoteVolume',0) > 1_000_000]
if not filtered: filtered = all_syms[:300]

alerted = load()
now = datetime.utcnow()
alerted = {k:v for k,v in alerted.items() if datetime.fromisoformat(v) > now - timedelta(hours=24)}

found = 0
for sym in filtered:
    try:
        ohlcv = exchange.fetch_ohlcv(sym, '1m', limit=50)
        if len(ohlcv) < 30: continue
        df = pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
        prev, curr = df.iloc[-2], df.iloc[-1]
        coin = sym.replace('/USDT:USDT','')
        if coin in alerted: continue
        if curr['c'] <= curr['o']: continue
        rng = curr['h'] - curr['l']
        if rng == 0: continue
        body_pct = (curr['c'] - curr['o']) / rng
        if body_pct < 0.8: continue
        if prev['v'] == 0 or curr['v'] < prev['v'] * 4: continue
        ema20 = df['c'].ewm(span=20).mean()
        if not (prev['c'] < ema20.iloc[-2] and curr['c'] > ema20.iloc[-1]): continue
        vol24 = tickers.get(sym,{}).get('quoteVolume',0)
        chart = f"/tmp/{coin}.png"
        make_chart(df, ema20, coin, chart)
        msg = f"🚀 1m BREAKOUT [{coin}]\nPrice: {curr['c']:.6f}\nBody: {body_pct*100:.0f}% | Vol: {curr['v']/prev['v']:.1f}x\nEMA20 Breakout ✅\n24h Vol: ${vol24/1e6:.1f}M"
        send_with_chart(msg, chart)
        alerted[coin] = now.isoformat()
        found += 1
        if found >= 10: break
    except: continue

save(alerted)
print(f"Done: {found}")
