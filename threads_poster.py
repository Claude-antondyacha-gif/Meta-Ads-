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
        f"Напиши пост-кейс (формат: ніша + результат, без назви клієнта).\n"
        f"Ніша: {case['niche']}\n"
        f"Дані за 30 днів: витрати €{case['spend']:.0f}, ліди {case['leads']}, "
        f"CPL €{case['cpl']:.2f}, CTR {case['ctr']:.2f}%\n"
        f"{top_str}\n"
        f"Формат посту: '🏠 [Ніша]\\nБуло / Стало' або 'Кейс: [ніша] — [головна цифра]'.\n"
        f"Стиль: конкретні числа, прогрів до себе як до експерта, без назви клієнта."
    )


# ─── ТЕМИ ПОСТІВ ──────────────────────────────────────────────────────────────
TOPICS = [
    # HOT TAKES / ПРОВОКАЦІЯ — найбільше replies за даними алгоритму Threads 2026
    {"text": "Непопулярна думка: більшість таргетологів продають ліди, а не результат. Різниця величезна — поясни чому.", "category": "opinion"},
    {"text": "Advantage+ від Meta — довіряти алгоритму чи контролювати самому? Моя чесна позиція після тестів.", "category": "opinion"},
    {"text": "Провокація: агентства які обіцяють гарантований ROAS — брехуть. Ось чому.", "category": "opinion"},
    {"text": "Незгода з популярною думкою: 'більший бюджет = більше лідів' — це міф. Що насправді важливо.", "category": "opinion"},
    {"text": "Чесно: iOS privacy вбила атрибуцію і більшість агенцій досі це приховують від клієнтів.", "category": "opinion"},

    # КЕЙСИ З НІШЕЮ — прогрів через соціальний доказ
    {"text": "Кейс з реальними цифрами: ніша клієнта + витрати/ліди/CPL. Без назви компанії, тільки результат.", "category": "case"},
    {"text": "Агентство нерухомості в Іспанії: як ми знизили CPL з ринкових 50 EUR до 8-15 EUR — що зробили.", "category": "case"},
    {"text": "Кейс ecommerce: чому збільшення бюджету на 50% не дало +50% продажів і що ми змінили.", "category": "case"},

    # ОСОБИСТІСТЬ / ПОМИЛКИ — викликають емпатію і replies
    {"text": "Особиста помилка яку зробив на початку кар'єри в рекламі і що з цього виніс.", "category": "personal"},
    {"text": "Клієнт якого я втратив — чесна історія без прикрашань і що я з цього зрозумів.", "category": "personal"},
    {"text": "Що мене дратує в ринку таргетованої реклами — чесно і без фільтрів.", "category": "personal"},
    {"text": "Чесний апдейт: що зараз тестую, що не зашло, що здивувало в результатах.", "category": "update"},

    # ЛАЙФАКИ / ІНСАЙТИ — корисний контент зупиняє скролінг
    {"text": "Один неочевидний лайфак по Meta Ads який дав несподіваний результат — коротко і по суті.", "category": "lifehack"},
    {"text": "Скільки реально коштує лід в різних нішах в Іспанії/Україні — цифри з моїх кабінетів.", "category": "lifehack"},
    {"text": "Різниця між таргетологом і маркетологом — чому це важливо для бізнесу.", "category": "education"},
    {"text": "Що змінилось в Meta Ads після iOS privacy і як ми адаптували стратегії клієнтів.", "category": "education"},

    # ЗАЛУЧЕННЯ — запитання що провокують відповіді
    {"text": "Відкрите запитання: яку найбільшу помилку в рекламі ви бачили у свого підрядника?", "category": "engagement"},
    {"text": "Запитання до власників бізнесу: ви знаєте свій реальний CPL і ROAS чи просто вірите підряднику?", "category": "engagement"},

    # ОФФЕР — м'який, через цінність
    {"text": "Оффер через кейс: безкоштовний аудит — що я перевіряю за 20 хвилин і що зазвичай знаходжу.", "category": "offer"},
]

# ─── ПРОМПТИ ──────────────────────────────────────────────────────────────────
def build_post_system():
    analytics_ctx = build_analytics_context()
    base = """Ти — Антон Дяча, таргетолог і експерт з Meta Ads / digital маркетингу.
Пишеш пости в Threads. Головна мета: прогріти аудиторію до себе як до експерта. Лідген — другорядний.

Послуги: Meta Ads, TikTok Ads, маркетингові воронки, аналітика.
Клієнти: агентства нерухомості в Іспанії, ecommerce, бізнеси в Україні/Іспанії.

АЛГОРИТМ THREADS 2026 — що просувається:
- Replies важливіші за лайки → провокуй дискусію, задавай запитання
- Перші 60 хвилин критичні → перший рядок має зупинити скролінг
- Оригінальний нативний контент (не перепости з інших платформ)
- Відповідь на коментарі підвищує охват на 42%

ФОРМАТИ що залітають (по даних Buffer/Sprout 2026):
1. Hot take / непопулярна думка → максимум replies
2. "Я помилявся коли думав що..." → емпатія + навчання
3. Цифра яка дивує + коротке пояснення → зупиняє скролінг
4. Кейс: ніша клієнта + результат (без назви компанії)
5. Відкрите запитання до аудиторії → провокує відповіді

СТРУКТУРА посту:
- Перший рядок (до 280 символів) = хук — провокація, цифра або несподівана думка
- 2-3 речення розкриття
- Фінал = відкрите запитання АБО інсайт що залишається в голові

ПРАВИЛА:
- Мова: живий мікс укр/рус, як у бізнес-чаті
- 3-5 речень, максимум 400 символів
- Без хештегів, максимум 1-2 емодзі
- Ніяких назв клієнтів — тільки "ніша + гео" (напр. "агентство нерухомості в Іспанії")
- НЕ згадуй Telegram в постах — тільки у відповідях на коментарі
- Уникай корпоративщини, шаблонів, загальних фраз"""

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
    if random.random() > 0.75:
        print("⏭️  Пропускаємо цей запуск (живий режим)")
        return

    kb = load_kb()
    top_topics = kb.get("top_topics", [])

    personal = [t for t in TOPICS if t["category"] in ("personal", "lifehack", "update", "opinion", "engagement", "tips")]
    leadgen  = [t for t in TOPICS if t["category"] in ("case", "offer", "education")]

    if top_topics:
        boosted = [t for t in TOPICS if t["category"] in top_topics]
        if boosted:
            personal = boosted + personal

    # Кожен 5-й пост — кейс з реальних BM даних, кожен 3-й — лідген, решта — охват
    kb_posts = kb.get("total_posts", 0)
    use_bm_case = (kb_posts % 5 == 4) and bool(kb.get("bm_cases"))
    if use_bm_case:
        pool = leadgen  # буде перевизначено нижче
        selected = [{"text": "__BM_CASE__", "category": "case"}]
    else:
        pool = leadgen if (kb_posts % 3 == 2) else personal
        selected = random.sample(pool, min(POSTS_PER_RUN, len(pool)))

    post_system = build_post_system()
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
                text = claude(post_system, bm_prompt)
            else:
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
