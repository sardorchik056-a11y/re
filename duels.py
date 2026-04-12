"""
duels.py — модуль дуэлей (группа + личка, без таймаута, без БД)

Команды:
  /cubx<N> <сумма>        🎲 до N очков (у кого больше — очко)
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

# Кастомный премиум эмодзи — человечек перед именем игрока
PLAYER_ICON = '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji>'

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
    chat_id:           int
    game_type:         str
    mode:              str
    rounds:            int       # для total-режима — кол-во бросков каждого
    win_score:         int       # для x-режима — сколько очков нужно победить (= N из команды)
    bet:               float
    player1:           Player
    player2:           Optional[Player] = None
    lobby_msg:         int = 0
    game_msg:          int = 0
    # lobby | playing | finished
    state:             str = "lobby"
    # x-режим: броски текущего раунда (None = ещё не бросил)
    p1_round_val:      Optional[int] = None
    p2_round_val:      Optional[int] = None
    # Комментарий итога последнего раунда
    last_round_result: str = ""

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

def _score_bar(pts: int, win_score: int) -> str:
    """Полоска прогресса — зелёные кружки до win_score."""
    return "🟢" * pts + "⚪" * (win_score - pts)

def _kb_lobby() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕Присоедениться", callback_data="duel_join"))
    return kb

def _kb_cancel() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌Отменить", callback_data="duel_cancel"))
    return kb

# ══════════════════════════════════════════════════════════════════════════════
#  ТЕКСТЫ
# ══════════════════════════════════════════════════════════════════════════════

def _t_lobby(g: Game) -> str:
    e = DICE_EMOJI[g.game_type]
    mode_lbl = f"до {g.win_score} очков" if g.mode == "x" else f"{g.rounds} бросков • сумма"
    return (
        f"{e} <b>Игра создана!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> Игрок:  <b>{g.player1.display}</b>\n'
        f'<tg-emoji emoji-id="5904462880941545555">👤</tg-emoji> Ставка:     <b>${g.bet:,.2f}</b>\n\n'
        f"<b>{mode_lbl}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Нажми кнопку ниже чтобы присоедениться!"
    )


def _t_x(g: Game) -> str:
    """
    Очковый режим: оба бросают в любом порядке.
    Раунд завершается когда оба бросили — сравниваем значения.
    Показывает итог предыдущего раунда (ничья / кто выиграл бросок).
    """
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    rnd = len(p1.scores) + 1
    ico = PLAYER_ICON

    def status(val):
        if val is not None:
            return f"✅ бросил <b>{val}</b>"
        return "⏳ ждём броска"

    # Блок с комментарием прошлого раунда (пустой в первом раунде)
    result_line = f"\n💬 {g.last_round_result}\n\n" if g.last_round_result else "\n"

    return (
        f"{e} <b>Раунд {rnd}  |  до {g.win_score} очков!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ico} {p1.display}  {_score_bar(p1.points, g.win_score)}  {status(g.p1_round_val)}\n"
        f"{ico} {p2.display}  {_score_bar(p2.points, g.win_score)}  {status(g.p2_round_val)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
        f"{result_line}"
        f"Отправьте {e} — в ответ на это сообщение!"
    )


def _t_total(g: Game) -> str:
    """
    Суммарный режим: каждый бросает N раз в любом порядке, без очереди.
    Каждый игрок сам решает когда бросить — хоть все N сразу.
    """
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    s1, s2 = sum(p1.scores), sum(p2.scores)
    ico = PLAYER_ICON

    def row(p: Player, s: int) -> str:
        vals = " + ".join(str(v) for v in p.scores) if p.scores else "—"
        left = g.rounds - len(p.scores)
        done_mark = " ✅" if left == 0 else f"  (осталось: {left})"
        return f"{vals}  =  <b>{s}</b>{done_mark}"

    return (
        f"{e} <b>Суммарный режим  |  {g.rounds} бросков каждому</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{ico} {p1.display}:  {row(p1, s1)}\n"
        f"{ico} {p2.display}:  {row(p2, s2)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Отправьте {e} — в ответ на это сообщение!"
    )


def _t_finish(g: Game, winner: Optional[Player], draw=False) -> str:
    e = DICE_EMOJI[g.game_type]
    p1, p2 = g.player1, g.player2
    ico = PLAYER_ICON
    if draw:
        result = "🤝 <b>Ничья!</b> Ставки возвращаются."
    else:
        result = f'<tg-emoji emoji-id="5461151367559141950">👤</tg-emoji> Победитель: <b>{winner.display}</b>!\n<tg-emoji emoji-id="5890848474563352982">👤</tg-emoji> Выигрыш: <b>${g.bet * 2:,.2f}</b>'
    if g.mode == "x":
        detail = (
            f"{ico} {p1.display}: {p1.points} очк.\n"
            f"{ico} {p2.display}: {p2.points} очк."
        )
    else:
        s1 = sum(p1.scores)
        s2 = sum(p2.scores)
        def row(p, s):
            return " + ".join(str(v) for v in p.scores) + f" = <b>{s}</b>"
        detail = (
            f"{ico} {p1.display}: {row(p1, s1)}\n"
            f"{ico} {p2.display}: {row(p2, s2)}"
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
    if not m.dice:
        return False
    g = _games.get(m.chat.id)
    if not g or g.state != "playing" or not g.player2:
        return False
    if m.dice.emoji != DICE_EMOJI.get(g.game_type):
        return False
    if not m.reply_to_message or m.reply_to_message.message_id != g.game_msg:
        return False
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
    #  X-режим: оба бросают в любом порядке, раунд закрывается когда оба
    #  бросили. После каждого раунда показывается итоговый комментарий.
    #  Победа — первый кто набрал g.win_score очков (= N из команды)
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
            rnd_num = len(p1.scores)

            if v1 > v2:
                p1.points += 1
                g.last_round_result = (
                    f"Раунд {rnd_num}: {p1.display} выиграл бросок "
                    f"({v1} vs {v2}) — счёт {p1.points}:{p2.points}"
                )
            elif v2 > v1:
                p2.points += 1
                g.last_round_result = (
                    f"Раунд {rnd_num}: {p2.display} выиграл бросок "
                    f"({v2} vs {v1}) — счёт {p1.points}:{p2.points}"
                )
            else:
                g.last_round_result = (
                    f"Раунд {rnd_num}: ничья ({v1} = {v2}) — "
                    f"счёт прежний {p1.points}:{p2.points}"
                )

            if p1.points >= g.win_score:
                end_game(g, winner=p1)
            elif p2.points >= g.win_score:
                end_game(g, winner=p2)
            else:
                safe_del(g.chat_id, g.game_msg)
                sent = bot.send_message(g.chat_id, _t_x(g), parse_mode="HTML")
                g.game_msg = sent.message_id
        else:
            edit_game(g, _t_x(g))

    # ──────────────────────────────────────────────────────────────────────
    #  Total-режим: БЕЗ очереди — каждый бросает в любой момент, хоть все
    #  N бросков подряд не дожидаясь соперника. Игра кончается когда оба
    #  исчерпали все свои броски.
    # ──────────────────────────────────────────────────────────────────────

    def _handle_total(g: Game, uid: int, val: int):
        p1, p2 = g.player1, g.player2

        if uid == p1.uid:
            if len(p1.scores) >= g.rounds:
                return  # p1 уже использовал все броски
            p1.scores.append(val)
        elif uid == p2.uid:
            if len(p2.scores) >= g.rounds:
                return  # p2 уже использовал все броски
            p2.scores.append(val)
        else:
            return

        # Оба закончили все броски — подводим итог
        if len(p1.scores) == g.rounds and len(p2.scores) == g.rounds:
            s1, s2 = sum(p1.scores), sum(p2.scores)
            if s1 > s2:
                end_game(g, winner=p1)
            elif s2 > s1:
                end_game(g, winner=p2)
            else:
                end_game(g, draw=True)
        else:
            # Кто-то ещё не закончил — обновляем таблицу
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
            game = Game(
                chat_id=chat_id,
                game_type=gtype,
                mode=mode,
                rounds=rounds,
                win_score=rounds,
                bet=bet,
                player1=p1,
            )
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
