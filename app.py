import os
import random
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

TOKEN = os.environ.get("BALE_TOKEN", "*******")
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"

rooms = {}

def send_message(chat_id, text, reply_markup=None):
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

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json()
    if not update:
        return jsonify({"status": "ok"})

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

@app.route("/", methods=["GET"])
def home():
    return "Bot is alive and running!"

def handle_text(chat_id, user_id, user_name, text):
    global rooms
    
    # دکمه ثابت پایین صفحه (Reply Keyboard)
    reply_keyboard = {
        "keyboard": [
            [{"text": "🎮 ساخت بازی جدید"}, {"text": "👤 پیوستن به بازی"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

    if text == "/start" or text == "سلام":
        send_message(chat_id, f"سلام کیا جان! خوش اومدی به ربات جرات حقیقت چندنفره.\nبرای شروع، از دکمه‌های پایین صفحه استفاده کن یا دستورات رو بفرست.", reply_markup=reply_keyboard)
    
    elif text == "🎮 ساخت بازی جدید" or text == "/newgame":
        rooms[chat_id] = {
            "players": [{"id": user_id, "name": user_name}],
            "state": "waiting_to_join",
            "turn_index": 0,
            "asker_index": 0
        }
        # کیبورد برای پیوستن بقیه یا شروع بازی
        game_keyboard = {
            "keyboard": [
                [{"text": "👤 پیوستن به بازی"}, {"text": "🚀 شروع بازی"}]
            ],
            "resize_keyboard": True
        }
        send_message(chat_id, f"🎮 بازی جدید توسط **{user_name}** ساخته شد!\nبقیه بازیکن‌ها روی «پیوستن به بازی» بزنن.\nوقتی همه اومدن، روی «شروع بازی» بزنید.", reply_markup=game_keyboard)
    
    elif text == "👤 پیوستن به بازی" or text == "/join":
        if chat_id in rooms and rooms[chat_id]["state"] == "waiting_to_join":
            player_ids = [p["id"] for p in rooms[chat_id]["players"]]
            if user_id not in player_ids:
                rooms[chat_id]["players"].append({"id": user_id, "name": user_name})
                send_message(chat_id, f"👤 **{user_name}** به بازی پیوست!")
            else:
                send_message(chat_id, f"تو قبلاً وارد بازی شدی {user_name} جان!")
        else:
            send_message(chat_id, "هنوز بازی جدیدی ساخته نشده! اول روی «ساخت بازی جدید» بزن.")
            
    elif text == "🚀 شروع بازی" or text == "/startgame":
        if chat_id in rooms and rooms[chat_id]["state"] == "waiting_to_join":
            if len(rooms[chat_id]["players"]) < 2:
                send_message(chat_id, "حداقل باید ۲ نفر باشید!")
                return
            rooms[chat_id]["state"] = "playing"
            start_new_round(chat_id)
    else:
        if chat_id in rooms and rooms[chat_id]["state"] == "playing":
            room = rooms[chat_id]
            current_target_id = room["players"][room["turn_index"]]["id"]
            current_asker_id = room["players"][room["asker_index"]]["id"]

            if user_id == current_asker_id and room.get("sub_state") == "waiting_for_question":
                room["sub_state"] = "waiting_for_answer"
                target_name = room["players"][room["turn_index"]]["name"]
                send_message(chat_id, f"❓ **سوال برای {target_name}:**\n\n_{text}_\n\nحالا جواب بده!")
            elif user_id == current_target_id and room.get("sub_state") == "waiting_for_answer":
                send_message(chat_id, f"✅ ثبت شد! بریم راند بعدی...")
                room["turn_index"] = (room["turn_index"] + 1) % len(room["players"])
                room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
                start_new_round(chat_id)

def start_new_round(chat_id):
    room = rooms[chat_id]
    target = room["players"][room["turn_index"]]
    asker = room["players"][room["asker_index"]]
    if target["id"] == asker["id"]:
        room["asker_index"] = (room["asker_index"] + 1) % len(room["players"])
        asker = room["players"][room["asker_index"]]

    room["sub_state"] = "choosing_jd"
    
    # کیبورد شیشه‌ای برای انتخاب جرات یا حقیقت
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "🤫 حقیقت", "callback_data": "truth"},
                {"text": "😈 جرات", "callback_data": "dare"}
            ]
        ]
    }
    send_message(chat_id, f"🎯 نوبت **{target['name']}** هست!\nپرسشگر: **{asker['name']}**\n\nجرات یا حقیقت؟", reply_markup=keyboard)

def handle_callback(chat_id, user_id, data):
    if chat_id in rooms and rooms[chat_id]["state"] == "playing":
        room = rooms[chat_id]
        current_target = room["players"][room["turn_index"]]
        if user_id != current_target["id"]:
            return
        choice_text = "حقیقت 🤫" if data == "truth" else "جرات 😈"
        asker = room["players"][room["asker_index"]]
        room["sub_state"] = "waiting_for_question"
        send_message(chat_id, f"🔔 **{current_target['name']}** گزینه **{choice_text}** رو انتخاب کرد!\n\nحالا **{asker['name']}** سوالش رو بفرسته.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
