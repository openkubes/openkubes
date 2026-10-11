#!/usr/bin/env bash
# OK-196: Cloudflare Pages preview build. Does not deploy to production GitHub Pages.
set -euo pipefail
cd "$(dirname "$0")/../.."

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r website/requirements-mkdocs.txt

mkdir -p .ok196-sources
git clone https://github.com/openkubes/ok-local.git .ok196-sources/ok-local
git -C .ok196-sources/ok-local checkout --detach 60397cdb2630b0cd9cfbcb5d9a29fe2e38ce323e
git clone https://github.com/openkubes/ok-cluster.git .ok196-sources/ok-cluster
git -C .ok196-sources/ok-cluster checkout --detach a341f4ad4eff73e3cf7a69a38d1de8e2455e73a6

python website/scripts/build-docs.py
python website/scripts/stage-legacy.py
mkdocs build --strict
python website/scripts/preserve-homepage.py
python website/scripts/render-navigation.py
python website/scripts/restore-legacy-urls.py
python website/scripts/check-preview.py

# Preview pages must not be indexed; Cloudflare Pages serves _headers at its root.
printf '/*\n  X-Robots-Tag: noindex, nofollow\n' > .mkdocs-site/_headers
printf 'User-agent: *\nDisallow: /\n' > .mkdocs-site/robots.txt
echo 'OK-196 Cloudflare Pages preview build ready'
