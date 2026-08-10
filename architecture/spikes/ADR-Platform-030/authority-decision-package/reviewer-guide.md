# Reviewer guide: authority decisions

This guide is procedural only. It does not assign authority or grant a gate.

## What this checkpoint proves

- all nine `EXPLICIT-AUTHORITY` obligations have one decision question;
- every question is bound to the current protocol and evidence chain;
- residual RBAC and DEV recovery boundaries are visible to reviewers;
- the two credential mutations cannot inherit authority from this package;
- an unchanged v1 package can only validate while all decisions are undecided.

It does not prove that a person is authorized to decide, that a target snapshot
is fresh, that an evidence destination exists, or that rebuild works.

## Required review order

1. Verify the package and all referenced raw digests.
2. Refresh the live target incarnation and compatibility evidence immediately
   before any decision session.
3. Review security and recovery boundaries before installation authority.
4. Resolve placement authority for M0b-I against the refreshed immutable
   `ok-shared` identity.
5. Assign independent observers and approve the evidence destination.
6. Bind named decision authority, final protocol digest, exact target
   incarnation, and one bounded time window in a new package revision.
7. Re-canonicalize, re-hash, and review that new revision.
8. Treat credential issuance as a later, separate mutation gate.

Any missing, stale, conflicting, or unverified input produces `NO-GO`.

## Decision boundaries

An authority may accept DEV state-loss risk without claiming HA, snapshot
recovery, rebuild proof, automatic adoption, production DR, or lifecycle
continuity. Acceptance records ownership of the stated risk; it does not turn
an absent capability into evidence.

Security acceptance is exact. It applies only to the RBAC artifact and digest
reviewed by this package. A changed role, binding, source manifest, target
incarnation, protocol, or window invalidates the decision scope.

Observer assignment is not installation authority. Recovery authority is not
credential authority. Placement authority is not permission to install Argo.

## Stop conditions

Stop and return to `NO-GO` when any of these occurs:

- source, protocol, evidence, target, or decision-package digest changes;
- live identity or compatibility no longer matches the reviewed snapshot;
- observer independence or evidence destination cannot be demonstrated;
- a credential is requested under this package instead of its own gate;
- a reviewer attempts to infer restore, adoption, HA, or continuity evidence;
- an authority, decision timestamp, or window is missing or ambiguous.
