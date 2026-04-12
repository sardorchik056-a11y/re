import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

BOT_TOKEN = "8796618330:AAHLie3NBXmDR5FqUiFhvwBtghU9aA5Vor0"
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

# ══════════════════════════════════════════════════════════════════════════════
#  ADMINS
# ══════════════════════════════════════════════════════════════════════════════

ADMINS = {8118184388}

_balances: dict[int, float] = {}

def get_balance(uid: int) -> float:
    return _balances.get(uid, 0.0)

def add_balance(uid: int, amount: float):
    _balances[uid] = round(_balances.get(uid, 0.0) + amount, 2)

_users: dict[str, int] = {}

def register_user(user):
    if user.username:
        _users[user.username.lower()] = user.id

def resolve_target(raw: str) -> int | None:
    if raw.startswith("@"):
        return _users.get(raw[1:].lower())
    try:
        return int(raw)
    except ValueError:
        return None

# ══════════════════════════════════════════════════════════════════════════════
#  EMOJI IDs
# ══════════════════════════════════════════════════════════════════════════════

EMOJI_PROFILE    = "5904462880941545555"
EMOJI_GAMES      = "5904462880941545555"
EMOJI_REFERRALS  = "5904462880941545555"
EMOJI_STATISTICS = "5904462880941545555"
EMOJI_ABOUT      = "5904462880941545555"
EMOJI_BACK       = "5904462880941545555"

EMOJI_DEPOSIT    = "5904462880941545555"
EMOJI_WITHDRAW   = "5904462880941545555"
EMOJI_ID         = "5904462880941545555"
EMOJI_USERNAME   = "5904462880941545555"
EMOJI_TURNOVER   = "5904462880941545555"
EMOJI_DAYS       = "5904462880941545555"
EMOJI_BALANCE    = "5904462880941545555"
EMOJI_RANK       = "5904462880941545555"

EMOJI_TOTAL_DEP  = "5904462880941545555"
EMOJI_TOTAL_WITH = "5904462880941545555"
EMOJI_PROFIT     = "5904462880941545555"
EMOJI_FILTER_DAY = "5904462880941545555"
EMOJI_FILTER_WEK = "5904462880941545555"
EMOJI_FILTER_ALL = "5904462880941545555"

EMOJI_LINK       = "5904462880941545555"
EMOJI_INVITED    = "5904462880941545555"
EMOJI_EARNED     = "5904462880941545555"

EMOJI_CHAT       = "5904462880941545555"
EMOJI_SUPPORT    = "5904462880941545555"
EMOJI_NEWS       = "5904462880941545555"

# ══════════════════════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def btn(text: str, callback_data: str, emoji_id: str) -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, callback_data=callback_data)
    b.icon_custom_emoji_id = emoji_id
    return b


def url_btn(text: str, url: str, emoji_id: str) -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, url=url)
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


def kb_back() -> InlineKeyboardMarkup:
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

# ══════════════════════════════════════════════════════════════════════════════
#  TEXT BUILDERS
# ══════════════════════════════════════════════════════════════════════════════

def text_profile(user) -> str:
    username = f"@{user.username}" if user.username else "не указан"
    uid      = user.id
    balance  = get_balance(uid)
    turnover = 0.00
    days     = 0
    rank     = "Новичок"
    return (
        f'<tg-emoji emoji-id="{EMOJI_PROFILE}">👤</tg-emoji> <b>Профиль</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_ID}">🆔</tg-emoji> <b>ID:</b>  <code>{uid}</code>\n'
        f'<tg-emoji emoji-id="{EMOJI_USERNAME}">✏️</tg-emoji> <b>Юзернейм:</b>  {username}\n'
        f'<tg-emoji emoji-id="{EMOJI_DAYS}">📅</tg-emoji> <b>В проекте:</b>  {days} дн.\n'
        f'<tg-emoji emoji-id="{EMOJI_RANK}">🏆</tg-emoji> <b>Ранг:</b>  {rank}\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_BALANCE}">💎</tg-emoji> <b>Баланс:</b>  <b>${balance:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_TURNOVER}">🔄</tg-emoji> <b>Оборот:</b>  <b>${turnover:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━'
    )


def text_stats(period: str = "all") -> str:
    period_labels = {"day": "Сегодня", "week": "Неделя", "all": "Все время"}
    label = period_labels.get(period, "Все время")
    total_dep  = 0.00
    total_with = 0.00
    turnover   = 0.00
    profit     = 0.00
    return (
        f'<tg-emoji emoji-id="{EMOJI_STATISTICS}">📊</tg-emoji> <b>Статистика — {label}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_TOTAL_DEP}">📥</tg-emoji> <b>Всего пополнений:</b>  <b>${total_dep:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_TOTAL_WITH}">📤</tg-emoji> <b>Всего выводов:</b>    <b>${total_with:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_TURNOVER}">🔄</tg-emoji> <b>Оборот:</b>           <b>${turnover:,.2f}</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_PROFIT}">💰</tg-emoji> <b>Прибыль:</b>          <b>${profit:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━'
    )


def text_referrals(user) -> str:
    uid      = user.id
    ref_link = f"https://t.me/YourBotUsername?start=ref{uid}"
    invited  = 0
    earned   = 0.00
    return (
        f'<tg-emoji emoji-id="{EMOJI_REFERRALS}">👥</tg-emoji> <b>Рефералы</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'<tg-emoji emoji-id="{EMOJI_LINK}">🔗</tg-emoji> <b>Ваша ссылка:</b>\n'
        f'<code>{ref_link}</code>\n\n'
        f'<tg-emoji emoji-id="{EMOJI_INVITED}">👤</tg-emoji> <b>Приглашено:</b>  <b>{invited} чел.</b>\n'
        f'<tg-emoji emoji-id="{EMOJI_EARNED}">💵</tg-emoji> <b>Заработано:</b>  <b>${earned:,.2f}</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'💡 Вы получаете <b>1%</b> от выигрыша каждого\n'
        f'приглашённого реферала — прямо на баланс!'
    )


def text_about() -> str:
    return (
        f'<tg-emoji emoji-id="{EMOJI_ABOUT}">ℹ️</tg-emoji> <b>О проекте</b>\n'
        f'━━━━━━━━━━━━━━━━━━━━━\n'
        f'Добро пожаловать в наш проект!\n\n'
        f'Мы предоставляем честную и прозрачную\n'
        f'платформу для игр и заработка.\n\n'
        f'По всем вопросам обращайтесь в поддержку\n'
        f'или следите за новостями в канале.\n'
        f'━━━━━━━━━━━━━━━━━━━━━'
    )

# ══════════════════════════════════════════════════════════════════════════════
#  ADMIN — /add
# ══════════════════════════════════════════════════════════════════════════════

@bot.message_handler(commands=["add"])
def cmd_add(message):
    if message.from_user.id not in ADMINS:
        bot.reply_to(message, "❌ Нет доступа.")
        return

    parts = message.text.strip().split()
    if len(parts) != 3:
        bot.reply_to(
            message,
            "❌ Неверный формат.\n"
            "Используй: <code>/add @username 500</code>\n"
            "или: <code>/add 123456789 500</code>",
        )
        return

    target_raw = parts[1]
    amount_raw = parts[2]

    try:
        amount = float(amount_raw.replace(",", "."))
        if amount <= 0:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ Сумма должна быть положительным числом.")
        return

    target_id = resolve_target(target_raw)

    if target_id is None:
        if target_raw.startswith("@"):
            bot.reply_to(
                message,
                f"❌ Пользователь <b>{target_raw}</b> не найден.\n"
                f"Он должен хотя бы раз запустить бота (/start).",
            )
        else:
            bot.reply_to(message, "❌ Укажи числовой ID или @username.")
        return

    add_balance(target_id, amount)
    new_balance = get_balance(target_id)

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
            f'⚠️ Пользователь <code>{target_id}</code> не запускал бота — уведомление не отправлено.',
        )

# ══════════════════════════════════════════════════════════════════════════════
#  HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

WELCOME_TEXT = "🏠 <b>Главное меню</b>\n\nДобро пожаловать! Выберите раздел:"


@bot.message_handler(commands=["start", "menu"])
def start_handler(message):
    register_user(message.from_user)
    bot.send_message(message.chat.id, WELCOME_TEXT, reply_markup=kb_main())


@bot.callback_query_handler(func=lambda call: call.data not in ("duel_join", "duel_cancel"))
def callback_handler(call):
    chat_id = call.message.chat.id
    msg_id  = call.message.message_id
    data    = call.data
    user    = call.from_user

    def edit(text, markup):
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=msg_id,
            text=text,
            reply_markup=markup,
        )

    if data == "main_menu":
        edit(WELCOME_TEXT, kb_main())
    elif data == "profile":
        edit(text_profile(user), kb_profile())
    elif data == "active_games":
        edit("🚧 <b>Активные игры</b>\n\nРаздел в разработке...", kb_back())
    elif data == "referrals":
        edit(text_referrals(user), kb_back())
    elif data in ("statistics", "stats_all"):
        edit(text_stats("all"), kb_stats("all"))
    elif data == "stats_day":
        edit(text_stats("day"), kb_stats("day"))
    elif data == "stats_week":
        edit(text_stats("week"), kb_stats("week"))
    elif data == "about":
        edit(text_about(), kb_about())
    elif data == "deposit":
        edit(
            f'<tg-emoji emoji-id="{EMOJI_DEPOSIT}">📥</tg-emoji> <b>Пополнение</b>\n\n'
            '🚧 Раздел в разработке...',
            kb_back(),
        )
    elif data == "withdraw":
        edit(
            f'<tg-emoji emoji-id="{EMOJI_WITHDRAW}">📤</tg-emoji> <b>Вывод</b>\n\n'
            '🚧 Раздел в разработке...',
            kb_back(),
        )

    bot.answer_callback_query(call.id)


# ══════════════════════════════════════════════════════════════════════════════
#  RUN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # ВАЖНО: duels.register(bot) вызывается ПОСЛЕ определения всех хендлеров main.py,
    # но ДО infinity_polling — иначе хендлеры дуэлей не зарегистрируются.
    import duels
    duels.register(bot)

    print("Бот запущен...")
    bot.infinity_polling()
