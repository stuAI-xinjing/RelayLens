# RelayLens

A standalone, standard-library Python audit tool for GPT and Claude gateway claims. It combines fresh deterministic tasks, tool round trips, repeated trials, categorical response fingerprints and latency diagnostics. Python 3.10+; no runtime dependencies.

[中文完整使用说明](README.zh-CN.md)

## Run

On Windows, double-click `start.cmd`. Or run directly without installing:

```text
python run_relaylens.py --interactive
python run_relaylens.py --list-targets
python run_relaylens.py --base-url https://gateway.example/v1 --model gateway-alias --target-model gpt-6-astra --seed 20261026 --task-rounds 5 --repeats 3 --stream --max-output-tokens 4096 --out reports/candidate.json --html-out reports/candidate.html
```

Keys are requested with hidden input or read from `RELAYLENS_API_KEY` / `RELAY_API_KEY` / `T8_API_KEY`. Existing `pip install -e .` and the `relaylens` console command remain supported.

API styles: `responses` (default), `chat` (Chat Completions), `messages` (native Claude; x-api-key authentication). Select the actual wire protocol offered by your endpoint. `--model` is the gateway ID; `--target-model` is the GPT/Claude claim. Current and legacy presets remain available, and GPT/Claude custom target IDs are supported. The catalog was checked on 2026-10-26; it does not imply account availability.

## Evidence

- Eight generated families: ordering logic, arithmetic, restricted-expression repair, strict instructions, shortest paths, scheduling optimization, long-context retrieval and state tracking.
- Exact local solvers and unseen boundary cases; generated answers are not sent in prompts. Generated code is never executed.
- Repeated, shuffled trials expose pass/fail changes on the same tasks. Different returned labels and stochastic variation are weak routing signals, never proof of mixing.
- Tool names vary by seed; arguments and use of every tool-result field are checked. All three protocols preserve the original user request and assistant context.
- Latency median, P95, MAD and first visible text-token timing are grouped by task family, with failed requests excluded from timing but included in task accuracy.
- Optional `--fingerprint-samples 20` adds 100 requests over five categorical prompts. Reference comparison reports JSD and a permutation test with Bonferroni correction; it does not reuse another paper's universal model-ID thresholds.

The built-in suite is a public smoke and comparison suite, not a calibrated intelligence scale. Strong models can saturate it. `--suite-module private_suite.py` loads operator-owned hard or holdout tasks via the existing `suite(seed, rounds)` interface.

## Reference calibration

Run the selected official model using your own official API key, then audit the candidate using its key. Supply the resulting JSON with `--reference-report reports/official.json`. Use `--trust-reference` only after verifying its provenance yourself; trust flags inside imported files are ignored.

Pairing requires identical target, seed, suite version/commitment, API style, task effort, output budget, streaming/repeat/sampling settings, task IDs and prompt hashes. Invalid or legacy reports remain uncalibrated. At least 30 unique tasks are needed; repeats do not inflate independent sample size. A case-cluster bootstrap describes loss, while a conservative one-sided 95% upper bound on the fraction of regressing tasks must fit `--loss-margin` (default 0.10) before a within-margin label is possible. A confidence interval covering zero is insufficient by itself.

- **D**: no usable response; inspect transport, authentication and API errors.
- **C**: low basic task performance or a calibrated deficit relative to the reference.
- **B**: observations available, but target calibration or evidence remains insufficient.
- **A**: within-margin task evidence against an operator-verified reference, for this suite/configuration/time only.

Every grade leaves model identity **not established**. Names, token usage, latency, style and matching results do not prove private weights or rule out adaptive routing. Randomization cannot hide plaintext prompts from a gateway. See [methodology](docs/methodology.md), [threat model](docs/threat-model.md) and [anti-adaptation](docs/anti-adaptation.md).

## Reports and routes

Local JSON/HTML retains answer text for inspection while scrubbing secrets. `--public-out reports/public.json` additionally removes answer text, URLs, IPs and local paths. Never publish full local reports accidentally.

Use `--route direct`, `--route env` or `--proxy http://proxy.example:8080`. Optional `--egress` queries ipinfo.io without API credentials; `--no-egress` overrides it. Nothing modifies global proxy configuration. Parameter probes use documented efforts by default; `--efforts` can probe others without treating every rejection as model substitution. `--task-effort omit` omits reasoning parameters. Output budgets and timeout remain configurable.

## Development

```text
python -m unittest discover -s tests -v
python -m compileall -q relaylens
```

Tests include loopback HTTP requests for Responses, Chat and native Claude, SSE parsing, full tool round trips, dilution and sample-size checks, false-reference rejection and privacy exports. They do not constitute a live official-model calibration.
