# RelayLens

## 0.9.0 · 独立 Token 消耗与账单核对

无需 Codex 或额外大模型：记录用量、独立输入估算、输入长度倍率线索、自动 New API 账单查询、整份文件导入和可选本机截图 OCR。双击向导结束后打开本机核账页面，建议使用专用测试 Key。

甲＋/甲/乙/丙/丁/戊/戊＋只评价相对 Token 消耗，独立于能力等级；没有可信官方同题参考时显示“待对照”。缓存量、隐藏推理与金额分开，缺数据不算零。默认不新增付费题目。

[使用方法、等级范围和支持边界](docs/TOKEN_AUDIT.md)。已有报告：`python run_relaylens.py --billing-ui reports/example.json`。


A standalone, standard-library Python audit tool for GPT and Claude gateways. Version 0.8.0 separates the selected model's target assessment from task screening. A Luna claim needs a Luna reference; a generic quiz score cannot certify Astra. The default is 16 questions, four workers and a 180-second collection budget. S requires conservative evidence of superiority against a trusted matched reference. Exact content and strict formatting are reported separately; partial component credit never raises the grade. Python 3.10+; no runtime dependencies.

[中文完整使用说明](README.zh-CN.md)

## Run

On Windows, double-click `start.cmd`: enter the endpoint, choose the target model, enter the hidden key and press Enter. Type `A` at the last step for advanced settings, protocol selection or gateway aliases. GPT defaults to Responses and Claude to native Messages. Or run directly without installing:

```text
python run_relaylens.py --interactive
python run_relaylens.py --list-targets
python run_relaylens.py --base-url https://gateway.example/v1 --model gateway-alias --target-model gpt-6-astra --mode fast --out reports/candidate.json --html-out reports/candidate.html
```

The wizard defaults to fast mode. Existing CLI scripts retain full execution unless `--mode fast` is supplied. Fast defaults: `--pack fast --task-rounds 2 --repeats 1 --concurrency 4 --time-budget 180`, high reasoning and a 32,768-token output ceiling. All remain configurable. `--mode full` retains the complete workflow without an overall deadline.

The budget bounds collection, not upstream completion: up to five seconds are reserved for cleanup and reporting. Unfinished tasks remain in the denominator, and partial results are saved. Closing a connection does not guarantee that upstream billing stops. Sixteen questions can earn a screening A/D; formal target comparison still requires adequate matched reference samples. The report visibly distinguishes these evidence bases.

Keys are requested with hidden input or read from `RELAYLENS_API_KEY` / `RELAY_API_KEY` / `T8_API_KEY`. Existing `pip install -e .` and the `relaylens` console command remain supported.

API styles: `responses` (default), `chat` (Chat Completions), `messages` (native Claude; x-api-key authentication). Select the actual wire protocol offered by your endpoint. `--model` is the gateway ID; `--target-model` is the GPT/Claude claim. Current and legacy presets remain available, and GPT/Claude custom target IDs are supported. The catalog was checked on 2026-10-26; it does not imply account availability.

## Evidence

- `--pack fast` selects eight families with two fresh tasks each: ordering, expression repair, constrained selection, probability, relational aggregation, context updates, frontend state and backend transactions. Selection is based on coverage, not measured model discrimination. Parameter, tool and catalog checks complete the default run.
- `--pack standard` preserves eight generated families: ordering logic, arithmetic, restricted-expression repair, strict instructions, shortest paths, scheduling optimization, context retrieval and state tracking.
- `--pack challenge` retains those eight and adds constrained selection/counting, exact conditional probability, relational aggregation, versioned context retrieval, frontend asynchronous state and backend idempotent transactions. Available in advanced settings. These engineering tasks test semantics; they do not build or execute a full generated app.
- Challenge context size is configurable with `--context-records 1024`. Character count and actual API usage are recorded separately; record counts are not advertised as token context size.
- Exact local solvers and unseen boundary cases; generated answers are not sent in prompts. Generated code is never executed.
- Repeated, shuffled trials expose pass/fail changes on the same tasks. Different returned labels and stochastic variation are weak routing signals, never proof of mixing.
- Tool names and receipt nonces vary by seed. Exact typed JSON arguments and tool-result objects are checked, preventing substring coincidences from passing. All three protocols preserve the original user request and assistant context.
- Latency median, P95, MAD and first visible text-token timing are grouped by task family, with failed requests excluded from timing but included in task accuracy.
- Optional `--fingerprint-samples 20` adds 100 requests over five categorical prompts. Reference comparison reports JSD and a permutation test with Bonferroni correction; it does not reuse another paper's universal model-ID thresholds.
- Optional `--numeric-samples 30` adds 30 numeric-sequence requests on **each** endpoint. Use the same seed, sample count and sampling settings in official and candidate runs. At least 30 valid paired requests and 95% valid responses per endpoint are required for a distribution test. Three requests provide a preview only. Allow enough output tokens to avoid truncation.

Numeric preferences are inspired by [lm-detector](https://github.com/Ikaleio/lm-detector), with an independent implementation and operator-collected references. All requests go through the existing configured endpoint/route; no website proxy or third-party bank is used. A whole answer is one observation. A paired, multivariate permutation test can flag distribution changes, including some synthetic mixtures, but provides neither an identity probability nor a traffic-wide substitution fraction. It never changes task scores. Public exports omit answer text and cannot recompute fingerprints.

Collect independent official-versus-official controls before interpreting relay shifts. Freeze sample counts before testing; repeatedly collecting until significance is not a valid test. See [research decisions](docs/research-review.md) and [statistical assumptions](docs/methodology.md). Real GPT/Claude detection power has not been calibrated for this feature.

The built-in suite is a public smoke and comparison suite, not a calibrated intelligence scale. Strong models can saturate it. `--suite-module private_suite.py` loads operator-owned hard or holdout tasks via the existing `suite(seed, rounds)` interface.

## Reference calibration

Run the selected official model using your own official API key, then audit the candidate using its key. Supply the resulting JSON with `--reference-report reports/official.json`. Use `--trust-reference` only after verifying its provenance yourself; trust flags inside imported files are ignored.

Pairing requires identical seed, suite version/commitment, API style, task effort, output budget, concurrency, task settings, task IDs and prompt hashes. The single-target result also requires matching target IDs; a reference panel can compare different GPT/Claude targets under the same task configuration. Diagnostic effort-probe lists and fingerprint sample counts do not alter task compatibility; fingerprint sampling settings are checked separately. Invalid, duplicate-ID, self-reference and incompatible reports cannot calibrate results. At least 30 unique prompts are needed; repeats do not inflate sample size.

Bootstrap intervals describe loss. Decisions use a conservative bounded-loss lower bound and an exact binomial upper bound on the fraction of regressing prompts. A reference panel corrects for multiple comparisons. Transport deficits are separated from lower correctness on completed task pairs. See [methodology](docs/methodology.md) for assumptions and thresholds.

Collect official anchors with the same seed/settings, place them in a dedicated folder, then compare an existing candidate **without API calls**:

```text
python run_relaylens.py --compare-report reports/candidate.json --reference-dir references --trust-reference --out reports/compared.json --html-out reports/compared.html
```

Multiple matching references are reported as overlapping, never forced into a nearest-model identity. Different protocols remain incompatible: collect references in the actual protocol being audited. Do not place the candidate itself in the reference directory. Only mark all references trusted when you have verified their provenance. Baselines are not bundled or fabricated.

Target grades: **S** = conservatively above the selected trusted reference on this suite/configuration; **A** = within the predeclared loss margin; **D** = conservatively below reference; **U** = unverified/inconclusive, not low intelligence. At least 30 unique matched prompts are needed, often more. No official baselines are bundled or fabricated. Reference provenance is an explicit operator assertion, not authenticated by the tool. A higher raw score alone cannot award S. References remain scored using identical strict whole-task pass criteria on both sides.

Separately, screening thresholds remain A >=90% fully correct content, >=75% per family, at least six families/four challenge prompts; B >=75%; C >=50%; D <50%. Under the default two-per-family design, A requires 16/16, B 12–15/16, C 8–11/16 and D fewer than eight correct. Fewer than eight unique questions or <90% completion is incomplete. These are operational screening rules, not per-model intelligence boundaries. Content may pass with surrounding prose only if it contains one unambiguous complete answer of exactly the expected types and values; strict format failure remains visible. Partial component scores are diagnostic only, never used to inflate grades.

First-attempt Wilson intervals are descriptive and do not account for all template correlations. Short runs and different seeds cannot establish account degradation or model mixing. Latency, style and identity signals never change capability scores. Usability remains a separate panel.

Review an old local built-in report without API calls, preserving its strict grades:

```text
python run_relaylens.py --compare-report reports/old.json --review-content --out reports/reviewed.json --html-out reports/reviewed.html
```

Review validates regenerated prompt hashes and recorded answer hashes; it refuses missing answers, altered prompts or imported private code. It writes a separate file. Public measurement reports cannot reconstruct omitted answers. Full suites, repeat sampling, custom suites and all advanced workflows remain available. See the [methodology](docs/methodology.md) for comparison assumptions and [Chinese guide](README.zh-CN.md) for complete examples.

## Reports and routes

Local JSON/HTML retains answer text for inspection while scrubbing secrets. `--public-out reports/public.json` additionally removes answers, error bodies, expected/parsed answers, gateway aliases, egress location/organization data, URLs, emails, IPs and local paths; case IDs are hashed. Public measurements remain usable for capability comparison, but contain no text for fingerprint comparison. Never publish full local reports accidentally.

Use `--route direct`, `--route env` or `--proxy http://proxy.example:8080`. Optional `--egress` queries ipinfo.io without API credentials; `--no-egress` overrides it. Nothing modifies global proxy configuration. Full-mode parameter probes use documented efforts by default; fast mode checks the task effort only; `--efforts` can probe others without treating every rejection as model substitution. `--task-effort omit` omits reasoning parameters. Output budgets and timeout remain configurable.

Chat uses `max_completion_tokens`; `--chat-token-field max_tokens` retains compatibility with older gateways. Official GPT-6 Astra / GPT-6.1 Sol Chat tool limitations are reported without invalidating task comparisons; tool probes still run. Use Responses for their tool tests. The advanced full-mode wizard suggests 32,768 output tokens and a 300-second timeout to leave room for reasoning; these are upper bounds, not a spend estimate, and remain editable. Existing full CLI defaults stay compatible, so explicitly increase them for challenge runs. A short output budget can measure truncation rather than reasoning.

Research decisions, adoption indicators and limitations: [community review](docs/research-review.md).

## Development

```text
python -m unittest discover -s tests -v
python -m compileall -q relaylens
```

Tests include loopback HTTP requests for Responses, Chat and native Claude, SSE parsing, full tool round trips, dilution and sample-size checks, false-reference rejection and privacy exports. They do not constitute a live official-model calibration.
