# Context, Harness & Loop Engineering — Cheat Sheet

> One page. Context first, then guardrails, then automation.
> Explained with the OpenKubes example.

---

## The three terms in one sentence

| Term | Question | Workshop analogy |
|---|---|---|
| **Context Engineering** | What info does the AI need *right now*? | The work order |
| **Harness Engineering** | What tools, rules, controls does it need? | The workshop |
| **Loop Engineering** | How does it repeat the workflow on its own? | The assembly line |

**Mnemonic:** *Context* says what matters. *Harness* makes sure it's done right. *Loop* makes sure it's done repeatedly.

---

## 1. Context — the right info, not all the info

The AI gets exactly what it needs for the next step: task, rules, relevant files, examples, goals, constraints.

**Desk rule:** More info ≠ better. The more clutter lying around, the easier the AI misses what matters. Old docs, unrelated project files, unfiltered logs → out.

**Just-in-time:** Don't load everything at once. Overview first, then pull only the affected files.

**In OpenKubes:** To "integrate observability into `ok-cluster`," the agent needs the Jira ticket, ADR-Platform-018, the interfaces of `ok-observability`, and the acceptance criteria — **not** every repo in full.

---

## 2. Harness — tools & guardrails

**Guides (before the work):** ADRs, `README.md`/repo rules, API spec, naming conventions, example modules, Definition of Done.

**Sensors (after the work):** `make validate`, schema/manifest validation, linters, architecture tests, security/policy checks, readiness gates, PR review.

**Formula:** `Model + Tools + Rules + Controls`

**In OpenKubes:** The agent may not just emit YAML — it must pass `make validate`, architecture tests, and the observability readiness gate green.

---

## 3. Loop — repeat the workflow

```
While open tasks remain:
  1. Read ticket / next task
  2. Load relevant ADRs + files
  3. Apply the change
  4. Run tests + gates
  5. Fix errors
  6. Record progress (Jira / PROGRESS.md / Git)
  7. Pick the next step
```

**Stop condition:** all acceptance criteria met — or an architecture decision requires a human.

**Memory:** Persist progress outside the AI (Jira ticket, `PROGRESS.md`, Git commits) so the agent can resume after a restart.

**⚠️ Danger:** A loop repeats mistakes too. Without a loop → 1 wrong class. With a loop → 50 wrong classes. That's why **every** loop needs strong controls and a clear stop condition.

---

## Diagnosis — what's missing right now?

- **Agent misunderstands the task** → check context (goal clear? right files? architecture known? up to date? example provided?)
- **Agent violates project rules** → improve the harness (rules documented? tests? architecture checks? can it detect its own errors?)
- **Agent works well but needs constant re-prompting** → build a loop (next task automatic? progress saved? controls? safe stop condition?)

---

## OpenKubes mnemonic

> **ADRs and tickets** explain what is right.
> **Tests and gates** verify it was implemented right.
> **The loop** keeps working until the provable criteria are met.

---

## Special case: our 3-way review *is* a loop

With **Arash / Claude / GPT** you already run a **human-governed architecture review loop**:

```
ADR draft → Reviewer A (Claude) → Reviewer B (GPT) checks ADR + Review A
   → extract conflicts & consensus → author revises
   → fact / conformance check → Approve / Changes / Human Decision
```

**Sensor diversity (the core):**

- **Claude** → internal logic, counter-arguments, contradictions
- **GPT** → governance language, term precision, cross-ADR consistency
- **Git / Jira / okgraph** → verifiable facts

Two *identical* reviewers would only duplicate the same blind spots.

**The merge gate is the most important part of the harness:** *AI may argue; only humans merge.* It is simultaneously the safety boundary, the stop condition, the assignment of responsibility, and the protection against automated error multiplication. Because a human merges, the loop cannot produce 50 wrong ADRs.

**Automate the facts / Keep the decision human:**

| Well automatable (facts) | Deliberately human (judgment) |
|---|---|
| Does the referenced ADR exist? | Which counter-argument *truly* matters? |
| Is the ADR title & status correct? | Is a conflict linguistic or architectural? |
| Does the Jira ticket exist? | Is the compromise sound? |
| Do commit hash & repo match? | Real consensus or surface-level agreement? |
| Are links/dependencies consistent? | Should the decision be made at all? |
| okgraph: contradictory edges? | |

**Why the manual hand-off between reviewers is a *feature*:** The media break looks like an automation gap but keeps the human decision-maker cognitively in the loop. An auto-summary would be more efficient — but would foster exactly the loss of understanding that Loop Engineering warns about.

**Own blind spot:** If Claude and GPT agree *too quickly*, that itself is a sensor signal — not a green light but a cue to look closer. A loop where both reviewers always agree is functionally a loop with a single reviewer. The value emerges where they *disagree*.

---

> **The process that creates the architecture is part of the architecture.**
>
> Automate the facts. Augment the reasoning. Keep the decision human.
