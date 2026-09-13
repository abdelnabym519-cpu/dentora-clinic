"""Development stand-in for a local OpenAI-compatible LLM endpoint.

Purpose
-------
Dentora's AI modules call ``OLLAMA_URL`` with ``response_format``
``{"type": "json_schema"}``.  Validating the *rest* of a chain (case
intelligence -> treatment planning -> simulation -> second review -> report ->
copilot) should not require a multi-gigabyte model download, so this script
serves the same wire contract from a local, clearly-labelled stub.

What it does and does not fake
------------------------------
The Dentora AI contracts deliberately do **not** let the model write clinical
prose.  For planning it returns only *selections*: an ``option_id``, one of four
allowed strategy codes, ``evidence`` items naming a real ``evidence_id`` plus
``fact_paths`` that must resolve to scalar values inside that record's facts,
and ``risk_factor_ids`` that must exist in ``risk_context.factors``.  Dentora
then renders all public text itself from the referenced real values and derives
data gaps deterministically (``ai_treatment_planning/generator.py``).

So this stand-in parses the incoming case projection, finds evidence records
whose facts actually resolve to scalars, and cites those genuine ids and paths.
Everything downstream of the selection -- the rendered option text, the risk
context, the safety analysis -- is produced by Dentora from real patient data.

What is synthetic is only the *choice* of which real evidence to cite.  A real
model would choose by clinical relevance; this stub chooses by section rank.
It never invents ids, paths, values, or prose, and it never satisfies a
readiness gate on its own.

Usage
-----
    python -m scripts.serve_dev_llm_stand_in --port 11499 --mode schema

Modes: ``schema`` (conformant selections), ``empty`` (``{}``, exercises the
fail-closed path), ``garbage`` (malformed, exercises validation).
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

# Clinical sections first: timeline/media records dominate the catalog (one per
# event or attachment) and would render as noise, while these carry the facts a
# dentist would actually cite.
SECTION_RANK = {
    "nerve": 0,
    "implant_planning": 1,
    "anatomy": 2,
    "periodontogram": 3,
    "odontogram": 4,
    "prosthetic": 5,
    "patient": 6,
    "medical_context": 7,
    "treatment_history": 8,
}
DEFAULT_RANK = 9


def _scalar_paths(facts: Any, prefix: str = "") -> list[str]:
    """Dotted paths inside ``facts`` that resolve to a non-null scalar."""
    found: list[str] = []
    if not isinstance(facts, dict):
        return found
    for key, value in facts.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            found.extend(_scalar_paths(value, f"{path}."))
        elif isinstance(value, list):
            # generator._resolve_fact can index lists, but a scalar leaf is the
            # safer citation, so descend into dict members only.
            for index, item in enumerate(value):
                if isinstance(item, dict):
                    found.extend(_scalar_paths(item, f"{path}.{index}."))
                elif item is not None and not isinstance(item, (dict, list)):
                    found.append(f"{path}.{index}")
        elif value is not None:
            found.append(path)
    return found


def _selection_context(
    payload: dict[str, Any],
) -> tuple[list[tuple[str, str, list[str]]], list[str]]:
    """Return (citable evidence records, risk factor ids) from a real request."""
    case = payload.get("case")
    evidence = case.get("evidence") if isinstance(case, dict) else payload.get("evidence")
    usable: list[tuple[str, str, list[str]]] = []
    if isinstance(evidence, dict):
        for evidence_id, record in evidence.items():
            if not isinstance(record, dict):
                continue
            paths = _scalar_paths(record.get("facts"))
            if paths:
                section = str(record.get("section") or "case")
                usable.append((str(evidence_id), section, paths))
    usable.sort(key=lambda item: (SECTION_RANK.get(item[1], DEFAULT_RANK), item[0]))

    factors = (
        ((payload.get("risk_context") or {}).get("factors"))
        if isinstance(payload.get("risk_context"), dict)
        else None
    )
    factor_ids: list[str] = []
    if isinstance(factors, list):
        factor_ids = [
            str(factor["factor_id"])
            for factor in factors
            if isinstance(factor, dict) and factor.get("factor_id")
        ]
    return usable, factor_ids


def _selections(
    usable: list[tuple[str, str, list[str]]], offset: int, count: int, *, max_paths: int
) -> list[dict[str, Any]]:
    """Distinct-evidence selections (duplicate ids are rejected by the module)."""
    picks = usable[offset : offset + count] or usable[:count]
    return [
        {"evidence_id": evidence_id, "fact_paths": paths[:max_paths]}
        for evidence_id, _section, paths in picks
    ]


def _enum(schema: dict[str, Any], property_name: str, fallback: str) -> str:
    node = (schema.get("properties") or {}).get(property_name) or {}
    values = node.get("enum")
    if isinstance(values, list) and values:
        return str(values[0])
    definitions = schema.get("$defs") or {}
    for definition in definitions.values():
        node = (definition.get("properties") or {}).get(property_name) or {}
        values = node.get("enum")
        if isinstance(values, list) and values:
            return str(values[0])
    return fallback


def _max_items(schema: dict[str, Any], property_name: str, fallback: int) -> int:
    node = (schema.get("properties") or {}).get(property_name) or {}
    value = node.get("maxItems")
    return int(value) if isinstance(value, int) else fallback


def build_options(
    schema: dict[str, Any], usable: list[tuple[str, str, list[str]]], factor_ids: list[str]
) -> dict[str, Any]:
    """Two advisory options citing genuine evidence records."""
    if not usable:
        return {"options": []}
    strategy = _enum(schema, "strategy", "review_documented_findings")
    limit = min(2, _max_items(schema, "options", 8))
    options: list[dict[str, Any]] = []
    cursor = 0
    for index in range(limit):
        option_evidence = _selections(usable, cursor, min(2, len(usable)), max_paths=2)
        cursor += len(option_evidence)
        step_evidence = _selections(usable, cursor, min(1, len(usable)), max_paths=2)
        cursor += len(step_evidence)
        if not step_evidence:
            step_evidence = option_evidence[:1]
        options.append(
            {
                "option_id": f"OPT-STUB-{index + 1:02d}",
                "strategy": strategy,
                "evidence": option_evidence,
                "risk_factor_ids": factor_ids[: min(2, len(factor_ids))],
                "steps": [
                    {
                        "step_id": f"STEP-STUB-{index + 1:02d}-01",
                        "strategy": strategy,
                        "evidence": step_evidence,
                        "risk_factor_ids": factor_ids[2:3] if len(factor_ids) > 2 else [],
                    }
                ],
            }
        )
    return {"options": options}


def build_claims(
    schema: dict[str, Any], usable: list[tuple[str, str, list[str]]]
) -> dict[str, Any]:
    """Case-summary claims, each citing one genuine evidence record."""
    if not usable:
        return {"claims": []}
    limit = min(6, _max_items(schema, "claims", 8))
    return {
        "claims": [
            {
                "claim_id": f"CLAIM-STUB-{index + 1:02d}",
                "evidence_id": evidence_id,
                "fact_paths": paths[:3],
            }
            for index, (evidence_id, _section, paths) in enumerate(usable[:limit])
        ]
    }


def build_advisory_claims(payload: dict[str, Any]) -> dict[str, Any]:
    """Report/copilot advisory claims.

    Unlike planning and case summary, this contract lets the model write text
    (``AdvisoryClaim{text, evidence_ids}``) and grounds it by requiring every
    cited id to appear in ``allowed_evidence_ids``. A stand-in cannot perform
    clinical reasoning, so the text says exactly what it is and cites real ids
    from the accepted evidence chain; the limitations restate the module's own
    ``missing_or_stale`` list. Nothing here asserts a clinical finding.
    """
    allowed = payload.get("allowed_evidence_ids")
    allowed = [str(a) for a in allowed] if isinstance(allowed, list) else []
    if not allowed:
        return {"claims": [], "limitations": []}
    missing = payload.get("missing_or_stale")
    missing = [str(m) for m in missing] if isinstance(missing, list) else []
    focus = payload.get("focus")
    disclosure = (
        "Development LLM stand-in (scripts/serve_dev_llm_stand_in.py): this advisory "
        "text was not produced by a clinical model. It cites the listed evidence ids "
        "from the accepted Dentora evidence chain and performs no clinical reasoning."
    )
    claims: list[dict[str, Any]] = [
        {
            "text": f"Focus {str(focus)[:80] if focus else 'advisory'} — {disclosure}",
            "evidence_ids": allowed[:4],
        }
    ]
    if len(allowed) > 4:
        claims.append(
            {
                "text": (
                    "Additional accepted evidence was available to this advisory step; "
                    "the stand-in cites it without interpretation. Run a real local model "
                    "to obtain clinically reasoned advisory text."
                ),
                "evidence_ids": allowed[4:8],
            }
        )
    limitations = [f"missing_or_stale: {item}" for item in missing[:8]]
    limitations.append(
        "Advisory text generated by a labelled development stand-in, not a clinical model."
    )
    return {"claims": claims, "limitations": limitations}


def _claims_are_advisory(schema: dict[str, Any]) -> bool:
    node = (schema.get("properties") or {}).get("claims") or {}
    ref = (node.get("items") or {}).get("$ref")
    if not ref:
        return False
    definition = (schema.get("$defs") or {}).get(ref.split("/")[-1]) or {}
    return "text" in (definition.get("required") or [])


def build_second_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Advisory second review: no findings, data gaps copied exactly.

    The module rejects any output that omits or invents a data gap
    (``provider_omitted_or_invented_data_gap``), so the gaps are copied verbatim
    from ``case.sections``.  ``findings`` stays empty, which the contract
    defines as "no grounded discrepancy was identified in this limited review"
    -- the only honest answer from a stand-in that performs no clinical
    reasoning.  It never asserts the treatment is safe, correct, or approved.
    """
    sections = ((payload.get("case") or {}).get("sections")) or {}
    gaps: list[dict[str, Any]] = []
    if isinstance(sections, dict):
        for name in sorted(sections):
            section = sections[name]
            if not isinstance(section, dict):
                continue
            status = section.get("status")
            if status in {"not_available", "invalid_or_stale"}:
                gap: dict[str, Any] = {"section": name, "status": status}
                if section.get("reason") is not None:
                    gap["reason"] = section["reason"]
                gaps.append(gap)
    return {"findings": [], "data_gaps": gaps}


def synthesize(schema: Any) -> Any:
    """Generic schema walk for shapes this stub has no specific builder for."""
    if isinstance(schema, list):
        return [synthesize(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if "const" in schema:
        return schema["const"]
    kind = schema.get("type")
    if kind == "object" or "properties" in schema:
        result = {}
        for name in schema.get("required", []) or []:
            value = (schema.get("properties") or {}).get(name)
            if value is not None:
                result[name] = synthesize(value)
        for name, value in (schema.get("properties") or {}).items():
            if name not in result:
                result[name] = synthesize(value)
        return result
    if kind == "array":
        items = schema.get("items")
        minimum = schema.get("minItems") or 0
        maximum = schema.get("maxItems")
        count = min(max(minimum, 1), 4) if maximum is None else min(max(minimum, 1), 2)
        if items is None or count == 0:
            return []
        return [copy.deepcopy(synthesize(items)) for _ in range(count)]
    if kind == "string":
        pattern = schema.get("pattern")
        if pattern and "uuid" in pattern:
            return "00000000-0000-4000-8000-000000000000"
        return "STUB-LOCAL-STAND-IN"
    if kind == "integer":
        return int(schema.get("minimum") or schema.get("exclusiveMinimum") or 0)
    if kind == "number":
        return float(schema.get("minimum") or schema.get("exclusiveMinimum") or 0)
    if kind == "boolean":
        return True
    if kind == "null":
        return None
    return "STUB-LOCAL-STAND-IN"


def build_content(request: dict[str, Any]) -> str:
    mode = request.get("_stub_mode") or "schema"
    if mode == "empty":
        return "{}"
    if mode == "garbage":
        return "not-json{" + "".join(random.choice('abc{}"') for _ in range(64))
    schema = ((request.get("response_format") or {}).get("json_schema") or {}).get("schema")
    if not isinstance(schema, dict):
        return json.dumps({"content": "STUB-LOCAL-STAND-IN"})
    payload: dict[str, Any] = {}
    for message in request.get("messages") or []:
        if isinstance(message, dict) and message.get("role") == "user":
            try:
                parsed = json.loads(message.get("content") or "{}")
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            if isinstance(parsed, dict):
                payload = parsed
    usable, factor_ids = _selection_context(payload)
    properties = schema.get("properties") or {}
    if "options" in properties:
        return json.dumps(build_options(schema, usable, factor_ids))
    if "claims" in properties:
        if _claims_are_advisory(schema):
            return json.dumps(build_advisory_claims(payload))
        return json.dumps(build_claims(schema, usable))
    if "data_gaps" in properties and "findings" in properties:
        return json.dumps(build_second_review(payload))
    return json.dumps(synthesize(schema))


def completion_chunks(model: str, content: str) -> bytes:
    """Server-sent events, the shape an OpenAI-compatible streaming client reads.

    Dentora always calls with ``stream: true`` and ``stream_options``
    ``include_usage``, so a plain JSON body yields zero deltas and the module
    reports ``provider_returned_invalid_structured_summary``.
    """
    base = {
        "id": "chatcmpl-dentora-dev-stub",
        "object": "chat.completion.chunk",
        "created": 1700000000,
        "model": model,
    }
    frames: list[dict[str, Any]] = [
        {
            **base,
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": content},
                    "finish_reason": None,
                }
            ],
        },
        {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
        {
            **base,
            "choices": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        },
    ]
    body = "".join(f"data: {json.dumps(frame)}\n\n" for frame in frames) + "data: [DONE]\n\n"
    return body.encode("utf-8")


def completion(model: str, content: str) -> dict[str, Any]:
    return {
        "id": "chatcmpl-dentora-dev-stub",
        "object": "chat.completion",
        "created": 1700000000,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def make_handler(state: dict[str, Any]) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:  # keep stdout readable
            return

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            if self.path.rstrip("/").endswith("/models"):
                self._json(
                    200,
                    {
                        "object": "list",
                        "data": [{"id": m, "object": "model"} for m in state["models"]],
                    },
                )
            else:
                self._json(
                    404,
                    {"error": {"message": f"stub: no route for {self.path}", "type": "not_found"}},
                )

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                request = json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                self._json(400, {"error": {"message": "invalid json", "type": "bad_request"}})
                return
            request["_stub_mode"] = state["mode"]
            if state["dump"]:
                with state["lock"], open(state["dump"], "a", encoding="utf-8") as handle:
                    handle.write(
                        json.dumps(
                            {k: v for k, v in request.items() if k != "_stub_mode"},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
            content = build_content(request)
            model = request.get("model") or (state["models"][0] if state["models"] else "stub")
            if state["verbose"]:
                print(
                    f"[stub] {self.path} mode={state['mode']} stream={bool(request.get('stream'))} -> {content[:180]}",
                    flush=True,
                )
            if request.get("stream"):
                body = completion_chunks(model, content)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._json(200, completion(model, content))

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="Dentora development LLM stand-in.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=11499)
    parser.add_argument("--mode", default="schema", choices=["schema", "empty", "garbage"])
    parser.add_argument(
        "--models", default="qwen3:8b", help="comma-separated model ids to advertise"
    )
    parser.add_argument("--dump", default="", help="append every request body to this JSONL file")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    state: dict[str, Any] = {
        "mode": args.mode,
        "models": [m.strip() for m in args.models.split(",") if m.strip()],
        "dump": args.dump,
        "verbose": args.verbose,
        "lock": threading.Lock(),
    }
    server = ThreadingHTTPServer((args.host, args.port), make_handler(state))
    print(
        f"dentora dev LLM stand-in on {args.host}:{args.port} mode={args.mode} "
        f"models={state['models']} dump={args.dump or 'off'}",
        flush=True,
    )
    print(
        "cites real evidence_ids/fact_paths from the incoming case projection; "
        "never invents ids, paths, values, or clinical prose",
        flush=True,
    )
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
