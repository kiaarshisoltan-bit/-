import os
import random
import threading
import time
import requests

# توکن و تنظیمات اصلی ربات بله
BOT_TOKEN = "*******"
BASE_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
RENDER_URL = (  # آدرس رندر شما برای پینگ نگه داشتن ربات
    "https://jorat-bot.onrender.com"
)

# پایگاه داده در حافظه
profiles = {}  # chat_id -> nickname
pending_name = set()
pending_new_name = set()
rooms = {}  # room_code -> dict
single_player = {}  # chat_id -> dict
scores = {}  # chat_id -> score
user_states = {}  # chat_id -> state


def send_message(chat_id, text, reply_markup=None):
  url = f"{BASE_URL}/sendMessage"
  payload = {"chat_id": chat_id, "text": text}
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error sending message: {e}")


def edit_message_text(chat_id, message_id, text, reply_markup=None):
  url = f"{BASE_URL}/editMessageText"
  payload = {"chat_id": chat_id, "message_id": message_id, "text": text}
  if reply_markup:
    payload["reply_markup"] = reply_markup
  try:
    requests.post(url, json=payload, timeout=5)
  except Exception as e:
    print(f"Error editing message: {e}")


def get_main_menu():
  return {
      "inline_keyboard": [
          [
              {"text": "🎮 اتاق‌های آنلاین", "callback_data": "menu_online"},
              {"text": "🤖 بازی تک‌نفره", "callback_data": "menu_single"},
          ],
          [
              {"text": "🏆 جدول امتیازات", "callback_data": "leaderboard"},
              {"text": "✏️ تغییر نام مستعار", "callback_data": "change_name"},
          ],
          [
              {"text": "📢 کانال اطلاع‌رسانی", "url": "https://ble.ir/ettelae_resani"},
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
          [{"text": "🔙 بازگشت", "callback_data": "back_to_menu"}],
      ]
  }


def get_random_prompt(mode, p_type):
  prompts = {
      "normal": {
          "truth": [
              "بزرگترین گند زندگیت چی بوده؟",
              "تا حالا توی جمع شکم درد گرفتی و خودتو زدی به اون راه؟",
          ],
          "dare": [
              "یک وویس ۱ دقیقه‌ای با صدای خنده‌دار بفرست.",
              "آخرین عکسی که توی گوشیت ذخیره شده رو بفرست.",
          ],
      },
      "fun": {
          "truth": [
              "اگه قرار باشه یک نفر رو توی این گروه از بازی بیرون کنی کیه؟",
              "عجیب‌ترین جایی که خوابت برده کجا بوده؟",
          ],
          "dare": [
              "یک عکس سلفی با قیافه خیلی عجیب بفرست.",
              "اسم سه تا از کراش‌های سابقت رو اعتراف کن!",
          ],
      },
      "scary": {
          "truth": [
              "ترسناک‌ترین تجربه‌ای که توی تاریکی داشتی چی بوده؟",
              "تا حالا حس کردی یک روح توی اتاقت هست؟",
          ],
          "dare": [
              "چراغ‌ها رو خاموش کن و یک ویس با صدای ترسناک بفرست.",
              "یک داستان کوتاه ترسناک همین الان تایپ کن و بفرست.",
          ],
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
          f"🎯 نوبت شماست در اتاق {room_code}!\nبرای تعیین نوع چالش (جرات یا حقیقت)"
          " روی دکمه زیر بزنید:",
          {
              "inline_keyboard": [[{
                  "text": "🎡 چرخش چرخ شانس",
                  "callback_data": f"spin_wheel_{room_code}",
              }]]
          },
      )
    else:
      send_message(p, f"⏳ نوبت {nickname} است که چالش خود را انتخاب کند...")


def start_single_game_turn(chat_id):
  sp = single_player[chat_id]
  chosen_type = random.choice(["truth", "dare"])
  sp["current_type"] = chosen_type
  type_name = "حقیقت 🎯" if chosen_type == "truth" else "جرات 🔥"
  prompt = get_random_prompt(sp["mode"], chosen_type)
  sp["waiting_for_proof"] = True

  send_message(
      chat_id,
      f"🤖 حالت تک‌نفره (مود: {sp['mode']})\n\nقرعه:"
      f" **{type_name}**\nچالش شما: {prompt}\n\n*(برای ثبت امتیاز، پاسخ، عکس یا"
      " ویس خود را بفرستید)*",
  )


# پردازش آپدیت‌ها در حالت پولینگ
def handle_update(update):
  if "message" in update:
    msg = update["message"]
    chat_id = msg["chat"]["id"]
    text = msg.get("text", "").strip()

    if chat_id not in profiles:
      if chat_id in pending_name:
        if not text:
          send_message(
              chat_id,
              "⚠️ نام مستعار نمی‌تواند خالی باشد. لطفاً نام خود را وارد کنید:",
          )
          return
        profiles[chat_id] = text
        pending_name.remove(chat_id)
        send_message(
            chat_id,
            f"🎉 خوش آمدی **{text}** عزیز!\nحساب کاربریت ساخته شد.",
            reply_markup=get_main_menu(),
        )
      else:
        pending_name.add(chat_id)
        send_message(
            chat_id,
            "سلام کیا! 🎮 به ربات جرات یا حقیقت خوش اومذی.\nلطفاً یک **نام"
            " مستعار** منحصربه‌فرد برای خودت وارد کن:",
        )
      return

    if chat_id in pending_new_name:
      new_name = text.strip()
      if new_name:
        profiles[chat_id] = new_name
        pending_new_name.remove(chat_id)
        send_message(
            chat_id,
            f"✅ نام مستعار شما با موفقیت به **{new_name}** تغییر کرد!",
            reply_markup=get_main_menu(),
        )
      else:
        send_message(
            chat_id, "⚠️ نام معتبر نیست. لطفاً یک نام مستعار دیگر وارد کنید:"
        )
      return

    if text == "/start":
      send_message(
          chat_id,
          f"سلام {profiles[chat_id]} عزیز! خوش برگشتی به ربات جرات یا حقیقت"
          f" 🚀\nیک گزینه رو انتخاب کن:",
          reply_markup=get_main_menu(),
      )
      return

    # تک‌نفره
    if chat_id in single_player and single_player[chat_id].get(
        "waiting_for_proof"
    ):
      single_player[chat_id]["waiting_for_proof"] = False
      scores[chat_id] = scores.get(chat_id, 0) + 10
      send_message(
          chat_id,
          "✅ آفرین! چالش با موفقیت انجام شد و ۱۰ امتیاز گرفتی! 🌟",
          reply_markup={
              "inline_keyboard": [
                  [
                      {
                          "text": "🎲 چالش بعدی",
                          "callback_data": "single_play_start",
                      }
                  ],
                  [{"text": "🔙 منوی اصلی", "callback_data": "back_to_menu"}],
              ]
          },
      )
      return

    # ارسال پاسخ در اتاق آنلاین
    for r_code, r_info in rooms.items():
      if r_info.get("state") == "playing" and r_info.get(
          "current_turn"
      ) == chat_id:
        r_info["waiting_vote_for"] = chat_id
        nickname = profiles.get(chat_id, "بازیکن")
        for p in r_info["players"]:
          send_message(
              p,
              f"📢 بازیکن **{nickname}** پاسخ خود را ارسال کرد:\n\n💬"
              f" {text or '[عکس/ویس]'}\n\nآیا چالش به درستی انجام شده است؟",
              reply_markup={
                  "inline_keyboard": [[
                      {
                          "text": "👍 بله (+امتیاز)",
                          "callback_data": f"vote_yes_{r_code}",
                      },
                      {
                          "text": "👎 خیر",
                          "callback_data": f"vote_no_{r_code}",
                      },
                  ]]
              },
          )
        break

  elif "callback_query" in update:
    query = update["callback_query"]
    chat_id = query["message"]["chat"]["id"]
    message_id = query["message"]["message_id"]
    data = query["data"]

    if data == "back_to_menu":
      user_states.pop(chat_id, None)
      edit_message_text(
          chat_id,
          message_id,
          "به منوی اصلی برگشتید:",
          reply_markup=get_main_menu(),
      )

    elif data == "change_name":
      pending_new_name.add(chat_id)
      send_message(chat_id, "لطفاً نام مستعار جدید خود را وارد کنید:")

    elif data == "leaderboard":
      sorted_scores = sorted(
          scores.items(), key=lambda x: x[1], reverse=True
      )[:10]
      lb_text = "🏆 **جدول برترین‌های بازی (لیدربرد)** 🏆\n\n"
      if not sorted_scores:
        lb_text += "هنوز امتیازی ثبت نشده است!"
      else:
        for idx, (cid, score) in enumerate(sorted_scores, 1):
          name = profiles.get(cid, "ناشناس")
          lb_text += f"{idx}. {name} ⟵ {score} امتیاز\n"
      send_message(
          chat_id,
          lb_text,
          reply_markup={
              "inline_keyboard": [[{
                  "text": "🔙 بازگشت به منو",
                  "callback_data": "back_to_menu",
              }]]
          },
      )

    elif data == "menu_single":
      send_message(
          chat_id,
          "لطفاً مود بازی تک‌نفره را انتخاب کنید:",
          reply_markup=get_game_modes_keyboard(),
      )
      user_states[chat_id] = "choosing_single_mode"

    elif data.startswith("mode_") and user_states.get(chat_id) in [
        "choosing_single_mode",
        "choosing_room_mode",
    ]:
      mode = data.split("_")[1]
      if user_states.get(chat_id) == "choosing_single_mode":
        single_player[chat_id] = {"mode": mode, "waiting_for_proof": False}
        user_states[chat_id] = "playing_single"
        start_single_game_turn(chat_id)
      elif user_states.get(chat_id) == "choosing_room_mode":
        room_code = str(random.randint(1000, 9999))
        rooms[room_code] = {
            "host": chat_id,
            "players": [chat_id],
            "state": "waiting",
            "current_turn": None,
            "mode": mode,
        }
        user_states.pop(chat_id, None)
        send_message(
            chat_id,
            f"✅ اتاق با موفقیت ساخته شد!\nکد اتاق شما: `{room_code}`\nمود"
            f" بازی: {mode}",
            reply_markup={
                "inline_keyboard": [
                    [
                        {
                            "text": "🚀 شروع بازی",
                            "callback_data": f"start_room_{room_code}",
                        },
                        {
                            "text": "🗑️ حذف اتاق",
                            "callback_data": f"delete_room_{room_code}",
                        },
                    ],
                    [{"text": "🔙 بازگشت به منو", "callback_data": "back_to_menu"}],
                ]
            },
        )

    elif data == "single_play_start":
      start_single_game_turn(chat_id)

    elif data == "single_truth":
      truths = [
          "بزرگترین گناهی که تا حالا کردی چی بوده؟",
          "اگر غیب می‌شدی، اولین جایی که می‌رفتی کجا بود؟",
      ]
      scores[chat_id] = scores.get(chat_id, 0) + 5
      send_message(chat_id, f"🧐 **حقیقت:** {random.choice(truths)}\n(+۵ امتیاز)")
      edit_message_text(
          chat_id,
          message_id,
          "پاسخ دادی! می‌تونی دوباره انتخاب کنی:",
          reply_markup={
              "inline_keyboard": [
                  [
                      {
                          "text": "🎲 چالش بعدی",
                          "callback_data": "single_play_start",
                      }
                  ],
                  [{"text": "🔙 منوی اصلی", "callback_data": "back_to_menu"}],
              ]
          },
      )

    elif data == "single_dare":
      dares = [
          "یک ویس ۱۰ ثانیه‌ای با صدای خنده‌دار بفرست.",
          "آخرین عکسی که تو گوشیت داری رو بفرست.",
      ]
      if chat_id not in single_player:
        single_player[chat_id] = {}
      single_player[chat_id]["waiting_for_proof"] = True
      send_message(
          chat_id,
          f"🔥 **جرئت:** {random.choice(dares)}\n\n(لطفاً عکس، ویس یا متن انجام"
          " چالش رو بفرست تا امتیاز بگیری!)",
      )

    elif data == "menu_online":
      send_message(
          chat_id,
          "🎮 بخش اتاق‌های آنلاین:\nیک گزینه را انتخاب کنید:",
          reply_markup={
              "inline_keyboard": [
                  [
                      {
                          "text": "🛠️ ساخت اتاق جدید",
                          "callback_data": "create_room",
                      }
                  ],
                  [
                      {
                          "text": "🚪 پیوستن به اتاق‌ها",
                          "callback_data": "list_rooms",
                      }
                  ],
                  [{"text": "🔙 بازگشت", "callback_data": "back_to_menu"}],
              ]
          },
      )

    elif data == "create_room":
      send_message(
          chat_id,
          "لطفاً مود اتاق آنلاین را انتخاب کنید:",
          reply_markup=get_game_modes_keyboard(),
      )
      user_states[chat_id] = "choosing_room_mode"

    elif data == "list_rooms":
      if not rooms:
        send_message(
            chat_id,
            "❌ هیچ اتاق فعالی وجود ندارد. می‌توانید یک اتاق جدید بسازید!",
            get_main_menu(),
        )
        return
      keyboard = []
      for r_code, r_info in rooms.items():
        if r_info["state"] == "waiting":
          p_count = len(r_info["players"])
          keyboard.append([{
              "text": (
                  f"اتاق {r_code} (بازیکنان: {p_count}) [{r_info['mode']}]"
              ),
              "callback_data": f"join_room_{r_code}",
          }])
      keyboard.append([{"text": "🔙 بازگشت", "callback_data": "menu_online"}])
      send_message(
          chat_id,
          "لیست اتاق‌های آماده‌ی پیوستن:",
          {"inline_keyboard": keyboard},
      )

    elif data.startswith("join_room_"):
      room_code = data.split("_")[2]
      if room_code in rooms and rooms[room_code]["state"] == "waiting":
        if chat_id not in rooms[room_code]["players"]:
          rooms[room_code]["players"].append(chat_id)
        send_message(
            chat_id,
            f"✅ با موفقیت به اتاق {room_code} پیوستید! منتظر شروع بازی از طرف"
            " میزبان باشید.",
        )
        host_id = rooms[room_code]["host"]
        send_message(
            host_id, f"👤 بازیکن {profiles.get(chat_id, 'ناشناس')} به اتاق پیوست."
        )
      else:
        send_message(
            chat_id, "⚠️ این اتاق دیگر وجود ندارد یا بازی آن شروع شده است."
        )

    elif data.startswith("start_room_"):
      room_code = data.split("_")[2]
      if room_code in rooms and rooms[room_code]["host"] == chat_id:
        room = rooms[room_code]
        if len(room["players"]) < 1:
          send_message(chat_id, "⚠️ تعداد بازیکنان کافی نیست!")
          return
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
        rooms[room_code]["target_type"] = chosen_type

        prompt_text = get_random_prompt(rooms[room_code]["mode"], chosen_type)
        nickname = profiles.get(chat_id, "بازیکن")

        for p in rooms[room_code]["players"]:
          send_message(
              p,
              f"🎡 چرخ شانس چرخید!\n\nنوبت: {nickname}\nقرعه افتاد روی:"
              f" **{type_name}**\n\nسوال/چالش: {prompt_text}\n\n*(جواب خود را"
              " به صورت متن، عکس یا ویس ارسال کنید)*",
          )

    elif data.startswith("vote_yes_"):
      room_code = data.split("_")[2]
      if room_code in rooms:
        room = rooms[room_code]
        turn_player = room.get("waiting_vote_for") or room["current_turn"]
        scores[turn_player] = scores.get(turn_player, 0) + 10
        send_message(chat_id, "✅ رأی شما (قبول) ثبت شد (+10 امتیاز برای بازیکن).")

        players = room["players"]
        curr_idx = (
            players.index(turn_player) if turn_player in players else 0
        )
        next_idx = (curr_idx + 1) % len(players)
        room["current_turn"] = players[next_idx]
        room["state"] = "playing"
        room.pop("waiting_vote_for", None)
        notify_room_turn(room_code)

    elif data.startswith("vote_no_"):
      room_code = data.split("_")[2]
      if room_code in rooms:
        room = rooms[room_code]
        send_message(chat_id, "❌ رأی شما (رد) ثبت شد.")
        turn_player = room.get("waiting_vote_for") or room["current_turn"]

        players = room["players"]
        curr_idx = (
            players.index(turn_player) if turn_player in players else 0
        )
        next_idx = (curr_idx + 1) % len(players)
        room["current_turn"] = players[next_idx]
        room["state"] = "playing"
        room.pop("waiting_vote_for", None)
        notify_room_turn(room_code)


# ---------------- مکانیزم نگهداری ربات روشن روی Render ----------------
def keep_alive():
  while True:
    try:
      requests.get(RENDER_URL, timeout=10)
    except Exception:
      pass
    time.sleep(240)  # هر ۴ دقیقه یک‌بار


# ---------------- حلقه اصلی پولینگ (Long Polling) ----------------
def run_polling():
  offset = 0
  print("Bot polling started...")
  while True:
    try:
      url = f"{BASE_URL}/getUpdates?offset={offset}&timeout=30"
      response = requests.get(url, timeout=35)
      if response.status_code == 200:
        data = response.json()
        if data.get("ok"):
          for update in data.get("result", []):
            offset = update["update_id"] + 1
            threading.Thread(
                target=handle_update, args=(update,), daemon=True
            ).start()
    except Exception as e:
      print(f"Polling error: {e}")
      time.sleep(3)


if __name__ == "__main__":
  # شروع ترد پینگ نگهدارنده ربات
  threading.Thread(target=keep_alive, daemon=True).start()
  # شروع حلقه پولینگ ربات
  run_polling()
