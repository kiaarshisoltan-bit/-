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
# وضعیت موقت بازی
# =====================================================

user_states = {}
single_player = {}
rooms = {}

# =====================================================
# وب‌سرور Render
# =====================================================

@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running!"

@app.route("/health")
def health():
    return jsonify({"status": "ok"})

# =====================================================
# دیتابیس PostgreSQL
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

        db.commit()
        cur.close()
        db.close()

    print("PostgreSQL database initialized")


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


def save_user(user_id, name):
    with db_lock:
        db = get_db()
        cur = db.cursor()

        cur.execute("""
            INSERT INTO users (user_id, name, score)
            VALUES (%s, %s, 0)
            ON CONFLICT (user_id)
            DO UPDATE SET name = EXCLUDED.name
        """, (user_id, name))

        db.commit()
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

    return result[0] if result else "بازیکن"


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

    for i, row in enumerate(rows, 1):
        result += f"{i}. {row[0]} — {row[1]} امتیاز\n"

    return result

# =====================================================
# ارتباط با API بله
# =====================================================

def api_request(method, payload=None, timeout=20):
    try:
        response = requests.post(
            f"{BASE_URL}/{method}",
            json=payload or {},
            timeout=timeout
        )

        data = response.json()

        if response.status_code != 200 or not data.get("ok"):
            print("API Error:", method, data)
            return None

        return data

    except Exception as error:
        print("Request Error:", error)
        return None


def send_message(chat_id, text, reply_markup=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return api_request("sendMessage", payload)


def answer_callback(callback_id, text=None):
    payload = {
        "callback_query_id": callback_id
    }

    if text:
        payload["text"] = text

    api_request("answerCallbackQuery", payload)


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
                {"text": "📢 کانال اطلاع‌رسانی"},
                {"text": "💬 پشتیبانی"}
            ],
            [
                {"text": "📖 راهنمای بازی"}
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
        "inline_keyboard": [
            [
                {
                    "text": "🎲 چالش بعدی",
                    "callback_data": "single_next"
                }
            ],
            [
                {
                    "text": "🔙 منوی اصلی",
                    "callback_data": "back_menu"
                }
            ]
        ]
    }


# =====================================================
# بانک سؤال و چالش تک‌نفره
# =====================================================

PROMPTS = {
    "normal": {
        "truth": [
            "آخرین باری که از ته دل خندیدی چه زمانی بود؟",
            "اگر می‌توانستی یک مهارت جدید یاد بگیری، چه بود؟",
            "بهترین خاطره مدرسه‌ات چیست؟",
            "چه چیزی خیلی زود خوشحالت می‌کند؟",
            "اگر یک روز نامرئی بودی، چه کار بی‌خطری انجام می‌دادی؟",
            "کدام شخصیت کارتونی را بیشتر دوست داری؟",
            "بهترین هدیه‌ای که گرفته‌ای چه بوده؟"
        ],
        "dare": [
            "سه بار پشت سر هم یک جمله سخت را سریع بگو.",
            "یک داستان خنده‌دار سه‌خطی بنویس.",
            "نام پنج میوه را در ده ثانیه بنویس.",
            "یک جمله را طوری بنویس که تمام کلماتش با یک حرف شروع شوند.",
            "یک معمای ساده بساز و جوابش را هم بنویس.",
            "یک شعر کوتاه و بامزه بساز."
        ]
    },

    "fun": {
        "truth": [
            "عجیب‌ترین غذایی که امتحان کرده‌ای چه بوده؟",
            "اگر مدیر مدرسه بودی چه قانون بامزه‌ای می‌گذاشتی؟",
            "اگر می‌توانستی یک قدرت جادویی داشته باشی، چه بود؟",
            "خنده‌دارترین اشتباهی که در یک بازی کرده‌ای چه بوده؟",
            "اگر یک روز جای یک شخصیت کارتونی بودی، چه کسی را انتخاب می‌کردی؟"
        ],
        "dare": [
            "یک جمله خنده‌دار با سه ایموجی بساز.",
            "اسم پنج حیوان را برعکس بنویس.",
            "یک لطیفه کوتاه و مناسب تعریف کن.",
            "یک تبلیغ بامزه برای یک مداد بنویس.",
            "یک جمله بنویس که در آن پنج کلمه با حرف «م» باشد."
        ]
    },

    "scary": {
        "truth": [
            "کدام صدا در شب بیشتر غافلگیرت می‌کند؟",
            "اگر در یک خانه قدیمی بودی، دوست داشتی کدام اتاق را کشف کنی؟",
            "ترسناک‌ترین فیلم یا داستانی که دیده‌ای چه بوده؟",
            "اگر در یک داستان معمایی بودی، چه نقشی داشتی؟",
            "کدام موجود خیالی برایت جالب‌تر است؟"
        ],
        "dare": [
            "یک داستان مرموز سه‌خطی بنویس.",
            "یک اسم ترسناک برای یک خانه خیالی انتخاب کن.",
            "یک معمای مرموز طراحی کن.",
            "یک پیام مرموز با سه ایموجی بنویس.",
            "یک داستان کوتاه با شروع «نیمه‌شب بود...» بساز."
        ]
    }
}


def get_random_prompt(mode, question_type):
    mode_prompts = PROMPTS.get(mode, PROMPTS["normal"])
    return random.choice(mode_prompts[question_type])


def mode_name(mode):
    names = {
        "normal": "معمولی و دوستانه",
        "fun": "خفن و چالشی",
        "scary": "ترسناک و مرموز"
    }

    return names.get(mode, "معمولی")


# =====================================================
# بازی تک‌نفره
# =====================================================

def start_single_game(chat_id):
    if chat_id not in single_player:
        return

    game = single_player[chat_id]

    question_type = random.choice(["truth", "dare"])

    prompt = get_random_prompt(
        game["mode"],
        question_type
    )

    game["question_type"] = question_type
    game["waiting_answer"] = True

    if question_type == "truth":
        title = "🎯 حقیقت"
    else:
        title = "🔥 جرئت"

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره شروع شد!\n\n"
            f"🎮 حالت بازی: {mode_name(game['mode'])}\n\n"
            f"{title}\n\n"
            f"📝 {prompt}\n\n"
            "✍️ پاسخ خود را به‌صورت پیام متنی ارسال کن.\n\n"
            "برای رد کردن این سؤال، می‌توانی از دکمه منوی اصلی استفاده کنی."
        ),
        {
            "keyboard": [
                [{"text": "🏠 منوی اصلی"}]
            ],
            "resize_keyboard": True
        }
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
            "✅ پاسخ شما ثبت شد!\n\n"
            "🌟 ۵ امتیاز به حساب شما اضافه شد.\n"
            "برای ادامه بازی از دکمه زیر استفاده کن."
        ),
        get_single_next_keyboard()
    )


# =====================================================
# اتاق‌های آنلاین
# =====================================================

def generate_room_code():
    while True:
        code = str(random.randint(1000, 9999))

        if code not in rooms:
            return code


def create_room(chat_id, mode):
    code = generate_room_code()

    rooms[code] = {
        "host": chat_id,
        "players": [chat_id],
        "mode": mode,
        "phase": "waiting",
        "round": 0,
        "votes": {},
        "question": None,
        "answer": None,
        "questioner": None,
        "answerer": None
    }

    send_message(
        chat_id,
        (
            "✅ اتاق شما ساخته شد!\n\n"
            f"🔢 کد اتاق: {code}\n"
            f"🎮 حالت: {mode_name(mode)}\n\n"
            "برای شروع بازی، بازیکنان باید به اتاق بپیوندند."
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
    keyboard = []

    for code, room in rooms.items():
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

    keyboard.append([
        {
            "text": "🔙 بازگشت",
            "callback_data": "back_menu"
        }
    ])

    if len(keyboard) == 1:
        send_message(
            chat_id,
            "❌ در حال حاضر اتاقی برای پیوستن وجود ندارد."
        )
        return

    send_message(
        chat_id,
        "🚪 یکی از اتاق‌های زیر را انتخاب کن:",
        {"inline_keyboard": keyboard}
    )


def start_online_round(code):
    room = rooms.get(code)

    if not room or len(room["players"]) < 2:
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
    room["phase"] = "choosing_type"

    message = (
        f"🎮 دور {room['round']}\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}"
    )

    for player in room["players"]:
        if player == answerer:
            send_message(
                player,
                message + "\n\nنوع بازی را انتخاب کن:",
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
                message + "\n\n⏳ منتظر انتخاب پاسخ‌دهنده باش."
            )


def send_online_question(code):
    room = rooms.get(code)

    if not room:
        return

    text = (
        "📢 سؤال یا چالش جدید\n\n"
        f"✍️ پرسش‌کننده: {get_name(room['questioner'])}\n"
        f"🎯 پاسخ‌دهنده: {get_name(room['answerer'])}\n\n"
        f"📝 {room['question']}"
    )

    room["phase"] = "waiting_answer"

    for player in room["players"]:
        if player == room["answerer"]:
            send_message(player, text + "\n\n💬 پاسخ خود را ارسال کن.")
        else:
            send_message(player, text + "\n\n⏳ منتظر پاسخ باش.")


def start_online_voting(code):
    room = rooms.get(code)

    if not room:
        return

    room["phase"] = "voting"

    eligible = [
        p for p in room["players"]
        if p != room["answerer"]
    ]

    room["eligible_voters"] = eligible
    room["votes"] = {}

    text = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(room['answerer'])}\n"
        f"💬 پاسخ: {room['answer']}\n\n"
        "🗳️ آیا پاسخ مورد قبول است؟"
    )

    for player in room["players"]:
        if player == room["answerer"]:
            send_message(player, text + "\n\n⏳ منتظر رأی دیگران باش.")
        else:
            send_message(
                player,
                text,
                {
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
            )


def register_vote(code, user_id, vote):
    room = rooms.get(code)

    if not room or room["phase"] != "voting":
        return

    if user_id not in room["eligible_voters"]:
        send_message(user_id, "⚠️ شما اجازه رأی دادن ندارید.")
        return

    if user_id in room["votes"]:
        send_message(user_id, "⚠️ شما قبلاً رأی داده‌اید.")
        return

    room["votes"][user_id] = vote

    send_message(user_id, "✅ رأی شما ثبت شد.")

    if len(room["votes"]) == len(room["eligible_voters"]):
        finish_online_voting(code)


def finish_online_voting(code):
    room = rooms.get(code)

    if not room:
        return

    yes_votes = sum(
        1 for v in room["votes"].values()
        if v == "yes"
    )

    no_votes = sum(
        1 for v in room["votes"].values()
        if v == "no"
    )

    answerer = room["answerer"]

    if yes_votes > no_votes:
        add_score(answerer, 10)
        result = "✅ پاسخ تأیید شد و ۱۰ امتیاز اضافه شد."
    elif no_votes > yes_votes:
        result = "❌ پاسخ رد شد و امتیازی اضافه نشد."
    else:
        result = "⚖️ رأی‌ها مساوی شدند."

    message = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 تأیید: {yes_votes}\n"
        f"👎 رد: {no_votes}\n\n"
        f"{result}\n\n"
        "🔄 دور بعدی به‌زودی شروع می‌شود."
    )

    room["phase"] = "between_rounds"

    for player in room["players"]:
        send_message(player, message)

    time.sleep(2)

    if code in rooms:
        start_online_round(code)


# =====================================================
# پردازش پیام‌های متنی
# =====================================================

def handle_message(message):
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = message.get("text", "").strip()

    if not user_exists(chat_id):
        if text:
            save_user(chat_id, text[:40])
            send_message(
                chat_id,
                f"🎉 خوش آمدی {text}!\nحساب کاربری ساخته شد.",
                get_main_menu()
            )
        else:
            send_message(
                chat_id,
                "👋 سلام!\nلطفاً برای شروع یک نام مستعار ارسال کن."
            )
        return

    # ثبت نام جدید
    if user_states.get(chat_id) == "register":
        if text:
            save_user(chat_id, text[:40])
            user_states.pop(chat_id, None)
            send_message(chat_id, "✅ نام شما ثبت شد.", get_main_menu())
        return

    # تغییر نام
    if user_states.get(chat_id) == "change_name":
        if text:
            save_user(chat_id, text[:40])
            user_states.pop(chat_id, None)
            send_message(chat_id, "✅ نام شما تغییر کرد.", get_main_menu())
        return

    # ثبت پاسخ تک‌نفره
    if single_player.get(chat_id, {}).get("waiting_answer"):
        if text and text != "🏠 منوی اصلی":
            finish_single_game(chat_id)
            return

    if text == "/start":
        send_message(
            chat_id,
            f"👋 سلام {get_name(chat_id)}!\nبه بازی جرئت یا حقیقت خوش آمدی.",
            get_main_menu()
        )
        return

    if text == "🏠 منوی اصلی":
        user_states.pop(chat_id, None)
        single_player.pop(chat_id, None)
        send_message(chat_id, "🏠 منوی اصلی", get_main_menu())
        return

    if text == "🤖 بازی تک‌نفره":
        user_states[chat_id] = "choosing_single_mode"
        send_message(
            chat_id,
            "🎮 حالت بازی تک‌نفره را انتخاب کن:",
            get_modes_keyboard()
        )
        return

    if text == "🎮 اتاق‌های آنلاین":
        send_message(
            chat_id,
            "🎮 بخش اتاق‌های آنلاین",
            get_rooms_menu()
        )
        return

    if text == "🛠️ ساخت اتاق جدید":
        user_states[chat_id] = "choosing_room_mode"
        send_message(
            chat_id,
            "🎮 حالت اتاق را انتخاب کن:",
            get_modes_keyboard()
        )
        return

    if text == "🚪 پیوستن به اتاق":
        list_rooms(chat_id)
        return

    if text == "🏆 جدول امتیازات":
        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu()
        )
        return

    if text == "✏️ تغییر نام":
        user_states[chat_id] = "change_name"
        send_message(chat_id, "✏️ نام مستعار جدید را ارسال کن:")
        return

    if text == "📢 کانال اطلاع‌رسانی":
        send_message(
            chat_id,
            "📢 کانال اطلاع‌رسانی:\nhttps://ble.ir/ettelae_resani",
            get_main_menu()
        )
        return

    if text == "💬 پشتیبانی":
        send_message(
            chat_id,
            "💬 پشتیبانی:\nhttps://ble.ir/kia_karfarma",
            get_main_menu()
        )
        return

    if text == "📖 راهنمای بازی":
        send_message(
            chat_id,
            (
                "📖 راهنمای بازی\n\n"
                "🤖 بازی تک‌نفره:\n"
                "یک حالت انتخاب کن، سؤال یا چالش را انجام بده و پاسخ متنی بفرست.\n"
                "برای هر پاسخ ثبت‌شده ۵ امتیاز می‌گیری.\n\n"
                "🎮 اتاق آنلاین:\n"
                "یک اتاق بساز یا وارد اتاق دیگران شو.\n"
                "ربات پرسش‌کننده و پاسخ‌دهنده را انتخاب می‌کند.\n"
                "بعد از پاسخ، بازیکنان رأی می‌دهند.\n"
                "با تأیید پاسخ، ۱۰ امتیاز به پاسخ‌دهنده داده می‌شود."
            ),
            get_main_menu()
        )
        return

    # دریافت سؤال پرسش‌کننده در اتاق آنلاین
    for code, room in list(rooms.items()):
        if (
            room["phase"] == "waiting_question"
            and room["questioner"] == chat_id
        ):
            if text:
                room["question"] = text
                send_online_question(code)
            return

    # دریافت پاسخ پاسخ‌دهنده در اتاق آنلاین
    for code, room in list(rooms.items()):
        if (
            room["phase"] == "waiting_answer"
            and room["answerer"] == chat_id
        ):
            if text:
                room["answer"] = text
                start_online_voting(code)
            return

    send_message(
        chat_id,
        "از دکمه‌های منو استفاده کن.",
        get_main_menu()
    )


# =====================================================
# پردازش دکمه‌های شیشه‌ای
# =====================================================

def handle_callback(query):
    callback_id = query.get("id")
    message = query.get("message", {})
    chat_id = message.get("chat", {}).get("id")
    data = query.get("data", "")

    answer_callback(callback_id)

    if not chat_id:
        return

    # بازگشت به منو
    if data == "back_menu":
        user_states.pop(chat_id, None)
        single_player.pop(chat_id, None)
        send_message(chat_id, "🏠 منوی اصلی", get_main_menu())
        return

    # انتخاب مود
    if data.startswith("mode_"):
        mode = data.replace("mode_", "", 1)
        state = user_states.get(chat_id)

        if mode not in ("normal", "fun", "scary"):
            return

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
            create_room(chat_id, mode)
            return

    # چالش بعدی
    if data == "single_next":
        if chat_id in single_player:
            start_single_game(chat_id)
        return

    # پیوستن به اتاق
    if data.startswith("join_room_"):
        code = data.replace("join_room_", "", 1)
        room = rooms.get(code)

        if not room or room["phase"] != "waiting":
            send_message(chat_id, "❌ این اتاق دیگر قابل ورود نیست.")
            return

        if chat_id not in room["players"]:
            room["players"].append(chat_id)

        send_message(
            chat_id,
            f"✅ به اتاق {code} پیوستی.",
            get_rooms_menu()
        )

        send_message(
            room["host"],
            f"👤 {get_name(chat_id)} به اتاق پیوست."
        )
        return

    # شروع اتاق
    if data.startswith("start_room_"):
        code = data.replace("start_room_", "", 1)
        room = rooms.get(code)

        if not room:
            return

        if room["host"] != chat_id:
            send_message(chat_id, "⚠️ فقط میزبان می‌تواند بازی را شروع کند.")
            return

        if len(room["players"]) < 2:
            send_message(chat_id, "⚠️ حداقل دو بازیکن لازم است.")
            return

        start_online_round(code)
        return

    # حذف اتاق
    if data.startswith("delete_room_"):
        code = data.replace("delete_room_", "", 1)
        room = rooms.get(code)

        if room and room["host"] == chat_id:
            for player in room["players"]:
                send_message(player, "❌ اتاق توسط میزبان بسته شد.")

            del rooms[code]
        return

    # انتخاب حقیقت یا جرئت
    if data.startswith("truth_") or data.startswith("dare_"):
        question_type, code = data.split("_", 1)
        room = rooms.get(code)

        if not room or room["phase"] != "choosing_type":
            return

        if room["answerer"] != chat_id:
            send_message(chat_id, "⚠️ شما پاسخ‌دهنده این دور نیستید.")
            return

        room["question_type"] = question_type
        room["phase"] = "waiting_question"

        send_message(
            room["questioner"],
            (
                "✍️ پاسخ‌دهنده انتخاب خود را انجام داد.\n"
                "حالا سؤال یا چالش را ارسال کن."
            )
        )
        return

    # رأی مثبت و منفی
    if data.startswith("yes_") or data.startswith("no_"):
        vote, code = data.split("_", 1)

        register_vote(
            code,
            chat_id,
            "yes" if vote == "yes" else "no"
        )
        return


# =====================================================
# پردازش آپدیت‌ها
# =====================================================

def handle_update(update):
    try:
        if "message" in update:
            handle_message(update["message"])

        elif "callback_query" in update:
            handle_callback(update["callback_query"])

    except Exception as error:
        print("Update Error:", error)


# =====================================================
# دریافت پیام‌ها
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
                time.sleep(3)
                continue

            for update in data.get("result", []):
                update_id = update.get("update_id")

                if update_id is not None:
                    offset = update_id + 1

                # برای حفظ ترتیب تغییر وضعیت بازی،
                # آپدیت‌ها در همین حلقه پردازش می‌شوند.
                handle_update(update)

        except Exception as error:
            print("Polling Error:", error)
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
