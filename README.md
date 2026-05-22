# redicheck-ai

RediCheck QC plugin for Claude Desktop — local-first spec-check and drawing-index-qc.

## Install

See [docs/onboarding.md](docs/onboarding.md).

Quick start after prerequisites (Python 3.11+, `gh`, Claude Desktop):

```
/plugin marketplace add tylernigrofr/redicheck-ai-plugin
```

Then run `/setup` and `/help`.

## Skills

- **qc-index** — index PDFs to `qc.sqlite`
- **spec-check** — spec findings preview / emit
- **drawing-index-qc** — drawing index cross-check
- **report-issue** — submit a bug report to Tyler (Linear via proxy)

## Support

Bug reports: use `/report-issue` inside Claude.

Engineering tracker (maintainers only): [tylernigrofr/redicheck-ai](https://github.com/tylernigrofr/redicheck-ai).
