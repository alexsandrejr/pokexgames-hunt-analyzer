"""Atualização pelo GitHub. Nenhum teste acessa a internet: as respostas são simuladas."""

import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import zipfile
from pathlib import Path
from threading import Event
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QWidget  # noqa: E402

from app.services.settings_service import AppSettings  # noqa: E402
from app.services.update_service import (  # noqa: E402
    API_URL,
    DOWNLOAD_PREFIX,
    EXE_NAME,
    OLD_DIR,
    RELEASES_URL,
    STAGING_DIR,
    USER_AGENT,
    ReleaseInfo,
    UpdateCancelled,
    UpdateError,
    UpdateService,
    apply_update,
    asset_name,
    can_install_itself,
    child_environment,
    clean_leftovers,
    ensure_writable,
    is_newer,
    parse_release,
    parse_version,
    wait_for_exit,
)
from app.ui.update.update_controller import UpdateController  # noqa: E402
from app.ui.update.update_dialog import UpdateDialog  # noqa: E402
from app.utils.constants import APP_NAME  # noqa: E402

APP_FOLDER = APP_NAME


def package_bytes(entries: dict[str, bytes] | None = None) -> bytes:
    if entries is None:
        entries = {f"{APP_FOLDER}/{EXE_NAME}": b"exe novo",
                   f"{APP_FOLDER}/_internal/lib.dll": b"lib nova"}
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def release_json(tag: str = "v9.0.0", content: bytes = b"zip", **changes) -> dict:
    version = tag.removeprefix("v")
    asset = {"name": asset_name(version), "size": len(content),
             "digest": f"sha256:{hashlib.sha256(content).hexdigest()}",
             "browser_download_url": f"{DOWNLOAD_PREFIX}{tag}/{asset_name(version)}"}
    return {"tag_name": tag, "body": "## Novidades", "draft": False, "prerelease": False,
            "html_url": f"https://github.com/alexsandrejr/pokexgames-hunt-analyzer/releases/tag/{tag}",
            "assets": [asset], **changes}


def release_info(content: bytes) -> ReleaseInfo:
    return parse_release(release_json(content=content), "1.0.0")


class FakeOpener:
    """Faz o papel do ``urlopen``: uma resposta por URL e o registro dos pedidos."""

    def __init__(self, responses: dict[str, bytes | Exception]) -> None:
        self.responses = responses
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        response = self.responses[request.full_url]
        if isinstance(response, Exception):
            raise response
        return io.BytesIO(response)


class VersionTests(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual(parse_version("v1.10.0"), (1, 10, 0))
        self.assertEqual(parse_version("1.6"), (1, 6))
        for text in ("", "versao", "v1.2-beta", "1..2"):
            self.assertIsNone(parse_version(text), text)

    def test_compares_as_numbers_and_not_as_text(self) -> None:
        self.assertTrue(is_newer((1, 10, 0), (1, 9, 0)))
        self.assertFalse(is_newer((1, 6, 0), (1, 6, 0)))
        self.assertFalse(is_newer((1, 5, 0), (1, 6, 0)))
        self.assertFalse(is_newer((1, 6), (1, 6, 0)))
        self.assertTrue(is_newer((1, 6, 0, 1), (1, 6)))


class ParseReleaseTests(unittest.TestCase):
    def test_newer_release_is_installable(self) -> None:
        release = parse_release(release_json(content=b"abc"), "1.6.0")
        self.assertEqual(release.version, "9.0.0")
        self.assertEqual(release.notes, "## Novidades")
        self.assertEqual(release.sha256, hashlib.sha256(b"abc").hexdigest())
        self.assertTrue(release.installable)

    def test_same_or_older_version_is_not_offered(self) -> None:
        self.assertIsNone(parse_release(release_json("v1.6.0"), "1.6.0"))
        self.assertIsNone(parse_release(release_json("v1.5.0"), "1.6.0"))

    def test_draft_and_prerelease_are_not_offered(self) -> None:
        self.assertIsNone(parse_release(release_json(draft=True), "1.6.0"))
        self.assertIsNone(parse_release(release_json(prerelease=True), "1.6.0"))

    def test_without_a_safe_package_only_the_page_is_offered(self) -> None:
        def changed(**fields) -> dict:
            data = release_json()
            data["assets"][0].update(fields)
            return data

        cases = {
            "sem pacote": release_json(assets=[]),
            "outro nome": changed(name="outro.zip"),
            "sem digest": changed(digest=None),
            "digest ruim": changed(digest="md5:abc"),
            "outro site": changed(browser_download_url="https://exemplo.com/virus.zip"),
            "outro repositório": changed(
                browser_download_url="https://github.com/outro/repo/releases/download/x.zip"),
            "http": changed(browser_download_url=DOWNLOAD_PREFIX.replace("https", "http") + "x.zip"),
        }
        for name, data in cases.items():
            with self.subTest(name):
                release = parse_release(data, "1.6.0")
                self.assertEqual(release.version, "9.0.0")
                self.assertFalse(release.installable)

    def test_page_url_from_elsewhere_is_ignored(self) -> None:
        release = parse_release(release_json(html_url="https://exemplo.com/"), "1.6.0")
        self.assertEqual(release.page_url, RELEASES_URL)

    def test_unexpected_answers(self) -> None:
        for data in ([], {}, {"tag_name": "nightly"}, {"tag_name": 5}):
            with self.subTest(data=data), self.assertRaises(UpdateError):
                parse_release(data, "1.6.0")


class CheckTests(unittest.TestCase):
    def test_request_identifies_only_the_app(self) -> None:
        opener = FakeOpener({API_URL: json.dumps(release_json("v1.0.0")).encode()})
        self.assertIsNone(UpdateService(Path("."), "1.6.0", opener).check())
        [request] = opener.requests
        self.assertEqual(request.get_header("User-agent"), USER_AGENT)
        self.assertNotIn("Authorization", request.headers)

    def test_no_release_published_is_not_an_error(self) -> None:
        error = urllib.error.HTTPError(API_URL, 404, "x", None, None)
        self.assertIsNone(UpdateService(Path("."), "1.6.0", FakeOpener({API_URL: error})).check())

    def test_failures_become_a_message(self) -> None:
        for response in (urllib.error.HTTPError(API_URL, 403, "x", None, None),
                         urllib.error.URLError("sem rede"), TimeoutError(), b"<html>"):
            with self.subTest(response=response), self.assertRaises(UpdateError):
                UpdateService(Path("."), "1.6.0", FakeOpener({API_URL: response})).check()


class DownloadTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.updates = Path(folder.name) / "updates"

    def _service(self, release: ReleaseInfo, content: bytes | Exception) -> UpdateService:
        return UpdateService(self.updates, "1.0.0", FakeOpener({release.asset_url: content}))

    def _leftovers(self) -> list[Path]:
        return list(self.updates.glob("*")) if self.updates.exists() else []

    def test_download_and_extract(self) -> None:
        content = package_bytes()
        release = release_info(content)
        service = self._service(release, content)
        seen = []
        archive = service.download(release, lambda done, total: seen.append((done, total)))
        self.assertEqual(seen[-1], (len(content), len(content)))
        root = service.extract(archive, release.version)
        self.assertEqual(root.name, APP_FOLDER)
        self.assertEqual((root / EXE_NAME).read_bytes(), b"exe novo")
        self.assertEqual((root / "_internal" / "lib.dll").read_bytes(), b"lib nova")

    def test_different_content_is_discarded(self) -> None:
        content = package_bytes()
        release = release_info(content)
        tampered = bytes([content[0] ^ 1]) + content[1:]
        with self.assertRaisesRegex(UpdateError, "não confere"):
            self._service(release, tampered).download(release)
        self.assertEqual(self._leftovers(), [])

    def test_shorter_and_bigger_downloads_are_discarded(self) -> None:
        content = package_bytes()
        release = release_info(content)
        for data in (content[:-1], content + b"x"):
            with self.subTest(size=len(data)), self.assertRaises(UpdateError):
                self._service(release, data).download(release)
            self.assertEqual(self._leftovers(), [])

    def test_network_failure(self) -> None:
        content = package_bytes()
        release = release_info(content)
        with self.assertRaisesRegex(UpdateError, "interrompido"):
            self._service(release, urllib.error.URLError("caiu")).download(release)

    def test_cancel(self) -> None:
        content = package_bytes()
        release = release_info(content)
        cancelled = Event()
        cancelled.set()
        with self.assertRaises(UpdateCancelled):
            self._service(release, content).download(release, None, cancelled)
        self.assertEqual(self._leftovers(), [])

    def test_release_without_package_is_refused(self) -> None:
        release = ReleaseInfo("9.0.0", "", RELEASES_URL)
        with self.assertRaises(UpdateError):
            UpdateService(self.updates, "1.0.0", FakeOpener({})).download(release)

    def test_bad_packages_are_refused(self) -> None:
        cases = {
            "fora da pasta": package_bytes({f"{APP_FOLDER}/{EXE_NAME}": b"x", "virus.exe": b"x"}),
            "subindo pastas": package_bytes({f"{APP_FOLDER}/{EXE_NAME}": b"x",
                                             f"{APP_FOLDER}/../../virus.exe": b"x"}),
            "caminho absoluto": package_bytes({f"{APP_FOLDER}/C:/virus.exe": b"x"}),
            "sem executável": package_bytes({f"{APP_FOLDER}/LEIA-ME.txt": b"x"}),
            "não é zip": b"isto nao e um zip",
        }
        for name, content in cases.items():
            with self.subTest(name):
                self.updates.mkdir(exist_ok=True)
                archive = self.updates / "pacote.zip"
                archive.write_bytes(content)
                with self.assertRaises(UpdateError):
                    UpdateService(self.updates).extract(archive, "9.0.0")


class ApplyUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        base = Path(folder.name)
        self.source, self.target = base / "novo", base / "instalado"
        self._write(self.source / EXE_NAME, "exe novo")
        self._write(self.source / "_internal" / "lib.dll", "lib nova")
        self._write(self.source / "LEIA-ME.txt", "leia novo")
        self._write(self.target / EXE_NAME, "exe antigo")
        self._write(self.target / "_internal" / "lib.dll", "lib antiga")
        self._write(self.target / "_internal" / "so_na_antiga.dll", "antiga")
        self._write(self.target / "data" / "hunts.db", "meus dados")
        self._write(self.target / "minhas_notas.txt", "notas")

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _read(self, *parts: str) -> str:
        return self.target.joinpath(*parts).read_text(encoding="utf-8")

    def test_replaces_the_program_files(self) -> None:
        apply_update(self.source, self.target)
        self.assertEqual(self._read(EXE_NAME), "exe novo")
        self.assertEqual(self._read("_internal", "lib.dll"), "lib nova")
        self.assertEqual(self._read("LEIA-ME.txt"), "leia novo")
        self.assertFalse((self.target / "_internal" / "so_na_antiga.dll").exists())
        self.assertFalse((self.target / STAGING_DIR).exists())
        self.assertFalse((self.target / OLD_DIR).exists())

    def test_keeps_portable_data_and_other_files(self) -> None:
        self._write(self.source / "data" / "hunts.db", "pacote malfeito")
        apply_update(self.source, self.target)
        self.assertEqual(self._read("data", "hunts.db"), "meus dados")
        self.assertEqual(self._read("minhas_notas.txt"), "notas")

    def test_failure_while_swapping_restores_the_old_version(self) -> None:
        real_replace = os.replace

        def failing(source, target):
            # Já tirou os antigos e pôs parte dos novos; falha ao pôr o _internal novo.
            if Path(source) == self.target / STAGING_DIR / "_internal":
                raise PermissionError("em uso")
            return real_replace(source, target)

        with patch("app.services.update_service.os.replace", failing), \
                patch("app.services.update_service.time.sleep"):
            with self.assertRaisesRegex(UpdateError, "versão anterior"):
                apply_update(self.source, self.target)
        self.assertEqual(self._read(EXE_NAME), "exe antigo")
        self.assertEqual(self._read("_internal", "lib.dll"), "lib antiga")
        self.assertEqual(self._read("_internal", "so_na_antiga.dll"), "antiga")
        self.assertFalse((self.target / "LEIA-ME.txt").exists())
        self.assertFalse((self.target / STAGING_DIR).exists())
        self.assertFalse((self.target / OLD_DIR).exists())

    def test_failure_while_restoring_keeps_the_old_files_and_says_where(self) -> None:
        real_replace = os.replace

        def failing(source, target):
            if Path(source) == self.target / STAGING_DIR / "_internal":
                raise PermissionError("em uso")
            if Path(source) == self.target / OLD_DIR / "_internal":
                raise PermissionError("também em uso")
            return real_replace(source, target)

        with patch("app.services.update_service.os.replace", failing), \
                patch("app.services.update_service.time.sleep"):
            with self.assertRaisesRegex(UpdateError, "nem devolver"):
                apply_update(self.source, self.target)
        self.assertEqual((self.target / OLD_DIR / "_internal" / "lib.dll").read_text(
            encoding="utf-8"), "lib antiga")
        self.assertEqual(self._read("data", "hunts.db"), "meus dados")

    def test_failure_while_copying_changes_nothing(self) -> None:
        with patch("app.services.update_service.shutil.copy2", side_effect=OSError("disco cheio")):
            with self.assertRaisesRegex(UpdateError, "copiar"):
                apply_update(self.source, self.target)
        self.assertEqual(self._read(EXE_NAME), "exe antigo")
        self.assertFalse((self.target / STAGING_DIR).exists())

    def test_temporary_lock_is_retried(self) -> None:
        real_replace = os.replace
        failures = [PermissionError("antivírus"), PermissionError("antivírus")]

        def flaky(source, target):
            if failures:
                raise failures.pop()
            return real_replace(source, target)

        with patch("app.services.update_service.os.replace", flaky), \
                patch("app.services.update_service.time.sleep"):
            apply_update(self.source, self.target)
        self.assertEqual(self._read(EXE_NAME), "exe novo")

    def test_refuses_folders_without_the_program(self) -> None:
        (self.target / EXE_NAME).unlink()
        with self.assertRaises(UpdateError):
            apply_update(self.source, self.target)
        with self.assertRaises(UpdateError):
            apply_update(self.source, self.source)  # o exe existe, mas é a mesma pasta
        self.assertEqual(self._read("data", "hunts.db"), "meus dados")

    def test_clean_leftovers(self) -> None:
        updates = self.target / "data" / "updates"
        self._write(updates / "1.0.0" / "x.txt", "x")
        self._write(self.target / OLD_DIR / "x.txt", "x")
        clean_leftovers(updates, self.target)
        self.assertFalse(updates.exists())
        self.assertFalse((self.target / OLD_DIR).exists())
        self.assertEqual(self._read("data", "hunts.db"), "meus dados")


class EnvironmentTests(unittest.TestCase):
    def test_only_the_original_exe_installs_itself(self) -> None:
        self.assertTrue(can_install_itself(True, Path("C:/app") / EXE_NAME))
        self.assertFalse(can_install_itself(False, Path("C:/app") / EXE_NAME))
        self.assertFalse(can_install_itself(True, Path("C:/app/renomeado.exe")))
        self.assertFalse(can_install_itself(True, Path(sys.executable)))

    def test_child_does_not_inherit_the_old_libraries(self) -> None:
        old = Path("C:/app/antigo")
        environment = child_environment(old, {
            "PATH": os.pathsep.join([str(old / "_internal"), str(old), "C:/Windows",
                                     "C:/app/antigo2"]),
            "QT_PLUGIN_PATH": "x", "QT_QPA_PLATFORM_PLUGIN_PATH": "y", "OUTRA": "z"})
        self.assertEqual(environment["PATH"].split(os.pathsep), ["C:/Windows", "C:/app/antigo2"])
        self.assertNotIn("QT_PLUGIN_PATH", environment)
        self.assertNotIn("QT_QPA_PLATFORM_PLUGIN_PATH", environment)
        self.assertEqual(environment["PYINSTALLER_RESET_ENVIRONMENT"], "1")
        self.assertEqual(environment["OUTRA"], "z")

    def test_wait_for_exit(self) -> None:
        process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
        self.addCleanup(process.wait)
        self.addCleanup(process.kill)
        self.assertFalse(wait_for_exit(process.pid, timeout=0.05))
        process.kill()
        process.wait()
        self.assertTrue(wait_for_exit(process.pid, timeout=5))

    def test_ensure_writable(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            ensure_writable(Path(folder))
            with self.assertRaisesRegex(UpdateError, "Sem permissão"):
                ensure_writable(Path(folder) / "nao_existe")

    def test_settings_default_and_invalid_value(self) -> None:
        self.assertTrue(AppSettings().check_updates)
        self.assertTrue(AppSettings(check_updates="sim").validated().check_updates)
        self.assertFalse(AppSettings(check_updates=False).validated().check_updates)


class FakeService:
    def __init__(self, result=None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.updates_dir = Path(".")

    def check(self):
        if self.error is not None:
            raise self.error
        return self.result


class UiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, condition, timeout_ms: int = 5000) -> None:
        loop = QEventLoop()
        timer = QTimer()
        timer.timeout.connect(lambda: loop.quit() if condition() else None)
        timer.start(5)
        QTimer.singleShot(timeout_ms, loop.quit)
        loop.exec()
        timer.stop()
        self.assertTrue(condition(), "a condição não aconteceu a tempo")


class ControllerTests(UiTestCase):
    def setUp(self) -> None:
        self.window = QWidget()
        self.statuses: list[str] = []
        self.dialogs: list[UpdateDialog] = []
        self.installed: list[tuple] = []
        self.quit_count = 0

    def _controller(self, service, result=QDialog.DialogCode.Rejected, new_root=None,
                    frozen=True) -> UpdateController:
        def show(dialog: UpdateDialog) -> int:
            self.dialogs.append(dialog)
            dialog.new_root = new_root
            return result

        def quit_app() -> None:
            self.quit_count += 1

        controller = UpdateController(
            self.window, service, frozen=frozen, executable=Path("C:/app") / EXE_NAME,
            install=lambda *args: self.installed.append(args), quit_app=quit_app, show_dialog=show)
        controller.status_changed.connect(self.statuses.append)
        self.finished = []
        controller.checking_changed.connect(self.finished.append)
        return controller

    def _check(self, controller: UpdateController, silent: bool) -> None:
        controller.check(silent=silent)
        self.wait_until(lambda: self.finished and self.finished[-1] is False)

    def test_manual_check_says_it_is_up_to_date(self) -> None:
        self._check(self._controller(FakeService()), silent=False)
        self.assertIn("mais recente", self.statuses[-1])
        self.assertEqual(self.dialogs, [])

    def test_silent_check_says_nothing_when_up_to_date_or_offline(self) -> None:
        self._check(self._controller(FakeService()), silent=True)
        self.finished.clear()
        self._check(self._controller(FakeService(error=UpdateError("sem rede"))), silent=True)
        self.assertEqual(self.statuses, [])
        self.assertEqual(self.dialogs, [])

    def test_manual_check_shows_the_failure(self) -> None:
        self._check(self._controller(FakeService(error=UpdateError("sem rede"))), silent=False)
        self.assertEqual(self.statuses[-1], "sem rede")

    def test_new_version_is_offered_and_nothing_happens_without_confirming(self) -> None:
        release = release_info(b"zip")
        self._check(self._controller(FakeService(release)), silent=True)
        self.assertEqual(len(self.dialogs), 1)
        self.assertEqual(self.installed, [])
        self.assertEqual(self.quit_count, 0)

    def test_confirming_starts_the_installer_and_closes_the_app(self) -> None:
        release = release_info(b"zip")
        root = Path("C:/tmp/novo")
        controller = self._controller(FakeService(release), QDialog.DialogCode.Accepted, root)
        self._check(controller, silent=True)
        [(new_root, target, pid)] = self.installed
        self.assertEqual((new_root, target), (root, Path("C:/app")))
        self.assertEqual(pid, QApplication.applicationPid())
        self.assertEqual(self.quit_count, 1)

    def test_installer_failure_keeps_the_app_open(self) -> None:
        def failing(*_args) -> None:
            raise UpdateError("não abriu")

        controller = self._controller(FakeService())
        controller._install = failing
        with patch("app.ui.update.update_controller.QMessageBox.warning") as warning:
            controller.install(Path("C:/tmp/novo"))
        warning.assert_called_once()
        self.assertEqual(self.quit_count, 0)

    def test_outside_the_exe_only_the_page_is_offered(self) -> None:
        self._check(self._controller(FakeService(release_info(b"zip")), frozen=False), silent=False)
        self.assertFalse(self.dialogs[0].can_install)
        self.assertTrue(self.dialogs[0].update_button.isHidden())


class DialogTests(UiTestCase):
    def setUp(self) -> None:
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.base = Path(folder.name)
        self.install_dir = self.base / "instalado"
        self.install_dir.mkdir()

    def _dialog(self, content: bytes | Exception, declared: bytes | None = None) -> UpdateDialog:
        release = release_info(declared if declared is not None else content)
        service = UpdateService(self.base / "updates", "1.0.0",
                                FakeOpener({release.asset_url: content}))
        return UpdateDialog(release, service, self.install_dir)

    def test_notes_are_shown_as_text(self) -> None:
        dialog = self._dialog(package_bytes())
        self.assertIn("Novidades", dialog.notes.toPlainText())
        self.assertFalse(dialog.update_button.isHidden())

    def test_download_ends_with_the_new_folder(self) -> None:
        dialog = self._dialog(package_bytes())
        dialog.start_update()
        self.wait_until(lambda: dialog.result() == QDialog.DialogCode.Accepted)
        self.assertEqual(dialog.new_root.name, APP_FOLDER)
        self.assertTrue((dialog.new_root / EXE_NAME).is_file())

    def test_bad_download_shows_the_error_and_allows_retrying(self) -> None:
        dialog = self._dialog(b"corrompido!", declared=b"outra coisa")
        dialog.start_update()
        self.wait_until(lambda: dialog.update_button.isEnabled())
        self.assertFalse(dialog.error_label.isHidden())
        self.assertIsNone(dialog.new_root)

    def test_program_folder_without_permission_stops_before_downloading(self) -> None:
        dialog = self._dialog(package_bytes())
        dialog._install_dir = self.base / "nao_existe"
        dialog.start_update()
        self.assertIn("Sem permissão", dialog.error_label.text())
        self.assertTrue(dialog.progress.isHidden())


class SettingsPageTests(UiTestCase):
    def test_check_now_and_preference(self) -> None:
        from app.services.hunt_service import HuntService
        from app.services.settings_service import SettingsStore
        from app.ui.settings.settings_widget import SettingsPage
        from tests.helpers import memory_database

        database = memory_database()
        self.addCleanup(database.dispose)
        with tempfile.TemporaryDirectory() as folder:
            store = SettingsStore(Path(folder) / "settings.json")
            page = SettingsPage(HuntService(database), Path("x.db"), store=store)
            self.assertFalse(page.check_now_button.isEnabled())

            page.check_updates_box.setChecked(False)
            self.assertFalse(store.load().check_updates)

            controller = UpdateController(page, FakeService())
            page.connect_updates(controller)
            self.assertTrue(page.check_now_button.isEnabled())
            page.check_now_button.click()
            self.wait_until(lambda: "mais recente" in page.update_status_label.text())
            self.assertTrue(page.check_now_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
