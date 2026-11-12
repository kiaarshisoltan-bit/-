import os
import random
import threading
import time
from datetime import date

import requests
import psycopg2
from flask import Flask, jsonify


# =====================================================
# تنظیمات
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))

ADMIN_ID = 1708788049

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL تنظیم نشده است.")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

app = Flask(__name__)

db_lock = threading.RLock()
game_lock = threading.RLock()


# =====================================================
# وضعیت‌های موقت
# =====================================================

user_states = {}
single_player = {}
rooms = {}


# =====================================================
# وب سرور Render
# =====================================================

@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running! 🤖"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "database": "postgresql"
    })


# =====================================================
# دیتابیس
# =====================================================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_database():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                score INTEGER NOT NULL DEFAULT 0,
                level INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS daily_missions (
                user_id BIGINT PRIMARY KEY,
                mission_date DATE NOT NULL,
                completed BOOLEAN NOT NULL DEFAULT FALSE
            )
        """)

        db.commit()

        cur.close()
        db.close()

    print("✅ PostgreSQL database initialized")


# =====================================================
# اطلاعات کاربران
# =====================================================

def user_exists(user_id):

    with db_lock:
        db = get_db()
        cur = db.cursor()

        cur.execute(
            "SELECT 1 FROM users WHERE user_id = %s",
            (user_id,)
        )

        result = cur.fetchone()

        cur.close()
        db.close()

    return result is not None


def name_exists(name, exclude_user_id=None):

    name = name.strip()

    with db_lock:
        db = get_db()
        cur = db.cursor()

        if exclude_user_id is None:

            cur.execute(
                "SELECT 1 FROM users WHERE LOWER(name) = LOWER(%s)",
                (name,)
            )

        else:

            cur.execute("""
                SELECT 1
                FROM users
                WHERE LOWER(name) = LOWER(%s)
                AND user_id != %s
            """, (name, exclude_user_id))

        result = cur.fetchone()

        cur.close()
        db.close()

    return result is not None


def save_user(user_id, name):

    name = name.strip()[:40]

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            INSERT INTO users (user_id, name, score, level)
            VALUES (%s, %s, 0, 1)

            ON CONFLICT (user_id)
            DO UPDATE SET name = EXCLUDED.name
        """, (user_id, name))

        db.commit()

        cur.close()
        db.close()


def get_user_data(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT name, score, level, created_at
            FROM users
            WHERE user_id = %s
        """, (user_id,))

        result = cur.fetchone()

        cur.close()
        db.close()

    return result


def get_name(user_id):

    data = get_user_data(user_id)

    if data:
        return data[0]

    return "بازیکن"


def get_score(user_id):

    data = get_user_data(user_id)

    if data:
        return data[1]

    return 0


def calculate_level(score):
    return max(1, (score // 100) + 1)


def add_score(user_id, points):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            UPDATE users
            SET score = score + %s
            WHERE user_id = %s
        """, (points, user_id))

        db.commit()

        cur.execute("""
            SELECT score
            FROM users
            WHERE user_id = %s
        """, (user_id,))

        result = cur.fetchone()
        score = result[0] if result else 0
        level = calculate_level(score)

        cur.execute("""
            UPDATE users
            SET level = %s
            WHERE user_id = %s
        """, (level, user_id))

        db.commit()

        cur.close()
        db.close()

    return level


def get_user_rank(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT COUNT(*) + 1
            FROM users
            WHERE score > (
                SELECT score
                FROM users
                WHERE user_id = %s
            )
        """, (user_id,))

        result = cur.fetchone()

        cur.close()
        db.close()

    return result[0] if result else 0


def get_total_users():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("SELECT COUNT(*) FROM users")

        result = cur.fetchone()

        cur.close()
        db.close()

    return result[0]


def get_leaderboard_text():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT name, score, level
            FROM users
            ORDER BY score DESC, name ASC
            LIMIT 10
        """)

        rows = cur.fetchall()

        cur.close()
        db.close()

    if not rows:
        return "🏆 هنوز امتیازی ثبت نشده است."

    text = "🏆 جدول برترین بازیکنان\n\n"

    for i, row in enumerate(rows, 1):

        text += (
            f"{i}. {row[0]}\n"
            f"⭐ {row[1]} امتیاز | 🎮 سطح {row[2]}\n\n"
        )

    return text


# =====================================================
# مأموریت روزانه
# =====================================================

def get_daily_mission(user_id):

    today = date.today()

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT mission_date, completed
            FROM daily_missions
            WHERE user_id = %s
        """, (user_id,))

        result = cur.fetchone()

        if not result or result[0] != today:

            cur.execute("""
                INSERT INTO daily_missions
                (user_id, mission_date, completed)

                VALUES (%s, %s, FALSE)

                ON CONFLICT (user_id)
                DO UPDATE SET
                    mission_date = EXCLUDED.mission_date,
                    completed = FALSE
            """, (user_id, today))

            db.commit()

            cur.close()
            db.close()

            return False

        completed = result[1]

        cur.close()
        db.close()

        return completed


def complete_daily_mission(user_id):

    if get_daily_mission(user_id):
        return False

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            UPDATE daily_missions
            SET completed = TRUE
            WHERE user_id = %s
        """, (user_id,))

        db.commit()

        cur.close()
        db.close()

    add_score(user_id, 20)

    return True


# =====================================================
# API بله
# =====================================================

def api_request(method, payload=None, timeout=20):

    try:

        response = requests.post(
            f"{BASE_URL}/{method}",
            json=payload or {},
            timeout=timeout
        )

        try:
            data = response.json()
        except Exception:
            print("❌ API پاسخ JSON معتبر نداد:", response.text)
            return None

        if response.status_code != 200 or not data.get("ok"):

            print(
                "❌ API Error:",
                method,
                data
            )

            return None

        return data

    except Exception as error:

        print(
            "❌ Request Error:",
            method,
            repr(error)
        )

        return None


def send_message(chat_id, text, reply_markup=None):

    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup is not None:
        payload["reply_markup"] = reply_markup

    return api_request(
        "sendMessage",
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
# منوها
# =====================================================

def get_main_menu(user_id=None):

    keyboard = [
        [
            {"text": "🎮 اتاق‌های آنلاین"},
            {"text": "🤖 بازی تک‌نفره"}
        ],
        [
            {"text": "⚔️ رقابت دو نفره"},
            {"text": "👤 حساب کاربری من"}
        ],
        [
            {"text": "🎯 مأموریت روزانه"},
            {"text": "🎡 گردونه شانس"}
        ],
        [
            {"text": "🏆 جدول امتیازات"},
            {"text": "✏️ تغییر نام"}
        ],
        [
            {"text": "📢 کانال اطلاع‌رسانی"},
            {"text": "💬 پشتیبانی"}
        ],
        [
            {"text": "📖 راهنمای بازی"}
        ]
    ]

    if user_id == ADMIN_ID:

        keyboard.append([
            {"text": "🛠️ پنل مدیریت"}
        ])

    return {
        "keyboard": keyboard,
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
                    "text": "👻 مرموز",
                    "callback_data": "mode_scary"
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
        "inline_keyboard": [
            [
                {
                    "text": "🎲 چالش بعدی",
                    "callback_data": "single_next"
                }
            ],
            [
                {
                    "text": "🏠 منوی اصلی",
                    "callback_data": "back_menu"
                }
            ]
        ]
    }


# =====================================================
# سؤال‌ها
# =====================================================

PROMPTS = {

    "normal": {

        "truth": [
            "بهترین خاطره مدرسه‌ات چیست؟",
            "اگر می‌توانستی یک مهارت جدید یاد بگیری، چه بود؟",
            "چه چیزی خیلی زود خوشحالت می‌کند؟",
            "کدام شخصیت کارتونی را بیشتر دوست داری؟"
        ],

        "dare": [
            "یک داستان خنده‌دار سه‌خطی بنویس.",
            "یک معمای ساده بساز و جوابش را بنویس.",
            "یک شعر کوتاه و بامزه بساز.",
            "نام پنج میوه را بنویس."
        ]
    },

    "fun": {

        "truth": [
            "عجیب‌ترین غذایی که امتحان کرده‌ای چه بوده؟",
            "اگر مدیر مدرسه بودی چه قانونی می‌گذاشتی؟",
            "اگر یک قدرت جادویی داشتی چه بود؟"
        ],

        "dare": [
            "یک جمله خنده‌دار با سه ایموجی بساز.",
            "یک لطیفه کوتاه و مناسب تعریف کن.",
            "یک تبلیغ بامزه برای یک مداد بنویس."
        ]
    },

    "scary": {

        "truth": [
            "کدام صدا در شب بیشتر غافلگیرت می‌کند؟",
            "اگر در یک خانه قدیمی بودی کدام اتاق را کشف می‌کردی؟"
        ],

        "dare": [
            "یک داستان مرموز سه‌خطی بنویس.",
            "یک اسم مرموز برای یک خانه خیالی انتخاب کن.",
            "یک معمای مرموز طراحی کن."
        ]
    }
}


DUEL_PROMPTS = [

    "🔥 چالش سخت: تصور کن یک شهر برای یک روز کاملاً بدون اینترنت می‌شود. در حداقل ۵ خط توضیح بده چه اتفاقی می‌افتد.",

    "🔥 چالش سخت: یک داستان کوتاه و خلاقانه بنویس که با جمله «وقتی در را باز کردم، هیچ‌کس آنجا نبود...» شروع شود و پایان غیرمنتظره داشته باشد.",

    "🔥 چالش سخت: اگر قرار بود یک اختراع جدید بسازی که زندگی دانش‌آموزان را بهتر کند، آن اختراع چه بود؟",

    "🔥 چالش سخت: تصور کن برای یک هفته مدیر یک مدرسه هستی. سه قانون جدید وضع کن و دلیل آن‌ها را بنویس.",

    "🔥 چالش سخت: یک معمای کاملاً جدید طراحی کن که جواب مشخص داشته باشد.",

    "🔥 چالش سخت: تصور کن به آینده سفر کرده‌ای و ۲۰ سال بعد را دیده‌ای. تغییرات را توضیح بده.",

    "🔥 چالش سخت: یک ایده برای ساخت یک بازی کاملاً جدید طراحی کن و قوانین آن را توضیح بده."
]


def get_random_prompt(mode, question_type):

    mode_prompts = PROMPTS.get(
        mode,
        PROMPTS["normal"]
    )

    return random.choice(
        mode_prompts[question_type]
    )


def mode_name(mode):

    names = {
        "normal": "معمولی و دوستانه",
        "fun": "خفن و چالشی",
        "scary": "مرموز"
    }

    return names.get(mode, "معمولی")


# =====================================================
# بازی تک‌نفره
# =====================================================

def start_single_game(chat_id):

    game = single_player.get(chat_id)

    if not game:
        return

    question_type = random.choice([
        "truth",
        "dare"
    ])

    prompt = get_random_prompt(
        game["mode"],
        question_type
    )

    game["waiting_answer"] = True

    title = (
        "🎯 حقیقت"
        if question_type == "truth"
        else "🔥 جرئت"
    )

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎮 حالت: {mode_name(game['mode'])}\n\n"
            f"{title}\n\n"
            f"📝 {prompt}\n\n"
            "✍️ پاسخ خود را ارسال کن."
        )
    )


def finish_single_game(chat_id):

    game = single_player.get(chat_id)

    if not game or not game.get("waiting_answer"):
        return

    game["waiting_answer"] = False

    add_score(chat_id, 5)

    send_message(
        chat_id,
        (
            "✅ پاسخ ثبت شد!\n\n"
            "🌟 ۵ امتیاز دریافت کردی."
        ),
        get_single_next_keyboard()
    )


# =====================================================
# اتاق آنلاین
# =====================================================

def generate_room_code():

    while True:

        code = str(random.randint(1000, 9999))

        with game_lock:
            if code not in rooms:
                return code


def create_room(chat_id, mode):

    code = generate_room_code()

    with game_lock:

        rooms[code] = {
            "host": chat_id,
            "players": [chat_id],
            "mode": mode,
            "phase": "waiting",
            "round": 0,
            "votes": {},
            "eligible_voters": [],
            "question": None,
            "answer": None,
            "questioner": None,
            "answerer": None,
            "duel": None,
            "duel_request": None
        }

    send_message(
        chat_id,
        (
            "✅ اتاق ساخته شد!\n\n"
            f"🔢 کد اتاق: {code}\n"
            f"🎮 حالت: {mode_name(mode)}"
        ),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "🚀 شروع بازی",
                        "callback_data": f"start_room_{code}"
                    }
                ],
                [
                    {
                        "text": "⚔️ درخواست دوئل",
                        "callback_data": f"show_duel_{code}"
                    }
                ],
                [
                    {
                        "text": "🗑️ حذف اتاق",
                        "callback_data": f"delete_room_{code}"
                    }
                ]
            ]
        }
    )


def list_rooms(chat_id):

    keyboard = []

    with game_lock:

        for code, room in rooms.items():

            # فقط اتاق‌هایی که هنوز بازی در آن‌ها شروع نشده
            if room["phase"] == "waiting":

                keyboard.append([
                    {
                        "text": (
                            f"🚪 اتاق {code} "
                            f"({len(room['players'])} نفر)"
                        ),
                        "callback_data": f"join_room_{code}"
                    }
                ])

    if not keyboard:

        send_message(
            chat_id,
            "❌ اتاقی که امکان ورود به آن وجود داشته باشد پیدا نشد."
        )

        return

    keyboard.append([
        {
            "text": "🔙 بازگشت",
            "callback_data": "back_menu"
        }
    ])

    send_message(
        chat_id,
        "🚪 یکی از اتاق‌ها را انتخاب کن:",
        {
            "inline_keyboard": keyboard
        }
    )


# =====================================================
# دوئل داخل اتاق
# =====================================================

def show_room_duel_players(chat_id, code):

    room = rooms.get(code)

    if not room:

        send_message(chat_id, "❌ اتاق پیدا نشد.")
        return

    if chat_id not in room["players"]:
        return

    if len(room["players"]) < 3:

        send_message(
            chat_id,
            (
                "⚠️ برای دوئل حداقل ۳ نفر لازم است.\n\n"
                "دو نفر رقابت می‌کنند و حداقل یک نفر رأی می‌دهد."
            )
        )

        return

    if room.get("duel"):

        send_message(
            chat_id,
            "⚠️ در حال حاضر یک دوئل در این اتاق فعال است."
        )

        return

    if room.get("duel_request"):

        send_message(
            chat_id,
            "⚠️ یک درخواست دوئل در انتظار پاسخ است."
        )

        return

    keyboard = []

    for player in room["players"]:

        if player != chat_id:

            keyboard.append([
                {
                    "text": f"⚔️ {get_name(player)}",
                    "callback_data":
                    f"duel_request_{code}_{player}"
                }
            ])

    send_message(
        chat_id,
        (
            "⚔️ درخواست دوئل\n\n"
            "حریف خود را انتخاب کن:"
        ),
        {
            "inline_keyboard": keyboard
        }
    )


def send_room_duel_request(
    code,
    challenger,
    opponent
):

    room = rooms.get(code)

    if not room:
        return

    if challenger not in room["players"]:
        return

    if opponent not in room["players"]:
        return

    if challenger == opponent:
        return

    if len(room["players"]) < 3:

        send_message(
            challenger,
            "⚠️ برای دوئل حداقل ۳ بازیکن لازم است."
        )

        return

    if room.get("duel"):

        send_message(
            challenger,
            "⚠️ یک دوئل در حال انجام است."
        )

        return

    if room.get("duel_request"):

        send_message(
            challenger,
            "⚠️ یک درخواست دوئل دیگر در انتظار پاسخ است."
        )

        return

    room["duel_request"] = {
        "challenger": challenger,
        "opponent": opponent
    }

    send_message(
        challenger,
        (
            "⚔️ درخواست دوئل ارسال شد!\n\n"
            f"⏳ منتظر پاسخ {get_name(opponent)} باش."
        )
    )

    send_message(
        opponent,
        (
            "⚔️ درخواست دوئل جدید!\n\n"
            f"👤 {get_name(challenger)} تو را به دوئل دعوت کرده است.\n\n"
            "آیا قبول می‌کنی؟"
        ),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "✅ قبول",
                        "callback_data":
                        f"duel_accept_{code}_{challenger}"
                    }
                ],
                [
                    {
                        "text": "❌ رد",
                        "callback_data":
                        f"duel_reject_{code}_{challenger}"
                    }
                ]
            ]
        }
    )


def start_room_duel(code, challenger, opponent):

    room = rooms.get(code)

    if not room:
        return

    if room.get("duel"):
        return

    challenge = random.choice(DUEL_PROMPTS)

    room["duel"] = {
        "challenger": challenger,
        "opponent": opponent,
        "challenge": challenge,
        "answers": {},
        "votes": {},
        "phase": "answering"
    }

    room["duel_request"] = None

    text = (
        "⚔️🔥 دوئل شروع شد!\n\n"
        f"🥊 بازیکن اول: {get_name(challenger)}\n"
        f"🥊 بازیکن دوم: {get_name(opponent)}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{challenge}\n\n"
        "━━━━━━━━━━━━━━"
    )

    for player in room["players"]:

        if player in (challenger, opponent):

            send_message(
                player,
                text + "\n\n✍️ پاسخ خود را ارسال کن."
            )

        else:

            send_message(
                player,
                (
                    text
                    + "\n\n🗳️ شما داور این دوئل هستید."
                    + "\nپس از ارسال پاسخ‌ها می‌توانید رأی بدهید."
                )
            )


def register_room_duel_answer(code, user_id, text):

    room = rooms.get(code)

    if not room:
        return False

    duel = room.get("duel")

    if not duel:
        return False

    if duel["phase"] != "answering":
        return False

    challenger = duel["challenger"]
    opponent = duel["opponent"]

    if user_id not in (challenger, opponent):
        return False

    if user_id in duel["answers"]:

        send_message(
            user_id,
            "⚠️ پاسخ شما قبلاً ثبت شده است."
        )

        return True

    duel["answers"][user_id] = text

    send_message(
        user_id,
        "✅ پاسخ شما ثبت شد."
    )

    if len(duel["answers"]) == 2:

        start_room_duel_voting(code)

    else:

        other_player = (
            opponent
            if user_id == challenger
            else challenger
        )

        send_message(
            other_player,
            "⏳ حریف پاسخ خود را ارسال کرد. منتظر پاسخ شما هستیم."
        )

    return True


def start_room_duel_voting(code):

    room = rooms.get(code)

    if not room:
        return

    duel = room.get("duel")

    if not duel:
        return

    if duel["phase"] != "answering":
        return

    challenger = duel["challenger"]
    opponent = duel["opponent"]

    duel["phase"] = "voting"
    duel["votes"] = {}

    challenger_answer = duel["answers"].get(
        challenger,
        "بدون پاسخ"
    )

    opponent_answer = duel["answers"].get(
        opponent,
        "بدون پاسخ"
    )

    text = (
        "⚔️📢 زمان رأی‌گیری!\n\n"
        f"🥊 بازیکن ۱: {get_name(challenger)}\n\n"
        f"💬 پاسخ:\n{challenger_answer}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"🥊 بازیکن ۲: {get_name(opponent)}\n\n"
        f"💬 پاسخ:\n{opponent_answer}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🗳️ به پاسخ بهتر رأی بده."
    )

    for player in room["players"]:

        if player in (challenger, opponent):

            send_message(
                player,
                text +
                "\n\n⛔ شما در دوئل هستید و نمی‌توانید رأی بدهید."
            )

        else:

            send_message(
                player,
                text,
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": f"🥊 {get_name(challenger)}",
                                "callback_data":
                                f"duel_vote_{code}_{challenger}"
                            }
                        ],
                        [
                            {
                                "text": f"🥊 {get_name(opponent)}",
                                "callback_data":
                                f"duel_vote_{code}_{opponent}"
                            }
                        ]
                    ]
                }
            )


def register_room_duel_vote(
    code,
    voter_id,
    selected_player
):

    room = rooms.get(code)

    if not room:
        return

    duel = room.get("duel")

    if not duel:
        return

    if duel["phase"] != "voting":

        send_message(
            voter_id,
            "⚠️ رأی‌گیری فعال نیست."
        )

        return

    challenger = duel["challenger"]
    opponent = duel["opponent"]

    if voter_id not in room["players"]:
        return

    if voter_id in (challenger, opponent):

        send_message(
            voter_id,
            "⛔ بازیکنان دوئل نمی‌توانند رأی بدهند."
        )

        return

    if voter_id in duel["votes"]:

        send_message(
            voter_id,
            "⚠️ شما قبلاً رأی داده‌اید."
        )

        return

    if selected_player not in (challenger, opponent):
        return

    duel["votes"][voter_id] = selected_player

    send_message(
        voter_id,
        "✅ رأی شما ثبت شد."
    )

    eligible_voters = [
        player
        for player in room["players"]
        if player not in (challenger, opponent)
    ]

    if len(duel["votes"]) >= len(eligible_voters):
        finish_room_duel(code)


def finish_room_duel(code):

    room = rooms.get(code)

    if not room:
        return

    duel = room.get("duel")

    if not duel:
        return

    if duel["phase"] != "voting":
        return

    # جلوگیری از اجرای دوباره نتیجه
    duel["phase"] = "finished"

    challenger = duel["challenger"]
    opponent = duel["opponent"]

    challenger_votes = sum(
        1
        for vote in duel["votes"].values()
        if vote == challenger
    )

    opponent_votes = sum(
        1
        for vote in duel["votes"].values()
        if vote == opponent
    )

    if challenger_votes > opponent_votes:

        winner = challenger
        add_score(winner, 15)

        result = (
            f"🏆 برنده: {get_name(winner)}\n"
            "🌟 جایزه: ۱۵ امتیاز"
        )

    elif opponent_votes > challenger_votes:

        winner = opponent
        add_score(winner, 15)

        result = (
            f"🏆 برنده: {get_name(winner)}\n"
            "🌟 جایزه: ۱۵ امتیاز"
        )

    else:

        result = (
            "⚖️ نتیجه دوئل مساوی شد!\n\n"
            "هیچ امتیازی اضافه نشد."
        )

    text = (
        "⚔️🏁 نتیجه نهایی دوئل\n\n"
        f"🥊 {get_name(challenger)}: "
        f"{challenger_votes} رأی\n\n"
        f"🥊 {get_name(opponent)}: "
        f"{opponent_votes} رأی\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"{result}"
    )

    for player in room["players"]:
        send_message(player, text)

    room["duel"] = None


# =====================================================
# بازی اصلی اتاق آنلاین
# =====================================================

def start_online_round(code):

    room = rooms.get(code)

    if not room:
        return

    if len(room["players"]) < 2:
        return

    if room.get("duel"):
        return

    room["round"] += 1

    questioner, answerer = random.sample(
        room["players"],
        2
    )

    room["questioner"] = questioner
    room["answerer"] = answerer
    room["question"] = None
    room["answer"] = None
    room["votes"] = {}
    room["eligible_voters"] = []
    room["phase"] = "choosing_type"

    text = (
        f"🎮 دور {room['round']}\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
    )

    for player in room["players"]:

        if player == answerer:

            send_message(
                player,
                text + "\n\nانتخاب کن:",
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎯 حقیقت",
                                "callback_data":
                                f"truth_{code}"
                            },
                            {
                                "text": "🔥 جرئت",
                                "callback_data":
                                f"dare_{code}"
                            }
                        ],
                        [
                            {
                                "text": "⚔️ درخواست دوئل",
                                "callback_data":
                                f"show_duel_{code}"
                            }
                        ]
                    ]
                }
            )

        else:

            send_message(
                player,
                text + "\n\n⏳ منتظر انتخاب..."
            )


def send_online_question(code):

    room = rooms.get(code)

    if not room:
        return

    room["phase"] = "waiting_answer"

    text = (
        "📢 سؤال یا چالش\n\n"
        f"📝 {room['question']}"
    )

    for player in room["players"]:

        if player == room["answerer"]:

            send_message(
                player,
                text + "\n\n💬 پاسخ خود را ارسال کن."
            )

        else:

            send_message(
                player,
                text + "\n\n⏳ منتظر پاسخ..."
            )


def start_online_voting(code):

    room = rooms.get(code)

    if not room:
        return

    room["phase"] = "voting"

    room["eligible_voters"] = [
        player
        for player in room["players"]
        if player != room["answerer"]
    ]

    room["votes"] = {}

    text = (
        "📢 پاسخ ثبت شد!\n\n"
        f"💬 {room['answer']}\n\n"
        "🗳️ آیا پاسخ قابل قبول است؟"
    )

    for player in room["players"]:

        if player == room["answerer"]:

            send_message(
                player,
                text + "\n\n⏳ منتظر رأی دیگران..."
            )

        else:

            send_message(
                player,
                text,
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "👍 تأیید",
                                "callback_data":
                                f"yes_{code}"
                            },
                            {
                                "text": "👎 رد",
                                "callback_data":
                                f"no_{code}"
                            }
                        ]
                    ]
                }
            )


def register_vote(code, user_id, vote):

    room = rooms.get(code)

    if not room:
        return

    if room["phase"] != "voting":
        return

    if user_id not in room["eligible_voters"]:

        send_message(
            user_id,
            "⚠️ شما اجازه رأی دادن ندارید."
        )

        return

    if user_id in room["votes"]:

        send_message(
            user_id,
            "⚠️ قبلاً رأی داده‌اید."
        )

        return

    room["votes"][user_id] = vote

    send_message(
        user_id,
        "✅ رأی شما ثبت شد."
    )

    if len(room["votes"]) >= len(room["eligible_voters"]):
        finish_online_voting(code)


def finish_online_voting(code):

    room = rooms.get(code)

    if not room:
        return

    if room["phase"] != "voting":
        return

    yes_votes = sum(
        1
        for vote in room["votes"].values()
        if vote == "yes"
    )

    no_votes = sum(
        1
        for vote in room["votes"].values()
        if vote == "no"
    )

    answerer = room["answerer"]

    if yes_votes > no_votes:

        add_score(answerer, 10)

        result = (
            "✅ پاسخ تأیید شد!\n"
            "🌟 ۱۰ امتیاز دریافت شد."
        )

    elif no_votes > yes_votes:

        result = "❌ پاسخ رد شد."

    else:

        result = "⚖️ رأی‌ها مساوی شدند."

    room["phase"] = "between_rounds"

    text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}"
    )

    for player in room["players"]:
        send_message(player, text)

    # بدون time.sleep تا Polling متوقف نشود
    start_online_round(code)


# =====================================================
# پیدا کردن اتاق کاربر
# =====================================================

def get_user_room(user_id):

    for code, room in rooms.items():

        if user_id in room["players"]:
            return code, room

    return None, None


# =====================================================
# پردازش پیام‌ها
# =====================================================

def handle_message(message):

    chat_id = (
        message.get("chat", {})
        .get("id")
    )

    if not chat_id:
        return

    text = (
        message.get("text", "")
        .strip()
    )

    if not text:
        return


    # =================================================
    # شناسه
    # =================================================

    if text == "/id":

        send_message(
            chat_id,
            f"🆔 شناسه عددی شما:\n\n{chat_id}"
        )

        return


    # =================================================
    # ثبت‌نام
    # =================================================

    if not user_exists(chat_id):

        if text == "/start":

            user_states[chat_id] = "register"

            send_message(
                chat_id,
                (
                    "👋 سلام!\n\n"
                    "✏️ یک نام مستعار انتخاب کن.\n\n"
                    "⚠️ نام باید منحصر‌به‌فرد باشد."
                )
            )

            return

        if user_states.get(chat_id) == "register":

            name = text[:40].strip()

            if len(name) < 2:

                send_message(
                    chat_id,
                    "⚠️ نام باید حداقل ۲ حرف داشته باشد."
                )

                return

            if name_exists(name):

                send_message(
                    chat_id,
                    "❌ این نام قبلاً انتخاب شده است."
                )

                return

            try:

                save_user(chat_id, name)

                user_states.pop(chat_id, None)

                send_message(
                    chat_id,
                    f"🎉 خوش آمدی {name}!",
                    get_main_menu(chat_id)
                )

            except Exception as error:

                print(
                    "Register Error:",
                    repr(error)
                )

                send_message(
                    chat_id,
                    "❌ خطا در ثبت‌نام."
                )

            return

        send_message(
            chat_id,
            "برای شروع /start را ارسال کن."
        )

        return


    # =================================================
    # تغییر نام
    # =================================================

    if user_states.get(chat_id) == "change_name":

        new_name = text[:40].strip()

        if len(new_name) < 2:

            send_message(
                chat_id,
                "⚠️ نام باید حداقل ۲ حرف داشته باشد."
            )

            return

        if name_exists(
            new_name,
            exclude_user_id=chat_id
        ):

            send_message(
                chat_id,
                "❌ این نام قبلاً توسط کاربر دیگری انتخاب شده است."
            )

            return

        save_user(chat_id, new_name)

        user_states.pop(chat_id, None)

        send_message(
            chat_id,
            "✅ نام شما با موفقیت تغییر کرد.",
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # پاسخ دوئل
    # =================================================

    for code, room in list(rooms.items()):

        if register_room_duel_answer(
            code,
            chat_id,
            text
        ):
            return


    # =================================================
    # پاسخ بازی تک‌نفره
    # =================================================

    if (
        single_player.get(chat_id, {})
        .get("waiting_answer")
    ):

        if text != "🏠 منوی اصلی":

            finish_single_game(chat_id)
            return


    # =================================================
    # شروع
    # =================================================

    if text == "/start":

        send_message(
            chat_id,
            (
                f"👋 سلام {get_name(chat_id)}!\n"
                "به بازی جرئت یا حقیقت خوش آمدی."
            ),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # منوی اصلی
    # =================================================

    if text == "🏠 منوی اصلی":

        user_states.pop(chat_id, None)
        single_player.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 منوی اصلی",
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # حساب کاربری
    # =================================================

    if text == "👤 حساب کاربری من":

        data = get_user_data(chat_id)
        rank = get_user_rank(chat_id)

        send_message(
            chat_id,
            (
                "👤 حساب کاربری من\n\n"
                f"📛 نام: {data[0]}\n"
                f"🆔 شناسه عددی: {chat_id}\n"
                f"⭐ امتیاز: {data[1]}\n"
                f"🎮 سطح: {data[2]}\n"
                f"🏆 رتبه: {rank}\n\n"
                f"📅 تاریخ عضویت: {data[3]}"
            ),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # مأموریت روزانه
    # =================================================

    if text == "🎯 مأموریت روزانه":

        completed = get_daily_mission(chat_id)

        if completed:

            send_message(
                chat_id,
                "🎯 مأموریت امروز را قبلاً انجام داده‌ای.",
                get_main_menu(chat_id)
            )

        else:

            complete_daily_mission(chat_id)

            send_message(
                chat_id,
                (
                    "🎯 مأموریت روزانه انجام شد!\n\n"
                    "🌟 ۲۰ امتیاز دریافت کردی."
                ),
                get_main_menu(chat_id)
            )

        return


    # =================================================
    # گردونه
    # =================================================

    if text == "🎡 گردونه شانس":

        reward = random.choice([
            1, 2, 5, 10, 15, 20
        ])

        add_score(chat_id, reward)

        send_message(
            chat_id,
            (
                "🎡 گردونه چرخید...\n\n"
                f"🎉 جایزه شما: {reward} امتیاز!"
            ),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # بازی تک‌نفره
    # =================================================

    if text == "🤖 بازی تک‌نفره":

        user_states[chat_id] = "choosing_single_mode"

        send_message(
            chat_id,
            "🎮 حالت بازی را انتخاب کن:",
            get_modes_keyboard()
        )

        return


    # =================================================
    # اتاق آنلاین
    # =================================================

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 بخش اتاق‌های آنلاین",
            get_rooms_menu()
        )

        return


    if text == "🛠️ ساخت اتاق جدید":

        # جلوگیری از ساخت چند اتاق توسط یک کاربر
        code, room = get_user_room(chat_id)

        if room:

            send_message(
                chat_id,
                (
                    "⚠️ شما در حال حاضر داخل یک اتاق هستید.\n"
                    f"🔢 کد اتاق: {code}"
                )
            )

            return

        user_states[chat_id] = "choosing_room_mode"

        send_message(
            chat_id,
            "🎮 حالت اتاق را انتخاب کن:",
            get_modes_keyboard()
        )

        return


    if text == "🚪 پیوستن به اتاق":

        code, room = get_user_room(chat_id)

        if room:

            send_message(
                chat_id,
                (
                    "⚠️ شما در حال حاضر داخل یک اتاق هستید.\n"
                    f"🔢 کد اتاق: {code}"
                )
            )

            return

        list_rooms(chat_id)

        return


    # =================================================
    # رقابت دو نفره
    # =================================================

    if text == "⚔️ رقابت دو نفره":

        send_message(
            chat_id,
            (
                "⚔️ رقابت دو نفره\n\n"
                "برای رقابت، وارد یک اتاق آنلاین شوید.\n\n"
                "اگر حداقل ۳ نفر در اتاق باشند، "
                "دو نفر می‌توانند با هم دوئل کنند و بقیه رأی بدهند."
            ),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # جدول امتیازات
    # =================================================

    if text == "🏆 جدول امتیازات":

        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # تغییر نام
    # =================================================

    if text == "✏️ تغییر نام":

        user_states[chat_id] = "change_name"

        send_message(
            chat_id,
            "✏️ نام جدید خود را ارسال کن."
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
                "https://ble.ir/ettelae_resani"
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
                "https://ble.ir/kia_karfarma"
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

                "🤖 بازی تک‌نفره:\n"
                "به چالش‌ها پاسخ بده و امتیاز بگیر.\n\n"

                "🎮 اتاق آنلاین:\n"
                "اتاق بساز یا وارد اتاق دیگران شو.\n\n"

                "⚔️ دوئل داخل اتاق:\n"
                "حداقل ۳ نفر لازم است. "
                "دو نفر رقابت می‌کنند و بقیه رأی می‌دهند.\n\n"

                "🆔 برای دیدن شناسه عددی خود /id را ارسال کن."
            ),
            get_main_menu(chat_id)
        )

        return


    # =================================================
    # پنل مدیریت
    # =================================================

    if text == "🛠️ پنل مدیریت":

        if chat_id != ADMIN_ID:

            send_message(
                chat_id,
                "⛔ شما اجازه ورود ندارید."
            )

            return

        send_message(
            chat_id,
            (
                "🛠️ پنل مدیریت\n\n"
                f"👥 تعداد کاربران: {get_total_users()}\n"
                f"🎮 اتاق‌های فعال: {len(rooms)}\n\n"
                "🔐 فقط مدیر به این بخش دسترسی دارد."
            )
        )

        return


    # =================================================
    # دریافت سؤال اتاق
    # =================================================

    for code, room in list(rooms.items()):

        if (
            room.get("phase") == "waiting_question"
            and room.get("questioner") == chat_id
        ):

            room["question"] = text

            send_online_question(code)

            return


    # =================================================
    # دریافت پاسخ اتاق
    # =================================================

    for code, room in list(rooms.items()):

        if (
            room.get("phase") == "waiting_answer"
            and room.get("answerer") == chat_id
        ):

            room["answer"] = text

            start_online_voting(code)

            return


    send_message(
        chat_id,
        "از دکمه‌های منو استفاده کن 👇",
        get_main_menu(chat_id)
    )


# =====================================================
# پردازش Callback
# =====================================================

def handle_callback(query):

    callback_id = query.get("id")

    message = query.get("message", {})

    chat_id = (
        message.get("chat", {})
        .get("id")
    )

    data = query.get("data", "")

    answer_callback(callback_id)

    if not chat_id:
        return


    # =================================================
    # بازگشت
    # =================================================

    if data == "back_menu":

        user_states.pop(chat_id, None)
        single_player.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 منوی اصلی",
            get_main_menu(chat_id)
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

            send_message(
                chat_id,
                "❌ حالت نامعتبر است."
            )

            return

        state = user_states.get(chat_id)

        if state == "choosing_single_mode":

            single_player[chat_id] = {
                "mode": mode,
                "waiting_answer": False
            }

            user_states.pop(chat_id, None)

            start_single_game(chat_id)

            return


        if state == "choosing_room_mode":

            user_states.pop(chat_id, None)

            create_room(
                chat_id,
                mode
            )

            return


    # =================================================
    # چالش بعدی
    # =================================================

    if data == "single_next":

        if chat_id in single_player:
            start_single_game(chat_id)

        return


    # =================================================
    # ورود به اتاق
    # =================================================

    if data.startswith("join_room_"):

        code = data.replace(
            "join_room_",
            "",
            1
        )

        room = rooms.get(code)

        if not room:

            send_message(
                chat_id,
                "❌ این اتاق وجود ندارد."
            )

            return

        if room["phase"] != "waiting":

            send_message(
                chat_id,
                "⚠️ بازی این اتاق شروع شده و امکان ورود جدید وجود ندارد."
            )

            return

        old_code, old_room = get_user_room(chat_id)

        if old_room and old_code != code:

            send_message(
                chat_id,
                "⚠️ شما قبلاً داخل یک اتاق دیگر هستید."
            )

            return

        if chat_id not in room["players"]:

            room["players"].append(chat_id)

            for player in room["players"]:

                send_message(
                    player,
                    f"👤 {get_name(chat_id)} وارد اتاق شد."
                )

        send_message(
            chat_id,
            (
                f"🎮 وارد اتاق {code} شدی.\n\n"
                "می‌توانی منتظر شروع بازی بمانی."
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "⚔️ درخواست دوئل",
                            "callback_data":
                            f"show_duel_{code}"
                        }
                    ]
                ]
            }
        )

        return


    # =================================================
    # نمایش بازیکنان دوئل
    # =================================================

    if data.startswith("show_duel_"):

        code = data.replace(
            "show_duel_",
            "",
            1
        )

        show_room_duel_players(
            chat_id,
            code
        )

        return


    # =================================================
    # ارسال درخواست دوئل
    # =================================================

    if data.startswith("duel_request_"):

        parts = data.split("_")

        try:

            if len(parts) >= 4:

                code = parts[2]
                opponent = int(parts[3])

                send_room_duel_request(
                    code,
                    chat_id,
                    opponent
                )

        except ValueError:

            send_message(
                chat_id,
                "❌ خطا در درخواست دوئل."
            )

        return


    # =================================================
    # قبول دوئل
    # =================================================

    if data.startswith("duel_accept_"):

        parts = data.split("_")

        try:

            if len(parts) >= 4:

                code = parts[2]
                challenger = int(parts[3])

                room = rooms.get(code)

                if not room:
                    return

                request = room.get("duel_request")

                if not request:
                    return

                if request["challenger"] != challenger:
                    return

                if request["opponent"] != chat_id:
                    return

                start_room_duel(
                    code,
                    challenger,
                    chat_id
                )

        except ValueError:
            pass

        return


    # =================================================
    # رد دوئل
    # =================================================

    if data.startswith("duel_reject_"):

        parts = data.split("_")

        try:

            if len(parts) >= 4:

                code = parts[2]
                challenger = int(parts[3])

                room = rooms.get(code)

                if room:

                    request = room.get("duel_request")

                    if (
                        request
                        and request["challenger"] == challenger
                        and request["opponent"] == chat_id
                    ):

                        room["duel_request"] = None

                        send_message(
                            challenger,
                            "❌ درخواست دوئل رد شد."
                        )

                        send_message(
                            chat_id,
                            "❌ درخواست دوئل را رد کردی."
                        )

        except ValueError:
            pass

        return


    # =================================================
    # رأی دوئل
    # =================================================

    if data.startswith("duel_vote_"):

        parts = data.split("_")

        try:

            if len(parts) >= 4:

                code = parts[2]
                selected_player = int(parts[3])

                register_room_duel_vote(
                    code,
                    chat_id,
                    selected_player
                )

        except ValueError:
            pass

        return


    # =================================================
    # شروع اتاق
    # =================================================

    if data.startswith("start_room_"):

        code = data.replace(
            "start_room_",
            "",
            1
        )

        room = rooms.get(code)

        if not room:
            return

        if room["phase"] != "waiting":

            send_message(
                chat_id,
                "⚠️ بازی این اتاق قبلاً شروع شده است."
            )

            return

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند بازی را شروع کند."
            )

            return

        if len(room["players"]) < 2:

            send_message(
                chat_id,
                "⚠️ حداقل دو بازیکن لازم است."
            )

            return

        start_online_round(code)

        return


    # =================================================
    # حذف اتاق
    # =================================================

    if data.startswith("delete_room_"):

        code = data.replace(
            "delete_room_",
            "",
            1
        )

        room = rooms.get(code)

        if not room:
            return

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند اتاق را حذف کند."
            )

            return

        for player in room["players"]:

            send_message(
                player,
                "❌ اتاق توسط میزبان بسته شد."
            )

        del rooms[code]

        return


    # =================================================
    # حقیقت و جرئت
    # =================================================

    if (
        data.startswith("truth_")
        or data.startswith("dare_")
    ):

        question_type, code = data.split(
            "_",
            1
        )

        room = rooms.get(code)

        if not room:
            return

        if room["phase"] != "choosing_type":
            return

        if room["answerer"] != chat_id:

            send_message(
                chat_id,
                "⚠️ شما پاسخ‌دهنده این دور نیستید."
            )

            return

        room["question_type"] = question_type
        room["phase"] = "waiting_question"

        send_message(
            room["questioner"],
            (
                "✍️ پاسخ‌دهنده انتخاب خود را انجام داد.\n\n"
                "حالا سؤال یا چالش را ارسال کن."
            )
        )

        return


    # =================================================
    # رأی بازی عادی
    # =================================================

    if (
        data.startswith("yes_")
        or data.startswith("no_")
    ):

        vote, code = data.split(
            "_",
            1
        )

        register_vote(
            code,
            chat_id,
            vote
        )

        return


# =====================================================
# پردازش آپدیت
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
            repr(error)
        )


# =====================================================
# Polling
# =====================================================
def run_polling():
    offset = None

    print("🤖 Polling started")
    print("📡 Requesting updates from Bale API...")

    while True:
        try:
            params = {
                "timeout": 20
            }

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                f"{BASE_URL}/getUpdates",
                params=params,
                timeout=30
            )

            print(f"📡 HTTP Status: {response.status_code}")
            print(f"📡 API Response: {response.text}")

            if response.status_code != 200:
                print(f"❌ HTTP Error: {response.status_code}")
                time.sleep(3)
                continue

            data = response.json()

            if not data.get("ok", False):
                print(f"❌ getUpdates API Error: {data}")
                time.sleep(3)
                continue

            updates = data.get("result", [])

            if updates:
                print(f"📨 Received {len(updates)} update(s)")

            for update in updates:

                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                print(f"📨 Processing update: {update}")

                handle_update(update)

        except requests.exceptions.Timeout:
            print("⏳ Request timeout")

        except Exception as error:
            print(f"❌ Polling Error: {repr(error)}")
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
