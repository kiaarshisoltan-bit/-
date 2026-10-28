import os
import logging
import random
import threading
import time
import requests
from flask import Flask
from bale import Bot, Message, Update
from bale.ext.commands import Bot as ExtBot

# --- تنظیمات وب‌سرور برای جلوگیری از خوابیدن رندر ---
app = Flask('')

@app.route('/')
def home():
    return "ربات فعال است و در حال کار در پس‌زمینه... 🚀"

def run_flask():
    # استفاده از پورت محیطی که رندر تعیین می‌کند
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- تنظیمات ربات ---
TOKEN = "*******" # توکن تو
bot = ExtBot(token=TOKEN)

users_db = {}
rooms_db = {}

# (بخش دستورات مثل Start، Truth و Dare که قبلاً نوشتم رو اینجا اضافه کن)

@bot.command(name="start")
async def start_command(message: Message):
    user_id = message.author.id
    name = message.author.first_name or "کیا جان"
    if user_id not in users_db:
        users_db[user_id] = {"name": name, "coins": 100, "score": 10}
    await message.reply(f"سلام {name}! به قلمرو بازی خوش اومدی. 🎮")

# --- سیستم خودکار پینگ (Self-Ping) ---
def self_ping():
    # این بخش سعی می‌کند آدرس خود رندر را پینگ کند
    # البته بهتر است از UptimeRobot استفاده کنی که به URL رندر درخواست بزند
    while True:
        try:
            # جایگزین کردن با URL اصلی که رندر بهت میده
            # مثلا: https://my-bot.onrender.com
            # requests.get("https://your-app-name.onrender.com") 
            print("Checking connection...")
        except:
            pass
        time.sleep(300) # هر ۵ دقیقه یکبار

# --- اجرای همزمان ---
if __name__ == "__main__":
    # ۱. شروع وب‌سرور در یک Thread جداگانه
    t = threading.Thread(target=run_flask)
    t.start()

    # ۲. شروع سیستم پینگ خودکار در یک Thread جداگانه
    p = threading.Thread(target=self_ping)
    p.start()

    # ۳. اجرای اصلی ربات
    bot.run()
