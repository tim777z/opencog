"""Regression tests for structured /shell and /scheme payload validation.

``validate_command_payload`` is the single body-shape gate shared by the two
code-execution endpoints.  These tests cover both the shape checks and the
control-character policy that keeps the line-oriented cogserver shell from
being fed injected commands.
"""

from __future__ import absolute_import

import pytest

from apisecurity import (
    ValidationError,
    validate_command,
    validate_command_payload,
)

MAX_LENGTH = 100


class TestCommandPayloadShape:
    def test_valid_payload_returns_the_command(self):
        assert validate_command_payload({"command": "agents-step"}, MAX_LENGTH) == "agents-step"

    def test_extra_keys_are_tolerated_for_client_compatibility(self):
        payload = {"command": "agents-step", "trace_id": "abc"}
        assert validate_command_payload(payload, MAX_LENGTH) == "agents-step"

    @pytest.mark.parametrize("body", [None, [], "agents-step", 42, True])
    def test_non_object_body_is_rejected(self, body):
        with pytest.raises(ValidationError, match="JSON object body is required"):
            validate_command_payload(body, MAX_LENGTH)

    @pytest.mark.parametrize("body", [{}, {"other": "value"}])
    def test_missing_command_is_rejected(self, body):
        with pytest.raises(ValidationError, match="command is missing"):
            validate_command_payload(body, MAX_LENGTH)

    @pytest.mark.parametrize("command", [None, 12345, ["agents-step"], {"a": 1}])
    def test_non_string_command_is_rejected(self, command):
        with pytest.raises(ValidationError):
            validate_command_payload({"command": command}, MAX_LENGTH)

    def test_length_limit_is_enforced(self):
        with pytest.raises(ValidationError, match="exceed"):
            validate_command_payload({"command": "a" * (MAX_LENGTH + 1)}, MAX_LENGTH)

    def test_bytes_command_is_decoded(self):
        assert validate_command_payload({"command": b"agents-step"}, MAX_LENGTH) == "agents-step"


class TestCommandControlCharacters:
    @pytest.mark.parametrize(
        "command",
        [
            "agents\r-step",
            "agents\n-step",
            "agents\x00-step",
            "agents\x1b[2J-step",
            "agents\x7f-step",
        ],
    )
    def test_single_line_endpoint_rejects_control_characters(self, command):
        with pytest.raises(ValidationError, match="control characters"):
            validate_command(command, MAX_LENGTH)

    def test_horizontal_tab_is_allowed(self):
        assert validate_command("agents\t-step", MAX_LENGTH) == "agents\t-step"

    @pytest.mark.parametrize(
        "command",
        [
            "(begin\n  (cog-set-af-boundary! 100))",
            "(begin\r\n  (cog-set-af-boundary! 100))",
            "(display\t100)",
        ],
    )
    def test_scheme_endpoint_accepts_multi_line_source(self, command):
        assert validate_command(command, MAX_LENGTH, allow_line_breaks=True) == command

    @pytest.mark.parametrize(
        "command",
        [
            "(begin\x00 1)",
            "(begin\x1b[2J 1)",
            "(begin\x7f 1)",
        ],
    )
    def test_scheme_endpoint_still_rejects_other_control_characters(self, command):
        with pytest.raises(ValidationError, match="control characters"):
            validate_command(command, MAX_LENGTH, allow_line_breaks=True)

    def test_shell_endpoint_never_accepts_embedded_line_break(self):
        # Explicitly pin the /shell policy: an embedded newline would smuggle
        # a second command into the line-oriented cogserver shell protocol.
        with pytest.raises(ValidationError):
            validate_command_payload({"command": "agents-step\nhelp"}, MAX_LENGTH)
