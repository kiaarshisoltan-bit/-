import os
import random
import string
import threading
import time
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

TOKEN = os.environ.get("BALE_TOKEN", "*******")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "https://jorat-bot.onrender.com")

# آیدی کانال اطلاع‌رسانی
CHANNEL_ID = "@ettelae_resani"

# متغیرهای حافظه
profiles = {}
pending_name = {}
rooms = {}
single_player = {}

# بانک سوالات و چالش‌های تک‌نفره پیش‌فرض ربات
BOT_TRUTHS = [
    "بزرگترین گند زندگیت چی بوده که هنوز کسی نفهمیده؟ 😂",
    "اگه مجبور باشی بینگ و یاهو رو برای همیشه حذف کنی کدومو انتخاب می‌کنی؟",
    "تا حالا شده چیزی رو از مغازه کش بری؟ چی بوده؟ 🤨",
    "خجالت‌آورترین خاطره دوران مدرسه‌ت چی بوده؟",
    "اگه غیب بشی، اولین جایی که میری کجاست و چیکار می‌کنی؟",
    "تا حالا توی اتاق در بسته با خودت حرف زدی و رقصیدی؟ 🕺",
    "آخرین دروغ بزرگی که گفتی چی بوده و به کی گفتی؟"
]

BOT_DARES = [
    "📷 یک عکس از سقف اتاقت همین الان بگیر و بفرست!",
    "💬 یک ویس بفرست و توش مثل اردک صحبت کن! 🦆",
    "😂 خنده‌دارترین عکسی که توی گوشیت داری رو همین الان بفرست.",
    "✍️ توی یک پیام، ۳ تا از عجیب‌ترین عادت‌هات رو بنویس.",
    "📱 اسم آخرین کسی که بهش پیام دادی رو بگو و بگو آخرین چت‌تون چی بوده.",
    "🕺 یک ویدیو یا عکس از خودت وقتی داری ادا یک ربات رو درمیاری بفرست!"
]


def keep_alive():
    while True:
        try:
            time.sleep(240)
            requests.get(RENDER_URL)
            print("Self-ping sent to keep bot awake!")
        except Exception as e:
            print(f"Keep-alive error: {e}")

threading.Thread(target=keep_alive, daemon=True).start()


def gen_code():
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
        if code not in rooms:
            return code


def send_message(chat_id, text, reply_markup=None):
    url = f"{BASE_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")


def send_photo(chat_id, photo_id, caption=""):
    url = f"{BASE_URL}/sendPhoto"
    payload = {"chat_id": chat_id, "photo": photo_id, "caption": caption, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending photo: {e}")


def main_keyboard():
    return {
        "keyboard": [
            [{"text": "🎮 ساخت اتاق جدید"}, {"text": "🚪 ورود به اتاق"}],
            [{"text": "🤖 بازی تک‌نفره (با ربات)"}],
            [{"text": "📢 کانال اطلاع‌رسانی"}, {"text": "💡 پشتیبانی و نظرات"}]
        ],
        "resize_keyboard": True
    }


def room_host_keyboard():
    return {
        "keyboard": [
            [{"text": "🚀 شروع بازی"}, {"text": "🗑 حذف اتاق"}],
            [{"text": "📢 کانال اطلاع‌رسانی"}, {"text": "💡 پشتیبانی و نظرات"}]
        ],
        "resize_keyboard": True
    }


def room_guest_keyboard():
    return {
        "keyboard": [
            [{"text": "🚪 خروج از اتاق"}],
            [{"text": "📢 کانال اطلاع‌رسانی"}, {"text": "💡 پشتیبانی و نظرات"}]
        ],
        "resize_keyboard": True
    }


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "ok"})

    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        text = msg.get("text", "")
        
        photo_list = msg.get("photo")
        photo_id = None
        if photo_list:
            photo_id = photo_list[-1].get("file_id")
            caption = msg.get("caption", "")
            handle_game_input(chat_id, user_id, text=caption, photo_id=photo_id)
        else:
            handle_text(chat_id, user_id, text)

    elif "callback_query" in update:
        query = update["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        user_id = query["from"]["id"]
        data = query["data"]
        handle_callback(chat_id, user_id, data)

    return jsonify({"status": "ok"})


@app.route("/", methods=["GET"])
def home():
    return "Bot is alive and running!"


def handle_text(chat_id, user_id, text):
    if text == "📢 کانال اطلاع‌رسانی":
        send_message(chat_id, 
            f"📢 **کانال رسمی اطلاع‌رسانی ربات:**\n\nبرای باخبر شدن از آپدیت‌ها، کدهای جایزه و خبرهای جدید، حتماً تو کانال ما عضو بشید:\n\n🔗 لینک کانال: `{CHANNEL_ID}`")
        return

    if text == "💡 پشتیبانی و نظرات":
        send_message(chat_id, 
            "💡 **ارسال ایده، گزارش مشکل و نظرات:**\n\nاگر باگ یا مشکلی دیدین، یا ایده‌ای برای بهتر شدن ربات دارید، می‌تونید به سازنده ربات پیام بدید:\n\n📩 آیدی ارتباطی: `@KIA_karfarma`")
        return

    if user_id in pending_name:
        name = text.strip()
        if len(name) < 2:
            send_message(chat_id, "اسم خیلی کوتاهه! یه اسم با حداقل ۲ حرف بفرست:")
            return
        if any(p["name"] == name for p in profiles.values()):
            send_message(chat_id, "😬 این اسم قبلاً توسط بازیکن دیگه‌ای انتخاب شده! یه اسم دیگه بچین:")
            return
        profiles[user_id] = {"name": name}
        del pending_name[user_id]
        send_message(chat_id, f"✅ خوش اومدی **{name}** جان!\nحالا می‌تونی اتاق بسازی، به اتاق‌ها بپیوندی یا با ربات تک‌نفره بازی کنی.", reply_markup=main_keyboard())
        return

    if text == "/start":
        if user_id in profiles:
            send_message(chat_id, f"سلام **{profiles[user_id]['name']}** جان! 👋", reply_markup=main_keyboard())
        else:
            pending_name[user_id] = True
            send_message(chat_id, "سلام! خوش اومدی به ربات جرات حقیقت 🎮\n\nاول یه **اسم بازی** برای خودت انتخاب کن.\n⚠️ اسمت نباید تکراری باشه!\n\nاسم رو همینجا بفرست:")
        return

    if user_id in single_player and single_player[user_id].get("state") == "waiting_for_answer":
        send_message(chat_id, "✨ عالی بود! چه جواب خفنی دادی. 😎\nمی‌خوای بازم با ربات بازی کنی یا برگردی منو؟", reply_markup={
            "inline_keyboard": [
                [{"text": "🔄 راند بعدی با ربات", "callback_data": "sp_again"},
                 {"text": "🏠 بازگشت به منوی اصلی", "callback_data": "sp_menu"}]
            ]
        })
        del single_player[user_id]
        return

    if handle_game_input(chat_id, user_id, text=text, photo_id=None):
        return

    if text == "🤖 بازی تک‌نفره (با ربات)":
        single_player[user_id] = {"state": "choosing"}
        keyboard = {
            "inline_keyboard": [
                [{"text": "🤫 حقیقت (با ربات)", "callback_data": "sp_truth"},
                 {"text": "😈 جرات (با ربات)", "callback_data": "sp_dare"}]
            ]
        }
        send_message(chat_id, "🤖 بخش بازی تک‌نفره با ربات!\n\nمن حریف تمرینی تو هستم. می‌خوای حقیقت رو انتخاب کنی یا جرات؟", reply_markup=keyboard)
        return

    if text == "🎮 ساخت اتاق جدید":
        for code, room in list(rooms.items()):
            if any(p["id"] == user_id for p in room["players"]):
                send_message(chat_id, f"تو الان توی اتاق `{code}` هستی! اول ازش خارج شو.")
                return
        code = gen_code()
        name = profiles.get(user_id, {}).get("name", "بازیکن")
        rooms[code] = {
            "host_id": user_id,
            "players": [{"id": user_id, "name": name}],
            "state": "waiting",
            "turn_index": 0,
            "asker_index": 0,
            "sub_state": None
        }
        send_message(chat_id,
            f"🎮 اتاق ساخته شد!\n\n📌 **کد اتاق:** `{code}`\n👑 میزبان: **{name}**\n\nبا دکمه «ورود به اتاق» بقیه می‌تونن لیست رو ببینن و بیان.\nوقتی همه جمع شدن، روی «🚀 شروع بازی» بزن.",
            reply_markup=room_host_keyboard())
        return

    if text == "🚪 ورود به اتاق":
        for code, room in list(rooms.items()):
            if any(p["id"] == user_id for p in room["players"]):
                send_message(chat_id, f"تو الان توی اتاق `{code}` هستی!")
                return
        
        waiting_rooms = {code: room for code, room in rooms.items() if room["state"] == "waiting"}
        if not waiting_rooms:
            send_message(chat_id, "❌ هیچ اتاق بازی‌ای در حال انتظار نیست! می‌تونی خودت یکی بسازی یا با ربات تک‌نفره بازی کنی.")
            return

        inline_buttons = []
        for code, room in waiting_rooms.items():
            host_name = room["players"][0]["name"]
            player_count = len(room["players"])
            inline_buttons.append([
                {"text": f"🏠 اتاق {code} (میزبان: {host_name} - {player_count} نفر)", "callback_data": f"join_{code}"}
            ])
        
        send_message(chat_id, "🚪 یکی از اتاق‌های زیر رو برای ورود انتخاب کن:", reply_markup={"inline_keyboard": inline_buttons})
        return

    if text == "🗑 حذف اتاق":
        for code, room in list(rooms.items()):
            if room["host_id"] == user_id:
                for p in room["players"]:
                    if p["id"] != user_id:
                        send_message(p["id"], f"🗑 اتاق `{code}` توسط میزبان حذف شد.", reply_markup=main_keyboard())
                del rooms[code]
                send_message(chat_id, f"🗑 اتاق `{code}` با موفقیت حذف شد.", reply_markup=main_keyboard())
                return
        send_message(chat_id, "تو میزبان هیچ اتاقی نیستی!")
        return

    if text == "🚀 شروع بازی":
        for code, room in rooms.items():
            if room["host_id"] == user_id and room["state"] == "waiting":
                if len(room["players"]) < 2:
                    send_message(chat_id, "حداقل باید ۲ نفر توی اتاق باشین! (اگه تنهائی می‌تونی از بخش تک‌نفره با ربات استفاده کنی)")
                    return
                room["state"] = "playing"
                send_message(chat_id, f"🚀 بازی توی اتاق `{code}` شروع شد!")
                start_new_round(code)
                return
        send_message(chat_id, "شما میزبان اتاقی که بازی‌ش شروع نشده نیستید!")
        return

    if text == "🚪 خروج از اتاق":
        for code, room in list(rooms.items()):
            for p in room["players"]:
                if p["id"] == user_id:
                    room["players"].remove(p)
                    if room["host_id"] == user_id:
                        for q in room["players"]:
                            send_message(q["id"], f"🗑 میزبان اتاق `{code}` خارج شد و اتاق حذف شد.", reply_markup=main_keyboard())
                        del rooms[code]
                    else:
                        send_message(room["host_id"], f"👋 **{p['name']}** اتاق رو ترک کرد. ({len(room['players'])} نفر)")
                    send_message(chat_id, f"از اتاق `{code}` خارج شدی.", reply_markup=main_keyboard())
                    return
        send_message(chat_id, "تو توی هیچ اتاقی نیستی!")
        return


def handle_game_input(chat_id, user_id, text, photo_id=None):
    for code, room in rooms.items():
        if room["state"] == "playing":
            if not any(p["id"] == user_id for p in room["players"]):
                continue

            target = room["players"][room["turn_index"]]
            asker = room["players"][room["asker_index"]]

            if user_id == asker["id"] and room.get("sub_state") == "waiting_for_question":
                if photo_id:
                    room["sub_state"] = "waiting_for_answer"
                    choice_label = room.get("last_choice", "سوال")
                    for p in room["players"]:
                        send_photo(p["id"], photo_id, caption=f"❓ **سوال تصویری ({choice_label}) از طرف {asker['name']} برای {target['name']}:**\n_{text}_\n\n👉 **{target['name']}**، حالا جواب یا عکس انجام جرات رو بفرست:")
                    return True
                elif text:
                    room["sub_state"] = "waiting_for_answer"
                    choice_label = room.get("last_choice", "سوال")
                    for p in room["players"]:
                        send_message(p["id"], f"❓ **سوال ({choice_label}) از طرف {asker['name']} برای {target['name']}:**\n\n_{text}_\n\n👉 **{target['name']}**، حالا جواب خودت رو بفرست:")
                    return True

            if user_id == target["id"] and room.get("sub_state") == "waiting_for_answer":
                if photo_id:
                    for p in room["players"]:
                        send_photo(p["id"], photo_id, caption=f"📸 **تصویر انجام جرات توسط {target['name']}:**\n_{text}_\n\n✨ این راند تمام شد! بریم راند بعدی...")
                else:
                    for p in room["players"]:
                        send_message(p["id"], f"💬 **پاسخ {target['name']}:**\n\n_{text}_\n\n✨ این راند تمام شد! بریم راند بعدی...")
                
                room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
                room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
                start_new_round(code)
                return True

    return False


def start_new_round(code):
    room = rooms[code]
    target = room["players"][room["turn_index"]]
    asker = room["players"][room["asker_index"]]
    if target["id"] == asker["id"] and len(room["players"]) > 1:
        room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
        asker = room["players"][room["asker_index"]]

    room["sub_state"] = "choosing_jd"
    
    keyboard = {
        "inline_keyboard": [
            [{"text": "🤫 حقیقت", "callback_data": "truth"},
             {"text": "😈 جرات", "callback_data": "dare"}]
        ]
    }
    for p in room["players"]:
        send_message(p["id"],
            f"🎯 اتاق `{code}`\n\n👤 نوبت انتخاب: **{target['name']}**\n❓ پرسشگر این راند: **{asker['name']}**\n\n**{target['name']}** عزیز، جرات یا حقیقت؟",
            reply_markup=keyboard)


def handle_callback(chat_id, user_id, data):
    if data == "sp_truth":
        q = random.choice(BOT_TRUTHS)
        single_player[user_id] = {"state": "waiting_for_answer"}
        send_message(chat_id, f"🤖 **حقیقت ربات برای تو:**\n\n_{q}_\n\n✍️ حالا جواب خودت رو برام بفرست:")
        return
    elif data == "sp_dare":
        d = random.choice(BOT_DARES)
        single_player[user_id] = {"state": "waiting_for_answer"}
        send_message(chat_id, f"🤖 **جرات ربات برای تو:**\n\n_{d}_\n\n👉 وقتی انجامش دادی، متن یا عکسش رو برام بفرست:")
        return
    elif data == "sp_again":
        single_player[user_id] = {"state": "choosing"}
        keyboard = {
            "inline_keyboard": [
                [{"text": "🤫 حقیقت (با ربات)", "callback_data": "sp_truth"},
                 {"text": "😈 جرات (با ربات)", "callback_data": "sp_dare"}]
            ]
        }
        send_message(chat_id, "دوباره انتخاب کن! حقیقت یا جرات؟", reply_markup=keyboard)
        return
    elif data == "sp_menu":
        if user_id in single_player:
            del single_player[user_id]
        send_message(chat_id, "به منوی اصلی برگشتی.", reply_markup=main_keyboard())
        return

    if data.startswith("join_"):
        code = data.split("_")[1]
        name = profiles.get(user_id, {}).get("name", "بازیکن")

        for c, r in rooms.items():
            if any(p["id"] == user_id for p in r["players"]):
                send_message(chat_id, f"تو الان توی اتاق `{c}` هستی!")
                return

        if code in rooms and rooms[code]["state"] == "waiting":
            room = rooms[code]
            room["players"].append({"id": user_id, "name": name})
            send_message(chat_id, f"👤 **{name}** وارد اتاق `{code}` شد! ({len(room['players'])} نفر)", reply_markup=room_guest_keyboard())
            send_message(room["host_id"], f"🔔 **{name}** به اتاقت پیوست! ({len(room['players'])} نفر)")
        else:
            send_message(chat_id, "❌ این اتاق دیگر وجود ندارد یا بازی‌ش شروع شده است!")
        return

    for code, room in rooms.items():
        if room["state"] == "playing":
            target = room["players"][room["turn_index"]]
            if user_id == target["id"] and room.get("sub_state") == "choosing_jd":
                choice_text = "حقیقت 🤫" if data == "truth" else "جرات 😈"
                room["last_choice"] = choice_text
                asker = room["players"][room["asker_index"]]
                room["sub_state"] = "waiting_for_question"
                
                for p in room["players"]:
                    send_message(p["id"],
                        f"🔔 **{target['name']}** گزینه **{choice_text}** رو انتخاب کرد!\n\n✍️ حالا **{asker['name']}** باید سوال یا چالش خودش رو برای **{target['name']}** بفرسته:")
                return


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
