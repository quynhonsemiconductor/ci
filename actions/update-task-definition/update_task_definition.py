#!/usr/bin/env python3
"""Point a task definition at the image tag being deployed, in EVERY container that runs that image.

    aws ecs describe-task-definition --task-definition FAMILY --query taskDefinition \
      | python3 update_task_definition.py --container worker --tag SHA --region R --out new.json

Why every container. The three inline steps this replaces rewrote only the container NAMED after the
service ('api', 'worker', 'migrator'). qnsc-kb's worker task also runs Celery beat from the SAME image in a
second container ('beat'); its Terraform baseline carries the module's default tag, `latest`, which does not
exist in an immutable ECR repository. beat kept `...-worker:latest`, the task could not start
(CannotPullContainerError ... not found), and because beat is essential the worker went down with it.

So: the primary container (--container) defines the service image's REPOSITORY, and every container whose image
is in that repository, at any tag, is moved to --tag. Each one is logged.

And then the result is CHECKED before it is registered, because a rewrite that misses something looks exactly like
a rewrite that worked until the task fails to start:
  * no container may be left on ':latest' (or on no tag, which means latest);
  * every container in this account's ECR must have its tag in ECR. The deploy role can BatchGetImage but not
    DescribeImages, so the lookup is `ecr batch-get-image`.
A failed check exits 1 with nothing registered.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

VERSION_ENV = "SERVICE_VERSION"   # what the products' observability reads for `service.version` and the log `version` field

STRIP = ["taskDefinitionArn", "revision", "status", "requiresAttributes", "placementConstraints", "compatibilities",
         "registeredAt", "registeredBy"]
ECR_HOST = re.compile(r"^(?P<account>\d{12})\.dkr\.ecr\.(?P<region>[a-z0-9-]+)\.amazonaws\.com$")


def split_image(image: str) -> tuple[str, str]:
    """('registry/repo', ref) where ref is 'tag', '@sha256:...' (digest) or '' (no tag: implicit latest)."""
    if "@" in image:
        repo, digest = image.split("@", 1)
        return repo.rsplit(":", 1)[0] if ":" in repo.rsplit("/", 1)[-1] else repo, "@" + digest
    last = image.rsplit("/", 1)[-1]
    if ":" in last:
        repo, tag = image.rsplit(":", 1)
        return repo, tag
    return image, ""


def rewrite(task_def: dict, primary: str, tag: str) -> tuple[dict, list[str], list[str]]:
    containers = task_def.get("containerDefinitions", [])
    main = next((c for c in containers if c.get("name") == primary), None)
    if main is None:
        names = ", ".join(c.get("name", "?") for c in containers)
        return task_def, [], [f"no container named '{primary}' in this task definition (it has: {names})"]
    repo, _ = split_image(main["image"])
    log: list[str] = []
    for c in containers:
        c_repo, c_ref = split_image(c["image"])
        if c_repo != repo:
            log.append(f"  {c['name']}: {c['image']}  (a different image, left alone)")
            continue
        new = f"{repo}:{tag}"
        log.append(f"  {c['name']}: {c['image']} -> {new}" if c["image"] != new else f"  {c['name']}: {new} (already)")
        c["image"] = new
        # The version the app REPORTS must be the tag it RUNS. Terraform's baseline carries its own SERVICE_VERSION (a placeholder in develop, since
        # `latest` does not exist), and rewriting only the image left every develop log line saying "version":"set-by-the-deploy-never-a-real-tag".
        if any(sec.get("name") == VERSION_ENV for sec in c.get("secrets") or []):
            # A secret and an environment entry of the same name cannot both be right (ECS rejects the duplicate or one silently wins), and a version
            # pinned in a secret is not the tag being deployed. Refuse rather than guess.
            return task_def, [], [f"container '{c['name']}' injects {VERSION_ENV} from a secret; it must come from the deployed tag, not a secret"]
        env = [e for e in c.get("environment") or [] if e.get("name") != VERSION_ENV]
        env.append({"name": VERSION_ENV, "value": tag})
        c["environment"] = env
        log.append(f"  {c['name']}: {VERSION_ENV}={tag}")
    for field in STRIP:
        task_def.pop(field, None)
    return task_def, log, []


def check(task_def: dict, rewritten_repo: str, aws_region: str, runner=subprocess.run) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    for c in task_def.get("containerDefinitions", []):
        repo, ref = split_image(c["image"])
        if ref in ("", "latest"):
            errors.append(f"container '{c['name']}' would run {c['image']}: ':latest' (or no tag) is not a version, "
                          "and in an immutable ECR repository it does not exist")
            continue
        if ref.startswith("@"):
            continue
        host, _, name = repo.partition("/")
        m = ECR_HOST.match(host)
        if not m:
            continue  # not ours to look up
        found = runner(["aws", "ecr", "batch-get-image", "--repository-name", name,
                        "--image-ids", f"imageTag={ref}", "--region", m.group("region") or aws_region,
                        "--query", "images[0].imageId.imageTag", "--output", "text"],
                       capture_output=True, text=True)
        out = (found.stdout or "").strip()
        if found.returncode != 0:
            msg = f"container '{c['name']}': could not look up {name}:{ref} in ECR: {(found.stderr or '').strip()}"
            (errors if repo == rewritten_repo else warnings).append(msg)
        elif out in ("", "None"):
            errors.append(f"container '{c['name']}' points at {name}:{ref}, which is not in ECR")
    return errors, warnings


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--container", required=True, help="the container that defines the service image")
    p.add_argument("--tag", required=True)
    p.add_argument("--region", default="")
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)

    task_def = json.load(sys.stdin)
    new_def, log, errors = rewrite(task_def, args.container, args.tag)
    if errors:
        for e in errors:
            print(f"::error title=update-task-definition::{e}")
        return 1
    print(f"Task definition {task_def.get('family', '?')}: image tag -> {args.tag}")
    print("\n".join(log))
    repo, _ = split_image(next(c for c in new_def["containerDefinitions"] if c["name"] == args.container)["image"])
    errors, warnings = check(new_def, repo, args.region)
    for w in warnings:
        print(f"::warning title=update-task-definition::{w}")
    if errors:
        for e in errors:
            print(f"::error title=update-task-definition::{e}")
        print("Refusing to register this task definition.")
        return 1
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(new_def, fh)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
