from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from .config import settings


class Base(DeclarativeBase):
    pass


engine = create_engine(
    settings().database_url,
    pool_pre_ping=True,
    **(
        {"connect_args": {"check_same_thread": False}}
        if settings().database_url.startswith("sqlite")
        else {}
    ),
)
if settings().database_url.startswith("sqlite"):

    @event.listens_for(engine, "connect")
    def sqlite_fk(dbapi, _):
        dbapi.execute("PRAGMA foreign_keys=ON")


Session = sessionmaker(engine, expire_on_commit=False)


def db_session():
    with Session() as db:
        yield db
