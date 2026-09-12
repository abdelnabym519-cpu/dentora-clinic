"""The AI provider doctor must name the real cause, not just "unavailable".

These tests drive ``scripts/diagnose_ai_provider.py`` against a real local
HTTP stub of Ollama's OpenAI-compatible surface, so the healthy path and
each failure mode are exercised end to end (including ``--probe``, which
runs a genuine completion through the production provider object) rather
than being asserted from mocked internals.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from app.config import settings


def _load_doctor():
    """Load the script as a module (``scripts/`` is not an import package)."""
    path = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_ai_provider.py"
    spec = importlib.util.spec_from_file_location("diagnose_ai_provider", path)
    module = importlib.util.module_from_spec(spec)
    # Register before executing: `@dataclass` resolves string annotations via
    # `sys.modules[cls.__module__]`, so an unregistered module blows up at
    # import time.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = _load_doctor()


class SettingsPatch:
    """Same pattern as test_ollama_provider.py — swap settings, restore."""

    def __init__(self, **values):
        self.values = values
        self.original = {}

    def __enter__(self):
        for key, value in self.values.items():
            self.original[key] = getattr(settings, key)
            setattr(settings, key, value)
        return self

    def __exit__(self, exc_type, exc, tb):
        for key, value in self.original.items():
            setattr(settings, key, value)


# --- Ollama stub ----------------------------------------------------------


class _StubHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep pytest output readable
        pass

    def _json(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802 - http.server API
        if self.path.rstrip("/").endswith("/models"):
            models = self.server.stub_models
            self._json(200, {"object": "list", "data": [{"id": m} for m in models]})
        else:
            self._json(404, {"error": {"message": "not found"}})

    def do_POST(self):  # noqa: N802 - http.server API
        length = int(self.headers.get("Content-Length") or 0)
        request = json.loads(self.rfile.read(length) or b"{}")
        model = request.get("model", "")
        chat_status = self.server.stub_chat_status
        if chat_status != 200:
            self._json(chat_status, {"error": {"message": f"model '{model}' not found"}})
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        chunk = {
            "id": "c1",
            "object": "chat.completion.chunk",
            "model": model,
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": None}],
        }
        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
        self.wfile.write(b"data: [DONE]\n\n")


@pytest.fixture
def stub_ollama():
    """A live stub of Ollama's ``/v1`` surface on an ephemeral port."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    server.stub_models = ["qwen3:8b"]
    server.stub_chat_status = 200
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address[:2]
    try:
        yield server, f"http://{host}:{port}/v1/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _closed_port_url() -> str:
    """A URL whose port nothing is listening on (connection refused)."""
    probe = ThreadingHTTPServer(("127.0.0.1", 0), _StubHandler)
    port = probe.server_address[1]
    probe.server_close()
    return f"http://127.0.0.1:{port}/v1/"


# --- Pure helpers ---------------------------------------------------------


class TestModelMatching:
    def test_exact_tag_matches(self):
        assert doctor._model_present("qwen3:8b", ["qwen3:8b", "llama3.2:3b"])

    def test_bare_name_matches_any_tag_of_that_model(self):
        """``qwen3`` must accept ``qwen3:8b`` — Ollama tags are optional."""
        assert doctor._model_present("qwen3", ["qwen3:8b"])
        assert doctor._model_present("qwen3:latest", ["qwen3:8b"])

    def test_different_model_does_not_match(self):
        assert not doctor._model_present("qwen3:8b", ["llama3.2:3b"])

    def test_empty_requirement_matches(self):
        assert doctor._model_present("", ["llama3.2:3b"])


class TestProviderResolution:
    def test_explicit_setting_wins(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="openai", ENVIRONMENT="development"):
            provider, source = doctor.resolved_provider()
        assert provider == "openai"
        assert "explicit" in source

    def test_environment_derives_when_unset(self):
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="", ENVIRONMENT="development"):
            provider, source = doctor.resolved_provider()
        assert provider == "ollama"
        assert "derived" in source


# --- Full runs ------------------------------------------------------------


class TestDoctorRuns:
    def test_healthy_provider_exits_zero(self, stub_ollama, capsys):
        _server, url = stub_ollama
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=url):
            code = doctor.main([])
        out = capsys.readouterr().out
        assert code == 0
        assert "is usable" in out
        assert "required 'qwen3:8b'" in out and "present" in out

    def test_probe_runs_a_real_completion(self, stub_ollama, capsys):
        _server, url = stub_ollama
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=url):
            code = doctor.main(["--probe"])
        out = capsys.readouterr().out
        assert code == 0
        assert "with a real completion" in out
        assert "model said" in out
        assert "ok" in out

    def test_refused_connection_names_the_loopback_binding(self, capsys):
        with SettingsPatch(
            COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=_closed_port_url()
        ):
            code = doctor.main([])
        out = capsys.readouterr().out
        assert code == 1
        assert "REFUSED" in out
        assert "OLLAMA_HOST=0.0.0.0" in out
        assert "NOT usable" in out

    def test_unresolvable_host_names_the_gateway_mapping(self, capsys):
        with SettingsPatch(
            COPILOT_PROVIDER_DEFAULT="ollama",
            OLLAMA_BASE_URL="http://host.docker.internal.invalid:11434/v1/",
        ):
            code = doctor.main([])
        out = capsys.readouterr().out
        assert code == 1
        assert "does not resolve" in out
        assert "host-gateway" in out

    def test_unpulled_model_names_ollama_pull(self, stub_ollama, capsys):
        server, url = stub_ollama
        server.stub_models = ["llama3.2:3b"]
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=url):
            code = doctor.main([])
        out = capsys.readouterr().out
        assert code == 1
        assert "MISSING" in out
        assert "ollama pull qwen3:8b" in out

    def test_probe_surfaces_the_translated_404(self, stub_ollama, capsys):
        """The provider answers 404 for an unpulled model: the probe must show
        the neutral ``LLMUnavailableError`` text, not a raw vendor traceback."""
        server, url = stub_ollama
        server.stub_chat_status = 404
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=url):
            code = doctor.main(["--probe"])
        out = capsys.readouterr().out
        assert code == 1
        assert "LLMUnavailableError" in out
        assert "ollama pull qwen3:8b" in out

    def test_empty_openai_key_is_reported_as_a_failure(self, capsys):
        with SettingsPatch(
            COPILOT_PROVIDER_DEFAULT="openai",
            OPENAI_API_KEY="",
            LICENSE_ENFORCEMENT=False,
            ENVIRONMENT="development",
        ):
            code = doctor.main([])
        out = capsys.readouterr().out
        assert code == 1
        assert "OPENAI_API_KEY is empty" in out

    def test_unreachable_database_degrades_to_a_warning(self, stub_ollama, monkeypatch, capsys):
        """``--db`` must not explode when the database is not reachable from
        wherever the doctor is being run."""
        _server, url = stub_ollama

        async def _boom():
            raise RuntimeError("connection refused")

        monkeypatch.setattr(doctor, "_load_clinic_overrides", _boom)
        with SettingsPatch(COPILOT_PROVIDER_DEFAULT="ollama", OLLAMA_BASE_URL=url):
            code = doctor.main(["--db"])
        out = capsys.readouterr().out
        assert code == 0  # the provider itself is fine
        assert "WARN" in out and "copilot_settings" in out


class TestTeardownNoiseFilter:
    def test_only_the_asyncgen_close_message_is_swallowed(self):
        forwarded: list[dict] = []

        class _Loop:
            def default_exception_handler(self, context):
                forwarded.append(context)

        loop = _Loop()
        doctor._ignore_asyncgen_teardown(
            loop, {"message": "an error occurred during closing of asynchronous generator <x>"}
        )
        assert forwarded == []

        doctor._ignore_asyncgen_teardown(loop, {"message": "Task exception was never retrieved"})
        assert len(forwarded) == 1
