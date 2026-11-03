#!/usr/bin/env bash
# Fails unless the pushed image has exactly the layers that were scanned.
#
#   same_layers.sh <scanned-layers.json> <pushed-image.json>
#
# scanned-layers.json: `docker image inspect --format '{{json .RootFS.Layers}}'` of the scanned image, a JSON array of diff_ids.
# pushed-image.json:   `docker buildx imagetools inspect <ref> --format '{{json .Image}}'` of the pushed digest. An index carries one
#                      config per platform; a single-platform push carries exactly one, and that is the only shape accepted here.
set -euo pipefail

scanned="$(jq -c . "$1")"
pushed="$(jq -c '[.. | objects | select(has("rootfs")) | .rootfs.diff_ids]' "$2")"

if [ "$(jq 'length' <<< "$scanned")" -eq 0 ]; then
  echo "::error title=build-push-ecr::no layers recorded for the scanned image"
  exit 1
fi
if [ "$(jq 'length' <<< "$pushed")" -ne 1 ]; then
  echo "::error title=build-push-ecr::expected one platform config in the pushed image, got $(jq 'length' <<< "$pushed")"
  exit 1
fi

pushed="$(jq -c '.[0]' <<< "$pushed")"
if [ "$scanned" != "$pushed" ]; then
  echo "::error title=build-push-ecr::the pushed image is not the scanned one; its layers differ, so the scan did not vouch for it. Nothing downstream may use it."
  echo "scanned: $scanned"
  echo "pushed:  $pushed"
  exit 1
fi
echo "pushed image has the scanned layers ($(jq 'length' <<< "$scanned") layers)"
