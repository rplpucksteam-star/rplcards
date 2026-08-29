import os
import re
import logging
import asyncio
import random
import time
from datetime import datetime, timedelta
import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан!")

ADMIN_SESSION_MINUTES = 30

SELL_PRICES = {
    "Редкая": 500,
    "Очень редкая": 1000,
    "Эпическая": 2500,
    "Мифическая": 5000,
    "Легендарная": 12000,
    "Секретная": 25000
}

# ==================== НОВЫЕ КОНСТАНТЫ (ПАТЧ) ====================
XP_FOR_CARD_RARITY = {
    "Редкая": 25,
    "Очень редкая": 50,
    "Эпическая": 100,
    "Мифическая": 250,
    "Легендарная": 500,
}

BOOSTERS = {
    "rare": {
        "title": "🔷 Редкий бустер",
        "price": 15000,
        "xp": 50,
        "xp_percent": 25,
        "money_percent": 0,
        "hours": 6,
    },
    "epic": {
        "title": "🟣 Эпический бустер",
        "price": 35000,
        "xp": 175,
        "xp_percent": 30,
        "money_percent": 0,
        "hours": 12,
    },
    "mythic": {
        "title": "🔴 Мифический бустер",
        "price": 70000,
        "xp": 250,
        "xp_percent": 30,
        "money_percent": 0,
        "hours": 24,
    },
    "legendary": {
        "title": "🟡 Легендарный бустер",
        "price": 130000,
        "xp": 500,
        "xp_percent": 30,
        "money_percent": 30,
        "hours": 48,
    },
}

(
    WAITING_LOGIN,
    WAITING_PASSWORD,
    WAITING_CHANNEL_USERNAME,
    WAITING_CHAT_LINK,
    WAITING_REPLY_TEXT,
    WAITING_SUPPORT_MSG,
    WAITING_DUEL_SHOT,
    WAITING_GIF_GOAL,
    WAITING_GIF_SAVE,
    CARD_ADMIN_MENU,
    ADD_COLLECTION_NAME,
    ADD_TEAM_NAME,
    ADD_TEAM_EMOJI,
    ADD_TEAM_PHOTO,
    DEL_TEAM_SELECT,
    ADD_CARD_RARITY,
    ADD_CARD_COLLECTION,
    ADD_CARD_COUNTRY,
    ADD_CARD_POSITION,
    ADD_CARD_TEAM,
    ADD_CARD_NICK,
    ADD_CARD_OVR,
    ADD_CARD_PHOTO,
    DEL_CARD_ID,
    ADD_PACK_NAME,
    ADD_PACK_PRICE,
    ADD_PACK_LIMIT,
    ADD_PACK_CARDS,
    ADD_PACK_PHOTO,
    GRANT_CARD_DATA,
    GIVE_MONEY_DATA,
    WAITING_VIEW_USER_INV,
    FREEPACK_ADMIN_SELECT_CARDS,
    ADD_PROMO_CODE,
    ADD_PROMO_TYPE,
    ADD_PROMO_VAL,
    ADD_PROMO_LIMIT,
    WAITING_PROMO_INPUT,
    WAITING_TRADE_TARGET,
    WAITING_TRADE_MONEY,
    WAITING_MARKET_PRICE_INPUT,
    WAITING_RPS_BET,
    WAITING_SLOTS_BET,
    WAITING_DICE_BET,
    WAITING_COIN_BET,
    ADMIN_SHOP_PACK_SELECT,
    ADMIN_SHOP_PACK_HOURS,
    WAITING_TEAM_NAME,
    WAITING_TEAM_COUNTRY,
    WAITING_TEAM_EMOJI,
) = range(50)

def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance INTEGER DEFAULT 5000,
            mmr INTEGER DEFAULT 1000,
            last_card_claim TIMESTAMP,
            last_daily_claim TIMESTAMP,
            daily_streak INTEGER DEFAULT 0,
            last_wheel_spin TIMESTAMP,
            free_card_cooldown_reset_until TIMESTAMP,
            freepack_claimed BOOLEAN DEFAULT FALSE,
            discount_percent INTEGER DEFAULT 0,
            matches_played INTEGER DEFAULT 0,
            matches_won INTEGER DEFAULT 0,
            matches_lost INTEGER DEFAULT 0,
            goals_scored INTEGER DEFAULT 0,
            goals_conceded INTEGER DEFAULT 0,
            custom_team_name TEXT DEFAULT 'RPL Team',
            custom_team_country TEXT DEFAULT 'Russian Federation',
            custom_team_emoji TEXT DEFAULT '🏒',
            coach_cooldown_until TIMESTAMP,
            illegal_cooldown_until TIMESTAMP
        )
    ''')
    
    c.execute('''
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS free_card_cooldown_reset_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS freepack_claimed BOOLEAN DEFAULT FALSE,
        ADD COLUMN IF NOT EXISTS discount_percent INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS matches_played INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS matches_won INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS matches_lost INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS goals_scored INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS goals_conceded INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS custom_team_name TEXT DEFAULT 'RPL Team',
        ADD COLUMN IF NOT EXISTS custom_team_country TEXT DEFAULT 'Russian Federation',
        ADD COLUMN IF NOT EXISTS custom_team_emoji TEXT DEFAULT '🏒',
        ADD COLUMN IF NOT EXISTS coach_cooldown_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS illegal_cooldown_until TIMESTAMP
    ''')
    
    # ===== ДОПОЛНИТЕЛЬНЫЕ ПОЛЯ (ПАТЧ) =====
    c.execute('''
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS experience INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS experience_bonus_percent INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS experience_bonus_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS money_bonus_percent INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS money_bonus_until TIMESTAMP
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS source_channels (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE,
            username TEXT,
            added_by BIGINT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS target_chats (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE,
            link TEXT,
            added_by BIGINT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            text TEXT,
            timestamp TEXT,
            answered INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY,
            last_activity INTEGER
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS collections (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS card_teams (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            emoji TEXT DEFAULT '🏒',
            photo_id TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS cards (
            id SERIAL PRIMARY KEY,
            collection_id INTEGER REFERENCES collections(id) ON DELETE CASCADE,
            team_id INTEGER REFERENCES card_teams(id) ON DELETE SET NULL,
            nickname TEXT NOT NULL,
            position TEXT NOT NULL,
            ovr INTEGER NOT NULL,
            country TEXT NOT NULL,
            rarity TEXT NOT NULL,
            image_id TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            count INTEGER DEFAULT 1,
            PRIMARY KEY(user_id, card_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_rosters (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            goalie_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater1_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater2_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater3_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater4_id INTEGER REFERENCES cards(id) ON DELETE SET NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS packs (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            buy_limit INTEGER DEFAULT 0,
            photo_id TEXT,
            available_until TIMESTAMP
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS pack_cards (
            pack_id INTEGER REFERENCES packs(id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            PRIMARY KEY(pack_id, card_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_pack_buys (
            user_id BIGINT,
            pack_id INTEGER REFERENCES packs(id) ON DELETE CASCADE,
            buy_count INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, pack_id)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS freepack_config (
            card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            reward_type TEXT NOT NULL,
            reward_value INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            current_uses INTEGER DEFAULT 0
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_promocodes (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            code TEXT REFERENCES promo_codes(code) ON DELETE CASCADE,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS market (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            price INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # ===== ТАБЛИЦА БУСТЕРОВ (ПАТЧ) =====
    c.execute('''
        CREATE TABLE IF NOT EXISTS user_boosters (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            booster_type TEXT NOT NULL,
            experience_amount INTEGER NOT NULL,
            experience_percent INTEGER DEFAULT 0,
            money_percent INTEGER DEFAULT 0,
            active_until TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def get_or_create_user(user_id, username="", first_name=""):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    if not row:
        c.execute(
            "INSERT INTO users (user_id, username, first_name, balance, mmr) VALUES (%s, %s, %s, 5000, 1000) RETURNING *",
            (user_id, username, first_name)
        )
        row = c.fetchone()
    else:
        c.execute("UPDATE users SET username = %s, first_name = %s WHERE user_id = %s", (username, first_name, user_id))
    conn.commit()
    conn.close()
    return row

def check_user_exists(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    row = c.fetchone()
    conn.close()
    return bool(row)

# ==================== ФУНКЦИИ XP (ПАТЧ) ====================
def get_level_and_progress(experience):
    """Первый уровень — 2500 XP, каждый следующий требует ещё +100 XP."""
    experience = max(0, int(experience or 0))
    level = 0
    required = 2500
    remaining = experience

    while remaining >= required:
        remaining -= required
        level += 1
        required += 100

    return level, remaining, required

def add_experience(cursor, user_id, amount):
    """Начисляет XP с учётом активного временного бонуса."""
    if amount <= 0:
        return 0

    now = datetime.now()
    cursor.execute("""
        SELECT experience_bonus_percent, experience_bonus_until
        FROM users
        WHERE user_id = %s
        FOR UPDATE
    """, (user_id,))
    row = cursor.fetchone() or {}

    bonus_percent = row.get("experience_bonus_percent") or 0
    bonus_until = row.get("experience_bonus_until")

    if bonus_until and now >= bonus_until:
        bonus_percent = 0
        cursor.execute("""
            UPDATE users
            SET experience_bonus_percent = 0,
                experience_bonus_until = NULL
            WHERE user_id = %s
        """, (user_id,))

    final_amount = int(amount * (100 + bonus_percent) / 100)
    cursor.execute("""
        UPDATE users
        SET experience = COALESCE(experience, 0) + %s
        WHERE user_id = %s
    """, (final_amount, user_id))
    return final_amount

def add_goal_reward(cursor, user_id, base_money=100, base_xp=10):
    """Награда за гол: XP и деньги с временным денежным бонусом."""
    now = datetime.now()
    cursor.execute("""
        SELECT money_bonus_percent, money_bonus_until
        FROM users
        WHERE user_id = %s
        FOR UPDATE
    """, (user_id,))
    row = cursor.fetchone() or {}

    money_percent = row.get("money_bonus_percent") or 0
    money_until = row.get("money_bonus_until")

    if money_until and now >= money_until:
        money_percent = 0
        cursor.execute("""
            UPDATE users
            SET money_bonus_percent = 0,
                money_bonus_until = NULL
            WHERE user_id = %s
        """, (user_id,))

    final_money = int(base_money * (100 + money_percent) / 100)
    final_xp = add_experience(cursor, user_id, base_xp)

    cursor.execute("""
        UPDATE users
        SET balance = balance + %s
        WHERE user_id = %s
    """, (final_money, user_id))

    return final_money, final_xp

def add_job_money(cursor, user_id, amount):
    """Начисление денег за работу с учётом бонуса легендарного бустера."""
    now = datetime.now()
    cursor.execute("""
        SELECT money_bonus_percent, money_bonus_until
        FROM users WHERE user_id = %s FOR UPDATE
    """, (user_id,))
    row = cursor.fetchone() or {}

    percent = row.get("money_bonus_percent") or 0
    until = row.get("money_bonus_until")
    if until and now >= until:
        percent = 0
        cursor.execute("""
            UPDATE users SET money_bonus_percent = 0, money_bonus_until = NULL
            WHERE user_id = %s
        """, (user_id,))

    final_amount = int(amount * (100 + percent) / 100)
    cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (final_amount, user_id))
    return final_amount

async def check_pm_registered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
        
    if check_user_exists(user.id):
        return True

    bot_username = context.bot.username
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Написать боту в ЛС", url=f"https://t.me/{bot_username}?start=start")]
    ])
    msg_text = "⚠️ **Чтобы взаимодействовать с ботом, сначала напишите ему в личные сообщения!**"
    
    if update.callback_query:
        await update.callback_query.answer("⚠️ Сначала напишите боту в ЛС!", show_alert=True)
    elif update.message:
        await update.message.reply_text(msg_text, reply_markup=kb, parse_mode="Markdown")
        
    return False

def choose_card_for_user(cursor, user_id, candidate_cards):
    if not candidate_cards:
        return None
    card_ids = tuple(c['id'] for c in candidate_cards)
    if len(card_ids) == 1:
        cursor.execute("SELECT card_id FROM user_cards WHERE user_id = %s AND card_id = %s AND count > 0", (user_id, card_ids[0]))
    else:
        cursor.execute("SELECT card_id FROM user_cards WHERE user_id = %s AND card_id IN %s AND count > 0", (user_id, card_ids))
    owned_rows = cursor.fetchall()
    owned_ids = set(r['card_id'] for r in owned_rows)
    unowned_cards = [c for c in candidate_cards if c['id'] not in owned_ids]
    if unowned_cards:
        return random.choice(unowned_cards)
    else:
        return random.choice(candidate_cards)

def choose_new_card_strict(cursor, user_id, candidate_cards):
    if not candidate_cards:
        return None
    card_ids = tuple(c['id'] for c in candidate_cards)
    if len(card_ids) == 1:
        cursor.execute("SELECT card_id FROM user_cards WHERE user_id = %s AND card_id = %s AND count > 0", (user_id, card_ids[0]))
    else:
        cursor.execute("SELECT card_id FROM user_cards WHERE user_id = %s AND card_id IN %s AND count > 0", (user_id, card_ids))
    owned_ids = set(r['card_id'] for r in cursor.fetchall())
    unowned_cards = [c for c in candidate_cards if c['id'] not in owned_ids]
    return random.choice(unowned_cards) if unowned_cards else None

def get_config(key):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM bot_config WHERE key = %s', (key,))
    row = c.fetchone()
    conn.close()
    return row['value'] if row else ''

def set_config(key, value):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO bot_config (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value', (key, value))
    conn.commit()
    conn.close()

def is_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT last_activity FROM admins WHERE user_id = %s', (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        last_activity = row['last_activity']
        if last_activity and (datetime.now().timestamp() - last_activity) < ADMIN_SESSION_MINUTES * 60:
            return True
        else:
            conn = get_db()
            c = conn.cursor()
            c.execute('DELETE FROM admins WHERE user_id = %s', (user_id,))
            conn.commit()
            conn.close()
            return False
    return False

def add_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO admins (user_id, last_activity) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET last_activity = EXCLUDED.last_activity',
              (user_id, int(datetime.now().timestamp())))
    conn.commit()
    conn.close()

def update_admin_activity(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE admins SET last_activity = %s WHERE user_id = %s',
              (int(datetime.now().timestamp()), user_id))
    conn.commit()
    conn.close()

def remove_admin(user_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('DELETE FROM admins WHERE user_id = %s', (user_id,))
    conn.commit()
    conn.close()

def check_credentials(login, password):
    credentials = {
        "goyda1488": "goydarpl",
        "rzk1488": "rzksigma",
    }
    return credentials.get(login) == password

def add_source_channel(chat_id, username, added_by):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO source_channels (chat_id, username, added_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
              (chat_id, username, added_by))
    conn.commit()
    conn.close()

def get_source_channels():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT chat_id, username FROM source_channels')
    rows = c.fetchall()
    conn.close()
    return rows

def add_target_chat(chat_id, link, added_by):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO target_chats (chat_id, link, added_by) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING',
              (chat_id, link, added_by))
    conn.commit()
    conn.close()

def get_target_chats():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT chat_id, link FROM target_chats')
    rows = c.fetchall()
    conn.close()
    return rows

def add_support_message(user_id, username, text):
    conn = get_db()
    c = conn.cursor()
    c.execute('INSERT INTO support_messages (user_id, username, text, timestamp) VALUES (%s, %s, %s, %s) RETURNING id',
              (user_id, username, text, datetime.now().isoformat()))
    msg_id = c.fetchone()['id']
    conn.commit()
    conn.close()
    return msg_id

def get_unanswered_messages():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT id, user_id, username, text, timestamp FROM support_messages WHERE answered = 0 ORDER BY id')
    rows = c.fetchall()
    conn.close()
    return rows

def mark_answered(msg_id):
    conn = get_db()
    c = conn.cursor()
    c.execute('UPDATE support_messages SET answered = 1 WHERE id = %s', (msg_id,))
    conn.commit()
    conn.close()

# ==================== ОБНОВЛЁННЫЕ КЛАВИАТУРЫ (ПАТЧ) ====================
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["🏠 Главная", "🎴 Карточка дня"],
        ["🎒 Коллекция", "🏪 Торговая площадка"],
        ["👤 Профиль и состав", "🏟 Найти матч"],
        ["🛍 Магазин", "🏆 Рейтинг MMR"],
        ["🤝 Обмен", "🎟 Промокод"],
        ["🎮 Игры", "🎡 Колесо удачи"],
        ["💼 Работы", "🎁 Ежедневная награда"],
    ], resize_keyboard=True)

def admin_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Добавить каналы", "➕ Добавить чаты"],
        ["📩 Проверить поддержку", "⚙️ Настройки"],
        ["🎮 Настройки игры", "🃏 Карточки"],
        ["📦 Выставить пак в магазин", "🔍 Инвентарь игрока"],
        ["👥 Список игроков", "🚪 Выйти"]
    ], resize_keyboard=True)

def card_admin_keyboard():
    return ReplyKeyboardMarkup([
        ["📁 Создать коллекцию", "🛡 Создать команду"],
        ["❌ Удалить команду", "🃏 Добавить карточку"],
        ["❌ Удалить карточку", "📦 Добавить пак"],
        ["📦 Настроить стартовый набор", "🎁 Выдать карточку игроку"],
        ["💰 Выдать деньги", "🎟 Создать промокод"],
        ["⬅️ Выйти из настройки карточек"]
    ], resize_keyboard=True)

def welcome_inline_keyboard():
    keyboard = [
        [InlineKeyboardButton("💬 Наш Discord", callback_data="discord")],
        [InlineKeyboardButton("🌐 Наш Сайт", callback_data="website")],
        [InlineKeyboardButton("🆘 Обратиться в поддержку", callback_data="support")],
        [InlineKeyboardButton("🏒 Дуэль Буллитов", callback_data="duel")]
    ]
    return InlineKeyboardMarkup(keyboard)

def duel_shot_keyboard():
    keyboard = [
        [InlineKeyboardButton("🥅 Левая девятка", callback_data="shot_left")],
        [InlineKeyboardButton("🥅 Правая девятка", callback_data="shot_right")],
        [InlineKeyboardButton("🧤 Домик (между щитков)", callback_data="shot_five")],
        [InlineKeyboardButton("🥅 Низ в угол", callback_data="shot_low")]
    ]
    return InlineKeyboardMarkup(keyboard)

def store_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Магазин паков", callback_data="store_packs")],
        [InlineKeyboardButton("🚀 Магазин бустеров", callback_data="store_boosters")],
        [InlineKeyboardButton("↩️ Главное меню", callback_data="back_to_main_inline")],
    ])

COUNTRIES = [
    "Russian Federation", "USA", "Canada", "Finland", "Sweden", "Czech Republic",
    "Slovakia", "Germany", "Switzerland", "Latvia", "Belarus", "Kazakhstan",
    "UK", "France", "Austria", "Norway", "Denmark", "Japan", "China"
]

async def grant_free_pack_to_user(user_id, context):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT freepack_claimed FROM users WHERE user_id = %s", (user_id,))
    usr = c.fetchone()
    if usr and usr['freepack_claimed']:
        conn.close()
        return False, "❌ Вы уже получили свой бесплатный стартовый набор!"

    c.execute("SELECT card_id FROM freepack_config")
    conf_cards = c.fetchall()

    if not conf_cards:
        c.execute("SELECT id FROM cards WHERE position = 'Goalie' LIMIT 1")
        g_card = c.fetchone()
        c.execute("SELECT id FROM cards WHERE position = 'Skater' LIMIT 4")
        s_cards = c.fetchall()
        
        if not g_card or len(s_cards) < 4:
            conn.close()
            return False, "❌ В базе данных недостаточно карт для формирования стартового набора. Обратитесь к администратору."
        card_ids = [g_card['id']] + [s['id'] for s in s_cards]
    else:
        card_ids = [rc['card_id'] for rc in conf_cards]

    for cid in card_ids:
        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user_id, cid))

    c.execute("SELECT * FROM cards WHERE id IN %s", (tuple(card_ids),))
    all_issued_cards = c.fetchall()
    
    goalie_id = next((c_item['id'] for c_item in all_issued_cards if c_item['position'] == 'Goalie'), None)
    skaters = [c_item['id'] for c_item in all_issued_cards if c_item['position'] == 'Skater']

    c.execute('''
        INSERT INTO user_rosters (user_id, goalie_id, skater1_id, skater2_id, skater3_id, skater4_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            goalie_id = COALESCE(user_rosters.goalie_id, EXCLUDED.goalie_id),
            skater1_id = COALESCE(user_rosters.skater1_id, EXCLUDED.skater1_id),
            skater2_id = COALESCE(user_rosters.skater2_id, EXCLUDED.skater2_id),
            skater3_id = COALESCE(user_rosters.skater3_id, EXCLUDED.skater3_id),
            skater4_id = COALESCE(user_rosters.skater4_id, EXCLUDED.skater4_id)
    ''', (
        user_id, 
        goalie_id, 
        skaters[0] if len(skaters) > 0 else None,
        skaters[1] if len(skaters) > 1 else None,
        skaters[2] if len(skaters) > 2 else None,
        skaters[3] if len(skaters) > 3 else None,
    ))

    c.execute("UPDATE users SET freepack_claimed = TRUE WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()
    return True, "🎉 **Поздравляем!** Вы успешно получили бесплатный стартовый набор карточек и они сразу были установлены в ваш состав!"

async def freepack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    success, msg = await grant_free_pack_to_user(user.id, context)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def freepack_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "claim_freepack_btn":
        success, msg = await grant_free_pack_to_user(query.from_user.id, context)
        await query.message.edit_text(msg, parse_mode="Markdown")

async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    await update.message.reply_text(
        f"🆔 **ID этого чата:** `{chat.id}`\n📌 **Тип чата:** `{chat.type}`",
        parse_mode="Markdown"
    )

async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT last_daily_claim, daily_streak FROM users WHERE user_id = %s", (user.id,))
    row = c.fetchone()
    conn.close()

    now = datetime.now()
    last_claim = row.get('last_daily_claim') if row else None
    streak = row.get('daily_streak', 0) if row else 0

    if last_claim:
        if isinstance(last_claim, str):
            last_claim = datetime.fromisoformat(last_claim)
        
        diff = now - last_claim
        if diff.total_seconds() < 86400:
            remaining = timedelta(seconds=86400) - diff
            hours, rem = divmod(int(remaining.total_seconds()), 3600)
            minutes = rem // 60
            await update.message.reply_text(
                f"⏳ Ежедневный бонус можно забирать раз в 24 часа!\nПодождите ещё: **{hours} ч {minutes} мин**\nВаш текущий стрик: **{streak} дней** 🔥",
                parse_mode="Markdown"
            )
            return
        elif diff.total_seconds() > 172800:
            streak = 0

    streak = (streak % 7) + 1
    conn = get_db()
    c = conn.cursor()

    reward_text = ""
    if streak == 1:
        c.execute("UPDATE users SET balance = balance + 5000, daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))
        reward_text = "5 000 RPLCoin 💳"
    elif streak == 2:
        c.execute("UPDATE users SET balance = balance + 10000, daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))
        reward_text = "10 000 RPLCoin 💳"
    elif streak == 3:
        c.execute("UPDATE users SET balance = balance + 15000, daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))
        reward_text = "15 000 RPLCoin 💳"
    elif streak == 4:
        c.execute("UPDATE users SET discount_percent = 15, daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))
        reward_text = "Скидку 15% в магазине на любую покупку и торговую площадку 🏷"
    elif streak == 5:
        c.execute("UPDATE users SET free_card_cooldown_reset_until = %s, daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (datetime.max, streak, now, user.id))
        reward_text = "Обнуление КД на бесплатную карточку ✨"
    elif streak == 6:
        c.execute("SELECT * FROM cards WHERE rarity != 'Секретная'")
        all_cds = c.fetchall()
        card = choose_card_for_user(c, user.id, all_cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            reward_text = f"Любая карточка: **{card['nickname']}** ({card['ovr']} OVR) [{card['rarity']}] 🃏"
        else:
            reward_text = "50 000 RPLCoin (нет карт в базе) 💳"
            c.execute("UPDATE users SET balance = balance + 50000 WHERE user_id = %s", (user.id,))
        c.execute("UPDATE users SET daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))
    elif streak == 7:
        c.execute("SELECT * FROM cards WHERE rarity IN ('Эпическая', 'Мифическая')")
        epic_mythic = c.fetchall()
        card = choose_card_for_user(c, user.id, epic_mythic) if epic_mythic else None
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            reward_text = f"Эпическая/Мифическая карточка: **{card['nickname']}** ({card['ovr']} OVR) [{card['rarity']}] 🌟"
        else:
            c.execute("UPDATE users SET balance = balance + 100000 WHERE user_id = %s", (user.id,))
            reward_text = "100 000 RPLCoin 💳"
        c.execute("UPDATE users SET daily_streak = %s, last_daily_claim = %s WHERE user_id = %s", (streak, now, user.id))

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎁 **Ежедневный бонус за день {streak}/7 успешно получен!**\nВы получили: {reward_text}\n\nВозвращайтесь завтра за новым бонусом!",
        parse_mode="Markdown"
    )

async def wheel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance, last_wheel_spin FROM users WHERE user_id = %s", (user.id,))
    u_row = c.fetchone()
    conn.close()

    if not u_row:
        return

    last_spin = u_row['last_wheel_spin']
    now = datetime.now()
    if last_spin:
        if isinstance(last_spin, str):
            last_spin = datetime.fromisoformat(last_spin)
        diff = now - last_spin
        if diff.total_seconds() < 129600:
            rem = timedelta(seconds=129600) - diff
            hours, rem_sec = divmod(int(rem.total_seconds()), 3600)
            minutes = rem_sec // 60
            await update.message.reply_text(f"⏳ Колесо удачи можно крутить раз в **36 часов**!\nПодождите ещё: **{hours} ч {minutes} мин**", parse_mode="Markdown")
            return

    cost = 10000
    if u_row['balance'] < cost:
        await update.message.reply_text(f"❌ Недостаточно средств! Прокрутка колеса стоит **{cost} RPLCoin**.", parse_mode="Markdown")
        return

    msg = await update.message.reply_text("🎡 **Идет открытие колеса удачи...** ⏳", parse_mode="Markdown")
    await asyncio.sleep(5)

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
    except Exception:
        pass

    prizes = ["reset_cd", "money", "card_50_65", "card_70_80", "card_80_85", "discount", "custom_card", "rare", "very_rare", "epic", "mythic", "nothing"]

    if get_config("custom_card_prize_claimed") == "1":
        prizes = [p for p in prizes if p != "custom_card"]

    prize = random.choice(prizes)

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance - %s, last_wheel_spin = %s WHERE user_id = %s", (cost, now, user.id))

    prize_text = ""
    if prize == "reset_cd":
        c.execute("UPDATE users SET free_card_cooldown_reset_until = %s WHERE user_id = %s", (datetime.max, user.id))
        prize_text = "✨ **Обнуление КД на выпадение бесплатной карты!**"
    elif prize == "money":
        amount = random.randint(1000, 150000)
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user.id))
        prize_text = f"💵 **Денежный приз:** +{amount} RPLCoin!"
    elif prize == "card_50_65":
        c.execute("SELECT * FROM cards WHERE ovr BETWEEN 50 AND 65")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🃏 **Карточка (50-65 OVR):** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 20000 WHERE user_id = %s", (user.id,))
            prize_text = "💵 Карточек 50-65 не найдено, зачислено 20 000 RPLCoin!"
    elif prize == "card_70_80":
        c.execute("SELECT * FROM cards WHERE ovr BETWEEN 70 AND 80")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🃏 **Карточка (70-80 OVR):** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 40000 WHERE user_id = %s", (user.id,))
            prize_text = "💵 Карточек 70-80 не найдено, зачислено 40 000 RPLCoin!"
    elif prize == "card_80_85":
        c.execute("SELECT * FROM cards WHERE ovr BETWEEN 80 AND 85")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🃏 **Карточка (80-85 OVR):** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 70000 WHERE user_id = %s", (user.id,))
            prize_text = "💵 Карточек 80-85 не найдено, зачислено 70 000 RPLCoin!"
    elif prize == "discount":
        disc = random.randint(10, 30)
        c.execute("UPDATE users SET discount_percent = %s WHERE user_id = %s", (disc, user.id))
        prize_text = f"🏷 **Скидка {disc}%** на магазин и торговую площадку применена к вашему аккаунту!"
    elif prize == "custom_card":
        set_config("custom_card_prize_claimed", "1")
        prize_text = "🎨 **Уникальный приз: создание своей карты с рейтингом 82!** Свяжитесь с администратором @admin для создания."
    elif prize == "rare":
        c.execute("SELECT * FROM cards WHERE rarity = 'Редкая'")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🌟 **Карта редкости Редкий:** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 10000 WHERE user_id = %s", (user.id,))
            prize_text = "🌟 Карта редкости Редкий (компенсация 10000 RPLCoin)"
    elif prize == "very_rare":
        c.execute("SELECT * FROM cards WHERE rarity = 'Очень редкая'")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🌟 **Карта редкости Очень Редкий:** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 20000 WHERE user_id = %s", (user.id,))
            prize_text = "🌟 Очень Редкий (компенсация 20000 RPLCoin)"
    elif prize == "epic":
        c.execute("SELECT * FROM cards WHERE rarity = 'Эпическая'")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🌟 **Карта редкости Эпический:** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 40000 WHERE user_id = %s", (user.id,))
            prize_text = "🌟 Эпический (компенсация 40000 RPLCoin)"
    elif prize == "mythic":
        c.execute("SELECT * FROM cards WHERE rarity = 'Мифическая'")
        cds = c.fetchall()
        card = choose_card_for_user(c, user.id, cds)
        if card:
            c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user.id, card['id']))
            prize_text = f"🌟 **Карта редкости Мифический:** {card['nickname']} ({card['ovr']} OVR)"
        else:
            c.execute("UPDATE users SET balance = balance + 80000 WHERE user_id = %s", (user.id,))
            prize_text = "🌟 Мифический (компенсация 80000 RPLCoin)"
    else:
        prize_text = "💨 **Ничего!** Повезет в следующий раз."

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎡 **Колесо удачи прокручено!**\n\n{prize_text}",
        parse_mode="Markdown"
    )

# ==================== РАЗДЕЛ "РАБОТЫ" ====================

async def jobs_menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏒 Тренер бросков (КД 2ч)", callback_data="job_coach_main")],
        [InlineKeyboardButton("🕵️‍♂️ Нелегал (КД 12ч / 48ч)", callback_data="job_illegal_main")],
        [InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_main_inline")]
    ])

    text = (
        "💼 **РАЗДЕЛ «РАБОТЫ»**\n\n"
        "Здесь вы можете заработать дополнительные RPLCoin!\n\n"
        "1️⃣ **Тренер бросков:**\n"
        "• Шанс успеха: 40%\n"
        "• Награда: **15 000 RPLCoin**\n"
        "• Кулдаун: **2 часа**\n\n"
        "2️⃣ **Нелегал:**\n"
        "• Различные рискованные дела (Банк, Кошелек, Магазин).\n"
        "• Возможность заработать до **100 000 RPLCoin**!\n"
        "• Риск попасть в тюрьму (КД **48 часов**)!"
    )

    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def job_coach_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coach_cooldown_until FROM users WHERE user_id = %s", (user.id,))
    row = c.fetchone()
    conn.close()

    now = datetime.now()
    cd_until = row.get('coach_cooldown_until') if row else None

    if cd_until:
        if isinstance(cd_until, str):
            cd_until = datetime.fromisoformat(cd_until)
        if now < cd_until:
            rem = cd_until - now
            hours, rem_sec = divmod(int(rem.total_seconds()), 3600)
            minutes = rem_sec // 60
            await query.edit_message_text(
                f"⏳ **Вы устали после проведения тренировки!**\nСледующая работа «Тренер бросков» будет доступна через **{hours} ч {minutes} мин**.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]]),
                parse_mode="Markdown"
            )
            return

    text = "🏒 **Тренировка бросков! Какие броски будем тренировать?**"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🥅 Броски в девятку", callback_data="job_coach_shoot1")],
        [InlineKeyboardButton("🎯 Буллиты", callback_data="job_coach_shoot2")],
        [InlineKeyboardButton("⚡️ Щелчки", callback_data="job_coach_shoot3")],
        [InlineKeyboardButton("🎬 Игровые моменты", callback_data="job_coach_shoot4")],
        [InlineKeyboardButton("🛡 Против 2-х защитников", callback_data="job_coach_shoot5")],
        [InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def job_coach_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT coach_cooldown_until FROM users WHERE user_id = %s", (user.id,))
    row = c.fetchone()

    now = datetime.now()
    cd_until = row.get('coach_cooldown_until') if row else None

    if cd_until:
        if isinstance(cd_until, str):
            cd_until = datetime.fromisoformat(cd_until)
        if now < cd_until:
            conn.close()
            rem = cd_until - now
            hours, rem_sec = divmod(int(rem.total_seconds()), 3600)
            minutes = rem_sec // 60
            await query.edit_message_text(
                f"⏳ **Вы уже провели тренировку!** Отдохните еще **{hours} ч {minutes} мин**.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="jobs_menu")]]),
                parse_mode="Markdown"
            )
            return

    new_cd = now + timedelta(hours=2)

    if random.random() < 0.40:
        reward = 15000
        # Используем add_job_money для учёта бонуса
        final_reward = add_job_money(c, user.id, reward)
        c.execute("UPDATE users SET coach_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
        conn.commit()
        conn.close()
        res_text = f"🎉 **ОТЛИЧНАЯ ТРЕНИРОВКА!** Игроки успешно отработали элементы, и руководство выплатило вам премию в размере **{final_reward} RPLCoin**!"
    else:
        c.execute("UPDATE users SET coach_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
        conn.commit()
        conn.close()
        res_text = "😔 **НЕУДАЧНАЯ ТРЕНИРОВКА!** Броски летели мимо ворот, тренировка сорвалась. В этот раз вы остались без выплаты."

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]])
    await query.edit_message_text(f"🏒 **Результат работы «Тренер бросков»:**\n\n{res_text}\n\n⏳ Следующая тренировка через 2 часа.", reply_markup=kb, parse_mode="Markdown")

async def job_illegal_main_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT illegal_cooldown_until FROM users WHERE user_id = %s", (user.id,))
    row = c.fetchone()
    conn.close()

    now = datetime.now()
    cd_until = row.get('illegal_cooldown_until') if row else None

    if cd_until:
        if isinstance(cd_until, str):
            cd_until = datetime.fromisoformat(cd_until)
        if now < cd_until:
            rem = cd_until - now
            hours, rem_sec = divmod(int(rem.total_seconds()), 3600)
            minutes = rem_sec // 60

            if rem.total_seconds() > 12 * 3600:
                msg_status = f"🚔 **ВЫ В ТЮРЬМЕ!**\nВас поймала полиция! Срок заключения закончится через **{hours} ч {minutes} мин**."
            else:
                msg_status = f"🕵️‍♂️ **НЕЛЬЗЯ РИСКОВАТЬ!**\nЛегавые на хвосте. Залечь на дно еще на **{hours} ч {minutes} мин**."

            await query.edit_message_text(
                msg_status,
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]]),
                parse_mode="Markdown"
            )
            return

    text = (
        "🕵️‍♂️ **РАБОТА «НЕЛЕГАЛ»**\n\n"
        "Выберите, какое дело хотите прокрутить:\n\n"
        "1️⃣ **Ограбить банк:**\n"
        "• 🟢 Успех (15%): **100 000 RPLCoin**\n"
        "• ⚪️ Неудача (15%): ничего\n"
        "• 🔴 Тюрьма (70%): КД **48 часов**\n\n"
        "2️⃣ **Украсть кошелёк:**\n"
        "• 🟢 Успех (40%): **до 10 000 RPLCoin**\n"
        "• ⚪️ Неудача (40%): ничего\n"
        "• 🔴 Тюрьма (20%): КД **48 часов**\n\n"
        "3️⃣ **Украсть продукты в магазине:**\n"
        "• 🟢 Успех (30%): **до 15 000 RPLCoin**\n"
        "• ⚪️ Неудача (30%): ничего\n"
        "• 🔴 Тюрьма (40%): КД **48 часов**"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🏦 Ограбить банк", callback_data="job_ill_bank")],
        [InlineKeyboardButton("👛 Украсть кошелёк", callback_data="job_ill_wallet")],
        [InlineKeyboardButton("🛒 Украсть продукты в магазине", callback_data="job_ill_groceries")],
        [InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]
    ])
    await query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")

async def job_illegal_action_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user
    action = query.data

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT illegal_cooldown_until FROM users WHERE user_id = %s", (user.id,))
    row = c.fetchone()

    now = datetime.now()
    cd_until = row.get('illegal_cooldown_until') if row else None

    if cd_until:
        if isinstance(cd_until, str):
            cd_until = datetime.fromisoformat(cd_until)
        if now < cd_until:
            conn.close()
            rem = cd_until - now
            hours, rem_sec = divmod(int(rem.total_seconds()), 3600)
            minutes = rem_sec // 60
            await query.edit_message_text(
                f"⏳ Вы еще не можете делать нелегальные дела! Времени осталось: **{hours} ч {minutes} мин**.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="jobs_menu")]]),
                parse_mode="Markdown"
            )
            return

    rand_val = random.random()
    res_text = ""

    if action == "job_ill_bank":
        if rand_val < 0.15:
            reward = 100000
            final_reward = add_job_money(c, user.id, reward)
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = f"🎉 **ГРАНДИОЗНЫЙ УСПЕХ!** Вы ограбили банк и ушли незамеченными! Награда: **{final_reward} RPLCoin**! 💰\n⏳ Кулдаун: 12 часов."
        elif rand_val < 0.30:
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "⚪️ **НЕУДАЧА!** Сигнализация сработала, но вам удалось сбежать без добычи!\n⏳ Кулдаун: 12 часов."
        else:
            new_cd = now + timedelta(hours=48)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "🚨 **ТЮРЬМА!** Охрана банка скрутила вас прямо у хранилища! Вы отправлены за решетку.\n🚔 Срок заключения: **48 часов**."

    elif action == "job_ill_wallet":
        if rand_val < 0.40:
            reward = random.randint(1000, 10000)
            final_reward = add_job_money(c, user.id, reward)
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = f"🎉 **УСПЕХ!** Вы тихо вытащили кошелёк из кармана и нашли там **{final_reward} RPLCoin**! 👛\n⏳ Кулдаун: 12 часов."
        elif rand_val < 0.80:
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "⚪️ **НЕУДАЧА!** В кошельке не оказалось наличных, пришлось выкинуть его.\n⏳ Кулдаун: 12 часов."
        else:
            new_cd = now + timedelta(hours=48)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "🚨 **ТЮРЬМА!** Владелец кошелька заметил кражу и вызвал полицию! Вы арестованы.\n🚔 Срок заключения: **48 часов**."

    elif action == "job_ill_groceries":
        if rand_val < 0.30:
            reward = random.randint(1000, 15000)
            final_reward = add_job_money(c, user.id, reward)
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = f"🎉 **УСПЕХ!** Вы вынесли товары из супермаркета и перепродали их на сумму **{final_reward} RPLCoin**! 🛒\n⏳ Кулдаун: 12 часов."
        elif rand_val < 0.60:
            new_cd = now + timedelta(hours=12)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "⚪️ **НЕУДАЧА!** Охранник заметил вас на выходе, пришлось бросить сумки и удрать.\n⏳ Кулдаун: 12 часов."
        else:
            new_cd = now + timedelta(hours=48)
            c.execute("UPDATE users SET illegal_cooldown_until = %s WHERE user_id = %s", (new_cd, user.id))
            res_text = "🚨 **ТЮРЬМА!** Вас зажали в тупике охранники магазина и передали полиции.\n🚔 Срок заключения: **48 часов**."

    conn.commit()
    conn.close()

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад к работам", callback_data="jobs_menu")]])
    await query.edit_message_text(f"🕵️‍♂️ **Результат работы «Нелегал»:**\n\n{res_text}", reply_markup=kb, parse_mode="Markdown")

# =========================================================

async def rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text("🎮 **Камень - Ножницы - Бумага**\nВведите ставку в RPLCoin (целое число):", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
    return WAITING_RPS_BET

async def rps_receive_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            await update.message.reply_text("❌ Ставка должна быть больше 0!", reply_markup=bet_cancel_keyboard())
            return WAITING_RPS_BET

        user = update.effective_user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        u_bal = c.fetchone()['balance']
        conn.close()

        if bet > u_bal:
            await update.message.reply_text(f"❌ Недостаточно средств! Ваш баланс: {u_bal} RPLCoin.", reply_markup=bet_cancel_keyboard())
            return WAITING_RPS_BET

        context.user_data["rps_bet"] = bet
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🪨 Камень", callback_data="rps_rock"),
             InlineKeyboardButton("✂️ Ножницы", callback_data="rps_scissors"),
             InlineKeyboardButton("📄 Бумага", callback_data="rps_paper")],
            [InlineKeyboardButton("🔙 Назад", callback_data="cancel_minigame")]
        ])
        await update.message.reply_text(f"✅ Ставка принята: **{bet} RPLCoin**.\nВыберите ваш ход:", reply_markup=kb, parse_mode="Markdown")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите ставку числом!", reply_markup=bet_cancel_keyboard())
        return WAITING_RPS_BET

async def rps_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("rps_"):
        return

    await query.answer()
    player_choice = data.replace("rps_", "")
    bet = context.user_data.get("rps_bet", 100)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    u_bal = c.fetchone()['balance']

    if bet > u_bal:
        conn.close()
        await query.message.edit_text("❌ Ошибка: недостаточно средств для выплаты ставки.")
        return

    rand_val = random.random()
    if rand_val < 0.42:
        if player_choice == "rock": bot_choice = "scissors"
        elif player_choice == "scissors": bot_choice = "paper"
        else: bot_choice = "rock"
        result = "win"
    elif rand_val < 0.58:
        bot_choice = player_choice
        result = "draw"
    else:
        if player_choice == "rock": bot_choice = "paper"
        elif player_choice == "scissors": bot_choice = "rock"
        else: bot_choice = "scissors"
        result = "lose"

    emojis = {"rock": "🪨 Камень", "scissors": "✂️ Ножницы", "paper": "📄 Бумага"}

    if result == "win":
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, user.id))
        res_str = f"🎉 **ПОБЕДА!** Вы выиграли **{bet} RPLCoin**!"
    elif result == "lose":
        c.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user.id))
        res_str = f"❌ **ПОРАЖЕНИЕ!** Вы потеряли **{bet} RPLCoin**."
    else:
        res_str = "🤝 **НИЧЬЯ!** Ставка возвращена на баланс."

    conn.commit()
    conn.close()

    text = (
        f"🎮 **Результат игры КНБ:**\n\n"
        f"👤 Ваш выбор: {emojis[player_choice]}\n"
        f"🤖 Выбор бота: {emojis[bot_choice]}\n\n"
        f"{res_str}"
    )
    await query.message.edit_text(text, parse_mode="Markdown")

async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text("🪙 **Мини-игра Орёл и Решка**\nШанс на выигрыш: **20%**, шанс на проигрыш: **80%**.\nВведите ставку в RPLCoin:", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
    return WAITING_COIN_BET

async def coin_receive_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            await update.message.reply_text("❌ Ставка должна быть больше 0!", reply_markup=bet_cancel_keyboard())
            return WAITING_COIN_BET

        user = update.effective_user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        u_bal = c.fetchone()['balance']
        conn.close()

        if bet > u_bal:
            await update.message.reply_text(f"❌ Недостаточно средств! Баланс: {u_bal} RPL", reply_markup=bet_cancel_keyboard())
            return WAITING_COIN_BET

        context.user_data["coin_bet"] = bet
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🦅 Орёл", callback_data="coin_eagle"), InlineKeyboardButton("🪙 Решка", callback_data="coin_tail")],
            [InlineKeyboardButton("🔙 Назад", callback_data="cancel_minigame")]
        ])
        await update.message.reply_text(f"✅ Ставка принята: **{bet} RPL**.\nВыберите сторону монеты:", reply_markup=kb, parse_mode="Markdown")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите ставку числом!", reply_markup=bet_cancel_keyboard())
        return WAITING_COIN_BET

async def coin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if not data.startswith("coin_"):
        return

    await query.answer()
    player_choice = data.replace("coin_", "")
    bet = context.user_data.get("coin_bet", 100)

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    u_bal = c.fetchone()['balance']

    if bet > u_bal:
        conn.close()
        await query.message.edit_text("❌ Недостаточно средств.")
        return

    win = random.random() < 0.20
    bot_choice = player_choice if win else ("tail" if player_choice == "eagle" else "eagle")

    if win:
        win_amt = bet * 4
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (win_amt, user.id))
        res_str = f"🎉 **ПОБЕДА!** Монета упала правильно! Вы выиграли **{win_amt} RPLCoin** (Коэффициент x4)!"
    else:
        c.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user.id))
        res_str = f"❌ **ПОРАЖЕНИЕ!** Вы потеряли ставку **{bet} RPLCoin**."

    conn.commit()
    conn.close()

    names = {"eagle": "🦅 Орёл", "tail": "🪙 Решка"}
    text = (
        f"🪙 **Результат Орёл и Решка:**\n\n"
        f"👤 Ваш выбор: {names[player_choice]}\n"
        f"🪙 Результат подброса: {names[bot_choice]}\n\n"
        f"{res_str}"
    )
    await query.message.edit_text(text, parse_mode="Markdown")

async def slots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text("🎰 **Игровые Слоты**\nВведите ставку в RPLCoin (целое число):", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
    return WAITING_SLOTS_BET

async def slots_receive_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            await update.message.reply_text("❌ Ставка должна быть больше 0!", reply_markup=bet_cancel_keyboard())
            return WAITING_SLOTS_BET

        user = update.effective_user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        u_bal = c.fetchone()['balance']
        conn.close()

        if bet > u_bal:
            await update.message.reply_text(f"❌ Недостаточно средств! Ваш баланс: {u_bal} RPLCoin.", reply_markup=bet_cancel_keyboard())
            return WAITING_SLOTS_BET

        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user.id))
        conn.commit()
        conn.close()

        msg = await update.message.reply_text("🎰 | 🔄 | 🔄 | 🔄 |\nКрутим слоты...", parse_mode="Markdown")
        await asyncio.sleep(2)

        symbols = ["🏒", "🥅", "⭐", "🍒", "7️⃣", "💎"]
        r = random.random()
        if r < 0.03:
            sym = random.choice(["7️⃣", "💎", "⭐"])
            line = [sym, sym, sym]
            mult = 10
        elif r < 0.10:
            sym = random.choice(symbols)
            line = [sym, sym, sym]
            mult = 5
        elif r < 0.25:
            sym = random.choice(symbols)
            other = random.choice([s for s in symbols if s != sym])
            line = [sym, sym, other]
            random.shuffle(line)
            mult = 2
        else:
            while True:
                line = random.choices(symbols, k=3)
                if len(set(line)) == 3:
                    break
            mult = 0

        conn = get_db()
        c = conn.cursor()
        if mult > 0:
            win_amount = int(bet * mult)
            c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (win_amount, user.id))
            conn.commit()
            conn.close()
            res_text = f"🎰 | {line[0]} | {line[1]} | {line[2]} |\n\n🎉 **ПОБЕДА!** Вы выиграли **{win_amount} RPLCoin** (Множитель x{mult})!"
        else:
            conn.close()
            res_text = f"🎰 | {line[0]} | {line[1]} | {line[2]} |\n\n❌ **ПРОИГРЫШ!** Вы потеряли ставку **{bet} RPLCoin**."

        await msg.edit_text(res_text, parse_mode="Markdown")
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Введите ставку числом!", reply_markup=bet_cancel_keyboard())
        return WAITING_SLOTS_BET

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text("🎲 **Игра в Кости**\nСначала бросает бот, затем бот бросает за вас!\nВведите ставку в RPLCoin (целое число):", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
    return WAITING_DICE_BET

async def dice_receive_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            await update.message.reply_text("❌ Ставка должна быть больше 0!", reply_markup=bet_cancel_keyboard())
            return WAITING_DICE_BET

        user = update.effective_user
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        u_bal = c.fetchone()['balance']
        conn.close()

        if bet > u_bal:
            await update.message.reply_text(f"❌ Недостаточно средств! Ваш баланс: {u_bal} RPLCoin.", reply_markup=bet_cancel_keyboard())
            return WAITING_DICE_BET

        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user.id))
        conn.commit()
        conn.close()

        msg = await update.message.reply_text("🎲 Бот готовится к броску...", parse_mode="Markdown")
        await asyncio.sleep(2)

        r = random.random()
        if r < 0.25:
            bot_val = random.randint(1, 4)
            player_val = random.randint(bot_val + 1, 6)
            res = "win"
        elif r < 0.45:
            bot_val = random.randint(1, 6)
            player_val = bot_val
            res = "draw"
        else:
            bot_val = random.randint(2, 6)
            player_val = random.randint(1, bot_val - 1)
            res = "lose"

        await msg.edit_text(f"🤖 Бот бросает кости...\n🎲 Результат бота: **{bot_val}**", parse_mode="Markdown")
        await asyncio.sleep(2.5)

        conn = get_db()
        c = conn.cursor()

        if res == "win":
            win_amount = bet * 2
            c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (win_amount, user.id))
            conn.commit()
            conn.close()
            final_str = f"🎉 **ПОБЕДА!** Бот бросил {bot_val}, а за вас выпало **{player_val}**!\nВы выиграли **{win_amount} RPLCoin**!"
        elif res == "lose":
            conn.close()
            final_str = f"❌ **ПОРАЖЕНИЕ!** Бот бросил {bot_val}, а за вас выпало **{player_val}**.\nВы потеряли ставку **{bet} RPLCoin**."
        else:
            c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, user.id))
            conn.commit()
            conn.close()
            final_str = f"🤝 **НИЧЬЯ!** У вас и у бота выпало по **{bot_val}**.\nСтавка возвращена на баланс."

        await update.message.reply_text(final_str, parse_mode="Markdown")
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Введите ставку числом!", reply_markup=bet_cancel_keyboard())
        return WAITING_DICE_BET

async def checkprofile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    args = context.args
    if not args:
        await update.message.reply_text("🔍 **Введите команду с указанием ID или username игрока:**\nПример: `/checkprofile @username` или `/checkprofile 123456789`", parse_mode="Markdown")
        return

    target_str = args[0].replace("@", "")
    conn = get_db()
    c = conn.cursor()

    if target_str.isdigit():
        c.execute("SELECT * FROM users WHERE user_id = %s", (int(target_str),))
    else:
        c.execute("SELECT * FROM users WHERE username = %s", (target_str,))

    target_user = c.fetchone()
    if not target_user:
        conn.close()
        await update.message.reply_text("❌ Пользователь не найден в базе данных!")
        return

    target_id = target_user['user_id']
    c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (target_id,))
    roster = c.fetchone()

    roster_info = {}
    positions = ["goalie", "skater1", "skater2", "skater3", "skater4"]
    total_ovr = 0
    count_filled = 0

    if roster:
        for pos in positions:
            card_id = roster[f"{pos}_id"]
            if card_id:
                c.execute("SELECT nickname, ovr, position, rarity FROM cards WHERE id = %s", (card_id,))
                cd = c.fetchone()
                if cd:
                    roster_info[pos] = f"**{cd['nickname']}** ({cd['ovr']} OVR)"
                    total_ovr += cd['ovr']
                    count_filled += 1
                else:
                    roster_info[pos] = "❌ Не выбран"
            else:
                roster_info[pos] = "❌ Не выбран"
    else:
        for pos in positions:
            roster_info[pos] = "❌ Не выбран"

    c.execute('''
        SELECT c.nickname, c.ovr, c.position 
        FROM user_cards uc JOIN cards c ON uc.card_id = c.id 
        WHERE uc.user_id = %s AND c.position = 'Skater' AND uc.count > 0 
        ORDER BY c.ovr DESC LIMIT 1
    ''', (target_id,))
    best_skater = c.fetchone()

    c.execute('''
        SELECT c.nickname, c.ovr, c.position 
        FROM user_cards uc JOIN cards c ON uc.card_id = c.id 
        WHERE uc.user_id = %s AND c.position = 'Goalie' AND uc.count > 0 
        ORDER BY c.ovr DESC LIMIT 1
    ''', (target_id,))
    best_goalie = c.fetchone()
    conn.close()

    avg_ovr = round(total_ovr / 5, 1) if count_filled == 5 else 0
    best_skater_str = f"**{best_skater['nickname']}** ({best_skater['ovr']} OVR)" if best_skater else "Отсутствует"
    best_goalie_str = f"**{best_goalie['nickname']}** ({best_goalie['ovr']} OVR)" if best_goalie else "Отсутствует"

    text = (
        f"🏒 **Профиль игрока {target_user['first_name'] or target_user['username']}:**\n\n"
        f"🛡 Команда: {target_user['custom_team_emoji']} **{target_user['custom_team_name']}** ({target_user['custom_team_country']})\n"
        f"💳 Баланс: **{target_user['balance']} RPLCoin**\n"
        f"🏆 Рейтинг MMR: **{target_user['mmr']}**\n"
        f"⭐ Средний OVR Состава: **{avg_ovr if avg_ovr > 0 else 'Состав не собран'}**\n\n"
        f"📊 **Статистика матчей:**\n"
        f"🏒 Матчи: **{target_user['matches_played']}**\n"
        f"🏆 Победы: **{target_user['matches_won']}**\n"
        f"❌ Поражения: **{target_user['matches_lost']}**\n"
        f"⚽️ Голы: **{target_user['goals_scored']}**\n"
        f"🥅 Пропущено: **{target_user['goals_conceded']}**\n\n"
        f"🏒 Лучший Skater: {best_skater_str}\n"
        f"🧤 Лучший Goalie: {best_goalie_str}\n\n"
        f"📋 **Текущий Состав:**\n"
        f"🧤 Вратарь: {roster_info.get('goalie')}\n"
        f"🏒 Полевой 1: {roster_info.get('skater1')}\n"
        f"🏒 Полевой 2: {roster_info.get('skater2')}\n"
        f"🏒 Полевой 3: {roster_info.get('skater3')}\n"
        f"🏒 Полевой 4: {roster_info.get('skater4')}\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("💬 Написать в ЛС", url=f"https://t.me/{target_user['username']}" if target_user['username'] else f"tg://user?id={target_id}")],
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_profile")]
    ])

    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ==================== ОБНОВЛЁННАЯ ФУНКЦИЯ rplcards_command (ПАТЧ) ====================
async def rplcards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    u_data = get_or_create_user(user.id, user.username, user.first_name)
    now = datetime.now()
    
    last_claim = u_data.get('last_card_claim')
    cooldown_reset = u_data.get('free_card_cooldown_reset_until')
    bypassed = False
    if cooldown_reset:
        if isinstance(cooldown_reset, str):
            cooldown_reset = datetime.fromisoformat(cooldown_reset)
        if now < cooldown_reset:
            bypassed = True

    if not bypassed and last_claim:
        if isinstance(last_claim, str):
            last_claim = datetime.fromisoformat(last_claim)
        if now < last_claim + timedelta(hours=8):
            wait = (last_claim + timedelta(hours=8)) - now
            hours, rem = divmod(wait.seconds, 3600)
            minutes = rem // 60
            await update.message.reply_text(f"⏳ Бесплатную карточку можно получать раз в **8 часов**!\nПодожди ещё: **{hours} ч {minutes} мин**", parse_mode="Markdown")
            return

    temp_msg = await update.message.reply_text("⏳ **Идет открытие карточки...**", parse_mode="Markdown")
    await asyncio.sleep(3)

    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=temp_msg.message_id)
    except Exception:
        pass

    rarity = random.choices(
        ["Редкая", "Очень редкая", "Эпическая", "Мифическая", "Легендарная"],
        weights=[50, 28, 14, 6, 2], k=1
    )[0]

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT c.*, col.name as collection_name, t.name as team_name, t.emoji as team_emoji
        FROM cards c
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN card_teams t ON c.team_id = t.id
        WHERE c.rarity = %s
    ''', (rarity,))
    cards = c.fetchall()

    if not cards:
        c.execute('''
            SELECT c.*, col.name as collection_name, t.name as team_name, t.emoji as team_emoji
            FROM cards c
            JOIN collections col ON c.collection_id = col.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE c.rarity != 'Секретная'
        ''')
        cards = c.fetchall()

    if not cards:
        conn.close()
        await update.message.reply_text("📭 В базе пока нет карточек! Администратор скоро их добавит.")
        return

    card = choose_new_card_strict(c, user.id, cards)

    if not card:
        c.execute('''
            SELECT c.*, col.name as collection_name, t.name as team_name, t.emoji as team_emoji
            FROM cards c
            JOIN collections col ON c.collection_id = col.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE c.rarity != 'Секретная'
        ''')
        all_non_secret = c.fetchall()
        card = choose_new_card_strict(c, user.id, all_non_secret)

    if not card:
        if bypassed:
            c.execute("UPDATE users SET free_card_cooldown_reset_until = NULL, balance = balance + 3000 WHERE user_id = %s", (user.id,))
        else:
            c.execute("UPDATE users SET last_card_claim = %s, balance = balance + 3000 WHERE user_id = %s", (now, user.id))
        conn.commit()
        conn.close()
        await update.message.reply_text(
            "🎉 **Невероятно!** У вас уже есть все доступные карточки в игре, поэтому вместо дубликата вам начислено **3 000 RPLCoin**!",
            parse_mode="Markdown"
        )
        return

    card_id = card['id']
    c.execute('''
        INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
        ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
    ''', (user.id, card_id))
    
    # === НАЧИСЛЕНИЕ XP ЗА КАРТУ (ПАТЧ) ===
    xp_reward = XP_FOR_CARD_RARITY.get(card['rarity'], 0)
    add_experience(c, user.id, xp_reward)
    
    if bypassed:
        c.execute("UPDATE users SET free_card_cooldown_reset_until = NULL WHERE user_id = %s", (user.id,))
    else:
        c.execute("UPDATE users SET last_card_claim = %s WHERE user_id = %s", (now, user.id))
        
    conn.commit()
    conn.close()

    team_str = f"{card['team_emoji'] or '🏒'} {card['team_name']}" if card['team_name'] else "Без команды"
    caption = (
        f"🔥 **Вам выпала карточка!**\n\n"
        f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ 👤 {card['nickname']}\n"
        f"┃ 📁 Коллекция: {card['collection_name']}\n"
        f"┃ 🏒 {card['position']}\n"
        f"┃ ⭐ {card['ovr']} OVR\n"
        f"┃ {team_str}\n"
        f"┃ 🌍 {card['country']}\n"
        f"┃ ✨ {card['rarity']}\n"
        f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
        f"✨ Опыт за карту: +{xp_reward} XP"
    )

    if card['image_id']:
        try:
            await update.message.reply_photo(photo=card['image_id'], caption=caption, parse_mode="Markdown")
            return
        except Exception:
            pass
    await update.message.reply_text(caption, parse_mode="Markdown")

async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    await show_inventory(update, context)

async def show_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT uc.count, c.*, col.name as col_name, t.name as team_name, t.emoji as team_emoji
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN card_teams t ON c.team_id = t.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY col.name, c.ovr DESC
    ''', (user.id,))
    user_cards = c.fetchall()
    conn.close()

    text = "🎒 **Ваш Инвентарь Карточек:**\n\n"
    buttons = []

    if not user_cards:
        text += "У вас пока нет карточек! Получите бесплатную или купите пак в /shop."
    else:
        mythic_counts = {}
        for uc in user_cards:
            t_str = f"{uc['team_emoji']} {uc['team_name']}" if uc['team_name'] else ""
            text += f"ID `{uc['id']}` | **{uc['nickname']}** ({uc['position']}, {uc['ovr']} OVR) — `x{uc['count']}` [{uc['rarity']}] | 📁 {uc['col_name']} {t_str}\n"
            
            if uc['rarity'] == 'Мифическая':
                col_id = uc['collection_id']
                mythic_counts[col_id] = mythic_counts.get(col_id, 0) + uc['count']

        for col_id, m_count in mythic_counts.items():
            if m_count >= 5:
                conn = get_db()
                c = conn.cursor()
                c.execute("SELECT name FROM collections WHERE id = %s", (col_id,))
                col_row = c.fetchone()
                conn.close()
                col_name = col_row['name'] if col_row else "Коллекция"
                buttons.append([InlineKeyboardButton(f"🔨 Скрафтить Легендарную ({col_name})", callback_data=f"craft_leg_{col_id}")])

        buttons.append([InlineKeyboardButton("🏷 Выставить на Рынок", callback_data="market_list_menu")])
        buttons.append([InlineKeyboardButton("💰 Продать карточки (системе)", callback_data="sell_menu")])

    buttons.append([InlineKeyboardButton("🔄 Обновить", callback_data="refresh_inv")])
    markup = InlineKeyboardMarkup(buttons)

    if query:
        await query.answer()
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            await query.message.delete()
            await context.bot.send_message(user.id, text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def show_sell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT uc.count, c.*
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr DESC
    ''', (user.id,))
    user_cards = c.fetchall()
    conn.close()

    if not user_cards:
        await query.answer("У вас нет карточек для продажи!", show_alert=True)
        return

    text = "💰 **Продажа карточек системе:**\nНажмите на карточку, чтобы продать 1 шт.\n\n"
    buttons = []

    for uc in user_cards:
        price = SELL_PRICES.get(uc['rarity'], 300)
        btn_text = f"Продать {uc['nickname']} ({uc['ovr']} OVR) — {price} RPLCoin"
        buttons.append([InlineKeyboardButton(btn_text, callback_data=f"do_sell_{uc['id']}")])

    buttons.append([InlineKeyboardButton("🔙 Назад в инвентарь", callback_data="refresh_inv")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def inventory_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "refresh_inv":
        await show_inventory(update, context, edit=True)
    elif data == "sell_menu":
        await show_sell_menu(update, context)
    elif data.startswith("do_sell_"):
        card_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()

        c.execute('''
            SELECT uc.count, c.rarity, c.nickname 
            FROM user_cards uc 
            JOIN cards c ON uc.card_id = c.id 
            WHERE uc.user_id = %s AND uc.card_id = %s AND uc.count > 0
        ''', (user.id, card_id))
        row = c.fetchone()

        if not row:
            conn.close()
            await query.answer("❌ У вас больше нет этой карточки!", show_alert=True)
            await show_sell_menu(update, context)
            return

        price = SELL_PRICES.get(row['rarity'], 300)
        c.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (user.id, card_id))
        c.execute("DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0", (user.id, card_id))
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (price, user.id))

        c.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user.id, card_id))
        rem = c.fetchone()
        if not rem or rem['count'] <= 0:
            c.execute('''
                UPDATE user_rosters SET
                    goalie_id = CASE WHEN goalie_id = %s THEN NULL ELSE goalie_id END,
                    skater1_id = CASE WHEN skater1_id = %s THEN NULL ELSE skater1_id END,
                    skater2_id = CASE WHEN skater2_id = %s THEN NULL ELSE skater2_id END,
                    skater3_id = CASE WHEN skater3_id = %s THEN NULL ELSE skater3_id END,
                    skater4_id = CASE WHEN skater4_id = %s THEN NULL ELSE skater4_id END
                WHERE user_id = %s
            ''', (card_id, card_id, card_id, card_id, card_id, user.id))

        conn.commit()
        conn.close()

        await query.answer(f"✅ Карточка {row['nickname']} продана за {price} RPLCoin!", show_alert=True)
        await show_sell_menu(update, context)

    elif data.startswith("craft_leg_"):
        col_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            SELECT uc.card_id, uc.count 
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            WHERE uc.user_id = %s AND c.collection_id = %s AND c.rarity = 'Мифическая' AND uc.count > 0
        ''', (user.id, col_id))
        m_cards = c.fetchall()

        total_mythic = sum(m['count'] for m in m_cards)
        if total_mythic < 5:
            conn.close()
            await query.answer("❌ Нужно ровно 5 мифических карточек этой коллекции!", show_alert=True)
            return

        c.execute("SELECT * FROM cards WHERE collection_id = %s AND rarity = 'Легендарная' LIMIT 1", (col_id,))
        leg_card = c.fetchone()

        if not leg_card:
            conn.close()
            await query.answer("❌ В этой коллекции ещё нет Легендарной карточки!", show_alert=True)
            return

        needed = 5
        for m in m_cards:
            take = min(m['count'], needed)
            c.execute("UPDATE user_cards SET count = count - %s WHERE user_id = %s AND card_id = %s", (take, user.id, m['card_id']))
            needed -= take
            if needed <= 0:
                break

        c.execute("DELETE FROM user_cards WHERE count <= 0")
        c.execute('''
            INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
        ''', (user.id, leg_card['id']))

        conn.commit()
        conn.close()

        await query.answer("🎉 Вы успешно скрафтили Легендарную карточку!", show_alert=True)
        await show_inventory(update, context, edit=True)

async def cardshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    await show_market(update, context)

async def show_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT m.id as market_id, m.price, m.seller_id, c.id as card_id, c.nickname, c.position, c.ovr, c.rarity, u.username, u.first_name
        FROM market m
        JOIN cards c ON m.card_id = c.id
        JOIN users u ON m.seller_id = u.user_id
        ORDER BY m.id DESC
        LIMIT 25
    ''')
    items = c.fetchall()

    c.execute("SELECT COUNT(*) as cnt FROM market WHERE seller_id = %s", (user.id,))
    my_cnt = c.fetchone()['cnt']
    conn.close()

    text = "🛒 **ТОРГОВАЯ ПЛОЩАДКА (РЫНОК):**\nЗдесь игроки продают и покупают карточки друг у друга!\n\n"
    buttons = []

    if not items:
        text += "📭 На рынке сейчас нет выставленных лотов."
    else:
        for item in items:
            seller_name = f"@{item['username']}" if item['username'] else item['first_name']
            safe_seller = seller_name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            safe_nick = item['nickname'].replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            text += f"🏷 **#{item['market_id']}** | **{safe_nick}** ({item['position']}, {item['ovr']} OVR) [{item['rarity']}] — **{item['price']} RPLCoin** (Продавец: {safe_seller})\n"
            if item['seller_id'] != user.id:
                buttons.append([InlineKeyboardButton(f"Купить #{item['market_id']} ({item['nickname']}) - {item['price']} RPL", callback_data=f"buy_market_{item['market_id']}")])

    nav_btns = []
    if my_cnt > 0:
        nav_btns.append(InlineKeyboardButton(f"📦 Мои лоты ({my_cnt})", callback_data="my_market_items"))
    nav_btns.append(InlineKeyboardButton("🔄 Обновить", callback_data="refresh_market"))
    buttons.append(nav_btns)

    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.answer()
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            await query.message.delete()
            await context.bot.send_message(user.id, text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def show_my_market_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT m.id as market_id, m.price, c.nickname, c.position, c.ovr, c.rarity
        FROM market m
        JOIN cards c ON m.card_id = c.id
        WHERE m.seller_id = %s
        ORDER BY m.id DESC
    ''', (user.id,))
    my_items = c.fetchall()
    conn.close()

    text = "📦 **Ваши выставленные карточки на рынке:**\n\n"
    buttons = []

    if not my_items:
        text += "У вас нет активных объявлений на рынке."
    else:
        for item in my_items:
            text += f"🏷 **#{item['market_id']}** | **{item['nickname']}** ({item['ovr']} OVR) — `{item['price']} RPLCoin`\n"
            buttons.append([InlineKeyboardButton(f"❌ Снять #{item['market_id']} ({item['nickname']})", callback_data=f"cancel_market_{item['market_id']}")])

    buttons.append([InlineKeyboardButton("🔙 Назад на рынок", callback_data="refresh_market")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def market_start_list_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute('''
        SELECT uc.count, c.id, c.nickname, c.ovr, c.position, c.rarity
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr DESC
    ''', (user.id,))
    user_cards = c.fetchall()
    conn.close()

    if not user_cards:
        await query.answer("У вас нет карточек в инвентаре!", show_alert=True)
        return

    text = "🏷 **Выставить карточку на Торговую площадку:**\nВыберите карточку, которую хотите выставить на продажу:"
    buttons = []
    for uc in user_cards:
        buttons.append([InlineKeyboardButton(f"{uc['nickname']} ({uc['ovr']} OVR) - x{uc['count']}", callback_data=f"select_mcard_{uc['id']}")])

    buttons.append([InlineKeyboardButton("🔙 Назад в инвентарь", callback_data="refresh_inv")])
    await query.message.edit_text(text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

async def market_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "refresh_market":
        await show_market(update, context)
    elif data == "my_market_items":
        await show_my_market_items(update, context)
    elif data == "market_list_menu":
        await market_start_list_card(update, context)
    elif data.startswith("select_mcard_"):
        card_id = int(data.split("_")[2])
        context.user_data["m_card_id"] = card_id
        await query.message.reply_text("💲 **Введите цену продажи (в RPLCoin, максимум 999 999):**\nНапример: `1500`", parse_mode="Markdown")
        return WAITING_MARKET_PRICE_INPUT
    elif data.startswith("cancel_market_"):
        market_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM market WHERE id = %s AND seller_id = %s", (market_id, user.id))
        item = c.fetchone()

        if not item:
            conn.close()
            await query.answer("❌ Лот не найден или уже продан!", show_alert=True)
            await show_my_market_items(update, context)
            return

        c.execute('''
            INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
        ''', (user.id, item['card_id']))
        c.execute("DELETE FROM market WHERE id = %s", (market_id,))

        conn.commit()
        conn.close()

        await query.answer("✅ Карточка снята с продажи и возвращена в инвентарь!", show_alert=True)
        await show_my_market_items(update, context)

    elif data.startswith("buy_market_"):
        market_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT * FROM market WHERE id = %s", (market_id,))
        item = c.fetchone()

        if not item:
            conn.close()
            await query.answer("❌ Этот лот уже продан или снят!", show_alert=True)
            await show_market(update, context)
            return

        if item['seller_id'] == user.id:
            conn.close()
            await query.answer("❌ Вы не можете купить собственный лот!", show_alert=True)
            return

        c.execute("SELECT balance, discount_percent FROM users WHERE user_id = %s", (user.id,))
        u_info = c.fetchone()
        buyer_bal = u_info['balance']
        discount = u_info['discount_percent']

        final_price = item['price']
        if discount > 0:
            final_price = int(item['price'] * (100 - discount) / 100)

        if buyer_bal < final_price:
            conn.close()
            await query.answer(f"❌ Недостаточно средств! Нужно: {final_price} RPL", show_alert=True)
            return

        c.execute("UPDATE users SET balance = balance - %s, discount_percent = 0 WHERE user_id = %s", (final_price, user.id))
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (item['price'], item['seller_id']))

        c.execute('''
            INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
        ''', (user.id, item['card_id']))
        c.execute("DELETE FROM market WHERE id = %s", (market_id,))

        conn.commit()
        conn.close()

        try:
            await context.bot.send_message(chat_id=item['seller_id'], text=f"🎉 Ваш лот на рынке куплен! Зачислено **{item['price']} RPLCoin**.", parse_mode="Markdown")
        except Exception:
            pass

        await query.answer("🎉 Вы успешно купили карточку с рынка!", show_alert=True)
        await show_market(update, context)

async def execute_market_list_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text.strip())
        if price <= 0 or price > 999999:
            await update.message.reply_text("❌ Цена должна быть от 1 до 999 999 RPLCoin! Попробуйте снова:")
            return WAITING_MARKET_PRICE_INPUT

        card_id = context.user_data.get("m_card_id")
        user = update.effective_user

        conn = get_db()
        c = conn.cursor()

        c.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s AND count > 0", (user.id, card_id))
        row = c.fetchone()

        if not row:
            conn.close()
            await update.message.reply_text("❌ У вас больше нет этой карточки!")
            return ConversationHandler.END

        c.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (user.id, card_id))
        c.execute("DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0", (user.id, card_id))

        c.execute("SELECT count FROM user_cards WHERE user_id = %s AND card_id = %s", (user.id, card_id))
        rem = c.fetchone()
        if not rem or rem['count'] <= 0:
            c.execute('''
                UPDATE user_rosters SET
                    goalie_id = CASE WHEN goalie_id = %s THEN NULL ELSE goalie_id END,
                    skater1_id = CASE WHEN skater1_id = %s THEN NULL ELSE skater1_id END,
                    skater2_id = CASE WHEN skater2_id = %s THEN NULL ELSE skater2_id END,
                    skater3_id = CASE WHEN skater3_id = %s THEN NULL ELSE skater3_id END,
                    skater4_id = CASE WHEN skater4_id = %s THEN NULL ELSE skater4_id END
                WHERE user_id = %s
            ''', (card_id, card_id, card_id, card_id, card_id, user.id))

        c.execute("INSERT INTO market (seller_id, card_id, price) VALUES (%s, %s, %s)", (user.id, card_id, price))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ **Карточка успешно выставлена за {price} RPLCoin на Торговую площадку!**", parse_mode="Markdown")
        await show_market(update, context)
        return ConversationHandler.END

    except ValueError:
        await update.message.reply_text("❌ Введите цену целым числом (до 999 999):")
        return WAITING_MARKET_PRICE_INPUT

active_trades = {}

async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    args = context.args

    if not args:
        await update.message.reply_text("🤝 **Введи команду с указанием никнейма или ID:**\nПример: `/trade @username` или `/trade 123456789`", parse_mode="Markdown")
        return

    target_str = args[0].replace("@", "")
    conn = get_db()
    c = conn.cursor()

    if target_str.isdigit():
        c.execute("SELECT * FROM users WHERE user_id = %s", (int(target_str),))
    else:
        c.execute("SELECT * FROM users WHERE username = %s", (target_str,))

    target_user = c.fetchone()
    conn.close()

    if not target_user:
        await update.message.reply_text("❌ Игрок не найден в базе данных бота!")
        return

    if target_user['user_id'] == user.id:
        await update.message.reply_text("❌ Вы не можете отправить предложение трейда самому себе!")
        return

    target_id = target_user['user_id']

    for tid, tdata in active_trades.items():
        if user.id in (tdata['p1'], tdata['p2']) or target_id in (tdata['p1'], tdata['p2']):
            await update.message.reply_text("❌ Один из игроков уже находится в активном трейде!")
            return

    trade_id = f"{user.id}_{target_id}_{int(time.time())}"
    active_trades[trade_id] = {
        "p1": user.id, "p2": target_id,
        "p1_cards": [], "p2_cards": [],
        "p1_money": 0, "p2_money": 0,
        "p1_ready": False, "p2_ready": False,
        "msgs": {}
    }

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Принять Трейд", callback_data=f"accept_trade_{trade_id}")],
        [InlineKeyboardButton("❌ Отклонить", callback_data=f"decline_trade_{trade_id}")]
    ])

    await update.message.reply_text(f"🤝 Вы отправили предложение обмена игроку **{target_user['first_name']}**! Ожидание ответа...", parse_mode="Markdown")

    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=f"🤝 **Игрок {user.first_name} предлагает вам обмен (трейд)!**\nХотите принять предложение?",
            reply_markup=kb,
            parse_mode="Markdown"
        )
    except Exception:
        await update.message.reply_text("❌ Не удалось отправить уведомление игроку (возможно, бот заблокирован им).")

async def tradecancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    found_tid = None
    for tid, tdata in active_trades.items():
        if user.id in (tdata['p1'], tdata['p2']):
            found_tid = tid
            break

    if not found_tid:
        await update.message.reply_text("❌ У вас нет активных трейдов для отмены.")
        return

    tdata = active_trades.pop(found_tid)
    for uid, mid in tdata['msgs'].items():
        try:
            await context.bot.edit_message_text(chat_id=uid, message_id=mid, text="🚫 **Трейд отменен командой /tradecancel.**", parse_mode="Markdown")
        except Exception:
            pass
    await update.message.reply_text("✅ Трейд успешно отменен.", parse_mode="Markdown")

async def render_trade_text(tdata):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT first_name, username FROM users WHERE user_id = %s", (tdata['p1'],))
    u1 = c.fetchone()
    c.execute("SELECT first_name, username FROM users WHERE user_id = %s", (tdata['p2'],))
    u2 = c.fetchone()

    name1 = u1['first_name'] if u1 else str(tdata['p1'])
    name2 = u2['first_name'] if u2 else str(tdata['p2'])

    p1_cards_str = ""
    if tdata['p1_cards']:
        c.execute("SELECT id, nickname, ovr, position FROM cards WHERE id IN %s", (tuple(tdata['p1_cards']),))
        cds = c.fetchall()
        for cd in cds:
            p1_cards_str += f"  • {cd['nickname']} ({cd['ovr']} OVR)\n"
    else:
        p1_cards_str = "  *(карточки не выбраны)*\n"

    p2_cards_str = ""
    if tdata['p2_cards']:
        c.execute("SELECT id, nickname, ovr, position FROM cards WHERE id IN %s", (tuple(tdata['p2_cards']),))
        cds = c.fetchall()
        for cd in cds:
            p2_cards_str += f"  • {cd['nickname']} ({cd['ovr']} OVR)\n"
    else:
        p2_cards_str = "  *(карточки не выбраны)*\n"

    conn.close()

    r1_status = "✅ ГОТОВ" if tdata['p1_ready'] else "⏳ Выбирает..."
    r2_status = "✅ ГОТОВ" if tdata['p2_ready'] else "⏳ Выбирает..."

    text = (
        f"🤝 **ОКНО ОБМЕНА (ТРЕЙД)**\n\n"
        f"🔴 **Предложение {name1}** [{r1_status}]:\n"
        f"💳 RPLCoin: **{tdata['p1_money']}**\n"
        f"🃏 Карточки:\n{p1_cards_str}\n"
        f"────────────────────\n"
        f"🔵 **Предложение {name2}** [{r2_status}]:\n"
        f"💳 RPLCoin: **{tdata['p2_money']}**\n"
        f"🃏 Карточки:\n{p2_cards_str}\n"
    )
    return text

async def update_trade_views(context, trade_id):
    if trade_id not in active_trades:
        return
    tdata = active_trades[trade_id]

    p1, p2 = tdata['p1'], tdata['p2']
    m1, m2 = tdata['msgs'].get(p1), tdata['msgs'].get(p2)

    txt = await render_trade_text(tdata)

    p1_ready_btn = InlineKeyboardButton("❌ Снять готовность" if tdata['p1_ready'] else "✅ ГОТОВ", callback_data=f"tr_ready_{trade_id}")
    kb1 = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить карту", callback_data=f"tr_addcard_{trade_id}"), InlineKeyboardButton("💵 RPLCoin", callback_data=f"tr_addmoney_{trade_id}")],
        [InlineKeyboardButton("🗑 Очистить", callback_data=f"tr_clear_{trade_id}"), p1_ready_btn],
        [InlineKeyboardButton("🚫 Отменить Трейд", callback_data=f"tr_cancel_{trade_id}")]
    ])

    p2_ready_btn = InlineKeyboardButton("❌ Снять готовность" if tdata['p2_ready'] else "✅ ГОТОВ", callback_data=f"tr_ready_{trade_id}")
    kb2 = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить карту", callback_data=f"tr_addcard_{trade_id}"), InlineKeyboardButton("💵 RPLCoin", callback_data=f"tr_addmoney_{trade_id}")],
        [InlineKeyboardButton("🗑 Очистить", callback_data=f"tr_clear_{trade_id}"), p2_ready_btn],
        [InlineKeyboardButton("🚫 Отменить Трейд", callback_data=f"tr_cancel_{trade_id}")]
    ])

    if m1:
        try:
            await context.bot.edit_message_text(chat_id=p1, message_id=m1, text=txt, reply_markup=kb1, parse_mode="Markdown")
        except Exception:
            pass
    if m2:
        try:
            await context.bot.edit_message_text(chat_id=p2, message_id=m2, text=txt, reply_markup=kb2, parse_mode="Markdown")
        except Exception:
            pass

async def trade_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("accept_trade_"):
        trade_id = data.replace("accept_trade_", "")
        if trade_id not in active_trades:
            await query.answer("❌ Этот трейд больше неактивен!", show_alert=True)
            return

        tdata = active_trades[trade_id]
        if user.id != tdata['p2']:
            await query.answer("❌ Это предложение не вам!", show_alert=True)
            return

        m1 = await context.bot.send_message(chat_id=tdata['p1'], text="🤝 **Трейд принят! Загрузка...**", parse_mode="Markdown")
        m2 = await query.message.edit_text("🤝 **Трейд начат! Загрузка...**", parse_mode="Markdown")

        tdata["msgs"][tdata['p1']] = m1.message_id
        tdata["msgs"][tdata['p2']] = m2.message_id

        await update_trade_views(context, trade_id)

    elif data.startswith("decline_trade_"):
        trade_id = data.replace("decline_trade_", "")
        tdata = active_trades.pop(trade_id, None)
        await query.edit_message_text("❌ Предложение трейда отклонено.")
        if tdata:
            try:
                await context.bot.send_message(chat_id=tdata['p1'], text="❌ Игрок отклонил ваше предложение обмена.")
            except Exception:
                pass

    elif data.startswith("tr_"):
        parts = data.split("_")
        action = parts[1]
        trade_id = "_".join(parts[2:])

        if trade_id not in active_trades:
            await query.answer("❌ Трейд не найден или завершен!", show_alert=True)
            return

        tdata = active_trades[trade_id]
        if user.id not in (tdata['p1'], tdata['p2']):
            await query.answer("❌ Вы не участник трейда!", show_alert=True)
            return

        is_p1 = (user.id == tdata['p1'])

        if action == "cancel":
            active_trades.pop(trade_id, None)
            for uid, mid in tdata['msgs'].items():
                try:
                    await context.bot.edit_message_text(chat_id=uid, message_id=mid, text="🚫 **Трейд отменен одной из сторон.**", parse_mode="Markdown")
                except Exception:
                    pass
            return

        elif action == "clear":
            if is_p1:
                tdata['p1_cards'] = []
                tdata['p1_money'] = 0
            else:
                tdata['p2_cards'] = []
                tdata['p2_money'] = 0
            tdata['p1_ready'] = False
            tdata['p2_ready'] = False
            await query.answer("Очищено")
            await update_trade_views(context, trade_id)

        elif action == "addmoney":
            context.user_data["active_trade_id"] = trade_id
            await query.message.reply_text("💵 **Введите сумму RPLCoin для трейда:**", parse_mode="Markdown")
            return WAITING_TRADE_MONEY

        elif action == "addcard":
            conn = get_db()
            c = conn.cursor()
            c.execute('''
                SELECT uc.card_id, uc.count, c.nickname, c.ovr, c.position
                FROM user_cards uc
                JOIN cards c ON uc.card_id = c.id
                WHERE uc.user_id = %s AND uc.count > 0
                ORDER BY c.ovr DESC
            ''', (user.id,))
            user_cards = c.fetchall()
            conn.close()

            if not user_cards:
                await query.answer("У вас нет карточек!", show_alert=True)
                return

            buttons = []
            curr_cards = tdata['p1_cards'] if is_p1 else tdata['p2_cards']
            for uc in user_cards:
                cnt_in_tr = curr_cards.count(uc['card_id'])
                if uc['count'] - cnt_in_tr > 0:
                    buttons.append([InlineKeyboardButton(f"{uc['nickname']} ({uc['ovr']} OVR)", callback_data=f"tr_putcard_{trade_id}_{uc['card_id']}")])

            buttons.append([InlineKeyboardButton("🔙 Назад", callback_data=f"tr_back_{trade_id}")])
            await query.edit_message_text("📋 **Выберите карточку для добавления:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

        elif action == "putcard":
            card_id = int(parts[3])
            tr_id = "_".join(parts[2:-1])
            tdata = active_trades.get(tr_id)
            if not tdata:
                return

            if is_p1:
                tdata['p1_cards'].append(card_id)
            else:
                tdata['p2_cards'].append(card_id)

            tdata['p1_ready'] = False
            tdata['p2_ready'] = False
            await update_trade_views(context, tr_id)

        elif action == "back":
            await update_trade_views(context, trade_id)

        elif action == "ready":
            if is_p1:
                tdata['p1_ready'] = not tdata['p1_ready']
            else:
                tdata['p2_ready'] = not tdata['p2_ready']

            await update_trade_views(context, trade_id)
            if tdata['p1_ready'] and tdata['p2_ready']:
                await execute_trade_finish(context, trade_id)

async def execute_trade_finish(context, trade_id):
    if trade_id not in active_trades:
        return
    tdata = active_trades.pop(trade_id)

    p1, p2 = tdata['p1'], tdata['p2']
    c1, c2 = tdata['p1_cards'], tdata['p2_cards']
    m1, m2 = tdata['p1_money'], tdata['p2_money']

    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT balance FROM users WHERE user_id = %s", (p1,))
    b1 = c.fetchone()['balance']
    c.execute("SELECT balance FROM users WHERE user_id = %s", (p2,))
    b2 = c.fetchone()['balance']

    if b1 < m1 or b2 < m2:
        conn.close()
        for uid, mid in tdata['msgs'].items():
            try:
                await context.bot.edit_message_text(chat_id=uid, message_id=mid, text="❌ **Ошибка трейда!** У кого-то недостаточно средств.")
            except Exception:
                pass
        return

    c.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (m1, m2, p1))
    c.execute("UPDATE users SET balance = balance - %s + %s WHERE user_id = %s", (m2, m1, p2))

    for card_id in c1:
        c.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (p1, card_id))
        c.execute("DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0", (p1, card_id))
        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (p2, card_id))

    for card_id in c2:
        c.execute("UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s", (p2, card_id))
        c.execute("DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0", (p2, card_id))
        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (p1, card_id))

    conn.commit()
    conn.close()

    for uid, mid in tdata['msgs'].items():
        try:
            await context.bot.edit_message_text(chat_id=uid, message_id=mid, text="🎉 **ОБМЕН УСПЕШНО ЗАВЕРШЕН!**", parse_mode="Markdown")
        except Exception:
            pass

async def execute_trade_money_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        if val < 0: val = 0

        user = update.effective_user
        trade_id = context.user_data.get("active_trade_id")

        if not trade_id or trade_id not in active_trades:
            await update.message.reply_text("❌ Трейд не активен!")
            return ConversationHandler.END

        tdata = active_trades[trade_id]
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        u_bal = c.fetchone()['balance']
        conn.close()

        if val > u_bal:
            await update.message.reply_text(f"❌ Недостаточно средств! Баланс: {u_bal}")
            return WAITING_TRADE_MONEY

        if user.id == tdata['p1']:
            tdata['p1_money'] = val
        else:
            tdata['p2_money'] = val

        tdata['p1_ready'] = False
        tdata['p2_ready'] = False

        await update.message.reply_text(f"✅ Сумма {val} RPL установлена.")
        await update_trade_views(context, trade_id)
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите сумму числом!")
        return WAITING_TRADE_MONEY

async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    if context.args:
        code = context.args[0].strip().upper()
        await process_promo_code(update, context, user.id, code)
        return
    await update.message.reply_text("🎟 **Введите ваш промокод:**", parse_mode="Markdown")
    return WAITING_PROMO_INPUT

async def promo_input_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user = update.effective_user
    await process_promo_code(update, context, user.id, code)
    return ConversationHandler.END

async def process_promo_code(update, context, user_id, code):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
    promo = c.fetchone()

    if not promo:
        conn.close()
        await update.message.reply_text("❌ Неверный промокод!")
        return

    c.execute("SELECT * FROM user_promocodes WHERE user_id = %s AND code = %s", (user_id, code))
    if c.fetchone():
        conn.close()
        await update.message.reply_text("❌ Вы уже активировали этот промокод!")
        return

    if promo['current_uses'] >= promo['max_uses']:
        conn.close()
        await update.message.reply_text("❌ Лимит активаций исчерпан!")
        return

    reward_msg = ""
    if promo['reward_type'] == 'money':
        c.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (promo['reward_value'], user_id))
        reward_msg = f"💳 **+{promo['reward_value']} RPLCoin**"
    elif promo['reward_type'] == 'card':
        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (user_id, promo['reward_value']))
        c.execute("SELECT nickname, ovr FROM cards WHERE id = %s", (promo['reward_value'],))
        cd = c.fetchone()
        cd_name = f"{cd['nickname']} ({cd['ovr']} OVR)" if cd else f"Карточка ID {promo['reward_value']}"
        reward_msg = f"🃏 **{cd_name}**"

    c.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = %s", (code,))
    c.execute("INSERT INTO user_promocodes (user_id, code) VALUES (%s, %s)", (user_id, code))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🎉 **Промокод активирован!**\nВы получили: {reward_msg}", parse_mode="Markdown")

async def admin_create_promo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎟 **Введите промокод (например `RPL2026`):**", parse_mode="Markdown")
    return ADD_PROMO_CODE

async def admin_promo_set_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_code"] = update.message.text.strip().upper()
    kb = [["💰 Деньги", "🃏 Карточка"]]
    await update.message.reply_text("🎁 Выберите тип награды:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADD_PROMO_TYPE

async def admin_promo_set_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    t_text = update.message.text.strip()
    r_type = "money" if "Деньги" in t_text else "card"
    context.user_data["p_reward_type"] = r_type
    if r_type == "money":
        await update.message.reply_text("💰 Введите сумму (RPLCoin):", reply_markup=ReplyKeyboardRemove())
    else:
        await update.message.reply_text("🃏 Введите ID карточки:", reply_markup=ReplyKeyboardRemove())
    return ADD_PROMO_VAL

async def admin_promo_set_val(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        val = int(update.message.text.strip())
        context.user_data["p_reward_val"] = val
        await update.message.reply_text("🔢 Введите лимит активаций:")
        return ADD_PROMO_LIMIT
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ADD_PROMO_VAL

async def admin_promo_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        limit = int(update.message.text.strip())
        code = context.user_data.get("p_code")
        r_type = context.user_data.get("p_reward_type")
        r_val = context.user_data.get("p_reward_val")

        conn = get_db()
        c = conn.cursor()
        c.execute('''
            INSERT INTO promo_codes (code, reward_type, reward_value, max_uses, current_uses)
            VALUES (%s, %s, %s, %s, 0)
            ON CONFLICT (code) DO UPDATE SET reward_type = EXCLUDED.reward_type, reward_value = EXCLUDED.reward_value, max_uses = EXCLUDED.max_uses
        ''', (code, r_type, r_val, limit))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Промокод `{code}` создан!", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
        return CARD_ADMIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ADD_PROMO_LIMIT

# ==================== ОБНОВЛЁННЫЙ ПРОФИЛЬ С XP (ПАТЧ) ====================
async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)
    await show_profile(update, context)

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user
    u_data = get_or_create_user(user.id, user.username, user.first_name)

    # Вычисляем уровень и прогресс XP
    level, current_xp, required_xp = get_level_and_progress(u_data.get("experience", 0))

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = c.fetchone()

    roster_info = {}
    positions = ["goalie", "skater1", "skater2", "skater3", "skater4"]
    total_ovr = 0
    count_filled = 0

    if roster:
        for pos in positions:
            card_id = roster[f"{pos}_id"]
            if card_id:
                c.execute("SELECT nickname, ovr, position, rarity FROM cards WHERE id = %s", (card_id,))
                cd = c.fetchone()
                if cd:
                    roster_info[pos] = f"**{cd['nickname']}** ({cd['ovr']} OVR)"
                    total_ovr += cd['ovr']
                    count_filled += 1
                else:
                    roster_info[pos] = "❌ Не выбран"
            else:
                roster_info[pos] = "❌ Не выбран"
    else:
        for pos in positions:
            roster_info[pos] = "❌ Не выбран"

    c.execute('''
        SELECT c.nickname, c.ovr, c.position 
        FROM user_cards uc JOIN cards c ON uc.card_id = c.id 
        WHERE uc.user_id = %s AND c.position = 'Skater' AND uc.count > 0 
        ORDER BY c.ovr DESC LIMIT 1
    ''', (user.id,))
    best_skater = c.fetchone()

    c.execute('''
        SELECT c.nickname, c.ovr, c.position 
        FROM user_cards uc JOIN cards c ON uc.card_id = c.id 
        WHERE uc.user_id = %s AND c.position = 'Goalie' AND uc.count > 0 
        ORDER BY c.ovr DESC LIMIT 1
    ''', (user.id,))
    best_goalie = c.fetchone()
    conn.close()

    avg_ovr = round(total_ovr / 5, 1) if count_filled == 5 else 0
    best_skater_str = f"**{best_skater['nickname']}** ({best_skater['ovr']} OVR)" if best_skater else "Отсутствует"
    best_goalie_str = f"**{best_goalie['nickname']}** ({best_goalie['ovr']} OVR)" if best_goalie else "Отсутствует"

    text = (
        f"🏒 **Профиль игрока {user.first_name}:**\n\n"
        f"🛡 Команда: {u_data['custom_team_emoji']} **{u_data['custom_team_name']}** ({u_data['custom_team_country']})\n"
        f"🏅 Уровень: **{level}**\n"
        f"✨ Опыт: **{current_xp}/{required_xp} XP**\n"
        f"💳 Баланс: **{u_data['balance']} RPLCoin**\n"
        f"🏆 Рейтинг MMR: **{u_data['mmr']}**\n"
        f"⭐ Средний OVR Состава: **{avg_ovr if avg_ovr > 0 else 'Состав не собран'}**\n\n"
        f"📊 **Статистика матчей:**\n"
        f"🏒 Матчи: **{u_data['matches_played']}**\n"
        f"🏆 Победы: **{u_data['matches_won']}**\n"
        f"❌ Поражения: **{u_data['matches_lost']}**\n"
        f"⚽️ Голы: **{u_data['goals_scored']}**\n"
        f"🥅 Пропущено: **{u_data['goals_conceded']}**\n\n"
        f"🏒 Лучший Skater: {best_skater_str}\n"
        f"🧤 Лучший Goalie: {best_goalie_str}\n\n"
        f"📋 **Текущий Состав:**\n"
        f"🧤 Вратарь: {roster_info.get('goalie')}\n"
        f"🏒 Полевой 1: {roster_info.get('skater1')}\n"
        f"🏒 Полевой 2: {roster_info.get('skater2')}\n"
        f"🏒 Полевой 3: {roster_info.get('skater3')}\n"
        f"🏒 Полевой 4: {roster_info.get('skater4')}\n"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛡 Настроить команду", callback_data="edit_custom_team")],
        [InlineKeyboardButton("⚙️ Изменить Состав", callback_data="edit_roster_menu")],
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_profile")]
    ])

    if query:
        await query.answer()
        try:
            await query.message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
        except Exception:
            await query.message.delete()
            await context.bot.send_message(user.id, text, reply_markup=kb, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")

async def profile_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "refresh_profile":
        await show_profile(update, context)
    elif data == "edit_custom_team":
        await query.message.reply_text("🛡 Введите название вашей команды (например: `Динамо Москва`):", parse_mode="Markdown")
        return WAITING_TEAM_NAME
    elif data == "edit_roster_menu":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🧤 Выбрать Вратаря", callback_data="set_pos_goalie")],
            [InlineKeyboardButton("🏒 Выбрать Полевого 1", callback_data="set_pos_skater1")],
            [InlineKeyboardButton("🏒 Выбрать Полевого 2", callback_data="set_pos_skater2")],
            [InlineKeyboardButton("🏒 Выбрать Полевого 3", callback_data="set_pos_skater3")],
            [InlineKeyboardButton("🏒 Выбрать Полевого 4", callback_data="set_pos_skater4")],
            [InlineKeyboardButton("🔙 Назад", callback_data="refresh_profile")]
        ])
        await query.edit_message_text("⚙️ **Выберите позицию:**", reply_markup=kb, parse_mode="Markdown")
    elif data.startswith("set_pos_"):
        pos_type = data.replace("set_pos_", "")
        conn = get_db()
        c = conn.cursor()
        needed_position = "Goalie" if pos_type == "goalie" else "Skater"
        c.execute('''
            SELECT c.id, c.nickname, c.ovr, c.rarity, t.emoji, t.name as team_name
            FROM user_cards uc
            JOIN cards c ON uc.card_id = c.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE uc.user_id = %s AND c.position = %s AND uc.count > 0
            ORDER BY c.ovr DESC
        ''', (user.id, needed_position))
        available = c.fetchall()
        conn.close()

        if not available:
            await query.answer(f"❌ Нет карточек на позицию {needed_position}!", show_alert=True)
            return

        buttons = []
        for card in available:
            buttons.append([InlineKeyboardButton(f"{card['nickname']} - {card['ovr']} OVR", callback_data=f"apply_card_{pos_type}_{card['id']}")])
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="edit_roster_menu")])
        await query.edit_message_text(f"📋 **Выберите карту для {pos_type.capitalize()}:**", reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown")

    elif data.startswith("apply_card_"):
        parts = data.split("_")
        pos_type = parts[2]
        card_id = int(parts[3])

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
        roster = c.fetchone()
        if not roster:
            c.execute("INSERT INTO user_rosters (user_id) VALUES (%s)", (user.id,))
            c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
            roster = c.fetchone()

        for p in ["goalie", "skater1", "skater2", "skater3", "skater4"]:
            if p != pos_type and roster[f"{p}_id"] == card_id:
                conn.close()
                await query.answer("❌ Эта карточка уже в составе на другой позиции!", show_alert=True)
                return

        c.execute(f"UPDATE user_rosters SET {pos_type}_id = %s WHERE user_id = %s", (card_id, user.id))
        conn.commit()
        conn.close()
        await query.answer("✅ Успешно!")
        await show_profile(update, context)

async def team_name_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["t_name"] = update.message.text.strip()
    kb = [COUNTRIES[i:i+3] for i in range(0, len(COUNTRIES), 3)]
    await update.message.reply_text("🌍 Выберите страну для вашей команды:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return WAITING_TEAM_COUNTRY

async def team_country_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["t_country"] = update.message.text.strip()
    await update.message.reply_text("🏒 Введите один эмодзи/смайлик для команды (например 🦅 или 🏒):", reply_markup=ReplyKeyboardRemove())
    return WAITING_TEAM_EMOJI

async def team_emoji_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emoji = update.message.text.strip()
    name = context.user_data.get("t_name")
    country = context.user_data.get("t_country")
    user = update.effective_user

    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET custom_team_name = %s, custom_team_country = %s, custom_team_emoji = %s WHERE user_id = %s",
              (name, country, emoji, user.id))
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Ваша команда {emoji} **{name}** ({country}) успешно создана и сохранена!", parse_mode="Markdown")
    await show_profile(update, context)
    return ConversationHandler.END

active_searches = {}
active_games = set()

def calc_goal_probabilities(p1_cards, p2_cards):
    p1_skater_ovr = sum(p1_cards[f"skater{i}"]["ovr"] for i in range(1, 5)) / 4.0
    p2_skater_ovr = sum(p2_cards[f"skater{i}"]["ovr"] for i in range(1, 5)) / 4.0
    g1_ovr = p1_cards["goalie"]["ovr"]
    g2_ovr = p2_cards["goalie"]["ovr"]

    p1_tot_ovr = (p1_skater_ovr * 4.0 + g1_ovr) / 5.0
    p2_tot_ovr = (p2_skater_ovr * 4.0 + g2_ovr) / 5.0

    diff1 = p1_skater_ovr - g2_ovr
    diff2 = p2_skater_ovr - g1_ovr

    prob_p1 = 0.12 * (1.8 ** (diff1 / 7.0)) if diff1 >= 0 else 0.12 * (0.5 ** (-diff1 / 7.0))
    prob_p2 = 0.12 * (1.8 ** (diff2 / 7.0)) if diff2 >= 0 else 0.12 * (0.5 ** (-diff2 / 7.0))

    tot_diff = p1_tot_ovr - p2_tot_ovr
    if tot_diff > 10:
        prob_p1 *= 1.5
        prob_p2 *= 0.3
    elif tot_diff < -10:
        prob_p1 *= 0.3
        prob_p2 *= 1.5

    return max(0.005, min(0.45, prob_p1)), max(0.005, min(0.45, prob_p2))

def calc_shootout_prob(skater_ovr, goalie_ovr):
    diff = skater_ovr - goalie_ovr
    prob = 0.35 * (1.6 ** (diff / 8.0)) if diff >= 0 else 0.35 * (0.5 ** (-diff / 8.0))
    return max(0.05, min(0.85, prob))

async def cardmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    u_data = get_or_create_user(user.id, user.username, user.first_name)

    if user.id in active_searches or user.id in active_games:
        await update.message.reply_text("🔎 Вы уже находитесь в поиске или играете матч!")
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = c.fetchone()
    conn.close()

    if not roster or not (roster['goalie_id'] and roster['skater1_id'] and roster['skater2_id'] and roster['skater3_id'] and roster['skater4_id']):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🎁 Получить стартовый набор карточек", callback_data="claim_freepack_btn")]
        ])
        await update.message.reply_text(
            "❌ **Состав не собран!** (Нужен 1 Вратарь + 4 Полевых).\nНажмите кнопку ниже для получения бесплатного набора:",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    if active_searches:
        other_user_id = next((uid for uid in active_searches.keys() if uid != user.id), None)
        if other_user_id:
            search_info = active_searches.pop(other_user_id)
            search_info["task"].cancel()

            p1_id = other_user_id
            p2_id = user.id
            p1_chat_id = search_info["chat_id"]
            p2_chat_id = chat_id
            p1_msg_id = search_info["msg_id"]

            try:
                await context.bot.edit_message_text(
                    chat_id=p1_chat_id,
                    message_id=p1_msg_id,
                    text=f"⚡️ **Соперник найден!** Игрок **{user.first_name}** присоединился. Начинаем матч...",
                    parse_mode="Markdown"
                )
            except Exception:
                pass

            msg_p2 = await update.message.reply_text(
                f"⚡️ **Соперник найден!** Начинается матч против **{search_info.get('first_name', 'Игрока')}**...",
                parse_mode="Markdown"
            )
            p2_msg_id = msg_p2.message_id

            asyncio.create_task(start_game_pvp(p1_id, p2_id, p1_chat_id, p2_chat_id, p1_msg_id, p2_msg_id, context))
            return

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⚔️ Принять Поиск", callback_data=f"accept_match_{user.id}")],
        [InlineKeyboardButton("❌ Отмена", callback_data=f"cancel_match_{user.id}")]
    ])

    msg = await update.message.reply_text(
        f"🏒 Игрок **{user.first_name}** ищет соперника для матча!\n"
        f"🛡 Команда: {u_data['custom_team_emoji']} **{u_data['custom_team_name']}** ({u_data['custom_team_country']})\n"
        f"🏆 MMR: **{u_data['mmr']}**",
        reply_markup=kb,
        parse_mode="Markdown"
    )

    active_searches[user.id] = {
        "chat_id": chat_id,
        "msg_id": msg.message_id,
        "username": user.username or "",
        "first_name": user.first_name or "Игрок",
        "start_time": time.time(),
        "task": asyncio.create_task(search_timeout_worker(user.id, context))
    }

async def search_timeout_worker(user_id, context):
    await asyncio.sleep(45)
    if user_id in active_searches:
        search_info = active_searches.pop(user_id)
        chat_id = search_info["chat_id"]
        msg_id = search_info["msg_id"]
        try:
            await context.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🤖 Соперник не найден за 45 сек.! Начинается матч против ИИ Бота...", parse_mode="Markdown")
        except Exception:
            pass
        await start_game_vs_ai(user_id, chat_id, msg_id, context)

async def match_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("cancel_match_"):
        host_id = int(data.split("_")[2])
        if user.id != host_id:
            await query.answer("❌ Только создатель поиска может отменить его!", show_alert=True)
            return
        if host_id in active_searches:
            s_info = active_searches.pop(host_id)
            s_info["task"].cancel()
            await query.edit_message_text("❌ Поиск матча отменен.")
        return

    elif data.startswith("accept_match_"):
        host_id = int(data.split("_")[2])
        if user.id == host_id:
            await query.answer("❌ Нельзя принять свой поиск!", show_alert=True)
            return
        if user.id in active_searches or user.id in active_games:
            await query.answer("❌ Вы уже в игре или в поиске!", show_alert=True)
            return
        if host_id not in active_searches:
            await query.answer("❌ Поиск уже неактуален!", show_alert=True)
            return

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
        roster = c.fetchone()
        conn.close()

        if not roster or not (roster['goalie_id'] and roster['skater1_id'] and roster['skater2_id'] and roster['skater3_id'] and roster['skater4_id']):
            await query.answer("❌ У вас не собран полный состав!", show_alert=True)
            return

        s_info = active_searches.pop(host_id)
        s_info["task"].cancel()
        get_or_create_user(user.id, user.username, user.first_name)
        await query.edit_message_text(f"⚔️ Игрок **{user.first_name}** принял вызов! Матч начинается...", parse_mode="Markdown")

        asyncio.create_task(start_game_pvp(host_id, user.id, s_info["chat_id"], query.message.chat_id, s_info["msg_id"], query.message.message_id, context))

async def broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, text):
    if p1_chat_id and p1_msg_id:
        try:
            await context.bot.edit_message_text(chat_id=p1_chat_id, message_id=p1_msg_id, text=text, parse_mode="Markdown")
        except Exception:
            pass
    if p2_chat_id and p2_msg_id and (p2_chat_id != p1_chat_id or p2_msg_id != p1_msg_id):
        try:
            await context.bot.edit_message_text(chat_id=p2_chat_id, message_id=p2_msg_id, text=text, parse_mode="Markdown")
        except Exception:
            pass

def format_cards_list(cards_dict):
    pos_labels = {
        "goalie": "🧤 Вратарь",
        "skater1": "🏒 Полевой 1",
        "skater2": "🏒 Полевой 2",
        "skater3": "🏒 Полевой 3",
        "skater4": "🏒 Полевой 4",
    }
    lines = []
    for k, v in cards_dict.items():
        label = pos_labels.get(k, "🏒")
        lines.append(f"  • {label}: **{v['nickname']}** ({v['ovr']} OVR)")
    return "\n".join(lines)

# ==================== ОБНОВЛЁННАЯ ФУНКЦИЯ start_game_pvp (ПАТЧ) ====================
async def start_game_pvp(p1_id, p2_id, p1_chat_id, p2_chat_id, p1_msg_id, p2_msg_id, context):
    active_games.add(p1_id)
    active_games.add(p2_id)
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = %s", (p1_id,))
        u1 = c.fetchone()
        c.execute("SELECT * FROM users WHERE user_id = %s", (p2_id,))
        u2 = c.fetchone()

        c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (p1_id,))
        r1 = c.fetchone()
        c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (p2_id,))
        r2 = c.fetchone()

        p1_cards = get_roster_cards(c, r1)
        p2_cards = get_roster_cards(c, r2)
        conn.close()

        p1_ovr = sum(c['ovr'] for c in p1_cards.values()) / 5.0
        p2_ovr = sum(c['ovr'] for c in p2_cards.values()) / 5.0

        name1 = u1['first_name'] or u1['username'] or str(p1_id)
        name2 = u2['first_name'] or u2['username'] or str(p2_id)

        team1_str = f"{u1['custom_team_emoji']} {u1['custom_team_name']} ({u1['custom_team_country']})"
        team2_str = f"{u2['custom_team_emoji']} {u2['custom_team_name']} ({u2['custom_team_country']})"

        roster1_text = format_cards_list(p1_cards)
        roster2_text = format_cards_list(p2_cards)

        header = (
            f"🏒 **МАТЧ НАЧАЛСЯ!**\n\n"
            f"🔴 **{name1}** | Команда: {team1_str}\n"
            f"⭐ Средний OVR: `{p1_ovr:.1f}` | MMR: `{u1['mmr']}`\n"
            f"📋 Состав:\n{roster1_text}\n\n"
            f" VS \n\n"
            f"🔵 **{name2}** | Команда: {team2_str}\n"
            f"⭐ Средний OVR: `{p2_ovr:.1f}` | MMR: `{u2['mmr']}`\n"
            f"📋 Состав:\n{roster2_text}\n\n"
            f"────────────────────\n"
        )

        await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, f"{header}⏱ **1-й Период стартует! Команды выходят на лед...**")
        await asyncio.sleep(4)

        score1, score2 = 0, 0
        all_events = []
        conn_g = get_db()
        c_g = conn_g.cursor()

        prob_p1, prob_p2 = calc_goal_probabilities(p1_cards, p2_cards)

        for period in range(1, 4):
            period_header = f"⏱ **ПЕРИОД {period}**\n"
            for tick in range(1, 4):
                minute = (period - 1) * 20 + tick * 6 + random.randint(-1, 2)
                minute = min(60, max(1, minute))
                rand_val = random.random()

                if rand_val < prob_p1:
                    scorer = random.choice([p1_cards['skater1'], p1_cards['skater2'], p1_cards['skater3'], p1_cards['skater4']])
                    assist_cand = [p for k, p in p1_cards.items() if k != 'goalie' and p['id'] != scorer['id']]
                    assist = random.choice(assist_cand) if assist_cand else None
                    score1 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_g, p1_id, 100, 10)
                    c_g.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p2_id,))
                    conn_g.commit()

                    assist_str = f" (пас: {assist['nickname']})" if assist else ""
                    evt = f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']}{assist_str} забивает за 🔴 {name1}! (+{reward_money} RPLCoin, +{reward_xp} XP) [{score1}:{score2}]"
                    all_events.append(evt)

                elif rand_val < prob_p1 + prob_p2:
                    scorer = random.choice([p2_cards['skater1'], p2_cards['skater2'], p2_cards['skater3'], p2_cards['skater4']])
                    assist_cand = [p for k, p in p2_cards.items() if k != 'goalie' and p['id'] != scorer['id']]
                    assist = random.choice(assist_cand) if assist_cand else None
                    score2 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_g, p2_id, 100, 10)
                    c_g.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p1_id,))
                    conn_g.commit()

                    assist_str = f" (пас: {assist['nickname']})" if assist else ""
                    evt = f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']}{assist_str} забивает за 🔵 {name2}! (+{reward_money} RPLCoin, +{reward_xp} XP) [{score1}:{score2}]"
                    all_events.append(evt)

                else:
                    event_type = random.choice(["save1", "save2", "post", "hit", "penalty", "var_cancel", "fight", "injury", "timeout"])
                    if event_type == "save1":
                        evt = f"🧤 **{minute}' СЕЙВ!** {p1_cards['goalie']['nickname']} спасает ворота после мощного щелчка!"
                    elif event_type == "save2":
                        evt = f"🧤 **{minute}' СЕЙВ!** {p2_cards['goalie']['nickname']} ловит шайбу ловушкой в прыжке!"
                    elif event_type == "post":
                        sk = random.choice([p1_cards['skater1'], p2_cards['skater1']])
                        evt = f"🏒 **{minute}' ШТАНГА!** {sk['nickname']} попадает прямо в каркас ворот! Шайба чудом не пересекла линию."
                    elif event_type == "hit":
                        evt = f"💥 **{minute}' СИЛОВОЙ ПРИЕМ!** Жесткое столкновение игроков у борта, судья разрешает продолжить игру."
                    elif event_type == "penalty":
                        sk = random.choice([p1_cards['skater3'], p2_cards['skater3']])
                        evt = f"2️⃣ **{minute}' УДАЛЕНИЕ!** {sk['nickname']} отправляется на скамейку штрафников на 2 минуты за задержку клюшкой."
                    elif event_type == "var_cancel":
                        evt = f"⚖️ **{minute}' ОТМЕНА ГОЛА СУДЬЯМИ (VAR)!** После видеопросмотра арбитры фиксируют игру высоко поднятой клюшкой. Гол отменен!"
                    elif event_type == "fight":
                        evt = f"🥊 **{minute}' ТАКОВАЯ ДРАКА НА ЛЬДУ!** Тафгаи обеих команд сбросили краги, но судьи вовремя разняли игроков!"
                    elif event_type == "injury":
                        evt = f"🚑 **{minute}' МЕДИЦИНСКАЯ ПАУЗА!** Игрок получил небольшое повреждение после броска, но возвращается в игру."
                    else:
                        evt = f"⏱ **{minute}' ТАЙМ-АУТ!** Тренеры проводят быструю установку на концовку периода."

                    all_events.append(evt)

                recent_events = "\n".join(all_events[-6:])
                status_text = (
                    f"{header}\n"
                    f"📊 **Счет:** 🔴 {score1} — {score2} 🔵\n"
                    f"{period_header}\n"
                    f"📝 **Ход матча:**\n{recent_events}"
                )
                await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, status_text)
                await asyncio.sleep(3.5)

        conn_g.close()
        await asyncio.sleep(2)

        if score1 == score2:
            conn_ot = get_db()
            c_ot = conn_ot.cursor()
            evt_ot_start = f"⏳ **ОСНОВНОЕ ВРЕМЯ ЗАВЕРШЕНО ({score1}:{score2})! НАЧИНАЕТСЯ ОВЕРТАЙМ (3х3)!**"
            all_events.append(evt_ot_start)
            await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, f"{header}\n📊 **Счет:** 🔴 {score1} — {score2} 🔵\n\n{evt_ot_start}")
            await asyncio.sleep(4)

            for ot_min in range(61, 66):
                rand_val = random.random()
                if rand_val < prob_p1 * 0.8:
                    scorer = random.choice([p1_cards['skater1'], p1_cards['skater2']])
                    score1 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_ot, p1_id, 100, 10)
                    c_ot.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p2_id,))
                    conn_ot.commit()
                    all_events.append(f"🔥 **{ot_min}' ЗОЛОТОЙ ГОЛ!** {scorer['nickname']} приносит победу 🔴 {name1}! [{score1}:{score2}]")
                    break
                elif rand_val < (prob_p1 + prob_p2) * 0.8:
                    scorer = random.choice([p2_cards['skater1'], p2_cards['skater2']])
                    score2 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_ot, p2_id, 100, 10)
                    c_ot.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p1_id,))
                    conn_ot.commit()
                    all_events.append(f"🔥 **{ot_min}' ЗОЛОТОЙ ГОЛ!** {scorer['nickname']} приносит победу 🔵 {name2}! [{score1}:{score2}]")
                    break
                else:
                    all_events.append(f"⚡️ **{ot_min}' Опасная атака в овертайме!**")
                
                await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, f"{header}\n📊 **Счет:** 🔴 {score1} — {score2} 🔵\n⏱ **ОВЕРТАЙМ**\n" + "\n".join(all_events[-6:]))
                await asyncio.sleep(3.5)
            conn_ot.close()

        await asyncio.sleep(2)
        if score1 == score2:
            conn_so = get_db()
            c_so = conn_so.cursor()
            all_events.append("🏒 **СЕРИЯ ПОСЛЕМАТЧЕВЫХ БУЛЛИТОВ!**")
            await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, f"{header}\n🏒 **СЕРИЯ БУЛЛИТОВ!**")
            await asyncio.sleep(3)

            for r_num in range(1, 4):
                sk1 = random.choice([p1_cards['skater1'], p1_cards['skater2']])
                if random.random() < calc_shootout_prob(sk1['ovr'], p2_cards['goalie']['ovr']):
                    score1 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_so, p1_id, 100, 10)
                    c_so.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p2_id,))
                    c_so.commit()
                    all_events.append(f"🎯 Буллит {r_num} 🔴 {name1}: {sk1['nickname']} — **ГОЛ!**")
                else:
                    all_events.append(f"🚫 Буллит {r_num} 🔴 {name1}: {sk1['nickname']} — СЕЙВ.")

                sk2 = random.choice([p2_cards['skater1'], p2_cards['skater2']])
                if random.random() < calc_shootout_prob(sk2['ovr'], p1_cards['goalie']['ovr']):
                    score2 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_so, p2_id, 100, 10)
                    c_so.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p1_id,))
                    c_so.commit()
                    all_events.append(f"🎯 Буллит {r_num} 🔵 {name2}: {sk2['nickname']} — **ГОЛ!**")
                else:
                    all_events.append(f"🚫 Буллит {r_num} 🔵 {name2}: {sk2['nickname']} — СЕЙВ.")

                await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, f"{header}\n📊 Счет: {score1}:{score2}\n" + "\n".join(all_events[-6:]))
                await asyncio.sleep(3)
            conn_so.close()

        conn = get_db()
        c = conn.cursor()
        if score1 > score2:
            res_text = f"🎉 **ПОБЕДА 🔴 {name1}!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p1_id, win=True)
            apply_match_stats(c, p2_id, win=False)
        elif score2 > score1:
            res_text = f"🎉 **ПОБЕДА 🔵 {name2}!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p2_id, win=True)
            apply_match_stats(c, p1_id, win=False)
        else:
            res_text = f"🤝 **НИЧЬЯ!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p1_id, win=None)
            apply_match_stats(c, p2_id, win=None)

        conn.commit()
        conn.close()

        final_text = (
            f"🏁 **МАТЧ ЗАВЕРШЕН!**\n\n{res_text}\n\n"
            f"🏆 Победитель: +50 MMR, +2000 RPL\n"
            f"🥈 Проигравший: -50 MMR, +500 RPL\n"
            f"⚽️ Голы оплачены с бонусами\n\n"
            f"📋 **Протокол:**\n" + "\n".join(all_events)
        )
        await broadcast_match_text(context, p1_chat_id, p1_msg_id, p2_chat_id, p2_msg_id, final_text)

    finally:
        active_games.discard(p1_id)
        active_games.discard(p2_id)

async def start_game_vs_ai(p1_id, chat_id, msg_id, context):
    active_games.add(p1_id)
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE user_id = %s", (p1_id,))
        u1 = c.fetchone()

        c.execute("SELECT * FROM user_rosters WHERE user_id = %s", (p1_id,))
        r1 = c.fetchone()
        p1_cards = get_roster_cards(c, r1)
        p1_ovr = sum(cd['ovr'] for cd in p1_cards.values()) / 5.0

        p1_card_ids = [cd['id'] for cd in p1_cards.values()]
        c.execute("SELECT * FROM cards WHERE id NOT IN %s AND ovr BETWEEN %s AND %s", 
                  (tuple(p1_card_ids), max(50, int(p1_ovr - 5)), int(p1_ovr + 5)))
        ai_candidates = c.fetchall()

        if len(ai_candidates) < 5:
            c.execute("SELECT * FROM cards WHERE id NOT IN %s", (tuple(p1_card_ids),))
            ai_candidates = c.fetchall()

        conn.close()

        random.shuffle(ai_candidates)
        ai_skaters = [cd for cd in ai_candidates if cd['position'] == 'Skater']
        ai_goalies = [cd for cd in ai_candidates if cd['position'] == 'Goalie']

        goalie_card = ai_goalies[0] if ai_goalies else {"id": -1, "nickname": "AI Goalie", "ovr": int(p1_ovr)}
        skater_cards = ai_skaters[:4] if len(ai_skaters) >= 4 else [{"id": -i, "nickname": f"AI Skater {i}", "ovr": int(p1_ovr)} for i in range(1, 5)]

        ai_cards = {
            "goalie": goalie_card,
            "skater1": skater_cards[0],
            "skater2": skater_cards[1],
            "skater3": skater_cards[2],
            "skater4": skater_cards[3]
        }

        ai_ovr = sum(cd['ovr'] for cd in ai_cards.values()) / 5.0
        name1 = u1['first_name'] or u1['username'] or str(p1_id)

        team1_str = f"{u1['custom_team_emoji']} {u1['custom_team_name']} ({u1['custom_team_country']})"
        roster1_text = format_cards_list(p1_cards)
        roster2_text = format_cards_list(ai_cards)

        header = (
            f"🏒 **МАТЧ ПРОТИВ ИИ БОТА**\n\n"
            f"🔴 **{name1}** | {team1_str}\n"
            f"⭐ OVR: `{p1_ovr:.1f}`\n📋 Состав:\n{roster1_text}\n\n"
            f" VS \n\n"
            f"🤖 **ИИ Бот (Сборная лиги)**\n"
            f"⭐ OVR: `{ai_ovr:.1f}`\n📋 Состав:\n{roster2_text}\n\n"
            f"────────────────────\n"
        )

        await broadcast_match_text(context, chat_id, msg_id, None, None, f"{header}⏱ **1-й Период стартует!**")
        await asyncio.sleep(4)

        score1, score2 = 0, 0
        all_events = []
        conn_ai = get_db()
        c_ai = conn_ai.cursor()

        prob_p1, prob_ai = calc_goal_probabilities(p1_cards, ai_cards)

        for period in range(1, 4):
            period_header = f"⏱ **ПЕРИОД {period}**\n"
            for tick in range(1, 4):
                minute = (period - 1) * 20 + tick * 6 + random.randint(-1, 2)
                minute = min(60, max(1, minute))
                rand_val = random.random()

                if rand_val < prob_p1:
                    scorer = random.choice([p1_cards['skater1'], p1_cards['skater2'], p1_cards['skater3'], p1_cards['skater4']])
                    score1 += 1
                    # === ЗАМЕНА НА add_goal_reward (ПАТЧ) ===
                    reward_money, reward_xp = add_goal_reward(c_ai, p1_id, 100, 10)
                    c_ai.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p1_id,))
                    conn_ai.commit()
                    all_events.append(f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']} забивает за 🔴 {name1}! (+{reward_money} RPLCoin, +{reward_xp} XP) [{score1}:{score2}]")
                elif rand_val < prob_p1 + prob_ai:
                    scorer = random.choice([ai_cards['skater1'], ai_cards['skater2'], ai_cards['skater3'], ai_cards['skater4']])
                    score2 += 1
                    # Для ИИ-гола начисляем только пропущенный гол
                    c_ai.execute("UPDATE users SET goals_conceded = goals_conceded + 1 WHERE user_id = %s", (p1_id,))
                    conn_ai.commit()
                    all_events.append(f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']} забивает за 🤖 ИИ Бота! [{score1}:{score2}]")
                else:
                    evt_type = random.choice(["save1", "save2", "post", "hit", "var_cancel", "fight"])
                    if evt_type == "save1": all_events.append(f"🧤 **{minute}' СЕЙВ!** {p1_cards['goalie']['nickname']} выручает команду.")
                    elif evt_type == "save2": all_events.append(f"🧤 **{minute}' СЕЙВ!** ИИ Вратарь забирает шайбу в ловушку.")
                    elif evt_type == "post": all_events.append(f"🏒 **{minute}' ШТАНГА!** Опаснейший бросок сотрясает каркас ворот!")
                    elif evt_type == "hit": all_events.append(f"💥 **{minute}' СИЛОВОЙ ПРИЕМ!** Жесткая борьба у бортов.")
                    elif evt_type == "var_cancel": all_events.append(f"⚖️ **{minute}' VAR:** Гол отменен из-за вне игры!")
                    else: all_events.append(f"🥊 **{minute}' ДРАКА!** Судья разнял хоккеистов.")

                recent_events = "\n".join(all_events[-6:])
                await broadcast_match_text(context, chat_id, msg_id, None, None, f"{header}\n📊 Счет: 🔴 {score1} — {score2} 🤖\n{period_header}\n{recent_events}")
                await asyncio.sleep(3.5)

        conn_ai.close()
        await asyncio.sleep(2)

        conn = get_db()
        c = conn.cursor()
        if score1 > score2:
            res_text = f"🎉 **ПОБЕДА НАД ИИ!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p1_id, win=True)
        elif score2 > score1:
            res_text = f"❌ **ПОРАЖЕНИЕ ОТ ИИ!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p1_id, win=False)
        else:
            res_text = f"🤝 **НИЧЬЯ С ИИ!** Счет: **{score1} - {score2}**"
            apply_match_stats(c, p1_id, win=None)

        conn.commit()
        conn.close()

        final_text = f"🏁 **МАТЧ С ИИ ЗАВЕРШЕН!**\n\n{res_text}\n\n📋 **Протокол:**\n" + "\n".join(all_events)
        await broadcast_match_text(context, chat_id, msg_id, None, None, final_text)

    finally:
        active_games.discard(p1_id)

def get_roster_cards(cursor, roster):
    cursor.execute("SELECT * FROM cards WHERE id IN (%s, %s, %s, %s, %s)", 
                   (roster['goalie_id'], roster['skater1_id'], roster['skater2_id'], roster['skater3_id'], roster['skater4_id']))
    cds = {cd['id']: cd for cd in cursor.fetchall()}
    return {
        "goalie": cds[roster['goalie_id']],
        "skater1": cds[roster['skater1_id']],
        "skater2": cds[roster['skater2_id']],
        "skater3": cds[roster['skater3_id']],
        "skater4": cds[roster['skater4_id']]
    }

def apply_match_stats(cursor, user_id, win):
    if win is True:
        cursor.execute("UPDATE users SET mmr = mmr + 50, balance = balance + 2000, matches_played = matches_played + 1, matches_won = matches_won + 1 WHERE user_id = %s", (user_id,))
    elif win is False:
        cursor.execute("UPDATE users SET mmr = GREATEST(0, mmr - 50), balance = balance + 500, matches_played = matches_played + 1, matches_lost = matches_lost + 1 WHERE user_id = %s", (user_id,))
    else:
        cursor.execute("UPDATE users SET balance = balance + 500, matches_played = matches_played + 1 WHERE user_id = %s", (user_id,))

async def cardmmr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT username, first_name, mmr FROM users ORDER BY mmr DESC LIMIT 10")
    top = c.fetchall()
    conn.close()

    if not top:
        await update.message.reply_text("🏆 **ТОП-10 ИГРОКОВ ПО MMR:**\n\nПока нет игроков.", parse_mode="Markdown")
        return

    text = "🏆 **ТОП-10 ИГРОКОВ ПО MMR:**\n\n"
    for i, u in enumerate(top, 1):
        name = u['first_name'] or u['username'] or "Игрок"
        safe_name = name.replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
        text += f"{i}. **{safe_name}** — `{u['mmr']} MMR`\n"

    await update.message.reply_text(text, parse_mode="Markdown")

# ==================== ОБНОВЛЁННАЯ ФУНКЦИЯ shop_command (ПАТЧ) ====================
async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text(
        "🛍 **МАГАЗИН**\n\nВыберите нужный раздел:",
        reply_markup=store_keyboard(),
        parse_mode="Markdown"
    )

async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    c = conn.cursor()
    now = datetime.now()
    c.execute("SELECT * FROM packs WHERE available_until IS NULL OR available_until > %s", (now,))
    packs = c.fetchall()

    c.execute("SELECT discount_percent FROM users WHERE user_id = %s", (user.id,))
    u_disc = c.fetchone()['discount_percent']
    conn.close()

    if not packs:
        text = "🛒 **Магазин Паков пуст.** Администратор скоро добавит новые паки!"
        if query:
            await query.answer()
            await query.message.edit_text(text)
        else:
            await update.message.reply_text(text)
        return

    text = f"🛒 **МАГАЗИН ПАКОВ КАРТОЧЕК:**\n🏷 Ваша скидка: **{u_disc}%**\n\nВыберите пак для покупки:\n\n"
    buttons = []

    for p in packs:
        final_price = p['price']
        if u_disc > 0:
            final_price = int(p['price'] * (100 - u_disc) / 100)

        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT buy_count FROM user_pack_buys WHERE user_id = %s AND pack_id = %s", (user.id, p['id']))
        b_row = c.fetchone()
        conn.close()
        b_count = b_row['buy_count'] if b_row else 0

        lim_str = f"{b_count}/{p['buy_limit']}" if p['buy_limit'] > 0 else "Безлимит"
        price_str = f"~~{p['price']}~~ **{final_price} RPL**" if u_disc > 0 else f"**{p['price']} RPL**"

        text += f"📦 **{p['name']}** — {price_str} (Куплено: {lim_str})\n"
        buttons.append([InlineKeyboardButton(f"📦 {p['name']} ({final_price} RPL)", callback_data=f"preview_pack_{p['id']}")])

    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.answer()
        try:
            await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
        except Exception:
            await query.message.delete()
            await context.bot.send_message(user.id, text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")

async def shop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("preview_pack_"):
        pack_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM packs WHERE id = %s", (pack_id,))
        pack = c.fetchone()

        c.execute("SELECT discount_percent FROM users WHERE user_id = %s", (user.id,))
        u_disc = c.fetchone()['discount_percent']

        c.execute("SELECT buy_count FROM user_pack_buys WHERE user_id = %s AND pack_id = %s", (user.id, pack_id))
        b_row = c.fetchone()
        b_count = b_row['buy_count'] if b_row else 0
        lim_str = f"{b_count}/{pack['buy_limit']}" if pack['buy_limit'] > 0 else "Безлимит"

        c.execute('''
            SELECT c.nickname, c.ovr, c.rarity, c.position
            FROM pack_cards pc
            JOIN cards c ON pc.card_id = c.id
            WHERE pc.pack_id = %s
        ''', (pack_id,))
        p_cards = c.fetchall()
        conn.close()

        final_price = pack['price']
        if u_disc > 0:
            final_price = int(pack['price'] * (100 - u_disc) / 100)

        cards_str = ""
        for pc in p_cards:
            cards_str += f"  • **{pc['nickname']}** ({pc['position']}, {pc['ovr']} OVR) [{pc['rarity']}]\n"

        caption = (
            f"📦 **ПРЕДПРОСМОТР ПАКА «{pack['name']}»**\n\n"
            f"💰 Цена: **{final_price} RPLCoin** {'(со скидкой)' if u_disc > 0 else ''}\n"
            f"🔢 Лимит покупок: **{lim_str}**\n\n"
            f"🃏 **Возможные карточки:**\n{cards_str or '  *(нет карт)*'}"
        )

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Подтвердить покупку", callback_data=f"confirm_pack_{pack_id}")],
            [InlineKeyboardButton("❌ Отмена", callback_data="cancel_pack_buy")]
        ])

        await query.answer()
        if pack['photo_id']:
            try:
                await query.message.delete()
                await context.bot.send_photo(chat_id=user.id, photo=pack['photo_id'], caption=caption, reply_markup=kb, parse_mode="Markdown")
                return
            except Exception:
                pass
        await query.message.edit_text(caption, reply_markup=kb, parse_mode="Markdown")

    elif data == "cancel_pack_buy":
        await show_shop(update, context)

    elif data.startswith("confirm_pack_"):
        pack_id = int(data.split("_")[2])
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM packs WHERE id = %s", (pack_id,))
        pack = c.fetchone()
        c.execute("SELECT balance, discount_percent FROM users WHERE user_id = %s", (user.id,))
        u_info = c.fetchone()
        u_bal = u_info['balance']
        u_disc = u_info['discount_percent']

        if not pack:
            conn.close()
            await query.answer("❌ Пак не найден!", show_alert=True)
            return

        final_price = pack['price']
        if u_disc > 0:
            final_price = int(pack['price'] * (100 - u_disc) / 100)

        if u_bal < final_price:
            conn.close()
            await query.answer("❌ Недостаточно средств!", show_alert=True)
            return

        c.execute("SELECT buy_count FROM user_pack_buys WHERE user_id = %s AND pack_id = %s", (user.id, pack_id))
        b_row = c.fetchone()
        b_count = b_row['buy_count'] if b_row else 0

        if pack['buy_limit'] > 0 and b_count >= pack['buy_limit']:
            conn.close()
            await query.answer("❌ Лимит исчерпан!", show_alert=True)
            return

        c.execute("SELECT c.* FROM pack_cards pc JOIN cards c ON pc.card_id = c.id WHERE pc.pack_id = %s", (pack_id,))
        p_cards = c.fetchall()

        if not p_cards:
            conn.close()
            await query.answer("❌ В паке нет карт!", show_alert=True)
            return

        chosen_card = choose_card_for_user(c, user.id, p_cards)
        chosen_card_id = chosen_card['id']

        c.execute("UPDATE users SET balance = balance - %s, discount_percent = 0 WHERE user_id = %s", (final_price, user.id))
        c.execute('''
            INSERT INTO user_pack_buys (user_id, pack_id, buy_count) VALUES (%s, %s, 1)
            ON CONFLICT (user_id, pack_id) DO UPDATE SET buy_count = user_pack_buys.buy_count + 1
        ''', (user.id, pack_id))
        c.execute('''
            INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1
        ''', (user.id, chosen_card_id))

        # === НАЧИСЛЕНИЕ XP ЗА КАРТУ (ПАТЧ) ===
        xp_reward = XP_FOR_CARD_RARITY.get(chosen_card['rarity'], 0)
        add_experience(c, user.id, xp_reward)

        c.execute('''
            SELECT c.*, col.name as collection_name, t.name as team_name, t.emoji as team_emoji
            FROM cards c
            JOIN collections col ON c.collection_id = col.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE c.id = %s
        ''', (chosen_card_id,))
        card = c.fetchone()

        conn.commit()
        conn.close()

        await query.answer("🎉 Пак успешно куплен!", show_alert=True)
        temp_msg = await context.bot.send_message(chat_id=user.id, text="⏳ **Открываем пак...**", parse_mode="Markdown")
        await asyncio.sleep(3)
        try:
            await context.bot.delete_message(chat_id=user.id, message_id=temp_msg.message_id)
        except Exception:
            pass

        team_str = f"{card['team_emoji'] or '🏒'} {card['team_name']}" if card['team_name'] else "Без команды"
        caption = (
            f"📦 **Вам выпала карточка!**\n\n"
            f"┏━━━━━━━━━━━━━━━━━━━━┓\n"
            f"┃ 👤 {card['nickname']}\n"
            f"┃ 📁 Коллекция: {card['collection_name']}\n"
            f"┃ 🏒 {card['position']}\n"
            f"┃ ⭐ {card['ovr']} OVR\n"
            f"┃ {team_str}\n"
            f"┃ ✨ {card['rarity']}\n"
            f"┗━━━━━━━━━━━━━━━━━━━━┛\n"
            f"✨ Опыт за карту: +{xp_reward} XP"
        )
        await context.bot.send_message(chat_id=user.id, text=caption, parse_mode="Markdown")
        await show_shop(update, context)

async def admin_freepack_setup_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📦 Введите ID карточек через пробел для стартового набора:", parse_mode="Markdown")
    return FREEPACK_ADMIN_SELECT_CARDS

async def admin_freepack_setup_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        card_ids = [int(x) for x in update.message.text.strip().split()]
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM freepack_config")
        for cid in card_ids:
            c.execute("INSERT INTO freepack_config (card_id) VALUES (%s) ON CONFLICT DO NOTHING", (cid,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Стартовый набор обновлен!", reply_markup=card_admin_keyboard())
        return CARD_ADMIN_MENU
    except ValueError:
        await update.message.reply_text("❌ Введите ID числами!")
        return FREEPACK_ADMIN_SELECT_CARDS

async def admin_set_pack_time_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM packs")
    packs = c.fetchall()
    conn.close()

    if not packs:
        await update.message.reply_text("📭 Нет созданных паков.", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END

    buttons = [[InlineKeyboardButton(p['name'], callback_data=f"adm_pack_{p['id']}")] for p in packs]
    await update.message.reply_text("📦 Выберите пак:", reply_markup=InlineKeyboardMarkup(buttons))
    return ADMIN_SHOP_PACK_SELECT

async def admin_shop_pack_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    pack_id = int(query.data.split("_")[2])
    context.user_data["admin_pack_id"] = pack_id
    await query.message.reply_text("⏳ Введите количество часов для магазина:", parse_mode="Markdown")
    return ADMIN_SHOP_PACK_HOURS

async def admin_shop_pack_hours_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        hours = int(update.message.text.strip())
        pack_id = context.user_data.get("admin_pack_id")
        until_time = datetime.now() + timedelta(hours=hours)

        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE packs SET available_until = %s WHERE id = %s", (until_time, pack_id))
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Пак выставлен в магазин на {hours} ч.!", reply_markup=admin_menu_keyboard(), parse_mode="Markdown")
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text("❌ Введите число часов!")
        return ADMIN_SHOP_PACK_HOURS

async def admin_card_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📁 Создать коллекцию":
        await update.message.reply_text("📁 Введите название новой коллекции:")
        return ADD_COLLECTION_NAME
    elif text == "🛡 Создать команду":
        await update.message.reply_text("🛡 Введите название команды:")
        return ADD_TEAM_NAME
    elif text == "❌ Удалить команду":
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT * FROM card_teams")
        teams = c.fetchall()
        conn.close()
        if not teams:
            await update.message.reply_text("📭 Нет команд.", reply_markup=card_admin_keyboard())
            return CARD_ADMIN_MENU
        buttons = [[InlineKeyboardButton(f"{t['emoji']} {t['name']}", callback_data=f"del_team_{t['id']}")] for t in teams]
        await update.message.reply_text("Выберите команду для удаления:", reply_markup=InlineKeyboardMarkup(buttons))
        return DEL_TEAM_SELECT
    elif text == "🃏 Добавить карточку":
        kb = [["Редкая", "Очень редкая"], ["Эпическая", "Мифическая"], ["Легендарная", "Секретная"]]
        await update.message.reply_text("✨ Выберите редкость:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
        return ADD_CARD_RARITY
    elif text == "❌ Удалить карточку":
        await update.message.reply_text("❌ Введите ID карточки:")
        return DEL_CARD_ID
    elif text == "📦 Добавить пак":
        await update.message.reply_text("📦 Введите название пака:")
        return ADD_PACK_NAME
    elif text == "📦 Настроить стартовый набор":
        return await admin_freepack_setup_start(update, context)
    elif text == "🎁 Выдать карточку игроку":
        await update.message.reply_text("🎁 Введите @username и ID карточки через пробел:", parse_mode="Markdown")
        return GRANT_CARD_DATA
    elif text == "💰 Выдать деньги":
        await update.message.reply_text("💰 Введите @username и сумму:", parse_mode="Markdown")
        return GIVE_MONEY_DATA
    elif text == "🎟 Создать промокод":
        await admin_create_promo_start(update, context)
        return ADD_PROMO_CODE
    elif text == "⬅️ Выйти из настройки карточек":
        await update.message.reply_text("⚙️ Админ-панель:", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END
    return CARD_ADMIN_MENU

async def save_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO collections (name) VALUES (%s)", (name,))
        conn.commit()
        await update.message.reply_text(f"✅ Коллекция **{name}** создана!", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Уже существует.", reply_markup=card_admin_keyboard())
    conn.close()
    return CARD_ADMIN_MENU

async def save_team_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["team_name"] = update.message.text.strip()
    await update.message.reply_text("🏒 Введите эмодзи для команды:")
    return ADD_TEAM_EMOJI

async def save_team_emoji(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["team_emoji"] = update.message.text.strip()
    await update.message.reply_text("🖼 Отправьте логотип (или `-`):")
    return ADD_TEAM_PHOTO

async def save_team_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    name = context.user_data.get("team_name")
    emoji = context.user_data.get("team_emoji", "🏒")

    conn = get_db()
    c = conn.cursor()
    try:
        c.execute("INSERT INTO card_teams (name, emoji, photo_id) VALUES (%s, %s, %s)", (name, emoji, photo_id))
        conn.commit()
        await update.message.reply_text(f"✅ Команда {emoji} **{name}** создана!", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
    except Exception:
        await update.message.reply_text("❌ Ошибка.", reply_markup=card_admin_keyboard())
    conn.close()
    return CARD_ADMIN_MENU

async def delete_team_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    team_id = int(query.data.split("_")[2])
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM card_teams WHERE id = %s", (team_id,))
    conn.commit()
    conn.close()
    await query.edit_message_text("✅ Удалено!")
    return CARD_ADMIN_MENU

async def card_set_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_rarity"] = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM collections")
    cols = c.fetchall()
    conn.close()

    if not cols:
        await update.message.reply_text("❌ Создайте коллекцию!", reply_markup=card_admin_keyboard())
        return CARD_ADMIN_MENU

    buttons = [[col['name']] for col in cols]
    await update.message.reply_text("📁 Выберите коллекцию:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    return ADD_CARD_COLLECTION

async def card_set_collection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_collection"] = update.message.text.strip()
    kb = [COUNTRIES[i:i+3] for i in range(0, len(COUNTRIES), 3)]
    await update.message.reply_text("🌍 Выберите страну:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADD_CARD_COUNTRY

async def card_set_country(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_country"] = update.message.text.strip()
    kb = [["Skater", "Goalie"]]
    await update.message.reply_text("🏒 Выберите позицию:", reply_markup=ReplyKeyboardMarkup(kb, resize_keyboard=True))
    return ADD_CARD_POSITION

async def card_set_position(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_position"] = update.message.text.strip()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM card_teams")
    teams = c.fetchall()
    conn.close()

    buttons = [[f"{t['emoji']} {t['name']}"] for t in teams]
    buttons.append(["Без команды"])
    await update.message.reply_text("🛡 Выберите команду:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))
    return ADD_CARD_TEAM

async def card_set_team(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_team"] = update.message.text.strip()
    await update.message.reply_text("🏷 Введите NickName игрока:", reply_markup=ReplyKeyboardRemove(), parse_mode="Markdown")
    return ADD_CARD_NICK

async def card_set_nick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["c_nick"] = update.message.text.strip()
    await update.message.reply_text("⭐ Введите OVR (50-99):")
    return ADD_CARD_OVR

async def card_set_ovr(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["c_ovr"] = int(update.message.text.strip())
        await update.message.reply_text("🖼 Отправьте фото карточки:")
        return ADD_CARD_PHOTO
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ADD_CARD_OVR

async def card_save_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = None
    if update.message.photo:
        photo_id = update.message.photo[-1].file_id
    elif update.message.animation:
        photo_id = update.message.animation.file_id

    rarity = context.user_data.get("c_rarity")
    col_name = context.user_data.get("c_collection")
    country = context.user_data.get("c_country")
    position = context.user_data.get("c_position")
    team_text = context.user_data.get("c_team")
    nick = context.user_data.get("c_nick")
    ovr = context.user_data.get("c_ovr")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT id FROM collections WHERE name = %s", (col_name,))
    col_row = c.fetchone()
    col_id = col_row['id'] if col_row else None

    team_id = None
    if team_text != "Без команды":
        c.execute("SELECT id FROM card_teams WHERE CONCAT(emoji, ' ', name) = %s OR name = %s", (team_text, team_text))
        t_row = c.fetchone()
        if t_row: team_id = t_row['id']

    c.execute('''
        INSERT INTO cards (collection_id, team_id, nickname, position, ovr, country, rarity, image_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
    ''', (col_id, team_id, nick, position, ovr, country, rarity, photo_id))
    
    new_card_id = c.fetchone()['id']
    conn.commit()
    conn.close()

    await update.message.reply_text(f"✅ Карточка создана! ID: `{new_card_id}`", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
    return CARD_ADMIN_MENU

async def delete_card_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        card_id = int(update.message.text.strip())
        conn = get_db()
        c = conn.cursor()
        c.execute("DELETE FROM cards WHERE id = %s", (card_id,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Карточка ID {card_id} удалена!", reply_markup=card_admin_keyboard())
    except ValueError:
        await update.message.reply_text("❌ Введите ID числом!", reply_markup=card_admin_keyboard())
    return CARD_ADMIN_MENU

async def pack_set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["p_name"] = update.message.text.strip()
    await update.message.reply_text("💰 Введите цену пака:")
    return ADD_PACK_PRICE

async def pack_set_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["p_price"] = int(update.message.text.strip())
        await update.message.reply_text("🔢 Введите лимит покупок на игрока (0 = безлимит):")
        return ADD_PACK_LIMIT
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ADD_PACK_PRICE

async def pack_set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        context.user_data["p_limit"] = int(update.message.text.strip())
        await update.message.reply_text("🆔 Введите ID карточек через пробел:", parse_mode="Markdown")
        return ADD_PACK_CARDS
    except ValueError:
        await update.message.reply_text("❌ Введите число!")
        return ADD_PACK_LIMIT

async def pack_set_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        card_ids = [int(x) for x in update.message.text.strip().split()]
        context.user_data["p_cards"] = card_ids
        await update.message.reply_text("🖼 Отправьте обложку пака:")
        return ADD_PACK_PHOTO
    except ValueError:
        await update.message.reply_text("❌ Введите ID через пробел!")
        return ADD_PACK_CARDS

async def pack_save_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photo_id = update.message.photo[-1].file_id if update.message.photo else None
    name = context.user_data.get("p_name")
    price = context.user_data.get("p_price")
    limit = context.user_data.get("p_limit")
    card_ids = context.user_data.get("p_cards", [])

    conn = get_db()
    c = conn.cursor()
    c.execute("INSERT INTO packs (name, price, buy_limit, photo_id) VALUES (%s, %s, %s, %s) RETURNING id",
              (name, price, limit, photo_id))
    pack_id = c.fetchone()['id']

    for cid in card_ids:
        c.execute("INSERT INTO pack_cards (pack_id, card_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (pack_id, cid))

    conn.commit()
    conn.close()
    await update.message.reply_text(f"✅ Пак **{name}** создан!", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
    return CARD_ADMIN_MENU

async def grant_card_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        user_input = parts[0].replace("@", "")
        card_id = int(parts[1])

        conn = get_db()
        c = conn.cursor()
        
        if user_input.isdigit():
            target_id = int(user_input)
        else:
            c.execute("SELECT user_id FROM users WHERE username = %s", (user_input,))
            u_row = c.fetchone()
            if not u_row:
                conn.close()
                await update.message.reply_text("❌ Пользователь не найден!", reply_markup=card_admin_keyboard())
                return CARD_ADMIN_MENU
            target_id = u_row['user_id']

        c.execute("INSERT INTO user_cards (user_id, card_id, count) VALUES (%s, %s, 1) ON CONFLICT (user_id, card_id) DO UPDATE SET count = user_cards.count + 1", (target_id, card_id))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"✅ Выдано!", reply_markup=card_admin_keyboard())
    except Exception:
        await update.message.reply_text("❌ Ошибка формата! Пример: `@username 5`", reply_markup=card_admin_keyboard())
    return CARD_ADMIN_MENU

async def give_money_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        parts = update.message.text.strip().split()
        username = parts[0].replace("@", "")
        amount = int(parts[1])

        conn = get_db()
        c = conn.cursor()
        c.execute("UPDATE users SET balance = balance + %s WHERE username = %s RETURNING user_id", (amount, username))
        row = c.fetchone()
        conn.commit()
        conn.close()

        if row:
            await update.message.reply_text(f"✅ Зачислено **{amount} RPL**!", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
        else:
            await update.message.reply_text("❌ Пользователь не найден!", reply_markup=card_admin_keyboard())
    except Exception:
        await update.message.reply_text("❌ Ошибка формата!", reply_markup=card_admin_keyboard())
    return CARD_ADMIN_MENU

async def admin_view_inventory_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text.strip().replace("@", "")
    conn = get_db()
    c = conn.cursor()
    if user_input.isdigit():
        c.execute("SELECT * FROM users WHERE user_id = %s", (int(user_input),))
    else:
        c.execute("SELECT * FROM users WHERE username = %s", (user_input,))
    target_user = c.fetchone()

    if not target_user:
        conn.close()
        await update.message.reply_text("❌ Не найден!", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END

    target_id = target_user['user_id']
    c.execute('''
        SELECT uc.count, c.*, col.name as col_name, t.name as team_name, t.emoji as team_emoji
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN card_teams t ON c.team_id = t.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY col.name, c.ovr DESC
    ''', (target_id,))
    user_cards = c.fetchall()
    conn.close()

    text = f"🎒 **Инвентарь игрока {target_user['username'] or target_user['first_name']}**:\n\n"
    for uc in user_cards:
        text += f"ID `{uc['id']}` | **{uc['nickname']}** ({uc['ovr']} OVR) — `x{uc['count']}`\n"

    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=admin_menu_keyboard())
    return ConversationHandler.END

async def admin_show_players_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT user_id, username, first_name, balance, mmr FROM users ORDER BY user_id DESC")
    users = c.fetchall()
    conn.close()

    text = f"👥 **Игроки (Всего: {len(users)}):**\n\n"
    for u in users:
        uname = f"@{u['username']}" if u['username'] else u['first_name']
        text += f"• {uname} (`{u['user_id']}`) | {u['balance']} RPL | {u['mmr']} MMR\n"
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=admin_menu_keyboard())

# ==================== ОБНОВЛЁННАЯ ФУНКЦИЯ start (ПАТЧ) ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    data = get_or_create_user(user.id, user.username, user.first_name)
    level, current_xp, required_xp = get_level_and_progress(data.get("experience", 0))

    team_name = data.get("custom_team_name") or "Команда не создана"
    team_country = data.get("custom_team_country") or "—"
    team_emoji = data.get("custom_team_emoji") or "🏒"

    text = (
        "🇷🇺 **Russian Puck League Bot!**\n\n"
        f"👤 Игрок: **{user.first_name or 'Игрок'}**\n"
        f"{team_emoji} Команда: **{team_name}**\n"
        f"🌍 Страна: **{team_country}**\n"
        f"🏅 Уровень: **{level}**\n"
        f"✨ Опыт: **{current_xp}/{required_xp} XP**\n"
        f"💰 Баланс: **{data['balance']} RPLCoin**\n"
        f"🏆 MMR: **{data['mmr']}**\n\n"
        "Выберите действие в меню ниже 👇"
    )
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard()
    )

async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text("📌 Выберите раздел:", reply_markup=welcome_inline_keyboard())

async def minigames_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Орёл и Решка", callback_data="play_coin")],
        [InlineKeyboardButton("🎮 Камень-Ножницы-Бумага", callback_data="play_rps")],
        [InlineKeyboardButton("🎰 Слоты", callback_data="play_slots")],
        [InlineKeyboardButton("🎲 Кости", callback_data="play_dice")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_main_inline")]
    ])
    await update.message.reply_text("🕹 **Мини-игры:**", reply_markup=kb, parse_mode="Markdown")

async def adminkarpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type != "private":
        return ConversationHandler.END
    if is_admin(update.effective_user.id):
        await update.message.reply_text("Вы уже авторизованы.", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END
    await update.message.reply_text("🔑 Введите логин:")
    return WAITING_LOGIN

async def wait_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login"] = update.message.text
    await update.message.reply_text("🔒 Введите пароль:")
    return WAITING_PASSWORD

async def wait_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    login = context.user_data.get("login")
    password = update.message.text
    if check_credentials(login, password):
        add_admin(update.effective_user.id)
        context.user_data.clear()
        await update.message.reply_text("✅ Авторизован!", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END
    else:
        await update.message.reply_text("❌ Неверно!")
        return ConversationHandler.END

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not is_admin(user_id): return
    update_admin_activity(user_id)
    text = update.message.text

    if text == "➕ Добавить каналы":
        await update.message.reply_text("Введите @username канала:")
        return WAITING_CHANNEL_USERNAME
    elif text == "➕ Добавить чаты":
        await update.message.reply_text("Введите ID чата или ссылку:")
        return WAITING_CHAT_LINK
    elif text == "📩 Проверить поддержку":
        await show_support_messages(update, context)
        return
    elif text == "⚙️ Настройки":
        await show_settings(update, context)
        return
    elif text == "🎮 Настройки игры":
        await update.message.reply_text("🎮 Настройки игры.", reply_markup=admin_menu_keyboard())
        return ConversationHandler.END
    elif text == "🃏 Карточки":
        await update.message.reply_text("🃏 Карточки:", reply_markup=card_admin_keyboard(), parse_mode="Markdown")
        return CARD_ADMIN_MENU
    elif text == "📦 Выставить пак в магазин":
        return await admin_set_pack_time_start(update, context)
    elif text == "🔍 Инвентарь игрока":
        await update.message.reply_text("🔍 Введите @username или ID:")
        return WAITING_VIEW_USER_INV
    elif text == "👥 Список игроков":
        await admin_show_players_list(update, context)
        return ConversationHandler.END
    elif text == "🚪 Выйти":
        remove_admin(user_id)
        await update.message.reply_text("🚪 Выход.", reply_markup=main_menu_keyboard())
        return
    return ConversationHandler.END

async def add_channel_username(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.message.text.strip()
    try:
        chat = await context.bot.get_chat(username)
        add_source_channel(chat.id, username, update.effective_user.id)
        await update.message.reply_text(f"✅ Добавлен канал {username}.", reply_markup=admin_menu_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    return ConversationHandler.END

async def add_chat_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    link = update.message.text.strip()
    try:
        chat = await context.bot.get_chat(link)
        add_target_chat(chat.id, link, update.effective_user.id)
        await update.message.reply_text(f"✅ Добавлен чат.", reply_markup=admin_menu_keyboard())
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")
    return ConversationHandler.END

async def show_support_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    messages = get_unanswered_messages()
    if not messages:
        await update.message.reply_text("📭 Нет обращений.", reply_markup=admin_menu_keyboard())
        return
    msg = messages[0]
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Закрыть", callback_data=f"close_{msg['id']}")]
    ])
    await update.message.reply_text(f"📩 Обращение #{msg['id']}\n{msg['text']}", reply_markup=keyboard)

async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📋 Настройки", reply_markup=admin_menu_keyboard())

# ==================== МАГАЗИН БУСТЕРОВ (ПАТЧ) ====================
async def store_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "store_packs":
        await show_shop(update, context)
        return

    if query.data == "store_boosters":
        await show_boosters(update, context)
        return

    if query.data == "open_store":
        await shop_command(update, context)

async def show_boosters(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    balance_row = c.fetchone()
    conn.close()

    balance = balance_row["balance"] if balance_row else 0
    text = (
        "🚀 **МАГАЗИН БУСТЕРОВ**\n\n"
        f"💰 Ваш баланс: **{balance} RPLCoin**\n\n"
        "Бустер сразу начисляет XP и активирует временный бонус.\n\n"
        "🔷 **Редкий** — +50 XP, +25% XP на 6 часов\n"
        "🟣 **Эпический** — +175 XP, +30% XP на 12 часов\n"
        "🔴 **Мифический** — +250 XP, +30% XP на 24 часа\n"
        "🟡 **Легендарный** — +500 XP, +30% XP и денег на 48 часов\n"
    )

    buttons = []
    for booster_id, booster in BOOSTERS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{booster['title']} — {booster['price']} RPL",
                callback_data=f"buy_booster_{booster_id}"
            )
        ])
    buttons.append([InlineKeyboardButton("↩️ Назад в магазин", callback_data="open_store")])

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown"
    )

async def booster_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    booster_id = query.data.replace("buy_booster_", "")
    booster = BOOSTERS.get(booster_id)
    if not booster:
        await query.answer("Бустер не найден.", show_alert=True)
        return

    user_id = query.from_user.id
    now = datetime.now()
    active_until = now + timedelta(hours=booster["hours"])

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT balance FROM users WHERE user_id = %s FOR UPDATE", (user_id,))
    row = c.fetchone()

    if not row or row["balance"] < booster["price"]:
        conn.rollback()
        conn.close()
        await query.answer("❌ Недостаточно RPLCoin.", show_alert=True)
        return

    # XP начисляется через общий механизм, чтобы применить уже активный бонус.
    add_experience(c, user_id, booster["xp"])

    # Бонусы складываются по максимальному проценту, срок продлевается.
    c.execute("""
        UPDATE users
        SET balance = balance - %s,
            experience_bonus_percent = GREATEST(COALESCE(experience_bonus_percent, 0), %s),
            experience_bonus_until = GREATEST(COALESCE(experience_bonus_until, %s), %s),
            money_bonus_percent = GREATEST(COALESCE(money_bonus_percent, 0), %s),
            money_bonus_until = CASE
                WHEN %s > 0 THEN GREATEST(COALESCE(money_bonus_until, %s), %s)
                ELSE money_bonus_until
            END
        WHERE user_id = %s
    """, (
        booster["price"],
        booster["xp_percent"], active_until, active_until,
        booster["money_percent"],
        booster["money_percent"], active_until, active_until,
        user_id,
    ))

    c.execute("""
        INSERT INTO user_boosters
            (user_id, booster_type, experience_amount, experience_percent,
             money_percent, active_until)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (
        user_id,
        booster_id,
        booster["xp"],
        booster["xp_percent"],
        booster["money_percent"],
        active_until,
    ))

    conn.commit()
    conn.close()

    await query.answer("✅ Бустер активирован!", show_alert=True)
    await show_boosters(update, context)

# =========================================================

async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_main_inline":
        await query.message.reply_text("📌 Меню:", reply_markup=welcome_inline_keyboard())
    elif data == "discord":
        await query.message.reply_text("💬 **Discord:** https://discord.gg/dgkFMCgDwx")
    elif data == "website":
        await query.message.reply_text("🌐 **Сайт:** rplpuck.ru")
    elif data == "support":
        await query.message.reply_text("✍️ Напишите ваше сообщение в поддержку:")
        return WAITING_SUPPORT_MSG
    elif data == "duel":
        await query.message.reply_text("🏒 Выберите зону броска:", reply_markup=duel_shot_keyboard())
        return WAITING_DUEL_SHOT
    elif data == "play_coin":
        await query.message.reply_text("🪙 Введите ставку для Орёл и Решка:", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
        return WAITING_COIN_BET
    elif data == "play_rps":
        await query.message.reply_text("🎮 Введите ставку для КНБ:", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
        return WAITING_RPS_BET
    elif data == "play_slots":
        await query.message.reply_text("🎰 Введите ставку для Слотов:", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
        return WAITING_SLOTS_BET
    elif data == "play_dice":
        await query.message.reply_text("🎲 Введите ставку для Костей:", reply_markup=bet_cancel_keyboard(), parse_mode="Markdown")
        return WAITING_DICE_BET

async def duel_shot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if random.random() < 0.35:
        await query.edit_message_text("⚡️ **ГОЛ!**")
    else:
        await query.edit_message_text("🧤 **СЕЙВ!**")
    return ConversationHandler.END

async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_support_message(user.id, user.username or str(user.id), update.message.text)
    await update.message.reply_text("✅ Отправлено в поддержку.")
    return ConversationHandler.END

# ==================== ОБНОВЛЁННЫЙ СПИСОК ГЛАВНОГО МЕНЮ (ПАТЧ) ====================
MAIN_MENU_TEXT_HANDLERS = {
    "🏠 Главная": start,
    "🎴 Карточка дня": rplcards_command,
    "🎒 Коллекция": inventory_command,
    "🏪 Торговая площадка": cardshop_command,
    "👤 Профиль и состав": profile_command,
    "🏟 Найти матч": cardmatch_command,
    "🛍 Магазин": shop_command,
    "🏆 Рейтинг MMR": cardmmr_command,
    "🤝 Обмен": trade_command,
    "🎟 Промокод": promo_command,
    "🎡 Колесо удачи": wheel_command,
    "💼 Работы": jobs_menu_command,
    "🎁 Ежедневная награда": daily_command,
    "🎮 Игры": minigames_menu,
}
MAIN_MENU_REGEX = "^(" + "|".join(re.escape(k) for k in MAIN_MENU_TEXT_HANDLERS) + ")$"

async def bet_state_menu_escape(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    handler = MAIN_MENU_TEXT_HANDLERS.get(text)
    if handler:
        await handler(update, context)
    return ConversationHandler.END

async def cancel_minigame_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🪙 Орёл и Решка", callback_data="play_coin")],
        [InlineKeyboardButton("🎮 КНБ", callback_data="play_rps")],
        [InlineKeyboardButton("🎰 Слоты", callback_data="play_slots")],
        [InlineKeyboardButton("🎲 Кости", callback_data="play_dice")]
    ])
    await context.bot.send_message(chat_id=update.effective_chat.id, text="🕹 **Мини-игры:**", reply_markup=kb, parse_mode="Markdown")
    return ConversationHandler.END

def bet_cancel_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="cancel_minigame")]])

async def cooldown_notifier_loop(application: Application):
    await asyncio.sleep(10)
    while True:
        try:
            conn = get_db()
            c = conn.cursor()
            now = datetime.now()

            c.execute("SELECT user_id, last_card_claim FROM users WHERE last_card_claim IS NOT NULL")
            users_card = c.fetchall()
            for u in users_card:
                last_claim = u['last_card_claim']
                if isinstance(last_claim, str):
                    last_claim = datetime.fromisoformat(last_claim)
                diff = (now - last_claim).total_seconds()
                if 28740 <= diff <= 28860:
                    try:
                        await application.bot.send_message(
                            chat_id=u['user_id'],
                            text="🃏 **Ваш кулдаун на бесплатную карточку завершился!**\nСкорее забирайте новую карту в меню или командой /rplcards!",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

            c.execute("SELECT user_id, last_wheel_spin FROM users WHERE last_wheel_spin IS NOT NULL")
            users_wheel = c.fetchall()
            for u in users_wheel:
                last_spin = u['last_wheel_spin']
                if isinstance(last_spin, str):
                    last_spin = datetime.fromisoformat(last_spin)
                diff = (now - last_spin).total_seconds()
                if 129540 <= diff <= 129660:
                    try:
                        await application.bot.send_message(
                            chat_id=u['user_id'],
                            text="🎡 **Колесо удачи снова доступно!**\nКулдаун 36 часов истек. Испытайте удачу в /wheel!",
                            parse_mode="Markdown"
                        )
                    except Exception:
                        pass

            conn.close()
        except Exception as e:
            logger.error(f"Error in cooldown_notifier_loop: {e}")
        
        await asyncio.sleep(60)

async def post_init_hook(application: Application):
    asyncio.create_task(cooldown_notifier_loop(application))

def main():
    app = Application.builder().token(TOKEN).post_init(post_init_hook).build()

    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("tradecancel", tradecancel_command))
    app.add_handler(CommandHandler("jobs", jobs_menu_command))
    app.add_handler(CommandHandler("works", jobs_menu_command))

    conv_auth = ConversationHandler(
        entry_points=[CommandHandler("adminkarpl", adminkarpl)],
        states={
            WAITING_LOGIN: [MessageHandler(filters.TEXT & ~filters.COMMAND, wait_login)],
            WAITING_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, wait_password)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_auth)

    conv_channel = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить каналы$") & filters.ChatType.PRIVATE, admin_buttons)],
        states={WAITING_CHANNEL_USERNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_channel_username)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_channel)

    conv_chat = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^➕ Добавить чаты$") & filters.ChatType.PRIVATE, admin_buttons)],
        states={WAITING_CHAT_LINK: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_chat_link)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_chat)

    conv_user_inv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🔍 Инвентарь игрока$") & filters.ChatType.PRIVATE, admin_buttons)],
        states={WAITING_VIEW_USER_INV: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_view_inventory_execute)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_user_inv)

    conv_support = ConversationHandler(
        entry_points=[CallbackQueryHandler(inline_callback, pattern="^support$")],
        states={WAITING_SUPPORT_MSG: [MessageHandler(filters.TEXT & ~filters.COMMAND, support_receive)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_support)

    conv_duel = ConversationHandler(
        entry_points=[CallbackQueryHandler(inline_callback, pattern="^duel$")],
        states={WAITING_DUEL_SHOT: [CallbackQueryHandler(duel_shot, pattern="^shot_")]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_duel)

    conv_promo_user = ConversationHandler(
        entry_points=[
            CommandHandler("promo", promo_command),
            MessageHandler(filters.Regex("^🎟 Промокод$"), promo_command)
        ],
        states={WAITING_PROMO_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_input_receive)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_promo_user)

    conv_market_price = ConversationHandler(
        entry_points=[CallbackQueryHandler(market_callback_handler, pattern="^select_mcard_")],
        states={WAITING_MARKET_PRICE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_market_list_price)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_market_price)

    conv_trade_money = ConversationHandler(
        entry_points=[CallbackQueryHandler(trade_callback_handler, pattern="^tr_addmoney_")],
        states={WAITING_TRADE_MONEY: [MessageHandler(filters.TEXT & ~filters.COMMAND, execute_trade_money_input)]},
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_trade_money)

    conv_custom_team = ConversationHandler(
        entry_points=[CallbackQueryHandler(profile_callback_handler, pattern="^edit_custom_team$")],
        states={
            WAITING_TEAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, team_name_receive)],
            WAITING_TEAM_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, team_country_receive)],
            WAITING_TEAM_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, team_emoji_receive)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_custom_team)

    conv_coin = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(inline_callback, pattern="^play_coin$"),
            CommandHandler("coin", coin_command),
        ],
        states={WAITING_COIN_BET: [
            MessageHandler(filters.Regex(MAIN_MENU_REGEX), bet_state_menu_escape),
            MessageHandler(filters.TEXT & ~filters.COMMAND, coin_receive_bet),
        ]},
        fallbacks=[
            CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено.")),
            CallbackQueryHandler(cancel_minigame_callback, pattern="^cancel_minigame$"),
        ],
        per_message=False,
    )
    app.add_handler(conv_coin)

    conv_rps = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(inline_callback, pattern="^play_rps$"),
            MessageHandler(filters.Regex("^🎮 Игры$"), minigames_menu),
            CommandHandler("rps", rps_command),
        ],
        states={WAITING_RPS_BET: [
            MessageHandler(filters.Regex(MAIN_MENU_REGEX), bet_state_menu_escape),
            MessageHandler(filters.TEXT & ~filters.COMMAND, rps_receive_bet),
        ]},
        fallbacks=[
            CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено.")),
            CallbackQueryHandler(cancel_minigame_callback, pattern="^cancel_minigame$"),
        ],
        per_message=False,
    )
    app.add_handler(conv_rps)

    conv_slots = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(inline_callback, pattern="^play_slots$"),
            CommandHandler("slots", slots_command),
        ],
        states={WAITING_SLOTS_BET: [
            MessageHandler(filters.Regex(MAIN_MENU_REGEX), bet_state_menu_escape),
            MessageHandler(filters.TEXT & ~filters.COMMAND, slots_receive_bet),
        ]},
        fallbacks=[
            CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено.")),
            CallbackQueryHandler(cancel_minigame_callback, pattern="^cancel_minigame$"),
        ],
        per_message=False,
    )
    app.add_handler(conv_slots)

    conv_dice = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(inline_callback, pattern="^play_dice$"),
            CommandHandler("dice", dice_command),
        ],
        states={WAITING_DICE_BET: [
            MessageHandler(filters.Regex(MAIN_MENU_REGEX), bet_state_menu_escape),
            MessageHandler(filters.TEXT & ~filters.COMMAND, dice_receive_bet),
        ]},
        fallbacks=[
            CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено.")),
            CallbackQueryHandler(cancel_minigame_callback, pattern="^cancel_minigame$"),
        ],
        per_message=False,
    )
    app.add_handler(conv_dice)

    conv_admin_shop_pack = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^📦 Выставить пак в магазин$") & filters.ChatType.PRIVATE, admin_buttons)
        ],
        states={
            ADMIN_SHOP_PACK_SELECT: [CallbackQueryHandler(admin_shop_pack_callback, pattern="^adm_pack_")],
            ADMIN_SHOP_PACK_HOURS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_shop_pack_hours_receive)]
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        per_message=False,
    )
    app.add_handler(conv_admin_shop_pack)

    conv_cards = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🃏 Карточки$") & filters.ChatType.PRIVATE, admin_buttons)],
        states={
            CARD_ADMIN_MENU: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_card_menu_handler)],
            ADD_COLLECTION_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_collection)],
            ADD_TEAM_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_team_name)],
            ADD_TEAM_EMOJI: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_team_emoji)],
            ADD_TEAM_PHOTO: [MessageHandler(filters.PHOTO | filters.TEXT, save_team_photo)],
            DEL_TEAM_SELECT: [CallbackQueryHandler(delete_team_callback, pattern="^del_team_")],
            ADD_CARD_RARITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_rarity)],
            ADD_CARD_COLLECTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_collection)],
            ADD_CARD_COUNTRY: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_country)],
            ADD_CARD_POSITION: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_position)],
            ADD_CARD_TEAM: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_team)],
            ADD_CARD_NICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_nick)],
            ADD_CARD_OVR: [MessageHandler(filters.TEXT & ~filters.COMMAND, card_set_ovr)],
            ADD_CARD_PHOTO: [MessageHandler(filters.PHOTO | filters.ANIMATION, card_save_all)],
            DEL_CARD_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_card_execute)],
            ADD_PACK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, pack_set_name)],
            ADD_PACK_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, pack_set_price)],
            ADD_PACK_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pack_set_limit)],
            ADD_PACK_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, pack_set_cards)],
            ADD_PACK_PHOTO: [MessageHandler(filters.PHOTO, pack_save_all)],
            FREEPACK_ADMIN_SELECT_CARDS: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_freepack_setup_receive)],
            GRANT_CARD_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, grant_card_execute)],
            GIVE_MONEY_DATA: [MessageHandler(filters.TEXT & ~filters.COMMAND, give_money_execute)],
            ADD_PROMO_CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_promo_set_code)],
            ADD_PROMO_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_promo_set_type)],
            ADD_PROMO_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_promo_set_val)],
            ADD_PROMO_LIMIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, admin_promo_save)],
        },
        fallbacks=[CommandHandler("cancel", lambda u,c: u.message.reply_text("Отменено."))],
        allow_reentry=True,
        per_message=False,
    )
    app.add_handler(conv_cards)

    app.add_handler(MessageHandler(filters.Regex("^(📩 Проверить поддержку|⚙️ Настройки|🎮 Настройки игры|👥 Список игроков|🚪 Выйти)$") & filters.ChatType.PRIVATE, admin_buttons))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("freepack", freepack_command))
    app.add_handler(CommandHandler("rplcards", rplcards_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("checkprofile", checkprofile_command))
    app.add_handler(CommandHandler("cardmatch", cardmatch_command))
    app.add_handler(CommandHandler("cardmmr", cardmmr_command))
    app.add_handler(CommandHandler("shop", shop_command))
    app.add_handler(CommandHandler("cardshop", cardshop_command))
    app.add_handler(CommandHandler("trade", trade_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("wheel", wheel_command))
    app.add_handler(CommandHandler("rps", rps_command))

    # Обновлённые обработчики главного меню
    app.add_handler(MessageHandler(filters.Regex("^🏠 Главная$"), start))
    app.add_handler(MessageHandler(filters.Regex("^🎴 Карточка дня$"), rplcards_command))
    app.add_handler(MessageHandler(filters.Regex("^🎒 Коллекция$"), inventory_command))
    app.add_handler(MessageHandler(filters.Regex("^🏪 Торговая площадка$"), cardshop_command))
    app.add_handler(MessageHandler(filters.Regex("^👤 Профиль и состав$"), profile_command))
    app.add_handler(MessageHandler(filters.Regex("^🏟 Найти матч$"), cardmatch_command))
    app.add_handler(MessageHandler(filters.Regex("^🛍 Магазин$"), shop_command))
    app.add_handler(MessageHandler(filters.Regex("^🏆 Рейтинг MMR$"), cardmmr_command))
    app.add_handler(MessageHandler(filters.Regex("^🤝 Обмен$"), trade_command))
    app.add_handler(MessageHandler(filters.Regex("^🎡 Колесо удачи$"), wheel_command))
    app.add_handler(MessageHandler(filters.Regex("^💼 Работы$"), jobs_menu_command))
    app.add_handler(MessageHandler(filters.Regex("^🎁 Ежедневная награда$"), daily_command))
    app.add_handler(MessageHandler(filters.Regex("^🎮 Игры$"), minigames_menu))

    app.add_handler(CallbackQueryHandler(jobs_menu_command, pattern="^jobs_menu$"))
    app.add_handler(CallbackQueryHandler(job_coach_main_handler, pattern="^job_coach_main$"))
    app.add_handler(CallbackQueryHandler(job_coach_action_handler, pattern="^job_coach_shoot"))
    app.add_handler(CallbackQueryHandler(job_illegal_main_handler, pattern="^job_illegal_main$"))
    app.add_handler(CallbackQueryHandler(job_illegal_action_handler, pattern="^job_ill_"))

    app.add_handler(CallbackQueryHandler(inventory_callback_handler, pattern="^(refresh_inv|craft_leg_|sell_menu|do_sell_)"))
    app.add_handler(CallbackQueryHandler(market_callback_handler, pattern="^(refresh_market|my_market_items|market_list_menu|cancel_market_|buy_market_)"))
    app.add_handler(CallbackQueryHandler(trade_callback_handler, pattern="^(accept_trade_|decline_trade_|tr_)"))
    app.add_handler(CallbackQueryHandler(profile_callback_handler, pattern="^(refresh_profile|edit_roster_menu|set_pos_|apply_card_)"))
    app.add_handler(CallbackQueryHandler(match_callback_handler, pattern="^(accept_match_|cancel_match_)"))
    app.add_handler(CallbackQueryHandler(shop_callback_handler, pattern="^(preview_pack_|confirm_pack_|cancel_pack_buy)"))
    app.add_handler(CallbackQueryHandler(freepack_callback_handler, pattern="^claim_freepack_btn$"))
    app.add_handler(CallbackQueryHandler(coin_callback_handler, pattern="^coin_"))
    app.add_handler(CallbackQueryHandler(rps_callback_handler, pattern="^rps_"))
    app.add_handler(CallbackQueryHandler(cancel_minigame_callback, pattern="^cancel_minigame$"))
    app.add_handler(CallbackQueryHandler(admin_shop_pack_callback, pattern="^adm_pack_"))
    # Новые обработчики для магазина и бустеров
    app.add_handler(CallbackQueryHandler(store_callback_handler, pattern=r"^(store_packs|store_boosters|open_store)$"))
    app.add_handler(CallbackQueryHandler(booster_callback_handler, pattern=r"^buy_booster_"))
    app.add_handler(CallbackQueryHandler(inline_callback))

    logger.info("Бот RPL успешно запущен...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
