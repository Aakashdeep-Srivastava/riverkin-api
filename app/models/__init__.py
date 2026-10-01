"""SQLAlchemy models.

Importing this package makes every model visible on ``Base.metadata`` so that
Alembic autogenerate and ``create_all`` see the full schema.
"""

from app.models.observation import Observation
from app.models.site import Site

__all__ = ["Observation", "Site"]
