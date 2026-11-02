# `bump-gitops-tag`

Point one service at a new image by editing `gitops/values/<product>/<env>.yaml`.

**This is the entire deploy mechanism** (§11). A product repository never touches
a cluster — no kubectl, no cluster credentials, no cluster access at all. It
builds an image and edits one line in another repository. ArgoCD reconciles from
there.

```yaml
- uses: quynhonsemiconductor/ci/actions/bump-gitops-tag@v1.22.0
  with:
    product: rova
    env: dev
    services: "api worker migrator"
    tag: sha-a3f9c2e01b2c
    mode: commit                 # dev. `pull-request` for prod.
    gitops-token: ${{ secrets.GITOPS_TOKEN }}
```

## Pin by digest

Pass `digests` (the `digests` output of `ghcr-publish.yml`, a JSON map of service to
`sha256:<64 hex>`) and each service also gets `image.digest`. The chart pins the
digest and ignores the tag, so a rewritten tag cannot change what runs; the tag stays
in the file for people to read. Every service in `services` needs an entry, else the
action fails before writing anything wrong. A bump **without** `digests` removes any `image.digest` it finds, so a tag-only
promotion or rollback can never keep running an older pinned image.

```yaml
    tag: sha-a3f9c2e01b2c
    digests: ${{ needs.publish.outputs.digests }}
```

## Dev as a PR with auto-merge

`mode: pull-request` also works for `env: dev`: it opens `bump/<product>-dev-<tag>` with a
`chore(<product>): dev -> <tag>` title (prod keeps `promote/...`). Add `auto-merge: 'true'` to
enable squash auto-merge; gitops's branch rules still apply, auto-merge only removes the click.

## Two modes, and the difference is the whole of §11

```
commit          dev.  Merge to main → the tag moves → ArgoCD syncs. No review.
pull-request    prod. Opens a PR. A human approves. THEN ArgoCD syncs.
```

Before that split existed, *"a version tag applied whatever `main` contained,
which is why rova production ran code from before 7 September while `main` was 44
commits ahead — and why an alerting fix could not reach production without
shipping nine features."*

## Scope the token

**§10b — the identity that bumps dev must NOT be able to write `prod.yaml`.** A
token that can bypass the promotion review makes branch protection on `gitops`
decorative, and the CI identity has no reason to hold one.

## What it refuses

```
tag: latest             `latest` is how a develop build reached a production task
                        definition (qnsc-kb-backend/infra/live/prod/main.tf:104).
                        The chart's schema rejects it too; failing here means the
                        image is never even referenced
env: production         §7c — dev | prod, never develop/production
a missing values file   a product with no <env>.yaml has no Application for that
                        environment. §5c: "Absence is the mechanism."
```

It also reports `changed=false` rather than committing a no-op. **A re-run is not
a deploy**, and a stream of empty commits makes the promotion diff unreadable.

## Concurrency

The caller sets `concurrency.group` per product. Two concurrent bumps race on the
same file and the loser silently reverts the winner; the push here retries with
`--rebase` three times, but the group is what actually prevents it.
