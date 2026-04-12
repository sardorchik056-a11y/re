import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

import database as db
import duels
import payments

BOT_TOKEN = "8796618330:AAHLie3NBXmDR5FqUiFhvwBtghU9aA5Vor0"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════════════════════
#  ADMINS
# ══════════════════════════════════════════════════════════════════════════════

ADMINS = {8118184388}

# ══════════════════════════════════════════════════════════════════════════════
#  EMOJI IDs
# ══════════════════════════════════════════════════════════════════════════════

EMOJI_PROFILE    = "5260399854500191689"
EMOJI_GAMES      = "6039496266180726678"
EMOJI_REFERRALS  = "5258513401784573443"
EMOJI_STATISTICS = "5258330865674494479"
EMOJI_ABOUT      = "5357069174512303778"
EMOJI_BACK       = "6039539366177541657"

EMOJI_DEPOSIT    = "5904462880941545555"
EMOJI_WITHDRAW   = "5258043150110301407"
EMOJI_ID         = "6030776052345737530"
EMOJI_USERNAME   = "5258185631355378853"
EMOJI_TURNOVER   = "5904462880941545555"
EMOJI_DAYS       = "5258330865674494479"
EMOJI_BALANCE    = "5258204546391351475"

EMOJI_FILTER_DAY = "5904462880941545555"
EMOJI_FILTER_WEK = "5904462880941545555"
EMOJI_FILTER_ALL = "5904462880941545555"

EMOJI_LINK       = "5260730055880876557"
EMOJI_INVITED    = "5258513401784573443"
EMOJI_EARNED     = "5890848474563352982"

EMOJI_CHAT       = "5258215846450305872"
EMOJI_SUPPORT    = "5357069174512303778"
EMOJI_NEWS       = "5258185631355378853"

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

DICE_EMOJI = {
    "cub":    "🎲",
    "dart":   "🎯",
    "basket": "🏀",
    "bowl":   "🎳",
    "foot":   "⚽",
}

BOT_USERNAME = "TEST_ADVdbot"   # ← замени на реальный юзернейм бота


def btn(text: str, callback_data: str, emoji_id: str = "") -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, callback_data=callback_data)
    if emoji_id:
        b.icon_custom_emoji_id = emoji_id
    return b


def url_btn(text: str, url: str, emoji_id: str = "") -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, url=url)
    if emoji_id:
        b.icon_custom_emoji_id = emoji_id
    return b

# ══════════════════════════════════════════════════════════════════════════════
#  KEYBOARDS
# ══════════════════════════════════════════════════════════════════════════════

def kb_main() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(
        btn("Профиль",       "profile",      EMOJI_PROFILE),
        btn("Активные игры", "active_games", EMOJI_GAMES),
    )
    m.row(
        btn("Рефералы",   "referrals",  EMOJI_REFERRALS),
        btn("Статистика", "statistics", EMOJI_STATISTICS),
    )
    m.row(btn("О проекте", "about", EMOJI_ABOUT))
    return m


def kb_back_main() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(btn("Главное меню", "main_menu", EMOJI_BACK))
    return m


def kb_profile() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(
        btn("Пополнить", "deposit",  EMOJI_DEPOSIT),
        btn("Вывести",   "withdraw", EMOJI_WITHDRAW),
    )
    m.row(btn("Главное меню", "main_menu", EMOJI_BACK))
    return m


def kb_stats(active: str = "all") -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    labels = {"day": "Сегодня", "week": "Неделя", "all": "Все время"}
    row = []
    for key, label in labels.items():
        text = f"· {label} ·" if key == active else label
        row.append(btn(text, f"stats_{key}",
                       EMOJI_FILTER_DAY if key == "day" else
                       EMOJI_FILTER_WEK if key == "week" else EMOJI_FILTER_ALL))
    m.row(*row)
    m.row(btn("Главное меню", "main_menu", EMOJI_BACK))
    return m


def kb_about() -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(
        url_btn("Наш чат",   "https://t.me/yourchat",    EMOJI_CHAT),
        url_btn("Поддержка", "https://t.me/yoursupport", EMOJI_SUPPORT),
    )
    m.row(url_btn("Новости", "https://t.me/yournews", EMOJI_NEWS))
    m.row(btn("Главное меню", "main_menu", EMOJI_BACK))
    return m


def kb_active_games(games: list) -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    for g in games:
        e    = DICE_EMOJI.get(g["game_type"], "🎲")
        mode = "очки" if g["mode"] == "x" else "сумма"
        label = f"{e} ${g['bet']:,.2f} | {g['rounds']}р {mode}"
        m.row(InlineKeyboardButton(text=label, callback_data=f"duel_view:{g['id']}"))
    m.row(btn("Главное меню", "main_menu", EMOJI_BACK))
    return m


def kb_duel_view(game_id: int) -> InlineKeyboardMarkup:
    m = InlineKeyboardMarkup()
    m.row(InlineKeyboardButton(text="➕ Присоединиться", callback_data=f"duel_join:{game_id}"))
    m.row(btn("Назад", "active_games", EMOJI_BACK))
    return m

# ══════════════════════════════════════════════════════════════════════════════
#  TEXT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def text_profile(user) -> str:
    uid      = user.id
    row      = db.get_user_row(uid)
    username = f"@{user.username}" if user.username else "не указан"
    balance  = row["balance"]  if row else 0.0
    turnover = row["turnover"] if row else 0.0
    days     = db.days_since_registration(uid)
    return (
        f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> <b>Профиль</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_ID}">🆔</tg-emoji> <b>ID:</b>  <code>{uid}</code>\n'
        f'<tg-emoji emoji-id="{EMOJI_USERNAME}">✏️</tg-emoji> <b>Юзернейм:</b>  {username}\n'
        f'<tg-emoji emoji-id="{EMOJI_DAYS}">📅</tg-emoji> <b>В проекте:</b>  {days} дн.\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_BALANCE}">💎</tg-emoji> <b>Баланс:</b>  <b>${balance:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_TURNOVER}">🔄</tg-emoji> <b>Оборот:</b>  <b>${turnover:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━'
    )


def text_stats(period: str = "all") -> str:
    period_labels = {"day": "Сегодня", "week": "Неделя", "all": "Все время"}
    label = period_labels.get(period, "Все время")
    s = db.get_stats(period)
    return (
        f'<tg-emoji emoji-id="{EMOJI_STATISTICS}">📊</tg-emoji> <b>Статистика — {label}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="5904462880941545555">📥</tg-emoji> <b>Всего пополнений:</b>  <b>${s["total_dep"]:,.2f}</b>\n'
        f'<tg-emoji emoji-id="5258043150110301407">📤</tg-emoji> <b>Всего выводов:</b>    <b>${s["total_with"]:,.2f}</b>\n'
        f'<tg-emoji emoji-id="6030833407339008632">🔄</tg-emoji> <b>Оборот:</b>           <b>${s["turnover"]:,.2f}</b>\n'
        f'<tg-emoji emoji-id="5890848474563352982">💰</tg-emoji> <b>Прибыль:</b>          <b>${s["profit"]:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━'
    )


def text_referrals(user) -> str:
    uid      = user.id
    ref_link = f"https://t.me/{BOT_USERNAME}?start=ref{uid}"
    invited, earned = db.get_referral_stats(uid)
    return (
        f'<tg-emoji emoji-id="{EMOJI_REFERRALS}">👥</tg-emoji> <b>Рефералы</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_LINK}">🔗</tg-emoji> <b>Ваша ссылка:</b>\n'
        f'<code>{ref_link}</code>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_INVITED}">👤</tg-emoji> <b>Приглашено:</b>  <b>{invited} чел.</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_EARNED}">💵</tg-emoji> <b>Заработано:</b>  <b>${earned:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'Вы получаете <b>1%</b> от выигрыша каждого\n'
        f'приглашённого реферала — прямо на баланс!'
    )


def text_about() -> str:
    return (
        f'<tg-emoji emoji-id="{EMOJI_ABOUT}">ℹ️</tg-emoji> <b>О проекте</b>\n'
    )


def text_active_games(games: list) -> str:
    if not games:
        return (
            f'<tg-emoji emoji-id="{EMOJI_GAMES}">⚔️</tg-emoji> <b>Активные игры</b>\n'
            f'━━━━━━━━━━━━━━━━━━━━━\n'
            f'Пусто — нет открытых дуэлей.\n'
        )
    return (
        f'<tg-emoji emoji-id="{EMOJI_GAMES}">⚔️</tg-emoji> <b>Активные игры</b>  ({len(games)} шт.)\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'Выбери дуэль чтобы присоединиться:'
    )


def text_duel_view(g) -> str:
    e = DICE_EMOJI.get(g["game_type"], "🎲")
    mode_lbl = (f"до {g['win_score']} очков" if g["mode"] == "x"
                else f"{g['rounds']} бросков • сумма")
    p1_row  = db.get_user_row(g["p1_uid"])
    p1_un   = p1_row["username"]   if p1_row and p1_row["username"]   else ""
    p1_name = p1_row["first_name"] if p1_row and p1_row["first_name"] else str(g["p1_uid"])
    p1_d    = f"@{p1_un}" if p1_un else p1_name
    return (
        f'{e} <b>Дуэль — информация</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_GAMES}">⚔️</tg-emoji> <b>Режим:</b>  {mode_lbl}\n'
        f'<tg-emoji emoji-id="{EMOJI_BALANCE}">💎</tg-emoji> <b>Ставка:</b>  <b>${g["bet"]:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> <b>Создатель:</b>  {p1_d}\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'Нажми <b>Присоединиться</b> чтобы вступить в игру!'
    )


# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — /add  /sub
# ══════════════════════════════════════════════════════════════════════════════

def _resolve_target(target_raw: str):
    if target_raw.startswith("@"):
        uid = db.resolve_username(target_raw[1:])
        if uid is None:
            return None, (
                f"❌ Пользователь <b>{target_raw}</b> не найден.\n"
                f"Он должен хотя бы раз запустить бота (/start)."
            )
        return uid, None
    else:
        try:
            return int(target_raw), None
        except ValueError:
            return None, "❌ Укажи числовой ID или @username."


@bot.message_handler(commands=["add"])
def cmd_add(message):
    if message.from_user.id not in ADMINS:
        bot.reply_to(message, "❌ Нет доступа.")
        return

    parts = message.text.strip().split()
    if len(parts) != 3:
        bot.reply_to(
            message,
            "❌ Формат: <code>/add @username 500</code>\n"
            "или:      <code>/add 123456789 500</code>",
        )
        return

    target_raw, amount_raw = parts[1], parts[2]

    try:
        amount = float(amount_raw.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ Сумма должна быть положительным числом.")
        return

    target_id, err = _resolve_target(target_raw)
    if err:
        bot.reply_to(message, err)
        return

    db.ensure_user(target_id)
    db.add_balance(target_id, amount)
    new_balance = db.get_balance(target_id)

    bot.reply_to(
        message,
        f'✅ <b>Баланс пополнен</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'👤 ID: <code>{target_id}</code>\n'
        f'💰 Начислено: <b>+${amount:,.2f}</b>\n'
        f'💎 Новый баланс: <b>${new_balance:,.2f}</b>',
    )
    try:
        bot.send_message(
            target_id,
            f'💰 <b>Вам начислен баланс!</b>\n'
            f'━━━━━━━━━━━━━━━━━━━━━\n'
            f'➕ Начислено: <b>+${amount:,.2f}</b>\n'
            f'💎 Ваш баланс: <b>${new_balance:,.2f}</b>',
        )
    except Exception:
        bot.send_message(
            message.chat.id,
            f'⚠️ Пользователь <code>{target_id}</code> не запускал бота — '
            f'уведомление не отправлено.',
        )


@bot.message_handler(commands=["sub"])
def cmd_sub(message):
    if message.from_user.id not in ADMINS:
        bot.reply_to(message, "❌ Нет доступа.")
        return

    parts = message.text.strip().split()
    if len(parts) != 3:
        bot.reply_to(
            message,
            "❌ Формат: <code>/sub @username 500</code>\n"
            "или:      <code>/sub 123456789 500</code>",
        )
        return

    target_raw, amount_raw = parts[1], parts[2]

    try:
        amount = float(amount_raw.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ Сумма должна быть положительным числом.")
        return

    target_id, err = _resolve_target(target_raw)
    if err:
        bot.reply_to(message, err)
        return

    db.ensure_user(target_id)
    current = db.get_balance(target_id)
    actually_sub = min(amount, current)

    if actually_sub <= 0:
        bot.reply_to(
            message,
            f'❌ У <code>{target_id}</code> нулевой баланс. Нечего снимать.',
        )
        return

    db.add_balance(target_id, -actually_sub)
    new_balance = db.get_balance(target_id)

    warn = ""
    if actually_sub < amount:
        warn = (f'\n⚠️ Баланс был меньше — '
                f'списано только <b>${actually_sub:,.2f}</b>')

    bot.reply_to(
        message,
        f'✅ <b>Баланс списан</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'👤 ID: <code>{target_id}</code>\n'
        f'💸 Списано: <b>-${actually_sub:,.2f}</b>\n'
        f'💎 Новый баланс: <b>${new_balance:,.2f}</b>'
        f'{warn}',
    )
    try:
        bot.send_message(
            target_id,
            f'⚠️ <b>С вашего баланса списаны средства!</b>\n'
            f'━━━━━━━━━━━━━━━━━━━━━\n'
            f'➖ Списано: <b>-${actually_sub:,.2f}</b>\n'
            f'💎 Ваш баланс: <b>${new_balance:,.2f}</b>',
        )
    except Exception:
        bot.send_message(
            message.chat.id,
            f'⚠️ Пользователь <code>{target_id}</code> не запускал бота — '
            f'уведомление не отправлено.',
        )

# ══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

WELCOME_TEXT = (
    '<tg-emoji emoji-id="5258501105293205250">👤</tg-emoji>'
    '<b>Добро пожаловать, стрелок.</b>\n\n'
    '<b><tg-emoji emoji-id="5258185631355378853">👤</tg-emoji>'
    'Здесь слова имеют вес только если подкреплены звоном монет. '
    'Хочешь доказать, что ты лучший?</b>\n'
    '<b><tg-emoji emoji-id="6039496266180726678">👤</tg-emoji>'
    'Приготовь свой кошелек и хладнокровие!</b>'
)


def _parse_ref_from_start(text: str):
    """
    Парсит реферальный uid из параметра /start.
    /start ref123456789  →  123456789 (int)
    /start               →  None
    """
    parts = (text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        return None
    payload = parts[1].strip()
    if payload.startswith("ref"):
        try:
            return int(payload[3:])
        except ValueError:
            return None
    return None


@bot.message_handler(commands=["start", "menu"])
def start_handler(message):
    uid        = message.from_user.id
    username   = message.from_user.username or ""
    first_name = (
        f"{message.from_user.first_name or ''} "
        f"{message.from_user.last_name or ''}"
    ).strip()

    # Определяем реферера до записи в БД
    ref_uid = _parse_ref_from_start(message.text)

    # Защита: нельзя быть своим рефералом
    if ref_uid == uid:
        ref_uid = None

    # Защита: реферер должен существовать в БД
    if ref_uid is not None and db.is_new_user(ref_uid):
        ref_uid = None  # Реферер не зарегистрирован — игнорируем

    # Защита: ref_by записывается ТОЛЬКО при первой регистрации (ON CONFLICT DO UPDATE
    # не трогает ref_by — логика внутри ensure_user)
    is_new = db.is_new_user(uid)
    db.ensure_user(uid, username, first_name, ref_by=ref_uid if is_new else None)

    # Уведомить реферера если это новый пользователь
    if is_new and ref_uid is not None:
        try:
            ref_row = db.get_user_row(ref_uid)
            ref_invited, _ = db.get_referral_stats(ref_uid)
            # ref_count обновляется в referral_try_reward при первом выигрыше —
            # здесь шлём просто уведомление о регистрации реферала
            bot.send_message(
                ref_uid,
                f'<tg-emoji emoji-id="6039496266180726678">👤</tg-emoji><b>Новый реферал!</b>\n'
                parse_mode="HTML",
            )
        except Exception:
            pass

    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=kb_main())


# ── Главный callback_handler ─────────────────────────────────────────────────

@bot.callback_query_handler(func=lambda call: call.data not in ("pay_cancel",)
    and not call.data.startswith("duel_join:")
    and not call.data.startswith("duel_cancel:"))
def callback_handler(call):
    chat_id = call.message.chat.id
    msg_id  = call.message.message_id
    data    = call.data
    user    = call.from_user

    db.ensure_user(
        user.id,
        user.username or "",
        (f"{user.first_name or ''} {user.last_name or ''}").strip(),
    )

    def edit(text, markup):
        try:
            bot.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=markup,
                parse_mode="HTML",
            )
        except Exception:
            pass

    bot.answer_callback_query(call.id)

    if data == "main_menu":
        edit(WELCOME_TEXT, kb_main())

    elif data == "profile":
        edit(text_profile(user), kb_profile())

    elif data == "active_games":
        games = db.game_get_active_lobby_all()
        edit(text_active_games(games), kb_active_games(games))

    elif data.startswith("duel_view:"):
        game_id = int(data.split(":")[1])
        g = db.game_get(game_id)
        if not g or g["state"] != "lobby":
            games = db.game_get_active_lobby_all()
            edit(
                f'<tg-emoji emoji-id="{EMOJI_GAMES}">⚔️</tg-emoji> <b>Активные игры</b>\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n'
                f'❌ Эта дуэль уже недоступна.',
                kb_active_games(games),
            )
        else:
            edit(text_duel_view(g), kb_duel_view(game_id))

    elif data == "referrals":
        edit(text_referrals(user), kb_back_main())

    elif data in ("statistics", "stats_all"):
        edit(text_stats("all"), kb_stats("all"))

    elif data == "stats_day":
        edit(text_stats("day"), kb_stats("day"))

    elif data == "stats_week":
        edit(text_stats("week"), kb_stats("week"))

    elif data == "about":
        edit(text_about(), kb_about())

    elif data == "deposit":
        payments.open_deposit(bot, user.id, chat_id, msg_id)

    elif data == "withdraw":
        payments.open_withdraw(bot, user.id, chat_id, msg_id)


# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    db.init_db()
    duels.register(bot)
    payments.register(bot)

    print("Бот запущен...")
    bot.infinity_polling(skip_pending=True)
