# SPDX-FileCopyrightText: 2026 Tsakanyan Hovhannes
# SPDX-License-Identifier: Apache-2.0
"""Safe acquisition and archive extraction (B03 step 1).

Nothing here is used by tests against the network: the tests drive the same code with a fake
fetcher and locally generated archives. Guarantees enforced regardless of transport:

* HTTPS only, host allowlist, no userinfo, no fragment, each redirect hop re-validated;
* hostnames resolving to loopback/private/link-local/metadata addresses are refused;
* resumable ``.part`` downloads verified by SHA-256 and byte length before an atomic rename;
* a failed verification leaves no published file and no partially trusted cache entry;
* archive extraction rejects traversal, absolute paths, links, devices, duplicate or
  normalization-colliding names and enforces byte/file/count/depth limits.
"""

from __future__ import annotations

import fnmatch
import hashlib
import http.client
import ipaddress
import os
import shutil
import socket
import tarfile
import unicodedata
import urllib.parse
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Protocol

from .errors import AcquisitionError

CHUNK = 1024 * 1024


@dataclass(frozen=True)
class SourcePolicy:
    allowed_hosts: frozenset[str]
    max_redirects: int = 3
    allowed_schemes: frozenset[str] = frozenset({"https"})


@dataclass(frozen=True)
class FetchResult:
    """One HTTP response."""

    final_url: str
    status: int
    body: bytes  # bounded by the fetcher
    location: str | None = None
    range_start: int | None = None


class Fetcher(Protocol):
    def __call__(self, url: str, *, offset: int, max_bytes: int) -> FetchResult: ...


Resolver = Callable[[str], list[str]]


class HTTPSFetcher:
    """Bounded standard-library HTTPS GET with redirects returned, never auto-followed."""

    def __init__(self, *, timeout: float = 30.0) -> None:
        self.timeout = timeout

    def __call__(self, url: str, *, offset: int, max_bytes: int) -> FetchResult:
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "https" or not parts.hostname:
            raise AcquisitionError("HTTPSFetcher accepts only absolute HTTPS URLs")
        connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, timeout=self.timeout)
        path = urllib.parse.urlunsplit(("", "", parts.path or "/", parts.query, ""))
        headers = {"Accept-Encoding": "identity", "User-Agent": "audio-bench-acquirer/0.1"}
        headers["Range"] = f"bytes={offset}-{offset + max_bytes - 1}"
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                return FetchResult(url, response.status, b"", response.getheader("Location"))
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise AcquisitionError("HTTP response exceeded the requested chunk size")
            range_start = None
            content_range = response.getheader("Content-Range")
            if content_range and content_range.startswith("bytes "):
                try:
                    range_start = int(content_range[6:].split("-", 1)[0])
                except ValueError:
                    raise AcquisitionError("malformed Content-Range response") from None
            return FetchResult(url, response.status, body, range_start=range_start)
        finally:
            connection.close()


def _default_resolver(host: str) -> list[str]:
    infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    return sorted({info[4][0] for info in infos})


def validate_url(url: str, policy: SourcePolicy, *, resolver: Resolver | None = None) -> urllib.parse.SplitResult:
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in policy.allowed_schemes:
        raise AcquisitionError(f"scheme {parts.scheme!r} is not allowed")
    if parts.username or parts.password:
        raise AcquisitionError("credentials in URLs are forbidden")
    if parts.fragment:
        raise AcquisitionError("URL fragments are forbidden")
    host = (parts.hostname or "").lower()
    if not host:
        raise AcquisitionError("URL has no host")
    if host not in policy.allowed_hosts:
        raise AcquisitionError(f"host {host!r} is not on the acquisition allowlist")
    if parts.port not in (None, 443):
        raise AcquisitionError("only the default HTTPS port is allowed")
    addresses = (resolver or _default_resolver)(host)
    if not addresses:
        raise AcquisitionError(f"host {host!r} does not resolve")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            raise AcquisitionError(f"host {host!r} resolves to a non-public address")
    return parts


def acquire(
    url: str,
    destination: Path,
    *,
    expected_sha256: str,
    expected_bytes: int,
    policy: SourcePolicy,
    fetcher: Fetcher,
    max_bytes: int = 4 * 1024 * 1024 * 1024,
    resolver: Resolver | None = None,
) -> Path:
    """Download, verify and atomically publish one immutable artifact."""
    if expected_bytes <= 0 or expected_bytes > max_bytes:
        raise AcquisitionError("declared artifact size is outside the allowed range")
    if not expected_sha256.startswith("sha256:") or len(expected_sha256) != 71:
        raise AcquisitionError("expected_sha256 must be 'sha256:<64 lowercase hex>'")
    part = destination.with_suffix(destination.suffix + ".part")
    part.parent.mkdir(parents=True, exist_ok=True)
    offset = part.stat().st_size if part.exists() else 0
    if offset > expected_bytes:
        part.unlink()
        offset = 0
    current = url
    redirects = 0
    while offset < expected_bytes:
        validate_url(current, policy, resolver=resolver)
        chunk_bytes = min(4 * 1024 * 1024, expected_bytes - offset)
        result = fetcher(current, offset=offset, max_bytes=chunk_bytes)
        if result.status in (301, 302, 303, 307, 308):
            location = _location_of(result)
            if not location:
                raise AcquisitionError("redirect without a location")
            redirects += 1
            if redirects > policy.max_redirects:
                raise AcquisitionError("too many redirects")
            current = urllib.parse.urljoin(current, location)
            continue
        # A Fetcher must not silently follow redirects: every hop is allowlisted here.
        if result.final_url != current:
            raise AcquisitionError("fetcher followed an unvalidated redirect")
        if result.status not in (200, 206):
            raise AcquisitionError(f"unexpected HTTP status {result.status}")
        if offset and result.status != 206:
            raise AcquisitionError("server ignored the resume range request")
        if result.status == 206 and result.range_start != offset:
            raise AcquisitionError("Content-Range does not begin at the requested offset")
        body = result.body
        if not body:
            raise AcquisitionError("empty response body")
        if len(body) > chunk_bytes or offset + len(body) > expected_bytes:
            raise AcquisitionError("response exceeds the declared artifact size/chunk")
        with open(part, "ab") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        offset += len(body)
    if not part.exists() or part.stat().st_size != expected_bytes:
        raise AcquisitionError("download did not reach the declared artifact size")
    digest = _sha256_file(part)
    if digest != expected_sha256:
        part.unlink(missing_ok=True)
        raise AcquisitionError(f"archive digest mismatch: expected {expected_sha256}, computed {digest}")
    os.replace(part, destination)
    _fsync_dir(destination.parent)
    return destination


def _location_of(result: FetchResult) -> str | None:
    return result.location


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            hasher.update(chunk)
    return "sha256:" + hasher.hexdigest()


def _fsync_dir(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class ExtractionLimits:
    max_bytes: int = 2 * 1024 * 1024 * 1024
    max_files: int = 10_000
    max_depth: int = 8
    allowed_suffixes: tuple[str, ...] = (".wav", ".flac", ".json", ".jsonl", ".txt", ".csv", ".md")


def _check_member_name(name: str, limits: ExtractionLimits) -> str:
    if not name:
        raise AcquisitionError("empty archive member name")
    if name.startswith("/") or name.startswith("\\"):
        raise AcquisitionError(f"absolute archive member path: {name!r}")
    if "\\" in name:
        raise AcquisitionError(f"backslash in archive member name: {name!r}")
    if ":" in name.split("/")[0]:
        raise AcquisitionError(f"drive or scheme in archive member name: {name!r}")
    parts = [part for part in name.split("/") if part not in ("", ".")]
    if any(part == ".." for part in parts):
        raise AcquisitionError(f"path traversal in archive member: {name!r}")
    if len(parts) > limits.max_depth:
        raise AcquisitionError(f"archive member too deep: {name!r}")
    normalized = unicodedata.normalize("NFKC", "/".join(parts))
    if normalized != "/".join(parts):
        raise AcquisitionError(f"non-normalized archive member name: {name!r}")
    if not any(name.lower().endswith(suffix) for suffix in limits.allowed_suffixes):
        raise AcquisitionError(f"archive member type is not allowlisted: {name!r}")
    return "/".join(parts)


def _validate_members(members: list[tuple[str, int, bool, str]], limits: ExtractionLimits) -> list[str]:
    """``members`` holds (name, size, is_regular, kind) tuples from the archive index."""
    if len(members) > limits.max_files:
        raise AcquisitionError("archive exceeds the file-count limit")
    total = 0
    names: list[str] = []
    for name, size, is_regular, kind in members:
        if not is_regular:
            raise AcquisitionError(f"archive member {name!r} is a {kind}; links and devices are refused")
        if size < 0:
            raise AcquisitionError(f"archive member {name!r} has an invalid size")
        total += size
        if total > limits.max_bytes:
            raise AcquisitionError("archive exceeds the extracted byte limit")
        names.append(_check_member_name(name, limits).lower())
    if len(set(names)) != len(names):
        raise AcquisitionError("archive has duplicate or normalization-colliding member names")
    return names


def extract_archive(archive: Path, destination: Path, *, limits: ExtractionLimits | None = None) -> list[str]:
    """Safe extraction of an inspected tar/zip archive into a fresh directory."""
    limits = limits or ExtractionLimits()
    destination = destination.resolve()
    if destination.exists():
        raise AcquisitionError("extraction destination must not already exist")
    staging = destination.with_name(destination.name + ".extracting")
    staging.mkdir(parents=False, exist_ok=False)
    try:
        if zipfile.is_zipfile(archive):
            members = _zip_members(archive, limits)
            _validate_members(members, limits)
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    if info.is_dir():
                        continue
                    target = _member_target(staging, info.filename)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    written = 0
                    with bundle.open(info) as source, open(target, "wb") as sink:
                        for chunk in iter(lambda: source.read(CHUNK), b""):
                            written += len(chunk)
                            if written > info.file_size or written > limits.max_bytes:
                                raise AcquisitionError("zip member exceeds its declared size")
                            sink.write(chunk)
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive, mode="r:*") as bundle:
                members = _tar_members(bundle, limits)
                _validate_members(members, limits)
                for member in bundle.getmembers():
                    if member.isdir():
                        continue
                    target = _member_target(staging, member.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = bundle.extractfile(member)
                    if source is None:
                        raise AcquisitionError(f"cannot read archive member {member.name!r}")
                    written = 0
                    with source, open(target, "wb") as sink:
                        for chunk in iter(lambda: source.read(CHUNK), b""):
                            written += len(chunk)
                            if written > member.size:
                                raise AcquisitionError("tar member exceeds its declared size")
                            sink.write(chunk)
        else:
            raise AcquisitionError("unsupported archive format")
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    os.replace(staging, destination)
    return sorted(
        str(path.relative_to(destination)) for path in destination.rglob("*") if path.is_file()
    )


def _member_target(root: Path, name: str) -> Path:
    relative = Path(*[part for part in name.split("/") if part not in ("", ".")])
    target = (root / relative).resolve()
    if not str(target).startswith(str(root) + os.sep):
        raise AcquisitionError(f"archive member escapes the destination: {name!r}")
    return target


def _zip_members(archive: Path, limits: ExtractionLimits) -> list[tuple[str, int, bool, str]]:
    members = []
    with zipfile.ZipFile(archive) as bundle:
        for info in bundle.infolist():
            if info.is_dir():
                continue
            mode = (info.external_attr >> 16) & 0o170000
            is_regular = mode in (0, 0o100000)
            kind = "symlink" if mode == 0o120000 else "special"
            members.append((info.filename, info.file_size, is_regular, kind))
    return members


def _tar_members(bundle: tarfile.TarFile, limits: ExtractionLimits) -> list[tuple[str, int, bool, str]]:
    members = []
    for member in bundle.getmembers():
        if member.isdir():
            continue
        kind = "symlink" if member.issym() else "hardlink" if member.islnk() else "device" if member.isdev() else "special"
        members.append((member.name, member.size, member.isreg(), kind))
    return members


def match_allowlist(relative_paths: Iterable[str], patterns: Iterable[str]) -> list[str]:
    """Explicit allowlist matching used instead of copying a directory wholesale."""
    patterns = list(patterns)
    return sorted(
        path for path in relative_paths if any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)
    )
