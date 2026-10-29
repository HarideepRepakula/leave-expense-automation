"""Read-only analytics views for the dashboard (Phase 10; docs/03 sections 3 and 7.1, amendment F3).

Revision ID: 0003_analytics_views
Revises: 0002_step_covered_levels

Three views in ops, owned by the migrator, and SELECT on them (only them) for lea_analytics_ro. A view runs with
its owner's table rights, so the analytics role still has no grant on any table and none on the evaluation schema.
The views add no business rule: they project and join stored columns.

    ops.v_request            one row per leave request / expense claim (both kinds, one shape)
    ops.v_request_exception  request_exception rows of the CURRENT round, with exception_class and severity
    ops.v_reimbursement      reimbursement rows

The SQL is written out here (not imported) so this revision never changes.
"""
from __future__ import annotations

from alembic import op

revision = "0003_analytics_views"
down_revision = "0002_step_covered_levels"
branch_labels = None
depends_on = None

VIEWS = {
    "v_request": """
        SELECT 'LEAVE'::text AS request_type, l.leave_request_id AS request_id, l.employee_id, e.country,
               e.department_id, l.workflow_status, l.exception_class, l.current_round, l.first_submitted_at,
               l.start_date AS period_start, l.end_date AS period_end, l.requested_quantity AS leave_days,
               NULL::numeric AS total_amount, NULL::numeric AS approved_amount, NULL::text AS currency,
               NULL::numeric AS total_amount_usd, l.decision_reason_code
        FROM ops.leave_request l JOIN ops.employee e ON e.employee_id = l.employee_id
        UNION ALL
        SELECT 'EXPENSE', c.expense_claim_id, c.employee_id, c.country, e.department_id, c.workflow_status,
               c.exception_class, c.current_round, c.first_submitted_at, c.claim_period_start, c.claim_period_end,
               NULL, c.total_amount, c.approved_amount, c.currency, c.total_amount_usd, c.decision_reason_code
        FROM ops.expense_claim c JOIN ops.employee e ON e.employee_id = c.employee_id""",
    "v_request_exception": """
        SELECT x.exception_id, x.request_type, coalesce(x.leave_request_id, x.expense_claim_id) AS request_id,
               x.submission_round, x.exception_code, k.exception_class, k.severity, x.detected_by, x.detected_at
        FROM ops.request_exception x
        JOIN ops.exception_code k ON k.exception_code = x.exception_code
        LEFT JOIN ops.leave_request l ON l.leave_request_id = x.leave_request_id
        LEFT JOIN ops.expense_claim c ON c.expense_claim_id = x.expense_claim_id
        WHERE x.submission_round = coalesce(l.current_round, c.current_round)""",
    "v_reimbursement": """
        SELECT reimbursement_id, expense_claim_id, employee_id, approved_amount, currency, eligibility_status,
               reimbursement_status, created_at, completed_at
        FROM ops.reimbursement""",
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW ops.{name} AS {sql}")
        # The default privileges (sql/grants.sql) give lea_app write rights on new relations; a simple view is
        # updatable through its owner's rights, so the app gets nothing on the views.
        op.execute(f"REVOKE ALL ON ops.{name} FROM lea_app")
        op.execute(f"GRANT SELECT ON ops.{name} TO lea_analytics_ro")


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS ops.{name}")
