"""Modelos SQLAlchemy.

Cada importação de JSON vira uma ``HuntSession`` (registro histórico permanente),
com seus inimigos, drops e supplies em tabelas relacionadas. O JSON original é
sempre preservado em ``raw_json`` para que campos futuros do Analyzer não se percam.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class HuntSession(Base):
    __tablename__ = "hunt_sessions"
    __table_args__ = (
        # Usado na detecção de duplicidade.
        Index("ix_hunt_sessions_identity", "session_id", "player", "start_datetime"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    session_id: Mapped[int | None] = mapped_column(index=True)
    player: Mapped[str | None] = mapped_column(String(200), index=True)
    start_datetime: Mapped[datetime | None] = mapped_column(index=True)
    duration_seconds: Mapped[int | None]
    paused_seconds: Mapped[int | None]
    status: Mapped[str | None] = mapped_column(String(50))
    session_type: Mapped[str | None] = mapped_column(String(50))

    kills: Mapped[int | None]
    kills_per_hour: Mapped[float | None]
    rare_kills: Mapped[int | None]
    rare_kills_per_hour: Mapped[float | None]

    experience: Mapped[int | None]
    experience_per_hour: Mapped[float | None]

    profit: Mapped[int | None]
    profit_per_hour: Mapped[float | None]
    supplies: Mapped[int | None]
    supplies_per_hour: Mapped[float | None]
    raw_gains: Mapped[int | None]
    raw_gains_per_hour: Mapped[float | None]

    damage_dealt: Mapped[int | None]
    damage_dealt_per_second: Mapped[float | None]
    damage_taken: Mapped[int | None]
    damage_taken_per_second: Mapped[float | None]

    time_to_next_level: Mapped[str | None] = mapped_column(String(50))
    time_to_next_level_seconds: Mapped[int | None]

    source_file: Mapped[str | None] = mapped_column(String(500))
    # SHA-256 do conteúdo JSON canônico: identifica arquivos idênticos.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    raw_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    enemies: Mapped[list[EnemyDefeated]] = relationship(
        back_populates="hunt", cascade="all, delete-orphan", passive_deletes=True
    )
    drops: Mapped[list[Drop]] = relationship(
        back_populates="hunt", cascade="all, delete-orphan", passive_deletes=True
    )
    supplies_used: Mapped[list[Supply]] = relationship(
        back_populates="hunt", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return (
            f"HuntSession(id={self.id}, session_id={self.session_id}, "
            f"player={self.player!r}, start={self.start_datetime})"
        )


class EnemyDefeated(Base):
    __tablename__ = "enemies_defeated"

    id: Mapped[int] = mapped_column(primary_key=True)
    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    enemy: Mapped[str] = mapped_column(String(200), index=True)
    player: Mapped[str | None] = mapped_column(String(200))
    count: Mapped[int] = mapped_column(default=0)
    rare: Mapped[bool | None]
    ignored: Mapped[bool | None]

    hunt: Mapped[HuntSession] = relationship(back_populates="enemies")


class ItemEntryMixin:
    """Colunas comuns a Drops e Supplies."""

    id: Mapped[int] = mapped_column(primary_key=True)
    item: Mapped[str] = mapped_column(String(200), index=True)
    count: Mapped[int] = mapped_column(default=0)
    unit_price: Mapped[float | None]
    total_price: Mapped[int | None]
    player: Mapped[str | None] = mapped_column(String(200))
    ignored: Mapped[bool | None]


class Drop(ItemEntryMixin, Base):
    __tablename__ = "drops"

    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    hunt: Mapped[HuntSession] = relationship(back_populates="drops")


class Supply(ItemEntryMixin, Base):
    __tablename__ = "supplies"

    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    hunt: Mapped[HuntSession] = relationship(back_populates="supplies_used")
