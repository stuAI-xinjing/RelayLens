# Changelog

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
