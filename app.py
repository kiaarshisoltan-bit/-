import os
import random
import threading
import time
from flask import Flask, request
import requests

app = Flask(__name__)

# توکن اصلی ربات بله
TOKEN = "*******"
BASE_URL = f"https://tapi.bale.ai/bot{TOKEN}"
RENDER_URL = "https://jorat-bot.onrender.com"  # آدرس سرویس رندر شما

# پایگاه داده ساده درون حافظه
# ساختار: user_id -> { 'nick': str, 'coins': int, 'score': int, 'state': str, 'room': str, 'target': int }
users = {}
rooms = {}  # room_code -> { 'host': user_id, 'players': [user_id], 'mode': str }
leaderboard = {}  # user_id -> score


def send_message(chat_id, text, reply_markup=None):
  url = f"{BASE_URL}/sendMessage"
  payload = {"chat_id": chat_id, "text": text}
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending message: {e}")


def main_menu_keyboard():
  return {
      "keyboard": [
          [{"text": "🎮 بازی تک‌نفره"}, {"text": "👥 اتاق‌های چندنفره"}],
          [{"text": "🎡 چرخ شانس"}, {"text": "🏆 جدول امتیازات (لیدربرد)"}],
          [{"text": "🛒 فروشگاه و سکه"}, {"text": "🎯 چالش روزانه"}],
          [{"text": "✏️ تغییر نام مستعار"}, {"text": "📢 کانال اطلاع‌رسانی"}],
          [{"text": "📞 پشتیبانی و انتقادات"}],
      ],
      "resize_keyboard": True,
      "is_persistent": True,
  }


@app.route("/", methods=["GET"])
def home():
  return "Jorat va Haghiqat Bot is running!", 200


@app.route(f"/bot{TOKEN}", methods=["POST"])
def webhook():
  data = request.get_json()
  if not data:
    return "OK", 200

  if "message" in data:
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    # بررسی ثبت‌نام کاربر
    if chat_id not in users:
      if text.startswith("/start"):
        users[chat_id] = {
            "nick": "",
            "coins": 50,
            "score": 0,
            "state": "WAITING_NICK",
            "room": None,
        }
        send_message(
            chat_id,
            "سلام کیا جان! به ربات جذاب **«جرئت و حقیقت»** خوش اومدی. 🔥\nلطفاً"
            " یک **نام مستعار (Nickname)** یکتا برای خودت وارد کن:",
        )
      else:
        if (
            users.get(chat_id, {}).get("state") == "WAITING_NICK"
            or chat_id not in users
        ):
          users[chat_id] = {
              "nick": text,
              "coins": 50,
              "score": 0,
              "state": "MAIN_MENU",
              "room": None,
          }
          send_message(
              chat_id,
              f"نام مستعار تو با موفقیت ثبت شد: **{text}** 🎉\n۵۰ سکه اولیه به"
              " عنوان هدیه بهت داده شد!",
              reply_markup=main_menu_keyboard(),
          )
        else:
          send_message(
              chat_id,
              "لطفاً ابتدا دستور /start را ارسال کنید.",
              reply_markup=main_menu_keyboard(),
          )
      return "OK", 200

    user_data = users[chat_id]

    # مدیریت تغییر نام
    if user_data.get("state") == "CHANGING_NICK":
      user_data["nick"] = text
      user_data["state"] = "MAIN_MENU"
      send_message(
          chat_id,
          f"✅ نام مستعار جدید شما با موفقیت ثبت شد: **{text}**",
          reply_markup=main_menu_keyboard(),
      )
      return "OK", 200

    # دستورات منوی اصلی
    if text == "/start":
      user_data["state"] = "MAIN_MENU"
      send_message(
          chat_id,
          "به منوی اصلی برگشتی کیا جان! یکی از گزینه‌های زیر رو انتخاب کن:",
          reply_markup=main_menu_keyboard(),
      )

    elif text == "🎮 بازی تک‌نفره":
      user_data["state"] = "SINGLE_PLAYER"
      kb = {
          "keyboard": [[{"text": "جرئت"}, {"text": "حقیقت"}], [{"text": "🔙 بازگشت به منوی اصلی"}]],
          "resize_keyboard": True,
      }
      send_message(
          chat_id,
          "حالت تک‌نفره فعال شد! یکی رو انتخاب کن:",
          reply_markup=kb,
      )

    elif text == "حقیقت" and user_data.get("state") == "SINGLE_PLAYER":
      truths = [
          "بزرگترین گناهی که تا حالا کردی چی بوده؟",
          "تا حالا کسی رو سر کار گذاشتی؟ تعریف کن.",
          "اگر غیب می‌شدی، اولین جایی که می‌رفتی کجا بود؟",
      ]
      send_message(chat_id, f"🧐 **حقیقت:** {random.choice(truths)}")

    elif text == "جرئت" and user_data.get("state") == "SINGLE_PLAYER":
      dares = [
          "یک ویس ۱۰ ثانیه‌ای بفرست و با صدای خنده‌دار صحبت کن.",
          "آخرین عکسی که تو گالریت داری رو بفرست (با کات‌اف یا موضوع جالب).",
          "یک جوک بی‌مزە تعریف کن!",
      ]
      send_message(chat_id, f"🔥 **جرئت:** {random.choice(dares)}")

    elif text == "🎡 چرخ شانس":
      prize = random.choice([10, 20, 50, 0, 100])
      user_data["coins"] += prize
      send_message(
          chat_id,
          f"🎡 چرخ شانس چرخید و شما **{prize} سکه** برنده شدید! 💰\nموجودی جدید"
          f" سکه‌ها: {user_data['coins']}",
      )

    elif text == "🏆 جدول امتیازات (لیدربرد)":
      sorted_users = sorted(
          users.items(), key=lambda x: x[1].get("score", 0), reverse=True
      )[:5]
      lb_text = "🏆 **جدول برترین‌های جرئت و حقیقت:**\n\n"
      for idx, (uid, uinfo) in enumerate(sorted_users, 1):
        lb_text += (
            f"{idx}. {uinfo.get('nick', 'بدون نام')} - امتیاز:"
            f" {uinfo.get('score', 0)}\n"
        )
      send_message(chat_id, lb_text)

    elif text == "🛒 فروشگاه و سکه":
      send_message(
          chat_id,
          "🛒 **فروشگاه ربات:**\nموجودی شما: "
          f"{user_data['coins']} سکه\n\n1. خرید نشان ویژه (۵۰ سکه)\n2. خرید رنگ نام"
          " (۱۰۰ سکه)\n\n(به زودی اقلام بیشتر اضافه می‌شود!)",
      )

    elif text == "🎯 چالش روزانه":
      send_message(
          chat_id,
          "🎯 **چالش امروز:** یک عکس خفن از میز کار یا اتاق‌ت بفرست و ۲۰ سکه"
          " جایزه بگیر!",
      )

    elif text == "✏️ تغییر نام مستعار":
      user_data["state"] = "CHANGING_NICK"
      send_message(
          chat_id, "لطفاً نام مستعار جدید خود را ارسال کنید:", reply_markup={"remove_keyboard": True}
      )

    elif text == "📢 کانال اطلاع‌رسانی":
      send_message(chat_id, "برای پیگیری اخبار و آپدیت‌ها به کانال ما بپیوندید:\n@ettelae_resani")

    elif text == "📞 پشتیبانی و انتقادات":
      send_message(
          chat_id,
          "برای ارسال نظرات، ایده‌ها و گزارش مشکل به آیدی پشتیبانی کیا پیام"
          " دهید:\n@KIA_karfarma",
      )

    elif text == "🔙 بازگشت به منوی اصلی":
      user_data["state"] = "MAIN_MENU"
      send_message(chat_id, "به منوی اصلی برگشتید.", reply_markup=main_menu_keyboard())

    else:
      send_message(chat_id, "دستور نامفهوم است. لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=main_menu_keyboard())

  return "OK", 200


def keep_alive():
  while True:
    try:
      if RENDER_URL:
        requests.get(RENDER_URL, timeout=10)
    except Exception as e:
      print(f"Keep-alive ping error: {e}")
    time.sleep(300)  # هر ۵ دقیقه


if __name__ == "__main__":
  # راه‌اندازی ترد نگهدارنده سرور بیدار
  t = threading.Thread(target=keep_alive)
  t.daemon = True
  t.start()

  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
