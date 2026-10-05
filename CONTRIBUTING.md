# Contributing

1. Keep the runtime dependency-free unless a change clearly needs a dependency.
2. Add a deterministic seed and a local grader for every new synthetic task.
3. Do not execute model-generated code. Use a restricted interpreter or an external sandbox with an explicit threat model.
4. Keep raw prompts and completions out of default reports; include hashes and aggregate evidence instead.
5. Run `python -m unittest discover -s tests -v` and `python -m compileall relaylens` before opening a pull request.
6. Explain any change to scoring, thresholds, privacy redaction, or protocol semantics in the pull request.
