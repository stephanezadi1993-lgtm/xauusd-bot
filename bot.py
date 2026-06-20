"""
Multi-Asset Signal Bot v5
XAU/USD + NAS100 + BTC/USD + Tous les Synthetics Deriv
Zone 78.6% + FVG + OB
"""
import os
import time
import json
import logging
import requests
import websocket
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
TWELVE_API_KEY = os.getenv("TWELVE_API_KEY")
DERIV_TOKEN = os.getenv("DERIV_TOKEN")

TD_ASSETS = {
    "XAU/USD": {"symbol": "XAU/USD", "sessions": ["london", "ny"], "min_range": 3.0},
    "NAS100":  {"symbol": "NDX",      "sessions": ["ny"],           "min_range": 50.0},
    "BTC/USD": {"symbol": "BTC/USD",  "sessions": ["24h"],          "min_range": 200.0},
}

DERIV_ASSETS = {
    "V10":       {"symbol": "R_10",      "min_range": 0.3,  "emoji": "🔵", "spike_filter": False},
    "V25":       {"symbol": "R_25",      "min_range": 0.8,  "emoji": "🟣", "spike_filter": False},
    "V50":       {"symbol": "R_50",      "min_range": 1.5,  "emoji": "🟡", "spike_filter": False},
    "V75":       {"symbol": "R_75",      "min_range": 3.0,  "emoji": "🟠", "spike_filter": False},
    "V100":      {"symbol": "R_100",     "min_range": 5.0,  "emoji": "🔴", "spike_filter": False},
    "V10(1s)":   {"symbol": "1HZ10V",   "min_range": 0.3,  "emoji": "🔵", "spike_filter": False},
    "V25(1s)":   {"symbol": "1HZ25V",   "min_range": 0.8,  "emoji": "🟣", "spike_filter": False},
    "V50(1s)":   {"symbol": "1HZ50V",   "min_range": 1.5,  "emoji": "🟡", "spike_filter": False},
    "V75(1s)":   {"symbol": "1HZ75V",   "min_range": 3.0,  "emoji": "🟠", "spike_filter": False},
    "V100(1s)":  {"symbol": "1HZ100V",  "min_range": 5.0,  "emoji": "🔴", "spike_filter": False},
    "BOOM300":   {"symbol": "BOOM300N",  "min_range": 5.0,  "emoji": "🚀", "spike_filter": True},
    "BOOM500":   {"symbol": "BOOM500",   "min_range": 5.0,  "emoji": "🚀", "spike_filter": True},
    "BOOM600":   {"symbol": "BOOM600",   "min_range": 5.0,  "emoji": "🚀", "spike_filter": True},
    "BOOM900":   {"symbol": "BOOM900",   "min_range": 5.0,  "emoji": "🚀", "spike_filter": True},
    "BOOM1000":  {"symbol": "BOOM1000",  "min_range": 5.0,  "emoji": "🚀", "spike_filter": True},
    "CRASH300":  {"symbol": "CRASH300N", "min_range": 5.0,  "emoji": "💥", "spike_filter": True},
    "CRASH500":  {"symbol": "CRASH500",  "min_range": 5.0,  "emoji": "💥", "spike_filter": True},
    "CRASH600":  {"symbol": "CRASH600",  "min_range": 5.0,  "emoji": "💥", "spike_filter": True},
    "CRASH900":  {"symbol": "CRASH900",  "min_range": 5.0,  "emoji": "💥", "spike_filter": True},
    "CRASH1000": {"symbol": "CRASH1000", "min_range": 5.0,  "emoji": "💥", "spike_filter": True},
    "J10":       {"symbol": "JD10",      "min_range": 1.0,  "emoji": "⚡", "spike_filter": True},
    "J25":       {"symbol": "JD25",      "min_range": 2.0,  "emoji": "⚡", "spike_filter": True},
    "J50":       {"symbol": "JD50",      "min_range": 3.0,  "emoji": "⚡", "spike_filter": True},
    "J75":       {"symbol": "JD75",      "min_range": 4.0,  "emoji": "⚡", "spike_filter": True},
    "J100":      {"symbol": "JD100",     "min_range": 5.0,  "emoji": "⚡", "spike_filter": True},
    "STEP":      {"symbol": "stpindx",   "min_range": 0.1,  "emoji": "📶", "spike_filter": False},
}

FIB_LEVELS = [0.786]
FIB_LABELS = {0.786: "78.6%"}
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

def get_deriv_candles(symbol, granularity=300, count=60):
    if not DERIV_TOKEN:
        return None
    try:
        ws = websocket.create_connection("wss://ws.derivws.com/websockets/v3?app_id=1089", timeout=15)
        ws.send(json.dumps({"authorize": DERIV_TOKEN}))
        auth = json.loads(ws.recv())
        if auth.get("error"):
            ws.close()
            return None
        ws.send(json.dumps({"ticks_history": symbol, "adjust_start_time": 1, "count": count, "end": "latest", "granularity": granularity, "style": "candles"}))
        resp = json.loads(ws.recv())
        ws.close()
        if resp.get("error"):
            log.error(f"Deriv {symbol}: {resp['error']['message']}")
            return None
        result = []
        for c in reversed(resp.get("candles", [])):
            result.append({"open": float(c["open"]), "high": float(c["high"]), "low": float(c["low"]), "close": float(c["close"])})
        return result if result else None
    except Exception as e:
        log.error(f"Deriv WS {symbol}: {e}")
        return None

def filter_spikes(candles, multiplier=3.0):
    if not candles or len(candles) < 5:
        return candles
    ranges = [abs(c["high"] - c["low"]) for c in candles]
    avg_range = sum(ranges) / len(ranges)
    filtered = []
    for c in candles:
        rng = abs(c["high"] - c["low"])
        if rng > avg_range * multiplier:
            c = {"open": c["open"], "high": max(c["open"], c["close"]), "low": min(c["open"], c["close"]), "close": c["close"]}
        filtered.append(c)
    return filtered

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

def is_market_open(sessions, session_info):
    if "24h" in sessions:
        return True
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
        sd, t1d, t2d = rng*0.05, rng*0.382, rng*0.618
        if direction == "bull":
            sl, tp1, tp2, bias, sig_emoji = round(level-sd,4), round(level+t1d,4), round(level+t2d,4), "BUY", "🟢"
        else:
            sl, tp1, tp2, bias, sig_emoji = round(level+sd,4), round(level-t1d,4), round(level-t2d,4), "SELL", "🔴"
        last_signal[key] = price
        return {"asset": asset_name, "asset_emoji": emoji, "direction": direction, "bias": bias, "emoji": sig_emoji, "fib_label": FIB_LABELS[ratio], "price": round(price,4), "entry": round(level,4), "sl": sl, "tp1": tp1, "tp2": tp2, "rr1": round(t1d/sd,1), "rr2": round(t2d/sd,1), "swing_high": round(high,4), "swing_low": round(low,4), "h4": direction.upper(), "h1": h1s.upper(), "fvgs": fvgs, "obs": obs, "conf": conf, "zh": round(zh,4), "zl": round(zl,4)}
    return None

def format_signal(s, sess):
    kz = f"\n⚡ <b>Killzone:</b> {sess['killzone']}" if sess.get("killzone") else ""
    dl = "LONG" if s["direction"] == "bull" else "SHORT"
    stars = "⭐" * s["conf"] if s["conf"] > 0 else "—"
    cl = {0: "Signal simple", 1: "Bonne confluence", 2: "Confluence maximale ✅"}.get(s["conf"], "")
    fvg_txt = f"\n├ {s['fvgs'][-1]['type']}: <code>{s['fvgs'][-1]['bot']}</code>–<code>{s['fvgs'][-1]['top']}</code>" if s["fvgs"] else ""
    ob_txt = f"\n├ {s['obs'][-1]['type']}: <code>{s['obs'][-1]['bot']}</code>–<code>{s['obs'][-1]['top']}</code>" if s["obs"] else ""
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
├ SL: <code>{s['sl']}</code> 🛑
├ TP1: <code>{s['tp1']}</code> ✅ R:R 1:{s['rr1']}
└ TP2: <code>{s['tp2']}</code> ✅ R:R 1:{s['rr2']}

⚠️ <i>Confirme avant d'entrer. Max 1% risque.</i>
🤖 Bot v5 · XAU+NAS+BTC+Synthetics"""

def main():
    log.info("Bot v5 start")
    send_telegram("🤖 <b>Multi-Asset Bot v5</b>\n🥇 XAU/USD — London + NY\n💻 NAS100 — NY\n₿ BTC/USD — 24h/24\n🔵 V10/V25/V50/V75/V100\n🔵 V10(1s)/V25(1s)/V50(1s)/V75(1s)/V100(1s)\n🚀 BOOM 300/500/600/900/1000\n💥 CRASH 300/500/600/900/1000\n⚡ J10/J25/J50/J75/J100\n📶 Step Index\n🔍 Zone 78.6% + FVG + OB\n⏱ Scan toutes les 5 min")
    while True:
        try:
            sess = get_session_info()
            log.info(f"Scan {sess['time_gmt']}")
            for asset_name, cfg in TD_ASSETS.items():
                if not is_market_open(cfg["sessions"], sess):
                    continue
                m5 = get_candles_td(cfg["symbol"], "5min", 60)
                time.sleep(1)
                h1 = get_candles_td(cfg["symbol"], "1h", 24)
                time.sleep(1)
                h4 = get_candles_td(cfg["symbol"], "4h", 20)
                if not m5: continue
                price = m5[0]["close"]
                emoji = "🥇" if asset_name == "XAU/USD" else ("💻" if asset_name == "NAS100" else "₿")
                setup = detect_setup(asset_name, price, m5, h1 or [], h4 or [], cfg["min_range"], emoji)
                if setup:
                    send_telegram(format_signal(setup, sess))
                time.sleep(2)
            for asset_name, cfg in DERIV_ASSETS.items():
                log.info(f"Analyse {asset_name}")
                m5 = get_deriv_candles(cfg["symbol"], 300, 60)
                time.sleep(1)
                h1 = get_deriv_candles(cfg["symbol"], 3600, 24)
                time.sleep(1)
                h4 = get_deriv_candles(cfg["symbol"], 14400, 20)
                if not m5: continue
                if cfg["spike_filter"]:
                    m5 = filter_spikes(m5)
                    if h1: h1 = filter_spikes(h1)
                price = m5[0]["close"]
                log.info(f"{asset_name}: {price:.4f}")
                setup = detect_setup(asset_name, price, m5, h1 or [], h4 or [], cfg["min_range"], cfg["emoji"])
                if setup:
                    synth_sess = {"time_gmt": sess["time_gmt"], "sessions": "24h/24 🎰", "killzone": None}
                    send_telegram(format_signal(setup, synth_sess))
                time.sleep(2)
        except Exception as e:
            log.error(f"Erreur: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
