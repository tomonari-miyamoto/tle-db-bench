import pytest

from tlebench.cli import _build_parser
from tlebench.config import Settings, load_dotenv


def test_settings_require_passwords():
    with pytest.raises(RuntimeError, match="CH_USER"):
        Settings.from_env({})


def test_settings_from_env_and_public_hides_secrets():
    env = {"CH_USER": "u", "CH_PASSWORD": "s3cret", "PG_USER": "p", "PG_PASSWORD": "p@ss/word"}
    s = Settings.from_env(env)
    assert "p%40ss%2Fword" in s.pg_uri()
    assert "s3cret" not in str(s.public()) and "p@ss" not in str(s.public())


def test_load_dotenv_does_not_override(tmp_path):
    f = tmp_path / ".env"
    f.write_text("# c\nA=1\nB='two'\nC=3\n")
    env = {"C": "keep"}
    load_dotenv(f, env)
    assert env == {"C": "keep", "A": "1", "B": "two"}


def test_cli_has_single_entrypoint_with_four_commands():
    p = _build_parser()
    for cmd, extra in (("generate", ["--rows", "10"]), ("load", []), ("run", []), ("report", [])):
        assert p.parse_args([cmd, *extra]).cmd == cmd
