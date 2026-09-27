"""Unit tests for the OpenCog REST API security policy.

These tests are the regression net for the hardening of
``opencog/python/web/api``: they run on a fresh clone with no third-party
dependencies, because :mod:`apisecurity` is standard-library-only.

Run with::

    python -m pytest tests/python/pytest
"""

from __future__ import absolute_import

import pytest

import apisecurity
from apisecurity import (
    ApiSecurityConfig,
    ApiSecurityError,
    AuthenticationError,
    OriginNotAllowed,
    ValidationError,
    assert_safe_bind,
    authorize,
    coerce_limit,
    extract_bearer_token,
    is_origin_allowed,
    validate_command,
    validate_jsonp_callback,
    validate_token,
)

SECRET = "correct-horse-battery-staple"


def headers(**kwargs):
    """Build a Flask-shaped ``request.headers.get`` callable."""
    normalised = {k.replace("_", "-"): v for k, v in kwargs.items()}

    def get_header(name):
        return normalised.get(name)

    return get_header


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
class TestConfigDefaults:
    def test_defaults_are_not_insecure(self):
        config = ApiSecurityConfig.from_env({})
        # loopback, not 0.0.0.0
        assert config.bind_host == "127.0.0.1"
        # no wildcard CORS by default
        assert "*" not in config.allowed_origins
        # every unbounded-input knob has a finite default
        assert config.max_content_length > 0
        assert config.max_command_length > 0
        assert config.max_limit > 0
        assert 0 < config.default_limit <= config.max_limit

    def test_env_overrides(self):
        config = ApiSecurityConfig.from_env(
            {
                "OPENCOG_API_TOKEN": "  tok  ",
                "OPENCOG_API_ALLOWED_ORIGINS": "https://a.example, https://b.example",
                "OPENCOG_API_MAX_CONTENT_LENGTH": "2048",
                "OPENCOG_API_MAX_COMMAND_LENGTH": "16",
                "OPENCOG_API_MAX_LIMIT": "50",
                "OPENCOG_API_DEFAULT_LIMIT": "5",
                "OPENCOG_API_BIND_HOST": "0.0.0.0",
                "OPENCOG_API_BIND_PORT": "8080",
            }
        )
        assert config.api_token == "tok"
        assert config.allowed_origins == ("https://a.example", "https://b.example")
        assert config.max_content_length == 2048
        assert config.max_command_length == 16
        assert config.max_limit == 50
        assert config.default_limit == 5
        assert config.bind_host == "0.0.0.0"
        assert config.bind_port == 8080
        assert config.auth_required is True
        assert config.is_loopback_bind is False

    def test_explicitly_empty_origins_means_deny_all(self):
        config = ApiSecurityConfig.from_env({"OPENCOG_API_ALLOWED_ORIGINS": ""})
        assert config.allowed_origins == ()

    def test_garbage_numeric_env_falls_back_instead_of_crashing(self):
        config = ApiSecurityConfig.from_env(
            {
                "OPENCOG_API_MAX_CONTENT_LENGTH": "not-a-number",
                "OPENCOG_API_BIND_PORT": "70000",
                "OPENCOG_API_MAX_COMMAND_LENGTH": "-1",
            }
        )
        assert config.max_content_length == apisecurity.DEFAULT_MAX_CONTENT_LENGTH
        assert config.bind_port == 65535  # clamped, not accepted verbatim
        assert config.max_command_length == 1

    def test_repr_never_leaks_the_token(self):
        config = ApiSecurityConfig.from_env({"OPENCOG_API_TOKEN": SECRET})
        assert SECRET not in repr(config)
        assert "auth_required=True" in repr(config)

    @pytest.mark.parametrize(
        "host,loopback",
        [
            ("127.0.0.1", True),
            ("localhost", True),
            ("::1", True),
            ("0.0.0.0", False),
            ("10.0.0.5", False),
        ],
    )
    def test_loopback_detection(self, host, loopback):
        assert ApiSecurityConfig(bind_host=host).is_loopback_bind is loopback


# ----------------------------------------------------------------------
# Token handling
# ----------------------------------------------------------------------
class TestTokenValidation:
    def test_exact_match(self):
        assert validate_token(SECRET, SECRET) is True

    def test_mismatch(self):
        assert validate_token(SECRET, SECRET + "x") is False
        assert validate_token(SECRET, SECRET[:-1]) is False

    def test_missing_presented_token(self):
        assert validate_token(SECRET, None) is False
        assert validate_token(SECRET, "") is False

    def test_empty_expected_token_disables_auth(self):
        assert validate_token("", None) is True
        assert validate_token("", "anything") is True

    def test_constant_time_path_without_hmac(self, monkeypatch):
        monkeypatch.delattr(apisecurity.hmac, "compare_digest", raising=False)
        assert validate_token(SECRET, SECRET) is True
        assert validate_token(SECRET, "wrong") is False
        assert validate_token(SECRET, "wron") is False  # different length

    def test_unicode_tokens(self):
        assert validate_token("tökén", "tökén") is True
        assert validate_token("tökén", "toke") is False


class TestBearerExtraction:
    def test_valid_header(self):
        assert extract_bearer_token(headers(Authorization="Bearer " + SECRET)) == SECRET

    def test_scheme_is_case_insensitive(self):
        assert extract_bearer_token(headers(Authorization="bearer " + SECRET)) == SECRET

    @pytest.mark.parametrize(
        "value",
        [
            None,
            "",
            SECRET,
            "Bearer",
            "Bearer ",
            "Basic " + SECRET,
            "BearerX foo",
        ],
    )
    def test_rejects_malformed_headers(self, value):
        assert extract_bearer_token(headers(Authorization=value)) is None

    def test_no_header_at_all(self):
        assert extract_bearer_token(headers()) is None


class TestAuthorize:
    def test_open_loopback_allows_anonymous(self):
        config = ApiSecurityConfig()
        assert authorize(config, headers()) is True

    def test_missing_token_is_rejected(self):
        config = ApiSecurityConfig(api_token=SECRET)
        with pytest.raises(AuthenticationError):
            authorize(config, headers())

    def test_wrong_token_is_rejected(self):
        config = ApiSecurityConfig(api_token=SECRET)
        with pytest.raises(AuthenticationError):
            authorize(config, headers(Authorization="Bearer nope"))

    def test_correct_token_is_accepted(self):
        config = ApiSecurityConfig(api_token=SECRET)
        assert authorize(config, headers(Authorization="Bearer " + SECRET)) is True

    def test_disallowed_origin_is_rejected_even_with_a_valid_token(self):
        config = ApiSecurityConfig(api_token=SECRET, allowed_origins=("https://ok.example",))
        with pytest.raises(OriginNotAllowed):
            authorize(
                config, headers(Authorization="Bearer " + SECRET, Origin="https://evil.example")
            )

    def test_disallowed_origin_is_rejected_when_auth_is_off(self):
        config = ApiSecurityConfig(allowed_origins=("https://ok.example",))
        with pytest.raises(OriginNotAllowed):
            authorize(config, headers(Origin="https://evil.example"))

    def test_allowed_origin_passes(self):
        config = ApiSecurityConfig(allowed_origins=("https://ok.example",))
        assert authorize(config, headers(Origin="https://ok.example")) is True

    def test_authentication_is_checked_before_origin(self):
        # A missing credential must not be masked by a passing origin check.
        config = ApiSecurityConfig(api_token=SECRET)
        with pytest.raises(AuthenticationError):
            authorize(config, headers(Origin="http://127.0.0.1:5000"))


class TestOriginAllowList:
    def test_empty_origin_is_same_origin(self):
        assert is_origin_allowed(None, ("https://a.example",)) is True

    def test_exact_match(self):
        assert is_origin_allowed("https://a.example", ("https://a.example",)) is True

    def test_trailing_slash_equivalent(self):
        assert is_origin_allowed("https://a.example/", ("https://a.example",)) is True

    def test_wildcard_only_when_configured(self):
        assert is_origin_allowed("https://any.example", ("*",)) is True
        assert is_origin_allowed("https://any.example", ()) is False

    def test_prefix_is_not_a_match(self):
        # A naive startswith() check would let https://a.example.evil through.
        assert is_origin_allowed("https://a.example.evil", ("https://a.example",)) is False


class TestSafeBind:
    def test_loopback_without_token_is_allowed(self):
        assert assert_safe_bind(ApiSecurityConfig(bind_host="127.0.0.1")) is True

    def test_routable_bind_without_token_is_refused(self):
        with pytest.raises(ApiSecurityError) as excinfo:
            assert_safe_bind(ApiSecurityConfig(bind_host="0.0.0.0"))
        assert "OPENCOG_API_TOKEN" in str(excinfo.value)

    def test_routable_bind_with_token_is_allowed(self):
        config = ApiSecurityConfig(bind_host="0.0.0.0", api_token=SECRET)
        assert assert_safe_bind(config) is True


# ----------------------------------------------------------------------
# Input validation
# ----------------------------------------------------------------------
class TestJsonpCallback:
    @pytest.mark.parametrize(
        "name",
        [
            "cb",
            "_cb",
            "$cb",
            "a.b",
            "window.opener.cb",
            "a1",
            "_$a9",
        ],
    )
    def test_accepts_bare_identifiers(self, name):
        assert validate_jsonp_callback(name) == name

    def test_none_stays_none(self):
        assert validate_jsonp_callback(None) is None

    def test_empty_stays_none(self):
        assert validate_jsonp_callback("") is None
        assert validate_jsonp_callback("   ") is None

    @pytest.mark.parametrize(
        "name",
        [
            "alert(1)",  # call expression
            "alert(1)//",  # comment-out of the tail
            "a;b",  # statement separator
            "a-b",  # arithmetic
            "1abc",  # leading digit
            "a b",  # whitespace
            "a\nalert(1)",  # newline injection
            "<script>",  # tag
            "a.b.c.d",  # too deep
            "</script><script>alert(1)</script>",
        ],
    )
    def test_rejects_script_injection_payloads(self, name):
        with pytest.raises(ValidationError):
            validate_jsonp_callback(name)

    def test_rejects_overlong_name(self):
        with pytest.raises(ValidationError):
            validate_jsonp_callback("a" * 129)

    def test_strips_surrounding_whitespace(self):
        assert validate_jsonp_callback("  cb  ") == "cb"


class TestCoerceLimit:
    def test_none_uses_default(self):
        assert coerce_limit(None, 1000, 25) == 25

    def test_default_is_clamped_to_maximum(self):
        assert coerce_limit(None, 10, 500) == 10

    @pytest.mark.parametrize(
        "raw,expected",
        [
            (1, 1),
            (50, 50),
            ("50", 50),
            (" 50 ", 50),
            (50.0, 50),
        ],
    )
    def test_valid_values(self, raw, expected):
        assert coerce_limit(raw, 1000, 10) == expected

    @pytest.mark.parametrize(
        "raw", [0, -1, -1000, "abc", "", 1.5, True, False, None if False else "NaN"]
    )
    def test_invalid_values(self, raw):
        if raw == "":
            assert coerce_limit(raw, 1000, 10) == 10  # empty means default
            return
        with pytest.raises(ValidationError):
            coerce_limit(raw, 1000, 10)

    def test_above_maximum_is_rejected(self):
        with pytest.raises(ValidationError):
            coerce_limit(1001, 1000, 10)


class TestValidateCommand:
    def test_accepts_a_normal_command(self):
        assert validate_command("agents-step", 100) == "agents-step"

    def test_accepts_scheme(self):
        assert validate_command("(cog-set-af-boundary! 100)", 100) == "(cog-set-af-boundary! 100)"

    def test_missing_command(self):
        with pytest.raises(ValidationError):
            validate_command(None, 100)

    @pytest.mark.parametrize("command", ["", "   ", "\t\n"])
    def test_empty_command(self, command):
        with pytest.raises(ValidationError):
            validate_command(command, 100)

    def test_overlong_command(self):
        with pytest.raises(ValidationError):
            validate_command("a" * 101, 100)

    def test_nul_byte(self):
        with pytest.raises(ValidationError):
            validate_command("agents\x00-step", 100)

    def test_bytes_are_decoded(self):
        assert validate_command(b"agents-step", 100) == "agents-step"

    def test_non_string_rejected(self):
        with pytest.raises(ValidationError):
            validate_command(12345, 100)

    def test_undecodable_bytes_rejected(self):
        with pytest.raises(ValidationError):
            validate_command(b"\xff\xfe\x00", 100)
