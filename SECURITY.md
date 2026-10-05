# Security policy

## Scope

RelayLens sends prompts and tool-call payloads to the endpoint selected by the operator. It does not validate that an endpoint is trustworthy.

## API keys

- Prefer environment variables or interactive hidden input.
- Never commit a key, cookie, authorization header, or private report.
- Rotate a key immediately if it appears in a shell transcript, issue, CI log, or report.

## Reporting a vulnerability

Do not put secrets or live credentials in a public issue. Use a private security channel configured by the repository owner, or remove sensitive material and describe the minimal reproduction.
