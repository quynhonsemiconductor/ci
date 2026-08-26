# qnsc-ci

Shared GitHub Actions composite actions for all QNSC product repositories (Rally, OpsHub, and future products).

Shared CI/CD logic lives here as versioned composite actions, so bug fixes and improvements propagate automatically to all consumers on the next reference — no copy-paste drift. The examples below use Rally repositories, but the same actions are consumed by OpsHub and any other QNSC product.

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
| [`ecr-cleanup`](actions/ecr-cleanup/action.yml) | Delete old ECR images per repo (keep-N, protect semver tags) |
| [`attest-image`](actions/attest-image/action.yml) | GitHub-native SLSA provenance attestation (SOC 2 / supply chain) |

### ECS / Deploy
| Action | Description |
|---|---|
| [`ecs-run-task`](actions/ecs-run-task/action.yml) | Run a one-off Fargate task and wait for its exit code |
| [`run-db-migration`](actions/run-db-migration/action.yml) | Run Drizzle migrations as a gated ECS task (third motion — before traffic flip) |
| [`verify-ecs-deploy`](actions/verify-ecs-deploy/action.yml) | Poll ECS service until the expected image tag is running |
| [`post-deploy-health-check`](actions/post-deploy-health-check/action.yml) | Poll `/health/ready` until HTTP 200 (optionally assert version) |

### CDN / Frontend
| Action | Description |
|---|---|
| [`cloudfront-invalidate`](actions/cloudfront-invalidate/action.yml) | Create a CloudFront invalidation + optional wait for completion |

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

**Use the ACTION, not the reusable workflow, if `test-guard` is already a required
check.** A job that calls a reusable workflow reports as `<caller job>/<called
job>` — the security suite in this repo shows up as `security / SAST (Semgrep)` for
exactly this reason. So the reusable form reports **`test-guard / test-guard`**, and
a ruleset requiring `test-guard` matches nothing. A required check that never
reports does not fail: it blocks every merge, indefinitely, showing as "Expected"
in the protection UI.

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
      - uses: QNSC-VN/qnsc-ci/actions/agent-forge-test-guard@v1
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
ECS_CLUSTER                 # e.g. rally-develop
ECS_API_SERVICE             # e.g. rally-develop-api
ECS_WORKER_SERVICE          # e.g. rally-develop-worker
CLOUDFRONT_DISTRIBUTION_ID  # rally-web only
PRIVATE_SUBNET_IDS          # comma-separated private subnet IDs
MIGRATOR_SG_ID              # security group ID for migrator tasks
```

### IAM roles (provisioned by rally-infra)
| Role convention | Used for |
|---|---|
| `rally-<env>-github-deploy` | ECR push, ECS update-service, S3 sync, CloudFront invalidation |
| `rally-<env>-github-readonly` | CI read-only checks |
| `rally-<env>-github-infra` | rally-infra only (tofu apply — never from app repos) |

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
      - uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm lint && pnpm typecheck

  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm test:ci

  openapi:                          # rally-api only
    needs: [quality, test]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'
      - run: pnpm build:openapi      # generates openapi.json
      - uses: QNSC-VN/qnsc-ci/actions/publish-openapi-spec@main
        with:
          artifact-name: openapi-spec-${{ github.sha }}
      - uses: actions/download-artifact@v4
        with:
          name: openapi-spec-base    # uploaded by base-branch CI
          path: base-spec/
        continue-on-error: true      # graceful on first run / new branch
      - uses: QNSC-VN/qnsc-ci/actions/validate-openapi-contract@main
        with:
          current-spec-path: openapi.json
          base-spec-path: base-spec/openapi.json
```

### Deploy — rally-api (ECS Fargate)

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
      - uses: QNSC-VN/qnsc-ci/actions/setup-aws-oidc@main
        id: aws
        with:
          role-arn: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/rally-${{ inputs.environment }}-github-deploy
          region: ${{ vars.AWS_REGION }}
          ecr-login: 'true'

      # 2. Build & push image
      - uses: QNSC-VN/qnsc-ci/actions/build-push-ecr@main
        id: build
        with:
          ecr-registry: ${{ steps.aws.outputs.ecr-registry }}
          image-name: rally-api
          image-tag: ${{ env.IMAGE_TAG }}
          extra-tags: latest
          build-target: api
          cache-scope: api

      # 3. Attest (SOC 2 / supply-chain evidence)
      - uses: QNSC-VN/qnsc-ci/actions/attest-image@main
        with:
          image-ref: ${{ steps.build.outputs.image-uri }}

      # 4. Migrate DB (MUST run before new app version goes live)
      - uses: QNSC-VN/qnsc-ci/actions/run-db-migration@main
        with:
          cluster: ${{ vars.ECS_CLUSTER }}
          task-definition: rally-${{ inputs.environment }}-migrator
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

      # 6. Verify ECS stabilized
      - uses: QNSC-VN/qnsc-ci/actions/verify-ecs-deploy@main
        with:
          cluster: ${{ vars.ECS_CLUSTER }}
          service: ${{ vars.ECS_API_SERVICE }}
          image-tag: ${{ env.IMAGE_TAG }}
          region: ${{ vars.AWS_REGION }}

      # 7. Health-check live endpoint
      - uses: QNSC-VN/qnsc-ci/actions/post-deploy-health-check@main
        with:
          url: https://api.rally.io/v1/health/ready
          expected-version: ${{ env.IMAGE_TAG }}

      # 8. Notify result
      - uses: QNSC-VN/qnsc-ci/actions/notify-deploy@main
        if: always()
        with:
          webhook-url: ${{ secrets.SLACK_DEPLOY_WEBHOOK }}
          status: ${{ job.status == 'success' && 'success' || 'failure' }}
          service: rally-api
          environment: ${{ inputs.environment }}
          version: ${{ env.IMAGE_TAG }}
          run-url: ${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}
```

### Deploy — rally-web (S3 + CloudFront)

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

      - uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@main
        with:
          node-version: '22'
          pnpm-version: '10.10.0'

      - uses: QNSC-VN/qnsc-ci/actions/setup-aws-oidc@main
        with:
          role-arn: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/rally-${{ inputs.environment }}-github-deploy
          region: ${{ vars.AWS_REGION }}

      - run: pnpm build

      - run: |
          aws s3 sync dist/ s3://rally-${{ inputs.environment }}-web \
            --delete --region ${{ vars.AWS_REGION }}

      - uses: QNSC-VN/qnsc-ci/actions/cloudfront-invalidate@main
        with:
          distribution-id: ${{ vars.CLOUDFRONT_DISTRIBUTION_ID }}
          region: ${{ vars.AWS_REGION }}

      - uses: QNSC-VN/qnsc-ci/actions/post-deploy-health-check@main
        with:
          url: https://app.rally.io

      - uses: QNSC-VN/qnsc-ci/actions/notify-deploy@main
        if: always()
        with:
          webhook-url: ${{ secrets.SLACK_DEPLOY_WEBHOOK }}
          status: ${{ job.status == 'success' && 'success' || 'failure' }}
          service: rally-web
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
      - uses: QNSC-VN/qnsc-ci/actions/scan-secrets@main

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

### ECR cleanup (weekly cron)

```yaml
jobs:
  cleanup:
    runs-on: ubuntu-latest
    steps:
      - uses: QNSC-VN/qnsc-ci/actions/setup-aws-oidc@main
        with:
          role-arn: arn:aws:iam::${{ secrets.AWS_ACCOUNT_ID }}:role/rally-develop-github-deploy
          region: ${{ vars.AWS_REGION }}
      - uses: QNSC-VN/qnsc-ci/actions/ecr-cleanup@main
        with:
          repositories: |
            rally-api
            rally-worker
            rally-migrator
          keep-count: '20'
          region: ${{ vars.AWS_REGION }}
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
| `image-name` | **required** | ECR repository name (e.g. `rally-api`) |
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
  --signer-workflow <owner>/qnsc-ci/.github/workflows/backend-deploy.yml
```

---

### `ecr-cleanup`
| Input | Default | Description |
|---|---|---|
| `repositories` | **required** | Newline-separated ECR repo names |
| `keep-count` | `20` | Most-recent images to keep per repo |
| `protected-tag-pattern` | `^v[0-9]+\.[0-9]+\.[0-9]+$` | Tags matching this regex are never deleted |
| `region` | **required** | AWS region |
| `dry-run` | `false` | Print without deleting |

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

### `verify-ecs-deploy`
| Input | Default | Description |
|---|---|---|
| `cluster` | **required** | ECS cluster |
| `service` | **required** | ECS service name |
| `image-tag` | **required** | Expected image tag now running |
| `region` | **required** | AWS region |
| `timeout-seconds` | `600` | Max wait seconds |
| `poll-interval-seconds` | `15` | Poll interval seconds |

---

### `post-deploy-health-check`
| Input | Default | Description |
|---|---|---|
| `url` | **required** | Full URL to poll (e.g. `https://api.rally.io/v1/health/ready`) |
| `expected-version` | `` | Assert this string is in the response body |
| `timeout-seconds` | `120` | Max poll time |
| `poll-interval-seconds` | `10` | Poll interval |
| `expected-status` | `200` | Expected HTTP status code |

---

### `cloudfront-invalidate`
| Input | Default | Description |
|---|---|---|
| `distribution-id` | **required** | CloudFront distribution ID |
| `paths` | `/*` | Space-separated paths to invalidate |
| `region` | `us-east-1` | AWS region |
| `wait` | `false` | Wait for invalidation to reach `Completed` |

| Output | Description |
|---|---|
| `invalidation-id` | CloudFront invalidation ID |

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
| `service` | **required** | Service name (e.g. `rally-api`) |
| `environment` | **required** | Target environment |
| `version` | `` | Image tag or semver |
| `run-url` | auto | Link to the GitHub Actions run |

---

## Versioning

Pin to a release tag for production stability:
```yaml
# Production — pin to a tag
uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@v1

# Dev / fast iteration
uses: QNSC-VN/qnsc-ci/actions/setup-node-pnpm@main
```

This repo uses [release-please](https://github.com/googleapis/release-please) to auto-generate tags and `CHANGELOG.md`. Consuming repos should pin to `@v1` or `@v1.2.0` in production workflows.

## Adding new actions

1. Create `actions/<action-name>/action.yml`
2. Test from a consuming repo on a branch using `@<branch-name>`
3. Open a PR with a conventional commit message → release-please picks it up
4. Merge to `main` → tag is cut → update consumers to the new tag
