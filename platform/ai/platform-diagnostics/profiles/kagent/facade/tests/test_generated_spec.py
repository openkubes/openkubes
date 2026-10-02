"""The provider's own OpenAPI document must not drift from the normative one.

A provider built on a framework that generates its own OpenAPI document has two
schema sources. Only one of them is normative. Validating runtime responses
catches a wrong answer, but it does not catch a provider that *publishes* a
different contract than the one it implements — and consumers, code generators
and the MCP adapter read the published document.

This is the missing half of ADR-021 contract test 1: diff the generated document
against the normative file. The comparison is a reduced shape — property names,
required sets, types and enums, resolved through ``$ref`` — because a framework
legitimately differs in titles, descriptions, examples and the constraint
keywords it chooses to emit. What it may not differ in is which fields exist,
which of them are mandatory, and which values they admit. That is precisely the
class of drift that occurred: a nullable ``summary`` where the contract requires
a string, and result fields the provider never learned about.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker


os.environ.setdefault("DIAGNOSTICS_BEARER_TOKEN", "profile-a-contract-test")

from app import app  # noqa: E402


FACADE_DIR = Path(__file__).resolve().parents[1]
SPEC_PATH = FACADE_DIR.parents[2] / "contract" / "openapi.yaml"
NORMATIVE = yaml.safe_load(SPEC_PATH.read_text())

CONTRACT_VERSION = "1.1.0"

OPERATIONS = (
    "/v1/get_platform_health",
    "/v1/investigate_workload",
    "/v1/collect_diagnostic_evidence",
)

# Keywords a framework may legitimately render differently, or omit entirely.
IGNORED = frozenset(
    {
        "title",
        "description",
        "summary",
        "examples",
        "example",
        "default",
        "format",
        "minLength",
        "maxLength",
        "maxItems",
        "minItems",
        "uniqueItems",
        "pattern",
        "$ref",
    }
)


def _resolve(document: dict[str, Any], schema: Any) -> Any:
    """Follow local ``$ref`` chains; leave everything else untouched."""
    seen = 0
    while isinstance(schema, dict) and "$ref" in schema:
        seen += 1
        if seen > 32:
            raise AssertionError(f"cyclic $ref chain at {schema['$ref']}")
        target: Any = document
        for part in str(schema["$ref"]).lstrip("#/").split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]
        schema = target
    return schema


def shape(document: dict[str, Any], schema: Any) -> Any:
    """Reduce a schema to the part both sides must agree on."""
    schema = _resolve(document, schema)
    if not isinstance(schema, dict):
        return schema

    combinators = ("allOf", "anyOf", "oneOf")
    reduced: dict[str, Any] = {}
    for key, value in schema.items():
        if key in IGNORED or key in combinators:
            continue
        if key == "properties":
            reduced["properties"] = {
                name: shape(document, child) for name, child in value.items()
            }
        elif key == "items":
            reduced["items"] = shape(document, value)
        elif key == "required":
            reduced["required"] = sorted(value)
        elif key in {"if", "then", "else"}:
            reduced[key] = shape(document, value)
        elif key == "additionalProperties":
            reduced["additionalProperties"] = (
                value if isinstance(value, bool) else shape(document, value)
            )
        else:
            reduced[key] = value

    # Composition is flattened, and a branch may sit next to sibling keywords
    # (``properties`` plus ``allOf`` of if/then is how the contract expresses a
    # conditional requirement). A framework also spells "optional" as
    # anyOf[T, null]; that branch is dropped so the comparison is about the
    # field's type rather than about how optionality is written.
    for combinator in combinators:
        for branch in schema.get(combinator, []):
            branch_shape = shape(document, branch)
            if not isinstance(branch_shape, dict) or branch_shape in ({}, {"type": "null"}):
                continue
            if "if" in branch_shape:
                # A conditional requirement stays one unit; splitting if from
                # then would compare two halves that mean nothing apart.
                reduced.setdefault("conditions", []).append(branch_shape)
                continue
            for key, value in branch_shape.items():
                if key == "required":
                    reduced["required"] = sorted(
                        set(reduced.get("required", [])) | set(value)
                    )
                elif key == "properties":
                    reduced.setdefault("properties", {}).update(value)
                else:
                    reduced.setdefault(key, value)

    if "conditions" in reduced:
        reduced["conditions"] = sorted(reduced["conditions"], key=repr)
    return reduced


def _admits_null(document: dict[str, Any], schema: Any) -> bool:
    schema = _resolve(document, schema)
    if not isinstance(schema, dict):
        return False
    declared = schema.get("type")
    if declared == "null" or (isinstance(declared, list) and "null" in declared):
        return True
    return any(
        _admits_null(document, branch)
        for combinator in ("anyOf", "oneOf")
        for branch in schema.get(combinator, [])
    )


def _flattened(document: dict[str, Any], schema: Any) -> tuple[dict[str, Any], set[str]]:
    """Properties and unconditionally required names, with ``allOf`` folded in.

    A conditional requirement lives inside ``then`` and is deliberately not
    collected here: ``reason`` and ``uri`` are required only for certain
    ``status`` values, so treating them as always required would be wrong.
    """
    schema = _resolve(document, schema)
    if not isinstance(schema, dict):
        return {}, set()
    properties = dict(schema.get("properties", {}))
    required = set(schema.get("required", []))
    for branch in schema.get("allOf", []):
        resolved = _resolve(document, branch)
        if isinstance(resolved, dict):
            properties.update(resolved.get("properties", {}))
            required |= set(resolved.get("required", []))
    return properties, required


def nullable_required_fields(
    normative_schema: Any,
    generated_schema: Any,
    pointer: str = "",
) -> list[str]:
    """Contract-required fields whose provider schema still admits ``null``.

    This is the half of the drift a document diff cannot see on its own. A model
    that types a required field as optional publishes it as required anyway once
    the required set is derived from the declared fields — but it will happily
    hold ``None``, and then the provider either serialises ``null`` against a
    string, or drops the field and omits something required. Either way the
    published contract and the implemented one part company, which is exactly
    how ``ClusterHealth.summary`` drifted the first time.
    """
    findings: list[str] = []
    normative_properties, normative_required = _flattened(NORMATIVE, normative_schema)
    generated_properties, _ = _flattened(app.openapi(), generated_schema)
    for name, normative_child in normative_properties.items():
        generated_child = generated_properties.get(name)
        if generated_child is None:
            continue
        path = f"{pointer}.{name}"
        if name in normative_required and _admits_null(app.openapi(), generated_child):
            findings.append(path)
        findings.extend(
            nullable_required_fields(normative_child, generated_child, path)
        )
    normative_items = _resolve(NORMATIVE, normative_schema)
    generated_items = _resolve(app.openapi(), generated_schema)
    if isinstance(normative_items, dict) and isinstance(generated_items, dict):
        if "items" in normative_items and "items" in generated_items:
            findings.extend(
                nullable_required_fields(
                    normative_items["items"], generated_items["items"], pointer + "[]"
                )
            )
    return findings


class GeneratedSpecConformanceTests(unittest.TestCase):
    """The document the provider publishes vs. the document OpenKubes owns."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.generated = app.openapi()

    def test_normative_contract_version_is_pinned(self) -> None:
        self.assertEqual(CONTRACT_VERSION, NORMATIVE["info"]["version"])
        self.assertEqual(
            CONTRACT_VERSION,
            self.generated["info"]["version"],
            "the provider must publish the contract version it implements",
        )

    def test_generated_document_exposes_exactly_the_contract_operations(self) -> None:
        normative_paths = set(NORMATIVE["paths"])
        generated_paths = {
            path for path in self.generated["paths"] if path.startswith("/v1/")
        }
        self.assertEqual(normative_paths, generated_paths)
        self.assertEqual(set(OPERATIONS), normative_paths)

        for path in OPERATIONS:
            with self.subTest(path=path):
                self.assertEqual(
                    NORMATIVE["paths"][path]["post"]["operationId"],
                    self.generated["paths"][path]["post"]["operationId"],
                )
                self.assertEqual(
                    {"post"},
                    {
                        method
                        for method in self.generated["paths"][path]
                        if method in {"get", "put", "post", "delete", "patch"}
                    },
                    "the contract is POST-only; another verb is a write path",
                )

    def test_request_and_response_shapes_match_the_normative_contract(self) -> None:
        for path in OPERATIONS:
            for direction in ("request", "response"):
                with self.subTest(path=path, direction=direction):
                    if direction == "request":
                        normative = NORMATIVE["paths"][path]["post"]["requestBody"][
                            "content"
                        ]["application/json"]["schema"]
                        generated = self.generated["paths"][path]["post"]["requestBody"][
                            "content"
                        ]["application/json"]["schema"]
                    else:
                        normative = NORMATIVE["paths"][path]["post"]["responses"]["200"][
                            "content"
                        ]["application/json"]["schema"]
                        generated = self.generated["paths"][path]["post"]["responses"][
                            "200"
                        ]["content"]["application/json"]["schema"]
                    self.assertEqual(
                        shape(NORMATIVE, normative),
                        shape(self.generated, generated),
                    )

    def test_no_contract_required_field_is_nullable_in_the_provider(self) -> None:
        for path in OPERATIONS:
            with self.subTest(path=path):
                normative = NORMATIVE["paths"][path]["post"]["responses"]["200"][
                    "content"
                ]["application/json"]["schema"]
                generated = self.generated["paths"][path]["post"]["responses"]["200"][
                    "content"
                ]["application/json"]["schema"]
                self.assertEqual(
                    [],
                    nullable_required_fields(normative, generated),
                    "a field the contract requires must not be optional in the "
                    "provider's model",
                )

    def test_generated_result_models_reject_unknown_fields(self) -> None:
        """``extra="forbid"`` must survive into the published document."""
        for path in OPERATIONS:
            generated = shape(
                self.generated,
                self.generated["paths"][path]["post"]["responses"]["200"]["content"][
                    "application/json"
                ]["schema"],
            )
            with self.subTest(path=path):
                self.assertIs(
                    False,
                    generated.get("additionalProperties"),
                    "a result model that accepts unknown fields cannot enforce "
                    "the closed contract surface",
                )


class ClosedSurfaceRuntimeTests(unittest.TestCase):
    """The rejection path, which had no test at all.

    ``additionalProperties: false`` on the inputs is only a contract if a request
    carrying an unknown field is actually refused, and the refusal has to arrive
    in the normative ``Error`` shape — a framework's default validation body is a
    different contract that no consumer was told about.
    """

    def setUp(self) -> None:
        from fastapi.testclient import TestClient

        self.client = TestClient(app)
        self.headers = {
            "Authorization": "Bearer profile-a-contract-test",
            "X-Request-Id": "closed-surface-test",
        }

    def assert_contract_error(self, response, expected_status: int) -> dict[str, Any]:
        self.assertEqual(expected_status, response.status_code, response.text)
        payload = response.json()
        self.assertNotIn(
            "detail",
            payload,
            "the framework's default validation body is not the contract's Error",
        )
        self.assertEqual(
            response.headers["X-Invocation-Id"],
            payload["invocation_id"],
            "a rejected call must stay traceable in the invocation audit",
        )
        schema = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "components": NORMATIVE["components"],
            "$ref": "#/components/schemas/Error",
        }
        errors = list(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
                payload
            )
        )
        self.assertEqual([], [error.message for error in errors])
        return payload

    def test_unknown_request_field_is_refused(self) -> None:
        response = self.client.post(
            "/v1/investigate_workload",
            headers=self.headers,
            json={
                "cluster": "ok-ai",
                "namespace": "payments",
                "workload": "checkout-api",
                "tenant": "acme",
            },
        )
        payload = self.assert_contract_error(response, 422)
        self.assertEqual("invalid_request", payload["code"])

    def test_missing_required_field_is_refused(self) -> None:
        response = self.client.post(
            "/v1/investigate_workload",
            headers=self.headers,
            json={"cluster": "ok-ai", "namespace": "payments"},
        )
        payload = self.assert_contract_error(response, 422)
        self.assertEqual("invalid_request", payload["code"])


if __name__ == "__main__":
    unittest.main()
