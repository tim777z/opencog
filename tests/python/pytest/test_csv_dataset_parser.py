"""Unit tests for :mod:`csv_dataset_parser`.

The parser is the data-ingress path for OpenCog's learning experiments: it
accepts a caller-supplied string and turns it into either a URL fetch or a
local file read.  These tests cover both the data-quality guarantees and the
request-forgery / local-file-disclosure containment added around that.
"""

from __future__ import absolute_import

import io
import os

import pytest

import csv_dataset_parser
from csv_dataset_parser import (
    ALLOWED_URL_SCHEMES,
    INCOMPLETE_VALUE,
    CompositeRecord,
    Dataset,
    DatasetError,
    DatasetSourceError,
    DatasetValidationError,
    SimpleRecord,
    remove_white_space,
)


def write_csv(tmpdir, text):
    path = os.path.join(str(tmpdir), "dataset.csv")
    with io.open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)
    return path


# ----------------------------------------------------------------------
# Field normalisation
# ----------------------------------------------------------------------
class TestRemoveWhiteSpace:
    def test_strips_leading_spaces(self):
        assert remove_white_space("   value") == "value"

    def test_preserves_inner_and_trailing_spaces(self):
        assert remove_white_space("  a b  ") == "a b  "

    def test_empty(self):
        assert remove_white_space("") == ""

    def test_all_spaces(self):
        assert remove_white_space("    ") == ""

    def test_none(self):
        assert remove_white_space(None) == ""

    def test_dynamically_built_string_is_stripped(self):
        """Regression: the original compared with ``is ' '`` (identity).

        That is only accidentally correct on CPython, which hands out a
        singleton for every one-character latin-1 string.  It is wrong per the
        language spec, it warns on Python 3.8+, and it silently fails on any
        implementation that does not intern single characters.
        """
        dynamic = "".join([" ", "", "v", "a", "l"])
        assert dynamic == " val"
        assert remove_white_space(dynamic) == "val"

    def test_module_does_not_use_identity_comparison_on_literals(self):
        module_dir = os.path.dirname(os.path.abspath(csv_dataset_parser.__file__ or "."))
        module_path = os.path.join(module_dir, "csv_dataset_parser.py")
        with io.open(module_path, "r", encoding="utf-8") as handle:
            source = handle.read()
        assert "is ' '" not in source
        assert 'is " "' not in source

    def test_large_run_of_spaces(self):
        assert remove_white_space(" " * 5000 + "v") == "v"


class TestIncompleteValue:
    def test_repr(self):
        assert repr(INCOMPLETE_VALUE) == "incomplete-value"

    def test_is_falsy(self):
        assert not INCOMPLETE_VALUE


class TestConvertToBool:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("0", False),
            ("f", False),
            ("false", False),
            ("FALSE", False),
            ("n", False),
            ("no", False),
            ("", False),
            ("1", True),
            ("t", True),
            ("true", True),
            ("y", True),
            ("x", True),
        ],
    )
    def test_values(self, raw, expected):
        assert csv_dataset_parser._convert_to_bool(raw) is expected


# ----------------------------------------------------------------------
# Records
# ----------------------------------------------------------------------
class TestSimpleRecord:
    def test_normalises_fields(self):
        # remove_white_space strips *leading* spaces only; trailing content
        # is preserved.
        record = SimpleRecord(["  a", " b "], None)
        assert record == ["a", "b "]

    def test_applies_converter(self):
        record = SimpleRecord([" 1 ", " 2 "], int)
        assert record == [1, 2]


class TestCompositeRecord:
    class _FakeDataset(list):
        def __init__(self):
            list.__init__(self)
            self.number_of_records = 0
            self.number_of_incomplete_records = 0

    def _dataset(self):
        return self._FakeDataset()

    def test_basic_record(self):
        dataset = self._dataset()
        dataset.number_of_records = 1
        record = CompositeRecord(dataset, ["a", " 2 "], None, ["name", "count"], None, None, True)
        assert record["name"] == "a"
        assert record["count"] == " 2 ".lstrip()
        assert record.index_in_dataset == 0
        assert record.is_incomplete is False

    def test_per_column_converters(self):
        dataset = self._dataset()
        dataset.number_of_records = 1
        record = CompositeRecord(
            dataset, ["7"], None, ["count"], [(int, "count", "other")], None, True
        )
        assert record["count"] == 7

    def test_incomplete_record_is_dropped_not_half_built(self):
        dataset = self._dataset()
        dataset.number_of_records = 1
        record = CompositeRecord(
            dataset, ["", "x"], None, ["name", "other"], None, lambda v: v == "", True
        )
        assert record.is_incomplete is True
        assert dataset.number_of_incomplete_records == 1
        # No key was written for the incomplete field and the record never
        # received an index, so a caller cannot mistake it for a full row.
        assert "name" not in record
        assert not hasattr(record, "index_in_dataset")
        # repr must not explode on the half-built record.
        repr(record)

    def test_incomplete_record_kept_when_not_ignoring(self):
        dataset = self._dataset()
        dataset.number_of_records = 1
        record = CompositeRecord(
            dataset, ["", "x"], None, ["name", "other"], None, lambda v: v == "", False
        )
        assert record["name"] is INCOMPLETE_VALUE
        assert record["other"] == "x"

    def test_is_incomplete_is_per_instance(self):
        """Regression: these used to be class attributes shared by all records."""
        dataset = self._dataset()
        dataset.number_of_records = 1
        incomplete = CompositeRecord(dataset, [""], None, ["name"], None, lambda v: v == "", False)
        dataset.number_of_records = 2
        complete = CompositeRecord(dataset, ["ok"], None, ["name"], None, lambda v: v == "", False)
        assert incomplete.is_incomplete is True
        assert complete.is_incomplete is False

    def test_short_row_is_rejected(self):
        dataset = self._dataset()
        dataset.number_of_records = 1
        with pytest.raises(DatasetValidationError):
            CompositeRecord(dataset, ["only-one"], None, ["a", "b"], None, None, True)

    def test_missing_row_is_rejected(self):
        dataset = self._dataset()
        with pytest.raises(DatasetValidationError):
            CompositeRecord(dataset, None, None, ["a"], None, None, True)

    def test_dataset_errors_share_a_base_class(self):
        assert issubclass(DatasetSourceError, DatasetError)
        assert issubclass(DatasetValidationError, DatasetError)


# ----------------------------------------------------------------------
# Source handling (the security-relevant part)
# ----------------------------------------------------------------------
class TestSourceValidation:
    @pytest.mark.parametrize(
        "url",
        [
            "file:///etc/passwd",
            "file:/etc/passwd",
            "ftp://example.com/data.csv",
            "gopher://example.com/",
            "data:text/csv,a,b",
            "jar:file:///x!/y",
            "mailto:someone@example.com",
        ],
    )
    def test_rejects_non_http_schemes(self, url):
        with pytest.raises(DatasetSourceError) as excinfo:
            Dataset(url)
        assert "only" in str(excinfo.value)

    def test_only_http_and_https_are_allowed(self):
        assert set(ALLOWED_URL_SCHEMES) == {"http", "https"}

    @pytest.mark.parametrize(
        "url",
        [
            "http://localhost/data.csv",
            "http://127.0.0.1:8080/data.csv",
            "http://127.1.2.3/data.csv",
        ],
    )
    def test_rejects_loopback_urls(self, url):
        with pytest.raises(DatasetSourceError) as excinfo:
            Dataset(url)
        assert "loopback" in str(excinfo.value)

    @pytest.mark.parametrize(
        "url",
        [
            "http://169.254.169.254/latest/meta-data/",
            "http://metadata.google.internal/computeMetadata/v1/",
        ],
    )
    def test_rejects_cloud_metadata_urls(self, url):
        with pytest.raises(DatasetSourceError):
            Dataset(url)

    def test_rejects_url_without_host(self):
        with pytest.raises(DatasetSourceError):
            Dataset("http:///data.csv")

    def test_missing_file_raises_a_typed_error(self):
        with pytest.raises(DatasetSourceError):
            Dataset("/nonexistent/path/to/dataset.csv")

    def test_file_path_still_works(self, tmpdir):
        path = write_csv(tmpdir, "a,b\n1,2\n")
        dataset = Dataset(path)
        assert len(dataset) == 2


# ----------------------------------------------------------------------
# End-to-end parsing
# ----------------------------------------------------------------------
class TestDataset:
    def test_simple_rows(self, tmpdir):
        # The header is a row: with attribute_names=None the parser makes no
        # distinction, matching the original behaviour.
        path = write_csv(tmpdir, "a,b\n1,2\n3,4\n")
        dataset = Dataset(path)
        assert len(dataset) == 3
        assert dataset[0] == ["a", "b"]
        assert dataset[2] == ["3", "4"]
        assert dataset.number_of_records == 3
        assert dataset.number_of_malformed_records == 0

    def test_named_attributes(self, tmpdir):
        path = write_csv(tmpdir, "cat,3\ndog,5\n")
        dataset = Dataset(path, attribute_names=["name", "legs"])
        assert dataset[0]["name"] == "cat"
        assert dataset[0]["legs"] == "3"
        assert dataset.variable_names == ["legs", "name"]

    def test_malformed_rows_are_counted_not_silently_dropped(self, tmpdir):
        # Data quality: a truncated file previously produced a dataset that
        # looked complete.
        path = write_csv(tmpdir, "cat,3\ndog\nbird,2\n")
        dataset = Dataset(path, attribute_names=["name", "legs"])
        assert len(dataset) == 2
        assert dataset.number_of_records == 3
        assert dataset.number_of_malformed_records == 1

    def test_incomplete_rows_skipped_by_default(self, tmpdir):
        path = write_csv(tmpdir, "cat,3\n,5\ndog,4\n")
        dataset = Dataset(
            path, attribute_names=["name", "legs"], incomplete_value_evaluation_fn=lambda v: v == ""
        )
        assert len(dataset) == 2
        assert dataset.number_of_incomplete_records == 1
        # variable_names must come from a complete record, not a dropped one
        assert dataset.variable_names == ["legs", "name"]

    def test_accepts_an_in_memory_iterable(self):
        rows = ["a,b\n", "1,2\n"]
        dataset = Dataset(iter(rows))
        assert len(dataset) == 2
        assert dataset[1] == ["1", "2"]

    def test_accepts_a_file_object(self, tmpdir):
        path = write_csv(tmpdir, "a,b\n1,2\n")
        with io.open(path, "r", encoding="utf-8") as handle:
            dataset = Dataset(handle)
            assert len(dataset) == 2

    def test_stream_is_closed_on_success(self, tmpdir):
        path = write_csv(tmpdir, "a,b\n1,2\n")
        dataset = Dataset(path)
        # A leaked descriptor would keep the file locked on Windows.
        os.remove(path)
        assert len(dataset) == 2

    def test_stream_is_closed_on_error(self, tmpdir):
        # A converter that raises must not leave the file handle open.
        path = write_csv(tmpdir, "cat,3\ndog,4\n")

        def explode(_value):
            raise ValueError("converter exploded")

        with pytest.raises(ValueError, match="converter exploded"):
            Dataset(path, attribute_names=["name", "legs"], default_convertor_expression=explode)
        os.remove(path)  # would raise on Windows if still open

    def test_repr_uses_configured_names(self, tmpdir):
        path = write_csv(tmpdir, "cat,3\n")
        dataset = Dataset(path, attribute_names=["name", "legs"], names_for_repr=["name", "legs"])
        assert repr(dataset[0]) == "Record[0]{ name:cat legs:3 }"

    def test_embedded_newline_in_quoted_field(self, tmpdir):
        # This parser uses '|' as the quote character, not '"'.
        path = write_csv(tmpdir, "|line one\nline two|,2\n")
        dataset = Dataset(path)
        assert dataset[0][0] == "line one\nline two"
