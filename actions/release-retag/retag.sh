#!/usr/bin/env bash
# Add release-tag to the images already published for one commit, after verifying each digest's attestation.
#
# Called by action.yml with every value in the environment. Anything that consumes an input runs it as a
# variable, never as text (zizmor's template-injection rule, and the same rule bump-gitops-tag documents).
set -euo pipefail

PRODUCT="${PRODUCT:?product is required}"
RELEASE_TAG="${RELEASE_TAG:?release-tag is required}"
COMMIT="${COMMIT:?commit is required}"
REGISTRY_NAMESPACE="${REGISTRY_NAMESPACE:-ghcr.io/quynhonsemiconductor}"
SERVICES="${SERVICES:-api worker migrator web}"
SOURCE_REPOSITORY="${SOURCE_REPOSITORY:?source-repository is required}"
SIGNER_WORKFLOW="${SIGNER_WORKFLOW:?signer-workflow is required}"
GH_TOKEN="${GH_TOKEN:?github-token is required}"
export GH_TOKEN

# §11: the release tag is the only mutable-looking ref this action writes; it must be a real version tag.
if [[ ! "$RELEASE_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error title=release-retag::refusing '$RELEASE_TAG'; expected a release tag vX.Y.Z"
  exit 1
fi
if [[ ! "$COMMIT" =~ ^[0-9a-f]{40}$ ]]; then
  echo "::error title=release-retag::commit must be the full 40-character sha"
  exit 1
fi
if [[ ! "$PRODUCT" =~ ^[a-z0-9-]+$ ]]; then
  echo "::error title=release-retag::product must be a slug like rova, not '$PRODUCT'"
  exit 1
fi

# Pinned crane. Installed INSIDE this step (never via $GITHUB_PATH, which zizmor
# flags as a code-execution sink); a caller that already has crane uses it.
if ! command -v crane >/dev/null 2>&1; then
  GOBIN="${RUNNER_TEMP:-/tmp}/crane-bin" go install "github.com/google/go-containerregistry/cmd/crane@v0.20.6"
  export PATH="$GOBIN:$PATH"
fi

# Resolve a tag to its digest, distinguishing "this tag does not exist" from every
# other failure. An expired token, a 5xx or a rate limit must never look like "the
# image was not published" — that would silently drop a service from the release.
#
# RETURN CODES, not stdout, and never `exit` inside the function: every call site
# runs it in an `if`, and an `exit` would only kill the condition's subshell while
# the caller read status 1 as "missing". The digest is set in REF_DIGEST.
#   0 — found (REF_DIGEST has it)
#   1 — tag does not exist (MANIFEST_UNKNOWN / NAME_UNKNOWN)
#   2 — any other error (auth, network, 5xx); the caller must fail the run
REF_DIGEST=""
ref_digest() {
  local ref="$1" err out rc
  err=$(mktemp)
  if out=$(crane digest "$ref" 2>"$err"); then
    REF_DIGEST="$out"
    rm -f "$err"
    return 0
  else
    rc=$?
  fi
  # Match the registry's own codes, never a bare "404": a sha or a URL can
  # contain those digits, and a misread turns an error into a false "missing".
  if grep -qE 'MANIFEST_UNKNOWN|NAME_UNKNOWN' "$err"; then
    rm -f "$err"
    return 1
  fi
  echo "::error title=release-retag::could not read ${ref} (status ${rc}): not a missing manifest (auth, network or registry error)." >&2
  sed 's/^/  /' "$err" >&2
  rm -f "$err"
  return 2
}

short="${COMMIT:0:12}"
identity="sha-${short}"

# ── Find, verify, and check the release tag — THEN tag ──────────────────────
# Nothing gets a release tag until every image was found, attested, and has no
# conflicting existing vX.Y.Z. That includes the refusal: a partial release
# where api moved and worker was refused must be impossible.
found=()
tag_needed=""
digests='{}'
for svc in $SERVICES; do
  image="${REGISTRY_NAMESPACE}/${PRODUCT}-${svc}"
  if ref_digest "${image}:${identity}"; then
    digest="$REF_DIGEST"
  else
    rc=$?
    [ "$rc" -eq 2 ] && exit 1
    echo "release-retag: ${image}:${identity} not published for this commit — skipped"
    continue
  fi
  if [[ ! "$digest" =~ ^sha256:[0-9a-f]{64}$ ]]; then
    echo "::error title=release-retag::${image}:${identity} returned a bad digest '$digest'"
    exit 1
  fi
  if ! gh attestation verify "oci://${image}@${digest}" \
    --repo "$SOURCE_REPOSITORY" \
    --signer-workflow "$SIGNER_WORKFLOW" \
    --source-digest "$COMMIT" \
    --source-ref refs/heads/main >/dev/null; then
    echo "::error title=release-retag::no valid build attestation for ${image}@${digest} (signer ${SIGNER_WORKFLOW}, commit ${COMMIT}). Refusing to release an image this pipeline did not build from main."
    exit 1
  fi
  # Never move a release tag that already points somewhere else. Same digest is a
  # no-op. Checked HERE, before the first tag, so a refusal cannot leave a partial release.
  needs_tag=true
  if ref_digest "${image}:${RELEASE_TAG}"; then
    if [ "$REF_DIGEST" != "$digest" ]; then
      echo "::error title=release-retag::${image}:${RELEASE_TAG} already points at ${REF_DIGEST}, not ${digest}. Refusing to move a published release tag."
      exit 1
    fi
    echo "release-retag: ${image}:${RELEASE_TAG} already at ${digest} — unchanged"
    needs_tag=false
  else
    rc=$?
    [ "$rc" -eq 2 ] && exit 1
  fi
  found+=("$svc")
  [ "$needs_tag" = true ] && tag_needed="${tag_needed} ${svc}"
  digests=$(jq -c --arg s "$svc" --arg d "$digest" '. + {($s): $d}' <<<"$digests")
done

if [ "${#found[@]}" -eq 0 ]; then
  echo "::error title=release-retag::no ${PRODUCT}-<service> image carries ${identity}. Publish ran for this commit? Looked for: ${SERVICES}"
  exit 1
fi

for svc in $tag_needed; do
  image="${REGISTRY_NAMESPACE}/${PRODUCT}-${svc}"
  digest=$(jq -er --arg s "$svc" '.[$s]' <<<"$digests")
  # crane tag moves the reference onto the SAME digest: no pull, no push of layers, no rebuild.
  crane tag "${image}@${digest}" "$RELEASE_TAG"
  echo "release-retag: ${image}@${digest} -> ${RELEASE_TAG}"
done

{
  echo "digests=${digests}"
  echo "services=${found[*]}"
} >>"${GITHUB_OUTPUT:?GITHUB_OUTPUT is required}"
