import os
import threading
import time
import requests
from flask import Flask

# --- تنظیمات وب‌سرور برای رندر ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is Running! 🚀"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- تنظیمات ربات بله ---
# توکن خودت رو اینجا بذار
BOT_TOKEN = "*******" 
BASE_URL = "https://api.bale.ai/v1" # آدرس API بله

# دیتابیس ساده
users_db = {}

def send_message(chat_id, text):
    """یک تابع کمکی برای ارسال پیام ساده با استفاده از API بله"""
    url = f"{BASE_URL}/messages/send"
    payload = {
        "chat_id": chat_id,
        "text": text
    }
    headers = {
        "Authorization": f"Bearer {BOT_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

# --- سیستم دریافت پیام (Polling) ---
# چون در رندر نمی‌تونیم از Webhook ساده استفاده کنیم، از Polling استفاده می‌کنیم
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
                    
                    # بررسی اگر پیام متنی بود
                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "")

                        # دستور شروع
                        if text == "/start":
                            user_id = chat_id
                            users_db[user_id] = {"name": "User", "coins": 100}
                            send_message(chat_id, "سلام کیا عزیز! ربات با موفقیت بالا اومد. 🚀")
                        
                        # دستور تست
                        elif text == "/ping":
                            send_message(chat_id, "Pong! 🏓")

            else:
                print(f"Error from API: {response.status_code}")
        
        except Exception as e:
            print(f"Loop error: {e}")
        
        time.sleep(2) # صبر برای جلوگیری از فشار به سرور

if __name__ == "__main__":
    # ۱. اجرای وب‌سرور
    t = threading.Thread(target=run_flask)
    t.start()

    # ۲. اجرای حلقه ربات
    bot_loop()
