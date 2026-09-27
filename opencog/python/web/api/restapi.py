__author__ = 'Cosmo Harrigan'

import logging
from threading import Thread

import opencog.cogserver
from apisecurity import ApiSecurityConfig, assert_safe_bind
from web.api.apimain import RESTAPI

logger = logging.getLogger('opencog.restapi')

# Endpoint configuration
#
# Historically this module hard-coded IP_ADDRESS = '0.0.0.0' and PORT = 5000,
# which published an unauthenticated cogserver/Scheme endpoint (i.e. remote
# code execution) on every interface of the host.  Both values are now taken
# from the environment and default to loopback; see
# opencog/python/web/api/apisecurity.py for the full policy.
CONFIG = ApiSecurityConfig.from_env()
IP_ADDRESS = CONFIG.bind_host
PORT = CONFIG.bind_port


class Start(opencog.cogserver.Request):
    """
    Implements a CogServer Module to load upon startup that will load the REST
    API defined in apimain.py

    Prerequisites:
        1) Requires installation of the Python dependencies by running:
            sudo ./install_dependencies.sh

        2) Requires the configuration file (opencog.conf) to contain the
           following parameters:
            - PYTHON_EXTENSION_DIRS must specify the relative location of the
              API scripts
                Example: PYTHON_EXTENSION_DIRS = ../opencog/python/web/api
            - PYTHON_PRELOAD must specify the restapi module
                Example: PYTHON_PRELOAD = restapi

    To start the REST API, type restapi.Start at the CogServer shell
    """

    summary = "Start the OpenCog REST API"
    description = "Usage: restapi.Start\n\nStarts the OpenCog REST API. " \
                  "This will provide a REST interface to the Atomspace,\n" \
                  "allowing you to create, read, update and delete atoms " \
                  "across the network using\nHTTP requests/responses with " \
                  "JSON-formatted data.\n\nDefault endpoint: " \
                  "http://127.0.0.1:5000/api/v1.1/\nExample request: " \
                  "http://127.0.0.1:5000/api/v1.1/atoms?type=ConceptNode"

    def __init__(self):
        self.atomspace = None  # Will be passed as argument in run method
        self.api = None
        self.config = CONFIG

    def run(self, args, atomspace):
        self.atomspace = atomspace
        # Refuse to start on a routable interface without authentication.
        # Failing here is much better than coming up as an open RCE service.
        assert_safe_bind(self.config)
        '''
        make a daemon thread so that it can be interrupted
        '''
        thread = Thread(target=self.invoke)
        # setDaemon() is deprecated since Python 2.6 and raises DeprecationWarning
        thread.daemon = True
        thread.start()
        logger.info('REST API is now running in a separate daemon thread on %s:%d',
                    IP_ADDRESS, PORT)

    def invoke(self):
        self.api = RESTAPI(self.atomspace, config=self.config)
        self.api.run(host=IP_ADDRESS, port=PORT)
