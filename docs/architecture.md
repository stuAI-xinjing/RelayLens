# Architecture

```text
CLI
 ├─ Client        protocol, route, timeout, redirect and SSE handling
 ├─ Task suite    standard 8 families / challenge 14 families / private module
 ├─ Audit runner  catalog → parameters → tasks → tool continuation
 ├─ Statistics    prompt clusters, bounded losses, exact regression upper bound
 ├─ Comparison    single reference or multi-model panel; offline mode available
 ├─ Numeric probes optional request-level behavior vectors and paired tests
 └─ Reports       local JSON + responsive HTML + public measurements
```

The layers are independent. Failed/truncated requests count against end-to-end task accuracy, while their transport causes and completed-only accuracy remain separate. Protocol availability is not automatically labelled weaker reasoning. A task grader never sees an API key. A prompt hash supports consistency checks; it is not a signature or trusted execution attestation.

The standard library remains sufficient. A separate web backend was not added: it would not improve measurement accuracy. Frontend/backend engineering semantics are covered by exact-solver tasks; the HTML report provides local viewing without a server. Generated model code is not executed.
