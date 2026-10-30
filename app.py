import os
import random
from flask import Flask, request, jsonify

app = Flask(__name__)

# تنظیمات بله
BOT_TOKEN = "*******"
BALE_API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"

# پایگاه داده در حافظه
profiles = {}         # {chat_id: nickname}
pending_name = set()  # کاربرانی که در انتظار ارسال نام مستعار هستند
scores = {}           # {chat_id: coins}
inventory = {}        # {chat_id: [items]}
rooms = {}            # {room_code: {"host": chat_id, "members": [chat_id, ...]}}
user_room = {}        # {chat_id: room_code}

# بانک سوالات تک‌نفره
SINGLE_TRUTHS = [
    "بزرگترین گناهی که تا حالا کردی و کسی نفهمیده چیه؟",
    "اگر غیب می‌شدی، اولین جایی که می‌رفتی کجا بود؟",
    "خجالت‌آورترین خاطره دوران کودکیت چیه؟",
    "تا حالا شده از کسی متنفر باشی ولی به روش نیاری؟",
    "عجیب‌ترین کاری که تو تنهایی انجام دادی چی بوده؟"
]

SINGLE_DARES = [
    "یک ویس ۵ ثانیه‌ای با خنده‌دارترین صدایی که می‌تونی بفرست!",
    "آخرین عکسی که تو گوشیت ذخیره کردی رو (اگه مشکلی نداره) بفرست!",
    "۱۰ بار پشت سر هم بگو 'سقف سفت، سر سفت'!",
    "یک پیام طنز به آخرین مخاطبی که بهش پیام دادی بفرست.",
    "تا ۵ دقیقه آینده باید به هر پیامی فقط با ایموجی 🐒 جواب بدی!"
]

def send_message(chat_id, text, reply_markup=None):
    import requests
    url = f"{BALE_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=payload, timeout=5)
        return response.json()
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_main_menu():
    return {
        "keyboard": [
            [{"text": "🎮 بازی چندنفره (اتاق‌ها)"}, {"text": "🤖 بازی تک‌نفره"}],
            [{"text": "🏆 جدول رده‌بندی"}, {"text": "💰 سکه و فروشگاه"}],
            [{"text": "🎁 چالش روزانه"}, {"text": "✏️ تغییر نام مستعار"}],
            [{"text": "🛠 پشتیبانی و کانال"}]
        ],
        "resize_keyboard": True
    }

def get_multi_menu():
    return {
        "keyboard": [
            [{"text": "➕ ساخت اتاق جدید"}, {"text": "🚪 پیوستن به اتاق"}],
            [{"text": "❌ حذف اتاق من"}, {"text": "🏠 بازگشت به منوی اصلی"}]
        ],
        "resize_keyboard": True
    }

def get_single_menu():
    return {
        "keyboard": [
            [{"text": "❓ حقیقت تک‌نفره"}, {"text": "🔥 جرات تک‌نفره"}],
            [{"text": "🎡 چرخ شانس"}, {"text": "🏠 بازگشت به منوی اصلی"}]
        ],
        "resize_keyboard": True
    }

def get_shop_menu():
    return {
        "keyboard": [
            [{"text": "👑 تاج پادشاهی (50 سکه)"}, {"text": "✨ رنگ نام ویژه (30 سکه)"}],
            [{"text": "🎒 کیف کوله‌پشتی (100 سکه)"}, {"text": "🏠 بازگشت به منوی اصلی"}]
        ],
        "resize_keyboard": True
    }

def get_support_menu():
    return {
        "keyboard": [
            [{"text": "📢 کانال اطلاع‌رسانی"}, {"text": "🛠 ارتباط با پشتیبانی"}],
            [{"text": "🏠 بازگشت به منوی اصلی"}]
        ],
        "resize_keyboard": True
    }

@app.route('/', methods=['GET'])
def index():
    return "Jorat-o-Haghighat - Final Phase is running perfectly!", 200

@app.route(f'/{BOT_TOKEN}', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        if not data or "message" not in data:
            return jsonify({"status": "ok"})

        msg = data["message"]
        chat_id = msg["chat"]["id"]
        text = msg.get("text", "").strip()

        # ۱. مرحله ثبت نام نام مستعار
        if chat_id in pending_name:
            if len(text) < 2:
                send_message(chat_id, "❌ نام مستعار باید حداقل ۲ حرف باشد. لطفاً دوباره بفرست:")
                return jsonify({"status": "ok"})
            
            profiles[chat_id] = text
            pending_name.remove(chat_id)
            scores[chat_id] = scores.get(chat_id, 0) + 15
            send_message(chat_id, f"✅ عالی شد کیا جان! نام مستعار تو به **{text}** ثبت شد (+15 سکه 🎉)", get_main_menu())
            return jsonify({"status": "ok"})

        if chat_id not in profiles:
            pending_name.add(chat_id)
            send_message(chat_id, "👋 سلام کیا جان! به ربات **جرئت و حقیقت** خوش اومدی.\n\nلطفاً یک **نام مستعار منحصر‌به‌فرد** برای خودت بفرست:")
            return jsonify({"status": "ok"})

        # ۲. دستورات و منوها
        if text in ["🏠 بازگشت به منوی اصلی", "/start"]:
            user_room.pop(chat_id, None)
            send_message(chat_id, f"خوش برگشتی {profiles[chat_id]} عزیز! منوی اصلی:", get_main_menu())
            return jsonify({"status": "ok"})

        elif text == "🎮 بازی چندنفره (اتاق‌ها)":
            send_message(chat_id, "👥 به بخش بازی چندنفره خوش اومدی. از دکمه‌های زیر استفاده کن:", get_multi_menu())

        elif text == "➕ ساخت اتاق جدید":
            room_code = str(random.randint(1000, 9999))
            while room_code in rooms:
                room_code = str(random.randint(1000, 9999))
            
            rooms[room_code] = {"host": chat_id, "members": [chat_id]}
            user_room[chat_id] = room_code
            send_message(chat_id, f"✅ اتاق با موفقیت ساخته شد!\n\n🔑 کد اتاق شما: **{room_code}**\n\nبه دوستانت بگو این کد رو وارد کنند تا به اتاق بیان.", get_multi_menu())

        elif text == "🚪 پیوستن به اتاق":
            # نمایش لیست اتاق‌های فعال
            if not rooms:
                send_message(chat_id, "❌ در حال حاضر هیچ اتاقی ساخته نشده است. می‌تونی خودت یکی بسازی!", get_multi_menu())
                return jsonify({"status": "ok"})
            
            rooms_list_str = "📋 لیست اتاق‌های فعال:\n\n"
            for r_code, r_data in rooms.items():
                host_name = profiles.get(r_data["host"], "میزبان")
                rooms_list_str += f"🔑 کد: `{r_code}` | میزبان: {host_name} | اعضا: {len(r_data['members'])}\n"
            
            rooms_list_str += "\nبرای ورود به اتاق، کد ۴ رقمی آن را ارسال کنید (یا برای لغو، بازگشت به منوی اصلی را بزنید):"
            send_message(chat_id, rooms_list_str, get_multi_menu())

        elif text.isdigit() and len(text) == 4:
            room_code = text
            if room_code in rooms:
                if chat_id not in rooms[room_code]["members"]:
                    rooms[room_code]["members"].append(chat_id)
                user_room[chat_id] = room_code
                host_id = rooms[room_code]["host"]
                send_message(chat_id, f"🎉 با موفقیت به اتاق **{room_code}** ملحق شدی!", get_multi_menu())
                # اطلاع به میزبان
                if host_id != chat_id:
                    send_message(host_id, f"🔔 کاربر {profiles.get(chat_id, 'ناشناس')} به اتاق شما ملحق شد!")
            else:
                send_message(chat_id, "❌ این اتاق وجود ندارد یا منقضی شده است.", get_multi_menu())

        elif text == "❌ حذف اتاق من":
            r_code = user_room.get(chat_id)
            if r_code and r_code in rooms and rooms[r_code]["host"] == chat_id:
                del rooms[r_code]
                for m in rooms.get(r_code, {}).get("members", []):
                    user_room.pop(m, None)
                send_message(chat_id, "🗑 اتاق شما با موفقیت حذف شد.", get_multi_menu())
            else:
                send_message(chat_id, "❌ شما سازنده هیچ اتاق فعالی نیستید.", get_multi_menu())

        elif text == "🤖 بازی تک‌نفره":
            send_message(chat_id, "🎮 به بخش بازی تک‌نفره خوش اومدی! یکی رو انتخاب کن:", get_single_menu())

        elif text == "❓ حقیقت تک‌نفره":
            question = random.choice(SINGLE_TRUTHS)
            scores[chat_id] = scores.get(chat_id, 0) + 5
            send_message(chat_id, f"🤔 **حقیقت:**\n\n{question}\n\n*(+۵ سکه پاداش گرفتی!)*", get_single_menu())

        elif text == "🔥 جرات تک‌نفره":
            dare = random.choice(SINGLE_DARES)
            scores[chat_id] = scores.get(chat_id, 0) + 10
            send_message(chat_id, f"🔥 **جرات:**\n\n{dare}\n\n*(+۱۰ سکه پاداش گرفتی!)*", get_single_menu())

        elif text == "🎡 چرخ شانس":
            choice_type = random.choice(["حقیقت", "جرات"])
            scores[chat_id] = scores.get(chat_id, 0) + 7
            if choice_type == "حقیقت":
                q = random.choice(SINGLE_TRUTHS)
                send_message(chat_id, f"🎡 چرخ شانس روی **حقیقت** افتاد (+7 سکه)!\n\nسوال:\n{q}", get_single_menu())
            else:
                d = random.choice(SINGLE_DARES)
                send_message(chat_id, f"🎡 چرخ شانس روی **جرات** افتاد (+7 سکه)!\n\nچالش:\n{d}", get_single_menu())

        elif text == "🏆 جدول رده‌بندی":
            if not scores:
                send_message(chat_id, "هنوز امتیازی ثبت نشده است!", get_main_menu())
                return jsonify({"status": "ok"})
            
            sorted_users = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:5]
            lb_text = "🏆 **جدول رده‌بندی برترین بازیکنان:**\n\n"
            for idx, (uid, sc) in enumerate(sorted_users, 1):
                name = profiles.get(uid, "ناشناس")
                lb_text += f"{idx}. {name} ⟵ {sc} سکه\n"
            send_message(chat_id, lb_text, get_main_menu())

        elif text == "💰 سکه و فروشگاه":
            my_coins = scores.get(chat_id, 0)
            my_inv = inventory.get(chat_id, [])
            inv_str = ", ".join(my_inv) if my_inv else "ندارد"
            shop_text = f"💰 موجودی سکه شما: **{my_coins}** سکه\n🎒 آیتم‌های شما: {inv_str}\n\nلطفاً یک آیتم برای خرید انتخاب کنید:"
            send_message(chat_id, shop_text, get_shop_menu())

        elif text == "👑 تاج پادشاهی (50 سکه)":
            if scores.get(chat_id, 0) >= 50:
                scores[chat_id] -= 50
                inventory.setdefault(chat_id, []).append("👑 تاج پادشاهی")
                send_message(chat_id, "🎉 مبارک باشه! تاج پادشاهی رو با موفقیت خریدی.", get_shop_menu())
            else:
                send_message(chat_id, "❌ سکه‌هات کافی نیست!", get_shop_menu())

        elif text == "✨ رنگ نام ویژه (30 سکه)":
            if scores.get(chat_id, 0) >= 30:
                scores[chat_id] -= 30
                inventory.setdefault(chat_id, []).append("✨ رنگ نام ویژه")
                send_message(chat_id, "🎉 مبارک باشه! رنگ نام ویژه رو خریدی.", get_shop_menu())
            else:
                send_message(chat_id, "❌ سکه‌هات کافی نیست!", get_shop_menu())

        elif text == "🎒 کیف کوله‌پشتی (100 سکه)":
            if scores.get(chat_id, 0) >= 100:
                scores[chat_id] -= 100
                inventory.setdefault(chat_id, []).append("🎒 کیف کوله‌پشتی")
                send_message(chat_id, "🎉 مبارک باشه! کوله‌پشتی رو خریدی.", get_shop_menu())
            else:
                send_message(chat_id, "❌ سکه‌هات کافی نیست!", get_shop_menu())

        elif text == "🎁 چالش روزانه":
            scores[chat_id] = scores.get(chat_id, 0) + 20
            send_message(chat_id, "🎁 چالش امروز انجام شد!\n\n**+۲۰ سکه** جایزه به حساب‌هات اضافه شد. فردا هم سر بزن!", get_main_menu())

        elif text == "✏️ تغییر نام مستعار":
            pending_name.add(chat_id)
            send_message(chat_id, "✏️ لطفاً نام مستعار جدید خود را ارسال کنید:")

        elif text == "🛠 پشتیبانی و کانال":
            send_message(chat_id, "🛠 از طریق دکمه‌های زیر می‌تونی با ما در ارتباط باشی:", get_support_menu())

        elif text == "📢 کانال اطلاع‌رسانی":
            send_message(chat_id, "📢 کانال ما:\nhttps://ble.ir/ettelae_resani", get_support_menu())

        elif text == "🛠 ارتباط با پشتیبانی":
            send_message(chat_id, "🛠 ارتباط با پشتیبانی (کیا):\nhttps://ble.ir/KIA_karfarma", get_support_menu())

        else:
            send_message(chat_id, "لطفاً از دکمه‌های زیر استفاده کن:", get_main_menu())

        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error"}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
