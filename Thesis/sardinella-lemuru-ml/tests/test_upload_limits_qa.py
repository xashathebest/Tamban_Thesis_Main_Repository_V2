"""Upload limits are applied before buffering or decoding untrusted images."""
from __future__ import annotations

import asyncio
import importlib
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from starlette.requests import Request

from src.api.image_analysis import ImageUploadError, decode_uploaded_image

app_module = importlib.import_module("src.api.app")


@pytest.mark.parametrize("declared_length", [None, b"1"])
def test_oversized_chunked_body_stops_reading_before_remaining_chunks(monkeypatch, declared_length):
    monkeypatch.setattr(app_module, "FISH_UPLOAD_MAX_BYTES", 5)
    quality = MagicMock()
    monkeypatch.setattr(app_module, "quality_model", quality)
    headers = [(b"x-filename", b"fish.jpg")]
    if declared_length is not None:
        headers.append((b"content-length", declared_length))
    chunks = iter([b"1234", b"5678", b"remaining"])
    received = []
    async def receive():
        value = next(chunks)
        received.append(value)
        return {"type": "http.request", "body": value, "more_body": value != b"remaining"}
    request = Request({"type": "http", "method": "POST", "path": "/api/analyze-image", "query_string": b"", "headers": headers}, receive)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module.analyze_image(request))
    assert exc.value.status_code == 413
    assert received == [b"1234", b"5678"]
    quality.switch_model.assert_not_called()


def test_dimensions_are_rejected_before_cv2_decodes_pixels():
    ok, encoded = cv2.imencode(".png", np.zeros((32, 32, 3), dtype=np.uint8))
    assert ok
    with patch("src.api.image_analysis.cv2.imdecode", wraps=cv2.imdecode) as decoder:
        with pytest.raises(ImageUploadError, match="dimensions"):
            decode_uploaded_image(encoded.tobytes(), "fish.png", max_bytes=100_000, max_dimension=16, max_pixels=1_000)
    decoder.assert_not_called()


def test_disguised_unsupported_image_is_rejected():
    ok, encoded = cv2.imencode(".bmp", np.zeros((8, 8, 3), dtype=np.uint8))
    assert ok
    with pytest.raises(ImageUploadError):
        decode_uploaded_image(encoded.tobytes(), "fish.jpg", max_bytes=100_000, max_dimension=100, max_pixels=10_000)


@pytest.mark.parametrize("mode,lossless", [("RGB", False), ("RGB", True), ("RGBA", False)])
def test_valid_webp_variants_decode(mode, lossless):
    image = Image.new(mode, (24, 18), (30, 60, 90, 160) if mode == "RGBA" else (30, 60, 90))
    output = BytesIO()
    image.save(output, format="WEBP", lossless=lossless)
    decoded = decode_uploaded_image(output.getvalue(), "fish.webp", max_bytes=100_000, max_dimension=100, max_pixels=10_000)
    assert decoded.shape == (18, 24, 3)


def test_jpeg_exif_orientation_is_preserved():
    image = Image.new("RGB", (24, 18), (30, 60, 90))
    exif = Image.Exif()
    exif[274] = 6
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    decoded = decode_uploaded_image(output.getvalue(), "fish.jpg", max_bytes=100_000, max_dimension=100, max_pixels=10_000)
    assert decoded.shape == (24, 18, 3)


def test_large_webp_canvas_is_rejected_without_initializing_pixel_decoder():
    # VP8X canvas dimensions are 24-bit values stored as width/height minus 1.
    oversized = b"RIFF" + (22).to_bytes(4, "little") + b"WEBPVP8X" + (10).to_bytes(4, "little") + b"\0\0\0\0" + (50000).to_bytes(3, "little") + (50000).to_bytes(3, "little")
    with patch("src.api.image_analysis.cv2.imdecode") as decoder:
        with pytest.raises(ImageUploadError, match="dimensions"):
            decode_uploaded_image(oversized, "fish.webp", max_bytes=100_000, max_dimension=100, max_pixels=10_000)
    decoder.assert_not_called()


def test_upload_stream_is_closed_after_limit_error():
    closed = []
    async def stream():
        try:
            yield b"1234"
            yield b"5678"
        finally:
            closed.append(True)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(app_module._read_bounded_upload(SimpleNamespace(stream=stream), 5))
    assert exc.value.status_code == 413
    assert closed == [True]
