#!/usr/bin/env bash
# Deploy to GitHub Pages via gh-pages branch.
# Usage: bash scripts/deploy.sh [--only <slug>]
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
ONLY_SLUG=""
if [[ "${1:-}" == "--only" ]]; then
    ONLY_SLUG="${2:-}"
    echo "Incremental mode: only rendering $ONLY_SLUG"
fi

# ── Helper: read trip.json field ──
trip_field() {
    python -c "import json,sys;d=json.load(open('$1',encoding='utf-8'));print(d.get('$2',''))"
}

echo "Building trips..."
for trip_dir in "$REPO_ROOT"/trips/*/; do
    if [ -f "$trip_dir/data/trip.json" ]; then
        trip_json="$trip_dir/data/trip.json"
        slug=$(basename "$trip_dir")
        status=$(trip_field "$trip_json" status)

        # Skip archived trips
        if python -c "import json,sys;d=json.load(open('$trip_json',encoding='utf-8'));sys.exit(0 if d.get('archived') else 1)" 2>/dev/null; then
            echo "  Skipping archived: $slug"
            continue
        fi
        # Skip test trips (never deploy unless explicitly targeted)
        if [[ "$status" == "test" && -z "$ONLY_SLUG" ]]; then
            echo "  Skipping test trip: $slug"
            continue
        fi
        # Skip if --only specified and this isn't the target
        if [[ -n "$ONLY_SLUG" && "$slug" != "$ONLY_SLUG" ]]; then
            echo "  Skipping (not target): $slug"
            continue
        fi
        # Guard: prerendered trips already have HTML, skip render
        prerendered=$(trip_field "$trip_json" prerendered)
        if [[ "$prerendered" == "True" ]]; then
            echo "  Prerendered (skip render): $slug"
            continue
        fi
        # Guard: refuse to render over a final trip without --only
        if [[ "$status" == "final" && -z "$ONLY_SLUG" ]]; then
            echo "  ⚠ Skipping final trip (use --only $slug to force): $slug"
            continue
        fi
        python "$REPO_ROOT/scripts/render_trip.py" "$trip_dir"
    fi
done

echo "Building index..."
python "$REPO_ROOT/scripts/build_index.py"

echo "Deploying to gh-pages..."
# Create a temporary directory with only the deployable files
DEPLOY_DIR=$(mktemp -d)
cp "$REPO_ROOT/index.html" "$DEPLOY_DIR/"

# ── Slug collision check ──
declare -A SEEN_SLUGS
for trip_dir in "$REPO_ROOT"/trips/*/; do
    [ -f "$trip_dir/data/trip.json" ] || continue
    trip_json="$trip_dir/data/trip.json"
    status=$(trip_field "$trip_json" status)
    [[ "$status" == "test" ]] && continue
    if python -c "import json,sys;d=json.load(open('$trip_json',encoding='utf-8'));sys.exit(0 if d.get('archived') else 1)" 2>/dev/null; then
        continue
    fi
    deploy_slug=$(trip_field "$trip_json" slug)
    deploy_slug="${deploy_slug:-$(basename "$trip_dir")}"
    if [[ -n "${SEEN_SLUGS[$deploy_slug]:-}" ]]; then
        echo "ERROR: slug collision! '$deploy_slug' used by both:"
        echo "  - ${SEEN_SLUGS[$deploy_slug]}"
        echo "  - $trip_dir"
        echo "Fix trip.json slugs before deploying."
        rm -rf "$DEPLOY_DIR"
        exit 1
    fi
    SEEN_SLUGS[$deploy_slug]="$trip_dir"
done

for trip_dir in "$REPO_ROOT"/trips/*/; do
    [ -f "$trip_dir/data/trip.json" ] || continue
    trip_json="$trip_dir/data/trip.json"
    status=$(trip_field "$trip_json" status)
    # Skip archived and test trips
    if python -c "import json,sys;d=json.load(open('$trip_json',encoding='utf-8'));sys.exit(0 if d.get('archived') else 1)" 2>/dev/null; then
        continue
    fi
    [[ "$status" == "test" ]] && continue
    deploy_slug=$(trip_field "$trip_json" slug)
    deploy_slug="${deploy_slug:-$(basename "$trip_dir")}"
    mkdir -p "$DEPLOY_DIR/$deploy_slug"
    [ -f "$trip_dir/index.html" ] && cp "$trip_dir/index.html" "$DEPLOY_DIR/$deploy_slug/"
    [ -f "$trip_dir/calendar.ics" ] && cp "$trip_dir/calendar.ics" "$DEPLOY_DIR/$deploy_slug/"
done

# Push to gh-pages branch, using the repo-level git identity
DEPLOY_USER=$(cd "$REPO_ROOT" && git config user.name)
DEPLOY_EMAIL=$(cd "$REPO_ROOT" && git config user.email)

cd "$DEPLOY_DIR"
git init
git config user.name "$DEPLOY_USER"
git config user.email "$DEPLOY_EMAIL"
git checkout -b gh-pages
git add -A
git commit -m "Deploy $(date +%Y-%m-%d\ %H:%M)"
git remote add origin "$(cd "$REPO_ROOT" && git remote get-url origin)"
git push origin gh-pages --force

rm -rf "$DEPLOY_DIR"
REPO_NAME=$(cd "$REPO_ROOT" && git remote get-url origin | sed 's/.*[:/]\([^/]*\)\.git/\1/' | sed 's/.*[:/]\([^/]*\)$/\1/')
REPO_OWNER=$(cd "$REPO_ROOT" && git remote get-url origin | sed 's/.*[:/]\([^/]*\)\/[^/]*/\1/')
echo "Deployed! Site: https://${REPO_OWNER}.github.io/${REPO_NAME}/"
