# Changelog

## 0.7.0

- Reoriented primary A/B/C/D ratings to useful task capability. The default eight-question screen can earn A without a reference; no model-specific IQ cutoff or probability is invented.
- Disclosed screening thresholds and coverage: A needs >=90% overall, >=75% per family, six families and four distinct challenge prompts; B >=75%, C >=50%, D <50%. Default complete runs map to 8 / 6–7 / 4–5 / 0–3 correct. Incomplete service and insufficient unique prompts remain separate.
- Preserve rigorous optional official comparisons: within-margin A and calibrated-deficit D retain their existing evidence requirements. Show screening versus reference evidence visibly next to the conclusion.
- Separate interface usability and identity/behavior signals from capability. Stronger task performance is accepted regardless of backend name or numeric drift; tool limitations remain explicit for tool-dependent uses.
- Keep eight-question/three-minute defaults and all advanced workflows. Record the new `capability-first-1` rating policy and report schema 0.9, with regression checks for accessible A, grade boundaries, repeat inflation, usable reference improvements and visible warnings.

## 0.6.0

- Simplified the default Windows flow to endpoint, target model, hidden key and Enter. Protocol aliases, full suites, repeats, fingerprints, routes and references remain in advanced settings.
- Added a coverage-based eight-question pack and bounded parallel collection: four workers, a 180-second default budget, at most 12 default requests. Partial results survive the deadline or Ctrl+C; unfinished tasks stay in accuracy denominators. High reasoning is retained.
- Stop reading SSE after its protocol completion marker rather than waiting indefinitely for the connection to close. Isolated workers also bound stalled reads and DNS resolution.
- Added actionable A/B/C/D labels and a separate incomplete state. D requires a trusted calibrated capability deficit; service failure is never D. Eight-question success yields B, not a fabricated identity probability.
- Put the conclusion, pass counts, elapsed time and next action first in HTML; collapse detailed statistics and hide unused numeric probes. Trusted numeric shifts flag an overall concern without altering capability scores.
- Preserve full CLI defaults and old sequential reference compatibility; compare concurrency explicitly for new task and numeric references. Keep private task graders in the parent process.
- Test all three protocols in full and fast modes, deadline cancellation with a live heartbeat stream, private suites, completion markers, grades, privacy and advanced controls. No live GPT/Claude model-identification accuracy is claimed.

## 0.5.1

- Reviewed lm.ikale.io / lm-detector, KBF, rank-based API auditing and token-count holdout research; documented applicable evidence and prerequisites without borrowing detection-rate claims.
- Added optional numeric-sequence probes through all three existing protocols. Frozen prompts/features, complete-array validation and request-level paired multivariate permutation tests avoid treating hundreds of dependent integers as independent calls.
- Added a separate numeric reference panel with per-panel multiplicity correction, strict prompt/configuration checks, invalid-response accounting and offline recomputation. Small samples, incomplete data and public reports without text cannot produce a numeric match claim.
- Kept capability grades independent of behavior signals. No identity probability, universal tokenizer mapping or estimated mixing percentage is emitted. Existing task comparisons remain compatible when numeric probes are absent.
- Extended the wizard, Chinese/English instructions and responsive HTML report. No new runtime dependencies, external fingerprint service or separate web backend.

## 0.5.0

- Added an opt-in 14-family challenge pack; the wizard selects it by default. New coverage includes constrained optimization/counting, exact probability, relational aggregation, versioned context, frontend async state and backend idempotent transactions.
- Added multi-model GPT/Claude reference panels and offline report comparison. Preserve overlapping matches, reject invalid/self/duplicate-ID references, and correct for multiple comparisons.
- Hardened evidence: cluster by prompt, use conservative bounded-loss and exact regression bounds, separate incomplete/service failures from completed-answer deficits, and expose repeat reliability and saturation warnings.
- Fixed typed JSON grading, duplicate keys/nonfinite values, short-circuit expression semantics, and tool false positives with exact typed results and a fresh receipt nonce.
- Hardened malformed/SSE completion handling, added the current Chat output-budget field with explicit legacy compatibility, and accounted for documented GPT Chat tool limitations without suppressing probes.
- Improved HTML readability and expanded public-export scrubbing of answers, expected values, error bodies, gateway aliases and egress metadata.
- Documented community framework selection, inference assumptions and the absence of live official-model calibration. No model-identification accuracy is claimed from software tests.

## 0.4.0

- Added an independent Windows wizard and responsive local HTML reports, with no pip requirement.
- Added native Claude Messages and SSE support, preserving tool context across all three wire APIs.
- Expanded the synthetic suite to eight families and added shuffled same-task repetitions, style/latency diagnostics and optional distribution fingerprints.
- Replaced uncalibrated per-target thresholds with paired reference checks, explicit provenance, sample-size requirements and conservative loss-margin evidence.
- Count failed/truncated attempts in accuracy and preserve streaming truncation state. Public reports remove answer text as well as credentials and local identifiers.
- Updated current GPT/Claude presets while retaining legacy IDs and custom aliases. Existing standalone flags remain compatible.

## 0.3.0

- Added explicit GPT and Claude target profiles for separating an operator's claimed model from observed behavior.
- Added conservative target metadata to audit reports and CLI summaries without treating it as proof of model identity.

## 0.2.0

- Generalized to Responses and Chat Completions compatible APIs.
- Added seeded generated task suite with exact, AST-based code grading.
- Added multi-turn tool result verification, streaming timing and usage capture.
- Added Wilson intervals, paired case-cluster bootstrap comparison and privacy scrubber.
- Removed provider-specific names, URLs and local environment assumptions.
