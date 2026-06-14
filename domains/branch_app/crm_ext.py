"""
domains/branch_app/crm_ext.py — CRM 확장 스키마/로직 (Phase 3~6)

- Phase 3: 상품 정산설정(products.pay_type/session_rate), GX 구간제(gx_pay_rules), 결제수단/VAT
- Phase 4: PT/레슨 라이프사이클(lesson_enrollments, lesson_sessions, 회원 서명)
- Phase 5: GX 출석(gx_enrollments, gx_attendance), 프로필/커리큘럼/피드백
- Phase 6: 페이롤 집계(crm_payroll), 일일보고/환불/민원/의견, 재고 임계치
"""
from shared.db import get_conn


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(cur):
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def init_crm_ext_tables():
    conn = get_conn()

    # ── Phase 3: 상품 정산설정 ───────────────────────────────
    pcols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
    if "pay_type" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN pay_type TEXT DEFAULT ''")     # 'percent'|'per_session'|''
    if "session_rate" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN session_rate INTEGER DEFAULT 0")
    if "instructor_employee_id" not in pcols:
        conn.execute("ALTER TABLE products ADD COLUMN instructor_employee_id INTEGER DEFAULT 0")  # GX 담당강사

    # 재고 임계치 (Phase 6 자동알림)
    icols = [r[1] for r in conn.execute("PRAGMA table_info(inventory_items)").fetchall()]
    if icols and "min_qty" not in icols:
        conn.execute("ALTER TABLE inventory_items ADD COLUMN min_qty INTEGER DEFAULT 0")

    conn.executescript("""
        -- GX 인원 구간제 인센티브
        CREATE TABLE IF NOT EXISTS gx_pay_rules (
            product_id       INTEGER PRIMARY KEY,
            base_amount      INTEGER DEFAULT 0,
            base_headcount   INTEGER DEFAULT 0,
            extra_per_person INTEGER DEFAULT 0
        );

        -- ── Phase 4: PT/레슨 라이프사이클 ──────────────────────
        CREATE TABLE IF NOT EXISTS lesson_enrollments (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            branch                 TEXT NOT NULL,
            member_id              INTEGER NOT NULL,
            member_name            TEXT DEFAULT '',
            product_id             INTEGER DEFAULT 0,
            product_name           TEXT DEFAULT '',
            lesson_type            TEXT DEFAULT 'PT',     -- 'PT'|'골프레슨'
            instructor_employee_id INTEGER DEFAULT 0,     -- 담당강사 (변경가능)
            instructor_name        TEXT DEFAULT '',
            total_sessions         INTEGER DEFAULT 0,
            used_sessions          INTEGER DEFAULT 0,
            pay_type               TEXT DEFAULT '',        -- 스냅샷
            session_rate           INTEGER DEFAULT 0,
            percent_snapshot       REAL DEFAULT 0,
            base_amount            INTEGER DEFAULT 0,      -- 상품가액(VAT제외) — %정산 기준
            pay_method             TEXT DEFAULT '카드',
            sale_id                INTEGER DEFAULT 0,
            status                 TEXT DEFAULT 'active',  -- 'active'|'done'|'refunded'
            created_at             TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS lesson_sessions (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            enrollment_id          INTEGER NOT NULL,
            branch                 TEXT NOT NULL,
            member_id              INTEGER NOT NULL,
            instructor_employee_id INTEGER DEFAULT 0,
            scheduled_date         TEXT DEFAULT '',
            scheduled_time         TEXT DEFAULT '',
            status                 TEXT DEFAULT 'reserved', -- reserved|pending_sign|completed|no_show|canceled
            completed_at           TEXT,
            signed_at              TEXT,
            signature_png          TEXT DEFAULT '',
            payroll_period         TEXT DEFAULT '',         -- 'YYYY-MM'
            created_at             TEXT DEFAULT (datetime('now','localtime'))
        );

        -- ── Phase 5: GX 출석 / 프로필 / 커리큘럼 / 피드백 ───────
        CREATE TABLE IF NOT EXISTS gx_enrollments (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            branch        TEXT NOT NULL,
            gx_product_id INTEGER NOT NULL,
            member_id     INTEGER NOT NULL,
            member_name   TEXT DEFAULT '',
            sale_id       INTEGER DEFAULT 0,
            status        TEXT DEFAULT 'active',
            created_at    TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS gx_attendance (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            gx_product_id INTEGER NOT NULL,
            session_date  TEXT NOT NULL,
            member_id     INTEGER NOT NULL,
            present       INTEGER DEFAULT 1,
            checked_by    INTEGER DEFAULT 0,
            branch        TEXT DEFAULT '',
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(gx_product_id, session_date, member_id)
        );

        CREATE TABLE IF NOT EXISTS instructor_profiles (
            employee_id INTEGER PRIMARY KEY,
            photo_png   TEXT DEFAULT '',
            intro       TEXT DEFAULT '',
            career      TEXT DEFAULT '',
            specialty   TEXT DEFAULT '',
            updated_at  TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS curriculums (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id   INTEGER DEFAULT 0,
            gx_product_id INTEGER DEFAULT 0,
            title         TEXT DEFAULT '',
            body          TEXT DEFAULT '',
            branch        TEXT DEFAULT '',
            updated_at    TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS lesson_feedback (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id             INTEGER DEFAULT 0,
            enrollment_id          INTEGER DEFAULT 0,
            member_id              INTEGER NOT NULL,
            instructor_employee_id INTEGER DEFAULT 0,
            content                TEXT DEFAULT '',
            created_at             TEXT DEFAULT (datetime('now','localtime'))
        );

        -- ── Phase 6: 페이롤 / 일일보고 / 환불 / 민원 / 의견 ─────
        CREATE TABLE IF NOT EXISTS crm_payroll (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            year             INTEGER NOT NULL,
            month            INTEGER NOT NULL,
            employee_id      INTEGER NOT NULL,
            branch           TEXT DEFAULT '',
            pt_session_count INTEGER DEFAULT 0,
            pt_amount        INTEGER DEFAULT 0,
            gx_session_count INTEGER DEFAULT 0,
            gx_amount        INTEGER DEFAULT 0,
            total_amount     INTEGER DEFAULT 0,
            status           TEXT DEFAULT 'draft',   -- 'draft'|'confirmed'
            confirmed_by     TEXT DEFAULT '',
            confirmed_at     TEXT,
            updated_at       TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, employee_id)
        );

        CREATE TABLE IF NOT EXISTS daily_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            branch      TEXT DEFAULT '',
            report_date TEXT NOT NULL,
            comment     TEXT DEFAULT '',
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, report_date)
        );

        CREATE TABLE IF NOT EXISTS refund_requests (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            branch           TEXT DEFAULT '',
            sale_id          INTEGER DEFAULT 0,
            enrollment_id    INTEGER DEFAULT 0,
            member_id        INTEGER DEFAULT 0,
            member_name      TEXT DEFAULT '',
            reason           TEXT DEFAULT '',
            paid_amount      INTEGER DEFAULT 0,
            used_sessions    INTEGER DEFAULT 0,
            total_sessions   INTEGER DEFAULT 0,
            suggested_amount INTEGER DEFAULT 0,
            final_amount     INTEGER DEFAULT 0,
            status           TEXT DEFAULT 'open',    -- 'open'|'done'
            requested_by     INTEGER DEFAULT 0,
            approval_item_id INTEGER DEFAULT 0,
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS member_complaints (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            branch           TEXT DEFAULT '',
            member_id        INTEGER DEFAULT 0,
            member_name      TEXT DEFAULT '',
            content          TEXT DEFAULT '',
            status           TEXT DEFAULT 'open',
            created_by       INTEGER DEFAULT 0,
            approval_item_id INTEGER DEFAULT 0,
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS product_suggestions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            branch           TEXT DEFAULT '',
            employee_id      INTEGER DEFAULT 0,
            employee_name    TEXT DEFAULT '',
            content          TEXT DEFAULT '',
            status           TEXT DEFAULT 'open',
            approval_item_id INTEGER DEFAULT 0,
            created_at       TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()


# ── Phase 3: 결제수단/VAT 헬퍼 ───────────────────────────────
def charge_amount(base_amount: int, pay_method: str) -> int:
    """회원 청구액 — 카드결제만 VAT(10%) 가산. 정산기준은 항상 base_amount."""
    base = int(base_amount or 0)
    if (pay_method or "").strip() in ("카드", "card"):
        return round(base * 1.1)
    return base


# ── Phase 3: GX 구간제 룰 ────────────────────────────────────
def set_gx_pay_rule(product_id: int, base_amount: int, base_headcount: int, extra_per_person: int):
    conn = get_conn()
    conn.execute("""
        INSERT INTO gx_pay_rules (product_id, base_amount, base_headcount, extra_per_person)
        VALUES (?,?,?,?)
        ON CONFLICT(product_id) DO UPDATE SET
            base_amount=excluded.base_amount,
            base_headcount=excluded.base_headcount,
            extra_per_person=excluded.extra_per_person
    """, (product_id, int(base_amount or 0), int(base_headcount or 0), int(extra_per_person or 0)))
    conn.commit()
    conn.close()


def get_gx_pay_rule(product_id: int) -> dict | None:
    conn = get_conn()
    r = _one(conn.execute("SELECT * FROM gx_pay_rules WHERE product_id=?", (product_id,)))
    conn.close()
    return r


def gx_session_pay(product_id: int, headcount: int) -> int:
    """GX 1회 수업 정산액 = base + max(0, 출석-base_headcount) × extra."""
    rule = get_gx_pay_rule(product_id)
    if not rule:
        return 0
    extra = max(0, int(headcount) - int(rule["base_headcount"])) * int(rule["extra_per_person"])
    return int(rule["base_amount"]) + extra


# ── Phase 4: PT/레슨 수강권(enrollment) + 세션 라이프사이클 ──────────
_SESSION_LIVE = ("reserved", "pending_sign", "completed", "no_show")  # 슬롯 점유 상태


def create_lesson_enrollment(*, branch, member_id, member_name, product, sale_id,
                             instructor_employee_id, instructor_name, pay_method) -> int:
    """PT/레슨 상품 판매 시 수강권 생성. 정산조건은 판매시점 스냅샷."""
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO lesson_enrollments
        (branch, member_id, member_name, product_id, product_name, lesson_type,
         instructor_employee_id, instructor_name, total_sessions, used_sessions,
         pay_type, session_rate, percent_snapshot, base_amount, pay_method, sale_id, status)
        VALUES (?,?,?,?,?,?,?,?,?,0,?,?,?,?,?,?, 'active')
    """, (branch, member_id, member_name,
          product.get("id", 0), product.get("name", ""),
          product.get("lesson_type", "PT"),
          instructor_employee_id, instructor_name,
          int(product.get("sessions", 0) or 0),
          product.get("pay_type", ""), int(product.get("session_rate", 0) or 0),
          float(product.get("_commission_percent", 0) or 0),
          int(product.get("price", 0) or 0), pay_method, sale_id))
    eid = cur.lastrowid
    conn.commit()
    conn.close()
    return eid


def get_enrollments(branch: str = "", member_id: int = 0, instructor_id: int = 0,
                    status: str = "") -> list[dict]:
    q = "SELECT * FROM lesson_enrollments WHERE 1=1"
    p: list = []
    if branch:        q += " AND branch=?"; p.append(branch)
    if member_id:     q += " AND member_id=?"; p.append(member_id)
    if instructor_id: q += " AND instructor_employee_id=?"; p.append(instructor_id)
    if status:        q += " AND status=?"; p.append(status)
    q += " ORDER BY id DESC"
    conn = get_conn()
    out = _rows(conn.execute(q, p))
    conn.close()
    return out


def get_enrollment(enrollment_id: int) -> dict | None:
    conn = get_conn()
    r = _one(conn.execute("SELECT * FROM lesson_enrollments WHERE id=?", (enrollment_id,)))
    conn.close()
    return r


def change_enrollment_instructor(enrollment_id: int, emp_id: int, name: str):
    conn = get_conn()
    conn.execute(
        "UPDATE lesson_enrollments SET instructor_employee_id=?, instructor_name=? WHERE id=?",
        (emp_id, name, enrollment_id))
    # 미진행(reserved/pending) 세션의 담당강사도 동기화
    conn.execute("""UPDATE lesson_sessions SET instructor_employee_id=?
                    WHERE enrollment_id=? AND status IN ('reserved','pending_sign')""",
                 (emp_id, enrollment_id))
    conn.commit()
    conn.close()


def _live_session_count(conn, enrollment_id: int) -> int:
    ph = ",".join("?" * len(_SESSION_LIVE))
    row = conn.execute(
        f"SELECT COUNT(*) FROM lesson_sessions WHERE enrollment_id=? AND status IN ({ph})",
        (enrollment_id, *_SESSION_LIVE)).fetchone()
    return row[0] if row else 0


def reserve_session(enrollment_id: int, date: str, time: str = "") -> tuple[bool, str]:
    """세션 예약. 총 횟수 초과 불가(취소분은 재예약 가능)."""
    conn = get_conn()
    enr = _one(conn.execute("SELECT * FROM lesson_enrollments WHERE id=?", (enrollment_id,)))
    if not enr:
        conn.close(); return False, "수강권을 찾을 수 없습니다"
    if _live_session_count(conn, enrollment_id) >= int(enr["total_sessions"]):
        conn.close(); return False, "예약 가능한 횟수를 모두 사용했습니다"
    conn.execute("""
        INSERT INTO lesson_sessions
        (enrollment_id, branch, member_id, instructor_employee_id, scheduled_date, scheduled_time, status)
        VALUES (?,?,?,?,?,?, 'reserved')
    """, (enrollment_id, enr["branch"], enr["member_id"],
          enr["instructor_employee_id"], date, time))
    conn.commit()
    conn.close()
    return True, "예약되었습니다"


def cancel_session(session_id: int) -> bool:
    conn = get_conn()
    conn.execute("UPDATE lesson_sessions SET status='canceled' WHERE id=? AND status='reserved'",
                 (session_id,))
    ok = conn.total_changes > 0
    conn.commit()
    conn.close()
    return ok


def complete_session(session_id: int) -> bool:
    """강사 '진행완료' → 회원 서명 대기."""
    conn = get_conn()
    conn.execute("""UPDATE lesson_sessions
                    SET status='pending_sign', completed_at=datetime('now','localtime')
                    WHERE id=? AND status='reserved'""", (session_id,))
    ok = conn.total_changes > 0
    conn.commit()
    conn.close()
    return ok


def _consume_one(conn, enrollment_id: int):
    conn.execute("UPDATE lesson_enrollments SET used_sessions=used_sessions+1 WHERE id=?",
                 (enrollment_id,))
    enr = _one(conn.execute("SELECT total_sessions, used_sessions FROM lesson_enrollments WHERE id=?",
                            (enrollment_id,)))
    if enr and enr["used_sessions"] >= enr["total_sessions"]:
        conn.execute("UPDATE lesson_enrollments SET status='done' WHERE id=?", (enrollment_id,))


def sign_session(session_id: int, signature_png: str) -> tuple[bool, str]:
    """회원 캔버스 서명 → 완료 확정 + 1회 차감 + 페이롤 기간 기록."""
    conn = get_conn()
    s = _one(conn.execute("SELECT * FROM lesson_sessions WHERE id=?", (session_id,)))
    if not s or s["status"] != "pending_sign":
        conn.close(); return False, "서명 대기 상태가 아닙니다"
    period = (s["completed_at"] or "")[:7] or _today_period()
    conn.execute("""UPDATE lesson_sessions
                    SET status='completed', signature_png=?, signed_at=datetime('now','localtime'),
                        payroll_period=? WHERE id=?""", (signature_png, period, session_id))
    _consume_one(conn, s["enrollment_id"])
    conn.commit()
    conn.close()
    return True, "수업이 완료 처리되었습니다"


def no_show_session(session_id: int) -> tuple[bool, str]:
    """강사 노쇼 처리 → 서명 없이 진행 인정 + 1회 차감 + 페이롤 포함."""
    conn = get_conn()
    s = _one(conn.execute("SELECT * FROM lesson_sessions WHERE id=?", (session_id,)))
    if not s or s["status"] not in ("reserved", "pending_sign"):
        conn.close(); return False, "처리할 수 없는 상태입니다"
    period = _today_period()
    conn.execute("""UPDATE lesson_sessions
                    SET status='no_show', completed_at=datetime('now','localtime'),
                        payroll_period=? WHERE id=?""", (period, session_id))
    _consume_one(conn, s["enrollment_id"])
    conn.commit()
    conn.close()
    return True, "노쇼 처리되었습니다 (진행 인정)"


def get_sessions(enrollment_id: int) -> list[dict]:
    conn = get_conn()
    out = _rows(conn.execute(
        "SELECT * FROM lesson_sessions WHERE enrollment_id=? ORDER BY scheduled_date, id",
        (enrollment_id,)))
    conn.close()
    return out


def get_member_sessions(member_id: int, statuses: tuple = ()) -> list[dict]:
    q = """SELECT s.*, e.product_name, e.instructor_name, e.lesson_type
           FROM lesson_sessions s JOIN lesson_enrollments e ON e.id=s.enrollment_id
           WHERE s.member_id=?"""
    p: list = [member_id]
    if statuses:
        q += f" AND s.status IN ({','.join('?'*len(statuses))})"; p += list(statuses)
    q += " ORDER BY s.scheduled_date, s.id"
    conn = get_conn()
    out = _rows(conn.execute(q, p))
    conn.close()
    return out


def _today_period() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m")


def get_product(product_id: int) -> dict | None:
    conn = get_conn()
    r = _one(conn.execute("SELECT * FROM products WHERE id=?", (product_id,)))
    conn.close()
    return r


def create_gx_enrollment(*, branch, gx_product_id, member_id, member_name, sale_id) -> int:
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO gx_enrollments (branch, gx_product_id, member_id, member_name, sale_id, status)
        VALUES (?,?,?,?,?, 'active')
    """, (branch, gx_product_id, member_id, member_name, sale_id))
    rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


# ── Phase 5: GX 출석 / 프로필 / 커리큘럼 / 피드백 ─────────────────
def get_gx_members(gx_product_id: int) -> list[dict]:
    conn = get_conn()
    out = _rows(conn.execute(
        "SELECT * FROM gx_enrollments WHERE gx_product_id=? AND status='active' ORDER BY member_name",
        (gx_product_id,)))
    conn.close()
    return out


def get_gx_classes_for_instructor(employee_id: int, branch: str) -> list[dict]:
    """GX강사가 담당하는 GX상품 목록 (수업관리용)."""
    conn = get_conn()
    out = _rows(conn.execute("""
        SELECT * FROM products
        WHERE category='gx' AND is_active=1 AND branch=? AND instructor_employee_id=?
        ORDER BY name
    """, (branch, employee_id)))
    conn.close()
    return out


def mark_gx_attendance(gx_product_id: int, session_date: str, member_id: int,
                       present: int, checked_by: int, branch: str = ""):
    conn = get_conn()
    conn.execute("""
        INSERT INTO gx_attendance (gx_product_id, session_date, member_id, present, checked_by, branch)
        VALUES (?,?,?,?,?,?)
        ON CONFLICT(gx_product_id, session_date, member_id)
        DO UPDATE SET present=excluded.present, checked_by=excluded.checked_by
    """, (gx_product_id, session_date, member_id, present, checked_by, branch))
    conn.commit()
    conn.close()


def get_gx_attendance(gx_product_id: int, session_date: str) -> list[dict]:
    conn = get_conn()
    out = _rows(conn.execute(
        "SELECT * FROM gx_attendance WHERE gx_product_id=? AND session_date=?",
        (gx_product_id, session_date)))
    conn.close()
    return out


def upsert_instructor_profile(employee_id: int, data: dict):
    conn = get_conn()
    conn.execute("""
        INSERT INTO instructor_profiles (employee_id, photo_png, intro, career, specialty, updated_at)
        VALUES (?,?,?,?,?, datetime('now','localtime'))
        ON CONFLICT(employee_id) DO UPDATE SET
            photo_png=excluded.photo_png, intro=excluded.intro,
            career=excluded.career, specialty=excluded.specialty,
            updated_at=datetime('now','localtime')
    """, (employee_id, data.get("photo_png", ""), data.get("intro", ""),
          data.get("career", ""), data.get("specialty", "")))
    conn.commit()
    conn.close()


def get_instructor_profile(employee_id: int) -> dict | None:
    conn = get_conn()
    r = _one(conn.execute("SELECT * FROM instructor_profiles WHERE employee_id=?", (employee_id,)))
    conn.close()
    return r


def upsert_curriculum(data: dict) -> int:
    conn = get_conn()
    if data.get("id"):
        conn.execute("""UPDATE curriculums SET title=?, body=?, updated_at=datetime('now','localtime')
                        WHERE id=?""", (data.get("title",""), data.get("body",""), data["id"]))
        rid = data["id"]
    else:
        cur = conn.execute("""INSERT INTO curriculums (employee_id, gx_product_id, title, body, branch)
                              VALUES (?,?,?,?,?)""",
                           (data.get("employee_id",0), data.get("gx_product_id",0),
                            data.get("title",""), data.get("body",""), data.get("branch","")))
        rid = cur.lastrowid
    conn.commit()
    conn.close()
    return rid


def get_curriculums(employee_id: int = 0, gx_product_id: int = 0, branch: str = "") -> list[dict]:
    q = "SELECT * FROM curriculums WHERE 1=1"; p = []
    if employee_id: q += " AND employee_id=?"; p.append(employee_id)
    if gx_product_id: q += " AND gx_product_id=?"; p.append(gx_product_id)
    if branch: q += " AND branch=?"; p.append(branch)
    q += " ORDER BY id DESC"
    conn = get_conn(); out = _rows(conn.execute(q, p)); conn.close()
    return out


def add_feedback(*, member_id, instructor_employee_id, content, session_id=0, enrollment_id=0) -> int:
    conn = get_conn()
    cur = conn.execute("""INSERT INTO lesson_feedback
        (session_id, enrollment_id, member_id, instructor_employee_id, content)
        VALUES (?,?,?,?,?)""",
        (session_id, enrollment_id, member_id, instructor_employee_id, content))
    rid = cur.lastrowid
    conn.commit(); conn.close()
    return rid


def get_member_feedback(member_id: int) -> list[dict]:
    conn = get_conn()
    out = _rows(conn.execute(
        "SELECT * FROM lesson_feedback WHERE member_id=? ORDER BY id DESC", (member_id,)))
    conn.close()
    return out


# ── Phase 6: 페이롤 집계 ─────────────────────────────────────────
def compute_crm_payroll(year: int, month: int, branch: str = "") -> list[dict]:
    """월별 강사 보수 집계 → crm_payroll draft 갱신. (확정분은 건드리지 않음)"""
    period = f"{year:04d}-{month:02d}"
    conn = get_conn()
    agg: dict = {}   # employee_id -> {pt_cnt, pt_amt, gx_cnt, gx_amt, branch}

    def slot(eid, br):
        if eid not in agg:
            agg[eid] = {"pt_cnt": 0, "pt_amt": 0, "gx_cnt": 0, "gx_amt": 0, "branch": br}
        return agg[eid]

    # PT/레슨: 완료/노쇼 세션
    q = """SELECT s.instructor_employee_id AS eid, s.branch AS br,
                  e.pay_type, e.session_rate, e.percent_snapshot, e.base_amount, e.total_sessions
           FROM lesson_sessions s JOIN lesson_enrollments e ON e.id=s.enrollment_id
           WHERE s.status IN ('completed','no_show') AND s.payroll_period=?"""
    p = [period]
    if branch:
        q += " AND s.branch=?"; p.append(branch)
    for r in conn.execute(q, p).fetchall():
        eid, br, pay_type, srate, pct, base, total = r
        if not eid:
            continue
        if pay_type == "per_session":
            pay = int(srate or 0)
        elif pay_type == "percent":
            per = (int(base or 0) / int(total)) if total else 0
            pay = round(per * float(pct or 0) / 100.0)
        else:
            pay = 0
        s = slot(eid, br); s["pt_cnt"] += 1; s["pt_amt"] += pay

    # GX: 월내 (상품, 날짜)별 출석인원 → 구간제, 상품 담당강사에 귀속
    q2 = """SELECT a.gx_product_id, a.session_date, a.branch,
                   SUM(CASE WHEN a.present=1 THEN 1 ELSE 0 END) AS headcount,
                   pr.instructor_employee_id
            FROM gx_attendance a JOIN products pr ON pr.id=a.gx_product_id
            WHERE substr(a.session_date,1,7)=?"""
    p2 = [period]
    if branch:
        q2 += " AND a.branch=?"; p2.append(branch)
    q2 += " GROUP BY a.gx_product_id, a.session_date"
    for gx_pid, sdate, br, headcount, inst in conn.execute(q2, p2).fetchall():
        if not inst:
            continue
        pay = gx_session_pay(gx_pid, headcount or 0)
        s = slot(inst, br or ""); s["gx_cnt"] += 1; s["gx_amt"] += pay

    # draft 업서트 (확정된 행은 스킵)
    for eid, v in agg.items():
        total_amt = v["pt_amt"] + v["gx_amt"]
        row = _one(conn.execute(
            "SELECT id, status FROM crm_payroll WHERE year=? AND month=? AND employee_id=?",
            (year, month, eid)))
        if row and row["status"] == "confirmed":
            continue
        conn.execute("""
            INSERT INTO crm_payroll
            (year, month, employee_id, branch, pt_session_count, pt_amount,
             gx_session_count, gx_amount, total_amount, status, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?, 'draft', datetime('now','localtime'))
            ON CONFLICT(year, month, employee_id) DO UPDATE SET
                branch=excluded.branch, pt_session_count=excluded.pt_session_count,
                pt_amount=excluded.pt_amount, gx_session_count=excluded.gx_session_count,
                gx_amount=excluded.gx_amount, total_amount=excluded.total_amount,
                updated_at=datetime('now','localtime')
        """, (year, month, eid, v["branch"], v["pt_cnt"], v["pt_amt"],
              v["gx_cnt"], v["gx_amt"], total_amt))
    conn.commit()
    conn.close()
    return get_crm_payroll(year, month, branch)


def get_crm_payroll(year: int, month: int, branch: str = "", employee_id: int = 0) -> list[dict]:
    q = """SELECT cp.*, e.name AS employee_name
           FROM crm_payroll cp LEFT JOIN employees e ON e.id=cp.employee_id
           WHERE cp.year=? AND cp.month=?"""
    p = [year, month]
    if branch: q += " AND cp.branch=?"; p.append(branch)
    if employee_id: q += " AND cp.employee_id=?"; p.append(employee_id)
    q += " ORDER BY cp.total_amount DESC"
    conn = get_conn(); out = _rows(conn.execute(q, p)); conn.close()
    return out


def confirm_crm_payroll(year: int, month: int, admin_name: str, branch: str = "") -> int:
    conn = get_conn()
    q = """UPDATE crm_payroll SET status='confirmed', confirmed_by=?,
           confirmed_at=datetime('now','localtime') WHERE year=? AND month=? AND status='draft'"""
    p = [admin_name, year, month]
    if branch: q += " AND branch=?"; p.append(branch)
    conn.execute(q, p)
    n = conn.total_changes
    conn.commit(); conn.close()
    return n


# ── Phase 6: 일일보고 (자동집계 + 코멘트) ────────────────────────
def daily_report_autodata(employee_id: int, branch: str, date_str: str) -> dict:
    """그날의 내 매출 + 진행 수업 자동 집계."""
    conn = get_conn()
    sales = _rows(conn.execute(
        "SELECT * FROM sales WHERE branch=? AND sale_date=? AND sold_by=(SELECT name FROM employees WHERE id=?)",
        (branch, date_str, employee_id)))
    sess = _rows(conn.execute("""
        SELECT s.*, e.product_name, e.member_name FROM lesson_sessions s
        JOIN lesson_enrollments e ON e.id=s.enrollment_id
        WHERE s.instructor_employee_id=? AND s.status IN ('completed','no_show')
              AND substr(COALESCE(s.completed_at,''),1,10)=?""", (employee_id, date_str)))
    conn.close()
    return {
        "sales": sales, "sales_total": sum(x.get("amount", 0) for x in sales),
        "sessions": sess, "session_count": len(sess),
    }


def save_daily_report(employee_id: int, branch: str, date_str: str, comment: str):
    conn = get_conn()
    conn.execute("""INSERT INTO daily_reports (employee_id, branch, report_date, comment)
                    VALUES (?,?,?,?)
                    ON CONFLICT(employee_id, report_date)
                    DO UPDATE SET comment=excluded.comment""",
                 (employee_id, branch, date_str, comment))
    conn.commit(); conn.close()


def get_daily_report(employee_id: int, date_str: str) -> dict | None:
    conn = get_conn()
    r = _one(conn.execute(
        "SELECT * FROM daily_reports WHERE employee_id=? AND report_date=?",
        (employee_id, date_str)))
    conn.close()
    return r


# ── Phase 6: 환불 계산 ───────────────────────────────────────────
def refund_suggestion(paid_amount: int, base_amount: int, total_sessions: int,
                      used_sessions: int, penalty_rate: float = 0.10) -> int:
    """기본 제안 환불액 = 결제액 - 사용회차분 - 위약금(최대 10%)."""
    used_value = (int(base_amount or 0) / total_sessions * used_sessions) if total_sessions else 0
    penalty = int(paid_amount or 0) * penalty_rate
    return max(0, round(int(paid_amount or 0) - used_value - penalty))
