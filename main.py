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
        "لطفاً آن را در Environment Variables رندر قرار دهید."
    )

BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
PORT = int(os.getenv("PORT", 10000))


# =========================================================
# وب‌سرور برای Render
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
# اطلاعات موقت ربات
# توجه: با ری‌استارت شدن Render پاک می‌شوند.
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

    except requests.RequestException as e:
        print(f"API Request Error [{method}]: {e}")
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


def edit_message_text(
    chat_id,
    message_id,
    text,
    reply_markup=None
):

    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return api_request(
        "editMessageText",
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
# منوی اصلی
# =========================================================

def get_main_menu():

    return {
        "inline_keyboard": [
            [
                {
                    "text": "🎮 اتاق‌های آنلاین",
                    "callback_data": "menu_online"
                },
                {
                    "text": "🤖 بازی تک‌نفره",
                    "callback_data": "menu_single"
                }
            ],
            [
                {
                    "text": "🏆 جدول امتیازات",
                    "callback_data": "leaderboard"
                },
                {
                    "text": "✏️ تغییر نام مستعار",
                    "callback_data": "change_name"
                }
            ],
            [
                {
                    "text": "📢 کانال اطلاع‌رسانی",
                    "url": "https://ble.ir/ettelae_resani"
                },
                {
                    "text": "💡 پشتیبانی و انتقادات",
                    "url": "https://ble.ir/KIA_karfarma"
                }
            ]
        ]
    }


# =========================================================
# انتخاب مود بازی
# =========================================================

def get_game_modes_keyboard():

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
                    "callback_data": "back_to_menu"
                }
            ]
        ]
    }


# =========================================================
# سوال‌ها و چالش‌ها
# =========================================================

def get_random_prompt(mode, prompt_type):

    prompts = {
        "normal": {
            "truth": [
                "بزرگ‌ترین سوتی زندگیت چی بوده؟",
                "بیشتر از همه به چه چیزی می‌خندی؟",
                "عجیب‌ترین عادتی که داری چیه؟"
            ],
            "dare": [
                "یک وویس کوتاه با صدای خنده‌دار بفرست.",
                "یک جمله بامزه درباره خودت بنویس."
            ]
        },

        "fun": {
            "truth": [
                "عجیب‌ترین جایی که خوابت برده کجا بوده؟",
                "خنده‌دارترین خاطره‌ای که داری چیست؟"
            ],
            "dare": [
                "سه ویژگی بامزه درباره خودت بگو.",
                "یک پیام کاملاً خنده‌دار برای گروه بنویس."
            ]
        },

        "scary": {
            "truth": [
                "ترسناک‌ترین تجربه‌ای که در تاریکی داشتی چی بوده؟",
                "کدام فیلم یا داستان بیشتر از همه تو را ترسانده؟"
            ],
            "dare": [
                "یک داستان کوتاه و مرموز تایپ کن.",
                "یک وویس با لحن مرموز بفرست."
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
# بازی تک‌نفره
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
        "حقیقت 🎯"
        if chosen_type == "truth"
        else "جرئت 🔥"
    )

    prompt = get_random_prompt(
        game["mode"],
        chosen_type
    )

    send_message(
        chat_id,
        (
            f"🤖 حالت تک‌نفره\n"
            f"🎮 مود: {game['mode']}\n\n"
            f"🎡 نتیجه:\n{type_name}\n\n"
            f"📝 چالش:\n{prompt}\n\n"
            "پاسخ یا مدرک انجام چالش را ارسال کنید."
        )
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
# ارسال نوبت اتاق آنلاین
# =========================================================

def notify_room_turn(room_code):

    if room_code not in rooms:
        return

    room = rooms[room_code]
    turn_player = room.get("current_turn")

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
                    f"🎯 نوبت شماست!\n"
                    f"🏠 اتاق: {room_code}\n\n"
                    "برای انتخاب چالش روی دکمه زیر بزنید:"
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
                f"⏳ نوبت {nickname} است..."
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

    current_player = room["current_turn"]

    if current_player in players:
        current_index = players.index(current_player)
    else:
        current_index = -1

    next_index = (
        current_index + 1
    ) % len(players)

    room["current_turn"] = players[next_index]

    room.pop("waiting_vote_for", None)
    room.pop("voting_active", None)

    notify_room_turn(room_code)


# =========================================================
# پردازش پیام
# =========================================================

def handle_message(msg):

    chat_id = msg.get("chat", {}).get("id")

    if not chat_id:
        return

    text = msg.get("text", "").strip()

    # ثبت نام

    if chat_id not in profiles:

        if chat_id in pending_name:

            if not text:

                send_message(
                    chat_id,
                    "⚠️ لطفاً یک نام مستعار وارد کنید."
                )

                return

            profiles[chat_id] = text
            pending_name.discard(chat_id)

            send_message(
                chat_id,
                f"🎉 خوش آمدی {text} عزیز!",
                get_main_menu()
            )

        else:

            pending_name.add(chat_id)

            send_message(
                chat_id,
                (
                    "سلام! 👋🎮\n"
                    "به ربات جرئت یا حقیقت خوش اومدی.\n\n"
                    "لطفاً یک نام مستعار وارد کن:"
                )
            )

        return

    # تغییر نام

    if chat_id in pending_new_name:

        if text:

            profiles[chat_id] = text
            pending_new_name.discard(chat_id)

            send_message(
                chat_id,
                "✅ نام مستعار با موفقیت تغییر کرد.",
                get_main_menu()
            )

        else:

            send_message(
                chat_id,
                "⚠️ لطفاً یک نام معتبر وارد کنید."
            )

        return

    # شروع

    if text == "/start":

        send_message(
            chat_id,
            (
                f"سلام {profiles[chat_id]} عزیز! 👋\n\n"
                "یک گزینه را انتخاب کن:"
            ),
            get_main_menu()
        )

        return

    # بازی تک‌نفره

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
                "✅ آفرین!\n"
                "🌟 ۱۰ امتیاز گرفتی."
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
                            "text": "🔙 منوی اصلی",
                            "callback_data": "back_to_menu"
                        }
                    ]
                ]
            }
        )

        return

    # پاسخ در اتاق آنلاین

    for room_code, room in list(rooms.items()):

        if (
            room.get("state") == "playing"
            and room.get("current_turn") == chat_id
        ):

            if room.get("voting_active"):
                return

            room["waiting_vote_for"] = chat_id
            room["voting_active"] = True

            nickname = profiles.get(
                chat_id,
                "بازیکن"
            )

            content = text or "[عکس / ویس / فایل]"

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
                                    "text": "👍 بله",
                                    "callback_data": (
                                        f"vote_yes_{room_code}"
                                    )
                                },
                                {
                                    "text": "👎 خیر",
                                    "callback_data": (
                                        f"vote_no_{room_code}"
                                    )
                                }
                            ]
                        ]
                    }
                )

            return


# =========================================================
# پردازش دکمه‌ها
# =========================================================

def handle_callback(query):

    callback_id = query.get("id")

    answer_callback_query(callback_id)

    message = query.get("message", {})

    chat_id = message.get(
        "chat",
        {}
    ).get("id")

    message_id = message.get("message_id")

    data = query.get("data", "")

    if not chat_id:
        return

    # بازگشت

    if data == "back_to_menu":

        user_states.pop(chat_id, None)

        edit_message_text(
            chat_id,
            message_id,
            "🏠 منوی اصلی:",
            get_main_menu()
        )

        return

    # تغییر نام

    if data == "change_name":

        pending_new_name.add(chat_id)

        send_message(
            chat_id,
            "✏️ نام مستعار جدید را وارد کنید:"
        )

        return

    # جدول امتیازات

    if data == "leaderboard":

        sorted_scores = sorted(
            scores.items(),
            key=lambda item: item[1],
            reverse=True
        )[:10]

        text = "🏆 جدول امتیازات\n\n"

        if not sorted_scores:

            text += "هنوز امتیازی ثبت نشده است."

        else:

            for index, (
                player_id,
                score
            ) in enumerate(sorted_scores, 1):

                name = profiles.get(
                    player_id,
                    "ناشناس"
                )

                text += (
                    f"{index}. {name} — "
                    f"{score} امتیاز\n"
                )

        send_message(
            chat_id,
            text,
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🔙 بازگشت",
                            "callback_data": "back_to_menu"
                        }
                    ]
                ]
            }
        )

        return

    # بازی تک‌نفره

    if data == "menu_single":

        user_states[chat_id] = (
            "choosing_single_mode"
        )

        send_message(
            chat_id,
            "🎮 مود بازی را انتخاب کنید:",
            get_game_modes_keyboard()
        )

        return

    # انتخاب مود

    if (
        data.startswith("mode_")
        and user_states.get(chat_id)
        in [
            "choosing_single_mode",
            "choosing_room_mode"
        ]
    ):

        mode = data.replace("mode_", "", 1)

        state = user_states.get(chat_id)

        if state == "choosing_single_mode":

            single_player[chat_id] = {
                "mode": mode,
                "waiting_for_proof": False
            }

            user_states[chat_id] = "playing_single"

            start_single_game_turn(chat_id)

            return

        if state == "choosing_room_mode":

            room_code = generate_room_code()

            rooms[room_code] = {
                "host": chat_id,
                "players": [chat_id],
                "state": "waiting",
                "current_turn": None,
                "mode": mode
            }

            user_states.pop(chat_id, None)

            send_message(
                chat_id,
                (
                    "✅ اتاق ساخته شد!\n\n"
                    f"🔢 کد اتاق: {room_code}\n"
                    f"🎮 مود: {mode}"
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
                        ],
                        [
                            {
                                "text": "🗑️ حذف اتاق",
                                "callback_data": (
                                    f"delete_room_{room_code}"
                                )
                            }
                        ]
                    ]
                }
            )

            return

    # چالش بعدی

    if data == "single_play_start":

        start_single_game_turn(chat_id)

        return

    # اتاق آنلاین

    if data == "menu_online":

        send_message(
            chat_id,
            "🎮 اتاق‌های آنلاین:",
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "🛠️ ساخت اتاق جدید",
                            "callback_data": "create_room"
                        }
                    ],
                    [
                        {
                            "text": "🚪 پیوستن به اتاق",
                            "callback_data": "list_rooms"
                        }
                    ],
                    [
                        {
                            "text": "🔙 بازگشت",
                            "callback_data": "back_to_menu"
                        }
                    ]
                ]
            }
        )

        return

    # ساخت اتاق

    if data == "create_room":

        user_states[chat_id] = (
            "choosing_room_mode"
        )

        send_message(
            chat_id,
            "🎮 مود اتاق را انتخاب کنید:",
            get_game_modes_keyboard()
        )

        return

    # لیست اتاق‌ها

    if data == "list_rooms":

        keyboard = []

        for room_code, room in rooms.items():

            if room.get("state") == "waiting":

                count = len(room["players"])

                keyboard.append(
                    [
                        {
                            "text": (
                                f"اتاق {room_code} "
                                f"({count} بازیکن)"
                            ),
                            "callback_data": (
                                f"join_room_{room_code}"
                            )
                        }
                    ]
                )

        if not keyboard:

            send_message(
                chat_id,
                "❌ هیچ اتاق فعالی وجود ندارد."
            )

            return

        send_message(
            chat_id,
            "🚪 اتاق‌های موجود:",
            {
                "inline_keyboard": keyboard
            }
        )

        return

    # پیوستن به اتاق

    if data.startswith("join_room_"):

        room_code = data.replace(
            "join_room_",
            "",
            1
        )

        if room_code not in rooms:

            send_message(
                chat_id,
                "⚠️ اتاق پیدا نشد."
            )

            return

        room = rooms[room_code]

        if room.get("state") != "waiting":

            send_message(
                chat_id,
                "⚠️ بازی این اتاق شروع شده است."
            )

            return

        if chat_id not in room["players"]:

            room["players"].append(chat_id)

        send_message(
            chat_id,
            f"✅ به اتاق {room_code} پیوستید."
        )

        send_message(
            room["host"],
            (
                f"👤 بازیکن "
                f"{profiles.get(chat_id, 'ناشناس')} "
                "به اتاق پیوست."
            )
        )

        return

    # شروع بازی اتاق

    if data.startswith("start_room_"):

        room_code = data.replace(
            "start_room_",
            "",
            1
        )

        if room_code not in rooms:
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
                "⚠️ حداقل ۲ بازیکن لازم است."
            )

            return

        room["state"] = "playing"
        room["current_turn"] = room["players"][0]

        notify_room_turn(room_code)

        return

    # حذف اتاق

    if data.startswith("delete_room_"):

        room_code = data.replace(
            "delete_room_",
            "",
            1
        )

        if room_code not in rooms:
            return

        room = rooms[room_code]

        if room["host"] != chat_id:

            send_message(
                chat_id,
                "⚠️ فقط میزبان می‌تواند اتاق را حذف کند."
            )

            return

        for player_id in room["players"]:

            send_message(
                player_id,
                "❌ اتاق توسط میزبان بسته شد."
            )

        del rooms[room_code]

        return

    # چرخ شانس

    if data.startswith("spin_wheel_"):

        room_code = data.replace(
            "spin_wheel_",
            "",
            1
        )

        if room_code not in rooms:
            return

        room = rooms[room_code]

        if room["current_turn"] != chat_id:

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
            "حقیقت 🎯"
            if chosen_type == "truth"
            else "جرئت 🔥"
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
                    f"🎯 {type_name}\n\n"
                    f"📝 {prompt}\n\n"
                    "پاسخ را ارسال کنید."
                )
            )

        return

    # رأی مثبت

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

        send_message(
            chat_id,
            "✅ چالش تأیید شد."
        )

        next_room_turn(room_code)

        return

    # رأی منفی

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

        send_message(
            chat_id,
            "❌ چالش تأیید نشد."
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

    except Exception as e:

        print(
            f"Handle Update Error: {e}"
        )


# =========================================================
# Long Polling
# =========================================================

def run_polling():

    offset = 0

    print("🤖 Bot polling started...")

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

        except Exception as e:

            print(
                f"Polling Error: {e}"
            )

            time.sleep(5)


# =========================================================
# اجرای وب‌سرور
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

    print("🚀 Starting Bale Bot...")

    threading.Thread(
        target=run_polling,
        daemon=True
    ).start()

    run_web_server()
