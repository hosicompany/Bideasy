"""Small authenticated client for the creative-runner lease and upload API."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Self

import httpx

from .config import PINNED_HIGGSFIELD_VERSION, RunnerConfig
from .errors import ApiAuthenticationError, ApiError, InvalidJobError

_JOB_ID = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}"
)


@dataclass(frozen=True)
class InputAsset:
    url: str
    sha256: str
    mime_type: str
    role: str


@dataclass(frozen=True)
class ClaimedAttempt:
    attempt_id: int
    creative_id: str
    attempt_no: int
    job_type: str
    prompt: str
    params: dict[str, Any]
    input_assets: tuple[InputAsset, ...]
    input_hash: str | None
    lease_expires_at: str | None
    brief_format: str | None = None
    higgsfield_job_id: str | None = None
    virality_job_id: str | None = None
    hook: str = ""
    body_copy: str = ""
    cta_copy: str = ""


def _json_object(value: Any, label: str) -> dict[str, Any]:
    if value in (None, ""):
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InvalidJobError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise InvalidJobError(f"{label} must be a JSON object")
    return value


def _input_assets(value: Any) -> tuple[InputAsset, ...]:
    if value in (None, ""):
        return ()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise InvalidJobError("input_files_json is not valid JSON") from exc
    if not isinstance(value, list):
        raise InvalidJobError("input_files_json must be a JSON array")

    assets: list[InputAsset] = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidJobError("each input file must be an object")
        try:
            asset = InputAsset(
                url=str(item["url"]),
                sha256=str(item["sha256"]).lower(),
                mime_type=str(item["mime_type"]).lower(),
                role=str(item["role"]),
            )
        except KeyError as exc:
            raise InvalidJobError(f"input file missing {exc.args[0]}") from exc
        if len(asset.sha256) != 64 or any(
            ch not in "0123456789abcdef" for ch in asset.sha256
        ):
            raise InvalidJobError(
                "input file sha256 must be 64 lowercase hex characters"
            )
        assets.append(asset)
    return tuple(assets)


def _optional_job_id(value: Any, label: str) -> str | None:
    if value in (None, ""):
        return None
    if not isinstance(value, str) or not _JOB_ID.fullmatch(value):
        raise InvalidJobError(f"{label} must be a UUID")
    return value.lower()


class CreativeApiClient:
    def __init__(
        self,
        config: RunnerConfig,
        *,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self._sleep = sleeper
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=config.request_timeout_seconds,
            headers={"Authorization": f"Bearer {config.service_token}"},
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        retry_waiter: Callable[[float], None] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        url = f"{self.config.runner_api_url}/{path.lstrip('/')}"
        request_headers = dict(kwargs.pop("headers", {}))
        request_headers["Authorization"] = f"Bearer {self.config.service_token}"
        last_error: Exception | None = None
        for retry_index in range(len(self.config.retry_backoffs) + 1):
            for file_value in (kwargs.get("files") or {}).values():
                if (
                    isinstance(file_value, tuple)
                    and len(file_value) >= 2
                    and hasattr(file_value[1], "seek")
                ):
                    file_value[1].seek(0)
            try:
                response = self._client.request(
                    method, url, headers=request_headers, **kwargs
                )
            except httpx.RequestError as exc:
                last_error = exc
                response = None

            if response is not None:
                if response.status_code in (401, 403):
                    raise ApiAuthenticationError(
                        "creative runner service token was rejected"
                    )
                if response.status_code != 429 and response.status_code < 500:
                    return response
                last_error = ApiError(
                    f"runner API returned HTTP {response.status_code}"
                )

            if retry_index == len(self.config.retry_backoffs):
                break
            (retry_waiter or self._sleep)(self.config.retry_backoffs[retry_index])
        raise ApiError(
            "runner API request failed after bounded retries"
        ) from last_error

    def claim(self) -> ClaimedAttempt | None:
        response = self._request(
            "POST",
            "claim",
            json={
                "runner_id": self.config.runner_id,
                "cli_version": PINNED_HIGGSFIELD_VERSION,
            },
        )
        if response.status_code == 204:
            return None
        if response.status_code != 200:
            raise ApiError(f"claim failed with HTTP {response.status_code}")
        try:
            payload = response.json()
            return ClaimedAttempt(
                attempt_id=int(payload["attempt_id"]),
                creative_id=str(payload["creative_id"]),
                attempt_no=int(payload["attempt_no"]),
                job_type=str(payload["job_type"]),
                prompt=str(payload.get("prompt") or ""),
                params=_json_object(payload.get("params_json"), "params_json"),
                input_assets=_input_assets(payload.get("input_files_json")),
                input_hash=str(payload["input_hash"])
                if payload.get("input_hash")
                else None,
                lease_expires_at=str(payload["lease_expires_at"])
                if payload.get("lease_expires_at")
                else None,
                brief_format=str(payload["brief_format"])
                if payload.get("brief_format")
                else None,
                higgsfield_job_id=_optional_job_id(
                    payload.get("higgsfield_job_id"), "higgsfield_job_id"
                ),
                virality_job_id=_optional_job_id(
                    payload.get("virality_job_id"), "virality_job_id"
                ),
                hook=str(payload["hook"]),
                body_copy=str(payload["body_copy"]),
                cta_copy=str(payload["cta_copy"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise InvalidJobError("claim response is missing required fields") from exc

    def heartbeat(
        self,
        attempt_id: int,
        *,
        status: str,
        higgsfield_job_id: str | None = None,
        virality_job_id: str | None = None,
    ) -> None:
        if status not in {"GENERATING", "PROCESSING"}:
            raise ValueError("invalid heartbeat status")
        body: dict[str, Any] = {"runner_id": self.config.runner_id, "status": status}
        if higgsfield_job_id:
            body["higgsfield_job_id"] = higgsfield_job_id
        if virality_job_id:
            body["virality_job_id"] = virality_job_id
        response = self._request("POST", f"{attempt_id}/heartbeat", json=body)
        if response.status_code not in (200, 204):
            raise ApiError(f"heartbeat failed with HTTP {response.status_code}")

    def upload_output(
        self,
        attempt_id: int,
        path: Path,
        *,
        kind: str,
        is_primary: bool = False,
        metadata: dict[str, Any] | None = None,
        retry_waiter: Callable[[float], None] | None = None,
    ) -> dict[str, Any]:
        hasher = hashlib.sha256()
        with path.open("rb") as digest_handle:
            for chunk in iter(lambda: digest_handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = self._request(
                "POST",
                f"{attempt_id}/output",
                retry_waiter=retry_waiter,
                files={"file": (path.name, handle, mime_type)},
                data={
                    "runner_id": self.config.runner_id,
                    "kind": kind,
                    "is_primary": "true" if is_primary else "false",
                    "metadata_json": json.dumps(
                        metadata or {}, ensure_ascii=False, separators=(",", ":")
                    ),
                    "sha256": digest,
                },
            )
        if response.status_code not in (200, 201):
            raise ApiError(f"output upload failed with HTTP {response.status_code}")
        try:
            return response.json()
        except json.JSONDecodeError as exc:
            raise ApiError("output upload returned invalid JSON") from exc

    def fail(
        self, attempt_id: int, error: str, *, auth_required: bool, retryable: bool
    ) -> None:
        response = self._request(
            "POST",
            f"{attempt_id}/fail",
            json={
                "runner_id": self.config.runner_id,
                "error": error[:2000],
                "auth_required": auth_required,
                "retryable": retryable,
            },
        )
        if response.status_code not in (200, 204):
            raise ApiError(f"failure report returned HTTP {response.status_code}")
