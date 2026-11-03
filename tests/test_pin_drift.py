"""Tests for scripts/pin_drift.py (stdlib only).

The report's job is to say which consumer is on an old pin. It read only TAG refs (`@v1.7.2`), but every consumer has
pinned a full commit SHA with the release in a `# vX.Y.Z` comment since 2026-10-20 — so the `ci` row was empty and stale
pins were never reported. These tests pin the SHA+comment form down, plus the forms that must NOT be read.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import pin_drift  # noqa: E402

SHA = "4ab9d053b565b4fef50da119b0ff675de19217e0"


def versions(*lines: str) -> set[str]:
    with TemporaryDirectory() as tmp:
        (Path(tmp) / "ci.yml").write_text("\n".join(lines) + "\n")
        return pin_drift.pins_used(Path(tmp))[0]


class CiPins(unittest.TestCase):
    def test_a_sha_pin_with_a_release_comment_is_read(self):
        self.assertEqual(
            versions(f"uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@{SHA} # v1.21.0"),
            {"v1.21.0"},
        )

    def test_the_whitespace_and_alignment_do_not_matter(self):
        for gap in (" ", "  ", "\t", "    "):
            with self.subTest(gap=repr(gap)):
                self.assertEqual(
                    versions(f"      uses: quynhonsemiconductor/ci/.github/workflows/security.yml@{SHA}{gap}# v1.24.3"),
                    {"v1.24.3"},
                )

    def test_a_second_comment_after_the_version_is_ignored(self):
        # rova's web-ci carries `# v1.29.0 # ci#245 force-run; bump ...`
        self.assertEqual(
            versions(f"uses: quynhonsemiconductor/ci/actions/changed-paths@{SHA} # v1.29.0 # ci#245 force-run"),
            {"v1.29.0"},
        )

    def test_a_truncated_release_comment_is_read_as_what_it_says(self):
        self.assertEqual(versions(f"uses: quynhonsemiconductor/ci/.github/workflows/labeler.yml@{SHA} # v1"), {"v1"})

    def test_a_tag_pin_is_still_read(self):
        self.assertEqual(versions("uses: quynhonsemiconductor/ci/actions/pr-labels@v1.24.3"), {"v1.24.3"})
        self.assertEqual(versions("uses: quynhonsemiconductor/ci/actions/pr-labels@v1"), {"v1"})

    def test_a_sha_without_a_comment_is_not_guessed(self):
        # Nothing to read: the SHA does not encode its release. Left out rather than invented.
        self.assertEqual(versions(f"uses: quynhonsemiconductor/ci/actions/pr-labels@{SHA}"), set())

    def test_a_comment_that_is_not_a_version_is_ignored(self):
        self.assertEqual(versions(f"uses: quynhonsemiconductor/ci/actions/pr-labels@{SHA} # ci#243"), set())

    def test_another_repositorys_pin_is_not_ci(self):
        self.assertEqual(versions(f"uses: actions/checkout@{SHA} # v7.0.1"), set())

    def test_both_forms_in_one_repository_are_reported_together(self):
        # A repo mid-migration: the report's whole point is that this is one finding, not two rows.
        self.assertEqual(
            versions(
                f"uses: quynhonsemiconductor/ci/.github/workflows/security.yml@{SHA} # v1.22.0",
                "uses: quynhonsemiconductor/ci/.github/workflows/pr-title.yml@v1",
            ),
            {"v1.22.0", "v1"},
        )


class Classification(unittest.TestCase):
    def test_a_sha_comment_makes_staleness_visible(self):
        self.assertEqual(pin_drift.classify(["v1.23.0", "v1.23.0"], "v1.31.0"), "stale")
        self.assertEqual(pin_drift.classify(["v1.23.0", "v1.31.0"], "v1.31.0"), "**diverged**")
        self.assertEqual(pin_drift.classify(["", "v1.31.0"], "v1.31.0"), "ok")
        self.assertEqual(pin_drift.classify(["v1"], "v1.31.0"), "ok")  # a truncated pin is a different thing, not stale


if __name__ == "__main__":
    unittest.main(verbosity=2)
