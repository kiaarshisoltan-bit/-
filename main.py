import os
import random
import threading
import time

import requests
import psycopg2
from flask import Flask, jsonify


# =========================================================
# تنظیمات
# =========================================================

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


# =========================================================
# وب‌سرور برای Render
# =========================================================

@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running! 🤖"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "database": "postgresql"
    })


# =========================================================
# اتصال به PostgreSQL
# =========================================================

def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=10
    )


# =========================================================
# ساخت جدول‌ها
# =========================================================

def init_database():

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        db.commit()

        cursor.close()
        db.close()

    print("✅ PostgreSQL database initialized")


# =========================================================
# مدیریت کاربران
# =========================================================

def user_exists(user_id):

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "SELECT 1 FROM users WHERE user_id = %s",
            (user_id,)
        )

        result = cursor.fetchone()

        cursor.close()
        db.close()

        return result is not None


def save_user(user_id, name):

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            INSERT INTO users (user_id, name, score)
            VALUES (%s, %s, 0)

            ON CONFLICT (user_id)
            DO UPDATE SET name = EXCLUDED.name
        """, (
            user_id,
            name
        ))

        db.commit()

        cursor.close()
        db.close()


def get_name(user_id):

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute(
            "SELECT name FROM users WHERE user_id = %s",
            (user_id,)
        )

        result = cursor.fetchone()

        cursor.close()
        db.close()

    if result:
        return result[0]

    return f"بازیکن {user_id}"


def add_score(user_id, points):

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            UPDATE users
            SET score = score + %s
            WHERE user_id = %s
        """, (
            points,
            user_id
        ))

        db.commit()

        cursor.close()
        db.close()


def get_leaderboard_text():

    with db_lock:

        db = get_db()
        cursor = db.cursor()

        cursor.execute("""
            SELECT name, score
            FROM users
            ORDER BY score DESC, name ASC
            LIMIT 10
        """)

        rows = cursor.fetchall()

        cursor.close()
        db.close()

    if not rows:

        return (
            "🏆 جدول امتیازات\n\n"
            "هنوز امتیازی ثبت نشده است."
        )

    text = "🏆 جدول برترین‌ها 🏆\n\n"

    for index, row in enumerate(rows, start=1):

        name = row[0]
        score = row[1]

        text += (
            f"{index}. {name} — "
            f"{score} امتیاز\n"
        )

    return text


# =========================================================
# اطلاعات موقت بازی
# =========================================================

pending_new_name = set()
user_states = {}
single_player = {}
rooms = {}


# =========================================================
# ارتباط با API بله
# =========================================================

def api_request(method, payload=None, timeout=20):

    url = f"{BASE_URL}/{method}"

    try:

        response = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )

        data = response.json()

        if response.status_code != 200:

            print(
                f"HTTP Error {method}: "
                f"{response.status_code}"
            )

            return None

        if not data.get("ok", False):

            print(
                f"Bale API Error {method}: {data}"
            )

            return None

        return data

    except Exception as error:

        print(
            f"API Error {method}: {error}"
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


def answer_callback_query(callback_id, text=None):

    payload = {
        "callback_query_id": callback_id
    }

    if text:
        payload["text"] = text

    api_request(
        "answerCallbackQuery",
        payload
    )


# =========================================================
# منوی اصلی
# =========================================================

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
            ]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
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
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


# =========================================================
# کد اتاق
# =========================================================

def generate_room_code():

    while True:

        code = str(
            random.randint(1000, 9999)
        )

        if code not in rooms:
            return code


# =========================================================
# انتخاب بازیکنان
# =========================================================

def choose_players(room):

    players = room["players"]

    if len(players) < 2:
        return False

    questioner, answerer = random.sample(
        players,
        2
    )

    room["questioner"] = questioner
    room["answerer"] = answerer

    room["question"] = None
    room["answer"] = None
    room["votes"] = {}

    room["phase"] = "choosing_type"

    return True


# =========================================================
# شروع دور جدید
# =========================================================

def start_new_round(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    if len(room["players"]) < 2:
        return

    room["round"] = room.get("round", 0) + 1

    if not choose_players(room):
        return

    questioner = room["questioner"]
    answerer = room["answerer"]

    text = (
        f"🎮 دور {room['round']}\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                text + "\n\nانتخاب کن:",
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎯 حقیقت",
                                "callback_data":
                                f"truth_{room_code}"
                            },
                            {
                                "text": "🔥 جرئت",
                                "callback_data":
                                f"dare_{room_code}"
                            }
                        ]
                    ]
                }
            )

        else:

            send_message(
                player_id,
                text + "\n\n⏳ منتظر انتخاب..."
            )


# =========================================================
# نمایش سؤال
# =========================================================

def broadcast_question(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    room["phase"] = "waiting_answer"

    text = (
        "📢 سؤال / چالش\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(room['questioner'])}\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(room['answerer'])}\n\n"
        f"📝 {room['question']}"
    )

    for player_id in room["players"]:

        if player_id == room["answerer"]:

            send_message(
                player_id,
                text + "\n\n💬 پاسخ خود را ارسال کن."
            )

        else:

            send_message(
                player_id,
                text + "\n\n⏳ منتظر پاسخ..."
            )


# =========================================================
# رأی‌گیری
# =========================================================

def start_voting(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    room["phase"] = "voting"

    answerer = room["answerer"]

    room["eligible_voters"] = [
        player
        for player in room["players"]
        if player != answerer
    ]

    text = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}\n\n"
        f"💬 {room['answer']}\n\n"
        "🗳️ رأی بده:"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                text + "\n\n⏳ منتظر رأی دیگران..."
            )

        else:

            send_message(
                player_id,
                text,
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "👍 تأیید",
                                "callback_data":
                                f"yes_{room_code}"
                            },
                            {
                                "text": "👎 رد",
                                "callback_data":
                                f"no_{room_code}"
                            }
                        ]
                    ]
                }
            )


def register_vote(room_code, user_id, vote):

    room = rooms.get(room_code)

    if not room:
        return

    if room["phase"] != "voting":
        return

    if user_id not in room["eligible_voters"]:

        send_message(
            user_id,
            "⚠️ شما نمی‌توانید رأی دهید."
        )

        return

    if user_id in room["votes"]:

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

    if (
        len(room["votes"])
        >= len(room["eligible_voters"])
    ):

        finish_voting(room_code)


def finish_voting(room_code):

    room = rooms.get(room_code)

    if not room:
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
            "🌟 ۱۰ امتیاز اضافه شد."
        )

    elif no_votes > yes_votes:

        result = "❌ پاسخ رد شد."

    else:

        result = (
            "⚖️ رأی‌ها مساوی شد."
        )

    text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی شروع می‌شود..."
    )

    room["phase"] = "between_rounds"

    for player_id in room["players"]:

        send_message(
            player_id,
            text
        )

    time.sleep(2)

    start_new_round(room_code)


# =========================================================
# پردازش پیام
# =========================================================

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

    # ثبت نام کاربر جدید

    if not user_exists(chat_id):

        if text == "/start":

            send_message(
                chat_id,
                "👋 سلام!\n\n✏️ نام مستعار خود را ارسال کن:"
            )

            user_states[chat_id] = "register"

            return

        if user_states.get(chat_id) == "register":

            if not text:
                return

            save_user(chat_id, text)

            user_states.pop(chat_id, None)

            send_message(
                chat_id,
                f"🎉 خوش آمدی {text}!",
                get_main_menu()
            )

            return

        send_message(
            chat_id,
            "برای شروع /start را ارسال کن."
        )

        return

    # تغییر نام

    if user_states.get(chat_id) == "change_name":

        if text:

            save_user(chat_id, text)

            user_states.pop(chat_id, None)

            send_message(
                chat_id,
                "✅ نام شما تغییر کرد.",
                get_main_menu()
            )

        return

    # شروع

    if text == "/start":

        send_message(
            chat_id,
            f"👋 سلام {get_name(chat_id)}!",
            get_main_menu()
        )

        return

    # منوی اصلی

    if text == "🏠 منوی اصلی":

        send_message(
            chat_id,
            "🏠 منوی اصلی",
            get_main_menu()
        )

        return

    # تغییر نام

    if text == "✏️ تغییر نام":

        user_states[chat_id] = "change_name"

        send_message(
            chat_id,
            "✏️ نام جدید خود را ارسال کن:"
        )

        return

    # جدول امتیازات

    if text == "🏆 جدول امتیازات":

        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu()
        )

        return

    # اتاق آنلاین

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 بخش اتاق‌های آنلاین",
            get_rooms_menu()
        )

        return

    # ساخت اتاق

    if text == "🛠️ ساخت اتاق جدید":

        code = generate_room_code()

        rooms[code] = {
            "host": chat_id,
            "players": [chat_id],
            "phase": "waiting",
            "round": 0
        }

        send_message(
            chat_id,
            f"✅ اتاق ساخته شد!\n\n🔢 کد اتاق: {code}",
            get_rooms_menu()
        )

        send_message(
            chat_id,
            "بعد از ورود بازیکنان بازی را شروع کن:",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 شروع بازی",
                            "callback_data":
                            f"start_{code}"
                        }
                    ]
                ]
            }
        )

        return

    # لیست اتاق‌ها

    if text == "🚪 پیوستن به اتاق":

        keyboard = []

        for code, room in rooms.items():

            if room.get("phase") == "waiting":

                keyboard.append([
                    {
                        "text":
                        f"🚪 اتاق {code}"
                    }
                ])

        if not keyboard:

            send_message(
                chat_id,
                "❌ اتاق فعالی وجود ندارد.",
                get_rooms_menu()
            )

            return

        keyboard.append([
            {"text": "🏠 منوی اصلی"}
        ])

        send_message(
            chat_id,
            "یک اتاق انتخاب کن:",
            {
                "keyboard": keyboard,
                "resize_keyboard": True
            }
        )

        return

    # ورود به اتاق

    if text.startswith("🚪 اتاق "):

        parts = text.split()

        if len(parts) >= 3:

            code = parts[2]

            room = rooms.get(code)

            if room and room.get("phase") == "waiting":

                if chat_id not in room["players"]:

                    room["players"].append(chat_id)

                    for player in room["players"]:

                        send_message(
                            player,
                            (
                                f"👤 {get_name(chat_id)} "
                                "وارد اتاق شد."
                            )
                        )

                return

    # ارسال سؤال

    for code, room in rooms.items():

        if (
            room.get("phase")
            == "waiting_question"
            and room.get("questioner") == chat_id
        ):

            room["question"] = text

            broadcast_question(code)

            return

    # ارسال پاسخ

    for code, room in rooms.items():

        if (
            room.get("phase")
            == "waiting_answer"
            and room.get("answerer") == chat_id
        ):

            room["answer"] = text

            start_voting(code)

            return

    send_message(
        chat_id,
        "از منوی پایین استفاده کن 👇",
        get_main_menu()
    )


# =========================================================
# پردازش دکمه‌ها
# =========================================================

def handle_callback(query):

    callback_id = query.get("id")

    chat_id = (
        query.get("message", {})
        .get("chat", {})
        .get("id")
    )

    data = query.get("data", "")

    answer_callback_query(callback_id)

    if not chat_id:
        return

    # شروع اتاق

    if data.startswith("start_"):

        code = data.replace(
            "start_",
            "",
            1
        )

        room = rooms.get(code)

        if not room:
            return

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند شروع کند."
            )

            return

        if len(room["players"]) < 2:

            send_message(
                chat_id,
                "⚠️ حداقل ۲ بازیکن لازم است."
            )

            return

        start_new_round(code)

        return

    # حقیقت

    if data.startswith("truth_"):

        code = data.replace(
            "truth_",
            "",
            1
        )

        room = rooms.get(code)

        if (
            room
            and room["answerer"] == chat_id
        ):

            room["question_type"] = "truth"

            room["phase"] = "waiting_question"

            send_message(
                room["questioner"],
                (
                    "🎯 پاسخ‌دهنده حقیقت را انتخاب کرد.\n\n"
                    "✍️ حالا سؤال خود را ارسال کن."
                )
            )

        return

    # جرئت

    if data.startswith("dare_"):

        code = data.replace(
            "dare_",
            "",
            1
        )

        room = rooms.get(code)

        if (
            room
            and room["answerer"] == chat_id
        ):

            room["question_type"] = "dare"

            room["phase"] = "waiting_question"

            send_message(
                room["questioner"],
                (
                    "🔥 پاسخ‌دهنده جرئت را انتخاب کرد.\n\n"
                    "✍️ حالا چالش خود را ارسال کن."
                )
            )

        return

    # رأی مثبت

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

    # رأی منفی

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


# =========================================================
# پردازش آپدیت
# =========================================================

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
            f"Update Error: {error}"
        )


# =========================================================
# Long Polling
# =========================================================

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

                time.sleep(3)

                continue

            for update in data.get("result", []):

                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                threading.Thread(
                    target=handle_update,
                    args=(update,),
                    daemon=True
                ).start()

        except Exception as error:

            print(
                f"Polling Error: {error}"
            )

            time.sleep(5)


# =========================================================
# اجرای برنامه
# =========================================================

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
