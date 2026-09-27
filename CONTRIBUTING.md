# Contributing to OpenCog

Thanks for helping. This document is the operational half of the project:
what commands to run, what CI will check, and what a reviewer will expect.

## The short version

```bash
docker compose run --rm test     # build + full test run, no host setup
# or, natively:
make venv                        # pinned Python deps
make build                       # C++
make test                        # both suites
make lint                        # ruff + clang-tidy
```

`make help` lists every target with a one-line description.

## The test matrix

| Suite | Command | Needs a C++ build? | Runs in CI |
| ----- | ------- | ------------------ | ---------- |
| Python unit tests | `make test-python` | no | yes, on py3.8/3.11/3.12, every push |
| CxxTest suites | `make test-cpp` | yes | no (needs cogutil + atomspace) |
| Python integration | `ctest -R 'RestApiTest\|BlendingTest'` | yes | no (needs the Cython bindings) |
| Python lint | `make lint-python` | no | yes, blocking |
| C++ lint | `make lint-cpp` | yes (for `compile_commands.json`) | yes, on changed files |
| Dependency audit | `make audit` | no | yes, weekly |
| Secret scan | `make secret-scan` | no | yes, every push |

The Python unit tests under `tests/python/pytest/` are deliberately
**dependency-free**: they import only the standard library, so they run on a
fresh clone with `pip install pytest` and nothing else. That is the point of
having them -- it means there is always a green gate, even on a machine that
cannot build the C++ tree.

When you add a test, put it where it will actually run. A new test in a
directory nothing collects is worse than no test, because it looks like
coverage.

## Python 2 -> 3 migration status

The cogserver historically ran on Python 2.7, and most of `opencog/python`
still does. Rather than pretend otherwise, the linter is scoped to what it
can actually parse:

| Subtree | Python | Linted by ruff? |
| ------- | ------ | --------------- |
| `opencog/python/web/api` | 2.7 and 3.x | yes |
| `opencog/python/utility/csv_dataset_parser.py` | 2.7 and 3.x | yes |
| `tests/python/pytest` | 3.x | yes |
| `opencog/python/utility/` (rest) | 2.7 only | no (won't parse) |
| `opencog/python/learning`, `blending`, `conceptnet` | 2.7 | no |
| `opencog/python/pln_old` | 2.7, archived | no |
| `opencog/embodiment` | 2.7 | no |

To migrate a subtree: make it import cleanly on 3.x, add it to the
`[tool.ruff] include` list in `pyproject.toml`, fix what ruff reports, and
add a test that imports it. The scope list in `pyproject.toml` is the
source of truth; update it in the same PR.

New Python code should be **Python 3 clean** and avoid `print` statements,
`basestring`, `has_key`, and implicit relative imports. Use
`from __future__ import absolute_import` if you need the file to keep
working on 2.7 during a transition.

## Style

### C++

* `.clang-format` describes the target style: 4-space indent with tabs for
  indentation, Allman braces, 100 columns. Run `make format` on the files you
  touched. Do not reformat unrelated files -- it buries the real change.
* House style for exceptions is the `opencog::Exception` hierarchy
  (`InvalidParamException`, `NotFoundException`, ...) from
  `<opencog/util/exceptions.h>`, constructed with
  `THROW_XXX(TRACE_INFO, "printf-style %s", value)`. Do **not** `throw` a
  `std::string`: it is not a `std::exception`, so `catch (const
  std::exception&)` misses it, and a formatted literal is undefined
  behaviour rather than a message.
* Log through `logger()`, not `std::cout`. Include the component name in the
  message, as the existing modules do.

### Python

* `ruff check` and `ruff format` are the tools; both are blocking in CI.
* Log through the `logging` module, never `print`, in anything under
  `opencog/python`. The exception is the standalone example and demo
  scripts, which print to stdout on purpose.
* No `except:`. Catch the specific exception, and log the detail rather than
  returning `str(exc)` to a caller -- that pattern leaked internal paths and
  object layouts to unauthenticated REST clients.
* Validate and bound anything that arrives over the network or from a file.
  `opencog/python/web/api/apisecurity.py` is the reference implementation.

## Adding a C++ module

1. Create `opencog/<subsystem>/`.
2. Add a `CMakeLists.txt` modelled on a neighbouring one; register the
   library, its headers and its dependencies explicitly rather than relying on
   directory order.
3. Register any configuration keys in `lib/opencog.conf` with a default, and
   document them.
4. Add a `tests/<subsystem>/` directory with a CxxTest suite, and register it
   in `tests/CMakeLists.txt`. A module with no test does not get merged.
5. Add a line to `SUMMARY_ADD(...)` in the top-level `CMakeLists.txt` so it
   shows up in the configure summary.

## Adding a REST endpoint

1. Add the resource class in `opencog/python/web/api/`.
2. Call `self._authorize()` as the **first** statement of every handler, before
   touching the request body.
3. Validate every input through a helper in `apisecurity.py` and raise
   `ValidationError`; the app converts those to 4xx responses with a safe
   message. Never echo an internal exception to the client.
4. Bound anything unbounded: page sizes, string lengths, list sizes.
5. Add a test under `tests/python/pytest/`.

## Review expectations

* A behaviour change needs a test. A security fix needs a test that fails
  without the fix.
* Keep the diff reviewable. A 2000-line reformat in the same PR as a
  one-line bug fix means the bug fix does not get reviewed.
* Update `README.md` if you changed a build step, a test command, a default
  port, or a security default; update `CHANGELOG.md` under *Unreleased*.
* If you fixed a defect, say what it was in the PR description. "Fixed a
  crash" is not reviewable; "`std::string` constructed from a format string
  read out of bounds, reachable via the `dim-embedding` Scheme bindings" is.

## Commits and branches

* One logical change per commit; a commit builds and its tests pass.
* Reference the issue in the subject or body.
* Do not commit `.env`, `requirements.lock.txt` unless you ran `make lock`,
  or `build/` output.

## License

OpenCog is AGPL-3.0-or-later. CI runs a license scan over the Python
dependency tree; introducing a copyleft dependency that blocks proprietary
redistribution requires legal sign-off first.
