from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from sloi.installation import download_model_ranges


class _Response:
    def __init__(self, start: int, end: int, total: int, body: bytes):
        self.status_code = 206
        self.headers = {"Content-Range": f"bytes {start}-{end}/{total}"}
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def iter_bytes(self):
        yield self.body


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.ranges = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def stream(self, _method, _url, *, headers):
        self.ranges.append(headers["Range"])
        response = self.responses.pop(0)
        return response


def _use_client(monkeypatch, client):
    monkeypatch.setattr(httpx, "Client", lambda **_kwargs: client)


def _verified_payload(destination: Path, payload: bytes) -> Path:
    return download_model_ranges(
        "https://example.invalid/pinned.bin",
        destination,
        len(payload),
        hashlib.sha256(payload).hexdigest(),
    )


def test_model_range_download_resumes_partial_and_verifies_hash(tmp_path, monkeypatch):
    payload = b"pinned model payload"
    destination = tmp_path / "model.bin"
    partial = destination.with_name(destination.name + ".partial")
    partial.write_bytes(payload[:7])
    client = _Client([_Response(7, len(payload) - 1, len(payload), payload[7:])])
    _use_client(monkeypatch, client)

    result = _verified_payload(destination, payload)

    assert result == destination
    assert destination.read_bytes() == payload
    assert not partial.exists()
    assert client.ranges == [f"bytes=7-{len(payload) - 1}"]


@pytest.mark.parametrize("bad_partial", [b"oversized partial", b"bad-data"])
def test_model_range_download_quarantines_invalid_partial(tmp_path, monkeypatch, bad_partial):
    payload = b"verified"
    destination = tmp_path / "model.bin"
    partial = destination.with_name(destination.name + ".partial")
    partial.write_bytes(bad_partial)
    client = _Client([_Response(0, len(payload) - 1, len(payload), payload)])
    _use_client(monkeypatch, client)

    result = _verified_payload(destination, payload)

    quarantined = list(tmp_path.glob("model.bin.partial.invalid-*"))
    assert result == destination
    assert destination.read_bytes() == payload
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == bad_partial
    assert not partial.exists()
    assert client.ranges == [f"bytes=0-{len(payload) - 1}"]


def test_model_range_download_rejects_mismatched_content_range_after_retries(tmp_path, monkeypatch):
    payload = b"verified"
    destination = tmp_path / "model.bin"
    client = _Client([_Response(1, len(payload), len(payload), payload)] * 3)
    _use_client(monkeypatch, client)

    with pytest.raises(ValueError, match="range response did not match"):
        _verified_payload(destination, payload)

    assert client.ranges == ["bytes=0-7"] * 3
    assert not destination.exists()
