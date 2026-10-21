# RelayLens

Chinese quick start: [README.zh-CN.md](README.zh-CN.md)

RelayLens is a dependency-free, black-box audit harness for OpenAI-compatible gateways. It measures observable behavior and compatibility; it cannot prove a gateway's private upstream identity.

## What it tests

- `/models` catalog presence without treating the returned model name as proof.
- Responses API or Chat Completions API transport behavior.
- A declared reasoning-effort matrix, including explicit unsupported responses.
- Fresh seeded synthetic tasks: unique constraint logic, generated arithmetic, strict-format instruction following, and code-repair expressions tested by a local AST interpreter against unseen boundary cases. The built-in suite is reproducible and public; higher-value holdout suites can be loaded locally.
- A real multi-step function call: request a tool, return its result, and require the model to use the result.
- HTTP status, transport classification, latency, time to first streamed token, returned model, usage and reasoning-token fields when supplied.
- JSON reports with prompt hashes and task summaries, plus an optional scrubbed report for sharing.

## Install

Python 3.10+ is enough; there are no runtime dependencies.

```text
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e .
```

## Run

```text
relaylens --base-url https://gateway.example/v1 --model example-model --api-key %RELAYLENS_API_KEY% --out report.json --public-out report-public.json
```

When auditing a claimed GPT or Claude model, select the target explicitly. The
target records the provider claim; it does not turn a model name into proof:

```text
relaylens --base-url https://gateway.example/v1 --model gpt-6-astra --target-model gpt-6-astra --api-key %RELAYLENS_API_KEY%
```

Supported targets are GPT-6 Astra, GPT-6.1 Sol, GPT-6 Luna, GPT-5.6 Sol,
Claude Opus 5, Claude Sonnet 5, Claude Opus 4.8, Claude Opus 4.6, Claude
Sonnet 4.6 and Claude Haiku 4.5. The report keeps `model_requested` (what was
sent to the gateway) separate from `target_model` (what the gateway claims).

Use `--api responses` for Responses-compatible gateways or `--api chat` for Chat Completions gateways. `--route direct` bypasses environment proxies; `--proxy http://proxy.example:8080` selects an explicit HTTP proxy. Prefer `RELAYLENS_API_KEY` or interactive secret input; do not put keys in shell history or reports.

For a reproducible comparison, run candidate and reference with the same `--seed`, `--task-rounds`, API style, model prompt suite, and route policy. Compare task IDs, `prompt_hash`, `suite_version` and `suite_commitment`, not free-form prose. A result is not upgraded to an identity claim merely because scores are close.

For a private holdout suite, pass `--suite-module C:/private/path/private_suite.py`. The file must define `suite(seed, rounds)` and may define `SUITE_VERSION`. Keep it outside the public repository.

## Interpreting results

The harness deliberately reports separate dimensions:

1. **Transport/compatibility**: the request reached the endpoint, response schema was usable, and requested features were accepted.
2. **Task behavior**: exact or executable grading on fresh cases. Wilson intervals describe uncertainty when the number of cases is small.
3. **Reference similarity**: paired case differences only when prompt hashes and suite versions match.

The report labels evidence conservatively: **D** means unusable or missing the requested catalog/response, **C** means an independent protocol or task layer mismatched, **B** means healthy evidence without a trusted reference, and **A** means behavior was close to a trusted reference for this suite only. No label proves a private upstream identity. A gateway can imitate names, reject or silently ignore parameters, route requests to different backends, or change behavior over time. Publish the suite version, seed, API style, route class, timestamps, and raw HTTP evidence needed to reproduce the claim.

If `--target-model` is supplied, use a trusted official run with the same
target, seed, API style, reasoning setting and suite commitment as the
reference. A healthy response from a lower tier is not evidence that it is a
flagship target.

## Design basis

- OpenAI's Responses documentation defines reasoning configuration and typed function-call outputs; the tool continuation must preserve the returned items when the caller manually manages context.
- EleutherAI's evaluation harness separates task definitions, samples, filters and metrics; RelayLens follows the same separation for small provider audits.
- GSM-Symbolic motivates generated variants because memorized/static questions can overstate reasoning ability.
- Berkeley Function Calling Leaderboard motivates multi-turn and multi-step tool tests instead of checking only whether a tool name appeared.
- NIST's confidence-interval guidance motivates reporting uncertainty instead of presenting a small percentage as a precise capability estimate.

## Preventing test-specific adaptation

Do not treat encryption as a way to hide prompts from the gateway. The endpoint must receive the
plaintext to answer it, so it can still inspect and record the test. Encryption can protect a local
file at rest. For a stronger audit, keep a rotating holdout suite private, use fresh seeds, and let
RelayLens randomize the tool name and task order per run. The report includes a suite commitment hash
for paired-run integrity, but the hash is not a secret. See [anti-adaptation guidance](docs/anti-adaptation.md).

## Privacy and responsible use

The public-report path removes API keys, authorization values, full URLs, local paths, IP addresses and raw prompts. Inspect a report before publishing: the scrubber is defense in depth, not a substitute for human review. Use only keys you control, keep request volume within the provider's terms, and do not use the suite to bypass access controls.

## Limitations

This is a black-box behavioral audit, not cryptographic attestation. It cannot establish that two endpoints use the same weights, identify an undisclosed router, or guarantee future behavior. Add a trusted provider-side attestation or cryptographic fingerprint only when the provider offers one.

## References

- [OpenAI function calling](https://developers.openai.com/api/docs/guides/function-calling)
- [OpenAI Responses API reference](https://developers.openai.com/api/reference/resources/responses/methods/create)
- [EleutherAI lm-evaluation-harness](https://github.com/EleutherAI/lm-evaluation-harness)
- [GSM-Symbolic](https://machinelearning.apple.com/research/gsm-symbolic)
- [Berkeley Function Calling Leaderboard V3](https://gorilla.cs.berkeley.edu/blogs/13_bfcl_v3_multi_turn.html)
- [NIST confidence intervals](https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm)
- [Anti-adaptation guidance](docs/anti-adaptation.md)
