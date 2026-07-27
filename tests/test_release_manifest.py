"""Release artifact manifest, tag, baseline, and tamper-detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bella_harness.release_manifest import (
    MIN_REDTEAM_PROBES,
    MIN_UNIT_TESTS,
    ReleaseManifestError,
    build_release_manifest,
    read_project_version,
    validate_release_tag,
    verify_release_manifest,
)


COMMIT = "a" * 40


def _fixture(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "bella_harness-0.2.0-py3-none-any.whl").write_bytes(b"wheel-bytes")
    (dist / "bella_harness-0.2.0.tar.gz").write_bytes(b"sdist-bytes")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[project]\nname = "bella-harness"\nversion = "0.2.0"\n',
        encoding="utf-8",
    )
    doctor = tmp_path / "doctor.json"
    doctor.write_text(
        json.dumps(
            {
                "schema": "bella.doctor-report.v1",
                "package_version": "0.2.0",
                "ready": True,
                "live_checks_requested": False,
                "checks": [],
            }
        ),
        encoding="utf-8",
    )
    return dist, pyproject, doctor


def _arguments(tmp_path: Path, **overrides):
    dist, pyproject, doctor = _fixture(tmp_path)
    arguments = {
        "dist_dir": dist,
        "pyproject_path": pyproject,
        "commit_sha": COMMIT,
        "unit_tests": MIN_UNIT_TESTS,
        "redteam_probes": MIN_REDTEAM_PROBES,
        "doctor_report_path": doctor,
        "output_path": tmp_path / "release-manifest.json",
        "checksums_path": tmp_path / "SHA256SUMS",
        "dependency_audit_passed": True,
        "distribution_check_passed": True,
        "wheel_smoke_passed": True,
        "container_smoke_passed": True,
    }
    arguments.update(overrides)
    return arguments


def _build(tmp_path: Path):
    arguments = _arguments(tmp_path)
    manifest = build_release_manifest(**arguments)
    return (
        arguments["dist_dir"],
        arguments["output_path"],
        arguments["checksums_path"],
        manifest,
    )


def test_release_manifest_hashes_and_verifies_two_artifacts(tmp_path):
    dist, manifest_path, checksums_path, manifest = _build(tmp_path)
    assert manifest["schema"] == "bella.release-manifest.v1"
    assert manifest["version"] == "0.2.0"
    assert manifest["commit_sha"] == COMMIT
    assert manifest["gates"]["unit_tests_passed"] == MIN_UNIT_TESTS
    assert manifest["gates"]["unit_tests_minimum"] == MIN_UNIT_TESTS
    assert manifest["gates"]["redteam_probes_passed"] == MIN_REDTEAM_PROBES
    assert manifest["gates"]["redteam_probes_minimum"] == MIN_REDTEAM_PROBES
    assert manifest["gates"]["container_smoke_passed"] is True
    assert len(manifest["artifacts"]) == 2
    assert verify_release_manifest(manifest_path, dist_dir=dist)

    checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 2
    assert all("  bella_harness-0.2.0" in line for line in checksum_lines)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"dependency_audit_passed": False}, "dependency audit"),
        ({"distribution_check_passed": False}, "distribution check"),
        ({"wheel_smoke_passed": False}, "wheel smoke"),
        ({"container_smoke_passed": False}, "container smoke"),
    ],
)
def test_release_manifest_rejects_unpassed_gate(tmp_path, override, message):
    with pytest.raises(ReleaseManifestError, match=message):
        build_release_manifest(**_arguments(tmp_path, **override))


@pytest.mark.parametrize(
    ("unit_tests", "redteam_probes", "message"),
    [
        (MIN_UNIT_TESTS - 1, MIN_REDTEAM_PROBES, "unit test count"),
        (MIN_UNIT_TESTS, MIN_REDTEAM_PROBES - 1, "red-team probe count"),
    ],
)
def test_release_manifest_rejects_regressed_test_baselines(
    tmp_path,
    unit_tests,
    redteam_probes,
    message,
):
    with pytest.raises(ReleaseManifestError, match=message):
        build_release_manifest(
            **_arguments(
                tmp_path,
                unit_tests=unit_tests,
                redteam_probes=redteam_probes,
            )
        )


def test_release_manifest_rejects_not_ready_or_wrong_version_doctor(tmp_path):
    arguments = _arguments(tmp_path)
    doctor = Path(arguments["doctor_report_path"])
    payload = json.loads(doctor.read_text(encoding="utf-8"))
    payload["ready"] = False
    doctor.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="not production-ready"):
        build_release_manifest(**arguments)

    arguments = _arguments(tmp_path / "wrong-version")
    doctor = Path(arguments["doctor_report_path"])
    payload = json.loads(doctor.read_text(encoding="utf-8"))
    payload["package_version"] = "0.1.0"
    doctor.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="package version"):
        build_release_manifest(**arguments)


def test_release_manifest_rejects_unexpected_artifacts(tmp_path):
    arguments = _arguments(tmp_path)
    (Path(arguments["dist_dir"]) / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="unexpected files"):
        build_release_manifest(**arguments)


def test_release_manifest_detects_artifact_manifest_and_gate_tampering(tmp_path):
    dist, manifest_path, _, _ = _build(tmp_path)
    (dist / "bella_harness-0.2.0-py3-none-any.whl").write_bytes(b"changed")
    assert not verify_release_manifest(manifest_path, dist_dir=dist)

    dist, manifest_path, _, _ = _build(tmp_path / "second")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["commit_sha"] = "b" * 40
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_release_manifest(manifest_path, dist_dir=dist)

    dist, manifest_path, _, _ = _build(tmp_path / "third")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["gates"]["container_smoke_passed"] = False
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_release_manifest(manifest_path, dist_dir=dist)


def test_project_version_parser_stays_inside_project_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[build-system]\nversion = "wrong"\n\n[project]\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    assert read_project_version(pyproject) == "1.2.3"


def test_release_tag_must_exactly_match_project_version():
    assert validate_release_tag("v0.2.0", "0.2.0") == "0.2.0"
    with pytest.raises(ReleaseManifestError, match="does not match"):
        validate_release_tag("v0.2.1", "0.2.0")
    with pytest.raises(ReleaseManifestError, match="canonical form"):
        validate_release_tag("0.2.0", "0.2.0")
    with pytest.raises(ReleaseManifestError, match="canonical form"):
        validate_release_tag("release-v0.2.0", "0.2.0")
