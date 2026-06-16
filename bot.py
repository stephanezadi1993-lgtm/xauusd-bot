"""
XAU/USD Fibonacci Signal Bot v2
Vraies bougies OHLC via Twelve Data API
Analyse M5 + confirmation H1 + H4
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", "300"))
TWELVE_API_KEY   = os.getenv("TWELVE_API_KEY")

SYMBOL = "XAU/USD"
FIB_LEVELS = [0.705, 0.786]
FIB_LABELS = {0.705: "70.5%", 0.786: "78.6%"}
TOLERANCE_PCT = 0.50

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)
last_signal = {}

def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=10)
        r.raise_for_status()
        log.info("Signal envoyé")
        return True
    except Exception as e:
        log.error(f"Erreur Telegram: {e}")
        return False

def get_candles(interval, outputsize=50):
    if not TWELVE_API_KEY:
        return None
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": SYMBOL, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_API_KEY}
    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            log.error(f"Twelve Data: {data.get('message')}")
            return None
        return [{"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"]), "datetime": c["datetime"]} for c in data.get("values", [])]
    except Exception as e:
        log.error(f"Erreur API: {e}")
        return None

def get_session_info():
    now = datetime.now(timezone.utc)
    t = now.hour + now.minute / 60
    sessions = []
    if 8 <= t < 17: sessions.append("London")
    if 13 <= t < 22: sessions.append("New York")
    if not sessions: sessions.append("Asia")
    killzone = None
    if 8 <= t < 10: killzone = "London Open KZ"
    elif 13 <= t < 15: killzone = "New York Open KZ"
    return {"sessions": " + ".join(sessions), "killzone": killzone, "time_gmt": now.strftime("%H:%M GMT")}

def detect_swing(candles):
    if len(candles) < 10: return None
    high = max(c["high"] for c in candles)
    low  = min(c["low"]  for c in candles)
    if high - low < 3.0: return None
    return high, low

def get_h4_trend(candles):
    if not candles or len(candles) < 5: return "neutral"
    closes = [c["close"] for c in candles]
    ema_fast = sum(closes[:5]) / 5
    ema_slow = sum(closes[:20]) / 20 if len(closes) >= 20 else ema_fast
    return "bull" if ema_fast > ema_slow else "bear"

def get_h1_structure(candles):
    if not candles or len(candles) < 3: return "neutral"
    bull = sum(1 for c in candles[:3] if c["close"] > c["open"])
    return "bull" if bull >= 2 else "bear"

def detect_setup(price, m5, h1, h4):
    global last_signal
    swing = detect_swing(m5)
    if not swing: return None
    high, low = swing
    rng = high - low
    h4_trend  = get_h4_trend(h4)
    h1_struct = get_h1_structure(h1)
    direction = h4_trend if h4_trend != "neutral" else ("bull" if m5[0]["close"] > m5[-1]["close"] else "bear")
    fib_levels = {}
    for ratio in FIB_LEVELS:
        fib_levels[ratio] = round(high - rng * ratio, 2) if direction == "bull" else round(low + rng * ratio, 2)
    tolerance = rng * TOLERANCE_PCT / 100
    for ratio, level in fib_levels.items():
        if abs(price - level) <= tolerance:
            if ratio in last_signal and abs(last_signal[ratio] - price) < 2.0:
                return None
            sl_d, tp1_d, tp2_d = rng * 0.05, rng * 0.382, rng * 0.618
            if direction == "bull":
                sl, tp1, tp2, bias, emoji = round(level - sl_d, 2), round(level + tp1_d, 2), round(level + tp2_d, 2), "BUY", "🟢"
            else:
                sl, tp1, tp2, bias, emoji = round(level + sl_d, 2), round(level - tp1_d, 2), round(level - tp2_d, 2), "SELL", "🔴"
            last_signal[ratio] = price
            return {"direction": direction, "bias": bias, "emoji": emoji, "fib_label": FIB_LABELS[ratio],
                    "price": round(price, 2), "entry": round(level, 2), "sl": sl, "tp1": tp1, "tp2": tp2,
                    "rr1": round(tp1_d/sl_d, 1), "rr2": round(tp2_d/sl_d, 1),
                    "swing_high": round(high, 2), "swing_low": round(low, 2),
                    "h4_trend": h4_trend.upper(), "h1_struct": h1_struct.upper()}
    return None

def format_signal(s, session):
    kz = f"\n⚡ <b>Killzone:</b> {session['killzone']}" if session["killzone"] else ""
    dl = "LONG" if s["direction"] == "bull" else "SHORT"
    return f"""{s['emoji']} <b>SIGNAL XAU/USD — {s['bias']}</b>
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {session['time_gmt']}
📊 <b>Session:</b> {session['sessions']}{kz}

📐 <b>Fibonacci {s['fib_label']}</b>
├ Swing High: <code>{s['swing_high']}</code>
└ Swing Low:  <code>{s['swing_low']}</code>

📈 <b>Multi-TF</b>
├ H4: <b>{s['h4_trend']}</b>
└ H1: <b>{s['h1_struct']}</b>

🎯 <b>ORDRE {dl}</b>
├ Entrée:    <code>{s['entry']}</code>
├ Stop Loss: <code>{s['sl']}</code> 🛑
├ TP 1:      <code>{s['tp1']}</code> ✅ R:R 1:{s['rr1']}
└ TP 2:      <code>{s['tp2']}</code> ✅ R:R 1:{s['rr2']}

⚠️ <i>Confirme sur MT4. Risque max 1%.</i>
🤖 XAU/USD Bot v2 · M5+H1+H4"""

def main():
    log.info("Bot v2 démarré")
    send_telegram("🤖 <b>XAU/USD Fibonacci Bot v2</b>\n📊 Analyse M5 + H1 + H4\n⏱ Scan toutes les 5 min")
    while True:
        try:
            m5 = get_candles("5min", 60)
            h1 = get_candles("1h", 24)
            h4 = get_candles("4h", 20)
            if not m5:
                time.sleep(60)
                continue
            price = m5[0]["close"]
            log.info(f"Prix: {price:.2f}")
            setup = detect_setup(price, m5, h1 or [], h4 or [])
            if setup:
                send_telegram(format_signal(setup, get_session_info()))
        except Exception as e:
            log.error(f"Erreur: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
