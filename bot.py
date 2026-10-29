import ccxt, pandas as pd, requests, os, json, time
from datetime import datetime, timedelta

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
API_KEY=os.getenv("MEXC_API_KEY"); API_SECRET=os.getenv("MEXC_API_SECRET")

# CONFIG FOR $18 - EVERY TRADE COMPOUND
LEVERAGE=20
RISK_PCT=0.10  # 10% of CURRENT balance = compound every trade
TP_R=2.5
DAILY_TARGET=0.05  # For reporting only, NOT for stop
DAILY_STOP=0.15    # ONLY THIS STOPS DAILY
LEARN_FILE="trades_memory.json"

def t(m):
    try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":m,"parse_mode":"HTML"}, timeout=20)
    except: pass

def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
    d=s.diff(); g=d.where(d>0,0).ewm(alpha=1/p, adjust=False).mean()
    l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean()
    return 100-(100/(1+g/l))

# 1. MARKET ANALYSIS - 1D BTC CANDLE + TREND
def market_brain(ex):
    try:
        btc=pd.DataFrame(ex.fetch_ohlcv('BTC/USDT:USDT','1d',limit=50), columns=['t','o','h','l','c','v'])
        btc['ema20']=ema(btc['c'],20); btc['ema50']=ema(btc['c'],50); btc['rsi']=rsi(btc['c'])
        last=btc.iloc[-1]; prev=btc.iloc[-2]
        trend="BULL" if last['c']>last['ema20']>last['ema50'] else "BEAR" if last['c']<last['ema20']<last['ema50'] else "RANGE"
        btc_change=(last['c']-prev['c'])/prev['c']*100
        bias="LONG" if trend=="BULL" and last['rsi']<70 else "SHORT" if trend=="BEAR" and last['rsi']>30 else "BOTH"
        return {"trend":trend,"bias":bias,"btc_rsi":last['rsi'],"btc_change":btc_change,"btc_price":last['c']}
    except: return {"trend":"RANGE","bias":"BOTH","btc_rsi":50,"btc_change":0,"btc_price":0}

# SENTIMENT
def sentiment_check():
    try:
        fg=requests.get("https://api.alternative.me/fng/?limit=1",timeout=5).json()
        fear=fg['data'][0]['value']; fear_text=fg['data'][0]['value_classification']
    except: fear=50; fear_text="Neutral"
    return {"fear":int(fear),"fear_text":fear_text}

# 11. AI LEARN FROM PAST LOSSES
def load_memory():
    if os.path.exists(LEARN_FILE):
        try: return json.loads(open(LEARN_FILE).read())
        except: pass
    return {"trades":[],"win":0,"loss":0,"best_rsi_long":[20,42],"best_rsi_short":[58,80],"avoid_symbols":[],"win_vol":2.0}

def save_memory(mem):
    try: open(LEARN_FILE,'w').write(json.dumps(mem))
    except: pass

def ai_adjust(mem):
    if mem['loss']>=3:
        recent_losses=[x for x in mem['trades'][-10:] if x['result']=='loss']
        if len(recent_losses)>=3:
            avg_vol=sum([x['vol'] for x in recent_losses])/len(recent_losses)
            if avg_vol<2.5:
                mem['win_vol']=min(3.0, mem['win_vol']+0.2)
            long_losses=[x for x in recent_losses if x['side']=='long']
            if len(long_losses)>=2:
                mem['best_rsi_long'][1]=max(35, mem['best_rsi_long'][1]-2)
    return mem

# 9. BEST SETUPS SCAN WITH LEARNING
def scan(df, mem, market):
    if len(df)<50: return None
    df['ema9']=ema(df['c'],9); df['rsi']=rsi(df['c'],14); df['vma']=df['v'].rolling(20).mean()
    last=df.iloc[-1]
    if last['v'] < last['vma']*mem['win_vol']: return None
    
    rsi_low, rsi_high=mem['best_rsi_long']
    if market['bias']=="SHORT": rsi_high=38
    if market['bias']=="LONG": rsi_low=25
    
    if rsi_low<last['rsi']<rsi_high and last['c']>last['o'] and last['c']>last['ema9']:
        sl=last['l']*0.995
        risk=(last['c']-sl)/last['c']
        if risk>0.012 or risk<0.001: return None
        score=(rsi_high-last['rsi'])*last['v']/last['vma']
        return {'side':'long','p':last['c'],'sl':sl,'tp':last['c']+(last['c']-sl)*TP_R,'rsi':last['rsi'],'vol':last['v']/last['vma'],'risk':risk,'score':score}
    
    rsi_s_low, rsi_s_high=mem['best_rsi_short']
    if market['bias']=="LONG": rsi_s_low=62
    if rsi_s_low<last['rsi']<rsi_s_high and last['c']<last['o'] and last['c']<last['ema9']:
        sl=last['h']*1.005
        risk=(sl-last['c'])/last['c']
        if risk>0.012 or risk<0.001: return None
        score=(last['rsi']-rsi_s_low)*last['v']/last['vma']
        return {'side':'short','p':last['c'],'sl':sl,'tp':last['c']-(sl-last['c'])*TP_R,'rsi':last['rsi'],'vol':last['v']/last['vma'],'risk':risk,'score':score}
    return None

def execute(sym,sig,ex,total,mem):
    try:
        ex.set_leverage(LEVERAGE,sym); ex.set_margin_mode('isolated',sym)
        risk_usdt=total*RISK_PCT  # EVERY TRADE COMPOUND - uses CURRENT total
        qty=(risk_usdt/sig['risk']*LEVERAGE)/sig['p']
        qty=ex.amount_to_precision(sym, qty)
        if float(qty)*sig['p']<5: qty=ex.amount_to_precision(sym, 5.5/sig['p'])
        if sig['side']=='long':
            ex.create_market_buy_order(sym,qty)
            ex.create_order(sym,'market','sell',qty,None,{'stopPrice':sig['sl'],'type':'stop_market'})
            ex.create_limit_sell_order(sym,qty,sig['tp'])
        else:
            ex.create_market_sell_order(sym,qty)
            ex.create_order(sym,'market','buy',qty,None,{'stopPrice':sig['sl'],'type':'stop_market'})
            ex.create_limit_buy_order(sym,qty,sig['tp'])
        win=risk_usdt*TP_R
        t(f"{'🚀 LONG' if sig['side']=='long' else '🔻 SHORT'} {sym}\n🔄 EVERY TRADE COMPOUND\nBal NOW ${total:.2f}\nRisk ${risk_usdt:.2f} → Win +${win:.2f}\nAfter WIN ${total+win:.2f} NEXT risk ${(total+win)*RISK_PCT:.2f}\nEntry {sig['p']:.6f} SL {sig['sl']:.6f} TP {sig['tp']:.6f}\nScore {sig['score']:.1f} Vol {sig['vol']:.1f}x RSI {sig['rsi']:.0f}\nLev {LEVERAGE}x Iso\nAI Vol filter {mem['win_vol']:.1f}x")
        mem['trades'].append({"time":str(datetime.utcnow()),"symbol":sym,"side":sig['side'],"result":"open","vol":sig['vol'],"rsi":sig['rsi']})
        save_memory(mem)
        return True
    except Exception as e:
        t(f"❌ {sym}: {str(e)[:200]}")
        return False

# MAIN
t(f"🧠 AI SELF-LEARNING SNIPER V9.1 {datetime.utcnow().strftime('%H:%M UTC')} $18 MODE - EVERY TRADE COMPOUND")

ex=ccxt.mexc({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True}) if API_KEY else ccxt.mexc({'enableRateLimit':True})
ex.options['defaultType']='swap'; ex.options['defaultMarginMode']='isolated'
ex.load_markets()

mem=load_memory()
mem=ai_adjust(mem)

market=market_brain(ex)
sent=sentiment_check()

t(f"📊 MARKET BRAIN 1D BTC CLOSED:\nBTC ${market['btc_price']:.0f} {market['btc_change']:+.2f}%\nTrend {market['trend']} Bias {market['bias']} RSI {market['btc_rsi']:.0f}\nFear&Greed {sent['fear']} {sent['fear_text']}\nToday BEST: {market['bias']} trades\nAI Learning: W{mem['win']} L{mem['loss']} Vol filter {mem['win_vol']:.1f}x\nRSI Long {mem['best_rsi_long']} Short {mem['best_rsi_short']}")

if not API_KEY:
    t("⚠️ Add MEXC API keys")
    exit()

bal=ex.fetch_balance()
total=float(bal['USDT']['total']) if bal['USDT'] else 0
free=float(bal['USDT']['free']) if bal['USDT'] else 0

# DAILY TRACKER - EDITED: ONLY STOP ON -15%, 5% DOES NOT STOP
today=datetime.utcnow().date()
daily_file=f"daily_{today}.json"
daily={"pnl":0,"trades":0}
if os.path.exists(daily_file):
    try: daily=json.loads(open(daily_file).read())
    except: pass

pos=ex.fetch_positions()
open_pos=[p for p in pos if float(p['contracts'])>0]
open_pnl=sum([float(p['unrealizedPnl']) for p in open_pos]) if open_pos else 0
current_pnl=daily['pnl']+open_pnl

# ONLY STOP ON -15%
if current_pnl <= -total*DAILY_STOP:
    t(f"🛑 DAILY MAX LOSS -15% HIT! Daily PnL ${current_pnl:.2f}\nProtecting ${total:.2f} - STOPPED TODAY - Resume tomorrow")
    exit()

# 5% DOES NOT STOP - JUST REPORT AND CONTINUE
if current_pnl >= total*DAILY_TARGET:
    t(f"🚀 5% TARGET HIT +${current_pnl:.2f} BUT CONTINUE!\nTotal ${total:.2f} Open ${open_pnl:.2f}\n🔄 EVERY TRADE COMPOUND - Keep trading!\nNext risk ${total*RISK_PCT:.2f} → Win +${total*RISK_PCT*TP_R:.2f}\nRule: Only -15% stops daily")
else:
    t(f"💰 Total ${total:.2f} Free ${free:.2f} Open PnL ${open_pnl:.2f}\nDaily PnL ${current_pnl:.2f} / Target +${total*DAILY_TARGET:.2f} (continue) Stop -${total*DAILY_STOP:.2f}\n🔄 Risk EVERY TRADE ${total*RISK_PCT:.2f} (10%) → Win +${total*RISK_PCT*TP_R:.2f} → Next Bal ${total+total*RISK_PCT*TP_R:.2f}\nTrades today {daily['trades']} AI Trades {len(mem['trades'])}")

if open_pos:
    t(f"⏸️ {len(open_pos)} open (Isolated multi) PnL ${open_pnl:.2f}\n{[p['symbol'] for p in open_pos][:3]}\nCan open more - Isolated system")
    if len(open_pos)>=3:
        t("⏸️ Max 3 isolated trades open - Waiting")
        exit()

# SCAN BEST 3 SETUPS
syms=[s for s in ex.markets if ':USDT' in s][:500]
found=[]
for sym in syms:
    if sym in mem['avoid_symbols'][-5:]: continue
    try:
        df=pd.DataFrame(ex.fetch_ohlcv(sym,'1m',limit=60),columns=['t','o','h','l','c','v'])
        s=scan(df,mem,market)
        if s: found.append((s['score'],sym,s))
    except: continue

found=sorted(found,key=lambda x:x[0],reverse=True)[:2]

if found:
    for score,sym,sig in found:
        if len(ex.fetch_positions())>=3: break
        execute(sym,sig,ex,total,mem)
        time.sleep(1)
        # EVERY TRADE COMPOUND - update total for next trade
        bal=ex.fetch_balance()
        total=float(bal['USDT']['total']) if bal['USDT'] else total
else:
    t(f"No best setup now - Market {market['trend']} {market['bias']}\nAI waiting for perfect sniper - Next scan 5m")

open(daily_file,'w').write(json.dumps(daily))
t("✅ AI Cycle done - Every trade compounds - Only -15% stops daily")
