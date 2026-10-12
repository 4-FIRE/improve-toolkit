# Necessary Decision Explanations

Use this format only for decisions that pass the conditions in [SKILL.md](./SKILL.md#record-only-necessary-decision-explanations).

## Location

Keep the existing `docs/adr/` location and sequential names: `0001-slug.md`, `0002-slug.md`, etc.
In multi-context projects, use the relevant context's `docs/adr/`; use the root directory for system-wide decisions.

Create the directory only when a record is needed.
For a new record, scan the directory for the highest existing number and increment it by one.

## Template

```md
# {Short title of the decision}

{1–3 sentences: the relevant context, the confirmed decision, and its reason.}
```

State the condition or rejected alternative only when it helps explain the reason.
A short paragraph is normally enough. Do not require status fields, option lists, or consequence sections.

## Example

Record a confirmed ban on automatic retries when an external system cannot prevent duplicate charges.
Explain that constraint rather than merely stating that retries are disabled.

## Existing records

Use an existing explanation when it already covers the reason.
If its decision changes, update or supersede the relevant record rather than adding another account of the discussion.

An old record is not proof of current behavior.
If it conflicts with current code or the user's statement, check the decision before relying on it.

Do not recreate records because they were removed. Their absence does not mean that a decision was reversed.
Do not clean up historical records unless the user requests that work.
