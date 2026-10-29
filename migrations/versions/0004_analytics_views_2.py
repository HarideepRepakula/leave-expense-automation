"""More read-only analytics views for the dashboard (completion pass; docs/03 sections 3 and 7.1, spec section 20).

Revision ID: 0004_analytics_views_2
Revises: 0003_analytics_views

Same pattern as 0003: views in ops owned by the migrator, SELECT for lea_analytics_ro only, nothing for lea_app.
They project and join stored columns; no business rule. No personal data (no names, e-mail, merchant text or
error messages). The deferred 8B-2 migration (ground_truth.record_round_expectation) becomes 0005.

    ops.v_employee                organisation fields of each employee (filters, total employees)
    ops.v_request_dimension       per request: leave type, cost center, requester's manager, final decision time
    ops.v_expense_line            expense lines of each claim's CURRENT round
    ops.v_approval_step           approval steps of each request's CURRENT round
    ops.v_approval_attempt        approval attempts (accepted and blocked)
    ops.v_reimbursement_attempt   reimbursement attempts (payments, failures, blocked duplicates)
    ops.v_processing_failure      technical processing failures

The SQL is written out here (not imported) so this revision never changes.
"""
from __future__ import annotations

from alembic import op

revision = "0004_analytics_views_2"
down_revision = "0003_analytics_views"
branch_labels = None
depends_on = None

VIEWS = {
    "v_employee": """
        SELECT employee_id, manager_id, department_id, country, grade, employment_status, default_cost_center_id
        FROM ops.employee""",
    "v_request_dimension": """
        SELECT 'LEAVE'::text AS request_type, l.leave_request_id AS request_id, p.leave_type,
               NULL::text AS cost_center_id, e.manager_id,
               (SELECT max(s.occurred_at) FROM ops.request_status_event s
                WHERE s.leave_request_id = l.leave_request_id AND s.new_status = l.workflow_status
                AND l.workflow_status IN ('APPROVED', 'REJECTED')) AS decided_at
        FROM ops.leave_request l JOIN ops.employee e ON e.employee_id = l.employee_id
        JOIN ops.leave_policy p ON p.leave_policy_id = l.leave_policy_id
        UNION ALL
        SELECT 'EXPENSE', c.expense_claim_id, NULL, c.cost_center_id, e.manager_id,
               (SELECT max(s.occurred_at) FROM ops.request_status_event s
                WHERE s.expense_claim_id = c.expense_claim_id AND s.new_status = c.workflow_status
                AND c.workflow_status IN ('APPROVED', 'REJECTED'))
        FROM ops.expense_claim c JOIN ops.employee e ON e.employee_id = c.employee_id""",
    "v_expense_line": """
        SELECT x.expense_line_id, x.expense_claim_id, x.category, x.line_amount, x.currency,
               coalesce(x.cost_center_id, c.cost_center_id) AS cost_center_id, x.validation_result
        FROM ops.expense_line x JOIN ops.expense_claim c ON c.expense_claim_id = x.expense_claim_id
        WHERE x.submission_round = c.current_round""",
    "v_approval_step": """
        SELECT s.approval_step_id, s.request_type, coalesce(s.leave_request_id, s.expense_claim_id) AS request_id,
               s.submission_round, s.sequence_no, s.required_level, s.approver_employee_id, s.step_status,
               s.assigned_at, s.decision_at
        FROM ops.approval_step s
        LEFT JOIN ops.leave_request l ON l.leave_request_id = s.leave_request_id
        LEFT JOIN ops.expense_claim c ON c.expense_claim_id = s.expense_claim_id
        WHERE s.submission_round = coalesce(l.current_round, c.current_round)""",
    "v_approval_attempt": """
        SELECT attempt_id, request_type, request_id, actor_id, approval_step_id, attempted_action, attempted_at,
               outcome, reason_code
        FROM ops.approval_attempt""",
    "v_reimbursement_attempt": """
        SELECT attempt_id, actor_type, expense_claim_id, reimbursement_id, attempted_action, attempted_at, outcome,
               reason_code
        FROM ops.reimbursement_attempt""",
    "v_processing_failure": """
        SELECT failure_id, entity_type, entity_id, operation, error_code, occurred_at, resolution_status
        FROM ops.processing_failure""",
}


def upgrade() -> None:
    for name, sql in VIEWS.items():
        op.execute(f"CREATE VIEW ops.{name} AS {sql}")
        op.execute(f"REVOKE ALL ON ops.{name} FROM lea_app")       # see 0003: default privileges would grant it
        op.execute(f"GRANT SELECT ON ops.{name} TO lea_analytics_ro")


def downgrade() -> None:
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW IF EXISTS ops.{name}")
