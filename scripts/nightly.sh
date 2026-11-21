#!/bin/bash
# Spirka nightly job (runs on GitHub Actions).
# 1. downloads the city's timetable, 2. builds the data folder, 3. publishes it to the gh-pages branch.
# Last night's data is kept as v1.prev. If the city's file looks broken, nothing is published.
set -euo pipefail
REPO_URL="${REPO_URL:?}"
WORK="$(mktemp -d)"
OUT="$WORK/out"

curl -fsSL --retry 3 --max-time 300 -o "$WORK/gtfs.zip" "https://gtfs.sofiatraffic.bg/api/v1/static"
mkdir "$WORK/gtfs" && unzip -q "$WORK/gtfs.zip" -d "$WORK/gtfs"

# start from what is online now, so the build can keep it as v1.prev
if git clone -q --depth 1 -b gh-pages "$REPO_URL" "$OUT" 2>/dev/null; then rm -rf "$OUT/.git"; else mkdir -p "$OUT"; fi

python3 scripts/build.py "$WORK/gtfs" "$OUT" 9 -v

touch "$OUT/.nojekyll"   # serve files as they are
cat > "$OUT/index.html" <<'HTML'
<!doctype html><meta charset="utf-8"><title>Spirka data</title><p>Timetable data for the Sofia public transport page. Built nightly from the Sofia Urban Mobility Center's open GTFS data (CC BY 4.0).</p>
HTML

cd "$OUT"
git init -q -b gh-pages
git config user.name "spirka-bot"; git config user.email "spirka-bot@users.noreply.github.com"
git add -A && git commit -q -m "Timetable $(date -u +%Y-%m-%d)"
git push -q -f "$REPO_URL" gh-pages   # one commit only: the data branch never grows
echo "Published."
