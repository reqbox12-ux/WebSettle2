"""
domains/branch_app/db.py — 지점 랜딩페이지 전용 DB 레이어
Phase 2: 운영관리 / Phase 3: 회원 CRM / Phase 4: 결제 / Phase 5: 문자
"""
import json
import base64
import requests as _req
from shared.db import get_conn


# ═══════════════════════════════════════════════════════════════
#  테이블 초기화
# ═══════════════════════════════════════════════════════════════
def init_branch_tables():
    conn = get_conn()
    conn.executescript("""
    PRAGMA foreign_keys = ON;

    -- ── Phase 2: 운영관리 ─────────────────────────────────────

    CREATE TABLE IF NOT EXISTS as_requests (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        branch        TEXT NOT NULL,
        title         TEXT NOT NULL,
        description   TEXT DEFAULT '',
        status        TEXT DEFAULT 'open',
        priority      TEXT DEFAULT 'normal',
        created_by    INTEGER,
        created_name  TEXT DEFAULT '',
        assigned_to   TEXT DEFAULT '',
        note          TEXT DEFAULT '',
        resolved_at   TEXT,
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS supply_requests (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        branch        TEXT NOT NULL,
        item_name     TEXT NOT NULL,
        quantity      INTEGER DEFAULT 1,
        unit          TEXT DEFAULT '개',
        reason        TEXT DEFAULT '',
        status        TEXT DEFAULT 'pending',
        created_by    INTEGER,
        created_name  TEXT DEFAULT '',
        approved_by   TEXT DEFAULT '',
        reject_reason TEXT DEFAULT '',
        deliver_date  TEXT DEFAULT '',
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS inventory_items (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        branch       TEXT NOT NULL,
        item_name    TEXT NOT NULL,
        category     TEXT DEFAULT '일반',
        quantity     INTEGER DEFAULT 0,
        min_quantity INTEGER DEFAULT 0,
        unit         TEXT DEFAULT '개',
        note         TEXT DEFAULT '',
        updated_at   TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(branch, item_name)
    );

    CREATE TABLE IF NOT EXISTS inventory_transactions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        item_id       INTEGER NOT NULL,
        tx_type       TEXT NOT NULL,
        quantity      INTEGER NOT NULL,
        employee_name TEXT DEFAULT '',
        note          TEXT DEFAULT '',
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS announcements (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        target_branch TEXT DEFAULT 'all',
        title         TEXT NOT NULL,
        content       TEXT DEFAULT '',
        priority      TEXT DEFAULT 'normal',
        created_by    TEXT DEFAULT '',
        expires_at    TEXT,
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS announcement_reads (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        announcement_id INTEGER NOT NULL,
        employee_id     INTEGER NOT NULL,
        read_at         TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(announcement_id, employee_id)
    );

    -- ── Phase 3: 회원 CRM ─────────────────────────────────────

    CREATE TABLE IF NOT EXISTS members (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        branch     TEXT NOT NULL,
        name       TEXT NOT NULL,
        phone      TEXT DEFAULT '',
        email      TEXT DEFAULT '',
        birth_date TEXT DEFAULT '',
        gender     TEXT DEFAULT '',
        join_date  TEXT DEFAULT (date('now','localtime')),
        status     TEXT DEFAULT 'active',
        pin        TEXT DEFAULT '',
        note       TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS membership_products (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        branch         TEXT NOT NULL,
        name           TEXT NOT NULL,
        product_type   TEXT DEFAULT 'period',
        duration_days  INTEGER DEFAULT 30,
        sessions       INTEGER DEFAULT 0,
        price          INTEGER DEFAULT 0,
        is_active      INTEGER DEFAULT 1,
        created_at     TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS memberships (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        member_id          INTEGER NOT NULL,
        product_id         INTEGER,
        product_name       TEXT DEFAULT '',
        start_date         TEXT NOT NULL,
        end_date           TEXT,
        remaining_sessions INTEGER DEFAULT 0,
        status             TEXT DEFAULT 'active',
        hold_start         TEXT,
        hold_end           TEXT,
        paid_amount        INTEGER DEFAULT 0,
        sold_by_name       TEXT DEFAULT '',
        note               TEXT DEFAULT '',
        created_at         TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS class_schedules (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        branch          TEXT NOT NULL,
        class_name      TEXT NOT NULL,
        instructor_name TEXT DEFAULT '',
        days            TEXT DEFAULT '',
        start_time      TEXT NOT NULL,
        end_time        TEXT NOT NULL,
        capacity        INTEGER DEFAULT 20,
        is_active       INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    );

    -- 통합 상품 (GX프로그램 / 레슨 / 일반상품)
    CREATE TABLE IF NOT EXISTS products (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        branch          TEXT NOT NULL,
        category        TEXT NOT NULL,          -- 'gx' | 'lesson' | 'goods'
        name            TEXT NOT NULL,
        price           INTEGER DEFAULT 0,
        instructor_name TEXT DEFAULT '',        -- gx
        days            TEXT DEFAULT '',        -- gx
        start_time      TEXT DEFAULT '',        -- gx
        end_time        TEXT DEFAULT '',        -- gx
        capacity        INTEGER DEFAULT 0,      -- gx
        lesson_type     TEXT DEFAULT '',        -- lesson: 'PT' | '골프레슨'
        sessions        INTEGER DEFAULT 0,      -- lesson: 횟수
        is_active       INTEGER DEFAULT 1,
        created_at      TEXT DEFAULT (datetime('now','localtime'))
    );

    -- 결제 기록 (CRM)
    CREATE TABLE IF NOT EXISTS sales (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        branch        TEXT NOT NULL,
        member_id     INTEGER DEFAULT 0,
        member_name   TEXT DEFAULT '',
        product_id    INTEGER DEFAULT 0,
        product_name  TEXT NOT NULL,
        category      TEXT DEFAULT '',          -- 'gx' | 'lesson' | 'goods'
        amount        INTEGER DEFAULT 0,
        pay_method    TEXT DEFAULT '카드',       -- '카드' | '현금' | '계좌이체'
        is_mgmt_fee   INTEGER DEFAULT 0,        -- 관리비 청구 대상 여부
        sold_by       TEXT DEFAULT '',
        sale_date     TEXT DEFAULT (date('now','localtime')),
        created_at    TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS class_reservations (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        schedule_id      INTEGER NOT NULL,
        member_id        INTEGER NOT NULL,
        member_name      TEXT DEFAULT '',
        reservation_date TEXT NOT NULL,
        status           TEXT DEFAULT 'reserved',
        checked_in_at    TEXT,
        created_at       TEXT DEFAULT (datetime('now','localtime')),
        UNIQUE(schedule_id, member_id, reservation_date)
    );

    -- ── Phase 4: 결제/POS ─────────────────────────────────────

    CREATE TABLE IF NOT EXISTS branch_products (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        branch     TEXT NOT NULL,
        name       TEXT NOT NULL,
        category   TEXT DEFAULT '기타',
        price      INTEGER NOT NULL DEFAULT 0,
        stock      INTEGER DEFAULT 0,
        is_active  INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sales_transactions (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        branch           TEXT NOT NULL,
        tx_type          TEXT DEFAULT 'pos',
        total_amount     INTEGER NOT NULL,
        payment_method   TEXT DEFAULT 'card',
        status           TEXT DEFAULT 'paid',
        toss_order_id    TEXT DEFAULT '',
        toss_payment_key TEXT DEFAULT '',
        member_id        INTEGER,
        member_name      TEXT DEFAULT '',
        employee_name    TEXT DEFAULT '',
        note             TEXT DEFAULT '',
        paid_at          TEXT DEFAULT (datetime('now','localtime')),
        created_at       TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sale_items (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        transaction_id INTEGER NOT NULL,
        item_type      TEXT DEFAULT 'product',
        item_id        INTEGER,
        item_name      TEXT NOT NULL,
        unit_price     INTEGER NOT NULL,
        quantity       INTEGER DEFAULT 1,
        total_price    INTEGER NOT NULL
    );

    CREATE TABLE IF NOT EXISTS payment_config (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        toss_client_key TEXT DEFAULT '',
        toss_secret_key TEXT DEFAULT '',
        updated_at      TEXT DEFAULT (datetime('now','localtime'))
    );

    -- ── Phase 5: 문자 (Aligo) ────────────────────────────────

    CREATE TABLE IF NOT EXISTS aligo_config (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        api_key    TEXT DEFAULT '',
        user_id    TEXT DEFAULT '',
        sender     TEXT DEFAULT '',
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sms_templates (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT NOT NULL,
        content    TEXT NOT NULL,
        sms_type   TEXT DEFAULT 'SMS',
        is_active  INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS sms_logs (
        id             INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id    INTEGER,
        recipient      TEXT NOT NULL,
        recipient_name TEXT DEFAULT '',
        content        TEXT NOT NULL,
        sms_type       TEXT DEFAULT 'SMS',
        status         TEXT DEFAULT 'pending',
        aligo_msg_id   TEXT DEFAULT '',
        error_msg      TEXT DEFAULT '',
        sent_by_name   TEXT DEFAULT '',
        sent_at        TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS auto_sms_rules (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        rule_name    TEXT NOT NULL,
        trigger_type TEXT NOT NULL,
        days_offset  INTEGER DEFAULT 0,
        template_id  INTEGER,
        is_active    INTEGER DEFAULT 1,
        created_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()
    conn.close()


def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    return dict(zip(cols, row)) if row else None


# ═══════════════════════════════════════════════════════════════
#  Phase 2: AS 요청
# ═══════════════════════════════════════════════════════════════
def get_as_requests(branch: str, status: str = None) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM as_requests WHERE branch=?"
    args = [branch]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY created_at DESC"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def create_as_request(data: dict) -> int:
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO as_requests (branch, title, description, priority, created_by, created_name)
        VALUES (?,?,?,?,?,?)
    """, (data["branch"], data["title"], data.get("description",""),
          data.get("priority","normal"), data.get("created_by"), data.get("created_name","")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_as_status(req_id: int, status: str, assigned_to: str = "", note: str = ""):
    conn = get_conn()
    resolved = "datetime('now','localtime')" if status == "done" else "NULL"
    conn.execute(f"""
        UPDATE as_requests
        SET status=?, assigned_to=?, note=?,
            resolved_at=({resolved})
        WHERE id=?
    """, (status, assigned_to, note, req_id))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 2: 비품 요청
# ═══════════════════════════════════════════════════════════════
def get_supply_requests(branch: str, status: str = None) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM supply_requests WHERE branch=?"
    args = [branch]
    if status:
        q += " AND status=?"
        args.append(status)
    q += " ORDER BY created_at DESC"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def create_supply_request(data: dict) -> int:
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO supply_requests
        (branch, item_name, quantity, unit, reason, created_by, created_name)
        VALUES (?,?,?,?,?,?,?)
    """, (data["branch"], data["item_name"], data.get("quantity",1),
          data.get("unit","개"), data.get("reason",""),
          data.get("created_by"), data.get("created_name","")))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def update_supply_status(req_id: int, status: str, approved_by: str = "",
                         reject_reason: str = "", deliver_date: str = ""):
    conn = get_conn()
    conn.execute("""
        UPDATE supply_requests
        SET status=?, approved_by=?, reject_reason=?, deliver_date=?
        WHERE id=?
    """, (status, approved_by, reject_reason, deliver_date, req_id))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 2: 재고
# ═══════════════════════════════════════════════════════════════
def get_inventory(branch: str) -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute(
        "SELECT * FROM inventory_items WHERE branch=? ORDER BY category, item_name",
        (branch,)
    ))
    conn.close()
    return res


def upsert_inventory_item(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE inventory_items
            SET item_name=?, category=?, min_quantity=?, unit=?, note=?,
                updated_at=datetime('now','localtime')
            WHERE id=?
        """, (data["item_name"], data.get("category","일반"),
              data.get("min_quantity",0), data.get("unit","개"),
              data.get("note",""), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT OR IGNORE INTO inventory_items
            (branch, item_name, category, quantity, min_quantity, unit, note)
            VALUES (?,?,?,?,?,?,?)
        """, (data["branch"], data["item_name"], data.get("category","일반"),
              data.get("quantity",0), data.get("min_quantity",0),
              data.get("unit","개"), data.get("note","")))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def adjust_inventory(item_id: int, tx_type: str, qty: int, emp_name: str, note: str = ""):
    conn = get_conn()
    delta = qty if tx_type == "in" else -qty
    conn.execute("""
        UPDATE inventory_items
        SET quantity = MAX(0, quantity + ?), updated_at=datetime('now','localtime')
        WHERE id=?
    """, (delta, item_id))
    conn.execute("""
        INSERT INTO inventory_transactions (item_id, tx_type, quantity, employee_name, note)
        VALUES (?,?,?,?,?)
    """, (item_id, tx_type, qty, emp_name, note))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 2: 공지사항
# ═══════════════════════════════════════════════════════════════
def get_announcements(branch: str) -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute("""
        SELECT * FROM announcements
        WHERE (target_branch='all' OR target_branch=?)
          AND (expires_at IS NULL OR expires_at >= date('now'))
        ORDER BY priority DESC, created_at DESC
    """, (branch,)))
    conn.close()
    return res


def create_announcement(data: dict) -> int:
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO announcements (target_branch, title, content, priority, created_by, expires_at)
        VALUES (?,?,?,?,?,?)
    """, (data.get("target_branch","all"), data["title"], data.get("content",""),
          data.get("priority","normal"), data.get("created_by",""),
          data.get("expires_at") or None))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def mark_announcement_read(ann_id: int, emp_id: int):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO announcement_reads (announcement_id, employee_id)
        VALUES (?,?)
    """, (ann_id, emp_id))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 3: 회원
# ═══════════════════════════════════════════════════════════════
def get_members(branch: str, status: str = None, search: str = "") -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM members WHERE branch=?"
    args = [branch]
    if status:
        q += " AND status=?"
        args.append(status)
    if search:
        q += " AND (name LIKE ? OR phone LIKE ?)"
        args += [f"%{search}%", f"%{search}%"]
    q += " ORDER BY name"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def get_member(member_id: int) -> dict | None:
    conn = get_conn()
    res  = _one(conn.execute("SELECT * FROM members WHERE id=?", (member_id,)))
    conn.close()
    return res


def upsert_member(data: dict) -> int:
    conn = get_conn()
    # PIN 자동 설정 (전화번호 뒷4자리)
    phone = data.get("phone","").replace("-","").replace(" ","")
    pin   = data.get("pin") or (phone[-4:] if len(phone) >= 4 else "")
    if data.get("id"):
        conn.execute("""
            UPDATE members SET name=?, phone=?, email=?, birth_date=?, gender=?,
                join_date=?, status=?, pin=?, note=?
            WHERE id=?
        """, (data["name"], data.get("phone",""), data.get("email",""),
              data.get("birth_date",""), data.get("gender",""),
              data.get("join_date",""), data.get("status","active"),
              pin, data.get("note",""), data["id"]))
        mid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO members (branch, name, phone, email, birth_date, gender, join_date, status, pin, note)
            VALUES (?,?,?,?,?,?,?,?,?,?)
        """, (data["branch"], data["name"], data.get("phone",""), data.get("email",""),
              data.get("birth_date",""), data.get("gender",""),
              data.get("join_date",""), data.get("status","active"),
              pin, data.get("note","")))
        mid = cur.lastrowid
    conn.commit()
    conn.close()
    return mid


# ═══════════════════════════════════════════════════════════════
#  Phase 3: 회원권 상품
# ═══════════════════════════════════════════════════════════════
def get_membership_products(branch: str, active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM membership_products WHERE branch=?"
    args = [branch]
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY name"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def upsert_membership_product(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE membership_products
            SET name=?, product_type=?, duration_days=?, sessions=?, price=?, is_active=?
            WHERE id=?
        """, (data["name"], data.get("product_type","period"),
              data.get("duration_days",30), data.get("sessions",0),
              data.get("price",0), data.get("is_active",1), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO membership_products (branch, name, product_type, duration_days, sessions, price)
            VALUES (?,?,?,?,?,?)
        """, (data["branch"], data["name"], data.get("product_type","period"),
              data.get("duration_days",30), data.get("sessions",0), data.get("price",0)))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ═══════════════════════════════════════════════════════════════
#  Phase 3: 회원권 등록
# ═══════════════════════════════════════════════════════════════
def get_member_memberships(member_id: int) -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute(
        "SELECT * FROM memberships WHERE member_id=? ORDER BY created_at DESC",
        (member_id,)
    ))
    conn.close()
    return res


def get_active_memberships(branch: str) -> list[dict]:
    """만료 임박 회원 포함 전체 활성 회원권"""
    conn = get_conn()
    res  = _rows(conn.execute("""
        SELECT m.*, mb.name as member_name, mb.phone as member_phone
        FROM memberships m
        JOIN members mb ON m.member_id = mb.id
        WHERE mb.branch=? AND m.status='active'
        ORDER BY m.end_date
    """, (branch,)))
    conn.close()
    return res


def create_membership(data: dict) -> int:
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO memberships
        (member_id, product_id, product_name, start_date, end_date,
         remaining_sessions, paid_amount, sold_by_name, note)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (data["member_id"], data.get("product_id"), data.get("product_name",""),
          data["start_date"], data.get("end_date"),
          data.get("remaining_sessions",0), data.get("paid_amount",0),
          data.get("sold_by_name",""), data.get("note","")))
    conn.commit()
    mid = cur.lastrowid
    conn.close()
    return mid


def hold_membership(membership_id: int, hold_start: str, hold_end: str):
    conn = get_conn()
    # 정지 기간만큼 end_date 연장
    conn.execute("""
        UPDATE memberships
        SET status='hold', hold_start=?, hold_end=?,
            end_date = date(end_date, '+' || (julianday(?) - julianday(?)) || ' days')
        WHERE id=?
    """, (hold_start, hold_end, hold_end, hold_start, membership_id))
    conn.commit()
    conn.close()


def expire_old_memberships():
    conn = get_conn()
    conn.execute("""
        UPDATE memberships SET status='expired'
        WHERE status='active' AND end_date < date('now') AND end_date IS NOT NULL
    """)
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 3: 수업 시간표 & 예약
# ═══════════════════════════════════════════════════════════════
def get_class_schedules(branch: str, active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM class_schedules WHERE branch=?"
    args = [branch]
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY start_time"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def upsert_class_schedule(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE class_schedules
            SET class_name=?, instructor_name=?, days=?, start_time=?, end_time=?, capacity=?, is_active=?
            WHERE id=?
        """, (data["class_name"], data.get("instructor_name",""),
              data.get("days",""), data["start_time"], data["end_time"],
              data.get("capacity",20), data.get("is_active",1), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO class_schedules (branch, class_name, instructor_name, days, start_time, end_time, capacity)
            VALUES (?,?,?,?,?,?,?)
        """, (data["branch"], data["class_name"], data.get("instructor_name",""),
              data.get("days",""), data["start_time"], data["end_time"],
              data.get("capacity",20)))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ═══════════════════════════════════════════════════════════════
#  상품 (GX / 레슨 / 일반상품) + 결제 기록
# ═══════════════════════════════════════════════════════════════
def get_products(branch: str, category: str = "", active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM products WHERE branch=?"
    args = [branch]
    if category:
        q += " AND category=?"
        args.append(category)
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY category, name"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def upsert_product(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE products
            SET name=?, price=?, instructor_name=?, days=?, start_time=?, end_time=?,
                capacity=?, lesson_type=?, sessions=?, is_active=?,
                pay_type=?, session_rate=?, instructor_employee_id=?
            WHERE id=?
        """, (data["name"], data.get("price", 0), data.get("instructor_name", ""),
              data.get("days", ""), data.get("start_time", ""), data.get("end_time", ""),
              data.get("capacity", 0), data.get("lesson_type", ""), data.get("sessions", 0),
              data.get("is_active", 1),
              data.get("pay_type", ""), data.get("session_rate", 0),
              data.get("instructor_employee_id", 0), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO products (branch, category, name, price, instructor_name, days,
                                  start_time, end_time, capacity, lesson_type, sessions,
                                  pay_type, session_rate, instructor_employee_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (data["branch"], data["category"], data["name"], data.get("price", 0),
              data.get("instructor_name", ""), data.get("days", ""),
              data.get("start_time", ""), data.get("end_time", ""),
              data.get("capacity", 0), data.get("lesson_type", ""), data.get("sessions", 0),
              data.get("pay_type", ""), data.get("session_rate", 0),
              data.get("instructor_employee_id", 0)))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def deactivate_product(product_id: int):
    conn = get_conn()
    conn.execute("UPDATE products SET is_active=0 WHERE id=?", (product_id,))
    conn.commit()
    conn.close()


def get_sales(branch: str, year: int = None, month: int = None, limit: int = 100) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM sales WHERE branch=?"
    args = [branch]
    if year and month:
        q += " AND sale_date LIKE ?"
        args.append(f"{year}-{month:02d}%")
    q += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def create_sale(data: dict) -> int:
    conn = get_conn()
    cur  = conn.execute("""
        INSERT INTO sales (branch, member_id, member_name, product_id, product_name,
                           category, amount, pay_method, is_mgmt_fee, sold_by, sale_date)
        VALUES (?,?,?,?,?,?,?,?,?,?,COALESCE(?, date('now','localtime')))
    """, (data["branch"], data.get("member_id", 0), data.get("member_name", ""),
          data.get("product_id", 0), data["product_name"], data.get("category", ""),
          data.get("amount", 0), data.get("pay_method", "카드"),
          data.get("is_mgmt_fee", 0), data.get("sold_by", ""),
          data.get("sale_date") or None))
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return rid


def get_reservations(schedule_id: int, date: str) -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute("""
        SELECT cr.*, m.phone as member_phone
        FROM class_reservations cr
        JOIN members m ON cr.member_id = m.id
        WHERE cr.schedule_id=? AND cr.reservation_date=?
        ORDER BY cr.created_at
    """, (schedule_id, date)))
    conn.close()
    return res


def reserve_class(schedule_id: int, member_id: int, member_name: str, res_date: str) -> tuple[bool, str]:
    conn = get_conn()
    try:
        # 정원 체크
        cap = conn.execute("SELECT capacity FROM class_schedules WHERE id=?",
                           (schedule_id,)).fetchone()
        cnt = conn.execute("""
            SELECT COUNT(*) FROM class_reservations
            WHERE schedule_id=? AND reservation_date=? AND status='reserved'
        """, (schedule_id, res_date)).fetchone()[0]
        if cap and cnt >= cap[0]:
            return False, "수업 정원이 초과되었습니다."
        conn.execute("""
            INSERT INTO class_reservations (schedule_id, member_id, member_name, reservation_date)
            VALUES (?,?,?,?)
        """, (schedule_id, member_id, member_name, res_date))
        conn.commit()
        return True, "예약 완료"
    except Exception as e:
        if "UNIQUE" in str(e):
            return False, "이미 예약된 수업입니다."
        return False, str(e)
    finally:
        conn.close()


def checkin_reservation(res_id: int):
    conn = get_conn()
    conn.execute("""
        UPDATE class_reservations
        SET status='checked_in', checked_in_at=datetime('now','localtime')
        WHERE id=?
    """, (res_id,))
    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════════════════════
#  Phase 4: 상품 관리
# ═══════════════════════════════════════════════════════════════
def get_branch_products(branch: str, active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM branch_products WHERE branch=?"
    args = [branch]
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY category, name"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


def upsert_branch_product(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE branch_products SET name=?, category=?, price=?, stock=?, is_active=?
            WHERE id=?
        """, (data["name"], data.get("category","기타"), data.get("price",0),
              data.get("stock",0), data.get("is_active",1), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO branch_products (branch, name, category, price, stock)
            VALUES (?,?,?,?,?)
        """, (data["branch"], data["name"], data.get("category","기타"),
              data.get("price",0), data.get("stock",0)))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ═══════════════════════════════════════════════════════════════
#  Phase 4: 결제/POS
# ═══════════════════════════════════════════════════════════════
def save_transaction(branch: str, items: list[dict], payment_method: str,
                     member_name: str, emp_name: str, note: str = "",
                     toss_order_id: str = "", toss_key: str = "") -> int:
    total = sum(i["total_price"] for i in items)
    conn  = get_conn()
    cur   = conn.execute("""
        INSERT INTO sales_transactions
        (branch, total_amount, payment_method, status, toss_order_id, toss_payment_key,
         member_name, employee_name, note, paid_at)
        VALUES (?,?,?,'paid',?,?,?,?,?,datetime('now','localtime'))
    """, (branch, total, payment_method, toss_order_id, toss_key,
          member_name, emp_name, note))
    tx_id = cur.lastrowid
    for item in items:
        conn.execute("""
            INSERT INTO sale_items (transaction_id, item_name, unit_price, quantity, total_price)
            VALUES (?,?,?,?,?)
        """, (tx_id, item["item_name"], item["unit_price"],
              item.get("quantity",1), item["total_price"]))
        # 재고 차감
        if item.get("product_id"):
            conn.execute("""
                UPDATE branch_products SET stock = MAX(0, stock - ?)
                WHERE id=?
            """, (item.get("quantity",1), item["product_id"]))
    conn.commit()
    conn.close()
    return tx_id


def get_sales(branch: str, date_from: str = None, date_to: str = None) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM sales_transactions WHERE branch=?"
    args = [branch]
    if date_from:
        q += " AND paid_at >= ?"
        args.append(date_from)
    if date_to:
        q += " AND paid_at <= ?"
        args.append(date_to + " 23:59:59")
    q += " ORDER BY paid_at DESC"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


# ═══════════════════════════════════════════════════════════════
#  Phase 4: Toss Payments 설정 & API
# ═══════════════════════════════════════════════════════════════
def get_payment_config() -> dict:
    conn = get_conn()
    row  = _one(conn.execute("SELECT * FROM payment_config ORDER BY id LIMIT 1"))
    conn.close()
    return row or {"toss_client_key": "", "toss_secret_key": ""}


def save_payment_config(client_key: str, secret_key: str):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM payment_config LIMIT 1").fetchone()
    if existing:
        conn.execute("""
            UPDATE payment_config
            SET toss_client_key=?, toss_secret_key=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (client_key, secret_key, existing[0]))
    else:
        conn.execute("""
            INSERT INTO payment_config (toss_client_key, toss_secret_key)
            VALUES (?,?)
        """, (client_key, secret_key))
    conn.commit()
    conn.close()


def toss_confirm_payment(payment_key: str, order_id: str, amount: int) -> dict:
    """Toss Payments 결제 승인 API 호출"""
    cfg = get_payment_config()
    secret = cfg.get("toss_secret_key","")
    if not secret:
        return {"error": "Toss 시크릿 키가 설정되지 않았습니다."}
    encoded = base64.b64encode(f"{secret}:".encode()).decode()
    try:
        resp = _req.post(
            "https://api.tosspayments.com/v1/payments/confirm",
            headers={"Authorization": f"Basic {encoded}", "Content-Type": "application/json"},
            json={"paymentKey": payment_key, "orderId": order_id, "amount": amount},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


def toss_cancel_payment(payment_key: str, reason: str = "취소") -> dict:
    """Toss Payments 결제 취소"""
    cfg = get_payment_config()
    secret = cfg.get("toss_secret_key","")
    if not secret:
        return {"error": "시크릿 키 없음"}
    encoded = base64.b64encode(f"{secret}:".encode()).decode()
    try:
        resp = _req.post(
            f"https://api.tosspayments.com/v1/payments/{payment_key}/cancel",
            headers={"Authorization": f"Basic {encoded}", "Content-Type": "application/json"},
            json={"cancelReason": reason},
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
#  Phase 5: Aligo SMS 설정 & 발송
# ═══════════════════════════════════════════════════════════════
def get_aligo_config() -> dict:
    conn = get_conn()
    row  = _one(conn.execute("SELECT * FROM aligo_config ORDER BY id LIMIT 1"))
    conn.close()
    return row or {"api_key": "", "user_id": "", "sender": ""}


def save_aligo_config(api_key: str, user_id: str, sender: str):
    conn = get_conn()
    existing = conn.execute("SELECT id FROM aligo_config LIMIT 1").fetchone()
    if existing:
        conn.execute("""
            UPDATE aligo_config SET api_key=?, user_id=?, sender=?, updated_at=datetime('now','localtime')
            WHERE id=?
        """, (api_key, user_id, sender, existing[0]))
    else:
        conn.execute("INSERT INTO aligo_config (api_key, user_id, sender) VALUES (?,?,?)",
                     (api_key, user_id, sender))
    conn.commit()
    conn.close()


def aligo_send(receiver: str, msg: str, title: str = "") -> dict:
    """Aligo SMS 발송 (단건)"""
    cfg = get_aligo_config()
    if not cfg.get("api_key"):
        return {"result_code": "-1", "message": "Aligo API 키가 설정되지 않았습니다."}
    msg_type = "SMS" if len(msg) <= 90 else "LMS"
    try:
        resp = _req.post(
            "https://apis.aligo.in/send/",
            data={
                "key":     cfg["api_key"],
                "user_id": cfg["user_id"],
                "sender":  cfg["sender"],
                "receiver": receiver,
                "msg":     msg,
                "msg_type": msg_type,
                "title":   title if msg_type == "LMS" else "",
            },
            timeout=10,
        )
        return resp.json()
    except Exception as e:
        return {"result_code": "-1", "message": str(e)}


def aligo_send_bulk(targets: list[dict], msg_template: str, title: str = "") -> list[dict]:
    """일괄 발송. targets = [{"phone": "...", "name": "...", ...}]"""
    results = []
    for t in targets:
        # 템플릿 변수 치환
        msg = msg_template
        for k, v in t.items():
            msg = msg.replace(f"{{{k}}}", str(v))
        res = aligo_send(t["phone"], msg, title)
        results.append({"name": t.get("name",""), "phone": t["phone"],
                        "status": "sent" if res.get("result_code") == "1" else "failed",
                        "msg": res.get("message","")})
    return results


def get_sms_templates(active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM sms_templates"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY name"
    res = _rows(conn.execute(q))
    conn.close()
    return res


def upsert_sms_template(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE sms_templates SET name=?, content=?, sms_type=?, is_active=?
            WHERE id=?
        """, (data["name"], data["content"], data.get("sms_type","SMS"),
              data.get("is_active",1), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO sms_templates (name, content, sms_type)
            VALUES (?,?,?)
        """, (data["name"], data["content"], data.get("sms_type","SMS")))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def log_sms(recipient: str, name: str, content: str, status: str,
            template_id: int = None, aligo_id: str = "", error: str = "",
            sent_by: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO sms_logs
        (template_id, recipient, recipient_name, content, status, aligo_msg_id, error_msg, sent_by_name)
        VALUES (?,?,?,?,?,?,?,?)
    """, (template_id, recipient, name, content, status, aligo_id, error, sent_by))
    conn.commit()
    conn.close()


def get_sms_logs(limit: int = 100) -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute(
        "SELECT * FROM sms_logs ORDER BY sent_at DESC LIMIT ?", (limit,)
    ))
    conn.close()
    return res


def get_auto_sms_rules() -> list[dict]:
    conn = get_conn()
    res  = _rows(conn.execute(
        "SELECT r.*, t.name as template_name FROM auto_sms_rules r "
        "LEFT JOIN sms_templates t ON r.template_id=t.id ORDER BY r.trigger_type"
    ))
    conn.close()
    return res


def upsert_auto_sms_rule(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""
            UPDATE auto_sms_rules SET rule_name=?, trigger_type=?, days_offset=?, template_id=?, is_active=?
            WHERE id=?
        """, (data["rule_name"], data["trigger_type"], data.get("days_offset",0),
              data.get("template_id"), data.get("is_active",1), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""
            INSERT INTO auto_sms_rules (rule_name, trigger_type, days_offset, template_id, is_active)
            VALUES (?,?,?,?,?)
        """, (data["rule_name"], data["trigger_type"], data.get("days_offset",0),
              data.get("template_id"), data.get("is_active",1)))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def run_auto_sms(branch: str, trigger_type: str, sent_by: str = "") -> list[dict]:
    """자동발송 규칙 실행. 반환: 발송 결과 목록"""
    rules  = [r for r in get_auto_sms_rules() if r["trigger_type"] == trigger_type and r["is_active"]]
    result = []
    for rule in rules:
        tpl = next((t for t in get_sms_templates() if t["id"] == rule["template_id"]), None)
        if not tpl:
            continue
        targets = []
        if trigger_type == "membership_expire":
            # 만료 D+days_offset 회원 (음수=D-N)
            from datetime import date, timedelta
            target_date = (date.today() + timedelta(days=rule["days_offset"])).strftime("%Y-%m-%d")
            ms = get_active_memberships(branch)
            for m in ms:
                if m.get("end_date") == target_date and m.get("member_phone"):
                    targets.append({"phone": m["member_phone"], "name": m["member_name"],
                                    "만료일": target_date, "지점명": branch})
        elif trigger_type == "birthday":
            from datetime import date
            today_md = date.today().strftime("-%m-%d")
            mems = get_members(branch)
            for m in mems:
                if m.get("birth_date","").endswith(today_md) and m.get("phone"):
                    targets.append({"phone": m["phone"], "name": m["name"], "지점명": branch})
        for t in targets:
            res = aligo_send(t["phone"], tpl["content"].format(**t))
            status = "sent" if res.get("result_code") == "1" else "failed"
            log_sms(t["phone"], t["name"], tpl["content"], status,
                    tpl["id"], str(res.get("msg_id","")), res.get("message",""), sent_by)
            result.append({"name": t["name"], "status": status})
    return result
