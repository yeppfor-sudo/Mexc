import ccxt, pandas as pd, requests, os, time
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

def scan_long(df):
    if len(df)<60: return None
    df['ema9']=ema(df['c'],9); df['ema20']=ema(df['c'],20)
    df['rsi']=rsi(df['c'],14); df['vma']=df['v'].rolling(20).mean()
    last=df.iloc[-1]
    if last['v'] < last['vma']*2.8: return None
    if not (20 <= last['rsi'] <= 44): return None
    if not (last['c'] > last['o'] and last['c'] > last['ema9']): return None
    if (df.iloc[-7:-1]['h'].max()-df.iloc[-7:-1]['l'].min())/df.iloc[-7:-1]['l'].min() > 0.06: return None
    sl=last['l']*0.993
    risk=last['c']-sl
    if risk<=0: return None
    return {'side':'long','price':last['c'],'sl':sl,'tp1':last['c']+risk*2,'tp2':last['c']+risk*4,'score':last['v']/last['vma'],'rsi':last['rsi']}

def scan_short(df):
    if len(df)<60: return None
    df['ema9']=ema(df['c'],9); df['ema20']=ema(df['c'],20)
    df['rsi']=rsi(df['c'],14); df['vma']=df['v'].rolling(20).mean()
    last=df.iloc[-1]
    if last['v'] < last['vma']*2.8: return None
    if not (56 <= last['rsi'] <= 80): return None
    if not (last['c'] < last['o'] and last['c'] < last['ema9']): return None
    if (df.iloc[-7:-1]['h'].max()-df.iloc[-7:-1]['l'].min())/df.iloc[-7:-1]['l'].min() > 0.06: return None
    sl=last['h']*1.007
    risk=sl-last['c']
    if risk<=0: return None
    return {'side':'short','price':last['c'],'sl':sl,'tp1':last['c']-risk*2,'tp2':last['c']-risk*4,'score':last['v']/last['vma'],'rsi':last['rsi']}

def trade_futures(sym, sig, ex):
    try:
        # FUTURES SETUP - MOST IMPORTANT
        ex.set_leverage(20, sym)  # 20x leverage futures
        ex.set_margin_mode('isolated', sym)  # Isolated not cross
        ex.set_position_mode(True)  # Hedge mode = can hold long+short same coin
        
        bal=ex.fetch_balance()
        usdt=float(bal['USDT']['free'])
        if usdt < 10:
            t(f"❌ Futures balance low ${usdt:.2f} Need $10")
            return
        
        # Risk 10% per trade = $1 on $10 account with 20x = $20 position
        trade_usdt=usdt*0.10
        qty=trade_usdt*20/sig['price']
        qty=ex.amount_to_precision(sym, qty)
        
        if sig['side']=='long':
            # LONG FUTURES
            ex.create_market_buy_order(sym, qty)
            # SL
            ex.create_order(sym,'market','sell',qty,None,{'stopPrice':sig['sl'],'type':'stop_market','closePosition':False})
            # TP
            ex.create_limit_sell_order(sym, float(qty)*0.5, sig['tp1'])
            ex.create_limit_sell_order(sym, float(qty)*0.5, sig['tp2'])
            t(f"🚀 FUTURES LONG {sym}\nEntry {sig['price']:.6f}\nQty {qty}\nLev 20x Iso\nSL {sig['sl']:.6f}\nTP1 {sig['tp1']:.6f} TP2 {sig['tp2']:.6f}\nRSI {sig['rsi']:.0f}")
        else:
            # SHORT FUTURES
            ex.create_market_sell_order(sym, qty)
            ex.create_order(sym,'market','buy',qty,None,{'stopPrice':sig['sl'],'type':'stop_market','closePosition':False})
            ex.create_limit_buy_order(sym, float(qty)*0.5, sig['tp1'])
            ex.create_limit_buy_order(sym, float(qty)*0.5, sig['tp2'])
            t(f"🔻 FUTURES SHORT {sym}\nEntry {sig['price']:.6f}\nQty {qty}\nLev 20x Iso\nSL {sig['sl']:.6f}\nTP1 {sig['tp1']:.6f} TP2 {sig['tp2']:.6f}\nRSI {sig['rsi']:.0f}")
        return True
    except Exception as e:
        t(f"❌ Futures {sym} {sig['side']} error: {str(e)[:150]}")
        return False

t(f"⚡ FUTURES BOT START {datetime.utcnow().strftime('%H:%M UTC')}")

if not API_KEY:
    t("⚠️ Set MEXC_API_KEY + SECRET in GitHub Secrets for FUTURES auto trade\nRunning SCAN ONLY now")
    ex=ccxt.mexc({'enableRateLimit':True})
    ex.options['defaultType']='swap'
    ex.load_markets()
    syms=[s for s in ex.markets if ':USDT' in s][:300]
    longs=0; shorts=0
    for sym in syms:
        try:
            ohlcv=ex.fetch_ohlcv(sym,'1m',limit=70)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            if scan_long(df.copy()): longs+=1
            if scan_short(df.copy()): shorts+=1
        except: continue
    t(f"📊 FUTURES SCAN: {longs} LONG setups, {shorts} SHORT setups found\nAdd API keys to auto trade them")
else:
    ex=ccxt.mexc({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True})
    ex.options['defaultType']='swap'
    ex.options['defaultMarginMode']='isolated'
    ex.load_markets()
    
    # Check open futures positions
    try:
        pos=ex.fetch_positions()
        open_p=[p for p in pos if float(p['contracts'])>0]
        t(f"📈 Open Futures Positions: {len(open_p)} { [p['symbol']+p['side'] for p in open_p] if open_p else 'None'}")
        if len(open_p)>=2:
            t("⏸️ Max 2 futures positions - wait for close")
            exit()
    except Exception as e:
        t(f"Pos check: {str(e)[:80]}")
    
    syms=[s for s in ex.markets if ':USDT' in s][:400]
    found=[]
    for sym in syms:
        try:
            ohlcv=ex.fetch_ohlcv(sym,'1m',limit=70)
            df=pd.DataFrame(ohlcv,columns=['t','o','h','l','c','v'])
            l=scan_long(df.copy()); s=scan_short(df.copy())
            if l: found.append((l['score'],sym,l))
            if s: found.append((s['score'],sym,s))
        except: continue
    
    top=sorted(found, key=lambda x:x[0], reverse=True)[:1]
    if top:
        trade_futures(top[0][1], top[0][2], ex)
    else:
        t("No futures signal now - next scan 10m")

t("✅ Futures bot cycle done")
