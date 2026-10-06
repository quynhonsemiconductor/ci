"""Tests for pr-size — the advisory size check on pull requests.

The cases that matter: what counts as code (a lockfile or a test file must not make a pull request
"large"), where the labels change, and that the check never fails unless `fail-above` was asked for.
Loaded by path: the script ships inside its action and runs as a standalone file.
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import subprocess
import sys

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "actions" / "pr-size" / "pr_size.py"
spec = importlib.util.spec_from_file_location("pr_size", SCRIPT)
pr_size = importlib.util.module_from_spec(spec)
sys.modules["pr_size"] = pr_size  # dataclasses resolve their module by name
spec.loader.exec_module(pr_size)


@pytest.mark.parametrize("path,expected", [
    ("libs/modules/work-items/src/application/work-items.service.ts", "code"),
    ("db/migrations/0132_story_lifecycle_dates.sql", "code"),
    ("apps/web/src/pages/reports/ui/carryover-report.tsx", "code"),
    (".github/workflows/code-review.yml", "code"),
    ("package.json", "code"),
    ("libs/modules/work-items/src/application/work-items.service.spec.ts", "test"),
    ("apps/web/src/pages/reports/ui/carryover-report.test.tsx", "test"),
    ("apps/web/src/test/e2e/story-carryover.e2e.ts", "test"),
    ("test/route-policy.ratchet.spec.ts", "test"),
    ("test/e2e/support/flow-harness.ts", "test"),
    ("scripts/tests/test_gate.py", "test"),
    ("internal/agent/agent_test.go", "test"),
    ("CLAUDE.md", "docs"),
    ("docs/PLAN-phase7-story-carryover.md", "docs"),
    ("pnpm-lock.yaml", "ignored"),
    ("apps/web/pnpm-lock.yaml", "ignored"),
    ("go.sum", "ignored"),
    ("apps/web/src/shared/api/generated/api.ts", "ignored"),
    ("db/migrations/meta/_journal.json", "ignored"),
    ("db/migrations/meta/0133_snapshot.json", "ignored"),
    ("src/__snapshots__/x.test.tsx.snap", "ignored"),
    ("CHANGELOG.md", "ignored"),
    ("proto/user.pb.go", "ignored"),
])
def test_kind(path, expected):
    assert pr_size.kind(path) == expected


@pytest.mark.parametrize("code,label", [
    (0, "size/XS"), (9, "size/XS"), (10, "size/S"), (99, "size/S"), (100, "size/M"),
    (399, "size/M"), (400, "size/L"), (999, "size/L"), (1000, "size/XL"), (2499, "size/XL"),
    (2500, "size/XXL"), (90000, "size/XXL"),
])
def test_label_boundaries(code, label):
    assert pr_size.label_for(code) == label


def files(**lines):
    return [{"filename": name, "additions": n, "deletions": 0} for name, n in lines.items()]


def test_only_code_counts():
    size = pr_size.measure([
        {"filename": "src/a.ts", "additions": 300, "deletions": 50},
        {"filename": "src/a.test.ts", "additions": 5000, "deletions": 0},
        {"filename": "pnpm-lock.yaml", "additions": 9000, "deletions": 8000},
        {"filename": "README.md", "additions": 400, "deletions": 0},
        {"filename": "img.png", "additions": 0, "deletions": 0},
    ])
    assert size.code == 350
    assert size.lines == {"code": 350, "test": 5000, "docs": 400, "ignored": 17000}
    assert pr_size.decide(size, 1000, 2500, 0, False).level == "none"


def test_a_dependency_bump_is_tiny():
    size = pr_size.measure([
        {"filename": "package.json", "additions": 3, "deletions": 3},
        {"filename": "pnpm-lock.yaml", "additions": 517, "deletions": 369},
    ])
    assert pr_size.label_for(size.code) == "size/XS"


def test_levels_and_body():
    size = pr_size.measure([{"filename": f"src/f{i}.ts", "additions": 300, "deletions": 0}
                            for i in range(5)])
    d = pr_size.decide(size, 1000, 2500, 0, False)
    assert (d.label, d.level, d.fail) == ("size/XL", "warn", False)
    assert d.body.startswith(pr_size.MARKER) and "1,500 lines of code" in d.body
    assert "`src/f0.ts` (300)" in d.body and "per layer" in d.body

    big = pr_size.measure(files(**{"src/big.ts": 4574}))
    d = pr_size.decide(big, 1000, 2500, 0, False)
    assert (d.level, d.fail) == ("large", False) and "marked ready for review" in d.body


def test_fail_above_and_override():
    big = pr_size.measure(files(**{"src/big.ts": 4000}))
    d = pr_size.decide(big, 1000, 2500, 3000, False)
    assert (d.level, d.fail) == ("fail", True) and "override label" in d.body
    assert pr_size.decide(big, 1000, 2500, 3000, True).level == "large"   # overridden
    assert not pr_size.decide(big, 1000, 2500, 0, False).fail             # 0 never fails


def test_cli_rova_653_shape(tmp_path):
    """The shape of rova#653: big in raw lines, and still big once only code counts."""
    rows = [
        {"filename": "libs/modules/work-items/src/application/work-items.service.ts", "additions": 470, "deletions": 1},
        {"filename": "libs/modules/work-items/src/application/work-items.service.spec.ts", "additions": 480, "deletions": 2},
        {"filename": "apps/web/src/shared/api/generated/api.ts", "additions": 719, "deletions": 10},
        {"filename": "docs/PLAN-phase7-story-carryover.md", "additions": 363, "deletions": 0},
        {"filename": "db/migrations/meta/_journal.json", "additions": 21, "deletions": 0},
    ] + [{"filename": f"apps/web/src/pages/p{i}.tsx", "additions": 150, "deletions": 3} for i in range(26)]
    f = tmp_path / "files.jsonl"
    f.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    out, body = tmp_path / "out", tmp_path / "body.md"
    subprocess.run([sys.executable, str(SCRIPT), "--files", str(f), "--body-out", str(body)],
                   check=True, capture_output=True,
                   env={"GITHUB_OUTPUT": str(out), "WARN_ABOVE": "1000", "LARGE_ABOVE": "2500",
                        "FAIL_ABOVE": "0", "PATH": ""})
    text = out.read_text()
    assert "label=size/XXL" in text and "level=large" in text and "fail=false" in text
    assert "code_lines=4449" in text


def test_cli_small_pr_writes_an_empty_body(tmp_path):
    f = tmp_path / "files.jsonl"
    f.write_text(json.dumps({"filename": "src/a.ts", "additions": 20, "deletions": 3}) + "\n")
    out, body = tmp_path / "out", tmp_path / "body.md"
    subprocess.run([sys.executable, str(SCRIPT), "--files", str(f), "--body-out", str(body)],
                   check=True, capture_output=True,
                   env={"GITHUB_OUTPUT": str(out), "WARN_ABOVE": "1000", "PATH": ""})
    assert body.read_text() == "" and "label=size/S" in out.read_text()


def test_standard_library_only():
    source = SCRIPT.read_text()
    imports = {m.split()[1].split(".")[0] for m in source.splitlines()
               if m.startswith(("import ", "from ")) and "__future__" not in m}
    assert imports <= {"argparse", "json", "os", "re", "sys", "dataclasses", "pathlib"}


def test_action_metadata_parses():
    """actionlint checks workflows, not action.yml — an unquoted `key: value` in a description
    broke this file once and nothing else would have noticed before a caller ran it."""
    import yaml
    action = yaml.safe_load((SCRIPT.parent / "action.yml").read_text())
    assert set(action["inputs"]) == {"github-token", "warn-above", "large-above", "fail-above",
                                     "override-label"}
    assert action["inputs"]["fail-above"]["default"] == "0"   # advisory unless asked
    assert action["runs"]["using"] == "composite"
