# ci

Shared GitHub Actions composite actions for all QNSC product repositories (Rova, OpsHub, and future products).

Shared CI/CD logic lives here as versioned composite actions, so bug fixes and improvements propagate automatically to all consumers on the next reference — no copy-paste drift. The examples below use Rova repositories, but the same actions are consumed by OpsHub and any other QNSC product.

---

## Actions

> **AWS exit, 2026-11-02.** The AWS-only actions (`setup-aws-oidc`, `ecs-run-task`, `update-task-definition`, `run-db-migration`, `ensure-environment-awake`, `promote-ecr-images`) and the `backend-deploy.yml` reusable were removed; no repository in the organisation referenced them.

### Node / Build
| Action | Description |
|---|---|
| [`setup-node-pnpm`](actions/setup-node-pnpm/action.yml) | Install pnpm, set up Node.js with cache, run `pnpm install` |

### Docker / GHCR
| Action | Description |
|---|---|
| [`build-push-image`](actions/build-push-image/action.yml) | Buildx build + push, with an optional pre-push scan. Caller logs in first |
| [`build-push-ecr`](actions/build-push-ecr/action.yml) | **Deprecated path, removed in v1.35.0**; identical to `build-push-image` |
| [`release-retag`](actions/release-retag/action.yml) | Add a release tag to the digests already published for a commit — verifies the build attestation first, never rebuilds. The [`release-retag` reusable workflow](.github/workflows/release-retag.yml) runs it on a tag push |

### ECS / Deploy
| Action | Description |
|---|---|
| [`post-deploy-health-check`](actions/post-deploy-health-check/action.yml) | Poll `/health/ready` until HTTP 200 (optionally assert version) |

### CDN / Frontend
| Action | Description |
|---|---|

### API Contract
| Action | Description |
|---|---|
| [`publish-openapi-spec`](actions/publish-openapi-spec/action.yml) | Upload the generated spec as a GitHub artifact for the contract check and FE codegen |
| [`validate-openapi-contract`](actions/validate-openapi-contract/action.yml) | oasdiff breaking-change detection between two OpenAPI specs |
| [`fetch-openapi-base-spec`](actions/fetch-openapi-base-spec/action.yml) | Download the OpenAPI spec of a pull request's base commit (or its nearest ancestor), failing rather than skipping when it is missing |

### Security / Quality
| Action | Description |
|---|---|
| [`scan-secrets`](actions/scan-secrets/action.yml) | Gitleaks secret scan with SARIF upload to GitHub Security tab |
| [`scan-osv`](actions/scan-osv/action.yml) | osv-scanner dependency CVE scan (report-only unless `blocking`) |
| [`scan-semgrep`](actions/scan-semgrep/action.yml) | Semgrep SAST through the official image (report-only unless `blocking`) |
| [`scan-image`](actions/scan-image/action.yml) | Trivy over a local image: CRITICAL blocks, HIGH reported. Run it right after the product's own Docker build (`load: true`) instead of building a second time in the security workflow |
| [`lint-workflows`](actions/lint-workflows/action.yml) | actionlint over the repo (always blocks) |
| [`audit-workflows`](actions/audit-workflows/action.yml) | zizmor over the repo (report-only unless `blocking`) |
| [`pr-labels`](actions/pr-labels/action.yml) | `area/*` and `size/*` labels as steps, so the PR-title job can label in the same runner |
| [`changed-paths`](actions/changed-paths/action.yml) | Decide from a PR's changed files whether a workflow's heavy jobs need to run (`run=true|false`). Fails open: only "every file is on the ignore list" skips. Gate on its output, never on bare `allow-skipped` |
| [`pr-title-conventional-commits`](actions/pr-title-conventional-commits/action.yml) | Validate a PR title against Conventional Commits — Release Please derives the CHANGELOG from it |
| [`pr-size`](actions/pr-size/action.yml) | Label a PR `size/XS…XXL` by lines of CODE (tests, docs, lockfiles and generated files reported, not counted) and comment above 1,000 — advisory unless `fail-above` is set |
| [`assert-jobs-succeeded`](actions/assert-jobs-succeeded/action.yml) | Fail a CI gate job unless every job it depends on reported `success` — closes the skipped/cancelled-counts-as-passing hole |
| [`wait-for-run`](actions/wait-for-run/action.yml) | Block until another workflow's run for THIS commit finishes, then propagate its conclusion — retries a rate limit instead of reporting it as a failed run |

### A REQUIRED check must be a composite action, never a reusable workflow

The single most expensive mistake available in this repo, and it fails in the one
direction CI normally cannot: **it does not go red, it goes silent.**

A job that calls a reusable workflow reports its check as `<caller job>/<called
job>` — the security suite here shows up as `security / SAST (Semgrep)` for exactly
this reason. So a reusable `test-guard` reports **`test-guard / test-guard`**, and a
ruleset requiring `test-guard` matches nothing at all. **A required check that never
reports does not fail — it blocks every merge indefinitely**, sitting as "Expected"
in the protection UI with nothing to click.

The same trap runs in reverse when a workflow is deleted: removing a workflow that
backs a required check leaves the same permanent "Expected". Check the ruleset before
deleting one:

```bash
gh api repos/<org>/<repo>/rulesets/<id> \
  -q '.rules[] | select(.type=="required_status_checks")
       | .parameters.required_status_checks[].context'
```

**The rule:** if the check name appears in `required_status_checks`, call a composite
action from a job defined in the consuming repository, so the job id and name stay
local and under that repo's control. Reusable workflows are fine for everything that
is not a required check.

Currently required in rova and opshub, and therefore action-shaped:
`PR title (conventional commits)`, `Lint & typecheck`, `Tests`, `E2E (Playwright)`,
`Migration upgrade path`, `OpenAPI contract`.

#### …and requiring each job by name is still not enough

Naming every job in `required_status_checks` closes the "wrong check name" half of the
trap and leaves the other half open: **a SKIPPED or CANCELLED required check counts as
PASSING.** So a job that never runs cannot be caught by requiring that job.

Both org incidents are this bug:

* opshub #110 — a PR-title edit cancelled the in-flight run; `cancel-in-progress` plus
  `if: action != 'edited'` guards replaced it with a run where every heavy job skipped.
  Green, having executed nothing. Three times.
* rova #558-#590 — `pull_request.branches: [main]` skipped the whole workflow for a PR
  aimed at the branch below it in a stack. Five PRs sat on `5/5` green with no tests, no
  build, no E2E, no migration check and no security scan.

Fix the cause, then add one **aggregate gate** per workflow so the class of bug cannot
return the next time somebody adds an `if:` or a `paths:` filter. The gate asserts a
positive `success` from every job, which is why
[`assert-jobs-succeeded`](actions/assert-jobs-succeeded/action.yml) compares against
`success` instead of listing known-bad states — a `contains(needs.*.result, 'failure')`
check silently passes any result GitHub adds later.

```yaml
  ci-required:
    name: Backend CI required     # this name IS the required check
    if: always()                  # mandatory — without it the gate skips when a dep fails
    needs: [quality, test, migrations, build, openapi]   # MUST list every job
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: quynhonsemiconductor/ci/actions/assert-jobs-succeeded@v1.21.0
        with:
          results: ${{ join(needs.*.result, ',') }}
```

Then require **only** the gate name (`Backend CI required`, `Web CI required`) rather than
the individual jobs. Two things to keep in mind when adopting it:

* Add the gate to the ruleset **only after** the workflow change is on the default branch.
  A required check that does not exist yet blocks every merge, including the release PR.
* A workflow with legitimately conditional jobs — `infra`'s `Detect changed stacks` matrix,
  for example — needs either `allow-skipped: true` or those jobs left out of `needs`.
  Prefer trimming `needs`, so "did not run" stays fatal for everything that should run.

Give two workflows in the same repo **distinct** gate names. rova's `backend-ci.yml` and
`web-ci.yml` both publish a job called `Lint & typecheck`, and a required check matched by
name against two producers is ambiguous.

The action form keeps the job local, so the check keeps the name of its job and an existing ruleset needs no change.

## Prerequisites

### GitHub repository secrets
Configure in each consuming repo → **Settings → Secrets and variables → Actions**:
```
AWS_ACCOUNT_ID              # e.g. 123456789012
SLACK_DEPLOY_WEBHOOK        # Slack or Discord incoming webhook URL
```

### GitHub repository variables
```
AWS_REGION                  # e.g. ap-southeast-1
ECS_CLUSTER                 # e.g. rova-develop
ECS_API_SERVICE             # e.g. rova-develop-api
ECS_WORKER_SERVICE          # e.g. rova-develop-worker
CLOUDFRONT_DISTRIBUTION_ID  # rova-web only
PRIVATE_SUBNET_IDS          # comma-separated private subnet IDs
MIGRATOR_SG_ID              # security group ID for migrator tasks
```

## Canonical Pipelines

### CI — quality gates (lint + typecheck + test + OpenAPI)

```yaml
jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm lint && pnpm typecheck

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm test:ci

  openapi:                          # rova-api only
    needs: [quality, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm build:openapi      # generates openapi.json
      - uses: quynhonsemiconductor/ci/actions/publish-openapi-spec@main
        with:
          artifact-name: openapi-spec-${{ github.sha }}
      - uses: actions/download-artifact@v4
        with:
          name: openapi-spec-base    # uploaded by base-branch CI
          path: base-spec/
        continue-on-error: true      # graceful on first run / new branch
      - uses: quynhonsemiconductor/ci/actions/validate-openapi-contract@main
        with:
          current-spec-path: openapi.json
          base-spec-path: base-spec/openapi.json
          # An intentional break: add the PR label `allow-breaking-api-change` and push (see the action's docs).
```

### Security scan (weekly + on push to main)

```yaml
jobs:
  secrets:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0          # full history for gitleaks
      - uses: quynhonsemiconductor/ci/actions/scan-secrets@main

  sast:                           # GitHub-native CodeQL — no composite needed
    runs-on: ubuntu-latest
    permissions:
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - uses: github/codeql-action/init@v3
        with:
          languages: javascript-typescript
      - uses: github/codeql-action/analyze@v3
```

---

## Action Reference

### `setup-node-pnpm`
| Input | Default | Description |
|---|---|---|
| `node-version` | `22` | Node.js version |
| `pnpm-version` | `10.33.2` | pnpm version (10 or 11) |
| `install-deps` | `true` | Run `pnpm install --frozen-lockfile` |
| `working-directory` | `.` | Working directory |

**Registry authentication (pnpm 10 and 11).** pnpm 11 ignores a token in a *project* `.npmrc` (the
`//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}` line the products commit) and answers `ERR_PNPM_FETCH_401`;
pnpm 10 still honours it. So the action first writes a **user-level** npmrc, which both versions expand, and exports its
path as `NPM_CONFIG_USERCONFIG`:

```ini
@quynhonsemiconductor:registry=https://npm.pkg.github.com
//npm.pkg.github.com/:_authToken=${NODE_AUTH_TOKEN}
```

- **The token is a placeholder**, expanded by pnpm when it reads the file. The action never reads, prints or stores the
  secret, so there is no secret at rest. Provide `NODE_AUTH_TOKEN` as you do today (job-level `env`, or on the step that
  installs); the same applies to a later step when you set `install-deps: 'false'`.
- The file is mode 600 in a mode 700 directory under `$RUNNER_TEMP`. Only its **path** goes to `GITHUB_ENV`.
- **Nothing to change in a caller.** Keep your project `.npmrc` as it is: on pnpm 10 it still works, on pnpm 11 its token
  line is ignored (pnpm prints `Ignored project-level auth setting`) and this file supplies the credential.
- Existing config is kept: if `NPM_CONFIG_USERCONFIG` or `~/.npmrc` already exists its lines are carried over, and a
  scope registry or token line for `npm.pkg.github.com` that is already there is not overridden.
- A job with no token (a build of public packages) still installs; pnpm warns `Failed to replace env in config`, as it
  already does for a project `.npmrc` that has the same line.

Proven by `.github/workflows/setup-node-pnpm-test.yml`, which installs a private `@quynhonsemiconductor` package on pnpm
10.33.2 and 11.28.5 (token at job level and on the step; clean and legacy project `.npmrc`; no token; `install-deps: 'false'`),
and includes a control showing that **without** the action pnpm 11 fails and pnpm 10 does not.

---

### `build-push-image`
Log in to the target registry first (`docker/login-action`; GHCR with `GITHUB_TOKEN`).

| Input | Default | Description |
|---|---|---|
| `registry` | **required** | Registry and namespace, no trailing slash (e.g. `ghcr.io/quynhonsemiconductor`). The old name `ecr-registry` is accepted until v1.35.0 |
| `image-name` | **required** | Repository name inside the registry (e.g. `rova-api`) |
| `image-tag` | **required** | Primary tag (e.g. `sha-abc1234`) |
| `extra-tags` | `` | Newline-separated additional tags |
| `dockerfile` | `Dockerfile` | Path to Dockerfile |
| `build-context` | `.` | Docker build context |
| `build-target` | `` | Multi-stage build target |
| `cache-scope` | `default` | GHA cache scope key (use unique value per image) |
| `cache-backend` | `gha` | Build cache: `gha`, `none`, or `registry`. `registry` cannot be used with IMMUTABLE repositories, pays egress on every build, and is refused with `scan: true` (the cache is written before the gates); see the action's `cache-backend` input |
| `scan` | `false` | `true` scans for CRITICAL CVEs from the local build and pushes THAT image (no rebuild), then attests the pushed digest (provenance + SBOM). Nothing is pushed if a CRITICAL fixable CVE or any secret is found. Needs a single platform, and cannot be combined with `push-by-digest`. The calling job must grant `id-token: write` and `attestations: write` on top of `packages: write` |
| `scan-severity` | `CRITICAL` | Severity that fails the pre-push scan (Trivy syntax, e.g. `HIGH,CRITICAL`); unfixed CVEs are ignored |

| Output | Description |
|---|---|
| `image-uri` | Full `registry/name:tag` URI |
| `image-digest` | The pushed digest (`sha256:...`), the subject of the attestations |

With `scan: true` the caller's job needs:
```yaml
permissions:
  contents: read
  packages: write
  id-token: write        # opens the OIDC token the attestation is signed with
  attestations: write    # writes to the repository's attestation store
```
A reusable workflow's permissions are capped by its caller's, so a product that calls `ghcr-publish.yml` must grant these four on the calling job as well.

---

### `release-retag`
Cut a version without rebuilding. For each candidate service it reads the image's identity tag `sha-<commit>`, gets its digest, verifies that digest's build attestation (`gh attestation verify`, signer `ghcr-publish.yml`), and only after every found image passes does it run `crane tag <image>@<digest> vX.Y.Z` — the tag moves onto the SAME digest. Every service listed must have a `sha-<commit>` tag: a missing one fails the step before any tag is written (no partial release), as does a failed attestation — the release never points at an unverified or missing image. Log in to the registry first.

A failed `crane tag` mid-loop leaves the earlier services tagged with this release; re-running is safe, because an existing tag at the same digest is a no-op and a tag at a different digest is refused.

The reusable workflow is the supported entry point (it installs crane, logs in to GHCR and calls the action):

```yaml
on:
  push:
    tags: ['v*']
jobs:
  retag:
    permissions: { contents: read, packages: write, attestations: read }
    uses: quynhonsemiconductor/ci/.github/workflows/release-retag.yml@<full-sha>
    with:
      product: rova
      release-tag: ${{ github.ref_name }}
      commit: ${{ github.sha }}
```

| Input | Default | Description |
|---|---|---|
| `product` | **required** | Short slug (`rova`, `opshub`, `kb`) |
| `release-tag` | **required** | `vX.Y.Z`; `latest` and `sha-*` are refused |
| `commit` | **required** | Full 40-character sha the release was cut from |
| `services` | `api worker migrator web` | Exactly the services the product ships; a missing one fails the run |

| Output | Description |
|---|---|
| `digests` | JSON map service → digest, the release digest map |
| `services` | Space-separated services that were tagged |

---

### `post-deploy-health-check`
| Input | Default | Description |
|---|---|---|
| `url` | **required** | Full URL to poll (e.g. `https://api.rova.io/v1/health/ready`) |
| `expected-version` | `` | Assert this string is in the response body |
| `timeout-seconds` | `120` | Max poll time |
| `poll-interval-seconds` | `10` | Poll interval |
| `expected-status` | `200` | Expected HTTP status code |

---

### `publish-openapi-spec`
| Input | Default | Description |
|---|---|---|
| `spec-path` | `openapi.json` | Path to the generated spec |
| `artifact-name` | `openapi-spec` | GitHub artifact name |
| `retention-days` | `30` | Artifact retention in days |

| Output | Description |
|---|---|
| `artifact-name` | Uploaded GitHub artifact name |

---

### `validate-openapi-contract`
| Input | Default | Description |
|---|---|---|
| `current-spec-path` | `openapi.json` | Current (PR) spec |
| `base-spec-path` | `base-openapi.json` | Base branch spec to compare against. A missing file is a **skip with a warning** (a first run has no base yet) |
| `fail-on-breaking` | `true` | Fail on ERR-level breaking changes. `true` or `false` only; `false` disables the gate for every PR, prefer `allow-breaking` |
| `allow-breaking` | `false` | Explicit override for ONE intentional break: ERR-level changes pass, but are printed, raised as a warning annotation and written to the job summary. `true` or `false` only |
| `allow-breaking-label` | `allow-breaking-api-change` | PR label with the same effect as `allow-breaking: true`. Empty disables the label |
| `pull-request-labels` | *(the PR's labels)* | JSON array of label names; leave empty. When set it replaces the PR's labels, and the job summary then says the override came from this input, not from the pull request |
| `oasdiff-version` | `v1.22.0` | oasdiff release to download (checksum verified) |
| `format` | `text` | Output format: `text` or `json` |

| Output | Description |
|---|---|
| `breaking-found` | `"true"` if ERR-level breaking changes were detected, even when allowed; `"false"` if there are none or nothing was compared (no base spec); **empty** when oasdiff failed or the input was invalid (unknown) |
| `breaking-allowed` | `"true"` if they were detected and let through by `allow-breaking` or the label |
| `message` | One line: how it ended, or why it failed (`Invalid input: ...`, `oasdiff config found: ...`) |

**What fails it.** ERR-level changes from `oasdiff breaking` (a removed endpoint or success status, a type change...).
WARN-level changes are printed and do not fail. A failure of oasdiff itself (a spec that does not load) **always fails**,
whatever `allow-breaking` and `fail-on-breaking` say. The step passes `--fail-on ERR` *and* counts the ERR-level changes in
oasdiff's JSON report independently; either one says "breaking" and it is breaking. (`oasdiff breaking` exits 0 whatever it
prints unless `--fail-on` is given; this action used to rely on exit 1 and so let opshub#354 pass with "2 changes: 2 error".)

**Letting an intentional break through.** Add the label `allow-breaking-api-change` to the pull request **and push**, or
pass `allow-breaking: 'true'`. The label is read from the event payload of the run, so a label added afterwards is not seen
by re-running an old run (the action then fails, which is the safe direction); push, or trigger the workflow on `labeled`.
The job summary lists every change that was let through under "BREAKING CHANGE ALLOWED". Remove the label once the change has
shipped. If no breaking change is found while the override is set, the action says so; remove it then.

**A committed oasdiff config is refused.** oasdiff 1.22 loads `.oasdiff.*` / `oasdiff.*` from its working directory on its own,
and one such file (`unmatch-path: ".*"`) makes every comparison report nothing. The action passes `--config` with an empty file
to both of its runs, and **fails** while such a file exists in the working directory, the workspace root or the directory of
either spec, so a silenced gate is visible instead of inert. Delete the file (or move the rule into the spec).

Proven by `.github/workflows/validate-openapi-contract-test.yml` (fixtures in `.github/fixtures/validate-openapi-contract`).

---

### `fetch-openapi-base-spec`
Gives `validate-openapi-contract` its baseline: the spec that the base branch's own push run uploaded
(`publish-openapi-spec` with `artifact-name: openapi-spec-<sha>`) for the pull request's base commit.

```yaml
- name: Fetch the base spec
  if: github.event_name == 'pull_request'
  uses: quynhonsemiconductor/ci/actions/fetch-openapi-base-spec@v1.21.0
  with:
    workflow: backend-ci.yml           # the workflow that uploads the specs
- name: Breaking change check
  if: github.event_name == 'pull_request'
  uses: quynhonsemiconductor/ci/actions/validate-openapi-contract@v1.21.0
  with:
    current-spec-path: openapi.json
    base-spec-path: base-spec/openapi.json
```

| Input | Default | Description |
|---|---|---|
| `workflow` | **required** | File name of the workflow that uploads the specs. A name that does not exist is an **error** (404), not "no baseline" |
| `artifact-prefix` | `openapi-spec-` | The artifact is `<prefix><commit sha>` |
| `file` | `openapi.json` | The file the artifact must contain; also what `spec-path` points at |
| `path` | `base-spec` | Directory to download into. Must be absent or an **empty** directory, not a symbolic link, resolving inside the workspace |
| `max-ancestors` | `30` | Commits to try along the **first-parent** chain, the base commit included (1 to 100) |
| `base-ref`, `base-sha` | the PR's | Override for tests or non-`pull_request` events |
| `repository`, `token` | this repo, `github.token` | Where the runs and artifacts live |

| Output | Description |
|---|---|
| `found` | `true` a spec was downloaded; `false` the base branch has no baseline (skip); **empty** the action failed |
| `commit`, `distance` | The commit whose spec was used, and how many **first-parent** steps before the base commit it is (0 = the base commit) |
| `run-id`, `path`, `spec-path`, `message` | The run that uploaded it, the directory, the spec file, and one line saying what happened |

**Decisions.** (1) The base branch has no successful *push* run of the workflow (a stacked PR aimed at another PR's branch, a new
repository): no baseline, `found=false`, the contract check skips with a warning. (2) Otherwise a baseline is **required**: the walk
goes from the base commit along the base branch's first parents, and the first commit that has a spec wins, with a warning naming it
when it is not the base commit itself; none within `max-ancestors` **fails**. (3) A commit has a spec only if a run of *this workflow
file* (`.github/workflows/<workflow>`), triggered by a **push** to the base branch, in this repository (not a fork's run), built
exactly that commit and **succeeded**, and that run uploaded an unexpired artifact named `<prefix><sha>`. Only first-parent commits
are ever looked up, so a commit merged in from a side branch is never a candidate (and does not count toward `distance`). (4) The
download goes into an empty destination and the expected file must be there afterwards, so a spec that a checkout of the pull request
planted at `base-spec/` is never mistaken for the downloaded one.

**Why a fallback at all.** A workflow that cancels in-progress runs per ref leaves some commits without a spec, and a pull request
opened while the merge's own push run is still going has a base commit whose run has not succeeded yet. Without the fallback each is
either a silent skip or a failure that is none of the pull request's doing.

**Limits.** A push `paths:` filter on the uploading workflow leaves every commit it skips without a run, so *more than
`max-ancestors` such commits in a row make every pull request fail here*: raise `max-ancestors` (up to 100), drop the filter, or
upload a spec on every push. Artifacts expire (30 days in the callers), so a long-idle base branch fails the same way, by design.
When the base commit's own run is still going, the comparison is against an earlier commit, so that commit's own API changes appear as
the pull request's; the warning says so. A tag named like the base branch cannot plant a spec: a run counts only for a commit on the
first-parent chain, and a tag push at such a commit built that same commit.

Replaces a `dawidd6/action-download-artifact` step with `continue-on-error`, which skipped the check silently in two ways (a wrong
workflow name was a swallowed 404; and it took the latest *successful* run, which is the previous commit while the merge's own run
is still going). No `fetch-depth: 0` is needed: history is read one commit at a time through the API (`commits/<sha>`, `.parents[0]`).

Proven by `.github/workflows/fetch-openapi-base-spec-test.yml`.

---

### `scan-secrets`
| Input | Default | Description |
|---|---|---|
| `config-path` | `` | Path to `.gitleaks.toml` (optional, uses defaults if empty) |
| `fail-on-leak` | `true` | Fail workflow if secrets detected |
| `scan-depth` | `0` | Commits to scan (0 = full history) |

---

## Fewer jobs per push

Free-plan runners cap at 20 concurrent jobs, and one push to a product used to start about 20. The shared workflows therefore have ONE shape:

| Workflow | Job | Check name |
|---|---|---|
| `security.yml` | Gitleaks + osv-scanner + Semgrep as steps of one job | `Security scans (Gitleaks, osv-scanner, Semgrep)` |
| `actions-security.yml` | actionlint + zizmor as steps of one job | `Workflow security (actionlint, zizmor)` |
| `security.yml` with `scan_container: true` | Trivy, built from scratch (the weekly scan) | `Container CVE scan (Trivy)` |

A product that already builds its image sets `scan_container: ${{ github.event_name == 'schedule' }}` and runs `actions/scan-image` right after that build, so the PR scan costs no extra job or image build while the scheduled scan still catches new CVEs in an unchanged image. A product's PR-title job can call `actions/pr-labels` instead of running the labeler workflow as a second job.

The `combine` input on both workflows is deprecated and ignored (it is still accepted so callers that pass it do not fail at startup).

## Switching the review model

`code-review.yml` reviews with GLM (Z.ai coding endpoint) or Claude (Anthropic API). One organisation variable flips every repository, with no edit to any caller.

1. Set the organisation variable `CODE_REVIEW_PROVIDER` to `glm` (default when unset) or `claude`. Optionally set `CODE_REVIEW_CLAUDE_MODEL` (default `claude-sonnet-5-5`). An unknown provider value fails the run rather than falling back. The caller's `vars` are what the reusable workflow sees, so a repository-level variable of the same name overrides the organisation one for that repository.
2. Each caller picks the matching key with ONE expression, so a repository never holds both keys in a long-lived input:

   ```yaml
   secrets:
     llm_token: ${{ vars.CODE_REVIEW_PROVIDER == 'claude' && secrets.ANTHROPIC_CODE_REVIEW_API_KEY || secrets.Z_AI_CODING_API_KEY }}
   ```

   The organisation secret `ANTHROPIC_CODE_REVIEW_API_KEY` must be visible to the same repositories as `Z_AI_CODING_API_KEY`. If it is missing while the provider is `claude`, the expression falls back to the Z.ai key and the probe reports the rejected key (a failed check that names the cause), never a silent GLM review under a Claude label.
3. The verdict comment on each pull request ends with `reviewer: <provider> / <model>`. Explicit `provider`, `model`, `llm_url` and `use_anthropic_protocol` inputs still override the variable.

Cost: Claude is billed per token on the Anthropic account; GLM is a flat plan. The guard is the monthly spend limit on the CI key in the Anthropic Console, not anything here. A spent limit shows as a probe `config` error.

`llm_reasoning_effort` is sent only on the OpenAI protocol (GLM); under Claude it is dropped, because the review action fails fast on it with the Anthropic protocol.

Re-review after a switch: the review action's checkpoint fingerprint hashes the endpoint, model, protocol, extra body and reasoning effort, so changing provider or model reviews the full range on the next push. To force one anyway, convert the pull request to draft and mark it ready, or re-open it.

## Versioning

Consumers pin a FULL COMMIT SHA and name the release it belongs to in the trailing comment:

```yaml
uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@4ab9d053b565b4fef50da119b0ff675de19217e0 # v1.21.0
```

This repo uses [release-please](https://github.com/googleapis/release-please) to auto-generate tags and `CHANGELOG.md`. Renovate (org preset, `pinDigests`) moves the SHA and the comment together in a reviewed pull request, so a bump is a reviewed diff rather than a ref that moves under the caller. The `# vX.Y.Z` comment is not decoration: `scripts/pin_drift.py` reads the version from it, so a SHA pin without one is invisible to the pin-drift report.

A reusable workflow in this repo pins the actions it calls to the release that LAST CHANGED that action, not to the current release (`ghcr-publish` calls `build-push-image@v1.31.1` and `bump-gitops-tag@v1.32.0` while the repo is on v1.33.0). One rule: a release bumps a self-pin only when it changes that action; a release that does not touch it leaves the pin alone. Reasons: the blast radius of a release stays what changed, and a job cannot pin a SHA that does not exist at the commit introducing it.

**`v1` is FROZEN** (2026-10-21, at v1.22). It does not move on release and will not be moved again; a caller on it runs code from before the on-prem migration, 40+ commits behind `main`. Do not use `v1`, or any other floating tag (`v1.<minor>`), in a workflow or an action — pin a SHA plus its `# vX.Y.Z` comment.

## Adding new actions

1. Create `actions/<action-name>/action.yml`
2. Test from a consuming repo on a branch using `@<branch-name>`
3. Open a PR with a conventional commit message → release-please picks it up
4. Merge to `main` → tag is cut → update consumers to the new tag
