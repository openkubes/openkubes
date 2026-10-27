# OK-141 Platform convergence cause diagnostic v1

The first redacted diagnostic proved that all three Applications resolve the
expected Git revision but remain `sync=Unknown` with identical error families.
Its broad `SOURCE-OR-RENDER` classification cannot distinguish repository and
manifest failures from failures loading the live target state.

This follow-up performs the same exact three read-only Application GETs and
derives stable cause indicators for target connectivity, TLS, authorization,
repository access, manifest generation and cache failures. Raw messages and
Application objects are never retained. It cannot retry or resume the Happy Run.
