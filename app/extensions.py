"""Flask extension singletons.

Kept in their own module so blueprints and services can import them without
creating a circular dependency back onto the application factory.
"""

from __future__ import annotations

import sqlite3

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

db = SQLAlchemy()
migrate = Migrate()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


@event.listens_for(Engine, "connect")
def _enable_sqlite_foreign_keys(dbapi_connection, connection_record):
    """SQLite ignores foreign keys unless this pragma is set per connection.

    Without it, ON DELETE CASCADE is silently a no-op: deleting an account left
    every conversation, message and mood entry orphaned in the database while
    the UI reported the data had been erased. That is a broken right-to-erasure
    promise, not just an integrity nit. Postgres enforces FKs natively and is
    unaffected by this hook.
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
