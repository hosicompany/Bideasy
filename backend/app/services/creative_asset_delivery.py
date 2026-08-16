"""Visibility checks and nginx-accelerated delivery for creative outputs.

The runner writes every output into one shared volume, but possession of its
versioned path is not an approval signal.  Public URLs therefore pass through a
database state check.  Admin and runner download endpoints use the same helper
after their own authentication dependencies have succeeded.
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath

from fastapi import Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db import models


PUBLIC_OUTPUT_KINDS = frozenset({"final_png", "webp", "mp4", "poster", "thumbnail"})
PUBLIC_STATUSES = frozenset({"APPROVED", "PUBLISHED"})

_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_MIME = re.compile(r"^[a-z0-9.+-]+/[a-z0-9.+-]+$")


class CreativeAssetNotFound(Exception):
    """The requested output does not exist or is not currently visible."""


def output_by_id(db: Session, output_id: int) -> models.CreativeOutput:
    output = db.get(models.CreativeOutput, output_id)
    if output is None:
        raise CreativeAssetNotFound
    return output


def public_output_by_path(db: Session, storage_path: str) -> models.CreativeOutput:
    """Return an output only when its exact attempt and brief are approved.

    Raw provider output and operational reports are deliberately never exposed
    through the public immutable URL.  They remain available to authenticated
    admins/runners for review.
    """
    output = (
        db.query(models.CreativeOutput)
        .join(models.CreativeAttempt, models.CreativeOutput.attempt_id == models.CreativeAttempt.id)
        .join(models.CreativeBrief, models.CreativeAttempt.creative_id == models.CreativeBrief.id)
        .filter(
            models.CreativeOutput.storage_path == storage_path,
            models.CreativeOutput.kind.in_(PUBLIC_OUTPUT_KINDS),
            models.CreativeAttempt.status.in_(PUBLIC_STATUSES),
            models.CreativeBrief.status.in_(PUBLIC_STATUSES),
        )
        .first()
    )
    if output is None:
        # A 404 avoids disclosing whether an unapproved version exists.
        raise CreativeAssetNotFound
    return output


def _safe_file(output: models.CreativeOutput) -> tuple[Path, str]:
    relative = PurePosixPath(output.storage_path)
    parts = relative.parts
    if (
        relative.is_absolute()
        or len(parts) != 3
        or any(part in {"", ".", ".."} or not _SAFE_SEGMENT.fullmatch(part) for part in parts)
    ):
        raise CreativeAssetNotFound

    root = Path(settings.CREATIVE_ASSET_ROOT).expanduser().resolve()
    file_path = root.joinpath(*parts).resolve()
    if root not in file_path.parents or not file_path.is_file():
        raise CreativeAssetNotFound
    return file_path, "/".join(parts)


def accelerated_response(
    output: models.CreativeOutput,
    *,
    public: bool,
) -> Response:
    """Serve locally in development or hand production delivery to nginx."""
    file_path, internal_path = _safe_file(output)
    mime_type = str(output.mime_type or "").lower()
    if not _SAFE_MIME.fullmatch(mime_type):
        raise CreativeAssetNotFound

    headers = {
        "ETag": f'"{output.sha256}"',
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": (
            # APPROVED/PUBLISHED can later become CHANGES_REQUESTED/STALE.
            # Revalidation makes that revocation effective instead of leaving a
            # year-long immutable copy addressable in browser/CDN caches.
            "public, max-age=0, must-revalidate"
            if public
            else "private, no-store, max-age=0"
        ),
    }
    # Local development normally runs uvicorn without nginx.  Returning a real
    # FileResponse keeps the authenticated admin preview usable while applying
    # the exact same DB visibility and path-containment checks.
    if settings.APP_ENV.strip().lower() != "production":
        return FileResponse(
            path=file_path,
            media_type=mime_type,
            filename=file_path.name,
            content_disposition_type="inline",
            headers=headers,
        )

    headers.update(
        {
            "X-Accel-Redirect": f"/_creative_assets_internal/{internal_path}",
            "Content-Type": mime_type,
            "Content-Disposition": f'inline; filename="{file_path.name}"',
        }
    )
    return Response(status_code=200, headers=headers)
