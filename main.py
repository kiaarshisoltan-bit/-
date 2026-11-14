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

            result = (
                cur.fetchall()
                if fetchall
                else (
                    cur.fetchone()
                    if fetchone
                    else None
                )
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
                    ADD COLUMN IF NOT EXISTS
                    {column} {definition}
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
            """
            SELECT 1
            FROM users
            WHERE user_id=%s
            """,
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
            SELECT 1
            FROM users
            WHERE LOWER(BTRIM(name))=
                  LOWER(BTRIM(%s))
            LIMIT 1
        """

        p = (name,)

    else:

        q = """
            SELECT 1
            FROM users
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
        """
        SELECT name
        FROM users
        WHERE user_id=%s
        """,
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

        db_execute(
            """
            INSERT INTO users(
                user_id,
                name,
                score,
                invite_code,
                invited_by,
                referral_count
            )
            VALUES(%s,%s,0,%s,%s,0)
            """,
            (
                user_id,
                name,
                generate_unique_invite_code(),
                invited_by
            )
        )

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

    if not inviter_id or new_user_id == inviter_id:
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
        SET successful_answers=successful_answers+1
        WHERE user_id=%s
        """,
        (user_id,)
    )
  # =====================================================
# API بله
# =====================================================
def api_request(method, payload=None, timeout=30):

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

def answer_callback(callback_id, text=None):

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
# محتوا
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
                    message.get(
                        "caption",
                        ""
                    )
                    or ""
                ).strip()
            }

    voice = message.get("voice")

    if voice and voice.get("file_id"):

        return {
            "type": "voice",
            "file_id": voice["file_id"],
            "caption": (
                message.get(
                    "caption",
                    ""
                )
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
            (
                f"{prefix}\n\n{text}"
                if prefix
                else text
            )
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

    return (
        random.choice(items)
        if items
        else {
            "type": "truth",
            "prompt": "یک سؤال مناسب پاسخ بده."
        }
    )

def mode_name(mode):

    return {
        "normal": "🟢 معمولی و دوستانه",
        "fun": "🔥 خفن و چالشی",
        "minecraft": "⛏️ ماینکرفت",
        "fast": "⚡ سریع جواب بده"
    }.get(
        mode,
        "🟢 معمولی"
    )

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
        (
            "👤 پروفایل کاربری\n\n"
            f"👤 نام: {name}\n"
            f"⭐ امتیاز: {score}\n"
            f"🏆 رتبه: {rank}\n"
            f"🎮 بازی‌ها: {games}\n"
            f"✅ پاسخ‌های تأییدشده: {successes}\n"
            f"👥 زیرمجموعه‌ها: {refs}\n"
            f"🔥 استریک جایزه روزانه: {streak} روز\n"
            f"🔑 کد دعوت: {code}\n"
            f"📅 عضویت: {created_text}"
        ),
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
                f"{icon} {name} — ⭐ {score}\n"
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

            yesterday = (
                today - timedelta(days=1)
            )

            streak = (
                (streak or 0) + 1
                if last == yesterday
                else 1
            )

            bonus = (
                min(streak // 7, 3) * 2
            )

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
          # =====================================================
# دعوت
# =====================================================
def show_invite_info(uid):

    row = db_execute(
        """
        SELECT
            invite_code,
            referral_count,
            score
        FROM users
        WHERE user_id=%s
        """,
        (uid,),
        fetchone=True
    )

    if not row:
        return

    code, count, score = row

    link = (
        f"https://bale.ai/{BOT_USERNAME}?start={code}"
        if BOT_USERNAME
        else "BOT_USERNAME تنظیم نشده است."
    )

    send_message(
        uid,
        (
            "👥 دعوت دوستان\n\n"
            f"🔑 کد دعوت: {code}\n"
            f"🔗 لینک دعوت:\n{link}\n\n"
            f"👤 زیرمجموعه‌ها: {count}\n"
            f"⭐ امتیاز: {score}\n\n"
            "🎁 هر دعوت موفق:\n"
            f"• شما: {REFERRER_REWARD} امتیاز\n"
            f"• کاربر جدید: {NEW_USER_REWARD} امتیاز"
        ),
        get_main_menu()
    )

# =====================================================
# گزارش کاربر
# =====================================================
def start_report(uid):

    user_states[uid] = {
        "state": "report_target"
    }

    send_message(
        uid,
        (
            "🚫 گزارش کاربر\n\n"
            "شناسه عددی کاربر موردنظر را "
            "به صورت عدد ارسال کن.\n\n"
            "برای لغو: 🏠 منوی اصلی"
        )
    )

def create_report(
    reporter,
    target,
    reason
):

    db_execute(
        """
        INSERT INTO reports(
            reporter_id,
            target_user_id,
            reason
        )
        VALUES(%s,%s,%s)
        """,
        (
            reporter,
            target,
            reason
        )
    )

def show_open_reports(admin_id):

    rows = db_execute("""
        SELECT
            r.id,
            r.reporter_id,
            r.target_user_id,
            r.reason,
            r.created_at
        FROM reports r
        WHERE r.status='open'
        ORDER BY r.id DESC
        LIMIT 20
    """, fetchall=True) or []

    if not rows:

        send_message(
            admin_id,
            "✅ گزارش بازی وجود ندارد.",
            admin_menu()
        )

        return

    text = "🚫 گزارش‌های باز\n\n"
    kb = []

    for (
        rid,
        rep,
        target,
        reason,
        created
    ) in rows:

        text += (
            f"🆔 گزارش {rid}\n"
            f"👤 گزارش‌دهنده: {rep}\n"
            f"🎯 کاربر: {target}\n"
            f"📝 دلیل: {reason}\n\n"
        )

        kb.append([
            {
                "text": f"✅ بستن گزارش {rid}",
                "callback_data": (
                    f"close_report_{rid}"
                )
            }
        ])

    send_message(
        admin_id,
        text[:4000],
        {
            "inline_keyboard": kb[:20]
        }
    )

# =====================================================
# بازی تک‌نفره
# =====================================================
def start_single_game(uid):

    with state_lock:

        game = single_player.get(uid)

        if not game:
            return

        selected = get_random_prompt(
            game["mode"]
        )

        game.update(
            question_type=selected["type"],
            prompt=selected["prompt"],
            waiting_answer=True
        )

    title = (
        "🎯 حقیقت"
        if selected["type"] == "truth"
        else "🔥 جرئت"
    )

    send_message(
        uid,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎮 حالت: {mode_name(game['mode'])}\n\n"
            f"{title}\n\n"
            f"📝 {selected['prompt']}\n\n"
            "📩 پاسخ را با متن، عکس یا ویس ارسال کن.\n"
            "ℹ️ این بخش امتیازدهی ندارد."
        ),
        {
            "keyboard": [
                [
                    {"text": "🏠 منوی اصلی"}
                ]
            ],
            "resize_keyboard": True
        }
    )

def finish_single_game(uid):

    with state_lock:

        game = single_player.get(uid)

        if (
            not game
            or not game.get("waiting_answer")
        ):
            return

        game["waiting_answer"] = False

    add_game_played(uid)

    send_message(
        uid,
        (
            "✅ پاسخ دریافت شد.\n"
            "برای ادامه سؤال جدید را انتخاب کن."
        ),
        get_single_next_keyboard()
    )

# =====================================================
# اتاق‌ها و بازی آنلاین
# =====================================================
def generate_room_code():

    for _ in range(100):

        code = str(
            random.randint(
                1000,
                9999
            )
        )

        if code not in rooms:
            return code

    return None

def find_player_room(uid):

    for code, room in rooms.items():

        if uid in room.get(
            "players",
            []
        ):
            return code, room

    return None, None

def reset_round(room):

    room.update(
        questioner=None,
        answerer=None,
        question_type=None,
        question=None,
        answer=None,
        votes={},
        eligible_voters=[],
        vote_finished=False
    )

def create_room(uid, mode):

    with room_lock:

        _, old = find_player_room(uid)

        if old:

            send_message(
                uid,
                "⚠️ شما در حال حاضر عضو یک اتاق هستید."
            )

            return

        code = generate_room_code()

        if not code:

            send_message(
                uid,
                "❌ ساخت اتاق انجام نشد."
            )

            return

        rooms[code] = {
            "host": uid,
            "players": [uid],
            "mode": mode,
            "phase": "waiting",
            "round": 0,
            "questioner": None,
            "answerer": None,
            "question_type": None,
            "question": None,
            "answer": None,
            "votes": {},
            "eligible_voters": [],
            "vote_finished": False
        }

    send_message(
        uid,
        (
            "✅ اتاق ساخته شد!\n\n"
            f"🔢 کد اتاق: {code}\n"
            f"🎮 حالت: {mode_name(mode)}\n\n"
            "کد اتاق را برای دوستانت بفرست."
        ),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "🚀 شروع بازی",
                        "callback_data": (
                            f"start_{code}"
                        )
                    }
                ],
                [
                    {
                        "text": "🗑️ حذف اتاق",
                        "callback_data": (
                            f"delete_{code}"
                        )
                    }
                ]
            ]
        }
    )

def list_rooms(uid):

    with room_lock:

        available = [
            (c, r)
            for c, r in rooms.items()
            if r.get("phase") == "waiting"
        ]

    if not available:

        send_message(
            uid,
            "📭 فعلاً اتاقی برای پیوستن وجود ندارد."
        )

        return

    kb = [
        [
            {
                "text": (
                    f"🚪 اتاق {c} | "
                    f"{len(r['players'])} نفر"
                ),
                "callback_data": f"join_{c}"
            }
        ]
        for c, r in available
    ]

    send_message(
        uid,
        "🚪 یکی از اتاق‌ها را انتخاب کن:",
        {
            "inline_keyboard": kb
        }
    )

def leave_room(uid):

    with room_lock:

        code, room = find_player_room(uid)

        if not room:

            send_message(
                uid,
                "⚠️ شما داخل هیچ اتاقی نیستید."
            )

            return

        room["players"].remove(uid)

        players = list(
            room["players"]
        )

        if (
            room["host"] == uid
            and players
        ):
            room["host"] = players[0]

        if len(players) < 2:

            room["phase"] = "waiting"
            reset_round(room)

        if not players:
            del rooms[code]

    send_message(
        uid,
        "🚪 از اتاق خارج شدی.",
        get_main_menu()
    )

    for p in players:

        send_message(
            p,
            (
                f"👋 {get_name(uid)} "
                "از اتاق خارج شد."
            )
        )

def start_online_round(code):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        players = list(
            room["players"]
        )

        if len(players) < 2:

            room["phase"] = "waiting"
            reset_round(room)

            return

        if room["phase"] not in (
            "waiting",
            "between_rounds"
        ):
            return

        reset_round(room)

        room["round"] += 1

        q, a = random.sample(
            players,
            2
        )

        room.update(
            questioner=q,
            answerer=a,
            phase="choosing_type"
        )

        rnd = room["round"]

    base = (
        f"🎮 دور {rnd}\n\n"
        f"✍️ پرسش‌کننده: {get_name(q)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(a)}"
    )

    for p in players:

        if p == a:

            send_message(
                p,
                base + "\n\n🎯 انتخاب کن:",
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎯 حقیقت",
                                "callback_data": (
                                    f"truth_{code}"
                                )
                            },
                            {
                                "text": "🔥 جرئت",
                                "callback_data": (
                                    f"dare_{code}"
                                )
                            }
                        ]
                    ]
                }
            )

        else:

            send_message(
                p,
                base + "\n\n⏳ منتظر انتخاب پاسخ‌دهنده باش."
            )

def publish_question(code):

    with room_lock:

        room = rooms.get(code)

        if (
            not room
            or room["phase"] != "waiting_question"
            or not room.get("question")
        ):
            return

        room["phase"] = "waiting_answer"

        players = list(room["players"])
        q = room["questioner"]
        a = room["answerer"]
        typ = room["question_type"]
        question = room["question"]

    prefix = (
        f"📢 {'🎯 حقیقت' if typ == 'truth' else '🔥 جرئت'}\n\n"
        f"✍️ پرسش‌کننده: {get_name(q)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(a)}\n\n"
        "❓ سؤال یا چالش:"
    )

    for p in players:

        send_content(
            p,
            question,
            prefix
        )

        send_message(
            p,
            (
                "📩 حالا پاسخ خودت را ارسال کن.\n"
                "می‌توانی متن، عکس یا ویس بفرستی."
                if p == a
                else "⏳ منتظر پاسخ بازیکن باش."
            )
        )

def publish_answer_and_start_vote(code):

    with room_lock:

        room = rooms.get(code)

        if (
            not room
            or room["phase"] != "waiting_answer"
            or not room.get("answer")
        ):
            return

        answerer = room["answerer"]
        players = list(room["players"])
        answer = room["answer"]

        room["eligible_voters"] = [
            p
            for p in players
            if p != answerer
        ]

        room["votes"] = {}
        room["vote_finished"] = False
        room["phase"] = "voting"

    prefix = (
        "💬 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}\n\n"
        "📨 پاسخ:"
    )

    kb = {
        "inline_keyboard": [
            [
                {
                    "text": "👍 تأیید",
                    "callback_data": f"yes_{code}"
                },
                {
                    "text": "👎 رد",
                    "callback_data": f"no_{code}"
                }
            ]
        ]
    }

    for p in players:

        send_content(
            p,
            answer,
            prefix
        )

        send_message(
            p,
            (
                "⏳ رأی‌گیری شروع شد."
                if p == answerer
                else (
                    "🗳️ آیا پاسخ مورد قبول است؟\n"
                    f"⏱️ {VOTE_TIMEOUT} ثانیه فرصت داری."
                )
            ),
            (
                None
                if p == answerer
                else kb
            )
        )

    threading.Thread(
        target=vote_timer,
        args=(code,),
        daemon=True
    ).start()

def vote_timer(code):

    time.sleep(VOTE_TIMEOUT)

    finish_online_voting(
        code,
        True
    )

def register_vote(
    code,
    uid,
    vote
):

    should = False

    with room_lock:

        room = rooms.get(code)

        if not room:
            status = "no_room"

        elif room["phase"] != "voting":
            status = "not_voting"

        elif room["vote_finished"]:
            status = "finished"

        elif uid not in room["eligible_voters"]:
            status = "not_allowed"

        elif uid in room["votes"]:
            status = "already"

        else:

            room["votes"][uid] = vote
            status = "success"

            should = (
                len(room["votes"])
                >= len(room["eligible_voters"])
            )

    send_message(
        uid,
        {
            "no_room": "❌ این اتاق وجود ندارد.",
            "not_voting": "⚠️ رأی‌گیری فعال نیست.",
            "finished": "⚠️ رأی‌گیری تمام شده است.",
            "not_allowed": "⚠️ شما اجازه رأی دادن ندارید.",
            "already": "⚠️ شما قبلاً رأی داده‌اید.",
            "success": "✅ رأی شما ثبت شد."
        }[status]
    )

    if should:
        finish_online_voting(code)

def finish_online_voting(
    code,
    force=False
):

    with room_lock:

        room = rooms.get(code)

        if (
            not room
            or room["phase"] != "voting"
            or room["vote_finished"]
        ):
            return

        if (
            not force
            and len(room["votes"])
            < len(room["eligible_voters"])
        ):
            return

        room["vote_finished"] = True
        room["phase"] = "between_rounds"

        votes = dict(room["votes"])
        players = list(room["players"])
        answerer = room["answerer"]

    yes = sum(
        v == "yes"
        for v in votes.values()
    )

    no = sum(
        v == "no"
        for v in votes.values()
    )

    if yes > no:

        add_score(
            answerer,
            10,
            "پاسخ موفق در بازی آنلاین"
        )

        add_successful_answer(answerer)

        result = (
            "🎉 پاسخ توسط اکثریت تأیید شد!\n"
            "⭐ ۱۰ امتیاز به پاسخ‌دهنده اضافه شد."
        )

    elif yes == 0 and no == 0:

        result = (
            "⏰ زمان رأی‌گیری تمام شد.\n"
            "هیچ رأیی ثبت نشد."
        )

    elif no > yes:

        result = (
            "❌ پاسخ توسط اکثریت رد شد.\n"
            "امتیازی داده نشد."
        )

    else:

        result = (
            "⚖️ رأی‌ها مساوی بودند.\n"
            "امتیازی داده نشد."
        )

    add_game_played(answerer)

    text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes}\n"
        f"👎 رد: {no}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی آماده می‌شود..."
    )

    for p in players:
        send_message(p, text)

    threading.Thread(
        target=start_next_round,
        args=(code,),
        daemon=True
    ).start()

def start_next_round(code):

    time.sleep(3)

    start_online_round(code)

# =====================================================
# پنل ادمین
# =====================================================
def is_admin(uid):
    return uid in ADMIN_IDS

def show_admin_stats(uid):

    users = db_execute(
        "SELECT COUNT(*) FROM users",
        fetchone=True
    )[0]

    reports = db_execute(
        """
        SELECT COUNT(*)
        FROM reports
        WHERE status='open'
        """,
        fetchone=True
    )[0]

    scores = db_execute(
        """
        SELECT COALESCE(SUM(score),0)
        FROM users
        """,
        fetchone=True
    )[0]

    with room_lock:
        active = len(rooms)

    send_message(
        uid,
        (
            "📊 آمار ربات\n\n"
            f"👥 کاربران: {users}\n"
            f"🎮 اتاق‌های حافظه: {active}\n"
            f"🚫 گزارش‌های باز: {reports}\n"
            f"⭐ مجموع امتیازات: {scores}"
        ),
        admin_menu()
    )

def broadcast(text, admin_id):

    rows = db_execute(
        """
        SELECT user_id
        FROM users
        """,
        fetchall=True
    ) or []

    ok = 0

    for (uid,) in rows:

        if send_message(uid, text):
            ok += 1

        time.sleep(0.03)

    send_message(
        admin_id,
        (
            "✅ پیام همگانی ارسال شد.\n"
            f"📨 موفق: {ok} از {len(rows)}"
        ),
        admin_menu()
    )
  # =====================================================
# پیام‌ها
# =====================================================
def handle_message(message):

    uid = message.get(
        "chat",
        {}
    ).get("id")

    if not uid:
        return

    content = get_content_from_message(message)

    text = (
        content["text"]
        if content and content["type"] == "text"
        else ""
    )

    # =================================================
    # ثبت‌نام
    # =================================================
    if not user_exists(uid):

        with state_lock:
            state = user_states.get(uid)

        if text.startswith("/start"):

            parts = text.split(
                maxsplit=1
            )

            deep_code = (
                parts[1].strip().upper()
                if len(parts) > 1
                else None
            )

            inviter_id = None

            if deep_code:

                inv = get_user_by_invite_code(
                    deep_code
                )

                if inv and inv[0] != uid:
                    inviter_id = inv[0]

                with state_lock:

                    user_states[uid] = {
                        "state": "register_name",
                        "inviter_id": inviter_id
                    }

                send_message(
                    uid,
                    (
                        "🎉 شما با لینک دعوت وارد شدید!\n\n"
                        "حالا یک نام مستعار انتخاب کن "
                        "و به صورت متن بفرست.\n"
                        "⚠️ نام تکراری پذیرفته نمی‌شود."
                    )
                )

            else:

                with state_lock:

                    user_states[uid] = {
                        "state": "ask_invite"
                    }

                send_message(
                    uid,
                    (
                        "👋 سلام! آیا کد دعوت داری؟\n\n"
                        "اگر داری کد را ارسال کن.\n"
                        "اگر نداری روی دکمه "
                        "«❌ کد دعوت ندارم» بزن."
                    ),
                    {
                        "keyboard": [
                            [
                                {
                                    "text": "❌ کد دعوت ندارم"
                                }
                            ]
                        ],
                        "resize_keyboard": True
                    }
                )

            return

        if (
            state
            and state.get("state") == "ask_invite"
        ):

            if text == "❌ کد دعوت ندارم":

                with state_lock:

                    user_states[uid] = {
                        "state": "register_name",
                        "inviter_id": None
                    }

                send_message(
                    uid,
                    (
                        "👤 حالا یک نام مستعار انتخاب کن "
                        "و به صورت متن ارسال کن."
                    )
                )

                return

            if not text:

                send_message(
                    uid,
                    (
                        "⚠️ کد دعوت را به صورت متن "
                        "ارسال کن یا گزینه «کد دعوت ندارم» "
                        "را انتخاب کن."
                    )
                )

                return

            inv = get_user_by_invite_code(text)

            if not inv:

                send_message(
                    uid,
                    (
                        "❌ این کد دعوت معتبر نیست.\n"
                        "دوباره امتحان کن یا "
                        "«❌ کد دعوت ندارم» را بزن."
                    )
                )

                return

            with state_lock:

                user_states[uid] = {
                    "state": "register_name",
                    "inviter_id": inv[0]
                }

            send_message(
                uid,
                (
                    f"✅ کد دعوت {get_name(inv[0])} "
                    "پذیرفته شد.\n\n"
                    "حالا نام مستعار خودت را ارسال کن."
                )
            )

            return

        if (
            not state
            or state.get("state") != "register_name"
        ):

            send_message(
                uid,
                "برای شروع ابتدا /start را ارسال کن."
            )

            return

        if not text:

            send_message(
                uid,
                "⚠️ لطفاً نام را فقط به صورت متن ارسال کن."
            )

            return

        name = normalize_name(text[:40])

        if len(name) < 2:

            send_message(
                uid,
                "⚠️ نام باید حداقل ۲ کاراکتر باشد."
            )

            return

        if name_exists(name):

            send_message(
                uid,
                (
                    "❌ این نام قبلاً انتخاب شده است.\n"
                    "نام دیگری انتخاب کن."
                )
            )

            return

        inviter = state.get("inviter_id")

        if not save_new_user(
            uid,
            name,
            inviter
        ):

            send_message(
                uid,
                (
                    "❌ ثبت‌نام انجام نشد. "
                    "دوباره تلاش کن."
                )
            )

            return

        rewarded = (
            reward_referral(uid, inviter)
            if inviter
            else False
        )

        with state_lock:
            user_states.pop(uid, None)

        welcome = (
            f"🎉 خوش آمدی {name}!\n\n"
            "حساب کاربری تو ساخته شد."
        )

        if rewarded:

            welcome += (
                f"\n\n🎁 {NEW_USER_REWARD} "
                "امتیاز جایزه دعوت دریافت کردی!"
            )

            send_message(
                inviter,
                (
                    "🔔 اعلان دعوت\n\n"
                    f"🎉 {name} با کد دعوت شما عضو شد!\n"
                    f"⭐ {REFERRER_REWARD} امتیاز "
                    "به شما اضافه شد."
                )
            )

        send_message(
            uid,
            welcome,
            get_main_menu()
        )

        return

    # =================================================
    # کاربران ثبت‌شده
    # =================================================
    if text.startswith("/start"):

        send_message(
            uid,
            (
                f"👋 سلام {get_name(uid)}!\n\n"
                "به بازی حقیقت یا جرئت خوش آمدی."
            ),
            get_main_menu()
        )

        return

    with state_lock:
        state = user_states.get(uid)

    # =================================================
    # تغییر نام
    # =================================================
    if (
        state
        and state.get("state") == "change_name"
    ):

        if not text:

            send_message(
                uid,
                "⚠️ نام را به صورت متن ارسال کن."
            )

            return

        name = normalize_name(text[:40])

        if len(name) < 2:

            send_message(
                uid,
                "⚠️ نام باید حداقل ۲ کاراکتر باشد."
            )

            return

        if name_exists(name, uid):

            send_message(
                uid,
                "❌ این نام قبلاً انتخاب شده است."
            )

            return

        if not change_user_name(uid, name):

            send_message(
                uid,
                "❌ تغییر نام انجام نشد."
            )

            return

        with state_lock:
            user_states.pop(uid, None)

        send_message(
            uid,
            f"✅ نام جدید شما: {name}",
            get_main_menu()
        )

        return

    # =================================================
    # گزارش کاربر
    # =================================================
    if (
        state
        and state.get("state") == "report_target"
    ):

        if not text or not text.isdigit():

            send_message(
                uid,
                "⚠️ شناسه عددی کاربر را وارد کن."
            )

            return

        target = int(text)

        if target == uid:

            send_message(
                uid,
                "⚠️ نمی‌توانی خودت را گزارش کنی."
            )

            return

        with state_lock:

            user_states[uid] = {
                "state": "report_reason",
                "target": target
            }

        send_message(
            uid,
            "📝 دلیل گزارش را به صورت متن ارسال کن."
        )

        return

    if (
        state
        and state.get("state") == "report_reason"
    ):

        if not text:

            send_message(
                uid,
                "⚠️ دلیل گزارش را به صورت متن ارسال کن."
            )

            return

        create_report(
            uid,
            state["target"],
            text[:1000]
        )

        with state_lock:
            user_states.pop(uid, None)

        send_message(
            uid,
            (
                "✅ گزارش شما ثبت شد و "
                "توسط مدیریت بررسی می‌شود."
            ),
            get_main_menu()
        )

        return

    # =================================================
    # ادمین: پیام همگانی
    # =================================================
    if (
        state
        and state.get("state") == "admin_broadcast"
        and is_admin(uid)
    ):

        if not content:

            send_message(
                uid,
                "⚠️ پیام را ارسال کن."
            )

            return

        if content["type"] != "text":

            send_message(
                uid,
                (
                    "⚠️ در این نسخه پیام همگانی "
                    "فقط به صورت متن است."
                )
            )

            return

        with state_lock:
            user_states.pop(uid, None)

        threading.Thread(
            target=broadcast,
            args=(
                content["text"],
                uid
            ),
            daemon=True
        ).start()

        send_message(
            uid,
            "⏳ ارسال پیام همگانی شروع شد..."
        )

        return

    # =================================================
    # ادمین: تغییر امتیاز
    # =================================================
    if (
        state
        and state.get("state") == "admin_score_user"
        and is_admin(uid)
    ):

        if not text or not text.isdigit():

            send_message(
                uid,
                "⚠️ شناسه عددی کاربر را وارد کن."
            )

            return

        if not user_exists(int(text)):

            send_message(
                uid,
                "❌ کاربر پیدا نشد."
            )

            return

        with state_lock:

            user_states[uid] = {
                "state": "admin_score_amount",
                "target": int(text),
                "sign": state["sign"]
            }

        send_message(
            uid,
            "🔢 تعداد امتیاز را به صورت عدد مثبت وارد کن."
        )

        return

    if (
        state
        and state.get("state") == "admin_score_amount"
        and is_admin(uid)
    ):

        try:
            amount = int(text)

        except Exception:

            send_message(
                uid,
                "⚠️ عدد معتبر وارد کن."
            )

            return

        if amount <= 0:

            send_message(
                uid,
                "⚠️ عدد باید مثبت باشد."
            )

            return

        points = amount * state["sign"]

        add_score(
            state["target"],
            points,
            "تغییر امتیاز توسط ادمین"
        )

        target = state["target"]

        with state_lock:
            user_states.pop(uid, None)

        send_message(
            uid,
            (
                f"✅ {abs(points)} امتیاز "
                f"{'اضافه' if points > 0 else 'کم'} شد."
            ),
            admin_menu()
        )

        send_message(
            target,
            (
                "🔔 امتیاز شما توسط مدیریت "
                f"{'افزایش' if points > 0 else 'کاهش'} یافت: "
                f"{abs(points)}"
            )
        )

        return

    # =================================================
    # ادمین: اطلاعات کاربر
    # =================================================
    if (
        state
        and state.get("state") == "admin_user_info"
        and is_admin(uid)
    ):

        if not text or not text.isdigit():

            send_message(
                uid,
                "⚠️ شناسه عددی کاربر را وارد کن."
            )

            return

        target = int(text)

        row = db_execute(
            """
            SELECT
                name,
                score,
                referral_count,
                games_played,
                successful_answers
            FROM users
            WHERE user_id=%s
            """,
            (target,),
            fetchone=True
        )

        with state_lock:
            user_states.pop(uid, None)

        if not row:

            send_message(
                uid,
                "❌ کاربر پیدا نشد.",
                admin_menu()
            )

            return

        send_message(
            uid,
            (
                "👤 اطلاعات کاربر\n\n"
                f"🆔 {target}\n"
                f"👤 نام: {row[0]}\n"
                f"⭐ امتیاز: {row[1]}\n"
                f"👥 زیرمجموعه: {row[2]}\n"
                f"🎮 بازی: {row[3]}\n"
                f"✅ پاسخ موفق: {row[4]}"
            ),
            admin_menu()
        )

        return

    # =================================================
    # بازی تک‌نفره
    # =================================================
    with state_lock:

        game = single_player.get(uid)

        waiting = bool(
            game
            and game.get("waiting_answer")
        )

    if waiting:

        if text == "🏠 منوی اصلی":

            with state_lock:
                single_player.pop(uid, None)

            send_message(
                uid,
                "🏠 منوی اصلی",
                get_main_menu()
            )

            return

        if content:

            finish_single_game(uid)

            return

    # =================================================
    # سؤال آنلاین
    # =================================================
    with room_lock:

        code, room = find_player_room(uid)

        question_code = (
            code
            if (
                room
                and room["phase"] == "waiting_question"
                and room["questioner"] == uid
            )
            else None
        )

    if question_code:

        if not content:

            send_message(
                uid,
                "⚠️ سؤال را به صورت متن، عکس یا ویس ارسال کن."
            )

            return

        with room_lock:

            room = rooms.get(question_code)

            if (
                room
                and room["phase"] == "waiting_question"
                and room["questioner"] == uid
            ):

                room["question"] = content

            else:
                return

        publish_question(question_code)

        return

    # =================================================
    # جواب آنلاین
    # =================================================
    with room_lock:

        code, room = find_player_room(uid)

        answer_code = (
            code
            if (
                room
                and room["phase"] == "waiting_answer"
                and room["answerer"] == uid
            )
            else None
        )

    if answer_code:

        if not content:

            send_message(
                uid,
                "⚠️ جواب را به صورت متن، عکس یا ویس ارسال کن."
            )

            return

        with room_lock:

            room = rooms.get(answer_code)

            if (
                room
                and room["phase"] == "waiting_answer"
                and room["answerer"] == uid
            ):

                room["answer"] = content

            else:
                return

        publish_answer_and_start_vote(answer_code)

        return

    # =================================================
    # دکمه‌ها
    # =================================================
    if text == "⏭️ سؤال جدید":

        if uid in single_player:
            start_single_game(uid)

        return

    if text == "🏠 منوی اصلی":

        with state_lock:

            user_states.pop(uid, None)
            single_player.pop(uid, None)

        send_message(
            uid,
            "🏠 منوی اصلی",
            get_main_menu()
        )

        return

    if text == "🤖 بازی تک‌نفره":

        user_states[uid] = {
            "state": "choosing_single_mode"
        }

        send_message(
            uid,
            "🎮 حالت بازی را انتخاب کن:",
            get_modes_keyboard()
        )

        return

    if text == "👤 پروفایل من":
        show_profile(uid)
        return

    if text == "🎁 جایزه روزانه":

        status, reward, streak = claim_daily_reward(uid)

        if status == "success":

            send_message(
                uid,
                (
                    "🎁 جایزه روزانه دریافت شد!\n\n"
                    f"⭐ {reward} امتیاز گرفتی.\n"
                    f"🔥 استریک: {streak} روز"
                ),
                get_main_menu()
            )

        else:

            send_message(
                uid,
                (
                    "⏳ جایزه امروز را قبلاً دریافت کرده‌ای.\n"
                    "فردا دوباره بیا!"
                ),
                get_main_menu()
            )

        return

    if text == "👥 دعوت دوستان":
        show_invite_info(uid)
        return

    if text in (
        "🏆 رتبه‌بندی",
        "🏆 جدول امتیازات"
    ):

        show_leaderboard(uid, "all")
        return

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            uid,
            "🎮 بخش بازی آنلاین",
            get_rooms_menu()
        )

        return

    if text == "🛠️ ساخت اتاق جدید":

        _, room = find_player_room(uid)

        if room:

            send_message(
                uid,
                "⚠️ ابتدا از اتاق فعلی خارج شو."
            )

            return

        user_states[uid] = {
            "state": "choosing_room_mode"
        }

        send_message(
            uid,
            "🎮 حالت اتاق را انتخاب کن:",
            get_modes_keyboard()
        )

        return

    if text == "🚪 پیوستن به اتاق":
        list_rooms(uid)
        return

    if text == "🚪 خروج از اتاق":
        leave_room(uid)
        return

    if text == "✏️ تغییر نام":

        user_states[uid] = {
            "state": "change_name"
        }

        send_message(
            uid,
            (
                "✏️ نام جدید خود را به صورت متن ارسال کن.\n"
                "⚠️ نام تکراری پذیرفته نمی‌شود."
            )
        )

        return

    if text == "🚫 گزارش کاربر":
        start_report(uid)
        return

    if text == "📢 کانال اطلاع‌رسانی":

        send_message(
            uid,
            (
                "📢 کانال اطلاع‌رسانی:\n"
                "@ettelae_resani"
            )
        )

        return

    if text == "💬 پشتیبانی":

        send_message(
            uid,
            (
                "💬 پشتیبانی:\n"
                "@kia_karfarma"
            )
        )

        return

    if text == "📖 راهنمای بازی":

        send_message(
            uid,
            (
                "📖 راهنمای بازی\n\n"
                f"👥 دعوت: دعوت‌کننده {REFERRER_REWARD} "
                f"و کاربر جدید {NEW_USER_REWARD} "
                "امتیاز می‌گیرند.\n\n"
                "🤖 تک‌نفره: ربات سؤال تصادفی می‌دهد؛ "
                "متن، عکس یا ویس بفرست.\n\n"
                "🎮 آنلاین: پرسش‌کننده و پاسخ‌دهنده "
                "به صورت تصادفی انتخاب می‌شوند و "
                "سایر بازیکنان رأی می‌دهند.\n\n"
                "🎁 جایزه روزانه: روزی یک‌بار دریافت کن.\n"
                "🚫 گزارش: کاربران نامناسب را گزارش کن."
            ),
            get_main_menu()
        )

        return

    # =================================================
    # پنل ادمین
    # =================================================
    if is_admin(uid):

        if text == "🛠️ پنل ادمین":

            send_message(
                uid,
                "🛠️ پنل مدیریت",
                admin_menu()
            )

            return

        if text == "📊 آمار ربات":
            show_admin_stats(uid)
            return

        if text == "🚫 گزارش‌های باز":
            show_open_reports(uid)
            return

        if text == "📢 پیام همگانی":

            user_states[uid] = {
                "state": "admin_broadcast"
            }

            send_message(
                uid,
                "📢 متن پیام همگانی را ارسال کن."
            )

            return

        if text in (
            "➕ افزایش امتیاز",
            "➖ کاهش امتیاز"
        ):

            user_states[uid] = {
                "state": "admin_score_user",
                "sign": (
                    1
                    if text.startswith("➕")
                    else -1
                )
            }

            send_message(
                uid,
                "🆔 شناسه عددی کاربر را ارسال کن."
            )

            return

        if text == "👤 اطلاعات کاربر":

            user_states[uid] = {
                "state": "admin_user_info"
            }

            send_message(
                uid,
                "🆔 شناسه عددی کاربر را ارسال کن."
            )

            return

    if text:

        send_message(
            uid,
            "⚠️ لطفاً از دکمه‌های منو استفاده کن.",
            get_main_menu()
        )

# =====================================================
# Callback
# =====================================================
def handle_callback(query):

    callback_id = query.get("id")
    data = query.get("data", "")
    uid = query.get(
        "from",
        {}
    ).get("id")

    if callback_id:
        answer_callback(callback_id)

    if not uid or not data:
        return

    if data == "back_menu":

        user_states.pop(uid, None)

        send_message(
            uid,
            "🏠 منوی اصلی",
            get_main_menu()
        )

        return

    if data.startswith("lb_"):

        show_leaderboard(
            uid,
            data.replace("lb_", "", 1)
        )

        return

    if data.startswith("mode_"):

        mode = data[5:]

        state = user_states.get(
            uid,
            {}
        ).get("state")

        if state == "choosing_single_mode":

            user_states.pop(uid, None)

            single_player[uid] = {
                "mode": mode,
                "waiting_answer": False
            }

            start_single_game(uid)

            return

        if state == "choosing_room_mode":

            user_states.pop(uid, None)

            create_room(uid, mode)

            return

    if data.startswith("join_"):

        code = data[5:]

        with room_lock:

            room = rooms.get(code)

            if not room:
                status = "not_found"

            elif room["phase"] != "waiting":
                status = "started"

            elif (
                len(room["players"])
                >= MAX_ROOM_PLAYERS
            ):
                status = "full"

            elif find_player_room(uid)[1]:
                status = "other_room"

            else:

                room["players"].append(uid)

                players = list(
                    room["players"]
                )

                status = "success"

        if status != "success":

            send_message(
                uid,
                {
                    "not_found": "❌ اتاق وجود ندارد.",
                    "started": (
                        "❌ بازی این اتاق شروع شده است."
                    ),
                    "full": (
                        "❌ ظرفیت اتاق تکمیل شده است."
                    ),
                    "other_room": (
                        "⚠️ ابتدا از اتاق فعلی خارج شو."
                    )
                }[status]
            )

            return

        send_message(
            uid,
            f"✅ وارد اتاق {code} شدی.",
            get_rooms_menu()
        )

        for p in players:

            if p != uid:

                send_message(
                    p,
                    (
                        f"👤 {get_name(uid)} "
                        "به اتاق پیوست."
                    )
                )

        return

    if data.startswith("start_"):

        code = data[6:]

        with room_lock:

            room = rooms.get(code)

            if not room:
                status = "not_found"

            elif room["host"] != uid:
                status = "not_host"

            elif len(room["players"]) < 2:
                status = "not_enough"

            elif room["phase"] != "waiting":
                status = "started"

            else:
                status = "success"

        if status != "success":

            send_message(
                uid,
                {
                    "not_found": "❌ اتاق وجود ندارد.",
                    "not_host": (
                        "⚠️ فقط میزبان می‌تواند شروع کند."
                    ),
                    "not_enough": (
                        "⚠️ حداقل ۲ بازیکن لازم است."
                    ),
                    "started": (
                        "⚠️ بازی قبلاً شروع شده است."
                    )
                }[status]
            )

            return

        start_online_round(code)

        return

    if data.startswith("delete_"):

        code = data[7:]

        with room_lock:

            room = rooms.get(code)

            if not room:
                status = "not_found"

            elif room["host"] != uid:
                status = "not_host"

            else:

                players = list(
                    room["players"]
                )

                del rooms[code]

                status = "success"

        if status != "success":

            send_message(
                uid,
                (
                    "❌ اتاق وجود ندارد."
                    if status == "not_found"
                    else (
                        "⚠️ فقط میزبان می‌تواند "
                        "اتاق را حذف کند."
                    )
                )
            )

            return

        for p in players:

            send_message(
                p,
                "❌ اتاق توسط میزبان بسته شد.",
                get_main_menu()
            )

        return

    if data.startswith((
        "truth_",
        "dare_"
    )):

        choice, code = data.split(
            "_",
            1
        )

        with room_lock:

            room = rooms.get(code)

            if not room:
                status = "not_found"

            elif room["phase"] != "choosing_type":
                status = "wrong"

            elif room["answerer"] != uid:
                status = "not_answerer"

            else:

                room["question_type"] = choice
                room["phase"] = "waiting_question"

                q = room["questioner"]

                players = list(
                    room["players"]
                )

                status = "success"

        if status != "success":

            send_message(
                uid,
                (
                    "❌ اتاق وجود ندارد."
                    if status == "not_found"
                    else (
                        "⚠️ فقط پاسخ‌دهنده می‌تواند "
                        "این انتخاب را انجام دهد."
                    )
                )
            )

            return

        choice_text = (
            "🎯 حقیقت"
            if choice == "truth"
            else "🔥 جرئت"
        )

        for p in players:

            send_message(
                p,
                (
                    f"✅ انتخاب پاسخ‌دهنده: "
                    f"{choice_text}\n\n"
                    "✍️ حالا سؤال یا چالش خودت را "
                    "ارسال کن.\n"
                    "می‌توانی 📝 متن، 📷 عکس یا "
                    "🎤 ویس بفرستی."
                    if p == q
                    else (
                        f"✅ انتخاب شد: {choice_text}\n\n"
                        "⏳ منتظر ارسال سؤال یا چالش باش."
                    )
                )
            )

        return

    if data.startswith("yes_"):

        register_vote(
            data[4:],
            uid,
            "yes"
        )

        return

    if data.startswith("no_"):

        register_vote(
            data[3:],
            uid,
            "no"
        )

        return

    if data.startswith("close_report_"):

        if not is_admin(uid):
            return

        try:

            rid = int(
                data.replace(
                    "close_report_",
                    "",
                    1
                )
            )

        except ValueError:
            return

        db_execute(
            """
            UPDATE reports
            SET
                status='closed',
                resolved_at=CURRENT_TIMESTAMP,
                resolved_by=%s
            WHERE id=%s
            AND status='open'
            """,
            (
                uid,
                rid
            )
        )

        send_message(
            uid,
            f"✅ گزارش {rid} بسته شد.",
            admin_menu()
        )

# =====================================================
# Update و Polling
# =====================================================
def handle_update(update):

    try:

        if "message" in update:

            handle_message(
                update["message"]
            )

        elif "callback_query" in update:

            handle_callback(
                update["callback_query"]
            )

    except Exception as e:

        print(
            "❌ Update Error:",
            repr(e)
        )

def run_polling():

    offset = None

    print("🤖 Polling started")

    while True:

        try:

            params = {
                "timeout": 30
            }

            if offset is not None:
                params["offset"] = offset

            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params=params,
                timeout=45
            )

            data = r.json()

            if not data.get("ok"):

                print(
                    "❌ getUpdates Error:",
                    data
                )

                time.sleep(3)

                continue

            for update in data.get(
                "result",
                []
            ):

                if (
                    update.get("update_id")
                    is not None
                ):

                    offset = (
                        update["update_id"] + 1
                    )

                handle_update(update)

        except requests.exceptions.Timeout:
            continue

        except Exception as e:

            print(
                "❌ Polling Error:",
                repr(e)
            )

            time.sleep(5)

# =====================================================
# اجرا
# =====================================================
if __name__ == "__main__":

    print("🚀 Starting Bale Bot...")

    init_database()

    threading.Thread(
        target=run_polling,
        daemon=True
    ).start()

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
