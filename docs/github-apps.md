# GitHub Apps in the `quynhonsemiconductor` organisation

The register of every GitHub App installed in the org: what it is for, what it may do, where it is
installed, which credential it uses, and who owns it. **Update this file in the same change that
adds, removes or re-scopes an App.**

## Rules

1. **One App per purpose and trust level.** Workflows that run on `pull_request` (any branch pusher
   controls them) only ever hold a **read-only** App key. Write-capable keys are used only by
   workflows that run on `push` to `main`, `schedule` or `workflow_dispatch`.
2. **Install on selected repositories only**, never "All repositories" — except Renovate. Exceptions still open are marked in the register.
   No App that sends code to a hosted model, or that can write, is installed on an NDA repository.
3. **Org secrets holding App private keys use visibility `selected`**, listing only the repositories
   whose workflows mint a token. Never `all` (that includes public repositories).
4. **Every token is minted per job and down-scoped** with `actions/create-github-app-token`:
   `repositories:` (only the repositories the job touches) **and** `permission-*:` (only the
   permissions the job uses). Checkouts use `persist-credentials: false`.
5. **No personal access tokens** in workflows.
6. **Rotate** every private key at least yearly, and immediately after a scope change that removes
   access from anyone: generate the new key, update the org secret, delete the old key.

## Register

| App | Purpose | Permissions | Installed on | Credential (org) | Used by | Owner |
|---|---|---|---|---|---|---|
| `qnsc-automation` | **Write bot.** Release Please (release PRs, tags, Releases); infra-apply writes environment variables (AWS era — removed with the AWS wind-down) | contents: write · pull_requests: write · actions_variables: write (remove after AWS wind-down) · metadata: read | Selected: app-platform, mcp-tools, opshub, qnsc-kb-backend, qnsc-kb-frontend, qnsc-landing, rova, tf-modules | `QNSC_AUTOMATION_APP_ID` (variable) · `QNSC_AUTOMATION_PRIVATE_KEY` (secret, selected: the same eight repositories) | Only `push` to main / `workflow_dispatch`: `release-please.yml` (through the `ci` reusable) in the eight repositories; `infra-apply.yml` in rova, opshub, qnsc-kb-backend (writes kb-frontend variables too). **No pull-request workflow** | platform-infra |
| `qnsc-repo-reader` | **Read bot.** Cross-repository reads from pull-request and scheduled workflows: tf-modules for OpenTofu, platform conformance, app-platform consumer CI | contents: read · metadata: read | Selected: tf-modules, gitops, infra, rova, opshub | `QNSC_REPO_READER_APP_ID` · `QNSC_REPO_READER_PRIVATE_KEY` (both selected: ci, infra, 9router-pool, rova, opshub, qnsc-kb-backend, app-platform) | `infra-plan.yml` (ci reusable; callers rova, opshub, qnsc-kb-backend, 9router-pool), infra `infra-plan.yml` and `drift-detection.yml`, ci `platform-conformance.yml`, 9router-pool `infra-apply.yml`, app-platform consumer CI | platform-infra |
| `qnsc-code-review` | Identity for the LLM code-review comments | contents: read · pull_requests: write · metadata: read | Selected: rova, opshub, mcp-tools (the callers of `code-review.yml`). Never NDA repositories | `CODE_REVIEW_APP_ID` · `app_private_key` (passed by callers) | `code-review.yml` | platform-infra |
| `qnsc-agent-force` | Coding agents open branches and pull requests | contents: write · pull_requests: write · checks: read · statuses: read · metadata: read | **All repositories — accepted for now (owner decision 2026-10-09).** Target: selected, never `VLSIT_RTL_Generator_AI_Model` or `ceo-suite` | held by the agent-forge runtime | agent-forge | platform-infra |
| `rova-scm-prod` | rova (production) links commits and pull requests to work items | contents: read · pull_requests: read · metadata: read | All repositories — accepted for now (read-only). Target: repositories linked to rova projects | rova production secrets | rova | rova team |
| `rova-scm-dev` | Same, for rova's dev environment | contents: read · pull_requests: read · metadata: read | All repositories — accepted for now (read-only). Target: one or two test repositories | rova dev secrets | rova (dev) | rova team |
| `renovate` | Dependency update pull requests (Mend-hosted) | as granted by Renovate | All repositories (standard for Renovate) | — | Renovate | platform-infra |

## Change log

| Date | Change |
|---|---|
| 2026-10-10 | solodesk retired and its repository archived: removed from the `qnsc-repo-reader` and `qnsc-automation` installations, and from app-platform consumer CI |
| 2026-10-09 | `qnsc-automation` installation and key moved to the same eight repositories (infra, 9router-pool and ci no longer use it). `qnsc-code-review` installation moved to selected. `qnsc-agent-force`, `rova-scm-prod` and `rova-scm-dev` stay on all repositories for now — open risk, see the register |
| 2026-10-09 | Every infra-plan caller (rova, opshub, qnsc-kb-backend, 9router-pool) and infra's own workflows read tf-modules with `qnsc-repo-reader`; the deprecated `qnsc-automation` fallback is removed from `infra-plan`. No pull-request workflow holds a write-capable key any more |
| 2026-10-09 | `qnsc-automation` private key rotated; its secret moved to selected (11 repositories). `qnsc-repo-reader` created (contents: read) and installed on selected repositories. `platform-conformance` moved to it; `infra-plan` prefers it, with the `qnsc-automation` key as a deprecated fallback until every caller switches |
| 2026-10-09 | Register created. Release Please, infra-plan and platform-conformance tokens down-scoped to named repositories and permissions. Planned: `QNSC_AUTOMATION_PRIVATE_KEY` → selected + key rotation; create `qnsc-repo-reader`; move installations to selected repositories |
