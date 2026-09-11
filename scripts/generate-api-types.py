#!/usr/bin/env python3
"""Export the HTTP contract from FastAPI to TypeScript.

``apps/api/alppy/schemas/__init__.py`` is the single source of truth for every
shape that crosses the wire. This script asks the application for its own
OpenAPI document and writes the response/request models into
``packages/shared/src/api-types.generated.ts`` so the web app cannot
hand-transcribe them — and so a CI step (see ``.github/workflows/ci.yml``) can
catch the day someone renames a Pydantic field and the browser is the first
thing to find out, by re-running this script and failing if the generated file
changes.

It is the sibling of ``export-layout.py`` and works the same way: import the
Python source of truth, render TypeScript, let ``git diff --exit-code`` in CI
be the check. There is no ``--check`` flag here for the same reason there is
none there.

**Why the app and not a running server.** ``create_app()`` is a factory with no
side effects — no connection is opened, no bucket is reached, and
``core.config`` has a safe default for every setting — so the document can be
produced from a checkout with nothing running. The served
``/api/v1/openapi.json`` is the same document, and is deliberately switched off
in staging and production (``main.py``), which is exactly why the contract is
generated in the repository rather than fetched from a deployment.

**What this file does NOT contain**, and why each one is absent rather than
forgotten:

- ``ApiErrorBody`` — the error envelope is *raised*, never returned through a
  ``response_model``, so FastAPI has never heard of it. It stays hand-written
  beside ``api/errors.py``'s docstring.
- ``ApiLocale``, ``MatrixSort`` — Pydantic ``Literal`` aliases. One is inlined
  into every field that uses it, the other is a *query parameter*, and neither
  earns a name in ``components.schemas``.
- ``ExerciseOut.is_ai_generated`` and ``AdaptiveStudentPlan.total_items`` —
  Python ``@property`` members, not Pydantic fields, so they are not in the
  JSON either. They are derived on the client.

All five live in ``apps/web/src/lib/api/types.ts``, which is now a short file
that says why it exists rather than a 1 162-line mirror.

Usage:
    PYTHONPATH=apps/api python scripts/generate-api-types.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = REPO_ROOT / "packages" / "shared" / "src" / "api-types.generated.ts"
ROUTES_PATH = REPO_ROOT / "packages" / "shared" / "src" / "api-routes.generated.ts"
CONSTANTS_PATH = REPO_ROOT / "packages" / "shared" / "src" / "api-constants.generated.ts"

#: `format` values worth a name of their own. Everything else that is a string
#: stays `string`: `email` and `date` carry no extra guarantee a TypeScript
#: reader could act on, and pretending otherwise would be a type that lies.
_FORMAT_ALIASES = {"uuid": "Uuid", "date-time": "IsoDateTime"}


def _import_app() -> Any:
    """Import alppy.main, adding apps/api to sys.path if needed so this also
    works when invoked without PYTHONPATH pre-set."""
    try:
        from alppy.main import create_app
    except ImportError:
        api_src = str(REPO_ROOT / "apps" / "api")
        if api_src not in sys.path:
            sys.path.insert(0, api_src)
        from alppy.main import create_app
    return create_app


# --------------------------------------------------------------------------
# Type rendering
# --------------------------------------------------------------------------
def _literal(value: Any) -> str:
    """A JSON enum member as a TypeScript literal."""
    if isinstance(value, str):
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return "null"
    return json.dumps(value)


def _union(parts: list[str]) -> str:
    """Join without repeating a member, preserving first-seen order.

    `anyOf: [string, null]` and `anyOf: [null, string]` both occur in the
    document and must not render as two different types.
    """
    seen: list[str] = []
    for part in parts:
        if part not in seen:
            seen.append(part)
    return " | ".join(seen) if seen else "unknown"


def ts_type(schema: dict[str, Any]) -> str:
    """Render one JSON-Schema node as a TypeScript type expression."""
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]

    if "anyOf" in schema:
        return _union([ts_type(member) for member in schema["anyOf"]])

    if "enum" in schema:
        return _union([_literal(value) for value in schema["enum"]])

    kind = schema.get("type")

    if kind == "null":
        return "null"
    if kind == "boolean":
        return "boolean"
    if kind in ("integer", "number"):
        return "number"
    if kind == "string":
        return _FORMAT_ALIASES.get(schema.get("format", ""), "string")
    if kind == "array":
        item = ts_type(schema.get("items", {}))
        # `(a | b)[]` — an unparenthesised union binds looser than `[]` and
        # would render `a | b[]`, which is a different and wrong type.
        return f"({item})[]" if "|" in item else f"{item}[]"
    if kind == "object":
        extra = schema.get("additionalProperties")
        if isinstance(extra, dict):
            return f"Record<string, {ts_type(extra)}>"
        # `additionalProperties: true` (an open payload) and a bare
        # `type: object` (no shape declared) are both "some JSON object".
        # `unknown` rather than `any`: the web app lints `any` as an error,
        # and a caller should have to narrow a payload before reading it.
        return "Record<string, unknown>"

    # A field annotated `Any` carries no `type` at all.
    return "unknown"


def _doc(text: str | None, indent: str) -> list[str]:
    """A description as a JSDoc block, or nothing."""
    if not text:
        return []
    lines = [line.rstrip() for line in text.strip().splitlines()]
    if len(lines) == 1:
        return [f"{indent}/** {lines[0]} */"]
    out = [f"{indent}/**"]
    out += [f"{indent} * {line}".rstrip() for line in lines]
    out.append(f"{indent} */")
    return out


def _referenced(node: Any, out: set[str]) -> None:
    """Every `$ref` name anywhere under a node."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            out.add(ref.rsplit("/", 1)[-1])
        for value in node.values():
            _referenced(value, out)
    elif isinstance(node, list):
        for value in node:
            _referenced(value, out)


def _closure(seeds: set[str], schemas: dict[str, Any]) -> set[str]:
    """`seeds` plus every schema reachable from them by `$ref`."""
    seen: set[str] = set()
    stack = list(seeds)
    while stack:
        name = stack.pop()
        if name in seen or name not in schemas:
            continue
        seen.add(name)
        found: set[str] = set()
        _referenced(schemas[name], found)
        stack.extend(found)
    return seen


def response_schemas(spec: dict[str, Any]) -> set[str]:
    """The schemas that are ever RETURNED, transitively.

    Which is the whole question for optionality. OpenAPI's `required` list
    comes from Pydantic, where a field is optional when it has a default —
    the right rule for a request body, and the wrong one for a response.
    Nothing in this API passes `response_model_exclude_unset` or
    `exclude_defaults`, so FastAPI serialises every field of a response
    model, defaults included: a defaulted field is ALWAYS on the wire.

    Marking those `?` made the client null-check about thirty fields that
    cannot be absent, and `plan.retrieved` — a `list[...] = []` — needed a
    guard on every read. That is not caution, it is a type that lies in the
    other direction.
    """
    schemas: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    seeds: set[str] = set()
    for operations in spec.get("paths", {}).values():
        for operation in operations.values():
            if isinstance(operation, dict):
                _referenced(operation.get("responses", {}), seeds)
    return _closure(seeds, schemas)


def render_enum(name: str, schema: dict[str, Any]) -> list[str]:
    out = _doc(schema.get("description"), "")
    members = _union([_literal(value) for value in schema["enum"]])
    out.append(f"export type {name} = {members};")
    return out


def render_interface(
    name: str, schema: dict[str, Any], *, returned: bool = False
) -> list[str]:
    out = _doc(schema.get("description"), "")
    properties: dict[str, Any] = schema.get("properties") or {}
    if not properties:
        out.append(f"export type {name} = Record<string, never>;")
        return out

    required = set(schema.get("required") or ())
    out.append(f"export interface {name} {{")
    for prop, node in properties.items():
        out += _doc(node.get("description"), "  ")
        # In a REQUEST, optional exactly when Pydantic gave the field a
        # default — the caller may leave it out. In a RESPONSE, never: this
        # API excludes nothing on the way out, so a defaulted field is always
        # serialised, and `?` would only buy the client a null-check it can
        # never satisfy. A nullable field still renders `| null` either way;
        # that is a value on the wire, not an absent key.
        mark = "" if returned or prop in required else "?"
        out.append(f"  {prop}{mark}: {ts_type(node)};")
    out.append("}")
    return out


def render_ts(spec: dict[str, Any]) -> str:
    schemas: dict[str, Any] = spec.get("components", {}).get("schemas", {})
    returned = response_schemas(spec)

    header = [
        "// AUTO-GENERATED — DO NOT EDIT.",
        "// Source of truth: apps/api/alppy/schemas/__init__.py, as FastAPI",
        "// serialises it (create_app().openapi()).",
        "// Regenerate with: PYTHONPATH=apps/api python scripts/generate-api-types.py",
        "// CI fails if this file is stale (see .github/workflows/ci.yml) --",
        "// a renamed or retyped Pydantic field used to compile on both sides",
        "// and fail in the browser, with no test in between.",
        "//",
        "// Field names are snake_case because that is what FastAPI serialises:",
        "// the Pydantic models use `populate_by_name`, not an alias generator.",
        "//",
        "// A property is optional (`?`) only on a schema this API accepts as a",
        "// REQUEST body and never returns, and there exactly when its Pydantic",
        "// field has a default. A returned schema has no optional properties:",
        "// nothing here passes `response_model_exclude_unset`, so a defaulted",
        "// field is always serialised. A schema that is both keeps the",
        "// response reading, because that is the one a screen relies on.",
        "//",
        "// `| null` is unaffected either way -- that is a value on the wire,",
        "// not an absent key.",
        "",
        "/** A UUID, as a string. `format: uuid` on the wire. */",
        "export type Uuid = string;",
        "",
        "/** An ISO-8601 timestamp, as a string. `format: date-time` on the wire. */",
        "export type IsoDateTime = string;",
    ]

    body: list[str] = []
    for name in sorted(schemas):
        schema = schemas[name]
        body.append("")
        if "enum" in schema:
            body += render_enum(name, schema)
        else:
            body += render_interface(name, schema, returned=name in returned)

    return "\n".join(header + body) + "\n"


def render_routes(spec: dict[str, Any]) -> str:
    """Every route the application actually serves, as `METHOD /path` strings.

    The types above say what a payload looks like; this says what may be
    ASKED. `endpoints.ts` used to call `POST /scans/{id}/pages/{id}/assign` for
    two milestones against an API that only ever exposed
    `PATCH .../pages/{id}` — a guess at "the obvious path", which no type
    could catch because the payload was right and only the address was wrong.
    """
    routes: list[str] = []
    responses: dict[str, str] = {}
    for path, operations in spec.get("paths", {}).items():
        for method, operation in operations.items():
            if isinstance(operation, dict):
                route = f"{method.upper()} {path}"
                routes.append(route)
                responses[route] = _response_type(operation)

    lines = [
        "// AUTO-GENERATED — DO NOT EDIT.",
        "// Source of truth: the routers under apps/api/alppy/api/v1/, as",
        "// FastAPI collects them (create_app().openapi()).",
        "// Regenerate with: PYTHONPATH=apps/api python scripts/generate-api-types.py",
        "",
        "/** Every `METHOD /path` this API serves. */",
        "export const API_ROUTES = [",
    ]
    lines += [f"  '{route}'," for route in sorted(routes)]
    lines += [
        "] as const;",
        "",
        "export type ApiRoute = (typeof API_ROUTES)[number];",
        "",
        "/**",
        " * What each route RETURNS, as the TypeScript type expression for it.",
        " *",
        " * `apiRequest<T>` is an assertion and not a check: the client states the",
        " * shape it expects and TypeScript believes it, so a route whose response",
        " * model changes goes on compiling at every call site while the data",
        " * underneath is a different shape. The generated types cannot see that —",
        " * they describe the document, not who reads it. This is the join, and",
        " * `contract.test.ts` is what enforces it.",
        " */",
        "export const API_RESPONSES: Record<string, string> = {",
    ]
    lines += [f"  '{route}': '{responses[route]}'," for route in sorted(routes)]
    lines += ["};"]
    return "\n".join(lines) + "\n"


def _response_type(operation: dict[str, Any]) -> str:
    """The TypeScript type of a route's success response.

    `void` where there is no body at all (a 204), and `string` for the routes
    that answer with HTML or a PDF rather than JSON — the preview and the
    print views, which are real responses with a real shape the client has to
    declare.
    """
    for status in ("200", "201", "202", "204"):
        response = operation.get("responses", {}).get(status)
        if response is None:
            continue
        content = response.get("content") or {}
        if not content:
            return "void"
        for media, body in content.items():
            if media.startswith("application/json"):
                return ts_type(body.get("schema") or {})
        # text/html, application/pdf: a body, but not a modelled one.
        return "string"
    return "void"
def collect_error_codes() -> list[str]:
    """Every `code` the error envelope can carry.

    Read out of the source rather than declared in a list, because a list is
    the thing that drifts. Two origins, and both are needed:

    · `errors._STATUS_CODES` — the generic one per HTTP status, which is what
      an unhandled 403 or 503 arrives as.
    · every `code="..."` a handler passes to `conflict`/`unprocessable`, which
      is where the domain codes live (`scan_pages_unassigned`, and fourteen
      others at the time of writing).

    Plus the three the client itself can produce or fall back to, since the
    catalogue has to answer for those as well: a fetch that never left the
    browser, a response the envelope did not shape, and the last resort.
    """
    from alppy.api import errors as api_errors

    codes: set[str] = set(api_errors._STATUS_CODES.values())

    # `validation_error` is raised by the request-validation handler rather
    # than by a helper, and `internal_error` by the catch-all.
    source_root = REPO_ROOT / "apps" / "api" / "alppy"
    literal = re.compile(r'code="([a-z_]+)"')
    for path in source_root.rglob("*.py"):
        codes.update(literal.findall(path.read_text(encoding="utf-8")))

    # Raised by handlers rather than by a helper, so no literal to find:
    # `error_body("internal_error", ...)` in the catch-all, and the request
    # validation handler's own code.
    codes.update({"internal_error", "validation_error"})

    # Client-side origins. `network_error` is `api/client.ts` when the fetch
    # itself fails; `http_error` is `parseError` when the body is not our
    # envelope (a proxy's HTML); `fallback` is what `apiErrorMessage` renders
    # when it recognises nothing.
    codes.update({"network_error", "http_error", "fallback"})
    return sorted(codes)


def collect_cantons() -> list[str]:
    """The 26 cantons, from the allowlist the API validates against.

    The settings screen used to take the canton as a free two-character box, so
    "XX" or a typo for "ZH" was stored — and `School.canton` is what a
    curriculum mapping keys on. Reading the list from the server's own
    `SWISS_CANTONS` means the picker cannot offer something the API would then
    refuse, and cannot fall behind if the set ever changes.
    """
    from alppy.schemas import SWISS_CANTONS

    return sorted(SWISS_CANTONS)


def render_constants(codes: list[str], cantons: list[str]) -> str:
    lines = [
        "// AUTO-GENERATED — DO NOT EDIT.",
        "// Source of truth: apps/api/alppy/api/errors.py, plus every",
        "// `code=\"...\"` raised under apps/api/alppy/.",
        "// Regenerate with: PYTHONPATH=apps/api python scripts/generate-api-types.py",
        "",
        "/**",
        " * Every `code` the error envelope can carry.",
        " *",
        " * `scripts/check-i18n.mjs` asserts that each one has a sentence in all",
        " * three catalogues. The catalogue used to cover thirteen of them, so a",
        " * teacher meeting any of the rest read the generic fallback — which is",
        " * how a rate limit, a permission refusal and a dead API all came to say",
        " * the same thing (F14).",
        " */",
        "export const API_ERROR_CODES = [",
    ]
    lines += [f"  '{code}'," for code in codes]
    lines += [
        "] as const;",
        "",
        "export type ApiErrorCode = (typeof API_ERROR_CODES)[number];",
        "",
        "/** The 26 Swiss cantons, as `schemas.SWISS_CANTONS` validates them. */",
        "export const SWISS_CANTONS = [",
    ]
    lines += [f"  '{canton}'," for canton in cantons]
    lines += [
        "] as const;",
        "",
        "export type SwissCanton = (typeof SWISS_CANTONS)[number];",
    ]
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str, label: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text() if path.exists() else None
    path.write_text(text)
    rel = path.relative_to(REPO_ROOT)
    if previous != text:
        print(f"wrote {rel} ({label}, {'updated' if previous else 'created'})")
    else:
        print(f"{rel} already up to date ({label})")


def main() -> int:
    create_app = _import_app()
    spec = create_app().openapi()

    schemas = len(spec.get("components", {}).get("schemas", {}))
    routes = sum(
        1
        for operations in spec.get("paths", {}).values()
        for operation in operations.values()
        if isinstance(operation, dict)
    )
    _write(OUTPUT_PATH, render_ts(spec), f"{schemas} schemas")
    _write(ROUTES_PATH, render_routes(spec), f"{routes} routes")
    codes = collect_error_codes()
    cantons = collect_cantons()
    _write(
        CONSTANTS_PATH,
        render_constants(codes, cantons),
        f"{len(codes)} error codes, {len(cantons)} cantons",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
