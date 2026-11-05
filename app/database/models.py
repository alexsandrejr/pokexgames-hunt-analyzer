"""Modelos SQLAlchemy.

Cada importação de JSON vira uma ``HuntSession`` (registro histórico permanente),
com seus inimigos, drops e supplies em tabelas relacionadas. A ``category`` separa
Hunts comuns das sessões de boss (ver ``app/services/categories.py``). O JSON original é
sempre preservado em ``raw_json`` para que campos futuros do Analyzer não se percam.

``ItemPrice`` guarda os preços personalizados dos itens (ver ``price_service``).
``ChatReward`` guarda as mensagens "Você recebeu:" adicionadas a uma sessão; os itens
delas viram ``Drop`` ligados à mensagem (ver ``chat_rewards``).

As tabelas ``dps_*`` são da página DPS (ver ``dps_service``) e não têm relação com as
sessões importadas: os bosses de lá têm só nome e tempo limite.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Column, ForeignKey, Index, String, Table, Text
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
    # Valor de ``Category``: "hunt", "rift", "boss_red", "boss_blue" ou "terror".
    category: Mapped[str] = mapped_column(String(20), default="hunt", server_default="hunt",
                                          index=True)

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
    chat_rewards: Mapped[list[ChatReward]] = relationship(
        back_populates="hunt", cascade="all, delete-orphan", passive_deletes=True,
        order_by="ChatReward.id",
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
    # Preço em vigor: o do Analyzer ou o da tabela de preços personalizados.
    unit_price: Mapped[float | None]
    total_price: Mapped[int | None]
    # Preço exportado pelo Analyzer, restaurado quando o preço personalizado é removido.
    original_unit_price: Mapped[float | None]
    original_total_price: Mapped[int | None]
    player: Mapped[str | None] = mapped_column(String(200))
    ignored: Mapped[bool | None]


class Drop(ItemEntryMixin, Base):
    __tablename__ = "drops"

    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    # Preenchido nos drops vindos de uma mensagem do chat (fora do JSON do Analyzer).
    chat_reward_id: Mapped[int | None] = mapped_column(
        ForeignKey("chat_rewards.id", ondelete="CASCADE"), index=True
    )
    hunt: Mapped[HuntSession] = relationship(back_populates="drops")
    chat_reward: Mapped[ChatReward | None] = relationship(back_populates="drops")

    @property
    def from_chat(self) -> bool:
        return self.chat_reward_id is not None


class Supply(ItemEntryMixin, Base):
    __tablename__ = "supplies"

    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    hunt: Mapped[HuntSession] = relationship(back_populates="supplies_used")


class ItemPrice(Base):
    """Preço unitário personalizado de um item, válido para todas as Hunts."""

    __tablename__ = "item_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Nome em minúsculas, usado para casar com drops e supplies.
    key: Mapped[str] = mapped_column(String(200), unique=True)
    item: Mapped[str] = mapped_column(String(200))  # nome como exibido
    unit_price: Mapped[float]
    updated_at: Mapped[datetime] = mapped_column(default=datetime.now, onupdate=datetime.now)


class ChatReward(Base):
    """Mensagens "Você recebeu:" coladas para uma sessão (itens que o JSON não traz)."""

    __tablename__ = "chat_rewards"

    id: Mapped[int] = mapped_column(primary_key=True)
    hunt_id: Mapped[int] = mapped_column(
        ForeignKey("hunt_sessions.id", ondelete="CASCADE"), index=True
    )
    # Uma mensagem por linha, como foram coladas (sem espaços repetidos).
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(default=datetime.now)

    hunt: Mapped[HuntSession] = relationship(back_populates="chat_rewards")
    drops: Mapped[list[Drop]] = relationship(back_populates="chat_reward")

    @property
    def messages(self) -> list[str]:
        return [line for line in self.text.splitlines() if line.strip()]


dps_boss_pokemons = Table(
    "dps_boss_pokemons",
    Base.metadata,
    Column("boss_id", ForeignKey("dps_bosses.id", ondelete="CASCADE"), primary_key=True),
    Column("pokemon_id", ForeignKey("dps_pokemons.id", ondelete="CASCADE"), primary_key=True,
           index=True),
)


class DpsBoss(Base):
    __tablename__ = "dps_bosses"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    time_limit_seconds: Mapped[int]
    # Dummy de onde vem o dano no ranking: "neutral" ou valor de ``Element``.
    dummy: Mapped[str] = mapped_column(String(20), default="neutral", server_default="neutral")
    # Valor de ``DamageSource``: como o ranking deste boss calcula o dano.
    damage_source: Mapped[str] = mapped_column(String(20), default="dummy", server_default="dummy")
    # Só informativos: o que entra na conta é ``effectiveness``. Valores de ``Element``.
    element_1: Mapped[str | None] = mapped_column(String(20))
    element_2: Mapped[str | None] = mapped_column(String(20))

    pokemons: Mapped[list[DpsPokemon]] = relationship(
        secondary=dps_boss_pokemons, back_populates="bosses", passive_deletes=True
    )
    effectiveness: Mapped[list[DpsBossEffectiveness]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True,
    )


class DpsBossEffectiveness(Base):
    """Efetividade de um elemento de ataque contra o boss; sem linha, o ataque é Normal."""

    __tablename__ = "dps_boss_effectiveness"

    boss_id: Mapped[int] = mapped_column(
        ForeignKey("dps_bosses.id", ondelete="CASCADE"), primary_key=True
    )
    element: Mapped[str] = mapped_column(String(20), primary_key=True)  # valor de ``Element``
    level: Mapped[str] = mapped_column(String(20))  # valor de ``EffectivenessLevel``


class DpsPokemon(Base):
    __tablename__ = "dps_pokemons"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    note: Mapped[str] = mapped_column(Text, default="")

    # Sem aproveitamento: o pokémon não tem ataque básico.
    basic_efficiency: Mapped[float | None]
    basic_element: Mapped[str | None] = mapped_column(String(20))  # valor de ``Element``

    # Sem recarga: o pokémon não tem buff.
    buff_cooldown: Mapped[float | None]
    buff_basic_multiplier: Mapped[float | None]
    buff_basic_duration: Mapped[float | None]
    buff_next_spell_multiplier: Mapped[float | None]

    skills: Mapped[list[DpsSkill]] = relationship(
        back_populates="pokemon", cascade="all, delete-orphan", passive_deletes=True,
        order_by="DpsSkill.position",
    )
    bosses: Mapped[list[DpsBoss]] = relationship(
        secondary=dps_boss_pokemons, back_populates="pokemons", passive_deletes=True
    )
    damage_tests: Mapped[list[DpsDamageTest]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True, order_by="DpsDamageTest.id",
    )


class DpsSkill(Base):
    __tablename__ = "dps_skills"

    id: Mapped[int] = mapped_column(primary_key=True)
    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("dps_pokemons.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int]
    name: Mapped[str] = mapped_column(String(200), default="")
    shape: Mapped[str] = mapped_column(String(20))  # valor de ``SkillShape``
    reach: Mapped[str] = mapped_column(String(20))  # valor de ``SkillReach``
    cooldown: Mapped[float]
    efficiency: Mapped[float]  # fração 0–1
    element: Mapped[str | None] = mapped_column(String(20))  # valor de ``Element``

    pokemon: Mapped[DpsPokemon] = relationship(back_populates="skills")


class DpsDamageTest(Base):
    """Até 3 danos medidos em um dummy ou boss, para uma skill ou para o ataque básico."""

    __tablename__ = "dps_damage_tests"

    id: Mapped[int] = mapped_column(primary_key=True)
    pokemon_id: Mapped[int] = mapped_column(
        ForeignKey("dps_pokemons.id", ondelete="CASCADE"), index=True
    )
    # Sem skill: o teste é do ataque básico.
    skill_id: Mapped[int | None] = mapped_column(
        ForeignKey("dps_skills.id", ondelete="CASCADE"), index=True
    )
    # "neutral", valor de ``Element`` ou "boss" (teste dentro do boss ``boss_id``).
    dummy: Mapped[str] = mapped_column(String(20))
    boss_id: Mapped[int | None] = mapped_column(
        ForeignKey("dps_bosses.id", ondelete="CASCADE"), index=True
    )
    damage_1: Mapped[int | None]
    damage_2: Mapped[int | None]
    damage_3: Mapped[int | None]
    # Sem data de cadastro: o teste é anterior ao registro de datas.
    created_at: Mapped[datetime | None]
    # Sem data de modificação: os danos nunca mudaram depois do cadastro.
    updated_at: Mapped[datetime | None]


class DpsSettings(Base):
    """Linha única com os ajustes da página DPS (ficam nos backups, junto com os dados)."""

    __tablename__ = "dps_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    basic_turn_seconds: Mapped[float]
    target_melee_efficiency: Mapped[float]
    default_efficiency: Mapped[float]
    basic_efficiency: Mapped[float]
    last_boss_id: Mapped[int | None] = mapped_column(
        ForeignKey("dps_bosses.id", ondelete="SET NULL")
    )
