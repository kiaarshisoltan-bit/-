import os
import random
import threading
import time
import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

# تنظیمات ربات Bale
BOT_TOKEN = "*******"
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
RENDER_URL = "https://jorat-bot.onrender.com"

# ذخیره وضعیت‌ها در حافظه
profiles = {}  # chat_id -> nickname
pending_name = set()  # chat_id های در انتظار ثبت نام
pending_new_name = set()  # chat_id های در انتظار تغییر نام
rooms = {}  # room_code -> dict
single_player = {}  # chat_id -> dict
scores = {}  # chat_id -> score (سکه‌ها و امتیازها)
user_states = {}  # chat_id -> state
referrals = {}  # referrer_id -> count
completed_dailies = {}  # chat_id -> date_string
user_inventory = {}  # chat_id -> list of bought items / extra lives


# ---------------- توابع کمکی ارتباط با Bale API ----------------
def send_message(chat_id, text, reply_markup=None):
  url = f"{BASE_URL}/sendMessage"
  payload = {"chat_id": chat_id, "text": text}
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending message: {e}")


def get_user_rank_title(score):
  if score >= 300:
    return "👑 افسانه جرات و حقیقت"
  elif score >= 200:
    return "🔥 شجاع اعظم"
  elif score >= 100:
    return "⚡ بازیکن حرفه‌ای"
  elif score >= 30:
    return "🎯 نوآموز جسور"
  else:
    return "🌱 تازه‌کار"


# ---------------- کیبوردهای اصلی ----------------
def get_main_menu():
  return {
      "inline_keyboard": [
          [
              {"text": "🎮 اتاق‌های آنلاین", "callback_data": "menu_online"},
              {"text": "🤖 بازی تک‌نفره", "callback_data": "menu_single"},
          ],
          [
              {"text": "🎯 چالش روزانه (+50 سکه)", "callback_data": "daily_challenge"},
              {"text": "🛍️ فروشگاه ربات", "callback_data": "open_shop"},
          ],
          [
              {"text": "👥 دعوت از دوستان", "callback_data": "invite_friends"},
              {"text": "🏆 جدول امتیازات و پروفایل", "callback_data": "leaderboard"},
          ],
          [
              {"text": "✏️ تغییر نام مستعار", "callback_data": "change_name"},
              {"text": "📢 کانال اطلاع‌رسانی", "url": "https://ble.ir/ettelae_resani"},
          ],
          [
              {"text": "💡 پشتیبانی و انتقادات", "url": "https://ble.ir/KIA_karfarma"},
          ],
      ]
  }


def get_game_modes_keyboard():
  return {
      "inline_keyboard": [
          [{"text": "🟢 معمولی و دوستانه", "callback_data": "mode_normal"}],
          [{"text": "🔥 خفن و چالشی", "callback_data": "mode_fun"}],
          [{"text": "👻 ترسناک و مرموز", "callback_data": "mode_scary"}],
      ]
  }


# ---------------- وب‌هوک و مدیریت پیام‌ها ----------------
@app.route("/webhook", methods=["POST"])
def webhook():
  data = request.get_json()
  if not data:
    return jsonify({"status": "ok"})

  if "message" in data:
    msg = data["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "")
    photo = msg.get("photo")
    voice = msg.get("voice") or msg.get("audio")

    # بررسی لینک‌های دعوت (Referral) در دستور start
    if text.startswith("/start"):
      parts = text.split(" ")
      if len(parts) > 1 and parts[1].startswith("ref_"):
        try:
          ref_id = int(parts[1].split("_")[1])
          if ref_id != chat_id and ref_id in profiles:
            referrals[ref_id] = referrals.get(ref_id, 0) + 1
            scores[ref_id] = scores.get(ref_id, 0) + 30
            send_message(ref_id, f"🎉 یک نفر با لینک دعوت شما وارد ربات شد! ۳۰ سکه هدیه گرفتید 🎁")
        except Exception:
          pass

    # بررسی ثبت نام اولیه
    if chat_id not in profiles:
      if chat_id in pending_name:
        nickname = text.strip()
        if not nickname:
          send_message(chat_id, "⚠️ نام مستعار نمی‌تواند خالی باشد. لطفاً نام خود را وارد کنید:")
          return jsonify({"status": "ok"})
        profiles[chat_id] = nickname
        pending_name.remove(chat_id)
        send_message(
            chat_id,
            f"🎉 خوش آمدی {nickname} عزیز!\nحالا می‌تونی از منوی زیر بازی رو شروع کنی:",
            get_main_menu(),
        )
      else:
        pending_name.add(chat_id)
        send_message(
            chat_id,
            "سلام کیا! 🎮 به ربات جرات یا حقیقت خوش اومدی.\nلطفاً یک **نام مستعار** منحصربه‌فرد برای خودت وارد کن:",
        )
      return jsonify({"status": "ok"})

    # بررسی تغییر نام
    if chat_id in pending_new_name:
      new_name = text.strip()
      if new_name:
        profiles[chat_id] = new_name
        pending_new_name.remove(chat_id)
        send_message(chat_id, f"✅ نام مستعار شما با موفقیت به **{new_name}** تغییر کرد!", get_main_menu())
      else:
        send_message(chat_id, "⚠️ نام معتبر نیست. لطفاً یک نام مستعار دیگر وارد کنید:")
      return jsonify({"status": "ok"})

    if text == "/start":
      send_message(
          chat_id,
          f"سلام {profiles[chat_id]} عزیز! خوش برگشتی به ربات جرات یا حقیقت 🚀\nیک گزینه رو انتخاب کن:",
          get_main_menu(),
      )
      return jsonify({"status": "ok"})

    # پردازش ارسال عکس، ویس یا متن برای چالش‌ها
    handle_proof_submissions(chat_id, photo, voice, text)

  elif "callback_query" in data:
    query = data["callback_query"]
    chat_id = query["message"]["chat"]["id"]
    message_id = query["message"]["message_id"]
    data_callback = query["data"]

    handle_callbacks(chat_id, message_id, data_callback)

  return jsonify({"status": "ok"})


def handle_proof_submissions(chat_id, photo, voice, text):
  # بررسی چالش روزانه
  if user_states.get(chat_id) == "waiting_daily_proof":
    user_states.pop(chat_id, None)
    scores[chat_id] = scores.get(chat_id, 0) + 50
    send_message(
        chat_id,
        "✅ چالش روزانه شما تایید شد و ۵۰ سکه به حساب شما واریز گردید! 🌟",
        get_main_menu(),
    )
    return

  # بررسی حالت تک‌نفره
  if chat_id in single_player and single_player[chat_id].get("waiting_for_proof"):
    sp = single_player[chat_id]
    sp["waiting_for_proof"] = False
    scores[chat_id] = scores.get(chat_id, 0) + 15
    send_message(
        chat_id,
        "✅ آفرین! چالش با موفقیت انجام شد و ۱۵ سکه گرفتی! 🌟\nمی‌تونی دوباره بازی کنی:",
        {
            "inline_keyboard": [
                [{"text": "🎲 چالش بعدی", "callback_data": "single_play_start"}],
                [{"text": "🔙 منوی اصلی", "callback_data": "back_to_menu"}],
            ]
        },
    )
    return

  # بررسی اتاق‌های آنلاین
  for room_code, room in rooms.items():
    if chat_id in room["players"] and room.get("state") == "playing":
      if room["current_turn"] == chat_id:
        proof_type = "متن"
        if photo:
          proof_type = "عکس 🖼️"
        elif voice:
          proof_type = "ویس 🎙️"

        room["state"] = "voting"
        nickname = profiles.get(chat_id, "بازیکن")

        voting_markup = {
            "inline_keyboard": [
                [
                    {"text": "👍 قبول (+10 سکه)", "callback_data": f"vote_yes_{room_code}"},
                    {"text": "👎 رد (-)", "callback_data": f"vote_no_{room_code}"},
                ]
            ]
        }

        for p in room["players"]:
          send_message(
              p,
              f"📢 {nickname} چالش خود را با ({proof_type}) انجام داد!\nمتن: {text}\nلطفاً به انجام چالش رأی دهید:",
              voting_markup,
          )
        return


def handle_callbacks(chat_id, message_id, data):
  if data == "back_to_menu":
    send_message(chat_id, "منوی اصلی:", get_main_menu())

  elif data == "change_name":
    pending_new_name.add(chat_id)
    send_message(chat_id, "لطفاً نام مستعار جدید خود را وارد کنید:")

  elif data == "open_shop":
    user_coins = scores.get(chat_id, 0)
    send_message(
        chat_id,
        f"🛍️ **فروشگاه بزرگ ربات**\n\nسکه‌های شما: **{user_coins} 🪙**\n\nیک مورد را برای خرید انتخاب کنید:",
        {
            "inline_keyboard": [
                [{"text": "🛡️ خرید جان اضافه (50 سکه)", "callback_data": "buy_life"}],
                [{"text": "👑 تاج پادشاهی در پروفایل (150 سکه)", "callback_data": "buy_crown"}],
                [{"text": "🔙 بازگشت به منو", "callback_data": "back_to_menu"}],
            ]
        },
    )

  elif data == "buy_life":
    if scores.get(chat_id, 0) >= 50:
      scores[chat_id] -= 50
      user_inventory[chat_id] = user_inventory.get(chat_id, []) + ["جان اضافه"]
      send_message(chat_id, "✅ جان اضافه با موفقیت خریداری شد!")
    else:
      send_message(chat_id, "❌ سکه‌های شما برای خرید این آیتم کافی نیست!")

  elif data == "buy_crown":
    if scores.get(chat_id, 0) >= 150:
      scores[chat_id] -= 150
      user_inventory[chat_id] = user_inventory.get(chat_id, []) + ["تاج پادشاهی 👑"]
      send_message(chat_id, "✅ تاج پادشاهی به پروفایل شما اضافه شد!")
    else:
      send_message(chat_id, "❌ سکه‌های شما برای خرید این آیتم کافی نیست!")

  elif data == "invite_friends":
    bot_username = "jorat_bot"
    invite_link = f"https://ble.ir/{bot_username}?start=ref_{chat_id}"
    send_message(
        chat_id,
        f"👥 **سیستم دعوت از دوستان**\n\nبا ارسال لینک زیر به دوستانتان، به ازای هر نفری که وارد ربات شود **۳۰ سکه** جایزه بگیرید!\n\nلینک اختصاصی شما:\n`{invite_link}`",
        {
            "inline_keyboard": [
                [{"text": "🔙 بازگشت به منو", "callback_data": "back_to_menu"}]
            ]
        },
    )

  elif data == "daily_challenge":
    today_str = time.strftime("%Y-%m-%d")
    if completed_dailies.get(chat_id) == today_str:
      send_message(chat_id, "⚠️ شما چالش امروز را قبلاً انجام داده‌اید. فردا دوباره سر بزنید!")
      return

    completed_dailies[chat_id] = today_str
    user_states[chat_id] = "waiting_daily_proof"
    send_message(
        chat_id,
        "🎯 **چالش ویژه امروز (+50 سکه)**\n\nیک عکس خنده‌دار از میز کار یا اتاق‌تان بفرستید یا یک ویس ۳۰ ثانیه‌ای از خواندن ترانه موردعلاقه‌تان ضبط کنید!",
    )

  elif data == "leaderboard":
    user_score = scores.get(chat_id, 0)
    user_title = get_user_rank_title(user_score)
    user_refs = referrals.get(chat_id, 0)
    inv = ", ".join(user_inventory.get(chat_id, [])) or "ندارد"

    sorted_scores = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:10]
    text = f"👤 پروفایل شما:\n• لقب: {user_title}\n• سکه‌ها: {user_score} 🪙\n• آیتم‌ها: {inv}\n• دوستان دعوت‌شده: {user_refs}\n\n"
    text += "🏆 **جدول برترین‌های بازی (لیدربرد)** 🏆\n\n"
    if not sorted_scores:
      text += "هنوز امتیازی ثبت نشده است!"
    else:
      for idx, (cid, score) in enumerate(sorted_scores, 1):
        name = profiles.get(cid, "ناشناس")
        title = get_user_rank_title(score)
        text += f"{idx}. {name} ({title}) ⟵ {score} سکه\n"
    send_message(
        chat_id,
        text,
        {
            "inline_keyboard": [
                [{"text": "🔙 بازگشت به منو", "callback_data": "back_to_menu"}]
            ]
        },
    )

  elif data == "menu_single":
    send_message(chat_id, "لطفاً مود بازی تک‌نفره را انتخاب کنید:", get_game_modes_keyboard())
    user_states[chat_id] = "choosing_single_mode"

  elif data.startswith("mode_") and user_states.get(chat_id) == "choosing_single_mode":
    mode = data.split("_")[1]
    single_player[chat_id] = {"mode": mode, "waiting_for_proof": False}
    user_states[chat_id] = "playing_single"
    start_single_game_turn(chat_id)

  elif data == "single_play_start":
    start_single_game_turn(chat_id)

  elif data == "menu_online":
    send_message(
        chat_id,
        "🎮 بخش اتاق‌های آنلاین:\nیک گزینه را انتخاب کنید:",
        {
            "inline_keyboard": [
                [{"text": "🛠️ ساخت اتاق جدید", "callback_data": "create_room"}],
                [{"text": "🚪 پیوستن به اتاق‌ها", "callback_data": "list_rooms"}],
                [{"text": "🔙 بازگشت", "callback_data": "back_to_menu"}],
            ]
        },
    )

  elif data == "create_room":
    send_message(chat_id, "لطفاً مود اتاق آنلاین را انتخاب کنید:", get_game_modes_keyboard())
    user_states[chat_id] = "choosing_room_mode"

  elif data.startswith("mode_") and user_states.get(chat_id) == "choosing_room_mode":
    mode = data.split("_")[1]
    room_code = str(random.randint(1000, 9999))
    
    # تعیین مأموریت مخفی برای میزبان
    secret_missions = [
        "کاری کن یکی از بازیکنان کلمه 'سلام' بگه.",
        "کاری کن یکی از بازیکنان کلمه 'چطور' رو تایپ کنه.",
        "بدون اینکه کسی بفهمه، سه بار پشت سر هم ایموجی ❤️ بفرست."
    ]
    
    rooms[room_code] = {
        "host": chat_id,
        "players": [chat_id],
        "state": "waiting",
        "current_turn": None,
        "mode": mode,
        "secret_missions": {chat_id: random.choice(secret_missions)}
    }
    user_states.pop(chat_id, None)
    
    send_message(
        chat_id,
        f"✅ اتاق با موفقیت ساخته شد!\nکد اتاق: `{room_code}`\n\n🕵️ **مأموریت مخفی شما:**\n{rooms[room_code]['secret_missions'][chat_id]}\n*(اگر موفق شدی انجامش بدی، کلی سکه پاداش می‌گیری!)*",
        {
            "inline_keyboard": [
                [{"text": "🚀 شروع بازی", "callback_data": f"start_room_{room_code}"}],
                [{"text": "🗑️ حذف اتاق", "callback_data": f"delete_room_{room_code}"}],
            ]
        },
    )

  elif data == "list_rooms":
    if not rooms:
      send_message(chat_id, "❌ هیچ اتاق فعالی وجود ندارد. می‌توانید یک اتاق جدید بسازید!", get_main_menu())
      return
    keyboard = []
    for r_code, r_info in rooms.items():
      if r_info["state"] == "waiting":
        p_count = len(r_info["players"])
        keyboard.append([{"text": f"اتاق {r_code} (بازیکنان: {p_count}) [{r_info['mode']}]", "callback_data": f"join_room_{r_code}"}])
    keyboard.append([{"text": "🔙 بازگشت", "callback_data": "menu_online"}])
    send_message(chat_id, "لیست اتاق‌های آماده‌ی پیوستن:", {"inline_keyboard": keyboard})

  elif data.startswith("join_room_"):
    room_code = data.split("_")[2]
    if room_code in rooms and rooms[room_code]["state"] == "waiting":
      if chat_id not in rooms[room_code]["players"]:
        rooms[room_code]["players"].append(chat_id)
        
        # اختصاص مأموریت مخفی به بازیکن جدید
        secret_missions = [
            "کاری کن یکی از بازیکنان کلمه 'سلام' بگه.",
            "کاری کن یکی از بازیکنان کلمه 'چطور' رو تایپ کنه.",
            "بدون اینکه کسی بفهمه، سه بار پشت سر هم ایموجی ❤️ بفرست."
        ]
        rooms[room_code]["secret_missions"][chat_id] = random.choice(secret_missions)

      send_message(
          chat_id,
          f"✅ با موفقیت به اتاق {room_code} پیوستید!\n\n🕵️ **مأموریت مخفی شما:**\n{rooms[room_code]['secret_missions'][chat_id]}\n\nمنتظر شروع بازی از طرف میزبان باشید."
      )
      host_id = rooms[room_code]["host"]
      send_message(host_id, f"👤 بازیکن {profiles.get(chat_id, 'ناشناس')} به اتاق پیوست.")
    else:
      send_message(chat_id, "⚠️ این اتاق دیگر وجود ندارد یا بازی آن شروع شده است.")

  elif data.startswith("start_room_"):
    room_code = data.split("_")[2]
    if room_code in rooms and rooms[room_code]["host"] == chat_id:
      room = rooms[room_code]
      room["state"] = "playing"
      room["current_turn"] = room["players"][0]
      notify_room_turn(room_code)

  elif data.startswith("delete_room_"):
    room_code = data.split("_")[2]
    if room_code in rooms and rooms[room_code]["host"] == chat_id:
      for p in rooms[room_code]["players"]:
        send_message(p, "❌ اتاق توسط میزبان بسته شد.")
      del rooms[room_code]
      send_message(chat_id, "🗑️ اتاق با موفقیت حذف شد.", get_main_menu())

  elif data.startswith("spin_wheel_"):
    room_code = data.split("_")[2]
    if room_code in rooms and rooms[room_code]["current_turn"] == chat_id:
      chosen_type = random.choice(["truth", "dare"])
      type_name = "حقیقت 🎯" if chosen_type == "truth" else "جرات 🔥"
      
      prompt_text = get_random_prompt(rooms[room_code]["mode"], chosen_type)
      nickname = profiles.get(chat_id, "بازیکن")
      
      for p in rooms[room_code]["players"]:
        send_message(
            p,
            f"🎡 چرخ شانس چرخید!\n\nنوبت: {nickname}\nقرعه افتاد روی: **{type_name}**\n\nسوال/چالش: {prompt_text}\n\n*(جواب خود را به صورت متن، عکس یا ویس ارسال کنید)*",
        )

  elif data.startswith("vote_yes_"):
    room_code = data.split("_")[2]
    if room_code in rooms:
      room = rooms[room_code]
      turn_player = room["current_turn"]
      scores[turn_player] = scores.get(turn_player, 0) + 10
      send_message(chat_id, "✅ رأی شما (قبول) ثبت شد (+10 سکه).")
      
      players = room["players"]
      curr_idx = players.index(turn_player)
      next_idx = (curr_idx + 1) % len(players)
      room["current_turn"] = players[next_idx]
      room["state"] = "playing"
      notify_room_turn(room_code)

  elif data.startswith("vote_no_"):
    room_code = data.split("_")[2]
    if room_code in rooms:
      room = rooms[room_code]
      send_message(chat_id, "❌ رأی شما (رد) ثبت شد.")
      turn_player = room["current_turn"]
      
      players = room["players"]
      curr_idx = players.index(turn_player)
      next_idx = (curr_idx + 1) % len(players)
      room["current_turn"] = players[next_idx]
      room["state"] = "playing"
      notify_room_turn(room_code)


def start_single_game_turn(chat_id):
  sp = single_player[chat_id]
  chosen_type = random.choice(["truth", "dare"])
  sp["current_type"] = chosen_type
  type_name = "حقیقت 🎯" if chosen_type == "truth" else "جرات 🔥"
  prompt = get_random_prompt(sp["mode"], chosen_type)
  sp["waiting_for_proof"] = True

  send_message(
      chat_id,
      f"🤖 حالت تک‌نفره (مود: {sp['mode']})\n\nقرعه: **{type_name}**\nچالش شما: {prompt}\n\n*(برای ثبت امتیاز، پاسخ، عکس یا ویس خود را بفرستید)*",
  )


def get_random_prompt(mode, p_type):
  prompts = {
      "normal": {
          "truth": ["بزرگترین گند زندگیت چی بوده؟", "تا حالا توی جمع شکم درد گرفتی و خودتو زدی به اون راه؟"],
          "dare": ["یک وویس ۱ دقیقه‌ای با صدای خنده‌دار بفرست.", "آخرین عکسی که توی گوشیت ذخیره شده رو بفرست."],
      },
      "fun": {
          "truth": ["اگه قرار باشه یک نفر رو توی این گروه از بازی بیرون کنی کیه؟", "عجیب‌ترین جایی که خوابت برده کجا بوده؟"],
          "dare": ["یک عکس سلفی با قیافه خیلی عجیب بفرست.", "اسم سه تا از کراش‌های سابقت رو اعتراف کن!"],
      },
      "scary": {
          "truth": ["ترسناک‌ترین تجربه‌ای که توی تاریکی داشتی چی بوده؟", "تا حالا حس کردی یک روح توی اتاقت هست؟"],
          "dare": ["چراغ‌ها رو خاموش کن و یک ویس با صدای ترسناک بفرست.", "یک داستان کوتاه ترسناک همین الان تایپ کن و بفرست."],
      },
  }
  return random.choice(prompts.get(mode, prompts["normal"])[p_type])


def notify_room_turn(room_code):
  room = rooms[room_code]
  turn_player = room["current_turn"]
  nickname = profiles.get(turn_player, "بازیکن")

  for p in room["players"]:
    if p == turn_player:
      send_message(
          p,
          f"🎯 نوبت شماست در اتاق {room_code}!\nبرای تعیین نوع چالش روی دکمه زیر بزنید:",
          {"inline_keyboard": [[{"text": "🎡 چرخش چرخ شانس", "callback_data": f"spin_wheel_{room_code}"}]]},
      )
    else:
      send_message(p, f"⏳ نوبت {nickname} است که چالش خود را انتخاب کند...")


# ---------------- مکانیزم نگهداری ربات روشن روی Render ----------------
def keep_alive():
  while True:
    try:
      requests.get(RENDER_URL, timeout=10)
    except Exception:
      pass
    time.sleep(240)


if __name__ == "__main__":
  threading.Thread(target=keep_alive, daemon=True).start()
  port = int(os.environ.get("PORT", 5000))
  app.run(host="0.0.0.0", port=port)
