__author__ = 'Cosmo Harrigan'

import logging

from flask import abort, jsonify, request
from flask.ext.restful import Resource, reqparse
from opencog.scheme_wrapper import scheme_eval
from flask_restful_swagger import swagger

from apisecurity import (
    ApiSecurityConfig,
    ValidationError,
    authorize,
    validate_command,
)

logger = logging.getLogger('opencog.restapi')

COGSERVER_PORT = 17001


def _get_header(name):
    """Header accessor in the shape :func:`apisecurity.authorize` expects."""
    return request.headers.get(name)


class SchemeAPI(Resource):
    """
    Defines an interface for issuing commands to and receiving responses from
    the OpenCog Scheme interpreter
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

        super(SchemeAPI, self).__init__()

    def _policy(self):
        """Resolve the security policy, preferring the one bound by the app."""
        config = getattr(SchemeAPI, 'config', None)
        if config is None:
            config = ApiSecurityConfig.from_env()
            SchemeAPI.config = config
        return config

    @swagger.operation(
	notes='''
Include a JSON object with the POST request containing the command
in a field named "command"

<p>Example command:

<pre>
{'command': '(cog-set-af-boundary! 100)'}
</pre>

<p>Returns:

<p>A JSON object containing the Scheme-formatted result of the command in
a field named "response".

<p>Example response:

<pre>
{'response': '100\n'}
</pre>

<p>Note that in this API, the request is processed synchronously. It
blocks until the request has finished.

<p>This functionality is implemented as a POST method because it can
cause side-effects.''',
	responseClass='response',
	nickname='post',
	parameters=[
	    {
		'name': 'command',
		'description': 'Scheme command',
		'required': True,
		'allowMultiple': False,
		'dataType': 'string',
		'paramType': 'body'
	    }
	],
	responseMessages=[
	    {'code': 200, 'message': 'Scheme command executed successfully'},
	    {'code': 400, 'message': 'Invalid request: Required parameter command missing'}
	]
    )
    def post(self):
        """
        Send a command to the Scheme interpreter
        """
        config = self._policy()
        # /scheme evaluates arbitrary Scheme, which is arbitrary code
        # execution inside the cogserver.  Authenticate and origin-check
        # before touching the body.
        authorize(config, _get_header)

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            raise ValidationError(
                'Invalid request: a JSON object body is required')

        command = validate_command(data.get('command'),
                                   config.max_command_length)
        try:
            response = scheme_eval(self.atomspace, command)
        except Exception:
            # Log the detail for the operator; return a generic message so
            # that interpreter internals are not disclosed to the caller.
            logger.exception('Scheme evaluation failed')
            abort(500, 'Error evaluating the Scheme command')

        return jsonify({'response': response})
