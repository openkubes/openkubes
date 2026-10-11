#!/usr/bin/env bash
# Build the GitHub Pages production candidate. This script NEVER deploys.
# Run after checkout of pinned .ok196-sources/{ok-local,ok-cluster}
# and installation of website/requirements-mkdocs.txt.
set -euo pipefail
cd "$(dirname "$0")/../.."

python website/scripts/build-docs.py
python website/scripts/stage-legacy.py
mkdocs build --strict
python website/scripts/preserve-homepage.py
python website/scripts/render-navigation.py
python website/scripts/restore-legacy-urls.py
python website/scripts/render-legacy-html.py
python website/scripts/check-preview.py
python website/scripts/audit-url-compatibility.py

# GitHub Pages custom domain and bypass Jekyll processing.
test "$(cat docs/CNAME)" = "openkubes.org"
cp docs/CNAME .mkdocs-site/CNAME
touch .mkdocs-site/.nojekyll

# Preview-only search-index blocking must never go to production.
rm -f .mkdocs-site/_headers
printf 'User-agent: *\nAllow: /\n' > .mkdocs-site/robots.txt
python website/scripts/check-github-pages-build.py
echo "GitHub Pages production candidate built. No deployment was performed."
