"""
Multi-Asset Signal Bot v4
XAU/USD + NAS100 — Zone 70.5%-78.6% + FVG + OB
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
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")

ASSETS = {
    "XAU/USD": {"symbol": "XAU/USD", "sessions": ["london", "ny"], "min_range": 3.0},
    "NAS100":  {"symbol": "NDX",      "sessions": ["ny"],           "min_range": 50.0},
}

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
        return True
    except Exception as e:
        log.error(f"Telegram: {e}")
        return False

def get_candles(symbol, interval, outputsize=50):
    if not TWELVE_API_KEY:
        return None
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_API_KEY}, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            log.error(f"API {symbol}: {data.get('message')}")
            return None
        return [{"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"]), "datetime": c["datetime"]} for c in data.get("values", [])]
    except Exception as e:
        log.error(f"API: {e}")
        return None

def get_session_info():
    now = datetime.now(timezone.utc)
    t = now.hour + now.minute / 60
    active = []
    if 8 <= t < 17: active.append("london")
    if 13 <= t < 22: active.append("ny")
    kz = None
    if 8 <= t < 10: kz = "London Open KZ"
    elif 13 <= t < 15: kz = "New York Open KZ"
    labels = {"london": "London", "ny": "New York"}
    return {"active": active, "sessions": " + ".join(labels[s] for s in active) if active else "Asia", "killzone": kz, "time_gmt": now.strftime("%H:%M GMT")}

def is_market_open(asset_cfg, session_info):
    for s in asset_cfg["sessions"]:
        if s in session_info["active"]:
            return True
    return False

def detect_swing(candles, min_range):
    if len(candles) < 10: return None
    h = max(c["high"] for c in candles)
    l = min(c["low"] for c in candles)
    if h - l < min_range: return None
    return h, l

def get_h4_trend(candles):
    if not candles or len(candles) < 5: return "neutral"
    closes = [c["close"] for c in candles]
    fast = sum(closes[:5]) / 5
    slow = sum(closes[:20]) / 20 if len(closes) >= 20 else fast
    return "bull" if fast > slow else "bear"

def get_h1_structure(candles):
    if not candles or len(candles) < 3: return "neutral"
    bull = sum(1 for c in candles[:3] if c["close"] > c["open"])
    return "bull" if bull >= 2 else "bear"

def detect_fvg(candles, direction, zh, zl):
    fvgs = []
    if len(candles) < 3: return fvgs
    for i in range(len(candles) - 2):
        c0, c1, c2 = candles[i+2], candles[i+1], candles[i]
        if direction == "bull" and c2["low"] > c0["high"]:
            mid = (c2["low"] + c0["high"]) / 2
            if zl <= mid <= zh:
                fvgs.append({"type": "Bull FVG", "top": round(c2["low"], 2), "bot": round(c0["high"], 2)})
        elif direction == "bear" and c2["high"] < c0["low"]:
            mid = (c2["high"] + c0["low"]) / 2
            if zl <= mid <= zh:
                fvgs.append({"type": "Bear FVG", "top": round(c0["low"], 2), "bot": round(c2["high"], 2)})
    return fvgs[-2:] if fvgs else []

def detect_ob(candles, direction, zh, zl):
    obs = []
    if len(candles) < 4: return obs
    for i in range(1, len(candles) - 2):
        ob, nxt = candles[i], candles[i-1]
        if abs(ob["close"] - ob["open"]) < 0.5: continue
        in_zone = zl <= ob["low"] <= zh or zl <= ob["high"] <= zh
        if not in_zone: continue
        if direction == "bull" and ob["close"] < ob["open"] and nxt["close"] > ob["high"]:
            obs.append({"type": "Bull OB", "top": round(ob["high"], 2), "bot": round(ob["low"], 2)})
        elif direction == "bear" and ob["close"] > ob["open"] and nxt["close"] < ob["low"]:
            obs.append({"type": "Bear OB", "top": round(ob["high"], 2), "bot": round(ob["low"], 2)})
    return obs[-2:] if obs else []

def detect_setup(asset_name, price, m5, h1, h4, min_range):
    global last_signal
    swing = detect_swing(m5, min_range)
    if not swing: return None
    high, low = swing
    rng = high - low
    direction = get_h4_trend(h4)
    if direction == "neutral":
        direction = "bull" if m5[0]["close"] > m5[-1]["close"] else "bear"
    h1s = get_h1_structure(h1)
    tol = rng * TOLERANCE_PCT / 100
    for ratio in FIB_LEVELS:
        level = round(high - rng * ratio, 2) if direction == "bull" else round(low + rng * ratio, 2)
        if abs(price - level) > tol: continue
        key = f"{asset_name}_{ratio}"
        if key in last_signal and abs(last_signal[key] - price) < (min_range * 0.05): continue
        l705 = round(high - rng * 0.705, 2) if direction == "bull" else round(low + rng * 0.705, 2)
        l786 = round(high - rng * 0.786, 2) if direction == "bull" else round(low + rng * 0.786, 2)
        zh, zl = max(l705, l786), min(l705, l786)
        fvgs = detect_fvg(m5, direction, zh, zl)
        obs = detect_ob(m5, direction, zh, zl)
        conf = (1 if fvgs else 0) + (1 if obs else 0)
        sd, t1d, t2d = rng*0.05, rng*0.382, rng*0.618
        if direction == "bull":
            sl, tp1, tp2, bias, emoji = round(level-sd,2), round(level+t1d,2), round(level+t2d,2), "BUY", "🟢"
        else:
            sl, tp1, tp2, bias, emoji = round(level+sd,2), round(level-t1d,2), round(level-t2d,2), "SELL", "🔴"
        last_signal[key] = price
        return {"asset": asset_name, "direction": direction, "bias": bias, "emoji": emoji, "fib_label": FIB_LABELS[ratio], "price": round(price,2), "entry": round(level,2), "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": round(t1d/sd,1), "rr2": round(t2d/sd,1), "swing_high": round(high,2), "swing_low": round(low,2), "h4": direction.upper(), "h1": h1s.upper(), "fvgs": fvgs, "obs": obs, "conf": conf, "zh": zh, "zl": zl}
    return None

def format_signal(s, sess):
    kz = f"\n⚡ <b>Killzone:</b> {sess['killzone']}" if sess["killzone"] else ""
    dl = "LONG" if s["direction"] == "bull" else "SHORT"
    stars = "⭐" * s["conf"] if s["conf"] > 0 else "—"
    cl = {0: "Signal simple", 1: "Bonne confluence", 2: "Confluence maximale ✅"}.get(s["conf"], "")
    fvg_txt = f"\n├ {s['fvgs'][-1]['type']}: <code>{s['fvgs'][-1]['bot']}</code>–<code>{s['fvgs'][-1]['top']}</code>" if s["fvgs"] else ""
    ob_txt = f"\n├ {s['obs'][-1]['type']}: <code>{s['obs'][-1]['bot']}</code>–<code>{s['obs'][-1]['top']}</code>" if s["obs"] else ""
    asset_emoji = "🥇" if s["asset"] == "XAU/USD" else "💻"
    return f"""{s['emoji']} <b>SIGNAL {s['asset']} — {s['bias']}</b> {asset_emoji}
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {sess['time_gmt']}
📊 <b>Session:</b> {sess['sessions']}{kz}

📐 <b>Zone Fib {s['fib_label']}</b>
├ Zone: <code>{s['zl']}</code>–<code>{s['zh']}</code>
├ Swing High: <code>{s['swing_high']}</code>
└ Swing Low: <code>{s['swing_low']}</code>

📈 <b>Multi-TF</b>
├ H4: <b>{s['h4']}</b>
└ H1: <b>{s['h1']}</b>

🔍 <b>Confluence SMC</b> {stars}
├ {cl}{fvg_txt}{ob_txt}
└ Zone 70.5%–78.6% ✅

🎯 <b>ORDRE {dl}</b>
├ Entrée: <code>{s['entry']}</code>
├ SL: <code>{s['sl']}</code> 🛑
├ TP1: <code>{s['tp1']}</code> ✅ R:R 1:{s['rr1']}
└ TP2: <code>{s['tp2']}</code> ✅ R:R 1:{s['rr2']}

⚠️ <i>Confirme sur MT4. Max 1% risque.</i>
🤖 Bot v4 · XAU+NAS · SMC+FVG+OB"""

def main():
    log.info("Bot v4 start")
    send_telegram("🤖 <b>Multi-Asset Bot v4</b>\n🥇 XAU/USD — London + NY\n💻 NAS100 — Session NY uniquement\n🔍 Zone 70.5%-78.6% + FVG + OB\n⏱ Scan toutes les 5 min")
    while True:
        try:
            sess = get_session_info()
            log.info(f"Scan — {sess['time_gmt']}")
            for asset_name, cfg in ASSETS.items():
                if not is_market_open(cfg, sess):
                    log.info(f"{asset_name} hors session")
                    continue
                symbol = cfg["symbol"]
                m5 = get_candles(symbol, "5min", 60)
                time.sleep(1)
                h1 = get_candles(symbol, "1h", 24)
                time.sleep(1)
                h4 = get_candles(symbol, "4h", 20)
                if not m5:
                    continue
                price = m5[0]["close"]
                log.info(f"{asset_name}: {price:.2f}")
                setup = detect_setup(asset_name, price, m5, h1 or [], h4 or [], cfg["min_range"])
                if setup:
                    send_telegram(format_signal(setup, sess))
                time.sleep(2)
        except Exception as e:
            log.error(f"Erreur: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
