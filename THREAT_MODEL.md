# Threat model: the OpenCog REST API

This document describes the trust boundaries and mitigations for the two
code-execution endpoints of the REST API. It complements (and does not replace)
the reporting policy in [SECURITY.md](SECURITY.md).

## Scope and design intent

`POST /api/v1.1/shell` and `POST /api/v1.1/scheme` are **remote code execution
by design**. The first forwards a command to the cogserver shell on
`127.0.0.1:17001`; the second evaluates Scheme in-process through
`scheme_eval`. The goal is therefore not to make the payload harmless — Scheme
is Turing-complete and `GroundedSchemaNode` can reach C++ — but to ensure that
**only an authorized caller on a trusted network can reach the endpoint**, and
that malformed input cannot turn one command into several, crash the process,
or disclose internals.

The single source of truth for the policy is
`opencog/python/web/api/apisecurity.py`. The REST API resolves it once in
`RESTAPI.__init__` and publishes it to every resource, so the endpoints cannot
drift apart.

## Assets

| Asset | Why it matters |
| --- | --- |
| Integrity of the cogserver process | A `/scheme` caller can read or mutate any atom and reach the host through C++ bindings. |
| Confidentiality of the AtomSpace | Atoms may contain user or research data. The API previously allowed any web page to read it cross-origin. |
| Availability of the interpreter | Both endpoints execute synchronously and can pin a CPU core. |
| The bearer token and `OPENCOG_API_SECRET_KEY` | Possession of the token is equivalent to code execution. |
| The host filesystem and metadata service | Reachable through Scheme, C++ bindings, and (historically) the CSV loader. |

## Trust boundaries and controls

| # | Boundary | Control | Implementation |
| --- | --- | --- | --- |
| 1 | Network → REST API | Loopback bind by default; a routable bind with authentication disabled is refused at start-up. | `DEFAULT_BIND_HOST`, `assert_safe_bind()` |
| 2 | Browser → REST API | Bearer token checked **before** body parsing; exact `Origin` allow-list enforced server-side, not just via response headers. | `authorize()`, `is_origin_allowed()` |
| 3 | Request body → command validation | 1 MiB body cap, JSON object required, `command` must be a UTF-8 string, bounded length, control characters rejected. | `MAX_CONTENT_LENGTH`, `validate_command_payload()` |
| 4 | Validated command → cogserver shell | Single-command policy: CR/LF rejected so the line-oriented shell cannot be fed an injected second command; 5 s connect / 30 s IO timeouts; 1 MiB reply cap; `OSError` and timeout paths return 502/504 instead of a traceback. | `validate_command()`, `_send_to_cogserver()` |
| 5 | Validated command → Scheme interpreter | Multi-line source is explicitly allowed (`allow_line_breaks=True`); remaining C0 controls and DEL are still rejected; interpreter exceptions are logged with detail but returned as a generic 500. | `validate_command_payload()`, `apischeme.post()` |
| 6 | Error path → client | Structured JSON errors with stable `error_code` values; internal exception text, file paths and tokens are never echoed. Token is excluded from config `repr()` and logs. | `RESTAPI._register_error_handlers()`, `ApiSecurityConfig.__repr__` |
| 7 | Build/deploy → native dependencies | `cogutils` and `atomspace` are pinned to release-tagged commit SHAs in the `Makefile` and `Dockerfile`, so a rebuild cannot silently pick up upstream code. | `COGUTIL_REF`, `ATOMSPACE_REF` |

## Attack scenarios

| Threat | Precondition | Mitigation |
| --- | --- | --- |
| Cross-site request from a visited web page | Victim's browser, no token | Origin checked server-side; wildcard CORS is not the default; missing credential returns 401 before the body is read. |
| Remote unauthenticated code execution | API bound to `0.0.0.0` with no token | `assert_safe_bind()` aborts start-up with an actionable message. |
| Command injection through the shell endpoint | Valid token | C0 controls including CR/LF rejected; one command per request. |
| Log forging through a command containing control characters | Valid token | Control-character rejection; structured JSON log formatter escapes values via `json.dumps`. |
| Memory/CPU exhaustion | Valid token | Request body capped, command length capped, page size capped, reply buffered to 1 MiB, socket timeouts enforced. |
| Information disclosure via error text | Any caller | Generic client messages; detail only in operator logs with a request ID. |
| Brute-force of the bearer token | Network reach | Constant-time comparison, operator-generated 256-bit token, warnings logged on failure. |
| Supply-chain substitution of a native dependency | Build time | Immutable commit SHAs instead of a moving `master` branch. |

## Residual risks (accepted, with rationale)

1. **A valid token is full code execution.** There is no per-command
   authorization or command allow-list. This is inherent to the service's
   purpose; treat the token like a root SSH key and rotate it if exposed.
2. **The cogserver telnet interface on loopback is trusted.** Any local user
   can reach it. Multi-user hosts are out of scope; use OS-level isolation.
3. **An authenticated operator can deliberately run an expensive Scheme
   program.** The command-length bound limits parsing cost, not evaluation
   cost. Run the service with CPU/memory limits in production.
4. **Scheme multi-line source cannot be control-character filtered as tightly
   as shell commands.** C0 controls other than CR/LF/TAB remain rejected.
5. **`http://` is allowed for the local UI.** There is no TLS in the shipped
   image; terminate TLS at a trusted proxy if the API is reachable off-host.

## Verification

The controls in rows 1–5 have dependency-free regression tests:

```sh
python -m pytest tests/python/pytest -q
python -m mypy
python -m ruff check .
```

CI additionally runs CodeQL, gitleaks, semgrep, hadolint,
`dependency-review-action` and the pinned-dependency osv-scanner job from
`.github/workflows/security.yml`.
