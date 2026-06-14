"""
domains/branch_app/approvals.py — CRM 결재/이관 공통 엔진 + 알림

흐름:  직원 생성 → (지점관리자 1차 체크) → (본사관리자 2차) → 완료
- 지점에 manager 직무가 없으면 1차를 건너뛰고 바로 본사(hq)로.
- 각 단계 처리자/시각을 남겨 감사추적.

item_type 예: 'as' | 'supply' | 'complaint' | 'refund' | 'suggestion' | 'daily_report'
"""
from shared.db import get_conn


def init_approval_tables():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS approval_items (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            branch              TEXT NOT NULL,
            item_type           TEXT NOT NULL,
            ref_id              INTEGER DEFAULT 0,
            summary             TEXT DEFAULT '',
            created_by          INTEGER DEFAULT 0,      -- employee_id
            created_by_name     TEXT DEFAULT '',
            stage               TEXT DEFAULT 'branch',  -- 'branch' | 'hq' | 'done'
            status              TEXT DEFAULT 'pending', -- 'pending'|'branch_ok'|'completed'|'rejected'
            branch_approved_by  TEXT DEFAULT '',
            branch_approved_at  TEXT,
            hq_approved_by      TEXT DEFAULT '',
            hq_approved_at      TEXT,
            reject_reason       TEXT DEFAULT '',
            created_at          TEXT DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS notifications (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            branch              TEXT DEFAULT '',
            target_kind         TEXT NOT NULL,          -- 'branch_manager'|'hq_admin'|'employee'|'member'
            target_employee_id  INTEGER DEFAULT 0,
            approval_item_id    INTEGER DEFAULT 0,
            message             TEXT DEFAULT '',
            is_read             INTEGER DEFAULT 0,
            created_at          TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()


def _rows(cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def branch_has_manager(branch: str) -> bool:
    conn = get_conn()
    row = conn.execute("""
        SELECT 1 FROM employees e
        JOIN employee_roles r ON r.employee_id = e.id
        WHERE e.branch=? AND e.is_active=1 AND r.role='manager' LIMIT 1
    """, (branch,)).fetchone()
    conn.close()
    return bool(row)


def _notify(conn, branch, target_kind, message, approval_item_id=0, target_employee_id=0):
    conn.execute("""
        INSERT INTO notifications (branch, target_kind, target_employee_id, approval_item_id, message)
        VALUES (?,?,?,?,?)
    """, (branch, target_kind, target_employee_id, approval_item_id, message))


def create_approval(branch: str, item_type: str, ref_id: int, summary: str,
                    created_by: int = 0, created_by_name: str = "") -> int:
    """결재 항목 생성 + 1차 대상에게 알림. 반환: approval_item_id"""
    has_mgr = branch_has_manager(branch)
    stage = "branch" if has_mgr else "hq"
    conn = get_conn()
    cur = conn.execute("""
        INSERT INTO approval_items
        (branch, item_type, ref_id, summary, created_by, created_by_name, stage, status)
        VALUES (?,?,?,?,?,?,?, 'pending')
    """, (branch, item_type, ref_id, summary, created_by, created_by_name, stage))
    aid = cur.lastrowid
    if has_mgr:
        _notify(conn, branch, "branch_manager", f"[결재요청] {summary}", aid)
    else:
        _notify(conn, branch, "hq_admin", f"[본사결재] {summary}", aid)
    conn.commit()
    conn.close()
    return aid


def approve_branch(approval_id: int, manager_name: str) -> bool:
    """지점관리자 1차 결재 → 본사로 이관 + 본사 알림."""
    conn = get_conn()
    row = conn.execute(
        "SELECT branch, summary, stage FROM approval_items WHERE id=?", (approval_id,)
    ).fetchone()
    if not row or row[2] != "branch":
        conn.close()
        return False
    branch, summary, _ = row
    conn.execute("""
        UPDATE approval_items
        SET stage='hq', status='branch_ok',
            branch_approved_by=?, branch_approved_at=datetime('now','localtime')
        WHERE id=?
    """, (manager_name, approval_id))
    _notify(conn, branch, "hq_admin", f"[본사결재] {summary} (지점 승인: {manager_name})", approval_id)
    conn.commit()
    conn.close()
    return True


def approve_hq(approval_id: int, admin_name: str) -> bool:
    """본사관리자 최종 결재 → 완료. 생성자에게 완료 알림."""
    conn = get_conn()
    row = conn.execute(
        "SELECT branch, summary, created_by FROM approval_items WHERE id=?", (approval_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    branch, summary, created_by = row
    conn.execute("""
        UPDATE approval_items
        SET stage='done', status='completed',
            hq_approved_by=?, hq_approved_at=datetime('now','localtime')
        WHERE id=?
    """, (admin_name, approval_id))
    if created_by:
        _notify(conn, branch, "employee", f"[처리완료] {summary}", approval_id, created_by)
    conn.commit()
    conn.close()
    return True


def reject_approval(approval_id: int, by_name: str, reason: str = "") -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT branch, summary, created_by FROM approval_items WHERE id=?", (approval_id,)
    ).fetchone()
    if not row:
        conn.close()
        return False
    branch, summary, created_by = row
    conn.execute("""
        UPDATE approval_items SET stage='done', status='rejected', reject_reason=?
        WHERE id=?
    """, (reason, approval_id))
    if created_by:
        _notify(conn, branch, "employee",
                f"[반려] {summary} — {reason or '사유 미기재'}", approval_id, created_by)
    conn.commit()
    conn.close()
    return True


def list_approvals(branch: str = "", stage: str = "", status: str = "",
                   created_by: int = 0, limit: int = 200) -> list[dict]:
    q = "SELECT * FROM approval_items WHERE 1=1"
    p: list = []
    if branch:
        q += " AND branch=?"; p.append(branch)
    if stage:
        q += " AND stage=?"; p.append(stage)
    if status:
        q += " AND status=?"; p.append(status)
    if created_by:
        q += " AND created_by=?"; p.append(created_by)
    q += " ORDER BY id DESC LIMIT ?"; p.append(limit)
    conn = get_conn()
    out = _rows(conn.execute(q, p))
    conn.close()
    return out


def approvals_resolved_by_branch_on(branch: str, date_str: str) -> list[dict]:
    """지점관리자가 특정 날짜에 1차 처리한 결재 항목 (일일보고 롤업용)."""
    conn = get_conn()
    out = _rows(conn.execute("""
        SELECT * FROM approval_items
        WHERE branch=? AND date(branch_approved_at)=?
        ORDER BY id DESC
    """, (branch, date_str)))
    conn.close()
    return out


# ── 알림 ────────────────────────────────────────────────────
def get_notifications(target_kind: str, branch: str = "", employee_id: int = 0,
                      unread_only: bool = False, limit: int = 50) -> list[dict]:
    q = "SELECT * FROM notifications WHERE target_kind=?"
    p: list = [target_kind]
    if target_kind == "branch_manager":
        q += " AND branch=?"; p.append(branch)
    elif target_kind == "employee":
        q += " AND target_employee_id=?"; p.append(employee_id)
    if unread_only:
        q += " AND is_read=0"
    q += " ORDER BY id DESC LIMIT ?"; p.append(limit)
    conn = get_conn()
    out = _rows(conn.execute(q, p))
    conn.close()
    return out


def unread_count(target_kind: str, branch: str = "", employee_id: int = 0) -> int:
    return len(get_notifications(target_kind, branch, employee_id, unread_only=True, limit=999))


def mark_notification_read(notif_id: int):
    conn = get_conn()
    conn.execute("UPDATE notifications SET is_read=1 WHERE id=?", (notif_id,))
    conn.commit()
    conn.close()


def mark_all_read(target_kind: str, branch: str = "", employee_id: int = 0):
    conn = get_conn()
    q = "UPDATE notifications SET is_read=1 WHERE target_kind=?"
    p: list = [target_kind]
    if target_kind == "branch_manager":
        q += " AND branch=?"; p.append(branch)
    elif target_kind == "employee":
        q += " AND target_employee_id=?"; p.append(employee_id)
    conn.execute(q, p)
    conn.commit()
    conn.close()
