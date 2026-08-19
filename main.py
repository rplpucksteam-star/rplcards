import os
import re
import time
import random
import asyncio
import logging
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
    ConversationHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise ValueError("BOT_TOKEN не задан!")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL не задан!")

ADMIN_SESSION_MINUTES = 30
FATIGUE_MATCHES_MIN = 4
FATIGUE_MATCHES_MAX = 5
FATIGUE_RECOVERY_MINUTES = 30
UPGRADE_BASE_CHANCE = 15
CRAFT_CHANCE = 25

SELL_PRICES = {
    "Редкая": 500,
    "Очень редкая": 1000,
    "Эпическая": 2500,
    "Мифическая": 5000,
    "Легендарная": 12000,
    "Секретная": 25000,
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
    ADD_PACK_VISIBILITY,
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
    WAITING_TRADE_MONEY,
    WAITING_MARKET_PRICE_INPUT,
    WAITING_RPS_BET,
    WAITING_SLOTS_BET,
    WAITING_DICE_BET,
    WAITING_COIN_BET,
    ADMIN_SHOP_PACK_SELECT,
    ADMIN_SHOP_PACK_HOURS,
) = range(47)


def get_db():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)


def init_db():
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
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
            wheel_discount_percent INTEGER DEFAULT 0,
            wheel_discount_until TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS wheel_discount_percent INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS wheel_discount_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS free_card_cooldown_reset_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS freepack_claimed BOOLEAN DEFAULT FALSE
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS source_channels (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE,
            username TEXT,
            added_by BIGINT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS target_chats (
            id SERIAL PRIMARY KEY,
            chat_id BIGINT UNIQUE,
            link TEXT,
            added_by BIGINT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS support_messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            text TEXT,
            timestamp TEXT,
            answered INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY,
            last_activity INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS bot_config (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collections (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS card_teams (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL,
            emoji TEXT DEFAULT '🏒',
            photo_id TEXT
        )
        """
    )
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_cards (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            count INTEGER DEFAULT 1,
            PRIMARY KEY(user_id, card_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_rosters (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id) ON DELETE CASCADE,
            goalie_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater1_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater2_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater3_id INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            skater4_id INTEGER REFERENCES cards(id) ON DELETE SET NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS card_fatigue (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            matches_played INTEGER DEFAULT 0,
            tired_until TIMESTAMP,
            PRIMARY KEY(user_id, card_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS packs (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            buy_limit INTEGER DEFAULT 0,
            photo_id TEXT,
            available_until TIMESTAMP,
            reveal_cards BOOLEAN DEFAULT TRUE
        )
        """
    )
    cur.execute(
        """
        ALTER TABLE packs ADD COLUMN IF NOT EXISTS reveal_cards BOOLEAN DEFAULT TRUE
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pack_cards (
            pack_id INTEGER REFERENCES packs(id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            PRIMARY KEY(pack_id, card_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_pack_buys (
            user_id BIGINT,
            pack_id INTEGER REFERENCES packs(id) ON DELETE CASCADE,
            buy_count INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, pack_id)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS freepack_config (
            card_id INTEGER PRIMARY KEY REFERENCES cards(id) ON DELETE CASCADE
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            reward_type TEXT NOT NULL,
            reward_value INTEGER NOT NULL,
            max_uses INTEGER DEFAULT 1,
            current_uses INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_promocodes (
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            code TEXT REFERENCES promo_codes(code) ON DELETE CASCADE,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS market (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id) ON DELETE CASCADE,
            price INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS player_stats (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            attempts INTEGER DEFAULT 0,
            goals INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        INSERT INTO bot_config (key, value) VALUES ('gif_goal', ''), ('gif_save', '') ON CONFLICT DO NOTHING
        """
    )

    conn.commit()
    conn.close()


init_db()


def get_or_create_user(user_id, username="", first_name=""):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()

    if not row:
        cur.execute(
            """
            INSERT INTO users (user_id, username, first_name)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (user_id, username, first_name),
        )
        row = cur.fetchone()
    else:
        cur.execute(
            """
            UPDATE users
            SET username = %s, first_name = %s
            WHERE user_id = %s
            """,
            (username, first_name, user_id),
        )

    conn.commit()
    conn.close()
    return row


def check_user_exists(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM users WHERE user_id = %s", (user_id,))
    result = cur.fetchone()
    conn.close()
    return bool(result)


async def check_pm_registered(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return False

    if check_user_exists(user.id):
        return True

    bot_username = context.bot.username or ""
    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💬 Написать боту в ЛС",
                    url=f"https://t.me/{bot_username}?start=start",
                )
            ]
        ]
    )

    if update.callback_query:
        await update.callback_query.answer(
            "⚠️ Сначала напишите боту в ЛС!", show_alert=True
        )
    elif update.message:
        await update.message.reply_text(
            "⚠️ **Сначала напишите боту в личные сообщения.**",
            reply_markup=markup,
            parse_mode="Markdown",
        )
    return False


def get_config(key):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT value FROM bot_config WHERE key = %s", (key,))
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else ""


def set_config(key, value):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO bot_config (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def parse_dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def choose_card_for_user(cur, user_id, cards):
    if not cards:
        return None

    ids = [card["id"] for card in cards]
    cur.execute(
        """
        SELECT card_id
        FROM user_cards
        WHERE user_id = %s AND card_id = ANY(%s) AND count > 0
        """,
        (user_id, ids),
    )
    owned = {row["card_id"] for row in cur.fetchall()}
    fresh = [card for card in cards if card["id"] not in owned]
    return random.choice(fresh or cards)


def choose_new_card_strict(cur, user_id, cards):
    if not cards:
        return None

    ids = [card["id"] for card in cards]
    cur.execute(
        """
        SELECT card_id
        FROM user_cards
        WHERE user_id = %s AND card_id = ANY(%s) AND count > 0
        """,
        (user_id, ids),
    )
    owned = {row["card_id"] for row in cur.fetchall()}
    fresh = [card for card in cards if card["id"] not in owned]
    return random.choice(fresh) if fresh else None


def is_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT last_activity FROM admins WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    if datetime.now().timestamp() - row["last_activity"] < ADMIN_SESSION_MINUTES * 60:
        return True

    remove_admin(user_id)
    return False


def add_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO admins (user_id, last_activity)
        VALUES (%s, %s)
        ON CONFLICT (user_id)
        DO UPDATE SET last_activity = EXCLUDED.last_activity
        """,
        (user_id, int(datetime.now().timestamp())),
    )
    conn.commit()
    conn.close()


def update_admin_activity(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE admins SET last_activity = %s WHERE user_id = %s",
        (int(datetime.now().timestamp()), user_id),
    )
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()


def check_credentials(login, password):
    return {
        "goyda1488": "goydarpl",
        "rzk1488": "rzksigma",
    }.get(login) == password


def main_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["🏠 Главное меню", "🃏 Бесплатная карта"],
            ["🎒 Инвентарь", "🛒 Торговая площадка"],
            ["🏒 Состав и Профиль", "⚔️ Искать игру"],
            ["🛒 Магазин Паков", "🏆 Топ MMR"],
            ["🤝 Трейд", "🎁 Промокод"],
            ["🎮 Мини-игры", "🎡 Колесо удачи"],
            ["🎁 Ежедневный бонус"],
        ],
        resize_keyboard=True,
    )


def admin_menu_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["➕ Добавить каналы", "➕ Добавить чаты"],
            ["📩 Проверить поддержку", "⚙️ Настройки"],
            ["🎮 Настройки игры", "🃏 Карточки"],
            ["📦 Выставить пак в магазин", "🔍 Инвентарь игрока"],
            ["👥 Список игроков", "🚪 Выйти"],
        ],
        resize_keyboard=True,
    )


def card_admin_keyboard():
    return ReplyKeyboardMarkup(
        [
            ["📁 Создать коллекцию", "🛡 Создать команду"],
            ["❌ Удалить команду", "🃏 Добавить карточку"],
            ["❌ Удалить карточку", "📦 Добавить пак"],
            ["📦 Настроить стартовый набор", "🎁 Выдать карточку игроку"],
            ["💰 Выдать деньги", "🎟 Создать промокод"],
            ["⬅️ Выйти из настройки карточек"],
        ],
        resize_keyboard=True,
    )


def welcome_inline_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("💬 Наш Discord", callback_data="discord")],
            [InlineKeyboardButton("🌐 Наш сайт", callback_data="website")],
            [InlineKeyboardButton("🆘 Поддержка", callback_data="support")],
            [InlineKeyboardButton("🏒 Дуэль буллитов", callback_data="duel")],
        ]
    )


def bet_cancel_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Назад", callback_data="cancel_minigame")]]
    )


def duel_shot_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🥅 Левая девятка", callback_data="shot_left")],
            [InlineKeyboardButton("🥅 Правая девятка", callback_data="shot_right")],
            [InlineKeyboardButton("🧤 Домик", callback_data="shot_five")],
            [InlineKeyboardButton("🥅 Низ в угол", callback_data="shot_low")],
        ]
    )


COUNTRIES = [
    "Russian Federation",
    "USA",
    "Canada",
    "Finland",
    "Sweden",
    "Czech Republic",
    "Slovakia",
    "Germany",
    "Switzerland",
    "Latvia",
    "Belarus",
    "Kazakhstan",
    "UK",
    "France",
    "Austria",
    "Norway",
    "Denmark",
    "Japan",
    "China",
]


async def grant_free_pack_to_user(user_id, context):
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT freepack_claimed FROM users WHERE user_id = %s", (user_id,))
    user = cur.fetchone()

    if user and user["freepack_claimed"]:
        conn.close()
        return False, "❌ Вы уже получили стартовый набор!"

    cur.execute("SELECT card_id FROM freepack_config")
    configured = cur.fetchall()

    if configured:
        card_ids = [row["card_id"] for row in configured]
    else:
        cur.execute("SELECT id FROM cards WHERE position = 'Goalie' LIMIT 1")
        goalie = cur.fetchone()
        cur.execute("SELECT id FROM cards WHERE position = 'Skater' LIMIT 4")
        skaters = cur.fetchall()

        if not goalie or len(skaters) < 4:
            conn.close()
            return False, "❌ В базе недостаточно карт для стартового состава."

        card_ids = [goalie["id"]] + [row["id"] for row in skaters]

    cur.execute("SELECT * FROM cards WHERE id = ANY(%s)", (card_ids,))
    cards = cur.fetchall()

    for card_id in card_ids:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user_id, card_id),
        )

    goalie_id = next(
        (card["id"] for card in cards if card["position"] == "Goalie"), None
    )
    skaters = [card["id"] for card in cards if card["position"] == "Skater"]

    cur.execute(
        """
        INSERT INTO user_rosters
        (user_id, goalie_id, skater1_id, skater2_id, skater3_id, skater4_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            goalie_id = COALESCE(user_rosters.goalie_id, EXCLUDED.goalie_id),
            skater1_id = COALESCE(user_rosters.skater1_id, EXCLUDED.skater1_id),
            skater2_id = COALESCE(user_rosters.skater2_id, EXCLUDED.skater2_id),
            skater3_id = COALESCE(user_rosters.skater3_id, EXCLUDED.skater3_id),
            skater4_id = COALESCE(user_rosters.skater4_id, EXCLUDED.skater4_id)
        """,
        (
            user_id,
            goalie_id,
            skaters[0] if len(skaters) > 0 else None,
            skaters[1] if len(skaters) > 1 else None,
            skaters[2] if len(skaters) > 2 else None,
            skaters[3] if len(skaters) > 3 else None,
        ),
    )

    cur.execute(
        "UPDATE users SET freepack_claimed = TRUE WHERE user_id = %s",
        (user_id,),
    )

    conn.commit()
    conn.close()

    return True, "🎉 Стартовый набор получен! Карточки установлены в состав."


async def freepack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    _, text = await grant_free_pack_to_user(user.id, context)
    await update.message.reply_text(text, parse_mode="Markdown")


async def freepack_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "claim_freepack_btn":
        _, text = await grant_free_pack_to_user(query.from_user.id, context)
        await query.message.edit_text(text, parse_mode="Markdown")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        "👋 Добро пожаловать в Russian Puck League!\n\n"
        "Собирайте коллекцию, улучшайте состав и побеждайте в матчах.",
        reply_markup=main_menu_keyboard(),
        parse_mode="Markdown",
    )


async def daily_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_daily_claim, daily_streak FROM users WHERE user_id = %s",
        (user.id,),
    )
    row = cur.fetchone()
    now = datetime.now()
    last = parse_dt(row["last_daily_claim"]) if row else None
    streak = row["daily_streak"] if row else 0

    if last:
        diff = now - last
        if diff.total_seconds() < 86400:
            remaining = timedelta(seconds=86400) - diff
            hours, seconds = divmod(int(remaining.total_seconds()), 3600)
            minutes = seconds // 60
            conn.close()
            await update.message.reply_text(
                f"⏳ Следующий бонус через {hours} ч {minutes} мин.\n"
                f"🔥 Текущий стрик: {streak} дней",
                parse_mode="Markdown",
            )
            return

        if diff.total_seconds() > 172800:
            streak = 0

    streak = streak % 7 + 1
    reward = ""

    if streak in (1, 2, 3):
        amount = streak * 5000
        cur.execute(
            """
            UPDATE users
            SET balance = balance + %s,
                daily_streak = %s,
                last_daily_claim = %s
            WHERE user_id = %s
            """,
            (amount, streak, now, user.id),
        )
        reward = f"💳 +{amount} RPLCoin"

    elif streak == 4:
        cur.execute(
            """
            UPDATE users
            SET daily_streak = %s, last_daily_claim = %s
            WHERE user_id = %s
            """,
            (streak, now, user.id),
        )
        reward = "🏷 Скидка 15% на следующую покупку"

    elif streak == 5:
        cur.execute(
            """
            UPDATE users
            SET free_card_cooldown_reset_until = %s,
                daily_streak = %s,
                last_daily_claim = %s
            WHERE user_id = %s
            """,
            (datetime.max, streak, now, user.id),
        )
        reward = "✨ Сброс кулдауна бесплатной карты"

    elif streak == 6:
        cur.execute("SELECT * FROM cards WHERE rarity != 'Секретная'")
        cards = cur.fetchall()
        card = choose_card_for_user(cur, user.id, cards)
        if card:
            cur.execute(
                """
                INSERT INTO user_cards (user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, card["id"]),
            )
            reward = f"🃏 {card['nickname']} ({card['ovr']} OVR)"
        else:
            cur.execute(
                "UPDATE users SET balance = balance + 50000 WHERE user_id = %s",
                (user.id,),
            )
            reward = "💳 +50 000 RPLCoin"

        cur.execute(
            """
            UPDATE users SET daily_streak = %s, last_daily_claim = %s
            WHERE user_id = %s
            """,
            (streak, now, user.id),
        )

    else:
        cur.execute("SELECT * FROM cards WHERE rarity IN ('Эпическая', 'Мифическая')")
        cards = cur.fetchall()
        card = choose_card_for_user(cur, user.id, cards)
        if card:
            cur.execute(
                """
                INSERT INTO user_cards (user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, card["id"]),
            )
            reward = f"🌟 {card['nickname']} ({card['ovr']} OVR)"
        else:
            cur.execute(
                "UPDATE users SET balance = balance + 100000 WHERE user_id = %s",
                (user.id,),
            )
            reward = "💳 +100 000 RPLCoin"

        cur.execute(
            """
            UPDATE users SET daily_streak = %s, last_daily_claim = %s
            WHERE user_id = %s
            """,
            (streak, now, user.id),
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎁 **Ежедневный бонус {streak}/7 получен!**\n\n{reward}",
        parse_mode="Markdown",
    )


def get_active_discount(cur, user_id):
    cur.execute(
        """
        SELECT wheel_discount_percent, wheel_discount_until
        FROM users WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return 0

    until = parse_dt(row["wheel_discount_until"])
    if row["wheel_discount_percent"] and until and until > datetime.now():
        return min(50, max(0, int(row["wheel_discount_percent"])))
    return 0


def discounted_price(price, discount):
    return max(1, int(round(price * (100 - discount) / 100)))


async def wheel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT balance, last_wheel_spin FROM users WHERE user_id = %s",
        (user.id,),
    )
    row = cur.fetchone()
    conn.close()

    now = datetime.now()
    last_spin = parse_dt(row["last_wheel_spin"]) if row else None

    if last_spin and now - last_spin < timedelta(hours=36):
        remaining = timedelta(hours=36) - (now - last_spin)
        hours, seconds = divmod(int(remaining.total_seconds()), 3600)
        await update.message.reply_text(
            f"⏳ Колесо можно крутить через **{hours} ч {seconds // 60} мин**.",
            parse_mode="Markdown",
        )
        return

    cost = 10000
    if row["balance"] < cost:
        await update.message.reply_text(
            f"❌ Прокрутка стоит **{cost} RPLCoin**.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("🎡 Колесо вращается…", parse_mode="Markdown")
    await asyncio.sleep(2)

    prizes = [
        "money",
        "card",
        "discount",
        "reset",
        "nothing",
        "nothing",
        "money",
        "card",
    ]
    prize = random.choice(prizes)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE users
        SET balance = balance - %s, last_wheel_spin = %s
        WHERE user_id = %s
        """,
        (cost, now, user.id),
    )

    if prize == "money":
        amount = random.randint(5000, 100000)
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (amount, user.id),
        )
        result = f"💳 Вы выиграли **+{amount} RPLCoin**!"

    elif prize == "card":
        cur.execute("SELECT * FROM cards WHERE rarity != 'Секретная'")
        cards = cur.fetchall()
        card = choose_card_for_user(cur, user.id, cards)
        if card:
            cur.execute(
                """
                INSERT INTO user_cards (user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT (user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, card["id"]),
            )
            result = f"🃏 Вам выпала **{card['nickname']} ({card['ovr']} OVR)**!"
        else:
            cur.execute(
                "UPDATE users SET balance = balance + 20000 WHERE user_id = %s",
                (user.id,),
            )
            result = "💳 Все карты уже собраны. Компенсация: +20 000 RPLCoin."

    elif prize == "discount":
        percent = random.randint(10, 30)
        until = now + timedelta(hours=24)
        cur.execute(
            """
            UPDATE users
            SET wheel_discount_percent = %s,
                wheel_discount_until = %s
            WHERE user_id = %s
            """,
            (percent, until, user.id),
        )
        result = (
            f"🏷 Вы выиграли скидку {percent}% на 24 часа!\n"
            "Она действует в магазине паков и на торговой площадке."
        )

    elif prize == "reset":
        cur.execute(
            """
            UPDATE users
            SET free_card_cooldown_reset_until = %s
            WHERE user_id = %s
            """,
            (datetime.max, user.id),
        )
        result = "✨ Кулдаун бесплатной карты сброшен!"

    else:
        result = "💨 В этот раз ничего. Повезёт в следующем вращении!"

    conn.commit()
    conn.close()

    await msg.edit_text(
        f"🎡 **Колесо остановилось!**\n\n{result}",
        parse_mode="Markdown",
    )


async def rplcards_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    data = get_or_create_user(user.id, user.username or "", user.first_name or "")
    now = datetime.now()

    last_claim = parse_dt(data["last_card_claim"])
    reset_until = parse_dt(data["free_card_cooldown_reset_until"])
    bypass = reset_until and now < reset_until

    if not bypass and last_claim and now < last_claim + timedelta(hours=8):
        wait = last_claim + timedelta(hours=8) - now
        hours, seconds = divmod(int(wait.total_seconds()), 3600)
        await update.message.reply_text(
            f"⏳ Следующая бесплатная карта через **{hours} ч {seconds // 60} мин**.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("🃏 Открываем бесплатную карту…")
    await asyncio.sleep(2)

    conn = get_db()
    cur = conn.cursor()
    rarity = random.choices(
        ["Редкая", "Очень редкая", "Эпическая", "Мифическая", "Легендарная"],
        weights=[50, 28, 14, 6, 2],
        k=1,
    )[0]

    cur.execute(
        """
        SELECT c.*, col.name AS collection_name,
               t.name AS team_name, t.emoji AS team_emoji
        FROM cards c
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN card_teams t ON c.team_id = t.id
        WHERE c.rarity = %s
        """,
        (rarity,),
    )
    cards = cur.fetchall()

    if not cards:
        cur.execute(
            """
            SELECT c.*, col.name AS collection_name,
                   t.name AS team_name, t.emoji AS team_emoji
            FROM cards c
            JOIN collections col ON c.collection_id = col.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE c.rarity != 'Секретная'
            """
        )
        cards = cur.fetchall()

    card = choose_new_card_strict(cur, user.id, cards)

    if not card:
        cur.execute(
            """
            SELECT c.*, col.name AS collection_name,
                   t.name AS team_name, t.emoji AS team_emoji
            FROM cards c
            JOIN collections col ON c.collection_id = col.id
            LEFT JOIN card_teams t ON c.team_id = t.id
            WHERE c.rarity != 'Секретная'
            """
        )
        card = choose_new_card_strict(cur, user.id, cur.fetchall())

    if not card:
        cur.execute(
            """
            UPDATE users
            SET balance = balance + 3000,
                last_card_claim = %s,
                free_card_cooldown_reset_until = NULL
            WHERE user_id = %s
            """,
            (now, user.id),
        )
        conn.commit()
        conn.close()
        await msg.edit_text(
            "🎉 Все доступные карты уже собраны!\n"
            "Вместо дубликата начислено **3 000 RPLCoin**.",
            parse_mode="Markdown",
        )
        return

    cur.execute(
        """
        INSERT INTO user_cards (user_id, card_id, count)
        VALUES (%s, %s, 1)
        ON CONFLICT (user_id, card_id)
        DO UPDATE SET count = user_cards.count + 1
        """,
        (user.id, card["id"]),
    )
    cur.execute(
        """
        UPDATE users
        SET last_card_claim = %s,
            free_card_cooldown_reset_until = NULL
        WHERE user_id = %s
        """,
        (now, user.id),
    )

    conn.commit()
    conn.close()

    team = (
        f"{card['team_emoji'] or '🏒'} {card['team_name']}"
        if card["team_name"]
        else "Без команды"
    )
    text = (
        "🔥 **Вам выпала карточка!**\n\n"
        "┏━━━━━━━━━━━━━━━━━━━━┓\n"
        f"┃ 👤 {card['nickname']}\n"
        f"┃ 📁 {card['collection_name']}\n"
        f"┃ 🏒 {card['position']}\n"
        f"┃ ⭐ {card['ovr']} OVR\n"
        f"┃ {team}\n"
        f"┃ 🌍 {card['country']}\n"
        f"┃ ✨ {card['rarity']}\n"
        "┗━━━━━━━━━━━━━━━━━━━━┛"
    )

    try:
        await msg.delete()
    except Exception:
        pass

    if card["image_id"]:
        try:
            await update.message.reply_photo(
                card["image_id"], caption=text, parse_mode="Markdown"
            )
            return
        except Exception:
            pass

    await update.message.reply_text(text, parse_mode="Markdown")


async def inventory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    get_or_create_user(
        update.effective_user.id,
        update.effective_user.username or "",
        update.effective_user.first_name or "",
    )

    await show_inventory(update, context)


async def show_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT uc.count, c.*, col.name AS col_name,
               t.name AS team_name, t.emoji AS team_emoji,
               cf.matches_played, cf.tired_until
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN card_teams t ON c.team_id = t.id
        LEFT JOIN card_fatigue cf
          ON cf.user_id = uc.user_id AND cf.card_id = uc.card_id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr DESC, c.nickname
        """,
        (user.id,),
    )
    owned = cur.fetchall()

    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.position, c.rarity, col.name
        FROM cards c
        JOIN collections col ON c.collection_id = col.id
        LEFT JOIN user_cards uc
          ON uc.user_id = %s AND uc.card_id = c.id AND uc.count > 0
        WHERE uc.card_id IS NULL
        ORDER BY c.ovr DESC, c.nickname
        """,
        (user.id,),
    )
    missing = cur.fetchall()
    conn.close()

    text = "🎒 **КОЛЛЕКЦИЯ КАРТОЧЕК**\n\n"

    if owned:
        text += "✅ **Есть у вас:**\n"
        for card in owned:
            tired_until = parse_dt(card["tired_until"])
            if tired_until and tired_until > datetime.now():
                status = f"😴 до {tired_until.strftime('%H:%M')}"
            else:
                status = f"⚡ {card['matches_played'] or 0}/{FATIGUE_MATCHES_MAX}"
            text += (
                f"• ID `{card['id']}` — **{card['nickname']}** "
                f"({card['ovr']} OVR, {card['position']}) "
                f"×{card['count']} [{status}]\n"
            )
    else:
        text += "У вас пока нет карточек.\n"

    if missing:
        text += "\n❌ **Пока отсутствуют:**\n"
        for card in missing[:80]:
            text += (
                f"• ID `{card['id']}` — {card['nickname']} "
                f"({card['ovr']} OVR, {card['rarity']})\n"
            )
        if len(missing) > 80:
            text += f"… и ещё {len(missing) - 80} карточек.\n"
    else:
        text += "\n🏆 **Поздравляем, коллекция собрана полностью!**\n"

    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🚀 Апгрейдер", callback_data="upgrade_menu")],
            [InlineKeyboardButton("🔨 Крафт 3 карт", callback_data="craft_menu")],
            [InlineKeyboardButton("🏷 Выставить на рынок", callback_data="market_list_menu")],
            [InlineKeyboardButton("💰 Продать системе", callback_data="sell_menu")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_inv")],
        ]
    )

    if query:
        await query.answer()
        try:
            await query.message.edit_text(
                text, reply_markup=markup, parse_mode="Markdown"
            )
        except Exception:
            await context.bot.send_message(
                user.id, text, reply_markup=markup, parse_mode="Markdown"
            )
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )


async def show_sell_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT uc.count, c.id, c.nickname, c.ovr, c.rarity
        FROM user_cards uc
        JOIN cards c ON uc.card_id = c.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr DESC
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    buttons = []
    for card in cards:
        price = SELL_PRICES.get(card["rarity"], 300)
        buttons.append(
            [
                InlineKeyboardButton(
                    f"Продать {card['nickname']} ({card['ovr']}) — {price}",
                    callback_data=f"do_sell_{card['id']}",
                )
            ]
        )
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")]
    )

    await query.edit_message_text(
        "💰 **Продажа системе**\n\nНажмите на карточку, чтобы продать одну копию.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def inventory_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "refresh_inv":
        await show_inventory(update, context)
        return

    if data == "sell_menu":
        await show_sell_menu(update, context)
        return

    if data.startswith("do_sell_"):
        card_id = int(data.rsplit("_", 1)[1])
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT uc.count, c.nickname, c.rarity
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND uc.card_id = %s AND uc.count > 0
            """,
            (user.id, card_id),
        )
        card = cur.fetchone()

        if not card:
            conn.close()
            await query.answer("Карточка уже отсутствует.", show_alert=True)
            return

        price = SELL_PRICES.get(card["rarity"], 300)
        cur.execute(
            """
            UPDATE user_cards SET count = count - 1
            WHERE user_id = %s AND card_id = %s
            """,
            (user.id, card_id),
        )
        cur.execute(
            """
            DELETE FROM user_cards
            WHERE user_id = %s AND card_id = %s AND count <= 0
            """,
            (user.id, card_id),
        )
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (price, user.id),
        )
        conn.commit()
        conn.close()

        await query.answer(f"Продано за {price} RPLCoin.", show_alert=True)
        await show_sell_menu(update, context)
        return

    if data == "craft_menu":
        await show_craft_menu(update, context)
        return

    if data.startswith("craft_group_"):
        await craft_cards(update, context)
        return

    if data == "upgrade_menu":
        await show_upgrade_sources(update, context)
        return

    if data.startswith("upgrade_source_"):
        await show_upgrade_targets(update, context)
        return

    if data.startswith("upgrade_target_"):
        await show_upgrade_confirm(update, context)
        return

    if data.startswith("upgrade_confirm_"):
        await execute_upgrade(update, context)


async def show_craft_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.ovr, COUNT(*) AS amount
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s AND uc.count > 0
        GROUP BY c.ovr
        HAVING SUM(uc.count) >= 3
        ORDER BY c.ovr
        """,
        (user.id,),
    )
    groups = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"🔨 ОВР {row['ovr']} — {row['amount']} карт",
                callback_data=f"craft_group_{row['ovr']}",
            )
        ]
        for row in groups
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")]
    )

    await query.edit_message_text(
        "🔨 **КРАФТ КАРТОЧЕК**\n\n"
        "Выберите ОВР. Нужно 3 карты с разбросом не более 2 OVR.\n"
        "Шанс получить улучшенную карту — **25%**.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def craft_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    base_ovr = int(query.data.rsplit("_", 1)[1])

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT uc.card_id, uc.count, c.ovr, c.nickname
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s
          AND uc.count > 0
          AND c.ovr BETWEEN %s AND %s
        ORDER BY c.ovr
        """,
        (user.id, base_ovr - 2, base_ovr + 2),
    )
    rows = cur.fetchall()

    available = []
    for row in rows:
        available.extend([row["card_id"]] * min(row["count"], 3 - len(available)))
        if len(available) >= 3:
            break

    if len(available) < 3:
        conn.close()
        await query.answer("Нужно 3 подходящие карточки.", show_alert=True)
        return

    target_ovr = base_ovr + random.randint(3, 5)
    cur.execute(
        """
        SELECT *
        FROM cards
        WHERE ovr BETWEEN %s AND %s
        ORDER BY RANDOM()
        LIMIT 1
        """,
        (target_ovr, target_ovr + 2),
    )
    result_card = cur.fetchone()

    for card_id in available:
        cur.execute(
            """
            UPDATE user_cards SET count = count - 1
            WHERE user_id = %s AND card_id = %s AND count > 0
            """,
            (user.id, card_id),
        )
    cur.execute(
        """
        DELETE FROM user_cards
        WHERE user_id = %s AND count <= 0
        """,
        (user.id,),
    )

    success = random.random() < CRAFT_CHANCE / 100
    text = ""

    if success and result_card:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, result_card["id"]),
        )
        text = (
            f"🎉 КРАФТ УСПЕШЕН!\n\n"
            f"Вы получили {result_card['nickname']} "
            f"({result_card['ovr']} OVR)!"
        )
    else:
        text = (
            "💥 Крафт не удался.\n"
            "Три карточки были потрачены, но в следующий раз обязательно повезёт."
        )

    conn.commit()
    conn.close()
    await query.answer("Крафт завершён.", show_alert=True)
    await query.edit_message_text(text, parse_mode="Markdown")


async def show_upgrade_sources(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.position, uc.count
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"{card['nickname']} — {card['ovr']} OVR",
                callback_data=f"upgrade_source_{card['id']}",
            )
        ]
        for card in cards
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")]
    )

    await query.edit_message_text(
        "🚀 **АПГРЕЙДЕР**\n\nВыберите свою карточку, которую хотите улучшить:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def show_upgrade_targets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    source_id = int(query.data.rsplit("_", 1)[1])

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.position, c.rarity
        FROM cards c
        WHERE c.ovr > (
            SELECT ovr FROM cards WHERE id = %s
        )
        ORDER BY c.ovr, c.nickname
        """,
        (source_id,),
    )
    targets = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"{card['nickname']} — {card['ovr']} OVR",
                callback_data=f"upgrade_target_{source_id}_{card['id']}",
            )
        ]
        for card in targets[:100]
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="upgrade_menu")]
    )

    await query.edit_message_text(
        "🎯 **Выберите карту для выпадения:**\n"
        "Базовый шанс — **15%**. Шанс не превышает 40%.",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def show_upgrade_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    source_id, target_id = map(int, query.data.split("_")[2:])

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT nickname, ovr FROM cards WHERE id = %s",
        (source_id,),
    )
    source = cur.fetchone()
    cur.execute(
        "SELECT nickname, ovr, rarity FROM cards WHERE id = %s",
        (target_id,),
    )
    target = cur.fetchone()
    conn.close()

    if not source or not target:
        await query.answer("Карточка не найдена.", show_alert=True)
        return

    diff = target["ovr"] - source["ovr"]
    chance = max(5, min(40, upgrade_chance(diff)))
    await query.edit_message_text(
        f"🚀 **ПОДТВЕРЖДЕНИЕ АПГРЕЙДА**\n\n"
        f"🃏 Ваша карта: **{source['nickname']} ({source['ovr']} OVR)**\n"
        f"🎯 Цель: **{target['nickname']} ({target['ovr']} OVR)**\n"
        f"🎲 Шанс успеха: **{chance}%**\n\n"
        "При неудаче исходная карта будет потеряна.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Подтвердить",
                        callback_data=f"upgrade_confirm_{source_id}_{target_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Отмена", callback_data="refresh_inv"
                    )
                ],
            ]
        ),
        parse_mode="Markdown",
    )


def upgrade_chance(diff):
    if diff <= 2:
        return 25
    if diff <= 5:
        return 15
    if diff <= 8:
        return 10
    if diff <= 12:
        return 7
    return 5


async def execute_upgrade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    source_id, target_id = map(int, query.data.split("_")[2:])

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.ovr AS source_ovr, c.nickname AS source_name,
               uc.count
        FROM cards c
        JOIN user_cards uc ON uc.card_id = c.id
        WHERE c.id = %s AND uc.user_id = %s AND uc.count > 0
        """,
        (source_id, user.id),
    )
    source = cur.fetchone()
    cur.execute(
        "SELECT nickname, ovr FROM cards WHERE id = %s",
        (target_id,),
    )
    target = cur.fetchone()

    if not source or not target or target["ovr"] <= source["source_ovr"]:
        conn.close()
        await query.answer("❌ Исходная карта недоступна.", show_alert=True)
        return

    chance = max(5, min(40, upgrade_chance(target["ovr"] - source["source_ovr"])))

    cur.execute(
        """
        UPDATE user_cards SET count = count - 1
        WHERE user_id = %s AND card_id = %s AND count > 0
        """,
        (user.id, source_id),
    )
    cur.execute(
        """
        DELETE FROM user_cards
        WHERE user_id = %s AND card_id = %s AND count <= 0
        """,
        (user.id, source_id),
    )

    success = random.random() < chance / 100

    if success:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, target_id),
        )
        text = (
            f"🎉 АПГРЕЙД УСПЕШЕН!\n\n"
            f"Выпала карта {target['nickname']} ({target['ovr']} OVR)!"
        )
    else:
        text = (
            f"💥 Апгрейд не удался.\n"
            f"Карта сгорела. Шанс был {chance}%."
        )

    conn.commit()
    conn.close()
    await query.edit_message_text(text, parse_mode="Markdown")


async def cardshop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await show_market(update, context)


async def show_market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.id AS market_id, m.price, m.seller_id,
               c.nickname, c.position, c.ovr, c.rarity,
               u.username, u.first_name
        FROM market m
        JOIN cards c ON c.id = m.card_id
        JOIN users u ON u.user_id = m.seller_id
        ORDER BY m.id DESC
        LIMIT 30
        """
    )
    items = cur.fetchall()
    discount = get_active_discount(cur, user.id)
    conn.close()

    text = (
        "🛒 **ТОРГОВАЯ ПЛОЩАДКА**\n"
        f"🏷 Ваша скидка: **{discount}%**\n\n"
    )
    buttons = []

    for item in items:
        final_price = discounted_price(item["price"], discount)
        seller = (
            f"@{item['username']}"
            if item["username"]
            else item["first_name"] or str(item["seller_id"])
        )
        text += (
            f"🏷 **#{item['market_id']}** — {item['nickname']} "
            f"({item['ovr']} OVR) — **{final_price} RPLCoin** "
            f"(продавец: {seller})\n"
        )
        if item["seller_id"] != user.id:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"Купить #{item['market_id']} — {final_price}",
                        callback_data=f"buy_market_{item['market_id']}",
                    )
                ]
            )

    buttons.append(
        [InlineKeyboardButton("📦 Мои лоты", callback_data="my_market_items")]
    )
    buttons.append(
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_market")]
    )

    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.answer()
        await query.message.edit_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )


async def market_start_list_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.position, c.rarity, uc.count
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr DESC
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"{card['nickname']} ({card['ovr']} OVR) ×{card['count']}",
                callback_data=f"select_mcard_{card['id']}",
            )
        ]
        for card in cards
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")]
    )

    await query.edit_message_text(
        "🏷 Выберите карточку для выставления:",
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def show_my_market_items(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT m.id, m.price, c.nickname, c.ovr
        FROM market m
        JOIN cards c ON c.id = m.card_id
        WHERE m.seller_id = %s
        ORDER BY m.id DESC
        """,
        (user.id,),
    )
    items = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"❌ Снять #{item['id']} {item['nickname']}",
                callback_data=f"cancel_market_{item['id']}",
            )
        ]
        for item in items
    ]
    buttons.append(
        [InlineKeyboardButton("🔙 Назад", callback_data="refresh_market")]
    )

    text = "📦 **Ваши лоты:**\n\n"
    text += (
        "\n".join(
            f"#{item['id']} — {item['nickname']} ({item['ovr']} OVR), "
            f"{item['price']} RPLCoin"
            for item in items
        )
        or "Активных лотов нет."
    )

    await query.edit_message_text(
        text, reply_markup=InlineKeyboardMarkup(buttons), parse_mode="Markdown"
    )


async def execute_market_list_price(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите цену числом.")
        return WAITING_MARKET_PRICE_INPUT

    if not 1 <= price <= 999999:
        await update.message.reply_text("❌ Цена должна быть от 1 до 999999.")
        return WAITING_MARKET_PRICE_INPUT

    user = update.effective_user
    card_id = context.user_data.get("m_card_id")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT count FROM user_cards
        WHERE user_id = %s AND card_id = %s AND count > 0
        """,
        (user.id, card_id),
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        await update.message.reply_text("❌ Карточка больше недоступна.")
        return ConversationHandler.END

    cur.execute(
        """
        UPDATE user_cards SET count = count - 1
        WHERE user_id = %s AND card_id = %s
        """,
        (user.id, card_id),
    )
    cur.execute(
        """
        DELETE FROM user_cards
        WHERE user_id = %s AND card_id = %s AND count <= 0
        """,
        (user.id, card_id),
    )
    cur.execute(
        """
        INSERT INTO market (seller_id, card_id, price)
        VALUES (%s, %s, %s)
        """,
        (user.id, card_id, price),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"✅ Карточка выставлена за **{price} RPLCoin**.",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def market_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "refresh_market":
        await show_market(update, context)
        return

    if data == "my_market_items":
        await show_my_market_items(update, context)
        return

    if data == "market_list_menu":
        await market_start_list_card(update, context)
        return

    if data.startswith("select_mcard_"):
        context.user_data["m_card_id"] = int(data.rsplit("_", 1)[1])
        await query.message.reply_text(
            "💲 Введите цену продажи:", parse_mode="Markdown"
        )
        return WAITING_MARKET_PRICE_INPUT

    if data.startswith("cancel_market_"):
        market_id = int(data.rsplit("_", 1)[1])
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT card_id FROM market
            WHERE id = %s AND seller_id = %s
            """,
            (market_id, user.id),
        )
        item = cur.fetchone()

        if not item:
            conn.close()
            await query.answer("Лот уже отсутствует.", show_alert=True)
            return

        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, item["card_id"]),
        )
        cur.execute("DELETE FROM market WHERE id = %s", (market_id,))
        conn.commit()
        conn.close()

        await query.answer("Карточка возвращена.", show_alert=True)
        await show_my_market_items(update, context)
        return

    if data.startswith("buy_market_"):
        market_id = int(data.rsplit("_", 1)[1])
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM market WHERE id = %s FOR UPDATE", (market_id,))
        item = cur.fetchone()

        if not item:
            conn.rollback()
            conn.close()
            await query.answer("Лот уже продан.", show_alert=True)
            return

        if item["seller_id"] == user.id:
            conn.rollback()
            conn.close()
            await query.answer("Нельзя купить собственный лот.", show_alert=True)
            return

        discount = get_active_discount(cur, user.id)
        final_price = discounted_price(item["price"], discount)

        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        balance = cur.fetchone()["balance"]

        if balance < final_price:
            conn.rollback()
            conn.close()
            await query.answer("Недостаточно средств.", show_alert=True)
            return

        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (final_price, user.id),
        )
        cur.execute(
            """
            UPDATE users SET balance = balance + %s
            WHERE user_id = %s
            """,
            (item["price"], item["seller_id"]),
        )
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, item["card_id"]),
        )
        cur.execute("DELETE FROM market WHERE id = %s", (market_id,))
        conn.commit()
        conn.close()

        await query.answer("🎉 Карточка куплена!", show_alert=True)
        await show_market(update, context)


active_trades = {}


def trade_has_user(user_id):
    return any(
        user_id in (trade["p1"], trade["p2"])
        for trade in active_trades.values()
    )


async def trade_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    if not context.args:
        await update.message.reply_text(
            "🤝 Пример: `/trade @username` или `/trade 123456789`",
            parse_mode="Markdown",
        )
        return

    target = context.args[0].replace("@", "")
    conn = get_db()
    cur = conn.cursor()

    if target.isdigit():
        cur.execute("SELECT * FROM users WHERE user_id = %s", (int(target),))
    else:
        cur.execute("SELECT * FROM users WHERE username = %s", (target,))
    target_user = cur.fetchone()
    conn.close()

    if not target_user:
        await update.message.reply_text("❌ Пользователь не найден.")
        return

    target_id = target_user["user_id"]
    if target_id == user.id:
        await update.message.reply_text("❌ Нельзя торговать с самим собой.")
        return

    if trade_has_user(user.id) or trade_has_user(target_id):
        await update.message.reply_text("❌ Один из игроков уже в трейде.")
        return

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Принять",
                    callback_data=f"accept_trade_{user.id}_{target_id}",
                ),
                InlineKeyboardButton(
                    "❌ Отклонить",
                    callback_data=f"decline_trade_{user.id}_{target_id}",
                ),
            ]
        ]
    )

    await update.message.reply_text(
        f"🤝 Предложение отправлено игроку **{target_user['first_name'] or target}**.",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            target_id,
            f"🤝 Игрок {user.first_name or user.username or user.id} "
            "предлагает обмен.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception:
        await update.message.reply_text(
            "❌ Не удалось отправить предложение. Возможно, игрок заблокировал бота."
        )


async def render_trade_text(trade):
    conn = get_db()
    cur = conn.cursor()

    def name(user_id):
        cur.execute(
            "SELECT first_name, username FROM users WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
        return (
            row["first_name"]
            if row and row["first_name"]
            else row["username"]
            if row
            else str(user_id)
        )

    def cards_text(ids):
        if not ids:
            return "  — нет\n"
        cur.execute(
            """
            SELECT nickname, ovr
            FROM cards
            WHERE id = ANY(%s)
            """,
            (ids,),
        )
        rows = cur.fetchall()
        return "".join(
            f"  • {row['nickname']} ({row['ovr']} OVR)\n" for row in rows
        )

    n1 = name(trade["p1"])
    n2 = name(trade["p2"])
    conn.close()

    return (
        "🤝 **ОКНО ОБМЕНА**\n\n"
        f"🔴 **{n1}** {'✅' if trade['p1_ready'] else '⏳'}\n"
        f"💳 Монеты: **{trade['p1_money']}**\n"
        f"🃏 Карты:\n{cards_text(trade['p1_cards'])}\n"
        "──────────────\n"
        f"🔵 **{n2}** {'✅' if trade['p2_ready'] else '⏳'}\n"
        f"💳 Монеты: **{trade['p2_money']}**\n"
        f"🃏 Карты:\n{cards_text(trade['p2_cards'])}\n\n"
        "После изменения предложения готовность сбрасывается."
    )


def trade_keyboard(trade_id, ready):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "➕ Карта", callback_data=f"tr_addcard_{trade_id}"
                ),
                InlineKeyboardButton(
                    "💳 Монеты", callback_data=f"tr_addmoney_{trade_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🗑 Очистить", callback_data=f"tr_clear_{trade_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Снять готовность"
                    if ready
                    else "✅ Подтвердить готовность",
                    callback_data=f"tr_ready_{trade_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "🚫 Отменить", callback_data=f"tr_cancel_{trade_id}"
                )
            ],
        ]
    )


async def update_trade_views(context, trade_id):
    trade = active_trades.get(trade_id)
    if not trade:
        return

    text = await render_trade_text(trade)

    for user_id, message_id in trade["messages"].items():
        ready = (
            trade["p1_ready"]
            if user_id == trade["p1"]
            else trade["p2_ready"]
        )
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                reply_markup=trade_keyboard(trade_id, ready),
                parse_mode="Markdown",
            )
        except Exception as exc:
            logger.debug("trade view update failed: %s", exc)


async def trade_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("accept_trade_"):
        _, _, p1, p2 = data.split("_")
        p1, p2 = int(p1), int(p2)

        if user.id != p2:
            await query.answer("Это предложение адресовано не вам.", show_alert=True)
            return

        trade_id = f"{p1}_{p2}_{time.time_ns()}"
        trade = {
            "p1": p1,
            "p2": p2,
            "p1_cards": [],
            "p2_cards": [],
            "p1_money": 0,
            "p2_money": 0,
            "p1_ready": False,
            "p2_ready": False,
            "messages": {},
        }
        active_trades[trade_id] = trade

        first = await context.bot.send_message(
            p1, "🤝 **Трейд создаётся…**", parse_mode="Markdown"
        )
        await query.edit_message_text(
            "🤝 **Трейд создаётся…**", parse_mode="Markdown"
        )
        trade["messages"][p1] = first.message_id
        trade["messages"][p2] = query.message.message_id
        await update_trade_views(context, trade_id)
        await query.answer()
        return

    if data.startswith("decline_trade_"):
        parts = data.split("_")
        p1 = int(parts[2])
        await query.edit_message_text("❌ Предложение отклонено.")
        try:
            await context.bot.send_message(p1, "❌ Игрок отклонил трейд.")
        except Exception:
            pass
        await query.answer()
        return

    if not data.startswith("tr_"):
        return

    parts = data.split("_")
    action = parts[1]

    if action in ("addcard", "addmoney", "clear", "ready", "cancel"):
        trade_id = "_".join(parts[2:])
    else:
        trade_id = "_".join(parts[2:-1])

    trade = active_trades.get(trade_id)
    if not trade:
        await query.answer("Трейд уже завершён.", show_alert=True)
        return

    if user.id not in (trade["p1"], trade["p2"]):
        await query.answer("Вы не участник этого трейда.", show_alert=True)
        return

    first = user.id == trade["p1"]

    if action == "cancel":
        active_trades.pop(trade_id, None)
        for uid, mid in trade["messages"].items():
            try:
                await context.bot.edit_message_text(
                    uid,
                    mid,
                    "🚫 **Трейд отменён.**",
                    parse_mode="Markdown",
                )
            except Exception:
                pass
        await query.answer()
        return

    if action == "clear":
        key = "p1" if first else "p2"
        trade[f"{key}_cards"] = []
        trade[f"{key}_money"] = 0
        trade["p1_ready"] = False
        trade["p2_ready"] = False
        await update_trade_views(context, trade_id)
        await query.answer("Предложение очищено.")
        return

    if action == "addmoney":
        context.user_data["active_trade_id"] = trade_id
        await query.message.reply_text("💳 Введите сумму монет:")
        await query.answer()
        return WAITING_TRADE_MONEY

    if action == "addcard":
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.id, c.nickname, c.ovr, uc.count
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND uc.count > 0
            ORDER BY c.ovr DESC
            """,
            (user.id,),
        )
        cards = cur.fetchall()
        conn.close()

        offered = trade["p1_cards"] if first else trade["p2_cards"]
        buttons = [
            [
                InlineKeyboardButton(
                    f"{card['nickname']} ({card['ovr']})",
                    callback_data=f"tr_putcard_{trade_id}_{card['id']}",
                )
            ]
            for card in cards
            if offered.count(card["id"]) < card["count"]
        ]
        buttons.append(
            [InlineKeyboardButton("🔙 Назад", callback_data=f"tr_back_{trade_id}")]
        )
        await query.edit_message_text(
            "🃏 Выберите карту:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        await query.answer()
        return

    if action == "putcard":
        card_id = int(parts[-1])
        offered_key = "p1_cards" if first else "p2_cards"

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT count FROM user_cards
            WHERE user_id = %s AND card_id = %s AND count > 0
            """,
            (user.id, card_id),
        )
        row = cur.fetchone()
        conn.close()

        if not row or trade[offered_key].count(card_id) >= row["count"]:
            await query.answer("Этой карты больше нельзя добавить.", show_alert=True)
            return

        trade[offered_key].append(card_id)
        trade["p1_ready"] = False
        trade["p2_ready"] = False
        await update_trade_views(context, trade_id)
        await query.answer("Карта добавлена.")
        return

    if action == "back":
        await update_trade_views(context, trade_id)
        await query.answer()
        return

    if action == "ready":
        key = "p1_ready" if first else "p2_ready"
        trade[key] = not trade[key]
        await update_trade_views(context, trade_id)
        await query.answer()

        if trade["p1_ready"] and trade["p2_ready"]:
            await execute_trade_finish(context, trade_id)


async def execute_trade_finish(context, trade_id):
    trade = active_trades.pop(trade_id, None)
    if not trade:
        return

    conn = get_db()
    cur = conn.cursor()

    try:
        cur.execute(
            """
            SELECT user_id, balance
            FROM users
            WHERE user_id IN (%s, %s)
            FOR UPDATE
            """,
            (trade["p1"], trade["p2"]),
        )
        balances = {row["user_id"]: row["balance"] for row in cur.fetchall()}

        if (
            balances.get(trade["p1"], 0) < trade["p1_money"]
            or balances.get(trade["p2"], 0) < trade["p2_money"]
        ):
            conn.rollback()
            result = "❌ Трейд отменён: недостаточно монет."
        else:
            for uid, money_out, money_in in (
                (trade["p1"], trade["p1_money"], trade["p2_money"]),
                (trade["p2"], trade["p2_money"], trade["p1_money"]),
            ):
                cur.execute(
                    """
                    UPDATE users SET balance = balance - %s + %s
                    WHERE user_id = %s
                    """,
                    (money_out, money_in, uid),
                )

            for source_uid, target_uid, cards in (
                (trade["p1"], trade["p2"], trade["p1_cards"]),
                (trade["p2"], trade["p1"], trade["p2_cards"]),
            ):
                for card_id in cards:
                    cur.execute(
                        """
                        UPDATE user_cards SET count = count - 1
                        WHERE user_id = %s AND card_id = %s AND count > 0
                        """,
                        (source_uid, card_id),
                    )
                    cur.execute(
                        """
                        INSERT INTO user_cards (user_id, card_id, count)
                        VALUES (%s, %s, 1)
                        ON CONFLICT (user_id, card_id)
                        DO UPDATE SET count = user_cards.count + 1
                        """,
                        (target_uid, card_id),
                    )

            cur.execute("DELETE FROM user_cards WHERE count <= 0")
            conn.commit()
            result = "🎉 **Трейд успешно завершён!**"

    except Exception:
        conn.rollback()
        result = "❌ Произошла ошибка. Предметы не списаны."
        logger.exception("trade execution failed")
    finally:
        conn.close()

    for uid, mid in trade["messages"].items():
        try:
            await context.bot.edit_message_text(
                uid, mid, result, parse_mode="Markdown"
            )
        except Exception:
            pass


async def execute_trade_money_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    try:
        amount = int(update.message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите неотрицательное целое число.")
        return WAITING_TRADE_MONEY

    user = update.effective_user
    trade_id = context.user_data.get("active_trade_id")
    trade = active_trades.get(trade_id)

    if not trade or user.id not in (trade["p1"], trade["p2"]):
        await update.message.reply_text("❌ Трейд не активен.")
        return ConversationHandler.END

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    balance = cur.fetchone()["balance"]
    conn.close()

    if amount > balance:
        await update.message.reply_text(
            f"❌ Недостаточно средств. Баланс: {balance}."
        )
        return WAITING_TRADE_MONEY

    if user.id == trade["p1"]:
        trade["p1_money"] = amount
    else:
        trade["p2_money"] = amount

    trade["p1_ready"] = False
    trade["p2_ready"] = False
    await update.message.reply_text("✅ Сумма обновлена.")
    await update_trade_views(context, trade_id)
    return ConversationHandler.END


async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return
    await show_shop(update, context)


async def show_shop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM packs
        WHERE available_until IS NULL OR available_until > %s
        ORDER BY id DESC
        """,
        (datetime.now(),),
    )
    packs = cur.fetchall()
    discount = get_active_discount(cur, user.id)
    conn.close()

    text = f"🛒 **МАГАЗИН ПАКОВ**\n🏷 Скидка: **{discount}%**\n\n"
    buttons = []

    for pack in packs:
        price = discounted_price(pack["price"], discount)
        text += f"📦 **{pack['name']}** — {price} RPLCoin\n"
        buttons.append(
            [
                InlineKeyboardButton(
                    f"📦 {pack['name']} — {price}",
                    callback_data=f"preview_pack_{pack['id']}",
                )
            ]
        )

    if not packs:
        text += "Магазин пока пуст."

    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.answer()
        await query.message.edit_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode="Markdown"
        )


async def shop_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "cancel_pack_buy":
        await show_shop(update, context)
        return

    pack_id = int(data.rsplit("_", 1)[1])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM packs WHERE id = %s", (pack_id,))
    pack = cur.fetchone()

    if not pack:
        conn.close()
        await query.answer("Пак не найден.", show_alert=True)
        return

    if data.startswith("preview_pack_"):
        cur.execute(
            """
            SELECT c.nickname, c.ovr, c.rarity, c.position
            FROM pack_cards pc
            JOIN cards c ON c.id = pc.card_id
            WHERE pc.pack_id = %s
            ORDER BY c.ovr
            """,
            (pack_id,),
        )
        cards = cur.fetchall()
        discount = get_active_discount(cur, user.id)
        price = discounted_price(pack["price"], discount)
        conn.close()

        if pack["reveal_cards"]:
            cards_text = "\n".join(
                f"• {card['nickname']} ({card['ovr']} OVR, {card['rarity']})"
                for card in cards
            ) or "Карточки не указаны."
        else:
            cards_text = "🔒 Состав пака скрыт продавцом."

        caption = (
            f"📦 **ПАК «{pack['name']}»**\n\n"
            f"💰 Цена: **{price} RPLCoin**\n"
            f"🃏 Содержимое:\n{cards_text}"
        )
        await query.edit_message_text(
            caption,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Купить",
                            callback_data=f"confirm_pack_{pack_id}",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "🔙 Назад", callback_data="cancel_pack_buy"
                        )
                    ],
                ]
            ),
            parse_mode="Markdown",
        )
        return

    if data.startswith("confirm_pack_"):
        discount = get_active_discount(cur, user.id)
        price = discounted_price(pack["price"], discount)

        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        balance = cur.fetchone()["balance"]

        if balance < price:
            conn.close()
            await query.answer("Недостаточно средств.", show_alert=True)
            return

        cur.execute(
            """
            SELECT buy_count FROM user_pack_buys
            WHERE user_id = %s AND pack_id = %s
            """,
            (user.id, pack_id),
        )
        bought = cur.fetchone()
        bought_count = bought["buy_count"] if bought else 0

        if pack["buy_limit"] > 0 and bought_count >= pack["buy_limit"]:
            conn.close()
            await query.answer("Лимит покупок исчерпан.", show_alert=True)
            return

        cur.execute(
            """
            SELECT c.*, col.name AS collection_name,
                   t.name AS team_name, t.emoji AS team_emoji
            FROM pack_cards pc
            JOIN cards c ON c.id = pc.card_id
            JOIN collections col ON col.id = c.collection_id
            LEFT JOIN card_teams t ON t.id = c.team_id
            WHERE pc.pack_id = %s
            """,
            (pack_id,),
        )
        cards = cur.fetchall()

        if not cards:
            conn.close()
            await query.answer("В паке нет карт.", show_alert=True)
            return

        card = choose_card_for_user(cur, user.id, cards)

        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (price, user.id),
        )
        cur.execute(
            """
            INSERT INTO user_pack_buys (user_id, pack_id, buy_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, pack_id)
            DO UPDATE SET buy_count = user_pack_buys.buy_count + 1
            """,
            (user.id, pack_id),
        )
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, card["id"]),
        )
        conn.commit()
        conn.close()

        await query.answer("Пак куплен!", show_alert=True)

        text = (
            f"📦 Из пака **{pack['name']}** выпала карта!\n\n"
            f"🃏 **{card['nickname']}**\n"
            f"⭐ OVR: **{card['ovr']}**\n"
            f"✨ Редкость: **{card['rarity']}**"
        )
        if card["image_id"]:
            try:
                await context.bot.send_photo(
                    user.id,
                    card["image_id"],
                    caption=text,
                    parse_mode="Markdown",
                )
            except Exception:
                await context.bot.send_message(
                    user.id, text, parse_mode="Markdown"
                )
        else:
            await context.bot.send_message(user.id, text, parse_mode="Markdown")

        await show_shop(update, context)


async def coin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    await update.message.reply_text(
        "🪙 Орёл и решка\n"
        "Шанс выигрыша — 20%, проигрыша — 80%.\n"
        "Введите ставку:",
        reply_markup=bet_cancel_keyboard(),
        parse_mode="Markdown",
    )
    return WAITING_COIN_BET


async def coin_receive_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Ставка должна быть положительным числом.")
        return WAITING_COIN_BET

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    balance = cur.fetchone()["balance"]

    if balance < bet:
        conn.close()
        await update.message.reply_text("❌ Недостаточно средств.")
        return WAITING_COIN_BET

    win = random.random() < 0.20
    if win:
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (bet, user.id),
        )
        result = f"🎉 **Орёл!** Вы выиграли **{bet} RPLCoin**."
    else:
        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (bet, user.id),
        )
        result = f"💥 **Решка!** Вы проиграли **{bet} RPLCoin**."

    conn.commit()
    conn.close()
    await update.message.reply_text(result, parse_mode="Markdown")
    return ConversationHandler.END


async def rps_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Введите ставку для КНБ:",
        reply_markup=bet_cancel_keyboard(),
    )
    return WAITING_RPS_BET


async def slots_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎰 Введите ставку для слотов:",
        reply_markup=bet_cancel_keyboard(),
    )
    return WAITING_SLOTS_BET


async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎲 Введите ставку для костей:",
        reply_markup=bet_cancel_keyboard(),
    )
    return WAITING_DICE_BET


async def generic_bet_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите положительное число.")
        return context.user_data.get("bet_state", ConversationHandler.END)

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    balance = cur.fetchone()["balance"]

    if balance < bet:
        conn.close()
        await update.message.reply_text("❌ Недостаточно средств.")
        return context.user_data.get("bet_state", ConversationHandler.END)

    game = context.user_data.get("bet_game", "slots")
    cur.execute(
        "UPDATE users SET balance = balance - %s WHERE user_id = %s",
        (bet, user.id),
    )

    if game == "slots":
        roll = random.random()
        if roll < 0.03:
            payout = bet * 10
            line = "💎 | 💎 | 💎"
        elif roll < 0.10:
            payout = bet * 5
            line = "⭐ | ⭐ | ⭐"
        elif roll < 0.25:
            payout = bet * 2
            line = "🍒 | 🍒 | 🏒"
        else:
            payout = 0
            line = "🥅 | 🏒 | ⭐"
    else:
        player = random.randint(1, 6)
        bot = random.randint(1, 6)
        if player > bot:
            payout = bet * 2
        elif player == bot:
            payout = bet
        else:
            payout = 0
        line = f"🤖 {bot} — 🎲 {player}"

    if payout:
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (payout, user.id),
        )

    conn.commit()
    conn.close()

    if game == "slots":
        text = (
            f"🎰 {line}\n\n"
            + (
                f"🎉 Выигрыш: **{payout} RPLCoin**!"
                if payout
                else f"❌ Проигрыш: **{bet} RPLCoin**."
            )
        )
    else:
        text = (
            f"🎲 {line}\n\n"
            + (
                f"🎉 Вы выиграли **{payout} RPLCoin**!"
                if payout > bet
                else "🤝 Ничья, ставка возвращена."
                if payout == bet
                else f"❌ Вы проиграли **{bet} RPLCoin**."
            )
        )

    await update.message.reply_text(text, parse_mode="Markdown")
    return ConversationHandler.END


async def minigames_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎮 Мини-игры",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🪨 КНБ", callback_data="play_rps"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎰 Слоты", callback_data="play_slots"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🎲 Кости", callback_data="play_dice"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🪙 Орёл и решка", callback_data="play_coin"
                    )
                ],
            ]
        ),
        parse_mode="Markdown",
    )


async def inline_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()

    if data == "play_coin":
        await query.message.reply_text(
            "🪙 Введите ставку:",
            reply_markup=bet_cancel_keyboard(),
        )
        return WAITING_COIN_BET

    if data in ("play_rps", "play_slots", "play_dice"):
        game = {
            "play_rps": "rps",
            "play_slots": "slots",
            "play_dice": "dice",
        }[data]
        state = {
            "rps": WAITING_RPS_BET,
            "slots": WAITING_SLOTS_BET,
            "dice": WAITING_DICE_BET,
        }[game]
        context.user_data["bet_game"] = game
        context.user_data["bet_state"] = state
        await query.message.reply_text(
            "💳 Введите ставку:",
            reply_markup=bet_cancel_keyboard(),
        )
        return state

    if data == "back_to_main_inline":
        await query.message.reply_text(
            "📌 Выберите раздел:", reply_markup=welcome_inline_keyboard()
        )


async def cancel_minigame_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.edit_text("✅ Мини-игра отменена.")
    return ConversationHandler.END


def get_roster_cards(cur, roster):
    ids = [
        roster["goalie_id"],
        roster["skater1_id"],
        roster["skater2_id"],
        roster["skater3_id"],
        roster["skater4_id"],
    ]
    cur.execute("SELECT * FROM cards WHERE id = ANY(%s)", (ids,))
    by_id = {row["id"]: row for row in cur.fetchall()}
    return {
        "goalie": by_id[roster["goalie_id"]],
        "skater1": by_id[roster["skater1_id"]],
        "skater2": by_id[roster["skater2_id"]],
        "skater3": by_id[roster["skater3_id"]],
        "skater4": by_id[roster["skater4_id"]],
    }


def roster_card_ids(cards):
    return [card["id"] for card in cards.values()]


def fatigue_status(cur, user_id, card_ids):
    now = datetime.now()
    cur.execute(
        """
        SELECT card_id, matches_played, tired_until
        FROM card_fatigue
        WHERE user_id = %s AND card_id = ANY(%s)
        """,
        (user_id, card_ids),
    )
    rows = {row["card_id"]: row for row in cur.fetchall()}

    tired = []
    for card_id in card_ids:
        row = rows.get(card_id)
        until = parse_dt(row["tired_until"]) if row else None
        if until and until <= now:
            cur.execute(
                """
                UPDATE card_fatigue
                SET matches_played = 0, tired_until = NULL
                WHERE user_id = %s AND card_id = %s
                """,
                (user_id, card_id),
            )
            continue
        if until and until > now:
            tired.append((card_id, until))
    return tired


def register_match_fatigue(cur, user_id, card_ids):
    for card_id in set(card_ids):
        cur.execute(
            """
            INSERT INTO card_fatigue
            (user_id, card_id, matches_played, tired_until)
            VALUES (%s, %s, 1, NULL)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET
                matches_played = card_fatigue.matches_played + 1,
                tired_until = CASE
                    WHEN card_fatigue.matches_played + 1 >= %s
                    THEN %s
                    ELSE card_fatigue.tired_until
                END
            """,
            (
                user_id,
                card_id,
                random.randint(FATIGUE_MATCHES_MIN, FATIGUE_MATCHES_MAX),
                datetime.now() + timedelta(minutes=FATIGUE_RECOVERY_MINUTES),
            ),
        )


def calc_goal_probabilities(p1_cards, p2_cards):
    p1_attack = sum(
        p1_cards[f"skater{i}"]["ovr"] for i in range(1, 5)
    ) / 4
    p2_attack = sum(
        p2_cards[f"skater{i}"]["ovr"] for i in range(1, 5)
    ) / 4
    p1_power = (p1_attack * 4 + p1_cards["goalie"]["ovr"]) / 5
    p2_power = (p2_attack * 4 + p2_cards["goalie"]["ovr"]) / 5

    p1 = 0.12 * (1.55 ** ((p1_attack - p2_cards["goalie"]["ovr"]) / 8))
    p2 = 0.12 * (1.55 ** ((p2_attack - p1_cards["goalie"]["ovr"]) / 8))

    if p1_power - p2_power > 8:
        p1 *= 1.25
        p2 *= 0.8
    elif p2_power - p1_power > 8:
        p2 *= 1.25
        p1 *= 0.8

    return max(0.02, min(0.35, p1)), max(0.02, min(0.35, p2))


def format_cards_list(cards):
    labels = {
        "goalie": "🧤",
        "skater1": "🏒",
        "skater2": "🏒",
        "skater3": "🏒",
        "skater4": "🏒",
    }
    return "\n".join(
        f"{labels[pos]} {card['nickname']} ({card['ovr']} OVR)"
        for pos, card in cards.items()
    )


async def cardmatch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = cur.fetchone()

    if not roster or not all(
        roster[f"{pos}_id"]
        for pos in ("goalie", "skater1", "skater2", "skater3", "skater4")
    ):
        conn.close()
        await update.message.reply_text(
            "❌ Соберите состав: 1 вратарь + 4 полевых.",
            parse_mode="Markdown",
        )
        return

    cards = get_roster_cards(cur, roster)
    tired = fatigue_status(cur, user.id, roster_card_ids(cards))
    conn.commit()
    conn.close()

    if tired:
        until = max(row[1] for row in tired)
        await update.message.reply_text(
            f"😴 Некоторые карточки устали.\n"
            f"Они восстановятся примерно к {until.strftime('%H:%M')}.",
            parse_mode="Markdown",
        )
        return

    await run_cardmatch_ai(update, context, cards)


async def run_cardmatch_ai(update, context, player_cards):
    user = update.effective_user

    conn = get_db()
    cur = conn.cursor()

    avg_ovr = sum(card["ovr"] for card in player_cards.values()) / 5
    ids = roster_card_ids(player_cards)

    cur.execute(
        """
        SELECT *
        FROM cards
        WHERE id <> ALL(%s)
          AND ovr BETWEEN %s AND %s
        ORDER BY RANDOM()
        """,
        (ids, max(50, int(avg_ovr - 5)), int(avg_ovr + 5)),
    )
    candidates = cur.fetchall()

    goalies = [card for card in candidates if card["position"] == "Goalie"]
    skaters = [card for card in candidates if card["position"] == "Skater"]

    if len(goalies) < 1 or len(skaters) < 4:
        cur.execute(
            """
            SELECT *
            FROM cards
            WHERE id <> ALL(%s)
            ORDER BY ABS(ovr - %s), RANDOM()
            """,
            (ids, avg_ovr),
        )
        candidates = cur.fetchall()
        goalies = [card for card in candidates if card["position"] == "Goalie"]
        skaters = [card for card in candidates if card["position"] == "Skater"]

    if len(goalies) < 1 or len(skaters) < 4:
        conn.close()
        await update.message.reply_text(
            "❌ В базе недостаточно уникальных карт для соперника."
        )
        return

    ai_cards = {
        "goalie": goalies[0],
        "skater1": skaters[0],
        "skater2": skaters[1],
        "skater3": skaters[2],
        "skater4": skaters[3],
    }
    conn.close()

    player_name = user.first_name or user.username or "Игрок"
    ai_avg = sum(card["ovr"] for card in ai_cards.values()) / 5
    text = (
        "🏒 **МАТЧ ПРОТИВ ИИ**\n\n"
        f"🔴 {player_name} — **{avg_ovr:.1f} OVR**\n"
        f"🤖 ИИ — **{ai_avg:.1f} OVR**\n\n"
        f"🔴 **Ваш состав:**\n{format_cards_list(player_cards)}\n\n"
        f"🤖 **Состав ИИ:**\n{format_cards_list(ai_cards)}\n\n"
        "────────────────────\n"
        "⏱ Матч начинается!"
    )

    msg = await update.message.reply_text(text, parse_mode="Markdown")
    score_player = 0
    score_ai = 0
    events = []

    prob_player, prob_ai = calc_goal_probabilities(player_cards, ai_cards)

    for period in range(1, 4):
        for event_no in range(3):
            await asyncio.sleep(1.5)
            minute = (period - 1) * 20 + event_no * 6 + random.randint(1, 4)
            roll = random.random()

            if roll < prob_player:
                scorer = random.choice(
                    [player_cards[f"skater{i}"] for i in range(1, 5)]
                )
                score_player += 1
                event = (
                    f"⚡ **{minute}' ГОЛ!** {scorer['nickname']} забивает! "
                    f"[{score_player}:{score_ai}]"
                )
            elif roll < prob_player + prob_ai:
                scorer = random.choice(
                    [ai_cards[f"skater{i}"] for i in range(1, 5)]
                )
                score_ai += 1
                event = (
                    f"⚡ {minute}' ГОЛ ИИ! {scorer['nickname']} забивает! "
                    f"[{score_player}:{score_ai}]"
                )
            else:
                event = random.choice(
                    [
                        f"🧤 {minute}' СЕЙВ! Вратарь спасает команду.",
                        f"🏒 {minute}' ШТАНГА! Шайба попадает в каркас.",
                        f"💥 {minute}' СИЛОВОЙ ПРИЁМ! Жёсткая борьба у борта.",
                        f"2️⃣ {minute}' УДАЛЕНИЕ! Малый штраф.",
                        f"🚫 {minute}' ГОЛ ОТМЕНЁН! Судьи увидели положение вне игры.",
                        f"📺 {minute}' ВИДЕОПРОСМОТР! Решение арбитров изменено.",
                        f"🧊 {minute}' ЗАМЕНА КЛЮШКИ! Игра ненадолго остановлена.",
                        f"🎯 {minute}' ОПАСНЫЙ БРОСОК! Шайба чудом проходит рядом со штангой.",
                    ]
                )

            events.append(event)
            await msg.edit_text(
                f"{text}\n\n📊 **Счёт:** 🔴 {score_player} — {score_ai} 🤖\n\n"
                + "\n".join(events[-6:]),
                parse_mode="Markdown",
            )

    if score_player == score_ai:
        event = "🔥 **ОВЕРТАЙМ!** Победитель определится золотым голом."
        events.append(event)
        await msg.edit_text(
            f"{text}\n\n📊 **Счёт:** {score_player}:{score_ai}\n\n"
            + "\n".join(events[-6:]),
            parse_mode="Markdown",
        )
        await asyncio.sleep(1.5)

        if random.random() < 0.5:
            score_player += 1
            events.append("🏆 **ЗОЛОТОЙ ГОЛ!** Победа вашей команды!")
        else:
            score_ai += 1
            events.append("🏆 **ЗОЛОТОЙ ГОЛ ИИ!** Соперник забирает матч.")

    conn = get_db()
    cur = conn.cursor()
    register_match_fatigue(cur, user.id, roster_card_ids(player_cards))

    if score_player > score_ai:
        cur.execute(
            """
            UPDATE users
            SET mmr = mmr + 30, balance = balance + 2000
            WHERE user_id = %s
            """,
            (user.id,),
        )
        result = "🎉 **ПОБЕДА!** +30 MMR и +2 000 RPLCoin"
    else:
        cur.execute(
            """
            UPDATE users
            SET mmr = GREATEST(0, mmr - 20), balance = balance + 500
            WHERE user_id = %s
            """,
            (user.id,),
        )
        result = "😔 **ПОРАЖЕНИЕ.** -20 MMR и +500 RPLCoin"

    conn.commit()
    conn.close()

    await msg.edit_text(
        f"🏁 **МАТЧ ЗАВЕРШЁН!**\n\n"
        f"Итоговый счёт: **{score_player} — {score_ai}**\n"
        f"{result}\n\n"
        "😴 Карточки состава получили усталость.\n"
        "⏳ Восстановление после лимита матчей — 30 минут.",
        parse_mode="Markdown",
    )


async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
    profile = cur.fetchone()
    cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = cur.fetchone()

    text = (
        f"🏒 **ПРОФИЛЬ {user.first_name or 'ИГРОКА'}**\n\n"
        f"💳 Баланс: **{profile['balance']} RPLCoin**\n"
        f"🏆 MMR: **{profile['mmr']}**\n\n"
        "📋 **Состав:**\n"
    )

    if roster:
        for pos, label in (
            ("goalie", "🧤 Вратарь"),
            ("skater1", "🏒 Полевой 1"),
            ("skater2", "🏒 Полевой 2"),
            ("skater3", "🏒 Полевой 3"),
            ("skater4", "🏒 Полевой 4"),
        ):
            card_id = roster[f"{pos}_id"]
            if card_id:
                cur.execute(
                    "SELECT nickname, ovr FROM cards WHERE id = %s",
                    (card_id,),
                )
                card = cur.fetchone()
                value = (
                    f"{card['nickname']} ({card['ovr']} OVR)"
                    if card
                    else "не найдена"
                )
            else:
                value = "не выбрана"
            text += f"{label}: **{value}**\n"
    else:
        text += "Состав не собран."

    conn.close()

    await update.message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔄 Обновить", callback_data="refresh_profile"
                    )
                ]
            ]
        ),
        parse_mode="Markdown",
    )


async def cardmmr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_pm_registered(update, context):
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT first_name, username, mmr
        FROM users
        ORDER BY mmr DESC
        LIMIT 10
        """
    )
    rows = cur.fetchall()
    conn.close()

    text = "🏆 **ТОП-10 MMR**\n\n"
    for index, row in enumerate(rows, 1):
        name = row["first_name"] or row["username"] or "Игрок"
        text += f"{index}. {name} — **{row['mmr']} MMR**\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def checkprofile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Пример: /checkprofile @username",
            parse_mode="Markdown",
        )
        return

    target = context.args[0].replace("@", "")
    conn = get_db()
    cur = conn.cursor()

    if target.isdigit():
        cur.execute("SELECT * FROM users WHERE user_id = %s", (int(target),))
    else:
        cur.execute("SELECT * FROM users WHERE username = %s", (target,))
    row = cur.fetchone()
    conn.close()

    if not row:
        await update.message.reply_text("❌ Игрок не найден.")
        return

    await update.message.reply_text(
        f"👤 **{row['first_name'] or row['username']}**\n"
        f"💳 Баланс: {row['balance']}\n"
        f"🏆 MMR: {row['mmr']}",
        parse_mode="Markdown",
    )


async def promo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎟 Введите промокод:")
    return WAITING_PROMO_INPUT


async def promo_input_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    code = update.message.text.strip().upper()
    user = update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM promo_codes WHERE code = %s", (code,))
    promo = cur.fetchone()

    if not promo:
        conn.close()
        await update.message.reply_text("❌ Промокод не найден.")
        return ConversationHandler.END

    cur.execute(
        """
        SELECT 1 FROM user_promocodes
        WHERE user_id = %s AND code = %s
        """,
        (user.id, code),
    )
    if cur.fetchone():
        conn.close()
        await update.message.reply_text("❌ Вы уже использовали этот код.")
        return ConversationHandler.END

    if promo["current_uses"] >= promo["max_uses"]:
        conn.close()
        await update.message.reply_text("❌ Лимит промокода исчерпан.")
        return ConversationHandler.END

    if promo["reward_type"] == "money":
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (promo["reward_value"], user.id),
        )
        reward = f"+{promo['reward_value']} RPLCoin"
    else:
        cur.execute(
            """
            INSERT INTO user_cards (user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT (user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, promo["reward_value"]),
        )
        reward = f"карточка ID {promo['reward_value']}"

    cur.execute(
        """
        UPDATE promo_codes
        SET current_uses = current_uses + 1
        WHERE code = %s
        """,
        (code,),
    )
    cur.execute(
        """
        INSERT INTO user_promocodes (user_id, code)
        VALUES (%s, %s)
        """,
        (user.id, code),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎉 Промокод активирован!\nНаграда: **{reward}**",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📌 Выберите раздел:", reply_markup=welcome_inline_keyboard()
    )


async def adminkarpl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_admin(update.effective_user.id):
        await update.message.reply_text(
            "✅ Вы уже авторизованы.", reply_markup=admin_menu_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text("🔑 Введите логин:")
    return WAITING_LOGIN


async def wait_login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["login"] = update.message.text.strip()
    await update.message.reply_text("🔒 Введите пароль:")
    return WAITING_PASSWORD


async def wait_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if check_credentials(
        context.user_data.get("login"), update.message.text.strip()
    ):
        add_admin(update.effective_user.id)
        await update.message.reply_text(
            "✅ Авторизация успешна.", reply_markup=admin_menu_keyboard()
        )
    else:
        await update.message.reply_text("❌ Неверный логин или пароль.")
    return ConversationHandler.END


async def getid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"🆔 ID чата: {update.effective_chat.id}\n"
        f"Тип: {update.effective_chat.type}",
        parse_mode="Markdown",
    )


async def support_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO support_messages
        (user_id, username, text, timestamp)
        VALUES (%s, %s, %s, %s)
        """,
        (
            update.effective_user.id,
            update.effective_user.username or "",
            update.message.text,
            datetime.now().isoformat(),
        ),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ Сообщение отправлено в поддержку.")
    return ConversationHandler.END


async def duel_shot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if random.random() < 0.35:
        await query.edit_message_text("⚡ ГОЛ! Отличный бросок!")
    else:
        await query.edit_message_text("🧤 СЕЙВ! Вратарь спасает ворота!")
    return ConversationHandler.END


MAIN_MENU_HANDLERS = {
    "🏠 Главное меню": main_menu,
    "🃏 Бесплатная карта": rplcards_command,
    "🎒 Инвентарь": inventory_command,
    "🛒 Торговая площадка": cardshop_command,
    "🏒 Состав и Профиль": profile_command,
    "⚔️ Искать игру": cardmatch_command,
    "🛒 Магазин Паков": shop_command,
    "🏆 Топ MMR": cardmmr_command,
    "🤝 Трейд": trade_command,
    "🎁 Промокод": promo_command,
    "🎡 Колесо удачи": wheel_command,
    "🎁 Ежедневный бонус": daily_command,
    "🎮 Мини-игры": minigames_menu,
}


async def menu_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    handler = MAIN_MENU_HANDLERS.get(update.message.text)
    if handler:
        return await handler(update, context)


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid_command))
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
    app.add_handler(CommandHandler("wheel", wheel_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("promo", promo_command))
    app.add_handler(CommandHandler("rplcoin", coin_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("rps", rps_command))
    app.add_handler(CommandHandler("slots", slots_command))
    app.add_handler(CommandHandler("dice", dice_command))
    app.add_handler(CommandHandler("adminkarpl", adminkarpl))

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("promo", promo_command)],
            states={
                WAITING_PROMO_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        promo_input_receive,
                    )
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("rplcoin", coin_command),
                CommandHandler("coin", coin_command),
                CallbackQueryHandler(inline_callback, pattern="^play_coin$"),
            ],
            states={
                WAITING_COIN_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        coin_receive_bet,
                    )
                ]
            },
            fallbacks=[
                CallbackQueryHandler(
                    cancel_minigame_callback,
                    pattern="^cancel_minigame$",
                )
            ],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CommandHandler("rps", rps_command),
                CommandHandler("slots", slots_command),
                CommandHandler("dice", dice_command),
                CallbackQueryHandler(
                    inline_callback,
                    pattern="^play_(rps|slots|dice)$",
                ),
            ],
            states={
                WAITING_RPS_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        generic_bet_receive,
                    )
                ],
                WAITING_SLOTS_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        generic_bet_receive,
                    )
                ],
                WAITING_DICE_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        generic_bet_receive,
                    )
                ],
            },
            fallbacks=[
                CallbackQueryHandler(
                    cancel_minigame_callback,
                    pattern="^cancel_minigame$",
                )
            ],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    market_callback_handler,
                    pattern="^select_mcard_",
                )
            ],
            states={
                WAITING_MARKET_PRICE_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        execute_market_list_price,
                    )
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    trade_callback_handler,
                    pattern="^tr_addmoney_",
                )
            ],
            states={
                WAITING_TRADE_MONEY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        execute_trade_money_input,
                    )
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("adminkarpl", adminkarpl)],
            states={
                WAITING_LOGIN: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        wait_login,
                    )
                ],
                WAITING_PASSWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        wait_password,
                    )
                ],
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(inline_callback, pattern="^support$"),
            ],
            states={
                WAITING_SUPPORT_MSG: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        support_receive,
                    )
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(inline_callback, pattern="^duel$"),
            ],
            states={
                WAITING_DUEL_SHOT: [
                    CallbackQueryHandler(duel_shot, pattern="^shot_")
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            inventory_callback_handler,
            pattern=(
                r"^(refresh_inv|sell_menu|do_sell_|craft_menu|craft_group_|"
                r"upgrade_menu|upgrade_source_|upgrade_target_|upgrade_confirm_)"
            ),
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            market_callback_handler,
            pattern=r"^(refresh_market|my_market_items|market_list_menu|"
            r"select_mcard_|cancel_market_|buy_market_)",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            trade_callback_handler,
            pattern=r"^(accept_trade_|decline_trade_|tr_)",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            shop_callback_handler,
            pattern=r"^(preview_pack_|confirm_pack_|cancel_pack_buy$)",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            freepack_callback_handler,
            pattern=r"^claim_freepack_btn$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            inline_callback,
            pattern=r"^(play_|back_to_main_inline$|discord$|website$|support$|duel$)",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            cancel_minigame_callback,
            pattern=r"^cancel_minigame$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^(🏠 Главное меню|🃏 Бесплатная карта|🎒 Инвентарь|"
                r"🛒 Торговая площадка|🏒 Состав и Профиль|⚔️ Искать игру|"
                r"🛒 Магазин Паков|🏆 Топ MMR|🤝 Трейд|🎁 Промокод|"
                r"🎡 Колесо удачи|🎁 Ежедневный бонус|🎮 Мини-игры)$"
            ),
            menu_router,
        )
    )

    logger.info("RPL bot started")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
