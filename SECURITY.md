# Security Policy

## Supported versions

OpenCog is a research framework. Only the current `master` branch receives
security fixes; there is no long-term support branch.

| Version | Supported |
| ------- | --------- |
| `master` | yes       |
| anything older | no |

## Reporting a vulnerability

**Do not open a public issue for a security problem.**

Email the maintainers listed in `AUTHORS`, or use GitHub's private
vulnerability reporting for this repository
("Security" -> "Report a vulnerability"). Include:

* what an attacker can achieve (confidentiality / integrity / availability),
* the exact request, atom, file or configuration needed to trigger it,
* the OpenCog commit SHA and how the tree was built (CMake version, compiler,
  `COGUTIL_REF` and `ATOMSPACE_REF`),
* whether authentication was configured (`OPENCOG_API_TOKEN` set or not).

Please give the maintainers a reasonable window to publish a fix before
disclosure. We aim to acknowledge within 3 working days.

## Threat model, in one paragraph

The cogserver is a **code-execution service**. Its telnet interface and its
`/api/v1.1/shell` and `/api/v1.1/scheme` endpoints all evaluate arbitrary
Scheme inside the server process, and `GroundedSchemaNode` evaluation can
reach the C++ layer and the host. Anything that can talk to those interfaces
should be assumed to be running code as the cogserver user. The control that
matters is network reachability plus authentication, not input sanitisation.

For the end-to-end trust boundaries, controls and accepted residual risks of
`/shell` and `/scheme`, see [THREAT_MODEL.md](THREAT_MODEL.md).

## What is treated as a vulnerability

* Reaching `/api/v1.1/shell` or `/api/v1.1/scheme` without the configured
  `OPENCOG_API_TOKEN`, from an origin not in
  `OPENCOG_API_ALLOWED_ORIGINS`, or from outside the host.
* Starting the REST API on a non-loopback interface with no token. The server
  is meant to refuse this; if it does not, that is a bug in
  `assert_safe_bind()` in `opencog/python/web/api/apisecurity.py`.
* Script execution through the JSONP `callback` parameter on any endpoint.
* Reading local files or reaching cloud metadata endpoints (for example
  `169.254.169.254`) through the CSV dataset loader.
* Memory-safety defects in C++ reachable from Scheme evaluation, from the
  REST API, or from a persisted AtomSpace file: out-of-bounds read/write, use
  after free, uninitialised reads, unbounded allocation driven by input.
* Credentials in the repository. CI runs gitleaks on every push; see
  `.gitleaks.toml`.

## What is out of scope

* The Scheme/AtomSpace language being Turing-complete. That is the design.
* The `localhost` cogserver telnet interface being reachable by other local
  users. That is the documented trust boundary.
* Vulnerabilities in the compiled `cogutils` / `atomspace` / `guile`
  dependencies. Report those upstream; we will bump the pin.
* Denial of service from a *deliberately* huge but correctly formed
  AtomSpace operation by an authenticated local operator.
* Missing hardening in code paths that require a locally modified
  configuration, where the stock configuration is already safe.

## Secret management

The REST API reads every credential from the process environment
(`OPENCOG_API_TOKEN`, `OPENCOG_API_SECRET_KEY`); none is baked into the image
or the source tree. The project deliberately does **not** embed a vendor SDK:
the integration boundary is the process environment, so any secret manager can
be used without adding a runtime dependency to this repository.

Recommended injection paths, in increasing order of operational complexity:

1. **Local development** — copy `.env.example` to `.env`, restrict it to
   `chmod 600`, and keep it untracked (CI fails if `.env` is ever committed).
2. **Docker / Compose** — pass an external env file:
   `docker compose --env-file /run/secrets/opencog.env up`. Do not put a token
   in `docker-compose.yml`; build args are visible in image history.
3. **systemd** — `EnvironmentFile=/run/secrets/opencog.env` with
   `ProtectHome=yes` and a `tmpfs` mount for `/run/secrets`.
4. **Kubernetes / Vault / cloud secret managers** — have the orchestrator or
   an init sidecar fetch the secret at start-up and expose it as an environment
   variable or a `tmpfs`-backed file. Mounting a file and sourcing it into the
   environment keeps the token out of `docker inspect` and process listings.

Generate values with `openssl rand -hex 32`. A token is a **full code-execution
credential**, not a scoped API key: rotate it immediately if it may have been
exposed, then restart the API process (there is no hot reload today). Remember
to set `COGSERVER_PASSWORD` in `lib/opencog.conf` separately — the REST token
does not protect the cogserver's own interface.

Verify that no credential entered the tree with `make secret-scan`; CI runs
gitleaks on every push and pull request.

## Hardening checklist for operators

1. Set `OPENCOG_API_TOKEN` to a value from `openssl rand -hex 32` before
   binding the REST API to anything other than `127.0.0.1`.
2. Set `COGSERVER_PASSWORD` in `lib/opencog.conf` to something unique. The
   shipped default is public knowledge.
3. Leave `OPENCOG_API_ALLOWED_ORIGINS` at the loopback default. Do not set
   it to `*`.
4. Keep the `Dockerfile`'s `COGUTIL_REF` and `ATOMSPACE_REF` pinned to commit
   SHAs for anything you deploy.
5. Run the container as its non-root `opencog` user (the shipped image
   already does).
6. Do not set `LOG_LEVEL=DEBUG` in production: it logs Scheme evaluation,
   which can contain user data.
