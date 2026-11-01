"""Settings loader tests (native + container share this mechanism)."""

from config.settings import REPO_ROOT, settings, _load_dotenv


def test_defaults_active() -> None:
    assert settings.app_name == "marketing"
    assert settings.version == "0.1.0"
    # DRY RUN must default true — outreach safety rule
    assert settings.dry_run is True


def test_log_dir_defaults_inside_repo() -> None:
    assert settings.log_dir == REPO_ROOT / "logs"


def test_dotenv_parser() -> None:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:
        fh.write("# comment\nFOO=bar\nQUOTED=\"quoted value\"\n\nBADLINE\n")
        path = __import__("pathlib").Path(fh.name)
    parsed = _load_dotenv(path)
    assert parsed == {"FOO": "bar", "QUOTED": "quoted value"}
    path.unlink()
