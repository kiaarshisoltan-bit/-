import os
import random
import threading
import time
import secrets
import string

import requests
import psycopg2

from flask import Flask, jsonify


# =====================================================
# تنظیمات
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PORT = int(os.getenv("PORT", "10000"))

# نام کاربری ربات را در Environment Variables قرار بده
# مثال: BOT_USERNAME=my_bot
BOT_USERNAME = os.getenv("BOT_USERNAME", "").strip().lstrip("@")

VOTE_TIMEOUT = 60
MAX_ROOM_PLAYERS = 20

# امتیاز دعوت
REFERRER_REWARD = 5
NEW_USER_REWARD = 2

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL تنظیم نشده است.")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

app = Flask(__name__)


# =====================================================
# Lock ها و اطلاعات موقت
# =====================================================

db_lock = threading.Lock()
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

    return jsonify({
        "status": "ok",
        "rooms": room_count
    })


# =====================================================
# دیتابیس
# =====================================================

def get_db():

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def generate_invite_code():

    chars = string.ascii_uppercase + string.digits

    return "".join(
        secrets.choice(chars)
        for _ in range(8)
    )


def generate_unique_invite_code():

    for _ in range(100):

        code = generate_invite_code()

        with db_lock:

            db = get_db()
            cur = db.cursor()

            try:

                cur.execute(
                    """
                    SELECT 1
                    FROM users
                    WHERE invite_code = %s
                    LIMIT 1
                    """,
                    (code,)
                )

                exists = cur.fetchone() is not None

            finally:

                cur.close()
                db.close()

        if not exists:
            return code

    # حالت بسیار نادر
    return (
        secrets.token_hex(8)
        .upper()
    )


def init_database():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            # جدول اصلی
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    invite_code TEXT,
                    invited_by BIGINT,
                    referral_count INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db.commit()

            # برای دیتابیس‌های قدیمی
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS invite_code TEXT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS invited_by BIGINT
            """)

            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS referral_count INTEGER DEFAULT 0
            """)

            db.commit()

            # نام یکتا
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS users_unique_name_ci
                ON users (LOWER(BTRIM(name)))
            """)

            # کد دعوت یکتا
            cur.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS users_unique_invite_code
                ON users (invite_code)
                WHERE invite_code IS NOT NULL
            """)

            db.commit()

        except Exception as error:

            db.rollback()

            print(
                "❌ Database init error:",
                error
            )

            raise

        finally:

            cur.close()
            db.close()

    # ایجاد کد دعوت برای کاربران قدیمی
    fix_old_invite_codes()

    print("✅ PostgreSQL database initialized")


def fix_old_invite_codes():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT user_id
                FROM users
                WHERE invite_code IS NULL
                OR invite_code = ''
            """)

            users = cur.fetchall()

        finally:

            cur.close()
            db.close()

    for row in users:

        user_id = row[0]

        for _ in range(20):

            code = generate_invite_code()

            try:

                with db_lock:

                    db = get_db()
                    cur = db.cursor()

                    try:

                        cur.execute("""
                            UPDATE users
                            SET invite_code = %s
                            WHERE user_id = %s
                            AND (
                                invite_code IS NULL
                                OR invite_code = ''
                            )
                        """, (
                            code,
                            user_id
                        ))

                        db.commit()

                        if cur.rowcount > 0:
                            break

                    except Exception:

                        db.rollback()

                    finally:

                        cur.close()
                        db.close()

            except Exception:
                continue


def normalize_name(name):

    if not isinstance(name, str):
        return ""

    return " ".join(
        name.strip().split()
    )


def user_exists(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute(
                """
                SELECT 1
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            return cur.fetchone() is not None

        finally:

            cur.close()
            db.close()


def name_exists(
    name,
    exclude_user_id=None
):

    name = normalize_name(name)

    if not name:
        return False

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            if exclude_user_id is None:

                cur.execute("""
                    SELECT 1
                    FROM users
                    WHERE LOWER(BTRIM(name)) =
                          LOWER(BTRIM(%s))
                    LIMIT 1
                """, (name,))

            else:

                cur.execute("""
                    SELECT 1
                    FROM users
                    WHERE LOWER(BTRIM(name)) =
                          LOWER(BTRIM(%s))
                    AND user_id <> %s
                    LIMIT 1
                """, (
                    name,
                    exclude_user_id
                ))

            return cur.fetchone() is not None

        finally:

            cur.close()
            db.close()


def get_user_by_invite_code(invite_code):

    if not invite_code:
        return None

    invite_code = (
        invite_code
        .strip()
        .upper()
    )

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT user_id, name
                FROM users
                WHERE invite_code = %s
                LIMIT 1
            """, (invite_code,))

            return cur.fetchone()

        finally:

            cur.close()
            db.close()


def get_invite_code(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT invite_code
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            result = cur.fetchone()

            if result and result[0]:
                return result[0]

        finally:

            cur.close()
            db.close()

    return None


def save_new_user(
    user_id,
    name,
    invited_by=None
):

    name = normalize_name(name)

    invite_code = generate_unique_invite_code()

    try:

        with db_lock:

            db = get_db()
            cur = db.cursor()

            try:

                cur.execute("""
                    INSERT INTO users (
                        user_id,
                        name,
                        score,
                        invite_code,
                        invited_by,
                        referral_count
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        0
                    )
                """, (
                    user_id,
                    name,
                    0,
                    invite_code,
                    invited_by
                ))

                db.commit()

                return True

            except psycopg2.IntegrityError:

                db.rollback()

                return False

            finally:

                cur.close()
                db.close()

    except Exception as error:

        print(
            "❌ Save user error:",
            error
        )

        return False


def reward_referral(
    new_user_id,
    inviter_id
):

    # جلوگیری از دعوت خود
    if not inviter_id:
        return False

    if new_user_id == inviter_id:
        return False

    try:

        with db_lock:

            db = get_db()
            cur = db.cursor()

            try:

                # بررسی اینکه کاربر واقعاً دعوت‌کننده دارد
                cur.execute("""
                    SELECT invited_by
                    FROM users
                    WHERE user_id = %s
                    FOR UPDATE
                """, (new_user_id,))

                row = cur.fetchone()

                if not row:
                    db.rollback()
                    return False

                if row[0] != inviter_id:
                    db.rollback()
                    return False

                # بررسی وجود دعوت‌کننده
                cur.execute("""
                    SELECT user_id
                    FROM users
                    WHERE user_id = %s
                    FOR UPDATE
                """, (inviter_id,))

                inviter = cur.fetchone()

                if not inviter:
                    db.rollback()
                    return False

                # امتیاز کاربر جدید
                cur.execute("""
                    UPDATE users
                    SET score = score + %s
                    WHERE user_id = %s
                """, (
                    NEW_USER_REWARD,
                    new_user_id
                ))

                # امتیاز دعوت‌کننده
                cur.execute("""
                    UPDATE users
                    SET
                        score = score + %s,
                        referral_count =
                            referral_count + 1
                    WHERE user_id = %s
                """, (
                    REFERRER_REWARD,
                    inviter_id
                ))

                db.commit()

                return True

            except Exception as error:

                db.rollback()

                print(
                    "❌ Referral reward error:",
                    error
                )

                return False

            finally:

                cur.close()
                db.close()

    except Exception as error:

        print(
            "❌ Referral database error:",
            error
        )

        return False


def change_user_name(
    user_id,
    name
):

    name = normalize_name(name)

    try:

        with db_lock:

            db = get_db()
            cur = db.cursor()

            try:

                cur.execute("""
                    UPDATE users
                    SET name = %s
                    WHERE user_id = %s
                """, (
                    name,
                    user_id
                ))

                db.commit()

                return True

            except psycopg2.IntegrityError:

                db.rollback()

                return False

            finally:

                cur.close()
                db.close()

    except Exception as error:

        print(
            "❌ Change name error:",
            error
        )

        return False


def get_name(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT name
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            result = cur.fetchone()

            if result:
                return result[0]

            return "بازیکن"

        finally:

            cur.close()
            db.close()


def add_score(
    user_id,
    points
):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                UPDATE users
                SET score = score + %s
                WHERE user_id = %s
            """, (
                points,
                user_id
            ))

            db.commit()

        finally:

            cur.close()
            db.close()


def get_referral_info(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT
                    invite_code,
                    referral_count,
                    score
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            result = cur.fetchone()

            if not result:
                return None

            return {
                "invite_code": result[0],
                "referral_count": result[1] or 0,
                "score": result[2] or 0
            }

        finally:

            cur.close()
            db.close()


def get_leaderboard_text():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT name, score
                FROM users
                ORDER BY score DESC, name ASC
                LIMIT 10
            """)

            rows = cur.fetchall()

        finally:

            cur.close()
            db.close()

    if not rows:

        return (
            "🏆 هنوز کسی در جدول "
            "امتیازات نیست."
        )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    text = (
        "🏆 جدول برترین بازیکنان\n\n"
    )

    for index, row in enumerate(rows, 1):

        icon = (
            medals[index - 1]
            if index <= 3
            else f"{index}."
        )

        text += (
            f"{icon} {row[0]}\n"
            f"⭐ {row[1]} امتیاز\n\n"
        )

    return text


# =====================================================
# API بله
# =====================================================

def api_request(
    method,
    payload=None,
    timeout=30
):

    try:

        response = requests.post(
            f"{BASE_URL}/{method}",
            json=payload or {},
            timeout=timeout
        )

        data = response.json()

        if (
            response.status_code != 200
            or not data.get("ok")
        ):

            print(
                f"❌ API Error [{method}]:",
                data
            )

            return None

        return data

    except Exception as error:

        print(
            f"❌ API Request Error [{method}]:",
            error
        )

        return None


def send_message(
    chat_id,
    text,
    reply_markup=None
):

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup is not None:

        payload[
            "reply_markup"
        ] = reply_markup

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

        payload[
            "caption"
        ] = caption[:1024]

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

        payload[
            "caption"
        ] = caption[:1024]

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
# تشخیص محتوا
# =====================================================

def get_content_from_message(message):

    photos = message.get("photo")

    if photos:

        try:

            photo = photos[-1]

            file_id = photo.get("file_id")

            if file_id:

                return {
                    "type": "photo",
                    "file_id": file_id,
                    "caption": (
                        message.get(
                            "caption",
                            ""
                        )
                        or ""
                    ).strip()
                }

        except Exception:
            pass

    voice = message.get("voice")

    if voice:

        try:

            file_id = voice.get("file_id")

            if file_id:

                return {
                    "type": "voice",
                    "file_id": file_id,
                    "caption": (
                        message.get(
                            "caption",
                            ""
                        )
                        or ""
                    ).strip()
                }

        except Exception:
            pass

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

    content_type = content.get("type")

    if content_type == "text":

        text = content.get(
            "text",
            ""
        )

        if prefix:
            text = (
                f"{prefix}\n\n{text}"
            )

        send_message(
            chat_id,
            text
        )

        return

    caption = content.get(
        "caption",
        ""
    )

    if prefix:

        caption = (
            f"{prefix}\n\n{caption}"
            if caption
            else prefix
        )

    if content_type == "photo":

        send_photo(
            chat_id,
            content.get("file_id"),
            caption
        )

    elif content_type == "voice":

        send_voice(
            chat_id,
            content.get("file_id"),
            caption
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
                {"text": "👥 دعوت دوستان"},
                {"text": "🏆 جدول امتیازات"}
            ],
            [
                {"text": "✏️ تغییر نام"},
                {"text": "📖 راهنمای بازی"}
            ],
            [
                {"text": "📢 کانال اطلاع‌رسانی"},
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
            "آخرین بار کی گریه کردی و چرا؟",
            "بامزه‌ترین خاطره‌ات از مدرسه چیه؟",
            "بدترین غذایی که تا حالا خوردی چی بود؟",
            "اگر فقط یک چیز را تا آخر عمر می‌توانستی استفاده کنی، چی بود؟",
            "آیا تا حالا از کاری که کردی پشیمون شدی؟",
            "اگر بفهمی بهترین دوستت پشت سرت حرف زده، چیکار می‌کنی؟",
            "یک چیزی که در خودت واقعاً دوست داری چیه؟",
            "اگر یک روز نامرئی می‌شدی، اولین کاری که می‌کردی چی بود؟",
            "چیزی که باعث می‌شه سریع عصبانی بشی چیه؟",
            "آخرین بار کی از یک دوستت دلخور شدی و چرا؟",
            "بزرگ‌ترین ترست چیه؟",
            "اگر یک فرصت داشتی گذشته را عوض کنی، چه چیزی را انتخاب می‌کردی؟",
            "بزرگ‌ترین اشتباهی که در مورد یک دوست کردی چی بوده؟",
            "کدوم ویژگی اخلاقی خودت رو دوست داری تغییر بدی؟",
            "آیا تا حالا از موفقیت یکی از دوستات حسودی کردی؟",
            "اگر پول مهم نبود، الان مشغول چه کاری بودی؟",
            "بزرگ‌ترین ضعف اخلاقی خودت رو بگو.",
            "اگر می‌توانستی یک روز از زندگی یک نفر دیگر را تجربه کنی، کی را انتخاب می‌کردی؟",
            "بزرگ‌ترین فداکاری‌ای که تا حالا برای کسی کردی چی بوده؟",
            "آخرین آهنگی که گوش دادی چی بود؟",
            "یک عادت بد یا بامزه خودت را بگو.",
            "یک شهر نام ببر که دوست داری به آن سفر کنی.",
            "اگر یک ابرقدرت داشتی، چه قدرتی انتخاب می‌کردی؟",
            "بهترین بازی ویدیویی که انجام دادی چیست؟"
        ],

        "dare": [
            "با لهجه محلی، سه جمله درباره مدرسه‌ات بگو.",
            "یک داستان مرموز کوتاه تعریف کن.",
            "یک ایموجی بفرست که حالت الان را نشان بده و توضیح بده چرا.",
            "با آواز یا شعر بگو امروز چیکار کردی.",
            "از یک نفر در گروه یک تعریف واقعی و محترمانه بکن.",
            "یک جمله بگو که آخرش همه بخندن.",
            "یک جمله بگو که توش «مدرسه»، «فیل» و «برف» باشد.",
            "یک سؤال بپرس که جوابش بقیه را غافلگیر کند.",
            "یک اسم بامزه برای خودت انتخاب کن و دلیلش را بگو.",
            "یک لطیفه کوتاه و مناسب تعریف کن.",
            "با سه ایموجی یک داستان بساز.",
            "یک شخصیت خیالی بساز و سه ویژگی برایش بگو.",
            "یک اسم عجیب برای یک فیلم خیالی انتخاب کن.",
            "یک معمای کوتاه برای بقیه طراحی کن.",
            "یک جمله کاملاً عجیب ولی خنده‌دار بساز.",
            "یک پیام انگیزشی کوتاه برای اعضای گروه بنویس."
        ]
    },

    "fun": {

        "truth": [
            "کی از همه بیشتر دیر می‌رسد؟",
            "کی از همه بامزه‌تر است؟",
            "کی زودتر از همه عصبی می‌شود؟",
            "کی بهترین تایپیست است؟",
            "کی بیشتر در گروه ساکت است ولی در واقعیت پرحرف‌تر است؟",
            "اگر یک نفر را قهرمان گروه می‌کردی، کی بود؟",
            "اگر یک نفر در گروه شخصیت فیلم بود، چه نقشی می‌گرفت؟",
            "اگر یک نفر یک رنگ بود، چه رنگی می‌شد؟",
            "اگر یک نفر یک فصل بود، کدام فصل بود؟",
            "اگر یک نفر یک کتاب بود، اسم کتابش چی بود؟",
            "توی گوشی‌ات چند تا بازی داری و کدام را بیشتر بازی می‌کنی؟",
            "اگر مدیر مدرسه بودی چه قانونی می‌گذاشتی؟"
        ],

        "dare": [
            "یک نفر را انتخاب کن و یک ویژگی مثبت او را بگو.",
            "برای یکی از اعضای گروه یک لقب دوستانه و محترمانه بساز.",
            "یک تبلیغ بامزه برای یک مداد بنویس.",
            "یک داستان پنج‌کلمه‌ای بنویس.",
            "یک قانون عجیب برای یک مدرسه خیالی پیشنهاد بده.",
            "یک اسم بامزه برای یک فروشگاه خیالی بساز.",
            "یک داستان کوتاه و خنده‌دار بساز.",
            "یک تعریف صادقانه و محترمانه از یکی از اعضای گروه بکن.",
            "یک معمای کوتاه طراحی کن."
        ]
    },

    "minecraft": {

        "truth": [
            "تا حالا چند ساعت پشت سر هم ماینکرفت بازی کردی؟",
            "آخرین باری که در ماینکرفت شکست خوردی کی بود؟",
            "اگر می‌توانستی یک بلاک ماینکرفت را واقعی کنی، چی می‌شد؟",
            "اولین خانه‌ای که در ماینکرفت ساختی چه شکلی بود؟",
            "Survival را بیشتر دوست داری یا Creative؟",
            "بامزه‌ترین اتفاقی که در ماینکرفت برایت افتاده چی بوده؟",
            "به نظر تو سخت‌ترین دشمن ماینکرفت کدام است؟",
            "بهترین سازه‌ای که تا حالا ساختی چی بوده؟"
        ],

        "dare": [
            "در ۲۰ ثانیه توضیح بده چرا Creeper معروف است.",
            "یک اسم بامزه برای یک دنیای جدید ماینکرفت بساز.",
            "یک چالش ماینکرفت پیشنهاد بده که همه انجام بدهند.",
            "پنج ابزار ماینکرفت را نام ببر.",
            "یک دشمن جدید برای ماینکرفت اختراع کن.",
            "یک مأموریت بامزه برای بازیکنان ماینکرفت طراحی کن."
        ]
    },

    "fast": {

        "truth": [
            "[۱۰ ثانیه] اسم سه رنگ بگو.",
            "[۱۵ ثانیه] پنج بازی ویدیویی نام ببر.",
            "[۲۰ ثانیه] چهار استان ایران نام ببر.",
            "[۱۰ ثانیه] سه میوه قرمز نام ببر.",
            "[۱۵ ثانیه] پنج ابزار ماینکرفت نام ببر.",
            "[۱۰ ثانیه] سه حیوان نام ببر.",
            "[۱۵ ثانیه] پنج شخصیت کارتونی نام ببر.",
            "[۱۰ ثانیه] سه خوراکی شیرین نام ببر."
        ],

        "dare": [
            "[۱۰ ثانیه] یک جمله خنده‌دار بساز.",
            "[۱۵ ثانیه] پنج اسم برای یک ربات خیالی پیشنهاد بده.",
            "[۱۰ ثانیه] سه ایموجی بفرست که یک داستان بسازند.",
            "[۲۰ ثانیه] چهار بازی محبوب نام ببر.",
            "[۱۵ ثانیه] پنج میوه را بدون تکرار نام ببر."
        ]
    }
}


def get_random_prompt(mode):

    mode_data = PROMPTS.get(
        mode,
        PROMPTS["normal"]
    )

    all_prompts = []

    for question_type in [
        "truth",
        "dare"
    ]:

        for prompt in mode_data.get(
            question_type,
            []
        ):

            all_prompts.append({
                "type": question_type,
                "prompt": prompt
            })

    if not all_prompts:

        return {
            "type": "truth",
            "prompt": "یک سؤال مناسب پاسخ بده."
        }

    return random.choice(
        all_prompts
    )


def mode_name(mode):

    names = {
        "normal": "🟢 معمولی و دوستانه",
        "fun": "🔥 خفن و چالشی",
        "minecraft": "⛏️ ماینکرفت",
        "fast": "⚡ سریع جواب بده"
    }

    return names.get(
        mode,
        "🟢 معمولی"
    )


# =====================================================
# بازی تک‌نفره
# =====================================================

def start_single_game(chat_id):

    with state_lock:

        game = single_player.get(chat_id)

        if not game:
            return

        selected = get_random_prompt(
            game["mode"]
        )

        game["question_type"] = (
            selected["type"]
        )

        game["prompt"] = (
            selected["prompt"]
        )

        game["waiting_answer"] = True

        mode = game["mode"]

    title = (
        "🎯 حقیقت"
        if selected["type"] == "truth"
        else "🔥 جرئت"
    )

    instruction = (
        "به سؤال پاسخ بده."
        if selected["type"] == "truth"
        else "چالش را انجام بده و پاسخ یا نتیجه را ارسال کن."
    )

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎮 حالت: {mode_name(mode)}\n\n"
            f"{title}\n\n"
            f"📝 {selected['prompt']}\n\n"
            f"✍️ {instruction}\n\n"
            "📩 می‌توانی متن، عکس یا ویس ارسال کنی.\n\n"
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


def finish_single_game(chat_id):

    with state_lock:

        game = single_player.get(chat_id)

        if (
            not game
            or not game.get(
                "waiting_answer"
            )
        ):
            return

        game["waiting_answer"] = False

    send_message(
        chat_id,
        (
            "✅ پاسخ دریافت شد.\n\n"
            "🎮 در بازی تک‌نفره امتیازی داده نمی‌شود.\n\n"
            "برای ادامه سؤال جدید را انتخاب کن."
        ),
        get_single_next_keyboard()
    )


# =====================================================
# ابزارهای اتاق
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


def find_player_room(user_id):

    for code, room in rooms.items():

        if user_id in room.get(
            "players",
            []
        ):

            return code, room

    return None, None


def reset_round(room):

    room["questioner"] = None
    room["answerer"] = None
    room["question_type"] = None
    room["question"] = None
    room["answer"] = None
    room["votes"] = {}
    room["eligible_voters"] = []
    room["vote_finished"] = False


def create_room(
    chat_id,
    mode
):

    with room_lock:

        old_code, old_room = (
            find_player_room(chat_id)
        )

        if old_room:

            send_message(
                chat_id,
                "⚠️ شما در حال حاضر عضو یک اتاق هستید."
            )

            return

        code = generate_room_code()

        if not code:

            send_message(
                chat_id,
                "❌ ساخت اتاق انجام نشد."
            )

            return

        rooms[code] = {
            "host": chat_id,
            "players": [chat_id],
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
        chat_id,
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


def list_rooms(chat_id):

    with room_lock:

        available = [
            (code, room)
            for code, room in rooms.items()
            if room.get("phase") == "waiting"
        ]

    if not available:

        send_message(
            chat_id,
            "📭 فعلاً اتاقی برای پیوستن وجود ندارد."
        )

        return

    keyboard = []

    for code, room in available:

        keyboard.append([
            {
                "text": (
                    f"🚪 اتاق {code} | "
                    f"{len(room['players'])} نفر"
                ),
                "callback_data": (
                    f"join_{code}"
                )
            }
        ])

    send_message(
        chat_id,
        "🚪 یکی از اتاق‌ها را انتخاب کن:",
        {
            "inline_keyboard": keyboard
        }
    )


def leave_room(chat_id):

    players = []

    with room_lock:

        code, room = find_player_room(chat_id)

        if not room:

            found = False

        else:

            found = True

            if chat_id in room["players"]:

                room["players"].remove(
                    chat_id
                )

            players = list(
                room["players"]
            )

            if (
                room["host"] == chat_id
                and players
            ):

                room["host"] = players[0]

            if len(players) < 2:

                room["phase"] = "waiting"

                reset_round(room)

            if not players:

                del rooms[code]

    if not found:

        send_message(
            chat_id,
            "⚠️ شما داخل هیچ اتاقی نیستید."
        )

        return

    send_message(
        chat_id,
        "🚪 از اتاق خارج شدی.",
        get_main_menu()
    )

    for player in players:

        send_message(
            player,
            (
                f"👋 {get_name(chat_id)} "
                "از اتاق خارج شد."
            )
        )


# =====================================================
# بازی آنلاین
# =====================================================

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

        if room["phase"] not in [
            "waiting",
            "between_rounds"
        ]:
            return

        reset_round(room)

        room["round"] += 1

        questioner, answerer = (
            random.sample(
                players,
                2
            )
        )

        room["questioner"] = questioner
        room["answerer"] = answerer
        room["phase"] = "choosing_type"

        round_number = room["round"]

    base_text = (
        f"🎮 دور {round_number}\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}"
    )

    for player in players:

        if player == answerer:

            send_message(
                player,
                (
                    base_text +
                    "\n\n🎯 انتخاب کن:"
                ),
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
                player,
                (
                    base_text +
                    "\n\n⏳ منتظر انتخاب پاسخ‌دهنده باش."
                )
            )


def publish_question(code):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if (
            room["phase"]
            != "waiting_question"
        ):
            return

        question = room.get(
            "question"
        )

        if not question:
            return

        room["phase"] = (
            "waiting_answer"
        )

        players = list(
            room["players"]
        )

        questioner = room[
            "questioner"
        ]

        answerer = room[
            "answerer"
        ]

        question_type = room[
            "question_type"
        ]

    choice_text = (
        "🎯 حقیقت"
        if question_type == "truth"
        else "🔥 جرئت"
    )

    prefix = (
        f"📢 {choice_text}\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}\n\n"
        "❓ سؤال یا چالش:"
    )

    for player in players:

        send_content(
            player,
            question,
            prefix
        )

        if player == answerer:

            send_message(
                player,
                (
                    "📩 حالا پاسخ خودت را ارسال کن.\n\n"
                    "می‌توانی متن، عکس یا ویس بفرستی."
                )
            )

        else:

            send_message(
                player,
                "⏳ منتظر پاسخ بازیکن باش."
            )


def publish_answer_and_start_vote(code):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if (
            room["phase"]
            != "waiting_answer"
        ):
            return

        answer = room.get("answer")

        if not answer:
            return

        answerer = room["answerer"]

        players = list(
            room["players"]
        )

        room["eligible_voters"] = [
            player
            for player in players
            if player != answerer
        ]

        room["votes"] = {}
        room["vote_finished"] = False
        room["phase"] = "voting"

        eligible = list(
            room["eligible_voters"]
        )

    prefix = (
        "💬 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}\n\n"
        "📨 پاسخ:"
    )

    vote_keyboard = {
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

    for player in players:

        send_content(
            player,
            answer,
            prefix
        )

        if player == answerer:

            send_message(
                player,
                "⏳ رأی‌گیری شروع شد."
            )

        elif player in eligible:

            send_message(
                player,
                (
                    "🗳️ آیا پاسخ مورد قبول است؟\n\n"
                    f"⏱️ {VOTE_TIMEOUT} ثانیه فرصت داری."
                ),
                vote_keyboard
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
        force=True
    )


def register_vote(
    code,
    user_id,
    vote
):

    should_finish = False

    with room_lock:

        room = rooms.get(code)

        if not room:

            status = "no_room"

        elif room["phase"] != "voting":

            status = "not_voting"

        elif room["vote_finished"]:

            status = "finished"

        elif user_id not in (
            room["eligible_voters"]
        ):

            status = "not_allowed"

        elif user_id in room["votes"]:

            status = "already"

        else:

            room["votes"][user_id] = vote

            status = "success"

            if (
                len(room["votes"])
                >= len(
                    room["eligible_voters"]
                )
            ):

                should_finish = True

    messages = {
        "no_room": "❌ این اتاق وجود ندارد.",
        "not_voting": "⚠️ رأی‌گیری فعال نیست.",
        "finished": "⚠️ رأی‌گیری تمام شده است.",
        "not_allowed": "⚠️ شما اجازه رأی دادن ندارید.",
        "already": "⚠️ شما قبلاً رأی داده‌اید.",
        "success": "✅ رأی شما ثبت شد."
    }

    send_message(
        user_id,
        messages.get(
            status,
            "⚠️ خطا"
        )
    )

    if should_finish:

        finish_online_voting(
            code,
            force=False
        )


def finish_online_voting(
    code,
    force=False
):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if room["phase"] != "voting":
            return

        if room["vote_finished"]:
            return

        if not force:

            if (
                len(room["votes"])
                < len(
                    room["eligible_voters"]
                )
            ):
                return

        room["vote_finished"] = True

        room["phase"] = (
            "between_rounds"
        )

        votes = dict(room["votes"])

        players = list(
            room["players"]
        )

        answerer = room["answerer"]

    yes_votes = sum(
        1
        for vote in votes.values()
        if vote == "yes"
    )

    no_votes = sum(
        1
        for vote in votes.values()
        if vote == "no"
    )

    if yes_votes == 0 and no_votes == 0:

        result = (
            "⏰ زمان رأی‌گیری تمام شد.\n"
            "هیچ رأیی ثبت نشد."
        )

    elif yes_votes > no_votes:

        add_score(
            answerer,
            10
        )

        result = (
            "🎉 پاسخ توسط اکثریت تأیید شد!\n"
            "⭐ ۱۰ امتیاز به پاسخ‌دهنده اضافه شد."
        )

    elif no_votes > yes_votes:

        result = (
            "❌ پاسخ توسط اکثریت رد شد.\n"
            "امتیازی داده نشد."
        )

    else:

        result = (
            "⚖️ رأی‌ها مساوی بودند.\n"
            "امتیازی داده نشد."
        )

    result_text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی آماده می‌شود..."
    )

    for player in players:

        send_message(
            player,
            result_text
        )

    threading.Thread(
        target=start_next_round,
        args=(code,),
        daemon=True
    ).start()


def start_next_round(code):

    time.sleep(3)

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if len(
            room["players"]
        ) < 2:

            room["phase"] = "waiting"

            reset_round(room)

            return

    start_online_round(code)


# =====================================================
# سیستم دعوت دوستان
# =====================================================

def show_invite_info(chat_id):

    info = get_referral_info(chat_id)

    if not info:

        send_message(
            chat_id,
            "❌ اطلاعات دعوت پیدا نشد."
        )

        return

    invite_code = info["invite_code"]
    referral_count = info["referral_count"]
    score = info["score"]

    if BOT_USERNAME:

        invite_link = (
            f"https://bale.ai/{BOT_USERNAME}"
            f"?start={invite_code}"
        )

        invite_text = (
            "👥 دعوت دوستان و زیرمجموعه‌گیری\n\n"
            f"🔑 کد دعوت شما:\n"
            f"`{invite_code}`\n\n"
            f"🔗 لینک دعوت شما:\n"
            f"{invite_link}\n\n"
            f"👤 تعداد زیرمجموعه‌ها: "
            f"{referral_count}\n"
            f"⭐ امتیاز فعلی شما: "
            f"{score}\n\n"
            "🎁 قوانین دعوت:\n"
            f"• با هر دعوت موفق، شما "
            f"{REFERRER_REWARD} امتیاز می‌گیرید.\n"
            f"• کاربر جدید "
            f"{NEW_USER_REWARD} امتیاز خوش‌آمدگویی می‌گیرد.\n\n"
            "📤 لینک یا کد دعوتت را برای دوستانت ارسال کن."
        )

    else:

        invite_text = (
            "👥 دعوت دوستان و زیرمجموعه‌گیری\n\n"
            f"🔑 کد دعوت شما:\n"
            f"{invite_code}\n\n"
            f"👤 تعداد زیرمجموعه‌ها: "
            f"{referral_count}\n"
            f"⭐ امتیاز فعلی شما: "
            f"{score}\n\n"
            "🎁 قوانین دعوت:\n"
            f"• با هر دعوت موفق، شما "
            f"{REFERRER_REWARD} امتیاز می‌گیرید.\n"
            f"• کاربر جدید "
            f"{NEW_USER_REWARD} امتیاز خوش‌آمدگویی می‌گیرد.\n\n"
            "📤 برای ساخت لینک مستقیم، "
            "BOT_USERNAME را در Environment Variables تنظیم کن."
        )

    send_message(
        chat_id,
        invite_text,
        get_main_menu()
    )


# =====================================================
# دریافت پیام
# =====================================================

def handle_message(message):

    chat_id = (
        message.get(
            "chat",
            {}
        ).get("id")
    )

    if not chat_id:
        return

    content = get_content_from_message(
        message
    )

    text = ""

    if (
        content
        and content["type"] == "text"
    ):

        text = content["text"]

    # =================================================
    # پردازش /start و کد دعوت
    # =================================================

    start_invite_code = None

    if text.startswith("/start"):

        parts = text.split(
            maxsplit=1
        )

        if len(parts) > 1:

            start_invite_code = (
                parts[1]
                .strip()
                .upper()
            )

    # =================================================
    # ثبت‌نام کاربر جدید
    # =================================================

    if not user_exists(chat_id):

        with state_lock:

            state = user_states.get(chat_id)

        if text.startswith("/start"):

            inviter_id = None

            if start_invite_code:

                inviter = get_user_by_invite_code(
                    start_invite_code
                )

                if inviter:

                    possible_inviter_id = inviter[0]

                    # جلوگیری از دعوت خود
                    if (
                        possible_inviter_id
                        != chat_id
                    ):

                        inviter_id = (
                            possible_inviter_id
                        )

            with state_lock:

                user_states[chat_id] = {
                    "state": "register_name",
                    "inviter_id": inviter_id
                }

            if inviter_id:

                inviter_name = get_name(
                    inviter_id
                )

                send_message(
                    chat_id,
                    (
                        "🎉 شما با کد دعوت وارد شدید!\n\n"
                        f"👤 دعوت‌کننده: "
                        f"{inviter_name}\n\n"
                        "حالا یک نام مستعار انتخاب کن "
                        "و به صورت متن ارسال کن.\n\n"
                        "⚠️ نام تکراری پذیرفته نمی‌شود."
                    )
                )

            else:

                send_message(
                    chat_id,
                    (
                        "👋 سلام!\n\n"
                        "برای شروع یک نام مستعار انتخاب کن "
                        "و به صورت متن ارسال کن.\n\n"
                        "⚠️ نام تکراری پذیرفته نمی‌شود."
                    )
                )

            return

        if (
            not state
            or state.get("state")
            != "register_name"
        ):

            send_message(
                chat_id,
                "برای شروع ابتدا /start را ارسال کن."
            )

            return

        if not text:

            send_message(
                chat_id,
                "⚠️ لطفاً نام را فقط به صورت متن ارسال کن."
            )

            return

        new_name = normalize_name(
            text[:40]
        )

        if len(new_name) < 2:

            send_message(
                chat_id,
                "⚠️ نام باید حداقل ۲ کاراکتر باشد."
            )

            return

        if name_exists(new_name):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً انتخاب شده است.\n\n"
                    "لطفاً نام دیگری انتخاب کن."
                )
            )

            return

        inviter_id = state.get(
            "inviter_id"
        )

        if not save_new_user(
            chat_id,
            new_name,
            inviter_id
        ):

            send_message(
                chat_id,
                (
                    "❌ ثبت‌نام انجام نشد یا "
                    "این نام قبلاً انتخاب شده است."
                )
            )

            return

        referral_success = False

        if inviter_id:

            referral_success = reward_referral(
                chat_id,
                inviter_id
            )

        with state_lock:

            user_states.pop(
                chat_id,
                None
            )

        welcome_text = (
            f"🎉 خوش آمدی {new_name}!\n\n"
            "حساب کاربری تو ساخته شد."
        )

        if referral_success:

            welcome_text += (
                "\n\n🎁 به دلیل ورود با کد دعوت، "
                f"{NEW_USER_REWARD} امتیاز "
                "به شما اضافه شد!"
            )

            # اطلاع به دعوت‌کننده
            send_message(
                inviter_id,
                (
                    "🎉 یک نفر با کد دعوت شما "
                    "عضو ربات شد!\n\n"
                    f"👤 زیرمجموعه جدید: "
                    f"{new_name}\n"
                    f"⭐ {REFERRER_REWARD} امتیاز "
                    "به شما اضافه شد."
                )
            )

        send_message(
            chat_id,
            welcome_text,
            get_main_menu()
        )

        return

    # =================================================
    # /start برای کاربران ثبت‌نام‌شده
    # =================================================

    if text.startswith("/start"):

        send_message(
            chat_id,
            (
                f"👋 سلام {get_name(chat_id)}!\n\n"
                "به بازی حقیقت یا جرئت خوش آمدی."
            ),
            get_main_menu()
        )

        return

    # =================================================
    # تغییر نام
    # =================================================

    with state_lock:

        state_data = user_states.get(
            chat_id
        )

    if (
        isinstance(state_data, dict)
        and state_data.get("state")
        == "change_name"
    ):

        if not text:

            send_message(
                chat_id,
                "⚠️ لطفاً نام را به صورت متن ارسال کن."
            )

            return

        new_name = normalize_name(
            text[:40]
        )

        if len(new_name) < 2:

            send_message(
                chat_id,
                "⚠️ نام باید حداقل ۲ کاراکتر باشد."
            )

            return

        if name_exists(
            new_name,
            exclude_user_id=chat_id
        ):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط "
                    "کاربر دیگری انتخاب شده است."
                )
            )

            return

        if not change_user_name(
            chat_id,
            new_name
        ):

            send_message(
                chat_id,
                "❌ تغییر نام انجام نشد."
            )

            return

        with state_lock:

            user_states.pop(
                chat_id,
                None
            )

        send_message(
            chat_id,
            f"✅ نام جدید شما: {new_name}",
            get_main_menu()
        )

        return

    # =================================================
    # پاسخ بازی تک‌نفره
    # =================================================

    with state_lock:

        game = single_player.get(
            chat_id
        )

        waiting_single = bool(
            game
            and game.get(
                "waiting_answer"
            )
        )

    if waiting_single:

        if text == "🏠 منوی اصلی":

            with state_lock:

                single_player.pop(
                    chat_id,
                    None
                )

            send_message(
                chat_id,
                "🏠 منوی اصلی",
                get_main_menu()
            )

            return

        if content:

            finish_single_game(chat_id)

            return

    # =================================================
    # دریافت سؤال آنلاین
    # =================================================

    with room_lock:

        code, room = find_player_room(
            chat_id
        )

        if (
            room
            and room["phase"]
            == "waiting_question"
            and room["questioner"]
            == chat_id
        ):

            question_code = code

        else:

            question_code = None

    if question_code:

        if not content:

            send_message(
                chat_id,
                (
                    "⚠️ سؤال را به صورت متن، "
                    "عکس یا ویس ارسال کن."
                )
            )

            return

        if (
            text
            and text.startswith(
                (
                    "🏠",
                    "🚪",
                    "🎮",
                    "🤖"
                )
            )
        ):

            send_message(
                chat_id,
                (
                    "⚠️ اکنون باید سؤال یا "
                    "چالش ارسال کنی."
                )
            )

            return

        with room_lock:

            room = rooms.get(
                question_code
            )

            if (
                room
                and room["phase"]
                == "waiting_question"
                and room["questioner"]
                == chat_id
            ):

                room["question"] = content

            else:

                return

        publish_question(
            question_code
        )

        return

    # =================================================
    # دریافت جواب آنلاین
    # =================================================

    with room_lock:

        code, room = find_player_room(
            chat_id
        )

        if (
            room
            and room["phase"]
            == "waiting_answer"
            and room["answerer"]
            == chat_id
        ):

            answer_code = code

        else:

            answer_code = None

    if answer_code:

        if not content:

            send_message(
                chat_id,
                (
                    "⚠️ جواب را به صورت متن، "
                    "عکس یا ویس ارسال کن."
                )
            )

            return

        if (
            text
            and text.startswith(
                (
                    "🏠",
                    "🚪",
                    "🎮",
                    "🤖"
                )
            )
        ):

            send_message(
                chat_id,
                (
                    "⚠️ اکنون باید پاسخ سؤال "
                    "یا چالش را ارسال کنی."
                )
            )

            return

        with room_lock:

            room = rooms.get(
                answer_code
            )

            if (
                room
                and room["phase"]
                == "waiting_answer"
                and room["answerer"]
                == chat_id
            ):

                room["answer"] = content

            else:

                return

        publish_answer_and_start_vote(
            answer_code
        )

        return

    # =================================================
    # سؤال جدید تک‌نفره
    # =================================================

    if text == "⏭️ سؤال جدید":

        with state_lock:

            exists = (
                chat_id
                in single_player
            )

        if exists:

            start_single_game(
                chat_id
            )

        return

    # =================================================
    # منوی اصلی
    # =================================================

    if text == "🏠 منوی اصلی":

        with state_lock:

            user_states.pop(
                chat_id,
                None
            )

            single_player.pop(
                chat_id,
                None
            )

        send_message(
            chat_id,
            "🏠 منوی اصلی",
            get_main_menu()
        )

        return

    # =================================================
    # بازی تک‌نفره
    # =================================================

    if text == "🤖 بازی تک‌نفره":

        with state_lock:

            user_states[chat_id] = {
                "state": (
                    "choosing_single_mode"
                )
            }

        send_message(
            chat_id,
            "🎮 حالت بازی را انتخاب کن:",
            get_modes_keyboard()
        )

        return

    # =================================================
    # دعوت دوستان
    # =================================================

    if text == "👥 دعوت دوستان":

        show_invite_info(chat_id)

        return

    # =================================================
    # اتاق‌های آنلاین
    # =================================================

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 بخش بازی آنلاین",
            get_rooms_menu()
        )

        return

    # =================================================
    # ساخت اتاق
    # =================================================

    if text == "🛠️ ساخت اتاق جدید":

        with room_lock:

            code, room = find_player_room(
                chat_id
            )

        if room:

            send_message(
                chat_id,
                f"⚠️ شما عضو اتاق {code} هستید."
            )

            return

        with state_lock:

            user_states[chat_id] = {
                "state": (
                    "choosing_room_mode"
                )
            }

        send_message(
            chat_id,
            "🎮 حالت اتاق را انتخاب کن:",
            get_modes_keyboard()
        )

        return

    # =================================================
    # پیوستن به اتاق
    # =================================================

    if text == "🚪 پیوستن به اتاق":

        with room_lock:

            code, room = find_player_room(
                chat_id
            )

        if room:

            send_message(
                chat_id,
                (
                    f"⚠️ شما عضو اتاق {code} هستید.\n"
                    "ابتدا از اتاق خارج شو."
                )
            )

            return

        list_rooms(chat_id)

        return

    # =================================================
    # خروج از اتاق
    # =================================================

    if text == "🚪 خروج از اتاق":

        leave_room(chat_id)

        return

    # =================================================
    # جدول امتیازات
    # =================================================

    if text == "🏆 جدول امتیازات":

        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu()
        )

        return

    # =================================================
    # تغییر نام
    # =================================================

    if text == "✏️ تغییر نام":

        with state_lock:

            user_states[chat_id] = {
                "state": "change_name"
            }

        send_message(
            chat_id,
            (
                "✏️ نام جدید خود را به صورت متن ارسال کن.\n\n"
                "⚠️ نام تکراری پذیرفته نمی‌شود."
            )
        )

        return

    # =================================================
    # کانال
    # =================================================

    if text == "📢 کانال اطلاع‌رسانی":

        send_message(
            chat_id,
            (
                "📢 کانال اطلاع‌رسانی:\n"
                "@ettelae_resani"
            )
        )

        return

    # =================================================
    # پشتیبانی
    # =================================================

    if text == "💬 پشتیبانی":

        send_message(
            chat_id,
            (
                "💬 پشتیبانی:\n"
                "@kia_karfarma"
            )
        )

        return

    # =================================================
    # راهنما
    # =================================================

    if text == "📖 راهنمای بازی":

        send_message(
            chat_id,
            (
                "📖 راهنمای بازی\n\n"

                "👥 سیستم دعوت:\n"
                f"با هر دعوت موفق "
                f"{REFERRER_REWARD} امتیاز می‌گیری.\n"
                f"کاربر جدید هم "
                f"{NEW_USER_REWARD} امتیاز "
                "خوش‌آمدگویی دریافت می‌کند.\n\n"

                "🤖 بازی تک‌نفره:\n"
                "ربات به صورت شانسی سؤال یا چالش انتخاب می‌کند.\n"
                "امتیازدهی ندارد.\n\n"

                "🎮 بازی آنلاین:\n"
                "یک اتاق بساز یا وارد اتاق دیگران شو.\n\n"

                "🎯 یک نفر حقیقت یا جرئت را انتخاب می‌کند.\n"
                "✍️ پرسش‌کننده سؤال یا چالش را می‌فرستد.\n"
                "💬 پاسخ‌دهنده جواب می‌دهد.\n\n"

                "📩 هر دو نفر می‌توانند:\n"
                "📝 متن\n"
                "📷 عکس\n"
                "🎤 ویس\n"
                "ارسال کنند.\n\n"

                "🗳️ سایر بازیکنان یک بار رأی می‌دهند.\n"
                "⭐ در صورت تأیید اکثریت، "
                "۱۰ امتیاز داده می‌شود."
            ),
            get_main_menu()
        )

        return

    if text:

        send_message(
            chat_id,
            "⚠️ لطفاً از دکمه‌های منو استفاده کن.",
            get_main_menu()
        )


# =====================================================
# Callback ها
# =====================================================

def handle_callback(query):

    callback_id = query.get("id")

    data = query.get(
        "data",
        ""
    )

    sender = query.get(
        "from",
        {}
    )

    chat_id = sender.get("id")

    if not chat_id:

        chat_id = (
            query.get(
                "message",
                {}
            )
            .get(
                "chat",
                {}
            )
            .get("id")
        )

    if callback_id:

        answer_callback(
            callback_id
        )

    if not chat_id or not data:
        return

    # =================================================
    # بازگشت
    # =================================================

    if data == "back_menu":

        with state_lock:

            user_states.pop(
                chat_id,
                None
            )

        send_message(
            chat_id,
            "🏠 منوی اصلی",
            get_main_menu()
        )

        return

    # =================================================
    # انتخاب حالت
    # =================================================

    if data.startswith("mode_"):

        mode = data.replace(
            "mode_",
            "",
            1
        )

        if mode not in PROMPTS:
            return

        with state_lock:

            state_data = user_states.get(
                chat_id
            )

        state = None

        if isinstance(state_data, dict):

            state = state_data.get("state")

        if state == "choosing_single_mode":

            with state_lock:

                user_states.pop(
                    chat_id,
                    None
                )

                single_player[chat_id] = {
                    "mode": mode,
                    "waiting_answer": False
                }

            start_single_game(
                chat_id
            )

            return

        if state == "choosing_room_mode":

            with state_lock:

                user_states.pop(
                    chat_id,
                    None
                )

            create_room(
                chat_id,
                mode
            )

            return

    # =================================================
    # پیوستن به اتاق
    # =================================================

    if data.startswith("join_"):

        code = data.replace(
            "join_",
            "",
            1
        )

        players = []

        with room_lock:

            room = rooms.get(code)

            if not room:

                status = "not_found"

            elif (
                room["phase"]
                != "waiting"
            ):

                status = "started"

            elif len(
                room["players"]
            ) >= MAX_ROOM_PLAYERS:

                status = "full"

            else:

                old_code, old_room = (
                    find_player_room(chat_id)
                )

                if (
                    old_room
                    and old_code != code
                ):

                    status = "other_room"

                else:

                    status = "success"

                    if (
                        chat_id
                        not in room["players"]
                    ):

                        room["players"].append(
                            chat_id
                        )

                    players = list(
                        room["players"]
                    )

        if status == "not_found":

            send_message(
                chat_id,
                "❌ این اتاق وجود ندارد."
            )

            return

        if status == "started":

            send_message(
                chat_id,
                "❌ بازی این اتاق شروع شده است."
            )

            return

        if status == "full":

            send_message(
                chat_id,
                "❌ ظرفیت اتاق تکمیل شده است."
            )

            return

        if status == "other_room":

            send_message(
                chat_id,
                "⚠️ ابتدا از اتاق فعلی خارج شو."
            )

            return

        send_message(
            chat_id,
            f"✅ وارد اتاق {code} شدی.",
            get_rooms_menu()
        )

        for player in players:

            if player != chat_id:

                send_message(
                    player,
                    (
                        f"👤 {get_name(chat_id)} "
                        "به اتاق پیوست."
                    )
                )

        return

    # =================================================
    # شروع بازی
    # =================================================

    if data.startswith("start_"):

        code = data.replace(
            "start_",
            "",
            1
        )

        with room_lock:

            room = rooms.get(code)

            if not room:

                status = "not_found"

            elif room["host"] != chat_id:

                status = "not_host"

            elif len(
                room["players"]
            ) < 2:

                status = "not_enough"

            elif (
                room["phase"]
                != "waiting"
            ):

                status = "started"

            else:

                status = "success"

        messages = {
            "not_found": "❌ اتاق وجود ندارد.",
            "not_host": (
                "⚠️ فقط میزبان می‌تواند بازی را شروع کند."
            ),
            "not_enough": (
                "⚠️ حداقل ۲ بازیکن لازم است."
            ),
            "started": (
                "⚠️ بازی قبلاً شروع شده است."
            )
        }

        if status != "success":

            send_message(
                chat_id,
                messages[status]
            )

            return

        start_online_round(code)

        return

    # =================================================
    # حذف اتاق
    # =================================================

    if data.startswith("delete_"):

        code = data.replace(
            "delete_",
            "",
            1
        )

        players = []

        with room_lock:

            room = rooms.get(code)

            if not room:

                status = "not_found"

            elif room["host"] != chat_id:

                status = "not_host"

            else:

                status = "success"

                players = list(
                    room["players"]
                )

                del rooms[code]

        if status == "not_found":

            send_message(
                chat_id,
                "❌ اتاق وجود ندارد."
            )

            return

        if status == "not_host":

            send_message(
                chat_id,
                (
                    "⚠️ فقط میزبان می‌تواند "
                    "اتاق را حذف کند."
                )
            )

            return

        for player in players:

            send_message(
                player,
                "❌ اتاق توسط میزبان بسته شد.",
                get_main_menu()
            )

        return

    # =================================================
    # حقیقت یا جرئت
    # =================================================

    if (
        data.startswith("truth_")
        or data.startswith("dare_")
    ):

        choice, code = data.split(
            "_",
            1
        )

        with room_lock:

            room = rooms.get(code)

            if not room:

                status = "not_found"

            elif (
                room["phase"]
                != "choosing_type"
            ):

                status = "wrong_phase"

            elif (
                room["answerer"]
                != chat_id
            ):

                status = "not_answerer"

            else:

                status = "success"

                room["question_type"] = choice

                room["phase"] = (
                    "waiting_question"
                )

                questioner = room[
                    "questioner"
                ]

                players = list(
                    room["players"]
                )

        if status == "not_found":

            send_message(
                chat_id,
                "❌ اتاق وجود ندارد."
            )

            return

        if status == "wrong_phase":

            send_message(
                chat_id,
                (
                    "⚠️ این انتخاب قبلاً "
                    "انجام شده است."
                )
            )

            return

        if status == "not_answerer":

            send_message(
                chat_id,
                (
                    "⚠️ فقط پاسخ‌دهنده "
                    "می‌تواند انتخاب کند."
                )
            )

            return

        choice_text = (
            "🎯 حقیقت"
            if choice == "truth"
            else "🔥 جرئت"
        )

        for player in players:

            if player == questioner:

                send_message(
                    player,
                    (
                        f"✅ انتخاب پاسخ‌دهنده: "
                        f"{choice_text}\n\n"
                        "✍️ حالا سؤال یا چالش خودت را ارسال کن.\n\n"
                        "می‌توانی 📝 متن، "
                        "📷 عکس یا 🎤 ویس بفرستی."
                    )
                )

            else:

                send_message(
                    player,
                    (
                        f"✅ انتخاب شد: "
                        f"{choice_text}\n\n"
                        "⏳ منتظر ارسال سؤال "
                        "یا چالش باش."
                    )
                )

        return

    # =================================================
    # رأی مثبت
    # =================================================

    if data.startswith("yes_"):

        code = data.replace(
            "yes_",
            "",
            1
        )

        register_vote(
            code,
            chat_id,
            "yes"
        )

        return

    # =================================================
    # رأی منفی
    # =================================================

    if data.startswith("no_"):

        code = data.replace(
            "no_",
            "",
            1
        )

        register_vote(
            code,
            chat_id,
            "no"
        )

        return


# =====================================================
# Update Handler
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

    except Exception as error:

        print(
            "❌ Update Error:",
            error
        )


# =====================================================
# Polling
# =====================================================

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

            response = requests.get(
                f"{BASE_URL}/getUpdates",
                params=params,
                timeout=40
            )

            data = response.json()

            if not data.get("ok"):

                print(
                    "❌ getUpdates Error:",
                    data
                )

                time.sleep(3)

                continue

            updates = data.get(
                "result",
                []
            )

            for update in updates:

                update_id = update.get(
                    "update_id"
                )

                if update_id is not None:

                    offset = update_id + 1

                handle_update(update)

        except requests.exceptions.Timeout:

            continue

        except Exception as error:

            print(
                "❌ Polling Error:",
                error
            )

            time.sleep(5)


# =====================================================
# اجرای ربات
# =====================================================

if __name__ == "__main__":

    print("🚀 Starting Bale Bot...")

    init_database()

    polling_thread = threading.Thread(
        target=run_polling,
        daemon=True
    )

    polling_thread.start()

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )
