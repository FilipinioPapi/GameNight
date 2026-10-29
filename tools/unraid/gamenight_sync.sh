#!/bin/bash
# Game Night auto-publish (Unraid "User Scripts", custom schedule: */5 * * * *  = every 5 minutes).
# Checks the private GitHub repo's newest release; when a new one appears, downloads GameNightSetup.exe,
# signs the file list with the same NAS key as Roof Rage, and puts it in the updates share under gamenight/,
# which https://updates.jjsnas.xyz/gamenight/ serves. Log: /mnt/user/appdata/gamenight-sync/sync.log
#
# The secret key stays in /mnt/user/appdata/roofrage-sync/ (read-only to the container, never in $OUT).
#
# Fill in this line (keep the quotes). A fine-grained token with read-only Contents on GameNight is enough:
TOKEN="PASTE-YOUR-GITHUB-TOKEN-HERE"
OUT="/mnt/user/JJsNAS/RoofRage-Updates/gamenight"
KEY="/mnt/user/appdata/roofrage-sync/signing_key.pem"

REPO="FilipinioPapi/GameNight"
WORK="/mnt/user/appdata/gamenight-sync"
set -o pipefail
mkdir -p "$WORK" "$OUT"
exec 9>"$WORK/lock"; flock -n 9 || exit 0          # a slow download is still running
log() { echo "$(date '+%F %T') $*" >> "$WORK/sync.log"; }
api() { curl -fsSL -H "Authorization: Bearer $TOKEN" -H "X-GitHub-Api-Version: 2022-11-28" "$@"; }

tag=$(api "https://api.github.com/repos/$REPO/releases/latest" | grep -o '"tag_name": *"[^"]*"' | head -1 | sed 's/.*"\([^"]*\)"$/\1/') \
  || { log "could not reach GitHub (token or internet?)"; exit 0; }
[ -z "$tag" ] && exit 0                              # no release yet
[ "$tag" = "$(cat "$WORK/last_tag" 2>/dev/null)" ] && exit 0

[ -f "$KEY" ] || { log "no signing key at $KEY, not publishing $tag"; exit 0; }
log "new release $tag, publishing"
api -H "Accept: application/vnd.github.raw" "https://api.github.com/repos/$REPO/contents/tools/unraid/gamenight_publish.py?ref=main" -o "$WORK/gamenight_publish.py" \
  || { log "could not fetch the publish script"; exit 0; }
if docker run --rm -e GITHUB_TOKEN="$TOKEN" -v "$WORK":/work:ro -v "$KEY":/key/signing_key.pem:ro -v "$OUT":/out \
     python:3.12-alpine python /work/gamenight_publish.py /out >> "$WORK/sync.log" 2>&1; then
  echo "$tag" > "$WORK/last_tag"
  log "done"
else
  log "publishing failed (see lines above)"
fi
