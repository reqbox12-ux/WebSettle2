"""
domains/branch/db.py — 지점 마스터 및 월별 매출 입력 DB 레이어
"""
import sqlite3
from shared.db import get_conn
from shared.config import BRANCH_LIST as _JSON_BRANCH_LIST


def _migrate_branches(conn):
    """branches 테이블에 컬럼 추가 (기존 DB 마이그레이션)"""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(branches)")}
    if "address" not in existing:
        conn.execute("ALTER TABLE branches ADD COLUMN address TEXT DEFAULT ''")
    if "lat" not in existing:
        conn.execute("ALTER TABLE branches ADD COLUMN lat REAL DEFAULT NULL")
    if "lng" not in existing:
        conn.execute("ALTER TABLE branches ADD COLUMN lng REAL DEFAULT NULL")
    if "attendance_radius" not in existing:
        conn.execute("ALTER TABLE branches ADD COLUMN attendance_radius INTEGER DEFAULT 300")
    conn.commit()


def init_branch_tables():
    """지점 관리 전용 테이블 생성 + JSON 지점 자동 시딩"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS branches (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            name             TEXT UNIQUE NOT NULL,
            contract_date    TEXT DEFAULT '',
            termination_date TEXT DEFAULT '',
            is_active        INTEGER DEFAULT 1,
            address          TEXT DEFAULT '',
            lat              REAL DEFAULT NULL,
            lng              REAL DEFAULT NULL,
            note             TEXT DEFAULT '',
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS branch_monthly_revenue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            branch       TEXT NOT NULL,
            dogeub       INTEGER DEFAULT 0,
            pt_sales     INTEGER DEFAULT 0,
            gx_sales     INTEGER DEFAULT 0,
            cafe_sales   INTEGER DEFAULT 0,
            golf_sales   INTEGER DEFAULT 0,
            facility_fee INTEGER DEFAULT 0,
            cafe_labor   INTEGER DEFAULT 0,
            other_sales  INTEGER DEFAULT 0,
            note         TEXT DEFAULT '',
            updated_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, branch)
        );
    """)
    conn.commit()
    _migrate_branches(conn)

    # JSON branch_list에 있는 지점 자동 등록 (없는 것만)
    for name in _JSON_BRANCH_LIST:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO branches (name) VALUES (?)", (name,)
            )
        except Exception:
            pass
    conn.commit()


def get_all_branches(active_only: bool = False) -> list[dict]:
    """전체(또는 활성) 지점 목록 반환"""
    conn = get_conn()
    q = "SELECT * FROM branches"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY id"
    cur  = conn.execute(q)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_active_branch_names() -> list[str]:
    """활성 지점 이름 목록 (드롭다운용). DB 실패 시 JSON 폴백"""
    try:
        conn = get_conn()
        cur  = conn.execute("SELECT name FROM branches WHERE is_active = 1 ORDER BY id")
        rows = cur.fetchall()
        conn.close()
        names = [r[0] for r in rows]
        return names if names else _JSON_BRANCH_LIST
    except Exception:
        return _JSON_BRANCH_LIST


def upsert_branch(data: dict) -> int:
    """지점 추가 또는 수정. id가 없으면 INSERT, 있으면 UPDATE"""
    conn = get_conn()
    lat = data.get("lat") or None
    lng = data.get("lng") or None
    if lat is not None:
        try:
            lat = float(lat)
        except (TypeError, ValueError):
            lat = None
    if lng is not None:
        try:
            lng = float(lng)
        except (TypeError, ValueError):
            lng = None

    radius = data.get("attendance_radius")
    try:
        radius = int(radius) if radius is not None else 300
    except (TypeError, ValueError):
        radius = 300

    if not data.get("id"):
        cur = conn.execute(
            """INSERT INTO branches
               (name, contract_date, termination_date, is_active, address, lat, lng, note, attendance_radius)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("name", "").strip(),
                data.get("contract_date", ""),
                data.get("termination_date", ""),
                1 if data.get("is_active", True) else 0,
                data.get("address", ""),
                lat, lng,
                data.get("note", ""),
                radius,
            ),
        )
        conn.commit()
        conn.close()
        return cur.lastrowid
    else:
        conn.execute(
            """UPDATE branches
               SET name=?, contract_date=?, termination_date=?, is_active=?,
                   address=?, lat=?, lng=?, note=?, attendance_radius=?
               WHERE id=?""",
            (
                data.get("name", "").strip(),
                data.get("contract_date", ""),
                data.get("termination_date", ""),
                1 if data.get("is_active", True) else 0,
                data.get("address", ""),
                lat, lng,
                data.get("note", ""),
                radius,
                int(data["id"]),
            ),
        )
        conn.commit()
        conn.close()
        return int(data["id"])


def upsert_branch_monthly_revenue(year: int, month: int, branch: str, data: dict):
    """월별 지점 매출 저장 (UPSERT)"""
    conn = get_conn()
    conn.execute(
        """INSERT INTO branch_monthly_revenue
               (year, month, branch, dogeub, pt_sales, gx_sales, cafe_sales,
                golf_sales, facility_fee, cafe_labor, other_sales, note, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
           ON CONFLICT(year, month, branch) DO UPDATE SET
               dogeub       = excluded.dogeub,
               pt_sales     = excluded.pt_sales,
               gx_sales     = excluded.gx_sales,
               cafe_sales   = excluded.cafe_sales,
               golf_sales   = excluded.golf_sales,
               facility_fee = excluded.facility_fee,
               cafe_labor   = excluded.cafe_labor,
               other_sales  = excluded.other_sales,
               note         = excluded.note,
               updated_at   = excluded.updated_at""",
        (
            year, month, branch,
            int(data.get("dogeub", 0) or 0),
            int(data.get("pt_sales", 0) or 0),
            int(data.get("gx_sales", 0) or 0),
            int(data.get("cafe_sales", 0) or 0),
            int(data.get("golf_sales", 0) or 0),
            int(data.get("facility_fee", 0) or 0),
            int(data.get("cafe_labor", 0) or 0),
            int(data.get("other_sales", 0) or 0),
            data.get("note", ""),
        ),
    )
    conn.commit()


def get_branch_by_name(name: str) -> dict | None:
    """지점명으로 지점 정보(위도·경도·반경 포함) 조회"""
    conn = get_conn()
    try:
        cur  = conn.execute("SELECT * FROM branches WHERE name=?", (name,))
        cols = [d[0] for d in cur.description]
        row  = cur.fetchone()
        return dict(zip(cols, row)) if row else None
    except Exception:
        return None
    finally:
        conn.close()


def get_branch_monthly_revenue(year: int, month: int) -> list[dict]:
    """해당 연/월의 지점별 매출 입력값 조회"""
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM branch_monthly_revenue WHERE year=? AND month=? ORDER BY branch",
        (year, month),
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]
