#!/usr/bin/env python3
"""gateway_probe.py - probe a magpie gateway's HTTP endpoints, with real timings.

Answers the only question that matters when something "feels slow":
*which endpoint answers, how fast, and which model actually served the request?*

Read-only: it only issues GETs plus one tiny POST (max_tokens is capped) to
/v1/chat/completions. It never changes configuration.

Usage:
    python gateway_probe.py
    python gateway_probe.py --json
    python gateway_probe.py --model group/auto-gemini-3-8-flash
    python gateway_probe.py --no-call          # skip the real completion call
    python gateway_probe.py --base-url http://127.0.0.1:3425/v1

Exit code is 0 when the gateway answers /v1/models, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PI_AGENT = Path.home() / ".pi" / "agent"
DEFAULT_BASE = "http://127.0.0.1:3425/v1"


def load_pi_wiring() -> tuple[str | None, str | None, list[str]]:
    """Read pi's own wiring so probes default to what pi actually uses."""
    try:
        data = json.loads((PI_AGENT / "models.json").read_text(encoding="utf-8"))
    except Exception:
        return None, None, []
    prov = (data.get("providers") or {}).get("magpie") or {}
    base = prov.get("baseUrl")
    key = prov.get("apiKey")
    models = [m.get("id") for m in prov.get("models", []) if isinstance(m, dict) and m.get("id")]
    return base, key, models


def _key(s: str) -> str:
    """Normalize separators: model ids mix dots and hyphens (gemini-3.8-flash vs -3-8-)."""
    return s.lower().replace(".", "-")


def pick_default_model(ids: list[str]) -> str:
    """Prefer a routing group: it fails over for us, a bare provider id does not."""
    fallback = "group/auto-gemini-3-8-flash"
    want = "gemini-3-8-flash"
    groups = sorted(i for i in ids if i.startswith("group/"))
    if groups:
        return next((i for i in groups if want in _key(i)), groups[0])
    plain = sorted(i for i in ids if i)
    return next((i for i in plain if want in _key(i)), plain[0]) if plain else fallback


def norm_base(url: str) -> str:
    """Strip a trailing /v1 so endpoint paths can be appended uniformly."""
    url = url.rstrip("/")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def tcp_open(host: str, port: int, timeout: float = 2.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def request(url: str, method: str = "GET", body: dict | None = None,
            headers: dict | None = None, timeout: float = 120.0) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    hdrs = {"Content-Type": "application/json", "User-Agent": "gateway_probe.py"}
    hdrs.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return {"ok": 200 <= resp.status < 300, "status": resp.status,
                    "seconds": round(time.time() - t0, 2), "bytes": len(raw),
                    "text": raw.decode("utf-8", "replace"), "error": None}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        return {"ok": False, "status": exc.code, "seconds": round(time.time() - t0, 2),
                "bytes": len(raw), "text": raw.decode("utf-8", "replace"),
                "error": f"HTTPError {exc.code}"}
    except Exception as exc:
        return {"ok": False, "status": None, "seconds": round(time.time() - t0, 2),
                "bytes": 0, "text": "", "error": f"{type(exc).__name__}: {exc}"}


def served_model(payload_text: str) -> str | None:
    """Extract the model that actually served the request - the hard evidence."""
    try:
        obj = json.loads(payload_text)
    except Exception:
        return None
    if isinstance(obj, dict):
        if isinstance(obj.get("model"), str):
            return obj["model"]
        choices = obj.get("choices")
        if isinstance(choices, list) and choices and isinstance(choices[0], dict):
            m = choices[0].get("model")
            if isinstance(m, str):
                return m
    return None


def content_preview(payload_text: str) -> str | None:
    try:
        obj = json.loads(payload_text)
    except Exception:
        return None
    try:
        msg = obj["choices"][0]["message"]["content"]
        return msg if isinstance(msg, str) else None
    except Exception:
        return None


def main() -> int:
    wiring_base, wiring_key, wiring_models = load_pi_wiring()

    ap = argparse.ArgumentParser(description="Probe magpie gateway endpoints (read-only).")
    ap.add_argument("--base-url", default=None,
                    help="gateway base url; default: pi's models.json, else " + DEFAULT_BASE)
    ap.add_argument("--model", default=None,
                    help="model id for the real call; default: a group/auto-* from pi's wiring")
    ap.add_argument("--api-key", default=None, help="optional bearer key (loopback usually needs none)")
    ap.add_argument("--no-call", action="store_true", help="skip the real completion request")
    ap.add_argument("--max-tokens", type=int, default=32, help="cap for the real call (default 32)")
    ap.add_argument("--timeout", type=float, default=180.0, help="per-request timeout in seconds")
    ap.add_argument("--json", action="store_true", help="emit JSON")
    args = ap.parse_args()

    base = norm_base(args.base_url or wiring_base or DEFAULT_BASE)
    base_src = "arg" if args.base_url else ("pi models.json" if wiring_base else "default")
    model = args.model or pick_default_model(wiring_models or [])
    key = args.api_key or wiring_key

    try:
        hostport = base.split("//", 1)[1].split("/", 1)[0]
        host, port = (hostport.rsplit(":", 1) + ["80"])[:2] if ":" in hostport else (hostport, "80")
        port = int(port)
    except Exception:
        host, port = "127.0.0.1", 3425

    results: list[dict] = []
    text_lines: list[str] = []

    def emit(level: str, msg: str) -> None:
        results.append({"level": level, "message": msg})
        if not args.json:
            text_lines.append(f"[{level:<4}] {msg}")

    emit("INFO", f"base url      : {base}  (from {base_src})")
    emit("INFO", f"model for call: {model}")

    if tcp_open(host, port):
        emit("OK", f"tcp {host}:{port} reachable")
    else:
        emit("FAIL", f"tcp {host}:{port} refused - is the magpie gateway running?")
        if args.json:
            print(json.dumps({"base_url": base, "model": model, "results": results},
                             ensure_ascii=False, indent=2))
        else:
            print("\n".join(text_lines))
        return 1

    # --- read-only endpoints -------------------------------------------------
    r = request(f"{base}/v1/models", timeout=args.timeout)
    if r["ok"]:
        ids: list[str] = []
        try:
            payload = json.loads(r["text"])
            rows = payload.get("data") if isinstance(payload, dict) else payload
            ids = [row.get("id") for row in rows if isinstance(row, dict) and row.get("id")]
        except Exception:
            pass
        emit("OK", f"GET /v1/models -> {r['status']} in {r['seconds']}s, {r['bytes']} B, "
                   f"{len(ids)} model id(s), no auth on loopback")
        if ids and not args.json:
            text_lines.append("        e.g. " + ", ".join(ids[:6]))
    else:
        emit("FAIL", f"GET /v1/models -> {r['status']} in {r['seconds']}s "
                     f"({r['error'] or 'no response'})")

    for path in ("/", "/v1/magpie/quotas"):
        rr = request(f"{base}{path}", timeout=args.timeout)
        level = "OK" if rr["ok"] else ("INFO" if rr["status"] in (401, 403, 404) else "WARN")
        emit(level, f"GET {path} -> {rr['status']} in {rr['seconds']}s, {rr['bytes']} B"
                    + (f" ({rr['error']})" if rr["error"] else ""))

    # /health does not exist; a 404 still proves the server is answering.
    rr = request(f"{base}/health", timeout=args.timeout)
    emit("INFO" if rr["status"] == 404 else "WARN",
         f"GET /health -> {rr['status']} in {rr['seconds']}s "
         "(expected 404: use `magpie healthcheck` instead)")

    if args.no_call:
        if args.json:
            print(json.dumps({"base_url": base, "model": model, "results": results},
                             ensure_ascii=False, indent=2))
        else:
            print("\n".join(text_lines))
        return 0 if results[0]["level"] != "FAIL" else 1

    # --- the real thing: one tiny completion, timed --------------------------
    payload = {"model": model,
               "messages": [{"role": "user", "content": "Reply with the single word: OK"}],
               "max_tokens": args.max_tokens, "stream": False}
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    rc = request(f"{base}/v1/chat/completions", "POST", payload, headers, timeout=args.timeout)
    if rc["ok"]:
        served = served_model(rc["text"]) or "?"
        preview = (content_preview(rc["text"]) or "").strip().replace("\n", " ")[:60]
        emit("OK", f"POST /v1/chat/completions -> {rc['status']} in {rc['seconds']}s "
                   f"(max_tokens={args.max_tokens})")
        emit("OK", f"served by model: {served!r}   <- hard evidence of routing")
        if preview:
            emit("INFO", f"content: {preview!r}")
        if served in ("?", model) and "group/" in model:
            emit("INFO", "the response names the member model, not the group - routing resolved")
    else:
        hint = " (the gateway may reject a request whose model id it does not know)"
        emit("FAIL", f"POST /v1/chat/completions -> {rc['status']} in {rc['seconds']}s"
                     f" {rc['error'] or ''}{hint}")
        if rc["text"]:
            emit("INFO", "body: " + rc["text"][:300].replace("\n", " "))

    if args.json:
        print(json.dumps({"base_url": base, "model": model, "results": results},
                         ensure_ascii=False, indent=2))
    else:
        print("\n".join(text_lines))
        fails = [r for r in results if r["level"] == "FAIL"]
        print("-" * 68)
        print(f"{len(fails)} failure(s)")
    return 0 if not any(r["level"] == "FAIL" for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
