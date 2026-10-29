import ccxt, pandas as pd, requests, os, io, time
import matplotlib.pyplot as plt
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
API_KEY=os.getenv("MEXC_API_KEY"); API_SECRET=os.getenv("MEXC_API_SECRET")

def t(m):
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        data={"chat_id":CHAT_ID,"text":m,"parse_mode":"HTML"}, timeout=15)
    except: pass

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff()
    g=d.where(d>0,0).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

def adx(df,p=14):
    h,l,c=df['h'],df['l'],df['c']
    tr=pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(p).mean()
    plus_dm=h.diff().where((h.diff()>l.diff().mul(-1))&(h.diff()>0),0).rolling(p).mean()
    minus_dm=l.diff().mul(-1).where((l.diff().mul(-1)>h.diff())&(l.diff().mul(-1)>0),0).rolling(p).mean()
    plus_di=100*plus_dm/atr; minus_di=100*minus_dm/atr
    dx=100*(abs(plus_di-minus_di)/(plus_di+minus_di)).fillna(0)
    return dx.rolling(p).mean()

def snipe_auto(df, df5, df15):
    if len(df)<60: return None
    for d in [df,df5,df15]:
        d['ema9']=ema(d['c'],9); d['ema20']=ema(d['c'],20); d['rsi']=rsi(d['c'],14)
    df['vma']=df['v'].rolling(20).mean(); df['adx']=adx(df)
    last=df.iloc[-1]; last5=df5.iloc[-1]; last15=df15.iloc[-1]
    if last['v'] < last['vma']*3.2: return None
    if not (22 <= last['rsi'] <= 42): return None
    if last['adx'] < 18: return None
    if not (last['c'] > last['o'] and last['c'] > last['ema9']): return None
    if not (abs(last['c']-last['ema20'])/last['ema20'] < 0.006): return None
    if last5['c'] < last5['o']: return None
    if last15['rsi'] > 60: return None
    tight=df.iloc[-7:-1]
    if (tight['h'].max()-tight['l'].min())/tight['l'].min() > 0.045: return None
    if not (df.iloc[-3]['c'] < df.iloc[-3]['o'] and df.iloc[-2]['c'] < df.iloc[-2]['o']): return None
    sl=last['l']*0.994
    risk=last['c']-sl
    if risk<=0 or risk/last['c']>0.012: return None
    score=(last['v']/last['vma'])*3 + (42-last['rsi'])*0.5
    return {'curr':last['c'],'sl':sl,'tp1':last['c']+risk*2.2,'tp2':last['c']+risk*4,'score':score,'df':df}

def auto_trade(sym, res, ex):
    try:
        # Check balance
        bal=ex.fetch_balance()
        usdt=bal['USDT']['free'] if 'USDT' in bal else 0
        if usdt < 5:
            t(f"❌ Low balance ${usdt:.2f} - Need $10 min")
            return False
        # Position size 20% of balance, leverage 10x
        amount_usdt = usdt * 0.20
        amount_coin = amount_usdt * 10 / res['curr']  # 10x lev
        # Set leverage
        ex.set_leverage(10, sym)
        # BUY MARKET
        order=ex.create_market_buy_order(sym, amount_coin)
        entry=res['curr']
        t(f"🚀 AUTO BUY {sym}\nEntry {entry:.6f}\nSize ${amount_usdt:.2f} x10 = {amount_coin:.2f} coins\nSL {res['sl']:.6f} TP1 {res['tp1']:.6f} TP2 {res['tp2']:.6f}")
        # Set SL and TP
        time.sleep(1)
        ex.create_order(sym,'stop','sell',amount_coin,res['sl'],{'stopPrice':res['sl']})
        ex.create_order(sym,'limit','sell',amount_coin*0.5,res['tp1'])
        ex.create_order(sym,'limit','sell',amount_coin*0.5,res['tp2'])
        t(f"✅ Orders placed: SL + TP1(50%) + TP2(50%)")
        return True
    except Exception as e:
        t(f"❌ Auto trade failed {sym}: {str(e)[:100]}")
        return False

# MAIN
t(f"🤖 AUTO SNIPER START {datetime.utcnow().strftime('%H:%M UTC')}")

if not API_KEY:
    t("⚠️ No API Key - Running in ALERT ONLY mode. Add MEXC_API_KEY secret for auto trade")
    ex_public=ccxt.mexc({'enableRateLimit':True}); ex_public.options['defaultType']='swap'; ex_public.load_markets()
    BLACK={'BTC','ETH','SOL','BNB','XRP','EWJ','KWEB','STOCK','SPX'}
    FOUND=[]
    syms=[m['symbol'] for m in ex_public.markets.values() if ':USDT' in m['symbol']][:200]
    for sym in syms:
        clean=sym.split('/')[0]
        if any(b in clean for b in BLACK): continue
        try:
            ohlcv=ex_public.fetch_ohlcv(sym,'1m',limit=80)
            ohlcv5=ex_public.fetch_ohlcv(sym,'5m',limit=50)
            ohlcv15=ex_public.fetch_ohlcv(sym,'15m',limit=50)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            df5=pd.DataFrame(ohlcv5,columns=['t','o','h','l','c','v'])
            df15=pd.DataFrame(ohlcv15,columns=['t','o','h','l','c','v'])
            res=snipe_auto(df,df5,df15)
            if res: FOUND.append((res['score'],sym,res))
        except: continue
    TOP=sorted(FOUND, key=lambda x:x[0], reverse=True)[:1]
    if TOP:
        t(f"🎯 Would BUY {TOP[0][1]} but no API key - Add keys for auto")
else:
    ex=ccxt.mexc({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True})
    ex.options['defaultType']='swap'; ex.load_markets()
    BLACK={'BTC','ETH','SOL','BNB','XRP','EWJ','KWEB','STOCK','SPX'}
    FOUND=[]
    # Check existing positions - don't open if already in trade
    try:
        positions=ex.fetch_positions()
        open_syms=[p['symbol'] for p in positions if float(p['contracts'])>0]
        if open_syms:
            t(f"⏸️ Already in position {open_syms} - Skipping")
            exit()
    except: pass
    syms=[m['symbol'] for m in ex.markets.values() if ':USDT' in m['symbol']][:200]
    for sym in syms:
        clean=sym.split('/')[0]
        if any(b in clean for b in BLACK): continue
        try:
            ohlcv=ex.fetch_ohlcv(sym,'1m',limit=80)
            ohlcv5=ex.fetch_ohlcv(sym,'5m',limit=50)
            ohlcv15=ex.fetch_ohlcv(sym,'15m',limit=50)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            df5=pd.DataFrame(ohlcv5,columns=['t','o','h','l','c','v'])
            df15=pd.DataFrame(ohlcv15,columns=['t','o','h','l','c','v'])
            res=snipe_auto(df,df5,df15)
            if res: FOUND.append((res['score'],sym,res))
        except: continue
    TOP=sorted(FOUND, key=lambda x:x[0], reverse=True)[:1]
    if TOP:
        auto_trade(TOP[0][1], TOP[0][2], ex)
    else:
        t("No high accuracy signal this scan - Next scan in 15m")

t("🤖 Auto Sniper cycle done")
