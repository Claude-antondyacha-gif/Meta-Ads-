#!/usr/bin/env python3
"""
SFERO Meta Ads Report — daily + weekly
Telegram + Google Sheets logging
Cron via GitHub Actions (see .github/workflows/)
"""
import urllib.request, urllib.parse, json, sys, os
from datetime import datetime, timedelta
from pathlib import Path

# ─── CONFIG: env vars first (GitHub Actions), fallback to .env.local ─────────
def _load_env():
    env = {}
    p = Path(__file__).parent / ".env.local"
    if p.exists():
        for line in p.read_text().splitlines():
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env

_env = _load_env()
def _get(key): return os.environ.get(key) or _env.get(key, "")

META_TOKEN   = _get("META_ACCESS_TOKEN")
TG_TOKEN     = _get("TG_BOT_TOKEN") or "8948335437:AAFmlGhCBHF-QlK5aLHXw1vNXFm_hUAkOvw"
TG_CHAT      = _get("TG_CHAT_ID") or "557526625"
SHEETS_ID    = _get("GOOGLE_SHEETS_ID")
GCP_JSON     = _get("GOOGLE_SERVICE_ACCOUNT_JSON")
AD_ACCOUNT   = "act_445844598148716"
WEEKLY       = "--weekly" in sys.argv
# ─────────────────────────────────────────────────────────────────────────────

def api(path, params):
    p = urllib.parse.urlencode({**params, "access_token": META_TOKEN})
    req = urllib.request.Request(
        f"https://graph.facebook.com/v19.0/{path}?{p}",
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def action(arr, *types):
    for a in (arr or []):
        if a["action_type"] in types:
            return int(float(a["value"]))
    return 0

def cpa(arr, *types):
    for a in (arr or []):
        if a["action_type"] in types:
            return float(a["value"])
    return 0.0

def fetch_account(preset):
    r = api(f"{AD_ACCOUNT}/insights", {
        "fields": "spend,impressions,clicks,ctr,cpc,reach,actions,"
                  "cost_per_action_type,frequency,unique_clicks",
        "date_preset": preset, "level": "account"})
    return r["data"][0] if r.get("data") else None

def fetch_campaigns(preset):
    r = api(f"{AD_ACCOUNT}/insights", {
        "fields": "campaign_name,spend,impressions,clicks,ctr,cpc,"
                  "reach,actions,cost_per_action_type,frequency",
        "date_preset": preset, "level": "campaign",
        "sort": "spend_descending", "limit": "10"})
    return r.get("data", [])

def get_leads(d):
    a = d.get("actions", [])
    leads = action(a, "lead", "onsite_conversion.lead_grouped")
    if leads == 0:
        leads = action(a, "offsite_complete_registration_add_meta_leads")
    return leads

def get_cpl(d, leads, spend):
    c = cpa(d.get("cost_per_action_type", []),
            "lead", "onsite_conversion.lead_grouped",
            "offsite_complete_registration_add_meta_leads")
    if c == 0 and leads > 0:
        c = spend / leads
    return c

# ─── DAILY MESSAGE ────────────────────────────────────────────────────────────
def build_daily(acc, camps, date_str):
    spend  = float(acc.get("spend", 0))
    impr   = int(acc.get("impressions", 0))
    clicks = int(acc.get("clicks", 0))
    ctr    = float(acc.get("ctr", 0))
    cpc    = float(acc.get("cpc", 0))
    reach  = int(acc.get("reach", 0))
    freq   = float(acc.get("frequency", 0))
    lp_view = action(acc.get("actions", []),
                     "landing_page_view", "omni_landing_page_view")
    leads  = get_leads(acc)
    cpl    = get_cpl(acc, leads, spend)
    lp_rate  = (lp_view / clicks * 100) if clicks > 0 else 0
    conv_rate = (leads / lp_view * 100) if lp_view > 0 else 0

    camp_lines = []
    crit_camps = []
    for c in camps:
        name   = c["campaign_name"][:45].strip()
        cs     = float(c.get("spend", 0))
        cctr   = float(c.get("ctr", 0))
        ccpc   = float(c.get("cpc", 0))
        cl     = get_leads(c)
        ccpl   = get_cpl(c, cl, cs)
        cfreq  = float(c.get("frequency", 0))
        ok     = cctr >= 3 and (ccpl < 8 or cl == 0) and cfreq < 3
        bad    = cctr < 1.5 or (ccpl > 15 and cl > 0) or cfreq > 3.5
        ico    = "\U0001f7e2" if ok else ("\U0001f534" if bad else "\U0001f7e1")
        if bad: crit_camps.append(name[:35])
        leads_str = f"\U0001f3af {cl} лід · CPL ${ccpl:.2f}" if cl > 0 else "лідів нема"
        camp_lines.append(
            f"{ico} <b>{name}</b>\n"
            f"    \U0001f4b8${cs:.2f} · CTR {cctr:.2f}% · CPC ${ccpc:.2f} · freq {cfreq:.1f} · {leads_str}")

    good, warn, crit = [], [], []
    if ctr > 3:      good.append(f"CTR {ctr:.2f}% — вище норми (ціль >3%)")
    if cpc < 0.35:   good.append(f"CPC ${cpc:.2f} — ефективна ціна кліку")
    if leads > 5:    good.append(f"{leads} лідів — хороший об'єм")
    if 0 < cpl < 6:  good.append(f"CPL ${cpl:.2f} — відмінна вартість ліда")
    if lp_rate > 60: good.append(f"LPV rate {lp_rate:.0f}% — якісний трафік")

    if ctr < 2:       warn.append(f"CTR {ctr:.2f}% — нижче норми, тест нових креативів")
    if freq > 2.5:    warn.append(f"Frequency {freq:.2f} — аудиторія перегрівається")
    if lp_rate < 40:  warn.append(f"LPV {lp_rate:.0f}% від кліків — відмова на лендінгу")
    if conv_rate < 5 and leads > 0:
        warn.append(f"Конверсія LPV→ліди {conv_rate:.1f}% — перевір форму/оффер")

    if leads == 0:   crit.append("0 лідів — перевір піксель та форми")
    if cpl > 15:     crit.append(f"CPL ${cpl:.2f} — критично висока вартість ліда")
    if spend > 150:  crit.append(f"Витрати ${spend:.2f} — перевір денні бюджети")
    for n in crit_camps:
        crit.append(f"Зупини/перезапусти: {n}")

    g = "\n".join(f"✅ {x}" for x in good) or "—"
    w = "\n".join(f"⚠️ {x}" for x in warn) or "—"
    cr = "\n".join(f"⛔ {x}" for x in crit) or "—"

    return (
        f"\U0001f3e0 <b>SFERO Real Estate — Щоденний звіт</b>\n"
        f"\U0001f4c5 <b>{date_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>\U0001f4ca РЕЗУЛЬТАТИ ЗА ДЕНЬ</b>\n"
        f"\U0001f4b8 Витрати:         <b>${spend:.2f}</b>\n"
        f"\U0001f3af Ліди:              <b>{leads}</b>\n"
        f"\U0001f4b0 CPL:               <b>${cpl:.2f}</b>\n"
        f"\U0001f441 Покази:           <b>{impr:,}</b>\n"
        f"\U0001f5b1 Кліки:             <b>{clicks:,}</b>\n"
        f"\U0001f4c8 CTR:               <b>{ctr:.2f}%</b>\n"
        f"\U0001f4b5 CPC:               <b>${cpc:.2f}</b>\n"
        f"\U0001f3e0 LPV:               <b>{lp_view:,}</b> ({lp_rate:.0f}% від кліків)\n"
        f"\U0001f501 Конверсія:      <b>{conv_rate:.1f}%</b> (ліди/LPV)\n"
        f"\U0001f3af Охоплення:    <b>{reach:,}</b> · freq <b>{freq:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>\U0001f4c2 КАМПАНІЇ</b>\n"
        f"{chr(10).join(camp_lines) or '—'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>✅ ЩО ДОБРЕ ПРАЦЮЄ</b>\n{g}\n"
        f"<b>⚠️ НА ЩО ЗВЕРНУТИ УВАГУ</b>\n{w}\n"
        f"<b>\U0001f6a8 КРИТИЧНО</b>\n{cr}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\U0001f4ac Надішли фідбек по лідах — врахую у тижневому звіті"
    )

# ─── WEEKLY MESSAGE ───────────────────────────────────────────────────────────
def build_weekly(acc7, camps7, date_str):
    spend7  = float(acc7.get("spend", 0))
    impr7   = int(acc7.get("impressions", 0))
    clicks7 = int(acc7.get("clicks", 0))
    ctr7    = float(acc7.get("ctr", 0))
    cpc7    = float(acc7.get("cpc", 0))
    reach7  = int(acc7.get("reach", 0))
    freq7   = float(acc7.get("frequency", 0))
    leads7  = get_leads(acc7)
    cpl7    = get_cpl(acc7, leads7, spend7)

    camp_lines = []
    for c in camps7:
        name  = c["campaign_name"][:45].strip()
        cs    = float(c.get("spend", 0))
        cctr  = float(c.get("ctr", 0))
        ccpc  = float(c.get("cpc", 0))
        cl    = get_leads(c)
        ccpl  = get_cpl(c, cl, cs)
        ok    = cctr >= 3 and (ccpl < 8 or cl == 0)
        bad   = cctr < 1.5 or (ccpl > 15 and cl > 0)
        ico   = "\U0001f7e2" if ok else ("\U0001f534" if bad else "\U0001f7e1")
        leads_str = f"{cl} лід · CPL ${ccpl:.2f}" if cl > 0 else "лідів нема"
        camp_lines.append(
            f"{ico} <b>{name}</b>\n"
            f"    \U0001f4b8${cs:.2f} · CTR {cctr:.2f}% · CPC ${ccpc:.2f} · {leads_str}")

    recs = []
    if cpl7 > 10:  recs.append("• CPL >$10 — протести нові офери / аудиторії")
    if ctr7 < 2.5: recs.append("• CTR <2.5% — онови відео-креативи або карусель")
    if freq7 > 2.5: recs.append("• Frequency >2.5 — розшир аудиторію або вимкни вузькі")
    if leads7 > 20: recs.append("• Гарний об'єм лідів — масштабуй топ кампанії +20%")
    if 0 < cpl7 < 6: recs.append("• Відмінний CPL — тестуй збільшення бюджету")
    if not recs: recs.append("• Показники стабільні — тримай поточну стратегію")

    return (
        f"\U0001f3e0 <b>SFERO — Тижневий звіт Meta Ads</b>\n"
        f"\U0001f4c5 <b>{date_str}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>\U0001f4ca ПІДСУМОК ТИЖНЯ</b>\n"
        f"\U0001f4b8 Витрати:         <b>${spend7:.2f}</b>\n"
        f"\U0001f3af Ліди:              <b>{leads7}</b>\n"
        f"\U0001f4b0 CPL:               <b>${cpl7:.2f}</b>\n"
        f"\U0001f441 Покази:           <b>{impr7:,}</b>\n"
        f"\U0001f5b1 Кліки:             <b>{clicks7:,}</b>\n"
        f"\U0001f4c8 CTR:               <b>{ctr7:.2f}%</b>\n"
        f"\U0001f4b5 CPC:               <b>${cpc7:.2f}</b>\n"
        f"\U0001f3af Охоплення:    <b>{reach7:,}</b> · freq <b>{freq7:.2f}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>\U0001f4c2 КАМПАНІЇ ЗА ТИЖДЕНЬ</b>\n"
        f"{chr(10).join(camp_lines) or '—'}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>\U0001f4a1 РЕКОМЕНДАЦІЇ НА НАСТУПНИЙ ТИЖДЕНЬ</b>\n"
        f"{chr(10).join(recs)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"\U0001f4ac Надішли фідбек по якості лідів за тиждень"
    )

# ─── TELEGRAM ─────────────────────────────────────────────────────────────────
def send_tg(text):
    data = urllib.parse.urlencode({
        "chat_id": TG_CHAT, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": "true"
    }).encode()
    with urllib.request.urlopen(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage", data) as r:
        return json.loads(r.read())

# ─── GOOGLE SHEETS ────────────────────────────────────────────────────────────
def log_to_sheets(row: dict):
    if not SHEETS_ID or not GCP_JSON:
        return
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        creds_dict = json.loads(GCP_JSON)
        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds  = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc     = gspread.authorize(creds)
        sh     = gc.open_by_key(SHEETS_ID)

        try:
            ws = sh.worksheet("Daily")
        except Exception:
            ws = sh.add_worksheet("Daily", rows=1000, cols=15)
            ws.append_row(["Дата","Витрати $","Покази","Кліки","CTR %",
                           "CPC $","Охоплення","Freq","LPV","Conv %","Ліди","CPL $"])

        ws.append_row([
            row["date"], row["spend"], row["impressions"], row["clicks"],
            row["ctr"],  row["cpc"],   row["reach"],       row["freq"],
            row["lpv"],  row["conv"],  row["leads"],       row["cpl"]
        ])
        print("✅ Google Sheets updated")
    except Exception as e:
        print(f"⚠️  Sheets error (non-fatal): {e}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m.%Y")

    if WEEKLY:
        print("\U0001f4e1 Fetching weekly data...")
        acc7   = fetch_account("last_7d")
        camps7 = fetch_campaigns("last_7d")
        if not acc7:
            print("⚠️  No data"); sys.exit(1)
        week_end = (datetime.now() - timedelta(days=1)).strftime("%d.%m")
        week_start = (datetime.now() - timedelta(days=7)).strftime("%d.%m.%Y")
        msg = build_weekly(acc7, camps7, f"{week_start} — {week_end}")
    else:
        print("\U0001f4e1 Fetching daily data...")
        acc   = fetch_account("yesterday")
        camps = fetch_campaigns("yesterday")
        if not acc:
            print("⚠️  No data — no campaigns running yesterday"); sys.exit(0)

        spend  = float(acc.get("spend", 0))
        leads  = get_leads(acc)
        cpl    = get_cpl(acc, leads, spend)
        lp_view = action(acc.get("actions", []),
                         "landing_page_view", "omni_landing_page_view")
        clicks = int(acc.get("clicks", 0))
        lp_rate = (lp_view / clicks * 100) if clicks > 0 else 0
        conv    = (leads / lp_view * 100) if lp_view > 0 else 0

        msg = build_daily(acc, camps, yesterday)
        log_to_sheets({
            "date":        yesterday,
            "spend":       round(spend, 2),
            "impressions": acc.get("impressions"),
            "clicks":      clicks,
            "ctr":         round(float(acc.get("ctr", 0)), 2),
            "cpc":         round(float(acc.get("cpc", 0)), 2),
            "reach":       acc.get("reach"),
            "freq":        round(float(acc.get("frequency", 0)), 2),
            "lpv":         lp_view,
            "conv":        round(conv, 1),
            "leads":       leads,
            "cpl":         round(cpl, 2),
        })

    res = send_tg(msg)
    if res.get("ok"):
        print(f"✅ {'Weekly' if WEEKLY else 'Daily'} report sent!")
    else:
        print(f"❌ Telegram error: {res}")
