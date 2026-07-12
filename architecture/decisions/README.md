# Architecture Decision Records

Accepted ADRs are historical records. They are not silently rewritten when the architecture evolves.

## Changes to accepted ADRs

### Editorial changes

Editorial changes may be applied directly when they do not alter the decision or its consequences.

Examples:

- spelling and formatting fixes
- broken links
- incorrect ADR references
- removal of generation artifacts
- metadata corrections that do not change architectural meaning

### Extensions and clarifications

Material extensions or clarifications are recorded in a new ADR.

Use one of the following relationships:

- `Extends: ADR-Platform-XXX`
- `Clarifies: ADR-Platform-XXX`

The original ADR remains `Accepted`.

When a later ADR extends or clarifies an accepted ADR, a back-reference
(`Extended by: ADR-Platform-YYY` / `Clarified by: ADR-Platform-YYY`) may be
added to the original ADR's metadata. This is an editorial change.

### Superseding decisions

When a decision is replaced, the new ADR declares:

- `Supersedes: ADR-Platform-XXX`

The original ADR remains unchanged except for its status metadata:

- `Status: Superseded by ADR-Platform-YYY`

The original decision text is preserved as historical context.

## Relationships and the architecture graph

Relationships are part of the architecture graph and should be expressed in
ADR metadata using the exact keywords defined above.
