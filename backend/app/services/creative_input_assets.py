"""Private, authenticated storage for creative generation inputs.

Input source UI, storyboards and voiceovers are not publishable outputs.  They
live under a dedicated ``_inputs`` namespace and can only be read through the
admin or rotating service-token endpoints.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from fastapi import Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models
from app.schemas.creative import CreativeInputFile


INPUT_ROLES = frozenset({"source_ui", "reference", "storyboard", "voiceover"})
RUNNER_INPUT_PATH_RE = re.compile(
    r"^/api/v1/creative-runner/inputs/([1-9][0-9]*)/download$"
)

_MIME_ALIASES = {
    "image/png": "image/png",
    "image/jpeg": "image/jpeg",
    "image/jpg": "image/jpeg",
    "image/webp": "image/webp",
    "video/mp4": "video/mp4",
    "audio/mpeg": "audio/mpeg",
    "audio/mp3": "audio/mpeg",
    "audio/wav": "audio/wav",
    "audio/x-wav": "audio/wav",
}
_MIME_EXTENSIONS: dict[str, tuple[str, set[str]]] = {
    "image/png": (".png", {".png"}),
    "image/jpeg": (".jpg", {".jpg", ".jpeg"}),
    "image/webp": (".webp", {".webp"}),
    "video/mp4": (".mp4", {".mp4"}),
    "audio/mpeg": (".mp3", {".mp3"}),
    "audio/wav": (".wav", {".wav"}),
}
_ROLE_MIMES = {
    "source_ui": {"image/png", "image/jpeg", "image/webp", "video/mp4"},
    "storyboard": {"image/png", "image/jpeg", "image/webp"},
    "voiceover": {"audio/mpeg", "audio/wav"},
    "reference": set(_MIME_EXTENSIONS),
}
_MAX_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_AUDIO_BYTES = 50 * 1024 * 1024
_MAX_AUDIO_DURATION_MS = 10 * 60 * 1000
_MAX_VIDEO_DURATION_MS = 30 * 60 * 1000
_MAX_PIXELS = 50_000_000
_MAX_EDGE = 10_000
_WAV_VALIDATION_CHUNK_BYTES = 1024 * 1024
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_MIME = re.compile(r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")


class CreativeInputAssetError(Exception):
    """Base exception suitable for a bounded API error response."""


class CreativeInputAssetNotFound(CreativeInputAssetError):
    pass


class CreativeInputAssetValidationError(CreativeInputAssetError):
    pass


def runner_download_path(asset_id: int) -> str:
    return f"/api/v1/creative-runner/inputs/{asset_id}/download"


def admin_preview_path(asset_id: int) -> str:
    return f"/api/v1/admin/creative-inputs/{asset_id}/download"


def upload_response(asset: models.CreativeInputAsset) -> dict[str, Any]:
    return {
        "id": asset.id,
        "creative_id": asset.creative_id,
        "role": asset.role,
        "original_filename": asset.original_filename,
        "storage_path": asset.storage_path,
        "sha256": asset.sha256,
        "mime_type": asset.mime_type,
        "size_bytes": asset.size_bytes,
        "width": asset.width,
        "height": asset.height,
        "duration_ms": asset.duration_ms,
        "media_metadata_json": asset.media_metadata_json or {},
        "created_by": asset.created_by,
        "created_at": asset.created_at,
        "manifest": {
            "url": runner_download_path(asset.id),
            "sha256": asset.sha256,
            "mime_type": asset.mime_type,
            "role": asset.role,
        },
        "preview_url": admin_preview_path(asset.id),
    }


def _clean_filename(value: str | None) -> str:
    filename = (value or "upload").replace("\\", "/").rsplit("/", 1)[-1].strip()
    filename = "".join(character for character in filename if ord(character) >= 32)
    if not filename or filename in {".", ".."}:
        filename = "upload"
    return filename[:255]


def _detect_mime(header: bytes) -> str | None:
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return "image/webp"
    if len(header) >= 12 and header[4:8] == b"ftyp":
        return "video/mp4"
    if len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE":
        return "audio/wav"
    if header.startswith(b"ID3") or (
        len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
    ):
        return "audio/mpeg"
    return None


def _validate_dimensions(width: int, height: int) -> None:
    if (
        width <= 0
        or height <= 0
        or width > _MAX_EDGE
        or height > _MAX_EDGE
        or width * height > _MAX_PIXELS
    ):
        raise CreativeInputAssetValidationError(
            "이미지 또는 영상 해상도가 허용 범위를 벗어났어요"
        )


def _validate_image(path: Path, mime_type: str) -> tuple[int, int, dict[str, Any]]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            expected_format = {
                "image/png": "PNG",
                "image/jpeg": "JPEG",
                "image/webp": "WEBP",
            }[mime_type]
            if image.format != expected_format:
                raise CreativeInputAssetValidationError(
                    "파일 내용과 MIME 형식이 달라요"
                )
            width, height = image.size
            mode = str(image.mode)
            image.verify()
    except CreativeInputAssetValidationError:
        raise
    except Exception as exc:
        raise CreativeInputAssetValidationError(
            "올바른 이미지 파일이 아니에요"
        ) from exc
    _validate_dimensions(width, height)
    return width, height, {"format": expected_format, "mode": mode}


def _duration_ms(value: Any) -> int:
    try:
        duration = round(float(value) * 1000)
    except (TypeError, ValueError) as exc:
        raise CreativeInputAssetValidationError(
            "미디어 길이를 확인할 수 없어요"
        ) from exc
    if duration <= 0:
        raise CreativeInputAssetValidationError("미디어 길이를 확인할 수 없어요")
    return duration


def _probe_with_ffprobe(path: Path) -> dict[str, Any]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise CreativeInputAssetValidationError(
            "미디어 메타데이터를 검증할 ffprobe가 서버에 없어요"
        )
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                (
                    "format=duration,format_name:"
                    "stream=codec_type,codec_name,width,height,sample_rate,channels,duration"
                ),
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
        payload = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise CreativeInputAssetValidationError(
            "올바른 오디오 또는 MP4 파일이 아니에요"
        ) from exc
    if not isinstance(payload, dict):
        raise CreativeInputAssetValidationError("미디어 메타데이터가 올바르지 않아요")
    return payload


def _validate_wav(path: Path) -> tuple[int, dict[str, Any]]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_rate = source.getframerate()
            frames = source.getnframes()
            sample_width = source.getsampwidth()
            if (
                channels not in {1, 2}
                or sample_width not in {1, 2, 3, 4}
                or not 8_000 <= sample_rate <= 192_000
                or frames <= 0
            ):
                raise CreativeInputAssetValidationError(
                    "WAV 채널, 샘플폭 또는 샘플레이트가 허용 범위를 벗어났어요"
                )
            duration_ms = round(frames / sample_rate * 1000)
            if not 0 < duration_ms <= _MAX_AUDIO_DURATION_MS:
                raise CreativeInputAssetValidationError(
                    "음성 파일 길이는 10분 이하여야 해요"
                )

            frame_size = channels * sample_width
            expected_payload_bytes = frames * frame_size
            frames_per_chunk = max(1, _WAV_VALIDATION_CHUNK_BYTES // frame_size)
            payload_bytes = 0
            frames_read = 0
            while True:
                chunk = source.readframes(frames_per_chunk)
                if not chunk:
                    break
                if len(chunk) % frame_size:
                    raise CreativeInputAssetValidationError(
                        "WAV 샘플 데이터가 완전한 프레임으로 구성되지 않았어요"
                    )
                payload_bytes += len(chunk)
                frames_read += len(chunk) // frame_size
            if frames_read != frames or payload_bytes != expected_payload_bytes:
                raise CreativeInputAssetValidationError(
                    "WAV 샘플 데이터가 선언된 길이와 달라요"
                )
    except (wave.Error, EOFError, OSError) as exc:
        raise CreativeInputAssetValidationError("올바른 WAV 파일이 아니에요") from exc
    return duration_ms, {
        "codec": "pcm",
        "channels": channels,
        "sample_rate": sample_rate,
        "sample_width_bytes": sample_width,
    }


def _validate_ffprobe_media(
    path: Path,
    mime_type: str,
) -> tuple[int | None, int | None, int, dict[str, Any]]:
    payload = _probe_with_ffprobe(path)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        raise CreativeInputAssetValidationError("미디어 스트림을 확인할 수 없어요")
    format_info = payload.get("format") if isinstance(payload.get("format"), dict) else {}
    if mime_type == "video/mp4":
        stream = next(
            (item for item in streams if item.get("codec_type") == "video"), None
        )
        if not isinstance(stream, dict):
            raise CreativeInputAssetValidationError("MP4에 영상 스트림이 없어요")
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        _validate_dimensions(width, height)
        duration_ms = _duration_ms(format_info.get("duration") or stream.get("duration"))
        if duration_ms > _MAX_VIDEO_DURATION_MS:
            raise CreativeInputAssetValidationError("입력 영상 길이는 30분 이하여야 해요")
        audio_stream = next(
            (item for item in streams if item.get("codec_type") == "audio"), None
        )
        metadata = {
            "format": format_info.get("format_name"),
            "video_codec": stream.get("codec_name"),
            "has_audio": audio_stream is not None,
            "audio_codec": audio_stream.get("codec_name")
            if isinstance(audio_stream, dict)
            else None,
        }
        return width, height, duration_ms, metadata

    stream = next(
        (item for item in streams if item.get("codec_type") == "audio"), None
    )
    if not isinstance(stream, dict):
        raise CreativeInputAssetValidationError("MP3에 오디오 스트림이 없어요")
    duration_ms = _duration_ms(format_info.get("duration") or stream.get("duration"))
    if duration_ms > _MAX_AUDIO_DURATION_MS:
        raise CreativeInputAssetValidationError("음성 파일 길이는 10분 이하여야 해요")
    try:
        channels = int(stream.get("channels") or 0)
        sample_rate = int(stream.get("sample_rate") or 0)
    except (TypeError, ValueError) as exc:
        raise CreativeInputAssetValidationError(
            "MP3 채널 또는 샘플레이트를 확인할 수 없어요"
        ) from exc
    if channels not in {1, 2} or not 8_000 <= sample_rate <= 192_000:
        raise CreativeInputAssetValidationError(
            "MP3 채널 또는 샘플레이트가 허용 범위를 벗어났어요"
        )
    return None, None, duration_ms, {
        "format": format_info.get("format_name"),
        "codec": stream.get("codec_name"),
        "channels": channels,
        "sample_rate": sample_rate,
    }


def _max_bytes(mime_type: str) -> int:
    global_limit = max(1, settings.CREATIVE_MAX_UPLOAD_BYTES)
    if mime_type.startswith("image/"):
        return min(global_limit, _MAX_IMAGE_BYTES)
    if mime_type.startswith("audio/"):
        return min(global_limit, _MAX_AUDIO_BYTES)
    return global_limit


async def store_input_asset(
    db: Session,
    creative_id: str,
    *,
    upload: UploadFile,
    role: str,
    created_by: int,
) -> models.CreativeInputAsset:
    if db.get(models.CreativeBrief, creative_id) is None:
        raise CreativeInputAssetNotFound("크리에이티브 브리프를 찾을 수 없어요")
    role = role.strip().lower()
    if role not in INPUT_ROLES:
        raise CreativeInputAssetValidationError("허용되지 않은 입력 자산 역할이에요")

    declared_mime = (upload.content_type or "").lower().split(";", 1)[0].strip()
    mime_type = _MIME_ALIASES.get(declared_mime)
    if mime_type is None or mime_type not in _ROLE_MIMES[role]:
        raise CreativeInputAssetValidationError(
            f"{role} 역할에 허용되지 않은 MIME 형식이에요"
        )
    filename = _clean_filename(upload.filename)
    extension = Path(filename).suffix.lower()
    canonical_extension, allowed_extensions = _MIME_EXTENSIONS[mime_type]
    if extension not in allowed_extensions:
        raise CreativeInputAssetValidationError("파일 확장자와 MIME 형식이 달라요")

    root = Path(settings.CREATIVE_ASSET_ROOT).expanduser().resolve()
    target_dir = (root / "_inputs" / creative_id).resolve()
    if root not in target_dir.parents:
        raise CreativeInputAssetValidationError("입력 자산 저장 경로가 안전하지 않아요")
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    target_dir.chmod(0o755)

    temp_path: Path | None = None
    final_path: Path | None = None
    try:
        digest = hashlib.sha256()
        size = 0
        header = b""
        max_bytes = _max_bytes(mime_type)
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=".input-upload-",
            suffix=canonical_extension,
            dir=target_dir,
            delete=False,
        ) as temporary:
            temp_path = Path(temporary.name)
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise CreativeInputAssetValidationError(
                        f"입력 파일 크기가 {max_bytes}바이트 한도를 넘었어요"
                    )
                if len(header) < 64:
                    header += chunk[: 64 - len(header)]
                digest.update(chunk)
                temporary.write(chunk)
        if size == 0:
            raise CreativeInputAssetValidationError("빈 파일은 올릴 수 없어요")
        if _detect_mime(header) != mime_type:
            raise CreativeInputAssetValidationError(
                "파일 실제 형식과 선언한 MIME이 달라요"
            )

        width: int | None = None
        height: int | None = None
        duration_ms: int | None = None
        metadata: dict[str, Any]
        if mime_type.startswith("image/"):
            width, height, metadata = _validate_image(temp_path, mime_type)
        elif mime_type == "audio/wav":
            duration_ms, metadata = _validate_wav(temp_path)
        else:
            width, height, duration_ms, metadata = _validate_ffprobe_media(
                temp_path, mime_type
            )

        final_path = target_dir / (
            f"{role}-{secrets.token_hex(16)}{canonical_extension}"
        )
        os.replace(temp_path, final_path)
        final_path.chmod(0o644)
        temp_path = None
        relative_path = final_path.relative_to(root).as_posix()
        asset = models.CreativeInputAsset(
            creative_id=creative_id,
            role=role,
            original_filename=filename,
            storage_path=relative_path,
            sha256=digest.hexdigest(),
            mime_type=mime_type,
            size_bytes=size,
            width=width,
            height=height,
            duration_ms=duration_ms,
            media_metadata_json=metadata,
            created_by=created_by,
        )
        db.add(asset)
        db.commit()
        db.refresh(asset)
        return asset
    except Exception:
        db.rollback()
        if final_path is not None and final_path.exists():
            final_path.unlink()
        raise
    finally:
        await upload.close()
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def asset_by_id(db: Session, asset_id: int) -> models.CreativeInputAsset:
    asset = db.get(models.CreativeInputAsset, asset_id)
    if asset is None:
        raise CreativeInputAssetNotFound("입력 자산을 찾을 수 없어요")
    return asset


def list_assets(db: Session, creative_id: str) -> list[models.CreativeInputAsset]:
    if db.get(models.CreativeBrief, creative_id) is None:
        raise CreativeInputAssetNotFound("크리에이티브 브리프를 찾을 수 없어요")
    return (
        db.query(models.CreativeInputAsset)
        .filter(models.CreativeInputAsset.creative_id == creative_id)
        .order_by(models.CreativeInputAsset.created_at.desc(), models.CreativeInputAsset.id.desc())
        .all()
    )


def _safe_file(asset: models.CreativeInputAsset) -> tuple[Path, str]:
    relative = PurePosixPath(asset.storage_path)
    parts = relative.parts
    if (
        relative.is_absolute()
        or len(parts) != 3
        or parts[0] != "_inputs"
        or parts[1] != asset.creative_id
        or any(
            part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part)
            for part in parts
        )
    ):
        raise CreativeInputAssetNotFound("입력 자산을 찾을 수 없어요")
    root = Path(settings.CREATIVE_ASSET_ROOT).expanduser().resolve()
    file_path = root.joinpath(*parts).resolve()
    if root not in file_path.parents or not file_path.is_file():
        raise CreativeInputAssetNotFound("입력 자산을 찾을 수 없어요")
    return file_path, "/".join(parts)


def private_response(asset: models.CreativeInputAsset) -> Response:
    file_path, internal_path = _safe_file(asset)
    mime_type = str(asset.mime_type or "").lower()
    if not _SAFE_MIME.fullmatch(mime_type):
        raise CreativeInputAssetNotFound("입력 자산을 찾을 수 없어요")
    headers = {
        "ETag": f'"{asset.sha256}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store, max-age=0",
    }
    if settings.APP_ENV.strip().lower() != "production":
        return FileResponse(
            path=file_path,
            media_type=mime_type,
            filename=f"creative-input-{asset.id}{file_path.suffix}",
            content_disposition_type="inline",
            headers=headers,
        )
    headers.update(
        {
            "X-Accel-Redirect": f"/_creative_assets_internal/{internal_path}",
            "Content-Type": mime_type,
            "Content-Disposition": (
                f'inline; filename="creative-input-{asset.id}{file_path.suffix}"'
            ),
        }
    )
    return Response(status_code=200, headers=headers)


def private_asset_id_from_url(url: str) -> int | None:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise CreativeInputAssetValidationError(
            "비공개 입력 자산 URL이 올바르지 않아요"
        ) from exc
    reserved_prefix = "/api/v1/creative-runner/inputs/"
    reserved_path = parsed.path.startswith(reserved_prefix)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        if reserved_path:
            raise CreativeInputAssetValidationError(
                "비공개 입력 자산 URL은 query, fragment, 자격증명을 포함할 수 없어요"
            )
        return None
    match = RUNNER_INPUT_PATH_RE.fullmatch(parsed.path)
    if match is None:
        if reserved_path:
            raise CreativeInputAssetValidationError(
                "비공개 입력 자산 URL이 정확한 runner 다운로드 경로가 아니에요"
            )
        return None
    if not parsed.scheme and not parsed.netloc:
        return int(match.group(1))

    expected = urlsplit(settings.PUBLIC_API_URL)
    try:
        parsed_port = parsed.port
        expected_port = expected.port
    except ValueError as exc:
        raise CreativeInputAssetValidationError(
            "비공개 입력 자산 URL의 port가 올바르지 않아요"
        ) from exc
    if (
        parsed.scheme.lower() != expected.scheme.lower()
        or (parsed.hostname or "").lower().rstrip(".")
        != (expected.hostname or "").lower().rstrip(".")
        or parsed_port != expected_port
    ):
        raise CreativeInputAssetValidationError(
            "비공개 입력 자산 URL은 설정된 API origin과 일치해야 해요"
        )
    return int(match.group(1))


def validate_manifest_asset(
    db: Session,
    creative_id: str,
    item: CreativeInputFile,
) -> str | None:
    """Validate and canonicalise a private input manifest entry.

    Legacy approved HTTPS inputs remain supported.  Any entry using this
    service's private endpoint, however, must match the DB owner, role, MIME and
    SHA exactly before a generation attempt can be queued.
    """
    asset_id = private_asset_id_from_url(item.url)
    if asset_id is None:
        return None
    asset = asset_by_id(db, asset_id)
    if asset.creative_id != creative_id:
        raise CreativeInputAssetValidationError(
            "다른 브리프의 비공개 입력 자산은 사용할 수 없어요"
        )
    if asset.role != item.role or asset.mime_type != item.mime_type:
        raise CreativeInputAssetValidationError(
            "비공개 입력 자산의 역할 또는 MIME이 원장과 달라요"
        )
    if not secrets.compare_digest(asset.sha256, item.sha256):
        raise CreativeInputAssetValidationError(
            "비공개 입력 자산의 SHA-256이 원장과 달라요"
        )
    _safe_file(asset)
    return runner_download_path(asset.id)
