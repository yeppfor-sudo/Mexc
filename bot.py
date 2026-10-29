import ccxt, pandas as pd, requests, os, json, time
from datetime import datetime

BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")
API_KEY=os.getenv("MEXC_API_KEY"); API_SECRET=os.getenv("MEXC_API_SECRET")

LEVERAGE=20; RISK_PCT=0.10; TP_R=2.5; DAILY_STOP=0.15; DAILY_TARGET=0.05
LEARN_FILE="trades_memory.json"

def t(m):
 try: requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", data={"chat_id":CHAT_ID,"text":m,"parse_mode":"HTML"}, timeout=20)
 except: pass
def ema(s,n): return s.ewm(span=n, adjust=False).mean()
def rsi(s,p=14):
 d=s.diff(); g=d.where(d>0,0).ewm(alpha=1/p, adjust=False).mean(); l=(-d.where(d<0,0)).ewm(alpha=1/p, adjust=False).mean(); return 100-(100/(1+g/l))

def market_brain(ex):
 try:
  btc=pd.DataFrame(ex.fetch_ohlcv('BTC/USDT:USDT','1d',limit=50), columns=['t','o','h','l','c','v']); btc['ema20']=ema(btc['c'],20); btc['ema50']=ema(btc['c'],50); btc['rsi']=rsi(btc['c']); last=btc.iloc[-1]; trend="BULL" if last['c']>last['ema20']>last['ema50'] else "BEAR" if last['c']<last['ema20']<last['ema50'] else "RANGE"; bias="LONG" if trend=="BULL" else "SHORT" if trend=="BEAR" else "BOTH"; return {"trend":trend,"bias":bias,"btc_rsi":last['rsi'],"btc_price":last['c']}
 except: return {"trend":"RANGE","bias":"BOTH","btc_rsi":50,"btc_price":0}

def load_memory():
 if os.path.exists(LEARN_FILE):
  try: return json.loads(open(LEARN_FILE).read())
  except: pass
 return {"trades":[],"win":0,"loss":0,"win_vol":2.0,"best_rsi_long":[20,42],"best_rsi_short":[58,80]}
def save_memory(mem):
 try: open(LEARN_FILE,'w').write(json.dumps(mem))
 except: pass

def scan(df, mem, market):
 if len(df)<50: return None
 df['ema9']=ema(df['c'],9); df['rsi']=rsi(df['c'],14); df['vma']=df['v'].rolling(20).mean(); last=df.iloc[-1]
 if last['v'] < last['vma']*mem['win_vol']: return None
 if 20<last['rsi']<42 and last['c']>last['o'] and last['c']>last['ema9']:
  sl=last['l']*0.995; risk=(last['c']-sl)/last['c']
  if risk>0.012: return None
  return {'side':'long','p':last['c'],'sl':sl,'tp':last['c']+(last['c']-sl)*TP_R,'rsi':last['rsi'],'vol':last['v']/last['vma'],'risk':risk,'score':(42-last['rsi'])*last['v']/last['vma']}
 if 58<last['rsi']<80 and last['c']<last['o'] and last['c']<last['ema9']:
  sl=last['h']*1.005; risk=(sl-last['c'])/last['c']
  if risk>0.012: return None
  return {'side':'short','p':last['c'],'sl':sl,'tp':last['c']-(sl-last['c'])*TP_R,'rsi':last['rsi'],'vol':last['v']/last['vma'],'risk':risk,'score':(last['rsi']-58)*last['v']/last['vma']}
 return None

def execute(sym,sig,ex,total,mem):
 try:
  ex.set_leverage(LEVERAGE,sym); ex.set_margin_mode('isolated',sym)
  risk_usdt=total*RISK_PCT  # <--- EVERY TRADE COMPOUND HERE
  qty=(risk_usdt/sig['risk']*LEVERAGE)/sig['p']; qty=ex.amount_to_precision(sym, qty)
  if float(qty)*sig['p']<5: qty=ex.amount_to_precision(sym, 5.5/sig['p'])
  if sig['side']=='long':
   ex.create_market_buy_order(sym,qty); ex.create_order(sym,'market','sell',qty,None,{'stopPrice':sig['sl'],'type':'stop_market'}); ex.create_limit_sell_order(sym,qty,sig['tp'])
  else:
   ex.create_market_sell_order(sym,qty); ex.create_order(sym,'market','buy',qty,None,{'stopPrice':sig['sl'],'type':'stop_market'}); ex.create_limit_buy_order(sym,qty,sig['tp'])
  win=risk_usdt*TP_R
  t(f"{'🚀 LONG' if sig['side']=='long' else '🔻 SHORT'} {sym}\n🔄 EVERY TRADE COMPOUND\nBal NOW ${total:.2f} Risk ${risk_usdt:.2f} → Win +${win:.2f}\nAfter WIN ${total+win:.2f} NEXT risk ${(total+win)*RISK_PCT:.2f}\nEntry {sig['p']:.6f} SL {sig['sl']:.6f} TP {sig['tp']:.6f}\nLev {LEVERAGE}x Iso")
  mem['trades'].append({"time":str(datetime.utcnow()),"symbol":sym,"side":sig['side']}); save_memory(mem); return True
 except Exception as e:
  t(f"❌ {sym}: {str(e)[:200]}"); return False

# START
ex=ccxt.mexc({'apiKey':API_KEY,'secret':API_SECRET,'enableRateLimit':True}) if API_KEY else ccxt.mexc({'enableRateLimit':True})
ex.options['defaultType']='swap'; ex.options['defaultMarginMode']='isolated'; ex.load_markets()
mem=load_memory(); market=market_brain(ex)
bal=ex.fetch_balance(); total=float(bal['USDT']['total']) if bal['USDT'] else 0; free=float(bal['USDT']['free']) if bal['USDT'] else 0

# DAILY CHECK - ONLY -15% STOPS
today=str(datetime.utcnow().date()); daily={"pnl":0}
if os.path.exists(f"daily_{today}.json"):
 try: daily=json.loads(open(f"daily_{today}.json").read())
 except: pass
pos=ex.fetch_positions(); open_pos=[p for p in pos if float(p['contracts'])>0]; open_pnl=sum([float(p['unrealizedPnl']) for p in open_pos]) if open_pos else 0

if
