from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from support_demo.config import settings


def now() -> datetime:
    return datetime.now(UTC)


def uid() -> str:
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    status: Mapped[str] = mapped_column(String(30))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON)


class Policy(Base):
    __tablename__ = "policies"
    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    desk: Mapped[str] = mapped_column(String(20), index=True)
    text: Mapped[str] = mapped_column(Text)
    version: Mapped[str] = mapped_column(String(30))
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rules: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding_model: Mapped[str] = mapped_column(String(100))
    embedding: Mapped[list[float] | None] = mapped_column(Vector(), nullable=True)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    parent_run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"))
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"), index=True)
    desk: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    request: Mapped[dict] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    trace_id: Mapped[str] = mapped_column(String(32), default="")
    trace_context: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(40))
    actor: Mapped[str] = mapped_column(String(100), default="system")
    node: Mapped[str] = mapped_column(String(60), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Proposal(Base):
    __tablename__ = "proposals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), unique=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"))
    item_id: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[int] = mapped_column(Integer)
    amount_cents: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    citations: Mapped[list[str]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Resolution(Base):
    __tablename__ = "resolutions"
    __table_args__ = (UniqueConstraint("proposal_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    proposal_id: Mapped[str] = mapped_column(ForeignKey("proposals.id"))
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id"), index=True)
    item_id: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(30))
    amount_cents: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    owner: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class IndexConfig(Base):
    __tablename__ = "index_config"
    id: Mapped[str] = mapped_column(String(30), primary_key=True, default="policies")
    model: Mapped[str] = mapped_column(String(100))
    dimensions: Mapped[int] = mapped_column(Integer)
    threshold: Mapped[float] = mapped_column(Float, default=0.25)


engine = create_async_engine(
    settings().database_url, echo=False, hide_parameters=True, pool_pre_ping=True
)
sessions = async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def transaction() -> AsyncIterator[AsyncSession]:
    async with sessions() as session, session.begin():
        yield session
