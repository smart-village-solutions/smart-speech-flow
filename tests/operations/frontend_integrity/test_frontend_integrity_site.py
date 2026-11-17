"""The monitor fetches like an iPad and hashes what the browser would run (#620, spec §6)."""

import gzip
import zlib

import pytest

from scripts.frontend_integrity.site import UnreachableError, decode, fetch
from tests.operations.frontend_integrity.frontend_integrity_fakes import (
    FrontendServer,
    SiteBehaviour,
    closed_port_url,
    write_site,
)


def _no_wait(_seconds: float) -> None:
    pass


def test_decode_undoes_what_a_tablet_accepts():
    assert decode("", b"x") == b"x"
    assert decode("gzip", gzip.compress(b"x")) == b"x"
    assert decode("deflate", zlib.compress(b"x")) == b"x"


def test_an_unknown_encoding_is_hashed_as_sent_and_so_never_matches():
    assert decode("br", b"x") == b"x"


def test_a_fetch_is_decompressed_before_anything_is_compared(tmp_path):
    root = write_site(tmp_path)
    with FrontendServer(SiteBehaviour(root)) as base:
        reply = fetch(base + "/assets/index-a.js")

    assert reply.status == 200
    assert reply.headers["content-encoding"] == "gzip"
    assert reply.body == (root / "assets" / "index-a.js").read_bytes()


def test_an_http_error_is_a_reply(tmp_path):
    with FrontendServer(SiteBehaviour(write_site(tmp_path))) as base:
        assert fetch(base + "/assets/missing.js").status == 404


def test_a_refused_connection_is_unreachable_after_three_tries():
    waits = []

    with pytest.raises(UnreachableError):
        fetch(closed_port_url() + "/", wait=waits.append)

    assert waits == [5, 5]


def test_corrupt_gzip_is_unreachable_not_a_crash(tmp_path):
    with FrontendServer(SiteBehaviour(write_site(tmp_path), broken_gzip=True)) as base:
        with pytest.raises(UnreachableError):
            fetch(base + "/", wait=_no_wait)
