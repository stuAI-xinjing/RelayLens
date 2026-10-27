# Architecture

```text
CLI
 ├─ Client        protocol, route, timeout, redirect and SSE handling
 ├─ Task suite    fast 8 questions / standard 8 families / challenge 14 families / private module
 ├─ Audit runner  shared case/tool/grading logic; sequential full or bounded parallel fast
 ├─ Statistics    prompt clusters, bounded losses, exact regression upper bound
 ├─ Comparison    single reference or multi-model panel; offline mode available
 ├─ Numeric probes optional request-level behavior vectors and paired tests
 └─ Reports       local JSON + responsive HTML + public measurements
```

The layers are independent. Failed/truncated requests count against end-to-end task accuracy, while their transport causes and completed-only accuracy remain separate. Protocol availability is not automatically labelled weaker reasoning. A task grader never sees an API key. A prompt hash supports consistency checks; it is not a signature or trusted execution attestation.

The standard library remains sufficient. A separate web backend was not added: it would not improve measurement accuracy. Frontend/backend engineering semantics are covered by exact-solver tasks; the HTML report provides local viewing without a server. Generated model code is not executed.

Fast collection uses standard-library spawned processes. The parent owns the deadline, private task objects, graders and final report. Workers receive only request configuration and prompts; keys travel in memory. Secret-scrubbed partial observations are written atomically to a temporary directory, recovered on cancellation and removed after collection. All active workers are stopped together at the deadline; unstarted and interrupted tasks receive explicit incomplete records. Full execution remains sequential. This avoids an unbounded background HTTP thread after returning a report.
