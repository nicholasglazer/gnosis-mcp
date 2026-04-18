---
title: Releasing gnosis-mcp
category: docs
audience: maintainer
last_verified: "2026-04-18"
---

# Releasing gnosis-mcp

The full, auditable pipeline for shipping a new version. Every command
below is scripted — no manual version edits anywhere.

## TL;DR

```bash
# 1. Bump + tag + commit (library repo)
scripts/release.sh 0.11.0

# 2. Push — this triggers PyPI + GHCR + MCP Registry automatically
git push github main --tags
git push codeberg main --tags
git push selify main --tags     # non-critical mirror

# 3. Update website (separate repo)
cd /home/ng/prod/gnosismcp.com
scripts/bump-version.sh 0.11.0
pnpm graph-data && pnpm build
wrangler pages deploy .svelte-kit/cloudflare --project-name gnosismcp-com

# 4. Confirm
# Watch the four downstream registries resolve (see §6 below)
```

Everything under §1–§8 is automated by those commands. If you need to
deviate, the detail is below.

---

## 0. Release cadence + versioning

- **Patch** (x.y.Z): bugfixes, docs, no new required deps, no tool/resource
  API changes. Default cadence — any time a fix lands on main.
- **Minor** (x.Y.0): new features, new optional deps, additive tool/resource
  surface. Default for quarterly/feature releases.
- **Major** (X.0.0): breaking change to the tool/resource API, DB schema,
  or required deps. Plan + 2-week notice in CHANGELOG.

SemVer applies to the **user-facing surface**: MCP tools, resources,
CLI flags, env vars, REST endpoints. Internal refactors do not trigger
a bump on their own.

---

## 1. Pre-release checklist

Before running `scripts/release.sh`, confirm:

- [ ] All PRs for this release are merged to `main`
- [ ] `main` is green on CI (`gh run list --branch main --limit 5`)
- [ ] Benchmarks re-run if retrieval-path code changed
  (`uv run python tests/bench/bench_beir.py --dataset scifact` — sanity)
- [ ] `docs/bench-experiments-*.md` updated if new results were measured
- [ ] CHANGELOG `[Unreleased]` section is populated with the actual
  user-visible changes (Added / Changed / Fixed / Security)
- [ ] `docs/` entries for any new features exist (not just code docstrings)
- [ ] `agents/` and `skills/` updated if the tool surface changed

---

## 2. Cut the release (one command)

```bash
scripts/release.sh 0.11.0
```

This runs `scripts/bump-version.sh` under the hood and then:

1. Verifies clean tree + on main + tag doesn't already exist
2. Edits every authoritative version string (see §3)
3. Rolls `CHANGELOG.md` — `[Unreleased]` becomes `[0.11.0] — 2026-04-18`
   with a fresh empty `[Unreleased]` above it
4. Runs the test suite (`pytest -x`)
5. Runs `scripts/check-versions.sh` for parity
6. Shows you the diff; asks for y/N confirmation
7. Creates `release: v0.11.0` commit + annotated `v0.11.0` tag

Nothing pushed yet.

## 3. What the bump script touches

Authoritative code + config (must all match):

| File | Field |
|---|---|
| `pyproject.toml` | `version = "..."` |
| `src/gnosis_mcp/__init__.py` | `__version__ = "..."` |
| `server.json` | top-level `.version` and `.packages[0].version` |
| `marketplace.json` | `.plugins[0].version` |

Docs that move on version:

| File | What changes |
|---|---|
| `CHANGELOG.md` | `[Unreleased]` section rolls to `[X.Y.Z] — YYYY-MM-DD` |
| `SECURITY.md` | "latest X.Y.x patch receives security fixes" updated |
| `uv.lock` | regenerated via `uv sync` |

Intentionally **not** auto-bumped:

- `docs/benchmarks.md`, `docs/bench-experiments-*.md` — "captured on
  v0.10.13" is a historical measurement, not a live reference. Update
  manually if you re-ran benchmarks.
- `docs/rest-api.md` — `version: "0.10.13"` appears in an example JSON
  response; update manually if the example is out of date.
- `llms.txt`, `llms-full.txt` body text — may reference prior versions
  for context. Script flags but doesn't edit.

## 4. Push

Per the three-remote policy (see CLAUDE.md § git-safety):

```bash
git push github main --tags       # triggers Actions → PyPI + GHCR + MCP Registry
git push codeberg main --tags
git push selify main --tags        # may fail if ssh absent — non-critical
```

## 5. What the tag push automates

`.github/workflows/publish.yml` fires on any `v*` tag:

1. Tag-version parity check (`REF_TAG == pyproject version`)
2. `uv sync --extra dev --extra embeddings --extra postgres --extra web`
3. `ruff check .`
4. `uv run pytest -x`
5. `scripts/check-versions.sh`
6. `uv build` — wheel + sdist
7. `uv publish` — PyPI
8. `mcp-publisher publish` — MCP Registry

`.github/workflows/docker.yml` fires on the same tag:

1. Multi-arch build (linux/amd64 + linux/arm64)
2. Push to `ghcr.io/nicholasglazer/gnosis-mcp:{version,major.minor,latest}`

Both run in parallel, typically complete in 10–15 minutes.

## 6. Post-release — confirm the registries resolved

| Channel | URL | How to confirm |
|---|---|---|
| PyPI | https://pypi.org/project/gnosis-mcp/ | `pip install gnosis-mcp==X.Y.Z` works |
| GHCR | https://github.com/nicholasglazer/gnosis-mcp/pkgs/container/gnosis-mcp | `docker pull ghcr.io/nicholasglazer/gnosis-mcp:X.Y.Z` works |
| MCP Registry | https://registry.modelcontextprotocol.io/v0/servers?search=gnosis | `gnosis-mcp` entry shows `X.Y.Z` |
| GitHub Release | https://github.com/nicholasglazer/gnosis-mcp/releases | Tag appears with CHANGELOG-derived release notes |

If any is missing after 30 min:
- GitHub Actions logs under the tag's run
- For PyPI 2-factor: the API token may have expired; rotate via
  PyPI → Account → API tokens

## 7. Update the website (separate repo)

`gnosismcp.com` is a different repo with a different deploy pipeline.
Always do this after the library tag has been pushed so the registry
badges on the site link to a resolvable version.

```bash
cd /home/ng/prod/gnosismcp.com
scripts/bump-version.sh 0.11.0          # edits hero + JSON-LD + llms.txt
pnpm graph-data                          # rebuild the graph snapshot
pnpm build                               # rebuild site
wrangler pages deploy .svelte-kit/cloudflare --project-name gnosismcp-com
```

### What the website bump touches

- `src/app.html` — JSON-LD `softwareVersion` (for SEO/schema.org)
- `src/routes/+page.svelte` — hero line `v0.11.0 · MIT · Python 3.11+`
- `static/llms.txt` — `## Measured numbers (v0.11.0, laptop CPU)` header

Commit the diff and push — the site is a CF Pages project, so the
deploy itself happens via `wrangler`, not via git integration.

## 8. Arch Linux / AUR (two-phase)

`pkg/arch/PKGBUILD` is in-repo so Arch users can `makepkg` locally even
before the AUR publish. Bumping is two phases because `sha256sums` can
only be computed **after** PyPI has the new sdist online.

### Phase A — at bump time (automatic)

`scripts/bump-version.sh` already:

- bumps `pkgver`, resets `pkgrel=1`
- regenerates `pkg/arch/.SRCINFO` (via `makepkg --printsrcinfo` if
  available, else a sed fallback)
- leaves `sha256sums` pointing at the OLD hash on purpose — if we blew
  it away here, `makepkg` would silently accept any tampered tarball

### Phase B — after publish.yml finishes uploading to PyPI

```bash
# Wait for https://pypi.org/project/gnosis-mcp/#files to show X.Y.Z
scripts/update-arch-sums.sh 0.11.0     # or omit — reads pkgver from PKGBUILD
```

This downloads the sdist from the predictable PyPI source URL, computes
the sha256, rewrites `PKGBUILD` + regenerates `.SRCINFO`, and prints the
AUR-repo `git push` instructions.

Then commit the Phase B changes back to gnosis-mcp itself:

```bash
git add pkg/arch/PKGBUILD pkg/arch/.SRCINFO
git commit -m "pkg(arch): sha256 for 0.11.0"
git push selify main && git push codeberg main && git push github main
```

### First-time AUR publish (one-off)

If this is the first time shipping to AUR (python-gnosis-mcp not
registered yet):

```bash
ssh aur@aur.archlinux.org submit python-gnosis-mcp      # reserves the name
git clone ssh://aur@aur.archlinux.org/python-gnosis-mcp.git ~/aur-gnosis-mcp
cp pkg/arch/PKGBUILD pkg/arch/.SRCINFO ~/aur-gnosis-mcp/
cd ~/aur-gnosis-mcp && git add . && git commit -m "initial import 0.11.0" && git push
```

Then verify the package is visible at
https://aur.archlinux.org/packages/python-gnosis-mcp.

### Lower-maintenance alternative: `-git` flavor only

`pkg/arch/PKGBUILD-git` tracks `main` and doesn't need per-release
bumps. If full AUR maintenance sounds like a chore, publish only
`python-gnosis-mcp-git` and users get rolling releases from source.

## 9. Other post-release tasks (manual)

- [ ] Announce: HN / r/selfhosted / r/LocalLLaMA / X (if relevant)
- [ ] Refresh README badges if any changed (test count etc.)
- [ ] Open a `[Unreleased]` stub PR for the next version's upcoming
  changes (helps contributors know where to log entries)

---

## 9. Hotfix flow (for urgent patches)

If a critical bug needs a same-day fix:

```bash
git checkout main
# apply the fix
git commit -m "fix: <short description>"
scripts/release.sh 0.11.1             # patch bump
git push github main --tags
# wait ~10 min for Actions, then:
cd /home/ng/prod/gnosismcp.com
scripts/bump-version.sh 0.11.1
pnpm build && wrangler pages deploy .svelte-kit/cloudflare --project-name gnosismcp-com
```

Hotfix versions skip the full pre-release checklist (§1). The trade-off:
accept that a hotfix may reveal additional regressions that need a
follow-up patch.

---

## 10. Yanking a release

If a release turns out to be broken:

```bash
# 1. Yank from PyPI (marks it "please don't install this" — doesn't delete)
python -m pip index versions gnosis-mcp              # confirm version exists
# Use PyPI web UI → project → manage → releases → Yank
# (no CLI for yanking; it's a deliberate speed bump)

# 2. Delete the GHCR image tag
gh api -X DELETE "user/packages/container/gnosis-mcp/versions/<version-id>"
#   (find version-id from `gh api user/packages/container/gnosis-mcp/versions`)

# 3. Unpublish from MCP Registry (contact @modelcontextprotocol admins
#    if no CLI — they have a moderation queue)

# 4. Delete the GitHub tag + release
gh release delete v0.11.0 --yes
git push github :refs/tags/v0.11.0
git push codeberg :refs/tags/v0.11.0

# 5. Immediately publish the fixed version as 0.11.1 (never re-use a
#    version number — it breaks any pinned installs)
```
