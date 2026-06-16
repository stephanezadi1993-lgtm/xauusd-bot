"""
XAU/USD Fibonacci Signal Bot v3
Zone 70.5%-78.6% + FVG + Order Block detection
Analyse M5 + H1 + H4
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

def detect_fvg(candles, direction, fib_zone_high, fib_zone_low):
    fvg_list = []
    if len(candles) < 3:
        return fvg_list
    for i in range(len(candles) - 2):
        c0 = candles[i + 2]
        c1 = candles[i + 1]
        c2 = candles[i]
        if direction == "bull":
            if c2["low"] > c0["high"]:
                fvg_mid = (c2["low"] + c0["high"]) / 2
                if fib_zone_low <= fvg_mid <= fib_zone_high:
                    fvg_list.append({"type": "Bull FVG", "top": round(c2["low"], 2), "bot": round(c0["high"], 2), "mid": round(fvg_mid, 2), "datetime": c1["datetime"]})
        else:
            if c2["high"] < c0["low"]:
                fvg_mid = (c2["high"] + c0["low"]) / 2
                if fib_zone_low <= fvg_mid <= fib_zone_high:
                    fvg_list.append({"type": "Bear FVG", "top": round(c0["low"], 2), "bot": round(c2["high"], 2), "mid": round(fvg_mid, 2), "datetime": c1["datetime"]})
    return fvg_list[-3:] if fvg_list else []

def detect_orderblock(candles, direction, fib_zone_high, fib_zone_low):
    ob_list = []
    if len(candles) < 4:
        return ob_list
    for i in range(1, len(candles) - 2):
        c_ob   = candles[i]
        c_next = candles[i - 1]
        ob_size = abs(c_ob["close"] - c_ob["open"])
        if ob_size < 0.5:
            continue
        ob_in_zone = fib_zone_low <= c_ob["low"] <= fib_zone_high or fib_zone_low <= c_ob["high"] <= fib_zone_high
        if direction == "bull":
            if c_ob["close"] < c_ob["open"] and c_next["close"] > c_ob["high"] and ob_in_zone:
                ob_list.append({"type": "Bull OB", "top": round(c_ob["high"], 2), "bot": round(c_ob["low"], 2), "mid": round((c_ob["high"] + c_ob["low"]) / 2, 2), "datetime": c_ob["datetime"]})
        else:
            if c_ob["close"] > c_ob["open"] and c_next["close"] < c_ob["low"] and ob_in_zone:
                ob_list.append({"type": "Bear OB", "top": round(c_ob["high"], 2), "bot": round(c_ob["low"], 2), "mid": round((c_ob["high"] + c_ob["low"]) / 2, 2), "datetime": c_ob["datetime"]})
    return ob_list[-2:] if ob_list else []

def detect_setup(price, m5, h1, h4):
    global last_signal
    swing = detect_swing(m5)
    if not swing: return None
    high, low = swing
    rng = high - low
    h4_trend  = get_h4_trend(h4)
    h1_struct = get_h1_structure(h1)
    direction = h4_trend if h4_trend != "neutral" else ("bull" if m5[0]["close"] > m5[-1]["close"] else "bear")
    tolerance = rng * TOLERANCE_PCT / 100
    for ratio in FIB_LEVELS:
        level = round(high - rng * ratio, 2) if direction == "bull" else round(low + rng * ratio, 2)
        if abs(price - level) > tolerance:
            continue
        if ratio in last_signal and abs(last_signal[ratio] - price) < 2.0:
            continue
        level_705 = round(high - rng * 0.705, 2) if direction == "bull" else round(low + rng * 0.705, 2)
        level_786 = round(high - rng * 0.786, 2) if direction == "bull" else round(low + rng * 0.786, 2)
        fib_zone_high = max(level_705, level_786)
        fib_zone_low  = min(level_705, level_786)
        fvg_list = detect_fvg(m5, direction, fib_zone_high, fib_zone_low)
        ob_list  = detect_orderblock(m5, direction, fib_zone_high, fib_zone_low)
        confluence_score = (1 if fvg_list else 0) + (1 if ob_list else 0)
        sl_dist, tp1_dist, tp2_dist = rng * 0.05, rng * 0.382, rng * 0.618
        if direction == "bull":
            sl, tp1, tp2, bias, emoji = round(level - sl_dist, 2), round(level + tp1_dist, 2), round(level + tp2_dist, 2), "BUY", "🟢"
        else:
            sl, tp1, tp2, bias, emoji = round(level + sl_dist, 2), round(level - tp1_dist, 2), round(level - tp2_dist, 2), "SELL", "🔴"
        last_signal[ratio] = price
        return {"direction": direction, "bias": bias, "emoji": emoji, "fib_label": FIB_LABELS[ratio], "price": round(price, 2), "entry": round(level, 2), "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": round(tp1_dist/sl_dist, 1), "rr2": round(tp2_dist/sl_dist, 1), "swing_high": round(high, 2), "swing_low": round(low, 2), "h4_trend": h4_trend.upper(), "h1_struct": h1_struct.upper(), "fvg_list": fvg_list, "ob_list": ob_list, "confluence": confluence_score, "fib_zone_high": fib_zone_high, "fib_zone_low": fib_zone_low}
    return None

def format_signal(s, session):
    kz = f"\n⚡ <b>Killzone:</b> {session['killzone']}" if session["killzone"] else ""
    dl = "LONG" if s["direction"] == "bull" else "SHORT"
    stars = "⭐" * s["confluence"] if s["confluence"] > 0 else "—"
    conf_label = {0: "Signal simple", 1: "Bonne confluence", 2: "Confluence maximale ✅"}.get(s["confluence"], "")
    fvg_text = ""
    if s["fvg_list"]:
        fvg = s["fvg_list"][-1]
        fvg_text = f"\n├ {fvg['type']}: <code>{fvg['bot']}</code> – <code>{fvg['top']}</code>"
    ob_text = ""
    if s["ob_list"]:
        ob = s["ob_list"][-1]
        ob_text = f"\n├ {ob['type']}: <code>{ob['bot']}</code> – <code>{ob['top']}</code>"
    return f"""{s['emoji']} <b>SIGNAL XAU/USD — {s['bias']}</b>
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {session['time_gmt']}
📊 <b>Session:</b> {session['sessions']}{kz}

📐 <b>Zone Fibonacci {s['fib_label']}</b>
├ Zone: <code>{s['fib_zone_low']}</code> – <code>{s['fib_zone_high']}</code>
├ Swing High: <code>{s['swing_high']}</code>
└ Swing Low:  <code>{s['swing_low']}</code>

📈 <b>Multi-TF</b>
├ H4: <b>{s['h4_trend']}</b>
└ H1: <b>{s['h1_struct']}</b>

🔍 <b>Confluence SMC</b> {stars}
├ {conf_label}{fvg_text}{ob_text}
└ Zone 70.5%–78.6% ✅

🎯 <b>ORDRE {dl}</b>
├ Entrée:    <code>{s['entry']}</code>
├ Stop Loss: <code>{s['sl']}</code> 🛑
├ TP 1:      <code>{s['tp1']}</code> ✅ R:R 1:{s['rr1']}
└ TP 2:      <code>{s['tp2']}</code> ✅ R:R 1:{s['rr2']}

⚠️ <i>Confirme sur MT4. Risque max 1%.</i>
🤖 XAU/USD Bot v3 · SMC+FVG+OB"""

def main():
    log.info("Bot v3 démarré")
    send_telegram("🤖 <b>XAU/USD Bot v3 démarré</b>\n🔍 Zone 70.5%-78.6% + FVG + OB\n⏱ Scan toutes les 5 min")
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
