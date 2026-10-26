"""Acceptance criteria 1 and 2: the schema is executable and every required entity exists (R-7.0, AM-C, AM-E1)."""
import pytest
import sqlalchemy as sa

pytestmark = pytest.mark.db

EXPECTED_OPS = {
    # 11 core entities (spec section 7)
    "employee", "leave_policy", "leave_balance", "leave_request", "expense_policy", "expense_claim",
    "expense_line", "cost_center", "approval_rule", "approval_step", "reimbursement",
    # supporting entities (docs/04 section 1.2)
    "department", "cost_center_budget", "employee_cost_center_assignment", "country_holiday", "fx_rate",
    "delegation", "id_sequence", "exception_code", "leave_balance_transaction", "receipt",
    "cost_center_transaction", "approval_event", "approval_attempt", "request_status_event",
    "request_exception", "reimbursement_attempt", "audit_event", "processing_failure",
    "idempotency_record", "role", "application_user", "user_role",
}
EXPECTED_GT = {"record_expectation", "anomaly_label", "boundary_case", "scenario"}


def test_all_ops_tables_exist(engine):
    insp = sa.inspect(engine)
    assert set(insp.get_table_names(schema="ops")) == EXPECTED_OPS


def test_all_ground_truth_tables_exist(engine):
    insp = sa.inspect(engine)
    assert set(insp.get_table_names(schema="ground_truth")) == EXPECTED_GT


def test_no_foreign_keys_between_ops_and_ground_truth(engine):
    """Amendment E1: no FK in either direction."""
    insp = sa.inspect(engine)
    for schema, other in (("ops", "ground_truth"), ("ground_truth", "ops")):
        for table in insp.get_table_names(schema=schema):
            for fk in insp.get_foreign_keys(table, schema=schema):
                assert fk.get("referred_schema") != other, f"{schema}.{table} references {other}"


def test_no_ground_truth_label_columns_in_ops(engine):
    """Amendment E1: operational tables carry no is_anomaly / issue_type / is_planted style columns."""
    insp = sa.inspect(engine)
    forbidden = {"is_anomaly", "issue_type", "scenario_id", "is_planted", "ground_truth_label"}
    for table in insp.get_table_names(schema="ops"):
        cols = {c["name"] for c in insp.get_columns(table, schema="ops")}
        assert not (cols & forbidden), f"ops.{table} has label columns {cols & forbidden}"


def test_every_ops_table_has_text_primary_key_with_format_check(engine):
    insp = sa.inspect(engine)
    for table in insp.get_table_names(schema="ops"):
        pk = insp.get_pk_constraint(table, schema="ops")
        assert pk["constrained_columns"], f"ops.{table} has no primary key"
        checks = {c["name"] for c in insp.get_check_constraints(table, schema="ops")}
        if table in {"id_sequence", "user_role", "idempotency_record"}:
            continue  # natural keys without a formatted ID pattern (idempotency key has its own hex check)
        assert any(name.endswith("_format") for name in checks), f"ops.{table} lacks an ID format CHECK"
