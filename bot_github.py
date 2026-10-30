import os, asyncio, json, ccxt, pandas as pd, numpy as np, requests, pytz, pickle, time, sys
from datetime import datetime, timedelta
import websockets
from sklearn.ensemble import RandomForestClassifier

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")
PKT = pytz.timezone('Asia/Karachi')

print(f"TOKEN exists: {bool(TOKEN)} CHAT exists: {bool(CHAT)}", flush=True)

START_CAP = 8.54
LEVERAGE = 5
COMPOUND_EVERY_TRADE = 0.30
TRAILING = 0.6
MAX_PARALLEL = 1
CAP_FILE = "capital.json"
AI_FILE = "ws_ai.pkl"
MEM_FILE = "memory.json"
BLOCK = {'BTC','ETH','SOL','BNB','XRP','USDC','FDUSD','STOCK','ETF','GOLD'}

def tg(m):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":CHAT,"text":m,"parse_mode":"Markdown"}, timeout=15)
    except: pass

def load(f,d):
    try:
        with open(f,'r') as x: return json.load(x)
    except: return d
def save(f,d):
    with open(f,'w') as x: json.dump(d,x,indent=2)

tg(f"✅ *Bot Started* Bal ${START_CAP} | Compound Every Trade")
time.sleep(1)

try:
    ex = ccxt.mexc({'apiKey': os.getenv("MEXC_API_KEY"), 'secret': os.getenv("MEXC_SECRET"), 'enableRateLimit': True, 'options':{'defaultType':'swap'}})
    ex.load_markets()
    bal = ex.fetch_balance()['USDT']
    tg(f"✅ MEXC OK Avail ${bal.get('free',0):.2f} Total ${bal.get('total',0):.2f}")
except Exception as e:
    tg(f"❌ MEXC Error: {e}")
    sys.exit(1)

class Brain:
    def __init__(self):
        self.model=self._load()
        self.funding={}
        self.orderbooks={}
    def _load(self):
        try:
            with open(AI_FILE,'rb') as f: return pickle.load(f)
        except:
            m=RandomForestClassifier(n_estimators=200); m.fit(np.random.rand(100,18), np.random.randint(0,2,100)); return m
    def calc_ob(self, bids, asks):
        try:
            bid_vol=sum([float(b[1]) for b in bids[:20]]); ask_vol=sum([float(a[1]) for a in asks[:20]])
            imb=(bid_vol-ask_vol)/(bid_vol+ask_vol+1e-9)
            spread=(float(asks[0][0])-float(bids[0][0]))/float(bids[0][0])*100
            return imb, spread, bid_vol, ask_vol
        except: return 0,0,0,0
    def feats(self, df, sym):
        df['ema9']=df['c'].ewm(9).mean(); df['ema21']=df['c'].ewm(21).mean(); df['vol_ma']=df['v'].rolling(20).mean()
        df['rsi']=100-(100/(1+df['c'].diff().clip(lower=0).rolling(14).mean()/(df['c'].diff().clip(upper=0).abs().rolling(14).mean()+1e-9)))
        l=df.iloc[-2]
        ob=self.orderbooks.get(sym, {"imb":0,"spread":0,"bvol":0,"avol":0})
        funding=self.funding.get(sym, 0)
        return np.array([[l['c']/l['ema9'], l['c']/l['ema21'], l['v']/(l['vol_ma']+1e-9), l['rsi']/100, ob['imb'], ob['spread'], funding*100, l['c']/df['c'].rolling(50).max().iloc[-2], ob['bvol']/(ob['avol']+1e-9), df['c'].pct_change(5).iloc[-2], df['c'].pct_change(15).iloc[-2], (l['c']-l['o'])/l['o'], l['h']-l['l'], df['v'].pct_change().iloc[-2], 1 if funding>0.01 else 0, 1 if funding<-0.01 else 0, ob['imb']*funding, l['c']/l['vol_ma'] ]])
    def score(self, df, sym):
        try: return self.model.predict_proba(self.feats(df,sym))[0][1]
        except: return 0.5

brain = Brain()

# FIXED WS - NO SPAM
async def mexc_ws_hybrid(symbols, runtime_minutes=340):
    uri = "wss://contract.mexc.com/edge"
    subs=[]
    for sym in symbols:
        mexc_sym = sym.replace('/','').replace(':USDT','').replace('USDT','') + "_USDT"
        subs.append({"method":"sub.depth", "param":{"symbol":mexc_sym}})
        subs.append({"method":"sub.fundingRate", "param":{"symbol":mexc_sym}})
    start = time.time()
    first_connect = True
    while time.time() - start < runtime_minutes*60:
        try:
            async with websockets.connect(uri, ping_interval=20, ping_timeout=20) as ws:
                for s in subs:
                    await ws.send(json.dumps(s))
                    await asyncio.sleep(0.05)
                # TG ONLY FIRST TIME - NO SPAM
                if first_connect:
                    tg(f"📡 *WS Connected* {len(symbols)} syms | {runtime_minutes}m | Compound Every Trade | Live")
                    first_connect = False
                else:
                    print("WS Reconnected (no TG spam)", flush=True)
                while time.time() - start < runtime_minutes*60:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        data = json.loads(msg)
                        if 'data' in data:
                            d=data['data']
                            if 'bids' in d:
                                bids=d.get('bids',[]); asks=d.get('asks',[])
                                imb, spread, bvol, avol = brain.calc_ob(bids, asks)
                                for s in symbols:
                                    if s.split('/')[0] in data.get('symbol',''):
                                        brain.orderbooks[s]={"imb":imb,"spread":spread,"bvol":bvol,"avol":avol}
                            if 'fundingRate' in d or 'rate' in d:
                                rate=float(d.get('fundingRate', d.get('rate',0)))
                                for s in symbols:
                                    if s.split('/')[0] in data.get('symbol',''):
                                        brain.funding[s]=rate
                    except asyncio.TimeoutError:
                        # Fallback REST - no spam
                        for sym in symbols[:8]:
                            try:
                                ob=ex.fetch_order_book(sym, limit=20)
                                imb, spread, bvol, avol = brain.calc_ob(ob['bids'], ob['asks'])
                                brain.orderbooks[sym]={"imb":imb,"spread":spread,"bvol":bvol,"avol":avol}
                            except: pass
                        continue
        except Exception as e:
            print(f"WS Error {e}, reconnect in 10s (no TG)", flush=True)
            await asyncio.sleep(10)

def get_cap():
    d=load(CAP_FILE, {"cap":START_CAP, "day_start":START_CAP, "date":str(datetime.now(PKT).date())})
    today=str(datetime.now(PKT).date())
    if d['date']!=today:
        d['day_start']=d['cap']; d['date']=today; save(CAP_FILE,d)
    return d
def set_cap(new):
    d=get_cap(); d['cap']=new; save(CAP_FILE,d); return d

def pos_size():
    bal_data = ex.fetch_balance()['USDT']
    total = float(bal_data.get('total', START_CAP))
    free = float(bal_data.get('free', total))
    size = total * COMPOUND_EVERY_TRADE
    size = max(1.0, min(free*0.90, size, 3.0))
    return size, total, free

def daily_bias():
    try:
        btc=ex.fetch_ohlcv('BTC/USDT:USDT','1d',limit=100)
        df=pd.DataFrame(btc, columns=['t','o','h','l','c','v'])
        df['ema50']=df['c'].ewm(50).mean()
        last=df.iloc[-2]
        bias="LONG" if last['c']>last['ema50'] else "SHORT" if last['c']<last['ema50']*0.98 else "BOTH"
        tg(f"🌍 *BIAS* BTC ${last['c']:.0f} -> {bias}")
        return bias
    except: return "BOTH"

async def trading_loop(symbols, runtime_minutes=340):
    bias=daily_bias()
    last_day=datetime.now(PKT).date()
    start=time.time()
    while time.time() - start < runtime_minutes*60:
        try:
            cd=get_cap(); cap=cd['cap']; day_start=cd['day_start']
            dpct=(cap-day_start)/day_start*100 if day_start>0 else 0
            if dpct <= -15:
                tg(f"🛑 *DAILY -15% LOCK* ${cap:.2f} ({dpct:.1f}%) Paused till tomorrow")
                while datetime.now(PKT).date()==last_day and time.time()-start < runtime_minutes*60:
                    await asyncio.sleep(60)
                bias=daily_bias(); last_day=datetime.now(PKT).date(); continue

            cands=[]
            for sym in symbols[:30]:
                try:
                    fr=brain.funding.get(sym,0)
                    ob=brain.orderbooks.get(sym)
                    if not ob: continue
                    if ob['spread']>0.15: continue
                    if bias=="LONG" and ob['imb']<-0.35: continue
                    if bias=="SHORT" and ob['imb']>0.35: continue
                    for tf in ['1m','5m','15m']:
                        ohlcv=ex.fetch_ohlcv(sym,tf,limit=100)
                        df=pd.DataFrame(ohlcv, columns=['t','o','h','l','c','v'])
                        if len(df)<60: continue
                        score=brain.score(df,sym)
                        if score>0.72:
                            if fr>0.0008 and score<0.85: continue
                            cands.append((sym,tf,score,ob['imb'],fr))
                            break
                except: continue
            cands.sort(key=lambda x: x[2], reverse=True)
            positions=ex.fetch_positions()
            open_cnt=len([p for p in positions if float(p.get('contracts',0))>0])
            for sym,tf,score,imb,fr in cands[:2]:
                if open_cnt>=MAX_PARALLEL: break
                size_usdt, total_bal, free_bal = pos_size()
                if free_bal < 0.8: break
                side='buy' if imb>0.1 else 'sell'
                if bias=="LONG": side='buy'
                if bias=="SHORT": side='sell'
                if fr>0.0008: side='sell'
                if fr<-0.0008: side='buy'
                try:
                    price=ex.fetch_ticker(sym)['last']
                    qty=size_usdt/price
                    qty = float(ex.amount_to_precision(sym, qty))
                    if qty * price < 1.0: continue
                    ex.set_leverage(LEVERAGE, sym)
                    ex.set_margin_mode('ISOLATED', sym)
                    ex.create_order(sym,'market',side,qty)
                    sl=price*0.993 if side=='buy' else price*1.007
                    try:
                        ex.create_order(sym,'STOP_MARKET','sell' if side=='buy' else 'buy', qty, None, {'stopPrice':sl, 'callbackRate':TRAILING})
                    except: pass
                    tg(f"⚡ *{side.upper()}* {sym} {tf} OB {imb:+.2f} \n💰 ${size_usdt:.2f} (Total ${total_bal:.2f} x30%) Score {score:.2f}")
                    bal=ex.fetch_balance()['USDT']['total']
                    if bal>0: 
                        new_cap=set_cap(bal)['cap']
                        cap=new_cap
                    open_cnt+=1
                    await asyncio.sleep(2)
                except Exception as e: 
                    print(f"Trade error {sym}: {e}", flush=True)
                    await asyncio.sleep(5)
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Loop {e}"); await asyncio.sleep(5)

async def main():
    tickers=ex.fetch_tickers()
    syms=[s for s in ex.markets if s.endswith('USDT:USDT') and s.split('/')[0] not in BLOCK]
    syms=sorted(syms, key=lambda s: tickers.get(s,{}).get('quoteVolume',0), reverse=True)[:15]
    tg(f"🚀 *HFT STARTED* ${START_CAP} | Compound Every Trade | {len(syms)} syms | LEV {LEVERAGE}X | Profit ∞ Loss -15%")
    await asyncio.gather(
        mexc_ws_hybrid(syms, 340),
        trading_loop(syms, 340)
    )

if __name__=="__main__":
    asyncio.run(main())
