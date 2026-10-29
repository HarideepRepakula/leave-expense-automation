-- Table-level grants (docs/03 section 7.1, amendments E1, F3, F4).
-- Applied by Alembic migration 0001 after tables and triggers exist. Idempotent.
--
-- lea_migrator  owns both schemas (runs migrations)
-- lea_app       ops only; INSERT/SELECT only on append-only tables; no ground_truth access
-- lea_analytics_ro  SELECT on ops VIEWS only (views arrive in Phase 10); no ground_truth access
-- lea_evaluation    SELECT on ops and ground_truth

GRANT USAGE ON SCHEMA ops TO lea_app, lea_analytics_ro, lea_evaluation;
GRANT USAGE ON SCHEMA ground_truth TO lea_evaluation;

-- Default: lea_app may read and write ordinary ops tables.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ops TO lea_app;

-- Append-only tables: take UPDATE/DELETE away again (trigger is the second line of defence).
REVOKE UPDATE, DELETE ON
    ops.audit_event, ops.request_status_event, ops.approval_event, ops.approval_attempt,
    ops.reimbursement_attempt, ops.leave_balance_transaction, ops.cost_center_transaction,
    ops.request_exception
FROM lea_app;

-- idempotency_record: no DELETE for the app (UPDATE of status is required).
REVOKE DELETE ON ops.idempotency_record FROM lea_app;

-- Evaluation reads everything, writes nothing.
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO lea_evaluation;
GRANT SELECT ON ALL TABLES IN SCHEMA ground_truth TO lea_evaluation;

-- Analytics: no table grants. Migration 0003_analytics_views grants SELECT on ops.v_request,
-- ops.v_request_exception and ops.v_reimbursement only.

-- Explicitly deny ground_truth to the operational and analytics roles (defence in depth;
-- they have no USAGE on the schema, so this is belt and braces).
REVOKE ALL ON SCHEMA ground_truth FROM lea_app, lea_analytics_ro;
REVOKE ALL ON ALL TABLES IN SCHEMA ground_truth FROM lea_app, lea_analytics_ro;

-- Future tables created by the migrator inherit the same pattern.
ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO lea_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops GRANT SELECT ON TABLES TO lea_evaluation;
ALTER DEFAULT PRIVILEGES IN SCHEMA ground_truth GRANT SELECT ON TABLES TO lea_evaluation;
