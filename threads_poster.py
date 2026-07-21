#!/usr/bin/env python3
"""
Міла — Threads AI Agent
Автопостинг + аналітика + адаптивний контент + кваліфікація лідів
"""
import urllib.request, urllib.parse, urllib.error, json, sys, os, random, time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ─── CONFIG ───────────────────────────────────────────────────────────────────
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
def _get(k): return os.environ.get(k) or _env.get(k, "")

THREADS_TOKEN    = _get("THREADS_ACCESS_TOKEN")
ANTHROPIC_KEY    = _get("ANTHROPIC_API_KEY")
TELEGRAM_LINK    = "https://t.me/anton_dyacha"
TELEGRAM_CHANNEL = "https://t.me/anton_marketingg"
THREADS_BASE     = "https://graph.threads.net/v1.0"

STATE_FILE     = Path(__file__).parent / "replied_comments.json"
ANALYTICS_FILE = Path(__file__).parent / "posts_analytics.json"
KB_FILE        = Path(__file__).parent / "knowledge_base.json"

POST_MODE      = "--post"      in sys.argv
REPLY_MODE     = "--reply"     in sys.argv
ANALYTICS_MODE = "--analytics" in sys.argv
FORCE_MODE     = "--force"     in sys.argv

META_TOKEN     = _get("META_ACCESS_TOKEN")
META_BASE      = "https://graph.facebook.com/v21.0"
BM_AD_ACCOUNTS = [
    {"id": "act_445844598148716",  "niche": "агентство нерухомості в Іспанії"},
    {"id": "act_1179918680004739", "niche": "DOT ES"},
    {"id": "act_1074551967837555", "niche": "DOT nashi"},
]

POSTS_PER_RUN  = 1

# ─── META BM API ──────────────────────────────────────────────────────────────
def meta_get(path, params=None):
    p = urllib.parse.urlencode({**(params or {}), "access_token": META_TOKEN})
    req = urllib.request.Request(
        f"{META_BASE}/{path}?{p}",
        headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Meta HTTP {e.code}: {body}")

def fetch_bm_insights(account_id, days=30):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        data = meta_get(f"{account_id}/insights", {
            "fields": "spend,impressions,clicks,ctr,cpc,cpm,actions,cost_per_action_type",
            "time_range": json.dumps({"since": since, "until": today}),
            "level": "account",
        })
        items = data.get("data", [])
        if not items:
            return None
        row = items[0]
        # Витягуємо leads з actions
        leads = 0
        cpl = 0.0
        for a in row.get("actions", []):
            if a.get("action_type") in ("lead", "offsite_conversion.fb_pixel_lead"):
                leads += int(a.get("value", 0))
        for a in row.get("cost_per_action_type", []):
            if a.get("action_type") in ("lead", "offsite_conversion.fb_pixel_lead"):
                cpl = float(a.get("value", 0))
        return {
            "spend": float(row.get("spend", 0)),
            "impressions": int(row.get("impressions", 0)),
            "clicks": int(row.get("clicks", 0)),
            "ctr": float(row.get("ctr", 0)),
            "cpc": float(row.get("cpc", 0)),
            "cpm": float(row.get("cpm", 0)),
            "leads": leads,
            "cpl": cpl,
            "period_days": days,
        }
    except Exception as e:
        print(f"  ⚠️  BM insights error {account_id}: {e}")
        return None

def fetch_bm_top_campaigns(account_id, days=30, limit=3):
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        data = meta_get(f"{account_id}/campaigns", {
            "fields": "id,name,status",
            "limit": "30",
        })
        campaigns = [c for c in data.get("data", []) if c.get("status") == "ACTIVE"]
        results = []
        for c in campaigns[:10]:
            cid = c["id"]
            ins = meta_get(f"{cid}/insights", {
                "fields": "spend,impressions,clicks,ctr,actions,cost_per_action_type",
                "time_range": json.dumps({"since": since, "until": today}),
            })
            rows = ins.get("data", [])
            if not rows:
                continue
            row = rows[0]
            leads = sum(int(a.get("value", 0)) for a in row.get("actions", [])
                        if a.get("action_type") in ("lead", "offsite_conversion.fb_pixel_lead"))
            cpl = next((float(a.get("value", 0)) for a in row.get("cost_per_action_type", [])
                        if a.get("action_type") in ("lead", "offsite_conversion.fb_pixel_lead")), 0.0)
            results.append({
                "name": c["name"],
                "spend": float(row.get("spend", 0)),
                "leads": leads,
                "cpl": cpl,
                "ctr": float(row.get("ctr", 0)),
            })
        results.sort(key=lambda x: x["leads"], reverse=True)
        return results[:limit]
    except Exception as e:
        print(f"  ⚠️  Campaigns error {account_id}: {e}")
        return []

# ─── THREADS API ──────────────────────────────────────────────────────────────
def t_get(path, params=None):
    p = urllib.parse.urlencode({**(params or {}), "access_token": THREADS_TOKEN})
    req = urllib.request.Request(
        f"{THREADS_BASE}/{path}?{p}",
        headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {body}")

def t_post(path, params):
    data = urllib.parse.urlencode({**params, "access_token": THREADS_TOKEN}).encode()
    req = urllib.request.Request(
        f"{THREADS_BASE}/{path}", data=data,
        headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"HTTP {e.code}: {body}")

def get_user_id():
    return t_get("me", {"fields": "id,username"})

def publish_thread(user_id, text):
    container = t_post(f"{user_id}/threads", {"media_type": "TEXT", "text": text})
    cid = container.get("id")
    if not cid:
        raise RuntimeError(f"No container id: {container}")
    time.sleep(3)
    result = t_post(f"{user_id}/threads_publish", {"creation_id": cid})
    return result.get("id")

def reply_to_thread(user_id, reply_to_id, text):
    container = t_post(f"{user_id}/threads", {
        "media_type": "TEXT", "text": text, "reply_to_id": reply_to_id
    })
    cid = container.get("id")
    if not cid:
        raise RuntimeError(f"No reply container id: {container}")
    time.sleep(2)
    result = t_post(f"{user_id}/threads_publish", {"creation_id": cid})
    return result.get("id")

def get_my_threads(user_id, hours=24):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    data = t_get(f"{user_id}/threads", {
        "fields": "id,text,timestamp",
        "since": since,
        "limit": "50"
    })
    return data.get("data", [])

def get_post_insights(post_id):
    try:
        data = t_get(f"{post_id}/insights", {
            "metric": "views,likes,replies,reposts,quotes"
        })
        result = {}
        for item in data.get("data", []):
            result[item["name"]] = item.get("values", [{}])[0].get("value", 0)
        return result
    except Exception as e:
        print(f"  ⚠️  Insights error for {post_id}: {e}")
        return {}

def get_replies(thread_id):
    try:
        data = t_get(f"{thread_id}/replies", {
            "fields": "id,text,timestamp,username",
            "limit": "50"
        })
        return data.get("data", [])
    except Exception as e:
        print(f"  ⚠️  Replies error for {thread_id}: {e}")
        return []

# ─── CLAUDE API ───────────────────────────────────────────────────────────────
def claude(system_prompt, user_msg, max_tokens=600):
    data = json.dumps({
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": max_tokens,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_msg}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
    )
    try:
        with urllib.request.urlopen(req) as r:
            return json.loads(r.read())["content"][0]["text"].strip()
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Claude API HTTP {e.code}: {body}")

# ─── БАЗА ЗНАНЬ ───────────────────────────────────────────────────────────────
def load_analytics():
    if ANALYTICS_FILE.exists():
        try:
            return json.loads(ANALYTICS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_analytics(data):
    ANALYTICS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))

def load_kb():
    if KB_FILE.exists():
        try:
            return json.loads(KB_FILE.read_text())
        except Exception:
            pass
    return {"top_topics": [], "avoid_topics": [], "warm_contacts": {}, "total_posts": 0}

def save_kb(kb):
    KB_FILE.write_text(json.dumps(kb, indent=2, ensure_ascii=False))

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"replied": [], "lead_stage": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

# ─── АНАЛІТИЧНИЙ КОНТЕКСТ ДЛЯ ПОСТІВ ─────────────────────────────────────────
def build_analytics_context():
    analytics = load_analytics()
    kb = load_kb()
    lines = []

    posts = list(analytics.values())
    if posts:
        sorted_posts = sorted(posts, key=lambda x: x.get("views", 0), reverse=True)
        top3 = sorted_posts[:3]
        flop3 = sorted_posts[-3:] if len(sorted_posts) > 3 else []

        lines.append("📊 АНАЛІТИКА Threads (що залітає):")
        for p in top3:
            lines.append(f"  ✅ views={p.get('views',0)} replies={p.get('replies',0)} — [{p.get('category','?')}] {p.get('text','')[:60]}")
        if flop3:
            lines.append("📉 Що не залітає:")
            for p in flop3:
                lines.append(f"  ❌ views={p.get('views',0)} — [{p.get('category','?')}]")

    # BM кейси
    bm_cases = kb.get("bm_cases", [])
    if bm_cases:
        lines.append("\n💼 РЕАЛЬНІ КЕЙСИ З BM (для постів типу 'case'):")
        for c in bm_cases:
            lines.append(
                f"  Ніша: {c['niche']} | Витрати: €{c['spend']:.0f}/міс | "
                f"Ліди: {c['leads']} | CPL: €{c['cpl']:.2f} | CTR: {c['ctr']:.2f}%"
            )

    return "\n".join(lines) if lines else ""

def get_bm_case_prompt():
    kb = load_kb()
    cases = kb.get("bm_cases", [])
    if not cases:
        return None
    case = random.choice(cases)
    top_c = case.get("top_campaigns", [])
    top_str = ""
    if top_c:
        best = top_c[0]
        top_str = f"Найкраща кампанія: {best['leads']} лідів, CPL €{best['cpl']:.2f}, CTR {best['ctr']:.2f}%"
    return (
        f"Напиши пост-кейс з реальних даних. Без назви клієнта, тільки ніша + гео.\n"
        f"Ніша: {case['niche']}\n"
        f"Дані за 30 днів: витрати €{case['spend']:.0f}, ліди {case['leads']}, CPL €{case['cpl']:.2f}, CTR {case['ctr']:.2f}%\n"
        f"{top_str}\n\n"
        f"ОБОВ'ЯЗКОВА структура (перевірено аналітикою — дає 5x охоплення):\n"
        f"1. Число/ситуація до (стартовий CPL або проблема)\n"
        f"2. 'Змінили одну річ' — яку саме (конкретно)\n"
        f"3. Результат після (конкретні числа)\n"
        f"4. Провокуюче питання або висновок\n\n"
        f"НЕ починай з назви ніші або 'Кейс:'. Починай з числа або ситуації."
    )


# ─── ТЕМИ ПОСТІВ ──────────────────────────────────────────────────────────────
# Структура підтверджена аналітикою: "cabinet_numbers" і "case_pivot" дають 5-10x охоплення
TOPICS = [
    # CABINET NUMBERS — формат "Дивився в кабінети вчера — цифри дикі"
    # Найвищий avg views (129+), 5 з топ-15 постів. Запускати 2x/тиждень.
    {"text": "Відкрив кабінети зранку — різниця між нішами вражає. Нерухомість Іспанія: €8-14 за лід. Ecom Україна: 30-90 грн. B2B SaaS: €45-120. Що це означає для бюджетування.", "category": "cabinet_numbers"},
    {"text": "Порівнював CPL за квартал у своїх кабінетах. Три ніші, три реальності: лідогенерація в нерухомості, e-commerce одяг, автодилер. Числа яких ніхто не публікує.", "category": "cabinet_numbers"},
    {"text": "Дивився в кабінети вчера — дикі цифри. CTR 0.3% vs 4.2% в одній і тій же ніші. Різниця тільки в одному елементі. Розповім що.", "category": "cabinet_numbers"},
    {"text": "Відкрив звіти за місяць по 3 кабінетах. Один з них здивував — CPL впав вдвічі без зміни бюджету. Алгоритм сам знайшов аудиторію яку ми не тестували.", "category": "cabinet_numbers"},
    {"text": "Benchmark по нішах з моїх кабінетів: ресторан Барселона €3-6/лід, автодилер €25-45, онлайн-курси €8-18. Чому така різниця і що з цим робити.", "category": "cabinet_numbers"},

    # CASE PIVOT — "змінив одну річ" before/after з pivot. Топ-15 постів.
    {"text": "Ecom одяг, ROAS 1.8, власник готував закривати рекламу. Змінили одну річ в оптимізації — через 3 тижні ROAS 4.2. Що саме зробили.", "category": "case_pivot"},
    {"text": "Автодилер. CPL €45, хотіли зупиняти. Я запропонував змінити тільки CTA в оголошенні. Через 2 тижні: €12 за лід. Один рядок тексту.", "category": "case_pivot"},
    {"text": "Ресторан в Барселоні, 6 місяців порожній зал. Запустили на Meta один тип кампанії. За місяць — 47 бронювань. Бюджет €400.", "category": "case_pivot"},
    {"text": "B2B послуги. Клієнт платив €120 за лід і не розумів чому якість погана. Змінили аудиторію (не розмір — тип). CPL впав до €38, якість зросла.", "category": "case_pivot"},
    {"text": "Нерухомість Іспанія. Перший місяць: 188 лідів, CPL €14.49. Після оптимізації: 156 лідів, CPL €8.30, але конверсія в покупців +40%. Чому менше лідів = краще.", "category": "case_pivot"},
    {"text": "Інтернет-магазин косметики. ROAS 0.9 — реклама в мінус. Знайшов одну сегментацію яку не тестували. За 10 днів ROAS 3.4. Жодного нового креативу.", "category": "case_pivot"},

    # HOT TAKES / ПРОВОКАЦІЯ
    {"text": "Таргетолог говорить '50 лідів за €15 кожен'. Клієнт платить. Місяць потому: 2 продажі. Хто винен і чому це системна проблема ринку.", "category": "opinion"},
    {"text": "Advantage+ від Meta — довіряти алгоритму чи контролювати самому? 340 кампаній. Моя чесна позиція.", "category": "opinion"},
    {"text": "CPL, ROAS, CPA можуть бути ідеальними — і бізнес все одно банкрутує. Яку метрику насправді треба дивитись.", "category": "opinion"},
    {"text": "iOS privacy вбила атрибуцію 3 роки тому. Більшість агенцій досі це приховують від клієнтів і стверджують що все ок.", "category": "opinion"},
    {"text": "TikTok Ads vs Meta Ads у 2026 — конкретні числа з моїх кабінетів. Де дешевше і чому залежить від однієї змінної.", "category": "opinion"},
    {"text": "Таргетолог і маркетолог — різниця яка коштує власнику бізнесу €500-2000 на місяць переплати.", "category": "opinion"},

    # ОСОБИСТІСТЬ / ПОМИЛКИ (особисті професійні історії — post #6 226 views)
    {"text": "Перший рік в рекламі: запустив кампанію без пікселя. Клієнт заплатив за місяць €800. Продажів нуль. Як я це приховував і що вийшло.", "category": "personal"},
    {"text": "Клієнт якого я втратив через власну впертість — чесна історія. І чому я правий і одночасно неправий.", "category": "personal"},
    {"text": "Що мене реально дратує: 90% таргетологів продають мрію а не результат. Звідки я знаю — бо сам так робив.", "category": "personal"},
    {"text": "Найбільший провал за кар'єру — €3200 злито за тиждень. Що пішло не так і як я це виправляв.", "category": "personal"},

    # ЛАЙФАКИ — з конкретними числами (ключ — цифра в тілі)
    {"text": "Як ми зменшили CPM на 40% без зміни бюджету — один конкретний прийом з аудиторіями.", "category": "lifehack"},
    {"text": "Скільки реально коштує лід в різних нішах — цифри з моїх кабінетів цього місяця. Не теорія.", "category": "lifehack"},
    {"text": "Лайфак для ecommerce: чому оптимізація на 'покупку' з першого дня вбиває кампанію. І як правильно.", "category": "lifehack"},
    {"text": "Чому retargeting у 2026 дає CPL в 3x нижчий ніж холодна аудиторія — і чому більшість цим не користується.", "category": "lifehack"},

    # ЕДУКАЦІЯ — з counter-intuitive hook (post #9, #10 — 188-193 views)
    {"text": "Різниця між таргетологом і маркетологом: один запускає рекламу в людей, інший думає де, коли й навіщо. Чому ця різниця = €500-2000/міс.", "category": "education"},
    {"text": "Три метрики які виглядають ідеально — і при цьому бізнес в мінус. Пояснюю на реальному прикладі.", "category": "education"},
    {"text": "Воронка продажів яку малюють в презентаціях vs воронка яку я бачу в кабінетах. Різниця критична.", "category": "education"},

    # ЗАЛУЧЕННЯ — питання з реальним контекстом (не абстрактні)
    {"text": "Питання: ваш підрядник показує CPL — ви перевіряєте чи це реальні ліди чи просто форми з невалідними номерами?", "category": "engagement"},
    {"text": "Яка ніша на вашу думку найскладніша для таргету в 2026 — і чому? Порівняю з тим що бачу в кабінетах.", "category": "engagement"},
]

# ─── ПРОМПТИ ──────────────────────────────────────────────────────────────────
def build_post_system(with_channel_cta=False):
    analytics_ctx = build_analytics_context()
    kb = load_kb()
    frameworks = kb.get("psychology_frameworks", {})

    base = f"""Ти — Антон Дяча. Таргетолог, працюю з бізнесами в Іспанії та Україні: Meta Ads, TikTok Ads, воронки, аналітика.
Пишеш пост в Threads. Одна мета: людина має відчути щось і відреагувати.

━━━ ЯК ДУМАЄ ЧИТАЧ (Канеман, Система 1 vs 2) ━━━
Рішення приймає Система 1 — швидка, емоційна, без логіки.
Система 2 потім виправдовує те що вже вирішила С1.
Значить: перше речення б'є в емоцію — потім логіка підтверджує.

━━━ TRIP-ФОРМУЛА (єдина структура посту) ━━━
T — Тригер: число, парадокс, або втрата. Зупиняє скролінг за 0.3 сек.
R — Рефрейм: переверни очевидне. "Всі думають X — насправді Y."
I — Інсайт: одна конкретна деталь з реального досвіду. Не теорія.
P — Провокація: питання або твердження яке змушує написати відповідь.

━━━ ПРИНЦИПИ ЧАЛДІНІ (вшивай непомітно) ━━━
• Авторитет: специфічні цифри > загальні слова. "340 кампаній" > "великий досвід"
• Соціальний доказ: "клієнт з ніші X отримав Y" > "реклама може давати результат"
• Дефіцит: "більшість ніколи не перевіряє це" > "важливо знати"
• Взаємність: дай реальний інсайт безкоштовно — люди хочуть відповісти

━━━ ФРЕЙМІНГ ЧЕРЕЗ ВТРАТУ (Канеман — лосс-аверсія) ━━━
СЛАБКО: "Ти можеш заощадити €40 на лід"
СИЛЬНО: "Ти зараз переплачуєш €40 за кожен лід. Щодня."
Втрата болить вдвічі сильніше ніж рівноцінний прибуток.

━━━ ЗАБОРОНЕНІ КОНСТРУКЦІЇ ━━━
❌ "Більшість власників бізнесу не знають..." → банально, читач вже бачив 100 разів
❌ "Важливо розуміти що..." → лекторський тон, відштовхує
❌ "Реклама може давати результат якщо..." → нульова конкретика
❌ Будь-яке речення яке можна вставити в чужий акаунт без змін
❌ Мотиваційний контент, тревел, особисте без рекламного інсайту → чужа аудиторія, вбиває алгоритм
❌ Пост без конкретного числа → підтверджено аналітикою: всі топ-15 постів мають цифри

━━━ ЩО РЕАЛЬНО ЗАЛІТАЄ (з аналітики 140 постів) ━━━
🏆 ФОРМАТ №1 "кабінет": "Відкрив кабінети зранку — [adj]. [Ніша А]: €X. [Ніша Б]: €Y. [Ніша В]: €Z."
🏆 ФОРМАТ №2 "pivot": "[Проблема] → Змінили одну річ → [Результат у числах]"
🏆 Counter-intuitive hook: "CPL ідеальний, але бізнес банкрутує" — когнітивний дисонанс змушує читати
📊 Середній охват формату "кабінет": 400-630 views. Середній по акаунту: 54 views.

━━━ СТАНДАРТ ЯКОСТІ ━━━
Задай собі питання перед фіналом: "Чи це могла написати ChatGPT за 3 секунди?"
Якщо так — перепиши. Пост має звучати як живий запис думки, а не як контент.

━━━ ФОРМАТ ━━━
- Мова: живий мікс укр/рус, як думаєш а не як пишеш для клієнта
- 3-5 речень, максимум 450 символів
- Без хештегів. Максимум 1 емодзі — тільки якщо підсилює, не декорує
- Назви клієнтів — ніколи. Тільки "ніша + гео": "ecom одяг", "автодилер в Барселоні"
- Речення до 12 слів — мозок читає без зусиль"""

    if with_channel_cta:
        base += f"""

━━━ CTA НА КАНАЛ ━━━
В кінці посту одним реченням — природно, без "підписуйтесь":
Веду тг-канал де розбираю це глибше: {TELEGRAM_CHANNEL}
Або: "Більше таких кейсів у моєму тг: {TELEGRAM_CHANNEL}"
Підбери фразу під тему посту."""

    if analytics_ctx:
        base += f"\n\n━━━ АНАЛІТИКА (що реально залітає у твоєму акаунті) ━━━\n{analytics_ctx}\nАдаптуй на основі цих даних — не ігноруй їх."

    return base

REPLY_SYSTEM = f"""Ти — Антон Дяча, таргетолог і підприємець. Відповідаєш на коментарі під своїми постами в Threads.

ГОЛОВНЕ: відповідати треба на КОЖЕН коментар — навіть емодзі, навіть "клас", навіть одне слово.

Типи коментарів і як відповідати:

1. ЕМОДЗІ або 1 слово ("🔥", "👍", "огонь", "топ") → відповідь-емодзі або 1-2 слова у відповідь.
   Приклади: "🙌", "дякую!", "радий чути 🔥", "так тримати 💪"

2. ПОХВАЛА / ЗГОДА → коротка щира відповідь, можна додати інсайт або запитання.
   "Дякую! А у вас як — стикались з таким?"

3. ЗАПИТАННЯ про тему посту → відповідь по суті, 1-3 речення, без води.

4. ІНТЕРЕС ДО ПОСЛУГ / ЗАПИТ → задай 1 уточнювальне запитання: "Який у вас бізнес?"
   Якщо вже є контекст → запроси: "Напишіть в ТГ, швидше розберемось: {TELEGRAM_LINK}"

5. ТЕПЛИЙ КОНТАКТ (коментує 3+ рази) → більш особистий тон, звертайся по імені якщо є, запроси в ТГ.

6. НЕЗГОДА / ДИСКУСІЯ → прийми позицію, поясни свою думку коротко. Не сперечайся, але стій на своєму.

7. ВІДВЕРТИЙ НЕГАТИВ / ТРОЛІНГ → skip (тільки якщо це явний хейт без змісту)

ВАЖЛИВО:
- Мова: живий мікс укр/рус, як у чаті з другом
- Максимум 2 речення. Краще коротко і щиро ніж довго і формально
- Ніколи не пиши як бот — жодного "дякуємо за ваш коментар"
- Telegram пропонуй тільки якщо є реальний інтерес до послуг

Відповідай тільки текстом відповіді. Якщо це явний спам/тролінг — напиши рівно: skip"""

# ─── РЕЖИМ: АНАЛІТИКА ─────────────────────────────────────────────────────────
def run_bm_analytics(kb):
    if not META_TOKEN:
        print("  ⚠️  META_ACCESS_TOKEN не задано, пропускаємо BM аналітику")
        return kb

    print("\n💼 Збираю дані BM...")
    bm_data = kb.get("bm_accounts", {})

    for account in BM_AD_ACCOUNTS:
        acc_id = account["id"]
        niche = account["niche"]
        print(f"  📊 {niche} ({acc_id})...")

        insights = fetch_bm_insights(acc_id, days=30)
        if not insights:
            continue

        top_campaigns = fetch_bm_top_campaigns(acc_id, days=30)

        bm_data[acc_id] = {
            "niche": niche,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "insights_30d": insights,
            "top_campaigns": top_campaigns,
        }

        spend = insights["spend"]
        leads = insights["leads"]
        cpl = insights["cpl"]
        ctr = insights["ctr"]
        print(f"    ✅ Витрати: €{spend:.0f} | Ліди: {leads} | CPL: €{cpl:.2f} | CTR: {ctr:.2f}%")
        if top_campaigns:
            print(f"    🏆 Топ кампанія: {top_campaigns[0]['name'][:50]} — {top_campaigns[0]['leads']} лідів")

    kb["bm_accounts"] = bm_data
    kb["bm_last_updated"] = datetime.now(timezone.utc).isoformat()

    # Генеруємо готові кейси для постів
    cases = []
    for acc_id, acc_data in bm_data.items():
        ins = acc_data.get("insights_30d", {})
        niche = acc_data["niche"]
        if ins.get("leads", 0) > 0 and ins.get("cpl", 0) > 0:
            cases.append({
                "niche": niche,
                "spend": ins["spend"],
                "leads": ins["leads"],
                "cpl": ins["cpl"],
                "ctr": ins["ctr"],
                "top_campaigns": acc_data.get("top_campaigns", []),
            })
    kb["bm_cases"] = cases
    print(f"\n  📝 Готових кейсів для постів: {len(cases)}")
    return kb

def run_analytics(user_id):
    print("📊 Збираю аналітику постів за останні 7 днів...")
    analytics = load_analytics()
    kb = load_kb()

    posts = get_my_threads(user_id, hours=7*24)
    print(f"  Знайдено постів: {len(posts)}")

    updated = 0
    for post in posts:
        pid = post["id"]
        insights = get_post_insights(pid)
        if not insights:
            continue

        # Якщо пост вже є в аналітиці — оновлюємо метрики
        existing = analytics.get(pid, {})
        analytics[pid] = {
            **existing,
            "id": pid,
            "text": post.get("text", "")[:200],
            "timestamp": post.get("timestamp", ""),
            "views": insights.get("views", 0),
            "likes": insights.get("likes", 0),
            "replies": insights.get("replies", 0),
            "reposts": insights.get("reposts", 0),
            "quotes": insights.get("quotes", 0),
            "category": existing.get("category", "unknown"),
        }
        updated += 1
        print(f"  📈 {pid}: views={insights.get('views',0)} likes={insights.get('likes',0)} replies={insights.get('replies',0)}")

    save_analytics(analytics)

    # Оновлюємо knowledge base — топ теми
    all_posts = list(analytics.values())
    if all_posts:
        by_views = sorted(all_posts, key=lambda x: x.get("views", 0), reverse=True)
        top_categories = {}
        for p in by_views[:10]:
            cat = p.get("category", "unknown")
            v = p.get("views", 0)
            if cat not in top_categories:
                top_categories[cat] = {"views": 0, "count": 0}
            top_categories[cat]["views"] += v
            top_categories[cat]["count"] += 1

        # Середній охват по категорії
        cat_avg = {k: v["views"] / v["count"] for k, v in top_categories.items()}
        sorted_cats = sorted(cat_avg.items(), key=lambda x: x[1], reverse=True)

        kb["top_topics"] = [c for c, _ in sorted_cats[:3]]
        kb["avoid_topics"] = [c for c, _ in sorted_cats[-2:]] if len(sorted_cats) > 2 else []
        kb["total_posts"] = len(all_posts)
        kb["last_updated"] = datetime.now(timezone.utc).isoformat()
        save_kb(kb)

        print(f"\n✅ Аналітику оновлено: {updated} постів")
        print(f"  🏆 Топ категорії: {kb['top_topics']}")
        print(f"  📉 Уникати: {kb['avoid_topics']}")

    # BM аналітика
    kb = run_bm_analytics(kb)
    save_kb(kb)

# ─── РЕЖИМ: ПОСТИНГ ───────────────────────────────────────────────────────────
def run_post(user_id):
    # 75% шанс публікувати — щоб пости виходили нерівномірно, як жива людина
    if not FORCE_MODE and random.random() > 0.75:
        print("⏭️  Пропускаємо цей запуск (живий режим)")
        return

    kb = load_kb()
    top_topics = kb.get("top_topics", [])

    last_category = kb.get("last_category", "")

    # Кожен 5-й пост — кейс з реальних BM даних
    kb_posts = kb.get("total_posts", 0)
    use_bm_case = (kb_posts % 5 == 4) and bool(kb.get("bm_cases"))
    if use_bm_case:
        selected = [{"text": "__BM_CASE__", "category": "case_pivot"}]
    else:
        # Пріоритети підтверджені аналітикою:
        # cabinet_numbers → avg 129+ views, case_pivot → top-15 posts
        # opinion/personal → 160-226 views. education → 188-193 views.
        # engagement → лише з реальним контекстом. update/offer → видалено (0 replies, дно).

        # Розклад категорій: кожен 4-й = cabinet_numbers (найвищий avg охват)
        if kb_posts % 4 == 0:
            pool = [t for t in TOPICS if t["category"] == "cabinet_numbers"]
        # Кожен 4-й після cabinet = case_pivot
        elif kb_posts % 4 == 2:
            pool = [t for t in TOPICS if t["category"] == "case_pivot"]
        # Решта — opinion/personal/lifehack/education/engagement
        else:
            reach_cats = ("opinion", "personal", "lifehack", "education", "engagement")
            pool = [t for t in TOPICS if t["category"] in reach_cats and t["category"] != last_category]

        # Фолбек якщо категорія вичерпана або вже стояла
        if not pool:
            pool = [t for t in TOPICS if t["category"] != last_category] or list(TOPICS)

        # Буст топ-тем з аналітики
        if top_topics:
            boosted = [t for t in pool if t["category"] in top_topics]
            if boosted:
                pool = boosted + pool

        selected = random.sample(pool, min(POSTS_PER_RUN, len(pool)))

    # Кожен 4-й пост — з CTA на Telegram-канал
    with_channel_cta = (kb_posts % 4 == 3)
    post_system = build_post_system(with_channel_cta=with_channel_cta)
    analytics = load_analytics()

    print(f"📝 Генерую {len(selected)} пости...")
    posted = 0
    for i, topic in enumerate(selected):
        try:
            if topic["text"] == "__BM_CASE__":
                bm_prompt = get_bm_case_prompt()
                if not bm_prompt:
                    continue
                print(f"  [{i+1}/{len(selected)}] [bm_case] Генерую кейс з BM даних...")
                text = claude(post_system, bm_prompt + "\n\nВАЖЛИВО: максимум 480 символів. Без markdown, без заголовків (#), без зірочок (**). Тільки звичайний текст.")
            else:
                print(f"  [{i+1}/{len(selected)}] [{topic['category']}] {topic['text'][:50]}...")
                text = claude(post_system, f"Напиши пост на тему: {topic['text']}"
                         + "\n\nВАЖЛИВО: максимум 480 символів. Без markdown, без заголовків (#), без зірочок (**). Тільки звичайний текст.")
            # Очищаємо markdown і обрізаємо до 490 символів
            import re
            text = re.sub(r'^#+\s+.*\n?', '', text, flags=re.MULTILINE)  # прибираємо заголовки
            text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)  # прибираємо bold
            text = text.strip()[:490]
            print(f"  💬 {text[:100]}...")
            thread_id = publish_thread(user_id, text)
            print(f"  ✅ Опубліковано: {thread_id}")

            # Зберігаємо пост в аналітику (метрики з'являться пізніше)
            analytics[thread_id] = {
                "id": thread_id,
                "text": text[:200],
                "category": topic["category"],
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "views": 0, "likes": 0, "replies": 0, "reposts": 0, "quotes": 0
            }
            posted += 1

            if i < len(selected) - 1:
                time.sleep(random.randint(20, 45))

        except Exception as e:
            print(f"  ❌ Помилка: {e}")

    save_analytics(analytics)
    kb["total_posts"] = kb.get("total_posts", 0) + posted
    if selected:
        kb["last_category"] = selected[-1]["category"]
    save_kb(kb)
    print(f"\n✅ Опубліковано {posted}/{len(selected)} постів")

# ─── РЕЖИМ: ВІДПОВІДІ ─────────────────────────────────────────────────────────
def run_reply(user_id):
    state = load_state()
    kb = load_kb()
    replied_ids = set(state.get("replied", []))
    lead_stage = state.get("lead_stage", {})
    warm_contacts = kb.get("warm_contacts", {})

    print("🔍 Отримую пости за 48h...")
    threads = get_my_threads(user_id, hours=48)
    print(f"  Постів: {len(threads)}")

    new_replies = 0
    for thread in threads:
        tid = thread["id"]
        replies = get_replies(tid)
        if not replies:
            continue

        for reply in replies:
            rid = reply.get("id")
            if not rid or rid in replied_ids:
                continue

            username = reply.get("username", "?")
            text = reply.get("text", "").strip()
            if not text:
                continue

            # Рахуємо активність контакту
            warm_contacts[username] = warm_contacts.get(username, 0) + 1
            warmth = warm_contacts[username]
            stage = lead_stage.get(username, 0)

            print(f"  💬 @{username} (активність:{warmth}): {text[:60]}")

            try:
                context = (
                    f"Коментар від @{username}: \"{text}\"\n"
                    f"Стадія розмови: {stage} (0=перший контакт, 1=вже запитав про бізнес)\n"
                    f"Активність контакту: {warmth} коментарів (3+ = теплий контакт, запрошуй на зустріч)"
                )
                response = claude(REPLY_SYSTEM, context, max_tokens=200)

                if response.strip().lower() == "skip":
                    print(f"    ⏭️  Пропуск")
                    replied_ids.add(rid)
                    continue

                reply_to_thread(user_id, rid, response)
                print(f"    ✅ {response[:70]}")

                replied_ids.add(rid)
                lead_stage[username] = stage + 1
                new_replies += 1
                time.sleep(random.randint(10, 30))

            except Exception as e:
                print(f"    ❌ {e}")

    state["replied"] = list(replied_ids)
    state["lead_stage"] = lead_stage
    kb["warm_contacts"] = warm_contacts
    save_state(state)
    save_kb(kb)
    print(f"\n✅ Надіслано відповідей: {new_replies}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if not THREADS_TOKEN:
        print("❌ THREADS_ACCESS_TOKEN не задано"); sys.exit(1)
    if not ANTHROPIC_KEY:
        print("❌ ANTHROPIC_API_KEY не задано"); sys.exit(1)

    try:
        me = get_user_id()
        user_id = me["id"]
        username = me.get("username", "?")
        print(f"👤 Threads: @{username} (id: {user_id})")
    except Exception as e:
        print(f"❌ Threads API error: {e}"); sys.exit(1)

    if POST_MODE:
        run_post(user_id)
    elif REPLY_MODE:
        run_reply(user_id)
    elif ANALYTICS_MODE:
        run_analytics(user_id)
    else:
        print("Вкажи режим: --post | --reply | --analytics")
        sys.exit(1)
