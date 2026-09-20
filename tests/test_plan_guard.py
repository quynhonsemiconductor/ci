"""Tests for plan_guard — task 0.3's replacement for `prevent_destroy`.

The cases that matter are the ones where a guard could pass when it should not:
an unreadable plan, a replace disguised as a create, and an allowance with no
reason. Those are the bugs this estate has actually shipped before (#129, #132).
"""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "plan_guard.py"


def run(tmp_path: pathlib.Path, doc, allow: str | None = None):
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(doc) if not isinstance(doc, str) else doc)
    if allow is not None:
        (tmp_path / ".allow-data-destroy").write_text(allow)
    proc = subprocess.run([sys.executable, str(SCRIPT), str(plan)],
                          capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def change(addr: str, rtype: str, actions: list[str]) -> dict:
    return {"address": addr, "type": rtype, "change": {"actions": actions}}


def plan(*changes) -> dict:
    return {"format_version": "1.2", "resource_changes": list(changes)}


# ── the happy paths ──────────────────────────────────────────────────────────

def test_empty_plan_passes(tmp_path):
    code, out = run(tmp_path, plan())
    assert code == 0
    assert "no data resource is destroyed" in out


def test_creating_a_database_is_fine(tmp_path):
    code, out = run(tmp_path, plan(change("m.p.aws_db_instance.this", "aws_db_instance", ["create"])))
    assert code == 0


def test_updating_a_database_in_place_is_fine(tmp_path):
    code, out = run(tmp_path, plan(change("m.p.aws_db_instance.this", "aws_db_instance", ["update"])))
    assert code == 0


def test_destroying_a_non_data_resource_is_fine(tmp_path):
    """An ECS service, a security group, a route table — all a re-apply away."""
    code, out = run(tmp_path, plan(
        change("m.s.aws_ecs_service.api", "aws_ecs_service", ["delete"]),
        change("aws_security_group.app", "aws_security_group", ["delete"]),
    ))
    assert code == 0, out


def test_subnet_group_is_not_data(tmp_path):
    """rova-subnet-group-rebuild.md replaces one of these. It holds no data."""
    code, out = run(tmp_path, plan(
        change("m.p.aws_db_subnet_group.this", "aws_db_subnet_group", ["create", "delete"])))
    assert code == 0, out


# ── the refusals ─────────────────────────────────────────────────────────────

def test_destroying_a_database_is_refused(tmp_path):
    code, out = run(tmp_path, plan(
        change("m.postgres.aws_db_instance.this", "aws_db_instance", ["delete"])))
    assert code == 1
    assert "REFUSING THIS PLAN" in out
    assert "m.postgres.aws_db_instance.this" in out


def test_replace_is_treated_as_destroy(tmp_path):
    """The case most likely to slip through: the plan says create AND delete."""
    code, out = run(tmp_path, plan(
        change("m.postgres.aws_db_instance.this", "aws_db_instance", ["create", "delete"])))
    assert code == 1
    assert "REPLACE" in out


def test_replace_in_the_other_order_is_also_caught(tmp_path):
    code, out = run(tmp_path, plan(
        change("m.c.aws_elasticache_replication_group.this",
               "aws_elasticache_replication_group", ["delete", "create"])))
    assert code == 1


def test_secret_destroy_is_refused(tmp_path):
    code, out = run(tmp_path, plan(
        change('m.s.aws_secretsmanager_secret.app["jwt"]',
               "aws_secretsmanager_secret", ["delete"])))
    assert code == 1


def test_postgresql_database_is_refused(tmp_path):
    """A database on a SHARED instance: RDS deletion_protection guards the instance,
    nothing guards one database on it."""
    code, out = run(tmp_path, plan(
        change("m.profile.postgresql_database.this[0]", "postgresql_database", ["delete"])))
    assert code == 1


# ── the allowance file ───────────────────────────────────────────────────────

def test_allowance_permits_the_named_address(tmp_path):
    code, out = run(
        tmp_path,
        plan(change("m.postgres.aws_db_instance.this", "aws_db_instance", ["create", "delete"])),
        allow="m.postgres.aws_db_instance.this  -- rova-subnet-group-rebuild.md step 3\n",
    )
    assert code == 0, out
    assert "every one declared" in out


def test_allowance_does_not_cover_a_different_address(tmp_path):
    code, out = run(
        tmp_path,
        plan(change("m.other.aws_db_instance.this", "aws_db_instance", ["delete"])),
        allow="m.postgres.aws_db_instance.this  -- a different instance entirely\n",
    )
    assert code == 1
    assert "m.other.aws_db_instance.this" in out


def test_allowance_without_a_reason_is_refused(tmp_path):
    code, out = run(
        tmp_path,
        plan(change("m.postgres.aws_db_instance.this", "aws_db_instance", ["delete"])),
        allow="m.postgres.aws_db_instance.this\n",
    )
    assert code != 0
    assert "has no reason" in out


def test_stale_allowance_warns_but_passes(tmp_path):
    code, out = run(tmp_path, plan(), allow="m.gone.aws_db_instance.this  -- done last week\n")
    assert code == 0
    assert "STALE ALLOWANCES" in out


def test_comments_and_blank_lines_are_ignored(tmp_path):
    code, out = run(
        tmp_path,
        plan(change("m.p.aws_db_instance.this", "aws_db_instance", ["delete"])),
        allow="# teardown of the preview instance\n\nm.p.aws_db_instance.this  -- preview, ephemeral by design\n",
    )
    assert code == 0, out


# ── the failure modes a guard must not have ──────────────────────────────────

def test_unreadable_json_fails_loudly(tmp_path):
    code, out = run(tmp_path, "this is not json")
    assert code != 0
    assert "not valid JSON" in out


def test_a_document_with_no_resource_changes_and_no_format_version_fails(tmp_path):
    """The bug this estate has shipped twice: reporting success on data never read."""
    code, out = run(tmp_path, {"something": "else"})
    assert code != 0
    assert "could not read" in out


def test_a_genuinely_empty_plan_is_distinguished_from_an_unreadable_one(tmp_path):
    """OpenTofu omits resource_changes when there are none. That IS a pass."""
    code, out = run(tmp_path, {"format_version": "1.2"})
    assert code == 0, out


def test_it_reports_how_many_changes_it_read(tmp_path):
    """So a reviewer can see the guard looked at something."""
    code, out = run(tmp_path, plan(
        change("a", "aws_ecs_service", ["update"]),
        change("b", "aws_ecs_service", ["update"]),
    ))
    assert code == 0
    assert "2 resource change(s) read" in out
