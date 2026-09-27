# Changelog

All notable changes to OpenCog are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
targets [Semantic Versioning](https://semver.org/) from the next tag onward.

Security-relevant changes are called out under **Security** in each release.

## [Unreleased]

### Added

- **A test suite that runs on a fresh clone.** `tests/python/pytest/` holds 149
  unit tests covering the REST API security policy and the CSV dataset
  loader. They import only the standard library, so `python -m pytest` works
  immediately after `pip install -r requirements.lock.txt` -- no AtomSpace,
  no C++ build, no cogserver. This is the gate that runs on every push.
- **A single build/test entry point.** A root `Makefile` with
  `make build`, `make test`, `make lint`, `make coverage`, `make audit`,
  `make docker-build`. `make help` lists every target.
- **Static analysis configuration.** `.clang-tidy` (security and correctness
  checks as errors, style advisory) and `.clang-format`, plus
  `[tool.ruff]` / `[tool.pytest.ini_options]` / `[tool.coverage.*]` in
  `pyproject.toml`.
- **Pinned Python dependencies.** `pyproject.toml` (machine-readable
  manifest), `requirements.txt` (human-maintained input) and
  `requirements.lock.txt` (the versions CI installs). Regenerate with
  `make lock`.
- **CI matrix.** `.github/workflows/ci.yml` now runs the Python suite on
  3.8/3.11/3.12, blocks on `ruff` and `clang-tidy` over changed C++ files,
  emits a coverage artifact, and audits dependencies and licences.
  `.github/workflows/security.yml` adds CodeQL (C++ and Python), gitleaks
  with a project-specific config, osv-scanner, Semgrep, dependency review
  and Dockerfile hardening checks.
- **Dependency automation.** `.github/dependabot.yml` watches GitHub Actions
  pins, the Python requirements and the container base image.
- **A self-contained, non-root container build.** The `Dockerfile` is now
  multi-stage: a dependency stage that builds `cogutils` and `atomspace`
  from pinned refs, a build stage, and a slim runtime stage that runs as an
  unprivileged `opencog` user. `docker compose run --rm test` builds all
  three repositories and runs the suite with no host-side setup.
- **Documentation.** `CONTRIBUTING.md` (workflow, review expectations,
  Python 2 -> 3 migration status), `SECURITY.md` (threat model, reporting,
  operator checklist), `docs/ARCHITECTURE.md` (module map, request flow,
  security boundaries, known debt), `.env.example`, and a `CHANGELOG.md`
  (this file).
- **Coverage targets.** `make coverage` (Python, via `coverage`) and
  `make coverage-cpp` (C++, via the existing `CMAKE_BUILD_TYPE=Coverage` path
  and `scripts/combine_lcov.sh`), plus a `coverage` CMake target.

### Security

- **REST API authentication.** Every `/api/v1.1` endpoint now requires
  `Authorization: Bearer <token>` when `OPENCOG_API_TOKEN` is set, compared
  with `hmac.compare_digest` (with a constant-time fallback). Previously
  there was no authentication of any kind.
- **The REST API no longer binds to `0.0.0.0` by default.** It binds to
  `127.0.0.1`. `restapi.py` hard-coded `IP_ADDRESS = '0.0.0.0'`, publishing a
  Scheme-evaluation endpoint on every interface.
- **Fail-closed on the dangerous configuration.** The server refuses to start
  on a non-loopback interface when `OPENCOG_API_TOKEN` is unset, rather than
  coming up as an open remote shell.
- **CORS is no longer a wildcard.** `Access-Control-Allow-Origin: *` was
  emitted on every response, so any web page could read the AtomSpace
  cross-origin. Origins are now an explicit allow-list
  (`OPENCOG_API_ALLOWED_ORIGINS`) enforced server-side, not just by response
  header. The cross-site request forgery path from a browser to
  `127.0.0.1:5000` is closed.
- **Reflected XSS via JSONP fixed.** The `callback` query parameter was
  concatenated verbatim into a response served as `application/javascript`.
  It is now restricted to a bare JavaScript identifier path.
- **Request and response sizes bounded.** `MAX_CONTENT_LENGTH` (1 MiB),
  command length (8192 chars), atom name length, outgoing-set size, and a
  hard page-size cap. `GET /api/v1.1/atoms` with no `limit` previously
  serialised the entire AtomSpace into one response.
- **Error messages no longer disclose internals.** `GET /atoms` returned
  `str(exception)` to the caller, leaking file paths and library internals;
  `/scheme` returned a 500 with a traceback-shaped body. Both now log the
  detail and return a generic message.
- **Cogserver socket handling hardened.** `apishell.py` used a bare
  `except socket.error: print msg` and then used the unbound `connection`
  variable; a refused connection produced an `UnboundLocalError` and a 500.
  Connect and I/O timeouts are now set, failures return 502/504, and the
  socket is always closed.
- **SSRF and local-file disclosure closed in the CSV dataset loader.**
  `csv_dataset_parser.Dataset` passed its argument straight to `urllib.urlopen`
  and then `open()`, both inside bare `except:` handlers, with no timeout, no
  scheme restriction and no size limit. A caller-supplied `file://` URL read
  local files, a link-local or metadata URL was a server-side request forgery
  against the cloud metadata service, and a hostile endpoint could exhaust
  memory or block forever. Now: `http`/`https` only, loopback and
  cloud-metadata hosts refused, 30 s timeout, 64 MiB cap, and typed
  `DatasetSourceError` / `DatasetValidationError` instead of silent
  fallthrough.
- **Container build no longer executes remote code.** The previous
  `Dockerfile` did `ADD https://raw.githubusercontent.com/opencog/ocpkg/master/ocpkg`
  followed by `chmod 755 /tmp/octool && /tmp/octool -rdpcalv` -- unpinned
  remote code execution as root at build time. Dependencies are now
  installed explicitly, the base image is a supported release, the image
  drops to a non-root user, and CI enforces all three properties.
- **Supply-chain checks.** gitleaks on every push (with `.gitleaks.toml`
  flagging committed `COGSERVER_PASSWORD` values), osv-scanner over the
  pinned Python dependencies and the Dockerfile, and Dependabot on Actions
  pins and the base image.
- **Two memory-safety defects fixed in `DimEmbedModule`.** Nine
  `throw std::string("...%s...", tName)` statements were replaced with
  `InvalidParamException(TRACE_INFO, ...)`. `std::string(const char*, size_t)`
  was being selected, so the `const char*` type name was converted to a
  garbage length and used as a read length -- an out-of-bounds read
  reachable through the dimensional-embedding Scheme bindings. Throwing a
  bare `std::string` also meant `catch (const std::exception&)` never
  matched.
- **Secret and configuration handling.** `.env` is gitignored, `.env.example`
  documents every runtime variable with its secure default, `SECRET_KEY` is
  sourced from the environment instead of being implicit, and the security
   config's `__repr__` cannot leak the token into a log line.

### Fixed

- `apiatomcollection.post` referenced an unbound local `type` in its 400
  error message, turning a client error into a 500 `NameError`.
- `apiatomcollection.get` returned HTTP 200 with an error body for internal
  failures.
- `apitypes.get` built its response with a bare `filter()`, which is an
  iterator on Python 3 and is not JSON-serialisable. The type list is now
  sorted, which also makes the response deterministic between runs.
- `csv_dataset_parser` compared characters against the string literal with
  `is` (identity, not equality) -- correct only by accident on CPython, and a
  `SyntaxWarning` on Python 3.8+.
- `csv_dataset_parser.CompositeRecord` kept `is_incomplete` and the converter
  table as *class* attributes, so state was shared between records; a dropped
  incomplete record was still used to derive the dataset's variable names.
- `csv_dataset_parser` silently dropped malformed CSV rows, making a
  truncated or mis-delimited file look like a valid dataset. Malformed rows
  are now counted (`number_of_malformed_records`) and logged.
- `csv_dataset_parser` did not close its file handle if record conversion
  raised, and opened files without `newline=''`, mis-parsing quoted fields
  containing newlines.
- `restapi.py` called the deprecated `Thread.setDaemon(True)`.
- `server` / `scheme`: `get_json()` on a non-JSON body raised `TypeError`
  rather than a 400; bodies are now validated and rejected cleanly.
- Removed commented-out ZeroMQ initialisation and a no-op `int i = 0; i++;`
  pair from the `Octree3DMapManager` constructor, and a stale commented
  `config().get_bool(...)` call.

### Changed

- `thread.setDaemon(True)` -> `thread.daemon = True` in `restapi.py`.
- `print` replaced with the `logging` module across the REST API resources,
  so log level and routing are configurable without patching source.
- `opencog/python/utility/csv_dataset_parser.py` now imports cleanly on both
  Python 2.7 and 3.x and uses `io.open` with an explicit encoding.
- `.gitignore` no longer swallows the root developer `Makefile`
  (the unanchored `Makefile` pattern is now re-included for `/Makefile` only).
- CI actions are pinned to major-version tags and kept current by Dependabot
  rather than to floating commit SHAs that go stale.

## [0.1.4] -- 2015-11-08

Historical release. See the git history; this file starts at the point where
automated quality gates were introduced.

[Unreleased]: https://github.com/opencog/opencog/compare/v0.1.4...HEAD
[0.1.4]: https://github.com/opencog/opencog/releases/tag/old-embodiment_8-nov-2015
