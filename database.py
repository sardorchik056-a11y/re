import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

DB_PATH = Path("bot.db")

_local = threading.local()


def _conn() -> sqlite3.Connection:
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
            mode        TEXT    NOT NULL,
            rounds      INTEGER NOT NULL,
            win_score   INTEGER NOT NULL,
            bet         REAL    NOT NULL,
            state       TEXT    NOT NULL DEFAULT 'lobby',
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

        -- Пополнения: invoice_id уникален — защита от двойного зачисления
        CREATE TABLE IF NOT EXISTS deposits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uid         INTEGER NOT NULL,
            invoice_id  INTEGER NOT NULL UNIQUE,
            amount      REAL    NOT NULL,
            asset       TEXT    NOT NULL DEFAULT 'USDT',
            status      TEXT    NOT NULL DEFAULT 'pending',
            created_at  INTEGER DEFAULT (strftime('%s','now')),
            paid_at     INTEGER DEFAULT NULL
        );

        -- Выводы
        CREATE TABLE IF NOT EXISTS withdrawals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uid         INTEGER NOT NULL,
            amount      REAL    NOT NULL,
            asset       TEXT    NOT NULL DEFAULT 'USDT',
            check_id    INTEGER DEFAULT NULL,
            check_url   TEXT    DEFAULT NULL,
            status      TEXT    NOT NULL DEFAULT 'pending',
            created_at  INTEGER DEFAULT (strftime('%s','now')),
            sent_at     INTEGER DEFAULT NULL
        );

        -- Реферальный лог: game_id + ref_uid уникальны — защита от дублей
        -- winner_uid  — кто выиграл (получил приз)
        -- ref_uid     — реферер (кому начислен процент)
        -- amount      — начисленная сумма рефереру
        CREATE TABLE IF NOT EXISTS referral_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id     INTEGER NOT NULL,
            winner_uid  INTEGER NOT NULL,
            ref_uid     INTEGER NOT NULL,
            amount      REAL    NOT NULL,
            created_at  INTEGER DEFAULT (strftime('%s','now')),
            UNIQUE(game_id, ref_uid)
        );

        CREATE INDEX IF NOT EXISTS idx_games_chat   ON games(chat_id, state);
        CREATE INDEX IF NOT EXISTS idx_games_p1     ON games(p1_uid, state);
        CREATE INDEX IF NOT EXISTS idx_games_p2     ON games(p2_uid, state);
        CREATE INDEX IF NOT EXISTS idx_dep_uid      ON deposits(uid, status);
        CREATE INDEX IF NOT EXISTS idx_wit_uid      ON withdrawals(uid, status);
        CREATE INDEX IF NOT EXISTS idx_reflog_game  ON referral_log(game_id);
        CREATE INDEX IF NOT EXISTS idx_reflog_ref   ON referral_log(ref_uid);
    """)
    con.commit()


                                                                                
        
                                                                                

def ensure_user(uid: int, username: str = "", first_name: str = "",
                ref_by: Optional[int] = None):
    con = _conn()
    if ref_by is not None:
        con.execute(
            """INSERT INTO users(uid, username, first_name, ref_by)
               VALUES(?,?,?,?)
               ON CONFLICT(uid) DO UPDATE SET
                   username   = excluded.username,
                   first_name = excluded.first_name
            """,
            (uid, username or "", first_name or "", ref_by),
        )
    else:
        con.execute(
            """INSERT INTO users(uid, username, first_name)
               VALUES(?,?,?)
               ON CONFLICT(uid) DO UPDATE SET
                   username   = excluded.username,
                   first_name = excluded.first_name
            """,
            (uid, username or "", first_name or ""),
        )
    con.commit()


def is_new_user(uid: int) -> bool:
    row = _ex("SELECT uid FROM users WHERE uid=?", (uid,), fetch="one")
    return row is None


def get_balance(uid: int) -> float:
    row = _ex("SELECT balance FROM users WHERE uid=?", (uid,), fetch="one")
    return row["balance"] if row else 0.0


def add_balance(uid: int, amount: float):
    _ex(
        "UPDATE users SET balance=ROUND(balance+?,2) WHERE uid=?",
        (amount, uid),
    )


def subtract_balance(uid: int, amount: float) -> bool:
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
    row = _ex(
        "SELECT uid FROM users WHERE LOWER(username)=?",
        (username.lower().lstrip("@"),),
        fetch="one",
    )
    return row["uid"] if row else None


def get_referral_stats(uid: int):
    row = _ex(
        "SELECT ref_count, ref_earned FROM users WHERE uid=?",
        (uid,),
        fetch="one",
    )
    return (row["ref_count"], row["ref_earned"]) if row else (0, 0.0)


def get_ref_by(uid: int) -> Optional[int]:
    row = _ex("SELECT ref_by FROM users WHERE uid=?", (uid,), fetch="one")
    return row["ref_by"] if row else None


def get_stats(period: str = "all") -> dict:
    if period == "all":
        cond = ""
    elif period == "day":
        cond = "AND created_at >= strftime('%s','now','-1 day')"
    else:
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


                                                                                
            
                                                                                

REF_PERCENT = 0.01                              


def referral_try_reward(game_id: int, winner_uid: int, win_amount: float) -> Optional[tuple]:
    ref_uid = get_ref_by(winner_uid)
    if ref_uid is None:
        return None

    reward = round(win_amount * REF_PERCENT, 2)
    if reward <= 0:
        return None

    con = _conn()
    try:
        cur = con.execute(
            """INSERT OR IGNORE INTO referral_log
               (game_id, winner_uid, ref_uid, amount)
               VALUES (?, ?, ?, ?)""",
            (game_id, winner_uid, ref_uid, reward),
        )
        con.commit()
        if cur.rowcount == 0:
                                                         
            return None
    except Exception:
        con.rollback()
        return None

                                                    
    con.execute(
        """UPDATE users
           SET balance    = ROUND(balance + ?, 2),
               ref_earned = ROUND(ref_earned + ?, 2),
               ref_count  = ref_count + 1
           WHERE uid = ?""",
        (reward, reward, ref_uid),
    )
    con.commit()
    return (ref_uid, reward)


def referral_log_history(ref_uid: int, limit: int = 20) -> list:
    return _ex(
        """SELECT rl.*, u.username, u.first_name
           FROM referral_log rl
           LEFT JOIN users u ON u.uid = rl.winner_uid
           WHERE rl.ref_uid = ?
           ORDER BY rl.created_at DESC
           LIMIT ?""",
        (ref_uid, limit),
        fetch="all",
    )


                                                                                
           
                                                                                

def deposit_create(uid: int, invoice_id: int, amount: float, asset: str) -> Optional[int]:
    try:
        cur = _ex(
            """INSERT INTO deposits(uid, invoice_id, amount, asset)
               VALUES(?,?,?,?)""",
            (uid, invoice_id, amount, asset),
        )
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None


def deposit_get_by_invoice(invoice_id: int) -> Optional[sqlite3.Row]:
    return _ex(
        "SELECT * FROM deposits WHERE invoice_id=?",
        (invoice_id,),
        fetch="one",
    )


def deposit_confirm(invoice_id: int) -> bool:
    con = _conn()
    cur = con.execute(
        """UPDATE deposits
           SET status='paid', paid_at=strftime('%s','now')
           WHERE invoice_id=? AND status='pending'""",
        (invoice_id,),
    )
    con.commit()
    return cur.rowcount > 0


def deposit_expire(invoice_id: int):
    _ex(
        "UPDATE deposits SET status='expired' WHERE invoice_id=? AND status='pending'",
        (invoice_id,),
    )


def deposit_history(uid: int, limit: int = 10) -> list:
    return _ex(
        "SELECT * FROM deposits WHERE uid=? ORDER BY created_at DESC LIMIT ?",
        (uid, limit),
        fetch="all",
    )


                                                                                
              
                                                                                

def withdrawal_create(uid: int, amount: float, asset: str) -> Optional[int]:
    con = _conn()
    cur = con.execute(
        "UPDATE users SET balance=ROUND(balance-?,2) WHERE uid=? AND balance>=?",
        (amount, uid, amount),
    )
    if cur.rowcount == 0:
        con.rollback()
        return None
    cur2 = con.execute(
        "INSERT INTO withdrawals(uid, amount, asset) VALUES(?,?,?)",
        (uid, amount, asset),
    )
    wid = cur2.lastrowid
    con.commit()
    return wid


def withdrawal_set_check(withdrawal_id: int, check_id: int, check_url: str):
    _ex(
        """UPDATE withdrawals
           SET check_id=?, check_url=?, status='sent', sent_at=strftime('%s','now')
           WHERE id=?""",
        (check_id, check_url, withdrawal_id),
    )


def withdrawal_set_failed(withdrawal_id: int):
    con = _conn()
    row = con.execute(
        "SELECT uid, amount FROM withdrawals WHERE id=? AND status='pending'",
        (withdrawal_id,),
    ).fetchone()
    if not row:
        return
    con.execute(
        "UPDATE users SET balance=ROUND(balance+?,2) WHERE uid=?",
        (row["amount"], row["uid"]),
    )
    con.execute(
        "UPDATE withdrawals SET status='failed' WHERE id=?",
        (withdrawal_id,),
    )
    con.commit()


def withdrawal_get(withdrawal_id: int) -> Optional[sqlite3.Row]:
    return _ex(
        "SELECT * FROM withdrawals WHERE id=?",
        (withdrawal_id,),
        fetch="one",
    )


def withdrawal_history(uid: int, limit: int = 10) -> list:
    return _ex(
        "SELECT * FROM withdrawals WHERE uid=? ORDER BY created_at DESC LIMIT ?",
        (uid, limit),
        fetch="all",
    )


def withdrawal_has_pending(uid: int) -> bool:
    row = _ex(
        "SELECT id FROM withdrawals WHERE uid=? AND status='pending' LIMIT 1",
        (uid,),
        fetch="one",
    )
    return row is not None


                                                                                
        
                                                                                

def game_create(
    chat_id: int, game_type: str, mode: str,
    rounds: int, win_score: int, bet: float, p1_uid: int,
) -> int:
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
    return _ex(
        "SELECT * FROM games WHERE chat_id=? AND state IN ('lobby','playing')",
        (chat_id,),
        fetch="all",
    )


def game_get_active_lobby_all() -> list:
    return _ex(
        "SELECT * FROM games WHERE state='lobby' ORDER BY created_at DESC",
        fetch="all",
    )


def game_get_by_creator(p1_uid: int) -> list:
    return _ex(
        "SELECT * FROM games WHERE p1_uid=? AND state='lobby'",
        (p1_uid,),
        fetch="all",
    )


def game_get_all_active_for_user(uid: int) -> list:
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
