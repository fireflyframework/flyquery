# Copyright 2026 Firefly Software Foundation
# SPDX-License-Identifier: Apache-2.0
"""Reviewed service variants cannot exempt arbitrary or subsequently changed code."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = "scripts/lockstep_variants.v1.json"
VARIANT = "src/flyquery/core/agents/builder.py"
AUTH = "src/flyquery/core/services/auth/agent_token_service.py"


@pytest.fixture
def copy_gate(tmp_path):
    files = list(json.loads((ROOT / "scripts/lockstep_pins.json").read_text()))
    for rel in files + ["scripts/check_lockstep.py", "scripts/lockstep_pins.json", MANIFEST]:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    return tmp_path


def _run(root):
    return subprocess.run(
        [sys.executable, str(root / "scripts/check_lockstep.py")], capture_output=True, text=True
    )


@pytest.mark.parametrize(
    "change,expected",
    [
        ("unknown_path", "UNKNOWN VARIANT PATH"),
        ("missing_rationale", "INVALID VARIANT RATIONALE"),
        ("missing_sha", "INVALID VARIANT PIN"),
        ("invalid_sha", "INVALID VARIANT PIN"),
        ("missing_source", "INVALID CANONICAL SOURCE"),
        ("version", "UNSUPPORTED VARIANT VERSION"),
        ("boolean_version", "UNSUPPORTED VARIANT VERSION"),
    ],
)
def test_invalid_exception_manifest_fails_closed(copy_gate, change, expected):
    path = copy_gate / MANIFEST
    manifest = json.loads(path.read_text())
    if change == "unknown_path":
        manifest["variants"][AUTH] = manifest["variants"][VARIANT].copy()
    elif change == "missing_rationale":
        manifest["variants"][VARIANT].pop("rationale")
    elif change == "missing_sha":
        manifest["variants"][VARIANT].pop("sha256")
    elif change == "invalid_sha":
        manifest["variants"][VARIANT]["sha256"] = "not-a-pin"
    elif change == "missing_source":
        manifest.pop("canonical_source")
    elif change == "boolean_version":
        manifest["version"] = True
    else:
        manifest["version"] = 999
    path.write_text(json.dumps(manifest))
    result = _run(copy_gate)
    assert result.returncode == 1
    assert expected in result.stdout


def test_authentication_source_drift_still_fails(copy_gate):
    path = copy_gate / AUTH
    path.write_text(path.read_text() + "\n# unauthorized authentication drift\n")
    result = _run(copy_gate)
    assert result.returncode == 1
    assert "DRIFT: " + AUTH in result.stdout


def test_service_variant_source_drift_fails(copy_gate):
    path = copy_gate / VARIANT
    path.write_text(path.read_text() + "\n# unreviewed variant drift\n")
    result = _run(copy_gate)
    assert result.returncode == 1
    assert "SERVICE VARIANT DRIFT: " + VARIANT in result.stdout


def test_missing_variant_source_fails(copy_gate):
    (copy_gate / VARIANT).unlink()
    result = _run(copy_gate)
    assert result.returncode == 1
    assert "MISSING: " + VARIANT in result.stdout


def test_missing_exception_manifest_fails(copy_gate):
    (copy_gate / MANIFEST).unlink()
    result = _run(copy_gate)
    assert result.returncode == 1
    assert "INVALID VARIANT MANIFEST" in result.stdout
