# ci

Shared GitHub Actions composite actions for all QNSC product repositories (Rova, OpsHub, and future products).

Shared CI/CD logic lives here as versioned composite actions, so bug fixes and improvements propagate automatically to all consumers on the next reference — no copy-paste drift. The examples below use Rova repositories, but the same actions are consumed by OpsHub and any other QNSC product.

---

## Actions

### AWS Auth
| Action | Description |
|---|---|
| [`setup-aws-oidc`](actions/setup-aws-oidc/action.yml) | Configure AWS via GitHub OIDC (no stored keys) + optional ECR login |

### Node / Build
| Action | Description |
|---|---|
| [`setup-node-pnpm`](actions/setup-node-pnpm/action.yml) | Install pnpm, set up Node.js with cache, run `pnpm install` |

### Docker / ECR
| Action | Description |
|---|---|
| [`build-push-ecr`](actions/build-push-ecr/action.yml) | Buildx + ECR build + push (OIDC-based, no stored keys) |
| [`attest-image`](actions/attest-image/action.yml) | GitHub-native SLSA provenance attestation (SOC 2 / supply chain) |

### ECS / Deploy
| Action | Description |
|---|---|
| [`ecs-run-task`](actions/ecs-run-task/action.yml) | Run a one-off Fargate task and wait for its exit code |
| [`run-db-migration`](actions/run-db-migration/action.yml) | Run Drizzle migrations as a gated ECS task (third motion — before traffic flip) |
| [`post-deploy-health-check`](actions/post-deploy-health-check/action.yml) | Poll `/health/ready` until HTTP 200 (optionally assert version) |

### CDN / Frontend
| Action | Description |
|---|---|

### API Contract
| Action | Description |
|---|---|
| [`publish-openapi-spec`](actions/publish-openapi-spec/action.yml) | Upload generated spec as artifact + optionally to S3 for cross-repo codegen |
| [`validate-openapi-contract`](actions/validate-openapi-contract/action.yml) | oasdiff breaking-change detection between two OpenAPI specs |

### Security / Quality
| Action | Description |
|---|---|
| [`scan-secrets`](actions/scan-secrets/action.yml) | Gitleaks secret scan with SARIF upload to GitHub Security tab |
| [`agent-forge-test-guard`](actions/agent-forge-test-guard/action.yml) | Fail a PR that deletes assertions, drops test files or adds dependencies without declaring it |
| [`pr-title-conventional-commits`](actions/pr-title-conventional-commits/action.yml) | Validate a PR title against Conventional Commits — Release Please derives the CHANGELOG from it |
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
      - uses: quynhonsemiconductor/ci/actions/assert-jobs-succeeded@v1
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

The action form keeps the job local, so the check keeps the name `test-guard` and an
existing ruleset needs no change:

```yaml
name: agent-forge test-guard
on:
  pull_request:
    # `edited` is required: approvals are declared in the PR body, so editing the
    # body to add one has to re-run the check.
    types: [opened, synchronize, reopened, edited]
permissions:
  contents: read
jobs:
  test-guard:            # this job id IS the check name — do not rename it
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1  # v7.0.1
        with:
          fetch-depth: 0          # the guard diffs against the merge base
          persist-credentials: false
      - name: capture the pull request body
        env:
          PR_BODY: ${{ github.event.pull_request.body }}
        run: printf '%s' "$PR_BODY" > "${RUNNER_TEMP}/pr-body.txt"
      - uses: quynhonsemiconductor/ci/actions/agent-forge-test-guard@v1
        with:
          base-ref: ${{ github.event.pull_request.base.ref }}
          body-file: ${{ runner.temp }}/pr-body.txt
```

The reusable workflow (`.github/workflows/agent-forge-guard.yml@v1`) is shorter and
carries the checkout and body handling for you. It is the right choice only for a
repository that has **no** existing `test-guard` requirement, and whose ruleset can
name `test-guard / test-guard` from the start.

### Notifications
| Action | Description |
|---|---|
| [`notify-deploy`](actions/notify-deploy/action.yml) | Send deploy lifecycle events to Slack or Discord webhook |

---

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

### IAM roles (provisioned by rova infra)
| Role convention | Used for |
|---|---|
| `rova-<env>-github-deploy` | ECR push, ECS update-service, S3 sync, CloudFront invalidation |
| `rova-<env>-github-readonly` | CI read-only checks |
| `rova-<env>-github-infra` | rova infra only (tofu apply — never from app repos) |

### Job permissions for attestation
Jobs calling `attest-image` need:
```yaml
permissions:
  id-token: write
  attestations: write
  contents: read
```

---

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
```

### Deploy — rova-api (ECS Fargate)

```yaml
permissions:
  id-token: write
  attestations: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    env:
      IMAGE_TAG: sha-${{ github.sha }}
    steps:
      - uses: actions/checkout@v4

      # 1. AWS auth + ECR login
      - uses: quynhonsemiconductor/ci/actions/setup-aws-oidc@main
        id: aws
        with:
          role-arn: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/rova-${{ inputs.environment }}-github-deploy
          region: ${{ vars.AWS_REGION }}
          ecr-login: 'true'

      # 2. Build & push image
      - uses: quynhonsemiconductor/ci/actions/build-push-ecr@main
        id: build
        with:
          ecr-registry: ${{ steps.aws.outputs.ecr-registry }}
          image-name: rova-api
          image-tag: ${{ env.IMAGE_TAG }}
          # No `extra-tags: latest` — a moving tag defeats immutable pins (§11, task 0.8).
          # The immutable `sha-<commit>` / `v<version>` `image-tag` is the only tag pushed.
          build-target: api
          cache-scope: api

      # 3. Attest (SOC 2 / supply-chain evidence)
      - uses: quynhonsemiconductor/ci/actions/attest-image@main
        with:
          image-ref: ${{ steps.build.outputs.image-uri }}

      # 4. Migrate DB (MUST run before new app version goes live)
      - uses: quynhonsemiconductor/ci/actions/run-db-migration@main
        with:
          cluster: ${{ vars.ECS_CLUSTER }}
          task-definition: rova-${{ inputs.environment }}-migrator
          subnet-ids: ${{ vars.PRIVATE_SUBNET_IDS }}
          security-group-ids: ${{ vars.MIGRATOR_SG_ID }}
          region: ${{ vars.AWS_REGION }}
          environment: ${{ inputs.environment }}

      # 5. Flip traffic
      - run: |
          aws ecs update-service \
            --cluster ${{ vars.ECS_CLUSTER }} \
            --service ${{ vars.ECS_API_SERVICE }} \
            --force-new-deployment \
            --region ${{ vars.AWS_REGION }}

      # 6. Verify ECS stabilized — inline, see backend-deploy.yml's "Verify API
      #    deployment" step. `services-stable` plus an image comparison, which also
      #    catches a circuit-breaker rollback.
      - run: |
          AWS_MAX_ATTEMPTS=120 aws ecs wait services-stable \
            --cluster "$ECS_CLUSTER" --services "$ECS_API_SERVICE" --region "$AWS_REGION"

      # 7. Health-check live endpoint
      - uses: quynhonsemiconductor/ci/actions/post-deploy-health-check@main
        with:
          url: https://api.rova.io/v1/health/ready
          expected-version: ${{ env.IMAGE_TAG }}

      # 8. Notify result
      - uses: quynhonsemiconductor/ci/actions/notify-deploy@main
        if: always()
        with:
          webhook-url: ${{ secrets.SLACK_DEPLOY_WEBHOOK }}
          status: ${{ job.status == 'success' && 'success' || 'failure' }}
          service: rova-api
          environment: ${{ inputs.environment }}
          version: ${{ env.IMAGE_TAG }}
          run-url: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

### Deploy — rova-web (S3 + CloudFront)

```yaml
permissions:
  id-token: write
  contents: read

jobs:
  deploy:
    runs-on: ubuntu-latest
    environment: ${{ inputs.environment }}
    steps:
      - uses: actions/checkout@v4

      - uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'

      - uses: quynhonsemiconductor/ci/actions/setup-aws-oidc@main
        with:
          role-arn: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/rova-${{ inputs.environment }}-github-deploy
          region: ${{ vars.AWS_REGION }}

      - run: pnpm build

      - run: |
          aws s3 sync dist/ s3://rova-${{ inputs.environment }}-web \
            --delete --region ${{ vars.AWS_REGION }}

      - uses: quynhonsemiconductor/ci/actions/post-deploy-health-check@main
        with:
          url: https://app.rova.io

      - uses: quynhonsemiconductor/ci/actions/notify-deploy@main
        if: always()
        with:
          webhook-url: ${{ secrets.SLACK_DEPLOY_WEBHOOK }}
          status: ${{ job.status == 'success' && 'success' || 'failure' }}
          service: rova-web
          environment: ${{ inputs.environment }}
          version: ${{ github.sha }}
          run-url: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
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

### `setup-aws-oidc`
| Input | Default | Description |
|---|---|---|
| `role-arn` | **required** | IAM role ARN to assume via OIDC |
| `region` | **required** | AWS region |
| `ecr-login` | `false` | Also authenticate to ECR |
| `session-duration` | `3600` | Role session duration in seconds |
| `mask-aws-account-id` | `true` | Mask account ID in logs |

| Output | Description |
|---|---|
| `ecr-registry` | ECR registry URL (only when `ecr-login: true`) |
| `aws-account-id` | The assumed-role AWS account ID |

---

### `setup-node-pnpm`
| Input | Default | Description |
|---|---|---|
| `node-version` | `22` | Node.js version |
| `pnpm-version` | `10.10.0` | pnpm version |
| `install-deps` | `true` | Run `pnpm install --frozen-lockfile` |
| `working-directory` | `.` | Working directory |

---

### `build-push-ecr`
Call `setup-aws-oidc` with `ecr-login: true` first.

| Input | Default | Description |
|---|---|---|
| `ecr-registry` | **required** | ECR registry URL (`steps.aws.outputs.ecr-registry`) |
| `image-name` | **required** | ECR repository name (e.g. `rova-api`) |
| `image-tag` | **required** | Primary tag (e.g. `sha-abc1234`) |
| `extra-tags` | `` | Newline-separated additional tags |
| `dockerfile` | `Dockerfile` | Path to Dockerfile |
| `build-context` | `.` | Docker build context |
| `build-target` | `` | Multi-stage build target |
| `cache-scope` | `default` | GHA cache scope key (use unique value per image) |

| Output | Description |
|---|---|
| `image-uri` | Full `registry/name:tag` URI |

---

### `attest-image`
Job needs `permissions: attestations: write, id-token: write`.

| Input | Default | Description |
|---|---|---|
| `image-ref` | **required** | Full image ref with digest (`registry/name@sha256:…`) |
| `push-to-registry` | `true` | Store attestation as OCI artefact |
| `github-token` | `${{ github.token }}` | Token with `attestations: write` |

Verify later with (attestations are signed by this reusable workflow — the
trusted builder — so pin the signer identity, not just the source repo):

```bash
gh attestation verify oci://registry/name@sha256:… \
  --repo <owner>/<consumer-repo> \
  --signer-workflow <owner>/ci/.github/workflows/backend-deploy.yml
```

---

### `ecs-run-task`
| Input | Default | Description |
|---|---|---|
| `cluster` | **required** | ECS cluster name |
| `task-definition` | **required** | Task definition name or ARN |
| `container-name` | **required** | Container whose exit code is checked |
| `subnet-ids` | **required** | Comma-separated private subnet IDs |
| `security-group-ids` | **required** | Comma-separated security group IDs |
| `region` | **required** | AWS region |
| `command-override` | `` | JSON array override (e.g. `["pnpm","seed"]`) |
| `timeout-seconds` | `900` | Max wait seconds |
| `poll-interval-seconds` | `15` | Poll interval seconds |
| `launch-type` | `FARGATE` | ECS launch type |

| Output | Description |
|---|---|
| `task-arn` | ARN of the task |
| `exit-code` | Container exit code (0 = success) |

---

### `run-db-migration`
Wrapper around `ecs-run-task` for the Drizzle migration "third motion". Fails fast if migrations fail, blocking the deploy.

| Input | Default | Description |
|---|---|---|
| `cluster` | **required** | ECS cluster |
| `task-definition` | **required** | Migrator task definition name |
| `container-name` | `migrator` | Container name inside the task def |
| `subnet-ids` | **required** | Private subnets that can reach RDS:5432 |
| `security-group-ids` | **required** | SGs allowing outbound to RDS |
| `region` | **required** | AWS region |
| `environment` | `unknown` | Label for log messages |
| `timeout-seconds` | `600` | Max wait seconds |

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
| `s3-upload` | `false` | Also upload to S3 |
| `s3-bucket` | `` | S3 bucket (required when `s3-upload: true`) |
| `s3-environment` | `develop` | Env label for the S3 key path |
| `region` | `ap-southeast-1` | AWS region (for S3) |

| Output | Description |
|---|---|
| `artifact-name` | Uploaded GitHub artifact name |
| `s3-key` | S3 key of the immutable copy (when `s3-upload: true`) |

S3 key convention:
- `openapi/{env}/{git-sha}/openapi.json` — immutable per-build copy
- `openapi/{env}/latest/openapi.json` — mutable latest pointer (for FE codegen)

---

### `validate-openapi-contract`
| Input | Default | Description |
|---|---|---|
| `current-spec-path` | `openapi.json` | Current (PR) spec |
| `base-spec-path` | `base-openapi.json` | Base branch spec to compare against |
| `fail-on-breaking` | `true` | Fail on ERR-level breaking changes |
| `oasdiff-version` | `v1.10.24` | oasdiff release to download |
| `format` | `text` | Output format: `text` or `json` |

| Output | Description |
|---|---|
| `breaking-found` | `"true"` if ERR-level breaking changes detected |

---

### `scan-secrets`
| Input | Default | Description |
|---|---|---|
| `config-path` | `` | Path to `.gitleaks.toml` (optional, uses defaults if empty) |
| `fail-on-leak` | `true` | Fail workflow if secrets detected |
| `scan-depth` | `0` | Commits to scan (0 = full history) |

---

### `notify-deploy`
Auto-detects Slack vs Discord by webhook URL pattern.

| Input | Default | Description |
|---|---|---|
| `webhook-url` | **required** | Slack or Discord incoming webhook |
| `status` | **required** | `started` \| `success` \| `failure` \| `rollback` |
| `service` | **required** | Service name (e.g. `rova-api`) |
| `environment` | **required** | Target environment |
| `version` | `` | Image tag or semver |
| `run-url` | auto | Link to the GitHub Actions run |

---

## Versioning

Pin to a release tag for production stability:
```yaml
# Production — pin to a tag
uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@v1

# Dev / fast iteration
uses: quynhonsemiconductor/ci/actions/setup-node-pnpm@main
```

This repo uses [release-please](https://github.com/googleapis/release-please) to auto-generate tags and `CHANGELOG.md`. Consuming repos should pin to `@v1` or `@v1.2.0` in production workflows.

## Adding new actions

1. Create `actions/<action-name>/action.yml`
2. Test from a consuming repo on a branch using `@<branch-name>`
3. Open a PR with a conventional commit message → release-please picks it up
4. Merge to `main` → tag is cut → update consumers to the new tag
