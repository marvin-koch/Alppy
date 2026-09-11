"""Declarative base and the mixins every table in Alppy carries."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, MetaData, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# Explicit naming so Alembic autogenerate produces stable constraint names.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


class TimestampMixin:
    """Every table has created_at and updated_at. No exceptions."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class SchoolScopedMixin:
    """Tenancy from the first migration, not bolted on later.

    Every scoped query filters on school_id; the dependency in
    ``alppy.api.deps`` supplies it from the session so a handler cannot
    accidentally read across tenants.
    """

    #: Whether this table needs a standalone index on ``school_id``.
    #:
    #: True everywhere by default, because a scoped read filters on it and
    #: `0024`'s RLS policy compares it on every single statement — an unindexed
    #: `school_id` is a sequential scan per policy evaluation, which is the
    #: worst possible place to find one.
    #:
    #: Set False on a model whose `school_id` is already the LEADING column of
    #: a composite index, where the standalone one is dead weight a btree
    #: prefix already answers: it is maintained on every insert and chosen by
    #: the planner never (database audit M2). The model that sets it says which
    #: index covers it, so the claim can be checked by reading.
    __school_id_index__: bool = True

    @property
    def _school_fk(self) -> str:  # pragma: no cover - documentation helper
        return "school.id"

    @declared_attr
    def school_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805 - declared_attr takes the class
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("school.id", ondelete="CASCADE"),
            nullable=False,
            index=cls.__school_id_index__,
        )
