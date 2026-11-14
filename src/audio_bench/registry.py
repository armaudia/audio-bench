# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Closed catalog metadata validation and dependency-graph checks.

Metadata validation never executes source code, resolves URLs, downloads assets or imports
provider code. Catalog identity and evaluation evidence are separate: an entry marked blocked
cannot be converted to an executed/qualified record by metadata alone.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from . import canonical
from .errors import ValidationError
from .schemas import Validator, schema_dir


def validate_catalog(value: Any, *, directory: Path | None = None) -> None:
    if not isinstance(value, Mapping):
        raise ValidationError("catalog must be an object")
    schema_path = (directory or schema_dir()) / "catalog.schema.json"
    schema = canonical.strict_loads(schema_path.read_bytes(), path=str(schema_path))
    shared = Validator(directory)
    registry = shared.registry.with_resource(
        schema["$id"], Resource.from_contents(schema, default_specification=DRAFT202012)
    )
    validator = jsonschema.Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(value), key=lambda error: list(map(str, error.absolute_path)))
    if errors:
        first = errors[0]
        location = "/".join(str(part) for part in first.absolute_path) or "<root>"
        raise ValidationError(f"catalog schema error at {location}: {first.message}")

    entries = value["entries"]
    ids = [entry["id"] for entry in entries]
    if len(ids) != len(set(ids)):
        raise ValidationError("catalog has duplicate IDs")
    by_id = {entry["id"]: entry for entry in entries}
    for entry in entries:
        if entry["id"] in entry["dependencies"]:
            raise ValidationError(f"{entry['id']} depends on itself")
        for dependency in entry["dependencies"]:
            if dependency not in by_id:
                raise ValidationError(f"{entry['id']} has dangling dependency {dependency}")
        if entry["status"] == "available" and entry["blocked_reason"] is not None:
            raise ValidationError(f"available entry {entry['id']} cannot carry blocked_reason")
        if entry["status"] == "blocked" and entry["blocked_reason"] is None:
            raise ValidationError(f"blocked entry {entry['id']} needs an explicit reason")
        if entry["type"] == "provider" and entry["descriptor_digest"] is None and entry["status"] == "available":
            raise ValidationError(f"available provider {entry['id']} needs a descriptor digest")
        if entry["type"] in ("engine", "implementation", "provider") and entry["model_id"] is not None:
            if entry["model_id"] not in by_id or by_id[entry["model_id"]]["type"] != "model":
                raise ValidationError(f"{entry['id']} model_id does not refer to a model entry")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item: str) -> None:
        if item in visiting:
            raise ValidationError(f"catalog dependency cycle includes {item}")
        if item in visited:
            return
        visiting.add(item)
        for child in by_id[item]["dependencies"]:
            visit(child)
        visiting.remove(item)
        visited.add(item)

    for item in ids:
        visit(item)


def load_catalog(path: Path, *, directory: Path | None = None) -> dict[str, Any]:
    value = canonical.strict_loads(path.read_bytes(), path=str(path))
    validate_catalog(value, directory=directory)
    return value
