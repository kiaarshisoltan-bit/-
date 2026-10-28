مهراب: import os
import random
import sqlite3
import secrets
import logging
from datetime import datetime, date
from zoneinfo import ZoneInfo

import requests
from flask import Flask, request, jsonify

# ==================================================
# تنظیمات اصلی
# ==================================================

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

BOT_TOKEN = os.environ.get("BALE_BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()

if not BOT_TOKEN:
    logging.warning("BALE_BOT_TOKEN تنظیم نشده است.")

BALE_API_URL = f"https://tapi.bale.ai/bot{BOT_TOKEN}"
DB_PATH = os.environ.get("DB_PATH", "game.db")

# برای ایران
def today_iran():
    return datetime.now(ZoneInfo("Asia/Tehran")).date().isoformat()


TRUTHS = [
    "بامزه‌ترین خاطره‌ای که از مدرسه داری چیست؟",
    "اگر یک قدرت جادویی داشتی، چه قدرتی انتخاب می‌کردی؟",
    "تا حالا به خاطر یک اشتباه خنده‌دار شده‌ای؟",
    "دوست داری در چه چیزی بهترین دنیا باشی؟",
    "اگر یک روز نامرئی شوی، چه کار بی‌خطری می‌کنی؟",
    "کدام عادت خودت را دوست داری تغییر بدهی؟",
    "خنده‌دارترین اتفاق امسالت چه بوده؟",
    "اگر می‌توانستی به گذشته بروی، به خودت چه می‌گفتی؟",
    "چه مهارتی را دوست داری یاد بگیری؟",
    "بهترین هدیه‌ای که گرفته‌ای چه بوده؟",
]

DARES = [
    "در یک پیام، یک لطیفه تعریف کن! 😂",
    "اسم سه حیوان را در پنج ثانیه بنویس! 🐱",
    "یک جمله بامزه بدون استفاده از حرف «م» بنویس!",
    "در یک پیام، صدای یک حیوان را با کلمات تقلید کن!",
    "یک تعریف محترمانه از یکی از دوستانت بنویس!",
    "با سه ایموجی، حال امروزت را توصیف کن!",
    "یک معمای کوتاه برای دوستانت بفرست!",
    "اسم پنج خوراکی را بدون تکرار بنویس!",
    "یک جمله بساز که هم «اژدها» داشته باشد هم «هندوانه»!",
    "یک پیام انگیزشی برای گروه بنویس!",
]

SHOP = {
    "crown": {"name": "تاج طلایی", "price": 500},
    "color": {"name": "نام ویژه", "price": 200},
    "shield": {"name": "سپر امتیاز", "price": 150},
}

START_COINS = 100
NAME_REWARD = 15
DAILY_REWARD = 30
ROOM_REWARD = 10

# ==================================================
# پایگاه داده
# ==================================================

def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                chat_id INTEGER PRIMARY KEY,
                nickname TEXT NOT NULL COLLATE NOCASE UNIQUE,
                coins INTEGER NOT NULL DEFAULT 100,
                created_at TEXT NOT NULL,
                referred_by INTEGER,
                daily_date TEXT,
                daily_streak INTEGER NOT NULL DEFAULT 0
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS rooms (
                code TEXT PRIMARY KEY,
                host_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_members (
                room_code TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                PRIMARY KEY (room_code, chat_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                item_key TEXT NOT NULL,
                purchased_at TEXT NOT NULL,
                UNIQUE(chat_id, item_key)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS game_stats (
                chat_id INTEGER PRIMARY KEY,
                games_played INTEGER NOT NULL DEFAULT 0,
                truth_count INTEGER NOT NULL DEFAULT 0,
                dare_count INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(chat_id) REFERENCES users(chat_id)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_claims (
مهراب: chat_id INTEGER NOT NULL,
                claim_date TEXT NOT NULL,
                PRIMARY KEY(chat_id, claim_date)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS room_games (
                room_code TEXT PRIMARY KEY,
                current_player INTEGER,
                current_kind TEXT,
                current_question TEXT,
                FOREIGN KEY(room_code) REFERENCES rooms(code)
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS referrals (
                invited_id INTEGER PRIMARY KEY,
                inviter_id INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
        """)


init_db()

# ==================================================
# ارتباط با بله
# ==================================================

def send_message(chat_id, text, reply_markup=None):
    if not BOT_TOKEN:
        logging.error("توکن ربات تنظیم نشده است.")
        return None

    payload = {"chat_id": chat_id, "text": text}

    if reply_markup:
        payload["reply_markup"] = reply_markup

    try:
        response = requests.post(
            f"{BALE_API_URL}/sendMessage",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()

        if not result.get("ok", True):
            logging.error("Bale API error: %s", result)

        return result

    except (requests.RequestException, ValueError) as exc:
        logging.error("ارسال پیام ناموفق بود: %s", exc)
        return None


def main_menu():
    return {
        "keyboard": [
            [{"text": "🎮 بازی چندنفره"}, {"text": "🤖 بازی تک‌نفره"}],
            [{"text": "🏆 جدول رده‌بندی"}, {"text": "💰 سکه و فروشگاه"}],
            [{"text": "🎁 چالش روزانه"}, {"text": "🕵️‍♂️ مأمور مخفی"}],
            [{"text": "👥 دعوت دوستان"}, {"text": "✏️ تغییر نام"}],
            [{"text": "📊 آمار من"}, {"text": "❓ راهنما"}],
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False,
    }


def submenu(rows):
    rows.append([{"text": "🏠 منوی اصلی"}])
    return {"keyboard": rows, "resize_keyboard": True}


# ==================================================
# کاربران و نام مستعار
# ==================================================

pending_name = set()
pending_room_code = set()
pending_action = {}
pending_referral = {}

def get_user(chat_id):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()


def create_user(chat_id, nickname):
    with db() as conn:
        conn.execute(
            """INSERT INTO users
               (chat_id, nickname, coins, created_at)
               VALUES (?, ?, ?, ?)""",
            (chat_id, nickname, START_COINS, datetime.now().isoformat()),
        )
        conn.execute(
            "INSERT OR IGNORE INTO game_stats (chat_id) VALUES (?)",
            (chat_id,),
        )


def valid_nickname(name):
    name = name.strip()

    if not 2 <= len(name) <= 20:
        return False

    if name.startswith("/") or any(ord(c) < 32 for c in name):
        return False

    return True


def award_coins(chat_id, amount):
    with db() as conn:
        conn.execute(
            "UPDATE users SET coins = coins + ? WHERE chat_id = ?",
            (amount, chat_id),
        )


def add_game_stat(chat_id, kind):
    with db() as conn:
        conn.execute("""
            INSERT OR IGNORE INTO game_stats (chat_id)
            VALUES (?)
        """, (chat_id,))

        if kind == "truth":
            conn.execute("""
                UPDATE game_stats
                SET games_played = games_played + 1,
                    truth_count = truth_count + 1
                WHERE chat_id = ?
            """, (chat_id,))
        elif kind == "dare":
            conn.execute("""
                UPDATE game_stats
                SET games_played = games_played + 1,
                    dare_count = dare_count + 1
                WHERE chat_id = ?
            """, (chat_i
مهراب: d,))


def process_referral(new_id, inviter_id):
    if new_id == inviter_id or not get_user(inviter_id):
        return False

    with db() as conn:
        already = conn.execute(
            "SELECT 1 FROM referrals WHERE invited_id = ?",
            (new_id,),
        ).fetchone()

        if already:
            return False

        conn.execute("""
            INSERT INTO referrals (invited_id, inviter_id, created_at)
            VALUES (?, ?, ?)
        """, (new_id, inviter_id, datetime.now().isoformat()))

        conn.execute(
            "UPDATE users SET coins = coins + 50 WHERE chat_id = ?",
            (inviter_id,),
        )

    send_message(inviter_id, "🎉 یک دوست با لینک تو ثبت‌نام کرد! ۵۰ سکه گرفتی.")
    return True


# ==================================================
# بازی تک‌نفره
# ==================================================

def play_single(chat_id, kind):
    if kind == "truth":
        question = random.choice(TRUTHS)
        title = "❓ حقیقت"
    else:
        question = random.choice(DARES)
        title = "🔥 جرئت"

    add_game_stat(chat_id, kind)
    award_coins(chat_id, 5)

    send_message(
        chat_id,
        f"{title}\n\n{question}\n\n🎁 ۵ سکه بابت شرکت در بازی گرفتی!",
        submenu([
            [{"text": "❓ حقیقت"}, {"text": "🔥 جرئت"}],
            [{"text": "🎡 چرخ شانس"}],
        ]),
    )


# ==================================================
# اتاق‌های چندنفره
# ==================================================

def create_room(chat_id):
    with db() as conn:
        existing = conn.execute("""
            SELECT r.code
            FROM rooms r
            JOIN room_members m ON m.room_code = r.code
            WHERE r.host_id = ? AND r.status = 'open'
            LIMIT 1
        """, (chat_id,)).fetchone()

        if existing:
            return existing["code"]

        code = None
        for _ in range(20):
            candidate = str(random.randint(1000, 9999))
            exists = conn.execute(
                "SELECT 1 FROM rooms WHERE code = ?",
                (candidate,),
            ).fetchone()

            if not exists:
                code = candidate
                break

        if code is None:
            raise RuntimeError("ساخت کد اتاق ناموفق بود.")

        conn.execute("""
            INSERT INTO rooms (code, host_id, status, created_at)
            VALUES (?, ?, 'open', ?)
        """, (code, chat_id, datetime.now().isoformat()))

        conn.execute("""
            INSERT INTO room_members (room_code, chat_id, joined_at)
            VALUES (?, ?, ?)
        """, (code, chat_id, datetime.now().isoformat()))

    return code


def room_members(code):
    with db() as conn:
        return conn.execute("""
            SELECT u.chat_id, u.nickname
            FROM room_members m
            JOIN users u ON u.chat_id = m.chat_id
            WHERE m.room_code = ?
            ORDER BY m.joined_at
        """, (code,)).fetchall()


def join_room(chat_id, code):
    with db() as conn:
        room = conn.execute(
            "SELECT * FROM rooms WHERE code = ? AND status = 'open'",
            (code,),
        ).fetchone()

        if not room:
            return False, "این اتاق وجود ندارد یا بسته شده است."

        existing = conn.execute("""
            SELECT 1 FROM room_members
            WHERE room_code = ? AND chat_id = ?
        """, (code, chat_id)).fetchone()

        if not existing:
            count = conn.execute("""
                SELECT COUNT(*) AS total FROM room_members
                WHERE room_code = ?
            """, (code,)).fetchone()["total"]

            if count >= 10:
                return False, "ظرفیت این اتاق تکمیل شده است."

            conn.execute("""
                INSERT INTO room_members (room_code, chat_id, joined_at)
                VALUES (?, ?, ?)
            """, (code, chat_id, datetime.now().isoformat()))

    return True, "با موفقیت وارد اتاق شدی!"


def start_room_game(chat_id, code):
    with db() as conn:
        room = conn.execute(
            "SELECT * FROM rooms WHERE code = ?",
مهراب: (code,),
        ).fetchone()

        if not room:
            return "اتاق پیدا نشد."

        if room["host_id"] != chat_id:
            return "فقط سازنده اتاق می‌تواند بازی را شروع کند."

        members = conn.execute("""
            SELECT m.chat_id, u.nickname
            FROM room_members m
            JOIN users u ON u.chat_id = m.chat_id
            WHERE m.room_code = ?
        """, (code,)).fetchall()

        if len(members) < 2:
            return "برای شروع بازی حداقل دو بازیکن لازم است."

        player = random.choice(members)
        kind = random.choice(["truth", "dare"])
        question = random.choice(TRUTHS if kind == "truth" else DARES)

        conn.execute("""
            INSERT INTO room_games
                (room_code, current_player, current_kind, current_question)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(room_code) DO UPDATE SET
                current_player = excluded.current_player,
                current_kind = excluded.current_kind,
                current_question = excluded.current_question
        """, (code, player["chat_id"], kind, question))

        conn.execute(
            "UPDATE rooms SET status = 'playing' WHERE code = ?",
            (code,),
        )

    title = "❓ حقیقت" if kind == "truth" else "🔥 جرئت"

    for member in members:
        if member["chat_id"] == player["chat_id"]:
            send_message(
                member["chat_id"],
                f"🎯 نوبت توست، {player['nickname']}!\n\n"
                f"{title}\n{question}\n\n"
                "بعد از انجام، دکمه «انجام دادم» را بزن.",
                submenu([[{"text": "✅ انجام دادم"}]]),
            )
        else:
            send_message(
                member["chat_id"],
                f"🎮 بازی اتاق {code} شروع شد!\n"
                f"نوبت {player['nickname']} است.\n"
                f"{title}",
            )

    return None


def finish_room_turn(chat_id):
    with db() as conn:
        game = conn.execute("""
            SELECT g.*, r.status
            FROM room_games g
            JOIN rooms r ON r.code = g.room_code
            WHERE g.current_player = ? AND r.status = 'playing'
            LIMIT 1
        """, (chat_id,)).fetchone()

        if not game:
            return False

        code = game["room_code"]
        kind = game["current_kind"]

        conn.execute("""
            UPDATE rooms SET status = 'open'
            WHERE code = ?
        """, (code,))

        conn.execute(
            "DELETE FROM room_games WHERE room_code = ?",
            (code,),
        )

    add_game_stat(chat_id, kind)
    award_coins(chat_id, ROOM_REWARD)

    members = room_members(code)

    for member in members:
        send_message(
            member["chat_id"],
            f"✅ نوبت تمام شد!\n🎁 بازیکن این نوبت ۱۰ سکه گرفت.\n"
            "سازنده اتاق می‌تواند دور بعد را شروع کند.",
            submenu([[{"text": f"▶️ شروع دور {code}"}]]),
        )

    return True


# ==================================================
# چالش روزانه
# ==================================================

def claim_daily(chat_id):
    today = today_iran()

    with db() as conn:
        already = conn.execute("""
            SELECT 1 FROM daily_claims
            WHERE chat_id = ? AND claim_date = ?
        """, (chat_id, today)).fetchone()

        if already:
            return False

        conn.execute("""
            INSERT INTO daily_claims (chat_id, claim_date)
            VALUES (?, ?)
        """, (chat_id, today))

        conn.execute("""
            UPDATE users
            SET coins = coins + ?,
                daily_streak = CASE
                    WHEN daily_date = date(?, '-1 day')
                    THEN daily_streak + 1
                    ELSE 1
                END,
                daily_date = ?
            WHERE chat_id = ?
        """, (DAILY_REWARD, today, today, chat_id))

    return True


# ==================================================
# فروشگاه
# ==================================================

def shop_text(chat_id):
    user = get_user(chat_id)
مهراب: if not user:
        return

    items = []
    with db() as conn:
        purchased = conn.execute(
            "SELECT item_key FROM purchases WHERE chat_id = ?",
            (chat_id,),
        ).fetchall()

    owned = {row["item_key"] for row in purchased}

    for key, item in SHOP.items():
        status = "✅ خریداری شده" if key in owned else f"{item['price']} سکه"
        items.append(f"• {item['name']} — {status}")

    kb = [
        [{"text": "👑 خرید تاج طلایی"}],
        [{"text": "🎨 خرید نام ویژه"}],
        [{"text": "🛡️ خرید سپر امتیاز"}],
        [{"text": "🏠 منوی اصلی"}],
    ]

    send_message(
        chat_id,
        "💰 فروشگاه جرئت و حقیقت\n\n"
        + "\n".join(items)
        + f"\n\nموجودی شما: {user['coins']} سکه",
        {"keyboard": kb, "resize_keyboard": True},
    )


def buy_item(chat_id, key):
    item = SHOP[key]

    with db() as conn:
        user = conn.execute(
            "SELECT coins FROM users WHERE chat_id = ?",
            (chat_id,),
        ).fetchone()

        if not user:
            return "ابتدا ثبت‌نام کن."

        already = conn.execute("""
            SELECT 1 FROM purchases
            WHERE chat_id = ? AND item_key = ?
        """, (chat_id, key)).fetchone()

        if already:
            return "این آیتم را قبلاً خریده‌ای."

        if user["coins"] < item["price"]:
            return "سکه کافی نداری."

        conn.execute(
            "UPDATE users SET coins = coins - ? WHERE chat_id = ?",
            (item["price"], chat_id),
        )

        conn.execute("""
            INSERT INTO purchases (chat_id, item_key, purchased_at)
            VALUES (?, ?, ?)
        """, (chat_id, key, datetime.now().isoformat()))

    return f"🎉 {item['name']} با موفقیت خریداری شد!"


# ==================================================
# وبهوک
# ==================================================

@app.route("/", methods=["GET"])
def index():
    return "Jorat-o-Haghighat Bot is running.", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "bot_configured": bool(BOT_TOKEN),
        "database": "sqlite",
    })


@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        supplied = request.headers.get("X-Webhook-Secret", "")
        if not secrets.compare_digest(supplied, WEBHOOK_SECRET):
            return jsonify({"status": "forbidden"}), 403

    try:
        data = request.get_json(silent=True) or {}
        msg = data.get("message")

        if not msg or not msg.get("chat"):
            return jsonify({"status": "ok"})

        chat_id = msg["chat"]["id"]
        text = (msg.get("text") or "").strip()

        # ثبت نام و تغییر نام
        if chat_id in pending_name:
            if not valid_nickname(text):
                send_message(
                    chat_id,
                    "❌ نام باید بین ۲ تا ۲۰ نویسه باشد. دوباره تلاش کن.",
                )
                return jsonify({"status": "ok"})

            try:
                user = get_user(chat_id)

                if user:
                    with db() as conn:
                        duplicate = conn.execute("""
                            SELECT chat_id FROM users
                            WHERE nickname = ? COLLATE NOCASE
                              AND chat_id != ?
                        """, (text, chat_id)).fetchone()

                        if duplicate:
                            send_message(
                                chat_id,
                                "❌ این نام قبلاً انتخاب شده؛ نام دیگری بفرست.",
                            )
                            return jsonify({"status": "ok"})

                        conn.execute(
                            "UPDATE users SET nickname = ? WHERE chat_id = ?",
                            (text, chat_id),
                        )
                else:
                    create_user(chat_id, text)
                    award_coins(chat_id, NAME_REWARD)

                    inviter_id = pending_referral.pop(chat_id, None)
                    i
مهراب: f inviter_id:
                        process_referral(chat_id, inviter_id)

                pending_name.discard(chat_id)
                send_message(
                    chat_id,
                    f"✅ نام مستعار «{text}» ثبت شد!\n"
                    + (f"🎁 {NAME_REWARD} سکه هدیه گرفتی!" if not user else ""),
                    main_menu(),
                )

            except sqlite3.IntegrityError:
                send_message(chat_id, "این نام قبلاً ثبت شده؛ نام دیگری انتخاب کن.")

            return jsonify({"status": "ok"})

        # ثبت نام اولیه و لینک دعوت
        if not get_user(chat_id):
            inviter_id = None

            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                if len(parts) == 2 and parts[1].isdigit():
                    inviter_id = int(parts[1])

            if inviter_id and inviter_id != chat_id:
                pending_referral[chat_id] = inviter_id

            pending_name.add(chat_id)
            send_message(
                chat_id,
                "👋 به بازی جرئت و حقیقت خوش آمدی!\n"
                "برای شروع، یک نام مستعار منحصربه‌فرد بفرست "
                "(۲ تا ۲۰ نویسه).",
            )
            return jsonify({"status": "ok"})

        # رسیدگی به نوبت فعال
        if text == "✅ انجام دادم":
            if not finish_room_turn(chat_id):
                send_message(chat_id, "❌ اکنون نوبت فعالی برای تو وجود ندارد.")
            return jsonify({"status": "ok"})

        # ورود به اتاق با کد
        if chat_id in pending_room_code:
            pending_room_code.discard(chat_id)

            if not text.isdigit() or len(text) != 4:
                send_message(chat_id, "❌ کد اتاق باید چهار رقم باشد.", main_menu())
                return jsonify({"status": "ok"})

            ok, result = join_room(chat_id, text)
            send_message(chat_id, ("✅ " if ok else "❌ ") + result, main_menu())

            if ok:
                with db() as conn:
                    host = conn.execute(
                        "SELECT host_id FROM rooms WHERE code = ?",
                        (text,),
                    ).fetchone()

                if host:
                    user = get_user(chat_id)
                    send_message(
                        host["host_id"],
                        f"👤 {user['nickname']} وارد اتاق {text} شد.",
                    )

            return jsonify({"status": "ok"})

        # منوی اصلی
        if text in ("/start", "🏠 منوی اصلی"):
            user = get_user(chat_id)
            send_message(
                chat_id,
                f"سلام {user['nickname']}! 🎮\n"
                "آماده‌ای بازی کنیم؟",
                main_menu(),
            )

        elif text == "🎮 بازی چندنفره":
            send_message(
                chat_id,
                "🎮 بخش چندنفره را انتخاب کن:",
                submenu([
                    [{"text": "➕ ساخت اتاق"}, {"text": "🚪 پیوستن به اتاق"}],
                    [{"text": "📋 اتاق‌های من"}],
                ]),
            )

        elif text == "➕ ساخت اتاق":
            code = create_room(chat_id)
            send_message(
                chat_id,
                f"🏠 اتاق ساخته شد!\nکد اتاق: {code}\n"
                "دوستت باید با گزینه «پیوستن به اتاق» وارد شود.",
                submenu([
                    [{"text": f"▶️ شروع دور {code}"}],
                    [{"text": f"🗑️ حذف اتاق {code}"}],
                    [{"text": "🚪 پیوستن به اتاق"}],
                ]),
            )

        elif text == "🚪 پیوستن به اتاق":
            pending_room_code.add(chat_id)
            send_message(chat_id, "کد چهاررقمی اتاق را بفرست:")

        elif text == "📋 اتاق‌های من":
            with db() as conn:
                rows = conn.execute("""
                    SELECT r.code, r.host_id, r.status
                    FROM rooms r
                    JOIN room_members m ON m.room_code = r.code
                    WHERE m.chat_id = ?
                """, (chat_id,)).fetchall()

            if not rows:
                send_message(chat_id, "هنوز ع
مهراب: ضو هیچ اتاقی نیستی.", main_menu())
            else:
                lines = [
                    f"اتاق {r['code']} — "
                    f"{'سازنده' if r['host_id'] == chat_id else 'عضو'} — {r['status']}"
                    for r in rows
                ]
                send_message(chat_id, "\n".join(lines), main_menu())

        elif text.startswith("▶️ شروع دور "):
            code = text.split()[-1]
            error = start_room_game(chat_id, code)
            if error:
                send_message(chat_id, "❌ " + error)

        elif text.startswith("🗑️ حذف اتاق "):
            code = text.split()[-1]

            with db() as conn:
                room = conn.execute(
                    "SELECT host_id FROM rooms WHERE code = ?",
                    (code,),
                ).fetchone()

                if room and room["host_id"] == chat_id:
                    conn.execute("DELETE FROM room_games WHERE room_code = ?", (code,))
                    conn.execute("DELETE FROM room_members WHERE room_code = ?", (code,))
                    conn.execute("DELETE FROM rooms WHERE code = ?", (code,))
                    send_message(chat_id, "🗑️ اتاق حذف شد.", main_menu())
                else:
                    send_message(chat_id, "❌ فقط سازنده می‌تواند اتاق را حذف کند.")

        elif text == "🤖 بازی تک‌نفره":
            send_message(
                chat_id,
                "یک گزینه را انتخاب کن:",
                submenu([
                    [{"text": "❓ حقیقت"}, {"text": "🔥 جرئت"}],
                    [{"text": "🎡 چرخ شانس"}],
                ]),
            )

        elif text == "❓ حقیقت":
            play_single(chat_id, "truth")

        elif text == "🔥 جرئت":
            play_single(chat_id, "dare")

        elif text == "🎡 چرخ شانس":
            play_single(chat_id, random.choice(["truth", "dare"]))

        elif text == "🏆 جدول رده‌بندی":
            with db() as conn:
                rows = conn.execute("""
                    SELECT nickname, coins FROM users
                    ORDER BY coins DESC, nickname ASC LIMIT 10
                """).fetchall()

            lines = ["🏆 جدول ۱۰ نفر برتر", ""]
            for i, row in enumerate(rows, 1):
                lines.append(f"{i}. {row['nickname']} — {row['coins']} سکه")

            send_message(chat_id, "\n".join(lines), main_menu())

        elif text == "💰 سکه و فروشگاه":
            shop_text(chat_id)

        elif text.startswith("👑 خرید تاج"):
            send_message(chat_id, buy_item(chat_id, "crown"), main_menu())

        elif text.startswith("🎨 خرید نام"):
            send_message(chat_id, buy_item(chat_id, "color"), main_menu())

        elif text.startswith("🛡️ خرید سپر"):
            send_message(chat_id, buy_item(chat_id, "shield"), main_menu())

        elif text == "🎁 چالش روزانه":
            if claim_daily(chat_id):
                send_message(
                    chat_id,
                    f"🎉 چالش روزانه انجام شد!\n"
                    f"🎁 {DAILY_REWARD} سکه دریافت کردی.\n"
                    "فردا برای جایزه جدید برگرد!",
                    main_menu(),
                )
            else:
                send_message(
                    chat_id,
                    "⏳ جایزه امروز را قبلاً گرفته‌ای. فردا دوباره بیا!",
                    main_menu(),
                )

        elif text == "🕵️‍♂️ مأمور مخفی":
            send_message(
                chat_id,
                "🕵️‍♂️ مأمور مخفی\n\n"
                "این بخش در نسخه فعلی هنوز فعال نشده است.",
                main_menu(),
            )

        elif text == "👥 دعوت دوستان":
            send_message(
                chat_id,
                f"👥 لینک دعوت اختصاصی:\n"
                f"https://ble.ir/jorat_bot?start={chat_id}\n\n"
                "با ثبت‌نام دوستت از طریق این لینک، ۵۰ سکه می‌گیری.",
                main_menu(),
            )

        elif text == "✏️ تغییر نام":
            pending_name.add(chat_id)
            send_message(chat_id, "نام مستعار جدید را بفرست (۲ تا ۲۰ نویسه):")

        elif text == "📊 آمار من":
مهراب: user = get_user(chat_id)

            with db() as conn:
                stats = conn.execute(
                    "SELECT * FROM game_stats WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()

                referral_count = conn.execute(
                    "SELECT COUNT(*) AS n FROM referrals WHERE inviter_id = ?",
                    (chat_id,),
                ).fetchone()["n"]

                purchases = conn.execute(
                    "SELECT COUNT(*) AS n FROM purchases WHERE chat_id = ?",
                    (chat_id,),
                ).fetchone()["n"]

            send_message(
                chat_id,
                f"📊 آمار {user['nickname']}\n\n"
                f"💰 سکه: {user['coins']}\n"
                f"🎮 بازی‌ها: {stats['games_played']}\n"
                f"❓ حقیقت‌ها: {stats['truth_count']}\n"
                f"🔥 جرئت‌ها: {stats['dare_count']}\n"
                f"👥 دعوت موفق: {referral_count}\n"
                f"🛍️ خریدها: {purchases}\n"
                f"🔥 روزهای متوالی چالش: {user['daily_streak']}",
                main_menu(),
            )

        elif text == "❓ راهنما":
            send_message(
                chat_id,
                "📖 راهنمای بازی\n\n"
                "• از بازی تک‌نفره برای حقیقت و جرئت استفاده کن.\n"
                "• برای بازی با دوستت اتاق بساز و کد را بفرست.\n"
                "• هر روز جایزه روزانه را دریافت کن.\n"
                "• با بازی‌کردن سکه جمع کن و از فروشگاه خرید کن.\n"
                "• برای دریافت سکه دعوت، دوستت باید از لینک دعوت ثبت‌نام کند.",
                main_menu(),
            )

        else:
            send_message(
                chat_id,
                "از دکمه‌های منو استفاده کن.",
                main_menu(),
            )

        return jsonify({"status": "ok"})

    except Exception:
        logging.exception("خطا در webhook")
        # پاسخ OK از تکرار مداوم یک آپدیت معیوب جلوگیری می‌کند.
        return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
