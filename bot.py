import ccxt, pandas as pd, requests, os
BOT_TOKEN=os.getenv("BOT_TOKEN"); CHAT_ID=os.getenv("CHAT_ID")

def t(m):
    if not BOT_TOKEN or not CHAT_ID:
        print(f"❌ Missing secrets BOT_TOKEN={bool(BOT_TOKEN)} CHAT_ID={bool(CHAT_ID)}")
        return
    try:
        url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r=requests.post(url, data={"chat_id":CHAT_ID,"text":m,"parse_mode":"HTML"}, timeout=15)
        print(f"Telegram sent: {r.status_code} {r.text[:200]}")
        if r.status_code!=200:
            print(f"❌ Telegram failed: {r.text}")
    except Exception as e:
        print(f"❌ Telegram exception: {e}")

t("🔥 If you see this on Telegram, it's FIXED!")
t("📊 Running scan now...")

# Simple scan for test
ex=ccxt.mexc({'enableRateLimit':True})
ex.options['defaultType']='swap'
ex.load_markets()
print(f"Markets loaded: {len(ex.markets)}")

# Test one pair
try:
    ohlcv=ex.fetch_ohlcv('CROSS/USDT:USDT','1m',limit=10)
    print(f"CROSS fetched: {len(ohlcv)} candles")
    t(f"✅ Bot working! CROSS price {ohlcv[-1][4]}")
except Exception as e:
    print(f"Fetch error: {e}")
    t(f"❌ Fetch error: {e}")
