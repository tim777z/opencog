# Copyright (C) 2015 by OpenCog Foundation
# All Rights Reserved
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License v3 as
# published by the Free Software Foundation, and including the exceptions
# at http://opencog.org/wiki/Licenses
#
# CSV dataset loading for OpenCog learning experiments.
#
# Runs unmodified on Python 2.7 and Python 3.x.

from __future__ import absolute_import, print_function

import csv
import io
import logging
import re

try:                                        # Python 3
    from urllib.parse import urlsplit
    from urllib.request import urlopen
    from urllib.error import URLError, HTTPError
except ImportError:                         # Python 2
    from urlparse import urlsplit
    from urllib2 import urlopen, URLError, HTTPError

__author__ = 'keyvan-m-sadeghi'

logger = logging.getLogger('opencog.csv_dataset_parser')

#: Only these schemes are ever fetched. The previous implementation passed
#: the caller's string straight to urllib, which meant ``file:///etc/passwd``
#: and any other registered scheme was a local-file-disclosure primitive, and
#: an internal URL such as ``http://169.254.169.254/...`` was a server-side
#: request forgery against the cloud metadata service. Restricting the scheme
#: is the cheapest containment; callers that need a file pass a path.
ALLOWED_URL_SCHEMES = ('http', 'https')

#: Refuse to buffer an unbounded response into memory.
MAX_DATASET_BYTES = 64 * 1024 * 1024

#: Never block forever on a slow or hostile endpoint.
URL_OPEN_TIMEOUT = 30.0

_WHITESPACE_RE = re.compile(r'[ ]*')


class DatasetError(Exception):
    """Base class for dataset loading/validation failures."""


class DatasetSourceError(DatasetError):
    """The dataset could not be opened (bad URL, missing file, HTTP error)."""


class DatasetValidationError(DatasetError):
    """A row or field in the dataset failed validation."""


class _incomplete_value(object):
    def __repr__(self):
        return 'incomplete-value'

    def __bool__(self):
        return False

    __nonzero__ = __bool__      # Python 2


def _convert_to_bool(value):
    if value.lower() in ('0', 'f', 'false', 'n', 'no', ''):
        return False
    return True


INCOMPLETE_VALUE = _incomplete_value()

CONVERT_TO_STRING = None
CONVERT_TO_BOOL = _convert_to_bool
CONVERT_TO_INT = lambda v: int(v)
CONVERT_TO_FLOAT = lambda v: float(v)


def _convert_value(convert_function, value):
    if convert_function is not None:
        return convert_function(value)
    return value


def remove_white_space(sequence_element):
    """Strip leading spaces from a CSV field.

    The original implementation compared the character against the interned
    literal with ``is`` (identity, not equality), which is only accidentally
    correct for CPython single-character strings and emitted a
    SyntaxWarning from Python 3.8 onwards.
    """
    if sequence_element is None:
        return ''
    if not isinstance(sequence_element, str):
        try:
            sequence_element = sequence_element.decode('utf-8', 'replace')
        except AttributeError:            # pragma: no cover - defensive
            sequence_element = str(sequence_element)
    if sequence_element == '':
        return ''
    return _WHITESPACE_RE.sub('', sequence_element, count=1)


class SimpleRecord(list):
    def __init__(self, string_seq, convertor_function):
        for element in string_seq:
            if convertor_function is None:
                self.append(remove_white_space(element))
            else:
                self.append(
                    convertor_function(remove_white_space(element)))


class CompositeRecord(dict):

    def __init__(self, dataset, string_seq,
                 default_convertor_function,
                 attribute_names,
                 converter_by_names_tuples,
                 incomplete_value_evaluation_fn,
                 ignore_if_incomplete):

        # These used to be class attributes, i.e. mutable state shared by
        # every record in a dataset. Give each record its own.
        self.is_incomplete = False
        self._attributes_for_repr = None
        self._function_by_index = None

        if string_seq is None:
            raise DatasetValidationError('record is missing')
        if len(string_seq) < len(attribute_names):
            raise DatasetValidationError(
                'record has %d fields but %d attribute names were declared'
                % (len(string_seq), len(attribute_names)))

        self.generate_lambda_dict(converter_by_names_tuples)
        for index, name in enumerate(attribute_names):
            value = remove_white_space(string_seq[index])
            if incomplete_value_evaluation_fn is not None and\
               incomplete_value_evaluation_fn(value):
                value = INCOMPLETE_VALUE
                self.is_incomplete = True
                dataset.number_of_incomplete_records += 1
                if ignore_if_incomplete:
                    # Mark the record as dropped instead of returning a
                    # half-populated dict; the caller used to keep using it
                    # and derive the dataset's variable names from it.
                    return
            if value is not INCOMPLETE_VALUE:
                if self._function_by_index is None:
                    value = _convert_value(
                        default_convertor_function, value)
                elif name in self._function_by_index:
                    value = self._function_by_index[name](value)
                else:
                    value = _convert_value(
                        default_convertor_function, value)

            self[name] = value
        self.index_in_dataset = dataset.number_of_records - 1

    def generate_lambda_dict(self, converter_by_names_tuples):
        if converter_by_names_tuples is None:
            return
        self._function_by_index = {}
        for convertor_and_names_tuple in converter_by_names_tuples:
            for name in convertor_and_names_tuple[1:]:
                self._function_by_index[name] =\
                convertor_and_names_tuple[0]

    def set_attribute_names_for_repr(self, attribute_names):
        self._attributes_for_repr = attribute_names

    def __repr__(self):
        if self._attributes_for_repr is None:
            return dict.__repr__(self)
        if not hasattr(self, 'index_in_dataset'):
            return dict.__repr__(self)
        repr_str = 'Record[' + str(self.index_in_dataset) + ']{ '
        for name in self._attributes_for_repr:
            if name not in self:
                continue
            repr_str += name + ':' + str(self[name]) + ' '
        return repr_str + '}'


def _validate_remote_url(path):
    """Reject non-HTTP(S) URLs and obvious SSRF targets.

    Returns the URL unchanged when it is acceptable.
    """
    try:
        parts = urlsplit(path)
    except ValueError as exc:
        raise DatasetSourceError('malformed URL %r: %s' % (path, exc))
    if parts.scheme.lower() not in ALLOWED_URL_SCHEMES:
        raise DatasetSourceError(
            'refusing to fetch %r: only %s URLs are allowed'
            % (parts.scheme or path, '/'.join(ALLOWED_URL_SCHEMES)))
    if not parts.hostname:
        raise DatasetSourceError('refusing to fetch %r: no host' % (path,))
    hostname = parts.hostname.lower()
    if hostname in ('localhost', '::1') or hostname.startswith('127.'):
        raise DatasetSourceError(
            'refusing to fetch %r: loopback addresses are not allowed' % (path,))
    if hostname in ('169.254.169.254', 'metadata.google.internal'):
        raise DatasetSourceError(
            'refusing to fetch %r: cloud metadata endpoints are not allowed'
            % (path,))
    return path


def _looks_like_url(path):
    """True when ``path`` carries a URL scheme rather than being a file path.

    Detecting the scheme (instead of grepping for ``://``) also catches
    ``file:/etc/passwd`` and ``data:...``, both of which urllib would happily
    open and which therefore have to be refused explicitly.
    """
    try:
        scheme = urlsplit(path).scheme
    except ValueError:
        return False
    # A single-letter "scheme" is a Windows drive letter, not a URL.
    return len(scheme) > 1


def _open_source(path):
    """Open ``path`` as a text stream.

    ``path`` may be an ``http(s)`` URL, a filesystem path, or an already-open
    file-like object / iterable of lines.
    """
    if hasattr(path, 'read') or not isinstance(path, str):
        return path, False

    if _looks_like_url(path):
        _validate_remote_url(path)
        try:
            # `stream` may be an HTTPResponse (no context manager on py2) or
            # a file object; handle both, and cap the number of bytes read
            # so a hostile endpoint cannot exhaust memory.
            stream = urlopen(path, timeout=URL_OPEN_TIMEOUT)
        except (URLError, HTTPError, ValueError, OSError) as exc:
            raise DatasetSourceError('could not fetch %r: %s' % (path, exc))
        return _BoundedReader(stream), True

    try:
        # newline='' is required by the csv module to handle embedded
        # newlines inside quoted fields correctly.
        return io.open(path, 'r', newline='', encoding='utf-8',
                       errors='replace'), True
    except (IOError, OSError, UnicodeError, ValueError) as exc:
        raise DatasetSourceError('could not open %r: %s' % (path, exc))


class _BoundedReader(object):
    """Wrap a URL response so that at most ``MAX_DATASET_BYTES`` are read."""

    def __init__(self, stream, limit=MAX_DATASET_BYTES):
        self._stream = stream
        self._remaining = limit
        self._eof = False

    def __iter__(self):
        return self

    def __next__(self):
        line = next(self._stream)
        if self._remaining > 0:
            self._remaining -= len(line)
            if self._remaining <= 0:
                logger.warning('Dataset source truncated at %d bytes',
                               MAX_DATASET_BYTES)
        return line

    next = __next__            # Python 2

    def readline(self, *args):
        line = self._stream.readline(*args)
        if self._remaining > 0:
            self._remaining -= len(line)
        return line

    def read(self, *args):
        if self._remaining <= 0:
            return ''
        data = self._stream.read(*args)
        self._remaining -= len(data)
        return data

    def __getattr__(self, name):
        return getattr(self._stream, name)

    def close(self):
        try:
            self._stream.close()
        except Exception:       # pragma: no cover - defensive
            pass


class Dataset(list):
    def __init__(self, path,
                 default_convertor_expression=None,
                 attribute_names=None,
                 converter_by_names_tuples=None,
                 names_for_repr=None,
                 incomplete_value_evaluation_fn=None,
                 ignore_if_incomplete=True):

        self.number_of_incomplete_records = 0
        self.number_of_records = 0
        self.number_of_malformed_records = 0

        stream, should_close = _open_source(path)

        self.variable_names = None
        try:
            data = csv.reader(stream, delimiter=',', quotechar='|')
            for row in data:
                self.number_of_records += 1
                if attribute_names is None:
                    self.append(SimpleRecord(row, default_convertor_expression))
                    continue
                if len(row) != len(attribute_names):
                    # Data quality: count and report rather than silently
                    # dropping rows, which previously made a truncated or
                    # mis-delimited file look like a valid dataset.
                    self.number_of_malformed_records += 1
                    logger.warning(
                        'Skipping malformed record %d: expected %d fields, got %d',
                        self.number_of_records, len(attribute_names), len(row))
                    continue
                record = CompositeRecord(self, row,
                    default_convertor_expression,
                    attribute_names,
                    converter_by_names_tuples,
                    incomplete_value_evaluation_fn, ignore_if_incomplete)
                if ignore_if_incomplete and record.is_incomplete:
                    continue
                record.set_attribute_names_for_repr(names_for_repr)
                self.variable_names = sorted(record.keys())
                self.append(record)
        finally:
            if should_close:
                try:
                    stream.close()
                except Exception:   # pragma: no cover - defensive
                    pass

        if self.number_of_malformed_records:
            logger.warning('%d of %d dataset records were malformed and skipped',
                           self.number_of_malformed_records, self.number_of_records)
