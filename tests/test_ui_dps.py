"""Página DPS (plataforma offscreen)."""

import os
import unittest
from dataclasses import replace
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from app.services.dps_calculator import (  # noqa: E402
    BasicAttackSpec,
    BuffSpec,
    EffectivenessLevel,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
    Element,
)
from app.services.dps_service import (  # noqa: E402
    DamageSource,
    DamageTest,
    DpsService,
    DpsSettings,
)
from app.services.hunt_service import HuntService  # noqa: E402
from app.services.statistics_service import StatisticsService  # noqa: E402
from app.ui.dps.dps_dialogs import (  # noqa: E402
    DAMAGE_COLUMN,
    COOLDOWN_COLUMN,
    NAME_COLUMN,
    PERCENT_COLUMN,
    REACH_COLUMN,
    SHAPE_COLUMN,
    BossDialog,
    BossPokemonsDialog,
    DpsSettingsDialog,
    ELEMENT_COLUMN,
    PokemonDialog,
)
from app.ui.dps.dps_tests_dialog import AVERAGE_COLUMN, DamageTestsDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402
from app.ui.theme import ELEMENT_COLORS, apply_theme  # noqa: E402
from tests.helpers import memory_database  # noqa: E402


def area(damage: int, cooldown: float, name: str = "") -> SkillSpec:
    return SkillSpec(name, SkillShape.AREA, SkillReach.RANGED, damage, cooldown, 1)


class DpsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])
        apply_theme(cls.app)

    def setUp(self) -> None:
        self.database = memory_database()
        self.service = DpsService(self.database)

    def pokemon(self, pokemon_id: int):
        return next(p for p in self.service.list_pokemons() if p.id == pokemon_id)


class PokemonDialogTests(DpsTestCase):
    def fill(self, dialog: PokemonDialog, row: int, cooldown: str) -> None:
        dialog.skills_table.item(row, COOLDOWN_COLUMN).setText(cooldown)

    def test_builds_spec_from_the_form(self) -> None:
        dialog = PokemonDialog(DpsSettings())
        dialog.name_edit.setText(" Chumbin ")
        dialog.note_edit.setPlainText("+70")
        self.fill(dialog, 0, "8s")
        dialog.has_basic.setChecked(True)
        dialog.has_buff.setChecked(True)
        dialog.buff_cooldown_edit.setText("50")
        dialog.buff_basic_edit.setText("1,5")
        dialog.buff_duration_edit.setText("15")
        dialog.buff_spell_edit.setText("2")
        dialog.accept()

        self.assertEqual(dialog.result(), PokemonDialog.DialogCode.Accepted)
        self.assertEqual((dialog.pokemon_name(), dialog.note()), ("Chumbin", "+70"))
        self.assertEqual(dialog.spec(), PokemonSpec(
            (area(0, 8),), BasicAttackSpec(0, .75), BuffSpec(50, 1.5, 15, 2)))

    def test_damage_is_read_only(self) -> None:
        dialog = PokemonDialog(DpsSettings())
        item = dialog.skills_table.item(0, DAMAGE_COLUMN)
        self.assertFalse(item.flags() & Qt.ItemFlag.ItemIsEditable)
        self.assertEqual(item.text(), "sem teste")
        self.assertIsInstance(dialog.basic_damage_label, QLabel)

    def test_damage_follows_the_dummy_and_leaves_the_skill_element_alone(self) -> None:
        pokemon_id = self.service.save_pokemon(None, "Steelix", "", PokemonSpec(
            (replace(area(0, 40, "Sand Tomb"), element=Element.GROUND),), BasicAttackSpec(0, .75)))
        skill_id = self.pokemon(pokemon_id).spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (12000,)), DamageTest("ice", (6000,))])
        self.service.save_damage_tests(pokemon_id, None, [DamageTest("ice", (2110,))])

        dialog = PokemonDialog(DpsSettings(), self.pokemon(pokemon_id), dummy="ice")
        table = dialog.skills_table
        self.assertEqual(table.item(0, DAMAGE_COLUMN).text(), "6.000")
        self.assertEqual(dialog.basic_damage_label.text(), "2.110")

        dialog.dummy_combo.setCurrentIndex(dialog.dummy_combo.findData("neutral"))
        self.assertEqual(table.item(0, DAMAGE_COLUMN).text(), "12.000")
        self.assertEqual(dialog.basic_damage_label.text(), "sem teste")
        self.assertEqual(table.cellWidget(0, ELEMENT_COLUMN).currentData(), Element.GROUND)
        self.assertEqual(dialog.spec().skills[0].element, Element.GROUND)

    def test_shows_error_and_stays_open_on_invalid_values(self) -> None:
        dialog = PokemonDialog(DpsSettings())
        dialog.accept()
        self.assertIn("nome", dialog.error_label.text())

        dialog.name_edit.setText("Muq")
        self.fill(dialog, 0, "abc")
        dialog.accept()
        self.assertIn("Skill 1, recarga", dialog.error_label.text())

        self.fill(dialog, 0, "0")
        dialog.accept()
        self.assertIn("maior que zero", dialog.error_label.text())
        self.assertNotEqual(dialog.result(), PokemonDialog.DialogCode.Accepted)

    def test_class_change_suggests_percent_only_when_untouched(self) -> None:
        dialog = PokemonDialog(DpsSettings())
        table = dialog.skills_table
        shape = table.cellWidget(0, SHAPE_COLUMN)
        reach = table.cellWidget(0, REACH_COLUMN)
        percent = table.item(0, PERCENT_COLUMN)
        self.assertEqual(percent.text(), "100")

        reach.setCurrentIndex(reach.findData(SkillReach.MELEE))
        self.assertEqual(percent.text(), "100")  # Área + Melee
        shape.setCurrentIndex(shape.findData(SkillShape.TARGET))
        self.assertEqual(percent.text(), "75")
        reach.setCurrentIndex(reach.findData(SkillReach.RANGED))
        self.assertEqual(percent.text(), "100")

        percent.setText("60")  # alterado à mão: não muda mais
        reach.setCurrentIndex(reach.findData(SkillReach.MELEE))
        self.assertEqual(percent.text(), "60")

    def test_add_remove_and_default_names(self) -> None:
        dialog = PokemonDialog(DpsSettings())
        dialog.add_empty_skill()
        self.assertEqual(dialog.skills_table.rowCount(), 2)
        dialog.remove_current_skill()
        self.assertEqual(dialog.skills_table.rowCount(), 1)
        self.fill(dialog, 0, "2,5")
        dialog.skills_table.item(0, NAME_COLUMN).setText("Golpe")
        self.assertEqual(dialog.spec().skills, (area(0, 2.5, "Golpe"),))

    def test_editing_loads_every_field(self) -> None:
        spec = PokemonSpec(
            (SkillSpec("Golpe", SkillShape.TARGET, SkillReach.MELEE, 0, 2.5, .6),),
            BasicAttackSpec(0, .9), BuffSpec(50, 2, 15, 1.5))
        pokemon_id = self.service.save_pokemon(None, "Muq", "nota", spec)
        dialog = PokemonDialog(DpsSettings(), self.pokemon(pokemon_id))
        self.assertEqual(dialog.skills_table.item(0, COOLDOWN_COLUMN).text(), "2,5")
        self.assertEqual(dialog.spec(), spec)


class ElementFormTests(DpsTestCase):
    def test_form_saves_elements_and_keeps_skill_ids(self) -> None:
        spec = PokemonSpec((area(0, 10), area(0, 20)), BasicAttackSpec(0, .75))
        pokemon_id = self.service.save_pokemon(None, "Muq", "", spec)
        pokemon = self.service.list_pokemons()[0]
        first_id = pokemon.spec.skills[0].skill_id

        dialog = PokemonDialog(DpsSettings(), pokemon)
        combo = dialog.skills_table.cellWidget(0, ELEMENT_COLUMN)
        combo.setCurrentIndex(combo.findData(Element.GRASS))
        dialog.basic_element_combo.setCurrentIndex(
            dialog.basic_element_combo.findData(Element.FIRE))
        self.service.save_pokemon(pokemon_id, "Muq", "", dialog.spec())

        saved = self.service.list_pokemons()[0].spec
        self.assertEqual(saved.skills[0].element, Element.GRASS)
        self.assertEqual(saved.skills[0].skill_id, first_id)
        self.assertIsNone(saved.skills[1].element)
        self.assertEqual(saved.basic.element, Element.FIRE)


class DamageTestsDialogTests(DpsTestCase):
    def setUp(self) -> None:
        super().setUp()
        spec = PokemonSpec((area(0, 50, "Golpe"),), BasicAttackSpec(0, .75))
        self.pokemon_id = self.service.save_pokemon(None, "Chumbin", "", spec)
        self.dialog = DamageTestsDialog(self.service, self.pokemon(self.pokemon_id))

    def saved(self):
        return self.pokemon(self.pokemon_id).tests

    def fill(self, row: int, *damages: str) -> None:
        for column, damage in enumerate(damages, 1):
            self.dialog.table.item(row, column).setText(damage)

    def test_basic_comes_first_and_skills_follow(self) -> None:
        names = [self.dialog.targets_list.item(row).text()
                 for row in range(self.dialog.targets_list.count())]
        self.assertEqual(names, ["Ataque básico", "Golpe"])
        self.assertEqual(self.dialog.current_label.text(), "Ataque básico · Elemento: —")

    def test_average_updates_while_typing_and_saves_when_switching(self) -> None:
        self.dialog.add_test()
        self.fill(0, "20k", "21.000", "")
        self.assertEqual(self.dialog.table.item(0, AVERAGE_COLUMN).text(), "20.500")
        self.dialog.targets_list.setCurrentRow(1)
        self.assertEqual(self.dialog.table.rowCount(), 0)
        self.assertEqual(self.dialog.targets_list.item(0).text(), "Ataque básico (1)")
        self.assertEqual(self.saved(), {None: (DamageTest("neutral", (20000, 21000, None)),)})

    def test_new_row_suggests_a_free_dummy_and_rejects_repeated(self) -> None:
        self.dialog.add_test()
        self.dialog.add_test()
        second = self.dialog.table.cellWidget(1, 0)
        self.assertEqual(second.currentData(), "normal")
        self.fill(0, "100")
        self.fill(1, "200")
        second.setCurrentIndex(0)
        self.dialog.accept()
        self.assertIn("Neutro aparece em mais de um", self.dialog.error_label.text())
        self.assertEqual(self.saved(), {})

    def test_invalid_damage_keeps_the_current_skill_open(self) -> None:
        self.dialog.add_test()
        self.fill(0, "abc")
        self.dialog.targets_list.setCurrentRow(1)
        self.assertEqual(self.dialog.targets_list.currentRow(), 0)
        self.assertIn("não é um dano válido", self.dialog.error_label.text())
        self.dialog.show()
        self.dialog.reject()
        self.assertTrue(self.dialog.isVisible())  # fica aberta até corrigir
        self.assertEqual(self.saved(), {})
        self.dialog.table.removeRow(0)
        self.dialog.reject()
        self.assertFalse(self.dialog.isVisible())

    def test_empty_rows_are_ignored(self) -> None:
        self.dialog.add_test()
        self.dialog.accept()
        self.assertEqual(self.dialog.result(), DamageTestsDialog.DialogCode.Accepted)
        self.assertEqual(self.saved(), {})

    def test_saves_and_reloads_a_test_inside_a_boss(self) -> None:
        [boss] = self.service.list_bosses()
        self.dialog.add_test()
        combo = self.dialog.table.cellWidget(0, 0)
        combo.setCurrentIndex(combo.findData(boss.id))
        self.assertEqual(combo.currentText(), "Boss: Padrão")
        self.fill(0, "5k")
        self.dialog.accept()
        self.assertEqual(self.saved(), {None: (DamageTest.in_boss(boss.id, (5000, None, None)),)})

        reopened = DamageTestsDialog(self.service, self.pokemon(self.pokemon_id))
        self.assertEqual(reopened.table.cellWidget(0, 0).currentData(), boss.id)
        self.assertEqual(reopened.table.item(0, AVERAGE_COLUMN).text(), "5.000")

    def test_invalid_damage_in_a_boss_test_names_the_boss(self) -> None:
        [boss] = self.service.list_bosses()
        self.dialog.add_test()
        combo = self.dialog.table.cellWidget(0, 0)
        combo.setCurrentIndex(combo.findData(boss.id))
        self.fill(0, "abc")
        self.dialog.accept()
        self.assertIn("Boss: Padrão: “abc”", self.dialog.error_label.text())

    def test_reopening_loads_saved_values(self) -> None:
        self.service.save_damage_tests(self.pokemon_id, None,
                                       [DamageTest("ice", (1000, None, 3000))])
        dialog = DamageTestsDialog(self.service, self.pokemon(self.pokemon_id))
        self.assertEqual(dialog.table.cellWidget(0, 0).currentText(), "Ice")
        self.assertEqual(dialog.table.item(0, 1).text(), "1.000")
        self.assertEqual(dialog.table.item(0, 2).text(), "")
        self.assertEqual(dialog.table.item(0, AVERAGE_COLUMN).text(), "2.000")


class OtherDialogTests(DpsTestCase):
    def test_boss_dialog(self) -> None:
        [boss] = self.service.list_bosses()
        dialog = BossDialog([boss])
        dialog.name_edit.setText("padrão")
        dialog.accept()
        self.assertIn("Já existe", dialog.error_label.text())
        dialog.name_edit.setText("Terror")
        dialog.minutes_edit.setText("0")
        dialog.accept()
        self.assertIn("maior que zero", dialog.error_label.text())
        dialog.minutes_edit.setText("7,5")
        dialog.accept()
        self.assertEqual(dialog.result(), BossDialog.DialogCode.Accepted)
        self.assertEqual(dialog.time_limit_seconds(), 450)

        editing = BossDialog([boss], boss)
        self.assertEqual(editing.minutes_edit.text(), "7")

    def test_boss_dialog_edits_elements_and_effectiveness(self) -> None:
        [boss] = self.service.list_bosses()
        dialog = BossDialog([boss], boss)
        self.assertEqual(dialog.elements(), ())
        self.assertEqual(dialog.effectiveness(), {})
        self.assertEqual(len(dialog.effectiveness_combos), 18)

        first, second = dialog.element_combos
        first.setCurrentIndex(first.findData(Element.WATER))
        second.setCurrentIndex(second.findData(Element.WATER))
        dialog.accept()
        self.assertIn("diferentes", dialog.error_label.text())
        self.assertNotEqual(dialog.result(), BossDialog.DialogCode.Accepted)

        second.setCurrentIndex(0)
        combo = dialog.effectiveness_combos[Element.GRASS]
        combo.setCurrentIndex(combo.findData(EffectivenessLevel.SUPER_EFFECTIVE))
        dialog.accept()
        self.assertEqual(dialog.result(), BossDialog.DialogCode.Accepted)
        self.service.save_boss(boss.id, dialog.boss_name(), dialog.time_limit_seconds(),
                               dialog.elements(), dialog.effectiveness())

        [saved] = self.service.list_bosses()
        reopened = BossDialog([saved], saved)
        self.assertEqual(reopened.elements(), (Element.WATER,))
        self.assertEqual(reopened.effectiveness(),
                         {Element.GRASS: EffectivenessLevel.SUPER_EFFECTIVE})

    def test_boss_pokemons_search_keeps_hidden_marks(self) -> None:
        [boss] = self.service.list_bosses()
        first = self.service.save_pokemon(None, "Muq", "", PokemonSpec((area(0, 1),)))
        second = self.service.save_pokemon(None, "Jolt", "", PokemonSpec((area(0, 1),)))
        dialog = BossPokemonsDialog(boss, self.service.list_pokemons(), {first})
        dialog.search_edit.setText("jol")
        dialog._check_visible(Qt.CheckState.Checked)
        self.assertEqual(dialog.selected_ids(), {first, second})
        dialog._check_visible(Qt.CheckState.Unchecked)
        self.assertEqual(dialog.selected_ids(), {first})

    def test_settings_dialog(self) -> None:
        dialog = DpsSettingsDialog(DpsSettings(last_boss_id=9))
        self.assertEqual(dialog.turn_edit.text(), "2,5")
        dialog.turn_edit.setText("0")
        dialog.accept()
        self.assertIn("turno", dialog.error_label.text())
        dialog.turn_edit.setText("3")
        dialog.basic_edit.setText("50")
        dialog.accept()
        self.assertEqual(dialog.result(), DpsSettingsDialog.DialogCode.Accepted)
        self.assertEqual(dialog.settings(), DpsSettings(3, .75, 1, .5, 9))


class DpsPageTests(DpsTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.window = MainWindow(HuntService(self.database), StatisticsService(self.database),
                                 Path("mem.db"), dps_service=self.service)
        self.window.show()
        self.page = self.window.pages["dps"]
        self.ranking = self.page.ranking_tab
        self.pokemons = self.page.pokemons_tab
        [self.boss] = self.service.list_bosses()

    def tearDown(self) -> None:
        self.window.close()
        self.window.deleteLater()
        self.database.dispose()

    def add(self, name: str, damage: int, boss_id: int | None = None, dummy: str = "neutral") -> int:
        pokemon_id = self.service.save_pokemon(None, name, "", PokemonSpec((area(0, 10),)),
                                               boss_id or self.boss.id)
        skill_id = self.pokemon(pokemon_id).spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [DamageTest(dummy, (damage,))])
        return pokemon_id

    def add_unattached(self, name: str) -> int:
        return self.service.save_pokemon(None, name, "", PokemonSpec((area(0, 10),)))

    def test_empty_boss_shows_message(self) -> None:
        self.window.show_page("dps")
        self.assertIs(self.window.stack.currentWidget(), self.page)
        self.assertEqual(self.ranking._stack.currentIndex(), 0)
        self.assertFalse(self.ranking._remove_button.isEnabled())
        self.assertEqual(self.ranking.boss_combo.currentText(), "Padrão · 7min")
        self.assertEqual(self.pokemons._stack.currentIndex(), 0)
        self.assertFalse(self.pokemons._edit_button.isEnabled())

    def test_ranking_selects_leader_and_shows_breakdown(self) -> None:
        self.add("Fraco", 1000)
        self.add("Forte", 2000)
        self.window.show_page("dps")
        self.assertEqual(self.ranking._stack.currentIndex(), 1)
        self.assertEqual(self.ranking._ranking.count(), 2)
        self.assertEqual(self.ranking.selected_entry().pokemon.name, "Forte")
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 84.000 · DPS: 200")
        table = self.ranking._lines_table
        self.assertEqual(table.model().index(0, 0).data(), "Skill 1")
        self.assertEqual(table.model().index(0, 1).data(), "Área · Ranged · 2.000 / 10s · 100%")
        self.assertEqual(table.model().index(0, 3).data(), "100,0%")

        self.ranking._ranking.setCurrentRow(1)
        self.assertEqual(self.ranking.selected_entry().pokemon.name, "Fraco")
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 42.000 · DPS: 100")

    def test_dummy_selector_recalculates_warns_and_is_saved_per_boss(self) -> None:
        self.add("Muq", 1000)
        terror = self.service.save_boss(None, "Terror", 420)
        self.window.show_page("dps")
        self.assertEqual(self.ranking.dummy_combo.currentData(), "neutral")
        self.assertTrue(self.ranking._detail_warning.isHidden())

        combo = self.ranking.dummy_combo
        combo.setCurrentIndex(combo.findData("water"))
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 0 · DPS: 0")
        self.assertEqual(self.ranking._detail_warning.text(),
                         "Sem teste no dummy Water: Skill 1.")
        self.assertFalse(self.ranking._detail_warning.isHidden())
        padrao = next(b for b in self.service.list_bosses() if b.id == self.boss.id)
        self.assertEqual(padrao.dummy, "water")

        self.ranking.show_boss(terror)
        self.assertEqual(combo.currentData(), "neutral")
        self.ranking.show_boss(self.boss.id)
        self.assertEqual(combo.currentData(), "water")

    def choose_source(self, source: DamageSource) -> None:
        combo = self.ranking.source_combo
        combo.setCurrentIndex(combo.findData(source))

    def test_source_selector_recalculates_and_only_dummy_shows_the_dummy_combo(self) -> None:
        pokemon_id = self.service.save_pokemon(None, "Muq", "", PokemonSpec(
            (replace(area(0, 10), element=Element.GROUND),)), self.boss.id)
        skill_id = self.pokemon(pokemon_id).spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (1000,)), DamageTest.in_boss(self.boss.id, (3000,))])
        self.ranking.save_boss(self.boss.id, "Padrão", 420, (Element.WATER,),
                               {Element.GROUND: EffectivenessLevel.SUPER_EFFECTIVE})
        self.window.show_page("dps")
        self.assertEqual(self.ranking.source_combo.currentData(), DamageSource.DUMMY)
        self.assertFalse(self.ranking.dummy_combo.isHidden())
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 42.000 · DPS: 100")
        summary = self.ranking._boss_summary.text()
        self.assertIn("Elemento", summary)
        self.assertIn(ELEMENT_COLORS["Water"], summary)
        self.assertIn("Super&nbsp;Efetivo&nbsp;2x", summary)
        self.assertIn(ELEMENT_COLORS["Ground"], summary)

        self.choose_source(DamageSource.EFFECTIVENESS)
        self.assertTrue(self.ranking.dummy_combo.isHidden())
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 84.000 · DPS: 200")
        self.assertEqual(self.ranking._lines_table.model().index(0, 1).data(),
                         "Área · Ranged · 1.000 ×2 / 10s · 100%")

        self.choose_source(DamageSource.REAL)
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 126.000 · DPS: 300")
        [boss] = self.service.list_bosses()
        self.assertIs(boss.damage_source, DamageSource.REAL)

    def test_source_warnings(self) -> None:
        self.add("Muq", 1000)
        self.window.show_page("dps")
        self.assertTrue(self.ranking._boss_warning.isHidden())

        self.choose_source(DamageSource.EFFECTIVENESS)
        self.assertFalse(self.ranking._boss_warning.isHidden())  # nenhuma fraqueza marcada
        self.assertEqual(self.ranking._detail_warning.text(), "Sem elemento: Skill 1.")
        self.assertFalse(self.ranking._detail_warning.isHidden())

        self.choose_source(DamageSource.REAL)
        self.assertTrue(self.ranking._boss_warning.isHidden())
        self.assertEqual(self.ranking._detail_warning.text(), "Sem teste neste boss: Skill 1.")

    def test_source_is_saved_per_boss(self) -> None:
        self.add("Muq", 1000)
        terror = self.service.save_boss(None, "Terror", 420)
        self.window.show_page("dps")
        self.choose_source(DamageSource.REAL)
        self.ranking.show_boss(terror)
        self.assertEqual(self.ranking.source_combo.currentData(), DamageSource.DUMMY)
        self.ranking.show_boss(self.boss.id)
        self.assertEqual(self.ranking.source_combo.currentData(), DamageSource.REAL)

    def test_selection_survives_refresh_and_reorder(self) -> None:
        low = self.add("Fraco", 1000)
        self.add("Forte", 2000)
        self.window.show_page("dps")
        self.ranking._ranking.setCurrentRow(1)
        skill_id = self.pokemon(low).spec.skills[0].skill_id
        self.service.save_damage_tests(low, skill_id, [DamageTest("neutral", (9000,))])
        self.page.refresh()
        self.assertEqual(self.ranking._ranking.currentRow(), 0)
        self.assertEqual(self.ranking.selected_entry().pokemon.name, "Fraco")

    def test_changing_boss_filters_pokemons_and_is_remembered(self) -> None:
        self.add("Geral", 1000)
        terror = self.service.save_boss(None, "Terror", 300)
        self.add("Só Terror", 1000, terror)
        self.window.show_page("dps")
        self.ranking.show_boss(terror)
        self.assertEqual(self.ranking.selected_entry().pokemon.name, "Só Terror")
        self.assertEqual(self.ranking.boss_combo.currentText(), "Terror · 5min")
        self.assertEqual(self.service.settings().last_boss_id, terror)

        reopened = MainWindow(HuntService(self.database), StatisticsService(self.database),
                              Path("mem.db"), dps_service=self.service)
        reopened.show_page("dps")
        self.assertEqual(reopened.pages["dps"].ranking_tab.current_boss.id, terror)
        reopened.close()
        reopened.deleteLater()

    def test_remove_from_boss_keeps_the_pokemon_registered(self) -> None:
        self.add("Muq", 1000)
        self.window.show_page("dps")
        self.ranking.remove_selected()
        self.assertEqual(self.ranking._stack.currentIndex(), 0)
        [pokemon] = self.service.list_pokemons()
        self.assertEqual((pokemon.name, pokemon.boss_ids), ("Muq", frozenset()))
        self.assertEqual(self.pokemons.selected_pokemon().name, "Muq")
        self.assertEqual(self.pokemons._table.model().index(0, 4).data(), "—")

    def test_pokemons_tab_lists_unattached_and_shows_skills(self) -> None:
        self.add("Muq", 1000)
        self.add_unattached("Avulso")
        spec = PokemonSpec((area(0, 2.5, "Golpe"),), BasicAttackSpec(0, .75),
                           BuffSpec(50, 2, 15, 1.5))
        chumbin = self.service.save_pokemon(None, "Chumbin", "+70", spec, self.boss.id)
        skill_id = self.pokemon(chumbin).spec.skills[0].skill_id
        self.service.save_damage_tests(chumbin, skill_id, [DamageTest("ice", (1000,))])
        self.service.save_damage_tests(chumbin, None, [DamageTest("ice", (2700,))])
        self.window.show_page("dps")

        table = self.pokemons._table
        self.assertEqual(table.visible_row_count(), 3)
        self.assertEqual(self.ranking._ranking.count(), 2)  # o avulso só aparece aqui
        self.assertEqual(table.model().index(0, 0).data(), "Avulso")
        self.assertEqual(table.model().index(0, 4).data(), "—")

        self.pokemons.select_pokemon(chumbin)
        row = [table.model().index(1, column).data() for column in range(6)]
        self.assertEqual(row, ["Chumbin", "1", "75%",
                               "básico ×2 por 15s + magia ×1,5 / 50s", "Padrão", "+70"])
        skills = self.pokemons._skills_table.model()
        self.assertEqual([skills.index(0, column).data() for column in range(8)],
                         ["Golpe", "Área", "Ranged", "—", "sem teste", "2,5", "100%", "1"])
        self.assertEqual(self.pokemons._detail_basic.text(), "Ataque básico: sem teste")

        combo = self.pokemons._dummy_combo
        combo.setCurrentIndex(combo.findData("ice"))
        self.assertEqual(skills.index(0, 4).data(), "1.000")
        self.assertEqual(self.pokemons._detail_basic.text(), "Ataque básico: 2.700")

    def test_search_keeps_a_visible_selection(self) -> None:
        self.add_unattached("Jolt")
        muq = self.add_unattached("Muq")
        self.window.show_page("dps")
        self.pokemons.select_pokemon(muq)
        self.pokemons._search.setText("jol")
        self.assertEqual(self.pokemons._table.visible_row_count(), 1)
        self.assertEqual(self.pokemons.selected_pokemon().name, "Jolt")
        self.assertEqual(self.pokemons._count_label.text(), "1 de 2 pokémons")
        self.pokemons._search.setText("nada")
        self.assertIsNone(self.pokemons.selected_pokemon())
        self.assertFalse(self.pokemons._edit_button.isEnabled())

    def test_duplicate_selects_copy_and_delete_updates_both_tabs(self) -> None:
        self.add("Muq", 1000)
        self.window.show_page("dps")
        self.pokemons.duplicate_selected()
        copy = self.pokemons.selected_pokemon()
        self.assertEqual(copy.name, "Muq (cópia)")
        self.assertEqual(self.ranking._ranking.count(), 2)  # a cópia fica nos mesmos bosses
        self.assertEqual(self.ranking._entries[1].breakdown.total, 42000)  # e leva os testes
        self.pokemons.delete_pokemon(copy.id)
        self.assertEqual(self.ranking._ranking.count(), 1)
        self.assertEqual(self.pokemons.selected_pokemon().name, "Muq")

    def test_pokemons_tab_shows_test_counts_and_enables_tests(self) -> None:
        pokemon_id = self.add("Muq", 1000)
        skill_id = self.service.list_pokemons()[0].spec.skills[0].skill_id
        self.service.save_damage_tests(pokemon_id, skill_id, [
            DamageTest("neutral", (1000, None, None)), DamageTest("ice", (900, None, None))])
        self.window.show_page("dps")
        self.assertTrue(self.pokemons._tests_button.isEnabled())
        skills = self.pokemons._skills_table.model()
        self.assertEqual(skills.index(0, 7).data(), "2")
        self.assertEqual(skills.index(0, 4).data(), "1.000")

    def test_turn_setting_recalculates_after_refresh(self) -> None:
        pokemon_id = self.service.save_pokemon(None, "Básico", "",
                                               PokemonSpec((), BasicAttackSpec(0, 1)), self.boss.id)
        self.service.save_damage_tests(pokemon_id, None, [DamageTest("neutral", (1000,))])
        self.window.show_page("dps")
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 168.000 · DPS: 400")
        self.service.update_settings(DpsSettings(basic_turn_seconds=5))
        self.page.refresh()
        self.assertEqual(self.ranking._detail_summary.text(), "Dano total: 84.000 · DPS: 200")

    def test_delete_boss_action_is_disabled_for_the_last_boss(self) -> None:
        self.window.show_page("dps")
        self.assertFalse(self.ranking._delete_boss_action.isEnabled())
        self.ranking.save_boss(None, "Terror", 300)
        self.assertTrue(self.ranking._delete_boss_action.isEnabled())
        self.assertEqual(self.ranking.current_boss.name, "Terror")
        self.assertEqual(self.pokemons._boss_names[self.ranking.current_boss.id], "Terror")


if __name__ == "__main__":
    unittest.main()
