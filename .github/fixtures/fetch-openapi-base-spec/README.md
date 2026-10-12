Fixtures for `.github/workflows/fetch-openapi-base-spec-test.yml`, served by the stand-in `bin/gh`. One directory per case:

| File | Answers |
|---|---|
| `commits.json` | `GET repos/<r>/commits/<sha>`: a list of `{sha, parents:[{sha}...]}`, the history graph |
| `runs.<branch>.json` | the "is there any successful push run on this branch" query (no `head_sha`) |
| `runs/<sha>.json` | the same query for one commit (`head_sha=<sha>`); absent = no run |
| `run-artifacts/<run id>.json` | `GET repos/<r>/actions/runs/<id>/artifacts` |
| `download/openapi-spec-<sha>/` | what `gh run download -n openapi-spec-<sha>` would extract; each `openapi.json` carries `"x-commit": "<sha>"` so a test can tell which commit's spec it got |

Commits are `c0`..`c4` repeated 20 times (a 40-hex sha); `c0` is the base commit. The default graph is linear:
`c0 <- c1 <- c2 <- c3 <- c4`. The `merge-*` cases use a merge: `c0` has first parent `c1` and second parent `c2`,
`c1 -> c3 -> c4`, `c2 -> c3`; so the first-parent chain is `c0, c1, c3, c4` and `c2` is a side-branch commit.
Shapes (`workflow_run`-like fields of a run: `id, path, head_branch, head_sha, event, conclusion, head_repository.id,
repository.id`; artifacts: `id, name, expired`) were read from the live API.
