__author__ = 'Cosmo Harrigan'

import contextlib
import logging
import socket

from flask import abort, jsonify, request
from flask.ext.restful import Resource, reqparse
from flask_restful_swagger import swagger

from apisecurity import (
    ApiSecurityConfig,
    ValidationError,
    authorize,
    validate_command,
)

logger = logging.getLogger('opencog.restapi')

#: CogServer shell port. The cogserver only ever listens on loopback, so
#: this connection is never exposed to the network.
COGSERVER_PORT = 17001

#: Never block a request thread forever on an unresponsive cogserver.
COGSERVER_CONNECT_TIMEOUT = 5.0
COGSERVER_IO_TIMEOUT = 30.0

#: Cap on the reply we are willing to buffer from the cogserver.
MAX_REPLY_BYTES = 1 << 20


def _get_header(name):
    """Header accessor in the shape :func:`apisecurity.authorize` expects."""
    return request.headers.get(name)


class ShellAPI(Resource):
    """
    Defines a barebones resource for sending shell commands to the CogServer

    Security: this endpoint forwards arbitrary cogserver commands, so it is
    authenticated and CORS-restricted by :mod:`apisecurity` like every other
    endpoint.
    """

    # This is because of https://github.com/twilio/flask-restful/issues/134
    @classmethod
    def new(cls, atomspace):
        cls.atomspace = atomspace
        cls.config = None
        return cls

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('command', type=str, location='args')

        super(ShellAPI, self).__init__()

    def _policy(self):
        """Resolve the security policy, preferring the one bound by the app.

        Falls back to the environment so that the resource is still usable
        standalone (e.g. in a test client) instead of crashing on a missing
        attribute.
        """
        config = getattr(ShellAPI, 'config', None)
        if config is None:
            config = ApiSecurityConfig.from_env()
            ShellAPI.config = config
        return config

    @swagger.operation(
	notes='''
Include a JSON object with the POST request containing the command
in a field named "command"

<p>Examples:

<pre>
{'command': 'agents-step'}
{'command': 'agents-step opencog::SimpleImportanceDiffusionAgent'}
</pre>

<p>Requires an "Authorization: Bearer &lt;token&gt;" header when the
server is started with OPENCOG_API_TOKEN set.''',
	responseClass='response',
	nickname='post',
	parameters=[
	    {
		'name': 'command',
		'description': 'OpenCog Shell command',
		'required': True,
		'allowMultiple': False,
		'dataType': 'string',
		'paramType': 'body'
	    }
	],
	responseMessages=[
	    {'code': 200, 'message': 'OpenCog Shell command executed successfully'},
	    {'code': 400, 'message': 'Invalid request: Required parameter command missing'},
	    {'code': 401, 'message': 'Authentication required'},
	    {'code': 502, 'message': 'The cogserver is unreachable or did not reply'}
	]
    )
    def post(self):
        """
        Send a shell command to the cogserver
        """
        config = self._policy()
        # Raises AuthenticationError / OriginNotAllowed, which the application
        # converts to 401/403.  This must happen before any body parsing.
        authorize(config, _get_header)

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError(
                'Invalid request: a JSON object body is required')
        command = validate_command(data.get('command'),
                                   config.max_command_length)

        reply = self._send_to_cogserver(command)
        return jsonify({'status': 'success', 'response': reply})

    def _send_to_cogserver(self, command):
        """Forward ``command`` to the cogserver and return its reply.

        Every failure mode here used to be an unhandled exception (a failed
        connect left ``connection`` unbound and raised UnboundLocalError),
        which returned a 500 with an internal traceback-shaped message.
        """
        payload = command.encode('utf-8')
        try:
            connection = socket.create_connection(
                ('127.0.0.1', COGSERVER_PORT), COGSERVER_CONNECT_TIMEOUT)
        except (socket.error, socket.timeout, OSError) as exc:
            logger.error('Could not reach the cogserver on port %d: %s',
                         COGSERVER_PORT, exc)
            abort(502, 'The cogserver is unreachable')

        try:
            connection.settimeout(COGSERVER_IO_TIMEOUT)
            connection.sendall(payload)
            try:
                reply = connection.recv(MAX_REPLY_BYTES)
            except (socket.error, socket.timeout, OSError) as exc:
                # The cogserver executed the command but did not answer in
                # time.  Report that honestly instead of pretending success.
                logger.error('The cogserver did not reply within %ss: %s',
                             COGSERVER_IO_TIMEOUT, exc)
                abort(504, 'The cogserver did not reply in time')
        finally:
            with contextlib.suppress(OSError):
                connection.close()

        if not reply:
            return ''
        try:
            return reply.decode('utf-8', 'replace')
        except Exception:  # pragma: no cover - defensive
            return repr(reply)
