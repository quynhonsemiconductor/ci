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

short="${COMMIT:0:12}"
identity="sha-${short}"

# ── Find, then verify, THEN tag ─────────────────────────────────────────────
# Nothing gets a release tag until every image that has one was found and
# attested. A tag written before a later image fails its check would make the
# release look complete while one digest is unverified.
found=()
digests='{}'
for svc in $SERVICES; do
  image="${REGISTRY_NAMESPACE}/${PRODUCT}-${svc}"
  if ! digest=$(crane digest "${image}:${identity}" 2>/dev/null); then
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
    --source-digest "$COMMIT" >/dev/null; then
    echo "::error title=release-retag::no valid build attestation for ${image}@${digest} (signer ${SIGNER_WORKFLOW}, commit ${COMMIT}). Refusing to release an image this pipeline did not build."
    exit 1
  fi
  found+=("$svc")
  digests=$(jq -c --arg s "$svc" --arg d "$digest" '. + {($s): $d}' <<<"$digests")
done

if [ "${#found[@]}" -eq 0 ]; then
  echo "::error title=release-retag::no ${PRODUCT}-<service> image carries ${identity}. Publish ran for this commit? Looked for: ${SERVICES}"
  exit 1
fi

for svc in "${found[@]}"; do
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
