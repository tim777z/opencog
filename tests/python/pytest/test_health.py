"""Unit tests for the OpenCog REST API health endpoint and structured logging."""

from __future__ import absolute_import

import json

from health import create_health_blueprint, register_health_endpoint


class TestHealthEndpoint:
    """Tests for the /healthz endpoint."""

    def test_healthz_returns_200_and_json(self):
        """The health endpoint should return 200 with JSON."""
        from flask import Flask
        app = Flask(__name__)
        register_health_endpoint(app)
        client = app.test_client()

        response = client.get('/healthz')
        assert response.status_code == 200
        assert response.is_json

        data = json.loads(response.data)
        assert data['status'] == 'healthy'
        assert data['service'] == 'opencog-restapi'
        assert 'checks' in data
        assert 'python_version' in data['checks']
        assert 'uptime_seconds' in data['checks']
        assert 'bind_host' in data['checks']
        assert 'auth_enabled' in data['checks']

    def test_healthz_checks_structure(self):
        """The health checks should have the expected structure."""
        from flask import Flask
        app = Flask(__name__)
        register_health_endpoint(app)
        client = app.test_client()

        response = client.get('/healthz')
        data = json.loads(response.data)

        checks = data['checks']
        assert isinstance(checks['python_version'], str)
        assert isinstance(checks['uptime_seconds'], (int, float))
        assert checks['uptime_seconds'] >= 0
        assert isinstance(checks['bind_host'], str)
        assert isinstance(checks['auth_enabled'], bool)

    def test_healthz_blueprint_works(self):
        """The blueprint registration should work."""
        from flask import Flask
        app = Flask(__name__)
        bp = create_health_blueprint()
        app.register_blueprint(bp)
        client = app.test_client()

        response = client.get('/healthz')
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'healthy'
