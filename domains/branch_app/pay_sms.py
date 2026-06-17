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


def _one(cur):
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None


def _digits(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


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
                 instructor_employee_id=0, channel="link", created_by="") -> dict:
    token    = secrets.token_urlsafe(8)
    order_id = f"ord_{int(time.time())}_{secrets.token_hex(3)}"
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO payment_orders
        (token, order_id, branch, member_id, member_name, member_phone, product_id,
         product_name, category, base_amount, amount, pay_method,
         instructor_employee_id, channel, created_by)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (token, order_id, branch, member_id, member_name, _digits(member_phone),
          product_id, product_name, category, base_amount, amount, pay_method,
          instructor_employee_id, channel, created_by))
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

    # 매출 기록
    sale_id = create_sale({
        "branch": order["branch"], "member_id": order["member_id"],
        "member_name": order["member_name"], "product_id": order["product_id"],
        "product_name": order["product_name"], "category": order["category"],
        "amount": order["amount"], "pay_method": order["pay_method"],
        "is_mgmt_fee": 0, "sold_by": order["created_by"] or "셀프결제",
    })

    # 수강권 생성 (GX/레슨)
    product = get_product(order["product_id"]) if order["product_id"] else None
    if product and product.get("category") == "gx":
        create_gx_enrollment(branch=order["branch"], gx_product_id=product["id"],
                             member_id=order["member_id"], member_name=order["member_name"],
                             sale_id=sale_id)
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


# ── GX 신청/개강 로직 ─────────────────────────────────────────
def gx_apply(*, branch, gx_product_id, member_id, member_name, member_phone) -> dict:
    """최소인원 미달 시 개강대기 신청 등록. 충족되면 caller가 결제 진행 가능."""
    conn = get_conn()
    try:
        conn.execute("""INSERT OR IGNORE INTO gx_applications
            (branch, gx_product_id, member_id, member_name, member_phone)
            VALUES (?,?,?,?,?)""",
            (branch, gx_product_id, member_id, member_name, _digits(member_phone)))
        conn.commit()
        cnt = conn.execute("SELECT COUNT(*) FROM gx_applications WHERE gx_product_id=? AND status='waiting'",
                           (gx_product_id,)).fetchone()[0]
    finally:
        conn.close()
    return {"ok": True, "waiting": cnt}


def gx_headcounts(gx_product_id: int) -> dict:
    """현재 결제완료 수강(active) + 대기신청 수 + 상품 min/max"""
    conn = get_conn()
    enrolled = conn.execute("SELECT COUNT(*) FROM gx_enrollments WHERE gx_product_id=? AND status='active'",
                            (gx_product_id,)).fetchone()[0]
    waiting  = conn.execute("SELECT COUNT(*) FROM gx_applications WHERE gx_product_id=? AND status='waiting'",
                            (gx_product_id,)).fetchone()[0]
    p = _one(conn.execute("SELECT min_headcount, max_headcount, capacity FROM products WHERE id=?",
                          (gx_product_id,)))
    conn.close()
    p = p or {}
    cap = p.get("max_headcount") or p.get("capacity") or 0
    return {"enrolled": enrolled, "waiting": waiting,
            "min": p.get("min_headcount") or 0, "max": cap}


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
