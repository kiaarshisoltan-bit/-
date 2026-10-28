import os
import threading
import time
import requests
import random
from flask import Flask

# --- تنظیمات وب‌سرور ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running! 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- تنظیمات ربات بله ---
BOT_TOKEN = "*******" # حتماً توکن خودت رو بذار
BASE_URL = "https://api.bale.ai/v1"

# دیتابیس‌ها (در پروژه‌های بزرگ این‌ها باید در فایل ذخیره بشن)
users_db = {}
rooms_db = {} # ساختار: { "1234": {"owner": id, "members": [id1, id2]} }

def send_message(chat_id, text):
    url = f"{BASE_URL}/messages/send"
    payload = {"chat_id": chat_id, "text": text}
    headers = {"Authorization": f"Bearer {BOT_TOKEN}", "Content-Type": "application/json"}
    try:
        requests.post(url, json=payload, headers=headers)
    except:
        pass

# --- منطق بازی (Logic) ---

def create_room(user_id):
    room_code = str(random.randint(1000, 9999))
    rooms_db[room_code] = {
        "owner": user_id,
        "members": [user_id]
    }
    return room_code

def join_room(user_id, room_code):
    if room_code in rooms_db:
        if user_id not in rooms_db[room_code]["members"]:
            rooms_db[room_code]["members"].append(user_id)
            # اطلاع به صاحب اتاق
            owner_id = rooms_db[room_code]["owner"]
            send_message(owner_id, f"🔔 یک بازیکن جدید وارد اتاق {room_code} شد!")
            return True
    return False

# --- حلقه اصلی دریافت پیام ---

def bot_loop():
    print("Bot loop started...")
    last_update_id = 0
    
    while True:
        url = f"{BASE_URL}/updates?offset={last_update_id + 1}"
        headers = {"Authorization": f"Bearer {BOT_TOKEN}"}
        
        try:
            response = requests.get(url, headers=headers)
            if response.status_code == 200:
                updates = response.json().get("result", [])
                for update in updates:
                    last_update_id = update.get("update_id")
                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "")

                        # دستورات پایه
                        if text == "/start":
                            send_message(chat_id, "سلام کیا عزیز! به ربات خوش اومدی. 🎮\n\n"
                                                 "دستورات:\n"
                                                 "/create_room - ساخت اتاق جدید\n"
                                                 "/rooms - لیست اتاق‌ها\n"
                                                 "/join [code] - ورود به اتاق\n"
                                                 "/leave - ترک اتاق")

                        # ساخت اتاق
                        elif text == "/create_room":
                            code = create_room(chat_id)
                            send_message(chat_id, f"✅ اتاق شما با موفقیت ساخته شد!\nکد اتاق: `{code}`\n\nارسال این کد برای دوستانت!")

                        # لیست اتاق‌ها
                        elif text == "/rooms":
                            if not rooms_db:
                                send_message(chat_id, "😔 فعلاً هیچ اتاق فعالی وجود ندارد.")
                            else:
                                room_list = "🎮 **لیست اتاق‌های فعال:**\n\n"
                                for code, data in rooms_db.items():
                                    room_list += f"🔹 کد: `{code}` | تعداد بازیکن: {len(data['members'])}\n"
                                send_message(chat_id, room_list)

                        # ورود به اتاق
                        elif text.startswith("/join"):
                            try:
                                parts = text.split(" ")
                                if len(parts) < 2:
                                    send_message(chat_id, "❌ لطفاً کد اتاق را هم وارد کنید.\nمثال: `/join 1234`")
                                else:
                                    code = parts[1]
                                    if join_room(chat_id, code):
                                        send_message(chat_id, f"🎉 تبریک! وارد اتاق `{code}` شدی.")
                                    else:
                                        send_message(chat_id, "❌ کد اتاق اشتباه است یا پر شده است.")
                            except:
                                send_message(chat_id, "❌ فرمت دستور اشتباه است.")

                        # ترک اتاق
                        elif text == "/leave":
                            left = False
                            for code, data in rooms_db.items():
                                if chat_id in data["members"]:
                                    data["members"].remove(chat_id)
                                    send_message(chat_id, f"👋 شما اتاق `{code}` را ترک کردید.")
                                    # اگر اتاق خالی شد، حذفش کن
                                    if not data["members"]:
                                        del rooms_db[code]
                                    left = True
                                    break
                            if not left:
                                send_message(chat_id, "❌ شما در هیچ اتاکی نیستید!")

            else:
                print(f"API Error: {response.status_code}")
        except Exception as e:
            print(f"Loop error: {e}")
        
        time.sleep(2)

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.start()
    bot_loop()
