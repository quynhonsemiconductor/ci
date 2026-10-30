"""Org-wide exclude patterns must name file KINDS, never a repository's code.

rova#821 (2026-10-30) spent its whole token budget on user-guide prose: 63% of
the lines, 11 of 21 findings documentation nits, and the code files partly
unread. The org-wide excludes in `rules/base.json` exist to make that
impossible — which only holds if every pattern matches a KIND of file (a
lockfile, a snapshot, generated code, translation data, prose) and never a
path a repository's source could live on. A pattern like `**/content/**`
names a layout, not a kind, and stays a per-repo `exclude:` input; this test
is the tripwire that keeps such patterns out of the profiles.
"""

from __future__ import annotations

import fnmatch
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def union_excludes() -> list[str]:
    patterns: list[str] = []
    for path in sorted((ROOT / "rules").glob("*.json")):
        patterns += json.loads(path.read_text(encoding="utf-8")).get("exclude", [])
    return list(dict.fromkeys(patterns))


# A source file must survive every org-wide exclude pattern. These paths are
# the shapes real code lives on across the org's repositories.
CODE_PATHS = [
    "src/main.ts",
    "apps/api/src/auth/session.guard.ts",
    "apps/web/src/pages/guide/content/en/chapter-00.tsx",  # prose PATH, code FILE: per-repo choice
    "apps/web/functions/_lib/guide-gate.ts",
    "db/migrations/0001_add_users.sql",
    "functions/_lib/guide-gate.ts",
    "internal/worker/pipeline.py",
    "packages/http/src/fetch.client.ts",
    "src/i18n/setup.ts",
    "src/locales/load.ts",
    "src/fixtures_test.py",
    "test/snapshots_test.ts",
]

# Files a KIND exclude exists for. Each must be matched by at least one
# pattern, so the org-wide list cannot silently stop covering its kinds.
KIND_PATHS = [
    "pnpm-lock.yaml",
    "apps/web/package-lock.json",
    "docs/ARCHITECTURE.md",
    "README.mdx",
    "apps/web/src/locales/en.json",
    "apps/web/src/i18n/vi.json",
    "src/__snapshots__/render.test.tsx.snap",
    "src/button.test.tsx.snap",
    "src/routes/routeTree.gen.ts",
    "src/api/client.gen.tsx",
    "packages/db/generated/schema.ts",
    "tests/fixtures/identity-token.json",
    "src/__fixtures__/response-body.json",
    "static/app.min.js",
    "static/app.min.css",
    "static/app.js.map",
]


def kind_match(path: str, pattern: str) -> bool:
    """Approximate the glob engine OCR uses: a leading `**/` also matches zero
    directories, so `**/*.md` covers a root README, and a mid-pattern `**/`
    collapses the same way, so `**/locales/**/*.json` covers `src/locales/en.json`.
    fnmatch's `*` crossing `/` is looser than gitignore's, which is fine here —
    the test asks whether a pattern NAMES a kind of file, not for engine parity."""
    candidates = {pattern}
    if pattern.startswith("**/"):
        candidates.add(pattern[3:])
    candidates.add(pattern.replace("/**/", "/"))
    return any(fnmatch.fnmatch(path, c) for c in candidates)


def test_no_org_wide_exclude_matches_a_code_path():
    for path in CODE_PATHS:
        for pattern in union_excludes():
            if kind_match(path, pattern):
                raise AssertionError(f"exclude {pattern!r} matches code path {path!r}")


def test_every_kind_is_still_excluded():
    for path in KIND_PATHS:
        assert any(kind_match(path, p) for p in union_excludes()), f"{path!r} is no longer excluded"
