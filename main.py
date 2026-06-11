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
@app.get("/api/summary")
async def api_summary(request: Request, year: int, month: int):
    require_auth(request)
    from domains.dashboard.service import build_summary
    df = build_summary(year, month)
    if df is None or df.empty:
        return {"rows": [], "totals": {}}
    rows = df.fillna(0).to_dict("records")
    totals = {
        "총매출": int(df["총매출"].sum()),
        "총지출": int(df["총지출"].sum()),
        "손익":   int(df["손익"].sum()),
        "이익률": round(float(df["손익"].sum()) / float(df["총매출"].sum()) * 100, 1)
                  if df["총매출"].sum() else 0,
    }
    return {"rows": rows, "totals": totals}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8503)
