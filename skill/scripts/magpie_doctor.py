#!/usr/bin/env python3
"""magpie_doctor.py - one-shot, READ-ONLY health report for a magpie + pi setup.

Layers checked (see skill/SKILL.md for the 3-layer model):
  0. locate the magpie binary      (it is often NOT on PATH)
  1. config inventory              (~/.config/magpie + ~/.pi/agent)
  2. providers / routing groups    (magpie providers, magpie groups)
  3. agent wiring                  (magpie ls, ~/.pi/agent/models.json)
  4. gateway reachability          (TCP + HTTP GET /v1/models)

This script never modifies any file and never runs a state-changing magpie
subcommand. Everything it invokes is read-only.

Usage:
    python magpie_doctor.py
    python magpie_doctor.py --json
    python magpie_doctor.py --port 3425
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

IS_WINDOWS = os.name == "nt"
HOME = Path.home()
MAGPIE_CONFIG = HOME / ".config" / "magpie"
PI_AGENT = HOME / ".pi" / "agent"
DEFAULT_PORT = 3425

OK, WARN, BAD, INFO = "OK", "WARN", "BAD", "INFO"
_MARK = {OK: "[ OK ]", WARN: "[WARN]", BAD: "[FAIL]", INFO: "[INFO]"}

report: list[dict] = []


def add(level: str, area: str, msg: str, **extra) -> None:
    row = {"level": level, "area": area, "message": msg}
    row.update(extra)
    report.append(row)
    if not SILENT:
        print(f"{_MARK[level]} {area:<10} {msg}")


SILENT = False


def run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    """Run a command, return (returncode, combined output). Never raises."""
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            shell=False,
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except FileNotFoundError:
        return 127, f"not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, f"timeout after {timeout}s: {' '.join(cmd)}"
    except Exception as exc:  # pragma: no cover - defensive
        return 1, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# layer 0 - locate the magpie binary
# --------------------------------------------------------------------------

EXE_NAMES = ["magpie.exe", "magpie-windows-amd64.exe", "magpie", "magpie-linux-amd64",
             "magpie-darwin-arm64", "magpie-darwin-amd64"]


def _from_path() -> str | None:
    for name in EXE_NAMES:
        hit = shutil.which(name)
        if hit:
            return hit
    hit = shutil.which("magpie")
    return hit


def _from_running_process() -> str | None:
    """Most reliable on Windows: ask the OS where the running exe lives."""
    if IS_WINDOWS:
        ps = (
            "Get-Process -Name magpie* -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path } | Select-Object -First 1 -ExpandProperty Path"
        )
        for shell in ("pwsh", "powershell"):
            if shutil.which(shell):
                rc, out = run([shell, "-NoProfile", "-NonInteractive", "-Command", ps])
                if rc == 0 and out.strip() and Path(out.strip().splitlines()[0]).exists():
                    return out.strip().splitlines()[0]
        return None
    # POSIX
    rc, out = run(["ps", "-eo", "comm=,args="])
    if rc == 0:
        for line in out.splitlines():
            if "magpie" in line:
                for token in line.split():
                    if "magpie" in token and os.sep in token and Path(token).is_file():
                        return token
    return None


def _from_known_dirs() -> str | None:
    roots: list[Path] = []
    if IS_WINDOWS:
        for var in ("USERPROFILE", "LOCALAPPDATA", "APPDATA", "ProgramFiles"):
            if os.environ.get(var):
                roots.append(Path(os.environ[var]))
        if os.environ.get("USERPROFILE"):
            up = Path(os.environ["USERPROFILE"])
            roots += [up / "Downloads" / "Programs", up / "Downloads", up / "Desktop",
                      up / "Documents", up / "bin"]
        roots.append(Path("C:/tools"))
    else:
        roots += [Path("/usr/local/bin"), Path("/usr/bin"), Path("/opt"),
                  HOME / "bin", HOME / ".local" / "bin", HOME / "Downloads"]
    for root in roots:
        if not root.is_dir():
            continue
        for name in EXE_NAMES:
            cand = root / name
            if cand.is_file():
                return str(cand)
    return None


def find_magpie() -> tuple[str | None, str]:
    env = os.environ.get("MAGPIE_BIN")
    if env and Path(env).is_file():
        return env, "env MAGPIE_BIN"
    hit = _from_path()
    if hit:
        return hit, "PATH"
    hit = _from_running_process()
    if hit:
        return hit, "running process"
    hit = _from_known_dirs()
    if hit:
        return hit, "known directory"
    return None, "not found"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except Exception as exc:
        return {"__error__": f"{type(exc).__name__}: {exc}"}


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def http_get(url: str, timeout: float = 10.0) -> tuple[int | None, float, int, str]:
    t0 = time.time()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, time.time() - t0, len(body), ""
    except urllib.error.HTTPError as exc:
        return exc.code, time.time() - t0, 0, f"HTTPError {exc.code}"
    except Exception as exc:
        return None, time.time() - t0, 0, f"{type(exc).__name__}: {exc}"


def norm_base(url: str) -> str:
    """Strip a trailing /v1 so endpoint paths can be appended uniformly.

    pi's models.json stores the OpenAI-style baseUrl, i.e. it already ends in
    /v1; appending "/v1/models" to that yields /v1/v1/models -> spurious 404.
    """
    url = url.rstrip("/")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def detect_base_url(explicit: str | None, port: int) -> tuple[str, str]:
    """Prefer an explicit --base-url, then pi's wiring, then the default port."""
    if explicit:
        return norm_base(explicit), "arg --base-url"
    data = read_json(PI_AGENT / "models.json")
    if isinstance(data, dict):
        prov = (data.get("providers") or {}).get("magpie") or {}
        base = prov.get("baseUrl")
        if isinstance(base, str) and base.startswith("http"):
            return norm_base(base), "pi models.json"
    return f"http://127.0.0.1:{port}", "default"


# --------------------------------------------------------------------------
# checks
# --------------------------------------------------------------------------

def check_binary(binary: str | None, source: str) -> None:
    if not binary:
        add(BAD, "binary",
            "magpie not found (env MAGPIE_BIN / PATH / running process / known dirs all empty)")
        add(INFO, "binary", "hint: run `Get-Process magpie* | Select-Object Id,Path` "
                            "while the gateway is up, then set MAGPIE_BIN")
        return
    add(OK, "binary", f"{binary}  (found via {source})")
    rc, out = run([binary, "--version"], timeout=20)
    if rc == 0:
        add(OK, "binary", f"version: {out.splitlines()[0] if out else '?'}")
    else:
        add(WARN, "binary", f"--version failed (rc={rc}): {out[:200]}")


def check_configs() -> None:
    if MAGPIE_CONFIG.is_dir():
        files = sorted(p for p in MAGPIE_CONFIG.iterdir() if p.is_file())
        add(OK, "config", f"{MAGPIE_CONFIG}  ({len(files)} files)")
        for key in ("providers.json", "settings.json", "quotas.json"):
            p = MAGPIE_CONFIG / key
            if p.is_file():
                data = read_json(p)
                bad = isinstance(data, dict) and "__error__" in data
                add(BAD if bad else OK, "config",
                    f"{key}: {p.stat().st_size} B" + (f"  JSON ERROR {data['__error__']}" if bad else ""))
            else:
                add(WARN, "config", f"{key} missing")
        routing = MAGPIE_CONFIG / "routing"
        if routing.is_dir():
            logs = list(routing.glob("*"))
            add(INFO, "config", f"routing logs: {len(logs)} file(s) in {routing}")
    else:
        add(BAD, "config", f"{MAGPIE_CONFIG} does not exist - magpie may never have run")

    if not PI_AGENT.is_dir():
        add(BAD, "config", f"{PI_AGENT} does not exist - the pi CLI is not set up")
        return

    models = read_json(PI_AGENT / "models.json")
    if models is None:
        add(WARN, "pi", f"{PI_AGENT / 'models.json'} missing - pi has no providers file")
        return
    if isinstance(models, dict) and "__error__" in models:
        add(BAD, "pi", f"models.json is not valid JSON: {models['__error__']}")
        return
    providers = list((models.get("providers") or {}).keys())
    add(INFO, "pi", f"models.json providers: {providers or '(none)'}")
    if not providers:
        add(BAD, "pi", "no providers configured - pi cannot call anything")
    elif providers == ["magpie"]:
        add(OK, "pi", "single-provider setup (magpie) - the intended wiring")
    elif "magpie" in providers:
        extra = [p for p in providers if p != "magpie"]
        add(WARN, "pi",
            f"{len(extra)} direct provider(s) besides magpie: {extra} - "
            "dead ones add startup latency; verify each with a real call before removing")
    else:
        add(WARN, "pi", "magpie is not among pi's providers - is pi bypassing the gateway?")

    settings = read_json(PI_AGENT / "settings.json")
    if isinstance(settings, dict) and "__error__" not in settings:
        add(INFO, "pi", "defaultProvider={!r} defaultModel={!r} thinking={!r}".format(
            settings.get("defaultProvider"), settings.get("defaultModel"),
            settings.get("defaultThinkingLevel")))
        if settings.get("defaultProvider") != "magpie":
            add(WARN, "pi", "defaultProvider is not 'magpie' - the CLI will bypass the gateway")

    auth = PI_AGENT / "auth.json"
    if auth.is_file():
        data = read_json(auth)
        n = len(data) if isinstance(data, dict) and "__error__" not in data else "?"
        add(INFO, "pi", f"auth.json entries: {n} (expected 0/{{}} when only magpie is wired)")


def check_cli(binary: str | None) -> None:
    if not binary:
        add(INFO, "cli", "skipped (no magpie binary)")
        return

    rc, out = run([binary, "healthcheck"], timeout=60)
    if rc == 0:
        add(OK, "gateway", "magpie healthcheck -> exit 0")
    else:
        add(BAD, "gateway", f"magpie healthcheck exit {rc}: {out[:200] or '(no output)'}")

    rc, out = run([binary, "providers"], timeout=60)
    if rc == 0:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        on = sum(1 for ln in lines if "●" in ln or " on " in ln)
        add(OK, "providers", f"{len(lines)} line(s) of output")
        for ln in lines:
            if not SILENT:
                print(f"         | {ln}")
    else:
        add(WARN, "providers", f"`providers` failed (rc={rc}): {out[:200]}")

    rc, out = run([binary, "groups"], timeout=60)
    if rc == 0:
        lines = [ln for ln in out.splitlines() if ln.strip()]
        add(OK, "groups", f"{len(lines)} line(s) of output")
        if any("order" in ln.lower() for ln in lines):
            add(INFO, "groups",
                "at least one group uses routing=order - the first member is a strict priority, "
                "so it must be the fastest one you actually measured")
        for ln in lines:
            if not SILENT:
                print(f"         | {ln}")
    else:
        add(WARN, "groups", f"`groups` failed (rc={rc}): {out[:200]}")

    rc, out = run([binary, "ls"], timeout=60)
    if rc == 0:
        add(OK, "wiring", "magpie ls:")
        for ln in [ln for ln in out.splitlines() if ln.strip()]:
            if not SILENT:
                print(f"         | {ln}")
    else:
        add(WARN, "wiring", f"`ls` failed (rc={rc}): {out[:200]}")


def check_gateway(base_url: str, base_src: str) -> None:
    host, port = "127.0.0.1", DEFAULT_PORT
    try:
        tail = base_url.split("//", 1)[1]
        hostport = tail.split("/", 1)[0]
        if ":" in hostport:
            host, port_s = hostport.rsplit(":", 1)
            port = int(port_s)
    except Exception:
        pass
    add(INFO, "gateway", f"base url {base_url}  (from {base_src})")

    if tcp_open(host, port):
        add(OK, "gateway", f"TCP {host}:{port} reachable")
    else:
        add(BAD, "gateway", f"TCP {host}:{port} refused - the gateway is not listening")
        return

    for path in ("/v1/models", "/"):
        status, dt, size, err = http_get(f"{base_url}{path}", timeout=15)
        if status and 200 <= status < 300:
            add(OK, "gateway", f"GET {path} -> {status} {dt:.2f}s {size} B (no auth needed on loopback)")
        elif status:
            add(WARN, "gateway", f"GET {path} -> {status} {dt:.2f}s {err}")
        else:
            add(BAD, "gateway", f"GET {path} failed after {dt:.2f}s {err}")

    # /health is a known non-endpoint: expect 404, which still proves the server answers.
    status, dt, _, _ = http_get(f"{base_url}/health", timeout=10)
    if status == 404:
        add(INFO, "gateway", "/health -> 404 (expected: there is no such endpoint; "
                                "use `magpie healthcheck` instead)")
    elif status:
        add(INFO, "gateway", f"/health -> {status}")


# --------------------------------------------------------------------------

def main() -> int:
    global SILENT
    ap = argparse.ArgumentParser(description="Read-only health report for magpie + pi.")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of text")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"gateway port (default {DEFAULT_PORT})")
    ap.add_argument("--base-url", default=None, help="gateway base url (overrides port/pi wiring)")
    ap.add_argument("--no-cli", action="store_true", help="skip magpie CLI subcommands")
    args = ap.parse_args()

    base_url, base_src = detect_base_url(args.base_url, args.port)

    if args.json:
        SILENT = True
    else:
        print("magpie doctor - read-only report")
        print("=" * 72)

    binary, source = find_magpie()
    check_binary(binary, source)
    check_configs()
    if not args.no_cli:
        check_cli(binary)
    check_gateway(base_url, base_src)

    if args.json:
        counts = {lv: sum(1 for r in report if r["level"] == lv) for lv in (OK, WARN, BAD, INFO)}
        print(json.dumps({
            "binary": {"path": binary, "found_via": source},
            "base_url": base_url,
            "counts": counts,
            "checks": report,
        }, ensure_ascii=False, indent=2))
    else:
        bad = sum(1 for r in report if r["level"] == BAD)
        warn = sum(1 for r in report if r["level"] == WARN)
        print("=" * 72)
        print(f"summary: {bad} failure(s), {warn} warning(s)")

    return 1 if any(r["level"] == BAD for r in report) else 0


if __name__ == "__main__":
    sys.exit(main())
