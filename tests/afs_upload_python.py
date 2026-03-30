"""Simple AFS uploader for openBIS using the same logic as `afsDatasetAPI.ts`.

Flow:
1) Encode one AFS chunk (binary protocol).
2) POST to `/afs-server/api?method=write&sessionToken=...` with `.part` target.
3) POST `method=move` to atomically rename `.part` to final path.
"""

from __future__ import annotations

import argparse
import json
import random
import ssl
import struct
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

AFS_API_PATH = "/afs-server/api"


def generate_upload_id(prefix: str = "upload") -> str:
    now = datetime.now()
    return "-".join(
        [
            prefix,
            f"{now.year:04d}",
            f"{now.month:02d}",
            f"{now.day:02d}",
            f"{now.hour:02d}",
            f"{now.minute:02d}",
            f"{now.second:02d}",
            f"{random.randint(0, 100000):05d}",
        ]
    )


def _encode_afs_chunk(
    owner: str,
    source: str,
    offset: int,
    limit: Optional[int],
    data: Optional[bytes],
) -> bytes:
    owner_bytes = owner.encode("utf-8") if owner is not None else None
    source_bytes = source.encode("utf-8") if source is not None else None
    data_bytes = data if data is not None else None

    packet = bytearray()

    packet.extend(
        struct.pack(">i", len(owner_bytes) if owner_bytes is not None else -1)
    )
    if owner_bytes is not None:
        packet.extend(owner_bytes)

    packet.extend(
        struct.pack(">i", len(source_bytes) if source_bytes is not None else -1)
    )
    if source_bytes is not None:
        packet.extend(source_bytes)

    packet.extend(struct.pack(">q", offset if offset is not None else -1))

    chunk_limit = (
        limit
        if limit is not None
        else (len(data_bytes) if data_bytes is not None else -1)
    )
    packet.extend(struct.pack(">i", chunk_limit))

    packet.extend(struct.pack(">i", len(data_bytes) if data_bytes is not None else -1))
    if data_bytes is not None:
        packet.extend(data_bytes)

    return bytes(packet)


def _encode_afs_chunks_as_bytes(chunks: list[Dict[str, object]]) -> bytes:
    encoded_chunks = [
        _encode_afs_chunk(
            owner=str(chunk.get("owner", "")),
            source=str(chunk.get("source", "")),
            offset=int(chunk.get("offset", -1)),
            limit=int(chunk["limit"]) if chunk.get("limit") is not None else None,
            data=chunk.get("data")
            if isinstance(chunk.get("data"), (bytes, bytearray))
            else None,
        )
        for chunk in chunks
    ]

    packet = bytearray()
    packet.extend(struct.pack(">i", len(encoded_chunks)))
    for encoded in encoded_chunks:
        packet.extend(encoded)
    return bytes(packet)


def _http_post(
    url: str,
    body: bytes,
    headers: Dict[str, str],
    timeout: int = 120,
    verify_tls: bool = True,
) -> tuple[int, str]:
    request = Request(url=url, data=body, headers=headers, method="POST")
    ssl_context = None if verify_tls else ssl._create_unverified_context()
    with urlopen(request, timeout=timeout, context=ssl_context) as response:
        payload = response.read().decode("utf-8", errors="replace")
        return int(response.status), payload


def _parse_afs_api_response(status_code: int, payload: str):
    text = payload.strip()

    try:
        parsed = json.loads(text) if text else None
    except json.JSONDecodeError:
        if text.lower() == "true":
            return True
        if text.lower() == "false":
            return False
        raise RuntimeError(
            f"AFS returned non-JSON response (HTTP {status_code}): {text[:500]}"
        )

    if status_code < 200 or status_code >= 300:
        raise RuntimeError(f"AFS request failed (HTTP {status_code}): {parsed}")

    if isinstance(parsed, dict) and parsed.get("error"):
        raise RuntimeError(f"AFS request returned error: {parsed['error']}")

    return parsed


def write_afs_file(
    base_url: str, session_token: str, chunk: Dict[str, object], verify_tls: bool = True
) -> None:
    url = f"{base_url.rstrip('/')}{AFS_API_PATH}?{urlencode({'method': 'write', 'sessionToken': session_token})}"
    body = _encode_afs_chunks_as_bytes([chunk])

    status, payload = _http_post(
        url=url,
        body=body,
        headers={"Content-Type": "application/octet-stream"},
        verify_tls=verify_tls,
    )
    result = _parse_afs_api_response(status, payload)
    if result is not True:
        raise RuntimeError(f"AFS write returned non-true result: {result!r}")


def move_afs_file(
    base_url: str,
    session_token: str,
    owner: str,
    source: str,
    target: str,
    verify_tls: bool = True,
) -> None:
    url = f"{base_url.rstrip('/')}{AFS_API_PATH}"
    payload = urlencode(
        {
            "method": "move",
            "sourceOwner": owner,
            "source": source,
            "targetOwner": owner,
            "target": target,
            "sessionToken": session_token,
        }
    )

    status, response_payload = _http_post(
        url,
        body=payload.encode("utf-8"),
        headers={"Content-Type": "text/plain;charset=UTF-8"},
        verify_tls=verify_tls,
    )
    result = _parse_afs_api_response(status, response_payload)
    if result is not True:
        raise RuntimeError(f"AFS move returned non-true result: {result!r}")


def upload_afs_dataset(
    base_url: str,
    session_token: str,
    file_path: str,
    owner: str,
    verify_tls: bool = True,
) -> Dict[str, str]:
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    owner = owner.strip()
    if not owner:
        raise ValueError("AFS upload requires a non-empty owner.")

    relative_name = path.name
    afs_path = f"/{relative_name.replace('/', '_')}"
    part_path = f"{afs_path}.part"

    file_bytes = path.read_bytes()
    chunk = {
        "owner": owner,
        "source": part_path,
        "offset": 0,
        "limit": len(file_bytes),
        "data": file_bytes,
    }

    write_afs_file(base_url, session_token, chunk, verify_tls=verify_tls)
    move_afs_file(
        base_url, session_token, owner, part_path, afs_path, verify_tls=verify_tls
    )

    return {"afsPath": afs_path}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Upload one file to openBIS AFS using write-then-move."
    )
    parser.add_argument(
        "--base-url",
        required=True,
        help="openBIS base URL, e.g. https://openbis.example.org",
    )
    parser.add_argument(
        "--session-token",
        required=True,
        help="openBIS session token (PAT/session token)",
    )
    parser.add_argument(
        "--owner",
        required=True,
        help="AFS owner (samplePermId/experiment/sample identifier)",
    )
    parser.add_argument("--file", required=True, help="Local file path to upload")
    parser.add_argument(
        "--insecure", action="store_true", help="Disable TLS certificate verification"
    )
    args = parser.parse_args()
    result = upload_afs_dataset(
        base_url=args.base_url,
        session_token=args.session_token,
        file_path=args.file,
        owner=args.owner,
        verify_tls=not args.insecure,
    )
    print(json.dumps(result))


if __name__ == "__main__":
    main()
