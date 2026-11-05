"""Exportação e importação dos cadastros da página DPS em um arquivo JSON.

O arquivo leva bosses e pokémons, com os testes e as datas deles. Os bosses são citados pelo
nome, porque os ids mudam de um banco para outro. O conteúdo pode vir de outra pessoa, então é
validado por inteiro antes de gravar, e a importação acontece em uma única transação.
Os ajustes da página (turno do básico e aproveitamentos sugeridos) são de cada usuário e não
entram no arquivo.
"""

from __future__ import annotations

import json
import math
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from app.database.database import Database
from app.database.models import DpsBoss, DpsDamageTest, DpsPokemon
from app.database.repositories import DpsRepository
from app.services.dps_calculator import (
    BasicAttackSpec,
    BuffSpec,
    EffectivenessLevel,
    Element,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
    validate_spec,
)
from app.services.dps_service import (
    BOSS_TEST_DUMMY,
    DAMAGES_PER_TEST,
    DUMMY_OPTIONS,
    BossData,
    DamageSource,
    DamageTest,
    DpsService,
    PokemonData,
    apply_boss_profile,
    apply_spec,
    validate_boss_profile,
    validate_tests,
)
from app.utils.constants import APP_VERSION

FORMAT_ID = "pxg-hunt-analyzer-dps"
FORMAT_VERSION = 1
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_NAME_LENGTH = 200
MAX_NOTE_LENGTH = 10_000
MAX_DAMAGE = 10 ** 15
MAX_TIME_LIMIT = 10 ** 7
COPY_SUFFIX = "importado"


@dataclass(frozen=True)
class BundleTest:
    """Um teste no arquivo: em um dummy ou no boss citado pelo nome."""

    dummy: str
    boss: str | None
    damages: tuple[int | None, ...]
    created_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True)
class BundleBoss:
    name: str
    time_limit_seconds: int
    dummy: str
    damage_source: DamageSource
    elements: tuple[Element, ...]
    effectiveness: Mapping[Element, EffectivenessLevel]


@dataclass(frozen=True)
class BundlePokemon:
    name: str
    note: str
    spec: PokemonSpec
    bosses: tuple[str, ...]
    basic_tests: tuple[BundleTest, ...]
    skill_tests: tuple[tuple[BundleTest, ...], ...]  # na ordem de ``spec.skills``

    @property
    def test_count(self) -> int:
        return len(self.basic_tests) + sum(len(tests) for tests in self.skill_tests)


@dataclass(frozen=True)
class DpsBundle:
    bosses: tuple[BundleBoss, ...] = ()
    pokemons: tuple[BundlePokemon, ...] = ()


class ImportKind(Enum):
    BOSS = "boss"
    POKEMON = "pokemon"

    @property
    def label(self) -> str:
        return {"boss": "Boss", "pokemon": "Pokémon"}[self.value]


class ImportAction(Enum):
    SKIP = "skip"
    CREATE = "create"  # cadastro novo; com o nome em uso, é uma cópia "(importado)"
    REPLACE = "replace"


@dataclass(frozen=True)
class ImportItem:
    """Um cadastro do arquivo, o cadastro de mesmo nome (se houver) e o que fazer com ele."""

    kind: ImportKind
    index: int  # posição em ``DpsBundle.bosses`` ou ``DpsBundle.pokemons``
    name: str
    existing_id: int | None
    action: ImportAction

    @property
    def actions(self) -> tuple[ImportAction, ...]:
        if self.existing_id is None:
            return (ImportAction.CREATE, ImportAction.SKIP)
        return (ImportAction.SKIP, ImportAction.REPLACE, ImportAction.CREATE)


@dataclass(frozen=True)
class ImportResult:
    created: int = 0
    replaced: int = 0
    skipped: int = 0
    # Testes e vínculos com bosses que não vieram no arquivo e não existem neste banco.
    dropped_tests: int = 0
    dropped_links: int = 0


# ------------------------------------------------------------------ exportação


def build_bundle(bosses: Iterable[BossData], pokemons: Iterable[PokemonData],
                 boss_names: Mapping[int, str]) -> DpsBundle:
    """Monta o conteúdo do arquivo; ``boss_names`` tem todos os bosses, mesmo os não exportados."""

    def bundle_test(test: DamageTest) -> BundleTest:
        return BundleTest(test.dummy, boss_names[test.boss_id] if test.boss_id is not None else None,
                          test.damages, test.created_at, test.updated_at)

    return DpsBundle(
        tuple(BundleBoss(boss.name, boss.time_limit_seconds, boss.dummy, boss.damage_source,
                         boss.elements, boss.effectiveness) for boss in bosses),
        tuple(BundlePokemon(
            pokemon.name, pokemon.note, pokemon.spec,
            tuple(sorted((boss_names[boss_id] for boss_id in pokemon.boss_ids
                          if boss_id in boss_names), key=str.casefold)),
            tuple(bundle_test(test) for test in pokemon.tests.get(None, ())),
            tuple(tuple(bundle_test(test) for test in pokemon.tests.get(skill.skill_id, ()))
                  for skill in pokemon.spec.skills),
        ) for pokemon in pokemons))


def _test_json(test: BundleTest) -> dict[str, Any]:
    return {
        "dummy": None if test.boss is not None else test.dummy,
        "boss": test.boss,
        "damages": list(test.damages),
        "created_at": test.created_at.isoformat(timespec="seconds") if test.created_at else None,
        "updated_at": test.updated_at.isoformat(timespec="seconds") if test.updated_at else None,
    }


def _boss_json(boss: BundleBoss) -> dict[str, Any]:
    return {
        "name": boss.name,
        "time_limit_seconds": boss.time_limit_seconds,
        "dummy": boss.dummy,
        "damage_source": boss.damage_source.value,
        "elements": [element.value for element in boss.elements],
        "effectiveness": {element.value: level.value
                          for element, level in boss.effectiveness.items()},
    }


def _pokemon_json(pokemon: BundlePokemon) -> dict[str, Any]:
    spec = pokemon.spec
    return {
        "name": pokemon.name,
        "note": pokemon.note,
        "bosses": list(pokemon.bosses),
        "basic": ({"efficiency": spec.basic.efficiency,
                   "element": spec.basic.element.value if spec.basic.element else None}
                  if spec.basic else None),
        "basic_tests": [_test_json(test) for test in pokemon.basic_tests],
        "buff": ({"cooldown": spec.buff.cooldown,
                  "basic_multiplier": spec.buff.basic_multiplier,
                  "basic_duration": spec.buff.basic_duration,
                  "next_spell_multiplier": spec.buff.next_spell_multiplier}
                 if spec.buff else None),
        "skills": [{
            "name": skill.name,
            "shape": skill.shape.value,
            "reach": skill.reach.value,
            "cooldown": skill.cooldown,
            "efficiency": skill.efficiency,
            "element": skill.element.value if skill.element else None,
            "tests": [_test_json(test) for test in tests],
        } for skill, tests in zip(spec.skills, pokemon.skill_tests)],
    }


def bundle_to_json(bundle: DpsBundle, exported_at: datetime | None = None) -> str:
    return json.dumps({
        "format": FORMAT_ID,
        "version": FORMAT_VERSION,
        "app_version": APP_VERSION,
        "exported_at": (exported_at or datetime.now()).isoformat(timespec="seconds"),
        "bosses": [_boss_json(boss) for boss in bundle.bosses],
        "pokemons": [_pokemon_json(pokemon) for pokemon in bundle.pokemons],
    }, indent=2, ensure_ascii=False)


# ------------------------------------------------------------------ leitura


def _text(value: Any, label: str, *, limit: int = MAX_NAME_LENGTH, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label}: texto inválido.")
    text = value.strip()
    if required and not text:
        raise ValueError(f"{label}: não pode ficar vazio.")
    if len(text) > limit:
        raise ValueError(f"{label}: texto longo demais.")
    return text


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label}: número inválido.")
    return float(value)


def _enum(enum_type: type[Enum], value: Any, label: str) -> Any:
    try:
        return enum_type(value)
    except ValueError as exc:
        raise ValueError(f"{label}: valor desconhecido.") from exc


def _optional_element(value: Any, label: str) -> Element | None:
    return None if value is None else _enum(Element, value, label)


def _moment(value: Any, label: str) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{label}: data inválida.")
    try:
        moment = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label}: data inválida.") from exc
    return moment.replace(tzinfo=None)  # o banco guarda a hora local, sem fuso


def _list(value: Any, label: str) -> list:
    if not isinstance(value, list):
        raise ValueError(f"{label}: lista inválida.")
    return value


def _parse_test(data: dict, label: str) -> BundleTest:
    boss = data.get("boss")
    damages = []
    for value in _list(data["damages"], f"{label}: danos"):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int)
                                  or value > MAX_DAMAGE):
            raise ValueError(f"{label}: dano inválido.")
        damages.append(value)
    if len(damages) > DAMAGES_PER_TEST:
        raise ValueError(f"{label}: informe no máximo {DAMAGES_PER_TEST} danos.")
    damages += [None] * (DAMAGES_PER_TEST - len(damages))
    created_at = _moment(data.get("created_at"), label)
    updated_at = _moment(data.get("updated_at"), label)
    if boss is not None:
        return BundleTest(BOSS_TEST_DUMMY, _text(boss, f"{label}: boss", required=True),
                          tuple(damages), created_at, updated_at)
    return BundleTest(data["dummy"], None, tuple(damages), created_at, updated_at)


def _parse_tests(values: Any, label: str) -> tuple[BundleTest, ...]:
    tests = tuple(_parse_test(data, label) for data in _list(values, f"{label}: testes"))
    # Reaproveita a validação do cadastro; aqui o id do boss é só a identidade do nome.
    names = sorted({test.boss.casefold() for test in tests if test.boss is not None})
    ids = {name: number for number, name in enumerate(names)}
    try:
        validate_tests(
            [DamageTest(test.dummy, test.damages,
                        ids[test.boss.casefold()] if test.boss is not None else None)
             for test in tests],
            {number: name for name, number in ids.items()})
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc
    return tests


def _parse_boss(data: dict) -> BundleBoss:
    name = _text(data["name"], "Boss", required=True)
    label = f"Boss {name}"
    limit = data["time_limit_seconds"]
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 < limit <= MAX_TIME_LIMIT:
        raise ValueError(f"{label}: tempo limite inválido.")
    dummy = data["dummy"]
    if dummy not in dict(DUMMY_OPTIONS):
        raise ValueError(f"{label}: dummy desconhecido.")
    elements = tuple(_enum(Element, value, f"{label}: elemento")
                     for value in _list(data["elements"], f"{label}: elementos"))
    try:
        validate_boss_profile(elements)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc
    effectiveness = data["effectiveness"]
    if not isinstance(effectiveness, dict):
        raise ValueError(f"{label}: efetividade inválida.")
    return BundleBoss(
        name, limit, dummy, _enum(DamageSource, data["damage_source"], f"{label}: origem do dano"),
        elements,
        {_enum(Element, element, f"{label}: efetividade"):
         _enum(EffectivenessLevel, level, f"{label}: efetividade")
         for element, level in effectiveness.items()})


def _parse_pokemon(data: dict) -> BundlePokemon:
    name = _text(data["name"], "Pokémon", required=True)
    label = f"Pokémon {name}"
    skills = []
    skill_tests = []
    for position, skill in enumerate(_list(data["skills"], f"{label}: skills"), 1):
        skill_label = f"{label}, skill {position}"
        skills.append(SkillSpec(
            _text(skill["name"], skill_label),
            _enum(SkillShape, skill["shape"], f"{skill_label}: forma"),
            _enum(SkillReach, skill["reach"], f"{skill_label}: alcance"),
            0,
            _number(skill["cooldown"], f"{skill_label}: recarga"),
            _number(skill["efficiency"], f"{skill_label}: aproveitamento"),
            _optional_element(skill.get("element"), f"{skill_label}: elemento")))
        skill_tests.append(_parse_tests(skill["tests"], skill_label))
    basic = data.get("basic")
    buff = data.get("buff")
    spec = PokemonSpec(
        tuple(skills),
        None if basic is None else BasicAttackSpec(
            0, _number(basic["efficiency"], f"{label}: básico"),
            _optional_element(basic.get("element"), f"{label}: básico")),
        None if buff is None else BuffSpec(
            _number(buff["cooldown"], f"{label}: buff"),
            _number(buff["basic_multiplier"], f"{label}: buff"),
            _number(buff["basic_duration"], f"{label}: buff"),
            _number(buff["next_spell_multiplier"], f"{label}: buff")))
    try:
        validate_spec(spec)
    except ValueError as exc:
        raise ValueError(f"{label}: {exc}") from exc
    return BundlePokemon(
        name, _text(data.get("note", ""), f"{label}: observação", limit=MAX_NOTE_LENGTH), spec,
        tuple(_text(boss, f"{label}: boss", required=True)
              for boss in _list(data["bosses"], f"{label}: bosses")),
        _parse_tests(data["basic_tests"], f"{label}, ataque básico"),
        tuple(skill_tests))


def _reject_constant(value: str) -> None:
    raise ValueError(f"constante inválida: {value}")


def parse_bundle(text: str) -> DpsBundle:
    """Lê o conteúdo do arquivo. Lança ``ValueError`` com a mensagem para o usuário."""
    try:
        data = json.loads(text, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:
        raise ValueError("O arquivo não é um JSON válido.") from exc
    if not isinstance(data, dict) or data.get("format") != FORMAT_ID:
        raise ValueError("Este arquivo não é uma exportação do DPS.")
    version = data.get("version")
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError("Este arquivo não é uma exportação do DPS.")
    if version > FORMAT_VERSION:
        raise ValueError("O arquivo foi criado por uma versão mais nova do aplicativo. "
                         "Atualize o aplicativo para importá-lo.")
    try:
        bosses = tuple(_parse_boss(boss) for boss in _list(data["bosses"], "Bosses"))
        pokemons = tuple(_parse_pokemon(pokemon) for pokemon in _list(data["pokemons"], "Pokémons"))
    except (KeyError, TypeError, AttributeError, OverflowError) as exc:
        raise ValueError(f"O arquivo está incompleto ou foi alterado ({exc}).") from exc
    seen: set[str] = set()
    for boss in bosses:
        key = boss.name.casefold()
        if key in seen:
            raise ValueError(f"O boss {boss.name} aparece mais de uma vez no arquivo.")
        seen.add(key)
    if not bosses and not pokemons:
        raise ValueError("O arquivo não tem bosses nem pokémons.")
    return DpsBundle(bosses, pokemons)


def read_bundle(path: Path) -> DpsBundle:
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("O arquivo é grande demais para ser uma exportação do DPS.")
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Este arquivo não é uma exportação do DPS.") from exc
    except OSError as exc:
        raise ValueError(f"Não foi possível ler o arquivo: {exc}") from exc
    return parse_bundle(text)


# ------------------------------------------------------------------ importação


def plan_import(bundle: DpsBundle, bosses: Iterable[BossData],
                pokemons: Iterable[PokemonData]) -> list[ImportItem]:
    """O que há no arquivo e o padrão de cada um: importar o novo e pular o de nome repetido."""

    def default(existing_id: int | None) -> ImportAction:
        return ImportAction.CREATE if existing_id is None else ImportAction.SKIP

    boss_ids = {boss.name.casefold(): boss.id for boss in bosses}
    items = []
    for index, boss in enumerate(bundle.bosses):
        existing = boss_ids.get(boss.name.casefold())
        items.append(ImportItem(ImportKind.BOSS, index, boss.name, existing, default(existing)))
    # Pokémons podem repetir o nome: cada um do arquivo corresponde a no máximo um daqui.
    pokemon_ids: dict[str, list[int]] = {}
    for pokemon in sorted(pokemons, key=lambda p: p.id):
        pokemon_ids.setdefault(pokemon.name.casefold(), []).append(pokemon.id)
    for index, pokemon in enumerate(bundle.pokemons):
        available = pokemon_ids.get(pokemon.name.casefold())
        existing = available.pop(0) if available else None
        items.append(ImportItem(ImportKind.POKEMON, index, pokemon.name, existing,
                                default(existing)))
    return items


def _copy_name(name: str, taken: set[str]) -> str:
    candidate = f"{name} ({COPY_SUFFIX})"
    number = 2
    while candidate.casefold() in taken:
        candidate = f"{name} ({COPY_SUFFIX} {number})"
        number += 1
    taken.add(candidate.casefold())
    return candidate


class DpsTransferService:
    def __init__(self, database: Database) -> None:
        self.database = database
        self._dps = DpsService(database)

    def export_file(self, path: Path, boss_ids: Collection[int],
                    pokemon_ids: Collection[int]) -> None:
        bosses = self._dps.list_bosses()
        bundle = build_bundle([boss for boss in bosses if boss.id in boss_ids],
                              [pokemon for pokemon in self._dps.list_pokemons()
                               if pokemon.id in pokemon_ids],
                              {boss.id: boss.name for boss in bosses})
        try:
            path.write_text(bundle_to_json(bundle), encoding="utf-8")
        except OSError as exc:
            raise ValueError(f"Não foi possível salvar o arquivo: {exc}") from exc

    def plan(self, bundle: DpsBundle) -> list[ImportItem]:
        return plan_import(bundle, self._dps.list_bosses(), self._dps.list_pokemons())

    def apply(self, bundle: DpsBundle, items: Sequence[ImportItem]) -> ImportResult:
        """Grava as escolhas de ``items`` de uma vez: se algo falhar, nada muda."""
        counts = {ImportAction.CREATE: 0, ImportAction.REPLACE: 0, ImportAction.SKIP: 0}
        dropped_tests = dropped_links = 0
        with self.database.session() as session:
            repository = DpsRepository(session)
            current_bosses = repository.bosses()
            current_pokemons = repository.pokemons()
            taken_bosses = ({boss.name.casefold() for boss in current_bosses}
                            | {boss.name.casefold() for boss in bundle.bosses})
            taken_pokemons = ({pokemon.name.casefold() for pokemon in current_pokemons}
                              | {pokemon.name.casefold() for pokemon in bundle.pokemons})
            # Para qual boss deste banco aponta cada nome citado no arquivo.
            boss_of_name = {boss.name.casefold(): boss for boss in current_bosses}

            for item in items:
                if item.kind is not ImportKind.BOSS:
                    continue
                counts[item.action] += 1
                if item.action is ImportAction.SKIP:
                    continue
                data = bundle.bosses[item.index]
                boss = (repository.boss(item.existing_id)
                        if item.action is ImportAction.REPLACE and item.existing_id is not None
                        else None)
                if boss is None:
                    name = (_copy_name(data.name, taken_bosses)
                            if item.existing_id is not None else data.name)
                    boss = DpsBoss(name=name, time_limit_seconds=data.time_limit_seconds)
                    session.add(boss)
                boss.time_limit_seconds = data.time_limit_seconds
                boss.dummy = data.dummy
                boss.damage_source = data.damage_source.value
                session.flush()
                apply_boss_profile(boss, data.elements, data.effectiveness)
                boss_of_name[data.name.casefold()] = boss
            session.flush()

            for item in items:
                if item.kind is not ImportKind.POKEMON:
                    continue
                counts[item.action] += 1
                if item.action is ImportAction.SKIP:
                    continue
                data = bundle.pokemons[item.index]
                pokemon = (repository.pokemon(item.existing_id)
                           if item.action is ImportAction.REPLACE and item.existing_id is not None
                           else None)
                if pokemon is None:
                    name = (_copy_name(data.name, taken_pokemons)
                            if item.existing_id is not None else data.name)
                    pokemon = DpsPokemon(name=name, note=data.note)
                    session.add(pokemon)
                else:
                    pokemon.damage_tests.clear()  # o arquivo substitui a ficha e os testes
                    pokemon.note = data.note
                    session.flush()
                apply_spec(pokemon, replace(data.spec, skills=tuple(
                    replace(skill, skill_id=None) for skill in data.spec.skills)))
                # Substituir mantém os bosses que o pokémon já tinha.
                for boss_name in data.bosses:
                    boss = boss_of_name.get(boss_name.casefold())
                    if boss is None:
                        dropped_links += 1
                    elif boss not in pokemon.bosses:
                        pokemon.bosses.append(boss)
                session.flush()
                groups = [(None, data.basic_tests)]
                groups += [(skill.id, tests)
                           for skill, tests in zip(pokemon.skills, data.skill_tests)]
                for skill_id, tests in groups:
                    for test in tests:
                        boss_id = None
                        if test.boss is not None:
                            boss = boss_of_name.get(test.boss.casefold())
                            if boss is None:
                                dropped_tests += 1
                                continue
                            boss_id = boss.id
                        session.add(DpsDamageTest(
                            pokemon_id=pokemon.id, skill_id=skill_id, dummy=test.dummy,
                            boss_id=boss_id, damage_1=test.damages[0], damage_2=test.damages[1],
                            damage_3=test.damages[2], created_at=test.created_at,
                            updated_at=test.updated_at))
        return ImportResult(counts[ImportAction.CREATE], counts[ImportAction.REPLACE],
                            counts[ImportAction.SKIP], dropped_tests, dropped_links)

