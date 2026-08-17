from __future__ import annotations

import hashlib
import io
from pathlib import Path

import httpx
import pytest
from bideasy_creative_runner.api import InputAsset
from bideasy_creative_runner.assets import SafeDownloader
from bideasy_creative_runner.errors import AssetError
from PIL import Image


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), "#3182F6").save(buffer, "PNG")
    return buffer.getvalue()


def test_input_download_validates_host_mime_magic_and_hash(tmp_path: Path):
    body = _png_bytes()
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200, headers={"content-type": "image/png"}, content=body
        )
    )
    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("bideasy.kr",),
        client=httpx.Client(transport=transport),
        public_host_validator=lambda _host: True,
    )
    local = downloader.input_asset(
        InputAsset(
            "https://bideasy.kr/assets/source.png",
            hashlib.sha256(body).hexdigest(),
            "image/png",
            "source_ui",
        ),
        tmp_path,
        1,
    )
    assert local.path.read_bytes() == body
    assert local.role == "source_ui"


def test_input_download_rejects_unlisted_host(tmp_path: Path):
    downloader = SafeDownloader(
        max_bytes=1024,
        input_hosts=("bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200))
        ),
        public_host_validator=lambda _host: True,
    )
    with pytest.raises(AssetError, match="not allowlisted"):
        downloader.input_asset(
            InputAsset(
                "https://evil.example/a.png", "a" * 64, "image/png", "reference"
            ),
            tmp_path,
            1,
        )


def test_input_download_rejects_hash_mismatch(tmp_path: Path):
    body = _png_bytes()
    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200, headers={"content-type": "image/png"}, content=body
                )
            )
        ),
        public_host_validator=lambda _host: True,
    )
    with pytest.raises(AssetError, match="SHA-256"):
        downloader.input_asset(
            InputAsset("https://bideasy.kr/a.png", "b" * 64, "image/png", "reference"),
            tmp_path,
            1,
        )


def test_input_download_rejects_malformed_port_as_asset_error(tmp_path: Path):
    downloader = SafeDownloader(
        max_bytes=1024,
        input_hosts=("bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(lambda _request: httpx.Response(200))
        ),
        public_host_validator=lambda _host: True,
    )
    with pytest.raises(AssetError, match="malformed"):
        downloader.input_asset(
            InputAsset(
                "https://bideasy.kr:not-a-port/a.png",
                "a" * 64,
                "image/png",
                "reference",
            ),
            tmp_path,
            1,
        )


def test_private_input_sends_service_bearer_only_to_exact_runner_url(tmp_path: Path):
    body = _png_bytes()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("api.bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer default-must-not-decide"},
        ),
        public_host_validator=lambda _host: True,
        service_token="private-runner-token",
        authenticated_input_origin="https://api.bideasy.kr",
        authenticated_input_prefix="/api/v1/creative-runner",
    )
    downloader.input_asset(
        InputAsset(
            "https://api.bideasy.kr/api/v1/creative-runner/inputs/17/download",
            hashlib.sha256(body).hexdigest(),
            "image/png",
            "source_ui",
        ),
        tmp_path,
        1,
    )
    assert seen[0].headers["authorization"] == "Bearer private-runner-token"


def test_service_bearer_is_removed_from_external_input_and_generated_requests(
    tmp_path: Path,
):
    body = _png_bytes()
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "image/png"}, content=body)

    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer must-never-leak"},
        ),
        public_host_validator=lambda _host: True,
        service_token="private-runner-token",
        authenticated_input_origin="https://api.bideasy.kr",
        authenticated_input_prefix="/api/v1/creative-runner",
    )
    downloader.input_asset(
        InputAsset(
            "https://bideasy.kr/approved/source.png",
            hashlib.sha256(body).hexdigest(),
            "image/png",
            "source_ui",
        ),
        tmp_path,
        1,
    )
    downloader.generated_asset(
        "https://provider.example/generated.png",
        tmp_path,
        2,
        expected_prefix="image/",
    )
    assert len(seen) == 2
    assert all("authorization" not in request.headers for request in seen)


def test_authenticated_private_input_redirect_is_rejected_without_forwarding_token(
    tmp_path: Path,
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(302, headers={"location": "https://provider.example/file.png"})

    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("api.bideasy.kr",),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        public_host_validator=lambda _host: True,
        service_token="private-runner-token",
        authenticated_input_origin="https://api.bideasy.kr",
        authenticated_input_prefix="/api/v1/creative-runner",
    )
    with pytest.raises(AssetError, match="must not redirect"):
        downloader.input_asset(
            InputAsset(
                "https://api.bideasy.kr/api/v1/creative-runner/inputs/17/download",
                "a" * 64,
                "image/png",
                "source_ui",
            ),
            tmp_path,
            1,
        )
    assert len(seen) == 1
    assert seen[0].headers["authorization"] == "Bearer private-runner-token"


def test_provider_redirect_to_private_endpoint_never_receives_service_bearer(
    tmp_path: Path,
):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.host == "bideasy.kr":
            return httpx.Response(
                302,
                headers={
                    "location": (
                        "https://api.bideasy.kr/api/v1/creative-runner/inputs/17/download"
                    )
                },
            )
        return httpx.Response(401)

    downloader = SafeDownloader(
        max_bytes=1024 * 1024,
        input_hosts=("api.bideasy.kr", "bideasy.kr"),
        client=httpx.Client(
            transport=httpx.MockTransport(handler),
            headers={"Authorization": "Bearer must-never-leak"},
        ),
        public_host_validator=lambda _host: True,
        service_token="private-runner-token",
        authenticated_input_origin="https://api.bideasy.kr",
        authenticated_input_prefix="/api/v1/creative-runner",
    )
    with pytest.raises(AssetError, match="HTTP 401"):
        downloader.input_asset(
            InputAsset(
                "https://bideasy.kr/redirect.png",
                "a" * 64,
                "image/png",
                "source_ui",
            ),
            tmp_path,
            1,
        )
    assert len(seen) == 2
    assert all("authorization" not in request.headers for request in seen)


@pytest.mark.parametrize(
    "url",
    [
        "https://api.bideasy.kr/api/v1/creative-runner/inputs/17/download?token=x",
        "https://api.bideasy.kr/api/v1/creative-runner/inputs/017/download",
        "https://api.bideasy.kr/api/v1/creative-runner/inputs/17/download/extra",
    ],
)
def test_near_private_input_urls_are_rejected_without_request(tmp_path: Path, url: str):
    seen: list[httpx.Request] = []
    downloader = SafeDownloader(
        max_bytes=1024,
        input_hosts=("api.bideasy.kr",),
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda request: seen.append(request) or httpx.Response(200)
            )
        ),
        public_host_validator=lambda _host: True,
        service_token="private-runner-token",
        authenticated_input_origin="https://api.bideasy.kr",
        authenticated_input_prefix="/api/v1/creative-runner",
    )
    with pytest.raises(AssetError, match="exact runner endpoint"):
        downloader.input_asset(
            InputAsset(url, "a" * 64, "image/png", "source_ui"),
            tmp_path,
            1,
        )
    assert seen == []
