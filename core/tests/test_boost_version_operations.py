"""Tests for core.utils.boost_version_operations."""

import pytest

from core.utils.boost_version_operations import (
    compare_boost_version_tuples,
    compare_encoded_versions,
    compare_loose_version_strings,
    decode_boost_version,
    encode_boost_version,
    encode_boost_version_string,
    loose_version_tuple,
    normalize_boost_version_string,
    parse_boost_version_string,
    parse_stable_boost_release_tag,
)


def test_encode_decode_round_trip():
    assert encode_boost_version(1, 86, 0) == 108_600
    assert decode_boost_version(108_600) == (1, 86, 0)
    assert decode_boost_version(1_00_900) == (1, 9, 0)


def test_encode_boost_version_string():
    assert encode_boost_version_string("1.86.0") == 108_600
    assert encode_boost_version_string("boost-1.10.0") == 101_000
    assert encode_boost_version_string("1_56_0") == 105_600


def test_parse_invalid_returns_none():
    assert parse_boost_version_string("") is None
    assert parse_boost_version_string("not-a-version") is None


def test_encode_rejects_out_of_range():
    with pytest.raises(ValueError):
        encode_boost_version(1, 1000, 0)
    with pytest.raises(ValueError):
        encode_boost_version(1, 0, 100)


def test_loose_version_tuple_empty_and_digits():
    assert loose_version_tuple("") == (0, 0, 0)
    assert loose_version_tuple("1.82.x") == (1, 82, 0)
    assert loose_version_tuple("release-2.1.9-extra") == (2, 1, 9)


def test_normalize_boost_version_string():
    assert normalize_boost_version_string("1.82") == "1.82.0"
    assert normalize_boost_version_string("0.99") is None
    assert normalize_boost_version_string("") is None
    assert normalize_boost_version_string("boost-1.2.3") == "1.2.3"


def test_compare_boost_version_tuples():
    assert compare_boost_version_tuples((1, 0, 0), (2, 0, 0)) == -1
    assert compare_boost_version_tuples((1, 82, 0), (1, 82, 0)) == 0
    assert compare_boost_version_tuples((2, 0, 0), (1, 99, 99)) == 1


def test_compare_loose_version_strings():
    assert compare_loose_version_strings("1.0", "2.0") == -1
    assert compare_loose_version_strings("1.82.x", "1.81.0") == 1


def test_compare_encoded_versions():
    assert compare_encoded_versions(100_000, 200_000) == -1
    assert compare_encoded_versions(108_600, 108_600) == 0


def test_parse_stable_boost_release_tag():
    min_v = (1, 16, 1)
    assert parse_stable_boost_release_tag("boost-1.90.0", min_v) == "boost-1.90.0"
    assert parse_stable_boost_release_tag("boost-1.16.1", min_v) == "boost-1.16.1"
    assert parse_stable_boost_release_tag("boost-1.16.0", min_v) is None
    assert parse_stable_boost_release_tag("boost-1.90.0-beta", min_v) is None
    assert parse_stable_boost_release_tag("", min_v) is None
