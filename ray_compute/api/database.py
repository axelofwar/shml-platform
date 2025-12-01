"""
Database connection and session management
"""

import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator


# Read password from file if PASSWORD_FILE is set
def get_postgres_password():
    password_file = os.getenv("POSTGRES_PASSWORD_FILE")
    print(
        f"[DATABASE] POSTGRES_PASSWORD_FILE={password_file}",
        file=sys.stderr,
        flush=True,
    )

    if password_file and os.path.exists(password_file):
        with open(password_file, "r") as f:
            password = f.read().strip()
            print(
                f"[DATABASE] Loaded password from file, length: {len(password)}",
                file=sys.stderr,
                flush=True,
            )
            return password

    password = os.getenv("POSTGRES_PASSWORD", "")
    print(
        f"[DATABASE] Using POSTGRES_PASSWORD env var, length: {len(password)}",
        file=sys.stderr,
        flush=True,
    )
    return password


# Database configuration from environment
_postgres_password = get_postgres_password()
DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER', 'ray_compute')}:"
    f"{_postgres_password}@"
    f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
    f"{os.getenv('POSTGRES_PORT', '5432')}/"
    f"{os.getenv('POSTGRES_DB', 'ray_compute')}"
)

print(
    f"[DATABASE] Built DATABASE_URL for user={os.getenv('POSTGRES_USER', 'ray_compute')}, host={os.getenv('POSTGRES_HOST', 'localhost')}",
    file=sys.stderr,
    flush=True,
)

# Create engine
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,  # Verify connections before using
    pool_size=10,
    max_overflow=20,
    echo=os.getenv("DEBUG", "false").lower() == "true",
)

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """
    Dependency for getting database sessions
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
