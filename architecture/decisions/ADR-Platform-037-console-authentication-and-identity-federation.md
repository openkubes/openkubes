# ADR-Platform-037: Console Authentication, Identity Federation, and Break-glass Access

**Date:** 2026-08-21

**Status:** Proposed

**Extends:** ADR-Platform-036

**Extended by:** ADR-Platform-038

**Related:** ADR-Platform-001, ADR-Platform-017, ADR-Platform-025, ADR-Platform-030, ADR-Platform-034, ADR-Platform-035

**Prototype:** OK-154, [`openkubes/ok-console`](https://github.com/openkubes/ok-console)

---

## Context

The OpenKubes Console needs an authentication entry before it can become a real
operator surface. OpenKubes may run on a laptop, disconnected edge, bare metal, or in
cloud environments. Some installations have an established enterprise identity
provider; a new or recovering installation may temporarily have no working federation.

The Console also sits in front of operations whose authority is intentionally governed
by Contracts, Policy, point-of-use authorization, execution boundaries, and Evidence.
Successful authentication cannot be allowed to collapse those controls into a single
UI login decision.

The first Console remains a frontend-only prototype. OK-154 validates the signed-out
experience and the distinction between federated and exceptional local access. It does
not select an identity product, introduce an account database, create a token or cookie,
or establish a production security boundary.

## Decision drivers

- Make standards-based federation the normal operator experience.
- Support initial bootstrap and explicitly controlled recovery when federation is not
  yet available.
- Keep authentication, identity mapping, authorization, operation authority, and
  execution separate.
- Avoid exposing credentials or bearer tokens to browser JavaScript or browser storage.
- Avoid revealing fleet, Cluster, tenant, user, or infrastructure information before a
  session is established.
- Work across connected, sovereign, edge, and potentially disconnected deployments.
- Produce redaction-safe, correlation-ready authentication Evidence.
- Keep the first graphical prototype useful without implying production authentication.

## Decision

The OpenKubes Console adopts **federated identity by default** using OpenID Connect
(OIDC). A local identity path is retained only for controlled bootstrap and break-glass
access. The two paths are not presented or operated as equivalent everyday login
methods.

The conceptual boundary is:

```text
Identity provider or local verifier
                 |
                 v
        authenticated subject
                 |
                 v
     OpenKubes identity mapping
                 |
                 v
 server-side authorization and Policy
                 |
                 v
 review -> Authority -> execution -> Evidence
```

Authentication answers **who is present and with what assurance**. It does not answer
whether that subject may view a tenant, approve a Contract, invoke an operation, expand
authority, or execute a mutation.

### 1. Federated OIDC is the primary path

A production web Console MUST use the OIDC Authorization Code Flow with PKCE. PKCE MUST
use the `S256` challenge method. The implementation MUST NOT use the implicit flow or
place access, refresh, or ID tokens in URL fragments.

The server-side authentication boundary MUST validate at least:

- exact issuer and configured discovery or metadata provenance;
- signature and accepted algorithms;
- audience and authorized party where applicable;
- expiry, issued-at, and not-before constraints with bounded clock skew;
- cryptographically random `state` and `nonce` values bound to the initiating session;
- the exact registered redirect URI; and
- the PKCE verifier corresponding to the original challenge.

Provider discovery is configuration, not ambient trust. An arbitrary issuer supplied by
a browser, tenant field, email domain, or token claim MUST NOT become a trusted provider
without an accepted server-side trust configuration.

Provider passwords, MFA secrets, recovery codes, and private authentication material
MUST remain at the identity provider and MUST NOT be collected by the Console.

### 2. Browser session boundary

The preferred production shape is a Backend-for-Frontend (BFF) or equivalent
server-side session boundary. OAuth and OIDC tokens remain server-side. The browser
receives only an opaque, revocable session reference in a cookie with appropriate
`Secure`, `HttpOnly`, and `SameSite` attributes.

The production implementation MUST:

- avoid access, refresh, and ID tokens in `localStorage`, `sessionStorage`, IndexedDB,
  readable cookies, URLs, telemetry, or client logs;
- bind sessions to the intended Console origin and deployment context;
- enforce short idle and absolute expiries appropriate to assurance and access method;
- rotate the session identifier after authentication and privilege-relevant changes;
- protect state-changing browser requests against CSRF in addition to SameSite policy;
- support server-side revocation and provider-driven logout where the provider allows
  it; and
- prevent caches from storing authenticated or identity-bearing responses.

Exact cookie names, expiry durations, BFF technology, token store, and key-management
implementation are deferred to a production authentication design and threat model.

### 3. Identity mapping is not authorization

OIDC claims are inputs to a reviewed OpenKubes identity mapping. They do not directly
grant operation authority.

The mapping MUST use a stable provider-scoped subject identity such as the tuple of
trusted issuer and `sub`. Email address, display name, group name, or other mutable
human-readable claims MUST NOT be the sole durable identity key.

Group or role claims MAY inform server-side role bindings when an accepted mapping
policy defines their issuer, namespace, semantics, freshness, and removal behavior.
Unrecognized, missing, stale, ambiguous, or conflicting mappings MUST fail closed.

Just-in-time user creation, tenant membership, group synchronization, and service
identities require explicit follow-up decisions. Authentication success alone MUST NOT
create platform membership or a privileged role.

### 4. Local identities are bootstrap and break-glass only

Local access has two explicit operational purposes:

1. **Bootstrap** — establish the first controlled administrative identity before a
   federated provider has been configured and verified.
2. **Break-glass** — recover access during a declared federation outage or identity
   incident under an approved operational procedure.

Local access MUST NOT become a silent permanent fallback for ordinary use. A deployment
MUST be able to disable bootstrap and break-glass independently. Bootstrap SHOULD close
after federation is verified. Continued break-glass capability requires an explicit
owner, periodic test, credential rotation, and reviewable recovery procedure.

A production local verifier MUST:

- verify credentials only at the server-side authentication boundary;
- store passwords using a current, memory-hard password hashing scheme with unique
  salts and deployment-reviewed parameters;
- never log, echo, recover, export, or return a password to the browser;
- enforce rate limiting, progressive delay or lockout controls, and abuse monitoring;
- require MFA where the deployment can sustain it;
- use named, attributable identities rather than a shared generic administrator;
- issue a shorter-lived session than the normal federated path;
- require an operational reason for break-glass use; and
- emit a high-signal audit and Evidence event for every attempt and outcome.

Recovery of local access MUST NOT depend solely on the unavailable Console or the same
identity provider being recovered. The exact offline recovery, secret custody, quorum,
and hardware-backed mechanisms require a separate operational security design.

### 5. No protected disclosure before authentication

Before a valid session exists, the Console MAY display only public product identity,
configured sign-in choices, a non-sensitive environment label, accessibility and legal
links, and generic operational guidance.

The signed-out surface MUST NOT expose:

- Cluster, node, provider, region, tenant, namespace, workload, Capability, or finding
  inventory;
- user enumeration, privileged role names, membership, or account existence;
- private Evidence, readiness, incident, or policy state; or
- provider configuration secrets, internal callback details, or diagnostic errors that
  reveal trust configuration.

Authentication failures SHOULD be useful to the operator without becoming an account,
provider, or configuration enumeration oracle.

### 6. Authorization remains server-side and point-of-use

The Console MAY hide or disable controls for usability, but the rendered UI is not an
authorization boundary. Every protected read and every state-changing operation MUST be
authorized server-side against the current subject, tenant or scope, requested object,
operation, Policy, and current system state.

For state-changing flows, the Console continues to preserve ADR-036's sequence:

```text
Draft -> Review -> Authorization -> Execution -> Observation -> Evidence
```

The login session MUST NOT carry an implied approval for a later request. Elevated,
destructive, or especially sensitive operations MAY require recent authentication,
step-up assurance, separation of duties, or a new authorization decision. Those
requirements belong to the applicable operation Contract and Policy.

### 7. Authentication Evidence and privacy

Authentication events MUST be correlatable with later authorization and operation
Evidence without embedding credentials or reusable tokens.

A redaction-safe event SHOULD identify at least:

- deployment and environment identity;
- internal subject identity and trusted provider identifier;
- authentication method and assurance class;
- outcome and normalized failure category;
- session correlation identifier or non-reusable digest;
- timestamp and relevant freshness or expiry;
- break-glass reason and approval reference when applicable; and
- revocation, logout, timeout, or termination outcome.

Raw tokens, authorization codes, PKCE verifiers, cookies, passwords, recovery material,
and unnecessary personal claims MUST NOT appear in Evidence, application logs,
telemetry, browser diagnostics, screenshots, or support bundles.

Retention, access, redaction, and deletion of identity-related Evidence MUST follow the
applicable privacy, security, and audit policy. Evidence visibility does not imply that
all operators may inspect all authentication events.

### 8. Failure and degraded operation

Federation failure MUST fail closed for new federated sessions. The Console MUST
distinguish an unavailable provider from invalid credentials without exposing sensitive
diagnostics to an unauthenticated user.

Existing sessions MAY continue only within their accepted expiry and revocation model;
provider unavailability MUST NOT silently extend them. Cached identity or group claims
MUST NOT become indefinitely valid because federation is offline.

Break-glass access MAY be activated only when enabled by deployment policy and the
operational procedure. Activating it does not bypass authorization, Policy, review,
execution, or Evidence boundaries.

### 9. Prototype semantics

OK-154 implements a deterministic graphical simulation to validate this decision. The
prototype:

- presents configured OIDC choices as the preferred path;
- explains the redirect and secure-return boundary;
- renders an illustrative identity and session review;
- labels the local route as bootstrap or break-glass;
- requires a reason and explicit acknowledgement for the local route;
- keeps successful prototype session state only in React memory;
- clears entered password state before local session review;
- renders no protected fixture content until simulated sign-in succeeds; and
- supports an in-memory sign-out.

The prototype MUST NOT send an authentication request, discover a live provider,
validate a credential, issue or parse a token, create a cookie, persist session state,
or claim production assurance. Provider names, identities, assurance values, expiries,
and failure cases shown by the prototype are presentation fixtures only.

## Normative invariants

- **INV-037-1 — Federation first.** OIDC is the normal Console authentication path;
  local authentication is limited to explicit bootstrap or break-glass purposes.
- **INV-037-2 — Authentication is not authority.** A successful login MUST NOT by
  itself grant platform membership, approve a Contract, or authorize an operation.
- **INV-037-3 — Server-side token custody.** Reusable OAuth/OIDC tokens and local
  credentials MUST NOT be exposed to browser JavaScript or browser storage.
- **INV-037-4 — Stable identity join.** Durable identity mapping MUST use a trusted,
  provider-scoped stable subject, not email or display name alone.
- **INV-037-5 — No pre-auth disclosure.** Protected platform, tenant, fleet, and user
  data MUST NOT be rendered before a valid session exists.
- **INV-037-6 — Point-of-use authorization.** Every protected read and operation is
  independently authorized server-side against current scope and state.
- **INV-037-7 — Exceptional local access.** Local access is disableable, short-lived,
  attributable, rate-limited, reason-bound, and evidence-producing.
- **INV-037-8 — Redaction-safe Evidence.** Authentication Evidence MUST NOT contain
  credentials, reusable tokens, codes, verifiers, cookies, or unnecessary personal
  claims.
- **INV-037-9 — Failure does not expand access.** Provider outage, mapping ambiguity,
  stale claims, or unknown assurance MUST fail closed and MUST NOT extend authority.
- **INV-037-10 — UI is not enforcement.** Visibility, wording, disabled controls, and
  client state improve usability but MUST NOT be treated as security controls.

## Consequences

### Positive

- Enterprise and sovereign installations can use established standards-based identity.
- The browser is not required to hold reusable provider tokens.
- Bootstrap and federation-outage recovery remain possible without normalizing local
  passwords as the primary experience.
- Identity and later operation Evidence can be correlated without merging their
  authority semantics.
- The frontend prototype can validate the journey before a security-sensitive backend
  stack is selected.

### Costs and risks

- A production BFF, session store, revocation path, provider trust configuration, and
  operational key lifecycle must be designed and operated.
- Local recovery adds security and operational burden even when rarely used.
- Group and tenant mapping across providers requires explicit governance and lifecycle
  handling.
- Edge and disconnected deployments need a documented identity availability and
  recovery model rather than an assumed cloud dependency.
- The attractive prototype could be mistaken for implemented security unless its
  simulation boundary remains explicit.

## Alternatives considered

### Browser-held OIDC tokens

Rejected as the default because it expands the exposure of reusable bearer material to
browser JavaScript, extensions, dependency compromise, and storage mistakes. A future
alternative would require a separate threat model and accepted evidence.

### Local accounts as an equal login method

Rejected because it encourages long-lived parallel identity administration, weakens
federation governance, and makes exceptional recovery access appear routine.

### OIDC only, with no local recovery

Rejected for the general platform decision because bootstrap and some sovereign,
disconnected, or provider-outage recovery scenarios need an independent controlled
path. A deployment MAY disable local access after accepting its own recovery model.

### Authentication embedded in each Console backend API

Rejected because inconsistent token handling and duplicated identity mapping would make
assurance, revocation, audit, and authorization boundaries harder to reason about.

## Follow-up evidence required

Before production acceptance, a forcing implementation must provide at least:

1. a threat model covering browser, BFF, IdP, session store, callback, CSRF, XSS,
   dependency, logout, and recovery boundaries;
2. provider interoperability tests including key rotation and negative token cases;
3. session fixation, expiry, revocation, CSRF, cache, and logout tests;
4. identity and group mapping lifecycle tests, including removal and ambiguity;
5. local rate-limit, lockout, MFA, rotation, disablement, recovery, and audit evidence;
6. redaction tests for logs, telemetry, Evidence, errors, and support bundles;
7. accessibility and information-disclosure review of signed-out and failure states;
8. disconnected and provider-outage operational exercises; and
9. confirmation that state-changing operations still traverse their independent Policy,
   Authority, execution, and Evidence paths.

## Non-goals

This ADR does not select an identity provider, OAuth library, BFF framework, database,
session store, ingress product, secret backend, MFA mechanism, password hashing
parameters, hardware token, or account recovery implementation. It does not define a
general OpenKubes user or role Contract, authorize just-in-time membership, or accept
the OK-154 fixture vocabulary as a production API.

## Proposed amendment (2026-11-04): CLI-first local identity for ok-local

**Status:** Draft; conditionally reviewed, final amendment acceptance pending.
**Tracking:** [OK-214](https://kubernauts.atlassian.net/browse/OK-214).

### Scope and relationship to the original decision

This amendment proposes one explicit eligibility exception to the federation-first,
bootstrap/break-glass-only decision in sections 1 and 4 and INV-037-1: an explicitly
configured, non-production `ok-local` profile MAY authenticate ordinary named local
users without an external OIDC provider. It does not enable production local identity
or make ordinary local accounts an automatic fallback for federation failure.

The existing normative invariant text is retained verbatim. Its security protections
are not relaxed: authentication remains separate from authority; credentials remain
server-side; identity joins are stable; protected disclosure and operations require
current server-side checks; sessions are bounded and revocable; failures deny access;
and Evidence is credential-free. INV-037-7 continues to govern exceptional local
access, including its operational reason. Ordinary local accounts MUST use a distinct
authentication method and lifecycle, not be represented as Bootstrap or BreakGlass.

Existing OIDC, Bootstrap and BreakGlass behavior and guards MUST remain intact.
ADR-Platform-038 is unchanged, including its PostgreSQL session-store, separate
identity/session ownership, encryption, expiry, revocation and recovery requirements.

### Bounded implementation direction

The success condition is that a named administrator can create a local user through
an attended CLI and that user can sign in to the Console without Keycloak, Entra ID
or any other external identity provider. Extend the existing Console BFF and its
PostgreSQL-backed session system; do not introduce an identity service or OIDC issuer.

- The profile MUST be explicitly enabled server-side and restricted to a local,
  non-production deployment. A browser flag or profile label alone is insufficient;
  runtime and deployment checks MUST reject unsupported exposure or production use.
  Existing cookie, TLS and development-exception guards MUST NOT be weakened.
- An attended operator procedure MUST provision the first named administrator without
  public registration, default credentials or a shared administrator. Bootstrap MUST
  close after initialization, independently of whether federation is ever configured.
- An authenticated, authorized named administrator MAY create, list and disable local
  users through the CLI. Authorization MUST be rechecked at point of use. Secrets
  MUST use protected input, never command arguments, logs or ordinary command output.
  Account deletion and general role administration are outside this MVP.
- Local identity records MUST have immutable subject IDs and unambiguous normalized
  usernames. Accounts MUST store only salted, versioned password verifiers using
  maintained cryptographic primitives and reviewed, resource-bounded parameters.
- Login MUST use durable throttling, bounded credential processing and generic errors
  that do not distinguish unknown, disabled or incorrect-password accounts. Local
  login and startup MUST NOT depend on successful external OIDC discovery.
- The browser MUST receive only the existing opaque, hardened session cookies and
  redacted session projection. No credentials or session material may be persisted in
  browser storage. Ordinary-local method vocabulary requires explicit contract and
  consumer compatibility review; existing methods MUST retain their semantics.
- Enabled state and current account security revision MUST be verified for protected
  requests, session restoration and rotation. Disablement MUST revoke affected
  sessions and prevent concurrent login or rotation from leaving a usable session.
  Unavailable or unverifiable identity/session state MUST fail closed.
- Administrator disablement MUST be serialized so concurrent operations cannot remove
  the last active administrator. Account creation and disablement MUST commit with
  their audit records; login failures and recovery MUST also produce credential-free
  audit events. Required audit failure MUST deny the affected operation.
- Browser-originated state changes MUST enforce exact Origin and session-bound CSRF
  checks. CLI operations MUST independently authenticate and authorize the operator;
  a non-browser transport is not an authorization bypass.
- An attended offline recovery procedure MUST work without the Console UI or external
  OIDC, protect recovery custody, audit its use and invalidate affected sessions.
  Database restore MUST follow ADR-038's session invalidation procedure.

Local administrator status governs local-account administration only. Authentication
MUST NOT silently create platform membership, grant Kubernetes privileges or authorize
cluster operations. This MVP adds no Kubernetes RBAC assignments, multi-cluster
Projects, Project lifecycle, direct kubectl access, generic Kubernetes API proxy,
identity service, CRD or operator. Real Console user-administration UI is deferred;
the simulation remains explicitly separate and Developer Workspaces remain independent.

### CLI authorization and profile enforcement

The CLI MUST authenticate the named administrator through the BFF's ordinary local
login flow over verified HTTPS, using protected password input. It holds the existing
opaque session cookies and session-bound CSRF value in process memory only, then calls
fixed create/list/disable BFF routes; it MUST NOT receive database credentials, execute
SQL, use a privileged local socket or bypass authentication because it runs locally.
Each route MUST verify current session/account state and the explicit local-user
administration permission from authoritative server-side state. Create and disable
also require the exact configured Origin and session-bound CSRF value; list requires
the same administrator authorization. Browser UI visibility, client-supplied roles and
loopback location confer no permission. All routes remain unavailable outside this
profile; no unauthenticated account-management route is introduced.

First-admin initialization is the sole narrowly scoped setup transition: an attended
CLI uses an existing named Bootstrap session with an explicit initialization permission
to create the first ordinary local administrator. The BFF MUST atomically verify that
ordinary identity initialization has never completed, record its completion and audit
the creation. Replay or concurrent initialization MUST fail; absence of enabled users
MUST NOT reopen setup. The CLI still has no database access, and existing Bootstrap
credential verification and guards remain intact.

For this MVP, startup MUST require all of the following: an explicit server-side
ordinary-local enablement, profile `ok-local`, `NODE_ENV=development`, PostgreSQL
sessions, prototype authorization disabled, a numeric loopback BFF bind (`127.0.0.1`
or `::1`) and an exact HTTPS Console origin with a numeric loopback host. Missing,
unknown or conflicting values MUST reject startup before serving ordinary-local
routes. Neither a disposable-cluster acknowledgement nor proxy/Host headers may
override these checks. The HTTPS frontend MUST also bind only to loopback; it forwards
to the BFF on the same host or within the same Pod. CLI TLS verification MUST NOT be
disabled, and credential-bearing requests MUST NOT follow redirects to another origin.

Only a dedicated development deployment profile may set these options. Its rendered
configuration MUST reject Ingress/Gateway exposure, public proxies, NodePort or
LoadBalancer Services, host networking/host ports and non-loopback host-port publishing;
the BFF and TLS frontend have no Service exposure. A Pod-based lab may use an explicitly
loopback-bound port-forward to its TLS frontend. Rendered-profile checks and startup
negative tests MUST cover these restrictions, including rejection of production,
wildcard binds, public origins and disabled sessions. These checks constrain supported
configuration; they do not attest that a host/cluster administrator has not deliberately
republished the service. Ordinary local identity is unsupported in that configuration.

### Acceptance and delivery gates

Gate 1 is review and explicit acceptance of this amendment. Opening or merging a PR
alone MUST NOT be interpreted by an implementation agent as permission to start Gate 2;
the owner must explicitly approve that transition. Both PRs remain Draft until reviewed;
neither merge nor deployment is automatic.

After Gate 1 approval, Gate 2 targets 5–8 person-days for the CLI-first scope. Security
requirements take precedence over that estimate; any overrun or missing prerequisite
must be reported rather than addressed by weakening a guard. Acceptance evidence MUST
include the named-admin/create-user/login journey, negative authorization/CSRF and
redaction cases, disabled-user session rejection, real PostgreSQL login/disable/rotate
and last-admin concurrency tests, identity/session/throttle/audit outage tests, an
external-IdP-unavailable startup/login exercise, an offline recovery exercise and
regression tests for existing OIDC, Bootstrap and BreakGlass behavior.

Gate 2 MUST also demonstrate rejection of unauthenticated/non-admin CLI requests,
missing or invalid Origin/CSRF on mutations, replayed first-admin initialization and
the forbidden profile/exposure combinations above. Gate 1 verification is limited to
document consistency and preservation of the existing ADR text; runtime enforcement
and its test evidence remain unimplemented until Gate 2 is separately authorized.

This is a non-production local-development baseline, with MFA enrollment UI deferred
and no production assurance claim. Production ordinary-local identity requires a
separately accepted bootstrap, recovery, MFA and storage-security baseline and its
evidence; this amendment grants no production exception.
