"""
shared/db.py — modules.db 재수출 (하위 호환 + 단일 진입점)
실제 DB 코드는 modules/db.py에 유지.
"""
from modules.db import (  # noqa: F401
    get_conn, init_db, load_keyword_rules,
    upsert_card_sales, upsert_bank_transactions, upsert_payroll,
    upsert_insurance_payments, get_insurance_summary,
    get_card_by_branch, get_branch_cash_revenue,
    get_expense_by_category, get_revenue_by_category, get_payroll_summary,
    get_unreviewed_transactions, get_all_bank_transactions,
    update_transaction_classification,
    get_keyword_rules, EXPENSE_CATEGORIES, REVENUE_CATEGORIES,
    DB_PATH,
    delete_card_sales, delete_bank_transactions,
    delete_keyword_rule, update_keyword_rule,
    get_branch_goals, set_branch_goal,
)
