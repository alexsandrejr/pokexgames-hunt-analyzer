import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from app.database.database import Database
from app.database.migrations import LATEST_VERSION
from app.services.dps_calculator import (
    BasicAttackSpec,
    BuffSpec,
    EffectivenessLevel,
    Element,
    LineKind,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
    calculate,
    validate_spec,
)
from app.services.dps_service import (
    DUMMY_OPTIONS,
    DamageSource,
    DamageTest,
    DpsService,
    DpsSettings,
    damage_average,
)
from sqlalchemy import text
from tests.helpers import memory_database

FIGHT = 420
TURN = 2.5


def skills(*rows) -> tuple[SkillSpec, ...]:
    """``(dano, recarga)`` ou ``(dano, recarga, "target")``: target melee a 75%."""
    result = []
    for damage, cooldown, *target in rows:
        if target:
            result.append(SkillSpec("", SkillShape.TARGET, SkillReach.MELEE, damage, cooldown, .75))
        else:
            result.append(SkillSpec("", SkillShape.AREA, SkillReach.RANGED, damage, cooldown, 1))
    return tuple(result)


SANDSMAURO = skills((14000, 8), (22500, 32), (12900, 12), (25500, 35), (43700, 50),
                    (10700, 20, "target"), (7500, 20, "target"))
MAUROLEM = skills((18000, 12), (16000, 12), (9800, 8), (19000, 30), (42000, 50),
                  (11000, 40), (15000, 40))
POLISHOP = skills((10700, 10), (17600, 15), (29300, 40), (20400, 22), (5500, 25), (32500, 50))
JOLT = skills((41000, 50), (7900, 12), (9400, 10), (14000, 12), (14600, 25), (22100, 40),
              (8400, 25))
JEREMIA = skills((18000, 20, "target"), (12300, 10), (14800, 12), (22000, 28), (15000, 35),
                 (30000, 50), (25500, 40))
BARTOLOMEU = skills((23000, 40), (31000, 40), (22600, 40), (27000, 50), (14300, 20),
                    (11400, 20), (6600, 15), (4400, 15))
CHUMBIN = skills((20000, 35), (13000, 8), (15500, 12), (22000, 20), (14600, 50), (33000, 50))
MUQ = skills((13000, 40), (19000, 40), (22000, 50), (16000, 30), (11600, 25), (14700, 12),
             (12200, 8), (19000, 15))


class CalculatorTests(unittest.TestCase):
    def test_reproduces_the_original_ranking(self) -> None:
        # Básico a 100% e sem o bônus da próxima magia: as contas originais.
        basic_only_buff = BuffSpec(50, basic_multiplier=2, basic_duration=15)
        cases = [
            (PokemonSpec(CHUMBIN, BasicAttackSpec(2700, 1), basic_only_buff), 2916520),
            (PokemonSpec(MUQ), 2626680),
            (PokemonSpec(MAUROLEM), 2596300),
            (PokemonSpec(SANDSMAURO), 2441543),
            (PokemonSpec(JEREMIA), 2347850),
            (PokemonSpec(POLISHOP, BasicAttackSpec(1600, 1)), 2273505),
            (PokemonSpec(JOLT), 2124150),
            (PokemonSpec(BARTOLOMEU), 1878800),
        ]
        for spec, expected in cases:
            self.assertAlmostEqual(calculate(spec, FIGHT, TURN).total, expected, delta=1)

    def test_dps_is_total_over_time(self) -> None:
        self.assertAlmostEqual(calculate(PokemonSpec(MUQ), FIGHT, TURN).dps, 6254, delta=1)

    def test_full_buff_on_basic_at_75_percent_and_next_spell(self) -> None:
        spec = PokemonSpec(CHUMBIN, BasicAttackSpec(2700, .75),
                           BuffSpec(50, 2, 15, next_spell_multiplier=2))
        result = calculate(spec, FIGHT, TURN)
        self.assertAlmostEqual(result.total, 3046300)
        self.assertAlmostEqual(result.dps, 7253.095, places=2)
        spell = result.lines[-1]
        self.assertEqual(spell.kind, LineKind.BUFF)
        self.assertEqual(spell.source, "Buff: próxima magia (Skill 6)")  # a de 33.000
        self.assertAlmostEqual(spell.total, 33000 * FIGHT / 50)

    def test_next_spell_follows_the_slowest_cooldown(self) -> None:
        # 40.000 a cada 100 s rende menos que 30.000 a cada 50 s, se o buff vem a cada 50 s.
        spec = PokemonSpec(skills((40000, 100), (30000, 50)), None, BuffSpec(
            50, next_spell_multiplier=1.5))
        spell = calculate(spec, 100, TURN).lines[-1]
        self.assertEqual(spell.source, "Buff: próxima magia (Skill 2)")
        self.assertAlmostEqual(spell.total, 30000 * .5 * 100 / 50)

    def test_next_spell_respects_skill_efficiency(self) -> None:
        spec = PokemonSpec(skills((30000, 50, "target"), (25000, 50)), None,
                           BuffSpec(50, next_spell_multiplier=2))
        spell = calculate(spec, 50, TURN).lines[-1]
        self.assertEqual(spell.source, "Buff: próxima magia (Skill 2)")  # 25.000 > 22.500

    def test_partial_buff_only_on_basic(self) -> None:
        spec = PokemonSpec((), BasicAttackSpec(1000, 1), BuffSpec(10, 1.5, 5))
        result = calculate(spec, 100, 2)
        self.assertEqual([line.source for line in result.lines],
                         ["Ataque básico", "Buff: ataque básico"])
        self.assertAlmostEqual(result.lines[1].total, 50000 * .5 * .5)

    def test_buff_duration_longer_than_cooldown_counts_as_always_active(self) -> None:
        spec = PokemonSpec((), BasicAttackSpec(1000, 1), BuffSpec(10, 2, 30))
        self.assertAlmostEqual(calculate(spec, 100, 2).total, 100000)

    def test_buff_without_basic_or_skills_adds_nothing(self) -> None:
        spec = PokemonSpec(skills((1000, 10)), None, BuffSpec(10, 2, 5))
        self.assertEqual(len(calculate(spec, 100, 2).lines), 1)

    def test_untested_skill_counts_zero_and_says_so(self) -> None:
        untested = SkillSpec("", SkillShape.AREA, SkillReach.RANGED, 0, 10, 1)
        result = calculate(PokemonSpec((untested,), BasicAttackSpec(0, 1), BuffSpec(10, 2, 5, 2)),
                           100, 2)
        self.assertEqual(result.total, 0)
        self.assertEqual([line.source for line in result.lines], ["Skill 1", "Ataque básico"])
        self.assertIn("sem teste", result.lines[0].detail)

    def test_multiplier_applies_to_skill_basic_and_buffs(self) -> None:
        plain = calculate(PokemonSpec(CHUMBIN, BasicAttackSpec(2700, 1),
                                      BuffSpec(50, 2, 15, 1.5)), FIGHT, TURN)
        doubled = calculate(PokemonSpec(
            tuple(replace(skill, multiplier=2) for skill in CHUMBIN),
            BasicAttackSpec(2700, 1, multiplier=2), BuffSpec(50, 2, 15, 1.5)), FIGHT, TURN)
        self.assertAlmostEqual(doubled.total, plain.total * 2)

    def test_multiplier_is_shown_and_missing_element_counts_zero(self) -> None:
        skill = SkillSpec("", SkillShape.AREA, SkillReach.RANGED, 1000, 10, 1, multiplier=.75)
        self.assertEqual(calculate(PokemonSpec((skill,)), FIGHT, TURN).lines[0].detail,
                         "Área · Ranged · 1.000 ×0,75 / 10s · 100%")
        result = calculate(PokemonSpec((replace(skill, multiplier=None),)), FIGHT, TURN)
        self.assertEqual(result.total, 0)
        self.assertIn("sem elemento", result.lines[0].detail)

    def test_null_effectiveness_gives_no_buff_line(self) -> None:
        result = calculate(PokemonSpec((), BasicAttackSpec(1000, 1, multiplier=0),
                                       BuffSpec(50, 2, 15)), FIGHT, TURN)
        self.assertEqual(result.total, 0)
        self.assertEqual([line.kind for line in result.lines], [LineKind.BASIC])

    def test_next_spell_picks_the_best_after_effectiveness(self) -> None:
        strong = SkillSpec("Forte", SkillShape.AREA, SkillReach.RANGED, 2000, 50, 1, multiplier=.5)
        weak = SkillSpec("Fraca", SkillShape.AREA, SkillReach.RANGED, 1500, 50, 1, multiplier=2)
        result = calculate(PokemonSpec((strong, weak), None, BuffSpec(50, next_spell_multiplier=2)),
                           FIGHT, TURN)
        self.assertEqual(result.lines[-1].source, "Buff: próxima magia (Fraca)")

    def test_effectiveness_levels_follow_the_game_table(self) -> None:
        self.assertEqual([level.multiplier for level in EffectivenessLevel],
                         [2, 1.75, 1, .75, .5, 0])

    def test_validation(self) -> None:
        ok_skill = skills((1000, 10))
        invalid = [
            PokemonSpec(),
            PokemonSpec(skills((1000, 0))),
            PokemonSpec((SkillSpec("", SkillShape.AREA, SkillReach.MELEE, 1, 1, 1.5),)),
            PokemonSpec((), BasicAttackSpec(10, -.1)),
            PokemonSpec(ok_skill, None, BuffSpec(0, 2, 5)),
            PokemonSpec(ok_skill, None, BuffSpec(10)),  # sem efeito
            PokemonSpec(ok_skill, None, BuffSpec(10, .5, 5)),
            PokemonSpec(ok_skill, None, BuffSpec(10, 2, 0)),  # bônus sem duração
        ]
        for spec in invalid:
            with self.assertRaises(ValueError, msg=spec):
                validate_spec(spec)
        validate_spec(PokemonSpec(ok_skill, None, BuffSpec(10, next_spell_multiplier=2)))


class ServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = memory_database()
        self.service = DpsService(self.database)
        [self.default_boss] = self.service.list_bosses()

    def tearDown(self) -> None:
        self.database.dispose()

    def add(self, name: str, rows=SANDSMAURO, dummy: str = "neutral", **kwargs) -> int:
        """Cadastra o pokémon e grava o dano de cada skill como um teste no dummy."""
        kwargs.setdefault("boss_id", self.default_boss.id)
        pokemon_id = self.service.save_pokemon(None, name, "", PokemonSpec(rows), **kwargs)
        pokemon = next(p for p in self.service.list_pokemons() if p.id == pokemon_id)
        for skill, row in zip(pokemon.spec.skills, rows):
            self.service.save_damage_tests(pokemon_id, skill.skill_id,
                                           [DamageTest(dummy, (int(row.damage),))])
        return pokemon_id

    def pokemon(self, pokemon_id: int):
        return next(p for p in self.service.list_pokemons() if p.id == pokemon_id)

    def test_new_database_has_default_boss(self) -> None:
        self.assertEqual((self.default_boss.name, self.default_boss.time_limit_seconds,
                          self.default_boss.dummy), ("Padrão", 420, "neutral"))

    def test_ranking_orders_by_damage_and_shows_only_selected_pokemons(self) -> None:
        low, high = self.add("Jolt", JOLT), self.add("Muq", MUQ)
        other = self.service.save_boss(None, "Terror", 300)
        self.add("Fora", MAUROLEM, boss_id=other)

        ranking = self.service.ranking(self.default_boss.id)
        self.assertEqual([entry.pokemon.id for entry in ranking], [high, low])
        self.assertEqual([entry.position for entry in ranking], [1, 2])
        self.assertEqual(ranking[0].share_of_leader, 1)
        self.assertAlmostEqual(ranking[1].share_of_leader, 2124150 / 2626680)
        self.assertAlmostEqual(ranking[0].breakdown.total, 2626680)
        self.assertEqual(ranking[0].missing, ())

    def test_boss_time_limit_changes_the_total(self) -> None:
        self.add("Muq", MUQ)
        self.service.save_boss(self.default_boss.id, "Padrão", 210)
        [entry] = self.service.ranking(self.default_boss.id)
        self.assertAlmostEqual(entry.breakdown.total, 2626680 / 2)

    def test_ranking_uses_the_dummy_chosen_for_each_boss(self) -> None:
        pokemon_id = self.service.save_pokemon(None, "Muq", "", PokemonSpec(skills((0, 10))),
                                               self.default_boss.id)
        skill_id = self.pokemon(pokemon_id).spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (1000, 3000, None)), DamageTest("water", (500, None, None))])
        terror = self.service.save_boss(None, "Terror", 420)
        self.service.set_boss_pokemons(terror, [pokemon_id])
        self.service.set_boss_dummy(terror, "water")

        [neutral] = self.service.ranking(self.default_boss.id)
        self.assertAlmostEqual(neutral.breakdown.total, 2000 / 10 * 420)
        [water] = self.service.ranking(terror)
        self.assertAlmostEqual(water.breakdown.total, 500 / 10 * 420)

    def test_skill_without_test_on_the_dummy_is_zero_and_listed(self) -> None:
        spec = PokemonSpec((SkillSpec("Golpe", SkillShape.AREA, SkillReach.RANGED, 0, 10, 1),),
                           BasicAttackSpec(0, 1))
        pokemon_id = self.service.save_pokemon(None, "Muq", "", spec, self.default_boss.id)
        skill_id = self.pokemon(pokemon_id).spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [DamageTest("neutral", (1000,))])
        self.service.set_boss_dummy(self.default_boss.id, "water")

        [entry] = self.service.ranking(self.default_boss.id)  # sem usar o Neutro como substituto
        self.assertEqual(entry.breakdown.total, 0)
        self.assertEqual(entry.missing, ("Ataque básico", "Golpe"))
        self.assertEqual(entry.share_of_leader, 0)

    def test_set_boss_dummy_validation(self) -> None:
        for boss_id, dummy in ((self.default_boss.id, "crystal"), (999, "water")):
            with self.assertRaises(ValueError):
                self.service.set_boss_dummy(boss_id, dummy)

    def test_basic_turn_setting_changes_the_ranking(self) -> None:
        spec = PokemonSpec((), BasicAttackSpec(0, 1))
        pokemon_id = self.service.save_pokemon(None, "Básico", "", spec,
                                               boss_id=self.default_boss.id)
        self.service.save_damage_tests(pokemon_id, None, [DamageTest("neutral", (1000,))])
        self.service.update_settings(DpsSettings(basic_turn_seconds=5))
        [entry] = self.service.ranking(self.default_boss.id)
        self.assertAlmostEqual(entry.breakdown.total, 1000 / 5 * 420)

    def test_settings_validation_and_suggestions(self) -> None:
        with self.assertRaises(ValueError):
            self.service.update_settings(DpsSettings(basic_turn_seconds=0))
        with self.assertRaises(ValueError):
            self.service.update_settings(DpsSettings(basic_efficiency=1.1))
        self.service.update_settings(DpsSettings(target_melee_efficiency=.5))
        settings = self.service.settings()
        self.assertEqual(settings.suggested_efficiency(SkillShape.TARGET, SkillReach.MELEE), .5)
        self.assertEqual(settings.suggested_efficiency(SkillShape.TARGET, SkillReach.RANGED), 1)
        self.assertEqual(settings.suggested_efficiency(SkillShape.AREA, SkillReach.MELEE), 1)

    def test_pokemon_round_trip_and_edit_replaces_skills(self) -> None:
        spec = PokemonSpec(skills((0, 10), (0, 20, "target")), BasicAttackSpec(0, .75),
                           BuffSpec(50, 2, 15, 1.5))
        pokemon_id = self.service.save_pokemon(None, " Chumbin ", " +70 ", spec,
                                               boss_id=self.default_boss.id)
        [saved] = self.service.list_pokemons()
        self.assertEqual((saved.id, saved.name, saved.note, saved.spec),
                         (pokemon_id, "Chumbin", "+70", spec))
        self.assertEqual(saved.boss_ids, {self.default_boss.id})

        edited = PokemonSpec(skills((0, 30)))
        self.service.save_pokemon(pokemon_id, "Chumbin", "", edited)
        [saved] = self.service.list_pokemons()
        self.assertEqual(saved.spec, edited)
        self.assertEqual(saved.boss_ids, {self.default_boss.id})  # editar mantém os vínculos

    def test_damage_in_the_spec_is_ignored_when_saving(self) -> None:
        pokemon_id = self.service.save_pokemon(None, "Muq", "", PokemonSpec(skills((9999, 10))))
        self.assertEqual(self.pokemon(pokemon_id).spec.skills[0].damage, 0)

    def test_duplicate_goes_to_the_same_bosses_with_independent_tests(self) -> None:
        other = self.service.save_boss(None, "Terror", 300)
        original = self.add("Muq", MUQ)
        self.service.set_boss_pokemons(other, [original])
        self.service.save_damage_tests(original, None, [DamageTest("ice", (50,))])
        copy_id = self.service.duplicate_pokemon(original)

        copy, source = self.pokemon(copy_id), self.pokemon(original)
        self.assertEqual(copy.name, "Muq (cópia)")
        self.assertEqual(copy.spec, source.spec)
        self.assertEqual(copy.boss_ids, {self.default_boss.id, other})
        self.assertNotEqual(copy.spec.skills[0].skill_id, source.spec.skills[0].skill_id)
        self.assertEqual(copy.damage_on(copy.spec.skills[0].skill_id, "neutral"), 13000)
        self.assertEqual(copy.damage_on(None, "ice"), 50)
        self.assertEqual(len(source.tests), len(copy.tests))  # o original não perde nada

        self.service.save_damage_tests(copy_id, copy.spec.skills[0].skill_id,
                                       [DamageTest("neutral", (1,))])
        self.assertEqual(self.pokemon(original).damage_on(source.spec.skills[0].skill_id,
                                                          "neutral"), 13000)
        self.service.delete_pokemon(original)  # a cópia é independente
        self.assertEqual(self.service.ranking(other)[0].pokemon.id, copy_id)

    def test_set_boss_pokemons(self) -> None:
        first, second = self.add("A"), self.add("B")
        self.service.set_boss_pokemons(self.default_boss.id, [second])
        self.assertEqual([entry.pokemon.id for entry in self.service.ranking(self.default_boss.id)],
                         [second])
        self.assertEqual({pokemon.id for pokemon in self.service.list_pokemons()}, {first, second})

    def test_deleting_boss_keeps_pokemons_and_last_boss_is_protected(self) -> None:
        with self.assertRaises(ValueError):
            self.service.delete_boss(self.default_boss.id)
        other = self.service.save_boss(None, "Terror", 300)
        pokemon = self.add("Muq", MUQ, boss_id=other)
        self.service.remember_boss(other)
        self.service.delete_boss(other)
        [saved] = self.service.list_pokemons()
        self.assertEqual((saved.id, saved.boss_ids), (pokemon, frozenset()))
        self.assertIsNone(self.service.settings().last_boss_id)

    def test_deleting_pokemon_removes_it_from_every_boss(self) -> None:
        other = self.service.save_boss(None, "Terror", 300)
        pokemon = self.add("Muq", MUQ)
        self.service.set_boss_pokemons(other, [pokemon])
        self.service.delete_pokemon(pokemon)
        self.assertEqual(self.service.ranking(self.default_boss.id), [])
        self.assertEqual(self.service.ranking(other), [])

    def test_boss_validation(self) -> None:
        for name, seconds in (("", 60), ("Terror", 0), ("padrão", 60)):
            with self.assertRaises(ValueError):
                self.service.save_boss(None, name, seconds)
        self.service.save_boss(self.default_boss.id, "PADRÃO", 60)  # o próprio nome pode

    def test_pokemon_validation(self) -> None:
        with self.assertRaises(ValueError):
            self.service.save_pokemon(None, " ", "", PokemonSpec(MUQ))
        with self.assertRaises(ValueError):
            self.service.save_pokemon(None, "Vazio", "", PokemonSpec())
        self.assertEqual(self.service.list_pokemons(), [])

    def _with_tests(self) -> tuple[int, int]:
        spec = PokemonSpec(skills((0, 10), (0, 20)), BasicAttackSpec(0, .75))
        pokemon_id = self.service.save_pokemon(None, "Muq", "", spec, self.default_boss.id)
        skill_id = self.service.list_pokemons()[0].spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id,
                                       [DamageTest("neutral", (100, 200, 300))])
        self.service.save_damage_tests(pokemon_id, None, [DamageTest("ice", (50, None, None))])
        return pokemon_id, skill_id

    def test_dummies_are_neutral_and_the_18_elements(self) -> None:
        self.assertEqual(len(DUMMY_OPTIONS), 19)
        labels = dict(DUMMY_OPTIONS)
        self.assertEqual(labels["neutral"], "Neutro")
        self.assertEqual(labels["normal"], "Normal")
        self.assertEqual(labels["fighting"], "Fighting")
        self.assertNotIn("crystal", labels)

    def test_average_uses_only_filled_damages(self) -> None:
        self.assertEqual(damage_average((100, None, 300)), 200)
        self.assertIsNone(damage_average((None, None, None)))
        self.assertEqual(DamageTest("ice", (100, 200, 300)).average, 200)

    def test_tests_round_trip_and_replace(self) -> None:
        pokemon_id, skill_id = self._with_tests()
        self.assertEqual(self.pokemon(pokemon_id).tests, {
            skill_id: (DamageTest("neutral", (100, 200, 300)),),
            None: (DamageTest("ice", (50, None, None)),),
        })
        self.service.save_damage_tests(pokemon_id, skill_id, [])
        self.assertEqual(list(self.pokemon(pokemon_id).tests), [None])

    def test_tests_validation(self) -> None:
        pokemon_id, skill_id = self._with_tests()
        invalid = [
            [DamageTest("crystal", (1, None, None))],
            [DamageTest("ice", (None, None, None))],
            [DamageTest("ice", (0, None, None))],
            [DamageTest("ice", (1, 2, 3, 4))],
            [DamageTest("ice", (1,)), DamageTest("ice", (2,))],
        ]
        for tests in invalid:
            with self.assertRaises(ValueError, msg=tests):
                self.service.save_damage_tests(pokemon_id, skill_id, tests)
        self.assertEqual(self.pokemon(pokemon_id).tests[skill_id],
                         (DamageTest("neutral", (100, 200, 300)),))  # nada mudou

    def _save_on(self, day: int, pokemon_id: int, skill_id: int | None,
                 tests: list[DamageTest]) -> DamageTest:
        """Salva os testes como se fosse o dia ``day`` e devolve o primeiro, relido do banco."""
        with patch("app.services.dps_service.datetime") as clock:
            clock.now.return_value = datetime(2026, 11, day, 12)
            self.service.save_damage_tests(pokemon_id, skill_id, tests)
        return self.pokemon(pokemon_id).tests[skill_id][0]

    def test_new_test_has_only_the_created_date(self) -> None:
        pokemon_id = self.add("Muq")
        test = self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,))])
        self.assertEqual(test.created_at, datetime(2026, 11, 1, 12))
        self.assertIsNone(test.updated_at)

    def test_saving_the_same_damages_keeps_the_dates(self) -> None:
        pokemon_id = self.add("Muq")
        self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,))])
        test = self._save_on(2, pokemon_id, None, [DamageTest("ice", (100, None, None))])
        self.assertEqual(test.created_at, datetime(2026, 11, 1, 12))
        self.assertIsNone(test.updated_at)

    def test_changing_a_damage_records_the_modification(self) -> None:
        pokemon_id = self.add("Muq")
        self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,))])
        self._save_on(2, pokemon_id, None, [DamageTest("ice", (150,))])
        test = self._save_on(3, pokemon_id, None, [DamageTest("ice", (150,))])
        self.assertEqual(test.created_at, datetime(2026, 11, 1, 12))
        self.assertEqual(test.updated_at, datetime(2026, 11, 2, 12))

    def test_test_in_another_place_is_a_new_test(self) -> None:
        pokemon_id = self.add("Muq")
        self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,))])
        test = self._save_on(2, pokemon_id, None, [DamageTest("water", (100,))])
        self.assertEqual(test.created_at, datetime(2026, 11, 2, 12))
        self.assertIsNone(test.updated_at)

    def test_changing_one_test_keeps_the_dates_of_the_others(self) -> None:
        pokemon_id = self.add("Muq")
        self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,)), DamageTest("water", (5,))])
        self._save_on(2, pokemon_id, None, [DamageTest("ice", (100,)), DamageTest("water", (6,))])
        ice, water = self.pokemon(pokemon_id).tests[None]
        self.assertIsNone(ice.updated_at)
        self.assertEqual(water.updated_at, datetime(2026, 11, 2, 12))

    def test_duplicate_keeps_the_dates_of_the_tests(self) -> None:
        pokemon_id = self.add("Muq")
        self._save_on(1, pokemon_id, None, [DamageTest("ice", (100,))])
        self._save_on(2, pokemon_id, None, [DamageTest("ice", (150,))])
        [copied] = self.pokemon(self.service.duplicate_pokemon(pokemon_id)).tests[None]
        self.assertEqual(copied.created_at, datetime(2026, 11, 1, 12))
        self.assertEqual(copied.updated_at, datetime(2026, 11, 2, 12))

    def test_editing_keeps_tests_of_remaining_skills(self) -> None:
        pokemon_id, skill_id = self._with_tests()
        [first, second] = self.pokemon(pokemon_id).spec.skills
        changed = replace(first, cooldown=99, element=Element.GRASS)
        new = PokemonSpec((second, changed), BasicAttackSpec(0, .75))  # ordem trocada
        self.service.save_pokemon(pokemon_id, "Muq", "", new)
        saved = self.pokemon(pokemon_id)
        self.assertEqual([skill.skill_id for skill in saved.spec.skills],
                         [second.skill_id, skill_id])
        self.assertEqual(saved.spec.skills[1].cooldown, 99)
        self.assertIn(skill_id, saved.tests)

    def test_removing_a_skill_removes_its_tests_only(self) -> None:
        pokemon_id, _skill_id = self._with_tests()
        [_first, second] = self.pokemon(pokemon_id).spec.skills
        self.service.save_pokemon(pokemon_id, "Muq", "",
                                  PokemonSpec((second,), BasicAttackSpec(0, .75)))
        self.assertEqual(list(self.pokemon(pokemon_id).tests), [None])

    def test_removing_basic_keeps_its_tests_for_when_it_returns(self) -> None:
        pokemon_id, _skill_id = self._with_tests()
        spec = self.pokemon(pokemon_id).spec
        self.service.save_pokemon(pokemon_id, "Muq", "", PokemonSpec(spec.skills))
        self.assertIsNone(self.pokemon(pokemon_id).spec.basic)
        self.assertIn(None, self.pokemon(pokemon_id).tests)

    def test_deleting_pokemon_removes_its_tests(self) -> None:
        pokemon_id, _skill_id = self._with_tests()
        self.service.delete_pokemon(pokemon_id)
        with self.database.engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM dps_damage_tests")).scalar()
        self.assertEqual(count, 0)

    def test_default_boss_is_not_created_again(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            database = Database.from_path(Path(directory) / "hunts.db")
            self.addCleanup(database.dispose)
            database.create_schema()
            service = DpsService(database)
            renamed = service.list_bosses()[0].id
            service.save_boss(renamed, "Terror", 300)
            database.create_schema()
            self.assertEqual([boss.name for boss in service.list_bosses()], ["Terror"])
            database.dispose()

    def ground_boss(self, source: DamageSource = DamageSource.EFFECTIVENESS) -> int:
        """Boss de 420 s que recebe 2x de Ground, com Steelix (Sand Tomb, 100 s) anexado."""
        boss_id = self.service.save_boss(
            None, "Onix", 420, (Element.GROUND,),
            {Element.GROUND: EffectivenessLevel.SUPER_EFFECTIVE})
        self.service.set_boss_damage_source(boss_id, source)
        return boss_id

    def steelix(self, boss_id: int, element: Element | None = Element.GROUND) -> tuple[int, int]:
        spec = PokemonSpec((replace(skills((0, 100))[0], name="Sand Tomb", element=element),))
        pokemon_id = self.service.save_pokemon(None, "Steelix", "", spec, boss_id)
        return pokemon_id, self.pokemon(pokemon_id).spec.skills[0].skill_id

    def test_existing_behavior_is_the_dummy_source(self) -> None:
        self.assertIs(self.default_boss.damage_source, DamageSource.DUMMY)
        self.assertEqual(self.default_boss.elements, ())
        self.assertEqual(self.default_boss.effectiveness, {})

    def test_effectiveness_multiplies_the_neutral_test_and_ignores_the_boss_dummy(self) -> None:
        boss_id = self.ground_boss()
        self.service.set_boss_dummy(boss_id, "water")
        pokemon_id, skill_id = self.steelix(boss_id)
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (1000,)), DamageTest("water", (9000,))])
        [entry] = self.service.ranking(boss_id)
        self.assertAlmostEqual(entry.breakdown.total, 1000 * 2 / 100 * 420)
        self.assertIn("1.000 ×2", entry.breakdown.lines[0].detail)
        self.assertEqual((entry.missing, entry.no_element), ((), ()))

    def test_unmarked_element_is_normal_and_every_level_changes_the_total(self) -> None:
        boss_id = self.ground_boss()
        pokemon_id, skill_id = self.steelix(boss_id, Element.ICE)
        self.service.save_damage_tests(pokemon_id, skill_id, [DamageTest("neutral", (1000,))])
        for level in EffectivenessLevel:
            self.service.save_boss(boss_id, "Onix", 420, effectiveness={Element.ICE: level})
            [entry] = self.service.ranking(boss_id)
            self.assertAlmostEqual(entry.breakdown.total, 1000 * level.multiplier / 100 * 420)
        self.service.save_boss(boss_id, "Onix", 420, effectiveness={})
        [entry] = self.service.ranking(boss_id)
        self.assertAlmostEqual(entry.breakdown.total, 1000 / 100 * 420)

    def test_effectiveness_lists_what_has_no_test_or_no_element(self) -> None:
        boss_id = self.ground_boss()
        pokemon_id, skill_id = self.steelix(boss_id, None)
        self.service.save_damage_tests(pokemon_id, skill_id, [DamageTest("neutral", (1000,))])
        [entry] = self.service.ranking(boss_id)
        self.assertEqual(entry.breakdown.total, 0)
        self.assertEqual((entry.missing, entry.no_element), ((), ("Sand Tomb",)))

        self.service.save_damage_tests(pokemon_id, skill_id, [])
        [entry] = self.service.ranking(boss_id)
        self.assertEqual((entry.missing, entry.no_element), (("Sand Tomb",), ("Sand Tomb",)))

    def test_real_damage_uses_only_tests_in_that_boss_without_multiplier(self) -> None:
        boss_id = self.ground_boss(DamageSource.REAL)
        other = self.service.save_boss(None, "Kame", 420)
        self.service.set_boss_damage_source(other, DamageSource.REAL)
        pokemon_id, skill_id = self.steelix(boss_id, None)
        self.service.set_boss_pokemons(other, [pokemon_id])
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (9000,)), DamageTest.in_boss(boss_id, (3000, 5000, None))])
        [entry] = self.service.ranking(boss_id)
        self.assertAlmostEqual(entry.breakdown.total, 4000 / 100 * 420)
        self.assertEqual((entry.missing, entry.no_element), ((), ()))
        [elsewhere] = self.service.ranking(other)
        self.assertEqual(elsewhere.breakdown.total, 0)
        self.assertEqual(elsewhere.missing, ("Sand Tomb",))

    def test_boss_tests_do_not_count_as_dummy_tests(self) -> None:
        pokemon_id, skill_id = self.steelix(self.default_boss.id)
        self.service.save_damage_tests(pokemon_id, skill_id,
                                       [DamageTest.in_boss(self.default_boss.id, (5000,))])
        for dummy, _label in DUMMY_OPTIONS:
            self.assertIsNone(self.pokemon(pokemon_id).damage_on(skill_id, dummy))
        [entry] = self.service.ranking(self.default_boss.id)
        self.assertEqual(entry.missing, ("Sand Tomb",))

    def test_boss_tests_validation(self) -> None:
        pokemon_id, skill_id = self.steelix(self.default_boss.id)
        boss_id = self.default_boss.id
        invalid = [
            ([DamageTest.in_boss(boss_id, (1,)), DamageTest.in_boss(boss_id, (2,))],
             "O boss Padrão aparece em mais de um"),
            ([DamageTest.in_boss(boss_id, (None,))], "Boss Padrão: informe"),
            ([DamageTest.in_boss(boss_id, (-1,))], "Boss Padrão: o dano precisa"),
            ([DamageTest.in_boss(999, (1,))], "Boss não encontrado"),
        ]
        for tests, message in invalid:
            with self.assertRaisesRegex(ValueError, message):
                self.service.save_damage_tests(pokemon_id, skill_id, tests)
        other = self.service.save_boss(None, "Kame", 420)
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest.in_boss(boss_id, (1,)), DamageTest.in_boss(other, (2,)),
            DamageTest("neutral", (3,))])
        self.assertEqual(len(self.pokemon(pokemon_id).tests[skill_id]), 3)

    def test_deleting_boss_removes_its_tests_and_profile(self) -> None:
        boss_id = self.ground_boss()
        pokemon_id, skill_id = self.steelix(boss_id)
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (1000,)), DamageTest.in_boss(boss_id, (2000,))])
        self.service.delete_boss(boss_id)
        self.assertEqual(self.pokemon(pokemon_id).tests[skill_id],
                         (DamageTest("neutral", (1000, None, None)),))
        with self.database.engine.connect() as connection:
            count = connection.execute(text("SELECT count(*) FROM dps_boss_effectiveness")).scalar()
        self.assertEqual(count, 0)

    def test_duplicate_copies_boss_tests(self) -> None:
        pokemon_id, skill_id = self.steelix(self.default_boss.id)
        self.service.save_damage_tests(pokemon_id, skill_id,
                                       [DamageTest.in_boss(self.default_boss.id, (2000,))])
        copy = self.pokemon(self.service.duplicate_pokemon(pokemon_id))
        self.assertEqual(copy.damage_in_boss(copy.spec.skills[0].skill_id, self.default_boss.id),
                         2000)

    def test_boss_profile_round_trip_and_validation(self) -> None:
        boss_id = self.service.save_boss(
            None, "Venusaur", 420, (Element.GRASS, Element.POISON),
            {Element.FIRE: EffectivenessLevel.EFFECTIVE,
             Element.NORMAL: EffectivenessLevel.NORMAL})
        boss = next(b for b in self.service.list_bosses() if b.id == boss_id)
        self.assertEqual(boss.elements, (Element.GRASS, Element.POISON))
        self.assertEqual(boss.effectiveness, {Element.FIRE: EffectivenessLevel.EFFECTIVE})

        # Salvar só nome e tempo não apaga o perfil; trocar o nível atualiza a mesma linha.
        self.service.save_boss(boss_id, "Venusaur", 300)
        self.service.save_boss(boss_id, "Venusaur", 300, (Element.GRASS,),
                               {Element.FIRE: EffectivenessLevel.INEFFECTIVE})
        boss = next(b for b in self.service.list_bosses() if b.id == boss_id)
        self.assertEqual(boss.elements, (Element.GRASS,))
        self.assertEqual(boss.effectiveness, {Element.FIRE: EffectivenessLevel.INEFFECTIVE})

        for elements in ((Element.FIRE, Element.FIRE),
                         (Element.FIRE, Element.ICE, Element.WATER)):
            with self.assertRaises(ValueError):
                self.service.save_boss(boss_id, "Venusaur", 300, elements)

    def test_version_8_database_keeps_ranking_and_dummy_tests(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hunts.db"
            database = Database.from_path(path)
            self.addCleanup(database.dispose)
            database.create_schema()
            with database.engine.begin() as connection:
                # Banco como a versão 8 deixava: sem origem do dano e sem testes em boss.
                connection.execute(text("DROP TABLE dps_damage_tests"))
                connection.execute(text(
                    "CREATE TABLE dps_damage_tests (id INTEGER PRIMARY KEY, "
                    "pokemon_id INTEGER NOT NULL, skill_id INTEGER, dummy VARCHAR(20) NOT NULL, "
                    "damage_1 INTEGER, damage_2 INTEGER, damage_3 INTEGER)"))
                for column in ("damage_source", "element_1", "element_2"):
                    connection.execute(text(f"ALTER TABLE dps_bosses DROP COLUMN {column}"))
                connection.execute(text("DROP TABLE dps_boss_effectiveness"))
                connection.execute(text(
                    "INSERT INTO dps_pokemons (id, name, note) VALUES (1, 'Steelix', '')"))
                connection.execute(text(
                    "INSERT INTO dps_skills (id, pokemon_id, position, name, shape, reach, "
                    "cooldown, efficiency) VALUES (5, 1, 1, '', 'area', 'ranged', 100, 1)"))
                connection.execute(text(
                    "INSERT INTO dps_damage_tests (pokemon_id, skill_id, dummy, damage_1) "
                    "VALUES (1, 5, 'neutral', 1000)"))
                connection.execute(text("INSERT INTO dps_boss_pokemons VALUES (1, 1)"))
                connection.execute(text("PRAGMA user_version = 8"))
            database.dispose()

            database = Database.from_path(path)
            self.addCleanup(database.dispose)
            self.assertEqual([m.version for m in database.create_schema()],
                             list(range(9, LATEST_VERSION + 1)))
            service = DpsService(database)
            [boss] = service.list_bosses()
            self.assertIs(boss.damage_source, DamageSource.DUMMY)
            [entry] = service.ranking(boss.id)
            self.assertAlmostEqual(entry.breakdown.total, 1000 / 100 * 420)
            # O teste antigo fica sem data de cadastro, e a modificação passa a ser registrada.
            [pokemon] = service.list_pokemons()
            [test] = pokemon.tests[5]
            self.assertIsNone(test.created_at)
            self.assertIsNone(test.updated_at)
            [saved] = service.save_damage_tests(1, 5, [DamageTest("neutral", (2000,))])
            self.assertIsNone(saved.created_at)
            self.assertIsNotNone(saved.updated_at)
            database.dispose()

    def test_version_7_database_loses_typed_damage_and_keeps_the_rest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hunts.db"
            database = Database.from_path(path)
            self.addCleanup(database.dispose)
            database.create_schema()
            with database.engine.begin() as connection:
                # Banco como a versão 7 deixava: dano digitado e boss sem dummy.
                connection.execute(text("ALTER TABLE dps_bosses DROP COLUMN dummy"))
                connection.execute(text("ALTER TABLE dps_skills ADD COLUMN damage INTEGER"))
                connection.execute(text("ALTER TABLE dps_pokemons ADD COLUMN basic_damage INTEGER"))
                connection.execute(text(
                    "INSERT INTO dps_pokemons (id, name, note, basic_damage, basic_efficiency) "
                    "VALUES (1, 'Steelix', '', 2110, 0.75), (2, 'Muq', '', NULL, NULL)"))
                connection.execute(text(
                    "INSERT INTO dps_skills (pokemon_id, position, name, shape, reach, damage, "
                    "cooldown, efficiency) VALUES (1, 1, 'Sand Tomb', 'area', 'ranged', 12160, "
                    "40, 1)"))
                connection.execute(text("PRAGMA user_version = 7"))
            database.dispose()

            database = Database.from_path(path)
            self.addCleanup(database.dispose)
            self.assertEqual([m.version for m in database.create_schema()][0], 8)
            with database.engine.connect() as connection:
                columns = {row[1] for row in connection.execute(
                    text("PRAGMA table_info(dps_skills)"))}
            self.assertNotIn("damage", columns)

            service = DpsService(database)
            [muq, steelix] = service.list_pokemons()
            self.assertIsNone(muq.spec.basic)
            self.assertEqual(steelix.spec.basic.efficiency, .75)
            self.assertEqual(steelix.spec.skills[0].cooldown, 40)
            self.assertEqual(steelix.spec.skills[0].damage, 0)
            self.assertEqual(service.list_bosses()[0].dummy, "neutral")
            database.dispose()


if __name__ == "__main__":
    unittest.main()
