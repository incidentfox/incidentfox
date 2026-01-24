import os
import socket
from contextlib import contextmanager
from typing import Iterator, Optional

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from src.core.dotenv import load_dotenv


def get_database_url() -> str:
    """
    Resolve DB URL for runtime.

    Local dev:
    - If DATABASE_URL_TUNNEL is set and localhost tunnel port is reachable, prefer it.
    - Otherwise use DATABASE_URL.
    """
    # Developer convenience: auto-load .env if present.
    # Tests/containers may disable this to avoid surprising env mutation.
    if os.getenv("DOTENV_AUTOLOAD", "1") != "0":
        load_dotenv()

    tunnel_url = os.getenv("DATABASE_URL_TUNNEL")
    if tunnel_url and _is_local_tunnel_up(tunnel_url):
        return tunnel_url

    url = os.getenv("DATABASE_URL")
    if url:
        return url

    # Production-friendly fallback: allow assembling DATABASE_URL from discrete env vars,
    # so ECS/K8s can inject Secrets Manager JSON keys without putting full DSN into state.
    assembled = _assemble_database_url_from_components()
    if assembled:
        return assembled

    raise RuntimeError(
        "DATABASE_URL is not set (and DATABASE_URL_TUNNEL is not usable)"
    )


def _assemble_database_url_from_components() -> Optional[str]:
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT") or "5432"
    name = os.getenv("DB_NAME")
    user = os.getenv("DB_USERNAME")
    password = os.getenv("DB_PASSWORD")
    sslmode = os.getenv("DB_SSLMODE") or "require"

    if not (host and name and user and password):
        return None

    from urllib.parse import quote_plus

    pw = quote_plus(password)
    return f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{name}?sslmode={sslmode}"


def _is_local_tunnel_up(url: str) -> bool:
    try:
        # We only auto-select tunnel if it points to localhost.
        from urllib.parse import urlparse

        u = urlparse(url)
        host = u.hostname or ""
        port = int(u.port or 5432)
        if host not in ("127.0.0.1", "localhost"):
            return False

        s = socket.socket()
        s.settimeout(0.2)
        s.connect(("127.0.0.1", port))
        s.close()
        return True
    except Exception:
        return False


def make_engine():
    return create_engine(
        get_database_url(),
        pool_pre_ping=True,
        pool_size=20,
        max_overflow=40,
        pool_recycle=3600,
        connect_args={
            "connect_timeout": 10,
            "options": "-c statement_timeout=30000",  # 30 second query timeout
        },
    )


_SessionLocal: Optional[sessionmaker] = None


def get_session_maker() -> sessionmaker:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(
            autocommit=False, autoflush=False, bind=make_engine()
        )
    return _SessionLocal


@contextmanager
def db_session() -> Iterator[Session]:
    session = get_session_maker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency for database sessions."""
    session = get_session_maker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
