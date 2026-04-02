"""
Declarative base import that also registers all models with SQLAlchemy metadata.
"""
from app.db.session import Base  # noqa: F401
from app.db.models import *  # noqa: F401,F403

__all__ = ["Base"]
