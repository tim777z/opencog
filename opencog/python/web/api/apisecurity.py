"""Security policy for the OpenCog REST API.

This module deliberately depends on **nothing but the Python standard
library** (and is written to run unmodified on Python 2.7 and Python 3.x).
That has two purposes:

1.  It is importable -- and therefore unit testable -- on a fresh clone,
    without Flask, without the AtomSpace Cython bindings and without a
    running cogserver.  See ``tests/python/pytest/test_apisecurity.py``.
2.  It keeps the security policy in one auditable place instead of being
    smeared across the Flask resource classes.

Why this exists
---------------
The REST API exposes ``/api/v1.1/shell`` (arbitrary cogserver commands) and
``/api/v1.1/scheme`` (arbitrary Scheme evaluation, i.e. arbitrary code
execution inside the cogserver process).  Historically the server bound to
``0.0.0.0`` with a wildcard CORS policy and no authentication at all, which
meant that *any web page the user happened to visit* could drive the cogserver
cross-origin via a "simple" request, and that anybody on the network could do
so directly.  The helpers below turn those insecure defaults into explicit,
configurable, fail-closed policy.

Policy summary (all values are overridable through the environment)
-------------------------------------------------------------------
``OPENCOG_API_TOKEN``
    Bearer token required on every ``/api/v1.1`` request.  **Empty means
    authentication is disabled**, which is only acceptable on a loopback
    bind; :func:`assert_safe_bind` enforces that at start-up.
``OPENCOG_API_ALLOWED_ORIGINS``
    Comma separated list of origins allowed to read responses
    cross-origin.  Defaults to the loopback API origins only, so the
    wildcard is *not* the default.  Empty string denies all cross-origin
    reads.
``OPENCOG_API_MAX_CONTENT_LENGTH``
    Maximum accepted request body in bytes (default 1 MiB).  Bounds
    unauthenticated memory growth and request smuggling.
``OPENCOG_API_MAX_COMMAND_LENGTH``
    Maximum accepted cogserver/Scheme command length in characters
    (default 8192).  Bounds CPU spent inside the interpreter.
``OPENCOG_API_MAX_LIMIT`` / ``OPENCOG_API_DEFAULT_LIMIT``
    Ceiling and default page size for ``GET /api/v1.1/atoms``.  An
    unbounded atom dump is a trivially reachable memory-exhaustion DoS.
``OPENCOG_API_BIND_HOST`` / ``OPENCOG_API_BIND_PORT``
    Listen address.  Defaults to ``127.0.0.1``, not ``0.0.0.0``.
"""

from __future__ import absolute_import, print_function

import hmac
import logging
import os
import re

__all__ = [
    "ApiSecurityConfig",
    "ApiSecurityError",
    "AuthenticationError",
    "OriginNotAllowed",
    "ValidationError",
    "DEFAULT_ALLOWED_ORIGINS",
    "DEFAULT_BIND_HOST",
    "DEFAULT_BIND_PORT",
    "DEFAULT_MAX_COMMAND_LENGTH",
    "DEFAULT_MAX_CONTENT_LENGTH",
    "DEFAULT_MAX_LIMIT",
    "DEFAULT_DEFAULT_LIMIT",
    "JSONP_CALLBACK_RE",
    "assert_safe_bind",
    "authorize",
    "coerce_limit",
    "is_origin_allowed",
    "validate_command",
    "validate_jsonp_callback",
    "validate_token",
]

logger = logging.getLogger("opencog.restapi")

#: Origins that are allowed to read responses cross-origin by default.
#: Deliberately *not* ``*``: the API is normally reached from the local
#: machine, and a wildcard turns it into a cross-site data-exfiltration
#: primitive for any page the user visits.
DEFAULT_ALLOWED_ORIGINS = ("http://127.0.0.1:5000", "http://localhost:5000")

DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 5000
DEFAULT_MAX_CONTENT_LENGTH = 1024 * 1024  # 1 MiB
DEFAULT_MAX_COMMAND_LENGTH = 8192
DEFAULT_MAX_LIMIT = 10000
DEFAULT_DEFAULT_LIMIT = 100

#: A JSONP callback must be a bare JavaScript identifier path.  Anything
#: else (operators, parens, statements, newlines) turns the endpoint into a
#: reflected XSS primitive because the response is served as
#: ``application/javascript``.
JSONP_CALLBACK_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*){0,2}$")

_LOOPBACK_HOSTS = frozenset(("127.0.0.1", "localhost", "::1", "0:0:0:0:0:0:0:1"))


class ApiSecurityError(Exception):
    """Base class for REST API policy violations."""


class AuthenticationError(ApiSecurityError):
    """Raised when a request does not carry a valid bearer token."""


class OriginNotAllowed(ApiSecurityError):
    """Raised when a request carries a disallowed ``Origin`` header."""


class ValidationError(ApiSecurityError):
    """Raised when request input fails validation.

    Carries a short, safe, client-facing message.  Never wrap raw internal
    exception text in here: this API used to echo ``str(exc)`` straight back
    to the caller, which leaked file paths and library internals.
    """


def _as_int(raw, default, minimum=1, maximum=None):
    """Parse an environment integer defensively (never raises)."""
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Ignoring non-integer configuration value %r; using %d", raw, default)
        return default
    if value < minimum:
        logger.warning("Clamping out-of-range configuration value %d to %d", value, minimum)
        value = minimum
    if maximum is not None and value > maximum:
        logger.warning("Clamping out-of-range configuration value %d to %d", value, maximum)
        value = maximum
    return value


class ApiSecurityConfig(object):
    """Resolved, validated security policy for one API process."""

    __slots__ = (
        "api_token",
        "allowed_origins",
        "max_content_length",
        "max_command_length",
        "max_limit",
        "default_limit",
        "bind_host",
        "bind_port",
    )

    def __init__(
        self,
        api_token="",
        allowed_origins=DEFAULT_ALLOWED_ORIGINS,
        max_content_length=DEFAULT_MAX_CONTENT_LENGTH,
        max_command_length=DEFAULT_MAX_COMMAND_LENGTH,
        max_limit=DEFAULT_MAX_LIMIT,
        default_limit=DEFAULT_DEFAULT_LIMIT,
        bind_host=DEFAULT_BIND_HOST,
        bind_port=DEFAULT_BIND_PORT,
    ):
        self.api_token = api_token or ""
        self.allowed_origins = tuple(allowed_origins or ())
        self.max_content_length = int(max_content_length)
        self.max_command_length = int(max_command_length)
        self.max_limit = int(max_limit)
        self.default_limit = int(default_limit)
        self.bind_host = bind_host or DEFAULT_BIND_HOST
        self.bind_port = int(bind_port)

    @classmethod
    def from_env(cls, environ=None):
        """Build a config from ``environ`` (defaults to ``os.environ``)."""
        environ = os.environ if environ is None else environ
        raw_origins = environ.get("OPENCOG_API_ALLOWED_ORIGINS")
        if raw_origins is None:
            origins = DEFAULT_ALLOWED_ORIGINS
        else:
            # An explicitly empty value means "deny every cross-origin read",
            # which is a legitimate hardening choice, so do not fall back.
            origins = tuple(o.strip() for o in raw_origins.split(",") if o.strip())
        return cls(
            api_token=(environ.get("OPENCOG_API_TOKEN") or "").strip(),
            allowed_origins=origins,
            max_content_length=_as_int(
                environ.get("OPENCOG_API_MAX_CONTENT_LENGTH"),
                DEFAULT_MAX_CONTENT_LENGTH,
                minimum=1024,
            ),
            max_command_length=_as_int(
                environ.get("OPENCOG_API_MAX_COMMAND_LENGTH"),
                DEFAULT_MAX_COMMAND_LENGTH,
                minimum=1,
                maximum=1 << 20,
            ),
            max_limit=_as_int(
                environ.get("OPENCOG_API_MAX_LIMIT"), DEFAULT_MAX_LIMIT, minimum=1, maximum=1 << 24
            ),
            default_limit=_as_int(
                environ.get("OPENCOG_API_DEFAULT_LIMIT"),
                DEFAULT_DEFAULT_LIMIT,
                minimum=1,
                maximum=1 << 24,
            ),
            bind_host=(environ.get("OPENCOG_API_BIND_HOST") or DEFAULT_BIND_HOST).strip(),
            bind_port=_as_int(
                environ.get("OPENCOG_API_BIND_PORT"), DEFAULT_BIND_PORT, minimum=1, maximum=65535
            ),
        )

    @property
    def auth_required(self):
        return bool(self.api_token)

    @property
    def is_loopback_bind(self):
        return self.bind_host in _LOOPBACK_HOSTS

    def __repr__(self):
        # Never let the token reach a log line.
        return (
            "ApiSecurityConfig(bind_host=%r, bind_port=%d, "
            "auth_required=%r, allowed_origins=%r, max_content_length=%d, "
            "max_command_length=%d, max_limit=%d, default_limit=%d)"
            % (
                self.bind_host,
                self.bind_port,
                self.auth_required,
                self.allowed_origins,
                self.max_content_length,
                self.max_command_length,
                self.max_limit,
                self.default_limit,
            )
        )


def validate_token(expected, presented):
    """Constant-time comparison of a presented bearer token.

    Uses :func:`hmac.compare_digest` where available (Python 2.7.7+ and all
    Python 3) and falls back to a hand-rolled constant-time loop otherwise, so
    that token comparison never leaks its length or a prefix through timing.
    """
    if not expected:
        # Authentication disabled by configuration; see assert_safe_bind.
        return True
    if not presented:
        return False
    expected = expected.encode("utf-8") if hasattr(expected, "encode") else expected
    presented = presented.encode("utf-8") if hasattr(presented, "encode") else presented
    compare_digest = getattr(hmac, "compare_digest", None)
    if compare_digest is not None:
        return compare_digest(expected, presented)
    if len(expected) != len(presented):
        return False
    result = 0
    for left, right in zip(bytearray(expected), bytearray(presented)):
        result |= left ^ right
    return result == 0


def extract_bearer_token(get_header):
    """Pull a bearer token out of an ``Authorization`` header.

    ``get_header`` is a callable so that this stays Flask-free and testable.
    Returns ``None`` when no usable credential is present -- never raises on
    malformed input, because a malformed header must fail the same way a
    missing one does.
    """
    raw = get_header("Authorization")
    if not raw:
        return None
    if not isinstance(raw, str):
        try:
            raw = raw.decode("utf-8", "replace")
        except Exception:  # pragma: no cover - defensive
            return None
    parts = raw.split(None, 1)
    if len(parts) != 2:
        return None
    scheme, value = parts
    if scheme.lower() != "bearer":
        return None
    value = value.strip()
    return value or None


def authorize(config, get_header):
    """Authenticate a request.  Raises :class:`AuthenticationError` on failure.

    Also enforces the CORS origin allow-list when the browser sends an
    ``Origin`` header.  Rejecting server-side (rather than relying on the
    ``Access-Control-Allow-Origin`` response header alone) is what actually
    stops a malicious page from issuing a "simple" cross-origin POST.
    """
    if not config.auth_required:
        _assert_origin_allowed(config, get_header)
        return True
    presented = extract_bearer_token(get_header)
    if not validate_token(config.api_token, presented):
        logger.warning("Rejected REST API request with a missing or invalid " "bearer token")
        raise AuthenticationError("valid bearer token required")
    _assert_origin_allowed(config, get_header)
    return True


def _assert_origin_allowed(config, get_header):
    origin = get_header("Origin")
    if not origin:
        # Same-origin request, or a non-browser client.  Nothing to check.
        return
    if not is_origin_allowed(origin, config.allowed_origins):
        logger.warning("Rejected cross-origin REST API request from %s", origin)
        raise OriginNotAllowed("origin %s is not allowed" % origin)


def is_origin_allowed(origin, allowed_origins):
    """True when ``origin`` is in the allow-list (or the list is a wildcard)."""
    if not origin:
        return True
    for candidate in allowed_origins or ():
        if candidate == "*":
            return True
        if candidate.rstrip("/") == origin.rstrip("/"):
            return True
    return False


def assert_safe_bind(config):
    """Fail closed on the one configuration that is genuinely exploitable.

    Exposing an unauthenticated cogserver/Scheme endpoint on a routable
    interface is remote code execution.  Rather than silently allowing it, we
    refuse to start and tell the operator exactly what to do.
    """
    if config.auth_required or config.is_loopback_bind:
        return True
    raise ApiSecurityError(
        "Refusing to serve the OpenCog REST API on %r with authentication "
        "disabled: the /shell and /scheme endpoints execute code in the "
        "cogserver process. Set OPENCOG_API_TOKEN, or bind to 127.0.0.1." % (config.bind_host,)
    )


def validate_jsonp_callback(name):
    """Return a safe JSONP callback name, or ``None`` if it is not safe.

    A JSONP callback is concatenated verbatim into a response served as
    ``application/javascript``.  Without this check any page could inject
    arbitrary script through it, so the accepted grammar is a bare (possibly
    dotted) JavaScript identifier and nothing else.
    """
    if name is None:
        return None
    if not isinstance(name, str):
        name = name.decode("utf-8", "replace") if hasattr(name, "decode") else str(name)
    name = name.strip()
    if not name:
        return None
    if len(name) > 128:
        raise ValidationError("JSONP callback name is too long")
    if "\n" in name or "\r" in name or "<" in name or ">" in name:
        raise ValidationError("invalid JSONP callback name")
    if not JSONP_CALLBACK_RE.match(name):
        raise ValidationError("invalid JSONP callback name")
    return name


def coerce_limit(raw, maximum, default):
    """Validate a page-size parameter.

    ``raw`` may be ``None`` (use ``default``).  A non-numeric, zero, negative
    or oversized value is a client error rather than something to silently
    clamp, because ``atoms[0:limit]`` with a negative limit silently returns
    the wrong slice and an oversized one is a memory-exhaustion vector.
    """
    if raw is None or raw == "":
        value = int(default)
        if value > int(maximum):
            value = int(maximum)
        return value
    if isinstance(raw, bool):
        raise ValidationError("limit must be an integer")
    if isinstance(raw, float):
        if raw != int(raw):
            raise ValidationError("limit must be an integer")
        raw = int(raw)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise ValidationError("limit must be an integer")
    if value < 1:
        raise ValidationError("limit must be greater than zero")
    if value > int(maximum):
        raise ValidationError("limit must not exceed %d" % int(maximum))
    return value


def validate_command(command, max_length):
    """Validate a cogserver/Scheme command string.

    Returns the command unchanged on success; raises :class:`ValidationError`
    otherwise.  Length is bounded because both consumers interpret the string
    and an unbounded one is a cheap way to pin a CPU core.
    """
    if command is None:
        raise ValidationError("required parameter command is missing")
    if not isinstance(command, str):
        if hasattr(command, "decode"):
            try:
                command = command.decode("utf-8")
            except UnicodeDecodeError:
                raise ValidationError("command must be valid UTF-8")
        else:
            raise ValidationError("command must be a string")
    if not command.strip():
        raise ValidationError("command must not be empty")
    max_length = int(max_length)
    if len(command) > max_length:
        raise ValidationError("command must not exceed %d characters" % max_length)
    if "\x00" in command:
        raise ValidationError("command must not contain NUL bytes")
    return command
