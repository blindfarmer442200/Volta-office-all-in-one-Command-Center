"""Deterministic release artifact hashing and manifest generation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RELEASE_MANIFEST_SCHEMA = "bella.release-manifest.v1"
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"\s*$')


class ReleaseManifestError(RuntimeError):
    """Raised when release evidence is missing, malformed, or inconsistent."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_name = handle.name
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def read_project_version(pyproject_path: str | Path) -> str:
    path = Path(pyproject_path)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ReleaseManifestError(f"unable to read project metadata: {exc}") from exc
    in_project = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_project = line == "[project]"
            continue
        if in_project:
            match = _VERSION_RE.match(line)
            if match:
                version = match.group(1).strip()
                if not version or len(version) > 100:
                    break
                return version
    raise ReleaseManifestError("project version was not found in [project]")


def _read_doctor_report(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseManifestError(f"unable to read doctor report: {exc}") from exc
    if not isinstance(payload, dict):
        raise ReleaseManifestError("doctor report must be a JSON object")
    if payload.get("schema") != "bella.doctor-report.v1":
        raise ReleaseManifestError("doctor report schema is invalid")
    if payload.get("ready") is not True:
        raise ReleaseManifestError("doctor report is not production-ready")
    return payload


def build_release_manifest(
    *,
    dist_dir: str | Path,
    pyproject_path: str | Path,
    commit_sha: str,
    unit_tests: int,
    redteam_probes: int,
    doctor_report_path: str | Path,
    output_path: str | Path,
    checksums_path: str | Path,
    dependency_audit_passed: bool,
    distribution_check_passed: bool,
    wheel_smoke_passed: bool,
) -> dict[str, Any]:
    """Validate release evidence, hash artifacts, and write atomic outputs."""
    if not isinstance(commit_sha, str) or not _COMMIT_RE.fullmatch(commit_sha):
        raise ReleaseManifestError("commit SHA must be 40 lowercase hexadecimal characters")
    if not isinstance(unit_tests, int) or isinstance(unit_tests, bool) or unit_tests < 1:
        raise ReleaseManifestError("unit test count must be a positive integer")
    if (
        not isinstance(redteam_probes, int)
        or isinstance(redteam_probes, bool)
        or redteam_probes < 1
    ):
        raise ReleaseManifestError("red-team probe count must be a positive integer")
    for name, value in (
        ("dependency audit", dependency_audit_passed),
        ("distribution check", distribution_check_passed),
        ("wheel smoke", wheel_smoke_passed),
    ):
        if value is not True:
            raise ReleaseManifestError(f"{name} must pass before manifest generation")

    directory = Path(dist_dir)
    if not directory.is_dir():
        raise ReleaseManifestError("distribution directory does not exist")
    artifacts = sorted(path for path in directory.iterdir() if path.is_file())
    wheels = [path for path in artifacts if path.suffix == ".whl"]
    sdists = [
        path
        for path in artifacts
        if path.name.endswith(".tar.gz") or path.name.endswith(".zip")
    ]
    if len(wheels) != 1:
        raise ReleaseManifestError("release must contain exactly one wheel")
    if len(sdists) != 1:
        raise ReleaseManifestError("release must contain exactly one source archive")
    if len(artifacts) != 2:
        raise ReleaseManifestError("distribution directory contains unexpected files")

    version = read_project_version(pyproject_path)
    expected_prefix = f"bella_harness-{version}"
    if not wheels[0].name.startswith(expected_prefix):
        raise ReleaseManifestError("wheel filename does not match project version")
    normalized_sdist_prefix = f"bella_harness-{version}"
    alternate_sdist_prefix = f"bella-harness-{version}"
    if not sdists[0].name.startswith((normalized_sdist_prefix, alternate_sdist_prefix)):
        raise ReleaseManifestError("source archive filename does not match project version")

    doctor = _read_doctor_report(Path(doctor_report_path))
    file_records = []
    checksum_lines = []
    for artifact in artifacts:
        digest = _sha256_file(artifact)
        size = artifact.stat().st_size
        if size < 1:
            raise ReleaseManifestError(f"release artifact is empty: {artifact.name}")
        file_records.append(
            {
                "name": artifact.name,
                "sha256": digest,
                "bytes": size,
            }
        )
        checksum_lines.append(f"{digest}  {artifact.name}\n")

    core = {
        "schema": RELEASE_MANIFEST_SCHEMA,
        "version": version,
        "commit_sha": commit_sha,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "gates": {
            "unit_tests_passed": unit_tests,
            "redteam_probes_passed": redteam_probes,
            "doctor_ready": True,
            "doctor_package_version": doctor.get("package_version"),
            "dependency_audit_passed": True,
            "distribution_check_passed": True,
            "wheel_smoke_passed": True,
        },
        "artifacts": file_records,
    }
    manifest_sha256 = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
    manifest = {**core, "manifest_sha256": manifest_sha256}

    _atomic_write(
        Path(output_path),
        (json.dumps(manifest, indent=2, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    _atomic_write(Path(checksums_path), "".join(checksum_lines).encode("utf-8"))
    return manifest


def verify_release_manifest(
    manifest_path: str | Path,
    *,
    dist_dir: str | Path,
) -> bool:
    """Verify manifest integrity and current distribution hashes."""
    try:
        manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(manifest, dict):
            return False
        provided = manifest.get("manifest_sha256")
        if not isinstance(provided, str):
            return False
        core = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        expected = hashlib.sha256(_canonical_json(core).encode("utf-8")).hexdigest()
        if provided != expected:
            return False
        if manifest.get("schema") != RELEASE_MANIFEST_SCHEMA:
            return False
        directory = Path(dist_dir)
        records = manifest.get("artifacts")
        if not isinstance(records, list) or len(records) != 2:
            return False
        for record in records:
            if not isinstance(record, dict):
                return False
            name = record.get("name")
            digest = record.get("sha256")
            size = record.get("bytes")
            if not isinstance(name, str) or Path(name).name != name:
                return False
            artifact = directory / name
            if not artifact.is_file() or artifact.stat().st_size != size:
                return False
            if _sha256_file(artifact) != digest:
                return False
        return True
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return False
