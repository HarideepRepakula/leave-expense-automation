"""Enterprise Leave and Expense Approval Automation System.

Package layout (docs/03 section 6):
    src.common      shared kernel: enums, ID patterns, settings (clock and RNG arrive in Phase 3)
    src.models      SQLAlchemy models for the ops and ground_truth schemas
    src.services    business rules (Phase 5+)
    src.data        synthetic data generator (Phase 3+)
    src.reference   independent ground-truth oracle (Phase 4)
    src.validation  data-quality validators and detectors (Phase 4)
    src.evaluation  the only runtime package allowed to read ground truth (Phase 11)
    src.api         FastAPI (Phase 9)
    src.analytics   read-only queries (Phase 10)
    src.dashboard   Streamlit (Phase 10)
"""
