"""
branch_server.py — 라온스포츠 지점 포털 FastAPI 서버
Port: 8502  |  Auth: JWT (8h)  |  DB: data/settlement.db (shared with ERP)
"""

from __future__ import annotations

import hashlib
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import bcrypt
from fastapi import (
    Depends, FastAPI, File, Form, HTTPException, Request, UploadFile,
    status,
)
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from jose import JWTError, jwt
from pydantic import BaseModel

# ── Domain imports ─────────────────────────────────────────────────────────────
from domains.branch_app.db import (
    init_branch_tables,
    get_announcements, create_announcement,
    get_as_requests, create_as_request, update_as_status,
    get_supply_requests, create_supply_request, update_supply_status,
    get_inventory, upsert_inventory_item, adjust_inventory,
    get_members, get_member, upsert_member,
    get_member_memberships, create_membership,
    get_class_schedules, upsert_class_schedule,
)
from domains.payroll.db import (
    init_payroll_tables,
    attendance_clock_in, attendance_clock_out,
    attendance_break_start, attendance_break_end,
    get_attendance_record, get_monthly_attendance,
    get_payroll_entries, calc_and_save_daily_pay,
    get_daily_pay_records, get_monthly_pay_total,
    verify_employee_login,
    get_person_uid, get_person_branches, get_employee_brief,
    get_employee_roles, ROLE_LABELS,
)
from shared.db import get_conn

# ── JWT Config ─────────────────────────────────────────────────────────────────
def _load_secret_key() -> str:
    """data/settings.json에서 시크릿 키 로드 (없으면 자동 생성) — 하드코딩 제거"""
    import json as _json
    import secrets as _secrets
    sp = Path(__file__).parent / "data" / "settings.json"
    data: dict = {}
    if sp.exists():
        try:
            with open(sp, encoding="utf-8") as f:
                data = _json.load(f)
        except Exception:
            pass
    if "portal_secret_key" not in data:
        data["portal_secret_key"] = _secrets.token_hex(32)
        sp.parent.mkdir(exist_ok=True)
        with open(sp, "w", encoding="utf-8") as f:
            _json.dump(data, f, ensure_ascii=False, indent=2)
    return data["portal_secret_key"]

SECRET_KEY = _load_secret_key()
ALGORITHM  = "HS256"
TOKEN_EXPIRE_HOURS = 8

# ── Paths ──────────────────────────────────────────────────────────────────────
# 통합 레포(WebSettle2): ERP는 templates/static, CRM은 templates_crm/static_crm 사용
BASE_DIR     = Path(__file__).parent
STATIC_DIR   = BASE_DIR / "static_crm"
UPLOAD_DIR   = STATIC_DIR / "uploads"
TEMPLATE_DIR = BASE_DIR / "templates_crm"

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(title="라온스포츠 지점 포털", version="3.0.0")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# 정적 파일 캐시 무효화: app.js 수정 시각을 버전으로 사용 (?v=...)
try:
    _ASSET_VER = str(int((STATIC_DIR / "js" / "app.js").stat().st_mtime))
except Exception:
    _ASSET_VER = "1"
templates.env.globals["asset_ver"] = _ASSET_VER


# ── Startup ────────────────────────────────────────────────────────────────────
def init_all_tables():
    """Initialize all required tables on startup."""
    init_payroll_tables()   # includes employee_accounts, attendance, employees, roles
    init_branch_tables()    # includes members, inventory, announcements, etc.
    _init_events_tables()   # events, event_comments, instructors
    from domains.branch_app.approvals import init_approval_tables
    init_approval_tables()  # approval_items, notifications
    from domains.branch_app.crm_ext import init_crm_ext_tables
    init_crm_ext_tables()   # products 정산필드, PT/GX/페이롤/보고/환불/민원 등


def _init_events_tables():
    """Create events, event_comments, instructors tables."""
    conn = get_conn()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        branch      TEXT NOT NULL,
        title       TEXT NOT NULL,
        sub         TEXT DEFAULT '',
        eyebrow     TEXT DEFAULT '',
        content     TEXT DEFAULT '',
        image_path  TEXT DEFAULT '',
        ends_at     TEXT DEFAULT '',
        is_active   INTEGER DEFAULT 1,
        created_by  TEXT DEFAULT '',
        created_at  TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS event_comments (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id   INTEGER NOT NULL,
        author     TEXT NOT NULL,
        content    TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS portal_inquiries (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        type        TEXT NOT NULL,          -- 'pw_reset' | 'account' | 'etc'
        name        TEXT NOT NULL,
        phone       TEXT NOT NULL,
        branch      TEXT DEFAULT '',
        message     TEXT DEFAULT '',
        status      TEXT DEFAULT 'open',    -- 'open' | 'done'
        created_at  TEXT DEFAULT (datetime('now','localtime')),
        resolved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS instructors (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        branch       TEXT NOT NULL,
        name         TEXT NOT NULL,
        english      TEXT DEFAULT '',
        role         TEXT DEFAULT '',
        bio          TEXT DEFAULT '',
        tags         TEXT DEFAULT '[]',
        classes      TEXT DEFAULT '[]',
        curriculum   TEXT DEFAULT '',
        photo_path   TEXT DEFAULT '',
        is_active    INTEGER DEFAULT 1,
        created_at   TEXT DEFAULT (datetime('now','localtime'))
    );
    """)
    conn.commit()
    conn.close()


@app.on_event("startup")
async def on_startup():
    init_all_tables()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _rows(cur) -> list[dict]:
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _one(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row  = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def verify_password(plain: str, hashed: str) -> bool:
    """Support both bcrypt and sha256 hashes."""
    if not plain or not hashed:
        return False
    # Detect bcrypt (starts with $2b$ or $2a$)
    h = hashed.encode() if isinstance(hashed, str) else hashed
    if h.startswith(b"$2"):
        try:
            return bcrypt.checkpw(plain.encode(), h)
        except Exception:
            return False
    # Fallback: sha256 (used by existing employee accounts)
    return hashlib.sha256(plain.strip().encode("utf-8")).hexdigest() == hashed


def create_token(payload: dict) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode({**payload, "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError as e:
        raise HTTPException(status_code=401, detail=f"토큰이 유효하지 않습니다: {e}")


def get_token_from_request(request: Request) -> Optional[str]:
    """Extract bearer token from Authorization header or cookie."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.cookies.get("raon_token")


def require_auth(request: Request) -> dict:
    token = get_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="로그인이 필요합니다")
    return decode_token(token)


def require_staff(request: Request) -> dict:
    user = require_auth(request)
    if user.get("role") != "staff":
        raise HTTPException(status_code=403, detail="직원 전용 기능입니다")
    return user


def user_roles(user: dict) -> list[str]:
    """토큰의 직무 목록. ERP admin/지점관리자는 전 직무 동급."""
    if user.get("admin"):
        return list(ROLE_LABELS.keys())
    roles = user.get("roles") or []
    if "manager" in roles:
        # 지점관리자는 자기 지점 내 모든 직무 기능 열람 가능
        return list(ROLE_LABELS.keys())
    return roles


def require_role(request: Request, *allowed: str) -> dict:
    """지정된 직무 중 하나라도 보유해야 통과. admin/manager는 항상 통과."""
    user = require_staff(request)
    have = set(user_roles(user))
    if have.intersection(allowed) or user.get("admin"):
        return user
    raise HTTPException(status_code=403, detail="이 기능에 대한 권한이 없습니다")


def require_member(request: Request) -> dict:
    user = require_auth(request)
    if user.get("role") != "member":
        raise HTTPException(status_code=403, detail="회원 전용 기능입니다")
    return user


def _scope_branch(user: dict, requested: str = "") -> str:
    """지점 접근 제한: 일반 직원은 자기 지점만, ERP 관리자(admin)는 요청 지점 그대로."""
    if user.get("admin"):
        return requested
    return user.get("branch", "") or requested


# ── 로그인 시도 제한 (brute-force 방어) ─────────────────────────────────────────
_login_attempts: dict = {}   # {identifier: [timestamp, ...]}
_LOCKOUT_MAX    = 5          # 10분 내 5회 실패 시 잠금
_LOCKOUT_WINDOW = 600

def _check_rate_limit(identifier: str):
    now = time.time()
    attempts = [t for t in _login_attempts.get(identifier, []) if now - t < _LOCKOUT_WINDOW]
    _login_attempts[identifier] = attempts
    if len(attempts) >= _LOCKOUT_MAX:
        raise HTTPException(status_code=429,
                            detail="로그인 시도가 너무 많습니다. 10분 후 다시 시도하세요.")

def _record_fail(identifier: str):
    _login_attempts.setdefault(identifier, []).append(time.time())

def _clear_fails(identifier: str):
    _login_attempts.pop(identifier, None)


# ── 비밀번호 정책 ────────────────────────────────────────────────────────────────
def _validate_pw_policy(pw: str) -> str | None:
    """정책 위반 시 오류 메시지, 통과 시 None"""
    if len(pw) < 8:
        return "비밀번호는 최소 8자 이상이어야 합니다."
    if not re.search(r"[A-Z]", pw):
        return "대문자를 1자 이상 포함해야 합니다."
    if not re.search(r"[a-z]", pw):
        return "소문자를 1자 이상 포함해야 합니다."
    if not re.search(r"[0-9]", pw):
        return "숫자를 1자 이상 포함해야 합니다."
    return None


def save_upload(file: UploadFile) -> str:
    """Save uploaded file to static/uploads/ and return URL path."""
    ext  = Path(file.filename).suffix if file.filename else ""
    name = f"{uuid.uuid4().hex}{ext}"
    dest = UPLOAD_DIR / name
    with open(dest, "wb") as f:
        f.write(file.file.read())
    return f"/static/uploads/{name}"


# ── Page Routes ────────────────────────────────────────────────────────────────
@app.get("/")
async def root(request: Request):
    token = get_token_from_request(request)
    if not token:
        return RedirectResponse("/login")
    try:
        decode_token(token)
        return RedirectResponse("/home")
    except HTTPException:
        return RedirectResponse("/login")


@app.get("/login")
async def login_page(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")


@app.get("/home")
async def home_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "home"})


@app.get("/attendance")
async def attendance_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "attendance"})


@app.get("/operations")
async def operations_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "operations"})


@app.get("/members")
async def members_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "members"})


@app.get("/classes")
async def classes_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "classes"})


@app.get("/instructors")
async def instructors_page(request: Request):
    return templates.TemplateResponse(request=request, name="app.html", context={"page": "instructors"})


# ── Auth API ───────────────────────────────────────────────────────────────────
class LoginBody(BaseModel):
    role:       str   # "staff" | "member"
    identifier: str
    password:   str


def _issue_staff_token(name: str, branch_row: dict, must_change_pw: bool) -> dict:
    """선택된 지점(branch_row: {employee_id, branch, roles}) 기준 정식 토큰 발급."""
    eid    = branch_row["employee_id"]
    branch = branch_row["branch"]
    roles  = branch_row["roles"]
    token = create_token({
        "sub":            str(eid),
        "role":           "staff",
        "admin":          False,
        "name":           name,
        "branch":         branch,
        "roles":          roles,
        "must_change_pw": must_change_pw,
    })
    return {
        "token":          token,
        "role":           "staff",
        "admin":          False,
        "name":           name,
        "branch":         branch,
        "roles":          roles,
        "role_labels":    [ROLE_LABELS.get(r, r) for r in roles],
        "must_change_pw": must_change_pw,
    }


class BranchSelectBody(BaseModel):
    ticket:      str
    employee_id: int


@app.post("/api/auth/select-branch")
async def api_select_branch(body: BranchSelectBody):
    """멀티지점 직원의 지점 선택 → 정식 토큰 발급."""
    data = decode_token(body.ticket)
    if data.get("purpose") != "branch_select":
        raise HTTPException(status_code=400, detail="잘못된 선택 요청입니다")
    puid = data.get("person_uid", "")
    branches = get_person_branches(puid)
    chosen = next((b for b in branches if b["employee_id"] == body.employee_id), None)
    if not chosen:
        raise HTTPException(status_code=403, detail="선택한 지점에 접근 권한이 없습니다")
    return _issue_staff_token(
        data.get("name", ""), chosen, bool(data.get("must_change_pw", False)))


@app.post("/api/auth/login")
async def api_login(body: LoginBody):
    identifier = body.identifier.strip()
    _check_rate_limit(identifier)

    if body.role == "staff":
        # 1) ERP 관리자 계정 (admin) — 전 지점 접근 가능
        try:
            from modules.auth import verify_login as _erp_verify
            erp_user = _erp_verify(identifier, body.password)
        except Exception:
            erp_user = None
        if erp_user and erp_user.get("role") == "admin":
            _clear_fails(identifier)
            token = create_token({
                "sub":    "0",
                "role":   "staff",
                "admin":  True,
                "name":   erp_user["name"],
                "branch": "",
                "roles":  ["manager"],
                "must_change_pw": False,
            })
            return {
                "token": token, "role": "staff", "admin": True,
                "name": erp_user["name"], "branch": "", "roles": ["manager"],
                "must_change_pw": False,
            }

        # 2) 일반 직원 계정 — 자격증명 확인
        emp = verify_employee_login(identifier, body.password)
        if not emp:
            _record_fail(identifier)
            raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다")
        _clear_fails(identifier)

        # 사람(person_uid) 기준으로 로그인 가능한 지점들 조회
        puid = get_person_uid(emp["employee_id"])
        branches = get_person_branches(puid)
        if not branches:
            raise HTTPException(
                status_code=403,
                detail="배정된 직무가 없습니다. 관리자에게 직무 지정을 요청하세요.")

        # 지점이 여러 개 → 지점 선택 단계 (단기 ticket 발급)
        if len(branches) > 1:
            ticket = create_token({
                "purpose": "branch_select", "person_uid": puid,
                "name": emp["name"], "must_change_pw": emp.get("must_change_pw", False),
            })
            return {
                "needs_branch_selection": True,
                "ticket": ticket,
                "name": emp["name"],
                "branches": [
                    {"employee_id": b["employee_id"], "branch": b["branch"],
                     "roles": b["roles"],
                     "role_labels": [ROLE_LABELS.get(r, r) for r in b["roles"]]}
                    for b in branches
                ],
            }

        # 지점 1개 → 바로 토큰 발급
        b = branches[0]
        return _issue_staff_token(emp["name"], b, emp.get("must_change_pw", False))

    elif body.role == "member":
        conn = get_conn()
        # Match by phone (last 4 = PIN) or email
        member = _one(conn.execute(
            "SELECT * FROM members WHERE (phone=? OR email=?) AND status='active' LIMIT 1",
            (identifier, identifier)
        ))
        conn.close()
        if not member:
            _record_fail(identifier)
            raise HTTPException(status_code=401, detail="회원 정보를 찾을 수 없습니다")
        # PIN check: stored as last 4 digits of phone, or pin column
        pin = str(member.get("pin", ""))
        if not pin or (not verify_password(body.password, pin) and body.password != pin):
            _record_fail(identifier)
            raise HTTPException(status_code=401, detail="비밀번호(PIN)가 올바르지 않습니다")
        _clear_fails(identifier)
        token = create_token({
            "sub":    str(member["id"]),
            "role":   "member",
            "name":   member["name"],
            "branch": member.get("branch", ""),
        })
        return {
            "token":  token,
            "role":   "member",
            "name":   member["name"],
            "branch": member.get("branch", ""),
            "must_change_pw": False,
        }

    raise HTTPException(status_code=400, detail="role은 'staff' 또는 'member'여야 합니다")


class InquiryBody(BaseModel):
    type:    str = "etc"   # 'pw_reset' | 'account' | 'etc'
    name:    str
    phone:   str
    branch:  str = ""
    message: str = ""


@app.post("/api/auth/inquiry")
async def api_inquiry(body: InquiryBody):
    """비로그인 문의 접수 (비밀번호 초기화 요청 / 계정 문의) → ERP에서 확인"""
    name  = body.name.strip()
    phone = re.sub(r"[^0-9]", "", body.phone.strip())
    if not name or len(phone) < 8:
        raise HTTPException(status_code=400, detail="이름과 올바른 전화번호를 입력하세요")
    # 도배 방지: 같은 전화번호로 미처리 문의 3건 이상이면 차단
    conn = get_conn()
    cnt = conn.execute(
        "SELECT COUNT(*) FROM portal_inquiries WHERE phone=? AND status='open'", (phone,)
    ).fetchone()[0]
    if cnt >= 3:
        conn.close()
        raise HTTPException(status_code=429, detail="이미 접수된 문의가 있습니다. 관리자 확인을 기다려 주세요.")
    conn.execute(
        "INSERT INTO portal_inquiries (type, name, phone, branch, message) VALUES (?,?,?,?,?)",
        (body.type, name, phone, body.branch.strip(), body.message.strip()[:500])
    )
    conn.commit()
    conn.close()
    return {"ok": True, "msg": "접수되었습니다. 관리자 확인 후 연락드립니다."}


@app.get("/api/branches")
async def api_branches(request: Request):
    """활성 지점 목록 — 관리자 지점 선택기용"""
    require_auth(request)
    conn = get_conn()
    rows = conn.execute(
        "SELECT name FROM branches WHERE is_active=1 ORDER BY name").fetchall()
    conn.close()
    return [r[0] for r in rows]


@app.post("/api/auth/logout")
async def api_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("raon_token")
    return response


# ── 결재 / 알림 ──────────────────────────────────────────────────────────────────
def _notif_scope(user: dict) -> tuple[str, str, int]:
    """(target_kind, branch, employee_id) — 현재 사용자의 알림 수신 범위."""
    if user.get("admin"):
        return ("hq_admin", "", 0)
    roles = user.get("roles") or []
    if "manager" in roles:
        return ("branch_manager", user.get("branch", ""), 0)
    return ("employee", user.get("branch", ""), int(user.get("sub") or 0))


@app.get("/api/notifications")
async def api_notifications(request: Request, unread: int = 0):
    user = require_auth(request)
    from domains.branch_app.approvals import get_notifications
    kind, branch, eid = _notif_scope(user)
    return get_notifications(kind, branch, eid, unread_only=bool(unread))


@app.get("/api/notifications/count")
async def api_notifications_count(request: Request):
    user = require_auth(request)
    from domains.branch_app.approvals import unread_count
    kind, branch, eid = _notif_scope(user)
    return {"count": unread_count(kind, branch, eid)}


@app.post("/api/notifications/{notif_id}/read")
async def api_notification_read(request: Request, notif_id: int):
    require_auth(request)
    from domains.branch_app.approvals import mark_notification_read
    mark_notification_read(notif_id)
    return {"ok": True}


@app.post("/api/notifications/read-all")
async def api_notifications_read_all(request: Request):
    user = require_auth(request)
    from domains.branch_app.approvals import mark_all_read
    kind, branch, eid = _notif_scope(user)
    mark_all_read(kind, branch, eid)
    return {"ok": True}


@app.get("/api/approvals")
async def api_approvals(request: Request, box: str = "inbox"):
    """box=inbox: 내가 처리할 결재 / box=mine: 내가 올린 결재 / box=all(지점)"""
    user = require_staff(request)
    from domains.branch_app.approvals import list_approvals
    if box == "mine":
        return list_approvals(created_by=int(user.get("sub") or 0))
    if user.get("admin"):
        return list_approvals(stage="hq", status="branch_ok") if box == "inbox" \
            else list_approvals()
    roles = user.get("roles") or []
    branch = user.get("branch", "")
    if "manager" in roles:
        if box == "inbox":
            return list_approvals(branch=branch, stage="branch", status="pending")
        return list_approvals(branch=branch)
    # 일반 직원 → 내가 올린 것만
    return list_approvals(created_by=int(user.get("sub") or 0))


@app.post("/api/approvals/{approval_id}/approve")
async def api_approval_approve(request: Request, approval_id: int):
    user = require_staff(request)
    from domains.branch_app.approvals import approve_branch, approve_hq
    name = user.get("name", "")
    if user.get("admin"):
        ok = approve_hq(approval_id, name or "본사관리자")
    elif "manager" in (user.get("roles") or []):
        ok = approve_branch(approval_id, name or "지점관리자")
    else:
        raise HTTPException(status_code=403, detail="결재 권한이 없습니다")
    if not ok:
        raise HTTPException(status_code=400, detail="처리할 수 없는 결재 상태입니다")
    return {"ok": True}


class RejectBody(BaseModel):
    reason: str = ""


@app.post("/api/approvals/{approval_id}/reject")
async def api_approval_reject(request: Request, approval_id: int, body: RejectBody):
    user = require_staff(request)
    if not (user.get("admin") or "manager" in (user.get("roles") or [])):
        raise HTTPException(status_code=403, detail="결재 권한이 없습니다")
    from domains.branch_app.approvals import reject_approval
    reject_approval(approval_id, user.get("name", ""), body.reason)
    return {"ok": True}


@app.get("/api/auth/me")
async def api_me(request: Request):
    user = require_auth(request)
    roles = user.get("roles") or []
    return {
        "id":     user.get("sub"),
        "role":   user.get("role"),
        "name":   user.get("name"),
        "branch": user.get("branch"),
        "admin":  bool(user.get("admin")),
        "roles":  roles,
        "role_labels": [ROLE_LABELS.get(r, r) for r in roles],
        "effective_roles": user_roles(user),
        "must_change_pw": bool(user.get("must_change_pw")),
    }


class ChangePwBody(BaseModel):
    current_password: str
    new_password:     str


@app.post("/api/auth/change-password")
async def api_change_password(request: Request, body: ChangePwBody):
    """직원 비밀번호 변경 — 정책: 최소 8자, 대문자+소문자+숫자 포함"""
    user = require_staff(request)
    if user.get("admin"):
        raise HTTPException(status_code=400, detail="관리자 비밀번호는 ERP에서 변경하세요")

    # 정책 검증
    err = _validate_pw_policy(body.new_password)
    if err:
        raise HTTPException(status_code=400, detail=err)

    # 현재 비밀번호 확인
    from domains.payroll.db import update_employee_password
    emp_id = int(user["sub"])
    conn = get_conn()
    row = conn.execute(
        "SELECT username FROM employee_accounts WHERE employee_id=?", (emp_id,)
    ).fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="계정을 찾을 수 없습니다")
    if not verify_employee_login(row[0], body.current_password):
        raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다")

    if not update_employee_password(emp_id, body.new_password):
        raise HTTPException(status_code=500, detail="비밀번호 변경에 실패했습니다")

    # 새 토큰 발급 (must_change_pw 해제)
    token = create_token({
        "sub":    user["sub"],
        "role":   "staff",
        "name":   user.get("name", ""),
        "branch": user.get("branch", ""),
        "must_change_pw": False,
    })
    return {"ok": True, "token": token}


# ── Home API ───────────────────────────────────────────────────────────────────
@app.get("/api/home/data")
async def api_home_data(request: Request):
    user = require_auth(request)
    branch = user.get("branch", "")
    conn = get_conn()

    anns_cur = conn.execute("""
        SELECT * FROM announcements
        WHERE (target_branch='all' OR target_branch=?)
          AND (expires_at IS NULL OR expires_at >= date('now'))
        ORDER BY priority DESC, created_at DESC LIMIT 3
    """, (branch,))
    announcements = _rows(anns_cur)

    events_cur = conn.execute("""
        SELECT * FROM events
        WHERE (branch=? OR branch='all') AND is_active=1
          AND (ends_at='' OR ends_at >= date('now'))
        ORDER BY created_at DESC LIMIT 3
    """, (branch,))
    events = _rows(events_cur)

    classes_cur = conn.execute("""
        SELECT * FROM class_schedules
        WHERE branch=? AND is_active=1
        ORDER BY start_time LIMIT 4
    """, (branch,))
    classes = _rows(classes_cur)

    conn.close()
    return {"announcements": announcements, "events": events, "classes": classes}


@app.get("/api/home/announcements")
async def api_home_announcements(request: Request):
    user = require_auth(request)
    branch = user.get("branch", "")
    anns = get_announcements(branch)
    return anns


# ── Attendance API ─────────────────────────────────────────────────────────────
@app.get("/api/attendance/today")
async def api_attendance_today(request: Request):
    user = require_staff(request)
    today = datetime.now().strftime("%Y-%m-%d")
    rec   = get_attendance_record(int(user["sub"]), today)
    return rec or {
        "clock_in": None, "clock_out": None, "break_start": None,
        "break_minutes": 0, "status": None, "work_minutes": 0
    }


import math as _math

def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    R = 6_371_000
    p1, p2 = _math.radians(lat1), _math.radians(lat2)
    dp = _math.radians(lat2 - lat1)
    dl = _math.radians(lng2 - lng1)
    a  = _math.sin(dp/2)**2 + _math.cos(p1)*_math.cos(p2)*_math.sin(dl/2)**2
    return R * 2 * _math.atan2(_math.sqrt(a), _math.sqrt(1 - a))


def _gps_check(branch: str, user_lat: float | None, user_lng: float | None) -> str:
    """
    GPS 위치 검증. 반환값: 'ok' | 'skipped'
    - GPS null → HTTPException 400 (모바일 전용, GPS 필수)
    - 지점 좌표 미등록 → 'skipped'
    - 범위 이탈 → HTTPException 400
    """
    if user_lat is None or user_lng is None:
        raise HTTPException(status_code=400, detail="GPS 위치를 확인할 수 없습니다. 위치 권한을 허용하고 다시 시도해 주세요.")
    conn = get_conn()
    row  = conn.execute(
        "SELECT lat, lng, attendance_radius FROM branches WHERE name=?", (branch,)
    ).fetchone()
    conn.close()
    if not row or not row[0] or not row[1]:
        return "skipped"  # 지점 좌표 미등록 — GPS 좌표만 기록
    b_lat, b_lng, radius = float(row[0]), float(row[1]), int(row[2] or 300)
    dist = _haversine_m(b_lat, b_lng, user_lat, user_lng)
    if dist > radius:
        raise HTTPException(
            status_code=400,
            detail=f"현재 위치가 지점에서 {dist:.0f}m 떨어져 있습니다. (허용 {radius}m 이내)"
        )
    return "ok"


class ClockBody(BaseModel):
    time: Optional[str] = None   # HH:MM, defaults to now
    lat:  Optional[float] = None  # GPS 위도
    lng:  Optional[float] = None  # GPS 경도


@app.post("/api/attendance/clock-in")
async def api_clock_in(request: Request, body: ClockBody):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    today  = datetime.now().strftime("%Y-%m-%d")
    now_t  = body.time or datetime.now().strftime("%H:%M")
    gps_st = _gps_check(user.get("branch", ""), body.lat, body.lng)
    ok, msg = attendance_clock_in(emp_id, today, now_t)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "time": now_t, "gps": gps_st}


@app.post("/api/attendance/clock-out")
async def api_clock_out(request: Request, body: ClockBody):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    today  = datetime.now().strftime("%Y-%m-%d")
    now_t  = body.time or datetime.now().strftime("%H:%M")
    gps_st = _gps_check(user.get("branch", ""), body.lat, body.lng)
    conn = get_conn()
    emp_row = conn.execute(
        "SELECT work_start FROM employees WHERE id=?", (emp_id,)
    ).fetchone()
    conn.close()
    work_start = emp_row[0] if emp_row and emp_row[0] else "09:00"
    ok, msg = attendance_clock_out(emp_id, today, now_t, work_start)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    try:
        calc_and_save_daily_pay(emp_id, today)
    except Exception:
        pass
    return {"ok": True, "time": now_t, "gps": gps_st}


@app.post("/api/attendance/break-start")
async def api_break_start(request: Request, body: ClockBody):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    today  = datetime.now().strftime("%Y-%m-%d")
    now_t  = body.time or datetime.now().strftime("%H:%M")
    _gps_check(user.get("branch", ""), body.lat, body.lng)
    ok, msg = attendance_break_start(emp_id, today, now_t)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "time": now_t}


@app.post("/api/attendance/break-end")
async def api_break_end(request: Request, body: ClockBody):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    today  = datetime.now().strftime("%Y-%m-%d")
    now_t  = body.time or datetime.now().strftime("%H:%M")
    _gps_check(user.get("branch", ""), body.lat, body.lng)
    ok, msg = attendance_break_end(emp_id, today, now_t)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg}


@app.get("/api/attendance/pay")
async def api_attendance_pay(request: Request, year: int = None, month: int = None):
    """시급제 직원의 월별 급여 기록"""
    user   = require_staff(request)
    emp_id = int(user["sub"])
    now    = datetime.now()
    year   = year  or now.year
    month  = month or now.month
    records = get_daily_pay_records(emp_id, year, month)
    total   = get_monthly_pay_total(emp_id, year, month)
    return {"records": records, "total": total}


@app.get("/api/attendance/monthly")
async def api_attendance_monthly(request: Request, year: int = None, month: int = None):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    now    = datetime.now()
    year   = year  or now.year
    month  = month or now.month
    records = get_monthly_attendance(emp_id, year, month)
    return records


@app.get("/api/attendance/class-schedule")
async def api_attendance_class_schedule(request: Request, year: int = None, month: int = None):
    user   = require_staff(request)
    emp_id = int(user["sub"])
    now    = datetime.now()
    year   = year  or now.year
    month  = month or now.month
    entries = get_payroll_entries(year, month)
    # Filter to current employee
    my_entries = [e for e in entries if e.get("employee_id") == emp_id]
    return my_entries


# ── Operations: Inventory ──────────────────────────────────────────────────────
@app.get("/api/operations/inventory")
async def api_inventory_get(request: Request, branch: str = ""):
    user = require_staff(request)
    return get_inventory(_scope_branch(user, branch))


class InventoryItem(BaseModel):
    branch:       str
    item_name:    str
    category:     str = "일반"
    quantity:     int = 0
    min_quantity: int = 0
    unit:         str = "개"
    note:         str = ""


@app.post("/api/operations/inventory")
async def api_inventory_add(request: Request, body: InventoryItem):
    require_staff(request)
    rid = upsert_inventory_item(body.dict())
    return {"id": rid}


class AdjustBody(BaseModel):
    type: str  # "in" | "out"
    qty:  int
    note: str = ""


@app.post("/api/operations/inventory/{item_id}/adjust")
async def api_inventory_adjust(request: Request, item_id: int, body: AdjustBody):
    user = require_staff(request)
    adjust_inventory(item_id, body.type, body.qty, user.get("name", ""), body.note)
    # 재고 임계치 자동 알림 (min_qty 이하 → 관리자)
    conn = get_conn()
    row = conn.execute(
        "SELECT name, quantity, min_qty, branch FROM inventory_items WHERE id=?", (item_id,)
    ).fetchone()
    conn.close()
    if row and row[2] and row[1] <= row[2]:
        from domains.branch_app.approvals import branch_has_manager, _notify
        c = get_conn()
        kind = "branch_manager" if branch_has_manager(row[3]) else "hq_admin"
        _notify(c, row[3], kind, f"[재고부족] {row[0]} 잔여 {row[1]} (임계 {row[2]})")
        c.commit(); c.close()
    return {"ok": True}


# ── Operations: Supply Requests ────────────────────────────────────────────────
@app.get("/api/operations/supply")
async def api_supply_get(request: Request, branch: str = ""):
    user = require_staff(request)
    return get_supply_requests(_scope_branch(user, branch))


class SupplyBody(BaseModel):
    branch:       str
    item_name:    str
    quantity:     int = 1
    unit:         str = "개"
    reason:       str = ""
    created_name: str = ""


@app.post("/api/operations/supply")
async def api_supply_create(request: Request, body: SupplyBody):
    user = require_staff(request)
    data = body.dict()
    data["created_by"] = int(user["sub"])
    rid = create_supply_request(data)
    from domains.branch_app.approvals import create_approval
    branch = data.get("branch") or user.get("branch", "")
    create_approval(branch, "supply", rid,
                    f"물품요청 — {data.get('item_name','')} {data.get('quantity',1)}{data.get('unit','개')}",
                    created_by=int(user["sub"]), created_by_name=user.get("name", ""))
    return {"id": rid}


class SupplyPatchBody(BaseModel):
    status:        str
    approved_by:   str = ""
    reject_reason: str = ""
    deliver_date:  str = ""


@app.patch("/api/operations/supply/{req_id}")
async def api_supply_patch(request: Request, req_id: int, body: SupplyPatchBody):
    require_staff(request)
    update_supply_status(req_id, body.status, body.approved_by, body.reject_reason, body.deliver_date)
    return {"ok": True}


# ── Operations: A/S ───────────────────────────────────────────────────────────
@app.get("/api/operations/as")
async def api_as_get(request: Request, branch: str = ""):
    user = require_staff(request)
    return get_as_requests(_scope_branch(user, branch))


class AsBody(BaseModel):
    branch:       str
    title:        str
    description:  str = ""
    priority:     str = "normal"
    created_name: str = ""


@app.post("/api/operations/as")
async def api_as_create(request: Request, body: AsBody):
    user = require_staff(request)
    data = body.dict()
    data["created_by"] = int(user["sub"])
    rid = create_as_request(data)
    from domains.branch_app.approvals import create_approval
    branch = data.get("branch") or user.get("branch", "")
    summary = f"AS요청 — {data.get('title') or data.get('content','')[:30]}"
    create_approval(branch, "as", rid, summary,
                    created_by=int(user["sub"]), created_by_name=user.get("name", ""))
    return {"id": rid}


class AsPatchBody(BaseModel):
    status:      str
    assigned_to: str = ""
    note:        str = ""


@app.patch("/api/operations/as/{req_id}")
async def api_as_patch(request: Request, req_id: int, body: AsPatchBody):
    require_staff(request)
    update_as_status(req_id, body.status, body.assigned_to, body.note)
    return {"ok": True}


# ── Operations: Events ────────────────────────────────────────────────────────
@app.get("/api/operations/events")
async def api_events_get(request: Request, branch: str = ""):
    user = require_auth(request)
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM events WHERE (branch=? OR branch='all') ORDER BY created_at DESC",
        (_scope_branch(user, branch),)
    )
    rows = _rows(cur)
    conn.close()
    return rows


@app.post("/api/operations/events")
async def api_events_create(
    request: Request,
    branch:  str        = Form(""),
    title:   str        = Form(...),
    content: str        = Form(""),
    eyebrow: str        = Form(""),
    ends_at: str        = Form(""),
    image:   UploadFile = File(None),
):
    user = require_staff(request)
    image_path = save_upload(image) if image and image.filename else ""
    conn = get_conn()
    cur  = conn.execute(
        """INSERT INTO events (branch, title, content, eyebrow, ends_at, image_path, created_by)
           VALUES (?,?,?,?,?,?,?)""",
        (branch or user.get("branch", ""), title, content, eyebrow, ends_at,
         image_path, user.get("name", ""))
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return {"id": rid}


@app.get("/api/operations/events/{event_id}")
async def api_events_detail(request: Request, event_id: int):
    require_auth(request)
    conn = get_conn()
    ev   = _one(conn.execute("SELECT * FROM events WHERE id=?", (event_id,)))
    if not ev:
        conn.close()
        raise HTTPException(status_code=404, detail="이벤트를 찾을 수 없습니다")
    comments = _rows(conn.execute(
        "SELECT * FROM event_comments WHERE event_id=? ORDER BY created_at", (event_id,)
    ))
    conn.close()
    return {**ev, "comments": comments}


class EventPatchBody(BaseModel):
    title:     Optional[str] = None
    content:   Optional[str] = None
    eyebrow:   Optional[str] = None
    ends_at:   Optional[str] = None
    is_active: Optional[int] = None


@app.patch("/api/operations/events/{event_id}")
async def api_events_patch(request: Request, event_id: int, body: EventPatchBody):
    require_staff(request)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn = get_conn()
    conn.execute(f"UPDATE events SET {set_clause} WHERE id=?", (*updates.values(), event_id))
    conn.commit()
    conn.close()
    return {"ok": True}


class CommentBody(BaseModel):
    content: str


@app.post("/api/operations/events/{event_id}/comment")
async def api_events_comment(request: Request, event_id: int, body: CommentBody):
    user = require_auth(request)
    conn = get_conn()
    conn.execute(
        "INSERT INTO event_comments (event_id, author, content) VALUES (?,?,?)",
        (event_id, user.get("name", ""), body.content)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Operations: Announcements ─────────────────────────────────────────────────
@app.get("/api/operations/announcements")
async def api_announcements_get(request: Request, branch: str = ""):
    user = require_auth(request)
    return get_announcements(_scope_branch(user, branch))


class AnnouncementBody(BaseModel):
    title:         str
    content:       str = ""
    priority:      str = "normal"
    target_branch: str = "all"
    created_by:    str = ""
    expires_at:    Optional[str] = None


@app.post("/api/operations/announcements")
async def api_announcements_create(request: Request, body: AnnouncementBody):
    user = require_staff(request)
    data = body.dict()
    data["created_by"] = data["created_by"] or user.get("name", "")
    rid = create_announcement(data)
    return {"id": rid}


# ── Operations: Instructors ───────────────────────────────────────────────────
@app.get("/api/operations/instructors")
async def api_instructors_get(request: Request, branch: str = ""):
    user = require_auth(request)
    conn = get_conn()
    cur  = conn.execute(
        "SELECT * FROM instructors WHERE branch=? AND is_active=1 ORDER BY name",
        (_scope_branch(user, branch),)
    )
    rows = _rows(cur)
    conn.close()
    return rows


@app.post("/api/operations/instructors")
async def api_instructors_create(
    request:    Request,
    branch:     str        = Form(""),
    name:       str        = Form(...),
    english:    str        = Form(""),
    role:       str        = Form(""),
    bio:        str        = Form(""),
    tags:       str        = Form("[]"),
    classes:    str        = Form("[]"),
    curriculum: str        = Form(""),
    photo:      UploadFile = File(None),
):
    user = require_staff(request)
    photo_path = save_upload(photo) if photo and photo.filename else ""
    conn = get_conn()
    cur  = conn.execute(
        """INSERT INTO instructors (branch, name, english, role, bio, tags, classes, curriculum, photo_path)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (branch or user.get("branch", ""), name, english, role, bio,
         tags, classes, curriculum, photo_path)
    )
    conn.commit()
    rid = cur.lastrowid
    conn.close()
    return {"id": rid}


class InstructorPatchBody(BaseModel):
    name:       Optional[str] = None
    english:    Optional[str] = None
    role:       Optional[str] = None
    bio:        Optional[str] = None
    tags:       Optional[str] = None
    classes:    Optional[str] = None
    curriculum: Optional[str] = None
    is_active:  Optional[int] = None


@app.patch("/api/operations/instructors/{instructor_id}")
async def api_instructors_patch(request: Request, instructor_id: int, body: InstructorPatchBody):
    require_staff(request)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if not updates:
        return {"ok": True}
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn = get_conn()
    conn.execute(
        f"UPDATE instructors SET {set_clause} WHERE id=?",
        (*updates.values(), instructor_id)
    )
    conn.commit()
    conn.close()
    return {"ok": True}


# ── Members API ────────────────────────────────────────────────────────────────
@app.get("/api/members")
async def api_members_list(request: Request, branch: str = "", q: str = "", status: str = ""):
    user = require_staff(request)
    return get_members(_scope_branch(user, branch), status or None, q)


class MemberBody(BaseModel):
    branch:     str
    name:       str
    phone:      str = ""
    email:      str = ""
    birth_date: str = ""
    gender:     str = ""
    join_date:  str = ""
    status:     str = "active"
    pin:        str = ""
    note:       str = ""


@app.post("/api/members")
async def api_members_create(request: Request, body: MemberBody):
    require_staff(request)
    mid = upsert_member(body.dict())
    return {"id": mid}


@app.get("/api/members/{member_id}")
async def api_members_get(request: Request, member_id: int):
    require_staff(request)
    m = get_member(member_id)
    if not m:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")
    return m


class MemberPatchBody(BaseModel):
    name:       Optional[str] = None
    phone:      Optional[str] = None
    email:      Optional[str] = None
    birth_date: Optional[str] = None
    gender:     Optional[str] = None
    status:     Optional[str] = None
    note:       Optional[str] = None


@app.patch("/api/members/{member_id}")
async def api_members_patch(request: Request, member_id: int, body: MemberPatchBody):
    require_staff(request)
    existing = get_member(member_id)
    if not existing:
        raise HTTPException(status_code=404, detail="회원을 찾을 수 없습니다")
    updates = body.dict(exclude_none=True)
    merged  = {**existing, **updates, "id": member_id}
    upsert_member(merged)
    return {"ok": True}


@app.get("/api/members/{member_id}/memberships")
async def api_member_memberships(request: Request, member_id: int):
    require_staff(request)
    return get_member_memberships(member_id)


class MembershipBody(BaseModel):
    product_id:         Optional[int] = None
    product_name:       str = ""
    start_date:         str
    end_date:           Optional[str] = None
    remaining_sessions: int = 0
    paid_amount:        int = 0
    sold_by_name:       str = ""
    note:               str = ""


@app.post("/api/members/{member_id}/memberships")
async def api_member_memberships_create(request: Request, member_id: int, body: MembershipBody):
    require_staff(request)
    data = body.dict()
    data["member_id"] = member_id
    mid = create_membership(data)
    return {"id": mid}


# ── Products & Sales API (CRM) ─────────────────────────────────────────────────
from domains.branch_app.db import (
    get_products, upsert_product, deactivate_product, get_sales, create_sale,
)


@app.get("/api/products")
async def api_products_get(request: Request, branch: str = "", category: str = ""):
    user = require_auth(request)
    return get_products(_scope_branch(user, branch), category)


class ProductBody(BaseModel):
    id:              int = 0
    branch:          str = ""
    category:        str            # 'gx' | 'lesson' | 'goods'
    name:            str
    price:           int = 0        # 상품가액 (VAT 미포함, 정산 기준)
    instructor_name: str = ""
    days:            str = ""
    start_time:      str = ""
    end_time:        str = ""
    capacity:        int = 0
    lesson_type:     str = ""       # 'PT' | '골프레슨'
    sessions:        int = 0
    # 정산 설정 (lesson)
    pay_type:        str = ""       # 'percent' | 'per_session'
    session_rate:    int = 0        # per_session 단가
    # GX 담당강사 + 구간제
    instructor_employee_id: int = 0
    gx_base_amount:      int = 0
    gx_base_headcount:   int = 0
    gx_extra_per_person: int = 0


@app.post("/api/products")
async def api_products_create(request: Request, body: ProductBody):
    # 상품 등록/수정은 지점관리자·본사관리자만
    user = require_role(request, "manager")
    if body.category not in ("gx", "lesson", "goods"):
        raise HTTPException(status_code=400, detail="category는 gx/lesson/goods 중 하나여야 합니다")
    data = body.dict()
    data["branch"] = _scope_branch(user, body.branch) or user.get("branch", "")
    if not data["branch"]:
        raise HTTPException(status_code=400, detail="지점 정보가 없습니다")
    rid = upsert_product(data)
    # GX 구간제 룰 저장
    if body.category == "gx" and (body.gx_base_amount or body.gx_extra_per_person):
        from domains.branch_app.crm_ext import set_gx_pay_rule
        set_gx_pay_rule(rid, body.gx_base_amount, body.gx_base_headcount, body.gx_extra_per_person)
    return {"id": rid}


@app.get("/api/products/{product_id}/gx-rule")
async def api_gx_rule(request: Request, product_id: int):
    require_staff(request)
    from domains.branch_app.crm_ext import get_gx_pay_rule
    return get_gx_pay_rule(product_id) or {}


@app.delete("/api/products/{product_id}")
async def api_products_delete(request: Request, product_id: int):
    require_role(request, "manager")
    deactivate_product(product_id)
    return {"ok": True}


@app.get("/api/sales")
async def api_sales_get(request: Request, branch: str = "",
                        year: int = None, month: int = None):
    user = require_staff(request)
    return get_sales(_scope_branch(user, branch), year, month)


class SaleBody(BaseModel):
    branch:       str = ""
    member_id:    int = 0
    member_name:  str = ""
    product_id:   int = 0
    product_name: str
    category:     str = ""
    amount:       int = 0          # 미지정 시 상품가액 기준 자동(카드 VAT 가산)
    base_amount:  int = 0          # 상품가액(VAT 미포함)
    pay_method:   str = "카드"
    is_mgmt_fee:  int = 0
    sale_date:    str = ""
    instructor_employee_id: int = 0   # PT/레슨 담당강사 (판매 시 지정)


@app.post("/api/sales")
async def api_sales_create(request: Request, body: SaleBody):
    # 상품 판매: 인포·트레이너·프로·관리자 (GX강사 제외)
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import (
        charge_amount, get_product, create_lesson_enrollment, create_gx_enrollment)
    branch  = _scope_branch(user, body.branch) or user.get("branch", "")
    if not branch:
        raise HTTPException(status_code=400, detail="지점 정보가 없습니다")

    product = get_product(body.product_id) if body.product_id else None
    # 정산 기준 상품가액(VAT 제외)
    base = body.base_amount or (product["price"] if product else 0) or body.amount
    amount = body.amount or charge_amount(base, body.pay_method)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="결제 금액을 입력하세요")

    data = body.dict()
    data["branch"]  = branch
    data["sold_by"] = user.get("name", "")
    data["amount"]  = amount
    sale_id = create_sale(data)

    enrollment_id = 0
    if product and product.get("category") == "lesson":
        # 담당강사 정보 + %정산 스냅샷
        inst_name, comm = "", 0
        if body.instructor_employee_id:
            from domains.payroll.db import get_employee_brief
            b = get_employee_brief(body.instructor_employee_id)
            if b:
                inst_name = b["name"]; comm = b.get("commission_percent", 0)
        product["_commission_percent"] = comm
        product["price"] = base
        enrollment_id = create_lesson_enrollment(
            branch=branch, member_id=body.member_id, member_name=body.member_name,
            product=product, sale_id=sale_id,
            instructor_employee_id=body.instructor_employee_id, instructor_name=inst_name,
            pay_method=body.pay_method)
    elif product and product.get("category") == "gx":
        create_gx_enrollment(branch=branch, gx_product_id=product["id"],
                             member_id=body.member_id, member_name=body.member_name,
                             sale_id=sale_id)

    return {"id": sale_id, "amount": amount, "enrollment_id": enrollment_id}


# ── 강사 목록 (판매 시 담당강사·GX강사 선택) ────────────────────────────────────
@app.get("/api/branch-instructors")
async def api_branch_instructors(request: Request, branch: str = "", kind: str = "lesson"):
    user = require_staff(request)
    from domains.payroll.db import get_branch_staff_by_roles
    br = _scope_branch(user, branch) or user.get("branch", "")
    roles = ["gx"] if kind == "gx" else ["trainer", "golf_pro"]
    return get_branch_staff_by_roles(br, roles)


# ── PT/레슨 라이프사이클 ─────────────────────────────────────────────────────────
@app.get("/api/lessons/enrollments")
async def api_enrollments(request: Request, member_id: int = 0, mine: int = 0):
    user = require_staff(request)
    from domains.branch_app.crm_ext import get_enrollments
    branch = user.get("branch", "")
    if mine and not user.get("admin"):
        return get_enrollments(branch=branch, instructor_id=int(user.get("sub") or 0))
    return get_enrollments(branch=branch, member_id=member_id)


@app.get("/api/lessons/enrollment/{enrollment_id}")
async def api_enrollment_detail(request: Request, enrollment_id: int):
    require_staff(request)
    from domains.branch_app.crm_ext import get_enrollment, get_sessions
    enr = get_enrollment(enrollment_id)
    if not enr:
        raise HTTPException(status_code=404, detail="수강권을 찾을 수 없습니다")
    enr["sessions"] = get_sessions(enrollment_id)
    return enr


class InstructorChangeBody(BaseModel):
    employee_id: int


@app.post("/api/lessons/enrollment/{enrollment_id}/instructor")
async def api_change_instructor(request: Request, enrollment_id: int, body: InstructorChangeBody):
    user = require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import change_enrollment_instructor
    from domains.payroll.db import get_employee_brief
    b = get_employee_brief(body.employee_id)
    change_enrollment_instructor(enrollment_id, body.employee_id, b["name"] if b else "")
    return {"ok": True}


class ReserveBody(BaseModel):
    date: str
    time: str = ""


@app.post("/api/lessons/enrollment/{enrollment_id}/reserve")
async def api_reserve(request: Request, enrollment_id: int, body: ReserveBody):
    require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import reserve_session
    ok, msg = reserve_session(enrollment_id, body.date, body.time)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg}


@app.post("/api/lessons/session/{session_id}/cancel")
async def api_session_cancel(request: Request, session_id: int):
    require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import cancel_session
    return {"ok": cancel_session(session_id)}


@app.post("/api/lessons/session/{session_id}/complete")
async def api_session_complete(request: Request, session_id: int):
    require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import complete_session
    if not complete_session(session_id):
        raise HTTPException(status_code=400, detail="처리할 수 없는 상태입니다")
    return {"ok": True}


@app.post("/api/lessons/session/{session_id}/no-show")
async def api_session_noshow(request: Request, session_id: int):
    require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import no_show_session
    ok, msg = no_show_session(session_id)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg}


# ── 회원 포털: 내 수업 + 서명 ────────────────────────────────────────────────────
@app.get("/api/my/lessons")
async def api_my_lessons(request: Request):
    user = require_member(request)
    from domains.branch_app.crm_ext import get_enrollments, get_member_sessions
    mid = int(user.get("sub") or 0)
    return {
        "enrollments": get_enrollments(member_id=mid),
        "upcoming":    get_member_sessions(mid, ("reserved",)),
        "pending_sign": get_member_sessions(mid, ("pending_sign",)),
        "completed":   get_member_sessions(mid, ("completed", "no_show")),
    }


class SignBody(BaseModel):
    signature_png: str


@app.post("/api/my/lessons/session/{session_id}/sign")
async def api_my_sign(request: Request, session_id: int, body: SignBody):
    user = require_member(request)
    from domains.branch_app.crm_ext import get_member_sessions, sign_session
    mid = int(user.get("sub") or 0)
    # 본인 세션인지 확인
    owned = {s["id"] for s in get_member_sessions(mid, ("pending_sign",))}
    if session_id not in owned:
        raise HTTPException(status_code=403, detail="본인의 서명 대기 수업이 아닙니다")
    if not body.signature_png:
        raise HTTPException(status_code=400, detail="서명이 비어 있습니다")
    ok, msg = sign_session(session_id, body.signature_png)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg}


# ── Phase 5: GX 출석 / 프로필 / 커리큘럼 / 피드백 ─────────────────────────────────
@app.get("/api/gx/classes")
async def api_gx_classes(request: Request):
    user = require_role(request, "gx", "manager")
    from domains.branch_app.crm_ext import get_gx_classes_for_instructor
    from domains.branch_app.db import get_products
    branch = user.get("branch", "")
    if user.get("admin") or "manager" in user_roles(user):
        return get_products(branch, "gx")
    return get_gx_classes_for_instructor(int(user.get("sub") or 0), branch)


@app.get("/api/gx/members")
async def api_gx_members(request: Request, product_id: int):
    require_role(request, "gx", "manager")
    from domains.branch_app.crm_ext import get_gx_members, get_gx_attendance
    return get_gx_members(product_id)


@app.get("/api/gx/attendance")
async def api_gx_attendance_get(request: Request, product_id: int, date: str):
    require_role(request, "gx", "manager")
    from domains.branch_app.crm_ext import get_gx_attendance
    return get_gx_attendance(product_id, date)


class GxAttBody(BaseModel):
    product_id: int
    date:       str
    member_id:  int
    present:    int = 1


@app.post("/api/gx/attendance")
async def api_gx_attendance_set(request: Request, body: GxAttBody):
    user = require_role(request, "gx", "manager")
    from domains.branch_app.crm_ext import mark_gx_attendance
    mark_gx_attendance(body.product_id, body.date, body.member_id, body.present,
                       int(user.get("sub") or 0), user.get("branch", ""))
    return {"ok": True}


@app.get("/api/profile")
async def api_profile_get(request: Request, employee_id: int = 0):
    user = require_staff(request)
    from domains.branch_app.crm_ext import get_instructor_profile
    eid = employee_id or int(user.get("sub") or 0)
    return get_instructor_profile(eid) or {"employee_id": eid}


class ProfileBody(BaseModel):
    employee_id: int = 0
    photo_png:   str = ""
    intro:       str = ""
    career:      str = ""
    specialty:   str = ""


@app.post("/api/profile")
async def api_profile_set(request: Request, body: ProfileBody):
    user = require_role(request, "trainer", "golf_pro", "gx", "manager")
    target = body.employee_id or int(user.get("sub") or 0)
    # 타인 프로필 수정은 관리자만
    if target != int(user.get("sub") or 0) and not (user.get("admin") or "manager" in user_roles(user)):
        raise HTTPException(status_code=403, detail="타인 프로필은 관리자만 수정할 수 있습니다")
    from domains.branch_app.crm_ext import upsert_instructor_profile
    upsert_instructor_profile(target, body.dict())
    return {"ok": True}


@app.get("/api/curriculums")
async def api_curriculums_get(request: Request, employee_id: int = 0, gx_product_id: int = 0):
    user = require_staff(request)
    from domains.branch_app.crm_ext import get_curriculums
    return get_curriculums(employee_id or int(user.get("sub") or 0) if not gx_product_id else 0,
                           gx_product_id, "")


class CurriculumBody(BaseModel):
    id:            int = 0
    gx_product_id: int = 0
    title:         str = ""
    body:          str = ""


@app.post("/api/curriculums")
async def api_curriculums_set(request: Request, body: CurriculumBody):
    user = require_role(request, "gx", "manager")
    from domains.branch_app.crm_ext import upsert_curriculum
    data = body.dict()
    data["employee_id"] = int(user.get("sub") or 0)
    data["branch"] = user.get("branch", "")
    return {"id": upsert_curriculum(data)}


class FeedbackBody(BaseModel):
    member_id:     int
    enrollment_id: int = 0
    session_id:    int = 0
    content:       str


@app.post("/api/feedback")
async def api_feedback(request: Request, body: FeedbackBody):
    user = require_role(request, "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import add_feedback
    rid = add_feedback(member_id=body.member_id, instructor_employee_id=int(user.get("sub") or 0),
                       content=body.content, session_id=body.session_id, enrollment_id=body.enrollment_id)
    return {"id": rid}


@app.get("/api/my/feedback")
async def api_my_feedback(request: Request):
    user = require_member(request)
    from domains.branch_app.crm_ext import get_member_feedback
    return get_member_feedback(int(user.get("sub") or 0))


# ── Phase 6: 페이롤 (CRM 집계 → 본사 확정 → ERP 읽기) ─────────────────────────────
@app.get("/api/payroll/crm")
async def api_crm_payroll(request: Request, year: int, month: int):
    user = require_role(request, "trainer", "golf_pro", "gx", "manager")
    from domains.branch_app.crm_ext import compute_crm_payroll, get_crm_payroll
    branch = "" if user.get("admin") else user.get("branch", "")
    compute_crm_payroll(year, month, branch)
    rows = get_crm_payroll(year, month, branch)
    # 일반 강사는 본인 것만
    if not (user.get("admin") or "manager" in user_roles(user)):
        eid = int(user.get("sub") or 0)
        rows = [r for r in rows if r["employee_id"] == eid]
    return rows


@app.post("/api/payroll/crm/confirm")
async def api_crm_payroll_confirm(request: Request, year: int, month: int):
    user = require_auth(request)
    if not user.get("admin"):
        raise HTTPException(status_code=403, detail="페이롤 확정은 본사관리자만 가능합니다")
    from domains.branch_app.crm_ext import confirm_crm_payroll
    n = confirm_crm_payroll(year, month, user.get("name", "본사관리자"))
    return {"ok": True, "confirmed": n}


# ── Phase 6: 일일보고 ───────────────────────────────────────────────────────────
@app.get("/api/daily-report")
async def api_daily_report_get(request: Request, date: str = ""):
    user = require_staff(request)
    from domains.branch_app.crm_ext import daily_report_autodata, get_daily_report
    from datetime import datetime
    d = date or datetime.now().strftime("%Y-%m-%d")
    eid = int(user.get("sub") or 0)
    auto = daily_report_autodata(eid, user.get("branch", ""), d)
    saved = get_daily_report(eid, d)
    return {"date": d, "auto": auto, "comment": saved["comment"] if saved else ""}


class DailyReportBody(BaseModel):
    date:    str
    comment: str = ""


@app.post("/api/daily-report")
async def api_daily_report_set(request: Request, body: DailyReportBody):
    user = require_staff(request)
    from domains.branch_app.crm_ext import save_daily_report
    from domains.branch_app.approvals import create_approval
    eid = int(user.get("sub") or 0)
    save_daily_report(eid, user.get("branch", ""), body.date, body.comment)
    create_approval(user.get("branch", ""), "daily_report", 0,
                    f"{user.get('name','')} 일일보고 ({body.date})",
                    created_by=eid, created_by_name=user.get("name", ""))
    return {"ok": True}


# ── Phase 6: 환불 / 민원 / 의견제시 (결재 연동) ──────────────────────────────────
class RefundBody(BaseModel):
    sale_id:       int = 0
    enrollment_id: int = 0
    member_id:     int = 0
    member_name:   str = ""
    reason:        str = ""
    final_amount:  int = 0


@app.post("/api/refunds")
async def api_refund_create(request: Request, body: RefundBody):
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import get_enrollment, refund_suggestion
    from domains.branch_app.approvals import create_approval
    branch = user.get("branch", "")
    paid = used = total = base = 0
    if body.enrollment_id:
        enr = get_enrollment(body.enrollment_id)
        if enr:
            used, total, base = enr["used_sessions"], enr["total_sessions"], enr["base_amount"]
            paid = enr["base_amount"]
    suggested = refund_suggestion(paid, base, total, used) if total else 0
    conn = get_conn()
    cur = conn.execute("""INSERT INTO refund_requests
        (branch, sale_id, enrollment_id, member_id, member_name, reason, paid_amount,
         used_sessions, total_sessions, suggested_amount, final_amount, requested_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (branch, body.sale_id, body.enrollment_id, body.member_id, body.member_name,
         body.reason, paid, used, total, suggested, body.final_amount or suggested,
         int(user.get("sub") or 0)))
    rid = cur.lastrowid
    conn.commit(); conn.close()
    aid = create_approval(branch, "refund", rid,
                          f"환불요청 — {body.member_name} (제안 {suggested:,}원)",
                          created_by=int(user.get("sub") or 0), created_by_name=user.get("name", ""))
    conn = get_conn(); conn.execute("UPDATE refund_requests SET approval_item_id=? WHERE id=?", (aid, rid))
    conn.commit(); conn.close()
    return {"id": rid, "suggested_amount": suggested}


class ComplaintBody(BaseModel):
    member_id:   int = 0
    member_name: str = ""
    content:     str


@app.post("/api/complaints")
async def api_complaint_create(request: Request, body: ComplaintBody):
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.approvals import create_approval
    branch = user.get("branch", "")
    conn = get_conn()
    cur = conn.execute("""INSERT INTO member_complaints
        (branch, member_id, member_name, content, created_by) VALUES (?,?,?,?,?)""",
        (branch, body.member_id, body.member_name, body.content, int(user.get("sub") or 0)))
    rid = cur.lastrowid; conn.commit(); conn.close()
    aid = create_approval(branch, "complaint", rid, f"민원 — {body.member_name}: {body.content[:30]}",
                          created_by=int(user.get("sub") or 0), created_by_name=user.get("name", ""))
    conn = get_conn(); conn.execute("UPDATE member_complaints SET approval_item_id=? WHERE id=?", (aid, rid))
    conn.commit(); conn.close()
    return {"id": rid}


class SuggestionBody(BaseModel):
    content: str


@app.post("/api/suggestions")
async def api_suggestion_create(request: Request, body: SuggestionBody):
    user = require_role(request, "trainer", "golf_pro", "gx", "manager")
    from domains.branch_app.approvals import create_approval
    branch = user.get("branch", "")
    conn = get_conn()
    cur = conn.execute("""INSERT INTO product_suggestions (branch, employee_id, employee_name, content)
        VALUES (?,?,?,?)""", (branch, int(user.get("sub") or 0), user.get("name", ""), body.content))
    rid = cur.lastrowid; conn.commit(); conn.close()
    aid = create_approval(branch, "suggestion", rid, f"상품/수업 의견 — {body.content[:30]}",
                          created_by=int(user.get("sub") or 0), created_by_name=user.get("name", ""))
    conn = get_conn(); conn.execute("UPDATE product_suggestions SET approval_item_id=? WHERE id=?", (aid, rid))
    conn.commit(); conn.close()
    return {"id": rid}


# ── Classes API ────────────────────────────────────────────────────────────────
@app.get("/api/classes")
async def api_classes_get(request: Request, branch: str = ""):
    user = require_auth(request)
    return get_class_schedules(_scope_branch(user, branch))


class ClassBody(BaseModel):
    branch:          str
    class_name:      str
    instructor_name: str = ""
    days:            str = ""
    start_time:      str
    end_time:        str
    capacity:        int = 20
    is_active:       int = 1


@app.post("/api/classes")
async def api_classes_create(request: Request, body: ClassBody):
    require_staff(request)
    rid = upsert_class_schedule(body.dict())
    return {"id": rid}


# ── ERP Bridge ────────────────────────────────────────────────────────────────
@app.get("/api/erp/pending-reports")
async def api_erp_pending(request: Request, branch: str = ""):
    require_auth(request)
    conn  = get_conn()
    today = datetime.now().strftime("%Y-%m-%d")

    as_cur = conn.execute(
        "SELECT * FROM as_requests WHERE branch=? AND status='open' ORDER BY created_at DESC",
        (branch,)
    )
    as_requests = _rows(as_cur)

    sup_cur = conn.execute(
        "SELECT * FROM supply_requests WHERE branch=? AND status='pending' ORDER BY created_at DESC",
        (branch,)
    )
    supply_requests = _rows(sup_cur)

    att_count = conn.execute(
        """SELECT COUNT(*) FROM attendance a
           JOIN employees e ON a.employee_id=e.id
           WHERE e.branch=? AND a.work_date=? AND a.clock_in IS NOT NULL""",
        (branch, today)
    ).fetchone()[0]

    conn.close()
    return {
        "as_requests":      as_requests,
        "supply_requests":  supply_requests,
        "attendance_today": att_count,
    }


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("branch_server:app", host="0.0.0.0", port=8502, reload=True)
