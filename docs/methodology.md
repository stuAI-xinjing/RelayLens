# Methodology

## Question being tested

RelayLens tests whether an endpoint's observable behavior is compatible with a declared model and with a trusted reference endpoint under the same conditions. It does not attempt to discover private routing or claim a probability of model identity.

## Hypotheses

- **Capability comparison:** does the candidate's paired task loss exceed the preselected operational margin?
- **Within-margin evidence:** is an upper bound on the fraction of regressing unique prompts below that margin?
- **Behavior distribution comparison:** is there evidence of a categorical response-distribution shift under matching sampling settings?

These are different questions with different statistics. Failing to detect a shift is not an equivalence test. A gateway can route by request, imitate a response schema, or change its backend later.

## Test layers

1. **Transport:** DNS/TLS/HTTP outcome, status class, response decoding, redirect policy and latency.
2. **Catalog:** whether `/models` lists the requested identifier. This is a claim by the gateway, not an identity proof.
3. **Parameter contract:** each requested reasoning effort is sent as a separate request and its status/error is retained. Accepted input does not prove that the setting was honored internally.
4. **Task behavior:** every case has a version, seed-derived prompt, prompt hash, expected result and deterministic grader. Code tasks run the candidate expression in a tiny AST interpreter against unseen boundary cases; model-generated code is never executed.
5. **Tool workflow:** the model must request the declared tool, receive its result, and use the result in a second turn. Responses items are replayed in order; this preserves reasoning/function-call context required by the Responses protocol.
6. **Reference comparison:** only matching suite version/commitment, seed, API style, task settings, task IDs, families and prompt hashes are paired. The target-specific verdict requires matching targets; the panel compares separately named GPT/Claude anchors. Parameter-probe lists and fingerprint counts do not change task calls. Failures and truncation count as task failures. An operator must verify reference provenance; imported trust metadata is ignored. Duplicate graded IDs, non-boolean grades, inconsistent completion evidence and matching nonempty run IDs are rejected.
7. **Stability:** repeat exactly the same tasks with shuffled order. Same-task pass/fail flips and returned-name changes are reported as weak signals. Sampling, rate limits and caching can also cause them; a stable trace cannot rule out a router.
8. **Behavior distributions:** optional repeated categorical prompts support per-cell Jensen-Shannon divergence and permutation tests. At least 20 successful samples on each side are required for a tested cell, with a Bonferroni correction across cells. The prompts/settings must agree. No universal identity threshold is borrowed from another dataset.

## Why generated tasks

Public static questions can be memorized or optimized against. Each run generates fresh arithmetic values, nonce-bearing strict instructions, unique ordering constraints and unseen code-check inputs from the seed. The prompt hash allows another investigator to verify that the candidate and reference saw the same case without publishing sensitive prompt text.

The standard suite has eight families; the challenge pack retains them and adds six procedural families with exact solvers. Frontend asynchronous reducers and backend transactions extend engineering coverage without executing arbitrary generated apps. Context records include multiple versions and positions across the input. The label "challenge" denotes construction complexity, not empirically established difficulty for a model. Neither pack is a secret. For an adaptive provider, operators can
load a private suite with `--suite-module`. The runner records its version and SHA-256 commitment,
while prompt copies are omitted from public reports. This commitment records which local file was used; it cannot hide
plaintext prompts from the gateway receiving them. Per-run tool names and fresh seeds reduce fixed-pattern
routing, but no client-side randomization proves model identity.

## Statistical interpretation

Pass rates are estimates over this suite, not general intelligence scores. Wilson intervals for family counts are descriptive: repeated attempts are correlated, so they must not be interpreted as independent new questions. Paired bootstrap intervals cluster all repetitions of each unique task. At least 30 unique paired tasks are needed for a calibrated comparison.

For each distinct prompt, average reference-minus-candidate success across its repeated pairs. These losses lie in [-1,1]. The one-sided lower bound is `mean_loss - sqrt(2*log(1/alpha)/n)` (Hoeffding). A deficit label requires this bound to exceed the margin both for end-to-end results and for at least 30 unique prompts where both endpoints completed; otherwise an end-to-end deficit is marked service degradation. Complete-case comparisons can have selection bias and are explicitly not a substitute for end-to-end results.

Within-margin evidence requires the one-sided exact Clopper–Pearson upper bound on the fraction of prompts with positive mean loss to be no larger than `--loss-margin` (default 0.10). This sufficient condition ignores gains and loss sizes. Bootstrap intervals are descriptive only. The binomial interpretation assumes representative, independent prompt clusters and comparable repeat sampling; generated families are not a random sample of all intelligence tasks. Correlated templates, caching, adaptive routing and post-hoc selection weaken these assumptions. No population-wide IQ inference is justified.

The nominal one-sided alpha is .05. A panel divides it by the number of distinct reference reports attempted (Bonferroni); identical serialized reference reports are deduplicated. Multiple matching models remain ambiguous. For a target with multiple supplied runs, the target verdict requires all runs to be usable and consistent instead of selecting a favorable run. More anchors and smaller deficits require more independent prompts. At least 30 is a minimum, not a guarantee of power.

A reference must complete >=95% of graded attempts, pass >=50%, and complete the tool round trip where the official protocol supports it. These are explicit operational quality checks, not model IQ thresholds. GPT-6 Astra / GPT-6.1 Sol Chat tool unavailability is documented; the tool probe is retained but its success is not a requirement in this configuration. The report separates all-attempt accuracy, completed-only accuracy, format-only failures and every-repeat success.

Fingerprint comparisons require nonempty observed text and compatible sampling settings. Public exports deliberately omit text and therefore cannot produce a fingerprint match. Bonferroni correction also applies across fingerprint cells within the reference alpha; 400 permutations have a minimum resolvable p of .0025, which can make large panels inconclusive. Identical answers or cached requests do not establish independent draws. Do not interpret p-values or JSD as identity probabilities.

Timing is separated by task family and successful response, with median, nearest-rank P95, MAD and visible-text first-token time. Network, caching, queueing, thinking budgets and output length confound it. Style features are prompt-sensitive descriptions and do not influence model identity claims.

## Optional numeric behavior probes (0.5.1)

`--numeric-samples N` adds N independent requests, separate from task repetitions. The seed generates bilingual prompts requesting 224–320 integers in [1,355]. Each complete response must be an exact JSON integer array of the requested size. Refusals, prose, truncation, booleans, floats and out-of-range values remain recorded as invalid, never parsed into convenient subsets.

A response has six equally weighted square-root frequency blocks: 355 values, 10 last digits, and 16 bins for each of four position quarters, with 0.5 smoothing. The fixed kernel averages `exp(-squared_distance / scale)` for scales 0.05, 0.2 and 1.0. For paired responses a_i, b_i, H_ij = k(a_i,a_j)+k(b_i,b_j)-k(a_i,b_j)-k(b_i,a_j); the statistic is the mean H_ij over i != j. We swap entire responses within each prompt pair 1,999 times and use `(1 + number >= observed) / 2000`. One test covers all features, with alpha .05 divided by distinct reference reports. This family is separate from capability and categorical tests, not an omnibus identity test.

At least 30 complete pairs and >=95% valid responses on each side are required; failure counts remain visible. This threshold is an operational minimum, not a calibrated power guarantee. Validity assumes independent request pairs, exchangeability within an honest pair, and non-selective missingness. Prompt heterogeneity is preserved by paired swaps. Cached, correlated, response-dependent failures or temporally changing responses can violate assumptions. Public exports lack raw answers and cannot recompute this test. Numeric settings do not invalidate existing capability comparisons.

Before relay interpretation, run independent official-versus-official controls with the same frozen settings. Avoid choosing a seed, sample size, reference or threshold after seeing results. Repeated peeking is not corrected. Significant changes can have benign causes; no detected change is not equivalence. No mixing rate is inferred because that requires calibrated reference and substitute distributions and a routing model. This feature borrows numeric-preference motivation from lm-detector, not its classifier or bank, and does not reproduce the separate KBF factual-recall protocol.

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
- [API substitution audit](https://arxiv.org/abs/2504.04715): evaluates limits of software-only checks and stronger provider-side attestation approaches.
- [Framework review and adoption decisions](research-review.md): Reasoning Gym, Inspect, Promptfoo, EvalPlus and dedicated fingerprint tools.

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
