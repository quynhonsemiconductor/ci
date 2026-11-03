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

Two contracts, each guarding a bug that reached main:

```
secret-refs   every secretRef/configMapRef has something that creates it
module-refs   a live stack's `source` resolves — no path out of the repo, and
              every pinned `?ref=` is a tag tf-modules actually has
```

The ECS-era `size`, `services` (IRSA roles) and `remote-state` contracts went
with the stacks they compared; there is no per-product stack left to hold them.

**Adding a contract is adding an entry to `CONTRACTS`.** If a check does not fit
that shape, the shape is probably wrong — and it is certainly not another script.

It replaced `gitops/scripts/check-size-agreement.py` and
`infra/scripts/check_remote_state.py`, which were two ad-hoc tools growing
separately in two repositories, doing the same thing badly, and the retired
`stack_conformance.py`.

## `otel_duplicate_timestamps.py`

Finds the series that are written twice for one timestamp with different values (Grafana Cloud's
`sample_duplicate_timestamp` discards) in the collector's `debug` exporter log. Standard library only. Not a
conformance contract: a diagnostic tool, kept here with its tests so it is usable by any product.
Runbook: [`docs/runbooks/otel-duplicate-timestamps.md`](../docs/runbooks/otel-duplicate-timestamps.md).

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
