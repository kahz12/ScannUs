"""The setup wizard keeps saved keys, and ScannUs output stays limited to the current user."""

import os
import stat

import pytest
from dotenv import dotenv_values

from core import config
from core.cache import SQLiteCache
from utils import results_parse


KEYS = ("GOOGLE_API_KEY_FOR_GEMINI", "BRAVE_API_KEY", "TAVILY_API_KEY", "EXA_API_KEY",
        "HIBP_API_KEY", "ANTHROPIC_API_KEY", "OLLAMA_HOST", "OLLAMA_MODEL", "OPENAI_API_KEY")
FOLDERS = ("DIR_CASES", "DIR_DOWNLOADS", "DIR_MEDIA", "DIR_REPORTS", "DIR_SCREENSHOTS",
           "DIR_GRAPHS", "DIR_CACHE", "DIR_LOGS")


def mode_of(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def run_wizard(monkeypatch, answer):
    monkeypatch.setattr(config, "_prompt", answer)
    config.env_config()
    config.openai_config()


@pytest.fixture
def saved_env(tmp_path, monkeypatch):
    """A project folder whose .env already holds every key."""
    monkeypatch.chdir(tmp_path)
    for name in KEYS:
        monkeypatch.setenv(name, f"saved-{name}")
    env_file = tmp_path / ".env"
    env_file.write_text("".join(f"{name}=saved-{name}\n" for name in KEYS), encoding="utf-8")
    env_file.chmod(0o664)
    return env_file


@pytest.fixture
def restore_umask():
    previous = os.umask(0o022)
    yield
    os.umask(previous)


@pytest.fixture
def outputs(tmp_path, monkeypatch, restore_umask):
    """Points every output folder at a temporary tree that starts open to others."""
    root = tmp_path / "outputs"
    monkeypatch.setattr(config, "OUTPUT_DIR", str(root))
    for name in FOLDERS:
        folder = root / name.removeprefix("DIR_").lower()
        folder.mkdir(parents=True)
        folder.chmod(0o775)
        monkeypatch.setattr(config, name, str(folder))
    root.chmod(0o775)
    return root


class TestWizard:
    def test_blank_answers_keep_every_saved_key(self, monkeypatch, saved_env):
        before = saved_env.read_text(encoding="utf-8")

        run_wizard(monkeypatch, lambda label, hint="": "")

        assert saved_env.read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("name", KEYS)
    def test_blank_answers_keep_the_key_in_the_session(self, monkeypatch, saved_env, name):
        run_wizard(monkeypatch, lambda label, hint="": "")

        assert os.environ[name] == f"saved-{name}"

    def test_new_answer_replaces_only_that_key(self, monkeypatch, saved_env):
        def answer(label, hint=""):
            return "new-value" if label.startswith("Tavily") else ""

        run_wizard(monkeypatch, answer)

        stored = dotenv_values(saved_env)
        assert stored["TAVILY_API_KEY"] == "new-value"
        assert os.environ["TAVILY_API_KEY"] == "new-value"
        assert stored["EXA_API_KEY"] == "saved-EXA_API_KEY"

    def test_every_answer_reaches_its_own_key(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        for name in KEYS:
            monkeypatch.setenv(name, "")
        answers = iter(KEYS)

        run_wizard(monkeypatch, lambda label, hint="": next(answers))

        assert dotenv_values(tmp_path / ".env") == {name: name for name in KEYS}

    def test_saving_a_key_limits_an_open_env_file(self, monkeypatch, saved_env):
        config._save_key("BRAVE_API_KEY", "new-value")

        assert mode_of(saved_env) == 0o600

    def test_new_env_file_starts_private(self, tmp_path, monkeypatch, restore_umask):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BRAVE_API_KEY", "previous")

        config._save_key("BRAVE_API_KEY", "new-value")

        assert mode_of(tmp_path / ".env") == 0o600


class TestLoadEnvironment:
    def test_env_file_copied_from_the_template_becomes_private(
            self, tmp_path, monkeypatch, saved_env):
        monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

        config.load_environment()

        assert mode_of(saved_env) == 0o600

    def test_missing_env_file_is_not_a_problem(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, "BASE_DIR", str(tmp_path))

        config.load_environment()

        assert not (tmp_path / ".env").exists()


class TestOutputFolders:
    def test_existing_folders_close_to_other_users(self, outputs):
        config.init_directories()

        assert mode_of(outputs) == 0o700
        for name in FOLDERS:
            assert mode_of(getattr(config, name)) == 0o700

    def test_new_folders_are_private(self, tmp_path, monkeypatch, restore_umask):
        root = tmp_path / "fresh"
        monkeypatch.setattr(config, "OUTPUT_DIR", str(root))
        for name in FOLDERS:
            monkeypatch.setattr(config, name, str(root / name.lower()))

        config.init_directories()

        assert mode_of(root) == 0o700
        assert mode_of(config.DIR_REPORTS) == 0o700

    def test_older_files_keep_their_mode_behind_the_closed_folder(self, outputs):
        old_report = outputs / "reports" / "old.csv"
        old_report.write_text("data", encoding="utf-8")
        old_report.chmod(0o644)

        config.init_directories()

        assert mode_of(old_report) == 0o644
        assert mode_of(old_report.parent) == 0o700

    def test_refused_change_warns_once_and_keeps_running(self, outputs, monkeypatch):
        warnings = []

        def refuse(path, mode):
            raise PermissionError("read-only file system")

        monkeypatch.setattr(config.os, "chmod", refuse)
        monkeypatch.setattr(config, "print_warn", warnings.append)

        config.init_directories()

        assert len(warnings) == 1
        assert str(outputs) in warnings[0]

    def test_one_refused_folder_is_enough_to_warn(self, outputs, monkeypatch):
        warnings = []
        real_chmod = os.chmod

        def refuse_the_first(path, mode):
            if path == str(outputs):
                raise PermissionError("read-only file system")
            real_chmod(path, mode)

        monkeypatch.setattr(config.os, "chmod", refuse_the_first)
        monkeypatch.setattr(config, "print_warn", warnings.append)

        config.init_directories()

        assert len(warnings) == 1

    def test_folder_that_cannot_be_created_is_still_reported(self, outputs, monkeypatch):
        printed = []
        warnings = []
        monkeypatch.setattr(config, "DIR_MEDIA", str(outputs / "missing"))
        monkeypatch.setattr(config, "print_warn", warnings.append)

        def refuse(path):
            raise PermissionError("no space")

        monkeypatch.setattr(config.os, "makedirs", refuse)
        monkeypatch.setattr(config.console, "print", printed.append)

        config.init_directories()

        assert "Cannot create" in printed[0]
        assert warnings == []


class TestNewFiles:
    @pytest.fixture(autouse=True)
    def private_run(self, outputs, monkeypatch):
        monkeypatch.setattr(results_parse, "DIR_REPORTS", config.DIR_REPORTS)
        config.init_directories()

    def test_report_export(self):
        results_parse.export_report_json({"domain": "acme-corp.io"}, "recon.json")

        assert mode_of(os.path.join(config.DIR_REPORTS, "recon.json")) == 0o600

    def test_plain_file_written_by_any_tool(self):
        path = os.path.join(config.DIR_MEDIA, "photo.jpg")
        with open(path, "wb") as media:
            media.write(b"data")

        assert mode_of(path) == 0o600

    def test_cache_database(self):
        path = os.path.join(config.DIR_CACHE, "cache.db")
        cache = SQLiteCache(path)
        cache.set("search", "key", ["value"])

        assert mode_of(path) == 0o600
        assert [mode_of(extra) for extra in (f"{path}-wal", f"{path}-shm")
                if os.path.exists(extra)] in ([], [0o600], [0o600, 0o600])

    def test_new_folder_inside_outputs(self):
        path = os.path.join(config.DIR_DOWNLOADS, "batch")
        os.makedirs(path)

        assert mode_of(path) == 0o700
