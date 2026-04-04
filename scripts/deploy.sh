#!/usr/bin/env bash
# Deploy to GitHub Pages via gh-pages branch.
# Usage: bash scripts/deploy.sh
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"

echo "Building all trips..."
for trip_dir in "$REPO_ROOT"/trips/*/; do
    if [ -f "$trip_dir/data/trip.json" ]; then
        # Skip archived trips
        if python3 -c "import json,sys;d=json.load(open('$trip_dir/data/trip.json'));sys.exit(0 if d.get('archived') else 1)" 2>/dev/null; then
            echo "  Skipping archived: $(basename "$trip_dir")"
            continue
        fi
        python3 "$REPO_ROOT/scripts/render_trip.py" "$trip_dir"
    fi
done

echo "Building index..."
python3 "$REPO_ROOT/scripts/build_index.py"

echo "Deploying to gh-pages..."
# Create a temporary directory with only the deployable files
DEPLOY_DIR=$(mktemp -d)
cp "$REPO_ROOT/index.html" "$DEPLOY_DIR/"
for trip_dir in "$REPO_ROOT"/trips/*/; do
    # Skip archived trips
    if python3 -c "import json,sys;d=json.load(open('$trip_dir/data/trip.json'));sys.exit(0 if d.get('archived') else 1)" 2>/dev/null; then
        continue
    fi
    slug=$(basename "$trip_dir")
    mkdir -p "$DEPLOY_DIR/$slug"
    [ -f "$trip_dir/index.html" ] && cp "$trip_dir/index.html" "$DEPLOY_DIR/$slug/"
    [ -f "$trip_dir/calendar.ics" ] && cp "$trip_dir/calendar.ics" "$DEPLOY_DIR/$slug/"
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
