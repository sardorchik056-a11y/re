import re
import threading
from typing import Optional

import telebot
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

import database as db
                                                               

BET_MIN = 0.10
BET_MAX = 10_000.0

DICE_EMOJI = {
    "cub":    "🎲",
    "dart":   "🎯",
    "basket": "🏀",
    "bowl":   "🎳",
    "foot":   "⚽",
}

EMOJI_TO_TYPE = {v: k for k, v in DICE_EMOJI.items()}

CMD_RE = re.compile(
    r"^/(cub|dart|basket|bowl|foot)(x|total)([2-5])(?:@\w+)?$",
    re.IGNORECASE,
)

PLAYER_ICON = '<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji>'

NUM_EMOJI = {
    1: '<tg-emoji emoji-id="5382322671679708881">1️⃣</tg-emoji>',
    2: '<tg-emoji emoji-id="5381990043642502553">2️⃣</tg-emoji>',
    3: '<tg-emoji emoji-id="5381879959335738545">3️⃣</tg-emoji>',
    4: '<tg-emoji emoji-id="5382054253403577563">4️⃣</tg-emoji>',
    5: '<tg-emoji emoji-id="5391197405553107640">5️⃣</tg-emoji>',
    6: '<tg-emoji emoji-id="5390966190283694453">6️⃣</tg-emoji>',
}

# Custom emoji for rubles instead of dollar sign
EMOJI_RUBLES = '<tg-emoji emoji-id="5377746319601324795">💰</tg-emoji>'

_lock = threading.Lock()

                                                                                
          
                                                                                

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
        v = round(float(parts[1].replace(",", ".")), 2)
        if BET_MIN <= v <= BET_MAX:
            return v
        return None
    except ValueError:
        return None


def _fmt_name(u) -> str:
    return (f"{u.first_name or ''} {u.last_name or ''}".strip()) or str(u.id)


def _display(uid: int, name: str, username: str) -> str:
    return f"@{username}" if username else name


def _score_bar(pts: int, win_score: int) -> str:
    return "🟢" * pts + "⚪" * (win_score - pts)


def _kb_lobby(game_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("➕ Присоединиться", callback_data=f"duel_join:{game_id}"))
    return kb


def _kb_cancel_lobby(game_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отменить", callback_data=f"duel_cancel:{game_id}"))
    return kb


def _build_game_url(sent_msg) -> str:
    chat_id = sent_msg.chat.id
    msg_id  = sent_msg.message_id
    if sent_msg.chat.username:
        return f"https://t.me/{sent_msg.chat.username}/{msg_id}"
    clean_id = str(abs(chat_id))
    if clean_id.startswith("100"):
        clean_id = clean_id[3:]
    return f"https://t.me/c/{clean_id}/{msg_id}"

                                                                                
         
                                                                                

def _t_lobby(g, p1_display: str) -> str:
    e = DICE_EMOJI[g["game_type"]]
    if g["mode"] == "x":
        mode_lbl = f"до {g['win_score']} очков"
    else:
        mode_lbl = f"{g['rounds']} бросков • сумма"
    return (
        f"{e} <b>Игра создана!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f'<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> Игрок:  <b>{p1_display}</b>\n'
        f'{EMOJI_RUBLES} Ставка:     <b>{g["bet"]:,.2f}</b>\n'
        f" <b>{mode_lbl}</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"<b>Нажми кнопку ниже чтобы присоедениться!</b>"
    )


def _t_x(g, p1_display: str, p2_display: str,
          p1_pts: int, p2_pts: int,
          p1_round_val, p2_round_val,
          last_round_result: str, rnd: int) -> str:
    e = DICE_EMOJI[g["game_type"]]
    ws = g["win_score"]

    def status(val):
        if val is not None:
            return NUM_EMOJI.get(val, str(val))
        return "⏳"

    result_line = f"\n {last_round_result}\n\n" if last_round_result else "\n"
    return (
        f"{e} <b>Раунд {rnd}  |  до {ws} очков!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{PLAYER_ICON} {p1_display}  {_score_bar(p1_pts, ws)}  {status(p1_round_val)}\n"
        f"{PLAYER_ICON} {p2_display}  {_score_bar(p2_pts, ws)}  {status(p2_round_val)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━"
        f"{result_line}"
        f"Отправьте {e} — в ответ на это сообщение!"
    )


def _calculate_total_score(scores: list, rounds: int) -> int:
    """
    Новая логика расчёта для режима total:
    - 2 броска: просто сумма (старая логика)
    - 3-4 броска: сумма всех кроме последнего * множитель последнего
    - 5 бросков: сумма всех кроме последнего * множитель последнего
    
    Примеры:
    - 2 броска [1, 3]: 1 + 3 = 4
    - 3 броска [1, 3, 4]: (1 + 3) * 4 = 16
    - 4 броска [3, 5, 1, 3]: (3 + 5 + 1) * 3 = 27
    - 5 бросков [2, 1, 4, 3, 2]: (2 + 1 + 4 + 3) * 2 = 20
    """
    if not scores:
        return 0
    
    if len(scores) == 2:
        # При 2 бросках - просто сумма
        return sum(scores)
    else:
        # При 3 и более бросках - сумма всех кроме последнего, умноженная на последний
        sum_except_last = sum(scores[:-1])
        last_multiplier = scores[-1]
        return sum_except_last * last_multiplier


def _t_total(g, p1_display: str, p2_display: str,
             p1_scores: list, p2_scores: list) -> str:
    e = DICE_EMOJI[g["game_type"]]
    rounds = g["rounds"]

    def row(p_display: str, scores: list) -> str:
        if not scores:
            return f"{PLAYER_ICON} {p_display}:  \u2014  0/{rounds}"
        if len(scores) == rounds:
            final_score = _calculate_total_score(scores, rounds)
            if rounds == 2:
                vals = " + ".join(str(v) for v in scores)
                formula = f"{vals} = <b>{final_score}</b>"
            else:
                sum_part = " + ".join(str(v) for v in scores[:-1])
                last = scores[-1]
                formula = f"({sum_part}) \u00d7 {last} = <b>{final_score}</b>"
            return f"{PLAYER_ICON} {p_display}:  {formula} \u2705"
        else:
            vals = " + ".join(str(v) for v in scores)
            return f"{PLAYER_ICON} {p_display}:  {vals}  {len(scores)}/{rounds}"

    return (
        f"{e} <b>Сумма  |  {rounds} броска</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{row(p1_display, p1_scores)}\n"
        f"{row(p2_display, p2_scores)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"Отправьте {e} — в ответ на это сообщение!"
    )


def _t_finish(g, winner_display: Optional[str],
              p1_display: str, p2_display: str,
              p1_scores: list, p2_scores: list,
              p1_pts: int, p2_pts: int,
              draw=False) -> str:
    e = DICE_EMOJI[g["game_type"]]
    if draw:
        result = "🤝 <b>Ничья!</b> Ставки возвращаются."
    else:
        result = (
            f'<tg-emoji emoji-id="5461151367559141950">👤</tg-emoji> Победитель: <b>{winner_display}</b>!\n'
            f'{EMOJI_RUBLES} Выигрыш: <b>{g["bet"] * 2:,.2f}</b>'
        )
    if g["mode"] == "x":
        detail = (
            f"{PLAYER_ICON} {p1_display}: {p1_pts} очк.\n"
            f"{PLAYER_ICON} {p2_display}: {p2_pts} очк."
        )
    else:
        def row(p_d, scores):
            final_score = _calculate_total_score(scores, g["rounds"])
            if g["rounds"] == 2:
                return " + ".join(str(v) for v in scores) + f" = <b>{final_score}</b>"
            else:
                sum_part = " + ".join(str(v) for v in scores[:-1])
                last = scores[-1]
                return f"({sum_part}) × {last} = <b>{final_score}</b>"
        detail = (
            f"{PLAYER_ICON} {p1_display}: {row(p1_display, p1_scores)}\n"
            f"{PLAYER_ICON} {p2_display}: {row(p2_display, p2_scores)}"
        )
    return (
        f"{e} <b>Игра окончена!</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{detail}\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"{result}"
    )


def _t_my_games(games: list) -> str:
    if not games:
        return "📋 <b>Активных дуэлей нет.</b>"
    lines = ["📋 <b>Твои активные дуэли:</b>\n━━━━━━━━━━━━━━━━━━━━━"]
    for g in games:
        e = DICE_EMOJI.get(g["game_type"], "🎲")
        mode = "до очков" if g["mode"] == "x" else "сумма"
        state = "👥 lobby" if g["state"] == "lobby" else "⚔️ играем"
        lines.append(
            f"{e} ID:{g['id']}  {g['bet']:,.2f}  {g['rounds']}р/{mode}  {state}"
        )
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    return "\n".join(lines)


                                                                                
          
                                                                                

def is_duel_command(m: Message) -> bool:
    return bool(_parse_cmd(m.text or ""))


def is_duel_dice(m: Message) -> bool:
    if not m.dice:
        return False
    if not m.reply_to_message:
        return False
    gtype = EMOJI_TO_TYPE.get(m.dice.emoji)
    if gtype is None:
        return False
    games = db.game_get_by_chat(m.chat.id)
    playing = [g for g in games if g["state"] == "playing"
               and g["game_msg"] == m.reply_to_message.message_id
               and g["game_type"] == gtype]
    if not playing:
        return False
    g = playing[0]
    uid = m.from_user.id
    return uid in (g["p1_uid"], g["p2_uid"])

                                                                                
              
                                                                                

def register(bot: telebot.TeleBot):

                                                                             

    def safe_del(chat_id: int, msg_id: int):
        if not msg_id:
            return
        try:
            bot.delete_message(chat_id, msg_id)
        except Exception:
            pass

    def edit_game_msg(chat_id: int, msg_id: int, text: str):
        try:
            bot.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, parse_mode="HTML",
            )
        except Exception:
            pass

    def _load_displays(g) -> tuple:
        p1_un = db.get_username_by_uid(g["p1_uid"]) or ""
        p1_row = db.get_user_row(g["p1_uid"])
        p1_name = p1_row["first_name"] if p1_row else str(g["p1_uid"])
        p1_d = f"@{p1_un}" if p1_un else p1_name

        if g["p2_uid"]:
            p2_un = db.get_username_by_uid(g["p2_uid"]) or ""
            p2_row = db.get_user_row(g["p2_uid"])
            p2_name = p2_row["first_name"] if p2_row else str(g["p2_uid"])
            p2_d = f"@{p2_un}" if p2_un else p2_name
        else:
            p2_d = "?"
        return p1_d, p2_d

    def _notify_joined(g, joiner_uid: int, p1_d: str, p2_d: str, sent_msg):
        e = DICE_EMOJI.get(g["game_type"], "🎲")
        game_url = _build_game_url(sent_msg)
        mode_lbl = (
            f"до {g['win_score']} очков" if g["mode"] == "x"
            else f"{g['rounds']} бросков • сумма"
        )
        text = (
            f"{e} <b>Ты успешно присоединился к дуэли!</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
            f'<tg-emoji emoji-id="5260399854500191689">👤</tg-emoji> Соперник:  <b>{p1_d}</b>\n'
            f'{EMOJI_RUBLES} Ставка:    <b>{g["bet"]:,.2f}</b>\n'
            f" <b>{mode_lbl}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━\n"
        )
        kb = InlineKeyboardMarkup()
        kb.add(InlineKeyboardButton("Ваша игра", url=game_url))
        try:
            bot.send_message(joiner_uid, text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass

    def _notify_referrer(ref_uid: int, winner_display: str,
                         reward: float, game_id: int):
        try:
            new_balance = db.get_balance(ref_uid)
            bot.send_message(
                ref_uid,
                f'💰 <b>Реферальное начисление!</b>\n'
                f'━━━━━━━━━━━━━━━━━━━━━\n'
                f'👤 Ваш реферал <b>{winner_display}</b> выиграл дуэль.\n'
                f'➕ Начислено: <b>+{reward:,.2f}</b>\n'
                f'💎 Ваш баланс: <b>{new_balance:,.2f}</b>',
                parse_mode="HTML",
            )
        except Exception:
            pass

    def _end_game(g, winner_uid: Optional[int] = None, draw=False):
        game_id = g["id"]
        bet = g["bet"]

        p1_uid = g["p1_uid"]
        p2_uid = g["p2_uid"]
        p1_scores = db.player_get_scores(game_id, p1_uid)
        p2_scores = db.player_get_scores(game_id, p2_uid)
        p1_pts = db.player_get_points(game_id, p1_uid)
        p2_pts = db.player_get_points(game_id, p2_uid)
        p1_d, p2_d = _load_displays(g)

        db.game_finish(game_id)
        safe_del(g["chat_id"], g["game_msg"])

        if draw:
            db.add_balance(p1_uid, bet)
            db.add_balance(p2_uid, bet)
            winner_d = None
        else:
            win_amount = bet * 2
            db.add_balance(winner_uid, win_amount)
            winner_d = p1_d if winner_uid == p1_uid else p2_d

                                                                              
            ref_result = db.referral_try_reward(game_id, winner_uid, win_amount)
            if ref_result is not None:
                ref_uid, reward = ref_result
                _notify_referrer(ref_uid, winner_d, reward, game_id)

        db.add_turnover(p1_uid, bet)
        db.add_turnover(p2_uid, bet)

        text = _t_finish(
            g, winner_d, p1_d, p2_d,
            p1_scores, p2_scores, p1_pts, p2_pts, draw,
        )
        bot.send_message(g["chat_id"], text, parse_mode="HTML")

                                                                             

    def _handle_x(g, uid: int, val: int):
        game_id = g["id"]
        p1_uid  = g["p1_uid"]
        p2_uid  = g["p2_uid"]

        p1_rv = g["p1_round_val"]
        p2_rv = g["p2_round_val"]

        if uid == p1_uid:
            if p1_rv is not None:
                return
            p1_rv = val
        elif uid == p2_uid:
            if p2_rv is not None:
                return
            p2_rv = val
        else:
            return

        db.game_update_round(game_id, p1_rv, p2_rv, g["last_round_result"])
        g = db.game_get(game_id)

        if p1_rv is not None and p2_rv is not None:
            v1, v2 = p1_rv, p2_rv
            db.player_add_score(game_id, p1_uid, v1)
            db.player_add_score(game_id, p2_uid, v2)

            p1_pts = db.player_get_points(game_id, p1_uid)
            p2_pts = db.player_get_points(game_id, p2_uid)
            rnd_num = len(db.player_get_scores(game_id, p1_uid))

            p1_d, p2_d = _load_displays(g)
            if v1 > v2:
                db.player_add_point(game_id, p1_uid)
                p1_pts += 1
                lrr = (
                    f"Раунд {rnd_num}:({v1} vs {v2}) — счёт {p1_pts}:{p2_pts}"
                )
            elif v2 > v1:
                db.player_add_point(game_id, p2_uid)
                p2_pts += 1
                lrr = (
                    f"Раунд {rnd_num}:({v2} vs {v1}) — счёт {p1_pts}:{p2_pts}"
                )
            else:
                lrr = (
                    f"Раунд {rnd_num}: ничья ({v1}={v2}) — "
                    f"счёт прежний {p1_pts}:{p2_pts}"
                )

            db.game_update_round(game_id, None, None, lrr)
            g = db.game_get(game_id)

            if p1_pts >= g["win_score"]:
                _end_game(g, winner_uid=p1_uid)
            elif p2_pts >= g["win_score"]:
                _end_game(g, winner_uid=p2_uid)
            else:
                safe_del(g["chat_id"], g["game_msg"])
                p1_scores_len = len(db.player_get_scores(game_id, p1_uid))
                text = _t_x(
                    g, p1_d, p2_d, p1_pts, p2_pts, None, None, lrr,
                    p1_scores_len + 1,
                )
                sent = bot.send_message(g["chat_id"], text, parse_mode="HTML")
                db.game_set_game_msg(game_id, sent.message_id)
        else:
            p1_d, p2_d = _load_displays(g)
            p1_pts = db.player_get_points(game_id, p1_uid)
            p2_pts = db.player_get_points(game_id, p2_uid)
            p1_scores = db.player_get_scores(game_id, p1_uid)
            rnd = len(p1_scores) + 1
            text = _t_x(
                g, p1_d, p2_d, p1_pts, p2_pts,
                g["p1_round_val"], g["p2_round_val"],
                g["last_round_result"], rnd,
            )
            edit_game_msg(g["chat_id"], g["game_msg"], text)

                                                                              

    def _handle_total(g, uid: int, val: int):
        game_id = g["id"]
        p1_uid  = g["p1_uid"]
        p2_uid  = g["p2_uid"]
        rounds  = g["rounds"]

        p1_scores = db.player_get_scores(game_id, p1_uid)
        p2_scores = db.player_get_scores(game_id, p2_uid)

        if uid == p1_uid:
            if len(p1_scores) >= rounds:
                return
            db.player_add_score(game_id, p1_uid, val)
            p1_scores = db.player_get_scores(game_id, p1_uid)
        elif uid == p2_uid:
            if len(p2_scores) >= rounds:
                return
            db.player_add_score(game_id, p2_uid, val)
            p2_scores = db.player_get_scores(game_id, p2_uid)
        else:
            return

        p1_d, p2_d = _load_displays(g)

        if len(p1_scores) == rounds and len(p2_scores) == rounds:
            # Используем новую функцию расчёта
            s1 = _calculate_total_score(p1_scores, rounds)
            s2 = _calculate_total_score(p2_scores, rounds)
            if s1 > s2:
                _end_game(g, winner_uid=p1_uid)
            elif s2 > s1:
                _end_game(g, winner_uid=p2_uid)
            else:
                _end_game(g, draw=True)
        else:
            text = _t_total(g, p1_d, p2_d, p1_scores, p2_scores)
            edit_game_msg(g["chat_id"], g["game_msg"], text)

                                                                             
               
                                                                             

    @bot.message_handler(func=is_duel_command)
    def cmd_create(message: Message):
        parsed = _parse_cmd(message.text)
        if not parsed:
            return
        gtype, mode, rounds = parsed

        if mode == "total" and rounds < 2:
            bot.reply_to(message, "❌ Для total-режима минимальное число бросков — 2!")
            return

        bet = _get_bet(message.text)
        if bet is None:
            bot.reply_to(
                message,
                f"❌ Укажи ставку от {BET_MIN:.2f} до {BET_MAX:,.0f}!\n"
                f"Пример: <code>/{gtype}{mode}{rounds} 100</code>",
                parse_mode="HTML",
            )
            return

        uid = message.from_user.id
        db.ensure_user(uid, message.from_user.username or "", _fmt_name(message.from_user))

        if db.get_balance(uid) < bet:
            bot.reply_to(message, f"❌ Недостаточно средств!")
            return

        chat_id = message.chat.id

        with _lock:
            active = db.game_get_by_chat(chat_id)
            for ag in active:
                if ag["state"] == "lobby" and ag["p1_uid"] == uid:
                    bot.reply_to(
                        message,
                        "❌ У тебя уже есть активная lobby-дуэль в этом чате!\n",
                    )
                    return
                if ag["state"] in ("lobby", "playing"):
                    if ag["p1_uid"] == uid or ag["p2_uid"] == uid:
                        bot.reply_to(
                            message,
                            "❌ Ты уже участвуешь в активной дуэли в этом чате!",
                        )
                        return

            if not db.subtract_balance(uid, bet):
                bot.reply_to(message, f"❌ Недостаточно средств!")
                return

            game_id = db.game_create(
                chat_id=chat_id,
                game_type=gtype,
                mode=mode,
                rounds=rounds,
                win_score=rounds,
                bet=bet,
                p1_uid=uid,
            )

        g = db.game_get(game_id)
        p1_d, _ = _load_displays(g)

        sent = bot.send_message(
            chat_id,
            _t_lobby(g, p1_d),
            parse_mode="HTML",
            reply_markup=_kb_lobby(game_id),
        )
        db.game_set_lobby_msg(game_id, sent.message_id)

                                                                              

    @bot.callback_query_handler(func=lambda call: call.data.startswith("duel_join:"))
    def cb_join(call):
        game_id = int(call.data.split(":")[1])
        uid     = call.from_user.id

        with _lock:
            g = db.game_get(game_id)
            if not g or g["state"] != "lobby":
                bot.answer_callback_query(call.id, "Дуэль недоступна.", show_alert=True)
                return
            if uid == g["p1_uid"]:
                bot.answer_callback_query(call.id, "Нельзя играть самим с собой!", show_alert=True)
                return

            active = db.game_get_by_chat(g["chat_id"])
            for ag in active:
                if ag["id"] == game_id:
                    continue
                if ag["state"] in ("lobby", "playing") and (
                        ag["p1_uid"] == uid or ag["p2_uid"] == uid):
                    bot.answer_callback_query(
                        call.id, "Ты уже участвуешь в другой дуэли в этом чате!", show_alert=True
                    )
                    return

            db.ensure_user(uid, call.from_user.username or "", _fmt_name(call.from_user))

            if db.get_balance(uid) < g["bet"]:
                bot.answer_callback_query(
                    call.id,
                    f"Недостаточно средств! Нужно: {g['bet']:,.2f}",
                    show_alert=True,
                )
                return

            if not db.subtract_balance(uid, g["bet"]):
                bot.answer_callback_query(call.id, "Ошибка списания средств.", show_alert=True)
                return

            db.game_join(game_id, uid)

        bot.answer_callback_query(call.id, "✅ Ты в игре!")
        safe_del(g["chat_id"], g["lobby_msg"])

        g = db.game_get(game_id)
        p1_d, p2_d = _load_displays(g)

        if g["mode"] == "x":
            text = _t_x(g, p1_d, p2_d, 0, 0, None, None, "", 1)
        else:
            text = _t_total(g, p1_d, p2_d, [], [])

        sent = bot.send_message(g["chat_id"], text, parse_mode="HTML")
        db.game_set_game_msg(game_id, sent.message_id)

        _notify_joined(g, uid, p1_d, p2_d, sent)

                                                                              

    @bot.message_handler(commands=["del"])
    def cmd_del(message: Message):
        uid = message.from_user.id

        if not message.reply_to_message:
            bot.reply_to(
                message,
                "❌ Сделай реплай на сообщение дуэли, которую хочешь удалить.",
            )
            return

        reply_msg_id = message.reply_to_message.message_id
        chat_id = message.chat.id

        with _lock:
            games = db.game_get_by_chat(chat_id)
            target = None
            for ag in games:
                if ag["lobby_msg"] == reply_msg_id or ag["game_msg"] == reply_msg_id:
                    target = ag
                    break

            if not target:
                bot.reply_to(message, "❌ Дуэль не найдена или уже завершена.")
                return
            if target["state"] != "lobby":
                bot.reply_to(message, "❌ Нельзя удалить дуэль в процессе игры.")
                return
            if target["p1_uid"] != uid:
                bot.reply_to(message, "❌ Удалить дуэль может только её создатель.")
                return

            db.add_balance(uid, target["bet"])
            db.game_delete(target["id"])

        safe_del(chat_id, target["lobby_msg"])
        bot.send_message(chat_id, f"❌ Дуэль удалена. Ставка возвращена!", parse_mode="HTML")

                                                                              

    @bot.message_handler(commands=["delall"])
    def cmd_delall(message: Message):
        uid = message.from_user.id

        with _lock:
            lobby_games = db.game_get_by_creator(uid)
            if not lobby_games:
                bot.reply_to(message, "ℹ️ У тебя нет активных lobby-дуэлей.")
                return
            for g in lobby_games:
                db.add_balance(uid, g["bet"])
                safe_del(g["chat_id"], g["lobby_msg"])
                db.game_delete(g["id"])

        bot.reply_to(
            message,
            f"✅ Удалено {len(lobby_games)} дуэль(ей). Ставки возвращены.",
        )

                                                                               

    @bot.message_handler(commands=["myg", "mygames"])
    def cmd_myg(message: Message):
        uid = message.from_user.id
        games = db.game_get_all_active_for_user(uid)
        bot.reply_to(message, _t_my_games(games), parse_mode="HTML")

                                                                               

    @bot.message_handler(commands=["cancelduel"])
    def cmd_cancel(message: Message):
        uid     = message.from_user.id
        chat_id = message.chat.id

        with _lock:
            active = db.game_get_by_chat(chat_id)
            target = None
            for ag in active:
                if ag["p1_uid"] == uid and ag["state"] == "lobby":
                    target = ag
                    break

            if not target:
                bot.reply_to(message, "❌ Нет твоей активной lobby-дуэли в этом чате.")
                return

            db.add_balance(uid, target["bet"])
            db.game_delete(target["id"])

        safe_del(chat_id, target["lobby_msg"])
        bot.send_message(chat_id, "❌ Дуэль отменена. Ставка возвращена.", parse_mode="HTML")

                                                                               

    @bot.callback_query_handler(func=lambda call: call.data.startswith("duel_cancel:"))
    def cb_cancel(call):
        game_id = int(call.data.split(":")[1])
        uid     = call.from_user.id

        with _lock:
            g = db.game_get(game_id)
            if not g:
                bot.answer_callback_query(call.id, "Дуэль не найдена.", show_alert=True)
                return
            if g["p1_uid"] != uid:
                bot.answer_callback_query(call.id, "Отменить может только создатель.", show_alert=True)
                return
            if g["state"] != "lobby":
                bot.answer_callback_query(call.id, "Дуэль уже началась — нельзя отменить.", show_alert=True)
                return

            db.add_balance(uid, g["bet"])
            db.game_delete(game_id)

        bot.answer_callback_query(call.id)
        safe_del(g["chat_id"], g["lobby_msg"])
        bot.send_message(g["chat_id"], "❌ Дуэль отменена. Ставка возвращена.", parse_mode="HTML")

                                                                               

    @bot.message_handler(content_types=["dice"], func=is_duel_dice)
    def handle_dice(message: Message):
        chat_id = message.chat.id
        uid     = message.from_user.id
        val     = message.dice.value
        gtype   = EMOJI_TO_TYPE[message.dice.emoji]

        with _lock:
            games = db.game_get_by_chat(chat_id)
            g = None
            for ag in games:
                if (ag["state"] == "playing"
                        and ag["game_msg"] == message.reply_to_message.message_id
                        and ag["game_type"] == gtype):
                    g = ag
                    break

            if not g:
                return

            if g["mode"] == "x":
                _handle_x(g, uid, val)
            else:
                _handle_total(g, uid, val)

    def get_all_lobby_games() -> list:
        return db.game_get_active_lobby_all()

    register.get_lobby_games = get_all_lobby_games
