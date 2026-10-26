-- Integrity triggers for the ops schema (docs/04 section 5, docs/06 section 7.3).
-- Applied by Alembic migration 0001 after the tables exist. Idempotent: safe to re-run.
--
-- Documented limit (amendment F4): a superuser or the lea_migrator owner can drop these triggers.
-- They protect against application defects and ordinary roles, not against a DBA.

SET search_path TO ops, public;

-- 1. Append-only tables: block UPDATE and DELETE outright.
CREATE OR REPLACE FUNCTION ops.fn_block_update_delete() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'table ops.% is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'audit_event', 'request_status_event', 'approval_event', 'approval_attempt',
        'reimbursement_attempt', 'leave_balance_transaction', 'cost_center_transaction',
        'request_exception'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_append_only ON ops.%I', t);
        EXECUTE format(
            'CREATE TRIGGER trg_append_only BEFORE UPDATE OR DELETE ON ops.%I
             FOR EACH ROW EXECUTE FUNCTION ops.fn_block_update_delete()', t);
    END LOOP;
END
$$;

-- 2. Primary keys are immutable on every ops table (spec section 8).
--    Generic: TG_ARGV[0] is the PK column name; composite PKs pass several names.
CREATE OR REPLACE FUNCTION ops.fn_block_pk_update() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE
    col text;
    old_j jsonb := to_jsonb(OLD);
    new_j jsonb := to_jsonb(NEW);
BEGIN
    FOREACH col IN ARRAY TG_ARGV LOOP
        IF (old_j ->> col) IS DISTINCT FROM (new_j ->> col) THEN
            RAISE EXCEPTION 'primary key column %.% is immutable', TG_TABLE_NAME, col
                USING ERRCODE = 'integrity_constraint_violation';
        END IF;
    END LOOP;
    RETURN NEW;
END;
$$;

DO $$
DECLARE r record;
BEGIN
    FOR r IN
        SELECT c.conrelid::regclass AS tbl,
               c.conrelid::regclass::text AS tbl_text,
               string_agg(quote_literal(a.attname), ', ' ORDER BY a.attnum) AS pk_cols
        FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY (c.conkey)
        WHERE c.contype = 'p' AND n.nspname = 'ops'
        GROUP BY c.conrelid
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_pk_immutable ON %s', r.tbl);
        EXECUTE format(
            'CREATE TRIGGER trg_pk_immutable BEFORE UPDATE ON %s
             FOR EACH ROW EXECUTE FUNCTION ops.fn_block_pk_update(%s)', r.tbl, r.pk_cols);
    END LOOP;
END
$$;

-- 3. Decided approval steps are frozen (spec 7.10, 14.3).
CREATE OR REPLACE FUNCTION ops.fn_block_decided_step_update() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.step_status <> 'PENDING' THEN
        RAISE EXCEPTION 'approval_step % is % and cannot be modified', OLD.approval_step_id, OLD.step_status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_decided_step_frozen ON ops.approval_step;
CREATE TRIGGER trg_decided_step_frozen BEFORE UPDATE ON ops.approval_step
    FOR EACH ROW EXECUTE FUNCTION ops.fn_block_decided_step_update();

-- 4. No approval step may be assigned to the requester (spec 4.2, 13.3; acceptance criterion 10).
--    Blocked attempts are recorded in approval_attempt by the service; this is the last line of defence.
CREATE OR REPLACE FUNCTION ops.fn_block_self_approval_step() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE requester text;
BEGIN
    IF NEW.approver_employee_id IS NULL THEN
        RETURN NEW;
    END IF;
    IF NEW.leave_request_id IS NOT NULL THEN
        SELECT employee_id INTO requester FROM ops.leave_request WHERE leave_request_id = NEW.leave_request_id;
    ELSE
        SELECT employee_id INTO requester FROM ops.expense_claim WHERE expense_claim_id = NEW.expense_claim_id;
    END IF;
    IF requester = NEW.approver_employee_id THEN
        RAISE EXCEPTION 'self-approval: approver % is the requester of %',
            NEW.approver_employee_id, COALESCE(NEW.leave_request_id, NEW.expense_claim_id)
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_no_self_approval ON ops.approval_step;
CREATE TRIGGER trg_no_self_approval BEFORE INSERT OR UPDATE ON ops.approval_step
    FOR EACH ROW EXECUTE FUNCTION ops.fn_block_self_approval_step();

-- 5. Reimbursement only for an APPROVED claim, for the claim's employee, for the approved amount
--    (spec 7.11, 10 stage 6; acceptance criterion 14).
CREATE OR REPLACE FUNCTION ops.fn_check_reimbursement_eligibility() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record;
BEGIN
    SELECT employee_id, workflow_status, approved_amount, currency
      INTO c FROM ops.expense_claim WHERE expense_claim_id = NEW.expense_claim_id;
    IF c.workflow_status <> 'APPROVED' THEN
        RAISE EXCEPTION 'reimbursement for claim % refused: claim status is %', NEW.expense_claim_id, c.workflow_status
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF c.employee_id <> NEW.employee_id THEN
        RAISE EXCEPTION 'reimbursement employee % does not match claim employee %', NEW.employee_id, c.employee_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF c.approved_amount IS NULL OR c.approved_amount <> NEW.approved_amount THEN
        RAISE EXCEPTION 'reimbursement amount % does not match claim approved_amount %', NEW.approved_amount, c.approved_amount
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF c.currency <> NEW.currency THEN
        RAISE EXCEPTION 'reimbursement currency % does not match claim currency %', NEW.currency, c.currency
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_reimbursement_eligibility ON ops.reimbursement;
CREATE TRIGGER trg_reimbursement_eligibility BEFORE INSERT OR UPDATE ON ops.reimbursement
    FOR EACH ROW EXECUTE FUNCTION ops.fn_check_reimbursement_eligibility();

-- 6. idempotency_record: never deleted; only status, response_hash, completed_at and the two
--    request FKs may change after insert (IN_PROGRESS -> COMPLETED / FAILED).
CREATE OR REPLACE FUNCTION ops.fn_idempotency_update_guard() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'idempotency_record rows cannot be deleted' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    IF OLD.actor_user_id <> NEW.actor_user_id OR OLD.idempotency_key <> NEW.idempotency_key
       OR OLD.operation <> NEW.operation OR OLD.request_hash <> NEW.request_hash
       OR OLD.created_at <> NEW.created_at THEN
        RAISE EXCEPTION 'idempotency_record key fields are immutable' USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_idempotency_guard ON ops.idempotency_record;
CREATE TRIGGER trg_idempotency_guard BEFORE UPDATE OR DELETE ON ops.idempotency_record
    FOR EACH ROW EXECUTE FUNCTION ops.fn_idempotency_update_guard();

-- 7. Leave balance ledger: USAGE / USAGE_REVERSAL must reference a request; other types must not.
--    (Expressed as a CHECK in the model; kept here as documentation of intent.)

RESET search_path;
