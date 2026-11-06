"""La v2 NO puede tocar el bot vivo de la v1.

La v1 sigue midiendo en otro repositorio y su bot real corre en Docker con estos nombres fijos:
proyecto `minerva`, contenedor `minerva-minerva-1`, imagen `minerva:local`, volumenes
`minerva_data` y `minerva_logs`, puerto 8000, tareas `MinervaStartBot`/`MinervaHealthAlert`/
`MinervaDailySummary`/`MinervaBackup` y la marca `MIGRADO_A_DOCKER.txt`. Aqui se comprueba que
NINGUN valor por defecto de esta v2 coincide con alguno, y que los scripts que podrian actuar
sobre ellos los rechazan.

Todo es estatico o corre scripts que se detienen ANTES de hacer nada: no se usa Docker ni el
Programador de tareas, y ningun puerto se abre.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts import docker_support
from tests.support.winproc import NO_WINDOW

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = REPO_ROOT / "scripts"
COMPOSE = REPO_ROOT / "docker-compose.yml"

# Los nombres de la v1 que ninguna configuracion de la v2 puede usar.
V1_NAMES = (
    "minerva_data", "minerva_logs", "minerva_default", "minerva-minerva-1", "minerva:local",
    "MIGRADO_A_DOCKER.txt",
)
V1_TASKS = ("MinervaStartBot", "MinervaHealthAlert", "MinervaDailySummary", "MinervaBackup")
REAL_BOT_SWITCHES = (
    "LLM_LIVE_LABELING_ENABLED", "TELEGRAM_COMMANDS_ENABLED", "PAPER_EXECUTION_ENABLED",
    "NEWS_COLLECTION_ENABLED", "TELEGRAM_PUSH_ENABLED",
)


def compose() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


def powershell(script: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         str(SCRIPTS / script), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
        cwd=REPO_ROOT, creationflags=NO_WINDOW,
    )


# --- el compose ---------------------------------------------------------------------------------


def test_the_compose_names_everything_minerva_v2_and_pins_the_names():
    data = compose()
    service = data["services"]["minerva"]

    assert data["name"] == "minerva-v2"
    assert service["image"] == "minerva-v2:local"
    assert service["container_name"] == "minerva-v2-minerva-1"
    # los volumenes y la red tienen nombre FIJO: no dependen del proyecto (`-p minerva` no los toca)
    assert data["volumes"]["data"]["name"] == "minerva-v2_data"
    assert data["volumes"]["logs"]["name"] == "minerva-v2_logs"
    assert data["networks"]["default"]["name"] == "minerva-v2_default"


def test_no_v1_name_survives_in_the_compose_once_comments_are_dropped():
    resolved = yaml.safe_dump(compose())

    for name in V1_NAMES:
        assert name not in resolved, name
    assert not re.search(r"(?m)^name: minerva$", resolved)
    assert "minerva_" not in resolved.replace("minerva_estabilidad", "")


def test_the_default_host_port_is_8001_and_the_real_bot_switches_default_to_false():
    text = COMPOSE.read_text(encoding="utf-8")
    service = compose()["services"]["minerva"]

    assert '"127.0.0.1:${MINERVA_PORT:-8001}:8000"' in text
    assert "MINERVA_PORT:-8000" not in text
    for name in REAL_BOT_SWITCHES:
        assert service["environment"][name] == "${MINERVA_REAL_BOT:-false}", name
    assert "MINERVA_REAL_BOT:-true" not in text


# --- los scripts: valores por defecto -----------------------------------------------------------


@pytest.mark.parametrize("script", ["check_health.py", "telegram_alert.py", "telegram_daily.py"])
def test_the_health_and_telegram_scripts_default_to_port_8001(script):
    source = (SCRIPTS / script).read_text(encoding="utf-8")

    assert 'parser.add_argument("--port", type=int, default=8001)' in source
    assert "default=8000" not in source


@pytest.mark.parametrize("script", [
    "start_bot.ps1", "stop_bot.ps1", "migrate_to_docker.ps1", "rollback_from_docker.ps1",
])
def test_the_native_and_migration_scripts_default_to_ports_other_than_8000(script):
    source = (SCRIPTS / script).read_text(encoding="utf-8")
    defaults = re.findall(r"\[int\]\$(?:Port|NativePort|DockerPort) = (\d+)", source)

    assert defaults and set(defaults) == {"8001"}, (script, defaults)


def test_the_migration_scripts_default_to_the_v2_project_and_task():
    for script in ("migrate_to_docker.ps1", "rollback_from_docker.ps1"):
        source = (SCRIPTS / script).read_text(encoding="utf-8")
        assert '[string]$ProjectName = "minerva-v2"' in source, script
    migrate = (SCRIPTS / "migrate_to_docker.ps1").read_text(encoding="utf-8")
    assert '[string]$TaskName = "MinervaV2StartBot"' in migrate
    common = (SCRIPTS / "docker_common.ps1").read_text(encoding="utf-8")
    assert '$script:ComposeProject = "minerva-v2"' in common
    assert '$script:MarkerName = "MIGRADO_A_DOCKER_V2.txt"' in common


def test_the_marker_name_is_not_the_one_of_the_v1():
    assert docker_support.MARKER_NAME == "MIGRADO_A_DOCKER_V2.txt"
    assert docker_support.PROJECT_NAME == "minerva-v2"


def test_only_the_guards_name_the_v1_scheduled_tasks_in_code_and_scripts():
    allowed = {"docker_common.ps1", "migrate_to_docker.ps1", "rollback_from_docker.ps1"}
    pattern = re.compile(r"\b(" + "|".join(V1_TASKS) + r")\b")
    offenders = [
        f"{path.name}: {match.group(0)}"
        for path in sorted(SCRIPTS.glob("*"))
        if path.suffix in {".py", ".ps1"} and path.name not in allowed
        for match in pattern.finditer(path.read_text(encoding="utf-8", errors="replace"))
    ]

    assert offenders == []


# --- los candados -------------------------------------------------------------------------------


def test_compose_always_passes_the_v2_project_and_refuses_the_one_of_the_v1(monkeypatch):
    calls: list[list[str]] = []

    def fake_run_docker(args, **kwargs):
        calls.append(list(args))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(docker_support, "run_docker", fake_run_docker)
    monkeypatch.delenv("COMPOSE_PROJECT_NAME", raising=False)

    docker_support.compose(["ps"])

    assert calls and calls[0][calls[0].index("-p") + 1] == "minerva-v2"

    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "minerva")
    calls.clear()
    with pytest.raises(docker_support.DockerError, match="RECHAZADO"):
        docker_support.compose(["ps"])
    assert calls == []  # ni siquiera se llega a lanzar docker

    monkeypatch.setenv("COMPOSE_PROJECT_NAME", "minerva-prueba")
    docker_support.compose(["ps"])
    assert calls[0][calls[0].index("-p") + 1] == "minerva-prueba"


@pytest.mark.skipif(sys.platform != "win32", reason="son scripts de Windows PowerShell")
@pytest.mark.parametrize("script", ["start_bot.ps1", "stop_bot.ps1"])
def test_start_and_stop_refuse_the_port_of_the_v1_before_doing_anything(script):
    result = powershell(script, "-Port", "8000")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "RECHAZADO" in result.stdout and "8000" in result.stdout


@pytest.mark.skipif(sys.platform != "win32", reason="son scripts de Windows PowerShell")
@pytest.mark.parametrize("script", ["migrate_to_docker.ps1", "rollback_from_docker.ps1"])
@pytest.mark.parametrize("bad_args", [
    ["-ProjectName", "minerva"], ["-NativePort", "8000"], ["-DockerPort", "8000"],
])
def test_the_migration_scripts_refuse_the_project_and_ports_of_the_v1(script, bad_args):
    result = powershell(script, "-DryRun", *bad_args)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "RECHAZADO" in result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="son scripts de Windows PowerShell")
@pytest.mark.parametrize("task", V1_TASKS)
def test_migrate_refuses_a_scheduled_task_of_the_v1(task):
    result = powershell("migrate_to_docker.ps1", "-DryRun", "-TaskName", task)

    assert result.returncode != 0, result.stdout + result.stderr
    assert "RECHAZADO" in result.stdout + result.stderr
