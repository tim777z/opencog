__author__ = 'Cosmo Harrigan'

import json
import logging
import os
import uuid
from functools import wraps

from flask import Flask, request, g
from flask.ext.restful import Api
from flask.ext.cors import CORS

from apiatomcollection import *
from apitypes import *
from apishell import *
from apischeme import *
from apisecurity import (
    ApiSecurityConfig,
    ApiSecurityError,
    AuthenticationError,
    OriginNotAllowed,
    ValidationError,
    assert_safe_bind,
    is_origin_allowed,
)
from flask_restful_swagger import swagger
from health import register_health_endpoint

logger = logging.getLogger('opencog.restapi')

# Structured logging helper
def _log_structured(level, message, **fields):
    """Log a message with structured fields for machine parsing."""
    extra = {
        'request_id': getattr(g, 'request_id', None),
        'route': getattr(g, 'route', None),
        'method': getattr(g, 'method', None),
        'status_code': getattr(g, 'status_code', None),
    }
    extra.update(fields)
    # Filter out None values
    extra = {k: v for k, v in extra.items() if v is not None}
    logger.log(level, message, extra=extra)


def _request_id_middleware(app):
    """Add request_id to each request for tracing."""
    @app.before_request
    def _inject_request_id():
        g.request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())[:8]
        g.route = request.path
        g.method = request.method
        _log_structured(logging.INFO, 'Request started')

    @app.after_request
    def _log_response(response):
        g.status_code = response.status_code
        _log_structured(logging.INFO, 'Request completed',
                        status_code=response.status_code,
                        content_length=response.content_length)
        # Add request ID to response headers for client-side tracing
        response.headers['X-Request-ID'] = g.request_id
        return response


class RESTAPI(object):
    """
    REST API for OpenCog

    Implemented using the Flask micro-framework and Flask-RESTful extension

    Documentation:
    http://wiki.opencog.org/w/REST_API

    Prerequisites:
    Flask, mock, flask-restful, six, flask-restful-swagger

    Default endpoint: http://127.0.0.1:5000/api/v1.1/
    (Replace 127.0.0.1 with the IP address of the server if necessary)

    Example request: http://127.0.0.1:5000/api/v1.1/atoms?type=ConceptNode

    See: opencog/python/web/api/exampleclient.py for detailed examples of
    usage, and review the method definitions in each resource for request/
    response specifications.

    Security:
    This API can execute code in the cogserver process via the ``/shell`` and
    ``/scheme`` endpoints, so it is authenticated, CORS-restricted, size
    capped and bound to loopback by default.  See
    ``opencog/python/web/api/apisecurity.py`` for the full policy and the
    ``OPENCOG_API_*`` environment variables that control it.
    """

    def __init__(self, atomspace, config=None):
        self.atomspace = atomspace
        self.config = config or ApiSecurityConfig.from_env()

        # Initialize the web server and set the routing
        self.app = Flask(__name__, static_url_path="")
        self.app.config['MAX_CONTENT_LENGTH'] = self.config.max_content_length
        # Flask only needs this when sessions/messages are used, but an
        # unset SECRET_KEY is a latent weakness, so source it from the
        # environment rather than hard-coding a value in the image.
        self.app.config['SECRET_KEY'] = os.environ.get(
            'OPENCOG_API_SECRET_KEY', '')
        self.app.config['JSON_SORT_KEYS'] = False

        # Cross-origin resource sharing. flask-cors is instantiated (it
        # installs the preflight handling that browsers require) but the
        # default origin policy is *not* the wildcard: the actual allow-list
        # is enforced in after_request() below, from configuration.
        self.cors = CORS(self.app, resources={r'/api/*': {'origins': []}})

        # Create and add each resource
        atom_collection_api = AtomCollectionAPI.new(self.atomspace)
        atom_types_api = TypesAPI
        shell_api = ShellAPI
        scheme_api = SchemeAPI.new(self.atomspace)

        # Publish the one resolved policy to every resource so that all of
        # them enforce identical limits and share a single source of truth.
        for resource in (AtomCollectionAPI, TypesAPI, ShellAPI, SchemeAPI):
            resource.config = self.config

        self.api = swagger.docs(Api(self.app), apiVersion='1.1',
                                 api_spec_url='/api/v1.1/spec')
        self.api.add_resource(atom_collection_api,
                              '/api/v1.1/atoms',
                              '/api/v1.1/atoms/<int:id>', endpoint='atoms')
        self.api.add_resource(atom_types_api,
                              '/api/v1.1/types',
                              endpoint='types')
        self.api.add_resource(shell_api,
                              '/api/v1.1/shell',
                              endpoint='shell')
        self.api.add_resource(scheme_api,
                              '/api/v1.1/scheme',
                              endpoint='scheme')

        self.app.after_request(self._apply_response_headers)
        self._register_error_handlers()
        # Register request ID middleware for structured logging
        _request_id_middleware(self.app)
        # Register health check endpoint
        register_health_endpoint(self.app)

        logger.info('REST API configured: %r', self.config)
        if not self.config.auth_required:
            logger.warning(
                'The OpenCog REST API is running WITHOUT authentication. '
                'The /shell and /scheme endpoints execute code in the '
                'cogserver process. Set OPENCOG_API_TOKEN before exposing '
                'this service on any non-loopback interface.')
        assert_safe_bind(self.config)

    # ------------------------------------------------------------------
    # Cross-cutting response policy
    # ------------------------------------------------------------------
    def _apply_response_headers(self, response):
        """Emit CORS and hardening headers, driven by configuration.

        The previous code attached ``Access-Control-Allow-Origin: *`` to
        every response, which let any web page read the AtomSpace of a
        machine running cogserver.
        """
        origin = request.headers.get('Origin')
        if origin and is_origin_allowed(origin, self.config.allowed_origins):
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
            response.headers['Access-Control-Allow-Headers'] = \
                'Authorization, Content-Type'
            response.headers['Access-Control-Allow-Methods'] = \
                'GET, POST, PUT, DELETE, OPTIONS'
            response.headers['Access-Control-Max-Age'] = '600'
        response.headers.setdefault('X-Content-Type-Options', 'nosniff')
        response.headers.setdefault('X-Frame-Options', 'DENY')
        response.headers.setdefault('Cache-Control', 'no-store')
        return response

    def _register_error_handlers(self):
        """Translate policy violations into safe, non-informative responses.

        All JSON error responses follow a consistent schema:
        {
            "error_code": "AUTHENTICATION_ERROR|VALIDATION_ERROR|ORIGIN_NOT_ALLOWED|...",
            "message": "Human-readable description",
            "request_id": "optional request ID for tracing"
        }
        Nothing here echoes an internal exception message back to the client.
        """
        def _wants_json():
            accept = request.headers.get('Accept', '') or ''
            return 'application/json' in accept or \
                request.path.startswith('/api/')

        def _error_response(error_code, message, status, request_id=None):
            """Build a consistent JSON error response."""
            if _wants_json():
                body = json.dumps({
                    'error_code': error_code,
                    'message': message,
                    'request_id': request_id,
                })
                mimetype = 'application/json'
            else:
                body = message
                mimetype = 'text/plain'
            response = self.app.response_class(body, status=status,
                                               mimetype=mimetype)
            response.headers['X-Content-Type-Options'] = 'nosniff'
            if request_id:
                response.headers['X-Request-ID'] = request_id
            return response

        def _get_request_id():
            return getattr(g, 'request_id', None)

        @self.app.errorhandler(AuthenticationError)
        def _unauthorized(exc):
            request_id = _get_request_id()
            _log_structured(logging.WARNING, 'Authentication failed',
                            error_code='AUTHENTICATION_ERROR',
                            request_id=request_id)
            response = _error_response('AUTHENTICATION_ERROR',
                                       'valid bearer token required',
                                       401, request_id)
            response.headers['WWW-Authenticate'] = 'Bearer realm="opencog"'
            return response

        @self.app.errorhandler(OriginNotAllowed)
        def _forbidden(exc):
            request_id = _get_request_id()
            _log_structured(logging.WARNING, 'Origin not allowed',
                            error_code='ORIGIN_NOT_ALLOWED',
                            request_id=request_id)
            return _error_response('ORIGIN_NOT_ALLOWED',
                                   str(exc), 403, request_id)

        @self.app.errorhandler(ValidationError)
        def _bad_request(exc):
            request_id = _get_request_id()
            _log_structured(logging.WARNING, 'Validation error',
                            error_code='VALIDATION_ERROR',
                            request_id=request_id)
            return _error_response('VALIDATION_ERROR',
                                   str(exc), 400, request_id)

        @self.app.errorhandler(413)
        def _too_large(exc):
            request_id = _get_request_id()
            _log_structured(logging.WARNING, 'Request body too large',
                            error_code='PAYLOAD_TOO_LARGE',
                            request_id=request_id)
            return _error_response('PAYLOAD_TOO_LARGE',
                                   'request body too large', 413, request_id)

        @self.app.errorhandler(500)
        def _server_error(exc):
            # Log the detail, return a generic message. Echoing
            # str(exc) to the client used to disclose file paths and
            # library internals to unauthenticated callers.
            request_id = _get_request_id()
            _log_structured(logging.ERROR, 'Unhandled server error',
                            error_code='INTERNAL_SERVER_ERROR',
                            request_id=request_id,
                            path=request.path,
                            method=request.method)
            logger.exception('Unhandled error handling %s %s',
                             request.method, request.path)
            return _error_response('INTERNAL_SERVER_ERROR',
                                   'internal server error', 500, request_id)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def run(self, host=None, port=None):
        """
        Runs the REST API

        :param host: the hostname to listen on. Defaults to the configured
                     ``OPENCOG_API_BIND_HOST`` (loopback). Set to ``0.0.0.0``
                     to have the server available externally as well, which
                     *requires* ``OPENCOG_API_TOKEN`` to be set.
        :param port: the port of the webserver. Defaults to the configured
                     ``OPENCOG_API_BIND_PORT``.
        """
        host = self.config.bind_host if host is None else host
        port = self.config.bind_port if port is None else port
        if host is not None and host != self.config.bind_host:
            # Re-derive the policy so the "no auth on a routable interface"
            # guard is evaluated against the *effective* bind address.
            effective = ApiSecurityConfig(
                api_token=self.config.api_token,
                allowed_origins=self.config.allowed_origins,
                max_content_length=self.config.max_content_length,
                max_command_length=self.config.max_command_length,
                max_limit=self.config.max_limit,
                default_limit=self.config.default_limit,
                bind_host=host, bind_port=port)
            assert_safe_bind(effective)
        logger.info('Serving the OpenCog REST API on %s:%d', host, port)
        # use_reloader is deliberately off: the reloader re-executes the
        # process and would start a second unauthenticated listener.
        self.app.run(debug=False, host=host, port=port, use_reloader=False,
                     threaded=True)

    def test(self):
        """
        Returns a test client for the REST API
        """
        return self.app.test_client()
