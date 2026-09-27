# Architecture

A map of the tree, for someone who has to change something and needs to know
where it lives. For *how* to change it, read `CONTRIBUTING.md`.

## The 30-second version

OpenCog is a **code-execution server** wrapped around a graph database.

```
                       ┌──────────────────────────────────────┐
   telnet :17001 ─────▶│            cogserver                 │
                       │  (opencog/server/CogServer.cc)       │
   HTTP    :5000  ────▶│  dispatch, Module registry, Agents   │
                       └───────┬───────────────┬──────────────┘
                               │               │
                   load/scm     │               │  run
                               ▼               ▼
                    ┌─────────────────┐   ┌──────────────────┐
                    │   AtomSpace     │   │    Modules       │
                    │  (atomspace,    │◀──│  (loaded .so)    │
                    │   external dep) │   │                  │
                    └─────────────────┘   └──────────────────┘
```

`cogserver` loads shared objects called *modules*, each of which registers
Scheme primitives, Python request handlers, and/or background *agents*. The
AtomSpace (from the separate `atomspace` repository) stores the graph; this
repository is everything that reasons over it.

## Repository map

| Path | What lives there | Notes |
| ---- | ---------------- | ----- |
| `opencog/server/` | `CogServer`, `Agent`, `Module`, `Registry`, socket handling | The process entry point. `cogserver` links here. |
| `opencog/scm/` | `.scm` bootstrap files, loaded at start-up | Scheme-side wiring. |
| `opencog/util/` | atom utilities (`U()`, `TruthValue`, ... ) | Historically moved to `cogutil`. |
| `opencog/atomspace/` | thin wrappers over the external AtomSpace | |
| `opencog/atoms/` | atom type definitions and factory functions | Generated `atom_types.h` lands in the build dir. |
| `opencog/dynamics/` | attention allocation: ECAN, importance diffusion/updating | The `HAVE_ATTENTION` feature. |
| `opencog/spacetime/` | `SpaceServer`, `TimeServer`, `TemporalTable` | Temporal reasoning substrate. |
| `opencog/spatial/` | 3D/2D maps, A*/HPA search, TangentBug | Large; several files over 1000 lines. |
| `opencog/reasoning/pln/` | Probabilistic Logic Networks; rules are `.scm` | Rule-heavy; see `opencog/reasoning/pln/rules/`. |
| `opencog/learning/` | `PatternMiner`, dimensional embedding, statistics | |
| `opencog/nlp/` | relex, su-real, anaphora, IRC | |
| `opencog/persist/` | AtomSpace save/restore, ZeroMQ event publishing | |
| `opencog/guile/` | Guile bindings, `GroundedSchemaNode` evaluation | |
| `opencog/python/` | Python modules, the REST API, blending, learning | Mixed py2/py3; see the table in `CONTRIBUTING.md`. |
| `opencog/python/web/api/` | Flask REST API | Authenticated, CORS-restricted, size-bounded. |
| `opencog/embodiment/` | Robot/spatial agent stack (archived in practice) | Python 2 only. |
| `lib/` | CMake modules, `.conf` files, `json_spirit` | `lib/opencog.conf` is the runtime config. |
| `tests/` | CxxTest suites, `*.cxxtest` | Registered in `tests/CMakeLists.txt`. |
| `tests/python/pytest/` | Dependency-free pytest suite | The always-green gate. |
| `examples/` | Sample servers, the Hopfield demo | `make examples`. |
| `scripts/` | Dependency installers, lcov, packaging | |

## Request flow: the cogserver

1. `CogServerMain.cc` parses `-c <config>`, loads `lib/opencog.conf`.
2. `Module::load()` walks `MODULE_PATHS` and `dlopen()`s each `.so`, calling
   its registration hook. A module's static initialiser is what actually
   registers it (`DECLARE_MODULE`).
3. `.scm` files under `opencog/scm/` are loaded; they bind C++ primitives to
   Scheme names and start agents.
4. `ServerSocket` listens on 17001 (Scheme) and 18001 (Python). A request is
   read, dispatched by name, and executed. Some requests are marked
   "background" and run on the agent thread.
5. `Agent::stop()` is called at shutdown; the server waits for it.

`CogServer.cc` is the place to start reading. `CogServer.h` documents the
dispatch contract.

## Request flow: the REST API

1. `opencog/python/web/api/restapi.py` is a cogserver `Request` handler. Type
   `restapi.Start` at the cogserver shell (via `PYTHON_PRELOAD` in
   `lib/opencog.conf`).
2. `RESTAPI.__init__` resolves the security policy from the environment
   (`ApiSecurityConfig.from_env`), builds the Flask app, and registers four
   resources: `atoms`, `types`, `shell`, `scheme`.
3. Every handler calls `authorize(config, get_header)` first. That enforces
   the bearer token and the CORS origin allow-list, and raises on failure.
4. `/scheme` calls `scheme_eval(atomspace, command)` -- in-process Scheme.
   `/shell` opens a TCP connection to 127.0.0.1:17001 and forwards the
   command.
5. `apisecurity.py` owns all the policy: token comparison, origin matching,
   JSONP callback validation, page-size and command-length bounds, and
   `assert_safe_bind`. It imports nothing outside the standard library, which
   is what makes it unit-testable without Flask or an AtomSpace.

## Where the security boundaries are

| Boundary | Enforced by |
| -------- | ----------- |
| Is this request allowed at all? | `apisecurity.authorize` |
| Is this input the right shape and size? | `apisecurity.validate_*`, `coerce_limit` |
| May this process be listening on a routable interface? | `apisecurity.assert_safe_bind` |
| May the dataset loader fetch this URL? | `csv_dataset_parser._validate_remote_url` |
| Is a URL-derived fetch bounded in time and size? | `_open_source`, `_BoundedReader` |
| Is the cogserver password set? | `lib/opencog.conf` (operator responsibility; see `SECURITY.md`) |

New code handling untrusted input should route through `apisecurity.py`
rather than inventing a second policy.

## Data flow: an Atom

An *atom* is a typed node or link with a TruthValue and an AttentionValue. It
is created by a `GroundedSchemaNode` evaluation or a C++ factory call, and
lives in the AtomSpace. `Handle` is a `uint64` index into that space; it is
**not** stable across restarts unless persistence is configured.

TruthValues carry a *count* and a *confidence* as well as a mean, so an
inference can record how much evidence supports a claim. Attention values
(STI/LTI/VLTI) drive the ECAN agents in `opencog/dynamics/`, which decide
what the system spends compute on.

## Build-time feature detection

The top-level `CMakeLists.txt` probes for optional dependencies and sets
`HAVE_*` variables, then a `SUMMARY_ADD(...)` table at the bottom prints what
will be built. **Read that summary** before assuming a feature is missing --
`CURL_FOUND`, `HAVE_ZMQ`, `HAVE_GUILE` and friends silently disable
subsystems. `lib/Summary.cmake` implements the table.

Required: CogUtil >= 2.0.1, AtomSpace >= 5.0.3, Boost >= 1.46 (with
date_time, filesystem, program_options, regex, serialization, system, thread).
CxxTest is required for `tests/`.

## Known structural debt

Listed so that nobody rediscovers it the hard way:

* Several files exceed 1000 lines (`PatternMiner.cc` 2143,
  `LocalSpaceMap2D.cc`, `TangentBug.cc`, `Octree3DMapManager.cc`). Splitting
  them is a real task, not a mechanical refactor: they have no test coverage
  sufficient to prove a split is behaviour-preserving. Add characterisation
  tests first.
* `opencog/python` is mid-migration from Python 2.7. See the table in
  `CONTRIBUTING.md`.
* `opencog/embodiment` and `opencog/python/pln_old` are effectively archived
  and still Python 2 only. Nothing depends on them being modern; do not spend
  effort there without a reason.
* The C++ tree targets C++0x (`-std=gnu++0x`) and hand-rolls things
  `std::unique_ptr` and `<stdexcept>` now provide. `clang-tidy` is configured
  to surface these as advisory, not blocking, precisely because the
  conversion is large.
