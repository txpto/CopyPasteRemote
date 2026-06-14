"""Unit tests for the pure URI<->path helpers of the POSIX clipboard backend."""

import os

from cpr_client.clipboard_posix import paths_to_uri_list, uri_list_to_paths


def test_roundtrip_simple(tmp_path):
    p1 = str(tmp_path / "a.txt")
    p2 = str(tmp_path / "carpeta con espacios")
    data = paths_to_uri_list([p1, p2])
    assert b"file://" in data
    assert data.endswith(b"\r\n")
    out = uri_list_to_paths(data)
    assert out == [os.path.abspath(p1), os.path.abspath(p2)]


def test_special_chars_are_percent_encoded():
    data = paths_to_uri_list(["/tmp/a b#c.txt"])
    text = data.decode()
    assert "%20" in text and "%23" in text  # space and '#'
    assert uri_list_to_paths(data) == ["/tmp/a b#c.txt"]


def test_comments_and_blank_lines_ignored():
    payload = b"# comment\r\nfile:///tmp/x\r\n\r\n"
    assert uri_list_to_paths(payload) == ["/tmp/x"]


def test_non_file_scheme_skipped():
    payload = b"https://example.com/page\r\nfile:///tmp/ok\r\n"
    assert uri_list_to_paths(payload) == ["/tmp/ok"]
