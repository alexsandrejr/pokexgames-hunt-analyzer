"""Exportação e importação dos cadastros do DPS."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.database.database import Database  # noqa: E402
from app.services.backup_service import BackupService  # noqa: E402
from app.services.dps_calculator import (  # noqa: E402
    BasicAttackSpec,
    BuffSpec,
    EffectivenessLevel,
    Element,
    PokemonSpec,
    SkillReach,
    SkillShape,
    SkillSpec,
)
from app.services.dps_service import DamageSource, DamageTest, DpsService  # noqa: E402
from app.services.dps_transfer import (  # noqa: E402
    FORMAT_ID,
    DpsTransferService,
    ImportAction,
    ImportKind,
    bundle_to_json,
    parse_bundle,
    read_bundle,
)
from app.ui.dps.dps_transfer_dialogs import (  # noqa: E402
    ACTION_COLUMN,
    DpsExportDialog,
    DpsImportDialog,
)
from app.ui.dps.dps_widget import DpsPage  # noqa: E402
from tests.helpers import memory_database  # noqa: E402


def skill(name: str, cooldown: float = 10) -> SkillSpec:
    return SkillSpec(name, SkillShape.TARGET, SkillReach.MELEE, 0, cooldown, .75, Element.ICE)


SPEC = PokemonSpec((skill("Golpe"), skill("Outro", 20)), BasicAttackSpec(0, .5, Element.FIRE),
                   BuffSpec(60, 1.5, 10, 2))
CREATED = datetime(2026, 1, 2, 3, 4, 5)
UPDATED = datetime(2026, 2, 3, 4, 5, 6)


class TransferTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.source = self._database()
        self.target = self._database()
        self.source_dps = DpsService(self.source)
        self.target_dps = DpsService(self.target)
        self.source_transfer = DpsTransferService(self.source)
        self.target_transfer = DpsTransferService(self.target)

    def _database(self) -> Database:
        database = memory_database()
        self.addCleanup(database.dispose)
        return database

    def _seed(self) -> tuple[int, int]:
        """Na origem: um boss completo e um pokémon nele, com testes em dummy e no boss."""
        boss_id = self.source_dps.save_boss(
            None, "Venusaur", 300, (Element.GRASS, Element.POISON),
            {Element.FIRE: EffectivenessLevel.SUPER_EFFECTIVE})
        self.source_dps.set_boss_damage_source(boss_id, DamageSource.REAL)
        self.source_dps.set_boss_dummy(boss_id, "ice")
        pokemon_id = self.source_dps.save_pokemon(None, "Muq", "Com boost", SPEC, boss_id)
        skill_id = self._pokemon(self.source_dps, "Muq").spec.skills[0].skill_id
        with patch("app.services.dps_service.datetime") as clock:
            clock.now.return_value = CREATED
            self.source_dps.save_damage_tests(pokemon_id, skill_id, [
                DamageTest("neutral", (100, 200, None)), DamageTest.in_boss(boss_id, (300,))])
            self.source_dps.save_damage_tests(pokemon_id, None, [DamageTest("ice", (50,))])
            clock.now.return_value = UPDATED
            self.source_dps.save_damage_tests(pokemon_id, None, [DamageTest("ice", (60,))])
        return boss_id, pokemon_id

    @staticmethod
    def _pokemon(service: DpsService, name: str):
        return next(pokemon for pokemon in service.list_pokemons() if pokemon.name == name)

    def _bundle(self, boss_ids=None, pokemon_ids=None):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "cadastros.json"
            self.source_transfer.export_file(
                path,
                {b.id for b in self.source_dps.list_bosses()} if boss_ids is None else boss_ids,
                {p.id for p in self.source_dps.list_pokemons()} if pokemon_ids is None
                else pokemon_ids)
            return read_bundle(path)

    def _import(self, bundle, *choices: tuple[str, ImportAction]):
        """Importa com o padrão, trocando as ações dos nomes citados em ``choices``."""
        chosen = dict(choices)
        items = [replace(item, action=chosen.get(item.name, item.action))
                 for item in self.target_transfer.plan(bundle)]
        return self.target_transfer.apply(bundle, items)


class RoundTripTests(TransferTestCase):
    def test_everything_arrives_in_an_empty_database(self) -> None:
        self._seed()
        result = self._import(self._bundle())
        # "Padrão" existe nos dois bancos e, por padrão, é pulado.
        self.assertEqual((result.created, result.replaced, result.skipped), (2, 0, 1))

        boss = next(b for b in self.target_dps.list_bosses() if b.name == "Venusaur")
        self.assertEqual(boss.time_limit_seconds, 300)
        self.assertEqual(boss.dummy, "ice")
        self.assertIs(boss.damage_source, DamageSource.REAL)
        self.assertEqual(boss.elements, (Element.GRASS, Element.POISON))
        self.assertEqual(boss.effectiveness, {Element.FIRE: EffectivenessLevel.SUPER_EFFECTIVE})

        pokemon = self._pokemon(self.target_dps, "Muq")
        self.assertEqual(pokemon.note, "Com boost")
        self.assertEqual(pokemon.spec, SPEC)
        self.assertEqual(pokemon.boss_ids, {boss.id})
        skill_id = pokemon.spec.skills[0].skill_id
        self.assertEqual(pokemon.tests[skill_id], (DamageTest("neutral", (100, 200, None)),
                                                   DamageTest.in_boss(boss.id, (300, None, None))))
        self.assertEqual(pokemon.tests[None], (DamageTest("ice", (60, None, None)),))
        self.assertNotIn(pokemon.spec.skills[1].skill_id, pokemon.tests)

    def test_dates_of_the_tests_are_kept(self) -> None:
        self._seed()
        self._import(self._bundle())
        pokemon = self._pokemon(self.target_dps, "Muq")
        [test] = pokemon.tests[None]
        self.assertEqual((test.created_at, test.updated_at), (CREATED, UPDATED))
        first = pokemon.tests[pokemon.spec.skills[0].skill_id][0]
        self.assertEqual((first.created_at, first.updated_at), (CREATED, None))

    def test_ranking_is_the_same_on_both_sides(self) -> None:
        self._seed()
        self._import(self._bundle())
        ranking = {}
        for name, service in (("origem", self.source_dps), ("destino", self.target_dps)):
            boss = next(b for b in service.list_bosses() if b.name == "Venusaur")
            ranking[name] = service.ranking(boss.id)[0].breakdown.total
        self.assertGreater(ranking["origem"], 0)
        self.assertEqual(ranking["origem"], ranking["destino"])

    def test_export_only_what_was_chosen(self) -> None:
        boss_id, _pokemon_id = self._seed()
        other = self.source_dps.save_pokemon(None, "Jolt", "", SPEC)
        bundle = self._bundle({boss_id}, {other})
        self.assertEqual([b.name for b in bundle.bosses], ["Venusaur"])
        self.assertEqual([p.name for p in bundle.pokemons], ["Jolt"])

    def test_export_does_not_change_the_database(self) -> None:
        self._seed()
        before = self.source_dps.list_pokemons()
        self._bundle()
        self.assertEqual(self.source_dps.list_pokemons(), before)


class ConflictTests(TransferTestCase):
    def test_default_is_to_skip_repeated_names(self) -> None:
        self._seed()
        self.target_dps.save_pokemon(None, "muq", "minha nota", PokemonSpec((skill("Meu"),)))
        result = self._import(self._bundle())
        self.assertEqual(result.skipped, 2)  # Padrão e muq
        [pokemon] = [p for p in self.target_dps.list_pokemons() if p.name.casefold() == "muq"]
        self.assertEqual(pokemon.note, "minha nota")

    def test_replace_changes_the_card_and_the_tests_but_keeps_the_id_and_bosses(self) -> None:
        self._seed()
        local_boss = self.target_dps.list_bosses()[0]
        local = self.target_dps.save_pokemon(None, "Muq", "antiga", PokemonSpec((skill("Meu"),)),
                                             local_boss.id)
        self.target_dps.save_damage_tests(local, None, [DamageTest("water", (999,))])
        result = self._import(self._bundle(), ("Muq", ImportAction.REPLACE))
        self.assertEqual(result.replaced, 1)

        pokemon = self._pokemon(self.target_dps, "Muq")
        self.assertEqual(pokemon.id, local)
        self.assertEqual(pokemon.note, "Com boost")
        self.assertEqual(pokemon.spec, SPEC)
        self.assertEqual(pokemon.tests[None], (DamageTest("ice", (60, None, None)),))
        self.assertIn(local_boss.id, pokemon.boss_ids)  # o vínculo que já existia continua
        self.assertEqual(len(pokemon.boss_ids), 2)

    def test_copy_keeps_the_current_one_and_gets_a_free_name(self) -> None:
        self._seed()
        self.target_dps.save_pokemon(None, "Muq", "minha", PokemonSpec((skill("Meu"),)))
        self.target_dps.save_pokemon(None, "Muq (importado)", "", PokemonSpec((skill("Meu"),)))
        self._import(self._bundle(), ("Muq", ImportAction.CREATE))
        names = sorted(p.name for p in self.target_dps.list_pokemons())
        self.assertEqual(names, ["Muq", "Muq (importado 2)", "Muq (importado)"])
        self.assertEqual(self._pokemon(self.target_dps, "Muq").note, "minha")

    def test_replace_boss_keeps_its_pokemons(self) -> None:
        self._seed()
        boss = self.target_dps.save_boss(None, "Venusaur", 60)
        local = self.target_dps.save_pokemon(None, "Local", "", PokemonSpec((skill("X"),)), boss)
        self._import(self._bundle(), ("Venusaur", ImportAction.REPLACE))
        [saved] = [b for b in self.target_dps.list_bosses() if b.id == boss]
        self.assertEqual(saved.time_limit_seconds, 300)
        self.assertIn(local, saved.pokemon_ids)

    def test_pokemon_follows_a_copied_boss(self) -> None:
        self._seed()
        original = self.target_dps.save_boss(None, "Venusaur", 60)
        self._import(self._bundle(), ("Venusaur", ImportAction.CREATE))
        copy = next(b for b in self.target_dps.list_bosses() if b.name == "Venusaur (importado)")
        pokemon = self._pokemon(self.target_dps, "Muq")
        self.assertIn(copy.id, pokemon.boss_ids)
        self.assertNotIn(original, pokemon.boss_ids)

    def test_skipped_boss_still_receives_the_pokemon_by_name(self) -> None:
        self._seed()
        local = self.target_dps.save_boss(None, "VENUSAUR", 60)
        self._import(self._bundle())
        [saved] = [b for b in self.target_dps.list_bosses() if b.id == local]
        self.assertEqual(saved.time_limit_seconds, 60)
        pokemon = self._pokemon(self.target_dps, "Muq")
        self.assertEqual(pokemon.boss_ids, {local})
        skill_id = pokemon.spec.skills[0].skill_id
        self.assertEqual(pokemon.damage_in_boss(skill_id, local), 300)

    def test_tests_in_an_unknown_boss_stay_out_and_are_counted(self) -> None:
        _boss_id, pokemon_id = self._seed()
        bundle = self._bundle(set(), {pokemon_id})  # o boss não vai no arquivo
        result = self._import(bundle)
        self.assertEqual((result.dropped_tests, result.dropped_links), (1, 1))
        pokemon = self._pokemon(self.target_dps, "Muq")
        self.assertEqual(pokemon.boss_ids, frozenset())
        skill_id = pokemon.spec.skills[0].skill_id
        self.assertEqual(pokemon.tests[skill_id], (DamageTest("neutral", (100, 200, None)),))

    def test_two_with_the_same_name_in_the_file_replace_one_local_each(self) -> None:
        self.source_dps.save_pokemon(None, "Muq", "A", SPEC)
        self.source_dps.save_pokemon(None, "Muq", "B", SPEC)
        local = self.target_dps.save_pokemon(None, "Muq", "local", SPEC)
        bundle = self._bundle()
        items = [replace(item, action=ImportAction.REPLACE) if item.existing_id == local else item
                 for item in self.target_transfer.plan(bundle)]
        self.target_transfer.apply(bundle, items)
        self.assertEqual(len([p for p in self.target_dps.list_pokemons() if p.name == "Muq"]), 2)
        self.assertEqual(next(p for p in self.target_dps.list_pokemons() if p.id == local).note,
                         "A")

    def test_failure_in_the_middle_changes_nothing(self) -> None:
        self._seed()
        bundle = self._bundle()
        before = self.target_dps.list_bosses()
        with patch("app.services.dps_transfer.apply_spec", side_effect=RuntimeError("falhou")):
            with self.assertRaises(RuntimeError):
                self._import(bundle)
        self.assertEqual(self.target_dps.list_bosses(), before)
        self.assertEqual(self.target_dps.list_pokemons(), [])


class InvalidFileTests(TransferTestCase):
    def _valid(self) -> dict:
        self._seed()
        return json.loads(bundle_to_json(self._bundle()))

    def _assert_rejected(self, data: dict, fragment: str) -> None:
        with self.assertRaises(ValueError) as caught:
            parse_bundle(json.dumps(data))
        self.assertIn(fragment, str(caught.exception))

    def test_not_a_dps_file(self) -> None:
        for text in ("não é json", "[]", '{"Session": {}}', '{"format": "outro", "version": 1}'):
            with self.assertRaises(ValueError, msg=text):
                parse_bundle(text)

    def test_file_from_a_newer_version(self) -> None:
        with self.assertRaisesRegex(ValueError, "versão mais nova"):
            parse_bundle(json.dumps({"format": FORMAT_ID, "version": 99}))

    def test_empty_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "não tem bosses nem pokémons"):
            parse_bundle(json.dumps({"format": FORMAT_ID, "version": 1,
                                     "bosses": [], "pokemons": []}))

    def test_nan_is_rejected(self) -> None:
        text = bundle_to_json(self._bundle_with_pokemon()).replace('"cooldown": 10.0', '"cooldown": NaN', 1)
        self.assertIn("NaN", text)
        with self.assertRaisesRegex(ValueError, "JSON válido"):
            parse_bundle(text)

    def _bundle_with_pokemon(self):
        self.source_dps.save_pokemon(None, "Muq", "", SPEC)
        return self._bundle()

    def test_broken_fields_give_a_message_and_not_a_crash(self) -> None:
        cases = [
            (lambda d: d["pokemons"][0].pop("skills"), "incompleto"),
            (lambda d: d["pokemons"][0].update(name=""), "vazio"),
            (lambda d: d["pokemons"][0].update(name=123), "texto"),
            (lambda d: d["pokemons"][0].update(skills="x"), "lista"),
            (lambda d: d["pokemons"][0]["skills"][0].update(cooldown=0), "recarga"),
            (lambda d: d["pokemons"][0]["skills"][0].update(cooldown=True), "número"),
            (lambda d: d["pokemons"][0]["skills"][0].update(cooldown=10 ** 400), "incompleto"),
            (lambda d: d["pokemons"][0]["skills"][0].update(efficiency=2), "aproveitamento"),
            (lambda d: d["pokemons"][0]["skills"][0].update(element="crystal"), "elemento"),
            (lambda d: d["pokemons"][0]["skills"][0]["tests"][0].update(damages=[-1]), "maior"),
            (lambda d: d["pokemons"][0]["skills"][0]["tests"][0].update(damages=[10 ** 20]), "dano"),
            (lambda d: d["pokemons"][0]["skills"][0]["tests"][0].update(damages=[1, 2, 3, 4]),
             "no máximo"),
            (lambda d: d["pokemons"][0]["skills"][0]["tests"][0].update(created_at="ontem"),
             "data"),
            (lambda d: d["pokemons"][0]["skills"][0]["tests"][0].update(dummy="crystal"), "dummy"),
            (lambda d: d["bosses"].append(dict(d["bosses"][0])), "mais de uma vez"),
            (lambda d: d["bosses"][0].update(time_limit_seconds=0), "tempo limite"),
            (lambda d: d["bosses"][0].update(dummy="x"), "dummy"),
            (lambda d: d["bosses"][0].update(damage_source="x"), "origem"),
            (lambda d: d["bosses"][0].update(elements=["fire", "ice", "water"]), "elementos"),
            (lambda d: d["bosses"][0].update(effectiveness={"fire": "x"}), "efetividade"),
        ]
        valid = self._valid()
        for change, fragment in cases:
            data = json.loads(json.dumps(valid))
            change(data)
            with self.subTest(fragment=fragment):
                self._assert_rejected(data, fragment)

    def test_missing_file_and_binary_file(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Não foi possível ler"):
                read_bundle(Path(folder) / "nao_existe.json")
            binary = Path(folder) / "foto.json"
            binary.write_bytes(b"\xff\xfe\x00\x01")
            with self.assertRaisesRegex(ValueError, "não é uma exportação"):
                read_bundle(binary)


class TransferDialogTests(TransferTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_export_dialog_starts_with_everything_checked_and_requires_a_choice(self) -> None:
        boss_id, pokemon_id = self._seed()
        dialog = DpsExportDialog(self.source_dps.list_bosses(), self.source_dps.list_pokemons())
        self.assertIn(boss_id, dialog.boss_ids())
        self.assertEqual(dialog.pokemon_ids(), {pokemon_id})
        for widget in (dialog.bosses_list, dialog.pokemons_list):
            for row in range(widget.count()):
                widget.item(row).setCheckState(widget.item(row).checkState().Unchecked)
        dialog.accept()
        self.assertIn("ao menos um", dialog.error_label.text())
        self.assertEqual(dialog.result(), 0)

    def test_import_dialog_defaults_and_replace_warning(self) -> None:
        self._seed()
        self.target_dps.save_pokemon(None, "Muq", "", SPEC)
        bundle = self._bundle()
        dialog = DpsImportDialog(bundle, self.target_transfer.plan(bundle))
        by_name = {item.name: item for item in dialog.chosen_items()}
        self.assertIs(by_name["Muq"].action, ImportAction.SKIP)
        self.assertIs(by_name["Venusaur"].action, ImportAction.CREATE)
        self.assertTrue(dialog.replace_warning.isHidden())

        row = next(row for row, item in enumerate(dialog.chosen_items())
                   if item.kind is ImportKind.POKEMON)
        combo = dialog.table.cellWidget(row, ACTION_COLUMN)
        self.assertEqual([combo.itemText(i) for i in range(combo.count())],
                         ["Pular", "Substituir", "Criar cópia"])
        combo.setCurrentIndex(combo.findData(ImportAction.REPLACE))
        self.assertFalse(dialog.replace_warning.isHidden())
        self.assertIs(dialog.chosen_items()[row].action, ImportAction.REPLACE)

    def test_page_backs_up_only_when_replacing_and_stops_if_backup_fails(self) -> None:
        self._seed()
        self.target_dps.save_pokemon(None, "Muq", "local", SPEC)
        bundle = self._bundle()
        with tempfile.TemporaryDirectory() as folder:
            backups = BackupService(self.target, Path(folder))  # banco em memória: backup falha
            page = DpsPage(self.target_dps, backups=backups)
            items = self.target_transfer.plan(bundle)

            page.apply_import(bundle, items)  # sem substituir, não precisa de backup
            self.assertEqual(self._pokemon(self.target_dps, "Muq").note, "local")
            self.assertIn("Venusaur", [b.name for b in self.target_dps.list_bosses()])

            replacing = [replace(item, action=ImportAction.REPLACE)
                         if item.name == "Muq" else item for item in items]
            with patch.object(QMessageBox, "warning") as warning:
                page.apply_import(bundle, replacing)
            warning.assert_called_once()
            self.assertEqual(self._pokemon(self.target_dps, "Muq").note, "local")

    def test_page_reports_a_bad_file(self) -> None:
        page = DpsPage(self.target_dps)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "hunt.json"
            path.write_text('{"Session": {}}', encoding="utf-8")
            with patch.object(QMessageBox, "warning") as warning:
                page.import_from(path)
        self.assertIn("não é uma exportação", warning.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
