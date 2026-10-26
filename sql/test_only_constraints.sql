-- Applied ONLY to the test database (amendment A3). Requires the btree_gist extension,
-- which sql/init/02_test_database.sql enables in lea_test.
--
-- In the dev/main dataset, seeded overlapping APPROVED leave anomalies must be allowed to exist
-- so the detector can find them; therefore this constraint is never applied to lea_dev.

CREATE EXTENSION IF NOT EXISTS btree_gist;

ALTER TABLE ops.leave_request DROP CONSTRAINT IF EXISTS excl_no_overlapping_approved_leave;

ALTER TABLE ops.leave_request
    ADD CONSTRAINT excl_no_overlapping_approved_leave
    EXCLUDE USING gist (
        employee_id WITH =,
        daterange(start_date, end_date, '[]') WITH &&
    )
    WHERE (workflow_status = 'APPROVED');
