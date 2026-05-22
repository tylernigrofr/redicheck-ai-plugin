# Marketplace ref-resolution spike (#25)

Status: **doc-derived conclusions + manual verification pending**

Parent: [#24](https://github.com/tylernigrofr/redicheck-ai/issues/24). Blocks #26 and #28 until Tyler confirms observed behavior in Claude Desktop.

## Questions

1. Does `/plugin marketplace add <repo>` fetch from `main`, the latest tag, or honor `marketplace.json`'s `ref:` field?
2. Does the `ref:` field control top-level plugin fetch, or only sub-plugin pinning within a marketplace?
3. When `marketplace.json` is updated on the marketplace's `main`, do existing Reviewer installs see the change automatically, or only after `/plugin marketplace update`?

## Doc-derived answers (preliminary)

Source: [Claude Code plugin marketplaces docs](https://code.claude.com/docs/en/plugin-marketplaces) (2026-05-22).

### Q1 — What does `marketplace add` clone?

`/plugin marketplace add owner/repo` clones the repository's **default branch** (`main`), unless the Reviewer pins at add time:

```bash
/plugin marketplace add tylernigrofr/redicheck-ai-plugin@v0.1.0
```

The `@ref` suffix on the add command is the **marketplace source** ref — it controls which commit of the catalog repo is cloned, not individual plugin refs inside `marketplace.json`.

**Implication for redicheck-ai-plugin:** CI force-pushing `main` on each release is the correct delivery mechanism. Reviewers who added without `@ref` track `main`.

### Q2 — What does `ref:` in `marketplace.json` control?

Two independent concepts:

| Concept | Set where | `ref` support |
|---------|-----------|---------------|
| Marketplace source | `/plugin marketplace add` or `extraKnownMarketplaces` | branch/tag on catalog repo |
| Plugin source | `source` field of each plugin entry in `marketplace.json` | branch/tag/**sha** on the plugin repo |

For **relative-path** plugin sources (`"source": "./"`), there is no `ref` field — the plugin files come from whatever commit the marketplace clone checked out. This is our layout: the entire `redicheck-ai-plugin` repo *is* the plugin.

The `ref` field inside `marketplace.json` only applies to external sources (`github`, `url`, `git-subdir`, `npm`).

**Implication:** ADR-0018 step "bump `marketplace.json` `ref:`" is **not applicable** for our relative-path layout. Release detection instead relies on bumping `plugin.json` `version` (see Q3).

### Q3 — How do updates reach installed Reviewers?

- **Marketplace catalog refresh:** `/plugin marketplace update` re-pulls the marketplace clone. Docs also describe **background auto-update at session startup** (git pull on the marketplace directory).
- **Plugin install/update skip logic:** Claude Code compares resolved plugin version. Resolution order: `plugin.json` `version` → marketplace entry `version` → git commit SHA.
- **Critical:** If `plugin.json` declares `"version": "0.1.0"` and CI pushes new commits without bumping that string, existing installs **will not update** — same version = skip.

**Implication:** Every release must bump `version` in `.claude-plugin/plugin.json` (and keep `pyproject.toml` in sync). The SessionStart fingerprint hook (ADR-0017) then rebuilds the venv when `pyproject.toml` changes.

Private repo auto-update at startup requires `GITHUB_TOKEN` or `GH_TOKEN` in the Reviewer's environment (docs: credential helpers are not available during background auto-update).

## Recommended v0.1.0 layout

```json
// .claude-plugin/marketplace.json
{
  "name": "redicheck-ai",
  "owner": { "name": "The RediCheck Firm, LLC" },
  "plugins": [
    {
      "name": "redicheck-ai",
      "source": "./",
      "description": "RediCheck spec-check and drawing-index-qc for Claude Desktop"
    }
  ]
}
```

```json
// .claude-plugin/plugin.json
{
  "name": "redicheck-ai",
  "version": "0.1.0",
  ...
}
```

Release flow:

1. Tyler tags dev repo `vX.Y.Z` with matching `pyproject.toml` + `plugin.json` version.
2. CI slim-builds and force-pushes to `redicheck-ai-plugin` `main`, tags `vX.Y.Z`.
3. Reviewer-side auto-update pulls new `main`, sees new `plugin.json` version, refreshes cached plugin.
4. SessionStart fingerprint hook rebuilds `.venv` if `pyproject.toml` hash changed.

## Manual verification protocol

Run in Claude Desktop after a throwaway test marketplace is live (or after `redicheck-ai-plugin` exists):

| Step | Action | Record |
|------|--------|--------|
| 1 | `/plugin marketplace add tylernigrofr/redicheck-ai-plugin` (no `@ref`) | Which commit SHA lands in `~/.claude/plugins/marketplaces/...`? |
| 2 | Install `redicheck-ai@redicheck-ai` | Plugin cache path + resolved version |
| 3 | Push a commit to plugin repo `main` that bumps `plugin.json` version only | Does next session auto-pull? Does `/plugin update` show the new version? |
| 4 | Push a commit that does **not** bump version | Confirm update is skipped |
| 5 | `/plugin marketplace update` explicitly | Confirm catalog re-pulls |
| 6 | Re-add with `@v0.1.0` suffix | Confirm pinned catalog commit |

Fill the **Observed behavior** section below with concrete results (not docs citations). If any observation contradicts the preliminary answers above, amend ADR-0018 before merging the v0.1.0 PR.

## Observed behavior

_To be completed by Tyler in Claude Desktop._

| Step | Result |
|------|--------|
| 1 | |
| 2 | |
| 3 | |
| 4 | |
| 5 | |
| 6 | |

## ADR-0018 amendment

Pending manual verification. Preliminary change: replace "Bumps `.claude-plugin/marketplace.json` `ref:`" with "Bumps `.claude-plugin/plugin.json` `version` to match the release tag."
