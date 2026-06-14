"""
XAU/USD Fibonacci Signal Bot
Détecte les setups Fibonacci sur XAU/USD et envoie les signaux via Telegram
"""

import os
import time
import logging
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))

FIB_LEVELS = [0.382, 0.500, 0.618, 0.786]
FIB_LABELS = {0.382: "38.2%", 0.500: "50%", 0.618: "61.8% 🔑", 0.786: "78.6%"}
TOLERANCE_PCT = 0.15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

last_signal_price = None
last_signal_level = None
price_history = []
MAX_HISTORY = 60

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

def get_price():
    try:
        r = requests.get("https://api.metals.live/v1/spot/gold", timeout=8)
        data = r.json()
        if data and isinstance(data, list) and "gold" in data[0]:
            return float(data[0]["gold"])
    except Exception:
        pass
    try:
        r = requests.get("https://data-asg.goldprice.org/dbXRates/USD", headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
        data = r.json()
        if data and "items" in data and data["items"]:
            return float(data["items"][0]["xauPrice"])
    except Exception:
        pass
    return None

def get_session_info():
    now = datetime.now(timezone.utc)
    h, m = now.hour, now.minute
    t = h + m / 60
    sessions = []
    if 8 <= t < 17: sessions.append("London")
    if 13 <= t < 22: sessions.append("New York")
    if not sessions: sessions.append("Asia/Off-hours")
    killzone = None
    if 8 <= t < 10: killzone = "London Open KZ"
    elif 13 <= t < 15: killzone = "New York Open KZ"
    return {"sessions": " + ".join(sessions), "killzone": killzone, "time_gmt": now.strftime("%H:%M GMT")}

def detect_swing(prices):
    if len(prices) < 10: return None
    high, low = max(prices), min(prices)
    if high - low < 5.0: return None
    return high, low

def calc_fib_levels(high, low, direction):
    rng = high - low
    levels = {}
    for ratio in FIB_LEVELS:
        levels[ratio] = high - rng * ratio if direction == "bull" else low + rng * ratio
    return levels

def detect_setup(price, prices):
    global last_signal_price, last_signal_level
    swing = detect_swing(prices)
    if not swing: return None
    high, low = swing
    rng = high - low
    tolerance = rng * TOLERANCE_PCT / 100
    recent = prices[-10:] if len(prices) >= 10 else prices
    direction = "bull" if recent[-1] > recent[0] else "bear"
    fib_levels = calc_fib_levels(high, low, direction)
    for ratio, level_price in fib_levels.items():
        if abs(price - level_price) <= tolerance:
            if last_signal_level == ratio and last_signal_price and abs(price - last_signal_price) < 2.0:
                return None
            sl_dist = rng * 0.05
            tp1_dist = rng * 0.382
            tp2_dist = rng * 0.618
            if direction == "bull":
                sl = round(level_price - sl_dist, 2)
                tp1 = round(level_price + tp1_dist, 2)
                tp2 = round(level_price + tp2_dist, 2)
                bias, emoji = "BUY", "🟢"
            else:
                sl = round(level_price + sl_dist, 2)
                tp1 = round(level_price - tp1_dist, 2)
                tp2 = round(level_price - tp2_dist, 2)
                bias, emoji = "SELL", "🔴"
            last_signal_price = price
            last_signal_level = ratio
            return {"direction": direction, "bias": bias, "emoji": emoji, "fib_label": FIB_LABELS[ratio],
                    "price": round(price, 2), "entry": round(level_price, 2), "sl": sl, "tp1": tp1, "tp2": tp2,
                    "rr1": round(tp1_dist/sl_dist,1), "rr2": round(tp2_dist/sl_dist,1),
                    "swing_high": round(high,2), "swing_low": round(low,2)}
    return None

def format_signal(setup, session):
    kz = f"\n⚡ <b>Killzone:</b> {session['killzone']}" if session["killzone"] else ""
    direction_line = "LONG" if setup["direction"] == "bull" else "SHORT"
    return f"""{setup['emoji']} <b>SIGNAL XAU/USD — {setup['bias']} 📈</b>
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {session['time_gmt']}
📊 <b>Session:</b> {session['sessions']}{kz}

📐 <b>Setup Fibonacci {setup['fib_label']}</b>
├ Swing High: <code>{setup['swing_high']}</code>
└ Swing Low:  <code>{setup['swing_low']}</code>

🎯 <b>ORDRE {direction_line}</b>
├ Entrée:    <code>{setup['entry']}</code>
├ Stop Loss: <code>{setup['sl']}</code> 🛑
├ TP 1:      <code>{setup['tp1']}</code> ✅ R:R 1:{setup['rr1']}
└ TP 2:      <code>{setup['tp2']}</code> ✅ R:R 1:{setup['rr2']}

⚠️ <i>Confirme H1/H4. Risque max 1%.</i>
🤖 XAU/USD Fib Bot"""

def main():
    log.info("Bot démarré")
    send_telegram("🤖 <b>XAU/USD Fibonacci Bot démarré</b>\nScan toutes les 5 min")
    while True:
        try:
            price = get_price()
            if price is None:
                time.sleep(60)
                continue
            log.info(f"Prix: {price:.2f}")
            price_history.append(price)
            if len(price_history) > MAX_HISTORY:
                price_history.pop(0)
            setup = detect_setup(price, price_history)
            if setup:
                send_telegram(format_signal(setup, get_session_info()))
        except Exception as e:
            log.error(f"Erreur: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
