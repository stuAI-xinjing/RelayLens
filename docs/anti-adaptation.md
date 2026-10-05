# Anti-adaptation guidance

## Short answer

Do not rely on encrypting the public repository or encrypting prompts before sending them to a gateway.

The gateway must receive the plaintext prompt to answer it. A provider can therefore observe the
prompt after decryption, record it, recognize stable templates, and route future requests to a
special handler. Encryption can protect a local file at rest, but it cannot hide the test from the
endpoint that evaluates it.

## Recommended split

1. Keep the runner, graders, schemas and a small smoke suite public.
2. Keep the high-value holdout suite in a private file or private repository.
3. Pass the private file with `--suite-module`; it must define `suite(seed, rounds)` and may define
   `SUITE_VERSION`.
4. Use a fresh cryptographically random seed for routine audits. Use a fixed seed only when making
   a paired candidate/reference comparison.
5. Keep the raw report private. Share only `--public-out` after inspecting it.
6. Publish the suite commitment hash and aggregate results only after the run. The hash proves which
   local suite file was used; it does not hide prompts from the gateway.

Example private suite entry point:

```python
# private_suite.py -- keep outside the public repository
from relaylens.tasks import suite as public_smoke_suite

SUITE_VERSION = "private-2026-10"

def suite(seed, rounds):
    # Replace this with operator-owned generated or licensed tasks.
    return public_smoke_suite(seed ^ 0x91E10DA5, rounds)
```

This example only demonstrates the interface. A real holdout suite should use operator-owned task
generators and graders, with templates that are not copied into the public repository.

## What randomization helps with

- New numeric values and boundary cases prevent memorization of one answer.
- Random task order prevents position-based routing.
- Per-run tool names and schemas make a single fixed function-call probe less useful to a special
  handler.
- Fresh nonces prevent a gateway from matching one stable sentinel string.
- Unseen local grading cases make it harder to return a hard-coded answer.

Randomization reduces adaptation risk; it does not make an untrusted endpoint unable to inspect the
request.

## What a stronger evaluator looks like

Use a rotating private holdout suite, multiple prompt families, independent graders, and a trusted
reference endpoint. Keep each audit short enough to limit cost, but repeat it on different days and
keys. Record the suite version and commitment hash so later comparisons can show that the candidate
and reference used the same local test material.

No client-side design can provide cryptographic model identity without provider-side attestation,
a signed execution receipt, or another trusted hardware/software boundary.
