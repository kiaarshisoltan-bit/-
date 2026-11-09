import os
import random
import threading
import time

import requests
from flask import Flask


# =========================================================
# تنظیمات اصلی
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError(
        "BOT_TOKEN تنظیم نشده است. "
        "لطفاً آن را در Environment Variables رندر وارد کنید."
    )

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
PORT = int(os.getenv("PORT", 10000))


# =========================================================
# وب سرور برای Render
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Bale Bot is running! 🤖"


@app.route("/health")
def health():
    return {
        "status": "ok",
        "message": "Bale bot is running"
    }


# =========================================================
# اطلاعات ربات
# =========================================================

profiles = {}

pending_name = set()
pending_new_name = set()

rooms = {}

single_player = {}

scores = {}

user_states = {}


# =========================================================
# ارتباط با API بله
# =========================================================

def api_request(method, payload=None, timeout=15):

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
            data = None

        if response.status_code != 200:

            print(
                f"API Error [{method}]: "
                f"{response.status_code} - {response.text}"
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

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return api_request(
        "sendMessage",
        payload
    )


def answer_callback_query(callback_query_id):

    if not callback_query_id:
        return

    api_request(
        "answerCallbackQuery",
        {
            "callback_query_id": callback_query_id
        }
    )


# =========================================================
# منوی اصلی دائمی پایین صفحه
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
# منوی انتخاب مود بازی
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
# منوی اتاق‌های آنلاین
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
# سوال‌ها و چالش‌ها
# =========================================================

def get_random_prompt(mode, prompt_type):

    prompts = {

        "normal": {

            "truth": [
                "بزرگ‌ترین سوتی زندگیت چی بوده؟ 😄",
                "بیشتر از همه به چه چیزی می‌خندی؟",
                "عجیب‌ترین عادتی که داری چیه؟",
                "دوست داری چه مهارتی یاد بگیری؟"
            ],

            "dare": [
                "یک جمله بامزه درباره خودت بنویس 😄",
                "سه ویژگی مثبت خودت را بنویس.",
                "یک پیام خنده‌دار برای دوستانت بنویس."
            ]
        },

        "fun": {

            "truth": [
                "خنده‌دارترین خاطره‌ای که داری چیست؟ 😂",
                "عجیب‌ترین جایی که خوابت برده کجا بوده؟",
                "بامزه‌ترین اتفاقی که برایت افتاده چه بوده؟"
            ],

            "dare": [
                "یک جمله کاملاً خنده‌دار بنویس 😂",
                "سه کلمه عجیب درباره خودت بگو.",
                "یک داستان کوتاه و بامزه بنویس."
            ]
        },

        "scary": {

            "truth": [
                "ترسناک‌ترین فیلمی که دیده‌ای چه بوده؟ 👻",
                "آیا تا حالا تجربه‌ای عجیب و مرموز داشته‌ای؟",
                "از چه چیزی بیشتر می‌ترسی؟"
            ],

            "dare": [
                "یک داستان کوتاه و مرموز بنویس 👻",
                "یک جمله با فضای رازآلود بنویس.",
                "یک داستان تخیلی کمی ترسناک تعریف کن."
            ]
        }
    }

    selected_mode = prompts.get(
        mode,
        prompts["normal"]
    )

    return random.choice(
        selected_mode[prompt_type]
    )


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
# نمایش جدول امتیازات
# =========================================================

def get_leaderboard_text():

    sorted_scores = sorted(
        scores.items(),
        key=lambda item: item[1],
        reverse=True
    )[:10]

    text = "🏆 جدول برترین‌ها 🏆\n\n"

    if not sorted_scores:

        text += "هنوز امتیازی ثبت نشده است."

        return text

    for index, (player_id, score) in enumerate(
        sorted_scores,
        1
    ):

        name = profiles.get(
            player_id,
            "ناشناس"
        )

        text += (
            f"{index}. {name} — "
            f"{score} امتیاز\n"
        )

    return text


# =========================================================
# شروع نوبت بازی تک‌نفره
# =========================================================

def start_single_game_turn(chat_id):

    if chat_id not in single_player:
        return

    game = single_player[chat_id]

    chosen_type = random.choice([
        "truth",
        "dare"
    ])

    game["current_type"] = chosen_type
    game["waiting_for_proof"] = True

    type_name = (
        "🎯 حقیقت"
        if chosen_type == "truth"
        else "🔥 جرئت"
    )

    prompt = get_random_prompt(
        game["mode"],
        chosen_type
    )

    send_message(
        chat_id,
        (
            "🤖 بازی تک‌نفره\n\n"
            f"🎡 نتیجه: {type_name}\n\n"
            f"📝 چالش:\n{prompt}\n\n"
            "✍️ پاسخ یا نتیجه انجام چالش را ارسال کنید."
        ),
        {
            "inline_keyboard": [
                [
                    {
                        "text": "⏭️ چالش بعدی",
                        "callback_data": "single_play_start"
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
# اطلاع‌رسانی نوبت اتاق آنلاین
# =========================================================

def notify_room_turn(room_code):

    if room_code not in rooms:
        return

    room = rooms[room_code]

    turn_player = room.get(
        "current_turn"
    )

    if not turn_player:
        return

    nickname = profiles.get(
        turn_player,
        "بازیکن"
    )

    for player_id in room["players"]:

        if player_id == turn_player:

            send_message(
                player_id,
                (
                    "🎯 نوبت شماست!\n\n"
                    f"🏠 اتاق: {room_code}\n\n"
                    "برای شروع نوبت، چرخ شانس را بچرخانید."
                ),
                {
                    "inline_keyboard": [
                        [
                            {
                                "text": "🎡 چرخش چرخ شانس",
                                "callback_data": (
                                    f"spin_wheel_{room_code}"
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
                    f"⏳ نوبت {nickname} است..."
                )
            )


# =========================================================
# نوبت بعدی اتاق
# =========================================================

def next_room_turn(room_code):

    if room_code not in rooms:
        return

    room = rooms[room_code]

    players = room["players"]

    if not players:
        return

    current_player = room.get(
        "current_turn"
    )

    if current_player in players:

        current_index = players.index(
            current_player
        )

    else:

        current_index = -1

    next_index = (
        current_index + 1
    ) % len(players)

    room["current_turn"] = players[next_index]

    room["waiting_vote_for"] = None
    room["voting_active"] = False

    notify_room_turn(room_code)


# =========================================================
# ورود به اتاق با متن
# =========================================================

def join_room_by_text(chat_id, text):

    if not text.startswith("🚪 اتاق "):
        return False

    try:

        room_code = text.split(
            "🚪 اتاق "
        )[1].split(" ")[0]

    except Exception:

        return False

    if room_code not in rooms:

        send_message(
            chat_id,
            "⚠️ این اتاق دیگر وجود ندارد.",
            get_online_rooms_menu()
        )

        return True

    room = rooms[room_code]

    if room.get("state") != "waiting":

        send_message(
            chat_id,
            "⚠️ بازی این اتاق شروع شده است.",
            get_online_rooms_menu()
        )

        return True

    if chat_id not in room["players"]:

        room["players"].append(chat_id)

    send_message(
        chat_id,
        (
            f"✅ به اتاق {room_code} پیوستید.\n"
            "⏳ منتظر شروع بازی توسط میزبان باشید."
        ),
        get_online_rooms_menu()
    )

    send_message(
        room["host"],
        (
            f"👤 {profiles.get(chat_id, 'یک بازیکن')} "
            "به اتاق شما پیوست."
        )
    )

    return True


# =========================================================
# پردازش پیام‌ها
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
                    "به ربات جرئت یا حقیقت خوش آمدی.\n\n"
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
            "✅ نام مستعار شما با موفقیت تغییر کرد.",
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
                f"سلام {profiles[chat_id]} عزیز! 👋\n\n"
                "از منوی پایین یک گزینه را انتخاب کن 👇"
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
            "🏠 منوی اصلی",
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
            "🎮 مود بازی را انتخاب کنید:",
            get_game_modes_keyboard()
        )

        return

    # -----------------------------------------------------
    # اتاق‌های آنلاین
    # -----------------------------------------------------

    if text == "🎮 اتاق‌های آنلاین":

        send_message(
            chat_id,
            "🎮 بخش اتاق‌های آنلاین:",
            get_online_rooms_menu()
        )

        return

    # -----------------------------------------------------
    # ساخت اتاق
    # -----------------------------------------------------

    if text == "🛠️ ساخت اتاق جدید":

        user_states[chat_id] = (
            "choosing_room_mode"
        )

        send_message(
            chat_id,
            "🎮 مود اتاق را انتخاب کنید:",
            get_game_modes_keyboard()
        )

        return

    # -----------------------------------------------------
    # انتخاب مود
    # -----------------------------------------------------

    mode = None

    if text == "🟢 معمولی و دوستانه":
        mode = "normal"

    elif text == "🔥 خفن و چالشی":
        mode = "fun"

    elif text == "👻 ترسناک و مرموز":
        mode = "scary"

    if mode:

        state = user_states.get(chat_id)

        # بازی تک‌نفره

        if state == "choosing_single_mode":

            single_player[chat_id] = {
                "mode": mode,
                "waiting_for_proof": False
            }

            user_states[chat_id] = "playing_single"

            start_single_game_turn(chat_id)

            return

        # ساخت اتاق

        if state == "choosing_room_mode":

            room_code = generate_room_code()

            rooms[room_code] = {
                "host": chat_id,
                "players": [chat_id],
                "state": "waiting",
                "current_turn": None,
                "mode": mode,
                "waiting_vote_for": None,
                "voting_active": False
            }

            user_states.pop(chat_id, None)

            send_message(
                chat_id,
                (
                    "✅ اتاق با موفقیت ساخته شد!\n\n"
                    f"🔢 کد اتاق: {room_code}\n\n"
                    "👥 منتظر بمانید تا بازیکنان دیگر وارد شوند."
                ),
                get_online_rooms_menu()
            )

            send_message(
                chat_id,
                (
                    "🎮 وقتی حداقل دو بازیکن وارد شدند، "
                    "از دکمه زیر بازی را شروع کنید."
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

        send_message(
            chat_id,
            "⚠️ ابتدا از منوی اصلی یک بخش را انتخاب کنید.",
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # پیوستن به اتاق
    # -----------------------------------------------------

    if text == "🚪 پیوستن به اتاق":

        keyboard = []

        for room_code, room in rooms.items():

            if room.get("state") == "waiting":

                count = len(room["players"])

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
            "🚪 یک اتاق را انتخاب کنید:",
            {
                "keyboard": keyboard,
                "resize_keyboard": True,
                "one_time_keyboard": False
            }
        )

        return

    # بررسی انتخاب یک اتاق

    if join_room_by_text(chat_id, text):
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
            "✏️ نام مستعار جدید خود را وارد کنید:"
        )

        return

    # -----------------------------------------------------
    # کانال اطلاع‌رسانی
    # -----------------------------------------------------

    if text == "📢 کانال اطلاع‌رسانی":

        send_message(
            chat_id,
            (
                "📢 کانال اطلاع‌رسانی:\n"
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
                "💬 پشتیبانی و ارتباط:\n"
                "https://ble.ir/KIA_karfarma"
            ),
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # بازی تک‌نفره - دریافت پاسخ
    # -----------------------------------------------------

    if (
        chat_id in single_player
        and single_player[chat_id].get(
            "waiting_for_proof"
        )
    ):

        single_player[chat_id][
            "waiting_for_proof"
        ] = False

        scores[chat_id] = (
            scores.get(chat_id, 0) + 10
        )

        send_message(
            chat_id,
            (
                "✅ آفرین! چالش ثبت شد.\n\n"
                "🌟 ۱۰ امتیاز دریافت کردی."
            ),
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🎲 چالش بعدی",
                            "callback_data": "single_play_start"
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

    # -----------------------------------------------------
    # دریافت پاسخ بازیکن در اتاق آنلاین
    # -----------------------------------------------------

    for room_code, room in list(rooms.items()):

        if (
            room.get("state") == "playing"
            and room.get("current_turn") == chat_id
            and not room.get("voting_active")
        ):

            room["waiting_vote_for"] = chat_id
            room["voting_active"] = True

            nickname = profiles.get(
                chat_id,
                "بازیکن"
            )

            content = text or "[پیام رسانه‌ای]"

            for player_id in room["players"]:

                send_message(
                    player_id,
                    (
                        f"📢 پاسخ {nickname}:\n\n"
                        f"💬 {content}\n\n"
                        "آیا چالش انجام شده است؟"
                    ),
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

            return

    # -----------------------------------------------------
    # پیام نامشخص
    # -----------------------------------------------------

    send_message(
        chat_id,
        (
            "🤔 این گزینه را متوجه نشدم.\n"
            "لطفاً از منوی پایین استفاده کنید."
        ),
        get_main_menu()
    )


# =========================================================
# پردازش دکمه‌های شیشه‌ای
# =========================================================

def handle_callback(query):

    callback_id = query.get("id")

    answer_callback_query(callback_id)

    message = query.get("message", {})

    chat_id = message.get(
        "chat",
        {}
    ).get("id")

    data = query.get("data", "")

    if not chat_id:
        return

    # -----------------------------------------------------
    # چالش بعدی تک‌نفره
    # -----------------------------------------------------

    if data == "single_play_start":

        if chat_id not in single_player:

            send_message(
                chat_id,
                "⚠️ ابتدا بازی تک‌نفره را شروع کنید.",
                get_main_menu()
            )

            return

        start_single_game_turn(chat_id)

        return

    # -----------------------------------------------------
    # پایان بازی تک‌نفره
    # -----------------------------------------------------

    if data == "single_end":

        single_player.pop(chat_id, None)

        user_states.pop(chat_id, None)

        send_message(
            chat_id,
            "🏠 بازی پایان یافت.",
            get_main_menu()
        )

        return

    # -----------------------------------------------------
    # شروع بازی اتاق
    # -----------------------------------------------------

    if data.startswith("start_room_"):

        room_code = data.replace(
            "start_room_",
            "",
            1
        )

        if room_code not in rooms:

            send_message(
                chat_id,
                "⚠️ این اتاق دیگر وجود ندارد.",
                get_online_rooms_menu()
            )

            return

        room = rooms[room_code]

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند بازی را شروع کند."
            )

            return

        if len(room["players"]) < 2:

            send_message(
                chat_id,
                "⚠️ برای شروع بازی حداقل ۲ بازیکن لازم است."
            )

            return

        room["state"] = "playing"

        room["current_turn"] = (
            room["players"][0]
        )

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    "🚀 بازی شروع شد!\n\n"
                    f"🏠 اتاق: {room_code}\n"
                    f"👥 تعداد بازیکنان: "
                    f"{len(room['players'])}"
                ),
                get_main_menu()
            )

        notify_room_turn(room_code)

        return

    # -----------------------------------------------------
    # چرخ شانس
    # -----------------------------------------------------

    if data.startswith("spin_wheel_"):

        room_code = data.replace(
            "spin_wheel_",
            "",
            1
        )

        if room_code not in rooms:
            return

        room = rooms[room_code]

        if room.get("state") != "playing":
            return

        if room.get("current_turn") != chat_id:

            send_message(
                chat_id,
                "⚠️ الان نوبت شما نیست."
            )

            return

        chosen_type = random.choice([
            "truth",
            "dare"
        ])

        type_name = (
            "🎯 حقیقت"
            if chosen_type == "truth"
            else "🔥 جرئت"
        )

        prompt = get_random_prompt(
            room["mode"],
            chosen_type
        )

        nickname = profiles.get(
            chat_id,
            "بازیکن"
        )

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    "🎡 چرخ شانس چرخید!\n\n"
                    f"👤 نوبت: {nickname}\n"
                    f"🎯 نتیجه: {type_name}\n\n"
                    f"📝 چالش:\n{prompt}\n\n"
                    "✍️ بازیکن باید پاسخ خود را ارسال کند."
                )
            )

        return

    # -----------------------------------------------------
    # رأی مثبت
    # -----------------------------------------------------

    if data.startswith("vote_yes_"):

        room_code = data.replace(
            "vote_yes_",
            "",
            1
        )

        if room_code not in rooms:
            return

        room = rooms[room_code]

        if not room.get("voting_active"):
            return

        turn_player = room.get(
            "waiting_vote_for"
        )

        if not turn_player:
            return

        scores[turn_player] = (
            scores.get(turn_player, 0) + 10
        )

        room["voting_active"] = False

        nickname = profiles.get(
            turn_player,
            "بازیکن"
        )

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    f"✅ چالش {nickname} تأیید شد!\n"
                    "🌟 ۱۰ امتیاز اضافه شد."
                )
            )

        next_room_turn(room_code)

        return

    # -----------------------------------------------------
    # رأی منفی
    # -----------------------------------------------------

    if data.startswith("vote_no_"):

        room_code = data.replace(
            "vote_no_",
            "",
            1
        )

        if room_code not in rooms:
            return

        room = rooms[room_code]

        if not room.get("voting_active"):
            return

        room["voting_active"] = False

        nickname = profiles.get(
            room.get("waiting_vote_for"),
            "بازیکن"
        )

        for player_id in room["players"]:

            send_message(
                player_id,
                (
                    f"❌ چالش {nickname} تأیید نشد."
                )
            )

        next_room_turn(room_code)

        return


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
                    f"HTTP Error: "
                    f"{response.status_code}"
                )

                time.sleep(3)

                continue

            data = response.json()

            if not data.get("ok"):

                print(
                    f"Bale API Error: {data}"
                )

                time.sleep(3)

                continue

            for update in data.get(
                "result",
                []
            ):

                update_id = update.get(
                    "update_id"
                )

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
# اجرای اصلی برنامه
# =========================================================

if __name__ == "__main__":

    print("🚀 Starting Bale Bot...")

    polling_thread = threading.Thread(
        target=run_polling,
        daemon=True
    )

    polling_thread.start()

    run_web_server()
