import os
import random
import threading
import time

import requests
import psycopg2
from flask import Flask, jsonify


# =====================================================
# تنظیمات
# =====================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN تنظیم نشده است.")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL تنظیم نشده است.")

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

app = Flask(__name__)

db_lock = threading.Lock()


# =====================================================
# اطلاعات موقت ربات
# =====================================================

user_states = {}

single_player = {}

rooms = {}


# =====================================================
# وب‌سرور برای Render
# =====================================================

@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running!"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


# =====================================================
# اتصال به دیتابیس
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
                name TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # جلوگیری از نام تکراری
        cur.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS users_unique_name_ci
            ON users (LOWER(BTRIM(name)))
        """)

        db.commit()

        cur.close()
        db.close()

    print("✅ PostgreSQL database initialized")


# =====================================================
# مدیریت کاربران
# =====================================================

def normalize_name(name):

    return " ".join(name.strip().split())


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

    normalized_name = normalize_name(name)

    with db_lock:

        db = get_db()
        cur = db.cursor()

        if exclude_user_id is None:

            cur.execute(
                """
                SELECT 1
                FROM users
                WHERE LOWER(BTRIM(name)) = LOWER(%s)
                LIMIT 1
                """,
                (normalized_name,)
            )

        else:

            cur.execute(
                """
                SELECT 1
                FROM users
                WHERE LOWER(BTRIM(name)) = LOWER(%s)
                AND user_id <> %s
                LIMIT 1
                """,
                (
                    normalized_name,
                    exclude_user_id
                )
            )

        result = cur.fetchone()

        cur.close()
        db.close()

    return result is not None


def save_user(user_id, name):

    normalized_name = normalize_name(name)

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                INSERT INTO users (user_id, name, score)
                VALUES (%s, %s, 0)

                ON CONFLICT (user_id)
                DO UPDATE SET
                    name = EXCLUDED.name
            """, (
                user_id,
                normalized_name
            ))

            db.commit()

            return True

        except psycopg2.IntegrityError:

            db.rollback()

            return False

        finally:

            cur.close()
            db.close()


def get_name(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute(
            "SELECT name FROM users WHERE user_id = %s",
            (user_id,)
        )

        result = cur.fetchone()

        cur.close()
        db.close()

    if result:
        return result[0]

    return "بازیکن"


def add_score(user_id, points):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            UPDATE users
            SET score = score + %s
            WHERE user_id = %s
        """, (
            points,
            user_id
        ))

        db.commit()

        cur.close()
        db.close()


def get_leaderboard_text():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        cur.execute("""
            SELECT name, score
            FROM users
            ORDER BY score DESC, name ASC
            LIMIT 10
        """)

        rows = cur.fetchall()

        cur.close()
        db.close()

    if not rows:

        return "🏆 هنوز امتیازی ثبت نشده است."

    result = "🏆 جدول برترین بازیکنان\n\n"

    for index, row in enumerate(rows, 1):

        result += (
            f"{index}. {row[0]} — "
            f"{row[1]} امتیاز\n"
        )

    return result


# =====================================================
# ارتباط با API بله
# =====================================================

def api_request(method, payload=None, timeout=30):

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
                "❌ API Error:",
                method,
                data
            )

            return None

        return data

    except Exception as error:

        print(
            "❌ Request Error:",
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

    if reply_markup:

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

        payload["caption"] = caption

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

        payload["caption"] = caption

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
# تشخیص عکس و ویس
# =====================================================

def get_media_from_message(message):

    photos = message.get("photo")

    if photos:

        photo = photos[-1]

        file_id = photo.get("file_id")

        if file_id:

            return {
                "type": "photo",
                "file_id": file_id,
                "caption": (
                    message.get("caption", "")
                    .strip()
                )
            }

    voice = message.get("voice")

    if voice:

        file_id = voice.get("file_id")

        if file_id:

            return {
                "type": "voice",
                "file_id": file_id,
                "caption": (
                    message.get("caption", "")
                    .strip()
                )
            }

    return None


def send_media(
    chat_id,
    media,
    prefix=None
):

    if not media:
        return

    media_type = media.get("type")

    file_id = media.get("file_id")

    caption = media.get("caption", "")

    if prefix:

        if caption:

            caption = (
                f"{prefix}\n\n"
                f"{caption}"
            )

        else:

            caption = prefix

    if media_type == "photo":

        send_photo(
            chat_id,
            file_id,
            caption
        )

    elif media_type == "voice":

        if prefix:

            send_message(
                chat_id,
                prefix
            )

        if caption:

            send_message(
                chat_id,
                caption
            )

        send_voice(
            chat_id,
            file_id
        )


# =====================================================
# منوی اصلی
# =====================================================

def get_main_menu():

    return {
        "keyboard": [

            [
                {"text": "🎮 اتاق‌های آنلاین"},
                {"text": "🤖 بازی تک‌نفره"}
            ],

            [
                {"text": "🏆 جدول امتیازات"},
                {"text": "✏️ تغییر نام"}
            ],

            [
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
                    "text": "👻 ترسناک و مرموز",
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
# بانک بازی تک‌نفره
# =====================================================

PROMPTS = {

    "normal": {

        "truth": [

            "آخرین باری که از ته دل خندیدی چه زمانی بود؟",

            "اگر می‌توانستی یک مهارت جدید یاد بگیری، چه بود؟",

            "بهترین خاطره مدرسه‌ات چیست؟",

            "چه چیزی خیلی زود خوشحالت می‌کند؟",

            "اگر یک روز نامرئی بودی، چه کار بی‌خطری انجام می‌دادی؟",

            "کدام شخصیت کارتونی را بیشتر دوست داری؟"

        ],

        "dare": [

            "یک داستان خنده‌دار سه‌خطی بنویس.",

            "نام پنج میوه را بنویس.",

            "یک معمای ساده بساز.",

            "یک شعر کوتاه و بامزه بنویس.",

            "یک جمله با پنج کلمه که با یک حرف شروع می‌شوند بنویس."

        ]
    },


    "fun": {

        "truth": [

            "عجیب‌ترین غذایی که امتحان کرده‌ای چه بوده؟",

            "اگر مدیر مدرسه بودی چه قانونی می‌گذاشتی؟",

            "اگر یک قدرت جادویی داشتی، چه بود؟",

            "خنده‌دارترین اشتباهی که در یک بازی کرده‌ای چه بوده؟"

        ],

        "dare": [

            "یک جمله خنده‌دار با سه ایموجی بساز.",

            "یک لطیفه کوتاه و مناسب تعریف کن.",

            "یک تبلیغ بامزه برای یک مداد بنویس.",

            "یک داستان کوتاه خنده‌دار بساز."

        ]
    },


    "scary": {

        "truth": [

            "کدام صدا در شب بیشتر غافلگیرت می‌کند؟",

            "ترسناک‌ترین داستانی که شنیده‌ای چه بوده؟",

            "اگر در یک داستان معمایی بودی چه نقشی داشتی؟"

        ],

        "dare": [

            "یک داستان مرموز سه‌خطی بنویس.",

            "یک اسم ترسناک برای یک خانه خیالی انتخاب کن.",

            "یک معمای مرموز طراحی کن."

        ]
    }

}


def get_random_prompt(
    mode,
    question_type
):

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

        "scary": "ترسناک و مرموز"

    }

    return names.get(
        mode,
        "معمولی"
    )


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

    game["question_type"] = question_type
    game["prompt"] = prompt
    game["waiting_answer"] = True

    if question_type == "truth":

        title = "🎯 حقیقت"

        instruction = (
            "به سؤال پاسخ بده."
        )

    else:

        title = "🔥 جرئت"

        instruction = (
            "چالش را انجام بده و "
            "نتیجه یا پاسخ مناسب را ارسال کن."
        )

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎮 حالت: {mode_name(game['mode'])}\n\n"
            f"{title}\n\n"
            f"📝 {prompt}\n\n"
            f"✍️ {instruction}\n\n"
            "ℹ️ بازی تک‌نفره صرفاً برای "
            "سرگرمی است و امتیازی ندارد."
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

    game = single_player.get(chat_id)

    if not game:
        return

    if not game.get("waiting_answer"):
        return

    game["waiting_answer"] = False

    send_message(
        chat_id,
        (
            "✅ پاسخ شما ثبت شد.\n\n"
            "🎮 در بازی تک‌نفره امتیازی داده نمی‌شود.\n\n"
            "برای ادامه، سؤال جدید را انتخاب کن."
        ),
        get_single_next_keyboard()
    )


# =====================================================
# مدیریت اتاق‌ها
# =====================================================

def generate_room_code():

    while True:

        code = str(
            random.randint(1000, 9999)
        )

        if code not in rooms:

            return code


def find_player_room(user_id):

    for code, room in rooms.items():

        if user_id in room.get(
            "players",
            []
        ):

            return code, room

    return None, None


def create_room(
    chat_id,
    mode
):

    # کاربر هم‌زمان فقط در یک اتاق باشد
    old_code, old_room = find_player_room(
        chat_id
    )

    if old_room:

        send_message(
            chat_id,
            (
                "⚠️ شما در حال حاضر عضو "
                "یک اتاق دیگر هستید."
            )
        )

        return

    code = generate_room_code()

    rooms[code] = {

        "host": chat_id,

        "players": [
            chat_id
        ],

        "mode": mode,

        "phase": "waiting",

        "round": 0,

        "questioner": None,

        "answerer": None,

        "question_type": None,

        "question": None,

        "answer": None,

        "votes": {},

        "eligible_voters": []

    }

    send_message(
        chat_id,
        (
            "✅ اتاق با موفقیت ساخته شد!\n\n"
            f"🔢 کد اتاق: {code}\n"
            f"🎮 حالت: {mode_name(mode)}\n\n"
            "👥 منتظر ورود بازیکنان باش."
        ),
        {
            "inline_keyboard": [

                [
                    {
                        "text": "🚀 شروع بازی",
                        "callback_data": (
                            f"start_room_{code}"
                        )
                    }
                ],

                [
                    {
                        "text": "🗑️ حذف اتاق",
                        "callback_data": (
                            f"delete_room_{code}"
                        )
                    }
                ]

            ]
        }
    )


def list_rooms(chat_id):

    keyboard = []

    for code, room in rooms.items():

        if room.get("phase") == "waiting":

            keyboard.append([

                {
                    "text": (
                        f"🚪 اتاق {code} | "
                        f"{len(room['players'])} نفر"
                    ),

                    "callback_data": (
                        f"join_room_{code}"
                    )
                }

            ])

    if not keyboard:

        send_message(
            chat_id,
            "❌ در حال حاضر اتاقی برای پیوستن وجود ندارد."
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
# شروع دور آنلاین
# =====================================================

def start_online_round(code):

    room = rooms.get(code)

    if not room:
        return

    players = room.get(
        "players",
        []
    )

    if len(players) < 2:

        return

    room["round"] += 1

    questioner, answerer = random.sample(
        players,
        2
    )

    # پاک‌سازی کامل دور قبلی
    room["questioner"] = questioner
    room["answerer"] = answerer
    room["question_type"] = None
    room["question"] = None
    room["answer"] = None
    room["votes"] = {}
    room["eligible_voters"] = []

    room["phase"] = "choosing_type"

    message = (
        f"🎮 دور {room['round']}\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(questioner)}\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}"
    )

    for player in list(players):

        if player == answerer:

            send_message(
                player,
                (
                    message +
                    "\n\n🎯 انتخاب کن:\n"
                    "حقیقت یا جرئت؟"
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
                    message +
                    "\n\n⏳ منتظر انتخاب "
                    "پاسخ‌دهنده باش."
                )
            )


# =====================================================
# ارسال سؤال برای همه
# =====================================================

def send_online_question(code):

    room = rooms.get(code)

    if not room:
        return

    question = room.get("question")

    room["phase"] = "waiting_answer"

    header = (
        "📢 سؤال یا چالش جدید\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(room['questioner'])}\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(room['answerer'])}"
    )

    for player in list(room["players"]):

        if isinstance(question, dict):

            send_message(
                player,
                header
            )

            send_media(
                player,
                question
            )

        else:

            send_message(
                player,
                (
                    header +
                    f"\n\n📝 {question}"
                )
            )

        if player == room["answerer"]:

            send_message(
                player,
                (
                    "💬 حالا پاسخ خود را به صورت "
                    "متن، عکس یا ویس ارسال کن."
                )
            )

        else:

            send_message(
                player,
                "⏳ منتظر پاسخ باش."
            )


# =====================================================
# شروع رأی‌گیری
# =====================================================

def start_online_voting(code):

    room = rooms.get(code)

    if not room:
        return

    answerer = room["answerer"]

    # همه به جز پاسخ‌دهنده می‌توانند رأی بدهند
    eligible_voters = [

        player

        for player in room["players"]

        if player != answerer

    ]

    room["eligible_voters"] = eligible_voters
    room["votes"] = {}

    room["phase"] = "voting"

    answer = room.get("answer")

    header = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}"
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

    for player in list(room["players"]):

        if isinstance(answer, dict):

            send_message(
                player,
                header
            )

            send_media(
                player,
                answer
            )

        else:

            send_message(
                player,
                (
                    header +
                    f"\n\n💬 پاسخ:\n{answer}"
                )
            )

        if player == answerer:

            send_message(
                player,
                "⏳ منتظر رأی سایر بازیکنان باش."
            )

        else:

            send_message(
                player,
                "🗳️ آیا پاسخ مورد قبول است؟",
                vote_keyboard
            )


# =====================================================
# ثبت رأی
# =====================================================

def register_vote(
    code,
    user_id,
    vote
):

    room = rooms.get(code)

    if not room:
        return

    if room.get("phase") != "voting":

        send_message(
            user_id,
            "⚠️ رأی‌گیری فعالی وجود ندارد."
        )

        return

    if user_id not in room.get(
        "players",
        []
    ):

        send_message(
            user_id,
            "⚠️ شما عضو این اتاق نیستید."
        )

        return

    if user_id == room.get("answerer"):

        send_message(
            user_id,
            (
                "⚠️ شما نمی‌توانید به "
                "پاسخ خودتان رأی بدهید."
            )
        )

        return

    if user_id not in room.get(
        "eligible_voters",
        []
    ):

        send_message(
            user_id,
            "⚠️ اجازه رأی دادن ندارید."
        )

        return

    if user_id in room.get(
        "votes",
        {}
    ):

        send_message(
            user_id,
            "⚠️ شما قبلاً رأی داده‌اید."
        )

        return

    room["votes"][user_id] = vote

    send_message(
        user_id,
        "✅ رأی شما ثبت شد."
    )

    # اگر همه رأی داده باشند
    if len(room["votes"]) >= len(
        room["eligible_voters"]
    ):

        finish_online_voting(code)


# =====================================================
# پایان رأی‌گیری
# =====================================================

def finish_online_voting(code):

    room = rooms.get(code)

    if not room:
        return

    # جلوگیری از اجرای دوباره
    if room.get("phase") != "voting":
        return

    room["phase"] = "between_rounds"

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

        add_score(
            answerer,
            10
        )

        result = (
            "✅ پاسخ تأیید شد!\n"
            "🌟 ۱۰ امتیاز به پاسخ‌دهنده اضافه شد."
        )

    elif no_votes > yes_votes:

        result = (
            "❌ پاسخ رد شد.\n"
            "امتیازی داده نشد."
        )

    else:

        result = (
            "⚖️ رأی‌ها مساوی شدند.\n"
            "امتیازی داده نشد."
        )

    message = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی شروع می‌شود..."
    )

    for player in list(
        room.get("players", [])
    ):

        send_message(
            player,
            message
        )

    # شروع دور بعدی بدون مسدود کردن ربات
    def next_round():

        time.sleep(2)

        room = rooms.get(code)

        if not room:
            return

        if len(room.get("players", [])) >= 2:

            start_online_round(code)

    threading.Thread(
        target=next_round,
        daemon=True
    ).start()


# =====================================================
# پردازش پیام‌های کاربران
# =====================================================

def handle_message(message):

    chat = message.get("chat", {})

    chat_id = chat.get("id")

    if not chat_id:
        return

    text = message.get(
        "text",
        ""
    ).strip()

    media = get_media_from_message(
        message
    )


    # =================================================
    # ثبت نام اولین ورود
    # =================================================

    if not user_exists(chat_id):

        if not text:

            send_message(
                chat_id,
                (
                    "👋 سلام!\n\n"
                    "لطفاً برای شروع یک نام "
                    "مستعار انتخاب و ارسال کن."
                )
            )

            return

        new_name = normalize_name(
            text[:40]
        )

        if not new_name:

            send_message(
                chat_id,
                "⚠️ لطفاً یک نام معتبر وارد کن."
            )

            return

        if name_exists(new_name):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط کاربر "
                    "دیگری انتخاب شده است.\n\n"
                    "لطفاً نام دیگری انتخاب کن."
                )
            )

            return

        if not save_user(
            chat_id,
            new_name
        ):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط کاربر "
                    "دیگری انتخاب شده است."
                )
            )

            return

        send_message(
            chat_id,
            (
                f"🎉 خوش آمدی {new_name}!\n\n"
                "حساب کاربری تو ساخته شد."
            ),
            get_main_menu()
        )

        return


    # =================================================
    # تغییر نام
    # =================================================

    if user_states.get(chat_id) == "change_name":

        if not text:

            send_message(
                chat_id,
                "⚠️ لطفاً نام جدید را به صورت متن ارسال کن."
            )

            return

        new_name = normalize_name(
            text[:40]
        )

        if not new_name:

            send_message(
                chat_id,
                "⚠️ نام واردشده معتبر نیست."
            )

            return

        if name_exists(
            new_name,
            exclude_user_id=chat_id
        ):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط کاربر "
                    "دیگری انتخاب شده است."
                )
            )

            return

        if not save_user(
            chat_id,
            new_name
        ):

            send_message(
                chat_id,
                "❌ تغییر نام انجام نشد."
            )

            return

        user_states.pop(
            chat_id,
            None
        )

        send_message(
            chat_id,
            "✅ نام شما با موفقیت تغییر کرد.",
            get_main_menu()
        )

        return


    # =================================================
    # پاسخ بازی تک‌نفره
    # =================================================

    if single_player.get(
        chat_id,
        {}
    ).get("waiting_answer"):

        if text == "🏠 منوی اصلی":

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

        if text or media:

            finish_single_game(chat_id)

            return

        send_message(
            chat_id,
            "⚠️ لطفاً یک پاسخ ارسال کن."
        )

        return


    # =================================================
    # شروع ربات
    # =================================================

    if text == "/start":

        send_message(
            chat_id,
            (
                f"👋 سلام {get_name(chat_id)}!\n\n"
                "به بازی جرئت یا حقیقت خوش آمدی."
            ),
            get_main_menu()
        )

        return


    # =================================================
    # منوی اصلی
    # =================================================

    if text == "🏠 منوی اصلی":

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

        user_states[chat_id] = (
            "choosing_single_mode"
        )

        send_message(
            chat_id,
            "🎮 حالت بازی را انتخاب کن:",
            get_modes_keyboard()
        )

        return


    # =================================================
    # سؤال جدید
    # =================================================

    if text == "⏭️ سؤال جدید":

        if chat_id in single_player:

            start_single_game(chat_id)

        return


    # =================================================
    # اتاق آنلاین
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

        user_states[chat_id] = (
            "choosing_room_mode"
        )

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

        list_rooms(chat_id)

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

        user_states[chat_id] = "change_name"

        send_message(
            chat_id,
            (
                "✏️ نام جدید خود را ارسال کن.\n\n"
                "نام نباید قبلاً توسط کاربر دیگری "
                "انتخاب شده باشد."
            )
        )

        return


    # =================================================
    # کانال
    # =================================================

    if text == "📢 کانال اطلاع‌رسانی":

        send_message(
            chat_id,
            "📢 کانال اطلاع‌رسانی:\n@ettelae_resani"
        )

        return


    # =================================================
    # پشتیبانی
    # =================================================

    if text == "💬 پشتیبانی":

        send_message(
            chat_id,
            "💬 پشتیبانی:\n@kia_karfarma"
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
                "سؤال یا چالش دریافت کن و پاسخ بده.\n"
                "این بخش صرفاً برای سرگرمی است و "
                "امتیازی ندارد.\n\n"

                "🎮 بازی آنلاین:\n"
                "یک اتاق بساز یا وارد اتاق دیگران شو.\n\n"

                "🎯 پاسخ‌دهنده حقیقت یا جرئت "
                "را انتخاب می‌کند.\n"

                "✍️ پرسش‌کننده سؤال یا چالش "
                "را ارسال می‌کند.\n"

                "📷🎤 سؤال و پاسخ می‌توانند "
                "متن، عکس یا ویس باشند.\n\n"

                "🗳️ سایر بازیکنان رأی می‌دهند.\n"

                "🏆 در صورت تأیید اکثریت، "
                "۱۰ امتیاز به پاسخ‌دهنده داده می‌شود."
            ),
            get_main_menu()
        )

        return


    # =================================================
    # دریافت سؤال آنلاین
    # =================================================

    for code, room in list(rooms.items()):

        if (
            room.get("phase") == "waiting_question"
            and room.get("questioner") == chat_id
        ):

            if media:

                room["question"] = media

                send_online_question(code)

                return

            if text:

                room["question"] = text

                send_online_question(code)

                return

            send_message(
                chat_id,
                (
                    "⚠️ سؤال یا چالش را به صورت "
                    "متن، عکس یا ویس ارسال کن."
                )
            )

            return


    # =================================================
    # دریافت پاسخ آنلاین
    # =================================================

    for code, room in list(rooms.items()):

        if (
            room.get("phase") == "waiting_answer"
            and room.get("answerer") == chat_id
        ):

            if media:

                room["answer"] = media

                start_online_voting(code)

                return

            if text:

                room["answer"] = text

                start_online_voting(code)

                return

            send_message(
                chat_id,
                (
                    "⚠️ پاسخ را به صورت متن، "
                    "عکس یا ویس ارسال کن."
                )
            )

            return


    # =================================================
    # پیام پیش‌فرض
    # =================================================

    send_message(
        chat_id,
        "⚠️ لطفاً از دکمه‌های منو استفاده کن.",
        get_main_menu()
    )


# =====================================================
# پردازش Callback ها
# =====================================================

def handle_callback(query):

    callback_id = query.get("id")

    message = query.get(
        "message",
        {}
    )

    chat = message.get(
        "chat",
        {}
    )

    chat_id = chat.get("id")

    data = query.get(
        "data",
        ""
    )

    if callback_id:

        answer_callback(callback_id)

    if not chat_id:
        return


    # =================================================
    # بازگشت
    # =================================================

    if data == "back_menu":

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

        if mode not in [
            "normal",
            "fun",
            "scary"
        ]:
            return

        state = user_states.get(chat_id)


        # بازی تک‌نفره
        if state == "choosing_single_mode":

            user_states.pop(
                chat_id,
                None
            )

            single_player[chat_id] = {

                "mode": mode,

                "waiting_answer": False

            }

            start_single_game(chat_id)

            return


        # ساخت اتاق
        if state == "choosing_room_mode":

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

        if room.get("phase") != "waiting":

            send_message(
                chat_id,
                "❌ بازی این اتاق شروع شده است."
            )

            return

        old_code, old_room = find_player_room(
            chat_id
        )

        if old_room and old_code != code:

            send_message(
                chat_id,
                "⚠️ شما عضو اتاق دیگری هستید."
            )

            return

        if chat_id not in room["players"]:

            room["players"].append(chat_id)

            # اطلاع به اعضا
            for player in room["players"]:

                if player != chat_id:

                    send_message(
                        player,
                        (
                            f"👤 {get_name(chat_id)} "
                            "به اتاق پیوست."
                        )
                    )

        send_message(
            chat_id,
            (
                f"✅ به اتاق {code} پیوستی.\n"
                "⏳ منتظر شروع بازی باش."
            ),
            get_rooms_menu()
        )

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

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند بازی را شروع کند."
            )

            return

        if len(room["players"]) < 2:

            send_message(
                chat_id,
                "⚠️ حداقل ۲ بازیکن لازم است."
            )

            return

        if room.get("phase") != "waiting":

            send_message(
                chat_id,
                "⚠️ بازی قبلاً شروع شده است."
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

        players = list(
            room["players"]
        )

        del rooms[code]

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

        room = rooms.get(code)

        if not room:
            return

        if room.get("phase") != "choosing_type":

            return

        if room.get("answerer") != chat_id:

            send_message(
                chat_id,
                "⚠️ شما پاسخ‌دهنده این دور نیستید."
            )

            return

        room["question_type"] = choice

        room["phase"] = "waiting_question"

        questioner = room["questioner"]

        if choice == "truth":

            choice_text = "🎯 حقیقت"

        else:

            choice_text = "🔥 جرئت"

        # اطلاع به همه
        for player in room["players"]:

            if player == questioner:

                send_message(
                    player,
                    (
                        f"✅ پاسخ‌دهنده انتخاب کرد: "
                        f"{choice_text}\n\n"
                        "✍️ حالا یک سؤال یا چالش مناسب "
                        "به صورت متن، عکس یا ویس ارسال کن."
                    )
                )

            else:

                send_message(
                    player,
                    (
                        f"✅ انتخاب شد: {choice_text}\n\n"
                        "⏳ منتظر ارسال سؤال یا چالش باش."
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
            error
        )


# =====================================================
# Polling
# =====================================================

def run_polling():

    offset = 0

    print("🤖 Polling started")

    while True:

        try:

            response = requests.get(
                f"{BASE_URL}/getUpdates",
                params={
                    "offset": offset,
                    "timeout": 30
                },
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

        except Exception as error:

            print(
                "❌ Polling Error:",
                error
            )

            time.sleep(5)


# =====================================================
# اجرای اصلی
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
