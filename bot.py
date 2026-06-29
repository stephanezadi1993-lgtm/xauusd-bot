"""
XAU/USD + XAG/USD Signal Bot
Zone 78.6% + FVG + OB
SL sous/sur Swing High/Low
Suivi TP/SL + Alerte Breakeven
Sessions : London + NY
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

TD_ASSETS = {
    "XAU/USD": {"symbol": "XAU/USD", "sessions": ["london", "ny"], "min_range": 3.0},
    "XAG/USD": {"symbol": "XAG/USD", "sessions": ["london", "ny"], "min_range": 0.3},
}

FIB_LEVELS = [0.786]
FIB_LABELS = {0.786: "78.6%"}
TOLERANCE_PCT = 0.50
SL_BUFFER_PCT = 0.002

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)
last_signal = {}
active_signals = {}

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

def get_candles_td(symbol, interval, outputsize=60):
    if not TWELVE_API_KEY:
        return None
    try:
        r = requests.get("https://api.twelvedata.com/time_series", params={"symbol": symbol, "interval": interval, "outputsize": outputsize, "apikey": TWELVE_API_KEY}, timeout=10)
        data = r.json()
        if data.get("status") == "error":
            return None
        return [{"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"])} for c in data.get("values", [])]
    except Exception as e:
        log.error(f"TD: {e}")
        return None

def get_current_price(symbol):
    try:
        r = requests.get("https://api.twelvedata.com/price", params={"symbol": symbol, "apikey": TWELVE_API_KEY}, timeout=10)
        data = r.json()
        return float(data["price"]) if "price" in data else None
    except Exception:
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
    labels = {"london": "London 🇬🇧", "ny": "New York 🗽"}
    return {"active": active, "sessions": " + ".join(labels[s] for s in active) if active else "Hors session", "killzone": kz, "time_gmt": now.strftime("%H:%M GMT")}

def is_market_open(sessions, session_info):
    return any(s in session_info["active"] for s in sessions)

def detect_swing(candles, min_range):
    if len(candles) < 10: return None
    h = max(c["high"] for c in candles)
    l = min(c["low"] for c in candles)
    if h - l < min_range: return None
    return h, l

def get_trend(candles):
    if not candles or len(candles) < 5: return "neutral"
    closes = [c["close"] for c in candles]
    fast = sum(closes[:5]) / 5
    slow = sum(closes[:20]) / 20 if len(closes) >= 20 else fast
    return "bull" if fast > slow else "bear"

def get_structure(candles):
    if not candles or len(candles) < 3: return "neutral"
    bull = sum(1 for c in candles[:3] if c["close"] > c["open"])
    return "bull" if bull >= 2 else "bear"

def detect_fvg(candles, direction, zh, zl):
    fvgs = []
    if len(candles) < 3: return fvgs
    for i in range(len(candles) - 2):
        c0, c2 = candles[i+2], candles[i]
        if direction == "bull" and c2["low"] > c0["high"]:
            mid = (c2["low"] + c0["high"]) / 2
            if zl <= mid <= zh:
                fvgs.append({"type": "Bull FVG", "top": round(c2["low"], 4), "bot": round(c0["high"], 4)})
        elif direction == "bear" and c2["high"] < c0["low"]:
            mid = (c2["high"] + c0["low"]) / 2
            if zl <= mid <= zh:
                fvgs.append({"type": "Bear FVG", "top": round(c0["low"], 4), "bot": round(c2["high"], 4)})
    return fvgs[-2:] if fvgs else []

def detect_ob(candles, direction, zh, zl):
    obs = []
    if len(candles) < 4: return obs
    for i in range(1, len(candles) - 2):
        ob, nxt = candles[i], candles[i-1]
        if abs(ob["close"] - ob["open"]) < 0.01: continue
        in_zone = zl <= ob["low"] <= zh or zl <= ob["high"] <= zh
        if not in_zone: continue
        if direction == "bull" and ob["close"] < ob["open"] and nxt["close"] > ob["high"]:
            obs.append({"type": "Bull OB", "top": round(ob["high"], 4), "bot": round(ob["low"], 4)})
        elif direction == "bear" and ob["close"] > ob["open"] and nxt["close"] < ob["low"]:
            obs.append({"type": "Bear OB", "top": round(ob["high"], 4), "bot": round(ob["low"], 4)})
    return obs[-2:] if obs else []

def detect_setup(asset_name, price, m5, h1, h4, min_range, emoji="📊"):
    global last_signal
    swing = detect_swing(m5, min_range)
    if not swing: return None
    high, low = swing
    rng = high - low
    direction = get_trend(h4) if h4 else get_trend(m5)
    if direction == "neutral":
        direction = "bull" if m5[0]["close"] > m5[-1]["close"] else "bear"
    h1s = get_structure(h1) if h1 else "neutral"
    tol = rng * TOLERANCE_PCT / 100
    buffer = rng * SL_BUFFER_PCT
    for ratio in FIB_LEVELS:
        level = round(high - rng * ratio, 4) if direction == "bull" else round(low + rng * ratio, 4)
        if abs(price - level) > tol: continue
        key = f"{asset_name}_{ratio}"
        if key in last_signal and abs(last_signal[key] - price) < (min_range * 0.05): continue
        l786 = round(high - rng * 0.786, 4) if direction == "bull" else round(low + rng * 0.786, 4)
        zh, zl = l786 + (rng * 0.01), l786 - (rng * 0.01)
        fvgs = detect_fvg(m5, direction, zh, zl)
        obs = detect_ob(m5, direction, zh, zl)
        conf = (1 if fvgs else 0) + (1 if obs else 0)
        if conf == 0: continue
        t1d, t2d = rng*0.382, rng*0.618
        if direction == "bull":
            sl = round(low - buffer, 4)
            tp1, tp2 = round(level+t1d,4), round(level+t2d,4)
            bias, sig_emoji = "BUY", "🟢"
        else:
            sl = round(high + buffer, 4)
            tp1, tp2 = round(level-t1d,4), round(level-t2d,4)
            bias, sig_emoji = "SELL", "🔴"
        sl_dist = abs(level - sl)
        if sl_dist == 0: continue
        rr1 = round(abs(tp1 - level) / sl_dist, 1)
        rr2 = round(abs(tp2 - level) / sl_dist, 1)
        be_level = round((level + tp1) / 2, 4)
        last_signal[key] = price
        return {"asset": asset_name, "asset_emoji": emoji, "direction": direction, "bias": bias, "emoji": sig_emoji, "fib_label": FIB_LABELS[ratio], "price": round(price,4), "entry": round(level,4), "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": rr1, "rr2": rr2, "swing_high": round(high,4), "swing_low": round(low,4), "h4": direction.upper(), "h1": h1s.upper(), "fvgs": fvgs, "obs": obs, "conf": conf, "zh": round(zh,4), "zl": round(zl,4), "be_level": be_level}
    return None

def format_signal(s, sess):
    kz = f"\n⚡ <b>Killzone:</b> {sess['killzone']}" if sess.get("killzone") else ""
    dl = "LONG" if s["direction"] == "bull" else "SHORT"
    stars = "⭐" * s["conf"] if s["conf"] > 0 else "—"
    cl = {1: "Bonne confluence ⭐", 2: "Confluence maximale ✅"}.get(s["conf"], "")
    fvg_txt = f"\n├ {s['fvgs'][-1]['type']}: <code>{s['fvgs'][-1]['bot']}</code>–<code>{s['fvgs'][-1]['top']}</code>" if s["fvgs"] else ""
    ob_txt = f"\n├ {s['obs'][-1]['type']}: <code>{s['obs'][-1]['bot']}</code>–<code>{s['obs'][-1]['top']}</code>" if s["obs"] else ""
    sl_note = "sous Swing Low" if s["direction"] == "bull" else "sur Swing High"
    return f"""{s['emoji']} <b>SIGNAL {s['asset']} — {s['bias']}</b> {s['asset_emoji']}
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
└ Zone 78.6% ✅

🎯 <b>ORDRE {dl}</b>
├ Entrée: <code>{s['entry']}</code>
├ SL: <code>{s['sl']}</code> 🛑 ({sl_note})
├ Breakeven à: <code>{s['be_level']}</code> ⚖️
├ TP1: <code>{s['tp1']}</code> ✅ R:R 1:{s['rr1']}
└ TP2: <code>{s['tp2']}</code> ✅ R:R 1:{s['rr2']}

⚠️ <i>Confirme avant d'entrer. Max 1% risque.</i>
🤖 Signal Bot · Zone 78.6%"""

def check_active_signals():
    global active_signals
    if not active_signals: return
    now = datetime.now(timezone.utc).strftime("%H:%M GMT")
    to_remove = []
    for key, sig in list(active_signals.items()):
        price = get_current_price(sig["asset"])
        if not price: continue
        direction = sig["direction"]
        tp1, tp2, sl = sig["tp1"], sig["tp2"], sig["sl"]
        entry, be_level = sig["entry"], sig["be_level"]
        if not sig.get("be_hit"):
            if (direction == "bull" and price >= be_level) or (direction == "bear" and price <= be_level):
                send_telegram(f"""⚖️ <b>BREAKEVEN — {sig['asset']}</b>
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {now}
💰 <b>Prix actuel:</b> <code>{price:.2f}</code>
📥 <b>Entrée:</b> <code>{entry}</code>

🔔 <b>Place ton SL à l'entrée !</b>
SL → <code>{entry}</code> (Breakeven)
━━━━━━━━━━━━━━━━━━━━""")
                active_signals[key]["be_hit"] = True
        result = None
        if direction == "bull":
            if price >= tp2: result = ("🚀", "TP2 ATTEINT")
            elif price >= tp1 and not sig.get("tp1_hit"): result = ("✅", "TP1 ATTEINT")
            elif price <= sl: result = ("❌", "SL TOUCHÉ")
        else:
            if price <= tp2: result = ("🚀", "TP2 ATTEINT")
            elif price <= tp1 and not sig.get("tp1_hit"): result = ("✅", "TP1 ATTEINT")
            elif price >= sl: result = ("❌", "SL TOUCHÉ")
        if result:
            emoji, label = result
            if label == "TP1 ATTEINT":
                active_signals[key]["tp1_hit"] = True
            send_telegram(f"""{emoji} <b>Suivi {sig['asset']} — {label}</b>
━━━━━━━━━━━━━━━━━━━━
🕐 <b>Heure:</b> {now}
💰 <b>Prix actuel:</b> <code>{price:.2f}</code>
📥 <b>Entrée:</b> <code>{entry}</code>
🛑 <b>SL:</b> <code>{sl}</code>
✅ <b>TP1:</b> <code>{tp1}</code>
🚀 <b>TP2:</b> <code>{tp2}</code>
━━━━━━━━━━━━━━━━━━━━""")
            if label in ("TP2 ATTEINT", "SL TOUCHÉ"):
                to_remove.append(key)
    for key in to_remove:
        active_signals.pop(key, None)

def main():
    log.info("Bot start")
    send_telegram("🤖 <b>Signal Bot</b>\n🥇 XAU/USD — London + NY\n🥈 XAG/USD — London + NY\n🔍 Zone 78.6% + FVG + OB\n🛑 SL sous/sur Swing High/Low\n⚖️ Alerte Breakeven\n📬 Suivi TP/SL automatique\n⏱ Scan toutes les 5 min")
    while True:
        try:
            sess = get_session_info()
            log.info(f"Scan {sess['time_gmt']}")
            check_active_signals()
            for asset_name, cfg in TD_ASSETS.items():
                if not is_market_open(cfg["sessions"], sess):
                    continue
                m5 = get_candles_td(cfg["symbol"], "5min", 60)
                time.sleep(2)
                h1 = get_candles_td(cfg["symbol"], "1h", 24)
                time.sleep(2)
                h4 = get_candles_td(cfg["symbol"], "4h", 20)
                if not m5: continue
                price = m5[0]["close"]
                emoji = "🥇" if asset_name == "XAU/USD" else "🥈"
                setup = detect_setup(asset_name, price, m5, h1 or [], h4 or [], cfg["min_range"], emoji)
                if setup:
                    send_telegram(format_signal(setup, sess))
                    active_signals[f"{asset_name}_{setup['fib_label']}"] = setup
                    log.info(f"Signal {asset_name} {setup['bias']}")
                time.sleep(2)
        except Exception as e:
            log.error(f"Erreur: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
