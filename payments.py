"""
payments.py — пополнение и вывод через @CryptoBot (CryptoPay API)

Пополнение:
  Пользователь вводит сумму → бот создаёт invoice через CryptoPay →
  присылает кнопку-ссылку → CryptoBot присылает webhook/polling уведомление →
  бот подтверждает оплату атомарно через deposit_confirm() → зачисляет баланс.

  Защита от дублей:
    • invoice_id уникален в таблице deposits (UNIQUE constraint)
    • deposit_confirm() использует UPDATE ... WHERE status='pending'
      (вернёт rowcount=0 если уже обработан)
    • Фоновый поллинг проверяет только 'pending' счета

Вывод:
  Пользователь вводит сумму → БД атомарно списывает баланс + создаёт заявку →
  бот создаёт чек через CryptoPay → шлёт ссылку пользователю.
  При ошибке API — деньги возвращаются через withdrawal_set_failed().

Команды (только в ЛС бота):
  /deposit  — начать пополнение
  /withdraw — начать вывод
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
#  КОНФИГ — заполни своими данными
# ══════════════════════════════════════════════════════════════════════════════

CRYPTO_PAY_TOKEN = "552018:AAmEzVekZI0E1Qcpi0ccOxbkOMk01J2Qs2n"   # Получить у @CryptoBot → /pay
CRYPTO_PAY_URL   = "https://pay.crypt.bot/api"  # mainnet
# CRYPTO_PAY_URL = "https://testnet-pay.crypt.bot/api"  # testnet для теста

# Валюта по умолчанию (поддерживаемые: USDT, TON, BTC, ETH, BNB, TRX, USDC)
DEFAULT_ASSET = "USDT"

# Минимальные и максимальные суммы (в USD-эквиваленте)
DEPOSIT_MIN  = 0.1
DEPOSIT_MAX  = 10_000.0
WITHDRAW_MIN = 1.0
WITHDRAW_MAX = 10_000.0

# Интервал фонового поллинга оплаченных счетов (секунды)
POLL_INTERVAL = 3

# Срок жизни инвойса (секунды, CryptoBot поддерживает до 1 часа = 3600)
INVOICE_EXPIRE_IN = 3600

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
                timeout=15,
            )
            data = r.json()
            if data.get("ok"):
                return data["result"]
            logger.error("CryptoPay error [%s]: %s", method, data)
            return None
        except Exception as e:
            logger.error("CryptoPay request failed [%s]: %s", method, e)
            return None

    def get_me(self) -> Optional[dict]:
        return self._call("getMe")

    def create_invoice(
        self,
        asset: str,
        amount: float,
        description: str = "",
        payload: str = "",
        expires_in: int = INVOICE_EXPIRE_IN,
    ) -> Optional[dict]:
        """Создаёт счёт на оплату. Возвращает dict с полями invoice_id, pay_url и др."""
        return self._call(
            "createInvoice",
            asset=asset,
            amount=str(round(amount, 8)),
            description=description,
            payload=payload,
            expires_in=expires_in,
        )

    def get_invoices(
        self,
        status: str = "paid",
        offset: int = 0,
        count: int = 100,
    ) -> list:
        """Возвращает список инвойсов с заданным статусом."""
        result = self._call(
            "getInvoices",
            status=status,
            offset=offset,
            count=count,
        )
        if result is None:
            return []
        return result.get("items", [])

    def create_check(
        self,
        asset: str,
        amount: float,
    ) -> Optional[dict]:
        """
        Создаёт чек (check) — пользователь получает ссылку и активирует его.
        Возвращает dict с полями check_id, bot_check_url и др.
        """
        return self._call(
            "createCheck",
            asset=asset,
            amount=str(round(amount, 8)),
        )

    def get_balance(self) -> list:
        """Возвращает список балансов кошелька приложения."""
        result = self._call("getBalance")
        return result if result else []


# ══════════════════════════════════════════════════════════════════════════════
#  Состояния FSM (простой in-memory словарь)
# ══════════════════════════════════════════════════════════════════════════════

# {uid: {"step": "deposit_amount" | "withdraw_amount", ...}}
_states: dict = {}
_states_lock  = threading.Lock()

def _set_state(uid: int, step: str, **extra):
    with _states_lock:
        _states[uid] = {"step": step, **extra}

def _get_state(uid: int) -> Optional[dict]:
    with _states_lock:
        return _states.get(uid)

def _clear_state(uid: int):
    with _states_lock:
        _states.pop(uid, None)


# ══════════════════════════════════════════════════════════════════════════════
#  ТЕКСТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _t_deposit_ask() -> str:
    return (
        f"💳 <b>Пополнение баланса</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Введите сумму пополнения в <b>USDT</b>:\n\n"
        f"• Минимум: <b>${DEPOSIT_MIN:,.2f}</b>\n"
        f"• Максимум: <b>${DEPOSIT_MAX:,.0f}</b>\n\n"
        f"Пример: <code>50</code> или <code>100.50</code>"
    )


def _t_deposit_created(amount: float, pay_url: str) -> str:
    return (
        f"💳 <b>Счёт создан!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Сумма: <b>{amount:,.2f} {DEFAULT_ASSET}</b>\n\n"
        f"Нажмите кнопку ниже и оплатите счёт через @CryptoBot.\n"
        f"После оплаты баланс зачислится <b>автоматически</b> в течение {POLL_INTERVAL} сек."
    )


def _t_deposit_success(amount: float) -> str:
    return (
        f"✅ <b>Пополнение прошло!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 Зачислено: <b>+{amount:,.2f} {DEFAULT_ASSET}</b>\n"
        f"💎 Проверь баланс: /start → Профиль"
    )


def _t_withdraw_ask(balance: float) -> str:
    return (
        f"📤 <b>Вывод средств</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Ваш баланс: <b>${balance:,.2f}</b>\n\n"
        f"Введите сумму вывода в <b>USDT</b>:\n\n"
        f"• Минимум: <b>${WITHDRAW_MIN:,.2f}</b>\n"
        f"• Максимум: <b>${WITHDRAW_MAX:,.0f}</b>\n\n"
        f"Пример: <code>50</code> или <code>100.50</code>"
    )


def _t_withdraw_processing() -> str:
    return (
        f"⏳ <b>Создаём чек...</b>\n"
        f"Пожалуйста подождите несколько секунд."
    )


def _t_withdraw_done(amount: float, check_url: str) -> str:
    return (
        f"✅ <b>Чек создан!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"💸 Сумма: <b>{amount:,.2f} {DEFAULT_ASSET}</b>\n\n"
        f"Перейдите по ссылке ниже чтобы активировать чек в @CryptoBot:"
    )


def _t_withdraw_failed() -> str:
    return (
        f"❌ <b>Ошибка вывода!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Не удалось создать чек. Средства возвращены на ваш баланс.\n"
        f"Попробуйте позже или обратитесь в поддержку."
    )


def _kb_pay(pay_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💳 Оплатить через CryptoBot", url=pay_url))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel"))
    return kb


def _kb_check(check_url: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💸 Получить чек", url=check_url))
    return kb


def _kb_cancel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="pay_cancel"))
    return kb


# ══════════════════════════════════════════════════════════════════════════════
#  ФОНОВЫЙ ПОЛЛИНГ оплаченных инвойсов
# ══════════════════════════════════════════════════════════════════════════════

def _start_poll_loop(bot: telebot.TeleBot, client: CryptoPayClient):
    """Запускает фоновый поток, который каждые POLL_INTERVAL сек проверяет оплаченные счета."""
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
    """
    Получает последние 100 оплаченных инвойсов и обрабатывает те,
    которые есть в нашей БД и ещё pending.
    """
    paid_invoices = client.get_invoices(status="paid", count=100)
    for inv in paid_invoices:
        invoice_id = int(inv["invoice_id"])
        row = db.deposit_get_by_invoice(invoice_id)
        if not row:
            continue  # не наш инвойс
        if row["status"] != "pending":
            continue  # уже обработан

        # Атомарно переводим в статус paid
        changed = db.deposit_confirm(invoice_id)
        if not changed:
            continue  # другой поток уже обработал

        uid    = row["uid"]
        amount = row["amount"]
        db.add_balance(uid, amount)

        try:
            bot.send_message(uid, _t_deposit_success(amount), parse_mode="HTML")
        except Exception:
            pass  # пользователь заблокировал бота


# ══════════════════════════════════════════════════════════════════════════════
#  РЕГИСТРАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def register(bot: telebot.TeleBot):
    client = CryptoPayClient(CRYPTO_PAY_TOKEN, CRYPTO_PAY_URL)

    # Проверяем токен при старте
    me = client.get_me()
    if me:
        logger.info("CryptoPay connected: %s", me.get("name", "?"))
    else:
        logger.warning("CryptoPay token invalid or network error!")

    # Запускаем фоновый поллинг
    _start_poll_loop(bot, client)

    # ── Хелпер: только ЛС ──────────────────────────────────────────────────

    def _require_private(message: Message) -> bool:
        if message.chat.type != "private":
            bot.reply_to(
                message,
                "💳 Пополнение и вывод доступны только в личных сообщениях с ботом.",
            )
            return False
        return True

    # ═══════════════════════════════════════════════════════════════════════
    #  /deposit — начать пополнение
    # ═══════════════════════════════════════════════════════════════════════

    @bot.message_handler(commands=["deposit"])
    def cmd_deposit(message: Message):
        if not _require_private(message):
            return
        uid = message.from_user.id
        db.ensure_user(uid, message.from_user.username or "",
                       f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip())
        _set_state(uid, "deposit_amount")
        bot.send_message(uid, _t_deposit_ask(), parse_mode="HTML", reply_markup=_kb_cancel())

    # ═══════════════════════════════════════════════════════════════════════
    #  /withdraw — начать вывод
    # ═══════════════════════════════════════════════════════════════════════

    @bot.message_handler(commands=["withdraw"])
    def cmd_withdraw(message: Message):
        if not _require_private(message):
            return
        uid     = message.from_user.id
        db.ensure_user(uid, message.from_user.username or "",
                       f"{message.from_user.first_name or ''} {message.from_user.last_name or ''}".strip())
        balance = db.get_balance(uid)
        _set_state(uid, "withdraw_amount")
        bot.send_message(uid, _t_withdraw_ask(balance), parse_mode="HTML", reply_markup=_kb_cancel())

    # ═══════════════════════════════════════════════════════════════════════
    #  Отмена через кнопку
    # ═══════════════════════════════════════════════════════════════════════

    @bot.callback_query_handler(func=lambda call: call.data == "pay_cancel")
    def cb_pay_cancel(call):
        uid = call.from_user.id
        _clear_state(uid)
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        bot.answer_callback_query(call.id, "Отменено.")
        bot.send_message(uid, "❌ Операция отменена.")

    # ═══════════════════════════════════════════════════════════════════════
    #  Обработка ввода суммы (FSM)
    # ═══════════════════════════════════════════════════════════════════════

    @bot.message_handler(
        func=lambda m: (
            m.chat.type == "private"
            and _get_state(m.from_user.id) is not None
        ),
        content_types=["text"],
    )
    def handle_payment_input(message: Message):
        uid   = message.from_user.id
        state = _get_state(uid)
        if state is None:
            return

        step = state["step"]

        # Парсим сумму
        try:
            amount = round(float(message.text.strip().replace(",", ".")), 2)
        except ValueError:
            bot.send_message(uid, "❌ Введите корректное число. Например: <code>100</code>", parse_mode="HTML")
            return

        # ── Пополнение ────────────────────────────────────────────────────

        if step == "deposit_amount":
            if not (DEPOSIT_MIN <= amount <= DEPOSIT_MAX):
                bot.send_message(
                    uid,
                    f"❌ Сумма должна быть от <b>${DEPOSIT_MIN:,.2f}</b> до <b>${DEPOSIT_MAX:,.0f}</b>.",
                    parse_mode="HTML",
                )
                return

            _clear_state(uid)

            # Создаём invoice в CryptoBot
            inv = client.create_invoice(
                asset=DEFAULT_ASSET,
                amount=amount,
                description=f"Пополнение баланса (uid={uid})",
                payload=str(uid),
                expires_in=INVOICE_EXPIRE_IN,
            )

            if not inv:
                bot.send_message(uid, "❌ Ошибка создания счёта. Попробуйте позже.")
                return

            invoice_id = int(inv["invoice_id"])
            pay_url    = inv["pay_url"]

            # Сохраняем в БД (защита от дублей через UNIQUE invoice_id)
            dep_id = db.deposit_create(uid, invoice_id, amount, DEFAULT_ASSET)
            if dep_id is None:
                # invoice_id уже есть — крайне маловероятно, но обрабатываем
                bot.send_message(uid, "❌ Дублирующийся счёт. Обратитесь в поддержку.")
                return

            bot.send_message(
                uid,
                _t_deposit_created(amount, pay_url),
                parse_mode="HTML",
                reply_markup=_kb_pay(pay_url),
            )

        # ── Вывод ─────────────────────────────────────────────────────────

        elif step == "withdraw_amount":
            if not (WITHDRAW_MIN <= amount <= WITHDRAW_MAX):
                bot.send_message(
                    uid,
                    f"❌ Сумма должна быть от <b>${WITHDRAW_MIN:,.2f}</b> до <b>${WITHDRAW_MAX:,.0f}</b>.",
                    parse_mode="HTML",
                )
                return

            balance = db.get_balance(uid)
            if balance < amount:
                bot.send_message(
                    uid,
                    f"❌ Недостаточно средств!\n💎 Ваш баланс: <b>${balance:,.2f}</b>",
                    parse_mode="HTML",
                )
                return

            # Проверяем нет ли уже активной заявки
            if db.withdrawal_has_pending(uid):
                bot.send_message(
                    uid,
                    "⏳ У вас уже есть заявка на вывод в обработке. Подождите.",
                )
                return

            _clear_state(uid)

            # Атомарно списываем баланс + создаём заявку
            wid = db.withdrawal_create(uid, amount, DEFAULT_ASSET)
            if wid is None:
                bot.send_message(uid, "❌ Недостаточно средств или ошибка базы данных.")
                return

            proc_msg = bot.send_message(uid, _t_withdraw_processing(), parse_mode="HTML")

            # Создаём чек в CryptoBot
            check = client.create_check(asset=DEFAULT_ASSET, amount=amount)

            if not check:
                # Ошибка API — возвращаем деньги
                db.withdrawal_set_failed(wid)
                try:
                    bot.delete_message(uid, proc_msg.message_id)
                except Exception:
                    pass
                bot.send_message(uid, _t_withdraw_failed(), parse_mode="HTML")
                return

            check_id  = int(check["check_id"])
            check_url = check["bot_check_url"]

            db.withdrawal_set_check(wid, check_id, check_url)

            try:
                bot.delete_message(uid, proc_msg.message_id)
            except Exception:
                pass

            bot.send_message(
                uid,
                _t_withdraw_done(amount, check_url),
                parse_mode="HTML",
                reply_markup=_kb_check(check_url),
            )
