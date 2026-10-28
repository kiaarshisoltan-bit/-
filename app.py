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
profiles = {}         # chat_id -> nickname
pending_name = set()  # انتظار برای نام مستعار
rooms = {}            # room_code -> {'host': chat_id, 'members': [chat_id]}
scores = {}           # chat_id -> سکه/امتیاز
user_states = {}      # chat_id -> حالت فعلی کاربر

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
        "inline_keyboard": [
            [{"text": "🎮 بازی چندنفره (اتاق)", "callback_data": "multiplayer"},
             {"text": "🤖 بازی تک‌نفره", "callback_data": "single_player"}],
            [{"text": "🏆 جدول رده‌بندی", "callback_data": "leaderboard"},
             {"text": "💰 سکه و فروشگاه", "callback_data": "shop"}],
            [{"text": "🕵️‍♂️ حالت مامور مخفی", "callback_data": "secret_agent"},
             {"text": "🎁 چالش روزانه", "callback_data": "daily_challenge"}],
            [{"text": "👥 زیرمجموعه‌گیری", "callback_data": "referral"},
             {"text": "✏️ تغییر نام مستعار", "callback_data": "change_name"}],
            [{"text": "📢 کانال اطلاع‌رسانی", "url": "https://ble.ir/ettelae_resani"},
             {"text": "🛠 پشتیبانی", "url": "https://ble.ir/KIA_karfarma"}]
        ]
    }

# --- روت‌های Flask ---
@app.route('/', methods=['GET'])
def index():
    return "Jorat-o-Haghighat Bot is running!", 200

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"status": "error"}), 400

        # دریافت پیام‌های متنی یا دستورات
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

            # بررسی حالت‌های انتظار (مثل وارد کردن کد اتاق)
            state = user_states.get(chat_id)
            if state == "waiting_room_code":
                room_code = text.upper()
                if room_code in rooms:
                    if chat_id not in rooms[room_code]["members"]:
                        rooms[room_code]["members"].append(chat_id)
                    user_states.pop(chat_id, None)
                    send_message(chat_id, f"✅ با موفقیت به اتاق `{room_code}` ملحق شدی! 🎉")
                    host_id = rooms[room_code]["host"]
                    send_message(host_id, f"👤 کاربر `{profiles.get(chat_id, 'ناشناس')}` به اتاق شما پیوست!")
                else:
                    send_message(chat_id, "❌ این اتاق وجود نداره. کد درستی وارد کن یا برگرد منو:")
                return jsonify({"status": "ok"})

            if text == "/start":
                send_message(chat_id, f"خوش برگشتی {profiles[chat_id]} عزیز! منوی اصلی:", get_main_menu())
            else:
                send_message(chat_id, "دستور نامعتبر. از منوی زیر استفاده کن:", get_main_menu())

        # دریافت کلیک روی دکمه‌های شیشه‌ای (Callback Query)
        elif "callback_query" in data:
            cb = data["callback_query"]
            chat_id = cb["message"]["chat"]["id"]
            callback_data = cb.get("data")

            if chat_id not in profiles:
                pending_name.add(chat_id)
                send_message(chat_id, "لطفاً ابتدا نام مستعار خود را ارسال کنید:")
                return jsonify({"status": "ok"})

            if callback_data == "multiplayer":
                kb = {
                    "inline_keyboard": [
                        [{"text": "➕ ساخت اتاق جدید", "callback_data": "create_room"},
                         {"text": "🚪 پیوستن به اتاق", "callback_data": "join_room"}],
                        [{"text": "🔙 بازگشت به منو", "callback_data": "main_menu"}]
                    ]
                }
                send_message(chat_id, "🎮 بخش بازی چندنفره:\nیک گزینه رو انتخاب کن:", kb)

            elif callback_data == "create_room":
                room_code = str(random.randint(1000, 9999))
                rooms[room_code] = {"host": chat_id, "members": [chat_id]}
                kb = {
                    "inline_keyboard": [
                        [{"text": "🗑 حذف اتاق", "callback_data": f"delete_room_{room_code}"}],
                        [{"text": "🔙 بازگشت", "callback_data": "multiplayer"}]
                    ]
                }
                send_message(chat_id, f"🏠 اتاق شما ساخته شد!\n\nکد اتاق: `{room_code}`\nاین کد رو به دوستات بده تا وارد بشن.", kb)

            elif callback_data and callback_data.startswith("delete_room_"):
                r_code = callback_data.split("_")[2]
                if r_code in rooms and rooms[r_code]["host"] == chat_id:
                    del rooms[r_code]
                    send_message(chat_id, f"🗑 اتاق `{r_code}` با موفقیت حذف شد.", get_main_menu())
                else:
                    send_message(chat_id, "❌ شما صاحب این اتاق نیستید.")

            elif callback_data == "join_room":
                user_states[chat_id] = "waiting_room_code"
                send_message(chat_id, "🔑 لطفاً کد ۴ رقمی اتاق مورد نظرت رو بفرست:")

            elif callback_data == "single_player":
                kb = {
                    "inline_keyboard": [
                        [{"text": "❓ حقیقت (Truth)", "callback_data": "sp_truth"},
                         {"text": "🔥 جرات (Dare)", "callback_data": "sp_dare"}],
                        [{"text": "🎡 چرخش چرخ شانس", "callback_data": "sp_wheel"}],
                        [{"text": "🔙 بازگشت به منو", "callback_data": "main_menu"}]
                    ]
                }
                send_message(chat_id, "🤖 بخش تک‌نفره جرئت و حقیقت:", kb)

            elif callback_data == "sp_truth":
                truths = [
                    "بزرگترین گند زندگیت چی بوده؟ 😂",
                    "تا حالا توی جمع خوابت برده؟",
                    "رازآلودترین چیزی که دیدی چی بوده؟",
                    "اگر میتونستی یک قانون توی دنیا عوض کنی چی بود؟"
                ]
                send_message(chat_id, f"❓ **حقیقت:**\n\n{random.choice(truths)}")

            elif callback_data == "sp_dare":
                dares = [
                    "باید یک ویس پر کنی و صدای یک حیوان رو تقلید کنی! 🎤",
                    "به آخرین نفری که پیام دادی بگو «دوستت دارم»! 📱",
                    "۱۰ تا شنا همین الان برو و گزارش بده! 💪",
                    "یک عکس با حالت خنده‌دار بفرست!"
                ]
                send_message(chat_id, f"🔥 **جرات:**\n\n{random.choice(dares)}")

            elif callback_data == "sp_wheel":
                choice = random.choice(["حقیقت ❓", "جرات 🔥"])
                send_message(chat_id, f"🎡 چرخ شانس چرخید و اومد روی: **{choice}**!")

            elif callback_data == "secret_agent":
                send_message(chat_id, "🕵️‍♂️ **حالت مامور مخفی:**\n\nبه زودی ماموریت‌های مخفی درون‌گروهی فعال میشن!", get_main_menu())

            elif callback_data == "shop":
                coins = scores.get(chat_id, 0)
                send_message(chat_id, f"💰 **فروشگاه جرئت و حقیقت:**\n\n- تاج پادشاهی طلایی (500 سکه)\n- رنگ نام ویژه (200 سکه)\n\nامتیاز فعلی شما: **{coins} سکه**", get_main_menu())

            elif callback_data == "leaderboard":
                top_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
                lb_text = "🏆 **جدول رده‌بندی برترین‌ها:**\n\n"
                for idx, (uid, sc) in enumerate(top_users, 1):
                    name = profiles.get(uid, "ناشناس")
                    lb_text += f"{idx}. {name} ⟷ {sc} سکه\n"
                send_message(chat_id, lb_text, get_main_menu())

            elif callback_data == "daily_challenge":
                send_message(chat_id, "🎁 **چالش امروز:**\nیک عکس جالب از میز کار یا اتاقت بفرست و +30 سکه بگیر!", get_main_menu())

            elif callback_data == "referral":
                send_message(chat_id, f"👥 **لینک دعوت اختصاصی شما:**\n`https://ble.ir/jorat_bot?start={chat_id}`\n\nبا دعوت هر دوست ۵۰ سکه هدیه بگیر!", get_main_menu())

            elif callback_data == "change_name":
                pending_name.add(chat_id)
                send_message(chat_id, "✏️ لطفاً نام مستعار جدید خود را ارسال کنید:")

            elif callback_data == "main_menu":
                send_message(chat_id, "🏠 منوی اصلی:", get_main_menu())

        return jsonify({"status": "ok"})

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
