"""
duels.py — модуль дуэлей (группа + личка, без таймаута, без БД)

Команды:
  /cubx<N> <сумма>        🎲 до 4 очков (у кого больше — очко)
  /cubtotal<N> <сумма>    🎲 N бросков, побеждает сумма
  /dartx<N> <сумма>       🎯
  /darttotal<N> <сумма>   🎯
  /basketx<N> <сумма>     🏀
  /baskettotal<N> <сумма> 🏀
  /bowlx<N> <сумма>       🎳
  /bowltotal<N> <сумма>   🎳
  /footx<N> <сумма>       ⚽
  /foottotal<N> <сумма>   ⚽

  N = 2..5
  /cancelduel — отмена (только создатель)
"""

import re
import threading
from dataclasses import dataclass, field
from typing import Optional

import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# ══════════════════════════════════════════════════════════════════════════════
#  КОНФИГ
# ══════════════════════════════════════════════════════════════════════════════

WIN_SCORE = 4

DICE_EMOJI = {
    "cub":    "🎲",
    "dart":   "🎯",
    "basket": "🏀",
    "bowl":   "🎳",
    "foot":   "⚽",
}

CMD_RE = re.compile(
    r"^/(cub|dart|basket|bowl|foot)(x|total)([2-5])(?:@\w+)?$",
    re.IGNORECASE,
)

# ══════════════════════════════════════════════════════════════════════════════
#  СТРУКТУРЫ
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Player:
    uid:      int
    name:     str
    username: str
    scores:   list = field(default_factory=list)
    points:   int  = 0

    @property
    def display(self) -> str:
        return f"@{self.username}" if self.username else self.name


@dataclass
class Game:
    chat_id:      int
    game_type:    str
    mode:         str
    rounds:       int
    bet:          float
    player1:      Player
    player2:      Optional[Player] = None
    lobby_msg:    int = 0
    game_msg:     int = 0
    # lobby | playing | finished
    state:        str = "lobby"
    # x-режим: броски текущего раунда (None = ещё не бросил)
    p1_round_val: Optional[int] = None
    p2_round_val: Optional[int] = None

# ══════════════════════════════════════════════════════════════════════════════
#  ХРАНИЛИЩЕ
# ══════════════════════════════════════════════════════════════════════════════

_lock:  threading.Lock  = threading.Lock()
_games: dict[int, Game] = {}

def _get(chat_id: int) -> Optional[Game]:
    return _games.get(chat_id)

def _set(game: Game):
    _games[game.chat_id] = game

def _del(chat_id: int):
    _games.pop(chat_id, None)

# ══════════════════════════════════════════════════════════════════════════════
#  УТИЛИТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _parse_cmd(text: str):
    parts = (text or "").split()
    if not parts:
        return None
    m = CMD_RE.match(parts[0])
    if not m:
        return None
    return m.group(1).lower(), m.group(2).lower(), int(m.group(3))

def _get_bet(text: str) -> Optional[float]:
    parts = (text or "").split()
    if len(parts) < 2:
        return None
    try:
        v = float(parts[1].replace(",", "."))
        return v if v > 0 else None
    except ValueError:
        return None

def _fmt_name(u) -> str:
    return (f"{u.first_name or ''} {u.last_name or ''}".strip()) or str(u.id)

def _score_bar(pts: int) -> str:
    return "🟢" * pts + "⚪" * (WIN_SCORE - pts)

def _kb_lobby() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⚔️ Принять вызов", callback_data="duel_join"))
    return kb

def _kb_cancel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отменить", callback_data="duel_cancel"))
    return kb

# ══════════════════════════════════════════════════════════════════════════════
#  ТЕКСТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _t_lobby(g: Game) -> str:
    e = DICE_EMOJI[g.game_type]
    mode_lbl = f"до {WIN_SCORE} очков" if g.mode == "x" else f"{g.rounds} бросков • сумма"
    return (
        f"{e} <b>Дуэль открыта!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"👤 Создатель:  <b>{g.player1.display}</b>\n"
        f"💰 Ставка:     <b>${g.bet:,.2f}</b>\n"
        f"🎮 Режим:      <b>{mode_lbl}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Нажми кнопку чтобы принять вызов!"
    )


def _t_x(g: Game) -> str:
    """
    Свободный режим: оба бросают в любом порядке.
    Раунд завершается когда оба бросили — сравниваем значения.
    """
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    rnd = len(p1.scores) + 1

    def status(player, val):
        if val is not None:
            return f"✅ бросил <b>{val}</b>"
        return f"⏳ ждём броска"

    return (
        f"{e} <b>Раунд {rnd}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 {p1.display}  {_score_bar(p1.points)}  {status(p1, g.p1_round_val)}\n"
        f"🔵 {p2.display}  {_score_bar(p2.points)}  {status(p2, g.p2_round_val)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Оба бросайте в любом порядке — ответьте на это сообщение эмодзи {e}"
    )


def _t_total(g: Game) -> str:
    """Свободный режим: каждый бросает до N раз в любом порядке."""
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    s1, s2 = sum(p1.scores), sum(p2.scores)
    done  = len(p1.scores) + len(p2.scores)
    total = g.rounds * 2

    def row(p: Player, s: int) -> str:
        vals = " · ".join(str(v) for v in p.scores) if p.scores else "—"
        left = g.rounds - len(p.scores)
        return f"{vals}  =  <b>{s}</b>  (осталось: {left})"

    return (
        f"{e} <b>Бросок {done + 1} / {total}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔴 {p1.display}:  {row(p1, s1)}\n"
        f"🔵 {p2.display}:  {row(p2, s2)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Оба бросают в любом порядке — ответьте на это сообщение эмодзи {e}"
    )


def _t_finish(g: Game, winner: Optional[Player], draw=False) -> str:
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    if draw:
        result = "🤝 <b>Ничья!</b> Ставки возвращаются."
    else:
        result = f"🏆 Победитель: <b>{winner.display}</b>!\n💵 Выигрыш: <b>${g.bet * 2:,.2f}</b>"
    if g.mode == "x":
        detail = (
            f"🔴 {p1.display}: {p1.points} очк.\n"
            f"🔵 {p2.display}: {p2.points} очк."
        )
    else:
        s1 = sum(p1.scores)
        s2 = sum(p2.scores)
        def row(p, s):
            return " + ".join(str(v) for v in p.scores) + f" = <b>{s}</b>"
        detail = (
            f"🔴 {p1.display}: {row(p1, s1)}\n"
            f"🔵 {p2.display}: {row(p2, s2)}"
        )
    return (
        f"{e} <b>Игра окончена!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{detail}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{result}"
    )

# ══════════════════════════════════════════════════════════════════════════════
#  ФИЛЬТРЫ
# ══════════════════════════════════════════════════════════════════════════════

def is_duel_command(m: Message) -> bool:
    return bool(_parse_cmd(m.text or ""))


def is_duel_dice(m: Message) -> bool:
    """
    Принимаем кубик только если:
      1. Это dice-сообщение с нужным эмодзи
      2. Игра активна
      3. Сообщение — реплай на game_msg
      4. Отправитель — один из двух участников дуэли (не посторонний)
    """
    if not m.dice:
        return False
    g = _games.get(m.chat.id)
    if not g or g.state != "playing" or not g.player2:
        return False
    if m.dice.emoji != DICE_EMOJI.get(g.game_type):
        return False
    if not m.reply_to_message or m.reply_to_message.message_id != g.game_msg:
        return False
    # ← КЛЮЧЕВАЯ ПРОВЕРКА: только участники дуэли
    uid = m.from_user.id
    if uid not in (g.player1.uid, g.player2.uid):
        return False
    return True

# ══════════════════════════════════════════════════════════════════════════════
#  РЕГИСТРАЦИЯ
# ══════════════════════════════════════════════════════════════════════════════

def register(bot: telebot.TeleBot):

    def safe_del(chat_id: int, msg_id: int):
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    def edit_game(g: Game, text: str):
        try:
            bot.edit_message_text(
                chat_id=g.chat_id,
                message_id=g.game_msg,
                text=text,
                parse_mode="HTML",
            )
        except Exception:
            pass

    def end_game(g: Game, winner: Optional[Player] = None, draw=False):
        g.state = "finished"
        safe_del(g.chat_id, g.game_msg)
        bot.send_message(g.chat_id, _t_finish(g, winner, draw), parse_mode="HTML")
        _del(g.chat_id)

    # ──────────────────────────────────────────────────────────────────────
    #  X-режим: строгая очерёдность p1 → p2 → p1 → ...
    #  p1_round_val is None  → ждём броска p1
    #  p1_round_val is not None → p1 бросил, ждём p2
    # ──────────────────────────────────────────────────────────────────────

    def _handle_x(g: Game, uid: int, val: int):
        p1, p2 = g.player1, g.player2

        if uid == p1.uid and g.p1_round_val is None:
            g.p1_round_val = val
        elif uid == p2.uid and g.p2_round_val is None:
            g.p2_round_val = val
        else:
            return  # уже бросил в этом раунде — игнор

        # Оба бросили — завершаем раунд
        if g.p1_round_val is not None and g.p2_round_val is not None:
            v1, v2 = g.p1_round_val, g.p2_round_val
            g.p1_round_val = None
            g.p2_round_val = None
            p1.scores.append(v1)
            p2.scores.append(v2)
            if v1 > v2:
                p1.points += 1
            elif v2 > v1:
                p2.points += 1
            if p1.points >= WIN_SCORE:
                end_game(g, winner=p1)
            elif p2.points >= WIN_SCORE:
                end_game(g, winner=p2)
            else:
                # Удаляем сообщение прошлого раунда, шлём новое
                safe_del(g.chat_id, g.game_msg)
                sent = bot.send_message(g.chat_id, _t_x(g), parse_mode="HTML")
                g.game_msg = sent.message_id
        else:
            # Один уже бросил — обновляем статус в текущем сообщении
            edit_game(g, _t_x(g))

    # ──────────────────────────────────────────────────────────────────────
    #  Total-режим: строгая очерёдность p1 → p2 → p1 → ...
    #  len(p1.scores) == len(p2.scores) → ход p1
    #  len(p1.scores) >  len(p2.scores) → ход p2
    # ──────────────────────────────────────────────────────────────────────

    def _handle_total(g: Game, uid: int, val: int):
        p1, p2 = g.player1, g.player2

        if len(p1.scores) == len(p2.scores):
            # Ход p1
            if uid != p1.uid:
                return
            if len(p1.scores) >= g.rounds:
                return  # p1 уже исчерпал броски (не должно быть, но страховка)
            p1.scores.append(val)
        else:
            # p1 уже бросил в этом раунде → ход p2
            if uid != p2.uid:
                return
            if len(p2.scores) >= g.rounds:
                return
            p2.scores.append(val)

        # Оба закончили все раунды?
        if len(p1.scores) == g.rounds and len(p2.scores) == g.rounds:
            s1, s2 = sum(p1.scores), sum(p2.scores)
            if s1 > s2:
                end_game(g, winner=p1)
            elif s2 > s1:
                end_game(g, winner=p2)
            else:
                end_game(g, draw=True)
        else:
            edit_game(g, _t_total(g))

    # ── Создание дуэли ─────────────────────────────────────────────────────

    @bot.message_handler(func=is_duel_command)
    def cmd_create(message: Message):
        parsed = _parse_cmd(message.text)
        if not parsed:
            return
        gtype, mode, rounds = parsed
        bet = _get_bet(message.text)
        if bet is None:
            bot.reply_to(
                message,
                f"❌ Укажи ставку. Пример: <code>/{gtype}{mode}{rounds} 100</code>",
                parse_mode="HTML",
            )
            return
        chat_id = message.chat.id
        uid     = message.from_user.id
        with _lock:
            if _get(chat_id):
                bot.reply_to(message, "❌ Уже есть активная дуэль в этом чате!")
                return
            p1   = Player(uid=uid, name=_fmt_name(message.from_user),
                          username=message.from_user.username or "")
            game = Game(chat_id=chat_id, game_type=gtype, mode=mode,
                        rounds=rounds, bet=bet, player1=p1)
            _set(game)

        sent = bot.send_message(
            chat_id,
            _t_lobby(game),
            parse_mode="HTML",
            reply_markup=_kb_lobby(),
        )
        with _lock:
            g = _get(chat_id)
            if g:
                g.lobby_msg = sent.message_id

    # ── Принятие дуэли через inline-кнопку ────────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "duel_join")
    def cb_join(call):
        chat_id = call.message.chat.id
        uid     = call.from_user.id

        with _lock:
            g = _get(chat_id)
            if not g or g.state != "lobby":
                bot.answer_callback_query(call.id, "Дуэль уже недоступна.", show_alert=True)
                return
            if uid == g.player1.uid:
                bot.answer_callback_query(call.id, "Нельзя играть самим с собой!", show_alert=True)
                return

            p2 = Player(uid=uid, name=_fmt_name(call.from_user),
                        username=call.from_user.username or "")
            g.player2 = p2
            g.state   = "playing"

        bot.answer_callback_query(call.id, "✅ Ты в игре!")

        # убираем лобби-сообщение
        safe_del(chat_id, g.lobby_msg)

        text = _t_x(g) if g.mode == "x" else _t_total(g)
        sent = bot.send_message(chat_id, text, parse_mode="HTML")
        with _lock:
            gx = _get(chat_id)
            if gx:
                gx.game_msg = sent.message_id

    # ── Отмена через inline-кнопку ─────────────────────────────────────────

    @bot.callback_query_handler(func=lambda call: call.data == "duel_cancel")
    def cb_cancel(call):
        chat_id = call.message.chat.id
        uid     = call.from_user.id
        with _lock:
            g = _get(chat_id)
            if not g:
                bot.answer_callback_query(call.id, "Нет активной дуэли.")
                return
            if g.player1.uid != uid:
                bot.answer_callback_query(call.id, "Отменить может только создатель.", show_alert=True)
                return
            _del(chat_id)

        bot.answer_callback_query(call.id)
        mid = g.game_msg or g.lobby_msg
        if mid:
            safe_del(chat_id, mid)
        bot.send_message(
            chat_id,
            f"❌ Дуэль отменена — {g.player1.display}",
            parse_mode="HTML",
        )

    # ── Броски костей ──────────────────────────────────────────────────────

    @bot.message_handler(content_types=["dice"], func=is_duel_dice)
    def handle_dice(message: Message):
        chat_id = message.chat.id
        uid     = message.from_user.id
        with _lock:
            g = _get(chat_id)
            if not g:
                return
            val = message.dice.value
            if g.mode == "x":
                _handle_x(g, uid, val)
            else:
                _handle_total(g, uid, val)

    # ── /cancelduel командой ───────────────────────────────────────────────

    @bot.message_handler(commands=["cancelduel"])
    def cmd_cancel(message: Message):
        chat_id = message.chat.id
        uid     = message.from_user.id
        with _lock:
            g = _get(chat_id)
            if not g:
                bot.reply_to(message, "❌ Нет активной дуэли.")
                return
            if g.player1.uid != uid:
                bot.reply_to(message, "❌ Отменить может только создатель.")
                return
            _del(chat_id)
        mid = g.game_msg or g.lobby_msg
        if mid:
            safe_del(chat_id, mid)
        bot.send_message(
            chat_id,
            f"❌ Дуэль отменена — {g.player1.display}",
            parse_mode="HTML",
        )
