"""Exercise bootstrap scripts without touching the host toolchain or Docker."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FAKE_TOOL = r"""
import json
import os
import subprocess
import sys
from pathlib import Path

name = Path(sys.argv[0]).name
args = sys.argv[1:]
if name == "dirname":
    print(str(Path(args[0]).parent))
    sys.exit(0)
if name == "id":
    print(os.environ.get("FAKE_UID", "0"))
    sys.exit(0)
command = " ".join([name, *args])
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([command, os.getcwd()]) + "\n")
if command == os.environ.get("FAIL_COMMAND"):
    sys.exit(42)
if name == "dpkg":
    sys.exit(int(os.environ.get("DPKG_STATUS", "0")))
if name == "sudo":
    sys.exit(subprocess.run(args[1:], check=False).returncode)
"""


class ScriptSandbox:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.tools = root / "tools"
        self.tools.mkdir()
        (root / "bin").mkdir()
        (root / "home").mkdir()
        self.log = root / "calls.jsonl"
        for name in ("setup", "dev"):
            shutil.copy2(ROOT / "bin" / name, root / "bin" / name)
        for name in ("dirname", "id", "dpkg", "sudo", "apt-get", "mise", "uv", "docker"):
            tool = self.tools / name
            tool.write_text(f"#!{sys.executable}\n{FAKE_TOOL}")
            tool.chmod(0o755)

    def run(self, script: str = "setup", **env: str) -> subprocess.CompletedProcess[str]:
        bash = shutil.which("bash")
        assert bash is not None
        return subprocess.run(
            [bash, str(self.root / "bin" / script)],
            cwd=self.root / "home",
            env={
                "PATH": str(self.tools),
                "HOME": str(self.root / "home"),
                "CALL_LOG": str(self.log),
                **env,
            },
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    @property
    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        entries = [json.loads(line) for line in self.log.read_text().splitlines()]
        assert all(cwd == str(self.root) for _, cwd in entries)
        return [command for command, _ in entries]


@pytest.fixture
def sandbox(tmp_path: Path) -> ScriptSandbox:
    return ScriptSandbox(tmp_path)


DPKG = "dpkg -s build-essential git curl gh"
INSTALL = "apt-get install -y --no-install-recommends build-essential git curl gh"
TOOLCHAIN = [
    "mise install",
    "mise use -g uv@0.13",
    "mise use -g python@3.14",
    "uv sync --all-extras --python 3.14",
    "docker volume create claudetm-profiles",
]


def test_setup_installed_packages(sandbox: ScriptSandbox) -> None:
    result = sandbox.run()
    assert result.returncode == 0, result.stderr
    assert sandbox.calls == ["docker compose version", DPKG, *TOOLCHAIN]


@pytest.mark.parametrize("uid", ["0", "1000"])
def test_setup_installs_packages(sandbox: ScriptSandbox, uid: str) -> None:
    result = sandbox.run(FAKE_UID=uid, DPKG_STATUS="1")
    assert result.returncode == 0, result.stderr
    packages = ["apt-get update", INSTALL]
    if uid != "0":
        packages = ["sudo -n apt-get update", "apt-get update", f"sudo -n {INSTALL}", INSTALL]
    assert sandbox.calls == ["docker compose version", DPKG, *packages, *TOOLCHAIN]


@pytest.mark.parametrize("uid", ["0", "1000"])
@pytest.mark.parametrize("failure", ["apt-get update", INSTALL])
def test_apt_failure_stops_setup(sandbox: ScriptSandbox, uid: str, failure: str) -> None:
    result = sandbox.run(FAKE_UID=uid, DPKG_STATUS="1", FAIL_COMMAND=failure)
    assert result.returncode == 42, result.stderr
    assert sandbox.calls[-1] == failure
    assert not any(call in sandbox.calls for call in TOOLCHAIN)
    if failure == "apt-get update":
        assert INSTALL not in sandbox.calls


@pytest.mark.parametrize("failure", TOOLCHAIN)
def test_setup_failure_stops_subsequent_steps(sandbox: ScriptSandbox, failure: str) -> None:
    result = sandbox.run(FAIL_COMMAND=failure)
    assert result.returncode == 42, result.stderr
    assert sandbox.calls == [
        "docker compose version",
        DPKG,
        *TOOLCHAIN[: TOOLCHAIN.index(failure) + 1],
    ]


@pytest.mark.parametrize("missing", ["mise", "docker", "dpkg"])
def test_setup_missing_prerequisite(sandbox: ScriptSandbox, missing: str) -> None:
    (sandbox.tools / missing).unlink()
    result = sandbox.run()
    assert result.returncode != 0
    assert missing in result.stderr
    assert not any(call in sandbox.calls for call in TOOLCHAIN)


def test_setup_requires_compose(sandbox: ScriptSandbox) -> None:
    result = sandbox.run(FAIL_COMMAND="docker compose version")
    assert result.returncode != 0
    assert "Compose" in result.stderr
    assert sandbox.calls == ["docker compose version"]


def test_setup_requires_sudo_for_nonroot(sandbox: ScriptSandbox) -> None:
    (sandbox.tools / "sudo").unlink()
    result = sandbox.run(FAKE_UID="1000", DPKG_STATUS="1")
    assert result.returncode != 0
    assert "sudo" in result.stderr
    assert sandbox.calls == ["docker compose version", DPKG]


def test_setup_sudo_failure(sandbox: ScriptSandbox) -> None:
    result = sandbox.run(FAKE_UID="1000", DPKG_STATUS="1", FAIL_COMMAND="sudo -n apt-get update")
    assert result.returncode == 42
    assert sandbox.calls == ["docker compose version", DPKG, "sudo -n apt-get update"]


@pytest.mark.parametrize("exit_failure", [False, True])
def test_dev_builds_and_waits(sandbox: ScriptSandbox, exit_failure: bool) -> None:
    command = "docker compose up --build --wait --wait-timeout 180"
    result = sandbox.run("dev", FAIL_COMMAND=command if exit_failure else "")
    assert result.returncode == (42 if exit_failure else 0), result.stderr
    assert sandbox.calls == [command]


def test_dev_missing_docker(sandbox: ScriptSandbox) -> None:
    (sandbox.tools / "docker").unlink()
    result = sandbox.run("dev")
    assert result.returncode != 0
    assert "docker" in result.stderr
    assert sandbox.calls == []


def test_setup_requires_apt_when_packages_missing(sandbox: ScriptSandbox) -> None:
    (sandbox.tools / "apt-get").unlink()
    result = sandbox.run(DPKG_STATUS="1")
    assert result.returncode != 0
    assert "apt-get" in result.stderr
    assert sandbox.calls == ["docker compose version", DPKG]


def test_setup_root_does_not_require_sudo(sandbox: ScriptSandbox) -> None:
    (sandbox.tools / "sudo").unlink()
    result = sandbox.run(DPKG_STATUS="1")
    assert result.returncode == 0, result.stderr
    assert sandbox.calls == ["docker compose version", DPKG, "apt-get update", INSTALL, *TOOLCHAIN]
