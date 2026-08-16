import os
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
    WAITING_SUPPORT_MSG,
    WAITING_DUEL_SHOT,
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
    WAITING_TRADE_MONEY,
    WAITING_MARKET_PRICE_INPUT,
    WAITING_RPS_BET,
    WAITING_CASINO_BET,
    ADMIN_SHOP_PACK_SELECT,
    ADMIN_SHOP_PACK_HOURS,
) = range(41)


def get_db():
    return psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor,
    )


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
            freepack_claimed BOOLEAN DEFAULT FALSE
        )
        """
    )

    cur.execute(
        """
        ALTER TABLE users
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
            collection_id INTEGER REFERENCES collections(id)
                ON DELETE CASCADE,
            team_id INTEGER REFERENCES card_teams(id)
                ON DELETE SET NULL,
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
            user_id BIGINT REFERENCES users(user_id)
                ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id)
                ON DELETE CASCADE,
            count INTEGER DEFAULT 1,
            PRIMARY KEY(user_id, card_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_rosters (
            user_id BIGINT PRIMARY KEY REFERENCES users(user_id)
                ON DELETE CASCADE,
            goalie_id INTEGER REFERENCES cards(id)
                ON DELETE SET NULL,
            skater1_id INTEGER REFERENCES cards(id)
                ON DELETE SET NULL,
            skater2_id INTEGER REFERENCES cards(id)
                ON DELETE SET NULL,
            skater3_id INTEGER REFERENCES cards(id)
                ON DELETE SET NULL,
            skater4_id INTEGER REFERENCES cards(id)
                ON DELETE SET NULL
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
            available_until TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS pack_cards (
            pack_id INTEGER REFERENCES packs(id)
                ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id)
                ON DELETE CASCADE,
            PRIMARY KEY(pack_id, card_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS user_pack_buys (
            user_id BIGINT,
            pack_id INTEGER REFERENCES packs(id)
                ON DELETE CASCADE,
            buy_count INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, pack_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS freepack_config (
            card_id INTEGER PRIMARY KEY REFERENCES cards(id)
                ON DELETE CASCADE
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
            user_id BIGINT REFERENCES users(user_id)
                ON DELETE CASCADE,
            code TEXT REFERENCES promo_codes(code)
                ON DELETE CASCADE,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY(user_id, code)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS market (
            id SERIAL PRIMARY KEY,
            seller_id BIGINT REFERENCES users(user_id)
                ON DELETE CASCADE,
            card_id INTEGER REFERENCES cards(id)
                ON DELETE CASCADE,
            price INTEGER NOT NULL CHECK(price > 0),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        INSERT INTO bot_config(key, value)
        VALUES ('gif_goal', '')
        ON CONFLICT DO NOTHING
        """
    )

    cur.execute(
        """
        INSERT INTO bot_config(key, value)
        VALUES ('gif_save', '')
        ON CONFLICT DO NOTHING
        """
    )

    conn.commit()
    conn.close()


init_db()


def get_or_create_user(user_id, username="", first_name=""):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM users WHERE user_id = %s",
        (user_id,),
    )
    user = cur.fetchone()

    if user is None:
        cur.execute(
            """
            INSERT INTO users(
                user_id,
                username,
                first_name,
                balance,
                mmr
            )
            VALUES (%s, %s, %s, 5000, 1000)
            RETURNING *
            """,
            (user_id, username, first_name),
        )
        user = cur.fetchone()
    else:
        cur.execute(
            """
            UPDATE users
            SET username = %s,
                first_name = %s
            WHERE user_id = %s
            """,
            (username, first_name, user_id),
        )

    conn.commit()
    conn.close()
    return user


def check_user_exists(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT 1 FROM users WHERE user_id = %s",
        (user_id,),
    )
    result = cur.fetchone()
    conn.close()
    return result is not None


async def check_pm_registered(update, context):
    user = update.effective_user

    if not user:
        return False

    if check_user_exists(user.id):
        return True

    bot_username = context.bot.username or ""
    keyboard = InlineKeyboardMarkup(
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
            "⚠️ Сначала напишите боту в ЛС!",
            show_alert=True,
        )
    elif update.message:
        await update.message.reply_text(
            "⚠️ **Сначала напишите боту в личные сообщения!**",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

    return False


def add_user_card(cur, user_id, card_id, amount=1):
    cur.execute(
        """
        INSERT INTO user_cards(user_id, card_id, count)
        VALUES (%s, %s, %s)
        ON CONFLICT(user_id, card_id)
        DO UPDATE SET count = user_cards.count + EXCLUDED.count
        """,
        (user_id, card_id, amount),
    )


def remove_user_card(cur, user_id, card_id, amount=1):
    cur.execute(
        """
        UPDATE user_cards
        SET count = count - %s
        WHERE user_id = %s
          AND card_id = %s
          AND count >= %s
        """,
        (amount, user_id, card_id, amount),
    )

    if cur.rowcount != 1:
        return False

    cur.execute(
        """
        DELETE FROM user_cards
        WHERE user_id = %s
          AND card_id = %s
          AND count <= 0
        """,
        (user_id, card_id),
    )
    return True


def choose_card_for_user(cur, user_id, cards):
    if not cards:
        return None

    ids = tuple(card["id"] for card in cards)

    if len(ids) == 1:
        cur.execute(
            """
            SELECT card_id
            FROM user_cards
            WHERE user_id = %s
              AND card_id = %s
              AND count > 0
            """,
            (user_id, ids[0]),
        )
    else:
        cur.execute(
            """
            SELECT card_id
            FROM user_cards
            WHERE user_id = %s
              AND card_id IN %s
              AND count > 0
            """,
            (user_id, ids),
        )

    owned = {row["card_id"] for row in cur.fetchall()}
    unowned = [card for card in cards if card["id"] not in owned]

    return random.choice(unowned or cards)


def is_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_activity FROM admins WHERE user_id = %s",
        (user_id,),
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    last_activity = row["last_activity"]
    if not last_activity:
        return False

    if datetime.now().timestamp() - last_activity < ADMIN_SESSION_MINUTES * 60:
        return True

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM admins WHERE user_id = %s",
        (user_id,),
    )
    conn.commit()
    conn.close()
    return False


def add_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO admins(user_id, last_activity)
        VALUES (%s, %s)
        ON CONFLICT(user_id)
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
        """
        UPDATE admins
        SET last_activity = %s
        WHERE user_id = %s
        """,
        (int(datetime.now().timestamp()), user_id),
    )
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM admins WHERE user_id = %s",
        (user_id,),
    )
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
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO source_channels(chat_id, username, added_by)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (chat_id, username, added_by),
    )
    conn.commit()
    conn.close()


def add_target_chat(chat_id, link, added_by):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO target_chats(chat_id, link, added_by)
        VALUES (%s, %s, %s)
        ON CONFLICT DO NOTHING
        """,
        (chat_id, link, added_by),
    )
    conn.commit()
    conn.close()


def get_source_channels():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, username FROM source_channels")
    rows = cur.fetchall()
    conn.close()
    return rows


def get_target_chats():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT chat_id, link FROM target_chats")
    rows = cur.fetchall()
    conn.close()
    return rows


def add_support_message(user_id, username, text):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO support_messages(
            user_id,
            username,
            text,
            timestamp
        )
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (user_id, username, text, datetime.now().isoformat()),
    )
    message_id = cur.fetchone()["id"]
    conn.commit()
    conn.close()
    return message_id


def get_unanswered_messages():
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, user_id, username, text, timestamp
        FROM support_messages
        WHERE answered = 0
        ORDER BY id
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def mark_answered(message_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE support_messages SET answered = 1 WHERE id = %s",
        (message_id,),
    )
    conn.commit()
    conn.close()


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
            [InlineKeyboardButton("🌐 Наш Сайт", callback_data="website")],
            [
                InlineKeyboardButton(
                    "🆘 Обратиться в поддержку",
                    callback_data="support",
                )
            ],
            [
                InlineKeyboardButton(
                    "🏒 Дуэль Буллитов",
                    callback_data="duel",
                )
            ],
        ]
    )


def casino_keyboard():
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🎰 Слоты",
                    callback_data="casino_slots",
                ),
                InlineKeyboardButton(
                    "🎲 Кости",
                    callback_data="casino_dice",
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎮 Камень-Ножницы-Бумага",
                    callback_data="casino_rps",
                )
            ],
        ]
    )


def duel_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🥅 Левая девятка", callback_data="shot_left")],
            [InlineKeyboardButton("🥅 Правая девятка", callback_data="shot_right")],
            [InlineKeyboardButton("🧤 Домик", callback_data="shot_five")],
            [InlineKeyboardButton("🥅 Низ в угол", callback_data="shot_low")],
        ]
    )


async def start(update, context):
    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    await update.message.reply_text(
        "👋 Добро пожаловать в **Russian Puck League**!\n"
        "Выберите действие с помощью меню ниже.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def getid_command(update, context):
    chat = update.effective_chat
    await update.message.reply_text(
        f"🆔 **ID этого чата:** `{chat.id}`\n"
        f"📌 **Тип чата:** `{chat.type}`",
        parse_mode="Markdown",
    )


async def main_menu(update, context):
    if not await check_pm_registered(update, context):
        return

    await update.message.reply_text(
        "📌 Выберите раздел:",
        reply_markup=welcome_inline_keyboard(),
    )


async def inventory_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            uc.count,
            c.id,
            c.nickname,
            c.position,
            c.ovr,
            c.rarity
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s
          AND uc.count > 0
        ORDER BY c.ovr DESC, c.id
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    text = "🎒 **Ваш инвентарь:**\n\n"

    if not cards:
        text += "Инвентарь пуст."
    else:
        for card in cards:
            text += (
                f"ID `{card['id']}` | **{card['nickname']}** "
                f"({card['position']}, {card['ovr']} OVR) "
                f"[{card['rarity']}] — `x{card['count']}`\n"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏷 Выставить на рынок",
                    callback_data="market_list_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "💰 Продать системе",
                    callback_data="sell_menu",
                )
            ],
        ]
    )

    await update.message.reply_text(
        text,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def freepack_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    success, message = await grant_freepack(user.id)
    await update.message.reply_text(
        message,
        parse_mode="Markdown",
    )


async def grant_freepack(user_id):
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT freepack_claimed
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user_id,),
    )
    user = cur.fetchone()

    if not user:
        conn.close()
        return False, "❌ Пользователь не найден."

    if user["freepack_claimed"]:
        conn.close()
        return False, "❌ Вы уже получили стартовый набор."

    cur.execute(
        """
        SELECT c.id, c.position
        FROM freepack_config f
        JOIN cards c ON c.id = f.card_id
        ORDER BY f.card_id
        """
    )
    configured = cur.fetchall()

    if configured:
        selected = configured
    else:
        cur.execute(
            """
            SELECT id, position
            FROM cards
            WHERE position = 'Goalie'
            ORDER BY id
            LIMIT 1
            """
        )
        goalie = cur.fetchone()

        cur.execute(
            """
            SELECT id, position
            FROM cards
            WHERE position = 'Skater'
            ORDER BY id
            LIMIT 4
            """
        )
        skaters = cur.fetchall()

        if not goalie or len(skaters) < 4:
            conn.close()
            return (
                False,
                "❌ Стартовый набор не настроен. "
                "Администратор должен добавить карточки в админке.",
            )

        selected = [goalie] + skaters

    goalie_ids = [
        card["id"] for card in selected if card["position"] == "Goalie"
    ]
    skater_ids = [
        card["id"] for card in selected if card["position"] == "Skater"
    ]

    if len(goalie_ids) < 1 or len(skater_ids) < 4:
        conn.close()
        return (
            False,
            "❌ В стартовом наборе должен быть минимум "
            "1 вратарь и 4 полевых игрока.",
        )

    card_ids = [card["id"] for card in selected]

    for card_id in card_ids:
        add_user_card(cur, user_id, card_id, 1)

    cur.execute(
        """
        INSERT INTO user_rosters(
            user_id,
            goalie_id,
            skater1_id,
            skater2_id,
            skater3_id,
            skater4_id
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id)
        DO UPDATE SET
            goalie_id = EXCLUDED.goalie_id,
            skater1_id = EXCLUDED.skater1_id,
            skater2_id = EXCLUDED.skater2_id,
            skater3_id = EXCLUDED.skater3_id,
            skater4_id = EXCLUDED.skater4_id
        """,
        (
            user_id,
            goalie_ids[0],
            skater_ids[0],
            skater_ids[1],
            skater_ids[2],
            skater_ids[3],
        ),
    )

    cur.execute(
        """
        UPDATE users
        SET freepack_claimed = TRUE
        WHERE user_id = %s
        """,
        (user_id,),
    )

    conn.commit()
    conn.close()

    return (
        True,
        "🎁 **Стартовый набор получен!**\n\n"
        "Вам выданы 1 вратарь и 4 полевых игрока. "
        "Они автоматически установлены в состав.",
    )


async def freepack_callback(update, context):
    query = update.callback_query
    await query.answer()

    success, message = await grant_freepack(query.from_user.id)

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏒 Открыть профиль",
                    callback_data="refresh_profile",
                )
            ],
            [
                InlineKeyboardButton(
                    "⚔️ Искать матч",
                    callback_data="start_match_from_button",
                )
            ],
        ]
    )

    await query.message.edit_text(
        message,
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def profile_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance, mmr FROM users WHERE user_id = %s",
        (user.id,),
    )
    user_row = cur.fetchone()

    cur.execute(
        "SELECT * FROM user_rosters WHERE user_id = %s",
        (user.id,),
    )
    roster = cur.fetchone()

    positions = [
        ("goalie", "🧤 Вратарь"),
        ("skater1", "🏒 Полевой 1"),
        ("skater2", "🏒 Полевой 2"),
        ("skater3", "🏒 Полевой 3"),
        ("skater4", "🏒 Полевой 4"),
    ]

    lines = [
        f"🏒 **Профиль {user.first_name or 'игрока'}**",
        "",
        f"💳 Баланс: **{user_row['balance']} RPLCoin**",
        f"🏆 MMR: **{user_row['mmr']}**",
        "",
        "📋 **Состав:**",
    ]

    filled = 0
    total_ovr = 0

    for key, label in positions:
        card_id = roster[f"{key}_id"] if roster else None

        if not card_id:
            lines.append(f"{label}: ❌ Не выбран")
            continue

        cur.execute(
            "SELECT nickname, ovr FROM cards WHERE id = %s",
            (card_id,),
        )
        card = cur.fetchone()

        if not card:
            lines.append(f"{label}: ❌ Карточка не найдена")
            continue

        filled += 1
        total_ovr += card["ovr"]
        lines.append(
            f"{label}: **{card['nickname']}** ({card['ovr']} OVR)"
        )

    average = round(total_ovr / 5, 1) if filled == 5 else 0
    lines.insert(
        4,
        f"⭐ Средний OVR: **{average if average else 'Состав не собран'}**",
    )

    conn.close()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚙️ Изменить состав",
                    callback_data="edit_roster_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="refresh_profile",
                )
            ],
        ]
    )

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def profile_callback(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    if data == "refresh_profile":
        await show_profile_from_callback(update, context)
        return

    if data == "edit_roster_menu":
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🧤 Вратарь",
                        callback_data="set_pos_goalie",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏒 Полевой 1",
                        callback_data="set_pos_skater1",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏒 Полевой 2",
                        callback_data="set_pos_skater2",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏒 Полевой 3",
                        callback_data="set_pos_skater3",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🏒 Полевой 4",
                        callback_data="set_pos_skater4",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Назад",
                        callback_data="refresh_profile",
                    )
                ],
            ]
        )

        await query.edit_message_text(
            "⚙️ **Выберите позицию:**",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    if data.startswith("set_pos_"):
        position_key = data.replace("set_pos_", "")
        position = "Goalie" if position_key == "goalie" else "Skater"

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.id, c.nickname, c.ovr
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s
              AND uc.count > 0
              AND c.position = %s
            ORDER BY c.ovr DESC
            """,
            (user.id, position),
        )
        cards = cur.fetchall()
        conn.close()

        if not cards:
            await query.answer(
                "❌ Нет подходящих карточек.",
                show_alert=True,
            )
            return

        keyboard = [
            [
                InlineKeyboardButton(
                    f"{card['nickname']} — {card['ovr']} OVR",
                    callback_data=f"apply_card_{position_key}_{card['id']}",
                )
            ]
            for card in cards
        ]

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔙 Назад",
                    callback_data="edit_roster_menu",
                )
            ]
        )

        await query.edit_message_text(
            "📋 **Выберите карточку:**",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("apply_card_"):
        parts = data.split("_")
        position_key = parts[2]
        card_id = int(parts[3])

        allowed = {
            "goalie",
            "skater1",
            "skater2",
            "skater3",
            "skater4",
        }

        if position_key not in allowed:
            return

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            "SELECT 1 FROM user_cards WHERE user_id = %s AND card_id = %s AND count > 0",
            (user.id, card_id),
        )

        if not cur.fetchone():
            conn.close()
            await query.answer(
                "❌ Эта карточка отсутствует в инвентаре.",
                show_alert=True,
            )
            return

        cur.execute(
            "SELECT * FROM user_rosters WHERE user_id = %s",
            (user.id,),
        )
        roster = cur.fetchone()

        if not roster:
            cur.execute(
                "INSERT INTO user_rosters(user_id) VALUES (%s)",
                (user.id,),
            )
            cur.execute(
                "SELECT * FROM user_rosters WHERE user_id = %s",
                (user.id,),
            )
            roster = cur.fetchone()

        for key, _ in [
            ("goalie", ""),
            ("skater1", ""),
            ("skater2", ""),
            ("skater3", ""),
            ("skater4", ""),
        ]:
            if key != position_key and roster[f"{key}_id"] == card_id:
                conn.close()
                await query.answer(
                    "❌ Карточка уже используется в составе.",
                    show_alert=True,
                )
                return

        cur.execute(
            f"""
            UPDATE user_rosters
            SET {position_key}_id = %s
            WHERE user_id = %s
            """,
            (card_id, user.id),
        )

        conn.commit()
        conn.close()

        await query.answer("✅ Состав обновлён.")
        await show_profile_from_callback(update, context)


async def show_profile_from_callback(update, context):
    user = update.callback_query.from_user

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        "SELECT balance, mmr FROM users WHERE user_id = %s",
        (user.id,),
    )
    user_row = cur.fetchone()

    cur.execute(
        "SELECT * FROM user_rosters WHERE user_id = %s",
        (user.id,),
    )
    roster = cur.fetchone()

    text = (
        f"🏒 **Профиль {user.first_name or 'игрока'}**\n\n"
        f"💳 Баланс: **{user_row['balance']} RPLCoin**\n"
        f"🏆 MMR: **{user_row['mmr']}**\n\n"
        "📋 **Состав:**\n"
    )

    for key, label in [
        ("goalie", "🧤 Вратарь"),
        ("skater1", "🏒 Полевой 1"),
        ("skater2", "🏒 Полевой 2"),
        ("skater3", "🏒 Полевой 3"),
        ("skater4", "🏒 Полевой 4"),
    ]:
        card_id = roster[f"{key}_id"] if roster else None

        if not card_id:
            text += f"{label}: ❌ Не выбран\n"
            continue

        cur.execute(
            "SELECT nickname, ovr FROM cards WHERE id = %s",
            (card_id,),
        )
        card = cur.fetchone()

        if card:
            text += (
                f"{label}: **{card['nickname']}** "
                f"({card['ovr']} OVR)\n"
            )
        else:
            text += f"{label}: ❌ Не найден\n"

    conn.close()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⚙️ Изменить состав",
                    callback_data="edit_roster_menu",
                )
            ],
            [
                InlineKeyboardButton(
                    "🔄 Обновить",
                    callback_data="refresh_profile",
                )
            ],
        ]
    )

    try:
        await update.callback_query.message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
    except Exception:
        await context.bot.send_message(
            chat_id=user.id,
            text=text,
            reply_markup=keyboard,
            parse_mode="Markdown",
        )


async def cardmatch_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM user_rosters WHERE user_id = %s",
        (user.id,),
    )
    roster = cur.fetchone()
    conn.close()

    complete = roster and all(
        roster[f"{key}_id"]
        for key in [
            "goalie",
            "skater1",
            "skater2",
            "skater3",
            "skater4",
        ]
    )

    if not complete:
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🎁 Получить стартовый набор карточек",
                        callback_data="claim_freepack_btn",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "⚙️ Собрать состав",
                        callback_data="edit_roster_menu",
                    )
                ],
            ]
        )

        await update.message.reply_text(
            "❌ **Состав не собран.**\n"
            "Для поиска матча нужен 1 вратарь и 4 полевых игрока.",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    await update.message.reply_text(
        "🔎 Поиск соперника запущен.\n"
        "Матч будет доступен в следующем игровом модуле.",
    )


async def shop_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username, user.first_name)

    await show_shop(update, context)


async def show_shop(update, context):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM packs
        WHERE available_until IS NULL
           OR available_until > %s
        ORDER BY id DESC
        """,
        (datetime.now(),),
    )
    packs = cur.fetchall()

    lines = ["🛒 **МАГАЗИН ПАКОВ**", ""]
    keyboard = []

    for pack in packs:
        cur.execute(
            """
            SELECT buy_count
            FROM user_pack_buys
            WHERE user_id = %s
              AND pack_id = %s
            """,
            (user.id, pack["id"]),
        )
        buy_row = cur.fetchone()
        buy_count = buy_row["buy_count"] if buy_row else 0

        limit = (
            f"{buy_count}/{pack['buy_limit']}"
            if pack["buy_limit"] > 0
            else "без лимита"
        )

        lines.append(
            f"📦 **{pack['name']}** — "
            f"`{pack['price']} RPLCoin` "
            f"(куплено: {limit})"
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"📦 {pack['name']}",
                    callback_data=f"preview_pack_{pack['id']}",
                )
            ]
        )

    conn.close()

    if not packs:
        lines.append("Магазин пока пуст.")

    markup = InlineKeyboardMarkup(keyboard) if keyboard else None

    if query:
        await query.answer()
        try:
            await query.message.edit_text(
                "\n".join(lines),
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text="\n".join(lines),
                reply_markup=markup,
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=markup,
            parse_mode="Markdown",
        )


async def shop_callback_handler(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    if data == "cancel_pack_buy":
        await show_shop(update, context)
        return

    pack_id = int(data.split("_")[-1])

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT *
        FROM packs
        WHERE id = %s
          AND (
              available_until IS NULL
              OR available_until > %s
          )
        """,
        (pack_id, datetime.now()),
    )
    pack = cur.fetchone()

    if not pack:
        conn.close()
        await query.answer(
            "❌ Пак не найден или уже недоступен.",
            show_alert=True,
        )
        return

    cur.execute(
        """
        SELECT c.nickname, c.position, c.ovr, c.rarity
        FROM pack_cards pc
        JOIN cards c ON c.id = pc.card_id
        WHERE pc.pack_id = %s
        ORDER BY c.ovr DESC
        """,
        (pack_id,),
    )
    cards = cur.fetchall()

    card_text = "\n".join(
        f"• {card['nickname']} — {card['ovr']} OVR "
        f"[{card['rarity']}]"
        for card in cards
    ) or "Карточки не настроены."

    if data.startswith("preview_pack_"):
        conn.close()

        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Купить пак",
                        callback_data=f"confirm_pack_{pack_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "🔙 Назад",
                        callback_data="cancel_pack_buy",
                    )
                ],
            ]
        )

        await query.edit_message_text(
            f"📦 **{pack['name']}**\n\n"
            f"💰 Цена: **{pack['price']} RPLCoin**\n\n"
            f"🃏 Возможные карточки:\n{card_text}",
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        return

    if data.startswith("confirm_pack_"):
        cur.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = %s
            FOR UPDATE
            """,
            (user.id,),
        )
        balance = cur.fetchone()["balance"]

        cur.execute(
            """
            SELECT buy_count
            FROM user_pack_buys
            WHERE user_id = %s
              AND pack_id = %s
            """,
            (user.id, pack_id),
        )
        buy_row = cur.fetchone()
        buy_count = buy_row["buy_count"] if buy_row else 0

        if pack["buy_limit"] > 0 and buy_count >= pack["buy_limit"]:
            conn.close()
            await query.answer(
                "❌ Лимит покупок исчерпан.",
                show_alert=True,
            )
            return

        if balance < pack["price"]:
            conn.close()
            await query.answer(
                "❌ Недостаточно средств.",
                show_alert=True,
            )
            return

        if not cards:
            conn.close()
            await query.answer(
                "❌ В паке нет карточек.",
                show_alert=True,
            )
            return

        cur.execute(
            """
            SELECT c.*
            FROM pack_cards pc
            JOIN cards c ON c.id = pc.card_id
            WHERE pc.pack_id = %s
            """,
            (pack_id,),
        )
        candidates = cur.fetchall()
        chosen = choose_card_for_user(cur, user.id, candidates)

        cur.execute(
            """
            UPDATE users
            SET balance = balance - %s
            WHERE user_id = %s
              AND balance >= %s
            """,
            (pack["price"], user.id, pack["price"]),
        )

        if cur.rowcount != 1:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Покупка не выполнена.",
                show_alert=True,
            )
            return

        cur.execute(
            """
            INSERT INTO user_pack_buys(user_id, pack_id, buy_count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, pack_id)
            DO UPDATE SET buy_count = user_pack_buys.buy_count + 1
            """,
            (user.id, pack_id),
        )

        add_user_card(cur, user.id, chosen["id"], 1)

        conn.commit()
        conn.close()

        await query.edit_message_text(
            f"🎉 **Пак открыт!**\n\n"
            f"Вам выпала карточка:\n"
            f"🃏 **{chosen['nickname']}**\n"
            f"⭐ {chosen['ovr']} OVR\n"
            f"✨ {chosen['rarity']}",
            parse_mode="Markdown",
        )


async def cardshop_command(update, context):
    if not await check_pm_registered(update, context):
        return

    await show_market(update, context)


async def show_market(update, context):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT
            m.id AS market_id,
            m.price,
            m.seller_id,
            c.nickname,
            c.position,
            c.ovr,
            c.rarity,
            u.username,
            u.first_name
        FROM market m
        JOIN cards c ON c.id = m.card_id
        JOIN users u ON u.user_id = m.seller_id
        ORDER BY m.id DESC
        LIMIT 25
        """
    )
    lots = cur.fetchall()

    cur.execute(
        "SELECT COUNT(*) AS total FROM market WHERE seller_id = %s",
        (user.id,),
    )
    own_count = cur.fetchone()["total"]
    conn.close()

    lines = [
        "🛒 **ТОРГОВАЯ ПЛОЩАДКА**",
        "",
    ]
    keyboard = []

    if not lots:
        lines.append("На рынке пока нет лотов.")
    else:
        for lot in lots:
            seller = (
                f"@{lot['username']}"
                if lot["username"]
                else lot["first_name"] or "Игрок"
            )

            lines.append(
                f"🏷 **#{lot['market_id']}** "
                f"{lot['nickname']} — "
                f"**{lot['price']} RPLCoin** "
                f"({seller})"
            )

            if lot["seller_id"] != user.id:
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"Купить #{lot['market_id']}",
                            callback_data=f"buy_market_{lot['market_id']}",
                        )
                    ]
                )

    navigation = []

    if own_count:
        navigation.append(
            InlineKeyboardButton(
                f"📦 Мои лоты ({own_count})",
                callback_data="my_market_items",
            )
        )

    navigation.append(
        InlineKeyboardButton(
            "🔄 Обновить",
            callback_data="refresh_market",
        )
    )

    keyboard.append(navigation)
    markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.answer()
        try:
            await query.message.edit_text(
                "\n".join(lines),
                reply_markup=markup,
                parse_mode="Markdown",
            )
        except Exception:
            await context.bot.send_message(
                chat_id=user.id,
                text="\n".join(lines),
                reply_markup=markup,
                parse_mode="Markdown",
            )
    else:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=markup,
            parse_mode="Markdown",
        )


async def market_start_list_card(update, context):
    query = update.callback_query
    user = query.from_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.position, uc.count
        FROM user_cards uc
        JOIN cards c ON c.id = uc.card_id
        WHERE uc.user_id = %s
          AND uc.count > 0
        ORDER BY c.ovr DESC
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    if not cards:
        await query.answer(
            "❌ У вас нет карточек.",
            show_alert=True,
        )
        return

    keyboard = [
        [
            InlineKeyboardButton(
                f"{card['nickname']} "
                f"({card['ovr']} OVR, x{card['count']})",
                callback_data=f"select_mcard_{card['id']}",
            )
        ]
        for card in cards
    ]

    keyboard.append(
        [
            InlineKeyboardButton(
                "🔙 Назад",
                callback_data="refresh_inv",
            )
        ]
    )

    await query.edit_message_text(
        "🏷 **Выберите карточку для продажи:**",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def market_callback_handler(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    data = query.data

    if data == "market_list_menu":
        await market_start_list_card(update, context)
        return WAITING_MARKET_PRICE_INPUT

    if data == "refresh_market":
        await show_market(update, context)
        return

    if data == "my_market_items":
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
        lots = cur.fetchall()
        conn.close()

        keyboard = []
        lines = ["📦 **Мои лоты:**", ""]

        if not lots:
            lines.append("Активных лотов нет.")
        else:
            for lot in lots:
                lines.append(
                    f"#{lot['id']} — {lot['nickname']} "
                    f"({lot['ovr']} OVR) — {lot['price']} RPLCoin"
                )
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"❌ Снять #{lot['id']}",
                            callback_data=f"cancel_market_{lot['id']}",
                        )
                    ]
                )

        keyboard.append(
            [
                InlineKeyboardButton(
                    "🔙 Назад",
                    callback_data="refresh_market",
                )
            ]
        )

        await query.edit_message_text(
            "\n".join(lines),
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    if data.startswith("select_mcard_"):
        card_id = int(data.split("_")[-1])
        context.user_data["market_card_id"] = card_id

        await query.message.reply_text(
            "💲 Введите цену карточки от 1 до 999999 RPLCoin:",
        )
        return WAITING_MARKET_PRICE_INPUT

    if data.startswith("cancel_market_"):
        market_id = int(data.split("_")[-1])

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT card_id
            FROM market
            WHERE id = %s
              AND seller_id = %s
            FOR UPDATE
            """,
            (market_id, user.id),
        )
        lot = cur.fetchone()

        if not lot:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Лот уже снят или не принадлежит вам.",
                show_alert=True,
            )
            return

        add_user_card(cur, user.id, lot["card_id"], 1)
        cur.execute(
            "DELETE FROM market WHERE id = %s",
            (market_id,),
        )

        conn.commit()
        conn.close()

        await query.answer(
            "✅ Карточка возвращена в инвентарь.",
            show_alert=True,
        )
        await show_market(update, context)
        return

    if data.startswith("buy_market_"):
        market_id = int(data.split("_")[-1])

        conn = get_db()
        cur = conn.cursor()

        cur.execute(
            """
            SELECT *
            FROM market
            WHERE id = %s
            FOR UPDATE
            """,
            (market_id,),
        )
        lot = cur.fetchone()

        if not lot:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Лот уже продан или снят.",
                show_alert=True,
            )
            return

        if lot["seller_id"] == user.id:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Нельзя купить собственный лот.",
                show_alert=True,
            )
            return

        cur.execute(
            """
            SELECT balance
            FROM users
            WHERE user_id = %s
            FOR UPDATE
            """,
            (user.id,),
        )
        buyer = cur.fetchone()

        if not buyer or buyer["balance"] < lot["price"]:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Недостаточно средств.",
                show_alert=True,
            )
            return

        cur.execute(
            """
            UPDATE users
            SET balance = balance - %s
            WHERE user_id = %s
              AND balance >= %s
            """,
            (lot["price"], user.id, lot["price"]),
        )

        if cur.rowcount != 1:
            conn.rollback()
            conn.close()
            await query.answer(
                "❌ Покупка не выполнена.",
                show_alert=True,
            )
            return

        cur.execute(
            """
            UPDATE users
            SET balance = balance + %s
            WHERE user_id = %s
            """,
            (lot["price"], lot["seller_id"]),
        )

        add_user_card(cur, user.id, lot["card_id"], 1)

        cur.execute(
            "DELETE FROM market WHERE id = %s",
            (market_id,),
        )

        conn.commit()
        conn.close()

        await query.answer(
            "🎉 Карточка куплена.",
            show_alert=True,
        )
        await show_market(update, context)


async def market_price_receive(update, context):
    try:
        price = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите целое число.")
        return WAITING_MARKET_PRICE_INPUT

    if price < 1 or price > 999999:
        await update.message.reply_text(
            "❌ Цена должна быть от 1 до 999999."
        )
        return WAITING_MARKET_PRICE_INPUT

    user = update.effective_user
    card_id = context.user_data.get("market_card_id")

    if not card_id:
        await update.message.reply_text("❌ Карточка не выбрана.")
        return ConversationHandler.END

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT count
        FROM user_cards
        WHERE user_id = %s
          AND card_id = %s
          AND count > 0
        FOR UPDATE
        """,
        (user.id, card_id),
    )
    row = cur.fetchone()

    if not row:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ Карточка отсутствует в инвентаре."
        )
        return ConversationHandler.END

    if not remove_user_card(cur, user.id, card_id, 1):
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ Не удалось списать карточку."
        )
        return ConversationHandler.END

    cur.execute(
        """
        UPDATE user_rosters
        SET goalie_id = CASE WHEN goalie_id = %s THEN NULL ELSE goalie_id END,
            skater1_id = CASE WHEN skater1_id = %s THEN NULL ELSE skater1_id END,
            skater2_id = CASE WHEN skater2_id = %s THEN NULL ELSE skater2_id END,
            skater3_id = CASE WHEN skater3_id = %s THEN NULL ELSE skater3_id END,
            skater4_id = CASE WHEN skater4_id = %s THEN NULL ELSE skater4_id END
        WHERE user_id = %s
        """,
        (
            card_id,
            card_id,
            card_id,
            card_id,
            card_id,
            user.id,
        ),
    )

    cur.execute(
        """
        INSERT INTO market(seller_id, card_id, price)
        VALUES (%s, %s, %s)
        """,
        (user.id, card_id, price),
    )

    conn.commit()
    conn.close()

    context.user_data.pop("market_card_id", None)

    await update.message.reply_text(
        f"✅ Карточка выставлена за {price} RPLCoin."
    )
    await show_market(update, context)

    return ConversationHandler.END


async def casino_command(update, context):
    if not await check_pm_registered(update, context):
        return

    await update.message.reply_text(
        "🎰 **Казино**\nВыберите игру:",
        reply_markup=casino_keyboard(),
        parse_mode="Markdown",
    )


async def casino_game_callback(update, context):
    query = update.callback_query
    await query.answer()

    data = query.data

    if data == "casino_rps":
        context.user_data["casino_game"] = "rps"
        context.user_data["rps_from_casino"] = True
        await query.message.reply_text(
            "🎮 Введите ставку для КНБ:",
        )
        return WAITING_RPS_BET

    if data == "casino_slots":
        context.user_data["casino_game"] = "slots"
        await query.message.reply_text(
            "🎰 Введите ставку для слотов:",
        )
        return WAITING_CASINO_BET

    if data == "casino_dice":
        context.user_data["casino_game"] = "dice"
        await query.message.reply_text(
            "🎲 Введите ставку для костей:",
        )
        return WAITING_CASINO_BET


async def casino_bet_receive(update, context):
    try:
        bet = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите ставку целым числом.")
        return WAITING_CASINO_BET

    if bet <= 0:
        await update.message.reply_text(
            "❌ Ставка должна быть больше нуля."
        )
        return WAITING_CASINO_BET

    if bet > 1000000:
        await update.message.reply_text(
            "❌ Максимальная ставка — 1 000 000 RPLCoin."
        )
        return WAITING_CASINO_BET

    user = update.effective_user
    game = context.user_data.get("casino_game")

    if game not in {"slots", "dice"}:
        await update.message.reply_text("❌ Игра не выбрана.")
        return ConversationHandler.END

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user.id,),
    )
    row = cur.fetchone()

    if not row or row["balance"] < bet:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ Недостаточно RPLCoin для этой ставки."
        )
        return WAITING_CASINO_BET

    cur.execute(
        """
        UPDATE users
        SET balance = balance - %s
        WHERE user_id = %s
          AND balance >= %s
        """,
        (bet, user.id, bet),
    )

    if cur.rowcount != 1:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ Ставка не была принята."
        )
        return ConversationHandler.END

    if game == "slots":
        result_text, payout = play_slots(bet)
    else:
        result_text, payout = play_dice(bet)

    if payout:
        cur.execute(
            """
            UPDATE users
            SET balance = balance + %s
            WHERE user_id = %s
            """,
            (payout, user.id),
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        result_text
        + f"\n\n💳 Изменение баланса: "
        f"{payout - bet:+d} RPLCoin",
        parse_mode="Markdown",
    )

    context.user_data.pop("casino_game", None)
    return ConversationHandler.END


def play_slots(bet):
    symbols = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣"]

    reels = [
        random.choice(symbols),
        random.choice(symbols),
        random.choice(symbols),
    ]

    if reels[0] == reels[1] == reels[2]:
        multiplier = {
            "🍒": 4,
            "🍋": 5,
            "🔔": 7,
            "⭐": 10,
            "💎": 20,
            "7️⃣": 35,
        }.get(reels[0], 4)

        payout = bet * multiplier
        result = "🎉 **ДЖЕКПОТ!**"
    elif len(set(reels)) == 2:
        payout = bet * 2
        result = "✨ **Две одинаковые!**"
    else:
        payout = 0
        result = "💨 Совпадений нет."

    text = (
        "🎰 **СЛОТЫ**\n\n"
        f"[ {reels[0]} | {reels[1]} | {reels[2]} ]\n\n"
        f"{result}\n"
        f"💰 Выплата: **{payout} RPLCoin**"
    )

    return text, payout


def play_dice(bet):
    bot_roll = random.SystemRandom().randint(1, 6)
    player_roll = random.SystemRandom().randint(1, 6)

    if player_roll > bot_roll:
        payout = bet * 2
        result = "🎉 **Вы победили!**"
    elif player_roll == bot_roll:
        payout = bet
        result = "🤝 **Ничья.** Ставка возвращена."
    else:
        payout = 0
        result = "❌ **Вы проиграли.**"

    text = (
        "🎲 **КОСТИ**\n\n"
        f"🤖 Бросок казино: **{bot_roll}**\n"
        f"👤 Бросок за игрока: **{player_roll}**\n\n"
        f"{result}\n"
        f"💰 Выплата: **{payout} RPLCoin**"
    )

    return text, payout


async def rps_command(update, context):
    if not await check_pm_registered(update, context):
        return

    context.user_data["casino_game"] = "rps"
    await update.message.reply_text(
        "🎮 Введите ставку для КНБ:",
    )
    return WAITING_RPS_BET


async def rps_bet_receive(update, context):
    try:
        bet = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Введите ставку числом.")
        return WAITING_RPS_BET

    if bet <= 0:
        await update.message.reply_text(
            "❌ Ставка должна быть больше нуля."
        )
        return WAITING_RPS_BET

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT balance
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user.id,),
    )
    row = cur.fetchone()

    if not row or row["balance"] < bet:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ Недостаточно средств."
        )
        return WAITING_RPS_BET

    choice_keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🪨 Камень",
                    callback_data="rps_rock",
                ),
                InlineKeyboardButton(
                    "✂️ Ножницы",
                    callback_data="rps_scissors",
                ),
                InlineKeyboardButton(
                    "📄 Бумага",
                    callback_data="rps_paper",
                ),
            ]
        ]
    )

    context.user_data["rps_bet"] = bet

    conn.close()

    await update.message.reply_text(
        f"✅ Ставка **{bet} RPLCoin** принята.\n"
        "Выберите ход:",
        reply_markup=choice_keyboard,
        parse_mode="Markdown",
    )

    return ConversationHandler.END


async def rps_callback(update, context):
    query = update.callback_query
    await query.answer()

    user = query.from_user
    player = query.data.replace("rps_", "")
    bet = context.user_data.get("rps_bet", 0)

    if bet <= 0:
        await query.edit_message_text("❌ Ставка не найдена.")
        return

    bot = random.choice(["rock", "scissors", "paper"])

    beats = {
        "rock": "scissors",
        "scissors": "paper",
        "paper": "rock",
    }

    if player == bot:
        payout = bet
        result = "🤝 Ничья. Ставка возвращена."
    elif beats[player] == bot:
        payout = bet * 2
        result = f"🎉 Победа! Выплата: {payout} RPLCoin."
    else:
        payout = 0
        result = "❌ Поражение. Выплата: 0 RPLCoin."

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        UPDATE users
        SET balance = balance + %s
        WHERE user_id = %s
        """,
        (payout, user.id),
    )

    conn.commit()
    conn.close()

    names = {
        "rock": "🪨 Камень",
        "scissors": "✂️ Ножницы",
        "paper": "📄 Бумага",
    }

    await query.edit_message_text(
        "🎮 **КНБ**\n\n"
        f"👤 Ваш ход: {names[player]}\n"
        f"🤖 Ход бота: {names[bot]}\n\n"
        f"{result}",
        parse_mode="Markdown",
    )

    context.user_data.pop("rps_bet", None)


async def daily_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT last_daily_claim, daily_streak
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user.id,),
    )
    row = cur.fetchone()
    now = datetime.now()

    if row and row["last_daily_claim"]:
        diff = now - row["last_daily_claim"]

        if diff.total_seconds() < 86400:
            remaining = timedelta(seconds=86400) - diff
            hours = int(remaining.total_seconds() // 3600)
            minutes = int(remaining.total_seconds() % 3600 // 60)
            conn.rollback()
            conn.close()

            await update.message.reply_text(
                f"⏳ Бонус будет доступен через "
                f"**{hours} ч {minutes} мин**.",
                parse_mode="Markdown",
            )
            return

    streak = (row["daily_streak"] if row else 0) + 1
    if streak > 7:
        streak = 1

    rewards = {
        1: 5000,
        2: 10000,
        3: 15000,
        4: 20000,
        5: 30000,
        6: 40000,
        7: 75000,
    }

    reward = rewards[streak]

    cur.execute(
        """
        UPDATE users
        SET balance = balance + %s,
            daily_streak = %s,
            last_daily_claim = %s
        WHERE user_id = %s
        """,
        (reward, streak, now, user.id),
    )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎁 Ежедневный бонус **{streak}/7** получен!\n"
        f"💳 +{reward} RPLCoin",
        parse_mode="Markdown",
    )


async def wheel_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    cost = 10000
    now = datetime.now()

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT balance, last_wheel_spin
        FROM users
        WHERE user_id = %s
        FOR UPDATE
        """,
        (user.id,),
    )
    row = cur.fetchone()

    if not row or row["balance"] < cost:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            f"❌ Для вращения нужно {cost} RPLCoin."
        )
        return

    if row["last_wheel_spin"]:
        if now - row["last_wheel_spin"] < timedelta(hours=36):
            conn.rollback()
            conn.close()
            await update.message.reply_text(
                "⏳ Колесо можно крутить раз в 36 часов."
            )
            return

    prizes = [
        ("money", 10000),
        ("money", 25000),
        ("money", 50000),
        ("card", 0),
        ("nothing", 0),
    ]

    prize, value = random.choice(prizes)

    cur.execute(
        """
        UPDATE users
        SET balance = balance - %s,
            last_wheel_spin = %s
        WHERE user_id = %s
        """,
        (cost, now, user.id),
    )

    if prize == "money":
        cur.execute(
            """
            UPDATE users
            SET balance = balance + %s
            WHERE user_id = %s
            """,
            (value, user.id),
        )
        text = f"🎡 Вы выиграли **{value} RPLCoin**!"
    elif prize == "card":
        cur.execute(
            """
            SELECT *
            FROM cards
            WHERE rarity != 'Секретная'
            ORDER BY random()
            LIMIT 1
            """
        )
        card = cur.fetchone()

        if card:
            add_user_card(cur, user.id, card["id"], 1)
            text = (
                f"🎡 Вы выиграли карточку "
                f"**{card['nickname']}**!"
            )
        else:
            text = "🎡 В базе пока нет карточек."
    else:
        text = "🎡 В этот раз ничего не выпало."

    conn.commit()
    conn.close()

    await update.message.reply_text(
        text,
        parse_mode="Markdown",
    )


async def admin_freepack_start(update, context):
    await update.message.reply_text(
        "📦 Введите ID карточек стартового набора через пробел.\n"
        "Нужно указать минимум 1 Goalie и 4 Skater.\n\n"
        "Пример: `1 2 3 4 5`",
        parse_mode="Markdown",
    )
    return FREEPACK_ADMIN_SELECT_CARDS


async def admin_freepack_receive(update, context):
    try:
        ids = [int(value) for value in update.message.text.split()]
    except ValueError:
        await update.message.reply_text(
            "❌ Используйте только числовые ID."
        )
        return FREEPACK_ADMIN_SELECT_CARDS

    if len(ids) < 5:
        await update.message.reply_text(
            "❌ Нужно минимум 5 карточек."
        )
        return FREEPACK_ADMIN_SELECT_CARDS

    conn = get_db()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT id, position
        FROM cards
        WHERE id IN %s
        """,
        (tuple(set(ids)),),
    )
    cards = cur.fetchall()

    goalies = [card for card in cards if card["position"] == "Goalie"]
    skaters = [card for card in cards if card["position"] == "Skater"]

    if len(goalies) < 1 or len(skaters) < 4:
        conn.rollback()
        conn.close()
        await update.message.reply_text(
            "❌ В наборе должен быть минимум 1 Goalie и 4 Skater."
        )
        return FREEPACK_ADMIN_SELECT_CARDS

    cur.execute("DELETE FROM freepack_config")

    for card_id in ids:
        cur.execute(
            """
            INSERT INTO freepack_config(card_id)
            VALUES (%s)
            ON CONFLICT DO NOTHING
            """,
            (card_id,),
        )

    conn.commit()
    conn.close()

    await update.message.reply_text(
        "✅ Стартовый набор сохранён.",
        reply_markup=card_admin_keyboard(),
    )
    return CARD_ADMIN_MENU


async def admin_auth_start(update, context):
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "Команда доступна только в личных сообщениях."
        )
        return ConversationHandler.END

    await update.message.reply_text("🔑 Введите логин:")
    return WAITING_LOGIN


async def admin_login_receive(update, context):
    context.user_data["admin_login"] = update.message.text
    await update.message.reply_text("🔒 Введите пароль:")
    return WAITING_PASSWORD


async def admin_password_receive(update, context):
    login = context.user_data.get("admin_login")
    password = update.message.text

    if check_credentials(login, password):
        add_admin(update.effective_user.id)
        context.user_data.clear()

        await update.message.reply_text(
            "✅ Авторизация успешна.",
            reply_markup=admin_menu_keyboard(),
        )
    else:
        await update.message.reply_text("❌ Неверные данные.")

    return ConversationHandler.END


async def admin_buttons(update, context):
    user_id = update.effective_user.id

    if not is_admin(user_id):
        return

    update_admin_activity(user_id)
    text = update.message.text

    if text == "🃏 Карточки":
        await update.message.reply_text(
            "🃏 **Управление карточками:**",
            reply_markup=card_admin_keyboard(),
            parse_mode="Markdown",
        )
        return CARD_ADMIN_MENU

    if text == "📦 Выставить пак в магазин":
        await update.message.reply_text(
            "Функция временного размещения паков доступна "
            "через настройки магазина."
        )
        return ConversationHandler.END

    if text == "🔍 Инвентарь игрока":
        await update.message.reply_text(
            "Введите ID или username игрока:"
        )
        return WAITING_VIEW_USER_INV

    if text == "📩 Проверить поддержку":
        messages = get_unanswered_messages()

        if not messages:
            await update.message.reply_text(
                "📭 Новых обращений нет.",
                reply_markup=admin_menu_keyboard(),
            )
            return ConversationHandler.END

        message = messages[0]

        await update.message.reply_text(
            f"📩 Обращение #{message['id']}\n\n"
            f"{message['text']}",
            reply_markup=admin_menu_keyboard(),
        )
        return ConversationHandler.END

    if text == "🚪 Выйти":
        remove_admin(user_id)
        await update.message.reply_text(
            "🚪 Вы вышли из админ-панели.",
            reply_markup=main_menu_keyboard(),
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Раздел пока не изменяет настройки.",
        reply_markup=admin_menu_keyboard(),
    )
    return ConversationHandler.END


async def admin_card_menu(update, context):
    text = update.message.text

    if text == "📦 Настроить стартовый набор":
        return await admin_freepack_start(update, context)

    await update.message.reply_text(
        "Выберите доступное действие.",
        reply_markup=card_admin_keyboard(),
    )
    return CARD_ADMIN_MENU


async def support_callback(update, context):
    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "✍️ Напишите сообщение для поддержки:"
    )
    return WAITING_SUPPORT_MSG


async def support_receive(update, context):
    user = update.effective_user

    add_support_message(
        user.id,
        user.username or str(user.id),
        update.message.text,
    )

    await update.message.reply_text(
        "✅ Сообщение отправлено в поддержку."
    )
    return ConversationHandler.END


async def inline_callback(update, context):
    query = update.callback_query
    await query.answer()

    if query.data == "discord":
        await query.message.reply_text(
            "💬 Discord: https://discord.gg/dgkFMCgDwx"
        )
    elif query.data == "website":
        await query.message.reply_text(
            "🌐 Сайт: https://rplpuck.ru"
        )
    elif query.data == "duel":
        await query.message.reply_text(
            "🏒 Выберите направление броска:",
            reply_markup=duel_keyboard(),
        )


async def duel_callback(update, context):
    query = update.callback_query
    await query.answer()

    if random.random() < 0.35:
        await query.edit_message_text("⚡️ **ГОЛ!**")
    else:
        await query.edit_message_text("🧤 **СЕЙВ!**")


async def text_minigames(update, context):
    if not await check_pm_registered(update, context):
        return

    await casino_command(update, context)


def build_application():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("getid", getid_command))
    app.add_handler(CommandHandler("freepack", freepack_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("cardmatch", cardmatch_command))
    app.add_handler(CommandHandler("shop", shop_command))
    app.add_handler(CommandHandler("cardshop", cardshop_command))
    app.add_handler(CommandHandler("casino", casino_command))
    app.add_handler(CommandHandler("rps", rps_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("wheel", wheel_command))
    app.add_handler(CommandHandler("adminkarpl", admin_auth_start))

    app.add_handler(
        ConversationHandler(
            entry_points=[
                CallbackQueryHandler(
                    market_callback_handler,
                    pattern=r"^select_mcard_",
                )
            ],
            states={
                WAITING_MARKET_PRICE_INPUT: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        market_price_receive,
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
                    casino_game_callback,
                    pattern=r"^casino_(slots|dice|rps)$",
                )
            ],
            states={
                WAITING_CASINO_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        casino_bet_receive,
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
                CommandHandler("rps", rps_command),
            ],
            states={
                WAITING_RPS_BET: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        rps_bet_receive,
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
                CommandHandler("adminkarpl", admin_auth_start),
            ],
            states={
                WAITING_LOGIN: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_login_receive,
                    )
                ],
                WAITING_PASSWORD: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_password_receive,
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
                MessageHandler(
                    filters.Regex(r"^🃏 Карточки$")
                    & filters.ChatType.PRIVATE,
                    admin_buttons,
                )
            ],
            states={
                CARD_ADMIN_MENU: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_card_menu,
                    )
                ],
                FREEPACK_ADMIN_SELECT_CARDS: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND,
                        admin_freepack_receive,
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
                CallbackQueryHandler(
                    support_callback,
                    pattern=r"^support$",
                )
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
        MessageHandler(
            filters.Regex(r"^🏠 Главное меню$"),
            main_menu,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🎒 Инвентарь$"),
            inventory_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🏒 Состав и Профиль$"),
            profile_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^⚔️ Искать игру$"),
            cardmatch_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🛒 Магазин Паков$"),
            shop_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🛒 Торговая площадка$"),
            cardshop_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🎮 Мини-игры$"),
            text_minigames,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🎁 Ежедневный бонус$"),
            daily_command,
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(r"^🎡 Колесо удачи$"),
            wheel_command,
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            freepack_callback,
            pattern=r"^claim_freepack_btn$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            profile_callback,
            pattern=r"^(refresh_profile|edit_roster_menu|set_pos_|apply_card_)",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            market_callback_handler,
            pattern=r"^(market_list_menu|refresh_market|my_market_items|select_mcard_|cancel_market_|buy_market_)",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            shop_callback_handler,
            pattern=r"^(preview_pack_|confirm_pack_|cancel_pack_buy)",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            casino_game_callback,
            pattern=r"^casino_(slots|dice|rps)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            rps_callback,
            pattern=r"^rps_(rock|scissors|paper)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            duel_callback,
            pattern=r"^shot_(left|right|five|low)$",
        )
    )

    app.add_handler(
        CallbackQueryHandler(
            inline_callback,
            pattern=r"^(discord|website|duel)$",
        )
    )

    app.add_handler(
        MessageHandler(
            filters.Regex(
                r"^(📩 Проверить поддержку|⚙️ Настройки|"
                r"🎮 Настройки игры|🔍 Инвентарь игрока|🚪 Выйти)$"
            )
            & filters.ChatType.PRIVATE,
            admin_buttons,
        )
    )

    return app


def main():
    app = build_application()
    logger.info("Бот RPL успешно запущен.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
