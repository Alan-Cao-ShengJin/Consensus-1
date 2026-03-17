from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///consensus-1.db")

engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)


@contextmanager
def get_session() -> Session:
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
