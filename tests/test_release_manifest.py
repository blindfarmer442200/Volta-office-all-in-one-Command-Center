"""Release artifact manifest and tamper-detection tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bella_harness.release_manifest import (
    ReleaseManifestError,
    build_release_manifest,
    read_project_version,
    verify_release_manifest,
)


COMMIT = "a" * 40


def _fixture(tmp_path: Path):
    dist = tmp_path / "dist"
    dist.mkdir()
    wheel = dist / "bella_harness-0.2.0-py3-none-any.whl"
    sdist = dist / "bella_harness-0.2.0.tar.gz"
    wheel.write_bytes(b"wheel-bytes")
    sdist.write_bytes(b"sdist-bytes")

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


def _build(tmp_path: Path):
    dist, pyproject, doctor = _fixture(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    checksums_path = tmp_path / "SHA256SUMS"
    manifest = build_release_manifest(
        dist_dir=dist,
        pyproject_path=pyproject,
        commit_sha=COMMIT,
        unit_tests=207,
        redteam_probes=115,
        doctor_report_path=doctor,
        output_path=manifest_path,
        checksums_path=checksums_path,
        dependency_audit_passed=True,
        distribution_check_passed=True,
        wheel_smoke_passed=True,
    )
    return dist, manifest_path, checksums_path, manifest


def test_release_manifest_hashes_and_verifies_two_artifacts(tmp_path):
    dist, manifest_path, checksums_path, manifest = _build(tmp_path)
    assert manifest["schema"] == "bella.release-manifest.v1"
    assert manifest["version"] == "0.2.0"
    assert manifest["commit_sha"] == COMMIT
    assert manifest["gates"]["unit_tests_passed"] == 207
    assert manifest["gates"]["redteam_probes_passed"] == 115
    assert len(manifest["artifacts"]) == 2
    assert verify_release_manifest(manifest_path, dist_dir=dist)

    checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
    assert len(checksum_lines) == 2
    assert all("  bella_harness-0.2.0" in line for line in checksum_lines)


def test_release_manifest_rejects_unpassed_gate(tmp_path):
    dist, pyproject, doctor = _fixture(tmp_path)
    with pytest.raises(ReleaseManifestError, match="dependency audit"):
        build_release_manifest(
            dist_dir=dist,
            pyproject_path=pyproject,
            commit_sha=COMMIT,
            unit_tests=207,
            redteam_probes=115,
            doctor_report_path=doctor,
            output_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "sums",
            dependency_audit_passed=False,
            distribution_check_passed=True,
            wheel_smoke_passed=True,
        )


def test_release_manifest_rejects_not_ready_doctor(tmp_path):
    dist, pyproject, doctor = _fixture(tmp_path)
    payload = json.loads(doctor.read_text(encoding="utf-8"))
    payload["ready"] = False
    doctor.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="not production-ready"):
        build_release_manifest(
            dist_dir=dist,
            pyproject_path=pyproject,
            commit_sha=COMMIT,
            unit_tests=207,
            redteam_probes=115,
            doctor_report_path=doctor,
            output_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "sums",
            dependency_audit_passed=True,
            distribution_check_passed=True,
            wheel_smoke_passed=True,
        )


def test_release_manifest_rejects_missing_or_unexpected_artifacts(tmp_path):
    dist, pyproject, doctor = _fixture(tmp_path)
    (dist / "extra.txt").write_text("unexpected", encoding="utf-8")
    with pytest.raises(ReleaseManifestError, match="unexpected files"):
        build_release_manifest(
            dist_dir=dist,
            pyproject_path=pyproject,
            commit_sha=COMMIT,
            unit_tests=207,
            redteam_probes=115,
            doctor_report_path=doctor,
            output_path=tmp_path / "manifest.json",
            checksums_path=tmp_path / "sums",
            dependency_audit_passed=True,
            distribution_check_passed=True,
            wheel_smoke_passed=True,
        )


def test_release_manifest_detects_artifact_and_manifest_tampering(tmp_path):
    dist, manifest_path, _, _ = _build(tmp_path)
    wheel = dist / "bella_harness-0.2.0-py3-none-any.whl"
    wheel.write_bytes(b"changed")
    assert not verify_release_manifest(manifest_path, dist_dir=dist)

    dist, manifest_path, _, _ = _build(tmp_path / "second")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["commit_sha"] = "b" * 40
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    assert not verify_release_manifest(manifest_path, dist_dir=dist)


def test_project_version_parser_stays_inside_project_table(tmp_path):
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        '[build-system]\nversion = "wrong"\n\n[project]\nversion = "1.2.3"\n',
        encoding="utf-8",
    )
    assert read_project_version(pyproject) == "1.2.3"
