OpenCog
=======
[![CI](https://github.com/opencog/opencog/actions/workflows/ci.yml/badge.svg)](https://github.com/opencog/opencog/actions/workflows/ci.yml)
[![Security](https://github.com/opencog/opencog/actions/workflows/security.yml/badge.svg)](https://github.com/opencog/opencog/actions/workflows/security.yml)

OpenCog is a framework for developing AI systems, especially appropriate
for integrative multi-algorithm systems, and artificial general intelligence
systems.  Though much work remains to be done, it currently contains a
functional core framework, and a number of cognitive agents at varying levels
of completion, some already displaying interesting and useful functionalities
alone and in combination.

The main project site is at http://opencog.org

An interactive tutorial for getting started is available at:
https://github.com/opencog/opencog/blob/master/TUTORIAL.md

Quick start
-----------
The fastest way to get a working build *and* a passing test run from a fresh
clone, with no host-side state:

```bash
docker compose run --rm test
```

That builds `cogutils`, `atomspace` and `opencog` from pinned sources inside
the image and runs every suite the tree can run. No `sudo make install` in
three directories.

Prefer a native build? See **Reproducible Build** below. `make help` lists
every target.

Prerequisites
-------------
To build and run OpenCog, the packages listed below are required.
With a few exceptions, most Linux distributions will provide these
packages. Users of Ubuntu 14.04 "Trusty Tahr" may use the dependency
installer at `/scripts/octool`.  Users of any version of Linux may
use the Dockerfile to quickly build a container in which OpenCog will
be built and run.

###### cogutil
> Common OpenCog C++ utilities
> http://github.com/opencog/cogutils
> It uses exactly the same build procedure as this package. Be sure
  to `sudo make install` at the end.

###### atomspace
> OpenCog Atomspace database and reasoning engine
> http://github.com/opencog/atomspace
> It uses exactly the same build procedure as this package. Be sure
  to `sudo make install` at the end.


Optional Prerequisites
----------------------
The following packages are optional. If they are not installed, some
optional parts of OpenCog will not be built.  The CMake command, during
the build, will be more precise as to which parts will not be built.

###### curl
> cURL groks URLs
> Used by opencog/ubigraph
> http://curl.haxx.se/ | libcurl4-gnutls-dev

###### expat
> an XML parsing library
> Used by Embodiment subsystem
> http://expat.sourceforge.net/ | http://www.jclark.com/xml/expat.html (version 1.2) | libexpat1-dev

###### Link Grammar
> Natural Language Parser for English, Russian, other languages.
> Required for experimental Viterbi parser.
> http://www.abisource.com/projects/link-grammar/

###### MOSES
> MOSES Machine Learning
> http://github/opencog/moses
> It uses exactly the same build proceedure as this pakcage. Be sure
  to `sudo make install` at the end.

###### OpenGL
> Open Graphics Library
> Used by opencog/spatial/MapTool
> http://www.opengl.org
> Commonly provided with your video card driver

###### SDL
> Simple DirectMedia Layer
> Used by opencog/spatial/MapTool
> http://www.libsdl.org | libsdl1.2-dev

###### SDL_gfx
> Simple DirectMedia Layer extension
> Used by opencog/spatial/MapTool
> http://www.ferzkopp.net/joomla/content/view/19/14/ | libsdl-gfx1.2-dev

###### Threading Building Blocks
> C++ template library for parallel programming
> https://www.threadingbuildingblocks.org/download | libtbb-dev

###### xercesc
> Apache Xerces-C++ XML Parser
> Required for embodiment
> http://xerces.apache.org/xerces-c/ | libxerces-c-dev

###### xmlrpc
> XML-RPC support
> Required by opencog/ubigraph
> http://www.xmlrpc.com | libxmlrpc-c-dev

###### ZeroMQ (version 3.2.4 or higher)
> Asynchronous messaging library
> http://zeromq.org/intro:get-the-software | libzmq3-dev

Building OpenCog
----------------
Perform the following steps at the shell prompt:
```
    cd to project root dir
    mkdir build
    cd build
    cmake ..
    make
```
Libraries will be built into subdirectories within build, mirroring
the structure of the source directory root.

Reproducible Build
------------------
A build that depends on "whatever `master` happened to be today" is not
reproducible, and neither is one that depends on a sibling repository the
reader has to install by hand. Both are addressed here.

**Pinned sibling repositories.** This tree will not configure until `cogutil`
and `atomspace` are built and installed, because the top-level
`CMakeLists.txt` declares:

```cmake
FIND_PACKAGE(CogUtil 2.0.1 REQUIRED)
FIND_PACKAGE(AtomSpace 5.0.3 REQUIRED)
```

The refs are declared in exactly one place each -- the `Makefile` and the
`Dockerfile` -- so that a release can pin them to commit SHAs:

| Repository | URL | Pinned ref variable |
| ---------- | --- | ------------------- |
| cogutils   | <https://github.com/opencog/cogutils>   | `COGUTIL_REF`   |
| atomspace  | <https://github.com/opencog/atomspace>  | `ATOMSPACE_REF`  |

Current values (from `Makefile`): `master` for both. **Before cutting a
release, replace these with commit SHAs** and record them in
`CHANGELOG.md`; a tag without pinned dependency SHAs is not a reproducible
release, only a snapshot.

To build a fully pinned image without editing any file:

```bash
COGUTIL_REF=<sha>   ATOMSPACE_REF=<sha>   docker compose build
```

**Pinned Python dependencies.** `requirements.lock.txt` holds the exact
versions the test suite and linter are verified against; `requirements.txt`
holds the readable, human-maintained input; `pyproject.toml` is the
machine-readable manifest and the source of the `[tool.*]` configuration for
pytest, coverage and ruff.

```bash
make venv     # .venv with requirements.lock.txt installed
make lock     # regenerate the lock (needs network + pip-tools)
```

**Native dependencies.** `scripts/install-*-dependencies.sh` covers
Debian/Ubuntu, Fedora, Arch and openSUSE. The Docker image installs its
packages explicitly rather than fetching a bootstrap script, because
`ADD <url>` followed by `chmod +x` is remote-code execution at build time.

Unit tests
----------
**The test command is `make test`.** It runs both suites:

```
    make test            # everything
    make test-python     # pytest, no C++ build required
    make test-cpp        # CxxTest via ctest, requires a C++ build
```

`make test-python` needs nothing but CPython and the standard library. It is
the gate that runs on every push for every supported Python version, because
it is the one that always works:

```bash
python -m pip install -r requirements.lock.txt
python -m pytest
```

Coverage:

```bash
make coverage       # Python: writes build/coverage-python/index.html
make coverage-cpp   # C++: gcov build, runs ctest, combines via lcov
```

The CxxTest suites under `tests/` and the nosetests suites under
`tests/python/restapi` and `tests/python/blending_test` require a built
AtomSpace and the Cython bindings; see `CONTRIBUTING.md` for the full test
matrix.

Lint and format
---------------
```bash
make lint           # ruff + clang-tidy
make lint-python    # ruff only
make lint-cpp       # clang-tidy over the files a PR touched
make format         # clang-format, new and modified code
```

`.clang-tidy` and `.clang-format` are at the repo root. Both are configured
for a large legacy C++0x tree: the security and correctness checks are
errors, style findings are advisory, and CI runs the C++ lint over changed
files only so that pre-existing debt is paid down incrementally instead of
being grandfathered in.

Security
--------
**The REST API can execute code in the cogserver process.**
`/api/v1.1/shell` forwards arbitrary cogserver commands and
`/api/v1.1/scheme` evaluates arbitrary Scheme. Treat the service as
equivalent to an unauthenticated remote shell unless you configure it
otherwise.

The defaults are the safe ones, defined in
`opencog/python/web/api/apisecurity.py`:

| Control | Default | Environment variable |
| ------- | ------- | -------------------- |
| Bind address | `127.0.0.1` | `OPENCOG_API_BIND_HOST` |
| Authentication | off (loopback only) | `OPENCOG_API_TOKEN` |
| CORS origins | loopback API origins only | `OPENCOG_API_ALLOWED_ORIGINS` |
| Max request body | 1 MiB | `OPENCOG_API_MAX_CONTENT_LENGTH` |
| Max command length | 8192 chars | `OPENCOG_API_MAX_COMMAND_LENGTH` |
| Max page size | 10000 | `OPENCOG_API_MAX_LIMIT` |

The server **refuses to start** on a non-loopback interface with
`OPENCOG_API_TOKEN` unset. To expose it deliberately:

```bash
export OPENCOG_API_TOKEN="$(openssl rand -hex 32)"
export OPENCOG_API_BIND_HOST=0.0.0.0
curl -H "Authorization: Bearer $OPENCOG_API_TOKEN" \
     -H 'Content-Type: application/json' \
     -d '{"command":"agents-step"}' \
     http://127.0.0.1:5000/api/v1.1/shell
```

See `.env.example` for a copy-pasteable template, and `SECURITY.md` for how
to report a vulnerability. The historical defaults (bind `0.0.0.0`,
`Access-Control-Allow-Origin: *`, no authentication, unbounded request
bodies, an unbounded atom dump) meant that any web page a user visited
could drive their cogserver cross-origin; that path is now closed.

Logging
-------
The cogserver logs through `opencog::logger()`. Levels and sinks are set in
`lib/opencog.conf`:

```
# Log level: DEBUG, INFO, WARNING, ERROR
LOG_LEVEL=INFO
# Send output to a file as well as the console
LOG_FILE=opencog.log
# When DEBUG, log every incoming Scheme evaluation. This can be very
# verbose and may include user data -- do not enable it in production.
LOG_CONSOLE=1
```

Start the server with a specific file via `cogserver -c <config-filename>`.
The Python components log under the `opencog.restapi` and
`opencog.csv_dataset_parser` logger names, and route through the standard
`logging` module rather than `print`, so they can be redirected without
patching the source. `OPENCOG_LOG_LEVEL` sets the level for the cogserver's
Python preloads.

Architecture
------------
See `docs/ARCHITECTURE.md` for the module map, the request/data flow through
the cogserver, and where to add a new module. Contributing guidelines,
including the Python 2 -> 3 migration status of each subtree, are in
`CONTRIBUTING.md`; notable behaviour changes are in `CHANGELOG.md`.

Using OpenCog
-------------
OpenCog can be used in one of three ways, or a mixture of all three:
By using the GNU Guile scheme interface, by using Python, or by running
the cogserver.

Guile provides the easiest interface for creating atoms, loading them
into the AtomSpace, and performing various processing operations on
them.  For examples, see the `/examples/guile` and the
`/examples/pattern-matcher` directories.

Python is more familiar than scheme (guile) to most programmers, and
it offers another way of intrfacing to the atomspace. See the
`/examples/python` directory for how to use python with OpenCog.

The cogserver provides a network server interface to OpenCog. It is
requires for running embodiment, some of the reasoning agents, and some
of the natural-language processing agents.

Running the server
------------------
The cogserver provides a network server interface to the various
components and agents.  After building everything, change directory
to your `opencog/build` folder and execute `opencog/server/cogserver`.
Then, from another terminal, run `rlwrap telnet localhost 17001`
The `help` command will list all of the other available commands.
Notable among these are the commands to attach to a (Postgres) database,
and networked scheme and python interfaces (i.e. scheme and python
shells that are usable over the network, if you are logged in remotely
to the cogserver).

The operation of the server can be altered by means of a config file.
This config file is in `lib/opencog.conf`. To make use of it, say
`cogserver -c <config-filename>` when starting the server. See the
**Logging** and **Security** sections above for what to configure there.

> The cogserver's telnet interface has no authentication beyond a shared
> password in `lib/opencog.conf`, and it grants full Scheme evaluation.
> Change `COGSERVER_PASSWORD` before any deployment that is reachable from
> another machine, and prefer the REST API with `OPENCOG_API_TOKEN` set over
> exposing telnet.


CMake notes
-----------
Some useful CMake's web sites/pages:

 - http://www.cmake.org (main page)
 - http://www.cmake.org/Wiki/CMake_Useful_Variables
 - http://www.cmake.org/Wiki/CMake_Useful_Variables/Get_Variables_From_CMake_Dashboards
 - http://www.cmake.org/Wiki/CMakeMacroAddCxxTest
 - http://www.cmake.org/Wiki/CMake_HowToFindInstalledSoftware


The main CMakeLists.txt currently sets -DNDEBUG. This disables Boost
matrix/vector debugging code and safety checks, with the benefit of
making it much faster. Boost sparse matrixes and (dense) vectors are
currently used by ECAN's ImportanceDiffusionAgent. If you use Boost
ublas in other code, it may be a good idea to at least temporarily
unset NDEBUG. Also if the Boost assert.h is used it will be necessary
to unset NDEBUG. Boost ublas is intended to respond to a specific
BOOST_UBLAS_NDEBUG, however this is not available as of the current
Ubuntu standard version (1.34).

-Wno-deprecated is currently enabled by default to avoid a number of
warnings regarding hash_map being deprecated (because the alternative
is still experimental!)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for the build, test and lint workflow
and the review expectations. To report a vulnerability, see
[SECURITY.md](SECURITY.md). Notable behaviour changes are recorded in
[CHANGELOG.md](CHANGELOG.md).

