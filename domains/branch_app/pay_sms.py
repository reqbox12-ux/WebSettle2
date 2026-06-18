"""
domains/branch_app/pay_sms.py
결제(토스 주문/링크) + 문자(알리고) 연결 로직.
- 단축 URL 토큰 기반 결제 페이지
- 계좌이체 안내문자 / 토스 결제링크 문자 / 결제완료 영수증
- GX 최소/최대 인원 (개강대기 → 충족 시 자동 안내)
기존 함수 재사용: get_payment_config, toss_confirm_payment, aligo_send (db.py)
                  get_product, create_lesson_enrollment, create_gx_enrollment (crm_ext.py)
"""
import secrets
import time

from shared.db import get_conn
from domains.branch_app.db import (
    get_payment_config, get_aligo_config, aligo_send, toss_confirm_payment,
    create_sale,
)
from domains.branch_app.crm_ext import (
    charge_amount, get_product, create_lesson_enrollment, create_gx_enrollment,
)


from shared.crypto import dec_row as _dec_row


def _one(cur):
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return _dec_row(dict(zip(cols, row))) if row else None


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


# ── GX 가변 요금 (일할 계산) ──────────────────────────────────
_WEEKDAY_MAP = {"월": 0, "화": 1, "수": 2, "목": 3, "금": 4, "토": 5, "일": 6}


def _parse_weekdays(product: dict) -> set:
    """상품의 운영요일 → weekday 집합(월0..일6). weekday_bits 우선, 없으면 days 자연어."""
    bits = (product.get("weekday_bits") or "").strip()
    if bits:
        out = set()
        for x in bits.split(","):
            x = x.strip()
            if x.isdigit():
                out.add(int(x))
        return out
    s = product.get("days", "") or ""
    if "매일" in s:
        return set(range(7))
    return {_WEEKDAY_MAP[ch] for ch in s if ch in _WEEKDAY_MAP}


def _gx_session_dates(year: int, month: int, weekdays: set) -> list:
    """해당 월의 수업 후보 날짜 (요일 매칭, 공휴일 제외)."""
    import calendar
    from datetime import date
    conn = get_conn()
    hol = {r[0] for r in conn.execute("SELECT holiday_date FROM public_holidays WHERE year=?", (year,))}
    conn.close()
    out = []
    for d in range(1, calendar.monthrange(year, month)[1] + 1):
        dt = date(year, month, d)
        ds = dt.isoformat()
        if dt.weekday() in weekdays and ds not in hol:
            out.append(ds)
    return out


def _confirmed_session_dates(gx_product_id: int, ym: str) -> list:
    """강사가 확정한 수업일(있으면 우선). 없으면 빈 리스트."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT session_date FROM gx_sessions WHERE gx_product_id=? AND ym=? AND confirmed=1 ORDER BY session_date",
        (gx_product_id, ym)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def gx_price(product: dict, target_ym: str, ref_dt=None) -> dict:
    """GX 청구가 계산.
    - target_ym = 'YYYY-MM'. 현재(오버라이드) 날짜의 월이면 '당월'(일할), 미래월이면 '풀'.
    - 1회단가(unit_price) 있으면 그것을, 없으면 정가÷총회차.
    - 강사 확정 수업일이 있으면 그 날짜 사용, 없으면 요일 자동 계산.
    - 횟수상한(pass_count, 횟수권만) 캡 적용.
    반환: charge / unit / total / remaining / dates
    """
    from datetime import datetime
    from domains.branch_app.testmode import today_dt
    now = ref_dt or today_dt()
    today = now.date().isoformat()
    y, m = int(target_ym[:4]), int(target_ym[5:7])

    weekdays = _parse_weekdays(product)
    conf = _confirmed_session_dates(product["id"], target_ym)
    dates = conf if conf else _gx_session_dates(y, m, weekdays)

    # 횟수권 상한 캡
    cap = int(product.get("pass_count") or 0)
    pass_type = product.get("pass_type", "count")
    full_price = int(product.get("price", 0) or 0)
    unit = int(product.get("unit_price") or 0)
    if not unit:
        # 단가 미설정: 정가 ÷ (상한 또는 총회차)
        denom = cap or len(dates) or 1
        unit = round(full_price / denom) if denom else full_price

    # 이번 달(오버라이드 기준)이면 중도일할, 미래월이면 풀
    is_current = (target_ym == today[:7])
    start_t = (product.get("start_time") or "00:00")[:5]
    cur_hm = now.strftime("%H:%M")

    if is_current:
        remaining = 0
        for ds in dates:
            if ds > today:
                remaining += 1
            elif ds == today and cur_hm < start_t:
                remaining += 1
    else:
        remaining = len(dates)   # 미래월 = 풀

    total = len(dates)
    # 상한 캡: 청구 회차는 cap 초과 못함 (횟수권만; 기간권은 정액)
    if pass_type == "count" and cap:
        remaining = min(remaining, cap)
        total = min(total, cap)

    if pass_type == "period":
        # 기간권: 미래월·1일등록=정가, 당월 중도=일할(정가÷총회차×남은회차)
        denom = total or 1
        charge = full_price if (not is_current or remaining >= total) else (full_price / denom * remaining)
    else:
        # 횟수권: 진행/남은 회차 × 단가
        charge = remaining * unit

    # 입력 금액은 VAT 포함가. 10원 반올림 후 100원 절사로 표기.
    from domains.branch_app.crm_ext import round_price
    charge = round_price(charge)

    return {"charge": charge, "unit": unit, "total": total, "remaining": remaining,
            "dates": dates, "pass_type": pass_type, "is_current": is_current,
            "confirmed": bool(conf)}


# ── 강사 수업일 확정 캘린더 ───────────────────────────────────
def gx_session_calendar(gx_product_id: int, ym: str) -> dict:
    """해당 월 수업일 편집용 캘린더.
    - 자동: 운영요일 매칭 - 공휴일 (기본 체크)
    - 강사가 확정했으면 그 선택을 우선 표시
    - 운영요일 외 날짜도 후보로 노출(강사가 보강 추가 가능)
    """
    import calendar
    from datetime import date
    product = get_product(gx_product_id)
    if not product:
        return {"error": "상품 없음"}
    y, m = int(ym[:4]), int(ym[5:7])
    weekdays = _parse_weekdays(product)
    auto = set(_gx_session_dates(y, m, weekdays))
    conf = _confirmed_session_dates(gx_product_id, ym)
    confirmed = bool(conf)
    selected = set(conf) if confirmed else set(auto)
    conn = get_conn()
    hol = {r[0]: r[1] for r in conn.execute(
        "SELECT holiday_date, name FROM public_holidays WHERE year=?", (y,))}
    conn.close()
    WK = ["월", "화", "수", "목", "금", "토", "일"]
    days = []
    for d in range(1, calendar.monthrange(y, m)[1] + 1):
        dt = date(y, m, d)
        ds = dt.isoformat()
        days.append({
            "date": ds, "day": d, "weekday": WK[dt.weekday()],
            "is_holiday": ds in hol, "holiday_name": hol.get(ds, ""),
            "candidate": dt.weekday() in weekdays,
            "on": ds in selected,
        })
    return {"confirmed": confirmed, "ym": ym, "weekdays": sorted(weekdays),
            "selected": sorted(selected), "count": len(selected),
            "cap": int(product.get("pass_count") or 0),
            "pass_type": product.get("pass_type", "count"), "days": days}


def gx_confirm_sessions(gx_product_id: int, ym: str, dates: list,
                        confirmed_by: str = "") -> dict:
    """강사가 선택한 수업일을 확정 저장(해당 월 덮어쓰기). 미래월도 가능."""
    from domains.branch_app.testmode import is_test_flag
    product = get_product(gx_product_id)
    if not product:
        return {"ok": False, "error": "상품 없음"}
    branch = product.get("branch", "")
    itest = is_test_flag()
    clean = sorted({d.strip() for d in dates if d and d.strip().startswith(ym)})
    conn = get_conn()
    conn.execute("DELETE FROM gx_sessions WHERE gx_product_id=? AND ym=?", (gx_product_id, ym))
    for ds in clean:
        conn.execute("""INSERT OR REPLACE INTO gx_sessions
            (gx_product_id, branch, ym, session_date, confirmed, confirmed_by, is_test)
            VALUES (?,?,?,?,1,?,?)""",
            (gx_product_id, branch, ym, ds, confirmed_by, itest))
    conn.commit()
    conn.close()
    return {"ok": True, "ym": ym, "count": len(clean), "dates": clean}


# 하위호환: 기존 호출부(gx_current_price)가 남아있을 수 있어 래핑
def gx_current_price(product: dict, ref_dt=None) -> dict:
    from domains.branch_app.testmode import today_str
    ym = today_str()[:7]
    r = gx_price(product, ym, ref_dt)
    return {"prorate": bool(product.get("prorate")), "full": int(product.get("price", 0) or 0),
            "charge": r["charge"], "total": r["total"], "remaining": r["remaining"],
            "per_session": r["unit"], "session_dates": r["dates"]}


# ── 문자 템플릿 ───────────────────────────────────────────────
def list_templates() -> list[dict]:
    conn = get_conn()
    cur = conn.execute("SELECT id, name, content, sms_type FROM sms_templates WHERE is_active=1 ORDER BY id DESC")
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    conn.close()
    return rows


def add_template(name: str, content: str) -> int:
    conn = get_conn()
    cur = conn.execute("INSERT INTO sms_templates (name, content, sms_type) VALUES (?,?,?)",
                       (name, content, "SMS" if len(content) <= 90 else "LMS"))
    conn.commit(); rid = cur.lastrowid; conn.close()
    return rid


def delete_template(tid: int):
    conn = get_conn()
    conn.execute("UPDATE sms_templates SET is_active=0 WHERE id=?", (tid,))
    conn.commit(); conn.close()


# ── 대상 회원 조회 ────────────────────────────────────────────
def get_class_members(gx_product_id: int) -> list[dict]:
    """GX 수업 수강 회원 (결제완료 active) — 재등록 안내 대상"""
    conn = get_conn()
    cur = conn.execute("""
        SELECT DISTINCT m.id, m.name, m.phone
        FROM gx_enrollments e JOIN members m ON e.member_id = m.id
        WHERE e.gx_product_id=? AND e.status='active' AND m.phone != ''
    """, (gx_product_id,))
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    conn.close()
    return rows


def get_members_by_ids(member_ids: list[int]) -> list[dict]:
    if not member_ids:
        return []
    conn = get_conn()
    qs = ",".join("?" * len(member_ids))
    cur = conn.execute(f"SELECT id, name, phone FROM members WHERE id IN ({qs}) AND phone != ''", member_ids)
    rows = [dict(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()]
    conn.close()
    return rows


# ── 일괄 발송 (치환: #{이름}) ─────────────────────────────────
def broadcast(targets: list[dict], message: str, sent_by: str = "") -> dict:
    sent = failed = 0
    for t in targets:
        msg = message.replace("#{이름}", t.get("name", "")).replace("{이름}", t.get("name", ""))
        res = send_sms(t.get("phone", ""), msg, title="안내", name=t.get("name", ""), sent_by=sent_by)
        if res.get("ok"):
            sent += 1
        else:
            failed += 1
    return {"sent": sent, "failed": failed, "total": len(targets)}


# ── 지점 입금계좌 ─────────────────────────────────────────────
def get_branch_account(branch: str) -> dict:
    conn = get_conn()
    row = _one(conn.execute(
        "SELECT bank, account_no, account_holder FROM branches WHERE name=?", (branch,)))
    conn.close()
    return row or {"bank": "", "account_no": "", "account_holder": ""}


# ── 문자 발송 + 로그 ──────────────────────────────────────────
def send_sms(receiver: str, msg: str, title: str = "", name: str = "",
             sent_by: str = "") -> dict:
    receiver = _digits(receiver)
    if len(receiver) < 9:
        return {"ok": False, "error": "전화번호가 올바르지 않습니다"}
    res = aligo_send(receiver, msg, title)
    ok  = str(res.get("result_code")) == "1"
    conn = get_conn()
    conn.execute("""
        INSERT INTO sms_logs (recipient, recipient_name, content, sms_type, status,
                              aligo_msg_id, error_msg, sent_by_name)
        VALUES (?,?,?,?,?,?,?,?)
    """, (receiver, name, msg, "SMS" if len(msg) <= 90 else "LMS",
          "sent" if ok else "failed", str(res.get("msg_id", "")),
          "" if ok else str(res.get("message", "")), sent_by))
    conn.commit()
    conn.close()
    return {"ok": ok, "raw": res}


# ── 주문 생성 (토스 링크 / 셀프구매) ──────────────────────────
def create_order(*, branch, member_id, member_name, member_phone, product_id,
                 product_name, category, base_amount, amount, pay_method,
                 instructor_employee_id=0, channel="link", created_by="",
                 target_ym="") -> dict:
    from domains.branch_app.testmode import is_test_flag, today_str
    token    = secrets.token_urlsafe(8)
    order_id = f"ord_{int(time.time())}_{secrets.token_hex(3)}"
    if not target_ym:
        target_ym = today_str()[:7]
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO payment_orders
        (token, order_id, branch, member_id, member_name, member_phone, product_id,
         product_name, category, base_amount, amount, pay_method,
         instructor_employee_id, channel, created_by, target_ym, is_test)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (token, order_id, branch, member_id, member_name, _digits(member_phone),
          product_id, product_name, category, base_amount, amount, pay_method,
          instructor_employee_id, channel, created_by, target_ym, is_test_flag()))
    conn.commit()
    oid = cur.lastrowid
    conn.close()
    return {"id": oid, "token": token, "order_id": order_id}


def get_order_by_token(token: str) -> dict | None:
    conn = get_conn()
    row = _one(conn.execute("SELECT * FROM payment_orders WHERE token=?", (token,)))
    conn.close()
    return row


def get_order_by_orderid(order_id: str) -> dict | None:
    conn = get_conn()
    row = _one(conn.execute("SELECT * FROM payment_orders WHERE order_id=?", (order_id,)))
    conn.close()
    return row


# ── 토스 승인 확정 → 매출/수강권 생성 → 영수증 ────────────────
def confirm_order(order_id: str, payment_key: str, amount: int) -> dict:
    """토스 successUrl 콜백에서 호출. 금액 검증 후 승인 확정."""
    order = get_order_by_orderid(order_id)
    if not order:
        return {"ok": False, "error": "주문을 찾을 수 없습니다"}
    if order["status"] == "paid":
        return {"ok": True, "already": True, "order": order}
    # 금액 위변조 방지
    if int(amount) != int(order["amount"]):
        return {"ok": False, "error": "결제 금액이 주문 금액과 일치하지 않습니다"}

    res = toss_confirm_payment(payment_key, order_id, int(amount))
    if res.get("status") != "DONE":
        err = res.get("message") or res.get("error") or "승인 실패"
        return {"ok": False, "error": err, "raw": res}

    itest = int(order.get("is_test", 0) or 0)
    tym   = order.get("target_ym", "") or ""
    # 매출 기록
    sale_id = create_sale({
        "branch": order["branch"], "member_id": order["member_id"],
        "member_name": order["member_name"], "product_id": order["product_id"],
        "product_name": order["product_name"], "category": order["category"],
        "amount": order["amount"], "pay_method": order["pay_method"],
        "is_mgmt_fee": 0, "sold_by": order["created_by"] or "셀프결제",
        "is_test": itest,
    })

    # 수강권 생성 (GX/레슨)
    product = get_product(order["product_id"]) if order["product_id"] else None
    if product and product.get("category") == "gx":
        create_gx_enrollment(branch=order["branch"], gx_product_id=product["id"],
                             member_id=order["member_id"], member_name=order["member_name"],
                             sale_id=sale_id, target_ym=tym, is_test=itest)
        # 결제로 최소인원 충족 시 해당 월 반 자동 '진행' 확정
        _auto_run_if_min_met(product["id"], tym, itest)
    elif product and product.get("category") == "lesson":
        product["price"] = order["base_amount"] or product.get("price", 0)
        product["_commission_percent"] = 0
        create_lesson_enrollment(
            branch=order["branch"], member_id=order["member_id"],
            member_name=order["member_name"], product=product, sale_id=sale_id,
            instructor_employee_id=order["instructor_employee_id"], instructor_name="",
            pay_method=order["pay_method"])
        # 레슨이면 지점 매니저·인포에게 알림
        _notify_lesson_purchase(order)

    conn = get_conn()
    conn.execute("""UPDATE payment_orders
                    SET status='paid', toss_payment_key=?, sale_id=?, paid_at=datetime('now','localtime')
                    WHERE order_id=?""", (payment_key, sale_id, order_id))
    conn.commit()
    conn.close()

    # 영수증 문자
    _send_receipt(order)
    return {"ok": True, "sale_id": sale_id, "order": order}


def _notify_lesson_purchase(order: dict):
    """레슨 구매 시 해당 지점 매니저·인포에게 알림"""
    conn = get_conn()
    try:
        rows = conn.execute("""
            SELECT DISTINCT e.id FROM employees e
            JOIN employee_roles r ON r.employee_id = e.id
            WHERE e.branch=? AND r.role IN ('manager','info') AND e.is_active=1
        """, (order["branch"],)).fetchall()
        for (eid,) in rows:
            conn.execute("""INSERT INTO notifications
                (branch, target_kind, target_employee_id, message)
                VALUES (?,?,?,?)""",
                (order["branch"], "employee", eid,
                 f"🆕 레슨 구매: {order['member_name']}님이 '{order['product_name']}' 결제 — 담당자 배정 필요"))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def _send_receipt(order: dict):
    if not order.get("member_phone"):
        return
    msg = (f"[라온스포츠 {order['branch']}]\n"
           f"{order['member_name']}님, 결제가 완료되었습니다.\n"
           f"· 상품: {order['product_name']}\n"
           f"· 금액: {order['amount']:,}원\n"
           f"이용해 주셔서 감사합니다.")
    send_sms(order["member_phone"], msg, title="결제 완료 안내",
             name=order["member_name"], sent_by="시스템")


# ── 계좌이체 안내문자 ─────────────────────────────────────────
def send_transfer_guide(*, branch, member_name, member_phone, product_name, amount):
    acct = get_branch_account(branch)
    if not acct.get("account_no"):
        return {"ok": False, "error": "지점 입금계좌가 설정되지 않았습니다 (설정에서 등록)"}
    msg = (f"[라온스포츠 {branch}]\n"
           f"{member_name}님, 아래 계좌로 입금 부탁드립니다.\n"
           f"· 상품: {product_name}\n"
           f"· 금액: {amount:,}원\n"
           f"· 입금: {acct['bank']} {acct['account_no']} ({acct['account_holder']})\n"
           f"입금 확인 후 등록 처리됩니다.")
    return send_sms(member_phone, msg, title="계좌이체 안내", name=member_name)


# ── 토스 결제링크 문자 ────────────────────────────────────────
def send_payment_link(*, base_url, order, member_name, member_phone, product_name, amount):
    link = f"{base_url}/p/{order['token']}"
    msg = (f"[라온스포츠] {member_name}님\n"
           f"'{product_name}' {amount:,}원 결제 안내입니다.\n"
           f"아래 링크에서 결제해 주세요.\n{link}")
    return send_sms(member_phone, msg, title="결제 안내", name=member_name)


# ── 재등록(다음달분) 결제링크 일괄 발송 ───────────────────────
def send_reregister_links(*, base_url, gx_product_id, sent_by="") -> dict:
    """기존 수강 회원에게 '다음 달분' 결제 링크를 개별 생성·발송.
    - 금액 = 다음달 1일 기준 풀계산(gx_price). 날짜 무관 고정.
    - 정원이 차면 더 보내지 않음(선착순, 자리보장 없음).
    - 이미 다음달분 주문/수강이 있는 회원은 건너뜀.
    - shop 화면엔 안 보이고 문자 링크로만 결제(channel='rereg').
    """
    product = get_product(gx_product_id)
    if not product:
        return {"ok": False, "error": "상품을 찾을 수 없습니다"}
    tym = next_ym()
    info = gx_price(product, tym)
    base = info["charge"]
    if base <= 0:
        return {"ok": False, "error": "다음 달 수업이 없어 재등록 금액을 계산할 수 없습니다"}
    amount = charge_amount(base, "토스")
    branch = product.get("branch", "")
    members = get_class_members(gx_product_id)

    conn = get_conn()
    sent = skipped = failed = blocked = 0
    for m in members:
        # 정원 체크(매 발송마다 갱신)
        hc = gx_headcounts(gx_product_id, tym)
        if hc["full"]:
            blocked = len(members) - (sent + skipped + failed)
            break
        mid = m["id"]
        # 이미 다음달분 주문/수강이 있으면 skip
        dup = conn.execute(
            "SELECT 1 FROM payment_orders WHERE product_id=? AND member_id=? AND target_ym=? "
            "AND status IN ('pending','paid') LIMIT 1", (gx_product_id, mid, tym)).fetchone()
        if not dup:
            dup = conn.execute(
                "SELECT 1 FROM gx_enrollments WHERE gx_product_id=? AND member_id=? AND target_ym=? "
                "AND status='active' LIMIT 1", (gx_product_id, mid, tym)).fetchone()
        if dup:
            skipped += 1
            continue
        order = create_order(
            branch=branch, member_id=mid, member_name=m["name"], member_phone=m["phone"],
            product_id=gx_product_id, product_name=f"{product['name']} (다음 달 {info['remaining']}회분)",
            category="gx", base_amount=base, amount=amount, pay_method="토스",
            channel="rereg", created_by=sent_by, target_ym=tym)
        res = send_payment_link(base_url=base_url, order=order, member_name=m["name"],
                                member_phone=m["phone"],
                                product_name=f"{product['name']} 다음 달 재등록", amount=amount)
        if res.get("ok"):
            sent += 1
        else:
            failed += 1
    conn.close()
    return {"ok": True, "target_ym": tym, "amount": amount, "sent": sent,
            "skipped": skipped, "failed": failed, "blocked": blocked,
            "total": len(members)}


# ── GX 신청/개강 로직 ─────────────────────────────────────────
def gx_apply(*, branch, gx_product_id, member_id, member_name, member_phone, target_ym="") -> dict:
    """최소인원 미달 시 개강대기 신청 등록. 충족되면 caller가 결제 진행 가능."""
    from domains.branch_app.testmode import is_test_flag, today_str
    if not target_ym:
        target_ym = today_str()[:7]
    conn = get_conn()
    try:
        conn.execute("""INSERT OR IGNORE INTO gx_applications
            (branch, gx_product_id, member_id, member_name, member_phone, target_ym, is_test)
            VALUES (?,?,?,?,?,?,?)""",
            (branch, gx_product_id, member_id, member_name, _digits(member_phone),
             target_ym, is_test_flag()))
        conn.commit()
        cnt = conn.execute("SELECT COUNT(*) FROM gx_applications WHERE gx_product_id=? "
                           "AND status='waiting' AND target_ym=?",
                           (gx_product_id, target_ym)).fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "waiting": cnt}


def gx_headcounts(gx_product_id: int, target_ym: str = "", include_test: bool = None) -> dict:
    """월별(target_ym) 결제완료 수강(active) + 대기신청 + 상품 min/max + 반 상태."""
    from domains.branch_app.testmode import is_test_mode, today_str
    if not target_ym:
        target_ym = today_str()[:7]
    if include_test is None:
        include_test = is_test_mode()
    test_filter = "" if include_test else " AND COALESCE(is_test,0)=0"
    conn = get_conn()
    enrolled = conn.execute(
        f"SELECT COUNT(*) FROM gx_enrollments WHERE gx_product_id=? AND status='active' "
        f"AND target_ym=?{test_filter}", (gx_product_id, target_ym)).fetchone()[0]
    waiting  = conn.execute(
        f"SELECT COUNT(*) FROM gx_applications WHERE gx_product_id=? AND status='waiting' "
        f"AND target_ym=?{test_filter}", (gx_product_id, target_ym)).fetchone()[0]
    p = _one(conn.execute("SELECT min_headcount, max_headcount, capacity FROM products WHERE id=?",
                          (gx_product_id,)))
    st = _one(conn.execute("SELECT status FROM gx_class_status WHERE gx_product_id=? AND ym=?",
                           (gx_product_id, target_ym)))
    conn.close()
    p = p or {}
    cap = p.get("max_headcount") or p.get("capacity") or 0
    mn = p.get("min_headcount") or 0
    status = (st or {}).get("status") or ("running" if (mn and enrolled >= mn) else ("waiting" if mn else "running"))
    return {"enrolled": enrolled, "waiting": waiting, "ym": target_ym,
            "min": mn, "max": cap, "status": status,
            "full": bool(cap and enrolled >= cap)}


def branch_gx_calendar(branch: str, ym: str) -> dict:
    """회원 홈 달력용 — 지점에서 '진행(running)'인 GX수업의 확정 수업일 + 날짜별 수업카드."""
    conn = get_conn()
    cur = conn.execute(
        "SELECT id, name, instructor_name, start_time, end_time, capacity, max_headcount "
        "FROM products WHERE category='gx' AND is_active=1 AND branch=?", (branch,))
    cols = [d[0] for d in cur.description]
    prods = [dict(zip(cols, r)) for r in cur.fetchall()]
    conn.close()
    by_date: dict = {}
    for p in prods:
        hc = gx_headcounts(p["id"], ym)
        if hc["status"] != "running":      # 반 상태가 '진행'인 수업만
            continue
        for d in _confirmed_session_dates(p["id"], ym):
            by_date.setdefault(d, []).append({
                "product_id": p["id"], "name": p["name"],
                "instructor_name": p.get("instructor_name", ""),
                "start_time": p.get("start_time", ""), "end_time": p.get("end_time", ""),
                "capacity": hc["max"] or p.get("capacity") or 0,
                "enrolled": hc["enrolled"],
            })
    return {"ym": ym, "by_date": by_date, "dates": sorted(by_date.keys())}


# ── GX 노출 정책 (1~23일 당월만 / 24~말일 +다음달, 재등록 20~23) ──
def gx_visible_yms() -> dict:
    """오늘(오버라이드) 기준 shop에 보일 대상월 목록 + 재등록 기간 여부."""
    from domains.branch_app.testmode import today_dt
    now = today_dt()
    cur_ym = now.strftime("%Y-%m")
    ny, nm = (now.year + 1, 1) if now.month == 12 else (now.year, now.month + 1)
    next_ym = f"{ny:04d}-{nm:02d}"
    day = now.day
    shop_yms = [cur_ym]
    if day >= 24:
        shop_yms.append(next_ym)
    rereg = (20 <= day <= 23)   # 재등록 안내 기간
    return {"current_ym": cur_ym, "next_ym": next_ym, "shop_yms": shop_yms,
            "rereg_period": rereg, "day": day}


def next_ym() -> str:
    return gx_visible_yms()["next_ym"]


# ── 반 상태(대기/진행) 관리 ──────────────────────────────────
def _set_class_status(gx_product_id: int, ym: str, status: str,
                      decided_by: str = "", is_test: int = 0):
    conn = get_conn()
    conn.execute("""INSERT INTO gx_class_status (gx_product_id, ym, status, decided_by, decided_at, is_test)
                    VALUES (?,?,?,?,datetime('now','localtime'),?)
                    ON CONFLICT(gx_product_id, ym) DO UPDATE SET
                      status=excluded.status, decided_by=excluded.decided_by,
                      decided_at=excluded.decided_at""",
                 (gx_product_id, ym, status, decided_by, is_test))
    conn.commit()
    conn.close()


def _auto_run_if_min_met(gx_product_id: int, ym: str, is_test: int = 0):
    """결제로 최소인원 충족 시 자동 '진행' 확정 (이미 진행이면 무시)."""
    hc = gx_headcounts(gx_product_id, ym)
    if hc["status"] == "running":
        return
    if hc["min"] > 0 and hc["enrolled"] >= hc["min"]:
        _set_class_status(gx_product_id, ym, "running", decided_by="자동(인원충족)", is_test=is_test)


def gx_set_class_running(base_url: str, gx_product_id: int, ym: str = "",
                         decided_by: str = "", notify: bool = True) -> dict:
    """관리자가 반을 '진행'으로 확정. 미달이어도 강행 가능 + 대기/수강자에게 결제안내."""
    from domains.branch_app.testmode import today_str, is_test_flag
    if not ym:
        ym = today_str()[:7]
    _set_class_status(gx_product_id, ym, "running", decided_by=decided_by, is_test=is_test_flag())
    notified = 0
    if notify:
        conn = get_conn()
        prod = _one(conn.execute("SELECT name, branch FROM products WHERE id=?", (gx_product_id,)))
        apps = conn.execute("""SELECT member_name, member_phone FROM gx_applications
                               WHERE gx_product_id=? AND status='waiting' AND target_ym=?""",
                            (gx_product_id, ym)).fetchall()
        conn.close()
        for name, phone in apps:
            msg = (f"[라온스포츠 {prod['branch']}]\n"
                   f"{name}님, 신청하신 '{prod['name']}' 수업이 개강 확정되었습니다!\n"
                   f"아래에서 결제하시면 수강이 확정됩니다.\n{base_url}/app")
            if send_sms(phone, msg, title="개강 확정 안내", name=name).get("ok"):
                notified += 1
        conn = get_conn()
        conn.execute("UPDATE gx_applications SET status='notified' "
                     "WHERE gx_product_id=? AND status='waiting' AND target_ym=?",
                     (gx_product_id, ym))
        conn.commit()
        conn.close()
    return {"ok": True, "status": "running", "ym": ym, "notified": notified}


def gx_set_class_waiting(gx_product_id: int, ym: str = "", decided_by: str = "") -> dict:
    """관리자가 반을 '대기'로 되돌림."""
    from domains.branch_app.testmode import today_str, is_test_flag
    if not ym:
        ym = today_str()[:7]
    _set_class_status(gx_product_id, ym, "waiting", decided_by=decided_by, is_test=is_test_flag())
    return {"ok": True, "status": "waiting", "ym": ym}


def gx_class_board(branch: str, ym: str = "") -> list[dict]:
    """지점 GX 반별 상태판 — 월별 정원/대기/진행 + 미달 경고."""
    from domains.branch_app.testmode import today_str
    if not ym:
        ym = today_str()[:7]
    conn = get_conn()
    prods = _rows_local(conn.execute(
        "SELECT id, name, instructor_name, min_headcount, max_headcount, capacity "
        "FROM products WHERE branch=? AND category='gx' AND is_active=1 ORDER BY name", (branch,)))
    conn.close()
    out = []
    for p in prods:
        hc = gx_headcounts(p["id"], ym)
        out.append({
            "id": p["id"], "name": p["name"], "instructor_name": p.get("instructor_name", ""),
            "ym": ym, "enrolled": hc["enrolled"], "waiting": hc["waiting"],
            "min": hc["min"], "max": hc["max"], "status": hc["status"], "full": hc["full"],
            "short": (hc["min"] > 0 and hc["status"] != "running" and hc["enrolled"] < hc["min"]),
        })
    return out


def _rows_local(cur):
    cols = [d[0] for d in cur.description]
    return [_dec_row(dict(zip(cols, r))) for r in cur.fetchall()]


def gx_check_and_open(base_url: str, gx_product_id: int) -> dict:
    """대기자 수가 최소인원 충족되면 전체 안내 발송."""
    hc = gx_headcounts(gx_product_id)
    if hc["min"] <= 0 or hc["waiting"] < hc["min"]:
        return {"opened": False, **hc}
    conn = get_conn()
    prod = _one(conn.execute("SELECT name, branch FROM products WHERE id=?", (gx_product_id,)))
    apps = conn.execute("""SELECT member_name, member_phone FROM gx_applications
                           WHERE gx_product_id=? AND status='waiting'""", (gx_product_id,)).fetchall()
    conn.close()
    sent = 0
    for name, phone in apps:
        msg = (f"[라온스포츠 {prod['branch']}]\n"
               f"{name}님, 신청하신 '{prod['name']}' 수업이 최소 개강 인원을 충족했습니다!\n"
               f"아래에서 결제하시면 수강이 확정됩니다.\n{base_url}/app")
        if send_sms(phone, msg, title="개강 확정 안내", name=name).get("ok"):
            sent += 1
    conn = get_conn()
    conn.execute("UPDATE gx_applications SET status='notified' WHERE gx_product_id=? AND status='waiting'",
                 (gx_product_id,))
    conn.commit()
    conn.close()
    return {"opened": True, "notified": sent, **hc}
