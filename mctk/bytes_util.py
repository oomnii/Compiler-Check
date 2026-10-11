"""Byte-accurate hashing, display, and comparison helpers."""

from __future__ import annotations

import base64
import hashlib

COMPARISON_POLICY = (
    "CRLF (0x0D 0x0A) sequences are normalized to LF (0x0A) before equality checks. "
    "Lone CR (0x0D) bytes are preserved. No other whitespace trimming or Unicode "
    "normalization is applied."
)

SCHEMA_VERSION = "1.2.0"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utf8_bytes(text: str) -> bytes:
    return text.encode("utf-8")


def normalize_bytes_for_compare(data: bytes) -> bytes:
    if not data:
        return data
    return data.replace(b"\r\n", b"\n")


def bytes_to_display(data: bytes, truncated: bool) -> str:
    text = data.decode("utf-8", errors="replace")
    if truncated:
        text += "\n...[truncated during capture]"
    return text


def captured_stream_payload(data: bytes, truncated: bool) -> dict:
    return {
        "bytes_sha256": sha256_hex(data),
        "bytes_base64": base64.b64encode(data).decode("ascii"),
        "display_text": bytes_to_display(data, truncated),
        "truncated": truncated,
        "comparison_eligible": not truncated,
    }
