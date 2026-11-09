import os
import random
import threading
import time

import requests
from flask import Flask, jsonify


# =========================================================
# تنظیمات
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
PORT = int(os.getenv("PORT", 10000))

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN تنظیم نشده است. "
        "آن را در Environment Variables رندر وارد کنید."
    )

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"


# =========================================================
# وب سرور برای Render
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bale Truth or Dare Bot is running! 🤖"


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "message": "Bot is running"
    })


# =========================================================
# ذخیره اطلاعات در حافظه
# =========================================================

profiles = {}
scores = {}

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
                f"Invalid JSON from Bale API: {response.text}"
            )

            return None

        if response.status_code != 200:

            print(
                f"API HTTP Error [{method}]: "
                f"{response.status_code}"
            )

            print(data)

            return None

        if not data.get("ok", False):

            print(
                f"Bale API Error [{method}]: {data}"
            )

            return None

        return data

    except requests.RequestException as error:

        print(
            f"API Request Error [{method}]: {error}"
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
# منوی اصلی دائمی
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


# =========================================================
# منوی اتاق آنلاین
# =========================================================

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


# =========================================================
# انتخاب مود برای بازی تک‌نفره
# =========================================================

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

        room_code = str(
            random.randint(1000, 9999)
        )

        if room_code not in rooms:
            return room_code


# =========================================================
# نام کاربر
# =========================================================

def get_name(user_id):

    return profiles.get(
        user_id,
        f"بازیکن {user_id}"
    )


# =========================================================
# جدول امتیازات
# =========================================================

def get_leaderboard_text():

    if not scores:

        return (
            "🏆 جدول امتیازات\n\n"
            "هنوز امتیازی ثبت نشده است."
        )

    sorted_scores = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )[:10]

    text = "🏆 جدول برترین‌ها 🏆\n\n"

    for index, (user_id, score) in enumerate(
        sorted_scores,
        start=1
    ):

        text += (
            f"{index}. "
            f"{get_name(user_id)} — "
            f"{score} امتیاز\n"
        )

    return text


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
            "🤣 خنده‌دارترین خاطره‌ات را تعریف کن.",
            "🎪 یک جمله کاملاً عجیب و بامزه بنویس."
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


# =========================================================
# شروع بازی تک‌نفره
# =========================================================

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
# انتخاب تصادفی دو نفر برای دور جدید
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
# شروع دور جدید
# =========================================================

def start_new_round(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    if room.get("state") != "playing":
        return

    if len(room.get("players", [])) < 2:

        room["state"] = "waiting"

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    "⚠️ تعداد بازیکنان برای ادامه بازی کافی نیست."
                ),
                get_online_rooms_menu()
            )

        return

    room["round"] = room.get("round", 0) + 1

    if not choose_random_players(room_code):
        return

    questioner = room["questioner"]
    answerer = room["answerer"]

    round_text = (
        f"🎮 دور شماره {room['round']} شروع شد!\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}\n\n"
        f"🎯 {get_name(answerer)} باید انتخاب کند:"
    )

    # اطلاع به همه

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                round_text,
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎯 حقیقت",
                                "callback_data": (
                                    f"choose_truth_{room_code}"
                                )
                            },
                            {
                                "text": "🔥 جرئت",
                                "callback_data": (
                                    f"choose_dare_{room_code}"
                                )
                            }
                        ]
                    ]
                }
            )

        else:

            send_message(
                player_id,
                (
                    round_text +
                    "\n\n⏳ منتظر انتخاب پاسخ‌دهنده هستیم..."
                )
            )


# =========================================================
# نمایش سوال برای همه
# =========================================================

def broadcast_question(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    questioner = room["questioner"]
    answerer = room["answerer"]

    question_type = room["question_type"]

    if question_type == "truth":
        type_name = "🎯 حقیقت"
    else:
        type_name = "🔥 جرئت"

    text = (
        "📢 سوال یا چالش ثبت شد!\n\n"
        f"✍️ پرسش‌کننده: {get_name(questioner)}\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}\n"
        f"🎲 انتخاب: {type_name}\n\n"
        f"📝 سوال / چالش:\n"
        f"{room['question']}"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                (
                    text +
                    "\n\n💬 فقط شما می‌توانید پاسخ دهید."
                )
            )

        else:

            send_message(
                player_id,
                (
                    text +
                    "\n\n⏳ منتظر پاسخ پاسخ‌دهنده هستیم..."
                )
            )

    room["phase"] = "waiting_answer"


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

    # پاسخ‌دهنده به خودش رأی نمی‌دهد
    eligible_voters = [
        player_id
        for player_id in room["players"]
        if player_id != answerer
    ]

    room["eligible_voters"] = eligible_voters

    answer_text = (
        "📢 پاسخ ثبت شد!\n\n"
        f"🎯 پاسخ‌دهنده: {get_name(answerer)}\n\n"
        f"💬 پاسخ:\n{room['answer']}\n\n"
        "🗳️ لطفاً رأی دهید:"
    )

    for player_id in room["players"]:

        if player_id == answerer:

            send_message(
                player_id,
                (
                    answer_text +
                    "\n\n⏳ سایر بازیکنان در حال رأی دادن هستند..."
                )
            )

        else:

            send_message(
                player_id,
                answer_text,
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "👍 تأیید",
                                "callback_data": (
                                    f"vote_yes_{room_code}"
                                )
                            },
                            {
                                "text": "👎 رد",
                                "callback_data": (
                                    f"vote_no_{room_code}"
                                )
                            }
                        ]
                    ]
                }
            )


# =========================================================
# پایان رأی‌گیری و محاسبه امتیاز
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

        scores[answerer] = (
            scores.get(answerer, 0) + points
        )

        result = (
            "✅ پاسخ توسط اکثریت تأیید شد!"
        )

    elif no_votes > yes_votes:

        result = (
            "❌ پاسخ توسط اکثریت رد شد."
        )

    else:

        result = (
            "⚖️ رأی‌ها مساوی شد؛ امتیازی داده نشد."
        )

    result_text = (
        "📊 نتیجه رأی‌گیری\n\n"
        f"👍 رأی تأیید: {yes_votes}\n"
        f"👎 رأی رد: {no_votes}\n\n"
        f"{result}"
    )

    if points > 0:

        result_text += (
            f"\n\n🌟 {get_name(answerer)} "
            f"{points} امتیاز دریافت کرد!"
        )

    result_text += (
        "\n\n🔄 دور بعدی در حال شروع است..."
    )

    room["phase"] = "between_rounds"

    for player_id in room["players"]:

        send_message(
            player_id,
            result_text
        )

    time.sleep(2)

    start_new_round(room_code)


# =========================================================
# بررسی کامل شدن رأی‌گیری
# =========================================================

def check_voting_finished(room_code):

    room = rooms.get(room_code)

    if not room:
        return

    eligible_voters = room.get(
        "eligible_voters",
        []
    )

    votes = room.get("votes", {})

    if len(votes) >= len(eligible_voters):

        finish_voting(room_code)


# =========================================================
# ورود به اتاق
# =========================================================

def join_room_by_text(chat_id, text):

    if not text.startswith("🚪 اتاق "):
        return False

    try:

        room_code = text.split(
            "🚪 اتاق ",
            1
        )[1].split(
            " ",
            1
        )[0]

    except Exception:

        return False

    room = rooms.get(room_code)

    if not room:

        send_message(
            chat_id,
            "⚠️ این اتاق دیگر وجود ندارد.",
            get_online_rooms_menu()
        )

        return True

    if room.get("state") != "waiting":

        send_message(
            chat_id,
            "⚠️ بازی این اتاق شروع شده است."
        )

        return True

    if chat_id not in room["players"]:

        room["players"].append(chat_id)

        send_message(
            room["host"],
            (
                f"👤 {get_name(chat_id)} "
                "به اتاق شما پیوست."
            )
        )

    send_message(
        chat_id,
        (
            f"✅ به اتاق {room_code} پیوستید!\n\n"
            "⏳ منتظر شروع بازی توسط میزبان باشید."
        ),
        get_online_rooms_menu()
    )

    return True


# =========================================================
# پردازش پیام‌های کاربران
# =========================================================

def handle_message(msg):

    chat = msg.get("chat", {})
    chat_id = chat.get("id")

    if not chat_id:
        return

    text = msg.get("text", "")

    if text:
        text = text.strip()

    # -----------------------------------------------------
    # ثبت نام اولیه
    # -----------------------------------------------------

    if chat_id not in profiles:

        if text == "/start":

            pending_name.add(chat_id)

            send_message(
                chat_id,
                (
                    "سلام! 👋🎮\n\n"
                    "به ربات جرئت یا حقیقت خوش آمدی!\n\n"
                    "✏️ لطفاً یک نام مستعار وارد کن:"
                )
            )

            return

        if not text:

            send_message(
                chat_id,
                "✏️ لطفاً یک نام مستعار وارد کنید."
            )

            return

        profiles[chat_id] = text

        pending_name.discard(chat_id)

        send_message(
            chat_id,
            (
                f"🎉 خوش آمدی {text} عزیز!\n\n"
                "از منوی پایین یک گزینه را انتخاب کن 👇"
            ),
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # تغییر نام
    # -----------------------------------------------------

    if chat_id in pending_new_name:

        if not text:

            send_message(
                chat_id,
                "⚠️ لطفاً یک نام معتبر وارد کنید."
            )

            return

        profiles[chat_id] = text

        pending_new_name.discard(chat_id)

        send_message(
            chat_id,
            "✅ نام مستعار شما تغییر کرد.",
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # دستور شروع
    # -----------------------------------------------------

    if text == "/start":

        send_message(
            chat_id,
            (
                f"سلام {get_name(chat_id)} عزیز! 👋\n\n"
                "از منوی پایین استفاده کن."
            ),
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # منوی اصلی
    # -----------------------------------------------------

    if text == "🏠 منوی اصلی":

        user_states.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 به منوی اصلی برگشتی.",
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # بازی تک‌نفره
    # -----------------------------------------------------

    if text == "🤖 بازی تک‌نفره":

        user_states[chat_id] = (
            "choosing_single_mode"
        )

        send_message(
            chat_id,
            "🎮 مود بازی را انتخاب کن:",
            get_game_modes_keyboard()
        )

        return

    # -----------------------------------------------------
    # اتاق‌های آنلاین
    # -----------------------------------------------------

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 بخش اتاق‌های آنلاین",
            get_online_rooms_menu()
        )

        return

    # -----------------------------------------------------
    # ساخت اتاق
    # -----------------------------------------------------

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
                "✅ اتاق با موفقیت ساخته شد!\n\n"
                f"🔢 کد اتاق: {room_code}\n\n"
                "👥 بازیکنان دیگر می‌توانند وارد اتاق شوند."
            ),
            get_online_rooms_menu()
        )

        send_message(
            chat_id,
            (
                "🚀 وقتی حداقل دو نفر در اتاق باشند، "
                "بازی را شروع کن."
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 شروع بازی",
                            "callback_data": (
                                f"start_room_{room_code}"
                            )
                        }
                    ]
                ]
            }
        )

        return

    # -----------------------------------------------------
    # پیوستن به اتاق
    # -----------------------------------------------------

    if text == "🚪 پیوستن به اتاق":

        keyboard = []

        for room_code, room in rooms.items():

            if room.get("state") == "waiting":

                count = len(
                    room.get("players", [])
                )

                keyboard.append(
                    [
                        {
                            "text": (
                                f"🚪 اتاق {room_code} "
                                f"({count} بازیکن)"
                            )
                        }
                    ]
                )

        keyboard.append(
            [
                {
                    "text": "🏠 منوی اصلی"
                }
            ]
        )

        if len(keyboard) == 1:

            send_message(
                chat_id,
                "❌ هیچ اتاق فعالی وجود ندارد.",
                get_online_rooms_menu()
            )

            return

        send_message(
            chat_id,
            "🚪 یک اتاق را انتخاب کن:",
            {
                "keyboard": keyboard,
                "resize_keyboard": True,
                "one_time_keyboard": False
            }
        )

        return

    # -----------------------------------------------------
    # انتخاب اتاق
    # -----------------------------------------------------

    if join_room_by_text(chat_id, text):
        return

    # -----------------------------------------------------
    # انتخاب مود تک‌نفره
    # -----------------------------------------------------

    mode = None

    if text == "🟢 معمولی و دوستانه":
        mode = "normal"

    elif text == "🔥 خفن و چالشی":
        mode = "fun"

    elif text == "👻 ترسناک و مرموز":
        mode = "scary"

    if mode:

        if (
            user_states.get(chat_id)
            == "choosing_single_mode"
        ):

            single_player[chat_id] = {
                "mode": mode,
                "waiting_for_answer": False
            }

            user_states[chat_id] = (
                "playing_single"
            )

            start_single_game_turn(chat_id)

            return

        send_message(
            chat_id,
            "⚠️ ابتدا یک بازی را انتخاب کن.",
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # جدول امتیازات
    # -----------------------------------------------------

    if text == "🏆 جدول امتیازات":

        send_message(
            chat_id,
            get_leaderboard_text(),
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # تغییر نام
    # -----------------------------------------------------

    if text == "✏️ تغییر نام":

        pending_new_name.add(chat_id)

        send_message(
            chat_id,
            "✏️ نام مستعار جدید خود را ارسال کنید:"
        )

        return

    # -----------------------------------------------------
    # کانال
    # -----------------------------------------------------

    if text == "📢 کانال اطلاع‌رسانی":

        send_message(
            chat_id,
            (
                "📢 کانال اطلاع‌رسانی:\n\n"
                "https://ble.ir/ettelae_resani"
            ),
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # پشتیبانی
    # -----------------------------------------------------

    if text == "💬 پشتیبانی":

        send_message(
            chat_id,
            (
                "💬 پشتیبانی:\n\n"
                "https://ble.ir/KIA_karfarma"
            ),
            get_main_menu()
        )

        return

    # =====================================================
    # بازی تک‌نفره
    # =====================================================

    if chat_id in single_player:

        game = single_player[chat_id]

        if game.get("waiting_for_answer"):

            game["waiting_for_answer"] = False

            scores[chat_id] = (
                scores.get(chat_id, 0) + 10
            )

            send_message(
                chat_id,
                (
                    "✅ پاسخ ثبت شد!\n\n"
                    "🌟 ۱۰ امتیاز دریافت کردی."
                ),
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎲 ادامه بازی",
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

            return

    # =====================================================
    # بازی آنلاین: دریافت سوال
    # =====================================================

    for room_code, room in rooms.items():

        if (
            chat_id == room.get("questioner")
            and room.get("phase") == "waiting_question"
        ):

            if not text:

                send_message(
                    chat_id,
                    "⚠️ لطفاً سوال یا چالش را به صورت متن ارسال کنید."
                )

                return

            room["question"] = text

            broadcast_question(room_code)

            return

    # =====================================================
    # بازی آنلاین: دریافت پاسخ
    # =====================================================

    for room_code, room in rooms.items():

        if (
            chat_id == room.get("answerer")
            and room.get("phase") == "waiting_answer"
        ):

            if not text:

                send_message(
                    chat_id,
                    "⚠️ لطفاً پاسخ خود را ارسال کنید."
                )

                return

            room["answer"] = text

            start_voting(room_code)

            return

    # =====================================================
    # جلوگیری از پیام افراد غیرمجاز هنگام بازی
    # =====================================================

    for room_code, room in rooms.items():

        if (
            chat_id in room.get("players", [])
            and room.get("state") == "playing"
        ):

            phase = room.get("phase")

            if phase == "waiting_question":

                send_message(
                    chat_id,
                    "⏳ فقط پرسش‌کننده انتخاب‌شده می‌تواند سوال ارسال کند."
                )

                return

            if phase == "waiting_answer":

                send_message(
                    chat_id,
                    "⏳ فقط پاسخ‌دهنده انتخاب‌شده می‌تواند جواب دهد."
                )

                return

            if phase == "voting":

                send_message(
                    chat_id,
                    "🗳️ لطفاً از دکمه‌های رأی‌گیری استفاده کنید."
                )

                return

    # -----------------------------------------------------
    # پیام نامشخص
    # -----------------------------------------------------

    send_message(
        chat_id,
        (
            "🤔 این گزینه را متوجه نشدم.\n\n"
            "از منوی پایین استفاده کنید."
        ),
        get_main_menu()
    )


# =========================================================
# پردازش دکمه‌های شیشه‌ای
# =========================================================

def handle_callback(query):

    callback_id = query.get("id")

    message = query.get("message", {})

    chat_id = (
        message.get("chat", {})
        .get("id")
    )

    data = query.get("data", "")

    if not chat_id:
        return

    answer_callback_query(callback_id)

    # =====================================================
    # بازی تک‌نفره - ادامه
    # =====================================================

    if data == "single_next":

        if chat_id not in single_player:

            send_message(
                chat_id,
                "⚠️ بازی فعال نیست.",
                get_main_menu()
            )

            return

        start_single_game_turn(chat_id)

        return

    # =====================================================
    # بازی تک‌نفره - پایان
    # =====================================================

    if data == "single_end":

        single_player.pop(chat_id, None)

        user_states.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 بازی تک‌نفره پایان یافت.",
            get_main_menu()
        )

        return

    # =====================================================
    # شروع اتاق
    # =====================================================

    if data.startswith("start_room_"):

        room_code = data.replace(
            "start_room_",
            "",
            1
        )

        room = rooms.get(room_code)

        if not room:

            send_message(
                chat_id,
                "⚠️ اتاق پیدا نشد."
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
                (
                    "⚠️ برای شروع بازی "
                    "حداقل ۲ بازیکن لازم است."
                )
            )

            return

        room["state"] = "playing"

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    "🚀 بازی شروع شد!\n\n"
                    f"👥 تعداد بازیکنان: "
                    f"{len(room['players'])}"
                ),
                get_main_menu()
            )

        start_new_round(room_code)

        return

    # =====================================================
    # انتخاب حقیقت
    # =====================================================

    if data.startswith("choose_truth_"):

        room_code = data.replace(
            "choose_truth_",
            "",
            1
        )

        room = rooms.get(room_code)

        if not room:
            return

        if room.get("phase") != "choosing_type":
            return

        if room.get("answerer") != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط پاسخ‌دهنده می‌تواند انتخاب کند."
            )

            return

        room["question_type"] = "truth"

        room["phase"] = "waiting_question"

        questioner = room["questioner"]

        for player_id in room["players"]:

            if player_id == questioner:

                send_message(
                    player_id,
                    (
                        "✍️ نوبت شماست!\n\n"
                        f"🎯 {get_name(room['answerer'])} "
                        "«حقیقت» را انتخاب کرده است.\n\n"
                        "لطفاً سوال خود را به صورت پیام ارسال کنید."
                    )
                )

            else:

                send_message(
                    player_id,
                    (
                        f"🎯 {get_name(room['answerer'])} "
                        "گزینه «حقیقت» را انتخاب کرد.\n\n"
                        f"⏳ منتظر سوال "
                        f"{get_name(questioner)} هستیم."
                    )
                )

        return

    # =====================================================
    # انتخاب جرئت
    # =====================================================

    if data.startswith("choose_dare_"):

        room_code = data.replace(
            "choose_dare_",
            "",
            1
        )

        room = rooms.get(room_code)

        if not room:
            return

        if room.get("phase") != "choosing_type":
            return

        if room.get("answerer") != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط پاسخ‌دهنده می‌تواند انتخاب کند."
            )

            return

        room["question_type"] = "dare"

        room["phase"] = "waiting_question"

        questioner = room["questioner"]

        for player_id in room["players"]:

            if player_id == questioner:

                send_message(
                    player_id,
                    (
                        "✍️ نوبت شماست!\n\n"
                        f"🔥 {get_name(room['answerer'])} "
                        "«جرئت» را انتخاب کرده است.\n\n"
                        "لطفاً چالش خود را به صورت پیام ارسال کنید."
                    )
                )

            else:

                send_message(
                    player_id,
                    (
                        f"🔥 {get_name(room['answerer'])} "
                        "گزینه «جرئت» را انتخاب کرد.\n\n"
                        f"⏳ منتظر چالش "
                        f"{get_name(questioner)} هستیم."
                    )
                )

        return

    # =====================================================
    # رأی مثبت
    # =====================================================

    if data.startswith("vote_yes_"):

        room_code = data.replace(
            "vote_yes_",
            "",
            1
        )

        register_vote(
            room_code,
            chat_id,
            "yes"
        )

        return

    # =====================================================
    # رأی منفی
    # =====================================================

    if data.startswith("vote_no_"):

        room_code = data.replace(
            "vote_no_",
            "",
            1
        )

        register_vote(
            room_code,
            chat_id,
            "no"
        )

        return


# =========================================================
# ثبت رأی
# =========================================================

def register_vote(room_code, voter_id, vote):

    room = rooms.get(room_code)

    if not room:
        return

    if room.get("phase") != "voting":

        send_message(
            voter_id,
            "⚠️ رأی‌گیری فعال نیست."
        )

        return

    eligible_voters = room.get(
        "eligible_voters",
        []
    )

    if voter_id not in eligible_voters:

        send_message(
            voter_id,
            "⚠️ شما نمی‌توانید در این دور رأی دهید."
        )

        return

    if voter_id in room["votes"]:

        send_message(
            voter_id,
            "⚠️ شما قبلاً در این دور رأی داده‌اید."
        )

        return

    room["votes"][voter_id] = vote

    vote_text = (
        "👍 تأیید"
        if vote == "yes"
        else "👎 رد"
    )

    send_message(
        voter_id,
        (
            f"✅ رأی شما ثبت شد: {vote_text}\n\n"
            "⏳ منتظر رأی سایر بازیکنان..."
        )
    )

    check_voting_finished(room_code)


# =========================================================
# پردازش Update
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
            f"Handle Update Error: {error}"
        )


# =========================================================
# Long Polling
# =========================================================

def run_polling():

    offset = 0

    print("🤖 Bale Bot polling started...")

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

            if response.status_code != 200:

                print(
                    f"Polling HTTP Error: "
                    f"{response.status_code}"
                )

                time.sleep(3)

                continue

            data = response.json()

            if not data.get("ok", False):

                print(
                    f"Bale API Error: {data}"
                )

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
# اجرای وب سرور
# =========================================================

def run_web_server():

    app.run(
        host="0.0.0.0",
        port=PORT,
        debug=False,
        use_reloader=False
    )


# =========================================================
# اجرای برنامه
# =========================================================

if __name__ == "__main__":

    print("🚀 Starting Bale Truth or Dare Bot...")

    polling_thread = threading.Thread(
        target=run_polling,
        daemon=True
    )

    polling_thread.start()

    run_web_server()
