"""
database.py — SQLite-хранилище (WAL-mode, thread-safe)

Таблицы:
  users        — балансы, оборот, рефералы, дата регистрации
  games        — активные / завершённые дуэли
  game_players — данные каждого игрока в дуэли (очки, броски)
"""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

DB_PATH = Path("bot.db")

_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Возвращает соединение для текущего потока (одно на поток)."""
    if not hasattr(_local, "conn"):
        con = sqlite3.connect(DB_PATH, check_same_thread=False)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        _local.conn = con
    return _local.conn


def _ex(sql: str, params=(), *, fetch: str = "none"):
    con = _conn()
    cur = con.execute(sql, params)
    con.commit()
    if fetch == "one":
        return cur.fetchone()
    if fetch == "all":
        return cur.fetchall()
    return cur


# ══════════════════════════════════════════════════════════════════════════════
#  INIT
# ══════════════════════════════════════════════════════════════════════════════

def init_db():
    con = _conn()
    con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            uid         INTEGER PRIMARY KEY,
            username    TEXT    DEFAULT '',
            first_name  TEXT    DEFAULT '',
            balance     REAL    DEFAULT 0.0,
            turnover    REAL    DEFAULT 0.0,
            ref_by      INTEGER DEFAULT NULL,
            ref_earned  REAL    DEFAULT 0.0,
            ref_count   INTEGER DEFAULT 0,
            created_at  INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS games (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id     INTEGER NOT NULL,
            game_type   TEXT    NOT NULL,
            mode        TEXT    NOT NULL,   -- 'x' | 'total'
            rounds      INTEGER NOT NULL,
            win_score   INTEGER NOT NULL,
            bet         REAL    NOT NULL,
            state       TEXT    NOT NULL DEFAULT 'lobby',   -- lobby|playing|finished
            lobby_msg   INTEGER DEFAULT 0,
            game_msg    INTEGER DEFAULT 0,
            p1_uid      INTEGER NOT NULL,
            p2_uid      INTEGER DEFAULT NULL,
            p1_round_val INTEGER DEFAULT NULL,
            p2_round_val INTEGER DEFAULT NULL,
            last_round_result TEXT DEFAULT '',
            created_at  INTEGER DEFAULT (strftime('%s','now'))
        );

        CREATE TABLE IF NOT EXISTS game_players (
            game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            uid         INTEGER NOT NULL,
            scores_json TEXT    NOT NULL DEFAULT '[]',
            points      INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (game_id, uid)
        );

        CREATE INDEX IF NOT EXISTS idx_games_chat ON games(chat_id, state);
        CREATE INDEX IF NOT EXISTS idx_games_p1   ON games(p1_uid, state);
        CREATE INDEX IF NOT EXISTS idx_games_p2   ON games(p2_uid, state);
    """)
    con.commit()


# ══════════════════════════════════════════════════════════════════════════════
#  USERS
# ══════════════════════════════════════════════════════════════════════════════

def ensure_user(uid: int, username: str = "", first_name: str = ""):
    _ex(
        """INSERT INTO users(uid, username, first_name)
           VALUES(?,?,?)
           ON CONFLICT(uid) DO UPDATE SET
               username   = excluded.username,
               first_name = excluded.first_name
        """,
        (uid, username or "", first_name or ""),
    )


def get_balance(uid: int) -> float:
    row = _ex("SELECT balance FROM users WHERE uid=?", (uid,), fetch="one")
    return row["balance"] if row else 0.0


def add_balance(uid: int, amount: float):
    _ex(
        "UPDATE users SET balance=ROUND(balance+?,2) WHERE uid=?",
        (amount, uid),
    )


def subtract_balance(uid: int, amount: float) -> bool:
    """Списывает amount если средств достаточно. Возвращает True при успехе."""
    con = _conn()
    cur = con.execute(
        "UPDATE users SET balance=ROUND(balance-?,2) WHERE uid=? AND balance>=?",
        (amount, uid, amount),
    )
    con.commit()
    return cur.rowcount > 0


def add_turnover(uid: int, amount: float):
    _ex(
        "UPDATE users SET turnover=ROUND(turnover+?,2) WHERE uid=?",
        (amount, uid),
    )


def get_user_row(uid: int) -> Optional[sqlite3.Row]:
    return _ex("SELECT * FROM users WHERE uid=?", (uid,), fetch="one")


def get_username_by_uid(uid: int) -> Optional[str]:
    row = _ex("SELECT username FROM users WHERE uid=?", (uid,), fetch="one")
    return row["username"] if row else None


def resolve_username(username: str) -> Optional[int]:
    """@username → uid (если зарегистрирован)."""
    row = _ex(
        "SELECT uid FROM users WHERE LOWER(username)=?",
        (username.lower().lstrip("@"),),
        fetch="one",
    )
    return row["uid"] if row else None


# Реферальная система
def add_referral(ref_uid: int, amount_earned: float):
    _ex(
        """UPDATE users
           SET ref_earned=ROUND(ref_earned+?,2),
               ref_count=ref_count+1
           WHERE uid=?""",
        (amount_earned, ref_uid),
    )


def get_referral_stats(uid: int):
    row = _ex(
        "SELECT ref_count, ref_earned FROM users WHERE uid=?",
        (uid,),
        fetch="one",
    )
    return (row["ref_count"], row["ref_earned"]) if row else (0, 0.0)


# Статистика (заглушка — расширяй по необходимости)
def get_stats(period: str = "all") -> dict:
    if period == "all":
        cond = ""
    elif period == "day":
        cond = "AND created_at >= strftime('%s','now','-1 day')"
    else:  # week
        cond = "AND created_at >= strftime('%s','now','-7 days')"

    row = _ex(
        f"""SELECT
               COALESCE(SUM(bet*2),0)  AS total_dep,
               COALESCE(SUM(bet*2),0)  AS turnover,
               0                       AS total_with,
               0                       AS profit
           FROM games
           WHERE state='finished' {cond}""",
        fetch="one",
    )
    return dict(row) if row else {"total_dep": 0, "turnover": 0,
                                  "total_with": 0, "profit": 0}


def days_since_registration(uid: int) -> int:
    row = _ex(
        "SELECT (strftime('%s','now') - created_at)/86400 AS d FROM users WHERE uid=?",
        (uid,),
        fetch="one",
    )
    return int(row["d"]) if row and row["d"] is not None else 0


# ══════════════════════════════════════════════════════════════════════════════
#  GAMES
# ══════════════════════════════════════════════════════════════════════════════

def game_create(
    chat_id: int, game_type: str, mode: str,
    rounds: int, win_score: int, bet: float, p1_uid: int,
) -> int:
    """Создаёт запись игры + запись игрока 1. Возвращает game_id."""
    con = _conn()
    cur = con.execute(
        """INSERT INTO games(chat_id,game_type,mode,rounds,win_score,bet,p1_uid)
           VALUES(?,?,?,?,?,?,?)""",
        (chat_id, game_type, mode, rounds, win_score, bet, p1_uid),
    )
    gid = cur.lastrowid
    con.execute(
        "INSERT INTO game_players(game_id,uid) VALUES(?,?)",
        (gid, p1_uid),
    )
    con.commit()
    return gid


def game_join(game_id: int, p2_uid: int):
    con = _conn()
    con.execute(
        "UPDATE games SET p2_uid=?,state='playing' WHERE id=?",
        (p2_uid, game_id),
    )
    con.execute(
        "INSERT OR IGNORE INTO game_players(game_id,uid) VALUES(?,?)",
        (game_id, p2_uid),
    )
    con.commit()


def game_delete(game_id: int):
    _ex("DELETE FROM games WHERE id=?", (game_id,))


def game_get(game_id: int) -> Optional[sqlite3.Row]:
    return _ex("SELECT * FROM games WHERE id=?", (game_id,), fetch="one")


def game_get_by_chat(chat_id: int) -> list:
    """Все активные (lobby|playing) игры в чате."""
    return _ex(
        "SELECT * FROM games WHERE chat_id=? AND state IN ('lobby','playing')",
        (chat_id,),
        fetch="all",
    )


def game_get_active_lobby_all() -> list:
    """Все игры в состоянии lobby (для /active_games в меню)."""
    return _ex(
        "SELECT * FROM games WHERE state='lobby' ORDER BY created_at DESC",
        fetch="all",
    )


def game_get_by_creator(p1_uid: int) -> list:
    """Все lobby-игры созданные данным игроком (для /delall, /myg)."""
    return _ex(
        "SELECT * FROM games WHERE p1_uid=? AND state='lobby'",
        (p1_uid,),
        fetch="all",
    )


def game_get_all_active_for_user(uid: int) -> list:
    """Все активные игры (lobby|playing) в которых участвует игрок."""
    return _ex(
        """SELECT * FROM games
           WHERE state IN ('lobby','playing')
             AND (p1_uid=? OR p2_uid=?)
           ORDER BY created_at DESC""",
        (uid, uid),
        fetch="all",
    )


def game_set_lobby_msg(game_id: int, msg_id: int):
    _ex("UPDATE games SET lobby_msg=? WHERE id=?", (msg_id, game_id))


def game_set_game_msg(game_id: int, msg_id: int):
    _ex("UPDATE games SET game_msg=? WHERE id=?", (msg_id, game_id))


def game_set_state(game_id: int, state: str):
    _ex("UPDATE games SET state=? WHERE id=?", (state, game_id))


def game_update_round(
    game_id: int,
    p1_round_val: Optional[int],
    p2_round_val: Optional[int],
    last_round_result: str,
):
    _ex(
        """UPDATE games
           SET p1_round_val=?, p2_round_val=?, last_round_result=?
           WHERE id=?""",
        (p1_round_val, p2_round_val, last_round_result, game_id),
    )


def game_finish(game_id: int):
    _ex("UPDATE games SET state='finished' WHERE id=?", (game_id,))


# ── Игроки ─────────────────────────────────────────────────────────────────

def player_get(game_id: int, uid: int) -> Optional[sqlite3.Row]:
    return _ex(
        "SELECT * FROM game_players WHERE game_id=? AND uid=?",
        (game_id, uid),
        fetch="one",
    )


def player_add_score(game_id: int, uid: int, val: int):
    row = _ex(
        "SELECT scores_json FROM game_players WHERE game_id=? AND uid=?",
        (game_id, uid),
        fetch="one",
    )
    scores = json.loads(row["scores_json"]) if row else []
    scores.append(val)
    _ex(
        "UPDATE game_players SET scores_json=? WHERE game_id=? AND uid=?",
        (json.dumps(scores), game_id, uid),
    )


def player_add_point(game_id: int, uid: int):
    _ex(
        "UPDATE game_players SET points=points+1 WHERE game_id=? AND uid=?",
        (game_id, uid),
    )


def player_get_scores(game_id: int, uid: int) -> list:
    row = _ex(
        "SELECT scores_json FROM game_players WHERE game_id=? AND uid=?",
        (game_id, uid),
        fetch="one",
    )
    return json.loads(row["scores_json"]) if row else []


def player_get_points(game_id: int, uid: int) -> int:
    row = _ex(
        "SELECT points FROM game_players WHERE game_id=? AND uid=?",
        (game_id, uid),
        fetch="one",
    )
    return row["points"] if row else 0
