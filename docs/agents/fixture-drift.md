# Fixture drift policy

When a snapshot test (`drawing_db_snapshot.json`, `db_snapshot.json`, or any
`expected.json` comparison) fails after a code change, **the failure is the
finding**, not a chore. Investigate the delta and demonstrate that every new
entry is a real, hand-verifiable improvement before regenerating the snapshot.

## Why this rule exists

Every time we've taken "+1 index entry" or "−1 finding" at face value and
auto-regenerated the snapshot, the new state has turned out to contain
something wrong — a hardware part number masquerading as a sheet, a parser
artifact, a regex that swept up noise alongside signal. Snapshots are the only
guardrail between "the parser changed" and "the parser got better." Treating a
delta as a paperwork step erases the guardrail.

## Procedure when a fixture snapshot diff appears

1. **Do not run `pytest --update-snapshots` first.** That's the last step, not
   the first.
2. **Enumerate every changed entry.** Not just the count delta — the actual
   set difference. `+ FR5210.ECD` is information; `index_entry_count: 655 →
   656` is not.
3. **For each new or removed entry, prove it is correct by inspection.** Open
   the source PDF, find the row, read what's around it. If it's a sheet, it
   sits in a sheet index with a title and an issue date. If it's a part
   number, it sits in a hardware schedule with a vendor and a SKU. They look
   different.
4. **If any single delta cannot be defended, the code change is wrong.** Fix
   the code, not the snapshot. The fact that "most of the deltas are good"
   does not license regenerating the file — one bad entry in a baseline rots
   every future measurement that uses it.
5. **Only then** regenerate the snapshot with `--update-snapshots`, and call
   out in the commit message what changed and why each delta is legitimate.

## What "hand-verifiable" means

For each delta, you can point at:

- The source PDF page (file + page number).
- The exact text on that page.
- Why the new behaviour represents the parser correctly recognising (or
  correctly ignoring) that text.

If you can only describe it in terms of the parser's own output ("the regex
now matches this pattern"), you have not verified it — you've described the
change. Verification answers "what is this thing in the real document?"

## Applies to

- `tests/fixtures/projects/*/drawing_db_snapshot.json`
- `tests/fixtures/projects/*/db_snapshot.json`
- `tests/fixtures/projects/*/expected.json` (when used as ground truth)
- Any future fixture file with hand-curated ground truth

## Doesn't apply to

- Adding a brand-new fixture for a new project — there's nothing to drift
  from.
- Fixture additions that are explicitly part of a curation task (`#NN: curate
  expected.json for X`), where the deltas are the deliverable.
