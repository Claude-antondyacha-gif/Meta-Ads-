#!/usr/bin/env python3
"""
Threads Lead Generation Bot
Автопостинг + відповіді в коментарях + кваліфікація лідів
"""
import urllib.request, urllib.parse, json, sys, os, random, time
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

THREADS_TOKEN   = _get("THREADS_ACCESS_TOKEN")
ANTHROPIC_KEY   = _get("ANTHROPIC_API_KEY")
TELEGRAM_LINK   = "https://t.me/anton_dyacha"
THREADS_BASE    = "https://graph.threads.net/v1.0"
STATE_FILE      = Path(__file__).parent / "replied_comments.json"
POST_MODE       = "--post"  in sys.argv
REPLY_MODE      = "--reply" in sys.argv

POSTS_PER_RUN   = 4   # 3 рази на день = 12 постів/день

# ─── THREADS API ──────────────────────────────────────────────────────────────
def t_get(path, params=None):
    p = urllib.parse.urlencode({**(params or {}), "access_token": THREADS_TOKEN})
    req = urllib.request.Request(
        f"{THREADS_BASE}/{path}?{p}",
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def t_post(path, params):
    data = urllib.parse.urlencode({**params, "access_token": THREADS_TOKEN}).encode()
    req = urllib.request.Request(
        f"{THREADS_BASE}/{path}", data=data,
        headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def get_user_id():
    return t_get("me", {"fields": "id,username"})

def publish_thread(user_id, text):
    """Створює і публікує пост у Threads."""
    container = t_post(f"{user_id}/threads", {
        "media_type": "TEXT",
        "text": text
    })
    cid = container.get("id")
    if not cid:
        raise RuntimeError(f"Failed to create container: {container}")
    time.sleep(3)
    result = t_post(f"{user_id}/threads_publish", {"creation_id": cid})
    return result.get("id")

def reply_to_thread(user_id, reply_to_id, text):
    """Публікує відповідь на коментар."""
    container = t_post(f"{user_id}/threads", {
        "media_type": "TEXT",
        "text": text,
        "reply_to_id": reply_to_id
    })
    cid = container.get("id")
    if not cid:
        raise RuntimeError(f"Failed to create reply container: {container}")
    time.sleep(2)
    result = t_post(f"{user_id}/threads_publish", {"creation_id": cid})
    return result.get("id")

def get_my_threads(user_id):
    """Отримує мої пости за останні 24h."""
    since = (datetime.now(timezone.utc) - timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S+0000")
    data = t_get(f"{user_id}/threads", {
        "fields": "id,text,timestamp",
        "since": since,
        "limit": "20"
    })
    return data.get("data", [])

def get_replies(thread_id):
    """Отримує коментарі до посту."""
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
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())["content"][0]["text"].strip()

# ─── СИСТЕМНИЙ ПРОМПТ ДЛЯ ПОСТІВ ─────────────────────────────────────────────
POST_SYSTEM = """Ти — Антон Дяча, експерт із таргетованої реклами та маркетингу для бізнесу.
Пишеш короткі пости в Threads (соцмережа) з метою залучення нових клієнтів.

Твої послуги:
- Таргетована реклама (Meta Ads, TikTok Ads)
- Побудова маркетингових воронок
- Аналітика та оптимізація реклами
- Комплексний розвиток бізнесу через digital

Твій оффер: безкоштовний аудит реклами / тестовий тиждень / гарантія результату (якщо гірше — повертаємо гроші).

Принципи написання (за Робертом Чалдіні та AIDA):
- Починай з болю або провокаційного твердження (Увага)
- Розкривай цінність або інсайт (Інтерес)
- Показуй конкретний результат або соціальний доказ (Бажання)
- Клич до дії або постав запитання (Дія)
- Використовуй принципи: соціальний доказ, дефіцит, авторитет, взаємність

Мова: природній мікс українська/російська (як розмовляють у пострадянських бізнес-колах)
Стиль: жива мова, без шаблонів, як пише реальна людина в соцмережах
Довжина: 3–7 речень, максимум 500 символів
Без хештегів, без зайвих емодзі (максимум 1–2 по тексту)
НЕ згадуй посилання на Telegram в постах — тільки у відповідях на коментарі"""

TOPICS = [
    "Кейс: конкретний результат клієнта (витрати/ліди/CPL) з таргету. Покажи цифри без перебільшень.",
    "Топ-3 помилки власників бізнесу в рекламі, які зливають бюджет.",
    "Чому більшість реклами не дає лідів — розкрий головну причину та запропонуй рішення.",
    "Оффер: безкоштовний аудит реклами. Поясни цінність, не тисни.",
    "Як побудувати воронку, яка продає навіть вночі — короткий інсайт.",
    "Аналітика в рекламі: чому без даних бізнес грає в лотерею.",
    "Запитання до аудиторії: що заважає масштабувати бізнес через рекламу?",
    "Соціальний доказ: скільки лідів/клієнтів отримали партнери цього місяця.",
    "Тестовий тиждень — чому це вигідно для клієнта і як це працює.",
    "Найдорожча помилка в таргеті — неправильна аудиторія. Як знайти правильну.",
    "Оффер з гарантією: якщо результат гірший — повертаємо гроші. Чому не боїмось.",
    "Різниця між дорогою і дешевою рекламою — не в бюджеті, а в стратегії.",
]

# ─── СИСТЕМНИЙ ПРОМПТ ДЛЯ ВІДПОВІДЕЙ ─────────────────────────────────────────
REPLY_SYSTEM = f"""Ти — Антон Дяча, експерт із таргетованої реклами. Відповідаєш на коментарі під своїми постами в Threads.

Твоя мета: кваліфікувати ліда і вивести його на особисту зустріч через Telegram.

Правила відповідей:
1. Перший контакт: задай 1 конкретне запитання, щоб зрозуміти бізнес і потребу людини
   Приклади: "Який у вас бізнес/ніша?", "Ви вже пробували запускати рекламу?"
2. Якщо людина відповіла на твоє запитання і є реальний інтерес — запропонуй продовжити в Telegram
   Формулювання: "Напишіть мені в ТГ, домовимося на короткий дзвінок: {TELEGRAM_LINK}"
3. На нейтральні коментарі (лайк-тексти, "клас", "вогонь") — коротка щира подяка
4. На негатив або тролінг — ігноруй (відповідай "skip")
5. Мова: мікс укр/рус, жива, без корпоративного стилю
6. Відповідь: 1–3 речення максимум

Відповідай тільки текстом відповіді. Якщо не треба відповідати — напиши рівно: skip"""

# ─── СТАН: ОБРОБЛЕНІ КОМЕНТАРІ ────────────────────────────────────────────────
def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"replied": [], "lead_stage": {}}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False))

# ─── ПОСТИНГ ──────────────────────────────────────────────────────────────────
def run_post(user_id):
    print(f"📝 Генерую {POSTS_PER_RUN} пости...")
    topics = random.sample(TOPICS, min(POSTS_PER_RUN, len(TOPICS)))
    posted = 0
    for i, topic in enumerate(topics):
        try:
            print(f"  [{i+1}/{POSTS_PER_RUN}] Тема: {topic[:50]}...")
            text = claude(POST_SYSTEM, f"Напиши пост на тему: {topic}")
            thread_id = publish_thread(user_id, text)
            print(f"  ✅ Опубліковано: {thread_id}")
            print(f"  📄 {text[:80]}...")
            posted += 1
            if i < len(topics) - 1:
                time.sleep(random.randint(15, 45))  # пауза між постами
        except Exception as e:
            print(f"  ❌ Помилка посту: {e}")
    print(f"\n✅ Опубліковано {posted}/{POSTS_PER_RUN} постів")

# ─── ВІДПОВІДІ НА КОМЕНТАРІ ───────────────────────────────────────────────────
def run_reply(user_id):
    state = load_state()
    replied_ids = set(state.get("replied", []))
    lead_stage = state.get("lead_stage", {})

    print("🔍 Отримую мої пости за 24h...")
    threads = get_my_threads(user_id)
    print(f"  Знайдено постів: {len(threads)}")

    new_replies = 0
    for thread in threads:
        tid = thread["id"]
        replies = get_replies(tid)
        if not replies:
            continue
        print(f"  Пост {tid}: {len(replies)} коментарів")
        for reply in replies:
            rid = reply.get("id")
            if not rid or rid in replied_ids:
                continue

            username = reply.get("username", "?")
            text = reply.get("text", "").strip()
            if not text:
                continue

            stage = lead_stage.get(rid, 0)
            print(f"    💬 @{username}: {text[:60]}")

            try:
                context = f"Коментар від @{username}: \"{text}\"\nСтадія розмови: {stage} (0=перший контакт, 1=вже запитав про бізнес)"
                response = claude(REPLY_SYSTEM, context, max_tokens=200)

                if response.strip().lower() == "skip":
                    print(f"    ⏭️  Пропускаємо")
                    replied_ids.add(rid)
                    continue

                reply_id = reply_to_thread(user_id, rid, response)
                print(f"    ✅ Відповів: {response[:60]}...")

                replied_ids.add(rid)
                lead_stage[rid] = stage + 1
                new_replies += 1
                time.sleep(random.randint(10, 25))

            except Exception as e:
                print(f"    ❌ Помилка відповіді: {e}")

    state["replied"] = list(replied_ids)
    state["lead_stage"] = lead_stage
    save_state(state)
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
    else:
        print("Вкажи режим: --post або --reply")
        sys.exit(1)
