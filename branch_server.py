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


def hash_password(plain: str) -> str:
    """bcrypt 해시 생성."""
    return bcrypt.hashpw(str(plain).encode(), bcrypt.gensalt()).decode()


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
    """직원 로그인"""
    return templates.TemplateResponse(request=request, name="login.html",
        context={"login_role": "staff"})


@app.get("/login/member")
async def login_member_page(request: Request):
    """회원 로그인 (QR 접속 대상)"""
    return templates.TemplateResponse(request=request, name="login.html",
        context={"login_role": "member"})


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
        # 전화번호는 암호화 저장 → blind index(phone_hash)로 조회. 이메일은 평문 fallback.
        from shared.crypto import blind_phone as _bph
        conn = get_conn()
        member = _one(conn.execute(
            "SELECT * FROM members WHERE (phone_hash=? OR email=?) AND status='active' LIMIT 1",
            (_bph(identifier), identifier)
        ))
        conn.close()
        if not member:
            _record_fail(identifier)
            raise HTTPException(status_code=401, detail="회원 정보를 찾을 수 없습니다")
        # PIN 검증: pin_hash(bcrypt) 우선, 없으면 평문 pin(레거시/임시PIN) 비교
        pin_hash = str(member.get("pin_hash", "") or "")
        pin      = str(member.get("pin", "") or "")
        ok = verify_password(body.password, pin_hash) if pin_hash else False
        if not ok and pin:
            ok = (body.password == pin)
        if not ok:
            _record_fail(identifier)
            raise HTTPException(status_code=401, detail="비밀번호(PIN)가 올바르지 않습니다")
        _clear_fails(identifier)
        must_change = bool(member.get("must_change_pw"))
        token = create_token({
            "sub":    str(member["id"]),
            "role":   "member",
            "name":   member["name"],
            "branch": member.get("branch", ""),
            "must_change_pw": must_change,
        })
        return {
            "token":  token,
            "role":   "member",
            "name":   member["name"],
            "branch": member.get("branch", ""),
            "must_change_pw": must_change,
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
async def api_home_data(request: Request, branch: str = ""):
    user = require_auth(request)
    # 관리자는 헤더에서 선택한 지점(branch 파라미터)을 따른다. 일반 직원/회원은 본인 지점.
    branch = _scope_branch(user, branch)
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


class AnnouncementPatchBody(BaseModel):
    title:         Optional[str] = None
    content:       Optional[str] = None
    priority:      Optional[str] = None
    target_branch: Optional[str] = None
    expires_at:    Optional[str] = None


@app.patch("/api/operations/announcements/{ann_id}")
async def api_announcements_patch(request: Request, ann_id: int, body: AnnouncementPatchBody):
    require_staff(request)
    updates = {k: v for k, v in body.dict().items() if v is not None}
    if updates:
        set_clause = ", ".join(f"{k}=?" for k in updates)
        conn = get_conn()
        conn.execute(f"UPDATE announcements SET {set_clause} WHERE id=?",
                     (*updates.values(), ann_id))
        conn.commit(); conn.close()
    return {"ok": True}


@app.delete("/api/operations/announcements/{ann_id}")
async def api_announcements_delete(request: Request, ann_id: int):
    require_staff(request)
    conn = get_conn()
    conn.execute("DELETE FROM announcements WHERE id=?", (ann_id,))
    conn.commit(); conn.close()
    return {"ok": True}


@app.delete("/api/operations/events/{event_id}")
async def api_events_delete(request: Request, event_id: int):
    require_staff(request)
    conn = get_conn()
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.execute("DELETE FROM event_comments WHERE event_id=?", (event_id,))
    conn.commit(); conn.close()
    return {"ok": True}


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
    dong:       str = ""
    ho:         str = ""


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
    dong:       Optional[str] = None
    ho:         Optional[str] = None


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


@app.get("/api/members/{member_id}/sales")
async def api_member_sales(request: Request, member_id: int):
    """회원 결제(구매) 내역"""
    require_staff(request)
    from domains.branch_app.db import get_sales_by_member
    return get_sales_by_member(member_id)


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
    # GX 최소/최대 인원 + 수강권 방식
    min_headcount:   int = 0
    max_headcount:   int = 0
    pass_type:       str = "count"   # 'count'|'period'
    pass_count:      int = 0
    pass_days:       int = 30
    prorate:         int = 0         # GX 가변요금 토글
    unit_price:      int = 0         # GX 1회 단가(횟수권)
    weekday_bits:    str = ""        # GX 운영요일 '0,2,4'(월0..일6)
    pay_methods:     str = ""        # 허용 결제수단(쉼표). 빈값=전체


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
    member_coupon_id: int = 0         # 적용할 회원 쿠폰(쿠폰함 id)


@app.post("/api/sales")
async def api_sales_create(request: Request, body: SaleBody):
    # 상품 판매: 인포·트레이너·프로·관리자 (GX강사 제외)
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.crm_ext import (
        charge_amount, get_product, create_lesson_enrollment, create_gx_enrollment,
        redeem_member_coupon)
    branch  = _scope_branch(user, body.branch) or user.get("branch", "")
    if not branch:
        raise HTTPException(status_code=400, detail="지점 정보가 없습니다")

    product = get_product(body.product_id) if body.product_id else None
    # 정산 기준 상품가액(VAT 제외)
    base = body.base_amount or (product["price"] if product else 0) or body.amount
    amount = body.amount or charge_amount(base, body.pay_method)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="결제 금액을 입력하세요")

    # 쿠폰 할인 (회원 쿠폰함에서 선택분)
    discount = 0
    if body.member_coupon_id and body.member_id:
        discount, _msg = redeem_member_coupon(
            body.member_coupon_id, body.member_id, body.category or (product.get("category") if product else ""),
            body.product_id, amount, sale_id=0)
        if discount <= 0:
            raise HTTPException(status_code=400, detail=_msg)
        amount = max(0, amount - discount)

    data = body.dict()
    data["branch"]  = branch
    data["sold_by"] = user.get("name", "")
    data["amount"]  = amount
    sale_id = create_sale(data)
    # 쿠폰 사용 행에 sale_id 연결
    if discount > 0:
        conn = get_conn()
        conn.execute("UPDATE member_coupons SET sale_id=? WHERE id=?", (sale_id, body.member_coupon_id))
        conn.commit(); conn.close()

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

    return {"id": sale_id, "amount": amount, "discount": discount, "enrollment_id": enrollment_id}


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


# ── 쿠폰: 관리자(정책·발급) ──────────────────────────────────────────────────────
class CouponBody(BaseModel):
    id:              int = 0
    name:            str
    discount_type:   str = "amount"      # 'amount' | 'percent'
    discount_value:  int = 0
    validity_type:   str = "permanent"   # 'permanent' | 'period'
    valid_from:      str = ""
    valid_to:        str = ""
    valid_days:      int = 0
    apply_scope:     str = "all"         # 'all' 또는 'gx,lesson'
    product_ids:     str = ""
    min_amount:      int = 0
    per_member_once: int = 1
    is_active:       int = 1
    scope_all:       bool = False        # True면 전 지점 공통 쿠폰


@app.get("/api/coupons")
async def api_coupons_get(request: Request):
    user = require_role(request, "manager")
    from domains.branch_app.crm_ext import get_coupons
    branch = "" if user.get("admin") else user.get("branch", "")
    return get_coupons(branch)


@app.post("/api/coupons")
async def api_coupons_create(request: Request, body: CouponBody):
    user = require_role(request, "manager")
    from domains.branch_app.crm_ext import create_coupon
    data = body.dict()
    data["branch"] = "all" if body.scope_all else (user.get("branch", "") or "all")
    return {"id": create_coupon(data)}


@app.delete("/api/coupons/{coupon_id}")
async def api_coupons_delete(request: Request, coupon_id: int):
    require_role(request, "manager")
    from domains.branch_app.crm_ext import deactivate_coupon
    deactivate_coupon(coupon_id)
    return {"ok": True}


@app.post("/api/coupons/{coupon_id}/issue-all")
async def api_coupons_issue_all(request: Request, coupon_id: int):
    user = require_role(request, "manager")
    from domains.branch_app.crm_ext import issue_coupon_bulk
    branch = "" if user.get("admin") else user.get("branch", "")
    n = issue_coupon_bulk(coupon_id, branch)
    return {"ok": True, "issued": n}


class IssueMembersBody(BaseModel):
    member_ids: list[int]


@app.post("/api/coupons/{coupon_id}/issue-members")
async def api_coupons_issue_members(request: Request, coupon_id: int, body: IssueMembersBody):
    user = require_role(request, "manager")
    from domains.branch_app.crm_ext import issue_coupon_selected
    n = issue_coupon_selected(coupon_id, body.member_ids, user.get("branch", ""))
    return {"ok": True, "issued": n}


# 이벤트 ↔ 쿠폰 연결
class EventCouponBody(BaseModel):
    coupon_id: int


@app.post("/api/operations/events/{event_id}/coupon")
async def api_event_set_coupon(request: Request, event_id: int, body: EventCouponBody):
    require_role(request, "manager")
    from domains.branch_app.crm_ext import set_event_coupon
    set_event_coupon(event_id, body.coupon_id)
    return {"ok": True}


# ── 쿠폰: 회원(쿠폰함·받기·결제 적용) ────────────────────────────────────────────
@app.get("/api/my/coupons")
async def api_my_coupons(request: Request):
    user = require_member(request)
    from domains.branch_app.crm_ext import get_member_coupons
    return get_member_coupons(int(user.get("sub") or 0))


@app.get("/api/my/coupons/applicable")
async def api_my_coupons_applicable(request: Request, category: str = "",
                                    product_id: int = 0, amount: int = 0):
    user = require_member(request)
    from domains.branch_app.crm_ext import applicable_member_coupons
    return applicable_member_coupons(int(user.get("sub") or 0), category, product_id, amount)


@app.post("/api/operations/events/{event_id}/claim-coupon")
async def api_event_claim_coupon(request: Request, event_id: int):
    """이벤트에 연결된 쿠폰을 회원이 받기."""
    user = require_member(request)
    conn = get_conn()
    ev = _one(conn.execute("SELECT coupon_id, branch FROM events WHERE id=?", (event_id,)))
    conn.close()
    if not ev or not ev.get("coupon_id"):
        raise HTTPException(status_code=400, detail="이 이벤트에는 받을 쿠폰이 없습니다")
    from domains.branch_app.crm_ext import issue_coupon_to_member
    ok, msg = issue_coupon_to_member(ev["coupon_id"], int(user.get("sub") or 0),
                                     user.get("branch", ""))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg}


# ── 지점 토큰 + 회원 가입요청(승인제) ────────────────────────────────────────────
import hashlib as _hl, base64 as _b64

def make_branch_token(branch: str) -> str:
    sig = _hl.sha256((SECRET_KEY + "|" + branch).encode()).hexdigest()[:16]
    b = _b64.urlsafe_b64encode(branch.encode()).decode().rstrip("=")
    return f"{b}.{sig}"

def verify_branch_token(token: str) -> str | None:
    try:
        b, sig = token.split(".")
        branch = _b64.urlsafe_b64decode(b + "=" * (-len(b) % 4)).decode()
        exp = _hl.sha256((SECRET_KEY + "|" + branch).encode()).hexdigest()[:16]
        import hmac as _hm
        return branch if _hm.compare_digest(sig, exp) else None
    except Exception:
        return None


@app.get("/api/branch-token")
async def api_branch_token(request: Request):
    """관리자: 우리 지점 가입 토큰 발급 (QR/링크용)."""
    user = require_staff(request)
    branch = user.get("branch", "")
    if not branch:
        raise HTTPException(status_code=400, detail="지점 정보가 없습니다")
    return {"branch": branch, "token": make_branch_token(branch)}


@app.get("/signup")
async def signup_page(request: Request, b: str = ""):
    branch = verify_branch_token(b) if b else None
    return templates.TemplateResponse(
        request=request, name="signup.html",
        context={"branch": branch or "", "token": b, "valid": bool(branch)})


@app.get("/api/signup/branch")
async def api_signup_branch(token: str = ""):
    branch = verify_branch_token(token) if token else None
    if not branch:
        raise HTTPException(status_code=400, detail="유효하지 않은 가입 링크입니다")
    return {"branch": branch}


class SignupBody(BaseModel):
    token: str
    name:  str
    phone: str
    dong:  str = ""
    ho:    str = ""
    kids:  str = ""


@app.post("/api/signup/request")
async def api_signup_request(body: SignupBody):
    branch = verify_branch_token(body.token)
    if not branch:
        raise HTTPException(status_code=400, detail="유효하지 않은 가입 링크입니다. 지점 QR로 접속하세요.")
    if not body.name.strip() or len(re.sub(r"[^0-9]", "", body.phone)) < 8:
        raise HTTPException(status_code=400, detail="이름과 전화번호를 정확히 입력하세요")
    from domains.branch_app.crm_ext import create_signup_request
    ok, msg, rid = create_signup_request(branch=branch, name=body.name.strip(),
        phone=body.phone.strip(), dong=body.dong.strip(), ho=body.ho.strip(), kids=body.kids.strip())
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg, "id": rid}


@app.get("/api/signup/requests")
async def api_signup_requests(request: Request):
    user = require_staff(request)
    from domains.branch_app.crm_ext import list_signup_requests
    return list_signup_requests(user.get("branch", ""))


@app.post("/api/signup/requests/{req_id}/approve")
async def api_signup_approve(request: Request, req_id: int):
    user = require_staff(request)   # 지점 직원 누구나 승인
    from domains.branch_app.crm_ext import approve_signup_request
    ok, msg, mid = approve_signup_request(req_id, user.get("name", ""))
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"ok": True, "msg": msg, "member_id": mid}


@app.post("/api/signup/requests/{req_id}/reject")
async def api_signup_reject(request: Request, req_id: int):
    user = require_staff(request)
    from domains.branch_app.crm_ext import reject_signup_request
    reject_signup_request(req_id, user.get("name", ""))
    return {"ok": True}


# ── 회원 PIN(비밀번호) 변경 ──────────────────────────────────────────────────────
class ChangePinBody(BaseModel):
    current: str
    new:     str


@app.post("/api/my/change-pin")
async def api_my_change_pin(request: Request, body: ChangePinBody):
    user = require_member(request)
    mid = int(user.get("sub") or 0)
    conn = get_conn()
    row = _one(conn.execute("SELECT pin, pin_hash FROM members WHERE id=?", (mid,)))
    if not row:
        conn.close(); raise HTTPException(status_code=404, detail="회원 정보를 찾을 수 없습니다")
    # 현재 PIN 확인 (pin_hash 우선, 없으면 평문 pin)
    ok = False
    if row.get("pin_hash"):
        ok = verify_password(body.current, row["pin_hash"])
    if not ok and row.get("pin"):
        ok = (body.current == str(row["pin"]))
    if not ok:
        conn.close(); raise HTTPException(status_code=401, detail="현재 비밀번호가 올바르지 않습니다")
    if len(body.new) < 4:
        conn.close(); raise HTTPException(status_code=400, detail="새 비밀번호는 4자 이상이어야 합니다")
    conn.execute("UPDATE members SET pin_hash=?, pin='', must_change_pw=0 WHERE id=?",
                 (hash_password(body.new), mid))
    conn.commit(); conn.close()
    return {"ok": True, "msg": "비밀번호가 변경되었습니다"}


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


# ═══════════════════════════════════════════════════════════════════════════════
#  설정: 토스 / 알리고 / 지점 입금계좌  (admin 전용)
# ═══════════════════════════════════════════════════════════════════════════════
def _require_admin(request: Request) -> dict:
    user = require_staff(request)
    if not user.get("admin"):
        raise HTTPException(status_code=403, detail="관리자 전용 기능입니다")
    return user


def _base_url(request: Request) -> str:
    """문자 링크용 외부 접속 주소. 운영도메인 우선, 없으면 요청 host."""
    import os as _os
    env = _os.getenv("PORTAL_BASE_URL")
    if env:
        return env.rstrip("/")
    return str(request.base_url).rstrip("/")


@app.get("/api/settings/pay")
async def api_settings_pay_get(request: Request):
    _require_admin(request)
    from domains.branch_app.db import get_payment_config, get_aligo_config
    pc = get_payment_config(); ac = get_aligo_config()
    def mask(k): return (k[:8] + "…" + k[-4:]) if k and len(k) > 14 else ("설정됨" if k else "")
    return {
        "toss_client_key": pc.get("toss_client_key", ""),  # client key는 공개키라 그대로
        "toss_secret_set": bool(pc.get("toss_secret_key")),
        "toss_secret_mask": mask(pc.get("toss_secret_key", "")),
        "toss_variant_key": pc.get("toss_variant_key", "") or "widgetA",
        "aligo_user_id": ac.get("user_id", ""),
        "aligo_sender": ac.get("sender", ""),
        "aligo_key_set": bool(ac.get("api_key")),
    }


class TossCfgBody(BaseModel):
    client_key:  str
    secret_key:  str = ""    # 빈값이면 기존 유지
    variant_key: str = "widgetA"


@app.post("/api/settings/toss")
async def api_settings_toss(request: Request, body: TossCfgBody):
    _require_admin(request)
    from domains.branch_app.db import get_payment_config, save_payment_config
    cur = get_payment_config()
    secret = body.secret_key.strip() or cur.get("toss_secret_key", "")
    save_payment_config(body.client_key.strip(), secret, body.variant_key.strip() or "widgetA")
    return {"ok": True}


class AligoCfgBody(BaseModel):
    api_key: str = ""
    user_id: str
    sender:  str


@app.post("/api/settings/aligo")
async def api_settings_aligo(request: Request, body: AligoCfgBody):
    _require_admin(request)
    from domains.branch_app.db import get_aligo_config, save_aligo_config
    cur = get_aligo_config()
    key = body.api_key.strip() or cur.get("api_key", "")
    save_aligo_config(key, body.user_id.strip(), body.sender.strip())
    return {"ok": True}


@app.get("/api/settings/branch-account")
async def api_branch_account_get(request: Request, branch: str = ""):
    user = require_staff(request)
    from domains.branch_app.pay_sms import get_branch_account
    return get_branch_account(_scope_branch(user, branch) or user.get("branch", ""))


class BranchAcctBody(BaseModel):
    branch:         str = ""
    bank:           str = ""
    account_no:     str = ""
    account_holder: str = ""


@app.post("/api/settings/branch-account")
async def api_branch_account_save(request: Request, body: BranchAcctBody):
    user = require_role(request, "manager")
    br = _scope_branch(user, body.branch) or user.get("branch", "")
    conn = get_conn()
    conn.execute("UPDATE branches SET bank=?, account_no=?, account_holder=? WHERE name=?",
                 (body.bank.strip(), body.account_no.strip(), body.account_holder.strip(), br))
    conn.commit(); conn.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
#  결제: 계좌이체 안내 / 토스 결제링크 / 결제페이지 / 승인콜백 / 현황판
# ═══════════════════════════════════════════════════════════════════════════════
class TransferBody(BaseModel):
    branch:       str = ""
    member_name:  str
    member_phone: str
    product_name: str
    amount:       int


@app.post("/api/pay/transfer-guide")
async def api_transfer_guide(request: Request, body: TransferBody):
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.pay_sms import send_transfer_guide
    br = _scope_branch(user, body.branch) or user.get("branch", "")
    res = send_transfer_guide(branch=br, member_name=body.member_name,
                              member_phone=body.member_phone,
                              product_name=body.product_name, amount=body.amount)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "문자 발송 실패"))
    return {"ok": True}


class OrderBody(BaseModel):
    branch:       str = ""
    member_id:    int = 0
    member_name:  str
    member_phone: str = ""
    product_id:   int = 0
    product_name: str
    category:     str = ""
    base_amount:  int = 0
    amount:       int
    instructor_employee_id: int = 0
    send_link:    int = 1    # 1=문자 발송, 0=링크만 생성(QR 등)


@app.post("/api/pay/toss-link")
async def api_toss_link(request: Request, body: OrderBody):
    """직원이 토스 결제링크를 만들어 회원에게 문자 발송."""
    user = require_role(request, "info", "trainer", "golf_pro", "manager")
    from domains.branch_app.pay_sms import create_order, send_payment_link
    br = _scope_branch(user, body.branch) or user.get("branch", "")
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="결제 금액을 입력하세요")
    order = create_order(
        branch=br, member_id=body.member_id, member_name=body.member_name,
        member_phone=body.member_phone, product_id=body.product_id,
        product_name=body.product_name, category=body.category,
        base_amount=body.base_amount, amount=body.amount, pay_method="토스",
        instructor_employee_id=body.instructor_employee_id, channel="link",
        created_by=user.get("name", ""))
    link = f"{_base_url(request)}/p/{order['token']}"
    if body.send_link and body.member_phone:
        send_payment_link(base_url=_base_url(request), order=order,
                          member_name=body.member_name, member_phone=body.member_phone,
                          product_name=body.product_name, amount=body.amount)
    return {"ok": True, "token": order["token"], "link": link}


@app.get("/p/{token}")
async def pay_page(request: Request, token: str):
    """단축URL 결제 페이지 (회원이 문자 링크로 접속)."""
    from domains.branch_app.pay_sms import get_order_by_token
    from domains.branch_app.db import get_payment_config
    order = get_order_by_token(token)
    if not order:
        return templates.TemplateResponse(request=request, name="pay.html",
            context={"error": "유효하지 않은 결제 링크입니다.", "order": None,
                     "client_key": "", "variant_key": "widgetA"})
    cfg = get_payment_config()
    return templates.TemplateResponse(request=request, name="pay.html",
        context={"order": order, "client_key": cfg.get("toss_client_key", ""),
                 "variant_key": cfg.get("toss_variant_key", "") or "widgetA",
                 "error": None, "already": order["status"] == "paid"})


class ConfirmBody(BaseModel):
    order_id:     str
    payment_key:  str
    amount:       int


@app.post("/api/pay/confirm")
async def api_pay_confirm(request: Request, body: ConfirmBody):
    """토스 결제창 성공 후 승인 확정 (인증 불필요 — orderId/amount 서버검증)."""
    from domains.branch_app.pay_sms import confirm_order
    res = confirm_order(body.order_id, body.payment_key, body.amount)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "결제 승인 실패"))
    return {"ok": True}


@app.get("/api/pay/orders")
async def api_pay_orders(request: Request, branch: str = "", status: str = ""):
    """결제 현황판."""
    user = require_staff(request)
    br = _scope_branch(user, branch) or user.get("branch", "")
    conn = get_conn()
    q = "SELECT * FROM payment_orders WHERE branch=?"
    args = [br]
    if status:
        q += " AND status=?"; args.append(status)
    q += " ORDER BY created_at DESC LIMIT 100"
    rows = _rows(conn.execute(q, args))
    conn.close()
    return rows


# ═══════════════════════════════════════════════════════════════════════════════
#  회원 셀프구매 + GX 신청/개강
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/my/products")
async def api_my_products(request: Request, category: str = ""):
    """회원이 구매 가능한 상품 (자기 지점). GX 가변요금이면 현재 청구가 동봉."""
    user = require_member(request)
    br = user.get("branch", "")
    conn = get_conn()
    q = "SELECT * FROM products WHERE branch=? AND is_active=1"
    args = [br]
    if category:
        q += " AND category=?"; args.append(category)
    q += " ORDER BY category, name"
    rows = _rows(conn.execute(q, args))
    conn.close()
    from domains.branch_app.pay_sms import gx_price, gx_headcounts, gx_visible_yms
    vis = gx_visible_yms()
    YM_LABEL = {vis["current_ym"]: "이번 달", vis["next_ym"]: "다음 달"}
    for p in rows:
        if p.get("category") == "gx":
            offers = []
            for ym in vis["shop_yms"]:            # 1~23일=당월만, 24~말일=당월+다음달
                info = gx_price(p, ym)
                hc = gx_headcounts(p["id"], ym)
                offers.append({
                    "target_ym": ym,
                    "label": YM_LABEL.get(ym, ym),
                    "charge": info["charge"],
                    "remaining": info["remaining"],
                    "total": info["total"],
                    "is_current": info["is_current"],
                    "dates": info["dates"],
                    "enrolled": hc["enrolled"], "waiting": hc["waiting"],
                    "min": hc["min"], "max": hc["max"],
                    "status": hc["status"], "full": hc["full"],
                })
            p["offers"] = offers
            # 하위호환 필드(첫 오퍼=당월)
            if offers:
                p["current_charge"] = offers[0]["charge"]
                p["remaining_sessions"] = offers[0]["remaining"]
                p["total_sessions"] = offers[0]["total"]
    return rows


class SelfBuyBody(BaseModel):
    product_id: int
    target_ym:  str = ""    # 비면 당월 (gx_visible_yms 검증)


@app.post("/api/my/buy")
async def api_my_buy(request: Request, body: SelfBuyBody):
    """회원 셀프구매 — 주문 생성 후 결제 토큰 반환. GX 최소인원 미달이면 신청만."""
    user = require_member(request)
    from domains.branch_app.crm_ext import get_product, charge_amount
    from domains.branch_app.pay_sms import (create_order, gx_apply, gx_headcounts,
                                            gx_price, gx_visible_yms)
    product = get_product(body.product_id)
    if not product or not product.get("is_active"):
        raise HTTPException(status_code=404, detail="상품을 찾을 수 없습니다")
    br = user.get("branch", "")
    mid = int(user.get("sub") or 0)
    mname = user.get("name", "")
    # 회원 전화
    conn = get_conn()
    mrow = conn.execute("SELECT phone FROM members WHERE id=?", (mid,)).fetchone()
    conn.close()
    mphone = mrow[0] if mrow else ""

    vis = gx_visible_yms()
    tym = body.target_ym or vis["current_ym"]
    # shop 노출 규칙 검증: 일반 회원은 shop_yms 내 월만 구매 가능 (다음달은 24일~)
    if product.get("category") == "gx" and tym not in vis["shop_yms"]:
        raise HTTPException(status_code=400, detail="현재 구매할 수 없는 월입니다")

    # GX 최소개강 인원 체크 (월별 독립)
    if product.get("category") == "gx":
        hc = gx_headcounts(product["id"], tym)
        # 이미 정원 마감
        if hc["max"] and hc["enrolled"] >= hc["max"]:
            raise HTTPException(status_code=400, detail="정원이 마감되었습니다")
        # 최소인원 미달 + 아직 '진행' 확정 전이면 대기신청만
        if hc["min"] > 0 and hc["status"] != "running" \
           and (hc["enrolled"] + hc["waiting"] + 1) < hc["min"]:
            gx_apply(branch=br, gx_product_id=product["id"], member_id=mid,
                     member_name=mname, member_phone=mphone, target_ym=tym)
            need = hc["min"] - (hc["enrolled"] + hc["waiting"] + 1)
            return {"applied": True,
                    "msg": f"개강 대기 신청 완료! 최소 개강 인원까지 {need}명 남았습니다. "
                           f"인원이 충족되면 결제 안내 문자를 보내드립니다."}

    # GX 월별 요금 계산
    base = product.get("price", 0)
    pname = product["name"]
    if product.get("category") == "gx":
        info = gx_price(product, tym)
        if info["remaining"] <= 0:
            raise HTTPException(status_code=400, detail="해당 월 남은 수업이 없습니다")
        base = info["charge"]
        lbl = "다음 달" if not info["is_current"] else "이번 달"
        pname = f"{product['name']} ({lbl} {info['remaining']}회분)"
    amount = charge_amount(base, "토스")   # 셀프구매는 토스(카드) → VAT 가산
    order = create_order(
        branch=br, member_id=mid, member_name=mname, member_phone=mphone,
        product_id=product["id"], product_name=pname,
        category=product.get("category", ""), base_amount=base, amount=amount,
        pay_method="토스", channel="self", created_by="", target_ym=tym)
    return {"applied": False, "token": order["token"],
            "link": f"{_base_url(request)}/p/{order['token']}"}


@app.post("/api/gx/check-open")
async def api_gx_check_open(request: Request, gx_product_id: int):
    """관리자/매니저가 GX 개강 충족 여부 확인 → 충족 시 대기자 일괄 안내."""
    user = require_role(request, "manager")
    from domains.branch_app.pay_sms import gx_check_and_open
    return gx_check_and_open(_base_url(request), gx_product_id)


@app.get("/api/gx/class-board")
async def api_gx_class_board(request: Request, ym: str = ""):
    """지점 GX 반별 상태판(월별 정원/대기/진행/미달) — 인포·GX·매니저."""
    user = require_role(request, "info", "gx", "manager")
    from domains.branch_app.pay_sms import gx_class_board
    return gx_class_board(user.get("branch", ""), ym)


class ClassStatusBody(BaseModel):
    gx_product_id: int
    ym:            str = ""
    notify:        bool = True


@app.post("/api/gx/class-run")
async def api_gx_class_run(request: Request, body: ClassStatusBody):
    """반을 '진행'으로 확정(미달이어도 강행) + 신청자에게 결제안내 — 매니저·관리자."""
    user = require_role(request, "manager")
    from domains.branch_app.pay_sms import gx_set_class_running
    return gx_set_class_running(_base_url(request), body.gx_product_id, body.ym,
                                decided_by=user.get("name", ""), notify=body.notify)


@app.post("/api/gx/class-wait")
async def api_gx_class_wait(request: Request, body: ClassStatusBody):
    """반을 '대기'로 되돌림 — 매니저·관리자."""
    user = require_role(request, "manager")
    from domains.branch_app.pay_sms import gx_set_class_waiting
    return gx_set_class_waiting(body.gx_product_id, body.ym, decided_by=user.get("name", ""))


@app.get("/api/gx/calendar")
async def api_gx_calendar(request: Request, ym: str, branch: str = ""):
    """회원 홈 달력 — 지점 진행중 GX수업 + 날짜별 수업. (회원·직원 공통)"""
    user = require_auth(request)
    br = _scope_branch(user, branch) or user.get("branch", "")
    from domains.branch_app.pay_sms import branch_gx_calendar
    return branch_gx_calendar(br, ym)


@app.get("/api/gx/sessions")
async def api_gx_sessions(request: Request, gx_product_id: int, ym: str):
    """강사 수업일 편집 캘린더 — GX강사(본인)·매니저·관리자."""
    user = require_role(request, "gx", "manager")
    _assert_gx_owner_or_mgr(user, gx_product_id)
    from domains.branch_app.pay_sms import gx_session_calendar
    return gx_session_calendar(gx_product_id, ym)


class SessionsBody(BaseModel):
    gx_product_id: int
    ym:            str
    dates:         list[str] = []


@app.post("/api/gx/sessions")
async def api_gx_sessions_save(request: Request, body: SessionsBody):
    """강사가 수업일 확정 저장 — GX강사(본인)·매니저·관리자."""
    user = require_role(request, "gx", "manager")
    _assert_gx_owner_or_mgr(user, body.gx_product_id)
    from domains.branch_app.pay_sms import gx_confirm_sessions
    return gx_confirm_sessions(body.gx_product_id, body.ym, body.dates,
                               confirmed_by=user.get("name", ""))


def _assert_gx_owner_or_mgr(user: dict, gx_product_id: int):
    """GX강사는 본인 담당 수업만. 매니저/관리자/인포는 통과."""
    roles = set(user_roles(user))
    if user.get("admin") or roles.intersection({"manager", "info"}):
        return
    if "gx" in roles:
        conn = get_conn()
        owner = conn.execute("SELECT instructor_employee_id FROM products WHERE id=?",
                             (gx_product_id,)).fetchone()
        conn.close()
        if owner and owner[0] == int(user.get("sub") or 0):
            return
    raise HTTPException(status_code=403, detail="본인 담당 수업만 편집할 수 있습니다")


# ═══════════════════════════════════════════════════════════════════════════════
#  환불 처리 (토스 취소 연동 / 수기) — 매니저·관리자
# ═══════════════════════════════════════════════════════════════════════════════
class RefundBody(BaseModel):
    sale_id:       int
    refund_amount: int = 0
    reason:        str = ""


@app.post("/api/refund")
async def api_refund(request: Request, body: RefundBody):
    user = require_role(request, "manager")
    from domains.branch_app.ops import process_refund, get_sale, log_action, is_locked
    sale = get_sale(body.sale_id)
    if not sale:
        raise HTTPException(404, "결제 내역을 찾을 수 없습니다")
    # 마감된 월이면 환불 차단
    sd = (sale.get("sale_date") or "")[:7]
    if sd:
        y, m = int(sd[:4]), int(sd[5:7])
        if is_locked(y, m, sale.get("branch", "")):
            raise HTTPException(400, f"{y}년 {m}월은 마감되어 환불할 수 없습니다 (먼저 마감 해제)")
    amt = body.refund_amount or int(sale.get("amount", 0))
    res = process_refund(body.sale_id, amt, body.reason, user.get("name", ""))
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "환불 실패"))
    log_action(user.get("name", ""), "sale.refund",
               target=f"{sale.get('member_name','')} / {sale.get('product_name','')}",
               detail=f"{amt:,}원 ({res.get('method')})", branch=sale.get("branch", ""),
               actor_role="manager")
    return {"ok": True, "method": res.get("method")}


@app.get("/api/refunds")
async def api_refunds(request: Request, branch: str = "", year: int = None, month: int = None):
    user = require_staff(request)
    from domains.branch_app.ops import get_refunds
    return get_refunds(_scope_branch(user, branch), year, month)


# ═══════════════════════════════════════════════════════════════════════════════
#  문자(SMS) 시스템: 템플릿 + 일괄발송 + 재등록 안내
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/sms/templates")
async def api_sms_templates(request: Request):
    require_staff(request)
    from domains.branch_app.pay_sms import list_templates
    return list_templates()


class TemplateBody(BaseModel):
    name:    str
    content: str


@app.post("/api/sms/templates")
async def api_sms_template_add(request: Request, body: TemplateBody):
    require_role(request, "manager")
    from domains.branch_app.pay_sms import add_template
    if not body.name.strip() or not body.content.strip():
        raise HTTPException(status_code=400, detail="이름과 내용을 입력하세요")
    return {"id": add_template(body.name.strip(), body.content.strip())}


@app.delete("/api/sms/templates/{tid}")
async def api_sms_template_del(request: Request, tid: int):
    require_role(request, "manager")
    from domains.branch_app.pay_sms import delete_template
    delete_template(tid)
    return {"ok": True}


class SmsSendBody(BaseModel):
    member_ids: list[int] = []
    message:    str


@app.post("/api/sms/send")
async def api_sms_send(request: Request, body: SmsSendBody):
    """일괄 문자 발송 — 관리자·지점매니저만 (비용 남용 방지)."""
    user = require_role(request, "manager")
    from domains.branch_app.pay_sms import get_members_by_ids, broadcast
    targets = get_members_by_ids(body.member_ids)
    if not targets:
        raise HTTPException(status_code=400, detail="발송 대상(전화번호 보유 회원)이 없습니다")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="메시지를 입력하세요")
    res = broadcast(targets, body.message, sent_by=user.get("name", ""))
    return res


@app.get("/api/sms/class-members")
async def api_sms_class_members(request: Request, gx_product_id: int):
    """GX 수업 수강 회원 — 재등록 안내 대상 미리보기."""
    require_role(request, "info", "gx", "manager")
    from domains.branch_app.pay_sms import get_class_members
    return get_class_members(gx_product_id)


class ReRegBody(BaseModel):
    gx_product_id: int
    message:       str


@app.post("/api/sms/reregister")
async def api_sms_reregister(request: Request, body: ReRegBody):
    """재등록 안내 — 인포·GX강사·지점매니저·관리자."""
    user = require_role(request, "info", "gx", "manager")
    from domains.branch_app.pay_sms import get_class_members, broadcast
    # GX강사는 자기 수업만
    if "gx" in user_roles(user) and not user.get("admin") and \
       not set(user_roles(user)).intersection({"info", "manager"}):
        conn = get_conn()
        owner = conn.execute("SELECT instructor_employee_id FROM products WHERE id=?",
                             (body.gx_product_id,)).fetchone()
        conn.close()
        if not owner or owner[0] != int(user.get("sub") or 0):
            raise HTTPException(status_code=403, detail="본인 담당 수업만 발송할 수 있습니다")
    targets = get_class_members(body.gx_product_id)
    if not targets:
        raise HTTPException(status_code=400, detail="수강 회원(전화번호 보유)이 없습니다")
    res = broadcast(targets, body.message, sent_by=user.get("name", ""))
    return res


class ReRegLinkBody(BaseModel):
    gx_product_id: int
    force:         bool = False   # 재등록 기간(20~23일) 밖에서도 강행(관리자)


@app.post("/api/sms/reregister-links")
async def api_sms_reregister_links(request: Request, body: ReRegLinkBody):
    """기존 수강 회원에게 '다음 달분' 결제 링크 개별 발송 — 인포·GX강사·매니저·관리자.
    재등록 기간(하드코딩 20~23일)에만 발송. 관리자는 force로 예외."""
    user = require_role(request, "info", "gx", "manager")
    from domains.branch_app.pay_sms import send_reregister_links, gx_visible_yms
    # GX강사는 자기 수업만
    if "gx" in user_roles(user) and not user.get("admin") and \
       not set(user_roles(user)).intersection({"info", "manager"}):
        conn = get_conn()
        owner = conn.execute("SELECT instructor_employee_id FROM products WHERE id=?",
                             (body.gx_product_id,)).fetchone()
        conn.close()
        if not owner or owner[0] != int(user.get("sub") or 0):
            raise HTTPException(status_code=403, detail="본인 담당 수업만 발송할 수 있습니다")
    vis = gx_visible_yms()
    if not vis["rereg_period"] and not (body.force and user.get("admin")):
        raise HTTPException(status_code=400,
            detail=f"재등록 안내 기간(매월 20~23일)에만 발송할 수 있습니다 (오늘 {vis['day']}일)")
    res = send_reregister_links(base_url=_base_url(request),
                                gx_product_id=body.gx_product_id,
                                sent_by=user.get("name", ""))
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "발송 실패"))
    return res


# ═══════════════════════════════════════════════════════════════════════════════
#  공휴일 관리 (GX 가변요금 계산용) — 매니저/관리자
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/holidays")
async def api_holidays(request: Request, year: int = 0):
    require_staff(request)
    conn = get_conn()
    if year:
        cur = conn.execute("SELECT id, holiday_date, name, year FROM public_holidays WHERE year=? ORDER BY holiday_date", (year,))
    else:
        cur = conn.execute("SELECT id, holiday_date, name, year FROM public_holidays ORDER BY holiday_date DESC")
    rows = _rows(cur)
    conn.close()
    return rows


class HolidayBody(BaseModel):
    holiday_date: str   # YYYY-MM-DD
    name:         str


@app.post("/api/holidays")
async def api_holiday_add(request: Request, body: HolidayBody):
    require_role(request, "manager")
    import re as _re
    if not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.holiday_date.strip()):
        raise HTTPException(status_code=400, detail="날짜는 YYYY-MM-DD 형식이어야 합니다")
    if not body.name.strip():
        raise HTTPException(status_code=400, detail="공휴일 이름을 입력하세요")
    yr = int(body.holiday_date[:4])
    conn = get_conn()
    conn.execute("INSERT OR REPLACE INTO public_holidays (holiday_date, name, year) VALUES (?,?,?)",
                 (body.holiday_date.strip(), body.name.strip(), yr))
    conn.commit(); conn.close()
    return {"ok": True}


@app.delete("/api/holidays/{hid}")
async def api_holiday_del(request: Request, hid: int):
    require_role(request, "manager")
    conn = get_conn()
    conn.execute("DELETE FROM public_holidays WHERE id=?", (hid,))
    conn.commit(); conn.close()
    return {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
#  테스트 모드 (가상 날짜 + 데이터 격리) — admin
# ═══════════════════════════════════════════════════════════════════════════════
@app.get("/api/testmode")
async def api_testmode_get(request: Request):
    require_staff(request)
    from domains.branch_app.testmode import get_test_state
    return get_test_state()


class TestModeBody(BaseModel):
    on:    bool
    vdate: str = ""   # YYYY-MM-DD


@app.post("/api/testmode")
async def api_testmode_set(request: Request, body: TestModeBody):
    user = require_staff(request)
    if not user.get("admin"):
        raise HTTPException(403, "관리자 전용")
    import re as _re
    if body.on and body.vdate and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", body.vdate):
        raise HTTPException(400, "날짜는 YYYY-MM-DD 형식이어야 합니다")
    from domains.branch_app.testmode import set_test_mode
    set_test_mode(body.on, body.vdate)
    return {"ok": True}


@app.post("/api/testmode/purge")
async def api_testmode_purge(request: Request):
    user = require_staff(request)
    if not user.get("admin"):
        raise HTTPException(403, "관리자 전용")
    from domains.branch_app.testmode import purge_test_data
    counts = purge_test_data()
    return {"ok": True, "deleted": counts}


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("branch_server:app", host="0.0.0.0", port=8502, reload=True)
