# OpenKubes Cloudflare Preview Deployment

This branch is the dedicated source for the Cloudflare Pages project `openkubes-preview`.

- Cloudflare Pages **production branch**: `website-preview` (this refers to the Cloudflare preview project, not `openkubes.org`).
- Custom preview URL: `https://preview.openkubes.org/`.
- The public production website `openkubes.org` remains on its existing GitHub Pages setup.
- Build command: `bash website/scripts/cloudflare-build.sh`.
- Build output: `.mkdocs-site`.
- Changes should be reviewed and tested before they are promoted to this branch.

This documentation-only commit intentionally triggers a fresh Cloudflare Pages deployment following the branch configuration change. It does not modify any website content or production deployment workflow.
