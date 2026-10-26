import os
import random
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# توکن ربات بله خودت رو اینجا بگذار یا از Environment Variables بگیر
TOKEN = os.environ.get("BALE_TOKEN", "YOUR_BOT_TOKEN_HERE")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

# ساختار ذخیره اتاق‌ها و وضعیت بازی‌ها (در حافظه)
# کلید: شناسه چت گروه یا کاربر، مقدار: دیکشنری اطلاعات بازی
rooms = {}

def send_message(chat_id, text, reply_markup=None):
    """تابع کمکی برای ارسال پیام به بله"""
    url = f"{BASE_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"Error sending message: {e}")

@app.route(f"/{TOKEN}", methods=["POST"])
def webhook():
    """دریافت آپدیت‌ها از وب‌هوک بله"""
    update = request.get_json()
    if not update:
        return jsonify({"status": "ok"})

    # پردازش پیام‌ها یا کلیک روی دکمه‌ها
    if "message" in update:
        msg = update["message"]
        chat_id = msg["chat"]["id"]
        user_id = msg["from"]["id"]
        user_name = msg["from"].get("first_name", "بازیکن")
        text = msg.get("text", "")

        handle_text(chat_id, user_id, user_name, text)

    elif "callback_query" in update:
        query = update["callback_query"]
        chat_id = query["message"]["chat"]["id"]
        user_id = query["from"]["id"]
        data = query["data"]

        handle_callback(chat_id, user_id, data)

    return jsonify({"status": "ok"})

def handle_text(chat_id, user_id, user_name, text):
    """مدیریت پیام‌های متنی و دستورات"""
    global rooms

    if text == "/start":
        send_message(chat_id, "سلام کیا! خوش اومدی به ربات جرات حقیقت چندنفره.\nبرای شروع بازی در گروه، دستور `/newgame` رو بفرست.")
    
    elif text == "/newgame":
        # ساخت یک اتاق جدید
        rooms[chat_id] = {
            "players": [{"id": user_id, "name": user_name}],
            "state": "waiting_to_join", # وضعیت: در حال عضوگیری
            "turn_index": 0,
            "asker_index": 0,
            "current_target": None,
            "current_asker": None
        }
        send_message(chat_id, f"🎮 بازی جدید توسط **{user_name}** ساخته شد!\nبقیه بازیکن‌ها با دستور `/join` می‌تونن بیان تو بازی.\nوقتی همه اومدن، سازنده بازی دستور `/startgame` رو بفرسته.")

    elif text == "/join":
        if chat_id in rooms and rooms[chat_id]["state"] == "waiting_to_join":
            player_ids = [p["id"] for p in rooms[chat_id]["players"]]
            if user_id not in player_ids:
                rooms[chat_id]["players"].append({"id": user_id, "name": user_name})
                send_message(chat_id, f"👤 **{user_name}** به بازی پیوست! (تعداد کل: {len(rooms[chat_id]['players'])})")
            else:
                send_message(chat_id, f"تو قبلاً وارد بازی شدی {user_name} جان!")
        else:
            send_message(chat_id, "بازی فعالی برای پیوستن وجود نداره یا بازی شروع شده!")

    elif text == "/startgame":
        if chat_id in rooms and rooms[chat_id]["state"] == "waiting_to_join":
            if len(rooms[chat_id]["players"]) < 2:
                send_message(chat_id, "حداقل باید ۲ نفر باشید تا بازی شروع بشه!")
                return
            rooms[chat_id]["state"] = "playing"
            start_new_round(chat_id)
        else:
            send_message(chat_id, "دستور غیرمجاز!")

    else:
        # مدیریت متن‌های ارسالی در طول بازی (سوال پرسیدن یا جواب دادن)
        if chat_id in rooms and rooms[chat_id]["state"] == "playing":
            room = rooms[chat_id]
            current_target_id = room["players"][room["turn_index"]]["id"]
            current_asker_id = room["players"][room["asker_index"]]["id"]

            # اگر پیام از طرف پرسشگر بود و منتظر سوال بودیم
            if user_id == current_asker_id and room.get("sub_state") == "waiting_for_question":
                room["question"] = text
                room["sub_state"] = "waiting_for_answer"
                target_name = room["players"][room["turn_index"]]["name"]
                send_message(chat_id, f"❓ **سوال جدید برای {target_name}:**\n\n_{text}_\n\nحالا {target_name} باید جواب بده یا چالش رو انجام بده و پیامش رو بفرسته!")

            # اگر پیام از طرف کسی بود که باید جواب بده
            elif user_id == current_target_id and room.get("sub_state") == "waiting_for_answer":
                send_message(chat_id, f"✅ جواب ثبت شد!\n\nحالا می‌ریم سراغ راند بعدی...")
                # رفتن به راند بعد
                room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
                room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
                start_new_round(chat_id)

def start_new_round(chat_id):
    """شروع یک راند جدید و مشخص کردن پرسشگر و پاسخگو"""
    room = rooms[chat_id]
    target = room["players"][room["turn_index"]]
    asker = room["players"][room["asker_index"]]

    # جلوگیری از اینکه پرسشگر و پاسخگو خودش باشه
    if target["id"] == asker["id"]:
        room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
        asker = room["players"][room["asker_index"]]

    room["sub_state"] = "choosing_jd" # منتظر انتخاب جرات یا حقیقت

    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🤫 حقیقت", "callback_data": "truth"},
                {"text": "😈 جرات", "callback_data": "dare"}
            ]
        ]
    }

    send_message(chat_id, f"🎯 نوبت **{target["name"]}** هست!\nپرسشگر این راند: **{asker["name"]}**\n\n{target["name"]} عزیز، جرات رو انتخاب می‌کنی یا حقیقت؟", reply_markup=keyboard)

def handle_callback(chat_id, user_id, data):
    """مدیریت دکمه‌های شیشه‌ای (انتخاب جرات یا حقیقت)"""
    if chat_id in rooms and rooms[chat_id]["state"] == "playing":
        room = rooms[chat_id]
        current_target = room["players"][room["turn_index"]]

        # فقط همون کسی که نوبتشه حق داره دکمه رو بزنه
        if user_id != current_target["id"]:
            return

        choice_text = "حقیقت 🤫" if data == "truth" else "جرات 😈"
        asker = room["players"][room["asker_index"]]
        
        room["sub_state"] = "waiting_for_question"
        send_message(chat_id, f"🔔 **{current_target['name']}** گزینه **{choice_text}** رو انتخاب کرد!\n\nحالا **{asker['name']}** باید سوال یا چالش خودش رو به صورت متنی بفرسته.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
