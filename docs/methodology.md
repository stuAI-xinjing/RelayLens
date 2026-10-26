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
6. **Reference comparison:** only matching target, suite version/commitment, seed, API style, complete settings, task IDs and prompt hashes are paired. Failures and truncation count as task failures. An operator must verify reference provenance; imported trust metadata is ignored.
7. **Stability:** repeat exactly the same tasks with shuffled order. Same-task pass/fail flips and returned-name changes are reported as weak signals. Sampling, rate limits and caching can also cause them; a stable trace cannot rule out a router.
8. **Behavior distributions:** optional repeated categorical prompts support per-cell Jensen-Shannon divergence and permutation tests. At least 20 successful samples on each side are required for a tested cell, with a Bonferroni correction across cells. The prompts/settings must agree. No universal identity threshold is borrowed from another dataset.

## Why generated tasks

Public static questions can be memorized or optimized against. Each run generates fresh arithmetic values, nonce-bearing strict instructions, unique ordering constraints and unseen code-check inputs from the seed. The prompt hash allows another investigator to verify that the candidate and reference saw the same case without publishing sensitive prompt text.

The built-in suite is a reproducible smoke suite, not a secret. For an adaptive provider, operators can
load a private suite with `--suite-module`. The runner records its version and SHA-256 commitment,
while the private prompts remain local. This commitment proves which local file was used; it cannot hide
plaintext prompts from the gateway receiving them. Per-run tool names and fresh seeds reduce fixed-pattern
routing, but no client-side randomization proves model identity.

## Statistical interpretation

Pass rates are estimates over this suite, not general intelligence scores. Wilson intervals for family counts are descriptive: repeated attempts are correlated, so they must not be interpreted as independent new questions. Paired bootstrap intervals cluster all repetitions of each unique task. At least 30 unique paired tasks are needed for a calibrated comparison.

The within-margin condition is conservative: the one-sided Wilson 95% upper bound (z=1.64485) on the fraction of unique tasks whose mean candidate score regresses relative to the reference must be no larger than `--loss-margin` (default 0.10). This ignores helpful gains and partial sizes of losses. A bootstrap interval merely including zero never establishes equivalence. A reference with mostly failures or a failed tool-result round trip is unusable for upgrading the label. These descriptive results depend on the generated suite, whose tasks are not a random sample of all intelligence tasks.

Timing is separated by task family and successful response, with median, nearest-rank P95, MAD and visible-text first-token time. Network, caching, queueing, thinking budgets and output length confound it. Style features are prompt-sensitive descriptions and do not influence model identity claims.

## Thresholds

RelayLens intentionally does not map an isolated score to “this is model X.” Its A/B/C/D labels describe evidence quality and behavioral mismatch, not an identity probability. A project may choose operational thresholds for its own deployment, but a public report should preserve the raw counts, intervals, suite version, seed, API style, timestamps, and errors.

There are no hand-invented per-model IQ cutoffs. The 50% basic-suite warning is a smoke-test warning, not an official GPT/Claude benchmark. Current model presets describe claims and API configuration only. The public suite can be too easy for current frontier models, and an adaptive provider can route recognized probes to its strongest backend. Use private harder suites and tests across different times to increase coverage.

## Research and implementation sources (checked 2026-10-26)

- [OpenAI evaluation guidance](https://developers.openai.com/api/docs/guides/evaluation-best-practices): scoped repeatable tests and calibrated grading.
- [OpenAI model catalog](https://developers.openai.com/api/docs/models) and [Claude model catalog](https://platform.claude.com/docs/en/models/overview): current target IDs and reasoning support; availability still depends on the account.
- [Claude Messages reference](https://platform.claude.com/docs/en/api/messages/create): native tool-use and tool-result context.
- [lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness): separation of tasks, reproducible configuration and evaluation results. No external benchmark score is converted to an IQ claim here.
- [llm-fingerprint-detector](https://github.com/ToseaAI/llm-fingerprint-detector): repeated categorical outputs and JSD as an empirical distribution signal. RelayLens uses its own probes/tests and does not import its model-specific thresholds or reference data.
- [Fingerprint spoofing research](https://arxiv.org/abs/2606.16100): weaker models can be tuned to evade representative fingerprint methods. This is why behavior similarity never becomes a verified-weight claim.

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
