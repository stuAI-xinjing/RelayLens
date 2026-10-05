# Architecture

```text
CLI
 ├─ Client        protocol, route, timeout, redirect and SSE handling
 ├─ Task suite    seeded generation + local ground truth + graders
 ├─ Audit runner  catalog → parameters → tasks → tool continuation
 ├─ Statistics    Wilson intervals + paired case-cluster bootstrap
 └─ Reports       private JSON + optional scrubbed JSON
```

The layers are intentionally independent. A protocol failure does not become a task score of zero; it remains a transport error. A task grader never sees an API key. The public report has no raw prompt text, and its hashes can still prove that two reports used the same generated cases.

The standard library is enough for the reference implementation. A future web UI can call the same runner without changing the protocol or grader contracts.
