# Release process (Tyler SOP)

How to ship a new redicheck-ai plugin version to Reviewers.

## Architecture

- **Dev repo:** `tylernigrofr/redicheck-ai` — private engineering, tests, fixtures, ADRs, Vercel proxy.
- **Plugin repo:** `tylernigrofr/redicheck-ai-plugin` — **public**, CI-maintained slim tree (ADR-0018).

## Cut a release

1. **Bump versions** (must match):
   - `pyproject.toml` → `version = "X.Y.Z"`
   - `.claude-plugin/plugin.json` → `"version": "X.Y.Z"`
   - `qc_core/plugin_config.py` → `PLUGIN_VERSION = "X.Y.Z"`

2. **Merge to `main`** on the dev repo.

3. **Tag and push:**
   ```bash
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

4. **CI** (`.github/workflows/release.yml`) runs automatically:
   - Verifies tag matches `pyproject.toml` version
   - Deletes dev-only paths
   - Force-pushes slim tree to `redicheck-ai-plugin` `main`
   - Tags `vX.Y.Z` on the plugin repo

5. **Verify reviewer-side** in a clean Claude Desktop session:
   - `/plugin marketplace add tylernigrofr/redicheck-ai-plugin` (no auth required — public repo)
   - `/setup` → `/spec-check --help`
   - `/report-issue --title "smoke" --body "test" --dry-run` → confirm payload
   - `/report-issue --title "smoke" --body "test"` → confirm Linear issue created in FBK

## One-time setup (before first release)

### Feedback proxy (Vercel)

See `services/feedback-proxy/README.md`.

1. Deploy `services/feedback-proxy` to Vercel (monorepo root = that folder).
2. Set Vercel env vars: `LINEAR_API_KEY`, `LINEAR_TEAM_ID`.
3. Set `FEEDBACK_PROXY_URL` in `qc_core/plugin_config.py` to the production `/api/feedback` URL.

### Plugin repo

1. Create **public** repo `tylernigrofr/redicheck-ai-plugin`.
2. Branch-protect `main` — only CI deploy key can push.

### Deploy key

1. Generate SSH deploy key with write access **only** to `redicheck-ai-plugin`.
2. Add public key as deploy key on `redicheck-ai-plugin`.
3. Store private key as dev-repo secret: `PLUGIN_REPO_DEPLOY_KEY`.

## Reviewer issue intake

Vercel proxy → Linear Feedback (ADR-0019). No secrets in the plugin artifact.

| Item | Value |
|------|-------|
| Proxy URL | `FEEDBACK_PROXY_URL` in `qc_core/plugin_config.py` |
| Subject prefix | `[redicheck-ai]` |
| CLI | `report-issue` → `qc_core/feedback_report.py` |
| Maintainer proxy | `services/feedback-proxy/` |

Tyler triages Linear FBK → promotes real engineering work to GitHub issues on `tylernigrofr/redicheck-ai`.

## Marketplace ref behavior

See `docs/notes/marketplace-ref-spike.md`.

## Dry-run tag

```bash
git tag v0.0.0-dryrun
git push origin v0.0.0-dryrun
```

Delete the tag after verifying plugin-repo state.
