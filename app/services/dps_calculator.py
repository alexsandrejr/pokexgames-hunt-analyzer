"""Estimativa do dano de um pokémon em um boss com tempo limite (funções puras).

O cálculo usa o dano médio, sem simular a luta (animações e usos inteiros ficam de fora):

* skill: ``dano ÷ recarga × tempo × aproveitamento``;
* ataque básico: ``dano ÷ turno × tempo × aproveitamento``;
* buff no básico: fração do tempo com o buff ativo × ``(multiplicador − 1)`` × dano do básico;
* buff na próxima magia: a magia que mais rende, supondo que ela é guardada para o buff.
  Ela só é reforçada na recarga mais lenta entre a magia e o buff.

O ``dano`` acima já inclui o multiplicador de efetividade, que vale 1 quando o dano medido
já a considera (ver ``DamageSource`` em ``dps_service``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.utils.formatters import format_number, format_plain


class SkillShape(Enum):
    AREA = "area"
    TARGET = "target"

    @property
    def label(self) -> str:
        return {"area": "Área", "target": "Target"}[self.value]


class SkillReach(Enum):
    MELEE = "melee"
    RANGED = "ranged"

    @property
    def label(self) -> str:
        return {"melee": "Melee", "ranged": "Ranged"}[self.value]


class Element(Enum):
    """Elementos dos golpes e dos bosses (ver ``docs/efetividade-pxg.md``)."""

    NORMAL = "normal"
    FIRE = "fire"
    WATER = "water"
    GRASS = "grass"
    ELECTRIC = "electric"
    ICE = "ice"
    FIGHTING = "fighting"
    POISON = "poison"
    GROUND = "ground"
    FLYING = "flying"
    PSYCHIC = "psychic"
    BUG = "bug"
    ROCK = "rock"
    GHOST = "ghost"
    DRAGON = "dragon"
    DARK = "dark"
    STEEL = "steel"
    FAIRY = "fairy"

    @property
    def label(self) -> str:
        return self.value.capitalize()


class EffectivenessLevel(Enum):
    """Resultado de um ataque contra o boss, como o jogo mostra (valores de PvE)."""

    SUPER_EFFECTIVE = "super_effective"
    EFFECTIVE = "effective"
    NORMAL = "normal"
    INEFFECTIVE = "ineffective"
    VERY_INEFFECTIVE = "very_ineffective"
    NULL = "null"

    @property
    def label(self) -> str:
        return {"super_effective": "Super Efetivo", "effective": "Efetivo", "normal": "Normal",
                "ineffective": "Inefetivo", "very_ineffective": "Muito Inefetivo",
                "null": "Nulo"}[self.value]

    @property
    def multiplier(self) -> float:
        return {"super_effective": 2.0, "effective": 1.75, "normal": 1.0, "ineffective": .75,
                "very_ineffective": .5, "null": 0.0}[self.value]


@dataclass(frozen=True)
class SkillSpec:
    name: str  # opcional: sem nome, a skill aparece como "Skill N"
    shape: SkillShape
    reach: SkillReach
    damage: float  # média do teste em uso; 0 = sem teste
    cooldown: float  # segundos
    efficiency: float  # fração 0–1
    element: Element | None = None
    # Skill já salva: permite editar o pokémon sem perder os testes dela.
    skill_id: int | None = field(default=None, compare=False)
    multiplier: float | None = 1.0  # efetividade; ``None`` = sem elemento (conta como 0)

    @property
    def effective_damage(self) -> float:
        return self.damage * (self.multiplier or 0)


@dataclass(frozen=True)
class BasicAttackSpec:
    damage: float  # média do teste em uso; 0 = sem teste
    efficiency: float  # fração 0–1
    element: Element | None = None
    multiplier: float | None = 1.0  # efetividade; ``None`` = sem elemento (conta como 0)

    @property
    def effective_damage(self) -> float:
        return self.damage * (self.multiplier or 0)


@dataclass(frozen=True)
class BuffSpec:
    cooldown: float  # segundos
    basic_multiplier: float = 1.0  # 1 = não afeta o ataque básico
    basic_duration: float = 0.0  # segundos
    next_spell_multiplier: float = 1.0  # 1 = não afeta a próxima magia


@dataclass(frozen=True)
class PokemonSpec:
    skills: tuple[SkillSpec, ...] = ()
    basic: BasicAttackSpec | None = None
    buff: BuffSpec | None = None


class LineKind(Enum):
    SKILL = "skill"
    BASIC = "basic"
    BUFF = "buff"


@dataclass(frozen=True)
class DamageLine:
    """Quanto uma fonte de dano soma ao total."""

    kind: LineKind
    source: str
    detail: str
    total: float


@dataclass(frozen=True)
class DamageBreakdown:
    lines: tuple[DamageLine, ...]
    total: float
    dps: float


def skill_label(skill: SkillSpec, position: int) -> str:
    """``position`` começa em 1."""
    return skill.name or f"Skill {position}"


def validate_spec(spec: PokemonSpec) -> None:
    """Lança ``ValueError`` com a primeira regra violada."""
    if not spec.skills and spec.basic is None:
        raise ValueError("Cadastre ao menos uma skill ou o ataque básico.")
    for position, skill in enumerate(spec.skills, 1):
        label = skill_label(skill, position)
        if skill.cooldown <= 0:
            raise ValueError(f"{label}: a recarga precisa ser maior que zero.")
        _validate_efficiency(skill.efficiency, label)
    if spec.basic is not None:
        _validate_efficiency(spec.basic.efficiency, "Ataque básico")
    if spec.buff is not None:
        _validate_buff(spec.buff)


def _validate_efficiency(efficiency: float, label: str) -> None:
    if not 0 <= efficiency <= 1:
        raise ValueError(f"{label}: o aproveitamento precisa estar entre 0% e 100%.")


def _validate_buff(buff: BuffSpec) -> None:
    if buff.cooldown <= 0:
        raise ValueError("Buff: a recarga precisa ser maior que zero.")
    if buff.basic_multiplier < 1 or buff.next_spell_multiplier < 1:
        raise ValueError("Buff: os multiplicadores não podem ser menores que 1.")
    if buff.basic_multiplier == 1 and buff.next_spell_multiplier == 1:
        raise ValueError("Buff: aumente ao menos um dos multiplicadores (1 = sem efeito).")
    if buff.basic_duration < 0 or (buff.basic_multiplier > 1 and buff.basic_duration == 0):
        raise ValueError("Buff: informe a duração do bônus no ataque básico.")


def calculate(spec: PokemonSpec, duration: float, basic_turn: float) -> DamageBreakdown:
    """Dano estimado em ``duration`` segundos, com um ataque básico a cada ``basic_turn``."""
    lines = [_skill_line(skill, position, duration)
             for position, skill in enumerate(spec.skills, 1)]
    if spec.basic is not None:
        lines.append(_basic_line(spec.basic, duration, basic_turn))
        if (spec.buff is not None and spec.buff.basic_multiplier > 1
                and spec.basic.effective_damage > 0):
            lines.append(_basic_buff_line(spec.basic, spec.buff, duration, basic_turn))
    if spec.buff is not None and spec.buff.next_spell_multiplier > 1:
        line = _next_spell_line(spec.skills, spec.buff, duration)
        if line is not None:
            lines.append(line)
    total = sum(line.total for line in lines)
    return DamageBreakdown(tuple(lines), total, total / duration)


def _skill_line(skill: SkillSpec, position: int, duration: float) -> DamageLine:
    detail = (f"{skill.shape.label} · {skill.reach.label} · "
              f"{_damage_text(skill.damage, skill.multiplier)} / "
              f"{format_plain(skill.cooldown)}s · {_percent(skill.efficiency)}")
    total = skill.effective_damage / skill.cooldown * duration * skill.efficiency
    return DamageLine(LineKind.SKILL, skill_label(skill, position), detail, total)


def _basic_damage(basic: BasicAttackSpec, duration: float, basic_turn: float) -> float:
    return basic.effective_damage / basic_turn * duration * basic.efficiency


def _basic_line(basic: BasicAttackSpec, duration: float, basic_turn: float) -> DamageLine:
    detail = (f"{_damage_text(basic.damage, basic.multiplier)} / {format_plain(basic_turn)}s · "
              f"{_percent(basic.efficiency)}")
    return DamageLine(LineKind.BASIC, "Ataque básico", detail,
                      _basic_damage(basic, duration, basic_turn))


def _basic_buff_line(basic: BasicAttackSpec, buff: BuffSpec, duration: float,
                     basic_turn: float) -> DamageLine:
    uptime = min(buff.basic_duration / buff.cooldown, 1.0)
    detail = (f"×{format_plain(buff.basic_multiplier)} por {format_plain(buff.basic_duration)}s "
              f"/ {format_plain(buff.cooldown)}s")
    total = _basic_damage(basic, duration, basic_turn) * uptime * (buff.basic_multiplier - 1)
    return DamageLine(LineKind.BUFF, "Buff: ataque básico", detail, total)


def _next_spell_line(skills: tuple[SkillSpec, ...], buff: BuffSpec,
                     duration: float) -> DamageLine | None:
    """A magia com o maior ganho; ``None`` se nenhuma ganhar dano."""
    best: DamageLine | None = None
    for position, skill in enumerate(skills, 1):
        interval = max(skill.cooldown, buff.cooldown)
        total = (skill.effective_damage * skill.efficiency * (buff.next_spell_multiplier - 1)
                 * duration / interval)
        if total > 0 and (best is None or total > best.total):
            detail = (f"{_damage_text(skill.damage, skill.multiplier)} "
                      f"×{format_plain(buff.next_spell_multiplier)} / "
                      f"{format_plain(interval)}s · {_percent(skill.efficiency)}")
            source = f"Buff: próxima magia ({skill_label(skill, position)})"
            best = DamageLine(LineKind.BUFF, source, detail, total)
    return best


def _damage_text(damage: float, multiplier: float | None = 1.0) -> str:
    if damage <= 0:
        return "sem teste"
    if multiplier is None:
        return "sem elemento"
    if multiplier == 1:
        return format_number(damage)
    return f"{format_number(damage)} ×{format_plain(multiplier)}"


def _percent(fraction: float) -> str:
    return f"{format_plain(round(fraction * 100, 2))}%"
