"""Isolated executor for generated code.

Docker backend: each tool runs in a throwaway container with no network, a read-only root
filesystem, the workspace mounted read-only, all capabilities dropped, an unprivileged user,
and CPU/memory/PID/time/output limits. There is intentionally no "local" backend: if Docker is not
available, execution-based checks are reported as skipped instead of running on the host.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404 - argv lists only, never shell=True
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import Settings
from app.executor.tools import ToolSpec
from app.security.redaction import redact

log = logging.getLogger("toolkit.sandbox")


@dataclass
class SandboxResult:
    exit_code: int | None
    output: str
    timed_out: bool
    truncated: bool
    duration_ms: int


class SandboxUnavailable(Exception):
    pass


class Sandbox(Protocol):
    name: str

    def available(self) -> tuple[bool, str]: ...

    def features(self) -> set[str]: ...

    def run(self, tool: ToolSpec, workspace: Path) -> SandboxResult: ...


class DisabledSandbox:
    name = "disabled"

    def available(self) -> tuple[bool, str]:
        return False, "sandbox disabled by configuration (SANDBOX_BACKEND=disabled)"

    def features(self) -> set[str]:
        return set()

    def run(self, tool: ToolSpec, workspace: Path) -> SandboxResult:
        raise SandboxUnavailable("sandbox disabled")


def _minimal_env() -> dict[str, str]:
    """Environment for the docker CLI process itself: no host secrets are inherited."""
    import os

    keep = (
        "PATH",
        "DOCKER_HOST",
        "DOCKER_CONFIG",
        "DOCKER_CERT_PATH",
        "DOCKER_TLS_VERIFY",
        "XDG_RUNTIME_DIR",
    )
    return {k: v for k, v in os.environ.items() if k in keep}


class DockerSandbox:
    name = "docker"

    def __init__(self, settings: Settings):
        self.s = settings
        self._features: set[str] | None = None
        self._available: tuple[bool, str] | None = None

    def _docker(self) -> str:
        path = shutil.which("docker")
        if not path:
            raise SandboxUnavailable("docker CLI not found")
        return path

    def available(self) -> tuple[bool, str]:
        if self._available is not None:
            return self._available
        try:
            docker = self._docker()
            out = subprocess.run(  # nosec B603
                [docker, "image", "inspect", "--format", "{{json .Config.Labels}}", self.s.sandbox_image],
                capture_output=True,
                text=True,
                timeout=15,
                env=_minimal_env(),
                check=False,
            )
        except (SandboxUnavailable, subprocess.SubprocessError, OSError) as exc:
            self._available = (False, f"docker not usable: {exc}")
            return self._available
        if out.returncode != 0:
            msg = out.stderr.strip().splitlines()[-1:] or ["unknown error"]
            self._available = (False, f"sandbox image '{self.s.sandbox_image}' not available: {msg[0][:200]}")
            return self._available
        try:
            labels = json.loads(out.stdout or "null") or {}
        except json.JSONDecodeError:
            labels = {}
        self._features = {f.strip() for f in labels.get("toolkit.features", "").split(",") if f.strip()}
        self._available = (True, "ok")
        return self._available

    def features(self) -> set[str]:
        self.available()
        return self._features or set()

    def _host_path(self, workspace: Path) -> Path:
        """Translate a container path to a host path when the worker itself runs in a container."""
        host_root = self.s.sandbox_host_data_dir
        if host_root is None:
            return workspace
        return host_root / workspace.resolve().relative_to(self.s.data_dir)

    def run(self, tool: ToolSpec, workspace: Path) -> SandboxResult:
        ok, reason = self.available()
        if not ok:
            raise SandboxUnavailable(reason)
        docker = self._docker()
        name = f"toolkit-sbx-{uuid.uuid4().hex[:12]}"
        timeout = min(tool.timeout_seconds, self.s.sandbox_timeout_seconds)
        argv = [
            docker,
            "run",
            "--rm",
            "--name",
            name,
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--user",
            "65534:65534",
            "--cpus",
            str(self.s.sandbox_cpus),
            "--memory",
            f"{self.s.sandbox_memory_mb}m",
            "--memory-swap",
            f"{self.s.sandbox_memory_mb}m",
            "--pids-limit",
            str(self.s.sandbox_pids_limit),
            "--ulimit",
            "nofile=1024:1024",
            "-v",
            f"{self._host_path(workspace)}:/workspace:ro",
            "-w",
            "/workspace",
        ]
        for k, v in tool.env.items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.s.sandbox_image, *tool.argv]

        started = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(  # nosec B603 - fixed argv from the tool registry
                argv, capture_output=True, timeout=timeout, env=_minimal_env(), check=False
            )
            exit_code: int | None = proc.returncode
            raw = proc.stdout + proc.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = None
            raw = (exc.stdout or b"") + (exc.stderr or b"")
            subprocess.run(
                [docker, "kill", name],
                capture_output=True,
                timeout=20,  # nosec B603
                env=_minimal_env(),
                check=False,
            )
        duration = int((time.monotonic() - started) * 1000)
        limit = self.s.sandbox_max_output_bytes
        truncated = len(raw) > limit
        text = raw[:limit].decode("utf-8", errors="replace")
        if truncated:
            text += f"\n... [output truncated at {limit} bytes]"
        return SandboxResult(exit_code, redact(text), timed_out, truncated, duration)


def build_sandbox(settings: Settings) -> Sandbox:
    if settings.sandbox_backend == "docker":
        return DockerSandbox(settings)
    return DisabledSandbox()
