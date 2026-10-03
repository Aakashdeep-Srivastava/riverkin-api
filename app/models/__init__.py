"""SQLAlchemy models.

Importing this package makes every model visible on ``Base.metadata`` so that
Alembic autogenerate and ``create_all`` see the full schema.
"""

from app.models.crew import Adoption, Checkin, Crew, CrewMember
from app.models.observation import Observation
from app.models.site import Site
from app.models.user import User
from app.models.verify import VerifyItem, Vote

__all__ = [
    "Adoption",
    "Checkin",
    "Crew",
    "CrewMember",
    "Observation",
    "Site",
    "User",
    "VerifyItem",
    "Vote",
]
