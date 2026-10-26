import os
import random
import string
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

TOKEN = os.environ.get("BALE_TOKEN", "*******")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# پروفایل بازیکن‌ها: {user_id: {"name": str}}
profiles = {}

# وضعیت ثبت‌نام: {user_id: "waiting_for_name"}
pending_name = {}

# اتاق‌ها: {room_code: {...}}
rooms = {}


def gen_code():
    """تولید کد ۴ حرفی یکتا برای اتاق"""
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


def main_keyboard():
    return {
        "keyboard": [[{"text": "🎮 ساخت اتاق جدید"}, {"text": "🚪 ورود به اتاق"}]],
        "resize_keyboard": True
    }


def room_host_keyboard():
    return {
        "keyboard": [
            [{"text": "🚀 شروع بازی"}],
            [{"text": "🗑 حذف اتاق"}]
        ],
        "resize_keyboard": True
    }


def room_guest_keyboard():
    return {
        "keyboard": [[{"text": "🚪 خروج از اتاق"}]],
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
    # ---------- مرحله انتخاب اسم ----------
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
        send_message(chat_id, f"✅ خوش اومدی **{name}** جان!\nحالا می‌تونی اتاق بسازی یا به اتاق‌ها بپیوندی.", reply_markup=main_keyboard())
        return

    # ---------- شروع / ثبت‌نام ----------
    if text == "/start":
        if user_id in profiles:
            send_message(chat_id, f"سلام **{profiles[user_id]['name']}** جان! 👋", reply_markup=main_keyboard())
        else:
            pending_name[user_id] = True
            send_message(chat_id, "سلام! خوش اومدی به ربات جرات حقیقت چندنفره 🎮\n\nاول یه **اسم بازی** برای خودت انتخاب کن.\n⚠️ اسمت نباید تکراری باشه!\n\nاسم رو همینجا بفرست:")
        return

    name = profiles.get(user_id, {}).get("name", "بازیکن")

    # ---------- ساخت اتاق ----------
    if text == "🎮 ساخت اتاق جدید":
        # اگه کاربر توی اتاق دیگه‌ای هست
        for code, room in list(rooms.items()):
            if any(p["id"] == user_id for p in room["players"]):
                send_message(chat_id, f"تو الان توی اتاق `{code}` هستی! اول ازش خارج شو.")
                return
        code = gen_code()
        rooms[code] = {
            "host_id": user_id,
            "players": [{"id": user_id, "name": name}],
            "state": "waiting",
            "turn_index": 0,
            "asker_index": 0,
            "sub_state": None
        }
        send_message(chat_id,
            f"🎮 اتاق ساخته شد!\n\n📌 **کد اتاق:** `{code}`\n👑 میزبان: **{name}**\n\nاین کد رو به دوستات بده تا با گزینه «🚪 ورود به اتاق» بیان تو.\nوقتی همه جمع شدن، روی «🚀 شروع بازی» بزن.",
            reply_markup=room_host_keyboard())
        return

    # ---------- ورود به اتاق ----------
    if text == "🚪 ورود به اتاق":
        for code, room in list(rooms.items()):
            if any(p["id"] == user_id for p in room["players"]):
                send_message(chat_id, f"تو الان توی اتاق `{code}` هستی!")
                return
        send_message(chat_id, "کد اتاق رو بفرست (مثلاً: `A7XK`):")
        # وضعیت انتظار کد اتاق
        rooms["_pending_join_" + str(user_id)] = {"waiting": True}
        return

    # ---------- دریافت کد اتاق ----------
    if str(user_id) in [k.replace("_pending_join_", "") for k in rooms if k.startswith("_pending_join_")]:
        code = text.strip().upper()
        pending_key = "_pending_join_" + str(user_id)
        if pending_key in rooms:
            del rooms[pending_key]
        if code in rooms:
            room = rooms[code]
            if room["state"] != "waiting":
                send_message(chat_id, "این اتاق بازی‌ش شروع شده و نمی‌تونی وارد بشی!")
                return
            room["players"].append({"id": user_id, "name": name})
            send_message(chat_id, f"👤 **{name}** وارد اتاق `{code}` شد! ({len(room['players'])} نفر)", reply_markup=room_guest_keyboard())
            # اطلاع به میزبان
            send_message(room["host_id"], f"🔔 **{name}** به اتاقت پیوست! ({len(room['players'])} نفر)")
        else:
            send_message(chat_id, "❌ اتاقی با این کد پیدا نشد! دوباره کد رو بفرست یا گزینه «ورود به اتاق» رو بزن.")
        return

    # ---------- حذف اتاق ----------
    if text == "🗑 حذف اتاق":
        for code, room in list(rooms.items()):
            if room["host_id"] == user_id:
                # اطلاع به همه اعضا
                for p in room["players"]:
                    if p["id"] != user_id:
                        send_message(p["id"], f"🗑 اتاق `{code}` توسط میزبان حذف شد.", reply_markup=main_keyboard())
                del rooms[code]
                send_message(chat_id, f"🗑 اتاق `{code}` با موفقیت حذف شد.", reply_markup=main_keyboard())
                return
        send_message(chat_id, "تو میزبان هیچ اتاقی نیستی!")
        return

    # ---------- شروع بازی ----------
    if text == "🚀 شروع بازی":
        for code, room in rooms.items():
            if room["host_id"] == user_id and room["state"] == "waiting":
                if len(room["players"]) < 2:
                    send_message(chat_id, "حداقل باید ۲ نفر توی اتاق باشین!")
                    return
                room["state"] = "playing"
                send_message(chat_id, f"🚀 بازی توی اتاق `{code}` شروع شد!")
                start_new_round(code)
                return
        send_message(chat_id, "شما میزبان اتاقی که بازی‌ش شروع نشده نیستید!")
        return

    # ---------- خروج از اتاق ----------
    if text == "🚪 خروج از اتاق":
        for code, room in list(rooms.items()):
            for p in room["players"]:
                if p["id"] == user_id:
                    room["players"].remove(p)
                    send_message(chat_id, f"از اتاق `{code}` خارج شدی.", reply_markup=main_keyboard())
                    if room["host_id"] == user_id:
                        # میزبان خارج شد => حذف اتاق
                        for q in room["players"]:
                            send_message(q["id"], f"🗑 میزبان اتاق `{code}` خارج شد و اتاق حذف شد.", reply_markup=main_keyboard())
                        del rooms[code]
                    else:
                        send_message(room["host_id"], f"👋 **{p['name']}** اتاق رو ترک کرد. ({len(room['players'])} نفر)")
                    return
        send_message(chat_id, "تو توی هیچ اتاقی نیستی!")
        return

    # ---------- پیام‌های داخل بازی ----------
    for code, room in rooms.items():
        if room["state"] == "playing" and any(p["id"] == user_id for p in room["players"]):
            target = room["players"][room["turn_index"]]
            asker = room["players"][room["asker_index"]]
            if user_id == asker["id"] and room.get("sub_state") == "waiting_for_question":
                room["sub_state"] = "waiting_for_answer"
                send_message(chat_id, f"❓ **سوال برای {target['name']}:**\n\n_{text}_\n\nحالا جواب بده!")
                return
            if user_id == target["id"] and room.get("sub_state") == "waiting_for_answer":
                send_message(chat_id, f"✅ جواب **{target['name']}** ثبت شد! بریم راند بعدی...")
                room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
                room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
                start_new_round(code)
                return


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
            f"🎯 اتاق `{code}`\nنوبت: **{target['name']}**\nپرسشگر: **{asker['name']}**\n\nجرات یا حقیقت؟",
            reply_markup=keyboard)


def handle_callback(chat_id, user_id, data):
    for code, room in rooms.items():
        if room["state"] == "playing":
            target = room["players"][room["turn_index"]]
            if user_id == target["id"]:
                choice_text = "حقیقت 🤫" if data == "truth" else "جرات 😈"
                asker = room["players"][room["asker_index"]]
                room["sub_state"] = "waiting_for_question"
                for p in room["players"]:
                    send_message(p["id"],
                        f"🔔 **{target['name']}** گزینه **{choice_text}** رو انتخاب کرد!\n\nحالا **{asker['name']}** سوالش رو بفرسته.")
                return


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
