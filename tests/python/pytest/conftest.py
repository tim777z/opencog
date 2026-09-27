"""Pytest bootstrap for OpenCog's dependency-free Python test suite.

Why this file exists
--------------------
The C++ tree needs cogutil/atomspace/CxxTest before anything can be compiled,
which meant that until now there was no test command at all that worked on a
fresh clone.  The modules exercised by this suite are deliberately
standard-library-only (or pure Python), so they can be imported straight out
of the source tree with no build step:

    python -m pytest tests/python/pytest

or, once the project is installed into a virtualenv:

    make test
"""

from __future__ import absolute_import

import os
import sys

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(TESTS_DIR, "..", "..", ".."))

# The cogserver loads these modules by putting PYTHON_EXTENSION_DIRS on
# sys.path (see lib/opencog.conf), and they use flat intra-directory imports
# (e.g. `from apisecurity import ...`). Mirror that here so the same import
# statements work in the tests exactly as they do at runtime.
SOURCE_PATHS = (
    os.path.join(REPO_ROOT, "opencog", "python", "web", "api"),
    os.path.join(REPO_ROOT, "opencog", "python", "utility"),
    os.path.join(REPO_ROOT, "opencog", "python"),
)

for _path in SOURCE_PATHS:
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.insert(0, _path)
