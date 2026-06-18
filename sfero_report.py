#!/usr/bin/env python3
"""
SFERO Meta Ads Daily Report — sends to Telegram directly
Usage:   python3 sfero_report.py
Cron:    0 7 * * * python3 /path/sfero_report.py   (09:00 Spain = 07:00 UTC)
"""
import urllib.request, urllib.parse, json
from datetime import datetime, timedelta

# ─── CONFIG (update token when it expires) ───────────────────────────────────
META_TOKEN   = "EAASydDZC4n4MBRrq9BucPUMEC8TBDXfabdg1yDwOOfM9oAi4sk1dpyUTGDiZCJr2CNShyrz69ZCvK3oCRKe84FfQtzwlN6bE8ZAwzrYKLFsdZAZAwRpps8S66dTdXCS3jJAMZA1507v6yP4T4EjPEWUkApgJCApjwnxRJAAHOERGp0brLdZACGMWEtt8zaZCC58Px5Df4uRSqZBLZBudWZBrHuWcHXSQQysF6nvJZBNAZCZBgnk56dpXiEoWXNzRsrA69phCcKEZBoyEMS4j6s3w0cJa57u4SCGI"
AD_ACCOUNT   = "act_445844598148716"
TG_BOT_TOKEN = "7545048373:AAHzJ6MAfSHqXMeVN6BKJiJXFYyZNcT3jTg"
TG_CHAT_ID   = "557526625"
# ─────────────────────────────────────────────────────────────────────────────

ACCOUNTS = [
    {"id": AD_ACCOUNT, "name": "SFERO Real Estate", "preset": "yesterday"},
]

def fetch(account_id, preset):
    url = (
        "https://graph.facebook.com/v19.0/"
        f"{account_id}/insights?fields=spend,impressions,clicks,ctr,cpc,reach"
        f"&date_preset={preset}&level=account&access_token={META_TOKEN}"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    if not resp.get("data"):
        return None
    return resp["data"][0]

def build_message(d, account_name):
    spend  = float(d.get("spend", 0))
    impr   = int(d.get("impressions", 0))
    clicks = int(d.get("clicks", 0))
    ctr    = float(d.get("ctr", 0))
    cpc    = float(d.get("cpc", 0))
    reach  = int(d.get("reach", 0))
    date   = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")

    good, warn = [], []
    if ctr > 3:      good.append(f"📈 CTR {ctr:.2f}% — вище норми (ціль >3%)")
    if cpc < 0.4:    good.append(f"💵 CPC ${cpc:.2f} — ефективна ціна кліку")
    if clicks > 150: good.append(f"🖱 Кліки {clicks:,} — хороший трафік")
    if ctr < 2:      warn.append(f"📉 CTR {ctr:.2f}% — нижче норми, перевір креативи")
    if cpc > 0.6:    warn.append(f"💸 CPC ${cpc:.2f} — завищена ціна, оптимізуй аудиторію")
    if spend > 80:   warn.append(f"🔥 Витрати ${spend:.2f} — перевір денні бюджети")

    return (
        f"🏠 <b>{account_name} — Щоденний звіт</b>\n"
        f"📅 <b>{date}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 <b>РЕЗУЛЬТАТИ ЗА ДЕНЬ</b>\n\n"
        f"💸 Витрати:      <b>${spend:.2f}</b>\n"
        f"👁 Покази:        <b>{impr:,}</b>\n"
        f"🖱 Кліки:          <b>{clicks:,}</b>\n"
        f"📈 CTR:            <b>{ctr:.2f}%</b>\n"
        f"💵 Ціна кліку:  <b>${cpc:.2f}</b>\n"
        f"🎯 Охоплення: <b>{reach:,}</b>\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ <b>ЩО ДОБРЕ ПРАЦЮЄ</b>\n"
        f"{chr(10).join(good) if good else '—'}\n\n"
        f"⚠️ <b>НА ЩО ЗВЕРНУТИ УВАГУ</b>\n"
        f"{chr(10).join(warn) if warn else '—'}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💬 Надішли фідбек по якості лідів — врахую у тижневому звіті\n"
        f'📊 <a href="https://app.notion.com/p/6f0b40f7475a4d95918fc699b77e82e8">Таблиця аналітики →</a>'
    )

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true"
    }).encode()
    with urllib.request.urlopen(url, data) as r:
        return json.loads(r.read())

if __name__ == "__main__":
    for acc in ACCOUNTS:
        print(f"📡 Fetching {acc['name']}...")
        try:
            d = fetch(acc["id"], acc["preset"])
            if not d:
                print(f"⚠️  No data for {acc['name']} (no campaigns running?)")
                continue
            msg = build_message(d, acc["name"])
            res = send_telegram(msg)
            if res.get("ok"):
                print(f"✅ Sent: {acc['name']}")
            else:
                print(f"❌ Telegram error: {res}")
        except Exception as e:
            print(f"❌ Error for {acc['name']}: {e}")
