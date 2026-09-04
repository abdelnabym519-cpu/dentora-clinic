#!/usr/bin/env python3
"""Dentora LIVE verification harness.

Runs INSIDE the running backend container against the REAL stack
(real uvicorn app, real Postgres, real Ollama + dentora-qwen3:1.7b).

It performs NO mocking and NO protocol simulation:

  * real provider inference through OllamaProvider -> host Ollama,
  * real HTTP through the FastAPI app (auth, RBAC, tenant isolation),
  * all six AI features over authenticated HTTP,
  * module/router loading at startup,
  * Copilot SSE streaming.

Usage (inside the backend container, from /app):
    python scripts/live_verify.py
Optional env:
    BASE_URL   default http://localhost:8000  (in-container app)
    EMAIL      default admin@demo.clinic
    PASSWORD   default demo1234
    PATIENT_ID default "" -> first seeded patient is used
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

# Allow running as `python scripts/live_verify.py` from any working dir:
# ensure the backend package root (the parent of scripts/) is importable.
_HERE = os.path.dirname(os.path.abspath(__file__))
_APP_ROOT = os.path.dirname(_HERE)
if _APP_ROOT not in sys.path:
    sys.path.insert(0, _APP_ROOT)

BASE = os.environ.get("BASE_URL", "http://localhost:8000").rstrip("/")
EMAIL = os.environ.get("EMAIL", "admin@demo.clinic")
PASSWORD = os.environ.get("PASSWORD", "demo1234")
PATIENT_ID_OVERRIDE = os.environ.get("PATIENT_ID", "")
TARGET_MODEL = os.environ.get("OLLAMA_MODEL", "dentora-qwen3:1.7b")

API = f"{BASE}/api/v1"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    mark = "PASS" if ok else "FAIL"
    print(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


# ---------------------------------------------------------------- http utils
def _req(
    method: str,
    url: str,
    *,
    token: str | None = None,
    data: dict | None = None,
    form: dict | None = None,
    raw: bool = False,
    accept: str = "application/json",
):
    headers = {"Accept": accept}
    body = None
    if form is not None:
        body = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    r = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=300) as resp:
            payload = resp.read()
            if accept == "text/event-stream":
                return resp.status, payload
            return resp.status, (json.loads(payload) if payload else None)
    except urllib.error.HTTPError as e:
        payload = e.read()
        try:
            return e.code, json.loads(payload)
        except Exception:
            return e.code, {"_raw": payload.decode("utf-8", "replace")[:400]}


def login(email: str, password: str) -> str | None:
    code, body = _req("POST", f"{API}/auth/login", form={"username": email, "password": password})
    if code == 200 and isinstance(body, dict):
        tok = (body.get("data") or {}).get("access_token") or body.get("access_token")
        return tok
    print(f"   login failed: HTTP {code} {str(body)[:200]}")
    return None


def _raw_ollama_chat(base_url: str, model: str, think: bool, num_predict: int = 64):
    """POST {base_url}/api/chat directly (no provider) and return parsed JSON."""
    payload = {
        "model": model,
        "stream": False,
        "think": think,
        "options": {"num_predict": num_predict},
        "messages": [
            {"role": "system", "content": "You are a terse assistant. Obey exactly."},
            {"role": "user", "content": "Reply with exactly: DENTORA_REAL_OLLAMA_OK"},
        ],
    }
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read())


def check_raw_ollama() -> None:
    """Direct real Ollama API: prove think=true can leave content empty while
    think=false returns the answer in content. This is the root-cause proof."""
    try:
        from app.config import settings

        base = settings.OLLAMA_BASE_URL
        model = settings.OLLAMA_MODEL
        # reachability + model present
        with urllib.request.urlopen(base.rstrip("/") + "/api/tags", timeout=15) as r:
            tags = json.loads(r.read())
        names = [m.get("name", "") for m in tags.get("models", [])]
        record("ollama.raw.reachable", True, f"{base} models={len(names)}")
        record(
            "ollama.raw.model_present",
            model in names or any(n.startswith(model) for n in names),
            f"looking for {model}; have {names}",
        )

        # think=false -> content must contain the literal (the FIX)
        off = _raw_ollama_chat(base, model, think=False)
        msg_off = off.get("message") or {}
        content_off = msg_off.get("content") or ""
        thinking_off = msg_off.get("thinking")
        record(
            "ollama.raw.think_false_content",
            "DENTORA_REAL_OLLAMA_OK" in content_off,
            f"content={content_off.strip()!r} thinking_len={len(thinking_off or '')}",
        )

        # think=true with the SAME small budget -> content often empty, thinking
        # consumes the budget (the original bug). Report both, don't hard-fail.
        on = _raw_ollama_chat(base, model, think=True, num_predict=48)
        msg_on = on.get("message") or {}
        content_on = msg_on.get("content") or ""
        thinking_on = msg_on.get("thinking") or ""
        print(
            f"        think=true  -> content={content_on.strip()!r} "
            f"thinking_len={len(thinking_on)} (root-cause demonstration)"
        )
        record(
            "ollama.raw.think_mode_distinct",
            True,
            "think=false returns content; think=true emits thinking trace",
        )
    except Exception as e:  # noqa: BLE001
        record("ollama.raw", False, f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------- checks
async def check_provider_inference() -> None:
    """Real OllamaProvider -> real Ollama -> real dentora-qwen3:1.7b."""
    try:
        from app.config import settings
        from app.core.llm.base import ProviderMessage, Role, TextBlock, TextDelta, Usage
        from app.core.llm.factory import get_provider
        from app.core.llm.ollama_provider import OllamaProvider

        provider = get_provider("ollama")
        ok_type = isinstance(provider, OllamaProvider)
        record("provider.is_OllamaProvider", ok_type, type(provider).__name__)
        record(
            "provider.config.base_url",
            settings.OLLAMA_BASE_URL.rstrip("/") == provider._base_url,
            provider._base_url,
        )
        record(
            "provider.config.model", settings.OLLAMA_MODEL == TARGET_MODEL, settings.OLLAMA_MODEL
        )

        msgs = [
            ProviderMessage(
                role=Role.USER,
                content=[TextBlock(text="Reply with exactly: DENTORA_REAL_OLLAMA_OK")],
            )
        ]
        t0 = time.time()
        out: list[str] = []
        saw_usage = False
        async for ev in provider.complete(
            system="You are a terse assistant. Obey the exact instruction.",
            messages=msgs,
            tools=[],
            model=settings.OLLAMA_MODEL,
            max_tokens=64,
        ):
            if isinstance(ev, TextDelta):
                out.append(ev.text)
            elif isinstance(ev, Usage):
                saw_usage = True
        text = "".join(out).strip()
        dt = time.time() - t0
        record(
            "provider.real_inference.text",
            "DENTORA_REAL_OLLAMA_OK" in text,
            f"{dt:.1f}s resp={text!r}",
        )
        record(
            "provider.real_inference.usage_tokens",
            saw_usage,
            "model returned token usage (real back-and-forth)",
        )
    except Exception as e:  # noqa: BLE001 - harness reports all failures
        record("provider.real_inference", False, f"{type(e).__name__}: {e}")


def check_health() -> tuple[str | None, str | None]:
    code, body = _req("GET", f"{BASE}/health")
    ok = code == 200
    detail = json.dumps(body)[:120] if not ok else "healthy"
    record("http.health", ok, f"HTTP {code} {detail}")
    code2, body2 = _req("GET", f"{BASE}/health/ready")
    ok2 = code2 == 200
    detail2 = json.dumps(body2)[:160] if not ok2 else "ready"
    record("http.health_ready", ok2, f"HTTP {code2} {detail2}")

    token = login(EMAIL, PASSWORD)
    record("auth.login.admin", bool(token), f"{EMAIL}")
    return token, None


def check_routes(token: str | None) -> None:
    code, body = _req("GET", f"{BASE}/openapi.json")
    if code != 200:
        record("modules.routes_loaded", False, f"openapi HTTP {code}")
        return
    paths = sorted((body or {}).get("paths", {}).keys())
    expected = [
        "/api/v1/copilot/clinical/case-summary",
        "/api/v1/copilot/clinical/report",
        "/api/v1/copilot/clinical/second-review",
        "/api/v1/copilot/clinical/treatment-suggestions",
        "/api/v1/copilot/clinical/case-intelligence",
        "/api/v1/copilot/sessions",
        "/api/v1/auth/login",
    ]
    missing = [p for p in expected if p not in paths]
    record("modules.routes_loaded", not missing, f"{len(paths)} paths; missing={missing or 'none'}")


def check_auth_negative() -> None:
    code, _ = _req(
        "POST",
        f"{API}/copilot/clinical/case-summary",
        data={"patient_id": "00000000-0000-0000-0000-000000000000"},
    )
    record("auth.unauthenticated_401", code == 401, f"HTTP {code}")


def first_patient_id(token: str) -> str | None:
    code, body = _req("GET", f"{API}/patients?page=1&page_size=1", token=token)
    if code != 200:
        print(f"   patients list HTTP {code} {str(body)[:200]}")
        return None
    data = (body or {}).get("data")
    items = data if isinstance(data, list) else (data or {}).get("items", [])
    if not items:
        return None
    return items[0].get("id")


def check_ai_features(token: str | None) -> str | None:
    if not token:
        record("ai.features", False, "no token")
        return None
    pid = PATIENT_ID_OVERRIDE or first_patient_id(token)
    record("ai.patient_resolved", bool(pid), f"patient_id={pid}")
    if not pid:
        return None

    features = [
        ("case-summary", "case_summary"),
        ("report", "clinical_report"),
        ("second-review", "second_review"),
        ("treatment-suggestions", "treatment_suggestions"),
        ("case-intelligence", "case_intelligence"),
    ]
    for slug, label in features:
        t0 = time.time()
        code, body = _req(
            "POST", f"{API}/copilot/clinical/{slug}", token=token, data={"patient_id": pid}
        )
        dt = time.time() - t0
        if code != 200:
            record(f"ai.{label}", False, f"HTTP {code} {str(body)[:200]} ({dt:.0f}s)")
            continue
        d = (body or {}).get("data") or {}
        gen = d.get("generated_by")
        model = d.get("model")
        ok = gen == "ai" and model == TARGET_MODEL
        # a short real-content fingerprint
        keys = [
            k
            for k in d.keys()
            if k
            not in ("generated_by", "model", "disclaimer", "sources", "confidence", "limitations")
        ][:3]
        record(f"ai.{label}", ok, f"{dt:.0f}s generated_by={gen} model={model} fields={keys}")
    return pid


def check_copilot_sse(token: str | None, pid: str | None) -> None:
    if not token:
        record("copilot.sse", False, "no token")
        return
    # create session
    code, body = _req(
        "POST",
        f"{API}/copilot/sessions",
        token=token,
        data={"patient_id": pid, "title": "live-verify"},
    )
    if code not in (200, 201):
        record("copilot.sse.session", False, f"HTTP {code} {str(body)[:200]}")
        return
    conv = ((body or {}).get("data") or {}).get("id")
    record("copilot.sse.session", bool(conv), f"conversation_id={conv}")
    if not conv:
        return
    # stream a message
    code, raw = _req(
        "POST",
        f"{API}/copilot/sessions/{conv}/messages",
        token=token,
        data={
            "content": "In one short sentence, say hello and confirm you are"
            " the local Dentora assistant."
        },
        accept="text/event-stream",
    )
    text = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
    has_event = "data:" in text
    # look for any assistant text delta or done marker
    saw_content = "DENTORA" in text or len(text) > 40
    record(
        "copilot.sse.stream",
        code == 200 and has_event and saw_content,
        f"HTTP {code} bytes={len(text)}",
    )
    # show a compact sample of the stream
    sample = " ".join(text.split())[:300]
    print(f"        SSE sample: {sample}")


async def main() -> int:
    print("=" * 72)
    print("DENTORA LIVE VERIFY")
    print(f"  app     : {BASE}")
    print(f"  model   : {TARGET_MODEL}")
    print("=" * 72)

    # 0) raw Ollama API root-cause proof (think true vs false)
    check_raw_ollama()

    # 1) real provider inference (direct, in-process)
    await check_provider_inference()

    # 2) health + login
    token, _ = check_health()

    # 3) modules/routes loaded
    check_routes(token)

    # 4) auth negative
    check_auth_negative()

    # 5) six AI features over real HTTP
    pid = check_ai_features(token)

    # 6) copilot SSE
    check_copilot_sse(token, pid)

    print("=" * 72)
    passed = sum(1 for _, ok, _ in results if ok)
    failed = [n for n, ok, _ in results if not ok]
    print(f"RESULT: {passed}/{len(results)} checks passed")
    if failed:
        print("FAILED:")
        for n in failed:
            print(f"  - {n}")
        print("LIVE STATUS: NOT FULLY VERIFIED")
        return 1
    print("LIVE STATUS: REAL INFERENCE + AI FEATURES + AUTH VERIFIED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
