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

THREADS_TOKEN  = _get("THREADS_ACCESS_TOKEN")
ANTHROPIC_KEY  = _get("ANTHROPIC_API_KEY")
TELEGRAM_LINK  = "https://t.me/anton_dyacha"
THREADS_BASE   = "https://graph.threads.net/v1.0"

STATE_FILE     = Path(__file__).parent / "replied_comments.json"
ANALYTICS_FILE = Path(__file__).parent / "posts_analytics.json"
KB_FILE        = Path(__file__).parent / "knowledge_base.json"

POST_MODE      = "--post"      in sys.argv
REPLY_MODE     = "--reply"     in sys.argv
ANALYTICS_MODE = "--analytics" in sys.argv

POSTS_PER_RUN  = 3

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
    if not analytics:
        return ""

    posts = list(analytics.values())
    if not posts:
        return ""

    # Сортуємо по views
    sorted_posts = sorted(posts, key=lambda x: x.get("views", 0), reverse=True)
    top3 = sorted_posts[:3]
    flop3 = sorted_posts[-3:] if len(sorted_posts) > 3 else []

    lines = ["📊 АНАЛІТИКА (що залітає):"]
    for p in top3:
        lines.append(f"  ✅ views={p.get('views',0)} likes={p.get('likes',0)} — тема: {p.get('category','?')} | {p.get('text','')[:60]}")

    if flop3:
        lines.append("📉 Що не залітає:")
        for p in flop3:
            lines.append(f"  ❌ views={p.get('views',0)} — тема: {p.get('category','?')}")

    return "\n".join(lines)

# ─── ТЕМИ ПОСТІВ ──────────────────────────────────────────────────────────────
TOPICS = [
    # ЛІДГЕН / ОФФЕР
    {"text": "Кейс: конкретний результат клієнта (витрати/ліди/CPL) з таргету. Цифри без перебільшень.", "category": "case"},
    {"text": "Топ-3 помилки власників бізнесу в рекламі, які зливають бюджет.", "category": "tips"},
    {"text": "Чому більшість реклами не дає лідів — головна причина і рішення.", "category": "education"},
    {"text": "Оффер: безкоштовний аудит реклами. Поясни цінність, не тисни.", "category": "offer"},
    {"text": "Різниця між дорогою і дешевою рекламою — не в бюджеті, а в стратегії.", "category": "education"},
    {"text": "Оффер з гарантією: якщо результат гірший — повертаємо гроші.", "category": "offer"},

    # ОСОБИСТІСТЬ / ОХВАТ
    {"text": "Особиста помилка яку зробив на початку кар'єри в рекламі і що з цього виніс.", "category": "personal"},
    {"text": "Один лайфак по бізнесу або рекламі який здивував мене цього тижня.", "category": "lifehack"},
    {"text": "Чесний апдейт: що зараз роблю, над чим працюю, що вчу.", "category": "update"},
    {"text": "Провокаційна думка про ринок реклами або digital маркетинг в Іспанії/Україні.", "category": "opinion"},
    {"text": "Що мене дратує в клієнтах або партнерах — чесно і без фільтрів.", "category": "personal"},
    {"text": "Запитання до аудиторії: що заважає масштабувати бізнес через рекламу?", "category": "engagement"},
    {"text": "Неочевидна порада для власників малого бізнесу — коротко і по суті.", "category": "tips"},
    {"text": "Що читаю / дивлюсь / слухаю зараз і чому рекомендую.", "category": "personal"},
    {"text": "Мій погляд на тренд у digital маркетингу який всі обговорюють.", "category": "opinion"},
]

# ─── ПРОМПТИ ──────────────────────────────────────────────────────────────────
def build_post_system():
    analytics_ctx = build_analytics_context()
    base = """Ти — Антон Дяча, експерт із таргетованої реклами і digital маркетингу.
Пишеш пости в Threads (соцмережа). Твоя мета: збирати охват на особистих постах і залучати клієнтів через корисний контент.

Твої послуги: Meta Ads, TikTok Ads, маркетингові воронки, аналітика.
Оффер: безкоштовний аудит реклами / тестовий тиждень / гарантія результату.

Принципи (Чалдіні + AIDA):
- Починай з болю, провокації або особистої історії
- Розкривай цінність або інсайт
- Конкретний результат або соціальний доказ
- Заклик до дії або відкрите запитання

Мова: природній мікс українська/російська (як розмовляють у бізнес-колах)
Стиль: жива мова, як пише реальна людина — без шаблонів і корпоративщини
Довжина: 3–6 речень, максимум 500 символів
Без хештегів, максимум 1–2 емодзі
НЕ згадуй Telegram в постах — тільки у відповідях на коментарі"""

    if analytics_ctx:
        base += f"\n\n{analytics_ctx}\nАдаптуй стиль і теми на основі цієї аналітики."

    return base

REPLY_SYSTEM = f"""Ти — Міла, AI-асистент Антона Дячі. Відповідаєш на коментарі під постами в Threads від його імені.

Твоя мета: допомогти людині і, якщо є потреба — запросити на онлайн зустріч з Антоном.

Правила:
1. ПЕРШИЙ контакт: задай 1 конкретне запитання про бізнес/потребу людини
   Приклади: "Який у вас бізнес?", "Ви вже пробували таргет?"
2. Є інтерес і потреба відповідає послугам → запропонуй зустріч:
   "Напишіть Антону в ТГ, домовитесь на короткий дзвінок: {TELEGRAM_LINK}"
3. ТЕПЛИЙ КОНТАКТ (коментує 3+ рази) → більш особистий тон, пряме запрошення на зустріч
4. Нейтральний коментар ("клас", "вогонь") → коротка щира подяка
5. Негатив/тролінг → skip
6. Мова: мікс укр/рус, жива, без корпоративного стилю
7. 1–3 речення максимум

Відповідай тільки текстом. Якщо не треба відповідати — напиши рівно: skip"""

# ─── РЕЖИМ: АНАЛІТИКА ─────────────────────────────────────────────────────────
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

# ─── РЕЖИМ: ПОСТИНГ ───────────────────────────────────────────────────────────
def run_post(user_id):
    kb = load_kb()
    top_topics = kb.get("top_topics", [])

    # Підбираємо теми: 60% особистість/охват, 40% лідген
    personal = [t for t in TOPICS if t["category"] in ("personal", "lifehack", "update", "opinion", "engagement", "tips")]
    leadgen  = [t for t in TOPICS if t["category"] in ("case", "offer", "education")]

    # Посилюємо топ-категорії якщо є аналітика
    if top_topics:
        boosted = [t for t in TOPICS if t["category"] in top_topics]
        if boosted:
            personal = boosted + personal

    # Збалансований мікс
    n_personal = max(1, round(POSTS_PER_RUN * 0.6))
    n_leadgen  = POSTS_PER_RUN - n_personal

    selected = []
    selected += random.sample(personal, min(n_personal, len(personal)))
    selected += random.sample(leadgen,  min(n_leadgen,  len(leadgen)))
    random.shuffle(selected)

    post_system = build_post_system()
    analytics = load_analytics()

    print(f"📝 Генерую {len(selected)} пости...")
    posted = 0
    for i, topic in enumerate(selected):
        try:
            print(f"  [{i+1}/{len(selected)}] [{topic['category']}] {topic['text'][:50]}...")
            text = claude(post_system, f"Напиши пост на тему: {topic['text']}")
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
