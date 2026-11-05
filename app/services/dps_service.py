"""Cadastro de bosses e pokémons da página DPS e o ranking de cada boss.

Cada boss tem um tempo limite, a origem do dano no ranking e os pokémons marcados para ele.
O dano não é digitado no cadastro: vem da média dos testes, em cada skill e no ataque básico,
feitos no dummy ou dentro do boss, conforme a ``DamageSource`` dele. A conta em si fica em
``dps_calculator``.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from enum import Enum

from app.database.database import Database
from app.database.models import (
    DpsBoss,
    DpsBossEffectiveness,
    DpsDamageTest,
    DpsPokemon,
    DpsSkill,
)
from app.database.models import DpsSettings as DpsSettingsRow
from app.database.repositories import DpsRepository
from app.services.dps_calculator import (
    BasicAttackSpec,
    BuffSpec,
    DamageBreakdown,
    EffectivenessLevel,
    Element,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
    calculate,
    skill_label,
    validate_spec,
)

DEFAULT_BASIC_TURN = 2.5
DEFAULT_TARGET_MELEE_EFFICIENCY = 0.75
DEFAULT_EFFICIENCY = 1.0
DEFAULT_BASIC_EFFICIENCY = 0.75

NEUTRAL_DUMMY = "neutral"
BOSS_TEST_DUMMY = "boss"  # coluna ``dummy`` de um teste feito dentro de um boss
MAX_BOSS_ELEMENTS = 2
# (valor gravado, nome exibido) dos dummies do jogo: o Neutro e o Normal são diferentes.
DUMMY_OPTIONS: tuple[tuple[str, str], ...] = (
    (NEUTRAL_DUMMY, "Neutro"),
    *((element.value, element.label) for element in Element),
)
DAMAGES_PER_TEST = 3


def dummy_label(dummy: str) -> str:
    return dict(DUMMY_OPTIONS).get(dummy, dummy)


class DamageSource(Enum):
    """De onde vem o dano de cada skill no ranking de um boss."""

    EFFECTIVENESS = "effectiveness"  # teste no dummy Neutro × efetividade contra o boss
    DUMMY = "dummy"  # teste no dummy escolhido no boss
    REAL = "real"  # teste dentro do boss, que já inclui a efetividade

    @property
    def label(self) -> str:
        return {"effectiveness": "Efetividade", "dummy": "Dummy", "real": "Dano real"}[self.value]


@dataclass(frozen=True)
class DpsSettings:
    basic_turn_seconds: float = DEFAULT_BASIC_TURN
    target_melee_efficiency: float = DEFAULT_TARGET_MELEE_EFFICIENCY
    default_efficiency: float = DEFAULT_EFFICIENCY
    basic_efficiency: float = DEFAULT_BASIC_EFFICIENCY
    last_boss_id: int | None = None

    def suggested_efficiency(self, shape: SkillShape, reach: SkillReach) -> float:
        """Aproveitamento sugerido: target melee exige achar um espaço colado no boss."""
        if shape is SkillShape.TARGET and reach is SkillReach.MELEE:
            return self.target_melee_efficiency
        return self.default_efficiency


@dataclass(frozen=True)
class BossData:
    id: int
    name: str
    time_limit_seconds: int
    pokemon_ids: frozenset[int]
    dummy: str = NEUTRAL_DUMMY
    damage_source: DamageSource = DamageSource.DUMMY
    elements: tuple[Element, ...] = ()  # só informativos: a conta usa ``effectiveness``
    # Só o que difere de Normal, como o jogo lista contra aquele boss.
    effectiveness: Mapping[Element, EffectivenessLevel] = field(default_factory=dict)

    @property
    def base_dummy(self) -> str:
        """Dummy de onde vem o dano; na origem Efetividade, é sempre o Neutro."""
        return NEUTRAL_DUMMY if self.damage_source is DamageSource.EFFECTIVENESS else self.dummy

    def multiplier(self, element: Element | None) -> float | None:
        """Multiplicador do elemento contra o boss; ``None`` se não houver elemento."""
        if element is None:
            return None
        return self.effectiveness.get(element, EffectivenessLevel.NORMAL).multiplier


@dataclass(frozen=True)
class DamageTest:
    """Danos medidos em um dummy ou boss; ``None`` é um dano ainda não preenchido."""

    dummy: str
    damages: tuple[int | None, ...]
    boss_id: int | None = None  # preenchido só em testes dentro de um boss
    # Registro, fora da comparação: quem define as datas é o ``save_damage_tests``.
    created_at: datetime | None = field(default=None, compare=False)
    updated_at: datetime | None = field(default=None, compare=False)

    @classmethod
    def in_boss(cls, boss_id: int, damages: tuple[int | None, ...]) -> DamageTest:
        return cls(BOSS_TEST_DUMMY, damages, boss_id)

    @property
    def average(self) -> float | None:
        return damage_average(self.damages)


def damage_average(damages: Iterable[float | None]) -> float | None:
    """Média só dos danos preenchidos; ``None`` se não houver nenhum."""
    filled = [damage for damage in damages if damage is not None]
    return sum(filled) / len(filled) if filled else None


def validate_tests(tests: Iterable[DamageTest],
                   boss_names: Mapping[int, str] | None = None) -> None:
    dummies = dict(DUMMY_OPTIONS)
    boss_names = boss_names or {}
    seen: set[tuple[str, int | None]] = set()
    for test in tests:
        if test.boss_id is not None:
            if test.boss_id not in boss_names:
                raise ValueError("Boss não encontrado.")
            kind, label = "Boss", boss_names[test.boss_id]
        elif test.dummy in dummies:
            kind, label = "Dummy", dummies[test.dummy]
        else:
            raise ValueError("Escolha um dummy da lista.")
        key = (test.dummy, test.boss_id)
        if key in seen:
            raise ValueError(f"O {kind.lower()} {label} aparece em mais de um teste.")
        seen.add(key)
        filled = [damage for damage in test.damages if damage is not None]
        if not filled or len(test.damages) > DAMAGES_PER_TEST:
            raise ValueError(f"{kind} {label}: informe de 1 a {DAMAGES_PER_TEST} danos.")
        if any(damage <= 0 for damage in filled):
            raise ValueError(f"{kind} {label}: o dano precisa ser maior que zero.")


def validate_boss_profile(elements: Sequence[Element]) -> None:
    if len(elements) > MAX_BOSS_ELEMENTS:
        raise ValueError(f"Um boss tem no máximo {MAX_BOSS_ELEMENTS} elementos.")
    if len(set(elements)) != len(elements):
        raise ValueError("Escolha dois elementos diferentes para o boss.")


@dataclass(frozen=True)
class PokemonData:
    id: int
    name: str
    note: str
    spec: PokemonSpec  # dano zerado: ele depende do dummy (ver ``spec_for_dummy``)
    boss_ids: frozenset[int]
    # Por ``skill_id``; a chave ``None`` é o ataque básico.
    tests: dict[int | None, tuple[DamageTest, ...]]

    def damage_on(self, skill_id: int | None, dummy: str) -> float | None:
        """Média do teste no dummy; ``None`` se a skill não foi testada nele."""
        return next((test.average for test in self.tests.get(skill_id, ())
                     if test.dummy == dummy), None)

    def damage_in_boss(self, skill_id: int | None, boss_id: int) -> float | None:
        """Média do teste dentro do boss; ``None`` se a skill não foi testada nele."""
        return next((test.average for test in self.tests.get(skill_id, ())
                     if test.boss_id == boss_id), None)


def spec_for_dummy(pokemon: PokemonData, dummy: str) -> tuple[PokemonSpec, tuple[str, ...]]:
    """A ficha com o dano medido no dummy, e os nomes do que não foi testado nele."""
    return _spec_with_damages(pokemon, lambda skill_id: pokemon.damage_on(skill_id, dummy))


def spec_for_boss(pokemon: PokemonData,
                  boss: BossData) -> tuple[PokemonSpec, tuple[str, ...], tuple[str, ...]]:
    """A ficha com o dano da origem do boss, o que está sem teste e o que está sem elemento."""
    if boss.damage_source is DamageSource.REAL:
        spec, missing = _spec_with_damages(
            pokemon, lambda skill_id: pokemon.damage_in_boss(skill_id, boss.id))
        return spec, missing, ()
    spec, missing = spec_for_dummy(pokemon, boss.base_dummy)
    if boss.damage_source is DamageSource.DUMMY:
        return spec, missing, ()
    spec, no_element = _with_effectiveness(spec, boss)
    return spec, missing, no_element


def _with_effectiveness(spec: PokemonSpec, boss: BossData) -> tuple[PokemonSpec, tuple[str, ...]]:
    no_element: list[str] = []
    basic = spec.basic
    if basic is not None:
        if basic.element is None:
            no_element.append("Ataque básico")
        basic = replace(basic, multiplier=boss.multiplier(basic.element))
    skills = []
    for position, skill in enumerate(spec.skills, 1):
        if skill.element is None:
            no_element.append(skill_label(skill, position))
        skills.append(replace(skill, multiplier=boss.multiplier(skill.element)))
    return replace(spec, skills=tuple(skills), basic=basic), tuple(no_element)


def _spec_with_damages(
    pokemon: PokemonData, damage_of: Callable[[int | None], float | None],
) -> tuple[PokemonSpec, tuple[str, ...]]:
    missing: list[str] = []

    def damage(skill_id: int | None, label: str) -> float:
        value = damage_of(skill_id)
        if value is None:
            missing.append(label)
            return 0.0
        return value

    basic = pokemon.spec.basic
    if basic is not None:
        basic = replace(basic, damage=damage(None, "Ataque básico"))
    skills = tuple(replace(skill, damage=damage(skill.skill_id, skill_label(skill, position)))
                   for position, skill in enumerate(pokemon.spec.skills, 1))
    return replace(pokemon.spec, skills=skills, basic=basic), tuple(missing)


@dataclass(frozen=True)
class RankingEntry:
    position: int
    pokemon: PokemonData
    breakdown: DamageBreakdown
    share_of_leader: float  # fração 0–1 do dano do 1º colocado
    missing: tuple[str, ...] = ()  # o que não foi testado na origem do boss (conta como 0)
    no_element: tuple[str, ...] = ()  # na origem Efetividade, golpes sem elemento (contam como 0)


def _element(value: str | None) -> Element | None:
    return Element(value) if value else None


def _boss_data(boss: DpsBoss) -> BossData:
    elements = tuple(Element(value) for value in (boss.element_1, boss.element_2) if value)
    return BossData(boss.id, boss.name, boss.time_limit_seconds,
                    frozenset(pokemon.id for pokemon in boss.pokemons), boss.dummy,
                    DamageSource(boss.damage_source), elements,
                    {Element(row.element): EffectivenessLevel(row.level)
                     for row in boss.effectiveness})


def apply_boss_profile(boss: DpsBoss, elements: Sequence[Element],
                        effectiveness: Mapping[Element, EffectivenessLevel]) -> None:
    values = [element.value for element in elements]
    boss.element_1, boss.element_2 = (*values, None, None)[:MAX_BOSS_ELEMENTS]
    # Reaproveita as linhas que continuam: a chave delas é (boss, elemento).
    current = {row.element: row for row in boss.effectiveness}
    rows = []
    for element, level in effectiveness.items():
        if level is not EffectivenessLevel.NORMAL:
            row = current.get(element.value) or DpsBossEffectiveness(element=element.value)
            row.level = level.value
            rows.append(row)
    boss.effectiveness = rows


def _pokemon_spec(pokemon: DpsPokemon) -> PokemonSpec:
    skills = tuple(
        SkillSpec(skill.name, SkillShape(skill.shape), SkillReach(skill.reach), 0,
                  skill.cooldown, skill.efficiency, _element(skill.element), skill.id)
        for skill in pokemon.skills
    )
    basic = None
    if pokemon.basic_efficiency is not None:
        basic = BasicAttackSpec(0, pokemon.basic_efficiency, _element(pokemon.basic_element))
    buff = None
    if pokemon.buff_cooldown is not None:
        buff = BuffSpec(pokemon.buff_cooldown, pokemon.buff_basic_multiplier or 1.0,
                        pokemon.buff_basic_duration or 0.0,
                        pokemon.buff_next_spell_multiplier or 1.0)
    return PokemonSpec(skills, basic, buff)


def _pokemon_data(pokemon: DpsPokemon) -> PokemonData:
    tests: dict[int | None, list[DamageTest]] = {}
    for row in pokemon.damage_tests:
        tests.setdefault(row.skill_id, []).append(
            DamageTest(row.dummy, (row.damage_1, row.damage_2, row.damage_3), row.boss_id,
                       row.created_at, row.updated_at))
    return PokemonData(pokemon.id, pokemon.name, pokemon.note, _pokemon_spec(pokemon),
                       frozenset(boss.id for boss in pokemon.bosses),
                       {key: tuple(value) for key, value in tests.items()})


def apply_spec(pokemon: DpsPokemon, spec: PokemonSpec) -> None:
    pokemon.basic_efficiency = spec.basic.efficiency if spec.basic else None
    pokemon.basic_element = (spec.basic.element.value
                             if spec.basic and spec.basic.element else None)
    pokemon.buff_cooldown = spec.buff.cooldown if spec.buff else None
    pokemon.buff_basic_multiplier = spec.buff.basic_multiplier if spec.buff else None
    pokemon.buff_basic_duration = spec.buff.basic_duration if spec.buff else None
    pokemon.buff_next_spell_multiplier = spec.buff.next_spell_multiplier if spec.buff else None
    # Reaproveita as skills que continuam (os testes apontam para elas); as que saíram da
    # lista são apagadas, com os testes delas.
    current = {skill.id: skill for skill in pokemon.skills}
    skills = []
    for position, spec_skill in enumerate(spec.skills, 1):
        skill = current.get(spec_skill.skill_id) or DpsSkill()
        skill.position = position
        skill.name = spec_skill.name
        skill.shape = spec_skill.shape.value
        skill.reach = spec_skill.reach.value
        skill.cooldown = spec_skill.cooldown
        skill.efficiency = spec_skill.efficiency
        skill.element = spec_skill.element.value if spec_skill.element else None
        skills.append(skill)
    pokemon.skills = skills


def validate_settings(settings: DpsSettings) -> None:
    if not math.isfinite(settings.basic_turn_seconds) or settings.basic_turn_seconds <= 0:
        raise ValueError("O turno do ataque básico precisa ser maior que zero.")
    for value in (settings.target_melee_efficiency, settings.default_efficiency,
                  settings.basic_efficiency):
        if not 0 <= value <= 1:
            raise ValueError("Os aproveitamentos precisam estar entre 0% e 100%.")


class DpsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    # ---------------------------------------------------------------- ajustes

    def settings(self) -> DpsSettings:
        with self.database.session() as session:
            row = DpsRepository(session).settings()
            if row is None:
                return DpsSettings()
            return DpsSettings(row.basic_turn_seconds, row.target_melee_efficiency,
                               row.default_efficiency, row.basic_efficiency, row.last_boss_id)

    def update_settings(self, settings: DpsSettings) -> None:
        validate_settings(settings)
        with self.database.session() as session:
            row = self._settings_row(session)
            row.basic_turn_seconds = settings.basic_turn_seconds
            row.target_melee_efficiency = settings.target_melee_efficiency
            row.default_efficiency = settings.default_efficiency
            row.basic_efficiency = settings.basic_efficiency

    def remember_boss(self, boss_id: int) -> None:
        with self.database.session() as session:
            self._settings_row(session).last_boss_id = boss_id

    @staticmethod
    def _settings_row(session) -> DpsSettingsRow:
        row = DpsRepository(session).settings()
        if row is None:
            row = DpsSettingsRow(basic_turn_seconds=DEFAULT_BASIC_TURN,
                                 target_melee_efficiency=DEFAULT_TARGET_MELEE_EFFICIENCY,
                                 default_efficiency=DEFAULT_EFFICIENCY,
                                 basic_efficiency=DEFAULT_BASIC_EFFICIENCY)
            session.add(row)
        return row

    # ----------------------------------------------------------------- bosses

    def list_bosses(self) -> list[BossData]:
        with self.database.session() as session:
            return [_boss_data(boss) for boss in DpsRepository(session).bosses()]

    def save_boss(self, boss_id: int | None, name: str, time_limit_seconds: int,
                  elements: Sequence[Element] | None = None,
                  effectiveness: Mapping[Element, EffectivenessLevel] | None = None) -> int:
        """Cria (``boss_id`` ``None``) ou altera um boss e retorna o id dele.

        Sem ``elements`` e ``effectiveness``, os que o boss já tem continuam como estão.
        """
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome do boss.")
        if time_limit_seconds <= 0:
            raise ValueError("O tempo limite precisa ser maior que zero.")
        if elements is not None:
            validate_boss_profile(elements)
        with self.database.session() as session:
            repository = DpsRepository(session)
            if any(boss.id != boss_id and boss.name.casefold() == name.casefold()
                   for boss in repository.bosses()):
                raise ValueError(f"Já existe um boss chamado {name}.")
            boss = repository.boss(boss_id) if boss_id is not None else None
            if boss is None:
                boss = DpsBoss(name=name, time_limit_seconds=time_limit_seconds)
                session.add(boss)
            else:
                boss.name = name
                boss.time_limit_seconds = time_limit_seconds
            session.flush()
            if elements is not None or effectiveness is not None:
                current = _boss_data(boss)
                apply_boss_profile(
                    boss, current.elements if elements is None else elements,
                    current.effectiveness if effectiveness is None else effectiveness)
                session.flush()
            return boss.id

    def set_boss_dummy(self, boss_id: int, dummy: str) -> None:
        """Escolhe de qual dummy vem o dano no ranking deste boss."""
        if dummy not in dict(DUMMY_OPTIONS):
            raise ValueError("Escolha um dummy da lista.")
        with self.database.session() as session:
            boss = DpsRepository(session).boss(boss_id)
            if boss is None:
                raise ValueError("Boss não encontrado.")
            boss.dummy = dummy

    def set_boss_damage_source(self, boss_id: int, source: DamageSource) -> None:
        """Escolhe como o ranking deste boss calcula o dano."""
        with self.database.session() as session:
            boss = DpsRepository(session).boss(boss_id)
            if boss is None:
                raise ValueError("Boss não encontrado.")
            boss.damage_source = source.value

    def delete_boss(self, boss_id: int) -> None:
        """Remove o boss e os vínculos dele; os pokémons continuam cadastrados."""
        with self.database.session() as session:
            repository = DpsRepository(session)
            if len(repository.bosses()) <= 1:
                raise ValueError("O último boss não pode ser excluído.")
            boss = repository.boss(boss_id)
            if boss is not None:
                session.delete(boss)

    def set_boss_pokemons(self, boss_id: int, pokemon_ids: Collection[int]) -> None:
        with self.database.session() as session:
            repository = DpsRepository(session)
            boss = repository.boss(boss_id)
            if boss is None:
                raise ValueError("Boss não encontrado.")
            boss.pokemons = [pokemon for pokemon in repository.pokemons()
                             if pokemon.id in pokemon_ids]

    # --------------------------------------------------------------- pokémons

    def list_pokemons(self) -> list[PokemonData]:
        with self.database.session() as session:
            return [_pokemon_data(pokemon) for pokemon in DpsRepository(session).pokemons()]

    def save_pokemon(self, pokemon_id: int | None, name: str, note: str, spec: PokemonSpec,
                     boss_id: int | None = None) -> int:
        """Cria ou altera um pokémon; um pokémon novo entra no boss ``boss_id``.

        O dano de ``spec`` é ignorado: ele vem dos testes.
        """
        name = name.strip()
        if not name:
            raise ValueError("Informe o nome do pokémon.")
        validate_spec(spec)
        with self.database.session() as session:
            repository = DpsRepository(session)
            pokemon = repository.pokemon(pokemon_id) if pokemon_id is not None else None
            if pokemon is None:
                pokemon = DpsPokemon(name=name)
                session.add(pokemon)
                boss = repository.boss(boss_id) if boss_id is not None else None
                if boss is not None:
                    pokemon.bosses.append(boss)
            pokemon.name = name
            pokemon.note = note.strip()
            apply_spec(pokemon, spec)
            session.flush()
            return pokemon.id

    def duplicate_pokemon(self, pokemon_id: int) -> int:
        """Cópia independente, com os testes e nos mesmos bosses do original."""
        with self.database.session() as session:
            repository = DpsRepository(session)
            original = repository.pokemon(pokemon_id)
            if original is None:
                raise ValueError("Pokémon não encontrado.")
            copy = DpsPokemon(name=f"{original.name} (cópia)", note=original.note)
            session.add(copy)
            # Sem ids na ficha, para criar skills novas em vez de mover as do original.
            spec = _pokemon_spec(original)
            apply_spec(copy, replace(spec, skills=tuple(
                replace(skill, skill_id=None) for skill in spec.skills)))
            copy.bosses = list(original.bosses)
            session.flush()
            new_skill_ids = {old.id: new.id for old, new in zip(original.skills, copy.skills)}
            for test in original.damage_tests:
                session.add(DpsDamageTest(
                    pokemon_id=copy.id, skill_id=new_skill_ids.get(test.skill_id),
                    dummy=test.dummy, boss_id=test.boss_id, damage_1=test.damage_1,
                    damage_2=test.damage_2, damage_3=test.damage_3,
                    # A cópia mantém as datas: copiar não torna a medição mais recente.
                    created_at=test.created_at, updated_at=test.updated_at))
            return copy.id

    def delete_pokemon(self, pokemon_id: int) -> None:
        with self.database.session() as session:
            pokemon = DpsRepository(session).pokemon(pokemon_id)
            if pokemon is not None:
                session.delete(pokemon)

    # ----------------------------------------------------------------- testes

    def save_damage_tests(self, pokemon_id: int, skill_id: int | None,
                          tests: Sequence[DamageTest]) -> tuple[DamageTest, ...]:
        """Substitui os testes da skill (sem ``skill_id``, os do ataque básico) e os retorna.

        Um teste é o mesmo se continua no mesmo dummy ou boss. Ele mantém as datas se os danos
        não mudaram e ganha a data de modificação se mudaram; em outro lugar, é um teste novo.
        """
        now = datetime.now()
        saved = []
        with self.database.session() as session:
            repository = DpsRepository(session)
            validate_tests(tests, {boss.id: boss.name for boss in repository.bosses()})
            previous = {
                (row.dummy, row.boss_id): (
                    (row.damage_1, row.damage_2, row.damage_3), row.created_at, row.updated_at)
                for row in repository.damage_tests(pokemon_id, skill_id)}
            repository.delete_damage_tests(pokemon_id, skill_id)
            for test in tests:
                damages = (*test.damages, *[None] * (DAMAGES_PER_TEST - len(test.damages)))
                old = previous.get((test.dummy, test.boss_id))
                if old is None:
                    created_at, updated_at = now, None
                else:
                    old_damages, created_at, updated_at = old
                    if damages != old_damages:
                        updated_at = now
                session.add(DpsDamageTest(
                    pokemon_id=pokemon_id, skill_id=skill_id, dummy=test.dummy,
                    boss_id=test.boss_id,
                    damage_1=damages[0], damage_2=damages[1], damage_3=damages[2],
                    created_at=created_at, updated_at=updated_at))
                saved.append(DamageTest(test.dummy, damages, test.boss_id, created_at, updated_at))
        return tuple(saved)

    # ---------------------------------------------------------------- ranking

    def ranking(self, boss_id: int) -> list[RankingEntry]:
        """Pokémons marcados no boss, do maior para o menor dano na origem e tempo dele."""
        settings = self.settings()
        with self.database.session() as session:
            repository = DpsRepository(session)
            boss_row = repository.boss(boss_id)
            if boss_row is None:
                return []
            boss = _boss_data(boss_row)
            pokemons = [_pokemon_data(pokemon) for pokemon in repository.pokemons(boss_id)]
        results = []
        for pokemon in pokemons:
            spec, missing, no_element = spec_for_boss(pokemon, boss)
            results.append((pokemon, calculate(spec, boss.time_limit_seconds,
                                               settings.basic_turn_seconds),
                            missing, no_element))
        results.sort(key=lambda result: result[1].total, reverse=True)
        leader = results[0][1].total if results else 0
        return [
            RankingEntry(position, pokemon, breakdown,
                         breakdown.total / leader if leader > 0 else 0.0, missing, no_element)
            for position, (pokemon, breakdown, missing, no_element) in enumerate(results, 1)
        ]
