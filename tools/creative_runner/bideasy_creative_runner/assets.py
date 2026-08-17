"""HTTPS-only, bounded asset downloads with hash and host validation."""

from __future__ import annotations

import hashlib
import ipaddress
import re
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Self
from urllib.parse import urljoin, urlparse

import httpx

from .api import InputAsset
from .errors import AssetError

_MIME_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "video/mp4": ".mp4",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "application/json": ".json",
}


def _sniff_mime(path: Path) -> str | None:
    with path.open("rb") as handle:
        header = handle.read(16)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    return None


@dataclass(frozen=True)
class LocalAsset:
    path: Path
    mime_type: str
    role: str
    sha256: str


def _is_public_hostname(hostname: str) -> bool:
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False
    if not addresses:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            return False
    return True


def _validate_https_url(
    url: str,
    *,
    allowed_hosts: tuple[str, ...] | None,
    public_host_validator: Callable[[str], bool],
) -> None:
    try:
        parsed = urlparse(url)
        port = parsed.port
    except ValueError as exc:
        raise AssetError("asset URL is malformed") from exc
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise AssetError("asset URL must be credential-free HTTPS")
    if port not in (None, 443):
        raise AssetError("asset URL must use HTTPS port 443")
    if allowed_hosts is not None and hostname not in allowed_hosts:
        raise AssetError(f"asset host is not allowlisted: {hostname}")
    if not public_host_validator(hostname):
        raise AssetError("asset URL resolved to a non-public address")


class SafeDownloader:
    def __init__(
        self,
        *,
        max_bytes: int,
        input_hosts: tuple[str, ...],
        client: httpx.Client | None = None,
        public_host_validator: Callable[[str], bool] = _is_public_hostname,
        heartbeat: Callable[[], None] | None = None,
        service_token: str | None = None,
        authenticated_input_origin: str | None = None,
        authenticated_input_prefix: str = "/api/v1/creative-runner",
    ) -> None:
        self.max_bytes = max_bytes
        self.input_hosts = tuple(host.lower().rstrip(".") for host in input_hosts)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(60.0, read=120.0), follow_redirects=False
        )
        self._public_host_validator = public_host_validator
        self._heartbeat = heartbeat or (lambda: None)
        self._service_token = service_token
        self._authenticated_input_origin = (
            urlparse(authenticated_input_origin)
            if authenticated_input_origin
            else None
        )
        self._authenticated_input_prefix = authenticated_input_prefix.rstrip("/")
        self._authenticated_input_path = re.compile(
            rf"^{re.escape(self._authenticated_input_prefix)}/inputs/"
            r"[1-9][0-9]*/download$"
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def set_heartbeat(self, heartbeat: Callable[[], None]) -> None:
        self._heartbeat = heartbeat

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _download(
        self,
        url: str,
        destination: Path,
        *,
        allowed_hosts: tuple[str, ...] | None,
        expected_mime: str | None,
        send_service_auth: bool = False,
    ) -> tuple[str, str]:
        current_url = url
        for _redirect in range(6):
            _validate_https_url(
                current_url,
                allowed_hosts=allowed_hosts,
                public_host_validator=self._public_host_validator,
            )
            if send_service_auth and not self._is_authenticated_input_url(current_url):
                raise AssetError("authenticated input URL left the exact runner endpoint")
            headers = {"Accept": "*/*"}
            if send_service_auth:
                if not self._service_token:
                    raise AssetError("runner service token is unavailable for private input")
                headers["Authorization"] = f"Bearer {self._service_token}"
            request = self._client.build_request("GET", current_url, headers=headers)
            # An injected/default httpx client must not be able to attach its own
            # Authorization header to provider or generated asset requests.
            request.headers.pop("authorization", None)
            if send_service_auth:
                request.headers["Authorization"] = f"Bearer {self._service_token}"
            response = self._client.send(request, stream=True)
            try:
                if response.status_code in {301, 302, 303, 307, 308}:
                    if send_service_auth:
                        raise AssetError("authenticated input endpoint must not redirect")
                    location = response.headers.get("location")
                    if not location:
                        raise AssetError("asset redirect omitted Location")
                    current_url = urljoin(current_url, location)
                    continue
                if response.status_code != 200:
                    raise AssetError(
                        f"asset download returned HTTP {response.status_code}"
                    )

                declared_length = response.headers.get("content-length")
                if declared_length:
                    try:
                        if int(declared_length) > self.max_bytes:
                            raise AssetError("asset exceeds maximum allowed size")
                    except ValueError as exc:
                        raise AssetError("asset Content-Length is invalid") from exc

                mime_type = (
                    response.headers.get("content-type", "")
                    .split(";", 1)[0]
                    .strip()
                    .lower()
                )
                if expected_mime and mime_type and mime_type != expected_mime:
                    raise AssetError(
                        f"asset MIME mismatch: expected {expected_mime}, received {mime_type}"
                    )

                digest = hashlib.sha256()
                size = 0
                last_heartbeat = time.monotonic()
                with destination.open("wb") as handle:
                    for chunk in response.iter_bytes():
                        size += len(chunk)
                        if size > self.max_bytes:
                            raise AssetError("asset exceeds maximum allowed size")
                        digest.update(chunk)
                        handle.write(chunk)
                        if time.monotonic() - last_heartbeat >= 30:
                            self._heartbeat()
                            last_heartbeat = time.monotonic()
                return mime_type or (
                    expected_mime or "application/octet-stream"
                ), digest.hexdigest()
            finally:
                response.close()
        raise AssetError("asset exceeded redirect limit")

    def _is_authenticated_input_url(self, url: str) -> bool:
        expected = self._authenticated_input_origin
        if expected is None:
            return False
        try:
            parsed = urlparse(url)
            parsed_port = parsed.port
            expected_port = expected.port
        except ValueError:
            return False
        return bool(
            parsed.scheme == "https"
            and parsed.scheme.lower() == expected.scheme.lower()
            and (parsed.hostname or "").lower().rstrip(".")
            == (expected.hostname or "").lower().rstrip(".")
            and parsed_port == expected_port
            and parsed.username is None
            and parsed.password is None
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
            and self._authenticated_input_path.fullmatch(parsed.path)
        )

    def input_asset(self, asset: InputAsset, directory: Path, index: int) -> LocalAsset:
        if (
            asset.mime_type not in _MIME_SUFFIXES
            or asset.mime_type == "application/json"
        ):
            raise AssetError(f"unsupported input MIME: {asset.mime_type}")
        if asset.role not in {"source_ui", "reference", "storyboard", "voiceover"}:
            raise AssetError(f"unsupported input role: {asset.role}")
        parsed_path = urlparse(asset.url).path
        reserved_private_path = parsed_path.startswith(
            self._authenticated_input_prefix + "/inputs/"
        )
        send_service_auth = self._is_authenticated_input_url(asset.url)
        if reserved_private_path and not send_service_auth:
            raise AssetError("private input URL does not match the exact runner endpoint")
        destination = directory / f"input-{index}{_MIME_SUFFIXES[asset.mime_type]}"
        mime_type, digest = self._download(
            asset.url,
            destination,
            allowed_hosts=self.input_hosts,
            expected_mime=asset.mime_type,
            send_service_auth=send_service_auth,
        )
        actual_mime = _sniff_mime(destination)
        if actual_mime != asset.mime_type:
            destination.unlink(missing_ok=True)
            raise AssetError("input asset bytes do not match declared MIME")
        if digest != asset.sha256:
            destination.unlink(missing_ok=True)
            raise AssetError("input asset SHA-256 mismatch")
        return LocalAsset(destination, mime_type, asset.role, digest)

    def generated_asset(
        self,
        url: str,
        directory: Path,
        index: int,
        *,
        expected_prefix: str,
    ) -> LocalAsset:
        parsed_suffix = Path(urlparse(url).path).suffix.lower()
        temporary_suffix = (
            parsed_suffix if parsed_suffix in set(_MIME_SUFFIXES.values()) else ".bin"
        )
        temporary = directory / f"generated-{index}{temporary_suffix}"
        mime_type, digest = self._download(
            url,
            temporary,
            allowed_hosts=None,
            expected_mime=None,
            send_service_auth=False,
        )
        sniffed_mime = _sniff_mime(temporary)
        if sniffed_mime:
            mime_type = sniffed_mime
        if not mime_type.startswith(expected_prefix):
            temporary.unlink(missing_ok=True)
            raise AssetError(f"generated asset is not {expected_prefix.rstrip('/')}")
        suffix = _MIME_SUFFIXES.get(mime_type)
        if suffix and temporary.suffix != suffix:
            destination = temporary.with_suffix(suffix)
            temporary.replace(destination)
            temporary = destination
        return LocalAsset(temporary, mime_type, "generated", digest)
