"""Test agent used by the Cython preload tests.

This module is listed in ``tests/cython/pyeval.conf`` under ``PYTHON_PRELOAD``,
so the cogserver imports it at start-up. That means it runs inside the
server, where ``print`` output is interleaved with unrelated server chatter and
cannot be routed or filtered.

Logging through the standard ``logging`` module under a namespaced logger
keeps the output attributable to this module and lets the cogserver's log
configuration decide what is actually emitted.
"""

from __future__ import print_function

import logging

import opencog.cogserver

logger = logging.getLogger('opencog.test.preload')

logger.info("Preloaded %s", __name__)


class PreloadTestAgent(opencog.cogserver.MindAgent):

    def __init__(self):
        pass

    def run(self, atomspace):
        logger.info("running agent from preloaded file")
