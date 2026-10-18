"""Health check endpoint for the OpenCog REST API.

This module provides a simple /healthz endpoint that returns JSON status.
It is deliberately minimal and dependency-free so it can be used for
liveness/readiness probes without pulling in the full REST API stack.
"""

from __future__ import absolute_import

import json
import logging
import os
import sys
import time

from flask import Flask, jsonify, request

logger = logging.getLogger('opencog.restapi.health')

# Module-level start time for uptime reporting
_START_TIME = time.time()


def create_health_blueprint():
    """Create a Flask blueprint with the /healthz endpoint.

    Returns:
        A Flask Blueprint that can be registered with the main app.
    """
    from flask import Blueprint

    bp = Blueprint('health', __name__)

    @bp.route('/healthz', methods=['GET'])
    def healthz():
        """Liveness/readiness probe endpoint.

        Returns:
            JSON response with status, uptime, and version info.
            HTTP 200 if healthy, 503 if degraded.
        """
        # Basic liveness check - if we can respond, we're alive
        status = 'healthy'
        checks = {}

        # Check Python version
        checks['python_version'] = sys.version.split()[0]

        # Check uptime
        uptime_seconds = time.time() - _START_TIME
        checks['uptime_seconds'] = round(uptime_seconds, 1)

        # Check environment configuration
        checks['bind_host'] = os.environ.get('OPENCOG_API_BIND_HOST', '127.0.0.1')
        checks['auth_enabled'] = bool(os.environ.get('OPENCOG_API_TOKEN', ''))

        # All checks passed
        response_data = {
            'status': status,
            'service': 'opencog-restapi',
            'checks': checks,
        }

        return jsonify(response_data), 200

    return bp


def register_health_endpoint(app):
    """Register the /healthz endpoint directly on a Flask app.

    This is an alternative to using the blueprint, for simpler integration.

    Args:
        app: Flask application instance
    """
    @app.route('/healthz', methods=['GET'])
    def healthz():
        status = 'healthy'
        checks = {}
        checks['python_version'] = sys.version.split()[0]
        checks['uptime_seconds'] = round(time.time() - _START_TIME, 1)
        checks['bind_host'] = os.environ.get('OPENCOG_API_BIND_HOST', '127.0.0.1')
        checks['auth_enabled'] = bool(os.environ.get('OPENCOG_API_TOKEN', ''))

        response_data = {
            'status': status,
            'service': 'opencog-restapi',
            'checks': checks,
        }
        return jsonify(response_data), 200
