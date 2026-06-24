"""
domains/branch_app/ops.py
운영 공통: 감사로그 / 월마감(락) / 환불.
ERP·CRM 양쪽에서 import 해서 사용.
"""
from shared.db import get_conn


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


# ── 감사 로그 ─────────────────────────────────────────────────
def log_action(actor: str, action: str, target: str = "", detail: str = "",
               branch: str = "", actor_role: str = ""):
    """민감 작업 기록. 실패해도 본작업에 영향 주지 않도록 조용히 무시."""
    try:
        conn = get_conn()
        conn.execute("""INSERT INTO audit_logs (actor, actor_role, branch, action, target, detail)
                        VALUES (?,?,?,?,?,?)""",
                     (actor, actor_role, branch, action, target, detail))
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_audit_logs(branch: str = "", action: str = "", limit: int = 200) -> list:
    conn = get_conn()
    q = "SELECT * FROM audit_logs WHERE 1=1"
    args = []
    if branch:
        q += " AND branch=?"; args.append(branch)
    if action:
        q += " AND action LIKE ?"; args.append(action + "%")
    q += " ORDER BY id DESC LIMIT ?"; args.append(limit)
    res = _rows(conn.execute(q, args))
    conn.close()
    return res


# ── 월 마감(락) ───────────────────────────────────────────────
def is_locked(year: int, month: int, branch: str = "") -> bool:
    """해당 월이 잠겼는지 (전사 락 또는 해당 지점 락)."""
    conn = get_conn()
    row = conn.execute(
        "SELECT 1 FROM month_locks WHERE year=? AND month=? AND (branch=? OR branch='')",
        (year, month, branch)).fetchone()
    conn.close()
    return bool(row)


def lock_month(year: int, month: int, branch: str, locked_by: str) -> bool:
    try:
        conn = get_conn()
        conn.execute("""INSERT OR REPLACE INTO month_locks (year, month, branch, locked_by, locked_at)
                        VALUES (?,?,?,?,datetime('now','localtime'))""",
                     (year, month, branch, locked_by))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def unlock_month(year: int, month: int, branch: str) -> bool:
    try:
        conn = get_conn()
        conn.execute("DELETE FROM month_locks WHERE year=? AND month=? AND branch=?",
                     (year, month, branch))
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def list_locks(year: int = None) -> list:
    conn = get_conn()
    if year:
        cur = conn.execute("SELECT * FROM month_locks WHERE year=? ORDER BY year DESC, month DESC", (year,))
    else:
        cur = conn.execute("SELECT * FROM month_locks ORDER BY year DESC, month DESC")
    res = _rows(cur)
    conn.close()
    return res


# ── 환불 ──────────────────────────────────────────────────────
def get_sale(sale_id: int) -> dict | None:
    conn = get_conn()
    cur = conn.execute("SELECT * FROM sales WHERE id=?", (sale_id,))
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    conn.close()
    return dict(zip(cols, row)) if row else None


def process_refund(sale_id: int, refund_amount: int, reason: str, refunded_by: str) -> dict:
    """결제 환불. 토스 결제건이면 토스 취소 API 호출, 아니면 수기 환불 기록.
    매출(sales)은 환불액만큼 음수 보정 기록을 남기지 않고, refunds에 기록 + 원매출 status 표시."""
    sale = get_sale(sale_id)
    if not sale:
        return {"ok": False, "error": "결제 내역을 찾을 수 없습니다"}

    method = "manual"
    toss_result = ""
    # 토스 결제건이면 payment_orders에서 paymentKey 찾아 취소
    conn = get_conn()
    po = conn.execute("SELECT toss_payment_key FROM payment_orders WHERE sale_id=? AND status='paid'",
                      (sale_id,)).fetchone()
    conn.close()
    if po and po[0]:
        from domains.branch_app.db import toss_cancel_payment
        res = toss_cancel_payment(po[0], reason or "환불")
        toss_result = str(res)[:200]
        if res.get("status") in ("CANCELED", "PARTIAL_CANCELED"):
            method = "toss"
        else:
            return {"ok": False, "error": "토스 취소 실패: " + str(res.get("message") or res.get("error") or res)}

    conn = get_conn()
    conn.execute("""INSERT INTO refunds (sale_id, branch, member_id, member_name, product_name,
                    paid_amount, refund_amount, reason, method, toss_result, refunded_by)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                 (sale_id, sale.get("branch", ""), sale.get("member_id", 0),
                  sale.get("member_name", ""), sale.get("product_name", ""),
                  sale.get("amount", 0), refund_amount, reason, method, toss_result, refunded_by))
    # 원 매출에 환불표시 (category 뒤에 태그 — 집계에서 제외 처리용)
    conn.execute("UPDATE sales SET pay_method = pay_method || '(환불)' WHERE id=? AND pay_method NOT LIKE '%환불%'",
                 (sale_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "method": method}


def get_refunds(branch: str = "", year: int = None, month: int = None) -> list:
    conn = get_conn()
    q = "SELECT * FROM refunds WHERE 1=1"
    args = []
    if branch:
        q += " AND branch=?"; args.append(branch)
    if year and month:
        q += " AND created_at LIKE ?"; args.append(f"{year}-{month:02d}%")
    q += " ORDER BY id DESC LIMIT 200"
    res = _rows(conn.execute(q, args))
    conn.close()
    return res
