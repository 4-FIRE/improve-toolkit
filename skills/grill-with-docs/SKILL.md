---
name: grill-with-docs
description: Interview the user to sharpen a plan or design, maintain CONTEXT.md terminology, and record only necessary decision explanations.
disable-model-invocation: true
---

# Grill with Docs

## Interview

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

The confirmation above concerns implementation. Record resolved terms and necessary decision explanations during the interview as described below.

## Domain Modeling

Clarify project terms, test their boundaries with concrete scenarios, and record resolved definitions.

### File structure

If a root `CONTEXT-MAP.md` exists, read it to locate the relevant context's `CONTEXT.md`.
Otherwise, use the root `CONTEXT.md`. Create it only when the first term is resolved.

Store necessary decision explanations in `docs/adr/`, using the location rules in the ADR template below.
Create the directory only when a record is needed.

### During the session

#### Challenge against the glossary

When the user uses a term that conflicts with the existing language in `CONTEXT.md`, call it out immediately. "Your glossary defines 'cancellation' as X, but you seem to mean Y. Which is it?"

#### Sharpen fuzzy language

When the user uses vague or overloaded terms, propose a precise canonical term. "You're saying 'account': do you mean the Customer or the User? Those are different things."

#### Discuss concrete scenarios

When domain relationships are being discussed, stress-test them with specific scenarios. Invent scenarios that probe edge cases and force the user to be precise about the boundaries between concepts.

#### Cross-reference with code

When the user states how something works, check whether the code agrees. If you find a contradiction, surface it: "Your code cancels entire Orders, but you just said partial cancellation is possible. Which is right?"

#### Update CONTEXT.md inline

When a term is resolved, update `CONTEXT.md` right there. Don't batch these up: capture them as they happen. Use the format in [CONTEXT-FORMAT.md](./CONTEXT-FORMAT.md).

`CONTEXT.md` should be totally devoid of implementation details. Do not treat `CONTEXT.md` as a spec, a scratch pad, or a repository for implementation decisions. It is a glossary and nothing else.

#### Record only necessary decision explanations

ADRs are occasional decision explanations, not a session log. Record one only when all four conditions apply:

1. The user has confirmed the decision.
2. Without its reason, a future maintainer would likely make a plausible but incorrect change.
3. The reason is not clear from the code.
4. Existing documentation does not already explain the reason.

Confirm the actual trade-off with the user, not whether they want an ADR. Do not routinely offer or announce ADR creation.

Skip routine technology choices, progress reports, implementation steps, and lists of options discussed.
Do not put decision explanations in `CONTEXT.md`.

Only when a record is needed, read [ADR-FORMAT.md](./ADR-FORMAT.md) for its format and handling of existing records.
