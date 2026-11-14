from tlebench import runner
from tlebench.config import Settings

ENV = {"CH_USER": "u", "CH_PASSWORD": "s", "PG_USER": "p", "PG_PASSWORD": "q"}


class FakeFetcher:
    def connect(self) -> None:
        pass

    def close(self) -> None:
        pass


def _record_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(runner.subprocess, "run", lambda *a, **kw: calls.append((a, kw)))
    return calls


def test_restart_default_uses_docker_compose(monkeypatch):
    calls = _record_calls(monkeypatch)
    runner.restart_service("clickhouse", FakeFetcher)
    assert calls == [((["docker", "compose", "restart", "clickhouse"],), {"check": True})]


def test_restart_with_cold_restart_cmd_runs_without_shell(monkeypatch):
    calls = _record_calls(monkeypatch)
    runner.restart_service("clickhouse", FakeFetcher, cold_restart_cmd="deploy/x.sh --drop")
    assert calls == [((["deploy/x.sh", "--drop", "clickhouse"],), {"check": True})]


def test_restart_cold_restart_cmd_keeps_quoted_argument(monkeypatch):
    calls = _record_calls(monkeypatch)
    runner.restart_service("timescaledb", FakeFetcher, cold_restart_cmd="x.sh 'a b'")
    assert calls == [((["x.sh", "a b", "timescaledb"],), {"check": True})]


def test_settings_cold_restart_cmd_unset_or_empty_is_none():
    assert Settings.from_env(ENV).cold_restart_cmd is None
    assert Settings.from_env({**ENV, "COLD_RESTART_CMD": ""}).cold_restart_cmd is None
    assert Settings.from_env({**ENV, "COLD_RESTART_CMD": "  \t "}).cold_restart_cmd is None


def test_settings_cold_restart_cmd_set_and_recorded():
    s = Settings.from_env({**ENV, "COLD_RESTART_CMD": "x.sh --fast"})
    assert s.cold_restart_cmd == "x.sh --fast"
    assert s.public()["cold_restart_cmd"] == "x.sh --fast"
