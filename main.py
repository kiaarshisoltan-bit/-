import os
import random
import threading
import time
import sqlite3

import requests
from flask import Flask, jsonify


# =========================================================
# تنظیمات
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

# مسیر دیتابیس:
# روی Render با Persistent Disk می‌توان این مقدار را
# در Environment Variable به /var/data/bot.db تغییر داد.
DATABASE_PATH = os.getenv(
    "DATABASE_PATH",
    "bot.db"
)

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN تنظیم نشده است."
    )

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"


# =========================================================
# Flask برای Render
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running! 🤖"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok"
    })


# =========================================================
# قفل دیتابیس
# =========================================================

db_lock = threading.Lock()


# =========================================================
# اتصال به SQLite
# =========================================================

def get_db():

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=30
    )

    connection.row_factory = sqlite3.Row

    return connection


# =========================================================
# ساخت جدول‌ها
# =========================================================

def init_database():

    with db_lock:

        db = get_db()

        cursor = db.cursor()

        # اطلاعات کاربران
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                score INTEGER DEFAULT 0
            )
        """)

        db.commit()
        db.close()

    print("✅ Database initialized")


# =========================================================
# کاربران
# =========================================================

def user_exists(user_id):

    with db_lock:

        db = get_db()

        cursor = db.cursor()

        cursor.execute(
            "SELECT user_id FROM users WHERE user_id = ?",
            (user_id,)
        )

        result = cursor.fetchone()

        db.close()

        return result is not None


def save_user(user_id, name):

    with db_lock:

        db = get_db()

        cursor = db.cursor()

        cursor.execute("""
            INSERT INTO users (user_id, name, score)
            VALUES (?, ?, 0)

            ON CONFLICT(user_id)
            DO UPDATE SET name = excluded.name
        """, (
            user_id,
            name
        ))

        db.commit()
        db.close()


def get_name(user_id):

    with db_lock:

        db = get_db()

        cursor = db.cursor()

        cursor.execute(
            "SELECT name FROM users WHERE user_id = ?",
            (user_id,)
        )

        result = cursor.fetchone()

        db.close()

    if result:
        return result["name"]

    return f"بازیکن {user_id}"


def add_score(user_id, points):

    with db_lock:

        db = get_db()

        cursor = db.cursor()

        cursor.execute("""
            UPDATE users
            SET score = score + ?
            WHERE user_id = ?
        """, (
            points,
            user_id
        ))

        db.commit()
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

        db.close()

    if not rows:

        return (
            "🏆 جدول امتیازات\n\n"
            "هنوز امتیازی ثبت نشده است."
        )

    text = "🏆 جدول برترین‌ها 🏆\n\n"

    for index, row in enumerate(
        rows,
        start=1
    ):

        text += (
            f"{index}. "
            f"{row['name']} — "
            f"{row['score']} امتیاز\n"
        )

    return text


# =========================================================
# اطلاعات موقت بازی
# این موارد بعد از Restart پاک می‌شوند،
# اما نام و امتیازها باقی می‌مانند.
# =========================================================

pending_name = set()
pending_new_name = set()

user_states = {}
single_player = {}

rooms = {}


# =========================================================
# درخواست به API بله
# =========================================================

def api_request(method, payload=None, timeout=20):

    url = f"{BASE_URL}/{method}"

    try:

        response = requests.post(
            url,
            json=payload or {},
            timeout=timeout
        )

        try:
            data = response.json()
        except Exception:

            print(
                f"Invalid JSON [{method}]: "
                f"{response.text}"
            )

            return None

        if response.status_code != 200:

            print(
                f"HTTP Error [{method}]: "
                f"{response.status_code}"
            )

            return None

        if not data.get("ok", False):

            print(
                f"Bale API Error [{method}]: {data}"
            )

            return None

        return data

    except requests.RequestException as error:

        print(
            f"Request Error [{method}]: {error}"
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


def answer_callback_query(callback_query_id, text=None):

    if not callback_query_id:
        return

    payload = {
        "callback_query_id": callback_query_id
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
                {
                    "text": "🎮 اتاق‌های آنلاین"
                },
                {
                    "text": "🤖 بازی تک‌نفره"
                }
            ],
            [
                {
                    "text": "🏆 جدول امتیازات"
                },
                {
                    "text": "✏️ تغییر نام"
                }
            ],
            [
                {
                    "text": "📢 کانال اطلاع‌رسانی"
                },
                {
                    "text": "💬 پشتیبانی"
                }
            ]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


def get_online_rooms_menu():

    return {
        "keyboard": [
            [
                {
                    "text": "🛠️ ساخت اتاق جدید"
                },
                {
                    "text": "🚪 پیوستن به اتاق"
                }
            ],
            [
                {
                    "text": "🏠 منوی اصلی"
                }
            ]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


def get_game_modes_keyboard():

    return {
        "keyboard": [
            [
                {
                    "text": "🟢 معمولی و دوستانه"
                }
            ],
            [
                {
                    "text": "🔥 خفن و چالشی"
                }
            ],
            [
                {
                    "text": "👻 ترسناک و مرموز"
                }
            ],
            [
                {
                    "text": "🏠 منوی اصلی"
                }
            ]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }


# =========================================================
# ساخت کد اتاق
# =========================================================

def generate_room_code():

    while True:

        code = str(
            random.randint(1000, 9999)
        )

        if code not in rooms:
            return code


# =========================================================
# سوال‌های بازی تک‌نفره
# =========================================================

def get_random_prompt(mode):

    prompts = {

        "normal": [
            "🎯 حقیقت: یک خاطره خنده‌دار تعریف کن.",
            "🔥 جرئت: سه ویژگی مثبت خودت را بنویس.",
            "🎯 حقیقت: دوست داری چه مهارتی یاد بگیری؟",
            "🔥 جرئت: یک جمله بامزه درباره خودت بنویس."
        ],

        "fun": [
            "😂 یک داستان کوتاه و خنده‌دار بنویس.",
            "🎭 سه کلمه عجیب برای توصیف خودت بگو.",
            "🤣 خنده‌دارترین خاطره‌ات را تعریف کن."
        ],

        "scary": [
            "👻 یک داستان کوتاه و مرموز بنویس.",
            "🌙 ترسناک‌ترین فیلمی که دیده‌ای چه بوده؟",
            "🔮 یک داستان تخیلی رازآلود تعریف کن."
        ]
    }

    return random.choice(
        prompts.get(
            mode,
            prompts["normal"]
        )
    )


def start_single_game_turn(chat_id):

    game = single_player.get(chat_id)

    if not game:
        return

    prompt = get_random_prompt(
        game.get("mode", "normal")
    )

    game["waiting_for_answer"] = True

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"{prompt}\n\n"
            "✍️ پاسخ خود را ارسال کنید."
        ),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "⏭️ سؤال بعدی",
                        "callback_data": "single_next"
                    }
                ],
                [
                    {
                        "text": "🏠 پایان بازی",
                        "callback_data": "single_end"
                    }
                ]
            ]
        }
    )


# =========================================================
# انتخاب بازیکنان
# =========================================================

def choose_random_players(room_code):

    room = rooms.get(room_code)

    if not room:
        return False

    players = room.get("players", [])

    if len(players) < 2:
        return False

    questioner, answerer = random.sample(
        players,
        2
    )

    room["questioner"] = questioner
    room["answerer"] = answerer

    room["question_type"] = None
    room["question"] = None
    room["answer"] = None
    room["votes"] = {}

    room["phase"] = "choosing_type"

    return True


# =========================================================
# شروع دور
# =========================================================

def start_new_round(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    if room.get("state") != "playing":
        return

    if len(room.get("players", [])) < 2:
        return

    room["round"] = (
        room.get("round", 0) + 1
    )

    if not choose_random_players(room_code):
        return

    questioner = room["questioner"]
    answerer = room["answerer"]

    base_text = (
        f"🎮 دور شماره {room['round']}\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                (
                    base_text +
                    "\n\n🎯 انتخاب کن:"
                ),
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎯 حقیقت",
                                "callback_data":
                                    f"choose_truth_{room_code}"
                            },
                            {
                                "text": "🔥 جرئت",
                                "callback_data":
                                    f"choose_dare_{room_code}"
                            }
                        ]
                    ]
                }
            )

        else:

            send_message(
                player_id,
                (
                    base_text +
                    "\n\n⏳ منتظر انتخاب پاسخ‌دهنده..."
                )
            )


# =========================================================
# نمایش سؤال
# =========================================================

def broadcast_question(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    questioner = room["questioner"]
    answerer = room["answerer"]

    type_name = (
        "🎯 حقیقت"
        if room["question_type"] == "truth"
        else "🔥 جرئت"
    )

    text = (
        "📢 سؤال / چالش\n\n"
        f"✍️ پرسش‌کننده: "
        f"{get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}\n"
        f"🎲 نوع: {type_name}\n\n"
        f"📝 {room['question']}"
    )

    room["phase"] = "waiting_answer"

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                (
                    text +
                    "\n\n💬 حالا پاسخ خودت را ارسال کن."
                )
            )

        else:

            send_message(
                player_id,
                (
                    text +
                    "\n\n⏳ منتظر پاسخ..."
                )
            )


# =========================================================
# شروع رأی‌گیری
# =========================================================

def start_voting(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    answerer = room["answerer"]

    room["phase"] = "voting"
    room["votes"] = {}

    room["eligible_voters"] = [
        player_id
        for player_id in room["players"]
        if player_id != answerer
    ]

    text = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: "
        f"{get_name(answerer)}\n\n"
        f"💬 پاسخ:\n"
        f"{room['answer']}\n\n"
        "🗳️ رأی دهید:"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                (
                    text +
                    "\n\n⏳ منتظر رأی سایر بازیکنان..."
                )
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
                                    f"vote_yes_{room_code}"
                            },
                            {
                                "text": "👎 رد",
                                "callback_data":
                                    f"vote_no_{room_code}"
                            }
                        ]
                    ]
                }
            )


# =========================================================
# پایان رأی‌گیری
# =========================================================

def finish_voting(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    if room.get("phase") != "voting":
        return

    votes = room.get("votes", {})

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

    answerer = room["answerer"]

    points = 0

    if yes_votes > no_votes:

        points = 10

        add_score(
            answerer,
            points
        )

        result = "✅ اکثریت پاسخ را تأیید کردند."

    elif no_votes > yes_votes:

        result = "❌ اکثریت پاسخ را رد کردند."

    else:

        result = "⚖️ رأی‌ها مساوی شد."

    text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}"
    )

    if points:

        text += (
            f"\n\n🌟 "
            f"{get_name(answerer)} "
            f"{points} امتیاز گرفت!"
        )

    text += (
        "\n\n🔄 دور بعدی شروع می‌شود..."
    )

    room["phase"] = "between_rounds"

    for player_id in room["players"]:

        send_message(
            player_id,
            text
        )

    time.sleep(2)

    start_new_round(room_code)


def check_voting_finished(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    voters = room.get(
        "eligible_voters",
        []
    )

    votes = room.get("votes", {})

    if len(votes) >= len(voters):

        finish_voting(room_code)


def register_vote(
    room_code,
    voter_id,
    vote
):

    room = rooms.get(room_code)

    if not room:
        return

    if room.get("phase") != "voting":

        send_message(
            voter_id,
            "⚠️ رأی‌گیری فعال نیست."
        )

        return

    if voter_id not in room.get(
        "eligible_voters",
        []
    ):

        send_message(
            voter_id,
            "⚠️ شما نمی‌توانید رأی دهید."
        )

        return

    if voter_id in room["votes"]:

        send_message(
            voter_id,
            "⚠️ قبلاً رأی داده‌اید."
        )

        return

    room["votes"][voter_id] = vote

    send_message(
        voter_id,
        "✅ رأی شما ثبت شد."
    )

    check_voting_finished(room_code)


# =========================================================
# پردازش پیام
# =========================================================

def handle_message(msg):

    chat_id = msg.get(
        "chat",
        {}
    ).get("id")

    if not chat_id:
        return

    text = msg.get(
        "text",
        ""
    ).strip()

    # ثبت نام

    if not user_exists(chat_id):

        if text == "/start":

            pending_name.add(chat_id)

            send_message(
                chat_id,
                "👋 سلام!\n\n✏️ نام مستعار خود را وارد کنید:"
            )

            return

        if not text:

            return

        save_user(
            chat_id,
            text
        )

        pending_name.discard(chat_id)

        send_message(
            chat_id,
            f"🎉 خوش آمدی {text}!",
            get_main_menu()
        )

        return

    # تغییر نام

    if chat_id in pending_new_name:

        if text:

            save_user(
                chat_id,
                text
            )

            pending_new_name.discard(chat_id)

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
            (
                f"👋 سلام {get_name(chat_id)}!\n\n"
                "از منوی پایین استفاده کن."
            ),
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

    # جدول

    if text == "🏆 جدول امتیازات":

        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu()
        )

        return

    # تغییر نام

    if text == "✏️ تغییر نام":

        pending_new_name.add(chat_id)

        send_message(
            chat_id,
            "✏️ نام جدید را ارسال کنید:"
        )

        return

    # بازی تک‌نفره

    if text == "🤖 بازی تک‌نفره":

        user_states[chat_id] = "choose_mode"

        send_message(
            chat_id,
            "🎮 مود را انتخاب کن:",
            get_game_modes_keyboard()
        )

        return

    mode_map = {
        "🟢 معمولی و دوستانه": "normal",
        "🔥 خفن و چالشی": "fun",
        "👻 ترسناک و مرموز": "scary"
    }

    if (
        text in mode_map
        and user_states.get(chat_id) == "choose_mode"
    ):

        single_player[chat_id] = {
            "mode": mode_map[text],
            "waiting_for_answer": False
        }

        start_single_game_turn(chat_id)

        return

    # اتاق‌ها

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 اتاق‌های آنلاین",
            get_online_rooms_menu()
        )

        return

    # ساخت اتاق

    if text == "🛠️ ساخت اتاق جدید":

        room_code = generate_room_code()

        rooms[room_code] = {
            "host": chat_id,
            "players": [chat_id],
            "state": "waiting",
            "phase": None,
            "questioner": None,
            "answerer": None,
            "question_type": None,
            "question": None,
            "answer": None,
            "votes": {},
            "eligible_voters": [],
            "round": 0
        }

        send_message(
            chat_id,
            (
                "✅ اتاق ساخته شد!\n\n"
                f"🔢 کد اتاق: {room_code}"
            ),
            get_online_rooms_menu()
        )

        send_message(
            chat_id,
            "🚀 برای شروع بازی دکمه زیر را بزن:",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 شروع بازی",
                            "callback_data":
                                f"start_room_{room_code}"
                        }
                    ]
                ]
            }
        )

        return

    # پیوستن

    if text == "🚪 پیوستن به اتاق":

        keyboard = []

        for code, room in rooms.items():

            if room["state"] == "waiting":

                keyboard.append([
                    {
                        "text":
                            f"🚪 اتاق {code}"
                    }
                ])

        keyboard.append([
            {
                "text": "🏠 منوی اصلی"
            }
        ])

        send_message(
            chat_id,
            "🚪 اتاق را انتخاب کن:",
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

            room_code = parts[2]

            room = rooms.get(room_code)

            if room and room["state"] == "waiting":

                if chat_id not in room["players"]:

                    room["players"].append(chat_id)

                send_message(
                    chat_id,
                    f"✅ وارد اتاق {room_code} شدی!"
                )

                return

    # دریافت سؤال

    for room_code, room in rooms.items():

        if (
            room.get("phase") == "waiting_question"
            and room.get("questioner") == chat_id
        ):

            room["question"] = text

            broadcast_question(room_code)

            return

    # دریافت پاسخ

    for room_code, room in rooms.items():

        if (
            room.get("phase") == "waiting_answer"
            and room.get("answerer") == chat_id
        ):

            room["answer"] = text

            start_voting(room_code)

            return

    # پاسخ بازی تک‌نفره

    if (
        chat_id in single_player
        and single_player[chat_id].get(
            "waiting_for_answer"
        )
    ):

        single_player[chat_id][
            "waiting_for_answer"
        ] = False

        add_score(chat_id, 5)

        send_message(
            chat_id,
            "✅ پاسخ ثبت شد! 🌟 ۵ امتیاز گرفتی."
        )

        return

    send_message(
        chat_id,
        "🤔 از منوی پایین استفاده کن.",
        get_main_menu()
    )


# =========================================================
# Callback
# =========================================================

def handle_callback(query):

    callback_id = query.get("id")

    chat_id = query.get(
        "message",
        {}
    ).get(
        "chat",
        {}
    ).get("id")

    data = query.get("data", "")

    answer_callback_query(callback_id)

    if not chat_id:
        return

    # ادامه تک نفره

    if data == "single_next":

        start_single_game_turn(chat_id)

        return

    if data == "single_end":

        single_player.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 بازی پایان یافت.",
            get_main_menu()
        )

        return

    # شروع اتاق

    if data.startswith("start_room_"):

        code = data.replace(
            "start_room_",
            "",
            1
        )

        room = rooms.get(code)

        if (
            not room
            or room["host"] != chat_id
        ):

            return

        if len(room["players"]) < 2:

            send_message(
                chat_id,
                "⚠️ حداقل ۲ بازیکن لازم است."
            )

            return

        room["state"] = "playing"

        start_new_round(code)

        return

    # حقیقت

    if data.startswith("choose_truth_"):

        code = data.replace(
            "choose_truth_",
            "",
            1
        )

        room = rooms.get(code)

        if (
            room
            and room["phase"] == "choosing_type"
            and room["answerer"] == chat_id
        ):

            room["question_type"] = "truth"

            room["phase"] = "waiting_question"

            questioner = room["questioner"]

            send_message(
                questioner,
                (
                    "✍️ نوبت شماست!\n\n"
                    "یک سؤال حقیقت ارسال کنید."
                )
            )

        return

    # جرئت

    if data.startswith("choose_dare_"):

        code = data.replace(
            "choose_dare_",
            "",
            1
        )

        room = rooms.get(code)

        if (
            room
            and room["phase"] == "choosing_type"
            and room["answerer"] == chat_id
        ):

            room["question_type"] = "dare"

            room["phase"] = "waiting_question"

            questioner = room["questioner"]

            send_message(
                questioner,
                (
                    "✍️ نوبت شماست!\n\n"
                    "چالش جرئت را ارسال کنید."
                )
            )

        return

    # رأی

    if data.startswith("vote_yes_"):

        code = data.replace(
            "vote_yes_",
            "",
            1
        )

        register_vote(
            code,
            chat_id,
            "yes"
        )

        return

    if data.startswith("vote_no_"):

        code = data.replace(
            "vote_no_",
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
# Update
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
# Polling
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

    init_database()

    print(
        "🚀 Starting Bale Bot..."
    )

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
