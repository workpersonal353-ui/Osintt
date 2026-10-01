import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import sqlite3
import re
import time
import json
import os
import sys
import gc
import threading
from datetime import datetime
from flask import Flask, request as _req, jsonify as _json

# ==================== FLASK WEB SERVER ====================
app = Flask(__name__)

@app.route('/', methods=['GET', 'POST'])
def home():
    return "Number OSINT Bot Server is Running ✅", 200

# ==================== BOT CONFIG & SPEED CONSTANTS ====================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8956607651:AAHtm8bQk9CR3elRPtj8VUgM0pYzPV0vTOM")
OWNER_ID = int(os.environ.get("OWNER_ID", "8682912888"))

CHANNEL_LINK = "https://t.me/+V77fVTmscHQ1YzA1"
FORCE_JOIN_CHANNEL = os.environ.get("FORCE_JOIN_CHANNEL", "-1003930518361") 

DEFAULT_API_URL = "https://free.proapis.bond/num?number="
CURRENT_API_URL = DEFAULT_API_URL

BOT_CREDIT = "⚡ ʙᴏᴛ ᴍᴀᴅᴇ ʙʏ : @Lailamajnuuu\n💳 ᴀᴩɪ ʙᴜʏ ᴋᴀʀɴᴇ ᴋᴇ ʟɪʏᴇ ᴅᴍ ᴋᴀʀᴏ : @Lailamajnuuu"

# Speed & Optimization Settings
API_TIMEOUT = 6
MAX_POOL_CONNECTIONS = 50
MAX_THREAD_WORKERS = 20
maintenance_mode = False

verified_users = set()
user_states = {}

# High-Performance HTTP Session setup
http_session = requests.Session()
retries = Retry(total=2, backoff_factor=0.2, status_forcelist=[500, 502, 503, 504])
adapter = HTTPAdapter(pool_connections=MAX_POOL_CONNECTIONS, pool_maxsize=MAX_POOL_CONNECTIONS, max_retries=retries)
http_session.mount('https://', adapter)
http_session.mount('http://', adapter)

def format_message(text):
    return f"<blockquote>{text}\n\n{BOT_CREDIT}</blockquote>"

# ==================== THREAD-SAFE DATABASE MANAGEMENT ====================
def get_db_connection():
    conn = sqlite3.connect('bot_data.db', timeout=30)
    conn.execute('PRAGMA journal_mode=WAL;')
    conn.execute('PRAGMA synchronous=NORMAL;')
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            searches_left INTEGER DEFAULT 3,
            last_claimed_date TEXT,
            referred_by INTEGER,
            is_banned INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute("PRAGMA table_info(users)")
    columns = [column[1] for column in cursor.fetchall()]
    if 'is_banned' not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_banned INTEGER DEFAULT 0")
        
    conn.commit()
    conn.close()

init_db()

def get_user_data(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute("SELECT searches_left, last_claimed_date, is_banned FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    if not row:
        cursor.execute("INSERT OR IGNORE INTO users (user_id, searches_left, last_claimed_date, is_banned) VALUES (?, ?, ?, 0)", (user_id, 3, today))
        conn.commit()
        searches_left, is_banned = 3, 0
    else:
        searches_left, last_claimed_date, is_banned = row
        if is_banned is None:
            is_banned = 0
        if last_claimed_date != today:
            searches_left = max(searches_left, 3)
            cursor.execute("UPDATE users SET searches_left = ?, last_claimed_date = ? WHERE user_id = ?", (searches_left, today, user_id))
            conn.commit()
            
    conn.close()
    return searches_left, is_banned

def update_searches(user_id, amount):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET searches_left = searches_left + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def deduct_search(user_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET searches_left = searches_left - 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_ban_status(user_id, status):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (status, user_id))
    conn.commit()
    conn.close()

def set_referrer(user_id, referrer_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT referred_by FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] is None and user_id != referrer_id:
        cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
        cursor.execute("UPDATE users SET searches_left = searches_left + 3 WHERE user_id = ?", (referrer_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False

def get_all_users():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]

# ==================== BOT API STYLED BUTTONS ====================
class _StyledKB(KeyboardButton):
    def __init__(self, text, style=None, **kwargs):
        super().__init__(text, **kwargs)
        self.__style = style

    def to_dict(self):
        d = super().to_dict()
        if self.__style:
            d['style'] = self.__style
        return d

def _KB(text, style=None, **kwargs):
    try:
        return _StyledKB(text, style=style, **kwargs)
    except Exception:
        return KeyboardButton(text)

# ==================== API LOOKUP FUNCTION ====================
def get_number_info(number):
    global CURRENT_API_URL, API_TIMEOUT
    try:
        clean_number = re.sub(r'[^\d]', '', str(number))
        url = f"{CURRENT_API_URL}{clean_number}"
        response = http_session.get(url, timeout=API_TIMEOUT)
        if response.status_code != 200:
            return {'success': False, 'msg': f'HTTP Error {response.status_code}'}
        data = response.json()
        return {'success': True, 'data': data}
    except requests.exceptions.Timeout:
        return {'success': False, 'msg': f'API Request Timed Out ({API_TIMEOUT}s)! Server slow hai.'}
    except Exception as e:
        return {'success': False, 'msg': str(e)}

# ==================== KEYBOARDS ====================
def main_keyboard(user_id):
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        _KB("📱 NUMBER INFO", style="primary"),
        _KB("💰 BALANCE & LIMIT", style="primary"),
        _KB("👥 REFER & EARN", style="success"),
        _KB("💳 BUY API / VIP", style="success"),
        _KB("ℹ️ HELP", style="primary")
    ]
    markup.add(buttons[0])
    markup.add(buttons[1], buttons[2])
    markup.add(buttons[3], buttons[4])
    if user_id == OWNER_ID:
        markup.add(_KB("⚙️ ADMIN PANEL", style="danger"))
    return markup

def admin_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(_KB("⚡ SPEED BOOST", style="success"), _KB("🧹 CLEAR CACHE", style="primary"))
    markup.add(_KB("📊 BOT STATS", style="primary"), _KB("🔌 CHECK API", style="success"))
    markup.add(_KB("🔄 RESTART BOT", style="danger"), _KB("⚙️ CHANGE API", style="primary"))
    markup.add(_KB("➕ ADD SEARCHES", style="success"), _KB("➖ REMOVE SEARCHES", style="danger"))
    markup.add(_KB("👤 USER INFO", style="primary"), _KB("📢 BROADCAST", style="primary"))
    markup.add(_KB("🚫 BAN USER", style="danger"), _KB("✅ UNBAN USER", style="success"))
    markup.add(_KB("🛠️ MAINTENANCE MODE", style="danger"), _KB("🏠 MAIN MENU", style="primary"))
    return markup

def cancel_keyboard():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(_KB("❌ CANCEL", style="danger"))
    return markup

def join_channel_keyboard():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📢 Join Official Channel", url=CHANNEL_LINK))
    markup.add(InlineKeyboardButton("✅ Joined / Verify", callback_data="check_join"))
    return markup

# ==================== CHANNEL JOIN CHECKER ====================
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=MAX_THREAD_WORKERS)

@bot.chat_join_request_handler()
def handle_join_request(request):
    try:
        verified_users.add(request.from_user.id)
    except Exception as e:
        print(f"[Join Request Catch Error]: {e}")

def is_user_joined(user_id):
    if user_id == OWNER_ID or user_id in verified_users:
        return True
    try:
        member = bot.get_chat_member(FORCE_JOIN_CHANNEL, user_id)
        if member.status in ['creator', 'administrator', 'member', 'restricted']:
            verified_users.add(user_id)
            return True
    except Exception:
        pass
    return False

def global_checks(message):
    uid = message.from_user.id
    searches, is_banned = get_user_data(uid)
    
    if is_banned and uid != OWNER_ID:
        bot.send_message(message.chat.id, format_message("❌ <b>Access Denied:</b> Aap banned hain!"), parse_mode='HTML')
        return True

    if maintenance_mode and uid != OWNER_ID:
        bot.send_message(message.chat.id, format_message("🛠️ <b>MAINTENANCE MODE ACTIVE</b>\n\nBot maintenance mode par hai!"), parse_mode='HTML')
        return True

    if not is_user_joined(uid):
        txt = (
            "<b>⚠️ ACCESS DENIED ⚠️</b>\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "Bot chalane ke liye pehle official channel join karein.\n\n"
            f"👉 Channel Link: {CHANNEL_LINK}\n\n"
            "Join karne ya Request bhejane ke baad <b>✅ Joined / Verify</b> button dabaen."
        )
        bot.send_message(message.chat.id, format_message(txt), reply_markup=join_channel_keyboard(), parse_mode='HTML')
        return True

    return False

# ==================== BOT START & VERIFY ====================

@bot.message_handler(commands=['start'])
def start_cmd(message):
    uid = message.from_user.id
    user_states.pop(uid, None)

    args = message.text.split()
    if len(args) > 1 and args[1].isdigit():
        referrer_id = int(args[1])
        if set_referrer(uid, referrer_id):
            try:
                bot.send_message(referrer_id, format_message("🎉 <b>Naya Referral Joined!</b> Aapko +3 Searches mil gaye hain!"), parse_mode='HTML')
            except Exception:
                pass

    if global_checks(message):
        return

    send_animated_welcome(message.chat.id, message.from_user)

@bot.callback_query_handler(func=lambda call: call.data == "check_join")
def check_join_callback(call):
    uid = call.from_user.id
    verified_users.add(uid)
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception:
        pass
    send_animated_welcome(call.message.chat.id, call.from_user)

def send_animated_welcome(chat_id, user):
    uid = user.id
    searches, _ = get_user_data(uid)
    
    welcome_txt = (
        f"<b>✨ WELCOME TO NUMBER OSINT BOT ✨</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>User:</b> {user.first_name}\n"
        f"🆔 <b>User ID:</b> <code>{uid}</code>\n"
        f"🔍 <b>Daily Searches Left:</b> <code>{searches}</code>\n\n"
        f"🎯 <b>Features:</b>\n"
        f"• Daily 3 Free Searches\n"
        f"• Direct Number OSINT Lookup\n"
        f"• Refer & Earn +3 Searches\n\n"
        f"<i>Select an option from the menu:</i>"
    )
    bot.send_message(chat_id, format_message(welcome_txt), reply_markup=main_keyboard(uid), parse_mode='HTML')

# ==================== CANCEL & MAIN MENU ROUTING ====================

@bot.message_handler(func=lambda msg: msg.text in ["❌ CANCEL", "🏠 MAIN MENU"])
def cancel_or_main(message):
    uid = message.from_user.id
    user_states.pop(uid, None)
    bot.send_message(message.chat.id, format_message("🏠 Main Menu:"), reply_markup=main_keyboard(uid), parse_mode='HTML')

# ==================== ADMIN SPEED & OPTIMIZATION COMMANDS ====================

@bot.message_handler(commands=['admin'])
@bot.message_handler(func=lambda msg: msg.text == "⚙️ ADMIN PANEL")
def admin_panel(message):
    if message.from_user.id != OWNER_ID:
        return
    user_states.pop(message.from_user.id, None)
    txt = "<b>⚙️ ADMIN CONTROL PANEL</b>\n\nWelcome Master! Niche diye gaye buttons se bot control karein:"
    bot.send_message(message.chat.id, format_message(txt), reply_markup=admin_keyboard(), parse_mode='HTML')

@bot.message_handler(commands=['ping'])
def ping_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    start = time.time()
    msg = bot.send_message(message.chat.id, "🏓 <i>Pinging Telegram API...</i>", parse_mode='HTML')
    latency = round((time.time() - start) * 1000, 2)
    bot.edit_message_text(format_message(f"🏓 <b>PONG!</b>\n⚡ Latency: <code>{latency} ms</code>"), message.chat.id, msg.message_id, parse_mode='HTML')

@bot.message_handler(commands=['clearcache'])
@bot.message_handler(func=lambda msg: msg.text == "🧹 CLEAR CACHE" and msg.from_user.id == OWNER_ID)
def clear_cache_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    global verified_users, user_states
    verified_users.clear()
    user_states.clear()
    gc.collect()
    bot.send_message(message.chat.id, format_message("🧹 <b>RAM & Memory Cache Flushed!</b>\nSpeed successfully optimized! 🚀"), reply_markup=admin_keyboard(), parse_mode='HTML')

@bot.message_handler(commands=['boost'])
@bot.message_handler(func=lambda msg: msg.text == "⚡ SPEED BOOST" and msg.from_user.id == OWNER_ID)
def boost_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    gc.collect()
    conn = get_db_connection()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    conn.close()
    bot.send_message(message.chat.id, format_message("🚀 <b>SPEED BOOST ACTIVATED!</b>\n\n• Thread Pool Maxed\n• Database WAL Flushed\n• Garbage Cleaned!"), reply_markup=admin_keyboard(), parse_mode='HTML')

@bot.message_handler(commands=['setspeed'])
def set_speed_cmd(message):
    global API_TIMEOUT
    if message.from_user.id != OWNER_ID:
        return
    try:
        sec = int(message.text.split()[1])
        API_TIMEOUT = sec
        bot.send_message(message.chat.id, format_message(f"⚡ API Timeout limit set to: <code>{sec} sec</code>"))
    except Exception:
        bot.send_message(message.chat.id, format_message("❌ Usage: <code>/setspeed <seconds></code>"))

@bot.message_handler(commands=['setworkers'])
def set_workers_cmd(message):
    global MAX_THREAD_WORKERS
    if message.from_user.id != OWNER_ID:
        return
    try:
        workers = int(message.text.split()[1])
        MAX_THREAD_WORKERS = workers
        bot.send_message(message.chat.id, format_message(f"⚙️ Max Workers set to: <code>{workers} Threads</code>"))
    except Exception:
        bot.send_message(message.chat.id, format_message("❌ Usage: <code>/setworkers <count></code>"))

@bot.message_handler(commands=['systeminfo'])
def system_info_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    threads = threading.active_count()
    txt = (
        f"<b>💻 SYSTEM DIAGNOSTICS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🧵 <b>Active Threads:</b> <code>{threads}</code>\n"
        f"⏱️ <b>Timeout Setting:</b> <code>{API_TIMEOUT}s</code>\n"
        f"⚡ <b>Max Connections Pool:</b> <code>{MAX_POOL_CONNECTIONS}</code>"
    )
    bot.send_message(message.chat.id, format_message(txt), parse_mode='HTML')

@bot.message_handler(commands=['optimize'])
def optimize_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    gc.collect()
    conn = get_db_connection()
    conn.execute("VACUUM;")
    conn.close()
    bot.send_message(message.chat.id, format_message("✨ <b>SQLite Database Vacuumed & RAM Garbage Cleaned!</b>"), parse_mode='HTML')

@bot.message_handler(commands=['restart'])
@bot.message_handler(func=lambda msg: msg.text == "🔄 RESTART BOT" and msg.from_user.id == OWNER_ID)
def restart_bot_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    bot.send_message(message.chat.id, format_message("🔄 <b>Restarting Bot...</b>"), parse_mode='HTML')
    os.execv(sys.executable, ['python'] + sys.argv)

@bot.message_handler(commands=['checkapi'])
@bot.message_handler(func=lambda msg: msg.text == "🔌 CHECK API" and msg.from_user.id == OWNER_ID)
def check_api_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    msg_wait = bot.send_message(message.chat.id, "🔌 <i>Testing Active API Endpoint...</i>", parse_mode='HTML')
    start_time = time.time()
    res = get_number_info("9876543210")
    latency = round((time.time() - start_time) * 1000, 2)
    status = "🟢 ONLINE & WORKING (200 OK)" if res.get('success') else f"🔴 ERROR ({res.get('msg')})"
    txt = (
        f"<b>🔌 API STATUS CHECK</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📡 <b>Active API:</b> <code>{CURRENT_API_URL}</code>\n"
        f"⚡ <b>Latency:</b> <code>{latency} ms</code>\n"
        f"📊 <b>Status:</b> {status}"
    )
    bot.edit_message_text(format_message(txt), message.chat.id, msg_wait.message_id, parse_mode='HTML')

@bot.message_handler(commands=['getapi'])
def get_api_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    bot.send_message(message.chat.id, format_message(f"📡 <b>Current API Endpoint:</b>\n<code>{CURRENT_API_URL}</code>"), parse_mode='HTML')

@bot.message_handler(commands=['setapi'])
@bot.message_handler(func=lambda msg: msg.text == "⚙️ CHANGE API" and msg.from_user.id == OWNER_ID)
def set_api_prompt(message):
    if message.from_user.id != OWNER_ID:
        return
    user_states[message.from_user.id] = 'WAITING_SET_API'
    txt = "⚙️ <b>Nayi Lookup API URL enter karein:</b>\n\nExample:\n<code>https://free.proapis.bond/num?number=</code>"
    bot.send_message(message.chat.id, format_message(txt), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(commands=['resetapi'])
def reset_api_cmd(message):
    global CURRENT_API_URL
    if message.from_user.id != OWNER_ID:
        return
    CURRENT_API_URL = DEFAULT_API_URL
    bot.send_message(message.chat.id, format_message(f"✅ API URL Default par Reset ho gayi hai:\n<code>{CURRENT_API_URL}</code>"), parse_mode='HTML')

@bot.message_handler(commands=['testapi'])
def test_api_cmd(message):
    if message.from_user.id != OWNER_ID:
        return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, format_message("❌ Usage: <code>/testapi <number></code>"), parse_mode='HTML')
        return
    num = parts[1]
    res = get_number_info(num)
    if res.get('success') and isinstance(res.get('data'), dict):
        res['data'].pop('API_Developer', None)
    bot.send_message(message.chat.id, format_message(f"🧪 <b>TEST RESULT:</b>\n\n<code>{json.dumps(res, indent=2)}</code>"), parse_mode='HTML')

@bot.message_handler(commands=['stats'])
@bot.message_handler(func=lambda msg: msg.text == "📊 BOT STATS")
def admin_stats(message):
    if message.from_user.id != OWNER_ID:
        return
    total_users = len(get_all_users())
    txt = f"<b>📊 BOT STATISTICS</b>\n━━━━━━━━━━━━━━━━━━\n👥 Total Users: <code>{total_users}</code>"
    bot.send_message(message.chat.id, format_message(txt), reply_markup=admin_keyboard(), parse_mode='HTML')

@bot.message_handler(commands=['maintenance'])
@bot.message_handler(func=lambda msg: msg.text == "🛠️ MAINTENANCE MODE")
def maintenance_cmd(message):
    global maintenance_mode
    if message.from_user.id != OWNER_ID:
        return
    maintenance_mode = not maintenance_mode
    status = "ENABLED 🟢" if maintenance_mode else "DISABLED 🔴"
    bot.send_message(message.chat.id, format_message(f"⚙️ <b>Maintenance Mode:</b> {status}"), reply_markup=admin_keyboard(), parse_mode='HTML')

# --- Interactive Admin Prompts ---

@bot.message_handler(func=lambda msg: msg.text == "➕ ADD SEARCHES" and msg.from_user.id == OWNER_ID)
def prompt_add_credits(message):
    user_states[message.from_user.id] = 'WAITING_ADD_CREDITS'
    bot.send_message(message.chat.id, format_message("➕ User ID aur amount enter karein:\nSyntax: <code>USER_ID AMOUNT</code>"), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "➖ REMOVE SEARCHES" and msg.from_user.id == OWNER_ID)
def prompt_rem_credits(message):
    user_states[message.from_user.id] = 'WAITING_REM_CREDITS'
    bot.send_message(message.chat.id, format_message("➖ User ID aur amount enter karein:\nSyntax: <code>USER_ID AMOUNT</code>"), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "👤 USER INFO" and msg.from_user.id == OWNER_ID)
def prompt_user_info(message):
    user_states[message.from_user.id] = 'WAITING_USER_INFO'
    bot.send_message(message.chat.id, format_message("👤 User ID enter karein:"), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "🚫 BAN USER" and msg.from_user.id == OWNER_ID)
def prompt_ban(message):
    user_states[message.from_user.id] = 'WAITING_BAN'
    bot.send_message(message.chat.id, format_message("🚫 Ban karne ke liye User ID enter karein:"), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "✅ UNBAN USER" and msg.from_user.id == OWNER_ID)
def prompt_unban(message):
    user_states[message.from_user.id] = 'WAITING_UNBAN'
    bot.send_message(message.chat.id, format_message("✅ Unban karne ke liye User ID enter karein:"), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "📢 BROADCAST" and msg.from_user.id == OWNER_ID)
def prompt_broadcast(message):
    user_states[message.from_user.id] = 'WAITING_BROADCAST'
    bot.send_message(message.chat.id, format_message("📢 Broadcast message enter karein:"), reply_markup=cancel_keyboard(), parse_mode='HTML')

# ==================== MAIN USER MENU HANDLERS ====================

@bot.message_handler(func=lambda msg: msg.text == "📱 NUMBER INFO")
def number_info_prompt(message):
    uid = message.from_user.id
    if global_checks(message):
        return

    searches, _ = get_user_data(uid)
    if searches <= 0:
        txt = (
            "❌ <b>Daily Limit Finished!</b>\n\n"
            "👥 Refer & Earn button se <b>+3 Searches</b> paayein."
        )
        bot.send_message(message.chat.id, format_message(txt), reply_markup=main_keyboard(uid), parse_mode='HTML')
        return

    user_states[uid] = 'WAITING_NUMBER'
    txt = f"<b>📱 NUMBER OSINT LOOKUP</b>\n\nAvailable Searches: <code>{searches}</code>\n\nKripya 10-digit mobile number enter karein:"
    bot.send_message(message.chat.id, format_message(txt), reply_markup=cancel_keyboard(), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "💰 BALANCE & LIMIT")
def check_balance(message):
    uid = message.from_user.id
    if global_checks(message):
        return

    searches, _ = get_user_data(uid)
    txt = (
        f"<b>📊 ACCOUNT STATS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👤 <b>ID:</b> <code>{uid}</code>\n"
        f"⚡ <b>Searches Today:</b> <code>{searches}</code>\n"
        f"🔄 Har raat 12 baje reset hota hai."
    )
    bot.send_message(message.chat.id, format_message(txt), reply_markup=main_keyboard(uid), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "👥 REFER & EARN")
def refer_and_earn(message):
    uid = message.from_user.id
    if global_checks(message):
        return

    bot_info = bot.get_me()
    refer_link = f"https://t.me/{bot_info.username}?start={uid}"
    txt = (
        f"<b>👥 REFER & EARN</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Refer karne par milenge <b>+3 Extra Searches</b>!\n\n"
        f"🔗 <b>Referral Link:</b>\n"
        f"<code>{refer_link}</code>"
    )
    bot.send_message(message.chat.id, format_message(txt), reply_markup=main_keyboard(uid), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "💳 BUY API / VIP")
def buy_api(message):
    txt = "💳 <b>VIP / API Buy karne ke liye DM karein:</b>\n📩 Owner: @Lailamajnuuu"
    bot.send_message(message.chat.id, format_message(txt), reply_markup=main_keyboard(message.from_user.id), parse_mode='HTML')

@bot.message_handler(func=lambda msg: msg.text == "ℹ️ HELP")
def help_cmd(message):
    txt = (
        "<b>ℹ️ HELP & GUIDE</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "1. Daily 3 Searches free.\n"
        "2. Refer par +3 Searches.\n"
        "3. Channel join mandatory.\n\n"
        "📩 Owner DM: @Lailamajnuuu"
    )
    bot.send_message(message.chat.id, format_message(txt), reply_markup=main_keyboard(message.from_user.id), parse_mode='HTML')

# ==================== PROCESS STATE INPUTS ====================

@bot.message_handler(func=lambda msg: msg.from_user.id in user_states)
def state_processor(message):
    uid = message.from_user.id
    state = user_states.get(uid)
    text = message.text.strip()

    if text == "❌ CANCEL":
        user_states.pop(uid, None)
        bot.send_message(message.chat.id, format_message("✅ Cancelled."), reply_markup=main_keyboard(uid), parse_mode='HTML')
        return

    # Admin Processing
    if uid == OWNER_ID:
        if state == 'WAITING_SET_API':
            global CURRENT_API_URL
            CURRENT_API_URL = text
            user_states.pop(uid, None)
            bot.send_message(message.chat.id, format_message(f"✅ Nayi API set ho gayi:\n<code>{CURRENT_API_URL}</code>"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_ADD_CREDITS':
            user_states.pop(uid, None)
            try:
                parts = text.split()
                target, amt = int(parts[0]), int(parts[1])
                update_searches(target, amt)
                bot.send_message(message.chat.id, format_message(f"✅ User <code>{target}</code> ko +{amt} searches add kar diye!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            except Exception:
                bot.send_message(message.chat.id, format_message("❌ Invalid Format! Use: <code>USER_ID AMOUNT</code>"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_REM_CREDITS':
            user_states.pop(uid, None)
            try:
                parts = text.split()
                target, amt = int(parts[0]), int(parts[1])
                update_searches(target, -amt)
                bot.send_message(message.chat.id, format_message(f"✅ User <code>{target}</code> se -{amt} searches deduct kar diye!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            except Exception:
                bot.send_message(message.chat.id, format_message("❌ Invalid Format! Use: <code>USER_ID AMOUNT</code>"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_USER_INFO':
            user_states.pop(uid, None)
            if text.isdigit():
                target = int(text)
                searches, is_banned = get_user_data(target)
                txt = f"<b>👤 USER INFO</b>\n━━━━━━━━━━━━━━━━━━\n🆔 ID: <code>{target}</code>\n⚡ Searches: <code>{searches}</code>\n🚫 Banned: {'Yes' if is_banned else 'No'}"
                bot.send_message(message.chat.id, format_message(txt), reply_markup=admin_keyboard(), parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, format_message("❌ Valid User ID enter karein!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_BAN':
            user_states.pop(uid, None)
            if text.isdigit():
                target = int(text)
                set_ban_status(target, 1)
                bot.send_message(message.chat.id, format_message(f"🚫 User <code>{target}</code> ban kar diya gaya!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, format_message("❌ Valid User ID enter karein!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_UNBAN':
            user_states.pop(uid, None)
            if text.isdigit():
                target = int(text)
                set_ban_status(target, 0)
                bot.send_message(message.chat.id, format_message(f"✅ User <code>{target}</code> unban kar diya gaya!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            else:
                bot.send_message(message.chat.id, format_message("❌ Valid User ID enter karein!"), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

        elif state == 'WAITING_BROADCAST':
            user_states.pop(uid, None)
            users = get_all_users()
            sent = 0
            for u in users:
                try:
                    bot.send_message(u, format_message(f"📢 <b>ANNOUNCEMENT</b>\n\n{text}"), parse_mode='HTML')
                    sent += 1
                except Exception:
                    pass
            bot.send_message(message.chat.id, format_message(f"✅ Broadcast Sent to {sent}/{len(users)} users."), reply_markup=admin_keyboard(), parse_mode='HTML')
            return

    # User State: Number Search
    if state == 'WAITING_NUMBER':
        if global_checks(message):
            return

        if not re.match(r'^\+?\d{10,12}$', text):
            bot.send_message(message.chat.id, format_message("❌ Kripya sahi 10-digit Mobile Number enter karein!"), reply_markup=cancel_keyboard(), parse_mode='HTML')
            return

        user_states.pop(uid, None)
        deduct_search(uid)
        
        msg_wait = bot.send_message(message.chat.id, "🔍 <i>Searching number details...</i>", parse_mode='HTML')
        res = get_number_info(text)

        if not res.get('success'):
            bot.edit_message_text(format_message(f"❌ <b>Error:</b> {res.get('msg', 'Data nahi mila.')}"), message.chat.id, msg_wait.message_id, parse_mode='HTML')
            bot.send_message(message.chat.id, "Main menu:", reply_markup=main_keyboard(uid))
            return

        data = res.get('data', {})
        # Remove API Developer branding tag if present
        if isinstance(data, dict):
            data.pop("API_Developer", None)

        formatted_data = json.dumps(data, indent=2, ensure_ascii=False)
        rem_searches, _ = get_user_data(uid)
        output_txt = (
            f"<b>📱 NUMBER OSINT RESULT</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📞 <b>Number:</b> <code>{text}</code>\n"
            f"⚡ <b>Remaining Searches:</b> <code>{rem_searches}</code>\n\n"
            f"<code>{formatted_data[:3000]}</code>"
        )
        bot.edit_message_text(format_message(output_txt), message.chat.id, msg_wait.message_id, parse_mode='HTML')
        bot.send_message(message.chat.id, "🔍 Select an option:", reply_markup=main_keyboard(uid))

# ==================== RUN BOT AND FLASK ====================
if __name__ == "__main__":
    def run_web():
        app.run(host='0.0.0.0', port=10000, use_reloader=False, threaded=True)
    
    t = threading.Thread(target=run_web, daemon=True)
    t.start()
    
    print("✅ Optimized Speed OSINT Bot Started with Multi-threading Connection Pooling.")
    bot.infinity_polling(skip_pending=True, allowed_updates=["message", "callback_query", "chat_join_request"])
