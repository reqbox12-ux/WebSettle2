"""
인증 모듈 — SQLite 기반 사용자 관리 + bcrypt 암호화 + HMAC 세션 토큰
기본 관리자: admin / Admin1234!
"""

import bcrypt
import hmac
import hashlib
import time
import secrets
import json
from pathlib import Path
from modules.db import get_conn

SESSION_MAX_DAYS = 30

SETTINGS_PATH = Path(__file__).parent.parent / "data" / "settings.json"
TOKEN_COOKIE   = "ws_auth_token"
TOKEN_MAX_DAYS = 30


# ── 시크릿 키 (자동 생성, settings.json에 저장) ─────────────────

def _get_secret() -> str:
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
    if "secret_key" not in data:
        data["secret_key"] = secrets.token_hex(32)
        SETTINGS_PATH.parent.mkdir(exist_ok=True)
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    return data["secret_key"]


# ── 세션 토큰 생성 / 검증 ────────────────────────────────────────

def make_token(username: str) -> str:
    secret = _get_secret()
    ts  = str(int(time.time()))
    sig = hmac.new(secret.encode(), f"{username}:{ts}".encode(), hashlib.sha256).hexdigest()
    return f"{username}:{ts}:{sig}"


def validate_token(token: str) -> str | None:
    """유효한 토큰이면 username 반환, 만료·위조면 None"""
    try:
        username, ts, sig = token.split(":", 2)
        if int(time.time()) - int(ts) > TOKEN_MAX_DAYS * 86400:
            return None
        secret   = _get_secret()
        expected = hmac.new(secret.encode(), f"{username}:{ts}".encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, expected):
            return username
    except Exception:
        pass
    return None


# ── 테이블 초기화 ─────────────────────────────────────────────

def init_users_table():
    """users 테이블 생성 + 기본 admin 계정 없으면 생성"""
    from modules.db import USE_POSTGRES
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         SERIAL PRIMARY KEY,
                username   TEXT UNIQUE NOT NULL,
                name       TEXT NOT NULL,
                password   TEXT NOT NULL,
                role       TEXT DEFAULT 'user',
                created_at TEXT DEFAULT (to_char(now(), 'YYYY-MM-DD HH24:MI:SS'))
            )
        """)
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not row:
            pw_hash = bcrypt.hashpw("Admin1234!".encode(), bcrypt.gensalt()).decode()
            c.execute(
                "INSERT INTO users (username, name, password, role) VALUES (%s,%s,%s,%s)",
                ("admin", "관리자", pw_hash, "admin")
            )
    else:
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                username   TEXT UNIQUE NOT NULL,
                name       TEXT NOT NULL,
                password   TEXT NOT NULL,
                role       TEXT DEFAULT 'user',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        conn.commit()
        row = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()
        if not row:
            pw_hash = bcrypt.hashpw("Admin1234!".encode(), bcrypt.gensalt()).decode()
            c.execute(
                "INSERT INTO users (username, name, password, role) VALUES (?,?,?,?)",
                ("admin", "관리자", pw_hash, "admin")
            )

    conn.commit()
    conn.close()


# ── 로그인 검증 ───────────────────────────────────────────────

def verify_login(username: str, password: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT username, name, password, role FROM users WHERE username=?",
        (username.strip(),)
    ).fetchone()
    conn.close()
    if row and bcrypt.checkpw(password.encode(), row[2].encode()):
        return {"username": row[0], "name": row[1], "role": row[3]}
    return None


def get_user_by_username(username: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT username, name, role FROM users WHERE username=?", (username,)
    ).fetchone()
    conn.close()
    if row:
        return {"username": row[0], "name": row[1], "role": row[2]}
    return None


# ── 사용자 관리 ───────────────────────────────────────────────

def get_all_users() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, username, name, role, created_at FROM users ORDER BY id"
    ).fetchall()
    conn.close()
    return [{"id": r[0], "username": r[1], "name": r[2], "role": r[3], "created_at": r[4]} for r in rows]


def add_user(username: str, name: str, password: str, role: str = "user") -> bool:
    try:
        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
        conn = get_conn()
        conn.execute(
            "INSERT INTO users (username, name, password, role) VALUES (?,?,?,?)",
            (username.strip(), name.strip(), pw_hash, role)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def delete_user(user_id: int) -> bool:
    try:
        conn = get_conn()
        conn.execute("DELETE FROM users WHERE id=? AND username != 'admin'", (user_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def change_password(username: str, new_password: str) -> bool:
    try:
        pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
        conn = get_conn()
        conn.execute("UPDATE users SET password=? WHERE username=?", (pw_hash, username))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── 세션 관리 (URL 토큰 방식) ──────────────────────────────────

def create_session(username: str, remember: bool = True) -> str:
    """새 세션 토큰 생성 후 DB에 저장, 토큰 문자열 반환
    remember=True → 30일, remember=False → 8시간"""
    token = secrets.token_urlsafe(32)
    seconds = SESSION_MAX_DAYS * 86400 if remember else 28800
    expires_at = int(time.time()) + seconds
    try:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO sessions (token, username, expires_at) VALUES (?,?,?)",
            (token, username, expires_at)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[session create] {e}")
    return token


def get_session_user(token: str) -> dict | None:
    """토큰으로 유저 정보 조회 — 만료·없으면 None"""
    if not token:
        return None
    try:
        conn = get_conn()
        row = conn.execute(
            "SELECT username, expires_at FROM sessions WHERE token=?", (token,)
        ).fetchone()
        conn.close()
        if row and int(time.time()) < row[1]:
            return get_user_by_username(row[0])
    except Exception as e:
        print(f"[session get] {e}")
    return None


def delete_session(token: str):
    """세션 토큰 삭제 (로그아웃)"""
    if not token:
        return
    try:
        conn = get_conn()
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[session delete] {e}")
