from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Company, Document, Theme


def get_or_create_company(session: Session, ticker: str, name: str | None = None) -> Company:
    obj = session.get(Company, ticker)
    if obj:
        return obj
    obj = Company(ticker=ticker, name=name or ticker)
    session.add(obj)
    session.flush()
    return obj


def get_or_create_theme(session: Session, theme_name: str) -> Theme:
    stmt = select(Theme).where(Theme.theme_name == theme_name)
    obj = session.scalar(stmt)
    if obj:
        return obj
    obj = Theme(theme_name=theme_name)
    session.add(obj)
    session.flush()
    return obj


def create_document(session: Session, **kwargs) -> Document:
    doc = Document(**kwargs)
    session.add(doc)
    session.flush()
    return doc