"""
payments.py — пополнение и вывод через @CryptoBot (CryptoPay API)

Вся навигация только через edit_message_text — никаких новых сообщений.
FSM хранит (chat_id, message_id) исходного меню-сообщения и редактирует его.

Защита от дублей:
  • invoice_id — UNIQUE в таблице deposits
  • deposit_confirm() — UPDATE WHERE status='pending' (rowcount=0 если уже обработан)
  • withdrawal_create() — атомарное списание + создание заявки в одной транзакции
  • withdrawal_has_pending() — блокирует параллельные запросы одного юзера

Настройки:
  DEPOSIT_MIN       = 0.10 USDT
  INVOICE_EXPIRE_IN = 300 сек (5 мин)
  POLL_INTERVAL     = 3 сек
"""

import threading
import time
import logging
from typing import Optional

import requests
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import database as db

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════════════════════════════════════

CRYPTO_PAY_TOKEN  = "552018:AAmEzVekZI0E1Qcpi0ccOxbkOMk01J2Qs2n"
CRYPTO_PAY_URL    = "https://pay.crypt.bot/api"
# CRYPTO_PAY_URL  = "https://testnet-pay.crypt.bot/api"

DEFAULT_ASSET     = "USDT"

DEPOSIT_MIN       = 0.10
DEPOSIT_MAX       = 10_000.0
WITHDRAW_MIN      = 0.10
WITHDRAW_MAX      = 10_000.0

POLL_INTERVAL     = 3
INVOICE_EXPIRE_IN = 300

# ══════════════════════════════════════════════════════════════════════════════
#  EMOJI IDs для кнопок (icon_custom_emoji_id — как в main.py)
# ══════════════════════════════════════════════════════════════════════════════

EMOJI_PAY      = "5260730055880876557"   # кнопка оплатить
EMOJI_CANCEL   = "6039539366177541657"   # кнопка отменить
EMOJI_BACK     = "6039539366177541657"   # кнопка назад
EMOJI_CHECK    = "5258185631355378853"   # кнопка получить чек

# ══════════════════════════════════════════════════════════════════════════════
#  КАСТОМНЫЕ ЭМОДЗИ ДЛЯ ТЕКСТОВ (tg-emoji в теле сообщений)
# ══════════════════════════════════════════════════════════════════════════════

E_WALLET   = '<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji>'
E_MONEY    = '<tg-emoji emoji-id="5258204546391351475">💰</tg-emoji>'
E_CLOCK    = '<tg-emoji emoji-id="5258204546391351475">⏳</tg-emoji>'
E_DIAMOND  = '<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji>'
E_SEND     = '<tg-emoji emoji-id="5258204546391351475">📤</tg-emoji>'
E_BOLT     = '<tg-emoji emoji-id="5258204546391351475">⚡</tg-emoji>'
E_STAR     = '<tg-emoji emoji-id="5258204546391351475">⭐</tg-emoji>'
E_FIRE     = '<tg-emoji emoji-id="5258204546391351475">🔥</tg-emoji>'
E_LOCK     = '<tg-emoji emoji-id="5258204546391351475">🔒</tg-emoji>'
E_PAY      = '<tg-emoji emoji-id="5258204546391351475">💸</tg-emoji>'
E_CROSS    = '<tg-emoji emoji-id="5258204546391351475">❌</tg-emoji>'
E_WARNING  = '<tg-emoji emoji-id="5258204546391351475">⚠️</tg-emoji>'

# ══════════════════════════════════════════════════════════════════════════════
#  ХЕЛПЕРЫ ДЛЯ КНОПОК (идентично main.py)
# ══════════════════════════════════════════════════════════════════════════════

def _btn(text: str, callback_data: str, emoji_id: str = "") -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, callback_data=callback_data)
    if emoji_id:
        b.icon_custom_emoji_id = emoji_id
    return b


def _url_btn(text: str, url: str, emoji_id: str = "") -> InlineKeyboardButton:
    b = InlineKeyboardButton(text=text, url=url)
    if emoji_id:
        b.icon_custom_emoji_id = emoji_id
    return b


# ══════════════════════════════════════════════════════════════════════════════
#  CryptoPay API клиент
# ══════════════════════════════════════════════════════════════════════════════

class CryptoPayClient:
    def __init__(self, token: str, base_url: str):
        self.token    = token
        self.base_url = base_url.rstrip("/")
        self.session  = requests.Session()
        self.session.headers["Crypto-Pay-API-Token"] = token

    def _call(self, method: str, **kwargs) -> Optional[dict]:
        try:
            r = self.session.post(
                f"{self.base_url}/{method}",
                json=kwargs,
                timeout=10,
            )
            data = r.json()
            if data.get("ok"):
                return data["result"]
            logger.error("CryptoPay [%s]: %s", method, data)
            return None
        except Exception as e:
            logger.error("CryptoPay request [%s] failed: %s", method, e)
            return None

    def get_me(self) -> Optional[dict]:
        return self._call("getMe")

    def create_invoice(self, asset: str, amount: float,
                       description: str = "", payload: str = "",
                       expires_in: int = INVOICE_EXPIRE_IN) -> Optional[dict]:
        return self._call(
            "createInvoice",
            asset=asset,
            amount=str(round(amount, 8)),
            description=description,
            payload=payload,
            expires_in=expires_in,
        )

    def get_invoices(self, status: str = "paid",
                     offset: int = 0, count: int = 100) -> list:
        result = self._call("getInvoices", status=status,
                            offset=offset, count=count)
        return (result or {}).get("items", [])

    def create_check(self, asset: str, amount: float) -> Optional[dict]:
        return self._call(
            "createCheck",
            asset=asset,
            amount=str(round(amount, 8)),
        )

    def get_balance(self) -> list:
        return self._call("getBalance") or []


# ══════════════════════════════════════════════════════════════════════════════
#  FSM — состояния пользователей
# ══════════════════════════════════════════════════════════════════════════════

_states: dict = {}
_states_lock  = threading.Lock()


def _set_state(uid: int, step: str, chat_id: int = 0,
               message_id: int = 0, **extra):
    with _states_lock:
        _states[uid] = {
            "step":       step,
            "chat_id":    chat_id,
            "message_id": message_id,
            **extra,
        }


def _get_state(uid: int) -> Optional[dict]:
    with _states_lock:
        return _states.get(uid)


def _clear_state(uid: int):
    with _states_lock:
        _states.pop(uid, None)


# ══════════════════════════════════════════════════════════════════════════════
#  КЛАВИАТУРЫ
# ══════════════════════════════════════════════════════════════════════════════

def _kb_cancel_input() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(_btn("Отменить", "pay_cancel", EMOJI_CANCEL))
    return kb


def _kb_pay(pay_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(_url_btn("Оплатить через CryptoBot", pay_url, EMOJI_PAY))
    kb.add(_btn("Отменить", "pay_cancel", EMOJI_CANCEL))
    return kb


def _kb_check(check_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(_url_btn("Забрать чек в CryptoBot", check_url, EMOJI_CHECK))
    kb.add(_btn("Назад", "profile", EMOJI_BACK))
    return kb


def _kb_back_profile() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(_btn("Назад", "profile", EMOJI_BACK))
    return kb


# ══════════════════════════════════════════════════════════════════════════════
#  ТЕКСТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _t_deposit_ask() -> str:
    return (
        f"{E_WALLET} <b>Пополнение баланса</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Введите сумму в <b>{DEFAULT_ASSET}</b>:\n\n'
        f" Минимум: <b>${DEPOSIT_MIN:,.2f}</b>\n"
        f" Максимум: <b>${DEPOSIT_MAX:,.0f}</b>\n"
    )


def _t_deposit_invoice(amount: float) -> str:
    return (
        f"{E_WALLET} <b>Счёт создан!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Сумма: <b>{amount:,.2f} {DEFAULT_ASSET}</b>\n'
        f'<tg-emoji emoji-id="6030537810509828330">💎</tg-emoji> Срок действия: <b>5 минут</b>\n'
        f"проверяется <b>автоматически</b> каждые {POLL_INTERVAL} сек."
    )


def _t_deposit_success(amount: float, new_balance: float) -> str:
    return (
        f'<tg-emoji emoji-id="5258185631355378853">💎</tg-emoji> <b>Успешное пополнение!</b>\n'
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5890848474563352982">💎</tg-emoji> Зачислено: <b>+{amount:,.2f} {DEFAULT_ASSET}</b>\n'
        f'<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji> Ваш баланс: <b>${new_balance:,.2f}</b>'
    )


def _t_deposit_expired() -> str:
    return (
        f'<tg-emoji emoji-id="6030776052345737530">💎</tg-emoji> <b>Счёт истёк!</b>\n'
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Время оплаты (5 мин) истекло.\n"
        f"Создайте новый счёт и попробуйте снова."
    )


def _t_withdraw_ask(balance: float) -> str:
    return (
        f'<tg-emoji emoji-id="5258043150110301407">💎</tg-emoji> <b>Вывод средств</b>\n'
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f" Введите сумму вывода в <b>{DEFAULT_ASSET}</b>:\n\n"
        f" Минимум: <b>${WITHDRAW_MIN:,.2f}</b>\n"
        f" Максимум: <b>${WITHDRAW_MAX:,.0f}</b>\n"
    )


def _t_withdraw_done(amount: float) -> str:
    return (
        f'<tg-emoji emoji-id="6030776052345737530">💎</tg-emoji> <b>Вывод обработан!</b>\n'
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Сумма: <b>{amount:,.2f} {DEFAULT_ASSET}</b>\n'
        f"<i>Чек одноразовый — не передавайте ссылку третьим лицам!</i>"
    )


def _t_withdraw_failed() -> str:
    return (
        f'<tg-emoji emoji-id="6030776052345737530">💎</tg-emoji> <b>Ошибка вывода!</b>\n'
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="6030833407339008632">💎</tg-emoji> Не удалось создать чек.\n'
        f"Средства возвращены на баланс.\n"
        f"Попробуйте позже или обратитесь в поддержку."
    )


# ══════════════════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНАЯ: безопасное редактирование
# ══════════════════════════════════════════════════════════════════════════════

def _edit(bot: telebot.TeleBot, chat_id: int, message_id: int,
          text: str, markup=None):
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
        )
    except Exception as e:
        logger.debug("edit_message_text failed: %s", e)


# ══════════════════════════════════════════════════════════════════════════════
#  ФОНОВЫЙ ПОЛЛИНГ
# ══════════════════════════════════════════════════════════════════════════════

def _start_poll_loop(bot: telebot.TeleBot, client: CryptoPayClient):
    def loop():
        logger.info("CryptoPay poll loop started (interval=%ds)", POLL_INTERVAL)
        while True:
            try:
                _poll_once(bot, client)
            except Exception as e:
                logger.error("Poll loop error: %s", e)
            time.sleep(POLL_INTERVAL)

    t = threading.Thread(target=loop, daemon=True, name="cryptopay-poll")
    t.start()


def _poll_once(bot: telebot.TeleBot, client: CryptoPayClient):
    paid = client.get_invoices(status="paid", count=100)
    for inv in paid:
        invoice_id = int(inv["invoice_id"])
        row = db.deposit_get_by_invoice(invoice_id)
        if not row or row["status"] != "pending":
            continue

        if not db.deposit_confirm(invoice_id):
            continue

        uid    = row["uid"]
        amount = row["amount"]
        db.add_balance(uid, amount)
        new_balance = db.get_balance(uid)

        state = _get_state(uid)
        if state and state.get("step") == "deposit_waiting" \
                and state.get("invoice_id") == invoice_id:
            _edit(
                bot,
                state["chat_id"],
                state["message_id"],
                _t_deposit_success(amount, new_balance),
                _kb_back_profile(),
            )
            _clear_state(uid)
        else:
            try:
                bot.send_message(
                    uid,
                    _t_deposit_success(amount, new_balance),
                    parse_mode="HTML",
                )
            except Exception:
                pass


# ══════════════════════════════════════════════════════════════════════════════
#  ПУБЛИЧНЫЙ API — вызывается из main.py
# ══════════════════════════════════════════════════════════════════════════════

def open_deposit(bot: telebot.TeleBot, uid: int,
                 chat_id: int, message_id: int):
    _set_state(uid, "deposit_amount", chat_id=chat_id, message_id=message_id)
    _edit(bot, chat_id, message_id, _t_deposit_ask(), _kb_cancel_input())


def open_withdraw(bot: telebot.TeleBot, uid: int,
                  chat_id: int, message_id: int):
    balance = db.get_balance(uid)
    _set_state(uid, "withdraw_amount", chat_id=chat_id, message_id=message_id)
    _edit(bot, chat_id, message_id, _t_withdraw_ask(balance), _kb_cancel_input())


# ══════════════════════════════════════════════════════════════════════════════
#  РЕГИСТРАЦИЯ ХЕНДЛЕРОВ
# ══════════════════════════════════════════════════════════════════════════════

def register(bot: telebot.TeleBot):
    client = CryptoPayClient(CRYPTO_PAY_TOKEN, CRYPTO_PAY_URL)

    me = client.get_me()
    if me:
        logger.info("CryptoPay connected: %s", me.get("name", "?"))
    else:
        logger.warning("CryptoPay token invalid or network error!")

    _start_poll_loop(bot, client)

    # ── Отмена через кнопку ────────────────────────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "pay_cancel")
    def cb_pay_cancel(call):
        uid   = call.from_user.id
        state = _get_state(uid)
        _clear_state(uid)
        bot.answer_callback_query(call.id, "Отменено.")

        if state:
            import main as m
            _edit(
                bot,
                state["chat_id"],
                state["message_id"],
                m.text_profile(call.from_user),
                m.kb_profile(),
            )

    # ── Обработка ввода суммы (text FSM) ───────────────────────────────────

    @bot.message_handler(
        func=lambda msg: (
            _get_state(msg.from_user.id) is not None
            and _get_state(msg.from_user.id).get("step")
                in ("deposit_amount", "withdraw_amount")
        ),
        content_types=["text"],
    )
    def handle_amount_input(message: Message):
        uid   = message.from_user.id
        state = _get_state(uid)
        if not state:
            return

        step       = state["step"]
        chat_id    = state["chat_id"]
        message_id = state["message_id"]

        try:
            bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass

        raw = message.text.strip().replace(",", ".")
        try:
            amount = round(float(raw), 2)
        except ValueError:
            _edit(
                bot, chat_id, message_id,
                (f" Введите корректное число. Например: <code>10</code>\n\n"
                 + (_t_deposit_ask() if step == "deposit_amount"
                    else _t_withdraw_ask(db.get_balance(uid)))),
                _kb_cancel_input(),
            )
            return

        # ── ПОПОЛНЕНИЕ ────────────────────────────────────────────────────

        if step == "deposit_amount":
            if not (DEPOSIT_MIN <= amount <= DEPOSIT_MAX):
                _edit(
                    bot, chat_id, message_id,
                    (f"{E_WARNING} Сумма: от <b>${DEPOSIT_MIN:,.2f}</b> "
                     f"до <b>${DEPOSIT_MAX:,.0f}</b>.\n\n"
                     + _t_deposit_ask()),
                    _kb_cancel_input(),
                )
                return

            _edit(bot, chat_id, message_id,
                  f'<tg-emoji emoji-id="5357069174512303778">💎</tg-emoji> <b>Создаём счёт...</b>', None)

            inv = client.create_invoice(
                asset=DEFAULT_ASSET,
                amount=amount,
                description=f"Пополнение баланса (uid={uid})",
                payload=str(uid),
                expires_in=INVOICE_EXPIRE_IN,
            )

            if not inv:
                _edit(bot, chat_id, message_id,
                      f" Ошибка создания счёта. Попробуйте позже.",
                      _kb_back_profile())
                _clear_state(uid)
                return

            invoice_id = int(inv["invoice_id"])
            pay_url    = inv["pay_url"]

            dep_id = db.deposit_create(uid, invoice_id, amount, DEFAULT_ASSET)
            if dep_id is None:
                _edit(bot, chat_id, message_id,
                      f" Дублирующийся счёт. Обратитесь в поддержку.",
                      _kb_back_profile())
                _clear_state(uid)
                return

            _set_state(uid, "deposit_waiting",
                       chat_id=chat_id, message_id=message_id,
                       invoice_id=invoice_id, amount=amount)

            _edit(bot, chat_id, message_id,
                  _t_deposit_invoice(amount), _kb_pay(pay_url))

            def _expire():
                time.sleep(INVOICE_EXPIRE_IN + 2)
                s = _get_state(uid)
                if (s and s.get("step") == "deposit_waiting"
                        and s.get("invoice_id") == invoice_id):
                    db.deposit_expire(invoice_id)
                    _edit(bot, chat_id, message_id,
                          _t_deposit_expired(), _kb_back_profile())
                    _clear_state(uid)

            threading.Thread(target=_expire, daemon=True).start()

        # ── ВЫВОД ─────────────────────────────────────────────────────────

        elif step == "withdraw_amount":
            balance = db.get_balance(uid)

            if not (WITHDRAW_MIN <= amount <= WITHDRAW_MAX):
                _edit(
                    bot, chat_id, message_id,
                    (f"{E_WARNING} Сумма: от <b>${WITHDRAW_MIN:,.2f}</b> "
                     f"до <b>${WITHDRAW_MAX:,.0f}</b>.\n\n"
                     + _t_withdraw_ask(balance)),
                    _kb_cancel_input(),
                )
                return

            if balance < amount:
                _edit(
                    bot, chat_id, message_id,
                    (f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Недостаточно средств!\n'
                     f'<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji> Баланс: <b>${balance:,.2f}</b>\n\n'
                     + _t_withdraw_ask(balance)),
                    _kb_cancel_input(),
                )
                return

            if db.withdrawal_has_pending(uid):
                _edit(bot, chat_id, message_id,
                      f"{E_CLOCK} Заявка уже в обработке. Подождите.",
                      _kb_back_profile())
                _clear_state(uid)
                return

            _clear_state(uid)
            _edit(bot, chat_id, message_id,
                  f'<tg-emoji emoji-id="5357069174512303778">💎</tg-emoji> <b>Создаём чек...</b>', None)

            wid = db.withdrawal_create(uid, amount, DEFAULT_ASSET)
            if wid is None:
                _edit(bot, chat_id, message_id,
                      f" Недостаточно средств или ошибка базы данных.",
                      _kb_back_profile())
                return

            check = client.create_check(asset=DEFAULT_ASSET, amount=amount)

            if not check:
                db.withdrawal_set_failed(wid)
                _edit(bot, chat_id, message_id,
                      _t_withdraw_failed(), _kb_back_profile())
                return

            check_id  = int(check["check_id"])
            check_url = check["bot_check_url"]
            db.withdrawal_set_check(wid, check_id, check_url)

            _edit(bot, chat_id, message_id,
                  _t_withdraw_done(amount), _kb_check(check_url))
