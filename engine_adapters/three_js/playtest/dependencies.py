"""Runtime dependency resolution for the three.js playtest recorder.

``record.mjs`` needs Playwright, a Chromium binary, and a dev server that
serves **this** project copy. None of those belong to a generated game —
they are harness concerns, resolved here in a fixed order so a recording
never fails with a bare ``Cannot find module 'playwright'`` again:

* ``playwright_root`` — explicit parameter → ``A3GAME_PLAYWRIGHT_ROOT`` →
  the recorded project's own ``node_modules/playwright`` (its devDependency
  — installed together with vite) → the repository's ``node_modules`` → a
  harness tools dir under the repo (auto-installed once, network needed).
* ``browser_executable`` — ``A3GAME_PLAYWRIGHT_BROWSER_EXECUTABLE`` → the
  ms-playwright browser cache (any revision: an explicit ``executablePath``
  bypasses Playwright's own revision pinning, so a cache downloaded by a
  different Playwright version still works). Absent → ``None`` → Playwright
  validates its own install and the failure surfaces honestly.
* project install — when the adapter must serve the project itself, missing
  ``node_modules`` are installed with the project's package manager first.

Every resolution step records what it did, so the report explains which
dependency came from where instead of silently picking one.
"""

from __future__ import annotations

import os
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[4]
_TOOLS_ROOT = _REPO_ROOT / ".tools"

#: chromium binary candidates inside a ``chromium-<rev>`` cache directory,
#: keyed by platform name fragments; first existing match wins.
_BROWSER_BINARY_SUFFIXES: dict[str, tuple[tuple[str, ...], ...]] = {
    "Darwin": (
        ("chrome-mac-arm64", "Google Chrome for Testing.app", "Contents", "MacOS"),
        ("chrome-mac", "Google Chrome for Testing.app", "Contents", "MacOS"),
        ("chrome-mac-arm64", "Chromium.app", "Contents", "MacOS"),
        ("chrome-mac", "Chromium.app", "Contents", "MacOS"),
    ),
    "Linux": (("chrome-linux",), ("chrome-linux64",)),
    "Windows": (("chrome-win",), ("chrome-win64",)),
}
_BROWSER_BINARY_NAMES = ("Google Chrome for Testing", "Chromium", "chrome")


def _env_path(*names: str) -> Path | None:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return Path(value).expanduser()
    return None


def default_browsers_cache() -> Path | None:
    """The Playwright browser cache location (env override, then platform default)."""
    configured = _env_path("PLAYWRIGHT_BROWSERS_PATH")
    if configured is not None:
        return configured
    home = Path.home()
    darwin = home / "Library" / "Caches" / "ms-playwright"
    if darwin.is_dir():
        return darwin
    linux = home / ".cache" / "ms-playwright"
    if linux.is_dir():
        return linux
    windows = home / "AppData" / "Local" / "ms-playwright"
    if windows.is_dir():
        return windows
    return None


def find_cached_browser_binary(cache: Path | None = None) -> Path | None:
    """A Chromium executable inside the ms-playwright cache, newest revision first.

    An explicit ``executablePath`` bypasses Playwright's revision pinning, so
    the cache revision does not need to match the installed Playwright.
    """
    root = cache if cache is not None else default_browsers_cache()
    if root is None or not root.is_dir():
        return None
    import platform as _platform

    suffixes = _BROWSER_BINARY_SUFFIXES.get(_platform.system(), ())
    revisions: list[tuple[int, Path]] = []
    for entry in root.glob("chromium-*"):
        if entry.is_dir() and entry.name.split("-")[-1].isdigit():
            revisions.append((int(entry.name.split("-")[-1]), entry))
    for _, revision_dir in sorted(revisions, reverse=True):
        for suffix in suffixes:
            base = revision_dir.joinpath(*suffix)
            if not base.is_dir():
                continue
            for name in _BROWSER_BINARY_NAMES:
                candidate = base / name
                if candidate.is_file() and os.access(candidate, os.X_OK):
                    return candidate
        # flat layouts (headless shell dirs keep the binary next to the app bundle)
        for candidate in revision_dir.rglob("chrome"):
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return candidate
    return None


@dataclass
class PlaywrightDeps:
    """Resolved recorder dependencies; every step explains itself in ``notes``."""

    playwright_root: Path | None = None
    browser_executable: Path | None = None
    notes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "playwright_root": str(self.playwright_root) if self.playwright_root else None,
            "browser_executable": str(self.browser_executable) if self.browser_executable else None,
            "notes": list(self.notes),
            "errors": list(self.errors),
        }


def resolve_playwright(project_dir: Path | None, toolchain: Any, *,
                       explicit_root: str | Path | None = None,
                       allow_install: bool = True) -> PlaywrightDeps:
    """Locate a usable Playwright install for recording ``project_dir``."""
    deps = PlaywrightDeps()

    candidates: list[tuple[str, Path]] = []
    if explicit_root:
        candidates.append(("explicit parameter", Path(explicit_root).expanduser()))
    env_root = _env_path("A3GAME_PLAYWRIGHT_ROOT")
    if env_root is not None:
        candidates.append(("A3GAME_PLAYWRIGHT_ROOT", env_root))
    if project_dir is not None:
        candidates.append(("project node_modules", Path(project_dir)))
    repo_modules = _REPO_ROOT / "node_modules"
    if (repo_modules / "playwright").is_dir():
        candidates.append(("repository node_modules", repo_modules))

    for origin, root in candidates:
        if (root / "node_modules" / "playwright").is_dir():
            deps.playwright_root = root
            deps.notes.append(f"playwright resolved from {origin}: {root}")
            break
    else:
        if allow_install:
            installed = _install_tools_playwright(toolchain)
            if installed is not None:
                deps.playwright_root = installed
                deps.notes.append(f"playwright installed into harness tools root: {installed}")
            else:
                deps.errors.append(
                    "no usable playwright install: pass --playwright-root (a project "
                    "with node_modules/playwright) or set A3GAME_PLAYWRIGHT_ROOT; "
                    "the automatic harness install failed (network unavailable?)")
        else:
            deps.errors.append(
                "no usable playwright install found and installation is disabled")

    browser = _env_path("A3GAME_PLAYWRIGHT_BROWSER_EXECUTABLE",
                        "A3GAME_PLAYWRIGHT_BROWSER")
    if browser is not None and browser.is_file():
        deps.browser_executable = browser
        deps.notes.append(f"browser executable from environment: {browser}")
    else:
        cached = find_cached_browser_binary()
        if cached is not None:
            deps.browser_executable = cached
            deps.notes.append(
                f"browser executable from the ms-playwright cache: {cached} "
                "(explicit executablePath — revision pinning is bypassed)")
        elif deps.playwright_root is not None:
            deps.notes.append(
                "no cached browser binary found; Playwright will use its own "
                "browser install (fails honestly when the pinned revision is missing)")
    return deps


def _install_tools_playwright(toolchain: Any) -> Path | None:
    """Install playwright once into ``<repo>/.tools/playwright-root``."""
    root = _TOOLS_ROOT / "playwright-root"
    modules = root / "node_modules" / "playwright"
    if modules.is_dir():
        return root
    version = os.environ.get("A3GAME_PLAYWRIGHT_VERSION", "").strip() or "latest"
    manager = getattr(toolchain, "package_manager", None)
    if manager is None:
        return None
    root.mkdir(parents=True, exist_ok=True)
    try:
        result = toolchain.run(
            [str(manager), "install", "--no-audit", "--no-fund",
             f"playwright@{version}"],
            cwd=root,
            timeout=900,
        )
    except Exception:  # noqa: BLE001 — install failure is reported, never raised
        return None
    if result.ok and modules.is_dir():
        return root
    return None


def project_needs_install(project_dir: Path) -> bool:
    """Whether the project's own dependencies are missing *or incomplete*.

    A ``node_modules`` directory alone proves nothing: a partially extracted
    critical package (directory present, runtime files missing — observed
    after workspace copies that blanket-excluded nested ``dist/`` dirs, and
    after flaky extractions) still needs an install, and the sentinel check
    says so.
    """
    project_dir = Path(project_dir)
    node_modules = project_dir / "node_modules"
    if not node_modules.is_dir():
        return True
    if not (project_dir / "package.json").is_file():
        return False
    try:
        import json

        package = json.loads(
            (project_dir / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    dependencies = {**(package.get("dependencies") or {}),
                    **(package.get("devDependencies") or {})}
    critical = [name for name in ("vite", "three") if name in dependencies]
    return bool(verify_critical_packages(project_dir, critical))


def _sentinel_files(name: str, package_root: Path | None = None) -> tuple[str, ...]:
    """Files whose presence proves a package actually materialized.

    A partially-extracted package (observed with vite on npm 11/Node 26)
    leaves the directory present — even its own bin — but its runtime
    files missing. The sentinels are the *imported* files: vite's bin
    loads ``dist/node/cli.js``, so that exact file must exist.

    For three.js, the structure changed across versions:
    - r168 and earlier: build/three.module.js exists, three.core.js doesn't
    - r169+: split into three.core.js and three.module.js

    We validate against what the installed version actually declares.
    """
    if name == "vite":
        return ("package.json", "dist/node/cli.js")
    if name == "three":
        # Always require package.json and at least one valid entry point
        base_sentinels = ["package.json"]

        # Try to read package.json to determine the actual entry points
        if package_root is not None:
            pkg_json = package_root / "package.json"
            if pkg_json.is_file():
                try:
                    import json as _json
                    pkg_data = _json.loads(pkg_json.read_text(encoding="utf-8"))

                    # Check what the package.json declares as entry points
                    main = pkg_data.get("main", "")
                    module = pkg_data.get("module", "")
                    exports = pkg_data.get("exports", {})

                    # Collect declared entry files
                    declared_entries = set()
                    if main and isinstance(main, str):
                        declared_entries.add(main.lstrip("./"))
                    if module and isinstance(module, str):
                        declared_entries.add(module.lstrip("./"))

                    # Handle exports field (can be string, object, or nested)
                    if isinstance(exports, str):
                        declared_entries.add(exports.lstrip("./"))
                    elif isinstance(exports, dict):
                        for key, value in exports.items():
                            if isinstance(value, str):
                                declared_entries.add(value.lstrip("./"))
                            elif isinstance(value, dict):
                                for subval in value.values():
                                    if isinstance(subval, str):
                                        declared_entries.add(subval.lstrip("./"))

                    # Filter to build/* files only
                    build_entries = [f for f in declared_entries if f.startswith("build/")]
                    if build_entries:
                        # Use declared entry points as sentinels
                        return tuple(base_sentinels + build_entries)
                except Exception:
                    pass  # Fall through to fallback

        # Fallback: check for common patterns across versions
        # three.module.js exists in both old and new versions
        return tuple(base_sentinels + ["build/three.module.js"])
    return ("package.json",)


def verify_critical_packages(project_dir: Path, packages: list[str]) -> list[str]:
    """Packages that did not fully materialize; empty list = all verified.

    Every sentinel must exist — a partially extracted package keeps its
    top-level files while the imported runtime files are missing.
    """
    broken: list[str] = []
    node_modules = project_dir / "node_modules"
    for name in packages:
        root = node_modules / name
        if not root.is_dir():
            broken.append(name)
            continue
        sentinels = _sentinel_files(name, package_root=root)
        if not all((root / sentinel).is_file() for sentinel in sentinels):
            broken.append(name)
    return broken


def install_project_dependencies(project_dir: Path, toolchain: Any, *,
                                 timeout: float = 1200.0, log_dir: str | Path | None = None) -> list[str]:
    """Install the project's packages; returns notes (errors raise ``RuntimeError``).

    A partially-extracted critical package (directory present, runtime files
    missing) is detected after the install, removed, and reinstalled once —
    and a second failure raises with the concrete broken package instead of
    letting the dev server crash with an opaque module-not-found later.
    """
    manager = getattr(toolchain, "package_manager", None)
    if manager is None:
        raise RuntimeError(
            "no Node package manager found on PATH; install the project "
            "dependencies manually and retry the recording")
    notes: list[str] = []
    if os.environ.get("A3GAME_THREE_SKIP_INSTALL", "").strip():
        notes.append("project dependency install skipped (A3GAME_THREE_SKIP_INSTALL)")
        return notes
    import json as _json

    try:
        package = _json.loads((project_dir / "package.json")
                              .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        package = {}
    dependencies = sorted({**(package.get("dependencies") or {}),
                           **(package.get("devDependencies") or {})})
    critical = [name for name in ("vite", "three") if name in dependencies]

    def _run_install() -> None:
        try:
            result = toolchain.run(
                [str(manager), "install", "--no-audit", "--no-fund",
                 "--prefer-offline"],
                cwd=project_dir, timeout=timeout)
        except Exception as exc:  # noqa: BLE001 — surfaced as install failure
            raise RuntimeError(
                f"dependency install failed: {type(exc).__name__}: {exc}") from exc
        if log_dir is not None:
            directory=Path(log_dir);directory.mkdir(parents=True,exist_ok=True)
            for channel in ('stdout','stderr'):
                with (directory/('dependency_install_'+channel+'.log')).open('a') as log:
                    log.write(getattr(result,channel,'') or '')
        if not result.ok:
            tail = (result.stderr or result.stdout or "").strip()[-800:]
            raise RuntimeError(
                f"dependency install failed (exit {result.returncode}): {tail}")

    _run_install()
    broken = verify_critical_packages(project_dir, critical)
    if broken:
        notes.append(
            f"first install left {broken} partially extracted — retrying once")
        import shutil as _shutil

        for name in broken:
            _shutil.rmtree(project_dir / "node_modules" / name,
                           ignore_errors=True)
        _run_install()
        broken = verify_critical_packages(project_dir, critical)
        if broken:
            raise RuntimeError(
                f"critical packages still broken after reinstall: {broken} — "
                f"delete the project's node_modules and retry the recording")
    notes.append(f"project dependencies installed with {Path(str(manager)).name}")
    return notes


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def probe_http_result(url: str, *, timeout: float = 2.0) -> dict[str, Any]:
    """Probe the owned loopback server without process-global urllib/proxy state.

    A Vite banner, TCP connection or redirect is not HTTP readiness. Keep the
    actual status/exception so a pre-record failure is not mislabelled as a game
    failure. Each attempt owns and closes its connection and has a total budget.
    """
    import http.client
    import ipaddress
    from urllib.parse import urlsplit

    started = time.monotonic()
    result: dict[str, Any] = {"url": url, "ready": False, "status": None,
                              "transport": "direct_loopback_http.v1"}
    connection = None
    try:
        target = urlsplit(url)
        if (target.scheme != "http" or target.username is not None
                or target.password is not None or target.fragment
                or not ipaddress.ip_address(target.hostname or "").is_loopback):
            raise ValueError("readiness requires an explicit loopback HTTP address")
        if timeout <= 0:
            raise TimeoutError("readiness budget exhausted")
        connection = http.client.HTTPConnection(target.hostname, target.port or 80, timeout=timeout)
        connection.connect()
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("readiness budget exhausted during connect")
        connection.sock.settimeout(remaining)
        path = target.path or "/"
        if target.query:
            path += "?" + target.query
        connection.request("GET", path, headers={"Connection": "close"})
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError("readiness budget exhausted during request")
        connection.sock.settimeout(remaining)
        response = connection.getresponse()
        result["status"] = int(response.status)
        result["ready"] = 200 <= result["status"] < 300
        response.close()
    except Exception as exc:
        result["exception"] = {"type": type(exc).__name__, "errno": getattr(exc, "errno", None),
                               "message": str(exc)[:400]}
    finally:
        if connection is not None:
            connection.close()
    result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result


def probe_http(url: str, *, timeout: float = 2.0) -> bool:
    """Compatibility boolean entry; detailed diagnostics are used by the session."""
    return probe_http_result(url, timeout=timeout)["ready"]


def _is_server_error_line(line: str) -> bool:
    import re
    # Node may print source as quoted strings after the actual exception.
    text = line.strip()
    if not text or text.startswith(("'", '"')):
        return False
    return bool(re.search(r'(?:\b(?:Error|TypeError|SyntaxError|ReferenceError):|'
                          r'Pre-transform error:|Internal server error:|'
                          r'error during build|EADDRINUSE|Cannot find module)', text))


class DevServerSession:
    """A dev server the adapter started for a *specific* project copy.

    The spawn env pins ``A3GAME_DEV_PORT``/``A3GAME_DEV_HOST`` so the served
    content is provably this project's dev pipeline on a private port — never
    whatever happens to listen on the default 5173 from an earlier run.
    """

    def __init__(self, project_dir: Path, toolchain: Any, *,
                 host: str = "127.0.0.1", port: int | None = None,
                 start_timeout: float = 120.0, log_dir: str | Path | None = None,
                 build_completed: bool = False) -> None:
        self.project_dir = Path(project_dir)
        self.build_completed = build_completed
        self.toolchain = toolchain
        self.host = host
        self.port = int(port or find_free_port())
        self.start_timeout = start_timeout
        self.log_dir = Path(log_dir) if log_dir is not None else None
        self.process: subprocess.Popen[Any] | None = None
        self.notes: list[str] = []
        self.launch_selection = None
        self._output_tail = []
        self._error_lines = []
        self._drainer = None
        self.readiness_attempts = []
        self.readiness_attempt_count = 0
        self._readiness_started = None

    @property
    def url(self) -> str:
        path = (self.launch_selection or {}).get("url_path", "/")
        return f"http://{self.host}:{self.port}" + (path if path != "/" else "")

    def start(self) -> str:
        from .launch import resolve_launch, launch_command
        self.launch_selection = resolve_launch(self.project_dir)
        environment = {
            "PORT": str(self.port), "HOST": self.host,
            "A3GAME_DEV_PORT": str(self.port),
            "A3GAME_DEV_HOST": self.host,
        }
        # Some deliveries explicitly use a shared web toolchain in their
        # unchanged Vite config/README. Honor only the configured environment;
        # never guess a sibling game's node_modules or rewrite package.json.
        shared = os.environ.get('A3GAME_WEB_ENV', '').strip()
        if shared:
            shared_root = Path(shared).expanduser().resolve()
            if verify_critical_packages(shared_root, ['vite', 'three']) or not (shared_root/'node_modules/.bin/vite').is_file():
                raise RuntimeError('A3GAME_WEB_ENV does not contain a complete Vite/Three toolchain')
            environment['A3GAME_WEB_ENV'] = str(shared_root)
            environment['PATH'] = str(shared_root/'node_modules/.bin') + os.pathsep + os.environ.get('PATH', '')
            self.notes.append(f'explicit shared web toolchain: {shared_root}; project sources unchanged')
            if self.log_dir is not None:
                import hashlib
                import json
                self.log_dir.mkdir(parents=True, exist_ok=True)
                files = [shared_root/'package-lock.json', shared_root/'node_modules/vite/package.json', shared_root/'node_modules/three/package.json']
                (self.log_dir/'shared_web_toolchain.json').write_text(json.dumps({
                    'configured_environment': str(shared_root),
                    'files': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files if p.is_file()},
                    'reason': 'Explicit A3GAME_WEB_ENV launch configuration; PATH supplies the declared dev script executable.',
                    'project_sources_modified': False}, indent=2))
        command = launch_command(self.launch_selection, self.toolchain.package_manager, self.host, self.port)
        if self.launch_selection['build_script'] and not self.build_completed:
            raise RuntimeError('build/preview requires a completed build under the separate import/build budget')
        if self.log_dir is not None:
            import json
            self.log_dir.mkdir(parents=True, exist_ok=True)
            (self.log_dir/'launch_selection.json').write_text(json.dumps({**self.launch_selection, 'command':command, 'environment':environment, 'url':self.url},indent=2))
        self.process = self.toolchain.spawn(command, cwd=self.project_dir, environment=environment)
        if self.process.stdout is not None:
            import threading
            stream=self.process.stdout
            def drain():
                log=(self.log_dir/'dev_server.log').open('a') if self.log_dir is not None else None
                try:
                    for line in stream:
                        self._output_tail.append(line)
                        if len(self._error_lines) < 8 and _is_server_error_line(line):
                            self._error_lines.append(line.strip()[:1600])
                        del self._output_tail[:-40]
                        if log is not None:log.write(line);log.flush()
                finally:
                    if log is not None:log.close()
            self._drainer=threading.Thread(target=drain,daemon=True)
            self._drainer.start()
        self._readiness_started = time.monotonic()
        deadline = self._readiness_started + self.start_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                if self._drainer is not None:self._drainer.join(timeout=1)
                self._save_readiness("server_exited")
                output = ''.join(self._output_tail)
                raise RuntimeError(
                    f"dev server exited with code {self.process.returncode}: "
                    f"{str(output)[-800:]}")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            attempt = probe_http_result(self.url, timeout=min(2.0, remaining))
            self.readiness_attempt_count += 1
            attempt["attempt"] = self.readiness_attempt_count
            self.readiness_attempts.append(attempt)
            # Keep the first cause and recent observations, bounded even for long callers.
            if len(self.readiness_attempts) > 128:
                del self.readiness_attempts[1]
            if attempt["ready"] and self.process.poll() is None:
                self._save_readiness("ready")
                self.notes.append(
                    f"dev server for {self.project_dir.name} answering on {self.url}")
                return self.url
            self._save_readiness("waiting")
            time.sleep(max(0, min(0.5, deadline - time.monotonic())))
        self._save_readiness("timeout")
        self.stop()
        raise RuntimeError(
            f"dev server did not answer on {self.url} within {self.start_timeout:.0f}s")

    def _save_readiness(self, state: str) -> None:
        if self.log_dir is None:
            return
        import json
        receipt = {"schema": "three-server-readiness.v1", "state": state,
                   "url": self.url, "transport": "direct_loopback_http.v1",
                   "timeout_s": self.start_timeout,
                   "elapsed_ms": round((time.monotonic() - self._readiness_started) * 1000),
                   "server_pid": getattr(self.process, "pid", None),
                   "server_returncode": self.process.poll(),
                   "attempt_count": self.readiness_attempt_count,
                   "attempts": self.readiness_attempts}
        path = self.log_dir / "server_readiness.json"
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(receipt, indent=2) + "\n")
        temp.replace(path)

    def failure_diagnostics(self) -> dict[str, Any] | None:
        """Describe a server that died after HTTP readiness; preserve recorder errors.

        A successful HTML request precedes Vite's lazy import transforms. The
        first transform error can be far outside the final stack/source dump.
        This reports the owned server process and its bounded first errors,
        without assigning product/harness blame from a network exception.
        """
        process = self.process
        if process is None or process.poll() is None:
            return None
        if self._drainer is not None:
            self._drainer.join(timeout=1)
        return {
            'version': 'three-server-failure.v1',
            'stage': 'project_server_exited',
            'exit_code': process.returncode,
            'url': self.url,
            'launch_selection': self.launch_selection,
            'first_errors': list(self._error_lines),
            'output_tail': ''.join(self._output_tail)[-2400:],
            'log_path': str(self.log_dir/'dev_server.log') if self.log_dir else None,
            'attribution': 'requires_source_and_dependency_review',
        }

    def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.poll() is not None:
            return
        import signal
        try:
            if os.name != 'nt' and hasattr(process,'pid'):os.killpg(process.pid,signal.SIGTERM)
            else:process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name != 'nt' and hasattr(process,'pid'):os.killpg(process.pid,signal.SIGKILL)
            else:process.kill()
            process.wait(timeout=5)
        except ProcessLookupError:pass
        if self._drainer is not None:self._drainer.join(timeout=1)

    def __enter__(self) -> "DevServerSession":
        self.start()
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.stop()


__all__ = [
    "PlaywrightDeps",
    "DevServerSession",
    "resolve_playwright",
    "find_cached_browser_binary",
    "default_browsers_cache",
    "install_project_dependencies",
    "project_needs_install",
    "verify_critical_packages",
    "find_free_port",
    "probe_http",
]
