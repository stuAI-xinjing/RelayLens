# Methodology

## Question being tested

RelayLens tests whether an endpoint's observable behavior is compatible with a declared model and with a trusted reference endpoint under the same conditions. It does not attempt to discover private routing or claim a probability of model identity.

## Hypotheses

- **H0 (compatible behavior):** the candidate and reference produce indistinguishable outcomes for the fixed, seeded cases and supported protocol features.
- **H1 (behavioral mismatch):** the candidate has materially different protocol, tool, parameter, latency, or task behavior.

The test can find evidence for H1. Failure to find a mismatch is weaker evidence for H0 because a gateway can route by request, imitate a response schema, or change its backend later.

## Test layers

1. **Transport:** DNS/TLS/HTTP outcome, status class, response decoding, redirect policy and latency.
2. **Catalog:** whether `/models` lists the requested identifier. This is a claim by the gateway, not an identity proof.
3. **Parameter contract:** each requested reasoning effort is sent as a separate request and its status/error is retained. Accepted input does not prove that the setting was honored internally.
4. **Task behavior:** every case has a version, seed-derived prompt, prompt hash, expected result and deterministic grader. Code tasks run the candidate expression in a tiny AST interpreter against unseen boundary cases; model-generated code is never executed.
5. **Tool workflow:** the model must request the declared tool, receive its result, and use the result in a second turn. Responses items are replayed in order; this preserves reasoning/function-call context required by the Responses protocol.
6. **Reference comparison:** only matching suite version, seed, API style and prompt hashes are paired. The report includes a case-cluster bootstrap interval for the candidate's pass-rate difference.

## Why generated tasks

Public static questions can be memorized or optimized against. Each run generates fresh arithmetic values, nonce-bearing strict instructions, unique ordering constraints and unseen code-check inputs from the seed. The prompt hash allows another investigator to verify that the candidate and reference saw the same case without publishing sensitive prompt text.

The built-in suite is a reproducible smoke suite, not a secret. For an adaptive provider, operators can
load a private suite with `--suite-module`. The runner records its version and SHA-256 commitment,
while the private prompts remain local. This commitment proves which local file was used; it cannot hide
plaintext prompts from the gateway receiving them. Per-run tool names and fresh seeds reduce fixed-pattern
routing, but no client-side randomization proves model identity.

## Statistical interpretation

Pass rates are estimates over this suite, not general intelligence scores. A Wilson 95% interval is shown for each task family. Paired bootstrap intervals summarize the observed candidate-reference difference at the case level. Small samples produce wide intervals; increasing rounds increases cost and precision together.

## Thresholds

RelayLens intentionally does not map an isolated score to “this is model X.” Its A/B/C/D labels describe evidence quality and behavioral mismatch, not an identity probability. A project may choose operational thresholds for its own deployment, but a public report should preserve the raw counts, intervals, suite version, seed, API style, timestamps, and errors.

## Reproduction record

Record:

- RelayLens version and source revision
- UTC start time
- API style and base URL host (keep private in a public report)
- model request string and route class
- suite version, seed and task rounds
- reasoning efforts and stream mode
- raw HTTP statuses, latency and usage fields
- reference report path and prompt-hash compatibility

Do not record API keys, cookies, authorization headers, private URLs, local paths or raw prompts in a public artifact.
