#!/usr/bin/env bash
# Build the GitHub Pages production candidate. This script NEVER deploys.
# Run after checkout of pinned .ok196-sources/{ok-local,ok-cluster,ok-baremetal-byoh}
# and installation of website/requirements-mkdocs.txt.
set -euo pipefail
cd "$(dirname "$0")/../.."

python -m unittest discover -s website/tests -p 'test_blog_editorial_dates.py'
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

# Keep the production candidate publicly indexable.
rm -f .mkdocs-site/_headers
printf 'User-agent: *\nAllow: /\n' > .mkdocs-site/robots.txt
python website/scripts/check-github-pages-build.py
python -m unittest discover -s website/tests -p 'test_privacy_resources.py'
python -m unittest discover -s website/tests -p 'test_privacy_legal_draft_guard.py'
python website/scripts/check-privacy-resources.py
python -m unittest discover -s website/tests -p 'test_retired_widgets.py'
echo "GitHub Pages production candidate built. No deployment was performed."
