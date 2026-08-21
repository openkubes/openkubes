# ADR-Platform-038: Console Session Store Contract and PostgreSQL Reference Profile

**Date:** 2026-08-21

**Status:** Proposed

**Extends:** ADR-Platform-037

**Related:** ADR-Platform-001, ADR-Platform-009, ADR-Platform-017, ADR-Platform-025, ADR-Platform-031, ADR-Platform-032

**Implementation:** OK-163, [`openkubes/ok-console`](https://github.com/openkubes/ok-console)

---

## Context

ADR-Platform-037 selects an opaque, revocable, server-side Console session but
deliberately leaves the production session store open. The first OK-163
implementation proves cookie, expiry, rotation, revocation, CSRF and
point-of-use authorization semantics with an in-memory store. That store is
useful executable evidence, but it loses revocation state on restart and cannot
coordinate multiple BFF replicas.

The production choice must work from a small single-cluster installation to an
HA management plane without turning a database into an authorization source.
It must also preserve OpenKubes' contract-first architecture: the Console
depends on session-store semantics, not directly on a particular operator or
managed database product.

## Decision drivers

- Revocation and rotation must be strongly consistent across BFF replicas.
- A successful write must not disappear silently during ordinary failover.
- Store unavailability must fail closed without falling back to local memory.
- Expiry correctness must not depend on asynchronous garbage collection.
- The design must minimize stored identity data and never store raw cookies or
  CSRF values.
- Recovery must not resurrect sessions from a backup.
- The reference profile should reuse an existing OpenKubes operational
  capability rather than require another stateful platform service.
- Laptop, edge, bare-metal and cloud deployments must retain implementation
  freedom behind one behavioral contract.

## Decision

OpenKubes defines a **Console Session Store port** and selects **PostgreSQL as
the first production reference profile**. The reference profile consumes the
database lifecycle and Evidence semantics of ADR-Platform-032 where that
capability is available. An external PostgreSQL service may satisfy the same
profile; CloudNativePG is a forcing implementation, not part of the Console
contract.

The in-memory implementation remains permitted for deterministic tests and an
explicit local-development mode only. It MUST NOT be enabled as a production
fallback.

### 1. Store port

The BFF owns a technology-neutral asynchronous port with these semantic
operations:

| Operation | Required semantic |
|---|---|
| `create` | Insert one new opaque-reference digest with bounded idle and absolute expiry; collision fails closed |
| `resolve` | Return one current context or absence; expiry, revocation and deployment epoch are checked atomically, and the stored authorization revision is returned for point-of-use validation |
| `touch` | Advance idle expiry no further than absolute expiry and only after successful point-of-use authorization |
| `rotate` | Replace the old reference and CSRF digest with new values in one transaction; never leave both usable |
| `revoke` | Mark the session unusable before reporting success; repeated revocation is idempotent |
| `purgeExpired` | Delete bounded batches of terminal rows without carrying authorization meaning |

Every BFF replica uses the same authoritative store. Session reads and writes
MUST use a read/write primary or an equivalently strongly consistent endpoint;
an asynchronously replicated read path is not sufficient for revocation.

### 2. PostgreSQL reference profile

The PostgreSQL adapter uses a dedicated database or schema and a dedicated
least-privilege role. It MUST NOT share tables or ownership with the identity
provider even when both consume one physical PostgreSQL cluster.

Creation uses a unique digest key. Resolution and idle touch use a conditional
statement that checks revocation and both expiry bounds using database time.
Rotation locks the old row and performs insert-new plus invalidate-old in one
transaction. Revocation is a conditional update. Implementations may use
`RETURNING` to make the committed result the only success response.

The adapter MUST NOT use a read replica for authorization decisions. Connection
pooling is optional and profile-specific; it does not change transaction or TLS
requirements.

### 3. Minimal record and cryptographic custody

The logical record contains only what the session boundary needs:

- SHA-256 digest of the opaque session reference as the lookup key;
- encrypted authorization context with internal subject ID, trusted provider
  join, scope, permissions and assurance;
- CSRF digest, never the raw CSRF value;
- issued, idle-expiry and absolute-expiry timestamps;
- authentication method, authorization-mapping revision and deployment session
  epoch;
- revocation timestamp and normalized revocation reason where present; and
- encryption key identifier and schema version.

The raw session cookie, raw CSRF value, password, authorization code, PKCE
verifier and reusable OIDC token MUST NOT be stored in the session table.
Provider token custody, if later required for refresh or provider logout, is a
separate encrypted server-side boundary referenced by a non-secret identifier.

The authorization context is envelope-encrypted before it crosses the store
port. Encryption keys come from the accepted Secret Contract and are not stored
in the session database or its backups. Key rotation must support a bounded
read-old/write-new interval; an unknown or unavailable key fails closed.

### 4. Expiry, mapping freshness and cleanup

Database time is authoritative for store predicates so BFF pod clock skew does
not extend a session. The BFF still validates the returned contract before use.

Expiry is a read-time security check. Background deletion only reclaims space;
a delayed cleanup job MUST NOT make an expired row usable. Cleanup operates in
bounded batches over indexed terminal timestamps.

A stored permission snapshot is not permanent authority. Each session carries
an authorization-mapping revision. A point-of-use evaluator must confirm that
the revision is current or obtain a current mapping; removal, ambiguity or
unknown freshness fails closed. A membership or privilege change revokes or
rotates affected sessions according to policy.

### 5. Failure, failover and recovery

- Store timeout, connection failure, schema incompatibility, decryption failure
  or ambiguous commit returns a bounded unavailable response. The BFF does not
  reuse cached authorization and does not create a local replacement session.
- Logout is not reported successful until revocation commits. The browser may
  still clear its local cookies after an unavailable response, but that is not
  evidence that a stolen reference was revoked.
- PostgreSQL HA policy must state whether acknowledged commits can be lost. A
  profile claiming revocation durability must provide synchronous-commit and
  failover evidence appropriate to that claim.
- Database restore, point-in-time recovery or environment clone invalidates all
  restored sessions before Console traffic resumes. The recovery ceremony
  advances a session epoch and rotates the envelope key, then purges restored
  rows. Operators reauthenticate.
- Session rows are not business records and are not a recovery objective.
  Authentication Evidence is written to its separate authoritative store.

### 6. Security and operational profile

The production profile requires:

- TLS with verified server identity between BFF and PostgreSQL;
- a dedicated credential delivered and rotated through the accepted Secret
  Contract;
- network policy limiting database access to the BFF workload identity;
- schema migrations with explicit forward/backward compatibility and no
  automatic destructive migration at request startup;
- statement and connection timeouts, bounded pools and backpressure;
- metrics for latency, errors, active/expired counts, cleanup lag, revocations
  and key/schema versions without session or subject identifiers; and
- negative logging and support-bundle tests for cookies, CSRF values, decrypted
  contexts and database credentials.

### 7. Deployment profiles

The contract does not require every OpenKubes deployment to run CloudNativePG.

| Profile | Allowed implementation | Claim |
|---|---|---|
| test/local development | in-memory adapter | deterministic evidence only; restart invalidates all sessions |
| single-node production | conforming PostgreSQL service, including a bounded local instance | durable restart semantics; no HA claim without replicas and evidence |
| HA management plane | PostgreSQL with a proven strongly consistent write/failover profile | cross-replica revocation and rotation |
| external/managed database | conforming PostgreSQL endpoint | provider-specific operation remains outside the Console contract |

A future store implementation may be added without changing the browser or
session contract only after it passes the same conformance and failure suite.

## Normative invariants

- **INV-038-1 — Digest-only lookup.** Raw session and CSRF values never cross
  the store port.
- **INV-038-2 — One authority path.** All BFF replicas resolve against one
  strongly consistent session authority; read replicas cannot authorize.
- **INV-038-3 — Atomic rotation.** Rotation never makes both old and new
  references usable and never loses the old reference on a failed transaction.
- **INV-038-4 — Expiry at read time.** Cleanup delay cannot extend a session.
- **INV-038-5 — No fallback expansion.** Store failure never creates or accepts
  an in-memory production session.
- **INV-038-6 — Restore invalidates.** Recovery cannot resurrect a previously
  usable session.
- **INV-038-7 — Stored permissions are not authority.** Current mapping and
  point-of-use policy still govern every protected request.
- **INV-038-8 — Evidence is separate.** Session storage is not the
  authentication or operation Evidence store.

## Consequences

### Positive

- The Console reuses the PostgreSQL capability already exercised by OpenKubes
  instead of introducing a mandatory Valkey/Redis operational stack.
- Transactions provide a direct, reviewable model for rotation and revocation.
- BFF replicas can remain stateless with respect to authenticated sessions.
- The store port preserves future deployment and implementation profiles.
- Recovery behavior is explicit: security wins over preserving user sessions.

### Costs and risks

- PostgreSQL adds network latency to every authenticated request and needs
  bounded connection management.
- Application-layer encryption introduces key lifecycle and rotation work.
- HA claims depend on the selected PostgreSQL replication and failover profile;
  an operator installation alone is not Evidence of durability.
- A database outage signs no one in and prevents protected access. This is the
  intended fail-closed behavior but requires an operational recovery path.
- Small deployments still carry a database footprint unless a future adapter
  earns a constrained production profile.

## Alternatives considered

### Valkey as the default

Not selected as the baseline. Native TTLs and atomic scripts are attractive,
but Valkey introduces another stateful capability and its normal replication is
asynchronous. Even acknowledged writes can be lost during failover depending on
persistence and topology. A future Valkey profile remains possible if it proves
durable revocation, atomic rotation, failover behavior, encryption, recovery
invalidation and the complete store conformance suite.

### Stateless signed browser sessions

Rejected for the primary Console boundary because immediate revocation,
privilege-removal propagation and server-side provider-token custody become
harder. Short expiry does not substitute for revocation.

### Kubernetes Secrets or custom resources per session

Rejected. High-churn session data would burden the Kubernetes API and etcd,
expand RBAC and watch exposure, and confuse desired-state resources with a
security session database.

### Identity-provider session as the Console session

Rejected. Provider authentication state does not contain OpenKubes scope,
authorization revision or operation policy and would couple the Console to one
provider's availability and session model.

### In-memory production sessions with sticky routing

Rejected. Sticky routing does not provide restart durability, fleet-wide
revocation, safe rolling updates or failover semantics.

## Required acceptance evidence

Before the PostgreSQL profile is production-accepted, OK-163 or a successor must
provide:

1. a store-port conformance suite run against real PostgreSQL;
2. concurrent rotate/revoke/resolve race tests proving the atomic invariants;
3. BFF restart and multi-replica tests without session loss or split authority;
4. primary failover tests with an explicit acknowledged-write-loss verdict;
5. database outage and ambiguous-commit tests proving no memory fallback;
6. expiry and cleanup tests using database time;
7. envelope-key rotation and unavailable/unknown-key negative tests;
8. recovery or clone rehearsal proving all restored sessions are invalidated;
9. authorization-mapping removal and stale-revision tests; and
10. redaction tests for SQL errors, logs, metrics, Evidence and support bundles.

## Non-goals

This ADR does not select an OIDC library, identity provider, PostgreSQL operator,
managed database vendor, schema migration tool, connection pooler, Secret
implementation or backup product. It does not make ADR-032 delivery evidence
stronger, turn the database into an authorization source, or accept the current
in-memory adapter for production.

## References

- [PostgreSQL transactions and explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html)
- [PostgreSQL `INSERT ... ON CONFLICT ... RETURNING`](https://www.postgresql.org/docs/current/sql-insert.html)
- [CloudNativePG operator capability levels](https://cloudnative-pg.io/documentation/current/operator_capability_levels/)
- [CloudNativePG automated failover](https://cloudnative-pg.io/documentation/current/failover/)
- [CloudNativePG connection pooling and TLS](https://cloudnative-pg.io/documentation/current/connection_pooling/)
- [Valkey replication safety](https://valkey.io/topics/replication/)
- [Valkey persistence modes](https://valkey.io/topics/persistence/)
