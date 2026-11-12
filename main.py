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

VOTE_TIMEOUT = 60

MAX_ROOM_PLAYERS = 20

app = Flask(__name__)


# =====================================================
# Lock ها
# =====================================================

db_lock = threading.Lock()

state_lock = threading.RLock()

room_lock = threading.RLock()


# =====================================================
# اطلاعات موقت
# =====================================================

user_states = {}

single_player = {}

rooms = {}


# =====================================================
# وب سرور برای Render
# =====================================================

@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running!"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "rooms": len(rooms)
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

        try:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    name TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            db.commit()

            try:

                cur.execute("""
                    CREATE UNIQUE INDEX IF NOT EXISTS
                    users_unique_name_ci
                    ON users (
                        LOWER(BTRIM(name))
                    )
                """)

                db.commit()

            except Exception as error:

                db.rollback()

                print(
                    "⚠️ Unique name index warning:",
                    error
                )

        finally:

            cur.close()
            db.close()

    print("✅ PostgreSQL database initialized")


# =====================================================
# ابزارهای کاربران
# =====================================================

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

            result = cur.fetchone()

        finally:

            cur.close()
            db.close()

    return result is not None


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

                cur.execute(
                    """
                    SELECT 1
                    FROM users
                    WHERE LOWER(BTRIM(name)) =
                          LOWER(BTRIM(%s))
                    LIMIT 1
                    """,
                    (name,)
                )

            else:

                cur.execute(
                    """
                    SELECT 1
                    FROM users
                    WHERE LOWER(BTRIM(name)) =
                          LOWER(BTRIM(%s))
                    AND user_id <> %s
                    LIMIT 1
                    """,
                    (
                        name,
                        exclude_user_id
                    )
                )

            result = cur.fetchone()

        finally:

            cur.close()
            db.close()

    return result is not None


def save_user(user_id, name):

    name = normalize_name(name)

    if not name:
        return False

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                INSERT INTO users (
                    user_id,
                    name,
                    score
                )
                VALUES (
                    %s,
                    %s,
                    0
                )

                ON CONFLICT (user_id)
                DO UPDATE SET
                    name = EXCLUDED.name
            """, (
                user_id,
                name
            ))

            db.commit()

            return True

        except psycopg2.IntegrityError:

            db.rollback()

            return False

        except Exception as error:

            db.rollback()

            print(
                "❌ Database save error:",
                error
            )

            return False

        finally:

            cur.close()
            db.close()


def get_name(user_id):

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute(
                """
                SELECT name
                FROM users
                WHERE user_id = %s
                """,
                (user_id,)
            )

            result = cur.fetchone()

        finally:

            cur.close()
            db.close()

    if result:
        return result[0]

    return "بازیکن"


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


def get_leaderboard_text():

    with db_lock:

        db = get_db()
        cur = db.cursor()

        try:

            cur.execute("""
                SELECT
                    name,
                    score
                FROM users
                ORDER BY
                    score DESC,
                    name ASC
                LIMIT 10
            """)

            rows = cur.fetchall()

        finally:

            cur.close()
            db.close()

    if not rows:

        return (
            "🏆 هنوز بازیکنی در جدول "
            "امتیازات وجود ندارد."
        )

    text = (
        "🏆 جدول برترین بازیکنان\n\n"
    )

    medals = [
        "🥇",
        "🥈",
        "🥉"
    ]

    for index, row in enumerate(rows, 1):

        if index <= 3:
            icon = medals[index - 1]
        else:
            icon = f"{index}."

        text += (
            f"{icon} {row[0]}\n"
            f"⭐ {row[1]} امتیاز\n\n"
        )

    return text


# =====================================================
# ارتباط با API بله
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
            f"❌ Request Error [{method}]:",
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
# تشخیص رسانه
# =====================================================

def get_media_from_message(message):

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
                        ).strip()
                    )
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
                        ).strip()
                    )
                }

        except Exception:
            pass

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

    caption = media.get(
        "caption",
        ""
    )

    if not file_id:
        return

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

        send_voice(
            chat_id,
            file_id,
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
                    "text": "👻 مرموز و معمایی",
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
# بانک سؤال‌ها
# =====================================================

PROMPTS = {

    "normal": {

        "truth": [

            "آخرین باری که از ته دل خندیدی چه زمانی بود؟",

            "اگر می‌توانستی یک مهارت جدید یاد بگیری، چه بود؟",

            "بهترین خاطره مدرسه‌ات چیست؟",

            "چه چیزی خیلی زود خوشحالت می‌کند؟",

            "اگر یک روز قدرت نامرئی شدن داشتی، چه کار جالبی انجام می‌دادی؟",

            "کدام شخصیت کارتونی را بیشتر دوست داری؟"

        ],

        "dare": [

            "یک داستان خنده‌دار سه‌خطی بنویس.",

            "نام پنج میوه را بنویس.",

            "یک معمای ساده بساز.",

            "یک شعر کوتاه و بامزه بنویس.",

            "یک جمله با پنج کلمه بنویس."

        ]
    },


    "fun": {

        "truth": [

            "عجیب‌ترین غذایی که امتحان کرده‌ای چه بوده؟",

            "اگر مدیر مدرسه بودی چه قانونی می‌گذاشتی؟",

            "اگر یک قدرت خیالی داشتی، چه بود؟",

            "خنده‌دارترین اتفاقی که در یک بازی برایت افتاده چیست؟"

        ],

        "dare": [

            "یک جمله خنده‌دار با سه ایموجی بساز.",

            "یک لطیفه کوتاه و مناسب تعریف کن.",

            "یک تبلیغ بامزه برای یک مداد بنویس.",

            "یک داستان کوتاه و خنده‌دار بساز."

        ]
    },


    "scary": {

        "truth": [

            "کدام صدا در شب بیشتر غافلگیرت می‌کند؟",

            "اگر در یک داستان معمایی بودی، چه نقشی انتخاب می‌کردی؟",

            "بهترین داستان معمایی که شنیده‌ای چه بوده؟"

        ],

        "dare": [

            "یک داستان مرموز سه‌خطی بنویس.",

            "یک اسم جالب برای یک خانه خیالی انتخاب کن.",

            "یک معمای مرموز طراحی کن."

        ]
    }

}


def get_random_prompt(
    mode,
    question_type
):

    mode_data = PROMPTS.get(
        mode,
        PROMPTS["normal"]
    )

    prompts = mode_data.get(
        question_type,
        []
    )

    if not prompts:
        return "یک سؤال یا چالش مناسب انجام بده."

    return random.choice(prompts)


def mode_name(mode):

    names = {

        "normal":
            "معمولی و دوستانه",

        "fun":
            "خفن و چالشی",

        "scary":
            "مرموز و معمایی"

    }

    return names.get(
        mode,
        "معمولی"
    )


# =====================================================
# بازی تک نفره
# =====================================================

def start_single_game(chat_id):

    with state_lock:

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
            "چالش را انجام بده و پاسخ یا نتیجه را ارسال کن."
        )


    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎮 حالت: {mode_name(game['mode'])}\n\n"
            f"{title}\n\n"
            f"📝 {prompt}\n\n"
            f"✍️ {instruction}\n\n"
            "ℹ️ این بخش صرفاً برای سرگرمی است "
            "و امتیازی ندارد."
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
# ابزارهای اتاق
# =====================================================

def generate_room_code():

    with room_lock:

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

    with room_lock:

        for code, room in rooms.items():

            if user_id in room.get(
                "players",
                []
            ):

                return code, room

    return None, None


def reset_round_data(room):

    room["questioner"] = None
    room["answerer"] = None

    room["question_type"] = None

    room["question"] = None

    room["answer"] = None

    room["votes"] = {}

    room["eligible_voters"] = []

    room["vote_finished"] = False

    room["vote_end_time"] = None


def create_room(
    chat_id,
    mode
):

    with room_lock:

        old_code, old_room = find_player_room(
            chat_id
        )

        if old_room:

            already_in_room = True

        else:

            already_in_room = False

            code = generate_room_code()

            if not code:

                code = None

            else:

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

                    "eligible_voters": [],

                    "vote_finished": False,

                    "vote_end_time": None

                }


    if already_in_room:

        send_message(
            chat_id,
            "⚠️ شما در حال حاضر عضو یک اتاق هستید."
        )

        return


    if not code:

        send_message(
            chat_id,
            "❌ ساخت اتاق انجام نشد. دوباره تلاش کن."
        )

        return


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
                        "callback_data": f"start_room_{code}"
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

    with room_lock:

        room_list = []

        for code, room in rooms.items():

            if room.get("phase") == "waiting":

                room_list.append(
                    (
                        code,
                        len(room.get("players", [])),
                        room.get("mode")
                    )
                )


    if not room_list:

        send_message(
            chat_id,
            "❌ در حال حاضر اتاقی برای پیوستن وجود ندارد."
        )

        return


    keyboard = []

    for code, count, mode in room_list:

        keyboard.append([

            {
                "text": (
                    f"🚪 اتاق {code} | "
                    f"{count} نفر | "
                    f"{mode_name(mode)}"
                ),

                "callback_data":
                    f"join_room_{code}"
            }

        ])


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


def leave_room(chat_id):

    with room_lock:

        code, room = find_player_room(
            chat_id
        )

        if not room:

            found = False

        else:

            found = True

            players = room.get(
                "players",
                []
            )

            if chat_id in players:

                players.remove(chat_id)

            # اگر میزبان خارج شد
            if room.get("host") == chat_id:

                if players:

                    room["host"] = players[0]

                    new_host = room["host"]

                else:

                    new_host = None

            else:

                new_host = room.get("host")


            # اگر تعداد افراد کمتر از 2 شد
            if len(players) < 2:

                if room.get("phase") != "waiting":

                    room["phase"] = "waiting"

                    reset_round_data(room)


            remaining_players = list(players)

            # حذف کامل اتاق
            if not remaining_players:

                del rooms[code]


    if not found:

        send_message(
            chat_id,
            "⚠️ شما در هیچ اتاقی حضور ندارید."
        )

        return


    send_message(
        chat_id,
        "🚪 شما از اتاق خارج شدید.",
        get_main_menu()
    )


    for player in remaining_players:

        send_message(
            player,
            (
                f"👋 {get_name(chat_id)} "
                "از اتاق خارج شد."
            )
        )


    if new_host and new_host != chat_id:

        send_message(
            new_host,
            "👑 شما میزبان جدید اتاق هستید."
        )


    if remaining_players and len(remaining_players) < 2:

        for player in remaining_players:

            send_message(
                player,
                (
                    "⚠️ تعداد بازیکنان برای ادامه بازی "
                    "کافی نیست.\n"
                    "بازی متوقف شد."
                )
            )


# =====================================================
# شروع دور آنلاین
# =====================================================

def start_online_round(code):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        players = list(
            room.get("players", [])
        )

        if len(players) < 2:

            room["phase"] = "waiting"

            reset_round_data(room)

            return


        # جلوگیری از شروع دور در وضعیت نامعتبر
        if room.get("phase") not in [
            "waiting",
            "between_rounds"
        ]:

            return


        room["round"] += 1

        questioner, answerer = random.sample(
            players,
            2
        )

        reset_round_data(room)

        room["questioner"] = questioner
        room["answerer"] = answerer

        room["phase"] = "choosing_type"

        round_number = room["round"]


    message = (
        f"🎮 دور {round_number}\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
    )


    for player in players:

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
                                "callback_data": f"truth_{code}"
                            },

                            {
                                "text": "🔥 جرئت",
                                "callback_data": f"dare_{code}"
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
                    "\n\n⏳ منتظر انتخاب پاسخ‌دهنده باش."
                )
            )


# =====================================================
# ارسال سؤال آنلاین
# =====================================================

def send_online_question(code):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if room.get("phase") != "waiting_question":
            return

        question = room.get("question")

        if question is None:
            return

        room["phase"] = "waiting_answer"

        players = list(
            room.get("players", [])
        )

        questioner = room.get("questioner")

        answerer = room.get("answerer")


    header = (
        "📢 سؤال یا چالش جدید\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
    )


    for player in players:

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


        if player == answerer:

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

    with room_lock:

        room = rooms.get(code)

        if not room:
            return

        if room.get("phase") != "waiting_answer":
            return

        answer = room.get("answer")

        if answer is None:
            return


        answerer = room.get("answerer")

        players = list(
            room.get("players", [])
        )


        eligible_voters = [

            player

            for player in players

            if player != answerer

        ]


        room["eligible_voters"] = eligible_voters

        room["votes"] = {}

        room["vote_finished"] = False

        room["vote_end_time"] = (
            time.time() + VOTE_TIMEOUT
        )

        room["phase"] = "voting"


    header = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
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
                (
                    f"⏳ رأی‌گیری آغاز شد.\n"
                    f"زمان رأی‌گیری: {VOTE_TIMEOUT} ثانیه"
                )
            )

        else:

            send_message(
                player,
                (
                    "🗳️ آیا پاسخ مورد قبول است؟\n\n"
                    f"⏱️ {VOTE_TIMEOUT} ثانیه فرصت داری."
                ),
                vote_keyboard
            )


    # پایان خودکار رأی‌گیری
    def vote_timer():

        time.sleep(VOTE_TIMEOUT)

        finish_online_voting(
            code,
            force=True
        )


    threading.Thread(
        target=vote_timer,
        daemon=True
    ).start()


# =====================================================
# ثبت رأی
# =====================================================

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

        elif room.get("phase") != "voting":

            status = "not_voting"

        elif room.get("vote_finished"):

            status = "finished"

        elif user_id not in room.get(
            "players",
            []
        ):

            status = "not_member"

        elif user_id == room.get("answerer"):

            status = "answerer"

        elif user_id not in room.get(
            "eligible_voters",
            []
        ):

            status = "not_eligible"

        elif user_id in room.get(
            "votes",
            {}
        ):

            status = "already_voted"

        else:

            room["votes"][user_id] = vote

            status = "success"

            if len(room["votes"]) >= len(
                room["eligible_voters"]
            ):

                should_finish = True


    # =================================================
    # پاسخ وضعیت
    # =================================================

    if status == "no_room":

        send_message(
            user_id,
            "❌ این اتاق دیگر وجود ندارد."
        )

        return


    if status == "not_voting":

        send_message(
            user_id,
            "⚠️ رأی‌گیری فعالی وجود ندارد."
        )

        return


    if status == "finished":

        send_message(
            user_id,
            "⚠️ رأی‌گیری تمام شده است."
        )

        return


    if status == "not_member":

        send_message(
            user_id,
            "⚠️ شما عضو این اتاق نیستید."
        )

        return


    if status == "answerer":

        send_message(
            user_id,
            "⚠️ پاسخ‌دهنده نمی‌تواند به پاسخ خودش رأی بدهد."
        )

        return


    if status == "not_eligible":

        send_message(
            user_id,
            "⚠️ شما اجازه رأی دادن ندارید."
        )

        return


    if status == "already_voted":

        send_message(
            user_id,
            "⚠️ شما قبلاً رأی داده‌اید."
        )

        return


    if status == "success":

        send_message(
            user_id,
            "✅ رأی شما با موفقیت ثبت شد."
        )


    if should_finish:

        finish_online_voting(
            code,
            force=False
        )


# =====================================================
# پایان رأی‌گیری
# =====================================================

def finish_online_voting(
    code,
    force=False
):

    with room_lock:

        room = rooms.get(code)

        if not room:
            return


        if room.get("phase") != "voting":
            return


        if room.get("vote_finished"):
            return


        # اگر اجباری نیست و هنوز همه رأی نداده‌اند
        if not force:

            if len(room["votes"]) < len(
                room["eligible_voters"]
            ):
                return


        # جلوگیری از اجرای دوباره
        room["vote_finished"] = True

        room["phase"] = "between_rounds"


        votes = dict(
            room.get("votes", {})
        )

        players = list(
            room.get("players", [])
        )

        answerer = room.get("answerer")


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


    # =================================================
    # نتیجه
    # =================================================

    if yes_votes > no_votes:

        add_score(
            answerer,
            10
        )

        result = (
            "✅ پاسخ توسط اکثریت تأیید شد!\n"
            "🌟 ۱۰ امتیاز به پاسخ‌دهنده اضافه شد."
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


    # اگر کسی رأی نداده باشد
    if yes_votes == 0 and no_votes == 0:

        result = (
            "⏰ زمان رأی‌گیری تمام شد.\n"
            "هیچ رأیی ثبت نشد و امتیازی داده نشد."
        )


    message = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 رأی تأیید: {yes_votes}\n"
        f"👎 رأی رد: {no_votes}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی در حال آماده شدن است..."
    )


    for player in players:

        send_message(
            player,
            message
        )


    # =================================================
    # شروع دور بعدی
    # =================================================

    def next_round():

        time.sleep(3)

        with room_lock:

            room = rooms.get(code)

            if not room:
                return

            if len(
                room.get("players", [])
            ) < 2:

                room["phase"] = "waiting"

                reset_round_data(room)

                return

        start_online_round(code)


    threading.Thread(
        target=next_round,
        daemon=True
    ).start()


# =====================================================
# دریافت پیام کاربران
# =====================================================

def handle_message(message):

    chat = message.get(
        "chat",
        {}
    )

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
    # ثبت نام کاربر جدید
    # =================================================

    if not user_exists(chat_id):

        if text == "/start":

            send_message(
                chat_id,
                (
                    "👋 سلام!\n\n"
                    "برای شروع، یک نام مستعار انتخاب "
                    "و به صورت متن ارسال کن.\n\n"
                    "⚠️ نام انتخابی نباید تکراری باشد."
                )
            )

            return


        if not text:

            send_message(
                chat_id,
                (
                    "👋 لطفاً برای شروع یک نام مستعار "
                    "به صورت متن ارسال کن."
                )
            )

            return


        new_name = normalize_name(
            text[:40]
        )


        if len(new_name) < 2:

            send_message(
                chat_id,
                "⚠️ نام باید حداقل ۲ کاراکتر داشته باشد."
            )

            return


        if name_exists(new_name):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط کاربر دیگری "
                    "انتخاب شده است.\n\n"
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
                    "❌ این نام قبلاً توسط کاربر دیگری "
                    "انتخاب شده است."
                )
            )

            return


        send_message(
            chat_id,
            (
                f"🎉 خوش آمدی {new_name}!\n\n"
                "حساب کاربری تو با موفقیت ساخته شد."
            ),
            get_main_menu()
        )

        return


    # =================================================
    # شروع
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
    # تغییر نام
    # =================================================

    with state_lock:

        current_state = user_states.get(chat_id)


    if current_state == "change_name":

        if text == "🏠 منوی اصلی":

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


        if not text:

            send_message(
                chat_id,
                "⚠️ لطفاً نام جدید را به صورت متن ارسال کن."
            )

            return


        new_name = normalize_name(
            text[:40]
        )


        if len(new_name) < 2:

            send_message(
                chat_id,
                "⚠️ نام باید حداقل ۲ کاراکتر داشته باشد."
            )

            return


        if name_exists(
            new_name,
            exclude_user_id=chat_id
        ):

            send_message(
                chat_id,
                (
                    "❌ این نام قبلاً توسط کاربر دیگری "
                    "انتخاب شده است."
                )
            )

            return


        if not save_user(
            chat_id,
            new_name
        ):

            send_message(
                chat_id,
                "❌ تغییر نام انجام نشد. دوباره تلاش کن."
            )

            return


        with state_lock:

            user_states.pop(
                chat_id,
                None
            )


        send_message(
            chat_id,
            (
                "✅ نام شما با موفقیت تغییر کرد.\n\n"
                f"نام جدید: {new_name}"
            ),
            get_main_menu()
        )

        return


    # =================================================
    # پاسخ بازی تک نفره
    # =================================================

    with state_lock:

        single_game = single_player.get(
            chat_id
        )

        waiting_single = bool(
            single_game
            and single_game.get(
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


        if text or media:

            finish_single_game(chat_id)

            return


    # =================================================
    # سؤال جدید تک نفره
    # =================================================

    if text == "⏭️ سؤال جدید":

        with state_lock:

            exists = chat_id in single_player

        if exists:

            start_single_game(chat_id)

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
    # بازی تک نفره
    # =================================================

    if text == "🤖 بازی تک‌نفره":

        with state_lock:

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

        code, room = find_player_room(
            chat_id
        )

        if room:

            send_message(
                chat_id,
                (
                    f"⚠️ شما در حال حاضر عضو اتاق "
                    f"{code} هستید."
                )
            )

            return


        with state_lock:

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

        code, room = find_player_room(
            chat_id
        )

        if room:

            send_message(
                chat_id,
                (
                    f"⚠️ شما عضو اتاق {code} هستید.\n"
                    "برای ورود به اتاق دیگر ابتدا خارج شو."
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

            user_states[chat_id] = "change_name"


        send_message(
            chat_id,
            (
                "✏️ نام جدید خود را ارسال کن.\n\n"
                "⚠️ نام نباید قبلاً توسط کاربر دیگری "
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

                "🤖 بازی تک‌نفره\n"
                "سؤال یا چالش دریافت کن و پاسخ بده.\n"
                "این بخش امتیازی ندارد.\n\n"

                "🎮 بازی آنلاین\n"
                "یک اتاق بساز یا وارد اتاق دیگران شو.\n\n"

                "🎯 پاسخ‌دهنده حقیقت یا جرئت انتخاب می‌کند.\n\n"

                "✍️ پرسش‌کننده سؤال یا چالش را "
                "به صورت متن، عکس یا ویس ارسال می‌کند.\n\n"

                "💬 پاسخ‌دهنده نیز می‌تواند متن، "
                "عکس یا ویس ارسال کند.\n\n"

                "🗳️ سایر بازیکنان یک‌بار رأی می‌دهند.\n\n"

                f"⏱️ رأی‌گیری {VOTE_TIMEOUT} ثانیه زمان دارد.\n\n"

                "🏆 اگر رأی تأیید بیشتر باشد، "
                "۱۰ امتیاز به پاسخ‌دهنده داده می‌شود."
            ),
            get_main_menu()
        )

        return


    # =================================================
    # دریافت سؤال آنلاین
    # =================================================

    with room_lock:

        question_room_code = None

        for code, room in rooms.items():

            if (
                room.get("phase") == "waiting_question"
                and room.get("questioner") == chat_id
            ):

                question_room_code = code

                break


    if question_room_code:

        if media:

            with room_lock:

                room = rooms.get(question_room_code)

                if (
                    room
                    and room.get("phase") == "waiting_question"
                    and room.get("questioner") == chat_id
                ):

                    room["question"] = media


            send_online_question(
                question_room_code
            )

            return


        if text:

            with room_lock:

                room = rooms.get(question_room_code)

                if (
                    room
                    and room.get("phase") == "waiting_question"
                    and room.get("questioner") == chat_id
                ):

                    room["question"] = text[:2000]


            send_online_question(
                question_room_code
            )

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

    with room_lock:

        answer_room_code = None

        for code, room in rooms.items():

            if (
                room.get("phase") == "waiting_answer"
                and room.get("answerer") == chat_id
            ):

                answer_room_code = code

                break


    if answer_room_code:

        if media:

            with room_lock:

                room = rooms.get(answer_room_code)

                if (
                    room
                    and room.get("phase") == "waiting_answer"
                    and room.get("answerer") == chat_id
                ):

                    room["answer"] = media


            start_online_voting(
                answer_room_code
            )

            return


        if text:

            with room_lock:

                room = rooms.get(answer_room_code)

                if (
                    room
                    and room.get("phase") == "waiting_answer"
                    and room.get("answerer") == chat_id
                ):

                    room["answer"] = text[:2000]


            start_online_voting(
                answer_room_code
            )

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


        if mode not in [
            "normal",
            "fun",
            "scary"
        ]:

            return


        with state_lock:

            state = user_states.get(
                chat_id
            )


        # بازی تک نفره
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


            start_single_game(chat_id)

            return


        # ساخت اتاق
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

    if data.startswith("join_room_"):

        code = data.replace(
            "join_room_",
            "",
            1
        )


        with room_lock:

            room = rooms.get(code)


            if not room:

                status = "not_found"


            elif room.get("phase") != "waiting":

                status = "started"


            elif len(
                room.get("players", [])
            ) >= MAX_ROOM_PLAYERS:

                status = "full"


            else:

                old_code, old_room = find_player_room(
                    chat_id
                )


                if old_room and old_code != code:

                    status = "other_room"


                else:

                    status = "join"


                    if chat_id not in room["players"]:

                        room["players"].append(
                            chat_id
                        )

                        joined = True

                    else:

                        joined = False


                    players = list(
                        room["players"]
                    )


        if status == "not_found":

            send_message(
                chat_id,
                "❌ این اتاق دیگر وجود ندارد."
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
                "❌ ظرفیت این اتاق تکمیل شده است."
            )

            return


        if status == "other_room":

            send_message(
                chat_id,
                (
                    "⚠️ شما عضو اتاق دیگری هستید.\n"
                    "ابتدا از آن خارج شو."
                )
            )

            return


        if joined:

            for player in players:

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
                "⏳ منتظر شروع بازی توسط میزبان باش."
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


        with room_lock:

            room = rooms.get(code)


            if not room:

                status = "not_found"


            elif room.get("host") != chat_id:

                status = "not_host"


            elif len(
                room.get("players", [])
            ) < 2:

                status = "not_enough"


            elif room.get("phase") != "waiting":

                status = "already_started"


            else:

                status = "success"


        if status == "not_found":

            send_message(
                chat_id,
                "❌ این اتاق وجود ندارد."
            )

            return


        if status == "not_host":

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند بازی را شروع کند."
            )

            return


        if status == "not_enough":

            send_message(
                chat_id,
                "⚠️ برای شروع بازی حداقل ۲ بازیکن لازم است."
            )

            return


        if status == "already_started":

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


        with room_lock:

            room = rooms.get(code)


            if not room:

                status = "not_found"

                players = []


            elif room.get("host") != chat_id:

                status = "not_host"

                players = []


            else:

                status = "success"

                players = list(
                    room.get("players", [])
                )

                del rooms[code]


        if status == "not_found":

            send_message(
                chat_id,
                "❌ این اتاق وجود ندارد."
            )

            return


        if status == "not_host":

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند اتاق را حذف کند."
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

        try:

            choice, code = data.split(
                "_",
                1
            )

        except ValueError:

            return


        with room_lock:

            room = rooms.get(code)


            if not room:

                status = "not_found"


            elif room.get("phase") != "choosing_type":

                status = "wrong_phase"


            elif room.get("answerer") != chat_id:

                status = "not_answerer"


            else:

                status = "success"

                room["question_type"] = choice

                room["phase"] = "waiting_question"

                questioner = room["questioner"]

                players = list(
                    room["players"]
                )


        if status == "not_found":

            send_message(
                chat_id,
                "❌ این اتاق وجود ندارد."
            )

            return


        if status == "wrong_phase":

            send_message(
                chat_id,
                "⚠️ انتخاب این دور قبلاً انجام شده است."
            )

            return


        if status == "not_answerer":

            send_message(
                chat_id,
                "⚠️ فقط پاسخ‌دهنده می‌تواند انتخاب کند."
            )

            return


        if choice == "truth":

            choice_text = "🎯 حقیقت"

        else:

            choice_text = "🔥 جرئت"


        for player in players:

            if player == questioner:

                send_message(
                    player,
                    (
                        f"✅ پاسخ‌دهنده انتخاب کرد: "
                        f"{choice_text}\n\n"
                        "✍️ حالا سؤال یا چالش مناسب را "
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
# پردازش Update
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


        except requests.exceptions.Timeout:

            continue


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
