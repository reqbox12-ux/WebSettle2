"""
domains/payroll/db.py — 급여 도메인 전용 DB 테이블 초기화 및 쿼리
"""
import sqlite3
from shared.db import get_conn


def _migrate_employees_emp_type(conn):
    """기존 employees 테이블의 emp_type 제약을 business/tax_exempt 포함으로 마이그레이션"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='employees'"
    ).fetchone()
    if not row or "'business'" in row[0]:
        return
    conn.executescript("""
        ALTER TABLE employees RENAME TO _employees_old;
        CREATE TABLE employees (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            branch          TEXT NOT NULL,
            emp_type        TEXT NOT NULL CHECK(emp_type IN ('insured','freelance','business','tax_exempt')),
            dependents      INTEGER DEFAULT 1,
            base_salary     INTEGER DEFAULT 0,
            meal_allowance  INTEGER DEFAULT 0,
            transport       INTEGER DEFAULT 0,
            email           TEXT DEFAULT '',
            id_number       TEXT DEFAULT '',
            join_date       TEXT DEFAULT '',
            is_active       INTEGER DEFAULT 1,
            note            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );
        INSERT INTO employees SELECT * FROM _employees_old;
        DROP TABLE _employees_old;
    """)
    conn.commit()


def _migrate_employees_add_columns(conn):
    """phone, work_start, work_end, hourly_rate, break_minutes 컬럼 마이그레이션"""
    cols = [r[1] for r in conn.execute("PRAGMA table_info(employees)").fetchall()]
    if "phone" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN phone TEXT DEFAULT ''")
    if "work_start" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN work_start TEXT DEFAULT '09:00'")
    if "work_end" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN work_end TEXT DEFAULT '18:00'")
    if "hourly_rate" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN hourly_rate INTEGER DEFAULT 0")
    if "break_minutes" not in cols:
        conn.execute("ALTER TABLE employees ADD COLUMN break_minutes INTEGER DEFAULT 0")
    conn.commit()


# CRM 직무(Role) enum — (사람×지점)당 최대 2개
VALID_ROLES = ("info", "trainer", "golf_pro", "gx", "manager")
ROLE_LABELS = {
    "info": "인포", "trainer": "트레이너", "golf_pro": "골프프로",
    "gx": "GX강사", "manager": "지점관리자",
}


def _migrate_roles_and_person(conn):
    """CRM 직무·멀티지점 로그인 기반:
    - employees.person_uid (같은 사람의 여러 지점 행 묶기)
    - employees.commission_percent (트레이너/프로 %정산 개인요율)
    - employee_roles 테이블 (지점별 직무, 행=지점단위 → 자동 지점별 직무)
    - employee_accounts.person_uid (계정=사람 단위 로그인)
    """
    ecols = [r[1] for r in conn.execute("PRAGMA table_info(employees)").fetchall()]
    if "person_uid" not in ecols:
        conn.execute("ALTER TABLE employees ADD COLUMN person_uid TEXT DEFAULT ''")
    if "commission_percent" not in ecols:
        conn.execute("ALTER TABLE employees ADD COLUMN commission_percent REAL DEFAULT 0")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS employee_roles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            role        TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, role)
        )
    """)

    acols = [r[1] for r in conn.execute("PRAGMA table_info(employee_accounts)").fetchall()]
    if acols and "person_uid" not in acols:
        conn.execute("ALTER TABLE employee_accounts ADD COLUMN person_uid TEXT DEFAULT ''")

    conn.commit()

    # person_uid 백필: 주민번호(id_number) 있으면 그걸 키로, 없으면 'EMP{id}' 단독키
    rows = conn.execute(
        "SELECT id, id_number, person_uid FROM employees"
    ).fetchall()
    for eid, idnum, puid in rows:
        if puid:
            continue
        key = (idnum or "").strip() or f"EMP{eid}"
        conn.execute("UPDATE employees SET person_uid=? WHERE id=?", (key, eid))
    conn.commit()


def _migrate_payroll_entries_unique(conn):
    """payroll_entries에 UNIQUE(year,month,employee_id) 제약이 없으면 테이블 재생성해 적용"""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='payroll_entries'"
    ).fetchone()
    if not row:
        return
    if "UNIQUE(year, month, employee_id)" in row[0]:
        return  # 이미 적용됨
    # 중복 제거(최신 id 유지) 후 테이블 재생성
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS _pe_tmp AS
            SELECT * FROM payroll_entries
            WHERE id IN (
                SELECT MAX(id) FROM payroll_entries
                GROUP BY year, month, employee_id
            );
        DROP TABLE payroll_entries;
        CREATE TABLE payroll_entries (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            year             INTEGER NOT NULL,
            month            INTEGER NOT NULL,
            employee_id      INTEGER NOT NULL,
            branch           TEXT NOT NULL,
            emp_type         TEXT NOT NULL,
            gross_pay        INTEGER DEFAULT 0,
            meal_allowance   INTEGER DEFAULT 0,
            transport        INTEGER DEFAULT 0,
            taxable_base     INTEGER DEFAULT 0,
            income_tax       INTEGER DEFAULT 0,
            local_tax        INTEGER DEFAULT 0,
            pension_emp      INTEGER DEFAULT 0,
            health_emp       INTEGER DEFAULT 0,
            employ_emp       INTEGER DEFAULT 0,
            total_deduction  INTEGER DEFAULT 0,
            net_pay          INTEGER DEFAULT 0,
            company_pension  INTEGER DEFAULT 0,
            company_health   INTEGER DEFAULT 0,
            company_employ   INTEGER DEFAULT 0,
            company_accident INTEGER DEFAULT 0,
            status           TEXT DEFAULT 'draft',
            note             TEXT DEFAULT '',
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, employee_id)
        );
        INSERT INTO payroll_entries SELECT * FROM _pe_tmp;
        DROP TABLE _pe_tmp;
    """)
    conn.commit()


def init_payroll_tables():
    """급여 시스템 전용 테이블 생성"""
    conn = get_conn()
    c = conn.cursor()
    c.executescript("""
        -- 직원 마스터
        CREATE TABLE IF NOT EXISTS employees (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            branch          TEXT NOT NULL,
            emp_type        TEXT NOT NULL CHECK(emp_type IN ('insured','freelance','business','tax_exempt')),
            dependents      INTEGER DEFAULT 1,
            base_salary     INTEGER DEFAULT 0,
            meal_allowance  INTEGER DEFAULT 0,
            transport       INTEGER DEFAULT 0,
            email           TEXT DEFAULT '',
            id_number       TEXT DEFAULT '',
            join_date       TEXT DEFAULT '',
            is_active       INTEGER DEFAULT 1,
            note            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 급여 계산 항목 (월별 직원별)
        CREATE TABLE IF NOT EXISTS payroll_entries (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            year                INTEGER NOT NULL,
            month               INTEGER NOT NULL,
            employee_id         INTEGER NOT NULL,
            branch              TEXT NOT NULL,
            emp_type            TEXT NOT NULL,
            gross_pay           INTEGER DEFAULT 0,
            meal_allowance      INTEGER DEFAULT 0,
            transport           INTEGER DEFAULT 0,
            taxable_base        INTEGER DEFAULT 0,
            income_tax          INTEGER DEFAULT 0,
            local_tax           INTEGER DEFAULT 0,
            pension_emp         INTEGER DEFAULT 0,
            health_emp          INTEGER DEFAULT 0,
            employ_emp          INTEGER DEFAULT 0,
            total_deduction     INTEGER DEFAULT 0,
            net_pay             INTEGER DEFAULT 0,
            company_pension     INTEGER DEFAULT 0,
            company_health      INTEGER DEFAULT 0,
            company_employ      INTEGER DEFAULT 0,
            company_accident    INTEGER DEFAULT 0,
            status              TEXT DEFAULT 'draft',
            note                TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, employee_id)
        );

        -- 간이세액표 (국세청)
        CREATE TABLE IF NOT EXISTS tax_brackets (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            salary_from     INTEGER NOT NULL,
            salary_to       INTEGER NOT NULL,
            dependents_0    INTEGER DEFAULT 0,
            dependents_1    INTEGER DEFAULT 0,
            dependents_2    INTEGER DEFAULT 0,
            dependents_3    INTEGER DEFAULT 0,
            dependents_4    INTEGER DEFAULT 0,
            dependents_5    INTEGER DEFAULT 0,
            dependents_6    INTEGER DEFAULT 0,
            dependents_7    INTEGER DEFAULT 0,
            tax_year        INTEGER DEFAULT 2025
        );

        -- 4대보험 요율 설정
        CREATE TABLE IF NOT EXISTS insurance_rates (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            year            INTEGER NOT NULL UNIQUE,
            pension_rate    REAL DEFAULT 0.045,
            health_rate     REAL DEFAULT 0.03545,
            employ_rate_emp REAL DEFAULT 0.009,
            employ_rate_co  REAL DEFAULT 0.009,
            accident_rate   REAL DEFAULT 0.007,
            updated_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 급여 확정 잠금
        CREATE TABLE IF NOT EXISTS payroll_locks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            year        INTEGER NOT NULL,
            month       INTEGER NOT NULL,
            locked_by   TEXT NOT NULL,
            locked_at   TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month)
        );

        -- 4대보험 실납부 고지액 (공단 고지서 기준)
        CREATE TABLE IF NOT EXISTS insurance_actuals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            employee_name TEXT NOT NULL,
            employee_id   INTEGER DEFAULT NULL,
            pension_base  INTEGER DEFAULT 0,
            pension_emp   INTEGER DEFAULT 0,
            pension_co    INTEGER DEFAULT 0,
            health_base   INTEGER DEFAULT 0,
            health_emp    INTEGER DEFAULT 0,
            health_co     INTEGER DEFAULT 0,
            employ_base   INTEGER DEFAULT 0,
            employ_emp    INTEGER DEFAULT 0,
            employ_co     INTEGER DEFAULT 0,
            created_at    TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(year, month, employee_name)
        );

        -- 이메일 발송 이력
        CREATE TABLE IF NOT EXISTS email_logs (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            year            INTEGER NOT NULL,
            month           INTEGER NOT NULL,
            employee_id     INTEGER NOT NULL,
            recipient_email TEXT NOT NULL,
            subject         TEXT,
            status          TEXT DEFAULT 'pending',
            sent_at         TEXT,
            error_msg       TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 직원 랜딩페이지 로그인 계정
        CREATE TABLE IF NOT EXISTS employee_accounts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id     INTEGER UNIQUE NOT NULL,
            username        TEXT UNIQUE NOT NULL,
            password_hash   TEXT NOT NULL,
            must_change_pw  INTEGER DEFAULT 1,
            last_login      TEXT,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT DEFAULT (datetime('now','localtime'))
        );

        -- 출퇴근 근태 기록
        CREATE TABLE IF NOT EXISTS attendance (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id     INTEGER NOT NULL,
            work_date       TEXT NOT NULL,
            clock_in        TEXT,
            clock_out       TEXT,
            work_minutes    INTEGER DEFAULT 0,
            break_minutes   INTEGER DEFAULT 0,
            status          TEXT DEFAULT 'present',
            note            TEXT DEFAULT '',
            created_at      TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, work_date)
        );

        -- 일별 급여 기록 (시급제 직원)
        CREATE TABLE IF NOT EXISTS daily_pay_records (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id      INTEGER NOT NULL,
            work_date        TEXT NOT NULL,
            work_minutes     INTEGER DEFAULT 0,
            regular_minutes  INTEGER DEFAULT 0,
            night_minutes    INTEGER DEFAULT 0,
            is_weekend       INTEGER DEFAULT 0,
            is_holiday       INTEGER DEFAULT 0,
            hourly_rate      REAL DEFAULT 0,
            regular_pay      INTEGER DEFAULT 0,
            extra_pay        INTEGER DEFAULT 0,
            total_pay        INTEGER DEFAULT 0,
            note             TEXT DEFAULT '',
            created_at       TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(employee_id, work_date)
        );

        -- 공휴일 관리
        CREATE TABLE IF NOT EXISTS public_holidays (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            holiday_date TEXT UNIQUE NOT NULL,
            name         TEXT NOT NULL,
            year         INTEGER NOT NULL
        );
    """)
    conn.commit()
    _migrate_employees_emp_type(conn)
    _migrate_employees_add_columns(conn)
    _migrate_payroll_entries_unique(conn)
    _migrate_attendance_breaks(conn)
    _migrate_roles_and_person(conn)

    # 대한민국 법정 공휴일 기본 시딩 (2025–2026)
    _KR_HOLIDAYS = [
        ("2025-01-01","신정",2025), ("2025-01-28","설날 연휴",2025),
        ("2025-01-29","설날",2025), ("2025-01-30","설날 연휴",2025),
        ("2025-03-01","삼일절",2025), ("2025-05-05","어린이날·석가탄신일",2025),
        ("2025-05-06","어린이날 대체공휴일",2025), ("2025-06-06","현충일",2025),
        ("2025-08-15","광복절",2025), ("2025-10-05","추석 연휴",2025),
        ("2025-10-06","추석",2025), ("2025-10-07","추석 연휴",2025),
        ("2025-10-09","한글날",2025), ("2025-12-25","성탄절",2025),
        ("2026-01-01","신정",2026), ("2026-02-16","설날 연휴",2026),
        ("2026-02-17","설날",2026), ("2026-02-18","설날 연휴",2026),
        ("2026-03-01","삼일절",2026), ("2026-05-05","어린이날",2026),
        ("2026-05-24","석가탄신일",2026), ("2026-06-06","현충일",2026),
        ("2026-08-15","광복절",2026), ("2026-09-24","추석 연휴",2026),
        ("2026-09-25","추석",2026), ("2026-09-26","추석 연휴",2026),
        ("2026-10-03","개천절",2026), ("2026-10-09","한글날",2026),
        ("2026-12-25","성탄절",2026),
    ]
    for _hd, _hn, _hy in _KR_HOLIDAYS:
        conn.execute(
            "INSERT OR IGNORE INTO public_holidays (holiday_date, name, year) VALUES (?,?,?)",
            (_hd, _hn, _hy)
        )
    conn.commit()

    # 기본 4대보험 요율 (2025년)
    exists = conn.execute("SELECT id FROM insurance_rates WHERE year=2025").fetchone()
    if not exists:
        conn.execute("""
            INSERT INTO insurance_rates
            (year, pension_rate, health_rate, employ_rate_emp, employ_rate_co, accident_rate)
            VALUES (2025, 0.045, 0.03545, 0.009, 0.009, 0.007)
        """)
        conn.commit()

    conn.close()


# ── 직원 마스터 쿼리 ─────────────────────────────────────────
def get_all_employees(active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q = "SELECT * FROM employees"
    if active_only:
        q += " WHERE is_active=1"
    q += " ORDER BY branch, emp_type, name"
    cur  = conn.execute(q)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_employees_by_branch(branch: str, active_only: bool = True) -> list[dict]:
    conn = get_conn()
    q    = "SELECT * FROM employees WHERE branch=?"
    params: list = [branch]
    if active_only:
        q += " AND is_active=1"
    q += " ORDER BY emp_type, name"
    cur  = conn.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


# ── CRM 직무(Role) / 멀티지점 ────────────────────────────────
def get_employee_roles(employee_id: int) -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role FROM employee_roles WHERE employee_id=? ORDER BY id", (employee_id,)
    ).fetchall()
    conn.close()
    return [r[0] for r in rows]


def set_employee_roles(employee_id: int, roles: list[str]) -> list[str]:
    """직원 직무 설정 (전체 교체). 유효 직무만, 최대 2개."""
    clean: list[str] = []
    for r in roles or []:
        r = (r or "").strip()
        if r in VALID_ROLES and r not in clean:
            clean.append(r)
    clean = clean[:2]
    conn = get_conn()
    conn.execute("DELETE FROM employee_roles WHERE employee_id=?", (employee_id,))
    for r in clean:
        conn.execute(
            "INSERT OR IGNORE INTO employee_roles (employee_id, role) VALUES (?,?)",
            (employee_id, r),
        )
    conn.commit()
    conn.close()
    return clean


def get_person_uid(employee_id: int) -> str:
    conn = get_conn()
    row = conn.execute(
        "SELECT person_uid FROM employees WHERE id=?", (employee_id,)
    ).fetchone()
    conn.close()
    return (row[0] if row else "") or f"EMP{employee_id}"


def get_person_branches(person_uid: str) -> list[dict]:
    """한 사람(person_uid)이 로그인 가능한 활성 지점들 + 각 지점 직무.
    반환: [{employee_id, branch, roles:[...]}] (직무가 1개 이상인 행만)."""
    if not person_uid:
        return []
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, branch FROM employees WHERE person_uid=? AND is_active=1 ORDER BY branch",
        (person_uid,),
    ).fetchall()
    out = []
    for eid, branch in rows:
        rl = [r[0] for r in conn.execute(
            "SELECT role FROM employee_roles WHERE employee_id=? ORDER BY id", (eid,)
        ).fetchall()]
        if rl:  # 직무가 지정된 지점만 로그인 대상
            out.append({"employee_id": eid, "branch": branch, "roles": rl})
    conn.close()
    return out


def get_branch_staff_by_roles(branch: str, roles: list[str]) -> list[dict]:
    """지점 내 특정 직무 보유 직원 목록 (강사 선택용)."""
    if not roles:
        return []
    ph = ",".join("?" * len(roles))
    conn = get_conn()
    rows = conn.execute(f"""
        SELECT DISTINCT e.id, e.name, e.commission_percent
        FROM employees e JOIN employee_roles r ON r.employee_id=e.id
        WHERE e.branch=? AND e.is_active=1 AND r.role IN ({ph})
        ORDER BY e.name
    """, (branch, *roles)).fetchall()
    conn.close()
    return [{"employee_id": r[0], "name": r[1], "commission_percent": r[2] or 0} for r in rows]


def get_employee_brief(employee_id: int) -> dict | None:
    """선택된 지점(employee 행) 로그인 컨텍스트 구성용."""
    conn = get_conn()
    row = conn.execute(
        "SELECT id, name, branch, person_uid, commission_percent FROM employees WHERE id=? AND is_active=1",
        (employee_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    roles = get_employee_roles(employee_id)
    return {
        "employee_id": row[0], "name": row[1], "branch": row[2],
        "person_uid": row[3], "commission_percent": row[4] or 0, "roles": roles,
    }


def upsert_employee(data: dict) -> int:
    """
    직원 추가/수정. 반환값: employee_id
    - id 있음 → 해당 ID 행 UPDATE
    - id 없음 → (name, branch) 동일 직원 존재 시 UPDATE, 없으면 INSERT
      → 엑셀 재업로드·중복 등록 방지
    """
    conn   = get_conn()
    name   = data["name"]
    branch = data["branch"]

    params_vals = (
        name, branch, data["emp_type"], data.get("dependents", 1),
        data.get("base_salary", 0), data.get("meal_allowance", 0), data.get("transport", 0),
        data.get("email", ""), data.get("id_number", ""), data.get("join_date", ""),
        data.get("is_active", 1), data.get("note", ""),
        data.get("phone", ""), data.get("work_start", "09:00"),
        data.get("work_end", "18:00"), data.get("hourly_rate", 0),
    )

    if data.get("id"):
        conn.execute("""
            UPDATE employees SET
                name=?, branch=?, emp_type=?, dependents=?,
                base_salary=?, meal_allowance=?, transport=?,
                email=?, id_number=?, join_date=?, is_active=?, note=?,
                phone=?, work_start=?, work_end=?, hourly_rate=?
            WHERE id=?
        """, (*params_vals, data["id"]))
        emp_id = int(data["id"])
    else:
        # 이름 + 지점 + 유형 3가지가 모두 같을 때만 기존 행 업데이트
        # → 같은 사람이 4대보험(기본급) + 사업소득(인센티브)로 중복 등록 가능
        existing = conn.execute(
            "SELECT id FROM employees WHERE name=? AND branch=? AND emp_type=? ORDER BY id LIMIT 1",
            (name, branch, data["emp_type"]),
        ).fetchone()

        if existing:
            emp_id = existing[0]
            conn.execute("""
                UPDATE employees SET
                    name=?, branch=?, emp_type=?, dependents=?,
                    base_salary=?, meal_allowance=?, transport=?,
                    email=?, id_number=?, join_date=?, is_active=?, note=?,
                    phone=?, work_start=?, work_end=?, hourly_rate=?
                WHERE id=?
            """, (*params_vals, emp_id))
        else:
            cur = conn.execute("""
                INSERT INTO employees
                (name, branch, emp_type, dependents, base_salary, meal_allowance,
                 transport, email, id_number, join_date, is_active, note,
                 phone, work_start, work_end, hourly_rate)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, params_vals)
            emp_id = cur.lastrowid

    # commission_percent (선택)
    if "commission_percent" in data and data.get("commission_percent") is not None:
        conn.execute(
            "UPDATE employees SET commission_percent=? WHERE id=?",
            (float(data.get("commission_percent") or 0), emp_id),
        )

    # person_uid 채우기: 주민번호 우선, 없으면 단독키 'EMP{id}'
    idnum = (data.get("id_number", "") or "").strip()
    desired_puid = idnum or f"EMP{emp_id}"
    cur_puid = conn.execute(
        "SELECT person_uid FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    # 주민번호가 입력되면 항상 그것으로 동기화(같은 사람 묶기), 없을 때만 기존/단독키 유지
    if idnum:
        conn.execute("UPDATE employees SET person_uid=? WHERE id=?", (idnum, emp_id))
    elif not (cur_puid and cur_puid[0]):
        conn.execute("UPDATE employees SET person_uid=? WHERE id=?", (desired_puid, emp_id))

    conn.commit()
    conn.close()
    return emp_id


def deduplicate_employees() -> dict:
    """
    (name, branch) 기준 중복 직원 행 정리.
    - 가장 오래된(id 최소) 행을 대표로 유지
    - 중복 행의 payroll_entries.employee_id를 대표 ID로 재연결 후 삭제
    반환: {"groups": 중복 그룹 수, "deleted": 삭제된 행 수, "detail": [...]}
    """
    conn    = get_conn()
    deleted = 0
    groups  = 0
    detail  = []

    # (name, branch, emp_type) 3개 모두 동일한 그룹만 중복으로 처리
    # → 같은 이름+지점이라도 유형(4대보험/사업소득)이 다르면 중복 아님
    dup_rows = conn.execute("""
        SELECT name, branch, emp_type, COUNT(*) as cnt, MIN(id) as keep_id
        FROM employees
        GROUP BY name, branch, emp_type
        HAVING cnt > 1
    """).fetchall()

    for name, branch, emp_type, cnt, keep_id in dup_rows:
        groups += 1
        # 대표 ID(keep_id) 제외한 나머지 ID 목록
        dup_ids = [
            r[0] for r in conn.execute(
                "SELECT id FROM employees WHERE name=? AND branch=? AND emp_type=? AND id!=? ORDER BY id",
                (name, branch, emp_type, keep_id),
            ).fetchall()
        ]
        for dup_id in dup_ids:
            # payroll_entries 재연결 (UNIQUE(year,month,employee_id) 충돌 방지: 이미 keep_id 항목 있으면 dup 행 삭제)
            conn.execute("""
                UPDATE OR IGNORE payroll_entries
                SET employee_id=?
                WHERE employee_id=?
            """, (keep_id, dup_id))
            # 재연결 안 된(충돌로 남은) 항목도 삭제
            conn.execute("DELETE FROM payroll_entries WHERE employee_id=?", (dup_id,))
            conn.execute("DELETE FROM employees WHERE id=?", (dup_id,))
            deleted += 1
        detail.append({"name": name, "branch": branch, "emp_type": emp_type, "kept_id": keep_id, "removed": len(dup_ids)})

    conn.commit()
    conn.close()
    return {"groups": groups, "deleted": deleted, "detail": detail}


def delete_employee(employee_id: int) -> bool:
    """직원 비활성화 (소프트 삭제)"""
    try:
        conn = get_conn()
        conn.execute("UPDATE employees SET is_active=0 WHERE id=?", (employee_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── 급여 계산 항목 쿼리 ───────────────────────────────────────
def get_payroll_entries(year: int, month: int, branch: str = None) -> list[dict]:
    conn = get_conn()
    q    = """
        SELECT pe.*, e.name, e.email, e.id_number, e.join_date
        FROM payroll_entries pe
        JOIN employees e ON pe.employee_id = e.id
        WHERE pe.year=? AND pe.month=?
    """
    params: list = [year, month]
    if branch:
        q += " AND pe.branch=?"
        params.append(branch)
    q += " ORDER BY pe.branch, e.emp_type, e.name"
    cur  = conn.execute(q, params)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def delete_payroll_entries(year: int, month: int, branch: str = None) -> int:
    """급여 데이터 삭제. branch=None 이면 해당 연월 전체 삭제. 반환: 삭제 건수"""
    conn = get_conn()
    if branch:
        cur = conn.execute(
            "DELETE FROM payroll_entries WHERE year=? AND month=? AND branch=?",
            (year, month, branch),
        )
    else:
        cur = conn.execute(
            "DELETE FROM payroll_entries WHERE year=? AND month=?",
            (year, month),
        )
    count = cur.rowcount
    conn.commit()
    conn.close()
    return count


def save_payroll_entry(entry: dict) -> bool:
    try:
        conn = get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO payroll_entries
            (year, month, employee_id, branch, emp_type,
             gross_pay, meal_allowance, transport, taxable_base,
             income_tax, local_tax, pension_emp, health_emp, employ_emp,
             total_deduction, net_pay,
             company_pension, company_health, company_employ, company_accident,
             status, note)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            entry["year"], entry["month"], entry["employee_id"],
            entry["branch"], entry["emp_type"],
            entry.get("gross_pay", 0), entry.get("meal_allowance", 0), entry.get("transport", 0),
            entry.get("taxable_base", 0),
            entry.get("income_tax", 0), entry.get("local_tax", 0),
            entry.get("pension_emp", 0), entry.get("health_emp", 0), entry.get("employ_emp", 0),
            entry.get("total_deduction", 0), entry.get("net_pay", 0),
            entry.get("company_pension", 0), entry.get("company_health", 0),
            entry.get("company_employ", 0), entry.get("company_accident", 0),
            entry.get("status", "draft"), entry.get("note", ""),
        ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[payroll_entry save] {e}")
        return False


# ── 4대보험 요율 쿼리 ─────────────────────────────────────────
def get_insurance_rates(year: int = 2025) -> dict:
    conn = get_conn()
    row  = conn.execute("SELECT * FROM insurance_rates WHERE year=?", (year,)).fetchone()
    conn.close()
    if row:
        return {
            "year": row[1], "pension_rate": row[2], "health_rate": row[3],
            "employ_rate_emp": row[4], "employ_rate_co": row[5], "accident_rate": row[6],
        }
    return {
        "year": year, "pension_rate": 0.045, "health_rate": 0.03545,
        "employ_rate_emp": 0.009, "employ_rate_co": 0.009, "accident_rate": 0.007,
    }


def save_insurance_rates(data: dict) -> bool:
    try:
        conn = get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO insurance_rates
            (year, pension_rate, health_rate, employ_rate_emp, employ_rate_co, accident_rate)
            VALUES (?,?,?,?,?,?)
        """, (
            data["year"], data["pension_rate"], data["health_rate"],
            data["employ_rate_emp"], data["employ_rate_co"], data["accident_rate"],
        ))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ── 간이세액표 쿼리 ───────────────────────────────────────────
def get_tax_brackets(tax_year: int = 2025) -> list[dict]:
    conn = get_conn()
    cur  = conn.execute("SELECT * FROM tax_brackets WHERE tax_year=? ORDER BY salary_from",
                        (tax_year,))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def upsert_tax_brackets(rows: list[dict], tax_year: int = 2025) -> bool:
    """간이세액표 전체 교체"""
    try:
        conn = get_conn()
        conn.execute("DELETE FROM tax_brackets WHERE tax_year=?", (tax_year,))
        for r in rows:
            conn.execute("""
                INSERT INTO tax_brackets
                (salary_from, salary_to,
                 dependents_0, dependents_1, dependents_2, dependents_3,
                 dependents_4, dependents_5, dependents_6, dependents_7, tax_year)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """, (
                r["salary_from"], r["salary_to"],
                r.get("dependents_0", 0), r.get("dependents_1", 0),
                r.get("dependents_2", 0), r.get("dependents_3", 0),
                r.get("dependents_4", 0), r.get("dependents_5", 0),
                r.get("dependents_6", 0), r.get("dependents_7", 0),
                tax_year,
            ))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"[tax_brackets upsert] {e}")
        return False


# ── 급여 잠금 ────────────────────────────────────────────────
def lock_payroll(year: int, month: int, username: str) -> bool:
    try:
        conn = get_conn()
        conn.execute("""
            INSERT OR IGNORE INTO payroll_locks (year, month, locked_by)
            VALUES (?,?,?)
        """, (year, month, username))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def unlock_payroll(year: int, month: int) -> bool:
    try:
        conn = get_conn()
        conn.execute("DELETE FROM payroll_locks WHERE year=? AND month=?", (year, month))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def is_payroll_locked(year: int, month: int) -> bool:
    conn = get_conn()
    row  = conn.execute("SELECT id FROM payroll_locks WHERE year=? AND month=?", (year, month)).fetchone()
    conn.close()
    return row is not None


# ── 4대보험 실납부 ───────────────────────────────────────────
def save_insurance_actuals(year: int, month: int, records: list[dict]) -> tuple[int, int]:
    """공단 고지내역 저장. 반환: (저장 수, 미매칭 수)"""
    conn      = get_conn()
    saved     = 0
    unmatched = 0
    for rec in records:
        name   = rec.get("employee_name", "").strip()
        if not name:
            continue
        emp_row = conn.execute(
            "SELECT id FROM employees WHERE TRIM(name)=TRIM(?) AND is_active=1", (name,)
        ).fetchone()
        emp_id = emp_row[0] if emp_row else None
        if not emp_id:
            unmatched += 1
        conn.execute("""
            INSERT OR REPLACE INTO insurance_actuals
            (year, month, employee_name, employee_id,
             pension_base, pension_emp, pension_co,
             health_base, health_emp, health_co,
             employ_base, employ_emp, employ_co)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            year, month, name, emp_id,
            rec.get("pension_base", 0), rec.get("pension_emp", 0), rec.get("pension_co", 0),
            rec.get("health_base", 0), rec.get("health_emp", 0), rec.get("health_co", 0),
            rec.get("employ_base", 0), rec.get("employ_emp", 0), rec.get("employ_co", 0),
        ))
        saved += 1
    conn.commit()
    conn.close()
    return saved, unmatched


def get_insurance_actual(year: int, month: int, employee_id: int) -> dict | None:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM insurance_actuals WHERE year=? AND month=? AND employee_id=?",
        (year, month, employee_id),
    )
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else None


def get_all_insurance_actuals(year: int, month: int) -> list[dict]:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM insurance_actuals WHERE year=? AND month=? ORDER BY employee_name",
        (year, month),
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def delete_insurance_actuals(year: int, month: int) -> bool:
    try:
        conn = get_conn()
        conn.execute("DELETE FROM insurance_actuals WHERE year=? AND month=?", (year, month))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def get_insurance_actuals_by_branch(year: int, month: int) -> list[dict]:
    """공단 고지내역(insurance_actuals) → 지점별 직원/회사 부담 합계 집계"""
    conn = get_conn()
    try:
        cur = conn.execute("""
            SELECT e.branch,
                   SUM(ia.pension_co + ia.health_co + ia.employ_co)   AS company_insurance,
                   SUM(ia.pension_emp + ia.health_emp + ia.employ_emp) AS employee_insurance
            FROM insurance_actuals ia
            JOIN employees e ON ia.employee_id = e.id
            WHERE ia.year=? AND ia.month=?
            GROUP BY e.branch
        """, (year, month))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        return [dict(zip(cols, r)) for r in rows]
    except Exception:
        return []
    finally:
        conn.close()


# ── 이메일 로그 ──────────────────────────────────────────────
# ── 직원 계정 (랜딩페이지 로그인) ────────────────────────────
import hashlib as _hashlib


def _hash_pw(pw: str) -> str:
    return _hashlib.sha256(str(pw).strip().encode("utf-8")).hexdigest()


def create_employee_account(employee_id: int, username: str, default_pw: str) -> tuple[bool, str]:
    """직원 계정 생성/갱신. username=이메일, default_pw=전화번호뒷4자리"""
    try:
        conn = get_conn()
        conn.execute("""
            INSERT OR REPLACE INTO employee_accounts
            (employee_id, username, password_hash, must_change_pw, is_active)
            VALUES (?,?,?,1,1)
        """, (employee_id, username.strip(), _hash_pw(default_pw)))
        conn.commit()
        conn.close()
        return True, "계정 생성 완료"
    except Exception as e:
        return False, str(e)


def get_employee_account(employee_id: int) -> dict | None:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM employee_accounts WHERE employee_id=?", (employee_id,)
    )
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else None


def get_all_employee_accounts() -> list[dict]:
    conn = get_conn()
    cur  = conn.execute("""
        SELECT ea.*, e.name, e.branch, e.email, e.phone
        FROM employee_accounts ea
        JOIN employees e ON ea.employee_id = e.id
        ORDER BY e.branch, e.name
    """)
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def verify_employee_login(username: str, password: str) -> dict | None:
    """로그인 검증. 성공 시 직원 정보 반환, 실패 시 None"""
    conn = get_conn()
    try:
        pw_hash = _hash_pw(password)
        row = conn.execute("""
            SELECT ea.employee_id, ea.must_change_pw, ea.is_active,
                   e.name, e.branch, e.emp_type, e.email, e.phone,
                   e.work_start, e.work_end, e.hourly_rate, ea.username
            FROM employee_accounts ea
            JOIN employees e ON ea.employee_id = e.id
            WHERE ea.username=? AND ea.password_hash=? AND ea.is_active=1 AND e.is_active=1
        """, (username.strip(), pw_hash)).fetchone()
        if row:
            conn.execute(
                "UPDATE employee_accounts SET last_login=datetime('now','localtime') WHERE employee_id=?",
                (row[0],)
            )
            conn.commit()
            return {
                "employee_id": row[0], "must_change_pw": bool(row[1]),
                "name": row[3], "branch": row[4], "emp_type": row[5],
                "email": row[6] or "", "phone": row[7] or "",
                "work_start": row[8] or "09:00", "work_end": row[9] or "18:00",
                "hourly_rate": row[10] or 0, "username": row[11],
            }
        return None
    finally:
        conn.close()


def update_employee_password(employee_id: int, new_password: str) -> bool:
    try:
        conn = get_conn()
        conn.execute("""
            UPDATE employee_accounts
            SET password_hash=?, must_change_pw=0
            WHERE employee_id=?
        """, (_hash_pw(new_password), employee_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def reset_employee_password(employee_id: int, new_pw: str) -> bool:
    """관리자용 비밀번호 초기화 (다음 로그인 시 변경 강제)"""
    try:
        conn = get_conn()
        conn.execute("""
            UPDATE employee_accounts
            SET password_hash=?, must_change_pw=1
            WHERE employee_id=?
        """, (_hash_pw(str(new_pw)), employee_id))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _migrate_attendance_breaks(conn):
    """attendance 테이블에 break_start / break_end 컬럼 추가"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(attendance)")}
    if "break_start" not in cols:
        conn.execute("ALTER TABLE attendance ADD COLUMN break_start TEXT DEFAULT NULL")
    if "break_end" not in cols:
        conn.execute("ALTER TABLE attendance ADD COLUMN break_end TEXT DEFAULT NULL")
    conn.commit()


# ── 근태 기록 (출퇴근) ────────────────────────────────────────

def attendance_clock_in(employee_id: int, work_date: str, clock_time: str) -> tuple[bool, str]:
    """출근 기록. work_date=YYYY-MM-DD, clock_time=HH:MM"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id, clock_in FROM attendance WHERE employee_id=? AND work_date=?",
            (employee_id, work_date)
        ).fetchone()
        if existing:
            if existing[1]:
                conn.close()
                return False, f"이미 출근 처리됨 ({existing[1]})"
            conn.execute("UPDATE attendance SET clock_in=? WHERE id=?", (clock_time, existing[0]))
        else:
            conn.execute(
                "INSERT INTO attendance (employee_id, work_date, clock_in) VALUES (?,?,?)",
                (employee_id, work_date, clock_time)
            )
        conn.commit()
        return True, clock_time
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def attendance_clock_out(employee_id: int, work_date: str, clock_time: str,
                         work_start: str = "09:00") -> tuple[bool, str]:
    """퇴근 기록 — 유효 근무 창(스케줄 기준 클램프) + 정규 휴게시간 적용"""
    from datetime import datetime as _dt, timedelta as _td
    conn = get_conn()
    try:
        # 직원 스케줄 정보 조회
        emp = conn.execute(
            "SELECT work_start, work_end, break_minutes FROM employees WHERE id=?",
            (employee_id,)
        ).fetchone()
        sched_start = (emp[0] if emp and emp[0] else None) or work_start
        sched_end   = (emp[1] if emp and emp[1] else None) or "23:59"
        sched_break = int(emp[2] if emp and emp[2] else 0)

        # 출근 기록 조회
        existing = conn.execute(
            "SELECT id, clock_in, break_start, break_minutes FROM attendance "
            "WHERE employee_id=? AND work_date=?",
            (employee_id, work_date)
        ).fetchone()
        if not existing or not existing[1]:
            conn.close()
            return False, "출근 기록이 없습니다."

        actual_ci = existing[1]

        # ── 유효 근무 창 계산 ──────────────────────────────────
        # 일찍 와도 스케줄 시작부터, 늦게 가도 스케줄 종료까지만 인정
        try:
            ci_dt  = _dt.strptime(f"{work_date} {actual_ci}",   "%Y-%m-%d %H:%M")
            co_dt  = _dt.strptime(f"{work_date} {clock_time}",  "%Y-%m-%d %H:%M")
            ws_dt  = _dt.strptime(f"{work_date} {sched_start}", "%Y-%m-%d %H:%M")
            we_dt  = _dt.strptime(f"{work_date} {sched_end}",   "%Y-%m-%d %H:%M")
            eff_start = max(ci_dt, ws_dt)
            eff_end   = min(co_dt, we_dt)
            total_min = max(0, int((eff_end - eff_start).total_seconds() / 60)) \
                        if eff_end > eff_start else 0
        except Exception:
            total_min = 0

        # ── 휴게시간 결정 ──────────────────────────────────────
        # 버튼으로 기록된 휴게 시간
        acc_break = existing[3] or 0
        if existing[2]:  # break_start 남아있으면 아직 휴게 중 → 자동 종료 처리
            try:
                bs  = _dt.strptime(existing[2], "%H:%M")
                co2 = _dt.strptime(clock_time,  "%H:%M")
                acc_break += max(0, int((co2 - bs).total_seconds() / 60))
            except Exception:
                pass
        # 설정된 정규 휴게 vs 실제 기록 → 큰 값 사용 (직원에게 유리)
        break_min = max(acc_break, sched_break)
        work_min  = max(0, total_min - break_min)

        # ── 지각 판정 ─────────────────────────────────────────
        try:
            ws2 = _dt.strptime(sched_start, "%H:%M")
            ci2 = _dt.strptime(actual_ci,   "%H:%M")
            status = "late" if ci2 > ws2 + _td(minutes=10) else "present"
        except Exception:
            status = "present"

        conn.execute("""
            UPDATE attendance
            SET clock_out=?, work_minutes=?, break_minutes=?, status=?, break_start=NULL
            WHERE id=?
        """, (clock_time, work_min, break_min, status, existing[0]))
        conn.commit()
        return True, clock_time
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def attendance_break_start(employee_id: int, work_date: str, break_time: str) -> tuple[bool, str]:
    """휴게 시작 기록"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id, clock_in, clock_out, break_start FROM attendance WHERE employee_id=? AND work_date=?",
            (employee_id, work_date)
        ).fetchone()
        if not existing or not existing[1]:
            return False, "출근 기록이 없습니다."
        if existing[2]:
            return False, "이미 퇴근한 상태입니다."
        if existing[3]:
            return False, "이미 휴게 중입니다."
        conn.execute(
            "UPDATE attendance SET break_start=? WHERE id=?",
            (break_time, existing[0])
        )
        conn.commit()
        return True, break_time
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def attendance_break_end(employee_id: int, work_date: str, end_time: str) -> tuple[bool, str]:
    """휴게 종료 기록 (break_minutes 누적)"""
    from datetime import datetime as _dt
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id, break_start, break_minutes FROM attendance WHERE employee_id=? AND work_date=?",
            (employee_id, work_date)
        ).fetchone()
        if not existing or not existing[1]:
            return False, "휴게 기록이 없습니다."
        try:
            bs  = _dt.strptime(existing[1], "%H:%M")
            be  = _dt.strptime(end_time, "%H:%M")
            added = max(0, int((be - bs).total_seconds() / 60))
        except Exception:
            added = 0
        new_break = (existing[2] or 0) + added
        conn.execute(
            "UPDATE attendance SET break_start=NULL, break_end=?, break_minutes=? WHERE id=?",
            (end_time, new_break, existing[0])
        )
        conn.commit()
        return True, f"{added}분 휴게"
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def get_attendance_record(employee_id: int, work_date: str) -> dict | None:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date=?",
        (employee_id, work_date)
    )
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else None


def get_monthly_attendance(employee_id: int, year: int, month: int) -> list[dict]:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM attendance WHERE employee_id=? AND work_date LIKE ? ORDER BY work_date",
        (employee_id, f"{year}-{month:02d}%")
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_today_branch_attendance(branch: str, work_date: str) -> list[dict]:
    """관리자용: 특정 지점 오늘 출퇴근 현황"""
    conn = get_conn()
    cur  = conn.execute("""
        SELECT a.work_date, a.clock_in, a.clock_out, a.work_minutes, a.status,
               e.name, e.emp_type, e.work_start, e.work_end
        FROM attendance a
        JOIN employees e ON a.employee_id = e.id
        WHERE e.branch=? AND a.work_date=? AND e.is_active=1
        ORDER BY a.clock_in NULLS LAST
    """, (branch, work_date))
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def log_email(year: int, month: int, employee_id: int,
              email: str, subject: str, status: str, error: str = "") -> bool:
    try:
        import time
        conn = get_conn()
        conn.execute("""
            INSERT INTO email_logs
            (year, month, employee_id, recipient_email, subject, status, sent_at, error_msg)
            VALUES (?,?,?,?,?,?,?,?)
        """, (year, month, employee_id, email, subject, status,
              time.strftime("%Y-%m-%d %H:%M:%S") if status == "sent" else None, error))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════
#  공휴일 관리
# ══════════════════════════════════════════════════════════════════

def get_public_holidays(year: int) -> list[dict]:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM public_holidays WHERE year=? ORDER BY holiday_date", (year,)
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def upsert_public_holiday(holiday_date: str, name: str, year: int) -> bool:
    try:
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO public_holidays (holiday_date, name, year) VALUES (?,?,?)",
            (holiday_date, name, year)
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def delete_public_holiday(holiday_id: int) -> bool:
    try:
        conn = get_conn()
        conn.execute("DELETE FROM public_holidays WHERE id=?", (holiday_id,))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _get_holiday_set(year: int) -> set:
    conn = get_conn()
    rows = conn.execute(
        "SELECT holiday_date FROM public_holidays WHERE year=?", (year,)
    ).fetchall()
    conn.close()
    return {r[0] for r in rows}


# ══════════════════════════════════════════════════════════════════
#  일별 급여 계산 (시급제)
# ══════════════════════════════════════════════════════════════════

def calc_and_save_daily_pay(employee_id: int, work_date: str) -> dict | None:
    from datetime import datetime as _dt, date as _date
    conn = get_conn()
    try:
        emp_row = conn.execute(
            "SELECT work_start, work_end, break_minutes, hourly_rate FROM employees WHERE id=?",
            (employee_id,)
        ).fetchone()
        if not emp_row:
            return None
        hourly_rate = float(emp_row[3] or 0)
        if hourly_rate <= 0:
            return None
        sched_start = emp_row[0] or "09:00"
        sched_end   = emp_row[1] or "18:00"
        sched_break = int(emp_row[2] or 0)
        att = conn.execute(
            "SELECT clock_in, clock_out, break_minutes FROM attendance "
            "WHERE employee_id=? AND work_date=?",
            (employee_id, work_date)
        ).fetchone()
        if not att or not att[0] or not att[1]:
            return None
        actual_ci, actual_co = att[0], att[1]
        actual_break = int(att[2] or 0)
        try:
            ci_dt = _dt.strptime(f"{work_date} {actual_ci}",   "%Y-%m-%d %H:%M")
            co_dt = _dt.strptime(f"{work_date} {actual_co}",   "%Y-%m-%d %H:%M")
            ws_dt = _dt.strptime(f"{work_date} {sched_start}", "%Y-%m-%d %H:%M")
            we_dt = _dt.strptime(f"{work_date} {sched_end}",   "%Y-%m-%d %H:%M")
            eff_start = max(ci_dt, ws_dt)
            eff_end   = min(co_dt, we_dt)
            total_min = max(0, int((eff_end - eff_start).total_seconds() / 60)) if eff_end > eff_start else 0
        except Exception:
            return None
        break_min = max(actual_break, sched_break)
        net_min   = max(0, total_min - break_min)
        d          = _date.fromisoformat(work_date)
        is_wknd    = d.weekday() >= 5
        hset       = _get_holiday_set(d.year)
        is_hol     = work_date in hset
        is_special = is_wknd or is_hol
        try:
            night_b = _dt.strptime(f"{work_date} 22:00", "%Y-%m-%d %H:%M")
            if eff_end <= night_b or net_min == 0:
                regular_min, night_min = net_min, 0
            else:
                pre_min  = max(0, int((night_b - eff_start).total_seconds() / 60))
                post_min = total_min - pre_min
                regular_min = max(0, pre_min  - break_min)
                night_min   = max(0, post_min - max(0, break_min - pre_min))
        except Exception:
            regular_min, night_min = net_min, 0
        rpm = hourly_rate / 60
        if is_special:
            regular_pay = round(regular_min * rpm * 1.5)
            extra_pay   = round(night_min   * rpm * 2.0)
        else:
            regular_pay = round(regular_min * rpm * 1.0)
            extra_pay   = round(night_min   * rpm * 1.5)
        total_pay = regular_pay + extra_pay
        conn.execute("""
            INSERT OR REPLACE INTO daily_pay_records
            (employee_id, work_date, work_minutes, regular_minutes, night_minutes,
             is_weekend, is_holiday, hourly_rate, regular_pay, extra_pay, total_pay)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (employee_id, work_date, net_min, regular_min, night_min,
              int(is_wknd), int(is_hol), hourly_rate, regular_pay, extra_pay, total_pay))
        conn.commit()
        return {"work_minutes": net_min, "regular_minutes": regular_min,
                "night_minutes": night_min, "is_weekend": int(is_wknd),
                "is_holiday": int(is_hol), "hourly_rate": hourly_rate,
                "regular_pay": regular_pay, "extra_pay": extra_pay, "total_pay": total_pay}
    except Exception as e:
        print(f"[calc_and_save_daily_pay] {e}")
        return None
    finally:
        conn.close()


def get_daily_pay_records(employee_id: int, year: int, month: int) -> list[dict]:
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM daily_pay_records WHERE employee_id=? AND work_date LIKE ? ORDER BY work_date",
        (employee_id, f"{year}-{month:02d}%")
    )
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    conn.close()
    return [dict(zip(cols, r)) for r in rows]


def get_monthly_pay_total(employee_id: int, year: int, month: int) -> int:
    conn = get_conn()
    row  = conn.execute(
        "SELECT COALESCE(SUM(total_pay),0) FROM daily_pay_records "
        "WHERE employee_id=? AND work_date LIKE ?",
        (employee_id, f"{year}-{month:02d}%")
    ).fetchone()
    conn.close()
    return int(row[0]) if row else 0
