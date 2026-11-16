import os
import random
import threading
import time
import secrets
import string
from datetime import datetime, timezone, timedelta

import requests
import psycopg2
from flask import Flask, jsonify

# =====================================================
# تنظیمات
# =====================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

# مثال: ADMIN_IDS=1708788049,123456789
ADMIN_IDS = {
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

VOTE_TIMEOUT = 60
MAX_ROOM_PLAYERS = 20
REFERRER_REWARD = 30
NEW_USER_REWARD = 10
DAILY_REWARD = 5

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است.")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL تنظیم نشده است.")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
app = Flask(__name__)

db_lock = threading.RLock()
state_lock = threading.RLock()
room_lock = threading.RLock()

user_states = {}
single_player = {}
rooms = {}

# =====================================================
# وب سرور
# =====================================================
@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running!"

@app.route("/health")
def health():
    with room_lock:
        room_count = len(rooms)
    return jsonify({"status": "ok", "rooms": room_count})

# =====================================================
# دیتابیس
# =====================================================
def get_db():
    return psycopg2.connect(DATABASE_URL, connect_timeout=10)

def db_execute(query, params=(), fetchone=False, fetchall=False):
    with db_lock:
        db = get_db()
        cur = db.cursor()
        try:
            cur.execute(query, params)
            result = cur.fetchall() if fetchall else (
                cur.fetchone() if fetchone else None
            )
            db.commit()
            return result
        except Exception:
            db.rollback()
            raise
        finally:
            cur.close()
            db.close()

def generate_invite_code():
    chars = string.ascii_uppercase + string.digits
    return "".join(
        secrets.choice(chars)
        for _ in range(8)
    )

def generate_unique_invite_code():
    for _ in range(100):
        code = generate_invite_code()

        row = db_execute(
            "SELECT 1 FROM users WHERE invite_code=%s LIMIT 1",
            (code,),
            fetchone=True
        )

        if not row:
            return code

    return secrets.token_hex(8).upper()

def init_database():
    with db_lock:
        db = get_db()
        cur = db.cursor()

        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    invite_code TEXT,
                    invited_by BIGINT,
                    referral_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    games_played INTEGER NOT NULL DEFAULT 0,
                    successful_answers INTEGER NOT NULL DEFAULT 0,
                    daily_streak INTEGER NOT NULL DEFAULT 0,
                    last_daily_reward DATE
                )
            """)

            # سازگاری با دیتابیس قدیمی
            for column, definition in [
                ("invite_code", "TEXT"),
                ("invited_by", "BIGINT"),
                ("referral_count", "INTEGER NOT NULL DEFAULT 0"),
                ("games_played", "INTEGER NOT NULL DEFAULT 0"),
                ("successful_answers", "INTEGER NOT NULL DEFAULT 0"),
                ("daily_streak", "INTEGER NOT NULL DEFAULT 0"),
                ("last_daily_reward", "DATE"),
                ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ]:
                cur.execute(
                    f"""
                    ALTER TABLE users
                    ADD COLUMN IF NOT EXISTS {column}
                    {definition}
                    """
                )

            cur.execute("""
                CREATE TABLE IF NOT EXISTS score_history (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    points INTEGER NOT NULL,
                    reason TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS reports (
                    id BIGSERIAL PRIMARY KEY,
                    reporter_id BIGINT NOT NULL,
                    target_user_id BIGINT,
                    reason TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    resolved_at TIMESTAMP,
                    resolved_by BIGINT
                )
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                users_unique_name_ci
                ON users (LOWER(BTRIM(name)))
            """)

            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                users_unique_invite_code
                ON users (invite_code)
                WHERE invite_code IS NOT NULL
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                score_history_created_idx
                ON score_history (created_at)
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                reports_status_idx
                ON reports (status)
            """)

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cur.close()
            db.close()

    # کد دعوت کاربران قدیمی
    rows = db_execute(
        """
        SELECT user_id
        FROM users
        WHERE invite_code IS NULL
        OR invite_code=''
        """,
        fetchall=True
    ) or []

    for (uid,) in rows:
        for _ in range(20):
            code = generate_unique_invite_code()

            try:
                db_execute(
                    """
                    UPDATE users
                    SET invite_code=%s
                    WHERE user_id=%s
                    AND (
                        invite_code IS NULL
                        OR invite_code=''
                    )
                    """,
                    (code, uid)
                )
                break

            except Exception:
                pass

    print("✅ PostgreSQL database initialized")

def normalize_name(name):
    return " ".join(
        str(name or "").strip().split()
    )

def user_exists(user_id):
    return bool(
        db_execute(
            "SELECT 1 FROM users WHERE user_id=%s",
            (user_id,),
            fetchone=True
        )
    )

def name_exists(name, exclude_user_id=None):
    name = normalize_name(name)

    if not name:
        return False

    if exclude_user_id is None:
        q = """
            SELECT 1 FROM users
            WHERE LOWER(BTRIM(name))=
                  LOWER(BTRIM(%s))
            LIMIT 1
        """

        p = (name,)

    else:
        q = """
            SELECT 1 FROM users
            WHERE LOWER(BTRIM(name))=
                  LOWER(BTRIM(%s))
            AND user_id<>%s
            LIMIT 1
        """

        p = (name, exclude_user_id)

    return bool(
        db_execute(
            q,
            p,
            fetchone=True
        )
    )

def get_name(user_id):
    row = db_execute(
        "SELECT name FROM users WHERE user_id=%s",
        (user_id,),
        fetchone=True
    )

    return row[0] if row else "بازیکن"

def get_user_by_invite_code(code):
    code = str(code or "").strip().upper()

    if not code:
        return None

    return db_execute(
        """
        SELECT user_id,name
        FROM users
        WHERE invite_code=%s
        LIMIT 1
        """,
        (code,),
        fetchone=True
    )

def save_new_user(user_id, name, invited_by=None):
    name = normalize_name(name)

    try:
        db_execute("""
            INSERT INTO users(
                user_id,
                name,
                score,
                invite_code,
                invited_by,
                referral_count
            )
            VALUES(
                %s,
                %s,
                0,
                %s,
                %s,
                0
            )
        """, (
            user_id,
            name,
            generate_unique_invite_code(),
            invited_by
        ))

        return True

    except psycopg2.IntegrityError:
        return False

    except Exception as e:
        print("❌ Save user:", e)
        return False

def add_score(
    user_id,
    points,
    reason="امتیاز بازی"
):
    if not points:
        return

    with db_lock:
        db = get_db()
        cur = db.cursor()

        try:
            cur.execute(
                """
                UPDATE users
                SET score=score+%s
                WHERE user_id=%s
                """,
                (points, user_id)
            )

            cur.execute(
                """
                INSERT INTO score_history(
                    user_id,
                    points,
                    reason
                )
                VALUES(%s,%s,%s)
                """,
                (
                    user_id,
                    points,
                    reason
                )
            )

            db.commit()

        except Exception:
            db.rollback()
            raise

        finally:
            cur.close()
            db.close()

def reward_referral(
    new_user_id,
    inviter_id
):
    if not inviter_id:
        return False

    if new_user_id == inviter_id:
        return False

    with db_lock:
        db = get_db()
        cur = db.cursor()

        try:
            cur.execute(
                """
                SELECT invited_by
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (new_user_id,)
            )

            row = cur.fetchone()

            if not row or row[0] != inviter_id:
                db.rollback()
                return False

            cur.execute(
                """
                SELECT 1
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (inviter_id,)
            )

            if not cur.fetchone():
                db.rollback()
                return False

            # جایزه کاربر جدید
            cur.execute(
                """
                UPDATE users
                SET score=score+%s
                WHERE user_id=%s
                """,
                (
                    NEW_USER_REWARD,
                    new_user_id
                )
            )

            # جایزه دعوت‌کننده
            cur.execute(
                """
                UPDATE users
                SET
                    score=score+%s,
                    referral_count=referral_count+1
                WHERE user_id=%s
                """,
                (
                    REFERRER_REWARD,
                    inviter_id
                )
            )

            cur.execute(
                """
                INSERT INTO score_history(
                    user_id,
                    points,
                    reason
                )
                VALUES(%s,%s,%s)
                """,
                (
                    new_user_id,
                    NEW_USER_REWARD,
                    "جایزه ورود با کد دعوت"
                )
            )

            cur.execute(
                """
                INSERT INTO score_history(
                    user_id,
                    points,
                    reason
                )
                VALUES(%s,%s,%s)
                """,
                (
                    inviter_id,
                    REFERRER_REWARD,
                    "جایزه دعوت کاربر جدید"
                )
            )

            db.commit()
            return True

        except Exception as e:
            db.rollback()
            print("❌ Referral:", e)
            return False

        finally:
            cur.close()
            db.close()

def change_user_name(user_id, name):
    try:
        db_execute(
            """
            UPDATE users
            SET name=%s
            WHERE user_id=%s
            """,
            (
                normalize_name(name),
                user_id
            )
        )

        return True

    except psycopg2.IntegrityError:
        return False

def add_game_played(user_id):
    db_execute(
        """
        UPDATE users
        SET games_played=games_played+1
        WHERE user_id=%s
        """,
        (user_id,)
    )

def add_successful_answer(user_id):
    db_execute(
        """
        UPDATE users
        SET successful_answers=
            successful_answers+1
        WHERE user_id=%s
        """,
        (user_id,)
    )

# =====================================================
# API بله
# =====================================================
def api_request(
    method,
    payload=None,
    timeout=30
):
    try:
        r = requests.post(
            f"{BASE_URL}/{method}",
            json=payload or {},
            timeout=timeout
        )

        data = r.json()

        if (
            r.status_code != 200
            or not data.get("ok")
        ):
            print(
                f"❌ API Error [{method}]:",
                data
            )

            return None

        return data

    except Exception as e:
        print(
            f"❌ API Request Error [{method}]:",
            e
        )

        return None

def send_message(
    chat_id,
    text,
    reply_markup=None
):
    payload = {
        "chat_id": chat_id,
        "text": str(text)[:4000]
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return api_request(
        "sendMessage",
        payload
    )

def send_photo(
    chat_id,
    photo,
    caption=None
):
    payload = {
        "chat_id": chat_id,
        "photo": photo
    }

    if caption:
        payload["caption"] = str(caption)[:1024]

    return api_request(
        "sendPhoto",
        payload
    )

def send_voice(
    chat_id,
    voice,
    caption=None
):
    payload = {
        "chat_id": chat_id,
        "voice": voice
    }

    if caption:
        payload["caption"] = str(caption)[:1024]

    return api_request(
        "sendVoice",
        payload
    )

def answer_callback(
    callback_id,
    text=None
):
    payload = {
        "callback_query_id": callback_id
    }

    if text:
        payload["text"] = text

    return api_request(
        "answerCallbackQuery",
        payload
    )

# =====================================================
# محتوا: متن / عکس / ویس
# =====================================================
def get_content_from_message(message):
    photos = message.get("photo")

    if photos:
        fid = photos[-1].get("file_id")

        if fid:
            return {
                "type": "photo",
                "file_id": fid,
                "caption": (
                    message.get("caption", "")
                    or ""
                ).strip()
            }

    voice = message.get("voice")

    if voice and voice.get("file_id"):
        return {
            "type": "voice",
            "file_id": voice["file_id"],
            "caption": (
                message.get("caption", "")
                or ""
            ).strip()
        }

    text = (
        message.get("text", "")
        or ""
    ).strip()

    if text:
        return {
            "type": "text",
            "text": text[:4000]
        }

    return None

def send_content(
    chat_id,
    content,
    prefix=None
):
    if not content:
        return

    typ = content.get("type")

    if typ == "text":
        text = content.get("text", "")

        send_message(
            chat_id,
            f"{prefix}\n\n{text}"
            if prefix
            else text
        )

    else:
        cap = content.get("caption", "")

        if prefix:
            cap = (
                f"{prefix}\n\n{cap}"
                if cap
                else prefix
            )

        if typ == "photo":
            send_photo(
                chat_id,
                content.get("file_id"),
                cap
            )

        elif typ == "voice":
            send_voice(
                chat_id,
                content.get("file_id"),
                cap
            )

# =====================================================
# منوها
# =====================================================
def get_main_menu():
    return {
        "keyboard": [
            [
                {"text": "🎮 اتاق‌های آنلاین"},
                {"text": "🤖 بازی تک‌نفره"}
            ],
            [
                {"text": "👤 پروفایل من"},
                {"text": "🎁 جایزه روزانه"}
            ],
            [
                {"text": "👥 دعوت دوستان"},
                {"text": "🏆 رتبه‌بندی"}
            ],
            [
                {"text": "✏️ تغییر نام"},
                {"text": "📖 راهنمای بازی"}
            ],
            [
                {"text": "🚫 گزارش کاربر"},
                {"text": "📢 کانال اطلاع‌رسانی"}
            ],
            [
                {"text": "💬 پشتیبانی"}
            ]
        ],
        "resize_keyboard": True
    }

def get_rooms_menu():
    return {
        "keyboard": [
            [
                {"text": "🛠️ ساخت اتاق جدید"},
                {"text": "🚪 پیوستن به اتاق"}
            ],
            [
                {"text": "🚪 خروج از اتاق"}
            ],
            [
                {"text": "🏠 منوی اصلی"}
            ]
        ],
        "resize_keyboard": True
    }

def get_modes_keyboard():
    return {
        "inline_keyboard": [
            [
                {
                    "text": "🟢 معمولی و دوستانه",
                    "callback_data": "mode_normal"
                }
            ],
            [
                {
                    "text": "🔥 خفن و چالشی",
                    "callback_data": "mode_fun"
                }
            ],
            [
                {
                    "text": "⛏️ ماینکرفت",
                    "callback_data": "mode_minecraft"
                }
            ],
            [
                {
                    "text": "⚡ سریع جواب بده",
                    "callback_data": "mode_fast"
                }
            ],
            [
                {
                    "text": "🔙 بازگشت",
                    "callback_data": "back_menu"
                }
            ]
        ]
    }

def get_single_next_keyboard():
    return {
        "keyboard": [
            [
                {"text": "⏭️ سؤال جدید"}
            ],
            [
                {"text": "🏠 منوی اصلی"}
            ]
        ],
        "resize_keyboard": True
    }

def admin_menu():
    return {
        "keyboard": [
            [
                {"text": "📊 آمار ربات"},
                {"text": "🚫 گزارش‌های باز"}
            ],
            [
                {"text": "📢 پیام همگانی"}
            ],
            [
                {"text": "➕ افزایش امتیاز"},
                {"text": "➖ کاهش امتیاز"}
            ],
            [
                {"text": "👤 اطلاعات کاربر"}
            ],
            [
                {"text": "🏠 منوی اصلی"}
            ]
        ],
        "resize_keyboard": True
    }

# =====================================================
# بانک سؤال‌ها
# =====================================================
PROMPTS = {
    "normal": {
        "truth": [
            "از بین کسایی که اینجا هستن، به کی بیشتر اعتماد داری و چرا؟",
            "آخرین بار کی دروغ گفتی و چرا؟",
            "اگر جای یکی از بچه‌های این گروه بودی، کی رو انتخاب می‌کردی؟",
            "چیزی که تا حالا به کسی نگفتی ولی دوست داری بگی چیه؟",
            "بامزه‌ترین خاطره‌ات از مدرسه چیه؟",
            "بدترین غذایی که تا حالا خوردی چی بود؟",
            "اگر بفهمی بهترین دوستت پشت سرت حرف زده، چیکار می‌کنی؟",
            "یک چیزی که در خودت واقعاً دوست داری چیه؟",
            "چیزی که باعث می‌شه سریع عصبانی بشی چیه؟",
            "بزرگ‌ترین ترست چیه؟",
            "اگر پول مهم نبود، الان مشغول چه کاری بودی؟",
            "یک عادت بد یا بامزه خودت را بگو.",
            "یک شهر نام ببر که دوست داری به آن سفر کنی.",
            "اگر یک ابرقدرت داشتی، چه قدرتی انتخاب می‌کردی؟",
            "بهترین بازی ویدیویی که انجام دادی چیست؟"
        ],
        "dare": [
            "با لهجه محلی، سه جمله درباره مدرسه‌ات بگو.",
            "یک داستان مرموز کوتاه تعریف کن.",
            "یک ایموجی بفرست که حالت الان را نشان بده و توضیح بده چرا.",
            "از یک نفر در گروه یک تعریف واقعی و محترمانه بکن.",
            "یک جمله بگو که آخرش همه بخندن.",
            "یک سؤال بپرس که جوابش بقیه را غافلگیر کند.",
            "یک لطیفه کوتاه و مناسب تعریف کن.",
            "با سه ایموجی یک داستان بساز.",
            "یک شخصیت خیالی بساز و سه ویژگی برایش بگو.",
            "یک معمای کوتاه برای بقیه طراحی کن.",
            "یک پیام انگیزشی کوتاه برای اعضای گروه بنویس."
        ]
    },

    "fun": {
        "truth": [
            "کی از همه بیشتر دیر می‌رسد؟",
            "کی از همه بامزه‌تر است؟",
            "کی زودتر از همه عصبی می‌شود؟",
            "کی بهترین تایپیست است؟",
            "اگر یک نفر را قهرمان گروه می‌کردی، کی بود؟",
            "اگر مدیر مدرسه بودی چه قانونی می‌گذاشتی؟"
        ],
        "dare": [
            "یک نفر را انتخاب کن و یک ویژگی مثبت او را بگو.",
            "برای یکی از اعضای گروه یک لقب دوستانه و محترمانه بساز.",
            "یک تبلیغ بامزه برای یک مداد بنویس.",
            "یک داستان پنج‌کلمه‌ای بنویس.",
            "یک معمای کوتاه طراحی کن."
        ]
    },

    "minecraft": {
        "truth": [
            "تا حالا چند ساعت پشت سر هم ماینکرفت بازی کردی؟",
            "اگر می‌توانستی یک بلاک ماینکرفت را واقعی کنی، چی می‌شد؟",
            "Survival را بیشتر دوست داری یا Creative؟",
            "به نظر تو سخت‌ترین دشمن ماینکرفت کدام است؟",
            "بهترین سازه‌ای که تا حالا ساختی چی بوده؟"
        ],
        "dare": [
            "در ۲۰ ثانیه توضیح بده چرا Creeper معروف است.",
            "یک اسم بامزه برای یک دنیای جدید ماینکرفت بساز.",
            "یک چالش ماینکرفت پیشنهاد بده که همه انجام بدهند.",
            "پنج ابزار ماینکرفت را نام ببر."
        ]
    },

    "fast": {
        "truth": [
            "[۱۰ ثانیه] اسم سه رنگ بگو.",
            "[۱۵ ثانیه] پنج بازی ویدیویی نام ببر.",
            "[۲۰ ثانیه] چهار استان ایران نام ببر.",
            "[۱۰ ثانیه] سه میوه قرمز نام ببر.",
            "[۱۰ ثانیه] سه حیوان نام ببر."
        ],
        "dare": [
            "[۱۰ ثانیه] یک جمله خنده‌دار بساز.",
            "[۱۵ ثانیه] پنج اسم برای یک ربات خیالی پیشنهاد بده.",
            "[۱۰ ثانیه] سه ایموجی بفرست که یک داستان بسازند."
        ]
    }
}

def get_random_prompt(mode):
    items = []

    for typ in ("truth", "dare"):
        for p in PROMPTS.get(
            mode,
            PROMPTS["normal"]
        ).get(typ, []):
            items.append({
                "type": typ,
                "prompt": p
            })

    if items:
        return random.choice(items)

    return {
        "type": "truth",
        "prompt": "یک سؤال مناسب پاسخ بده."
    }

def mode_name(mode):
    return {
        "normal": "🟢 معمولی و دوستانه",
        "fun": "🔥 خفن و چالشی",
        "minecraft": "⛏️ ماینکرفت",
        "fast": "⚡ سریع جواب بده"
    }.get(mode, "🟢 معمولی")

# =====================================================
# پروفایل، رتبه‌بندی و جایزه روزانه
# =====================================================
def show_profile(uid):
    row = db_execute("""
        SELECT
            name,
            score,
            referral_count,
            games_played,
            successful_answers,
            daily_streak,
            created_at,
            invite_code
        FROM users
        WHERE user_id=%s
    """, (uid,), fetchone=True)

    if not row:
        return

    (
        name,
        score,
        refs,
        games,
        successes,
        streak,
        created,
        code
    ) = row

    rank_row = db_execute(
        """
        SELECT COUNT(*)+1
        FROM users
        WHERE score>(
            SELECT score
            FROM users
            WHERE user_id=%s
        )
        """,
        (uid,),
        fetchone=True
    )

    rank = rank_row[0] if rank_row else "-"
    created_text = (
        created.strftime("%Y/%m/%d")
        if created
        else "-"
    )

    send_message(
        uid,
        f"👤 پروفایل کاربری\n\n"
        f"👤 نام: {name}\n"
        f"⭐ امتیاز: {score}\n"
        f"🏆 رتبه: {rank}\n"
        f"🎮 بازی‌ها: {games}\n"
        f"✅ پاسخ‌های تأییدشده: {successes}\n"
        f"👥 زیرمجموعه‌ها: {refs}\n"
        f"🔥 استریک جایزه روزانه: {streak} روز\n"
        f"🔑 کد دعوت: {code}\n"
        f"📅 عضویت: {created_text}",
        get_main_menu()
    )

def leaderboard_rows(period):
    if period == "all":
        return db_execute(
            """
            SELECT name,score
            FROM users
            ORDER BY score DESC,name ASC
            LIMIT 10
            """,
            fetchall=True
        ) or []

    if period == "week":
        return db_execute("""
            SELECT
                u.name,
                COALESCE(SUM(h.points),0) s
            FROM users u
            JOIN score_history h
            ON h.user_id=u.user_id
            WHERE h.created_at>=
                CURRENT_TIMESTAMP-INTERVAL '7 days'
            GROUP BY u.user_id,u.name
            ORDER BY s DESC,u.name ASC
            LIMIT 10
        """, fetchall=True) or []

    return db_execute("""
        SELECT
            u.name,
            COALESCE(SUM(h.points),0) s
        FROM users u
        JOIN score_history h
        ON h.user_id=u.user_id
        WHERE h.created_at>=
            date_trunc(
                'month',
                CURRENT_TIMESTAMP
            )
        GROUP BY u.user_id,u.name
        ORDER BY s DESC,u.name ASC
        LIMIT 10
    """, fetchall=True) or []

def show_leaderboard(uid, period="all"):
    title = {
        "all": "🏆 برترین‌های کل",
        "week": "📅 برترین‌های هفته",
        "month": "🗓️ برترین‌های ماه"
    }[period]

    rows = leaderboard_rows(period)

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    text = title + "\n\n"

    if not rows:
        text += (
            "هنوز امتیازی برای این بازه "
            "ثبت نشده است."
        )

    else:
        for i, (name, score) in enumerate(
            rows,
            1
        ):
            icon = (
                medals[i - 1]
                if i <= 3
                else str(i) + "."
            )

            text += (
                f"{icon} {name} — "
                f"⭐ {score}\n"
            )

    kb = {
        "inline_keyboard": [
            [
                {
                    "text": "🏆 کل",
                    "callback_data": "lb_all"
                },
                {
                    "text": "📅 هفته",
                    "callback_data": "lb_week"
                }
            ],
            [
                {
                    "text": "🗓️ ماه",
                    "callback_data": "lb_month"
                }
            ]
        ]
    }

    send_message(
        uid,
        text,
        kb
    )

def claim_daily_reward(uid):
    with db_lock:
        db = get_db()
        cur = db.cursor()

        try:
            cur.execute(
                """
                SELECT
                    last_daily_reward,
                    daily_streak
                FROM users
                WHERE user_id=%s
                FOR UPDATE
                """,
                (uid,)
            )

            row = cur.fetchone()

            if not row:
                db.rollback()
                return "missing", 0, 0

            last, streak = row

            today = datetime.now(
                timezone.utc
            ).date()

            if last == today:
                db.rollback()
                return "already", 0, streak

            yesterday = today - timedelta(days=1)

            if last == yesterday:
                streak = (streak or 0) + 1
            else:
                streak = 1

            bonus = min(
                streak // 7,
                3
            ) * 2

            reward = DAILY_REWARD + bonus

            cur.execute(
                """
                UPDATE users
                SET
                    score=score+%s,
                    last_daily_reward=%s,
                    daily_streak=%s
                WHERE user_id=%s
                """,
                (
                    reward,
                    today,
                    streak,
                    uid
                )
            )

            cur.execute(
                """
                INSERT INTO score_history(
                    user_id,
                    points,
                    reason
                )
                VALUES(%s,%s,%s)
                """,
                (
                    uid,
                    reward,
                    "جایزه روزانه"
                )
            )

            db.commit()

            return (
                "success",
                reward,
                streak
            )

        except Exception:
            db.rollback()
            raise

        finally:
            cur.close()
            db.close()
