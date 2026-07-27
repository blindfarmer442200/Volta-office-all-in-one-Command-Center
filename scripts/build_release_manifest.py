#!/usr/bin/env python3
"""Build or verify Bella release evidence using only the standard library."""

from __future__ import annotations

import argparse
import json
import sys

from bella_harness.release_manifest import (
    ReleaseManifestError,
    build_release_manifest,
    verify_release_manifest,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    build = subparsers.add_parser("build", help="Build checksums and release manifest.")
    build.add_argument("--dist-dir", default="dist")
    build.add_argument("--pyproject", default="pyproject.toml")
    build.add_argument("--commit", required=True)
    build.add_argument("--unit-tests", required=True, type=int)
    build.add_argument("--redteam-probes", required=True, type=int)
    build.add_argument("--doctor-report", required=True)
    build.add_argument("--output", default="release-manifest.json")
    build.add_argument("--checksums", default="SHA256SUMS")
    build.add_argument("--dependency-audit-passed", action="store_true")
    build.add_argument("--distribution-check-passed", action="store_true")
    build.add_argument("--wheel-smoke-passed", action="store_true")

    verify = subparsers.add_parser("verify", help="Verify a release manifest and artifacts.")
    verify.add_argument("--manifest", default="release-manifest.json")
    verify.add_argument("--dist-dir", default="dist")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            manifest = build_release_manifest(
                dist_dir=args.dist_dir,
                pyproject_path=args.pyproject,
                commit_sha=args.commit,
                unit_tests=args.unit_tests,
                redteam_probes=args.redteam_probes,
                doctor_report_path=args.doctor_report,
                output_path=args.output,
                checksums_path=args.checksums,
                dependency_audit_passed=args.dependency_audit_passed,
                distribution_check_passed=args.distribution_check_passed,
                wheel_smoke_passed=args.wheel_smoke_passed,
            )
            print(
                json.dumps(
                    {
                        "schema": manifest["schema"],
                        "version": manifest["version"],
                        "commit_sha": manifest["commit_sha"],
                        "manifest_sha256": manifest["manifest_sha256"],
                        "artifacts": manifest["artifacts"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        verified = verify_release_manifest(args.manifest, dist_dir=args.dist_dir)
        print(json.dumps({"verified": verified}, sort_keys=True))
        return 0 if verified else 1
    except ReleaseManifestError as exc:
        print(f"release manifest error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
