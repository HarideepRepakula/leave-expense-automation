"""SQLAlchemy models. Importing this package registers every table on the two metadata objects.

ops schema          -> Base.metadata          (operational tables)
ground_truth schema -> GroundTruthBase.metadata (read only by src.evaluation, written by the generator's
                                                 ground-truth stage and the Alembic migration)
"""
from src.models.base import Base, GroundTruthBase  # noqa: F401
from src.models import master, policies, leave, expenses, approvals, reimbursement, audit, security  # noqa: F401
from src.models import ground_truth  # noqa: F401

__all__ = ["Base", "GroundTruthBase"]
