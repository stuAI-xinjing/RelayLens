# Threat model

## What a gateway can fake

- The `model` field and `/models` catalog.
- Accepted request fields while ignoring their semantics.
- A generic text response that mentions a requested tool without actually making a typed call.
- A single good response while routing other requests to a different backend.
- A short-term behavior profile that changes after publication.

## What this harness can observe

- Protocol acceptance, schema and error behavior.
- Typed function-call and multi-turn tool output behavior.
- Repeatable task outcomes on fresh prompts.
- Usage/reasoning-token fields when the provider exposes them.
- Latency and streaming first-token timing.

## What it cannot establish

- The private upstream model weights or hardware.
- That two providers use the same checkpoint.
- That a provider will keep the same backend tomorrow.
- A cryptographic identity without provider-side attestation or a trusted fingerprint.

## Public repository and adaptive providers

The default suite is useful as a reproducible smoke suite, but its source is public. A provider
that reads the repository can recognize its templates or add a special route for them. Encrypting the
repository helps protect files at rest; it does not protect prompts after the audit client sends them
for evaluation.

For higher-stakes checks, keep an operator-owned holdout suite outside the public repository and
load it with `--suite-module`. Use fresh random seeds, per-run tool schemas, rotating task families
and local unseen graders. The report records a suite commitment hash so paired runs can prove they
used the same local suite without publishing its prompts.

See [anti-adaptation guidance](anti-adaptation.md) for the operating procedure.

## Operational precautions

- Use a throwaway or limited-scope key for audits.
- Never place a key in a command line, repository, issue, screenshot or CI log.
- Treat third-party endpoints as untrusted; do not send private prompts or files.
- Inspect `--public-out` before publishing it.
- Respect provider rate limits, terms and billing.
