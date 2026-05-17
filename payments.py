import threading
import time
import logging
from typing import Optional

import requests
import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import database as db

logger = logging.getLogger(__name__)                                                                       

CRYPTO_PAY_TOKEN  = "582363:AALEf7JOugnrQyrkMHzH5UrO7pdOjjYnTQy"
CRYPTO_PAY_URL    = "https://pay.crypt.bot/api"
                                                       

DEFAULT_ASSET     = "USDT"

DEPOSIT_MIN       = 0.10
DEPOSIT_MAX       = 10_000.0
WITHDRAW_MIN      = 0.10
WITHDRAW_MAX      = 10_000.0

POLL_INTERVAL     = 3
INVOICE_EXPIRE_IN = 300


EMOJI_PAY      = "5260730055880876557"                    
EMOJI_CANCEL   = "6039539366177541657"                    
EMOJI_BACK     = "6039539366177541657"                 
EMOJI_CHECK    = "5258185631355378853"                        

# Custom emoji for rubles instead of dollar sign
EMOJI_RUBLES = '<tg-emoji emoji-id="5377746319601324795">💰</tg-emoji>'

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


                                                                                
         
                                                                                

def _t_deposit_ask() -> str:
    return (
        f"{E_WALLET} <b>Пополнение баланса</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Введите сумму в <b>{DEFAULT_ASSET}</b>:\n\n'
        f" Минимум: {EMOJI_RUBLES}<b>{DEPOSIT_MIN:,.2f}</b>\n"
        f" Максимум: {EMOJI_RUBLES}<b>{DEPOSIT_MAX:,.0f}</b>\n"
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
        f'<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji> Ваш баланс: {EMOJI_RUBLES}<b>{new_balance:,.2f}</b>'
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
        f" Минимум: {EMOJI_RUBLES}<b>{WITHDRAW_MIN:,.2f}</b>\n"
        f" Максимум: {EMOJI_RUBLES}<b>{WITHDRAW_MAX:,.0f}</b>\n"
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
        f"<small>Попробуйте позже или свяжитесь со спортом.</small>"
    )


def _edit(bot: telebot.TeleBot, chat_id: int, message_id: int,
          text: str, markup):
    try:
        bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            reply_markup=markup,
            parse_mode="HTML",
        )
    except Exception:
        pass


def _start_poll_loop(bot: telebot.TeleBot, client: CryptoPayClient):
    def _poll():
        while True:
            time.sleep(POLL_INTERVAL)
            try:
                invoices = client.get_invoices(status="paid")
                for inv in invoices:
                    invoice_id = int(inv["invoice_id"])
                    dep = db.deposit_get(invoice_id)
                    if not dep or dep["status"] != "pending":
                        continue

                    uid     = dep["uid"]
                    amount  = dep["amount"]
                    state   = _get_state(uid)

                    if state and state.get("step") == "deposit_waiting" and state.get("invoice_id") == invoice_id:
                        db.deposit_mark_paid(invoice_id)
                        db.add_balance(uid, amount)
                        new_balance = db.get_balance(uid)

                        if state:
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
            except Exception as e:
                logger.error("Poll loop error: %s", e)

    threading.Thread(target=_poll, daemon=True).start()


                                                                                
                                        
                                                                                

def open_deposit(bot: telebot.TeleBot, uid: int,
                 chat_id: int, message_id: int):
    _set_state(uid, "deposit_amount", chat_id=chat_id, message_id=message_id)
    _edit(bot, chat_id, message_id, _t_deposit_ask(), _kb_cancel_input())


def open_withdraw(bot: telebot.TeleBot, uid: int,
                  chat_id: int, message_id: int):
    balance = db.get_balance(uid)
    _set_state(uid, "withdraw_amount", chat_id=chat_id, message_id=message_id)
    _edit(bot, chat_id, message_id, _t_withdraw_ask(balance), _kb_cancel_input())


                                                                                
                        
                                                                                

def register(bot: telebot.TeleBot):
    client = CryptoPayClient(CRYPTO_PAY_TOKEN, CRYPTO_PAY_URL)

    me = client.get_me()
    if me:
        logger.info("CryptoPay connected: %s", me.get("name", "?"))
    else:
        logger.warning("CryptoPay token invalid or network error!")

    _start_poll_loop(bot, client)

                                                                             

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

                                                                            

        if step == "deposit_amount":
            if not (DEPOSIT_MIN <= amount <= DEPOSIT_MAX):
                _edit(
                    bot, chat_id, message_id,
                    (f"{E_WARNING} Сумма: от {EMOJI_RUBLES}<b>{DEPOSIT_MIN:,.2f}</b> "
                     f"до {EMOJI_RUBLES}<b>{DEPOSIT_MAX:,.0f}</b>.\n\n"
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

                                                                            

        elif step == "withdraw_amount":
            balance = db.get_balance(uid)

            if not (WITHDRAW_MIN <= amount <= WITHDRAW_MAX):
                _edit(
                    bot, chat_id, message_id,
                    (f"{E_WARNING} Сумма: от {EMOJI_RUBLES}<b>{WITHDRAW_MIN:,.2f}</b> "
                     f"до {EMOJI_RUBLES}<b>{WITHDRAW_MAX:,.0f}</b>.\n\n"
                     + _t_withdraw_ask(balance)),
                    _kb_cancel_input(),
                )
                return

            if balance < amount:
                _edit(
                    bot, chat_id, message_id,
                    (f'<tg-emoji emoji-id="5904462880941545555">💎</tg-emoji> Недостаточно средств!\n'
                     f'<tg-emoji emoji-id="5258204546391351475">💎</tg-emoji> Баланс: {EMOJI_RUBLES}<b>{balance:,.2f}</b>\n\n'
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
