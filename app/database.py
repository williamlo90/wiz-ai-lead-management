from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, connect_args=connect_args)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
        )

    def create_tables(self) -> None:
        # Importing registers model metadata before create_all runs.
        from app import models  # noqa: F401

        Base.metadata.create_all(self.engine)

    def session(self) -> Generator[Session, None, None]:
        with self.session_factory() as session:
            yield session

