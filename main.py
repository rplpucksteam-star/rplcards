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
FATIGUE_MATCH_LIMIT = 5
FATIGUE_RECOVERY_MINUTES = 30
UPGRADER_MAX_CHANCE = 40
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
    WAITING_SUPPORT_MSG,
    WAITING_DUEL_SHOT,
    WAITING_RPS_BET,
    WAITING_SLOTS_BET,
    WAITING_DICE_BET,
    WAITING_COIN_BET,
    WAITING_PROMO_INPUT,
    WAITING_MARKET_PRICE_INPUT,
    WAITING_TRADE_MONEY,
    WAITING_UPGRADE_SOURCE,
    WAITING_CRAFT_CARDS,
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
    FREEPACK_ADMIN_SELECT_CARDS,
    GRANT_CARD_DATA,
    GIVE_MONEY_DATA,
    WAITING_VIEW_USER_INV,
    ADD_PROMO_CODE,
    ADD_PROMO_TYPE,
    ADD_PROMO_VAL,
    ADD_PROMO_LIMIT,
    ADMIN_SHOP_PACK_SELECT,
    ADMIN_SHOP_PACK_HOURS,
) = range(44)


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
            shop_discount_percent INTEGER DEFAULT 0,
            shop_discount_until TIMESTAMP
        )
        """
    )

    cur.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS shop_discount_percent INTEGER DEFAULT 0,
        ADD COLUMN IF NOT EXISTS shop_discount_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS free_card_cooldown_reset_until TIMESTAMP,
        ADD COLUMN IF NOT EXISTS freepack_claimed BOOLEAN DEFAULT FALSE
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
            recovery_until TIMESTAMP,
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
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            pack_id INTEGER REFERENCES packs(id) ON DELETE CASCADE,
            buy_count INTEGER DEFAULT 0,
            PRIMARY KEY(user_id, pack_id)
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
        INSERT INTO bot_config(key, value) VALUES ('custom_card_prize_claimed', '0') ON CONFLICT DO NOTHING
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

    if row:
        cur.execute(
            """
            UPDATE users
            SET username = %s, first_name = %s
            WHERE user_id = %s
            """,
            (username, first_name, user_id),
        )
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    else:
        cur.execute(
            """
            INSERT INTO users(user_id, username, first_name)
            VALUES (%s, %s, %s)
            RETURNING *
            """,
            (user_id, username, first_name),
        )
        row = cur.fetchone()
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


async def check_pm_registered(update, context):
    user = update.effective_user
    if not user:
        return False

    if check_user_exists(user.id):
        return True

    username = await context.bot.get_me()
    markup = InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Открыть бота в ЛС", url=f"https://t.me/{username.username}?start=start")]]
    )

    if update.callback_query:
        await update.callback_query.answer("Сначала откройте бота в личных сообщениях!", show_alert=True)
    elif update.message:
        await update.message.reply_text(
            "⚠️ Сначала напишите боту в личные сообщения.",
            reply_markup=markup,
        )
    return False


def parse_dt(value):
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return value


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
        INSERT INTO bot_config(key, value)
        VALUES (%s, %s)
        ON CONFLICT(key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def is_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT last_activity FROM admins WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    conn.close()

    if not row:
        return False

    if time.time() - row["last_activity"] < ADMIN_SESSION_MINUTES * 60:
        return True

    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
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
        ON CONFLICT(user_id) DO UPDATE SET last_activity = EXCLUDED.last_activity
        """,
        (user_id, int(time.time())),
    )
    conn.commit()
    conn.close()


def update_admin_activity(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "UPDATE admins SET last_activity = %s WHERE user_id = %s",
        (int(time.time()), user_id),
    )
    conn.commit()
    conn.close()


def remove_admin(user_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM admins WHERE user_id = %s", (user_id,))
    conn.commit()
    conn.close()


def get_discount(cur, user_id):
    cur.execute(
        """
        SELECT shop_discount_percent, shop_discount_until
        FROM users WHERE user_id = %s
        """,
        (user_id,),
    )
    row = cur.fetchone()
    if not row:
        return 0

    until = parse_dt(row["shop_discount_until"])
    if row["shop_discount_percent"] and until and until > datetime.now():
        return min(90, max(0, row["shop_discount_percent"]))

    if row["shop_discount_percent"]:
        cur.execute(
            """
            UPDATE users
            SET shop_discount_percent = 0, shop_discount_until = NULL
            WHERE user_id = %s
            """,
            (user_id,),
        )
    return 0


def discounted_price(price, discount):
    return max(1, int(round(price * (100 - discount) / 100)))


def choose_card(cur, user_id, cards, strict=False):
    if not cards:
        return None

    ids = [card["id"] for card in cards]
    cur.execute(
        """
        SELECT card_id FROM user_cards
        WHERE user_id = %s AND card_id = ANY(%s) AND count > 0
        """,
        (user_id, ids),
    )
    owned = {row["card_id"] for row in cur.fetchall()}
    available = [card for card in cards if card["id"] not in owned]

    if strict and not available:
        return None
    return random.choice(available or cards)


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


def bet_cancel_keyboard():
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Назад", callback_data="cancel_minigame")]]
    )


def minigames_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🎮 Камень-Ножницы-Бумага", callback_data="play_rps")],
            [InlineKeyboardButton("🎰 Слоты", callback_data="play_slots")],
            [InlineKeyboardButton("🎲 Кости", callback_data="play_dice")],
            [InlineKeyboardButton("🪙 Орёл и решка", callback_data="play_coin")],
        ]
    )


def roster_keyboard():
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🧤 Вратарь", callback_data="set_pos_goalie")],
            [InlineKeyboardButton("🏒 Полевой 1", callback_data="set_pos_skater1")],
            [InlineKeyboardButton("🏒 Полевой 2", callback_data="set_pos_skater2")],
            [InlineKeyboardButton("🏒 Полевой 3", callback_data="set_pos_skater3")],
            [InlineKeyboardButton("🏒 Полевой 4", callback_data="set_pos_skater4")],
        ]
    )


async def start(update, context):
    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")
    await update.message.reply_text(
        "👋 Добро пожаловать в Russian Puck League!\n\n"
        "Собирай состав, открывай паки, играй матчи и прокачивай коллекцию.",
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(),
    )


async def main_menu(update, context):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text(
        "📌 Главное меню\nВыберите нужный раздел:",
        parse_mode="Markdown",
    )


async def minigames_menu(update, context):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text(
        "🕹 Мини-игры\nВыберите игру и сделайте ставку:",
        reply_markup=minigames_keyboard(),
        parse_mode="Markdown",
    )


async def freepack_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT freepack_claimed FROM users WHERE user_id = %s", (user.id,))
    row = cur.fetchone()

    if row and row["freepack_claimed"]:
        conn.close()
        await update.message.reply_text("❌ Вы уже получили стартовый набор.")
        return

    cur.execute("SELECT card_id FROM freepack_config")
    configured = cur.fetchall()

    if configured:
        ids = [row["card_id"] for row in configured]
    else:
        cur.execute("SELECT id FROM cards WHERE position = 'Goalie' LIMIT 1")
        goalie = cur.fetchone()
        cur.execute("SELECT id FROM cards WHERE position = 'Skater' LIMIT 4")
        skaters = cur.fetchall()

        if not goalie or len(skaters) < 4:
            conn.close()
            await update.message.reply_text("❌ В базе недостаточно карт для стартового набора.")
            return

        ids = [goalie["id"]] + [row["id"] for row in skaters]

    for card_id in ids:
        cur.execute(
            """
            INSERT INTO user_cards(user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, card_id),
        )

    cur.execute("SELECT id, position FROM cards WHERE id = ANY(%s)", (ids,))
    cards = cur.fetchall()
    goalie_id = next((card["id"] for card in cards if card["position"] == "Goalie"), None)
    skaters = [card["id"] for card in cards if card["position"] == "Skater"][:4]

    cur.execute(
        """
        INSERT INTO user_rosters(user_id, goalie_id, skater1_id, skater2_id, skater3_id, skater4_id)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT(user_id) DO UPDATE SET
            goalie_id = COALESCE(user_rosters.goalie_id, EXCLUDED.goalie_id),
            skater1_id = COALESCE(user_rosters.skater1_id, EXCLUDED.skater1_id),
            skater2_id = COALESCE(user_rosters.skater2_id, EXCLUDED.skater2_id),
            skater3_id = COALESCE(user_rosters.skater3_id, EXCLUDED.skater3_id),
            skater4_id = COALESCE(user_rosters.skater4_id, EXCLUDED.skater4_id)
        """,
        (
            user.id,
            goalie_id,
            skaters[0] if len(skaters) > 0 else None,
            skaters[1] if len(skaters) > 1 else None,
            skaters[2] if len(skaters) > 2 else None,
            skaters[3] if len(skaters) > 3 else None,
        ),
    )

    cur.execute(
        "UPDATE users SET freepack_claimed = TRUE WHERE user_id = %s",
        (user.id,),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        "🎉 **Стартовый набор получен!**\n"
        "Карточки автоматически добавлены в инвентарь и состав.",
        parse_mode="Markdown",
    )


async def inventory_command(update, context):
    if not await check_pm_registered(update, context):
        return
    await show_inventory(update, context)


async def show_inventory(update, context, edit=False):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.*, uc.count, col.name AS collection_name,
               t.name AS team_name, t.emoji AS team_emoji
        FROM cards c
        JOIN collections col ON col.id = c.collection_id
        LEFT JOIN card_teams t ON t.id = c.team_id
        LEFT JOIN user_cards uc
          ON uc.card_id = c.id AND uc.user_id = %s
        ORDER BY c.ovr DESC, c.id
        """,
        (user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    owned = [card for card in cards if card["count"] and card["count"] > 0]
    text = "🎒 **КОЛЛЕКЦИЯ КАРТОЧЕК**\n\n"
    text += f"📊 Собрано: **{len(owned)}/{len(cards)}**\n\n"

    for card in cards:
        mark = "✅" if card["count"] and card["count"] > 0 else "▫️"
        count = f" ×{card['count']}" if card["count"] and card["count"] > 0 else ""
        text += (
            f"{mark} `#{card['id']}` **{card['nickname']}** — "
            f"{card['ovr']} OVR, {card['rarity']}{count}\n"
        )

    if not cards:
        text += "📭 В базе пока нет карточек."

    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🏒 Состав", callback_data="refresh_profile")],
            [InlineKeyboardButton("🔨 Крафт", callback_data="craft_menu")],
            [InlineKeyboardButton("🚀 Апгрейдер", callback_data="upgrade_menu")],
            [InlineKeyboardButton("🏷 На рынок", callback_data="market_list_menu")],
            [InlineKeyboardButton("💰 Продать", callback_data="sell_menu")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_inv")],
        ]
    )

    if len(text) > 3900:
        text = text[:3850] + "\n\n…"

    if query:
        await query.answer()
        await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def craft_menu(update, context):
    query = update.callback_query
    await query.answer()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.rarity, uc.count
        FROM cards c
        JOIN user_cards uc ON uc.card_id = c.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr
        """,
        (query.from_user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    if len(cards) < 3:
        await query.answer("Нужно минимум 3 карточки.", show_alert=True)
        return

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"{card['nickname']} ({card['ovr']} OVR) ×{card['count']}",
                    callback_data=f"craft_pick_{card['id']}",
                )
            ]
            for card in cards
        ]
        + [[InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")]]
    )

    await query.edit_message_text(
        "🔨 **КРАФТ КАРТОЧКИ**\n\n"
        "Выберите первую карту. Затем добавьте ещё две карты с одинаковым OVR "
        "с допустимым разбросом до 2 пунктов.",
        reply_markup=markup,
        parse_mode="Markdown",
    )


async def craft_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "craft_menu":
        await craft_menu(update, context)
        return

    if data.startswith("craft_pick_"):
        card_id = int(data.split("_")[-1])
        context.user_data["craft_cards"] = [card_id]
        await query.answer()
        await query.edit_message_text(
            "✅ Первая карточка выбрана.\n"
            "Теперь отправьте ID ещё двух карточек сообщением через пробел.\n"
            "Пример: `12 18`",
            parse_mode="Markdown",
        )
        return WAITING_CRAFT_CARDS

    if data == "craft_confirm":
        selected = context.user_data.get("craft_cards", [])
        if len(selected) != 3:
            await query.answer("Выберите 3 карточки.", show_alert=True)
            return

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.*, uc.count
            FROM cards c
            JOIN user_cards uc ON uc.card_id = c.id
            WHERE uc.user_id = %s AND c.id = ANY(%s) AND uc.count > 0
            """,
            (user.id, selected),
        )
        cards = cur.fetchall()

        if len(cards) != 3 or len(set(card["id"] for card in cards)) != 3:
            conn.close()
            await query.answer("Карточки не найдены или недостаточно копий.", show_alert=True)
            return

        ovrs = [card["ovr"] for card in cards]
        if max(ovrs) - min(ovrs) > 2:
            conn.close()
            await query.answer("Разброс OVR должен быть не больше 2.", show_alert=True)
            return

        cur.execute(
            """
            SELECT id, nickname, ovr, rarity
            FROM cards
            WHERE ovr > %s
            ORDER BY ovr ASC
            LIMIT 1
            """,
            (max(ovrs),),
        )
        result_card = cur.fetchone()

        if not result_card:
            conn.close()
            await query.answer("Нет подходящей карты с большим OVR.", show_alert=True)
            return

        for card in cards:
            cur.execute(
                "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
                (user.id, card["id"]),
            )
        cur.execute(
            "DELETE FROM user_cards WHERE user_id = %s AND count <= 0",
            (user.id,),
        )

        if random.random() < CRAFT_CHANCE / 100:
            cur.execute(
                """
                INSERT INTO user_cards(user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, result_card["id"]),
            )
            success = True
        else:
            success = False

        conn.commit()
        conn.close()
        context.user_data.pop("craft_cards", None)

        if success:
            await query.edit_message_text(
                f"🎉 **Крафт удался!**\n"
                f"Вы получили **{result_card['nickname']}** ({result_card['ovr']} OVR).\n"
                f"Шанс был: **{CRAFT_CHANCE}%**.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                f"💨 **Крафт не удался.**\n"
                f"Три карты переработаны, но новая карта не выпала.\n"
                f"Шанс был: **{CRAFT_CHANCE}%**.",
                parse_mode="Markdown",
            )


async def craft_cards_input(update, context):
    try:
        ids = [int(value) for value in update.message.text.split()]
    except ValueError:
        await update.message.reply_text("❌ Введите два ID карточек числами.")
        return WAITING_CRAFT_CARDS

    selected = context.user_data.get("craft_cards", [])
    if len(ids) != 2 or len(selected) != 1:
        await update.message.reply_text("❌ Нужно отправить ровно два ID.")
        return WAITING_CRAFT_CARDS

    selected.extend(ids)
    context.user_data["craft_cards"] = selected

    await update.message.reply_text(
        "🧪 Карточки выбраны. Нажмите кнопку для проверки и запуска крафта.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔨 Запустить крафт", callback_data="craft_confirm")]]
        ),
    )
    return ConversationHandler.END


async def upgrade_menu(update, context):
    query = update.callback_query
    await query.answer()

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.id, c.nickname, c.ovr, c.rarity, uc.count
        FROM cards c
        JOIN user_cards uc ON uc.card_id = c.id
        WHERE uc.user_id = %s AND uc.count > 0
        ORDER BY c.ovr
        """,
        (query.from_user.id,),
    )
    cards = cur.fetchall()
    conn.close()

    buttons = [
        [
            InlineKeyboardButton(
                f"{card['nickname']} — {card['ovr']} OVR ×{card['count']}",
                callback_data=f"upgrade_source_{card['id']}",
            )
        ]
        for card in cards
    ]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")])

    await query.edit_message_text(
        "🚀 **АПГРЕЙДЕР**\n\nВыберите свою карточку, которую хотите улучшить:",
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode="Markdown",
    )


async def upgrade_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "upgrade_menu":
        await upgrade_menu(update, context)
        return

    if data.startswith("upgrade_source_"):
        source_id = int(data.split("_")[-1])
        context.user_data["upgrade_source"] = source_id

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT ovr FROM cards WHERE id = %s", (source_id,))
        source = cur.fetchone()
        cur.execute(
            """
            SELECT id, nickname, ovr, rarity
            FROM cards
            WHERE ovr > %s
            ORDER BY ovr ASC
            LIMIT 30
            """,
            (source["ovr"],),
        )
        targets = cur.fetchall()
        conn.close()

        buttons = []
        for target in targets:
            gap = target["ovr"] - source["ovr"]
            chance = max(5, min(UPGRADER_MAX_CHANCE, 25 - gap * 2))
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"{target['nickname']} — {target['ovr']} OVR | шанс {chance}%",
                        callback_data=f"upgrade_target_{target['id']}",
                    )
                ]
            )
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="upgrade_menu")])

        await query.edit_message_text(
            "🎯 **Выберите карту для выпадения:**\n"
            "Чем выше цель, тем ниже шанс. Максимальный шанс ограничен 40%.",
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    if data.startswith("upgrade_target_"):
        target_id = int(data.split("_")[-1])
        source_id = context.user_data.get("upgrade_source")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM cards WHERE id = %s", (source_id,))
        source = cur.fetchone()
        cur.execute("SELECT * FROM cards WHERE id = %s", (target_id,))
        target = cur.fetchone()
        conn.close()

        if not source or not target or target["ovr"] <= source["ovr"]:
            await query.answer("Некорректная цель.", show_alert=True)
            return

        gap = target["ovr"] - source["ovr"]
        chance = max(5, min(UPGRADER_MAX_CHANCE, 25 - gap * 2))
        context.user_data["upgrade_target"] = target_id

        await query.edit_message_text(
            f"🚀 ПОДТВЕРЖДЕНИЕ АПГРЕЙДЕРА\n\n"
            f"🃏 Ваша карта: {source['nickname']} ({source['ovr']} OVR)\n"
            f"🎯 Цель: {target['nickname']} ({target['ovr']} OVR)\n"
            f"🎲 Шанс: {chance}%\n\n"
            f"При неудаче исходная карта сгорает.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Подтвердить", callback_data="upgrade_confirm")],
                    [InlineKeyboardButton("❌ Отмена", callback_data="refresh_inv")],
                ]
            ),
            parse_mode="Markdown",
        )
        return

    if data == "upgrade_confirm":
        source_id = context.user_data.get("upgrade_source")
        target_id = context.user_data.get("upgrade_target")

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM cards WHERE id = %s", (source_id,))
        source = cur.fetchone()
        cur.execute("SELECT * FROM cards WHERE id = %s", (target_id,))
        target = cur.fetchone()

        if not source or not target:
            conn.close()
            await query.answer("Карта не найдена.", show_alert=True)
            return

        cur.execute(
            """
            SELECT count FROM user_cards
            WHERE user_id = %s AND card_id = %s AND count > 0
            """,
            (user.id, source_id),
        )
        owned = cur.fetchone()
        if not owned:
            conn.close()
            await query.answer("У вас больше нет исходной карты.", show_alert=True)
            return

        gap = target["ovr"] - source["ovr"]
        chance = max(5, min(UPGRADER_MAX_CHANCE, 25 - gap * 2))

        cur.execute(
            "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
            (user.id, source_id),
        )
        cur.execute("DELETE FROM user_cards WHERE user_id = %s AND count <= 0", (user.id,))

        success = random.random() < chance / 100
        if success:
            cur.execute(
                """
                INSERT INTO user_cards(user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, target_id),
            )

        conn.commit()
        conn.close()
        context.user_data.pop("upgrade_source", None)
        context.user_data.pop("upgrade_target", None)

        if success:
            await query.edit_message_text(
                f"🎉 **АПГРЕЙД УДАЛСЯ!**\n"
                f"Выпала карта **{target['nickname']}** ({target['ovr']} OVR).\n"
                f"Шанс был **{chance}%**.",
                parse_mode="Markdown",
            )
        else:
            await query.edit_message_text(
                f"💨 **Апгрейд не удался.**\n"
                f"Исходная карта сгорела.\n"
                f"Шанс был **{chance}%**.",
                parse_mode="Markdown",
            )


async def show_profile(update, context):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id = %s", (user.id,))
    account = cur.fetchone()
    cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = cur.fetchone()

    positions = ["goalie", "skater1", "skater2", "skater3", "skater4"]
    labels = {
        "goalie": "🧤 Вратарь",
        "skater1": "🏒 Полевой 1",
        "skater2": "🏒 Полевой 2",
        "skater3": "🏒 Полевой 3",
        "skater4": "🏒 Полевой 4",
    }

    lines = []
    total = 0
    complete = True

    for pos in positions:
        card_id = roster[f"{pos}_id"] if roster else None
        if not card_id:
            lines.append(f"{labels[pos]}: ❌ не выбран")
            complete = False
            continue

        cur.execute("SELECT * FROM cards WHERE id = %s", (card_id,))
        card = cur.fetchone()
        if not card:
            lines.append(f"{labels[pos]}: ❌ карта удалена")
            complete = False
            continue

        cur.execute(
            """
            SELECT matches_played, recovery_until
            FROM card_fatigue
            WHERE user_id = %s AND card_id = %s
            """,
            (user.id, card_id),
        )
        fatigue = cur.fetchone()
        matches = fatigue["matches_played"] if fatigue else 0
        recovery = parse_dt(fatigue["recovery_until"]) if fatigue else None

        status = "✅ готова"
        if recovery and recovery > datetime.now():
            status = f"😴 до {recovery.strftime('%H:%M')}"
        elif matches:
            status = f"⚡ {matches}/{FATIGUE_MATCH_LIMIT}"

        lines.append(
            f"{labels[pos]}: **{card['nickname']}** ({card['ovr']} OVR) — {status}"
        )
        total += card["ovr"]

    conn.close()

    avg = round(total / 5, 1) if complete else 0
    discount = account["shop_discount_percent"] if account else 0
    discount_text = f"\n🏷 Скидка магазина: **{discount}%**" if discount else ""

    text = (
        f"🏒 **ПРОФИЛЬ И СОСТАВ**\n\n"
        f"👤 {user.first_name or user.username or user.id}\n"
        f"💳 Баланс: **{account['balance']} RPLCoin**\n"
        f"🏆 MMR: **{account['mmr']}**\n"
        f"⭐ Средний OVR: **{avg or 'не собран'}**{discount_text}\n\n"
        f"📋 **Состав:**\n" + "\n".join(lines) +
        "\n\nℹ️ Карта устаёт после 5 матчей и восстанавливается 30 минут."
    )

    markup = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("⚙️ Изменить состав", callback_data="edit_roster")],
            [InlineKeyboardButton("🎒 Коллекция", callback_data="refresh_inv")],
            [InlineKeyboardButton("🔄 Обновить", callback_data="refresh_profile")],
        ]
    )

    if query:
        await query.answer()
        await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def profile_command(update, context):
    if not await check_pm_registered(update, context):
        return
    await show_profile(update, context)


async def profile_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data in ("refresh_profile", "edit_roster"):
        if data == "edit_roster":
            await query.answer()
            await query.edit_message_text(
                "⚙️ Выберите позицию:",
                reply_markup=roster_keyboard(),
                parse_mode="Markdown",
            )
        else:
            await show_profile(update, context)
        return

    if data.startswith("set_pos_"):
        pos = data.replace("set_pos_", "")
        needed = "Goalie" if pos == "goalie" else "Skater"

        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT c.id, c.nickname, c.ovr, c.rarity
            FROM user_cards uc
            JOIN cards c ON c.id = uc.card_id
            WHERE uc.user_id = %s AND c.position = %s AND uc.count > 0
            ORDER BY c.ovr DESC
            """,
            (user.id, needed),
        )
        cards = cur.fetchall()
        conn.close()

        buttons = [
            [
                InlineKeyboardButton(
                    f"{card['nickname']} — {card['ovr']} OVR",
                    callback_data=f"apply_card_{pos}_{card['id']}",
                )
            ]
            for card in cards
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="edit_roster")])

        await query.answer()
        await query.edit_message_text(
            "📋 Выберите карточку:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if data.startswith("apply_card_"):
        _, _, pos, card_id = data.split("_")
        card_id = int(card_id)

        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
        roster = cur.fetchone()

        if not roster:
            cur.execute("INSERT INTO user_rosters(user_id) VALUES (%s)", (user.id,))
            cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
            roster = cur.fetchone()

        for other in ["goalie", "skater1", "skater2", "skater3", "skater4"]:
            if other != pos and roster[f"{other}_id"] == card_id:
                conn.close()
                await query.answer("Эта карточка уже стоит в составе.", show_alert=True)
                return

        cur.execute(
            f"UPDATE user_rosters SET {pos}_id = %s WHERE user_id = %s",
            (card_id, user.id),
        )
        conn.commit()
        conn.close()

        await query.answer("✅ Состав обновлён!")
        await show_profile(update, context)


def roster_card_ids(roster):
    if not roster:
        return []
    return [
        roster["goalie_id"],
        roster["skater1_id"],
        roster["skater2_id"],
        roster["skater3_id"],
        roster["skater4_id"],
    ]


def get_roster_cards(cur, roster):
    ids = roster_card_ids(roster)
    cur.execute("SELECT * FROM cards WHERE id = ANY(%s)", (ids,))
    by_id = {card["id"]: card for card in cur.fetchall()}
    return {
        "goalie": by_id[roster["goalie_id"]],
        "skater1": by_id[roster["skater1_id"]],
        "skater2": by_id[roster["skater2_id"]],
        "skater3": by_id[roster["skater3_id"]],
        "skater4": by_id[roster["skater4_id"]],
    }


def fatigue_status(cur, user_id, card_id):
    cur.execute(
        """
        SELECT matches_played, recovery_until
        FROM card_fatigue
        WHERE user_id = %s AND card_id = %s
        """,
        (user_id, card_id),
    )
    row = cur.fetchone()
    if not row:
        return 0, None

    recovery = parse_dt(row["recovery_until"])
    if recovery and recovery <= datetime.now():
        cur.execute(
            """
            UPDATE card_fatigue
            SET matches_played = 0, recovery_until = NULL
            WHERE user_id = %s AND card_id = %s
            """,
            (user_id, card_id),
        )
        return 0, None

    return row["matches_played"], recovery


def check_roster_fatigue(cur, user_id, roster):
    tired = []
    for card_id in roster_card_ids(roster):
        if not card_id:
            continue

        matches, recovery = fatigue_status(cur, user_id, card_id)
        if recovery and recovery > datetime.now():
            tired.append((card_id, recovery))
        elif matches >= FATIGUE_MATCH_LIMIT:
            recovery = datetime.now() + timedelta(minutes=FATIGUE_RECOVERY_MINUTES)
            cur.execute(
                """
                UPDATE card_fatigue
                SET recovery_until = %s
                WHERE user_id = %s AND card_id = %s
                """,
                (recovery, user_id, card_id),
            )
            tired.append((card_id, recovery))

    return tired


def mark_roster_match(cur, user_id, roster):
    recovery_time = datetime.now() + timedelta(minutes=FATIGUE_RECOVERY_MINUTES)

    for card_id in roster_card_ids(roster):
        if not card_id:
            continue

        cur.execute(
            """
            INSERT INTO card_fatigue(user_id, card_id, matches_played)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET matches_played = card_fatigue.matches_played + 1
            """,
            (user_id, card_id),
        )
        cur.execute(
            """
            UPDATE card_fatigue
            SET recovery_until = CASE
                WHEN matches_played >= %s THEN %s
                ELSE NULL
            END
            WHERE user_id = %s AND card_id = %s
            """,
            (FATIGUE_MATCH_LIMIT, recovery_time, user_id, card_id),
        )


def apply_match_reward(cur, user_id, result):
    if result == "win":
        cur.execute(
            "UPDATE users SET mmr = mmr + 50, balance = balance + 2000 WHERE user_id = %s",
            (user_id,),
        )
    elif result == "lose":
        cur.execute(
            """
            UPDATE users
            SET mmr = GREATEST(0, mmr - 50), balance = balance + 500
            WHERE user_id = %s
            """,
            (user_id,),
        )
    else:
        cur.execute(
            "UPDATE users SET balance = balance + 500 WHERE user_id = %s",
            (user_id,),
        )


active_searches = {}
active_games = set()


async def cardmatch_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    get_or_create_user(user.id, user.username or "", user.first_name or "")

    if user.id in active_searches or user.id in active_games:
        await update.message.reply_text("🔎 Вы уже ищете соперника или играете.")
        return

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user.id,))
    roster = cur.fetchone()

    if not roster or any(value is None for value in roster_card_ids(roster)):
        conn.close()
        await update.message.reply_text(
            "❌ Для матча нужен полный состав: 1 вратарь и 4 полевых.\n"
            "Получить стартовый набор можно командой /freepack."
        )
        return

    tired = check_roster_fatigue(cur, user.id, roster)
    conn.commit()
    conn.close()

    if tired:
        nearest = min(item[1] for item in tired)
        await update.message.reply_text(
            f"😴 Часть состава устала.\n"
            f"Карточки восстановятся примерно к **{nearest.strftime('%H:%M')}**."
        )
        return

    if active_searches:
        opponent_id, search = next(iter(active_searches.items()))
        if opponent_id != user.id:
            active_searches.pop(opponent_id, None)
            if search.get("task"):
                search["task"].cancel()

            await update.message.reply_text(
                f"⚡️ Соперник найден: **{search['first_name']}**!\nМатч начинается.",
                parse_mode="Markdown",
            )
            try:
                await context.bot.edit_message_text(
                    chat_id=search["chat_id"],
                    message_id=search["msg_id"],
                    text=f"⚡️ Соперник найден: **{user.first_name}**!\nМатч начинается.",
                    parse_mode="Markdown",
                )
            except Exception:
                pass

            asyncio.create_task(
                start_game_pvp(
                    opponent_id,
                    user.id,
                    search["chat_id"],
                    update.effective_chat.id,
                    search["msg_id"],
                    None,
                    context,
                )
            )
            return

    msg = await update.message.reply_text(
        "🔎 **Поиск соперника запущен!**\n"
        "Если игрок не найдётся за минуту, против вас сыграет ИИ.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("❌ Отменить", callback_data=f"cancel_match_{user.id}")]]
        ),
        parse_mode="Markdown",
    )

    active_searches[user.id] = {
        "chat_id": update.effective_chat.id,
        "msg_id": msg.message_id,
        "first_name": user.first_name or "Игрок",
        "task": asyncio.create_task(search_timeout(user.id, context)),
    }


async def search_timeout(user_id, context):
    await asyncio.sleep(60)
    data = active_searches.pop(user_id, None)
    if not data:
        return

    try:
        await context.bot.edit_message_text(
            chat_id=data["chat_id"],
            message_id=data["msg_id"],
            text="🤖 Игрок не найден. Подбираем соперника-ИИ...",
        )
    except Exception:
        pass

    await start_game_ai(user_id, data["chat_id"], data["msg_id"], context)


async def match_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("cancel_match_"):
        owner = int(data.split("_")[-1])
        if owner != user.id:
            await query.answer("Отменить поиск может только его автор.", show_alert=True)
            return

    search = active_searches.pop(owner, None)
    if search and search.get("task"):
        search["task"].cancel()

    await query.answer()
    await query.edit_message_text("❌ Поиск отменён.")
    return


def player_name(account):
    return account["first_name"] or account["username"] or str(account["user_id"])


def card_line(card):
    return f"{card['nickname']} ({card['ovr']} OVR)"


def match_event_random(p1, p2, name1, name2, score1, score2):
    choices = [
        f"🧤 Сейв! Вратарь {p1['goalie']['nickname']} спасает команду.",
        f"🧤 Сейв! Вратарь {p2['goalie']['nickname']} отбивает опасный бросок.",
        "🏒 Штанга! Шайба звенит о каркас ворот.",
        "💥 Силовой приём у борта — публика ревёт.",
        "2️⃣ Удаление! Игрок получает малый штраф на 2 минуты.",
        "🚨 Судья фиксирует офсайд — атака остановлена.",
        "🎥 Видеопросмотр! Арбитры проверяют спорный эпизод.",
        "🟨 Команды получают предупреждение за стычку после свистка.",
        "🌪 Шайба рикошетом меняет направление, но проходит рядом со штангой.",
        "🧊 Вратарь теряет клюшку, однако успевает накрыть шайбу.",
    ]
    return random.choice(choices)


async def start_game_pvp(
    p1_id,
    p2_id,
    p1_chat_id,
    p2_chat_id,
    p1_msg_id,
    p2_msg_id,
    context,
):
    active_games.update({p1_id, p2_id})

    try:
        conn = get_db()
        cur = conn.cursor()

        cur.execute("SELECT * FROM users WHERE user_id = %s", (p1_id,))
        u1 = cur.fetchone()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (p2_id,))
        u2 = cur.fetchone()
        cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (p1_id,))
        r1 = cur.fetchone()
        cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (p2_id,))
        r2 = cur.fetchone()

        tired1 = check_roster_fatigue(cur, p1_id, r1)
        tired2 = check_roster_fatigue(cur, p2_id, r2)
        if tired1 or tired2:
            conn.commit()
            conn.close()
            return

        cards1 = get_roster_cards(cur, r1)
        cards2 = get_roster_cards(cur, r2)
        mark_roster_match(cur, p1_id, r1)
        mark_roster_match(cur, p2_id, r2)
        conn.commit()
        conn.close()

        name1 = player_name(u1)
        name2 = player_name(u2)
        score1 = score2 = 0
        events = []

        avg1 = sum(card["ovr"] for card in cards1.values()) / 5
        avg2 = sum(card["ovr"] for card in cards2.values()) / 5

        header = (
            f"🏒 **МАТЧ RPL**\n"
            f"🔴 {name1} — {avg1:.1f} OVR\n"
            f"🔵 {name2} — {avg2:.1f} OVR\n\n"
            f"🎬 Команды выходят на лёд!"
        )

        async def send(text):
            for chat_id, message_id in ((p1_chat_id, p1_msg_id), (p2_chat_id, p2_msg_id)):
                if chat_id and message_id:
                    try:
                        await context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=message_id,
                            text=text,
                            parse_mode="Markdown",
                        )
                    except Exception:
                        pass

        await send(header)
        await asyncio.sleep(2)

        diff = avg1 - avg2
        prob1 = max(0.06, min(0.25, 0.12 + diff * 0.004))
        prob2 = max(0.06, min(0.25, 0.12 - diff * 0.004))

        for period in range(1, 4):
            await send(
                f"{header}\n\n⏱ **ПЕРИОД {period}/3**\n"
                f"📊 Счёт: 🔴 {score1} — {score2} 🔵"
            )
            await asyncio.sleep(1.5)

            for tick in range(4):
                minute = (period - 1) * 20 + random.randint(2, 19)
                roll = random.random()

                if roll < prob1:
                    scorer = random.choice(list(cards1.values())[1:])
                    if random.random() < 0.12:
                        event = (
                            f"🎥 **{minute}' ВИДЕОПРОСМОТР!**\n"
                            f"Гол {scorer['nickname']} отменён: была помеха вратарю."
                        )
                    else:
                        score1 += 1
                        conn = get_db()
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE users SET balance = balance + 100 WHERE user_id = %s",
                            (p1_id,),
                        )
                        conn.commit()
                        conn.close()
                        event = (
                            f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']} забивает "
                            f"за 🔴 {name1}! (+100 RPLCoin)"
                        )
                elif roll < prob1 + prob2:
                    scorer = random.choice(list(cards2.values())[1:])
                    if random.random() < 0.12:
                        event = (
                            f"🎥 **{minute}' ГОЛ ОТМЕНЁН!**\n"
                            f"Арбитры обнаружили офсайд у {scorer['nickname']}."
                        )
                    else:
                        score2 += 1
                        conn = get_db()
                        cur = conn.cursor()
                        cur.execute(
                            "UPDATE users SET balance = balance + 100 WHERE user_id = %s",
                            (p2_id,),
                        )
                        conn.commit()
                        conn.close()
                        event = (
                            f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']} забивает "
                            f"за 🔵 {name2}! (+100 RPLCoin)"
                        )
                else:
                    event = f"🏒 **{minute}'** {match_event_random(cards1, cards2, name1, name2, score1, score2)}"

                events.append(event)
                await send(
                    f"{header}\n\n"
                    f"⏱ ПЕРИОД {period}/3\n"
                    f"📊 Счёт: 🔴 {score1} — {score2} 🔵\n\n"
                    f"📝 {event}"
                )
                await asyncio.sleep(2)

        if score1 == score2:
            await send(
                f"{header}\n\n"
                f"🤝 Основное время завершилось со счётом **{score1}:{score2}**.\n"
                f"🔥 Начинается овертайм!"
            )
            await asyncio.sleep(2)

            if random.random() < 0.5:
                score1 += 1
                winner = name1
                side = "🔴"
                scorer = random.choice(list(cards1.values())[1:])
                p1_id_winner = p1_id
            else:
                score2 += 1
                winner = name2
                side = "🔵"
                scorer = random.choice(list(cards2.values())[1:])
                p1_id_winner = p2_id

            events.append(
                f"🔥 **ОВЕРТАЙМ!** {scorer['nickname']} забивает золотой гол "
                f"за {side} {winner}!"
            )
            await send(
                f"{header}\n\n"
                f"🔥 **ОВЕРТАЙМ**\n"
                f"{events[-1]}\n"
                f"📊 Счёт: 🔴 {score1} — {score2} 🔵"
            )
            await asyncio.sleep(2)

        conn = get_db()
        cur = conn.cursor()

        if score1 > score2:
            result1, result2 = "win", "lose"
            result_text = f"🎉 Победил 🔴 **{name1}**!"
        elif score2 > score1:
            result1, result2 = "lose", "win"
            result_text = f"🎉 Победил 🔵 **{name2}**!"
        else:
            result1 = result2 = "draw"
            result_text = "🤝 Матч завершился вничью!"

        apply_match_reward(cur, p1_id, result1)
        apply_match_reward(cur, p2_id, result2)
        conn.commit()
        conn.close()

        await send(
            f"🏁 **МАТЧ ЗАВЕРШЁН!**\n\n"
            f"{result_text}\n"
            f"📊 Итоговый счёт: **{score1}:{score2}**\n\n"
            f"🏆 Победа: +50 MMR и 2000 RPLCoin\n"
            f"🥈 Поражение: +500 RPLCoin\n\n"
            f"😴 Усталость состава увеличена. После 5 матчей карты уйдут на восстановление."
        )

    finally:
        active_games.discard(p1_id)
        active_games.discard(p2_id)


async def start_game_ai(user_id, chat_id, msg_id, context):
    active_games.add(user_id)

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
        user = cur.fetchone()
        cur.execute("SELECT * FROM user_rosters WHERE user_id = %s", (user_id,))
        roster = cur.fetchone()

        tired = check_roster_fatigue(cur, user_id, roster)
        if tired:
            conn.commit()
            conn.close()
            return

        player_cards = get_roster_cards(cur, roster)
        mark_roster_match(cur, user_id, roster)

        player_ids = roster_card_ids(roster)
        avg = sum(card["ovr"] for card in player_cards.values()) / 5

        cur.execute(
            """
            SELECT * FROM cards
            WHERE id <> ALL(%s)
            ORDER BY ABS(ovr - %s), RANDOM()
            LIMIT 30
            """,
            (player_ids, avg),
        )
        candidates = cur.fetchall()

        conn.commit()
        conn.close()

        goalies = [card for card in candidates if card["position"] == "Goalie"]
        skaters = [card for card in candidates if card["position"] == "Skater"]

        if len(goalies) < 1 or len(skaters) < 4:
            ai = {
                "goalie": {"id": -1, "nickname": "ИИ Вратарь", "ovr": int(avg)},
                "skater1": {"id": -2, "nickname": "ИИ Форвард 1", "ovr": int(avg)},
                "skater2": {"id": -3, "nickname": "ИИ Форвард 2", "ovr": int(avg)},
                "skater3": {"id": -4, "nickname": "ИИ Защитник 1", "ovr": int(avg)},
                "skater4": {"id": -5, "nickname": "ИИ Защитник 2", "ovr": int(avg)},
            }
        else:
            random.shuffle(skaters)
            ai = {
                "goalie": goalies[0],
                "skater1": skaters[0],
                "skater2": skaters[1],
                "skater3": skaters[2],
                "skater4": skaters[3],
            }

        ai_avg = sum(card["ovr"] for card in ai.values()) / 5
        name = player_name(user)
        score1 = score2 = 0
        events = []

        async def send(text):
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    parse_mode="Markdown",
                )
            except Exception:
                pass

        header = (
            f"🤖 **МАТЧ ПРОТИВ ИИ**\n"
            f"🔴 {name} — {avg:.1f} OVR\n"
            f"🤖 ИИ — {ai_avg:.1f} OVR"
        )
        await send(header + "\n\n🎬 Матч начинается!")
        await asyncio.sleep(2)

        diff = avg - ai_avg
        prob1 = max(0.06, min(0.25, 0.12 + diff * 0.004))
        prob2 = max(0.06, min(0.25, 0.12 - diff * 0.004))

        for period in range(1, 4):
            for _ in range(4):
                minute = (period - 1) * 20 + random.randint(2, 19)
                roll = random.random()

                if roll < prob1:
                    scorer = random.choice(list(player_cards.values())[1:])
                    score1 += 1
                    conn = get_db()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE users SET balance = balance + 100 WHERE user_id = %s",
                        (user_id,),
                    )
                    conn.commit()
                    conn.close()
                    event = f"⚡️ **{minute}' ГОЛ!** {scorer['nickname']} забивает!"
                elif roll < prob1 + prob2:
                    scorer = random.choice(list(ai.values())[1:])
                    score2 += 1
                    event = f"🤖 **{minute}' ГОЛ ИИ!** {scorer['nickname']} поражает ворота."
                else:
                    event = f"🏒 **{minute}'** {match_event_random(player_cards, ai, name, 'ИИ', score1, score2)}"

                events.append(event)
                await send(
                    f"{header}\n\n"
                    f"⏱ Период {period}/3\n"
                    f"📊 Счёт: 🔴 {score1} — {score2} 🤖\n\n{event}"
                )
                await asyncio.sleep(2)

        if score1 == score2:
            if random.random() < 0.5:
                score1 += 1
                events.append("🔥 Овертайм: победный гол забивает ваша команда!")
            else:
                score2 += 1
                events.append("🔥 Овертайм: ИИ забивает золотой гол!")

            await send(
                f"{header}\n\n{events[-1]}\n"
                f"📊 Счёт: 🔴 {score1} — {score2} 🤖"
            )
            await asyncio.sleep(2)

        conn = get_db()
        cur = conn.cursor()
        if score1 > score2:
            result = "win"
            result_text = "🎉 Вы победили ИИ!"
        elif score2 > score1:
            result = "lose"
            result_text = "❌ ИИ оказался сильнее."
        else:
            result = "draw"
            result_text = "🤝 Ничья."

        apply_match_reward(cur, user_id, result)
        conn.commit()
        conn.close()

        await send(
            f"🏁 **МАТЧ ЗАВЕРШЁН!**\n\n"
            f"{result_text}\n"
            f"📊 Итоговый счёт: **{score1}:{score2}**\n\n"
            f"😴 Сыгранные карточки получили усталость."
        )

    finally:
        active_games.discard(user_id)


async def wheel_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT balance, last_wheel_spin FROM users WHERE user_id = %s",
        (user.id,),
    )
    account = cur.fetchone()
    now = datetime.now()

    last = parse_dt(account["last_wheel_spin"])
    if last and now - last < timedelta(hours=36):
        remaining = timedelta(hours=36) - (now - last)
        conn.close()
        await update.message.reply_text(
            f"⏳ Колесо будет доступно через {remaining.seconds // 3600} ч "
            f"{(remaining.seconds % 3600) // 60} мин."
        )
        return

    cost = 10000
    if account["balance"] < cost:
        conn.close()
        await update.message.reply_text("❌ Недостаточно средств для вращения колеса.")
        return

    cur.execute(
        """
        UPDATE users
        SET balance = balance - %s, last_wheel_spin = %s
        WHERE user_id = %s
        """,
        (cost, now, user.id),
    )

    prize = random.choices(
        ["money", "discount", "reset", "card", "nothing"],
        weights=[30, 18, 10, 30, 12],
        k=1,
    )[0]

    if prize == "money":
        amount = random.randint(5000, 100000)
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (amount, user.id),
        )
        result = f"💰 Вы выиграли {amount} RPLCoin!"
    elif prize == "discount":
        discount = random.randint(5, 30)
        until = now + timedelta(days=7)
        cur.execute(
            """
            UPDATE users
            SET shop_discount_percent = %s, shop_discount_until = %s
            WHERE user_id = %s
            """,
            (discount, until, user.id),
        )
        result = (
            f"🏷 Вы выиграли скидку {discount}% на магазин паков "
            f"и торговую площадку до {until.strftime('%d.%m.%Y %H:%M')}!"
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
    elif prize == "card":
        cur.execute("SELECT * FROM cards WHERE rarity <> 'Секретная'")
        cards = cur.fetchall()
        card = choose_card(cur, user.id, cards, strict=True)
        if card:
            cur.execute(
                """
                INSERT INTO user_cards(user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, card["id"]),
            )
            result = f"🃏 Вам выпала карта {card['nickname']} ({card['ovr']} OVR)!"
        else:
            cur.execute(
                "UPDATE users SET balance = balance + 20000 WHERE user_id = %s",
                (user.id,),
            )
            result = "💰 Все карты уже собраны — компенсация 20 000 RPLCoin."
    else:
        result = "💨 В этот раз колесо ничего не принесло."

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🎡 **Колесо удачи остановилось!**\n\n{result}",
        parse_mode="Markdown",
    )


async def coin_command(update, context):
    if not await check_pm_registered(update, context):
        return
    await update.message.reply_text(
        "🪙 **Орёл и решка**\n"
        "Шанс выигрыша — 20%, проигрыша — 80%.\n"
        "Введите ставку:",
        reply_markup=bet_cancel_keyboard(),
        parse_mode="Markdown",
    )
    return WAITING_COIN_BET


async def coin_receive_bet(update, context):
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
    account = cur.fetchone()

    if not account or account["balance"] < bet:
        conn.close()
        await update.message.reply_text("❌ Недостаточно средств.")
        return WAITING_COIN_BET

    cur.execute(
        "UPDATE users SET balance = balance - %s WHERE user_id = %s",
        (bet, user.id),
    )

    win = random.random() < 0.2
    if win:
        payout = bet * 4
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (payout, user.id),
        )
        result = f"🎉 Выпал ОРЁЛ!\nВы выиграли {payout} RPLCoin."
    else:
        result = f"💨 Выпала РЕШКА.\nВы проиграли {bet} RPLCoin."

    conn.commit()
    conn.close()

    await update.message.reply_text(
        f"🪙 Монетка подброшена!\n\n{result}",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def show_shop(update, context):
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
    discount = get_discount(cur, user.id)
    conn.commit()
    conn.close()

    text = f"🛒 **МАГАЗИН ПАКОВ**\n🏷 Ваша скидка: **{discount}%**\n\n"
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
        text += "📭 Магазин временно пуст."

    markup = InlineKeyboardMarkup(buttons)
    if query:
        await query.answer()
        await query.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    else:
        await update.message.reply_text(text, reply_markup=markup, parse_mode="Markdown")


async def shop_command(update, context):
    if not await check_pm_registered(update, context):
        return
    await show_shop(update, context)


async def shop_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data == "cancel_pack_buy":
        await show_shop(update, context)
        return

    pack_id = int(data.split("_")[-1])
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM packs WHERE id = %s", (pack_id,))
    pack = cur.fetchone()

    if not pack:
        conn.close()
        await query.answer("Пак не найден.", show_alert=True)
        return

    discount = get_discount(cur, user.id)
    price = discounted_price(pack["price"], discount)

    if data.startswith("preview_pack_"):
        cur.execute(
            """
            SELECT c.nickname, c.ovr, c.rarity
            FROM pack_cards pc
            JOIN cards c ON c.id = pc.card_id
            WHERE pc.pack_id = %s
            ORDER BY c.ovr DESC
            """,
            (pack_id,),
        )
        cards = cur.fetchall()
        conn.close()

        if pack["reveal_cards"]:
            card_text = "\n".join(
                f"• {card['nickname']} — {card['ovr']} OVR [{card['rarity']}]"
                for card in cards
            ) or "Карточки не указаны."
        else:
            card_text = "🔒 Состав пака скрыт администратором."

        text = (
            f"📦 ПАК «{pack['name']}»\n\n"
            f"💰 Цена: {price} RPLCoin"
            + (f"  (скидка {discount}%)" if discount else "")
            + f"\n\n🃏 Содержимое:\n{card_text}"
        )

        await query.answer()
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(
                [
                    [InlineKeyboardButton("✅ Купить", callback_data=f"confirm_pack_{pack_id}")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="cancel_pack_buy")],
                ]
            ),
            parse_mode="Markdown",
        )
        return

    if data.startswith("confirm_pack_"):
        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        account = cur.fetchone()

        if account["balance"] < price:
            conn.close()
            await query.answer("Недостаточно средств.", show_alert=True)
            return

        cur.execute(
            "SELECT buy_count FROM user_pack_buys WHERE user_id = %s AND pack_id = %s",
            (user.id, pack_id),
        )
        buy_row = cur.fetchone()
        bought = buy_row["buy_count"] if buy_row else 0

        if pack["buy_limit"] > 0 and bought >= pack["buy_limit"]:
            conn.close()
            await query.answer("Лимит покупок исчерпан.", show_alert=True)
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
        cards = cur.fetchall()

        if not cards:
            conn.close()
            await query.answer("В паке нет карточек.", show_alert=True)
            return

        card = choose_card(cur, user.id, cards)
        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (price, user.id),
        )
        cur.execute(
            """
            INSERT INTO user_pack_buys(user_id, pack_id, buy_count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, pack_id)
            DO UPDATE SET buy_count = user_pack_buys.buy_count + 1
            """,
            (user.id, pack_id),
        )
        cur.execute(
            """
            INSERT INTO user_cards(user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, card["id"]),
        )
        conn.commit()
        conn.close()

        await query.answer("Пак открыт!", show_alert=True)
        await query.edit_message_text(
            f"🎉 Из пака **{pack['name']}** выпала карта:\n\n"
            f"🃏 **{card['nickname']}**\n"
            f"⭐ OVR: **{card['ovr']}**\n"
            f"✨ Редкость: **{card['rarity']}**",
            parse_mode="Markdown",
        )


active_trades = {}


def trade_keyboard(trade_id):
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("➕ Карта", callback_data=f"tr_addcard_{trade_id}"),
                InlineKeyboardButton("💰 Монеты", callback_data=f"tr_addmoney_{trade_id}"),
            ],
            [InlineKeyboardButton("🧹 Очистить своё", callback_data=f"tr_clear_{trade_id}")],
            [InlineKeyboardButton("✅ Готов", callback_data=f"tr_ready_{trade_id}")],
            [InlineKeyboardButton("❌ Отменить", callback_data=f"tr_cancel_{trade_id}")],
        ]
    )


async def render_trade(trade_id):
    trade = active_trades[trade_id]
    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT first_name, username FROM users WHERE user_id = %s", (trade["p1"],))
    p1 = cur.fetchone()
    cur.execute("SELECT first_name, username FROM users WHERE user_id = %s", (trade["p2"],))
    p2 = cur.fetchone()

    def name(row):
        return row["first_name"] or row["username"] or "Игрок"

    def cards_text(ids):
        if not ids:
            return "—"
        cur.execute("SELECT nickname, ovr FROM cards WHERE id = ANY(%s)", (ids,))
        return "\n".join(f"• {card['nickname']} ({card['ovr']} OVR)" for card in cur.fetchall())

    text = (
        "🤝 **ОКНО ТРЕЙДА**\n\n"
        f"🔴 **{name(p1)}** {'✅' if trade['ready1'] else '⏳'}\n"
        f"💰 {trade['money1']} RPLCoin\n{cards_text(trade['cards1'])}\n\n"
        f"🔵 **{name(p2)}** {'✅' if trade['ready2'] else '⏳'}\n"
        f"💰 {trade['money2']} RPLCoin\n{cards_text(trade['cards2'])}\n\n"
        "После готовности обеих сторон обмен завершится автоматически."
    )
    conn.close()
    return text


async def update_trade(trade_id, context):
    if trade_id not in active_trades:
        return

    text = await render_trade(trade_id)
    trade = active_trades[trade_id]

    for user_id, message_id in trade["messages"].items():
        try:
            await context.bot.edit_message_text(
                chat_id=user_id,
                message_id=message_id,
                text=text,
                reply_markup=trade_keyboard(trade_id),
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def trade_command(update, context):
    if not await check_pm_registered(update, context):
        return

    user = update.effective_user
    if not context.args:
        await update.message.reply_text("Пример: /trade @username")
        return

    target = context.args[0].lstrip("@")
    conn = get_db()
    cur = conn.cursor()
    if target.isdigit():
        cur.execute("SELECT * FROM users WHERE user_id = %s", (int(target),))
    else:
        cur.execute("SELECT * FROM users WHERE username = %s", (target,))
    opponent = cur.fetchone()
    conn.close()

    if not opponent:
        await update.message.reply_text("❌ Игрок не найден.")
        return
    if opponent["user_id"] == user.id:
        await update.message.reply_text("❌ Нельзя торговать с собой.")
        return

    trade_id = f"{user.id}_{opponent['user_id']}_{int(time.time() * 1000)}"
    active_trades[f"request_{trade_id}"] = {
        "from": user.id,
        "to": opponent["user_id"],
    }

    markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Принять",
                    callback_data=f"trade_accept_{trade_id}",
                ),
                InlineKeyboardButton(
                    "❌ Отклонить",
                    callback_data=f"trade_decline_{trade_id}",
                ),
            ]
        ]
    )

    await update.message.reply_text(
        f"🤝 Предложение отправлено игроку **{opponent['first_name']}**.",
        parse_mode="Markdown",
    )

    try:
        await context.bot.send_message(
            opponent["user_id"],
            f"🤝 **{user.first_name}** предлагает начать трейд.",
            reply_markup=markup,
            parse_mode="Markdown",
        )
    except Exception:
        active_trades.pop(f"request_{trade_id}", None)
        await update.message.reply_text("❌ Не удалось доставить предложение.")


async def trade_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data.startswith("trade_accept_") or data.startswith("trade_decline_"):
        trade_id = data.split("_", 2)[2]
        request_key = f"request_{trade_id}"
        request = active_trades.get(request_key)

        if not request or request["to"] != user.id:
            await query.answer("Запрос недействителен.", show_alert=True)
            return

        active_trades.pop(request_key, None)

        if data.startswith("trade_decline_"):
            await query.edit_message_text("❌ Предложение отклонено.")
            try:
                await context.bot.send_message(request["from"], "❌ Игрок отклонил трейд.")
            except Exception:
                pass
            return

        active_trades[trade_id] = {
            "p1": request["from"],
            "p2": request["to"],
            "cards1": [],
            "cards2": [],
            "money1": 0,
            "money2": 0,
            "ready1": False,
            "ready2": False,
            "messages": {},
        }

        message = await query.edit_message_text("🤝 Трейд создан. Загрузка предложения…")
        active_trades[trade_id]["messages"][user.id] = message.message_id

        other_message = await context.bot.send_message(
            request["from"],
            "🤝 Трейд создан. Откройте окно обмена ниже.",
        )
        active_trades[trade_id]["messages"][request["from"]] = other_message.message_id

        await update_trade(trade_id, context)
        return

    if not data.startswith("tr_"):
        return

    parts = data.split("_")
    action = parts[1]
    trade_id = "_".join(parts[2:])
    trade = active_trades.get(trade_id)

    if not trade or user.id not in (trade["p1"], trade["p2"]):
        await query.answer("Трейд больше не активен.", show_alert=True)
        return

    side = 1 if user.id == trade["p1"] else 2

    if action == "cancel":
        active_trades.pop(trade_id, None)
        await query.edit_message_text("🚫 Трейд отменён.")
        return

    if action == "clear":
        trade[f"cards{side}"] = []
        trade[f"money{side}"] = 0
        trade["ready1"] = trade["ready2"] = False
        await query.answer("Ваше предложение очищено.")
        await update_trade(trade_id, context)
        return

    if action == "addmoney":
        context.user_data["trade_id"] = trade_id
        await query.message.reply_text("💰 Введите сумму монет:")
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

        buttons = [
            [
                InlineKeyboardButton(
                    f"{card['nickname']} — {card['ovr']} OVR",
                    callback_data=f"tr_putcard_{trade_id}_{card['id']}",
                )
            ]
            for card in cards
            if card["id"] not in trade[f"cards{side}"]
        ]
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data=f"tr_back_{trade_id}")])

        await query.edit_message_text(
            "🃏 Выберите карточку:",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
        return

    if action == "putcard":
        card_id = int(parts[-1])
        if card_id not in trade[f"cards{side}"]:
            trade[f"cards{side}"].append(card_id)
        trade["ready1"] = trade["ready2"] = False
        await update_trade(trade_id, context)
        return

    if action == "back":
        await update_trade(trade_id, context)
        return

    if action == "ready":
        trade[f"ready{side}"] = not trade[f"ready{side}"]
        await update_trade(trade_id, context)

        if trade["ready1"] and trade["ready2"]:
            await finish_trade(trade_id, context)


async def trade_money_input(update, context):
    try:
        amount = int(update.message.text.strip())
        if amount < 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введите неотрицательное число.")
        return WAITING_TRADE_MONEY

    trade_id = context.user_data.get("trade_id")
    trade = active_trades.get(trade_id)
    if not trade:
        await update.message.reply_text("❌ Трейд больше не активен.")
        return ConversationHandler.END

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    balance = cur.fetchone()["balance"]
    conn.close()

    if amount > balance:
        await update.message.reply_text("❌ Недостаточно средств.")
        return WAITING_TRADE_MONEY

    side = 1 if user.id == trade["p1"] else 2
    trade[f"money{side}"] = amount
    trade["ready1"] = trade["ready2"] = False

    await update.message.reply_text("✅ Сумма добавлена.")
    await update_trade(trade_id, context)
    return ConversationHandler.END


async def finish_trade(trade_id, context):
    trade = active_trades.pop(trade_id, None)
    if not trade:
        return

    conn = get_db()
    cur = conn.cursor()

    cur.execute("SELECT balance FROM users WHERE user_id = %s FOR UPDATE", (trade["p1"],))
    b1 = cur.fetchone()["balance"]
    cur.execute("SELECT balance FROM users WHERE user_id = %s FOR UPDATE", (trade["p2"],))
    b2 = cur.fetchone()["balance"]

    if b1 < trade["money1"] or b2 < trade["money2"]:
        conn.rollback()
        conn.close()
        for uid, mid in trade["messages"].items():
            try:
                await context.bot.edit_message_text(uid, mid, "❌ Трейд отменён: недостаточно средств.")
            except Exception:
                pass
        return

    for side in (1, 2):
        owner = trade[f"p{side}"]
        for card_id in trade[f"cards{side}"]:
            cur.execute(
                """
                SELECT count FROM user_cards
                WHERE user_id = %s AND card_id = %s AND count > 0
                FOR UPDATE
                """,
                (owner, card_id),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                conn.close()
                return

    cur.execute(
        "UPDATE users SET balance = balance - %s + %s WHERE user_id = %s",
        (trade["money1"], trade["money2"], trade["p1"]),
    )
    cur.execute(
        "UPDATE users SET balance = balance - %s + %s WHERE user_id = %s",
        (trade["money2"], trade["money1"], trade["p2"]),
    )

    for side in (1, 2):
        owner = trade[f"p{side}"]
        receiver = trade[f"p{3 - side}"]
        for card_id in trade[f"cards{side}"]:
            cur.execute(
                "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
                (owner, card_id),
            )
            cur.execute(
                "DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0",
                (owner, card_id),
            )
            cur.execute(
                """
                INSERT INTO user_cards(user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (receiver, card_id),
            )

    conn.commit()
    conn.close()

    for uid, mid in trade["messages"].items():
        try:
            await context.bot.edit_message_text(
                chat_id=uid,
                message_id=mid,
                text="🎉 **ТРЕЙД УСПЕШНО ЗАВЕРШЁН!**\nВсе карточки и монеты переданы.",
                parse_mode="Markdown",
            )
        except Exception:
            pass


async def market_command(update, context):
    if not await check_pm_registered(update, context):
        return
    await show_market(update, context)


async def show_market(update, context):
    query = update.callback_query
    user = query.from_user if query else update.effective_user

    conn = get_db()
    cur = conn.cursor()
    discount = get_discount(cur, user.id)
    cur.execute(
        """
        SELECT m.id, m.seller_id, m.price, c.nickname, c.ovr, c.rarity,
               u.username, u.first_name
        FROM market m
        JOIN cards c ON c.id = m.card_id
        JOIN users u ON u.user_id = m.seller_id
        ORDER BY m.id DESC
        LIMIT 30
        """
    )
    items = cur.fetchall()
    conn.commit()
    conn.close()

    text = f"🛒 **ТОРГОВАЯ ПЛОЩАДКА**\n🏷 Ваша скидка: **{discount}%**\n\n"
    buttons = []

    for item in items:
        final_price = discounted_price(item["price"], discount)
        seller = item["username"] or item["first_name"] or "Игрок"
        text += (
            f"🏷 #{item['id']} **{item['nickname']}** — {item['ovr']} OVR\n"
            f"💰 {final_price} RPLCoin · продавец: {seller}\n\n"
        )
        if item["seller_id"] != user.id:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"Купить #{item['id']} — {final_price}",
                        callback_data=f"buy_market_{item['id']}",
                    )
                ]
            )

    if not items:
        text += "📭 Активных лотов нет."

    buttons.extend(
        [
            [InlineKeyboardButton("➕ Выставить карту", callback_data="market_list_menu")],
            [InlineKeyboardButton("📦 Мои лоты", callback_data="my_market_items")],
        ]
    )

    if query:
        await query.answer()
        await query.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )


async def market_callback(update, context):
    query = update.callback_query
    user = query.from_user
    data = query.data

    if data in ("refresh_market", "market_list_menu", "my_market_items"):
        if data == "refresh_market":
            await show_market(update, context)
            return

        if data == "market_list_menu":
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

            buttons = [
                [
                    InlineKeyboardButton(
                        f"{card['nickname']} — {card['ovr']} OVR",
                        callback_data=f"select_mcard_{card['id']}",
                    )
                ]
                for card in cards
            ]
            buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="refresh_inv")])
            await query.edit_message_text(
                "🏷 Выберите карточку для продажи:",
                reply_markup=InlineKeyboardMarkup(buttons),
            )
            return

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
        buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="refresh_market")])
        await query.edit_message_text(
            "📦 **Ваши лоты:**\n" +
            ("\n".join(f"#{item['id']} {item['nickname']} — {item['price']}" for item in items) or "Лотов нет."),
            reply_markup=InlineKeyboardMarkup(buttons),
            parse_mode="Markdown",
        )
        return

    if data.startswith("select_mcard_"):
        context.user_data["market_card_id"] = int(data.split("_")[-1])
        await query.message.reply_text("💰 Введите цену продажи:")
        return WAITING_MARKET_PRICE_INPUT

    if data.startswith("cancel_market_"):
        market_id = int(data.split("_")[-1])
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            "SELECT card_id FROM market WHERE id = %s AND seller_id = %s",
            (market_id, user.id),
        )
        item = cur.fetchone()
        if item:
            cur.execute(
                """
                INSERT INTO user_cards(user_id, card_id, count)
                VALUES (%s, %s, 1)
                ON CONFLICT(user_id, card_id)
                DO UPDATE SET count = user_cards.count + 1
                """,
                (user.id, item["card_id"]),
            )
            cur.execute("DELETE FROM market WHERE id = %s", (market_id,))
            conn.commit()
        conn.close()
        await query.answer("Лот снят.", show_alert=True)
        await show_market(update, context)
        return

    if data.startswith("buy_market_"):
        market_id = int(data.split("_")[-1])
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT * FROM market WHERE id = %s FOR UPDATE", (market_id,))
        item = cur.fetchone()

        if not item or item["seller_id"] == user.id:
            conn.rollback()
            conn.close()
            await query.answer("Лот недоступен.", show_alert=True)
            return

        discount = get_discount(cur, user.id)
        price = discounted_price(item["price"], discount)

        cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
        balance = cur.fetchone()["balance"]

        if balance < price:
            conn.rollback()
            conn.close()
            await query.answer("Недостаточно средств.", show_alert=True)
            return

        cur.execute(
            "UPDATE users SET balance = balance - %s WHERE user_id = %s",
            (price, user.id),
        )
        cur.execute(
            "UPDATE users SET balance = balance + %s WHERE user_id = %s",
            (price, item["seller_id"]),
        )
        cur.execute(
            """
            INSERT INTO user_cards(user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, item["card_id"]),
        )
        cur.execute("DELETE FROM market WHERE id = %s", (market_id,))
        conn.commit()
        conn.close()

        await query.answer("Покупка выполнена!", show_alert=True)
        await show_market(update, context)


async def market_price_input(update, context):
    try:
        price = int(update.message.text.strip())
        if price <= 0 or price > 999999:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Цена должна быть от 1 до 999999.")
        return WAITING_MARKET_PRICE_INPUT

    user = update.effective_user
    card_id = context.user_data.get("market_card_id")

    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT count FROM user_cards
        WHERE user_id = %s AND card_id = %s AND count > 0
        """,
        (user.id, card_id),
    )
    if not cur.fetchone():
        conn.close()
        await update.message.reply_text("❌ Карточка больше недоступна.")
        return ConversationHandler.END

    cur.execute(
        "UPDATE user_cards SET count = count - 1 WHERE user_id = %s AND card_id = %s",
        (user.id, card_id),
    )
    cur.execute(
        "DELETE FROM user_cards WHERE user_id = %s AND card_id = %s AND count <= 0",
        (user.id, card_id),
    )
    cur.execute(
        "INSERT INTO market(seller_id, card_id, price) VALUES (%s, %s, %s)",
        (user.id, card_id, price),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text("✅ Карточка выставлена на рынок.")
    return ConversationHandler.END


async def rps_command(update, context):
    await update.message.reply_text("🎮 Введите ставку:")
    return WAITING_RPS_BET


async def rps_bet(update, context):
    try:
        bet = int(update.message.text.strip())
        if bet <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Некорректная ставка.")
        return WAITING_RPS_BET

    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT balance FROM users WHERE user_id = %s", (user.id,))
    account = cur.fetchone()

    if account["balance"] < bet:
        conn.close()
        await update.message.reply_text("❌ Недостаточно средств.")
        return WAITING_RPS_BET

    choice_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🪨", callback_data=f"rps_rock_{bet}"),
                InlineKeyboardButton("✂️", callback_data=f"rps_scissors_{bet}"),
                InlineKeyboardButton("📄", callback_data=f"rps_paper_{bet}"),
            ]
        ]
    )
    conn.close()

    await update.message.reply_text("Выберите ход:", reply_markup=choice_markup)
    return ConversationHandler.END


async def rps_callback(update, context):
    query = update.callback_query
    _, player, bet_text = query.data.split("_")
    bet = int(bet_text)
    user = query.from_user

    bot_choice = random.choice(["rock", "scissors", "paper"])
    win = {
        ("rock", "scissors"),
        ("scissors", "paper"),
        ("paper", "rock"),
    }

    conn = get_db()
    cur = conn.cursor()
    if (player, bot_choice) in win:
        cur.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (bet, user.id))
        result = "🎉 Вы победили!"
    elif player == bot_choice:
        result = "🤝 Ничья!"
    else:
        cur.execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (bet, user.id))
        result = "❌ Вы проиграли."

    conn.commit()
    conn.close()
    await query.answer()
    await query.edit_message_text(
        f"🎮 Ваш выбор: **{player}**\n🤖 Бот: **{bot_choice}**\n\n{result}",
        parse_mode="Markdown",
    )


async def promo_command(update, context):
    await update.message.reply_text("🎁 Введите промокод:")
    return WAITING_PROMO_INPUT


async def promo_input(update, context):
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
        "SELECT 1 FROM user_promocodes WHERE user_id = %s AND code = %s",
        (user.id, code),
    )
    if cur.fetchone():
        conn.close()
        await update.message.reply_text("❌ Вы уже использовали этот промокод.")
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
        result = f"💰 +{promo['reward_value']} RPLCoin"
    else:
        cur.execute(
            """
            INSERT INTO user_cards(user_id, card_id, count)
            VALUES (%s, %s, 1)
            ON CONFLICT(user_id, card_id)
            DO UPDATE SET count = user_cards.count + 1
            """,
            (user.id, promo["reward_value"]),
        )
        result = f"🃏 Карточка ID {promo['reward_value']}"

    cur.execute(
        "UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = %s",
        (code,),
    )
    cur.execute(
        "INSERT INTO user_promocodes(user_id, code) VALUES (%s, %s)",
        (user.id, code),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(f"🎉 Промокод активирован!\n{result}")
    return ConversationHandler.END


async def cardmmr_command(update, context):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT first_name, username, mmr
        FROM users ORDER BY mmr DESC LIMIT 10
        """
    )
    users = cur.fetchall()
    conn.close()

    text = "🏆 **ТОП-10 MMR**\n\n"
    for index, user in enumerate(users, 1):
        name = user["first_name"] or user["username"] or "Игрок"
        text += f"{index}. {name} — **{user['mmr']} MMR**\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def daily_command(update, context):
    user = update.effective_user
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT last_daily_claim, daily_streak FROM users WHERE user_id = %s",
        (user.id,),
    )
    account = cur.fetchone()
    now = datetime.now()
    last = parse_dt(account["last_daily_claim"])

    if last and now - last < timedelta(hours=24):
        conn.close()
        await update.message.reply_text("⏳ Ежедневный бонус будет доступен через 24 часа после прошлого получения.")
        return

    streak = (account["daily_streak"] % 7) + 1
    reward = 5000 * streak
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
        f"🎁 Бонус за день **{streak}/7** получен!\n"
        f"💰 +{reward} RPLCoin",
        parse_mode="Markdown",
    )


async def checkprofile_command(update, context):
    await profile_command(update, context)


async def cancel_minigame(update, context):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("❌ Мини-игра отменена.")


async def admin_login(update, context):
    await update.message.reply_text("🔐 Введите логин:")
    return WAITING_LOGIN


async def admin_login_receive(update, context):
    context.user_data["admin_login"] = update.message.text.strip()
    await update.message.reply_text("🔑 Введите пароль:")
    return WAITING_PASSWORD


async def admin_password_receive(update, context):
    login = context.user_data.get("admin_login")
    password = update.message.text.strip()

    credentials = {
        "goyda1488": "goydarpl",
        "rzk1488": "rzksigma",
    }

    if credentials.get(login) != password:
        await update.message.reply_text("❌ Неверные данные.")
        return ConversationHandler.END

    add_admin(update.effective_user.id)
    await update.message.reply_text("✅ Авторизация успешна.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END


def build_application():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("freepack", freepack_command))
    app.add_handler(CommandHandler("inventory", inventory_command))
    app.add_handler(CommandHandler("profile", profile_command))
    app.add_handler(CommandHandler("checkprofile", checkprofile_command))
    app.add_handler(CommandHandler("cardmatch", cardmatch_command))
    app.add_handler(CommandHandler("cardmmr", cardmmr_command))
    app.add_handler(CommandHandler("shop", shop_command))
    app.add_handler(CommandHandler("cardshop", market_command))
    app.add_handler(CommandHandler("trade", trade_command))
    app.add_handler(CommandHandler("wheel", wheel_command))
    app.add_handler(CommandHandler("daily", daily_command))
    app.add_handler(CommandHandler("promo", promo_command))
    app.add_handler(CommandHandler("rps", rps_command))
    app.add_handler(CommandHandler("coin", coin_command))
    app.add_handler(CommandHandler("adminkarpl", admin_login))

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("promo", promo_command)],
            states={WAITING_PROMO_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, promo_input)]},
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("coin", coin_command)],
            states={WAITING_COIN_BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, coin_receive_bet)]},
            fallbacks=[CallbackQueryHandler(cancel_minigame, pattern="^cancel_minigame$")],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CommandHandler("rps", rps_command)],
            states={WAITING_RPS_BET: [MessageHandler(filters.TEXT & ~filters.COMMAND, rps_bet)]},
            fallbacks=[CallbackQueryHandler(cancel_minigame, pattern="^cancel_minigame$")],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(market_callback, pattern="^select_mcard_")],
            states={
                WAITING_MARKET_PRICE_INPUT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, market_price_input)
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(trade_callback, pattern="^tr_addmoney_")],
            states={
                WAITING_TRADE_MONEY: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, trade_money_input)
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        ConversationHandler(
            entry_points=[CallbackQueryHandler(craft_callback, pattern="^craft_pick_")],
            states={
                WAITING_CRAFT_CARDS: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, craft_cards_input)
                ]
            },
            fallbacks=[],
            per_message=False,
        )
    )

    app.add_handler(
        CallbackQueryHandler(match_callback, pattern="^(cancel_match_)")
    )

    app.add_handler(
        CallbackQueryHandler(profile_callback, pattern="^(refresh_profile|edit_roster|set_pos_|apply_card_)")
    )

    app.add_handler(
        CallbackQueryHandler(craft_callback, pattern="^(craft_menu|craft_pick_|craft_confirm)")
    )

    app.add_handler(
        CallbackQueryHandler(upgrade_callback, pattern="^(upgrade_menu|upgrade_source_|upgrade_target_|upgrade_confirm)")
    )

    app.add_handler(
        CallbackQueryHandler(shop_callback, pattern="^(preview_pack_|confirm_pack_|cancel_pack_buy)")
    )

    app.add_handler(
        CallbackQueryHandler(market_callback, pattern="^(refresh_market|market_list_menu|my_market_items|select_mcard_|cancel_market_|buy_market_)")
    )

    app.add_handler(
        CallbackQueryHandler(trade_callback, pattern="^(trade_accept_|trade_decline_|tr_)")
    )

    app.add_handler(
        CallbackQueryHandler(rps_callback, pattern="^rps_")
    )

    app.add_handler(
        CallbackQueryHandler(cancel_minigame, pattern="^cancel_minigame$")
    )

    app.add_handler(
        CallbackQueryHandler(
            lambda update, context: minigames_menu(update, context),
            pattern="^back_to_games$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda update, context: coin_command(update, context),
            pattern="^play_coin$",
        )
    )

    app.add_handler(MessageHandler(filters.Regex("^🏠 Главное меню$"), main_menu))
    app.add_handler(MessageHandler(filters.Regex("^🃏 Бесплатная карта$"), freepack_command))
    app.add_handler(MessageHandler(filters.Regex("^🎒 Инвентарь$"), inventory_command))
    app.add_handler(MessageHandler(filters.Regex("^🛒 Торговая площадка$"), market_command))
    app.add_handler(MessageHandler(filters.Regex("^🏒 Состав и Профиль$"), profile_command))
    app.add_handler(MessageHandler(filters.Regex("^⚔️ Искать игру$"), cardmatch_command))
    app.add_handler(MessageHandler(filters.Regex("^🛒 Магазин Паков$"), shop_command))
    app.add_handler(MessageHandler(filters.Regex("^🏆 Топ MMR$"), cardmmr_command))
    app.add_handler(MessageHandler(filters.Regex("^🤝 Трейд$"), trade_command))
    app.add_handler(MessageHandler(filters.Regex("^🎮 Мини-игры$"), minigames_menu))
    app.add_handler(MessageHandler(filters.Regex("^🎡 Колесо удачи$"), wheel_command))
    app.add_handler(MessageHandler(filters.Regex("^🎁 Ежедневный бонус$"), daily_command))

    return app


def main():
    application = build_application()
    logger.info("RPL bot started")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
