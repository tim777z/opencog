__author__ = 'Cosmo Harrigan'

from flask import json, current_app, request
from flask.ext.restful import Resource, reqparse
from mappers import *
from flask_restful_swagger import swagger
from apisecurity import authorize, validate_jsonp_callback

import logging

logger = logging.getLogger('opencog.restapi')


def _get_header(name):
    """Header accessor in the shape :func:`apisecurity.authorize` expects."""
    return request.headers.get(name)


class TypesAPI(Resource):
    config = None

    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('callback', type=str, location='args')
        super(TypesAPI, self).__init__()

    def _authorize(self):
        from apisecurity import ApiSecurityConfig
        config = getattr(TypesAPI, 'config', None)
        if config is None:
            config = ApiSecurityConfig.from_env()
            TypesAPI.config = config
        return authorize(config, _get_header)

    # Note: cross-origin headers are emitted by the application-level
    # after_request hook from configuration. The old per-resource
    # ``cors.crossdomain(origin='*')`` decorator made this endpoint readable
    # by any web page on any origin.
    @swagger.operation(
	notes='''
Returns a JSON representation of a list of valid atom types

<p>Example:

<pre>
{"types": ["TrueLink", "NumberNode", "OrLink",
  "PrepositionalRelationshipNode"]}
</pre>
''',
	responseClass='response',
	nickname='get',
	parameters=[
	],
	responseMessages=[
	    {'code': 200, 'message': 'Returned list of valid atom types'},
	]
    )
    def get(self):
        """
        Returns a list of valid atom types
        """
        self._authorize()

        # sorted() also makes the payload deterministic, which matters for
        # caching and for clients that diff the type list between releases.
        json_data = \
            {'types': sorted(x for x in types.__dict__
                             if not x.startswith('__')
                             and not x.endswith('__')
                             and x != 'NO_TYPE')}

        # if callback function supplied, pad the JSON data (i.e. JSONP).
        # `callback` is validated as a bare JavaScript identifier so that
        # this cannot be used to inject script.
        args = self.reqparse.parse_args()
        callback = validate_jsonp_callback(args.get('callback'))
        if callback is not None:
            response = callback + '(' + json.dumps(json_data) + ');'
            return current_app.response_class(
                response, mimetype='application/javascript')
        return current_app.response_class(
            json.dumps(json_data), mimetype='application/json')
