import sqlite3
import pandas as pd
from pathlib import Path
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine, text

# SETTLEMENT_DB 환경변수로 DB 경로 오버라이드 가능 (WEBAPP2 등 외부 앱용)
_ENV_DB = os.getenv("SETTLEMENT_DB")
DB_PATH = Path(_ENV_DB) if _ENV_DB else Path(__file__).parent.parent / "data" / "settlement.db"
DATABASE_URL = os.getenv("DATABASE_URL")

# PostgreSQL 또는 SQLite 결정
USE_POSTGRES = DATABASE_URL is not None

# SQLAlchemy 엔진 (pandas read_sql용)
def _build_engine():
    if not USE_POSTGRES:
        return None
    url = DATABASE_URL
    # postgresql:// → postgresql+psycopg2:// 형식으로 변환
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    # SSL 추가 (Supabase 필수)
    if "sslmode" not in url:
        url += "?sslmode=require"
    return create_engine(url, pool_pre_ping=True, pool_recycle=3600)

engine = _build_engine()

# 대시보드 기준 계정과목 체계
REVENUE_CATEGORIES = {
    "카드": ["PT매출(카드)", "GX매출(카드)", "골프매출(카드)", "키즈매출(카드)", "기타매출(카드)"],
    "현금": ["PT매출(현금)", "GX매출(현금)", "골프매출(현금)", "키즈매출(현금)", "기타매출(현금)"],
    "기타": ["도급비", "시설상환비", "카페매출"],
}
EXPENSE_CATEGORIES = [
    "급여", "4대보험료", "소득세·지방세 합계", "프리랜서", "퇴직금",
    "기타세금", "부가세", "카드수수료", "법인카드", "환불",
    "렌탈비", "관리비", "임차료", "비품구매", "기타지출",
    "운영경비", "외주용역비", "감가상각비", "기타보험료",
    "복리후생비", "이자비용", "AS비용", "차량유지비",
]


def get_conn():
    if USE_POSTGRES:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn
        except Exception as e:
            print(f"PostgreSQL 연결 실패: {e}")
            return None
    else:
        DB_PATH.parent.mkdir(exist_ok=True)
        return sqlite3.connect(DB_PATH)


def init_db():
    conn = get_conn()
    if not conn:
        return

    c = conn.cursor()

    if USE_POSTGRES:
        # PostgreSQL 테이블 생성
        try:
            c.execute("""
                CREATE TABLE IF NOT EXISTS card_sales (
                    id             SERIAL PRIMARY KEY,
                    year           INTEGER,
                    month          INTEGER,
                    source         TEXT,
                    branch         TEXT,
                    raw_merchant   TEXT,
                    card_company   TEXT,
                    total_amount   INTEGER DEFAULT 0,
                    vat            INTEGER DEFAULT 0,
                    supply_amount  INTEGER DEFAULT 0,
                    fee            INTEGER DEFAULT 0,
                    net_amount     INTEGER DEFAULT 0,
                    sale_date      TEXT
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS bank_transactions (
                    id                    SERIAL PRIMARY KEY,
                    year                  INTEGER,
                    month                 INTEGER,
                    bank                  TEXT,
                    tx_date               TEXT,
                    description           TEXT,
                    counterpart           TEXT,
                    deposit               INTEGER DEFAULT 0,
                    withdrawal            INTEGER DEFAULT 0,
                    balance               INTEGER DEFAULT 0,
                    branch                TEXT,
                    content               TEXT,
                    category              TEXT,
                    vat                   INTEGER DEFAULT 0,
                    is_excluded           INTEGER DEFAULT 0,
                    needs_review          INTEGER DEFAULT 0,
                    classification_source TEXT DEFAULT ''
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS payroll (
                    id              SERIAL PRIMARY KEY,
                    year            INTEGER,
                    month           INTEGER,
                    branch          TEXT,
                    type            TEXT,
                    gross_pay       INTEGER DEFAULT 0,
                    net_pay         INTEGER DEFAULT 0,
                    insurance       INTEGER DEFAULT 0,
                    income_tax      INTEGER DEFAULT 0,
                    local_tax       INTEGER DEFAULT 0,
                    headcount       INTEGER DEFAULT 0
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS keyword_rules (
                    id         SERIAL PRIMARY KEY,
                    bank       TEXT,
                    keyword    TEXT,
                    branch     TEXT,
                    category   TEXT,
                    hit_count  INTEGER DEFAULT 0,
                    UNIQUE(bank, keyword, branch, category)
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token      TEXT PRIMARY KEY,
                    username   TEXT NOT NULL,
                    expires_at BIGINT NOT NULL
                )
            """)
            c.execute("""
                CREATE TABLE IF NOT EXISTS insurance_payments (
                    id           SERIAL PRIMARY KEY,
                    year         INTEGER,
                    month        INTEGER,
                    branch       TEXT,
                    pension_co   INTEGER DEFAULT 0,
                    pension_emp  INTEGER DEFAULT 0,
                    health_total INTEGER DEFAULT 0,
                    employ_co    INTEGER DEFAULT 0,
                    employ_emp   INTEGER DEFAULT 0,
                    accident     INTEGER DEFAULT 0,
                    UNIQUE(year, month, branch)
                )
            """)
            conn.commit()
        except Exception as e:
            conn.rollback()
            print(f"PostgreSQL 테이블 생성 오류: {e}")
    else:
        # SQLite 테이블 생성
        c.executescript("""
            CREATE TABLE IF NOT EXISTS card_sales (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                year           INTEGER,
                month          INTEGER,
                source         TEXT,
                branch         TEXT,
                raw_merchant   TEXT,
                card_company   TEXT,
                total_amount   INTEGER DEFAULT 0,
                vat            INTEGER DEFAULT 0,
                supply_amount  INTEGER DEFAULT 0,
                fee            INTEGER DEFAULT 0,
                net_amount     INTEGER DEFAULT 0,
                sale_date      TEXT
            );

            CREATE TABLE IF NOT EXISTS bank_transactions (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                year                  INTEGER,
                month                 INTEGER,
                bank                  TEXT,
                tx_date               TEXT,
                description           TEXT,
                counterpart           TEXT,
                deposit               INTEGER DEFAULT 0,
                withdrawal            INTEGER DEFAULT 0,
                balance               INTEGER DEFAULT 0,
                branch                TEXT,
                content               TEXT,
                category              TEXT,
                vat                   INTEGER DEFAULT 0,
                is_excluded           INTEGER DEFAULT 0,
                needs_review          INTEGER DEFAULT 0,
                classification_source TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS payroll (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                year            INTEGER,
                month           INTEGER,
                branch          TEXT,
                type            TEXT,
                gross_pay       INTEGER DEFAULT 0,
                net_pay         INTEGER DEFAULT 0,
                insurance       INTEGER DEFAULT 0,
                income_tax      INTEGER DEFAULT 0,
                local_tax       INTEGER DEFAULT 0,
                headcount       INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS keyword_rules (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bank       TEXT,
                keyword    TEXT,
                branch     TEXT,
                category   TEXT,
                hit_count  INTEGER DEFAULT 0,
                UNIQUE(bank, keyword, branch, category)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                token      TEXT PRIMARY KEY,
                username   TEXT NOT NULL,
                expires_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS insurance_payments (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                year         INTEGER,
                month        INTEGER,
                branch       TEXT,
                pension_co   INTEGER DEFAULT 0,
                pension_emp  INTEGER DEFAULT 0,
                health_total INTEGER DEFAULT 0,
                employ_co    INTEGER DEFAULT 0,
                employ_emp   INTEGER DEFAULT 0,
                accident     INTEGER DEFAULT 0,
                UNIQUE(year, month, branch)
            );

            CREATE TABLE IF NOT EXISTS branch_goals (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                year        INTEGER NOT NULL,
                month       INTEGER NOT NULL,
                branch      TEXT NOT NULL,
                goal_amount INTEGER DEFAULT 0,
                UNIQUE(year, month, branch)
            );
        """)
        # SQLite 마이그레이션
        for col_def in [
            ("bank_transactions", "vat", "INTEGER DEFAULT 0"),
            ("bank_transactions", "classification_source", "TEXT DEFAULT ''"),
            ("card_sales", "source", "TEXT"),
            ("card_sales", "total_amount", "INTEGER DEFAULT 0"),
            ("card_sales", "vat", "INTEGER DEFAULT 0"),
            ("card_sales", "supply_amount", "INTEGER DEFAULT 0"),
            ("card_sales", "fee", "INTEGER DEFAULT 0"),
            ("card_sales", "net_amount", "INTEGER DEFAULT 0"),
        ]:
            try:
                c.execute(f"ALTER TABLE {col_def[0]} ADD COLUMN {col_def[1]} {col_def[2]}")
            except Exception:
                pass
        conn.commit()

    conn.close()


def load_keyword_rules():
    import json
    rules_path = Path(__file__).parent.parent / "mapping" / "keyword_rules.json"
    if not rules_path.exists():
        return

    try:
        with open(rules_path, encoding="utf-8") as f:
            data = json.load(f)

        conn = get_conn()
        if not conn:
            return

        c = conn.cursor()

        for bank, key in [("hana", "hana"), ("shinhan", "shinhan")]:
            for rule in data.get(key, []):
                cat = _normalize_category(rule["category"])

                if USE_POSTGRES:
                    # PostgreSQL: ON CONFLICT 문법 사용
                    c.execute("""
                        INSERT INTO keyword_rules (bank, keyword, branch, category, hit_count)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (bank, keyword, branch, category) DO NOTHING
                    """, (bank, rule["keyword"], rule["branch"], cat, rule.get("count", 0)))
                else:
                    # SQLite: INSERT OR IGNORE 문법
                    c.execute("""
                        INSERT OR IGNORE INTO keyword_rules (bank, keyword, branch, category, hit_count)
                        VALUES (?, ?, ?, ?, ?)
                    """, (bank, rule["keyword"], rule["branch"], cat, rule.get("count", 0)))

        conn.commit()
        conn.close()
    except Exception as e:
        print(f"키워드 규칙 로드 오류: {e}")


def _normalize_category(cat: str) -> str:
    """기존 계정과목을 대시보드 기준으로 정규화"""
    mapping = {
        "GX매출": "기타매출(현금)",
        "PT매출": "기타매출(현금)",
        "기타매출": "기타매출(현금)",
        "카드매출": "기타매출(카드)",
        "골프매출": "골프매출(현금)",
        "키즈매출": "키즈매출(현금)",
        "4대보험료": "4대보험료",
        "소득세·지방세": "소득세·지방세 합계",
        "소득세지방세": "소득세·지방세 합계",
    }
    return mapping.get(cat, cat)


# ── 카드 매출 ─────────────────────────────────────────────

def upsert_card_sales(df: pd.DataFrame, source: str, year: int, month: int):
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("DELETE FROM card_sales WHERE source=%s AND year=%s AND month=%s", (source, year, month))
    else:
        c.execute("DELETE FROM card_sales WHERE source=? AND year=? AND month=?", (source, year, month))

    df = df.copy()
    df["source"] = source
    df["year"] = year
    df["month"] = month
    df.to_sql("card_sales", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()


def get_card_by_branch(year: int, month: int = None):
    if USE_POSTGRES:
        mf = "AND month=:month" if month else ""
        params = {"year": year}
        if month:
            params["month"] = month

        query = f"""
            SELECT branch,
                   SUM(total_amount)  as card_total,
                   SUM(vat)           as card_vat,
                   SUM(supply_amount) as card_supply,
                   SUM(fee)           as card_fee,
                   SUM(net_amount)    as card_net
            FROM card_sales
            WHERE year=:year {mf}
            GROUP BY branch
        """
        df = pd.read_sql(text(query), engine, params=params)
        return df
    else:
        conn = get_conn()
        mf = "AND month=?" if month else ""
        params = [year]
        if month:
            params.append(month)

        query = f"""
            SELECT branch,
                   SUM(total_amount)  as card_total,
                   SUM(vat)           as card_vat,
                   SUM(supply_amount) as card_supply,
                   SUM(fee)           as card_fee,
                   SUM(net_amount)    as card_net
            FROM card_sales
            WHERE year=? {mf}
            GROUP BY branch
        """
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df


# ── 통장 거래 ─────────────────────────────────────────────

def upsert_bank_transactions(df: pd.DataFrame, bank: str, year: int, month: int):
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute("DELETE FROM bank_transactions WHERE bank=%s AND year=%s AND month=%s", (bank, year, month))
    else:
        c.execute("DELETE FROM bank_transactions WHERE bank=? AND year=? AND month=?", (bank, year, month))

    df = df.copy()
    df["bank"] = bank
    df["year"] = year
    df["month"] = month
    df.to_sql("bank_transactions", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()


def get_branch_cash_revenue(year: int, month: int = None):
    """통장 현금 매출: 공급가액(deposit - vat)과 VAT 반환"""
    revenue_cats = (
        "'기타매출(현금)','PT매출(현금)','GX매출(현금)',"
        "'골프매출(현금)','키즈매출(현금)','도급비','시설상환비','카페매출'"
    )

    if USE_POSTGRES:
        mf = "AND month=:month" if month else ""
        params = {"year": year}
        if month:
            params["month"] = month

        query = f"""
            SELECT branch,
                   SUM(deposit - vat) as cash_supply,
                   SUM(vat)           as cash_vat,
                   SUM(deposit)       as cash_total
            FROM bank_transactions
            WHERE year=:year {mf}
              AND is_excluded=0
              AND category IN ({revenue_cats})
              AND deposit > 0
            GROUP BY branch
        """
        df = pd.read_sql(text(query), engine, params=params)
        return df
    else:
        conn = get_conn()
        mf = "AND month=?" if month else ""
        params = [year]
        if month:
            params.append(month)

        query = f"""
            SELECT branch,
                   SUM(deposit - vat) as cash_supply,
                   SUM(vat)           as cash_vat,
                   SUM(deposit)       as cash_total
            FROM bank_transactions
            WHERE year=? {mf}
              AND is_excluded=0
              AND category IN ({revenue_cats})
              AND deposit > 0
            GROUP BY branch
        """
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df


def get_expense_by_category(year: int, month: int = None, branch: str = None):
    if USE_POSTGRES:
        filters = ["year=:year", "is_excluded=0", "withdrawal > 0"]
        params = {"year": year}
        if month:
            filters.append("month=:month")
            params["month"] = month
        if branch:
            filters.append("branch=:branch")
            params["branch"] = branch
        where = " AND ".join(filters)
        query = f"""
            SELECT branch, month, category, SUM(withdrawal) as amount, SUM(vat) as vat
            FROM bank_transactions
            WHERE {where}
            GROUP BY branch, month, category
        """
        df = pd.read_sql(text(query), engine, params=params)
        return df
    else:
        conn = get_conn()
        filters = ["year=?", "is_excluded=0", "withdrawal > 0"]
        params = [year]
        if month:
            filters.append("month=?")
            params.append(month)
        if branch:
            filters.append("branch=?")
            params.append(branch)
        where = " AND ".join(filters)
        query = f"""
            SELECT branch, month, category, SUM(withdrawal) as amount, SUM(vat) as vat
            FROM bank_transactions
            WHERE {where}
            GROUP BY branch, month, category
        """
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df


def get_revenue_by_category(year: int, month: int = None, branch: str = None):
    """통장 매출: 계정과목별 입금 내역 반환 (지점 상세 세부 표시용)"""
    revenue_cats = (
        "'기타매출(현금)','PT매출(현금)','GX매출(현금)',"
        "'골프매출(현금)','키즈매출(현금)',"
        "'기타매출(카드)','PT매출(카드)','GX매출(카드)',"
        "'골프매출(카드)','키즈매출(카드)',"
        "'도급비','시설상환비','카페매출'"
    )
    if USE_POSTGRES:
        filters = ["year=:year", "is_excluded=0", "deposit > 0",
                   f"category IN ({revenue_cats})"]
        params: dict = {"year": year}
        if month:
            filters.append("month=:month"); params["month"] = month
        if branch:
            filters.append("branch=:branch"); params["branch"] = branch
        where = " AND ".join(filters)
        query = f"""
            SELECT branch, category,
                   SUM(deposit)       as total_deposit,
                   SUM(vat)           as total_vat,
                   SUM(deposit - vat) as supply_amount
            FROM bank_transactions
            WHERE {where}
            GROUP BY branch, category
        """
        return pd.read_sql(text(query), engine, params=params)
    else:
        conn = get_conn()
        filters = ["year=?", "is_excluded=0", "deposit > 0",
                   f"category IN ({revenue_cats})"]
        params_list: list = [year]
        if month:
            filters.append("month=?"); params_list.append(month)
        if branch:
            filters.append("branch=?"); params_list.append(branch)
        where = " AND ".join(filters)
        query = f"""
            SELECT branch, category,
                   SUM(deposit)       as total_deposit,
                   SUM(vat)           as total_vat,
                   SUM(deposit - vat) as supply_amount
            FROM bank_transactions
            WHERE {where}
            GROUP BY branch, category
        """
        df = pd.read_sql(query, conn, params=params_list)
        conn.close()
        return df


def get_unreviewed_transactions():
    conn = get_conn()
    df = pd.read_sql(
        "SELECT * FROM bank_transactions WHERE needs_review=1 ORDER BY year, month, tx_date",
        conn
    )
    conn.close()
    return df


def get_all_bank_transactions(year: int, month: int, bank: str = None) -> pd.DataFrame:
    """연/월 기준 통장 거래 전체 조회 (계정과목 검토용)"""
    if USE_POSTGRES:
        filters = ["year=:year", "month=:month"]
        params = {"year": year, "month": month}
        if bank:
            filters.append("bank=:bank")
            params["bank"] = bank
        where = " AND ".join(filters)
        query = f"SELECT * FROM bank_transactions WHERE {where} ORDER BY bank, tx_date"
        return pd.read_sql(text(query), engine, params=params)
    else:
        conn = get_conn()
        filters = ["year=?", "month=?"]
        params = [year, month]
        if bank:
            filters.append("bank=?")
            params.append(bank)
        where = " AND ".join(filters)
        query = f"SELECT * FROM bank_transactions WHERE {where} ORDER BY bank, tx_date"
        df = pd.read_sql(query, conn, params=params)
        conn.close()
        return df


def update_transaction_classification(tx_id: int, branch: str, category: str, source: str = "manual"):
    conn = get_conn()
    c = conn.cursor()

    is_excluded = 1 if category == "제외" else 0

    if USE_POSTGRES:
        c.execute(
            "UPDATE bank_transactions SET branch=%s, category=%s, needs_review=0, is_excluded=%s, classification_source=%s WHERE id=%s",
            (branch, category, is_excluded, source, tx_id)
        )
    else:
        c.execute(
            "UPDATE bank_transactions SET branch=?, category=?, needs_review=0, is_excluded=?, classification_source=? WHERE id=?",
            (branch, category, is_excluded, source, tx_id)
        )

    conn.commit()
    conn.close()


# ── 인건비 ───────────────────────────────────────────────

def upsert_payroll(df: pd.DataFrame, year: int, month: int, pay_type: str):
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute(
            "DELETE FROM payroll WHERE year=%s AND month=%s AND type=%s",
            (year, month, pay_type)
        )
    else:
        c.execute(
            "DELETE FROM payroll WHERE year=? AND month=? AND type=?",
            (year, month, pay_type)
        )

    df = df.copy()
    df["year"] = year
    df["month"] = month
    df["type"] = pay_type
    df.to_sql("payroll", conn, if_exists="append", index=False)
    conn.commit()
    conn.close()


def get_payroll_summary(year: int, month: int = None, branch: str = None):
    """
    급여 집계 반환.
    우선순위: payroll_entries(인사탭 계산) > payroll(엑셀 업로드)
    동일 branch+month 조합은 payroll_entries 데이터를 사용하고 payroll은 무시.
    """
    if USE_POSTGRES:
        filters = ["year=:year"]
        params = {"year": year}
        if month:
            filters.append("month=:month")
            params["month"] = month
        if branch:
            filters.append("branch=:branch")
            params["branch"] = branch
        where = " AND ".join(filters)
        query = f"""
            SELECT branch, month, type,
                   SUM(gross_pay)  as gross_pay,
                   SUM(net_pay)    as net_pay,
                   SUM(insurance)  as insurance,
                   SUM(income_tax) as income_tax,
                   SUM(local_tax)  as local_tax,
                   SUM(headcount)  as headcount
            FROM payroll
            WHERE {where}
            GROUP BY branch, month, type
        """
        df = pd.read_sql(text(query), engine, params=params)
        return df
    else:
        conn = get_conn()

        # ── ① payroll_entries (인사탭) 집계 ──────────────────────────
        pe_filters = ["pe.year=?"]
        pe_params  = [year]
        if month:
            pe_filters.append("pe.month=?")
            pe_params.append(month)
        if branch:
            pe_filters.append("pe.branch=?")
            pe_params.append(branch)
        pe_where = " AND ".join(pe_filters)

        try:
            df_pe = pd.read_sql(f"""
                SELECT pe.branch,
                       pe.month,
                       pe.emp_type                                          AS type,
                       SUM(pe.gross_pay)                                    AS gross_pay,
                       SUM(pe.net_pay)                                      AS net_pay,
                       SUM(pe.pension_emp + pe.health_emp + pe.employ_emp)  AS insurance,
                       SUM(pe.income_tax)                                   AS income_tax,
                       SUM(pe.local_tax)                                    AS local_tax,
                       COUNT(*)                                             AS headcount
                FROM payroll_entries pe
                WHERE {pe_where}
                GROUP BY pe.branch, pe.month, pe.emp_type
            """, conn, params=pe_params)
        except Exception:
            df_pe = pd.DataFrame()

        # ── ② payroll (엑셀 업로드) 집계 ─────────────────────────────
        p_filters = ["year=?"]
        p_params  = [year]
        if month:
            p_filters.append("month=?")
            p_params.append(month)
        if branch:
            p_filters.append("branch=?")
            p_params.append(branch)
        p_where = " AND ".join(p_filters)

        try:
            df_p = pd.read_sql(f"""
                SELECT branch, month, type,
                       SUM(gross_pay)  AS gross_pay,
                       SUM(net_pay)    AS net_pay,
                       SUM(insurance)  AS insurance,
                       SUM(income_tax) AS income_tax,
                       SUM(local_tax)  AS local_tax,
                       SUM(headcount)  AS headcount
                FROM payroll
                WHERE {p_where}
                GROUP BY branch, month, type
            """, conn, params=p_params)
        except Exception:
            df_p = pd.DataFrame()

        conn.close()

        # ── ③ 병합: payroll_entries 우선, 중복 branch+month는 payroll 제외 ─
        if df_pe.empty and df_p.empty:
            return pd.DataFrame(columns=["branch","month","type","gross_pay",
                                         "net_pay","insurance","income_tax",
                                         "local_tax","headcount"])
        if df_pe.empty:
            return df_p
        if df_p.empty:
            return df_pe

        # payroll_entries에 있는 (branch, month) 조합은 payroll에서 제외
        pe_keys = set(zip(df_pe["branch"].astype(str), df_pe["month"].astype(str)))
        mask    = ~df_p.apply(
            lambda r: (str(r["branch"]), str(r["month"])) in pe_keys, axis=1
        )
        return pd.concat([df_pe, df_p[mask]], ignore_index=True)


# ── 4대보험 본사/직원 부담 ────────────────────────────────────────

def upsert_insurance_payments(df: pd.DataFrame, year: int, month: int):
    """4대보험 지점별 본사/직원 부담 upsert (연월 기준 교체)"""
    conn = get_conn()
    c = conn.cursor()

    if USE_POSTGRES:
        c.execute(
            "DELETE FROM insurance_payments WHERE year=%s AND month=%s",
            (year, month)
        )
        conn.commit()
        df = df.copy()
        df["year"] = year
        df["month"] = month
        df.to_sql("insurance_payments", conn, if_exists="append", index=False,
                  method="multi")
    else:
        c.execute(
            "DELETE FROM insurance_payments WHERE year=? AND month=?",
            (year, month)
        )
        conn.commit()
        df = df.copy()
        df["year"] = year
        df["month"] = month
        df.to_sql("insurance_payments", conn, if_exists="append", index=False)

    conn.commit()
    conn.close()


def get_insurance_summary(year: int, month: int = None, branch: str = None) -> pd.DataFrame:
    """지점별 보험료 본사·직원 부담 합계 반환

    반환 컬럼:
      branch, company_insurance, employee_insurance
      (건강보험은 health_total ÷ 2 로 배분)
    """
    if USE_POSTGRES:
        filters = ["year=:year"]
        params: dict = {"year": year}
        if month:
            filters.append("month=:month"); params["month"] = month
        if branch:
            filters.append("branch=:branch"); params["branch"] = branch
        where = " AND ".join(filters)
        query = f"""
            SELECT branch,
                   SUM(pension_co + FLOOR(health_total/2.0) + employ_co + accident)  AS company_insurance,
                   SUM(pension_emp + CEIL(health_total/2.0)  + employ_emp)            AS employee_insurance,
                   SUM(pension_co)    AS pension_co,
                   SUM(pension_emp)   AS pension_emp,
                   SUM(health_total)  AS health_total,
                   SUM(employ_co)     AS employ_co,
                   SUM(employ_emp)    AS employ_emp,
                   SUM(accident)      AS accident
            FROM insurance_payments
            WHERE {where}
            GROUP BY branch
        """
        return pd.read_sql(text(query), engine, params=params)
    else:
        conn = get_conn()
        filters = ["year=?"]
        params_list: list = [year]
        if month:
            filters.append("month=?"); params_list.append(month)
        if branch:
            filters.append("branch=?"); params_list.append(branch)
        where = " AND ".join(filters)
        query = f"""
            SELECT branch,
                   SUM(pension_co + CAST(health_total/2 AS INTEGER) + employ_co + accident)  AS company_insurance,
                   SUM(pension_emp + (health_total - CAST(health_total/2 AS INTEGER)) + employ_emp) AS employee_insurance,
                   SUM(pension_co)    AS pension_co,
                   SUM(pension_emp)   AS pension_emp,
                   SUM(health_total)  AS health_total,
                   SUM(employ_co)     AS employ_co,
                   SUM(employ_emp)    AS employ_emp,
                   SUM(accident)      AS accident
            FROM insurance_payments
            WHERE {where}
            GROUP BY branch
        """
        df = pd.read_sql(query, conn, params=params_list)
        conn.close()
        return df


def delete_card_sales(year: int, month: int):
    """해당 월 카드매출 전체 삭제"""
    conn = get_conn()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("DELETE FROM card_sales WHERE year=%s AND month=%s", (year, month))
    else:
        c.execute("DELETE FROM card_sales WHERE year=? AND month=?", (year, month))
    conn.commit()
    conn.close()


def delete_bank_transactions(year: int, month: int, bank: str = None):
    """해당 월 통장내역 삭제. bank 지정 시 해당 통장만 삭제"""
    conn = get_conn()
    c = conn.cursor()
    if bank:
        if USE_POSTGRES:
            c.execute("DELETE FROM bank_transactions WHERE year=%s AND month=%s AND bank=%s",
                      (year, month, bank))
        else:
            c.execute("DELETE FROM bank_transactions WHERE year=? AND month=? AND bank=?",
                      (year, month, bank))
    else:
        if USE_POSTGRES:
            c.execute("DELETE FROM bank_transactions WHERE year=%s AND month=%s", (year, month))
        else:
            c.execute("DELETE FROM bank_transactions WHERE year=? AND month=?", (year, month))
    conn.commit()
    conn.close()


def delete_keyword_rule(rule_id: int):
    """키워드 규칙 단건 삭제"""
    conn = get_conn()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("DELETE FROM keyword_rules WHERE id=%s", (rule_id,))
    else:
        c.execute("DELETE FROM keyword_rules WHERE id=?", (rule_id,))
    conn.commit()
    conn.close()


def update_keyword_rule(rule_id: int, branch: str, category: str):
    """키워드 규칙 지점·계정과목 수정"""
    conn = get_conn()
    c = conn.cursor()
    if USE_POSTGRES:
        c.execute("UPDATE keyword_rules SET branch=%s, category=%s WHERE id=%s",
                  (branch, category, rule_id))
    else:
        c.execute("UPDATE keyword_rules SET branch=?, category=? WHERE id=?",
                  (branch, category, rule_id))
    conn.commit()
    conn.close()


def get_keyword_rules(bank: str = None):
    if USE_POSTGRES:
        if bank:
            query = text("SELECT * FROM keyword_rules WHERE bank=:bank ORDER BY hit_count DESC")
            df = pd.read_sql(query, engine, params={"bank": bank})
        else:
            df = pd.read_sql(text("SELECT * FROM keyword_rules ORDER BY bank, hit_count DESC"), engine)
        return df
    else:
        conn = get_conn()
        if bank:
            df = pd.read_sql(
                "SELECT * FROM keyword_rules WHERE bank=? ORDER BY hit_count DESC",
                conn, params=(bank,)
            )
        else:
            df = pd.read_sql(
                "SELECT * FROM keyword_rules ORDER BY bank, hit_count DESC", conn
            )
        conn.close()
        return df


# ── 지점 목표 매출 ────────────────────────────────────────────
def get_branch_goals(year: int, month: int) -> dict:
    """지점별 목표 매출 조회 {branch: goal_amount}"""
    conn = get_conn()
    if not conn:
        return {}
    try:
        rows = conn.execute(
            "SELECT branch, goal_amount FROM branch_goals WHERE year=? AND month=?",
            (year, month)
        ).fetchall()
        conn.close()
        return {r[0]: r[1] for r in rows}
    except Exception:
        return {}


def set_branch_goal(year: int, month: int, branch: str, goal_amount: int):
    """지점 목표 매출 저장 (upsert)"""
    conn = get_conn()
    if not conn:
        return
    try:
        conn.execute(
            """INSERT INTO branch_goals (year, month, branch, goal_amount)
               VALUES (?,?,?,?)
               ON CONFLICT(year, month, branch)
               DO UPDATE SET goal_amount=excluded.goal_amount""",
            (year, month, branch, goal_amount)
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"set_branch_goal error: {e}")
