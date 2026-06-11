"""
WebSettle2 — 차세대 ERP (FastAPI + 일반 웹앱)
Port: 8503
DB·비즈니스 로직: 기존 WEBAPP 폴더의 모듈을 그대로 재사용 (settlement.db 공유)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# ── 기존 WEBAPP 모듈 재사용 (DB·집계 로직 공유) ─────────────────
BASE_DIR   = Path(__file__).parent
WEBAPP_DIR = (BASE_DIR.parent / "WEBAPP")
if not WEBAPP_DIR.exists():
    # NAS Docker 환경: /app/legacy 로 마운트
    WEBAPP_DIR = Path("/app/legacy")
sys.path.insert(0, str(WEBAPP_DIR))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# 기존 코드 재사용
from modules.auth import (
    verify_login, make_token, validate_token, get_user_by_username,
    init_users_table,
)
from modules.db import init_db

STATIC_DIR   = BASE_DIR / "static"
TEMPLATE_DIR = BASE_DIR / "templates"

app = FastAPI(title="WebSettle2 · 라온스포츠 ERP", version="0.1.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

try:
    _ASSET_VER = str(int((STATIC_DIR / "js" / "app.js").stat().st_mtime))
except Exception:
    _ASSET_VER = "1"
templates.env.globals["asset_ver"] = _ASSET_VER


@app.on_event("startup")
async def on_startup():
    init_db()
    init_users_table()


# ── 인증 ──────────────────────────────────────────────────────
_login_fails: dict = {}

def _rate_limit(ident: str):
    now = time.time()
    fails = [t for t in _login_fails.get(ident, []) if now - t < 600]
    _login_fails[ident] = fails
    if len(fails) >= 5:
        raise HTTPException(429, "로그인 시도가 너무 많습니다. 10분 후 다시 시도하세요.")


def require_auth(request: Request) -> dict:
    token = request.headers.get("Authorization", "")
    if token.startswith("Bearer "):
        token = token[7:]
    else:
        token = request.cookies.get("ws2_token", "")
    username = validate_token(token) if token else None
    if not username:
        raise HTTPException(401, "로그인이 필요합니다")
    user = get_user_by_username(username)
    if not user:
        raise HTTPException(401, "사용자를 찾을 수 없습니다")
    return user


# ── 페이지 라우트 ─────────────────────────────────────────────
@app.get("/")
async def root():
    return RedirectResponse("/app")


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/app")
async def app_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html")


# ── Auth API ──────────────────────────────────────────────────
class LoginBody(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login")
async def api_login(body: LoginBody):
    ident = body.username.strip()
    _rate_limit(ident)
    user = verify_login(ident, body.password)
    if not user:
        _login_fails.setdefault(ident, []).append(time.time())
        raise HTTPException(401, "아이디 또는 비밀번호가 올바르지 않습니다")
    _login_fails.pop(ident, None)
    token = make_token(user["username"])
    return {"token": token, "name": user["name"], "role": user["role"]}


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = require_auth(request)
    return {"username": user["username"], "name": user["name"], "role": user["role"]}


# ── 대시보드 API ──────────────────────────────────────────────
def _summary(year: int, month: int):
    from domains.dashboard.service import build_summary
    df = build_summary(year, month)
    return df


def _totals(df) -> dict:
    if df is None or df.empty:
        return {}
    return {
        "총매출": int(df["총매출"].sum()),
        "총지출": int(df["총지출"].sum()),
        "손익":   int(df["손익"].sum()),
        "이익률": round(float(df["손익"].sum()) / float(df["총매출"].sum()) * 100, 1)
                  if df["총매출"].sum() else 0,
    }


@app.get("/api/summary")
async def api_summary(request: Request, year: int, month: int):
    require_auth(request)
    df = _summary(year, month)
    if df is None or df.empty:
        return {"rows": [], "totals": {}, "prev": {}, "yoy": {}}
    # 전월 / 전년 동월
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    prev_df = _summary(py, pm)
    yoy_df  = _summary(year - 1, month)
    return {
        "rows":   df.fillna(0).to_dict("records"),
        "totals": _totals(df),
        "prev":   _totals(prev_df),
        "yoy":    _totals(yoy_df),
    }


@app.get("/api/summary/trend")
async def api_trend(request: Request, year: int, month: int):
    require_auth(request)
    from domains.dashboard.service import build_trend
    df = build_trend(year, month)
    if df is None or df.empty:
        return {"months": [], "revenue": [], "profit": []}
    g = df.groupby("month").agg(총매출=("총매출", "sum"), 손익=("손익", "sum")).reset_index()
    return {
        "months":  [int(m) for m in g["month"]],
        "revenue": [int(v) for v in g["총매출"]],
        "profit":  [int(v) for v in g["손익"]],
    }


@app.get("/api/summary/excel")
async def api_summary_excel(request: Request, year: int, month: int):
    require_auth(request)
    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse
    from urllib.parse import quote
    df = _summary(year, month)
    if df is None or df.empty:
        raise HTTPException(404, "데이터가 없습니다")
    cols = {"branch": "지점", "카드공급가액": "카드공급가액", "카드수수료": "카드수수료",
            "카드실수령": "카드실수령", "현금공급가액": "현금공급가액", "총매출": "총매출",
            "인건비합계": "인건비합계", "기타지출": "기타지출", "부가세합계": "부가세합계",
            "총지출": "총지출", "손익": "손익", "이익률": "이익률(%)"}
    out = df[[c for c in cols if c in df.columns]].rename(columns=cols)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        out.to_excel(w, sheet_name=f"{year}년{month:02d}월", index=False)
    buf.seek(0)
    fn = quote(f"손익현황_{year}년{month:02d}월.xlsx")
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})


# ── 지점 상세 API ─────────────────────────────────────────────
@app.get("/api/branches")
async def api_branches(request: Request):
    require_auth(request)
    from domains.branch.db import get_active_branch_names
    return get_active_branch_names()


@app.get("/api/branch/pnl")
async def api_branch_pnl(request: Request, year: int, month: int, branch: str):
    require_auth(request)
    from domains.dashboard.service import c_rev, c_exp
    from modules.db import get_branch_goals
    df = _summary(year, month)
    row = {}
    if df is not None and not df.empty:
        m = df[df.branch == branch]
        if not m.empty:
            row = {k: (round(float(v), 1) if isinstance(v, float) else v)
                   for k, v in m.iloc[0].fillna(0).to_dict().items()}
    rev_df = c_rev(year, month)
    exp_df = c_exp(year, month)
    rev_by_cat = {}
    exp_by_cat = {}
    if rev_df is not None and not rev_df.empty:
        br = rev_df[rev_df.branch == branch]
        if not br.empty:
            rev_by_cat = {str(k): int(v) for k, v in
                          br.groupby("category")["supply_amount"].sum().items()}
    if exp_df is not None and not exp_df.empty:
        br = exp_df[exp_df.branch == branch]
        if not br.empty:
            exp_by_cat = {str(k): int(v) for k, v in
                          br.groupby("category")["amount"].sum().items()}
    goal = get_branch_goals(year, month).get(branch, 0)
    return {"summary": row, "rev_by_cat": rev_by_cat, "exp_by_cat": exp_by_cat, "goal": goal}


class GoalBody(BaseModel):
    year:   int
    month:  int
    branch: str
    goal:   int


@app.post("/api/branch/goal")
async def api_branch_goal(request: Request, body: GoalBody):
    require_auth(request)
    from modules.db import set_branch_goal
    set_branch_goal(body.year, body.month, body.branch, body.goal)
    return {"ok": True}


# ── 출퇴근 현황 API ────────────────────────────────────────────
@app.get("/api/attendance")
async def api_attendance(request: Request, year: int, month: int, branch: str = ""):
    require_auth(request)
    from modules.db import get_conn
    conn = get_conn()
    prefix = f"{year}-{month:02d}"
    q = """SELECT e.name, e.branch, a.work_date, a.clock_in, a.clock_out,
                  a.work_minutes, a.break_minutes, a.status
           FROM attendance a JOIN employees e ON a.employee_id = e.id
           WHERE a.work_date LIKE ?"""
    args = [f"{prefix}%"]
    if branch:
        q += " AND e.branch=?"
        args.append(branch)
    q += " ORDER BY a.work_date DESC, e.branch, e.name"
    rows = [dict(zip(["name", "branch", "work_date", "clock_in", "clock_out",
                      "work_minutes", "break_minutes", "status"], r))
            for r in conn.execute(q, args).fetchall()]
    conn.close()
    return rows


@app.get("/api/attendance/branches")
async def api_att_branches(request: Request):
    require_auth(request)
    from modules.db import get_conn
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT DISTINCT branch FROM employees WHERE branch IS NOT NULL AND branch!='' ORDER BY branch"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ── 직원 목록 API ─────────────────────────────────────────────
@app.get("/api/employees")
async def api_employees(request: Request):
    require_auth(request)
    from domains.payroll.db import get_all_employees
    return get_all_employees()


# ── 데이터 업로드 API ─────────────────────────────────────────
from fastapi import UploadFile, File, Form
import tempfile
import os as _os


@app.post("/api/upload/card")
async def api_upload_card(request: Request, year: int = Form(...), month: int = Form(...),
                          kind: str = Form(...), file: UploadFile = File(...)):
    """카드매출 업로드 — kind: 'aggregate' | 'credit'"""
    require_auth(request)
    from modules.parser import parse_card_aggregate, parse_credit_card
    from modules.db import upsert_card_sales
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as tmp:
        tmp.write(await file.read())
        tp = tmp.name
    try:
        if kind == "aggregate":
            df = parse_card_aggregate(tp, year, month)
            upsert_card_sales(df, "card_aggregate", year, month)
        else:
            df = parse_credit_card(tp, year, month)
            upsert_card_sales(df, "credit_card", year, month)
        unmapped = int((df.branch == "미매핑").sum()) if "branch" in df.columns else 0
        return {"ok": True, "count": len(df), "unmapped": unmapped}
    except Exception as e:
        raise HTTPException(400, f"파싱 오류: {e}")
    finally:
        _os.unlink(tp)


@app.post("/api/upload/bank")
async def api_upload_bank(request: Request, year: int = Form(...), month: int = Form(...),
                          bank: str = Form(...), file: UploadFile = File(...)):
    """통장내역 업로드 — bank: 'hana' | 'shinhan'"""
    require_auth(request)
    import pandas as pd
    from modules.parser import parse_hana, parse_shinhan, recalc_vat
    from modules.classifier import classify_transactions
    from modules.db import upsert_bank_transactions
    import io
    content = await file.read()
    xl = pd.ExcelFile(io.BytesIO(content))
    try:
        df = parse_hana(xl, year, month) if bank == "hana" else parse_shinhan(xl, year, month)
        if df.empty:
            raise HTTPException(400, "인식 가능한 시트가 없습니다")
        df = classify_transactions(df, bank)
        df = recalc_vat(df)
        upsert_bank_transactions(df, bank, year, month)
        return {"ok": True, "count": len(df),
                "auto": int((df.needs_review == 0).sum()),
                "review": int(df.needs_review.sum())}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"파싱 오류: {e}")


@app.post("/api/upload/payroll")
async def api_upload_payroll(request: Request, year: int = Form(...), month: int = Form(...),
                             file: UploadFile = File(...)):
    require_auth(request)
    import pandas as pd
    import io
    from modules.parser import parse_payroll_insured, parse_payroll_freelance
    from modules.db import upsert_payroll
    xl = pd.ExcelFile(io.BytesIO(await file.read()))
    parts = []
    try:
        if "지점별집계" in xl.sheet_names:
            df = parse_payroll_insured(xl, year, month)
            if not df.empty:
                upsert_payroll(df, year, month, "insured")
                parts.append(f"4대보험 {len(df)}건")
        if "사업소득자" in xl.sheet_names:
            df = parse_payroll_freelance(xl, year, month)
            if not df.empty:
                upsert_payroll(df, year, month, "freelance")
                parts.append(f"프리랜서 {len(df)}건")
        if not parts:
            raise HTTPException(400, f"인식된 시트 없음 (현재: {', '.join(xl.sheet_names)})")
        return {"ok": True, "msg": " · ".join(parts)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"파싱 오류: {e}")


@app.delete("/api/upload/card")
async def api_delete_card(request: Request, year: int, month: int):
    require_auth(request)
    from modules.db import delete_card_sales
    delete_card_sales(year, month)
    return {"ok": True}


@app.delete("/api/upload/bank")
async def api_delete_bank(request: Request, year: int, month: int, bank: str = ""):
    require_auth(request)
    from modules.db import delete_bank_transactions
    delete_bank_transactions(year, month, bank or None)
    return {"ok": True}


# ── 설정: 미분류 검토 + 규칙 관리 ──────────────────────────────
@app.get("/api/rules/transactions")
async def api_rules_tx(request: Request, year: int, month: int,
                       bank: str = "", unclassified: int = 1):
    require_auth(request)
    from modules.db import get_all_bank_transactions
    df = get_all_bank_transactions(year, month, bank or None)
    if df is None or df.empty:
        return []
    if unclassified:
        df = df[df.needs_review == 1]
    cols = ["id", "bank", "tx_date", "description", "counterpart",
            "deposit", "withdrawal", "branch", "category", "needs_review",
            "classification_source"]
    return df[[c for c in cols if c in df.columns]].fillna("").to_dict("records")


class ClassifyBody(BaseModel):
    tx_id:    int
    branch:   str
    category: str
    add_rule: bool = False
    bank:     str = ""
    keyword:  str = ""


@app.post("/api/rules/classify")
async def api_rules_classify(request: Request, body: ClassifyBody):
    require_auth(request)
    from modules.db import update_transaction_classification
    update_transaction_classification(body.tx_id, body.branch, body.category, "manual")
    if body.add_rule and body.keyword and body.bank:
        from modules.classifier import add_rule
        add_rule(body.bank, body.keyword, body.branch, body.category)
    return {"ok": True}


@app.get("/api/rules")
async def api_rules_list(request: Request, bank: str = ""):
    require_auth(request)
    from modules.db import get_keyword_rules
    df = get_keyword_rules(bank or None)
    if df is None or len(df) == 0:
        return []
    return df.fillna("").to_dict("records")


class RuleBody(BaseModel):
    bank:     str
    keyword:  str
    branch:   str
    category: str


@app.post("/api/rules")
async def api_rules_add(request: Request, body: RuleBody):
    require_auth(request)
    from modules.classifier import add_rule
    add_rule(body.bank, body.keyword, body.branch, body.category)
    return {"ok": True}


@app.delete("/api/rules/{rule_id}")
async def api_rules_del(request: Request, rule_id: int):
    require_auth(request)
    from modules.db import delete_keyword_rule
    delete_keyword_rule(rule_id)
    return {"ok": True}


@app.get("/api/meta")
async def api_meta(request: Request):
    """지점 목록 + 계정과목 목록 + 미분류 건수"""
    require_auth(request)
    from shared.config import BRANCH_LIST, ALL_CATEGORIES
    from modules.db import get_conn
    unclf = 0
    try:
        conn = get_conn()
        unclf = conn.execute(
            "SELECT COUNT(*) FROM bank_transactions WHERE needs_review=1").fetchone()[0]
        conn.close()
    except Exception:
        pass
    return {"branches": BRANCH_LIST, "categories": ALL_CATEGORIES, "unclassified": unclf}


# ── 지점 관리 (좌표/주소/반경) ─────────────────────────────────
@app.get("/api/branch/list")
async def api_branch_list(request: Request):
    require_auth(request)
    from domains.branch.db import get_all_branches
    return get_all_branches()


class BranchBody(BaseModel):
    id:                int = 0
    name:              str
    address:           str = ""
    lat:               float | None = None
    lng:               float | None = None
    attendance_radius: int = 300
    is_active:         int = 1


@app.post("/api/branch/upsert")
async def api_branch_upsert(request: Request, body: BranchBody):
    require_auth(request)
    from domains.branch.db import upsert_branch
    data = body.dict()
    if not data["id"]:
        data.pop("id")
    rid = upsert_branch(data)
    return {"id": rid}


# ── 월별 매출 직접 입력 ────────────────────────────────────────
_BMR_COLS = ["dogeub", "pt_sales", "gx_sales", "cafe_sales",
             "golf_sales", "facility_fee", "cafe_labor", "other_sales"]


@app.get("/api/branch/monthly-revenue")
async def api_bmr_get(request: Request, year: int, month: int):
    require_auth(request)
    from domains.branch.db import get_branch_monthly_revenue, get_active_branch_names
    saved = {r["branch"]: r for r in get_branch_monthly_revenue(year, month)}
    out = []
    for br in get_active_branch_names():
        row = saved.get(br, {})
        out.append({"branch": br,
                    **{c: int(row.get(c, 0) or 0) for c in _BMR_COLS},
                    "note": row.get("note", "") or ""})
    return out


class BmrBody(BaseModel):
    year:   int
    month:  int
    branch: str
    data:   dict


@app.post("/api/branch/monthly-revenue")
async def api_bmr_save(request: Request, body: BmrBody):
    require_auth(request)
    from domains.branch.db import upsert_branch_monthly_revenue
    data = {c: int(body.data.get(c, 0) or 0) for c in _BMR_COLS}
    data["note"] = str(body.data.get("note", ""))[:200]
    upsert_branch_monthly_revenue(body.year, body.month, body.branch, data)
    return {"ok": True}


# ── 정산서 Excel (지점별 손익계산서) ───────────────────────────
@app.get("/api/branch/pnl/excel")
async def api_pnl_excel(request: Request, year: int, month: int, branches: str):
    require_auth(request)
    import io
    import pandas as pd
    from fastapi.responses import StreamingResponse
    from urllib.parse import quote
    df = _summary(year, month)
    if df is None or df.empty:
        raise HTTPException(404, "데이터가 없습니다")
    br_list = [b for b in branches.split(",") if b.strip()]
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for br in br_list:
            m = df[df.branch == br]
            if m.empty:
                continue
            d = m.iloc[0].fillna(0).to_dict()
            rows = [
                ("매출", "카드 공급가액",  int(d.get("카드공급가액", 0))),
                ("",     "카드 수수료",    -int(d.get("카드수수료", 0))),
                ("",     "카드 실수령",     int(d.get("카드실수령", 0))),
                ("",     "현금 공급가액",   int(d.get("현금공급가액", 0))),
                ("",     "직접입력 매출",   int(d.get("수동입력매출", 0))),
                ("",     "▶ 총매출",        int(d.get("총매출", 0))),
                ("지출", "급여",            int(d.get("급여", 0))),
                ("",     "4대보험(직원)",    int(d.get("4대보험료_직원", 0))),
                ("",     "4대보험(본사)",    int(d.get("4대보험_본사", 0))),
                ("",     "소득세·지방세",    int(d.get("소득세지방세", 0))),
                ("",     "프리랜서",         int(d.get("프리랜서", 0))),
                ("",     "인건비합계",       int(d.get("인건비합계", 0))),
                ("",     "기타지출",         int(d.get("기타지출", 0))),
                ("",     "부가세합계",       int(d.get("부가세합계", 0))),
                ("",     "▶ 총지출",         int(d.get("총지출", 0))),
                ("손익", "▶ 순손익",         int(d.get("손익", 0))),
                ("",     "이익률(%)",        float(d.get("이익률", 0))),
            ]
            pd.DataFrame(rows, columns=["구분", "항목", "금액"]).to_excel(
                w, sheet_name=br[:31], index=False)
    buf.seek(0)
    fn = quote(f"정산서_{year}년{month:02d}월.xlsx")
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{fn}"})


# ── 직원 CRUD ─────────────────────────────────────────────────
class EmployeeBody(BaseModel):
    id:          int = 0
    name:        str
    branch:      str = ""
    emp_type:    str = "insured"
    base_salary: int = 0
    dependents:  int = 1
    meal:        int = 0
    transport:   int = 0
    email:       str = ""
    phone:       str = ""
    work_start:  str = "09:00"
    work_end:    str = "18:00"
    hourly_rate: int = 0
    join_date:   str = ""
    note:        str = ""


@app.post("/api/employees")
async def api_emp_upsert(request: Request, body: EmployeeBody):
    require_auth(request)
    from domains.payroll.db import upsert_employee, create_employee_account, get_employee_account
    data = body.dict()
    data["is_active"] = 1
    if not data["id"]:
        data.pop("id")
    eid = upsert_employee(data)
    # 전화번호 있으면 포털 계정 자동 생성
    phone = body.phone.replace("-", "").replace(" ", "")
    acc_msg = ""
    if len(phone) >= 8 and not get_employee_account(eid):
        ok, _ = create_employee_account(eid, phone, phone[-4:])
        if ok:
            acc_msg = f"포털 계정 생성: {phone} / 초기PW {phone[-4:]}"
    return {"id": eid, "account": acc_msg}


@app.delete("/api/employees/{emp_id}")
async def api_emp_delete(request: Request, emp_id: int):
    require_auth(request)
    from domains.payroll.db import delete_employee
    delete_employee(emp_id)
    return {"ok": True}


# ── 급여 계산 ─────────────────────────────────────────────────
@app.get("/api/payroll/entries")
async def api_payroll_entries(request: Request, year: int, month: int):
    require_auth(request)
    from domains.payroll.db import get_payroll_entries
    return get_payroll_entries(year, month)


class PayrollConfirmBody(BaseModel):
    year:     int
    month:    int
    payments: dict   # {employee_id(str): gross(int)}


@app.post("/api/payroll/confirm")
async def api_payroll_confirm(request: Request, body: PayrollConfirmBody):
    """급여 확정: 기존 삭제 → 직원 유형별 계산 → 저장 (공단 실납부액 자동 적용)"""
    require_auth(request)
    from domains.payroll.db import (
        get_all_employees, delete_payroll_entries, save_payroll_entry,
        get_insurance_actual,
    )
    from domains.payroll.calculation.service import calc_insured, calc_freelance, calc_business
    from domains.payroll.insurance.service import apply_insurance_actuals

    emps = {e["id"]: e for e in get_all_employees()}
    delete_payroll_entries(body.year, body.month)
    ok = actual_applied = 0
    errors = []
    for emp_id_s, gross in body.payments.items():
        emp_id = int(emp_id_s)
        gross  = int(gross or 0)
        if gross <= 0 or emp_id not in emps:
            continue
        emp = emps[emp_id]
        try:
            if emp["emp_type"] == "insured":
                entry  = calc_insured(emp, body.year, body.month, override_gross=gross)
                actual = get_insurance_actual(body.year, body.month, emp_id)
                if actual:
                    entry = apply_insurance_actuals(entry, actual)
                    actual_applied += 1
            elif emp["emp_type"] == "business":
                entry = calc_business(emp, body.year, body.month, gross)
            else:
                entry = calc_freelance(emp, body.year, body.month, gross)
            if save_payroll_entry(entry):
                ok += 1
            else:
                errors.append(f"{emp['name']} 저장 실패")
        except Exception as e:
            errors.append(f"{emp['name']}: {e}")
    return {"ok": ok, "actual_applied": actual_applied, "errors": errors}


# ── 4대보험 고지내역 업로드 ────────────────────────────────────
@app.post("/api/upload/insurance")
async def api_upload_insurance(
    request: Request, year: int = Form(...), month: int = Form(...),
    pension: UploadFile = File(None), health: UploadFile = File(None),
    employ:  UploadFile = File(None),
):
    require_auth(request)
    from domains.payroll.insurance.service import (
        parse_pension, parse_health, parse_employment, merge_insurance_records,
    )
    from domains.payroll.db import save_insurance_actuals
    import io
    pension_recs = health_recs = employ_recs = []
    errs = []
    if pension and pension.filename:
        recs, e = parse_pension(io.BytesIO(await pension.read()))
        pension_recs = recs; errs += e
    if health and health.filename:
        recs, e = parse_health(io.BytesIO(await health.read()))
        health_recs = recs; errs += e
    if employ and employ.filename:
        recs, e = parse_employment(io.BytesIO(await employ.read()))
        employ_recs = recs; errs += e
    merged = merge_insurance_records(pension_recs, health_recs, employ_recs)
    if not merged:
        raise HTTPException(400, "파싱된 내역이 없습니다. " + " / ".join(map(str, errs[:3])))
    saved, unmatched = save_insurance_actuals(year, month, merged)
    return {"ok": True, "saved": saved, "matched": saved - unmatched,
            "unmatched": unmatched, "errors": [str(e) for e in errs[:5]]}


# ── 백업 / 복원 ───────────────────────────────────────────────
_BACKUP_DIR = WEBAPP_DIR / "backups"
_DB_FILE    = WEBAPP_DIR / "data" / "settlement.db"


@app.get("/api/backups")
async def api_backups(request: Request):
    require_auth(request)
    _BACKUP_DIR.mkdir(exist_ok=True)
    out = []
    for p in sorted(_BACKUP_DIR.glob("settlement_*.db"), reverse=True):
        out.append({"name": p.name, "size_mb": round(p.stat().st_size / 1048576, 1),
                    "ts": p.stem.replace("settlement_", "")})
    return out


@app.post("/api/backups")
async def api_backup_create(request: Request):
    require_auth(request)
    import shutil
    from datetime import datetime as _dt
    _BACKUP_DIR.mkdir(exist_ok=True)
    ts = _dt.now().strftime("%Y%m%d_%H%M%S")
    shutil.copy2(_DB_FILE, _BACKUP_DIR / f"settlement_{ts}.db")
    # 최근 7개 유지
    backups = sorted(_BACKUP_DIR.glob("settlement_*.db"), reverse=True)
    for old in backups[7:]:
        old.unlink()
    return {"ok": True, "name": f"settlement_{ts}.db"}


class RestoreBody(BaseModel):
    name: str


@app.post("/api/backups/restore")
async def api_backup_restore(request: Request, body: RestoreBody):
    require_auth(request)
    import shutil
    import re as _re
    from datetime import datetime as _dt
    if not _re.fullmatch(r"settlement_\d{8}_\d{6}\.db", body.name):
        raise HTTPException(400, "잘못된 백업 파일명")
    src = _BACKUP_DIR / body.name
    if not src.exists():
        raise HTTPException(404, "백업 파일이 없습니다")
    broken = _BACKUP_DIR / f"broken_{_dt.now().strftime('%Y%m%d_%H%M%S')}.db"
    shutil.copy2(_DB_FILE, broken)
    shutil.copy2(src, _DB_FILE)
    return {"ok": True, "msg": f"{body.name} 복원 완료 — 현재 DB는 {broken.name}으로 보존됨"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8503)
