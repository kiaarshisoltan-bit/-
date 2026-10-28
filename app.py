import os
import time
import random
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# تنظیمات اصلی
BOT_TOKEN = "*******"
RENDER_URL = os.environ.get("RENDER_URL", "https://jorat-bot.onrender.com")
BALE_API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# پایگاه داده در حافظه
profiles = {}         
pending_name = set()  
rooms = {}            
scores = {}           
user_states = {}      

# --- نگهداری ربات بیدار روی Render ---
def keep_alive():
    while True:
        try:
            if RENDER_URL:
                requests.get(RENDER_URL, timeout=10)
        except Exception:
            pass
        time.sleep(240)

threading.Thread(target=keep_alive, daemon=True).start()

# --- توابع ارتباطی بله ---
def send_message(chat_id, text, reply_markup=None):
    url = f"{BALE_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.json()
    except Exception as e:
        print(f"Error sending message: {e}")
        return None

def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎮 بازی چندنفره (اتاق)"}, {"text": "🤖 بازی تک‌نفره"}],
            [{"text": "🏆 جدول رده‌بندی"}, {"text": "💰 سکه و فروشگاه"}],
            [{"text": "🕵️‍♂️ حالت مامور مخفی"}, {"text": "🎁 چالش روزانه"}],
            [{"text": "👥 زیرمجموعه‌گیری"}, {"text": "✏️ تغییر نام مستعار"}],
            [{"text": "📢 کانال اطلاع‌رسانی"}, {"text": "🛠 پشتیبانی"}]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }

@app.route('/', methods=['GET'])
def index():
    return "Jorat-o-Haghighat Bot is running!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error"}), 400

        if "message" in data:
            msg = data["message"]
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "").strip()

            # بررسی تغییر نام یا ثبت‌نام اولیه
            if chat_id in pending_name:
                if len(text) < 2:
                    send_message(chat_id, "❌ نام مستعار باید حداقل ۲ حرف باشد. لطفاً دوباره بفرست:")
                    return jsonify({"status": "ok"})
                
                profiles[chat_id] = text
                pending_name.remove(chat_id)
                scores[chat_id] = scores.get(chat_id, 0) + 15
                user_states.pop(chat_id, None)
                send_message(chat_id, f"✅ عالی شد کیا جان! نام مستعار تو به **{text}** تغییر کرد (+15 سکه 🎉)", get_main_menu())
                return jsonify({"status": "ok"})

            if chat_id not in profiles:
                pending_name.add(chat_id)
                send_message(chat_id, "👋 سلام کیا جان! به ربات **جرئت و حقیقت** خوش اومدی.\n\nلطفاً یک **نام مستعار منحصر‌به‌فرد** برای خودت بفرست:")
                return jsonify({"status": "ok"})

            # اگر کاربر دکمه بازگشت یا منو رو زد، حتماً حالت‌ها رو پاک کن
            if text in ["🏠 بازگشت به منوی اصلی", "/start"]:
                user_states.pop(chat_id, None)
                if text == "/start":
                    send_message(chat_id, f"خوش برگشتی {profiles[chat_id]} عزیز! منوی اصلی:", get_main_menu())
                else:
                    send_message(chat_id, "🏠 منوی اصلی:", get_main_menu())
                return jsonify({"status": "ok"})

            # بررسی حالت‌های انتظار (مثل وارد کردن کد اتاق)
            state = user_states.get(chat_id)
            if state == "waiting_room_code":
                room_code = text.upper()
                if room_code in rooms:
                    if chat_id not in rooms[room_code]["members"]:
                        rooms[room_code]["members"].append(chat_id)
                    user_states.pop(chat_id, None)
                    send_message(chat_id, f"✅ با موفقیت به اتاق `{room_code}` ملحق شدی! 🎉", get_main_menu())
                    host_id = rooms[room_code]["host"]
                    send_message(host_id, f"👤 کاربر `{profiles.get(chat_id, 'ناشناس')}` به اتاق شما پیوست!")
                else:
                    # دکمه بازگشت اضطراری زیر پیام ارور برای راحتی کاربر
                    kb = {
                        "keyboard": [[{"text": "🏠 بازگشت به منوی اصلی"}]],
                        "resize_keyboard": True
                    }
                    send_message(chat_id, "❌ این اتاق وجود نداره. کد درستی وارد کن یا دکمه زیر رو بزن:", kb)
                return jsonify({"status": "ok"})

            # پردازش دکمه‌های منوی اصلی و گزینه‌ها
            if text == "🎮 بازی چندنفره (اتاق)":
                kb = {
                    "keyboard": [
                        [{"text": "➕ ساخت اتاق جدید"}, {"text": "🚪 پیوستن به اتاق"}],
                        [{"text": "🏠 بازگشت به منوی اصلی"}]
                    ],
                    "resize_keyboard": True
                }
                send_message(chat_id, "🎮 بخش بازی چندنفره:\nیک گزینه رو انتخاب کن:", kb)

            elif text == "➕ ساخت اتاق جدید":
                room_code = str(random.randint(1000, 9999))
                rooms[room_code] = {"host": chat_id, "members": [chat_id]}
                kb = {
                    "keyboard": [
                        [{"text": f"🗑 حذف اتاق {room_code}"}],
                        [{"text": "🏠 بازگشت به منوی اصلی"}]
                    ],
                    "resize_keyboard": True
                }
                send_message(chat_id, f"🏠 اتاق شما ساخته شد!\n\nکد اتاق: `{room_code}`\nاین کد رو به دوستات بده تا وارد بشن.", kb)

            elif text.startswith("🗑 حذف اتاق "):
                r_code = text.split(" ")[2]
                if r_code in rooms and rooms[r_code]["host"] == chat_id:
                    del rooms[r_code]
                    send_message(chat_id, f"🗑 اتاق `{r_code}` با موفقیت حذف شد.", get_main_menu())
                else:
                    send_message(chat_id, "❌ شما صاحب این اتاق نیستید یا اتاق وجود ندارد.", get_main_menu())

            elif text == "🚪 پیوستن به اتاق":
                user_states[chat_id] = "waiting_room_code"
                kb = {
                    "keyboard": [[{"text": "🏠 بازگشت به منوی اصلی"}]],
                    "resize_keyboard": True
                }
                send_message(chat_id, "🔑 لطفاً کد ۴ رقمی اتاق مورد نظرت رو بفرست:", kb)

            elif text == "🤖 بازی تک‌نفره":
                kb = {
                    "keyboard": [
                        [{"text": "❓ حقیقت (Truth)"}, {"text": "🔥 جرات (Dare)"}],
                        [{"text": "🎡 چرخش چرخ شانس"}],
                        [{"text": "🏠 بازگشت به منوی اصلی"}]
                    ],
                    "resize_keyboard": True
                }
                send_message(chat_id, "🤖 بخش تک‌نفره جرئت و حقیقت:", kb)

            elif text == "❓ حقیقت (Truth)":
                truths = [
                    "بزرگترین گند زندگیت چی بوده؟ 😂",
                    "تا حالا توی جمع خوابت برده؟",
                    "رازآلودترین چیزی که دیدی چی بوده؟",
                    "اگر میتونستی یک قانون توی دنیا عوض کنی چی بود؟"
                ]
                send_message(chat_id, f"❓ **حقیقت:**\n\n{random.choice(truths)}")

            elif text == "🔥 جرات (Dare)":
                dares = [
                    "باید یک ویس پر کنی و صدای یک حیوان رو تقلید کنی! 🎤",
                    "به آخرین نفری که پیام دادی بگو «دوستت دارم»! 📱",
                    "۱۰ تا شنا همین الان برو و گزارش بده! 💪",
                    "یک عکس با حالت خنده‌دار بفرست!"
                ]
                send_message(chat_id, f"🔥 **جرات:**\n\n{random.choice(dares)}")

            elif text == "🎡 چرخش چرخ شانس":
                choice = random.choice(["حقیقت ❓", "جرات 🔥"])
                send_message(chat_id, f"🎡 چرخ شانس چرخید و اومد روی: **{choice}**!")

            elif text == "🏆 جدول رده‌بندی":
                top_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                lb_text = "🏆 **جدول رده‌بندی برترین‌ها:**\n\n"
                for idx, (uid, sc) in enumerate(top_users, 1):
                    name = profiles.get(uid, "ناشناس")
                    lb_text += f"{idx}. {name} ⟷ {sc} سکه\n"
                send_message(chat_id, lb_text, get_main_menu())

            elif text == "💰 سکه و فروشگاه":
                coins = scores.get(chat_id, 0)
                send_message(chat_id, f"💰 **فروشگاه جرئت و حقیقت:**\n\n- تاج پادشاهی طلایی (500 سکه)\n- رنگ نام ویژه (200 سکه)\n\nامتیاز فعلی شما: **{coins} سکه**", get_main_menu())

            elif text == "🕵️‍♂️ حالت مامور مخفی":
                send_message(chat_id, "🕵️‍♂️ **حالت مامور مخفی:**\n\nبه زودی ماموریت‌های مخفی درون‌گروهی فعال میشن!", get_main_menu())

            elif text == "🎁 چالش روزانه":
                send_message(chat_id, "🎁 **چالش امروز:**\nیک عکس جالب از میز کار یا اتاقت بفرست و +30 سکه بگیر!", get_main_menu())

            elif text == "👥 زیرمجموعه‌گیری":
                send_message(chat_id, f"👥 **لینک دعوت اختصاصی شما:**\n`https://ble.ir/jorat_bot?start={chat_id}`\n\nبا دعوت هر دوست ۵۰ سکه هدیه بگیر!", get_main_menu())

            elif text == "✏️ تغییر نام مستعار":
                pending_name.add(chat_id)
                send_message(chat_id, "✏️ لطفاً نام مستعار جدید خود را ارسال کنید:")

            elif text == "📢 کانال اطلاع‌رسانی":
                send_message(chat_id, "📢 کانال ما:\nhttps://ble.ir/ettelae_resani", get_main_menu())

            elif text == "🛠 پشتیبانی":
                send_message(chat_id, "🛠 ارتباط با پشتیبانی (کیا): \nhttps://ble.ir/KIA_karfarma", get_main_menu())

            else:
                send_message(chat_id, "دستور نامعتبر. از دکمه‌های پایین صفحه استفاده کن:", get_main_menu())

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
