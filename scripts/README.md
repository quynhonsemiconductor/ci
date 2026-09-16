# ci/scripts

Estate-wide checks. **The distinction that decides what belongs here:**

```
repo-local tooling      stays in its repo
                        gitops/scripts/render.sh   — renders the chart
                        infra/scripts/measure_*.py — reads one account's metrics

CROSS-REPOSITORY        lives here, because no single repo can host a check that
CONTRACTS               spans several and no repo should try
```

## `platform_conformance.py`

Five contracts, each guarding a bug that reached main:

```
size          §7c — the one fact declared in gitops AND infra
services      chart ServiceAccounts vs product-profile IRSA roles
remote-state  a stack's reads vs the target stack's outputs
secret-refs   every secretRef/configMapRef has something that creates it
module-refs   a live stack's `source` resolves — no path out of the repo, and
              every pinned `?ref=` is a tag tf-modules actually has
```

**Adding a contract is adding an entry to `CONTRACTS`.** If a check does not fit
that shape, the shape is probably wrong — and it is certainly not another script.

It replaced `gitops/scripts/check-size-agreement.py` and
`infra/scripts/check_remote_state.py`, which were two ad-hoc tools growing
separately in two repositories, doing the same thing badly.

## Why these bugs are invisible otherwise

All five found in that review were the same shape: **a reference and its
definition in different files, each individually valid.**

```
terraform validate   passes — remote-state outputs resolve at PLAN time
helm lint            passes — the values satisfy the schema
helm unittest        passes — the template logic is correct
```

Per-concern directories are the right structure, and they are exactly what lets
this hide. The answer is not reorganising folders, it is validating across them.

## `stack_conformance.py`

The predecessor, and §17 retires it with the ECS estate. It compares the three
per-product `infra/modules/stack` copies against each other — a problem that
disappears when there is one chart instead of three modules.

Do not extend it. New checks go in `platform_conformance.py`.
