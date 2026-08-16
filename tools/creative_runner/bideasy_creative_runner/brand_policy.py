"""Local, reviewable creative policy; remote-extracted brand data is never authoritative."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .api import ClaimedAttempt
from .config import PINNED_HIGGSFIELD_VERSION
from .errors import ConfigurationError, InvalidJobError

_PROHIBITED_CLAIM_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"낙찰\s*(?:을|를|이|가)?\s*보장",
        r"(?:100\s*%\s*자격|자격\s*100\s*%)\s*(?:판정|확인)",
        r"실격\s*(?:을|를)?\s*(?:방지|예방)",
        r"(?:무효|적자).{0,10}(?:0|제로|없음)",
        r"(?:시간|업무\s*시간).{0,16}\d+(?:\.\d+)?\s*(?:%|배)?\s*(?:절감|단축)",
        r"투찰량.{0,16}\d+(?:\.\d+)?\s*(?:%|배)\s*(?:증가|향상)",
        r"수주(?:율|량|건수)?.{0,16}\d+(?:\.\d+)?\s*(?:%|배)\s*(?:증가|향상)",
        r"(?:조달청|나라장터).{0,20}(?:공식|제휴|인증|파트너)(?![^.\n]{0,20}(?:아닌|아닙니다|아님))",
    )
)


@dataclass(frozen=True)
class BrandAsset:
    path: str
    sha256: str
    mime_type: str
    label: str
    campaign_approved: bool


@dataclass(frozen=True)
class BrandPolicy:
    path: Path
    prohibited_claims: tuple[str, ...]
    production_rules: dict[str, Any]
    colors: dict[str, str]
    endline: str
    video_non_prediction_line: str
    disclaimer: str
    source_ui_assets: tuple[BrandAsset, ...]
    logo_hashes: dict[str, str]
    logo_paths: dict[str, str]

    @classmethod
    def load(cls, path: Path) -> BrandPolicy:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(
                f"could not read creative brand policy: {path}"
            ) from exc
        if not isinstance(payload, dict):
            raise ConfigurationError("creative brand policy must be a JSON object")
        higgsfield = payload.get("higgsfield")
        if not isinstance(higgsfield, dict):
            raise ConfigurationError("creative brand policy is missing Higgsfield data")
        remote_version = higgsfield.get("cli_version")
        if remote_version != PINNED_HIGGSFIELD_VERSION:
            raise ConfigurationError(
                "creative brand policy CLI version does not match the pinned runner"
            )
        rules = payload.get("production_rules")
        if not isinstance(rules, dict):
            raise ConfigurationError(
                "creative brand policy is missing production_rules"
            )
        required_rules = {
            "generated_background_only": True,
            "composite_real_ui_after_generation": True,
            "generate_korean_ui_text": False,
            "generate_notice_numbers_or_money": False,
            "representative_real_voice_only": True,
            "tts": False,
            "human_review_required": True,
        }
        if any(rules.get(key) is not value for key, value in required_rules.items()):
            raise ConfigurationError(
                "creative brand policy weakens a required production rule"
            )
        claims = payload.get("prohibited_claims")
        if not isinstance(claims, list) or not all(
            isinstance(item, str) and item.strip() for item in claims
        ):
            raise ConfigurationError(
                "creative brand policy must contain prohibited_claims"
            )
        visual = payload.get("visual")
        if not isinstance(visual, dict):
            raise ConfigurationError("creative brand policy is missing visual data")
        colors = visual.get("colors")
        required_colors = {"surface", "ink", "muted", "accent"}
        if not isinstance(colors, dict) or not required_colors.issubset(colors):
            raise ConfigurationError(
                "creative brand policy is missing required visual colors"
            )
        if any(
            not isinstance(colors[key], str)
            or not re.fullmatch(r"#[0-9a-fA-F]{6}", colors[key])
            for key in required_colors
        ):
            raise ConfigurationError(
                "creative brand policy contains an invalid visual color"
            )
        message = payload.get("message")
        brand = payload.get("brand")
        if not isinstance(message, dict) or not isinstance(brand, dict):
            raise ConfigurationError(
                "creative brand policy is missing message or brand data"
            )
        endline = message.get("endline")
        non_prediction = message.get("video_non_prediction_line")
        disclaimer = brand.get("official_relationship_disclaimer")
        if not all(
            isinstance(item, str) and item.strip()
            for item in (endline, non_prediction, disclaimer)
        ):
            raise ConfigurationError(
                "creative brand policy is missing approved copy lines"
            )

        source_assets_payload = payload.get("source_ui_assets")
        if not isinstance(source_assets_payload, list) or not source_assets_payload:
            raise ConfigurationError(
                "creative brand policy is missing source_ui_assets"
            )
        source_assets: list[BrandAsset] = []
        for item in source_assets_payload:
            if not isinstance(item, dict):
                raise ConfigurationError(
                    "creative source UI manifest entry must be an object"
                )
            try:
                asset = BrandAsset(
                    path=str(item["path"]),
                    sha256=str(item["sha256"]).lower(),
                    mime_type=str(item["mime_type"]).lower(),
                    label=str(item["label"]),
                    campaign_approved=item.get("campaign_approved", False),
                )
            except KeyError as exc:
                raise ConfigurationError(
                    f"creative source UI manifest is missing {exc.args[0]}"
                ) from exc
            if (
                not asset.path.startswith("/")
                or ".." in Path(asset.path).parts
                or not re.fullmatch(r"[0-9a-f]{64}", asset.sha256)
                or asset.mime_type != "image/png"
                or not asset.label.strip()
                or not isinstance(asset.campaign_approved, bool)
            ):
                raise ConfigurationError("creative source UI manifest entry is invalid")
            source_assets.append(asset)

        logos = brand.get("logos")
        logo_hashes = brand.get("logo_sha256")
        if (
            not isinstance(logos, dict)
            or not isinstance(logo_hashes, dict)
            or set(logos) != set(logo_hashes)
            or any(
                not isinstance(path_value, str)
                or not path_value.startswith("/")
                or not isinstance(logo_hashes[key], str)
                or not re.fullmatch(r"[0-9a-f]{64}", logo_hashes[key])
                for key, path_value in logos.items()
            )
        ):
            raise ConfigurationError("creative brand logo paths or hashes are invalid")
        return cls(
            path=path,
            prohibited_claims=tuple(item.strip() for item in claims),
            production_rules=rules,
            colors={key: str(value) for key, value in colors.items()},
            endline=endline.strip(),
            video_non_prediction_line=non_prediction.strip(),
            disclaimer=disclaimer.strip(),
            source_ui_assets=tuple(source_assets),
            logo_hashes={str(key): str(value) for key, value in logo_hashes.items()},
            logo_paths={str(key): str(value) for key, value in logos.items()},
        )

    def verify_local_assets(self, asset_root: Path) -> None:
        root = asset_root.expanduser().resolve()
        expected = [(asset.path, asset.sha256) for asset in self.source_ui_assets]
        expected.extend(
            (self.logo_paths[key], digest) for key, digest in self.logo_hashes.items()
        )
        for public_path, digest in expected:
            local_path = (root / public_path.lstrip("/")).resolve()
            if root not in local_path.parents or not local_path.is_file():
                raise ConfigurationError(
                    f"approved brand asset is missing: {public_path}"
                )
            hasher = hashlib.sha256()
            try:
                with local_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        hasher.update(chunk)
            except OSError as exc:
                raise ConfigurationError(
                    f"approved brand asset could not be read: {public_path}"
                ) from exc
            if hasher.hexdigest() != digest:
                raise ConfigurationError(
                    f"approved brand asset hash changed: {public_path}"
                )

    def validate_attempt(self, attempt: ClaimedAttempt) -> None:
        copy_fields = {
            "hook": attempt.hook,
            "body_copy": attempt.body_copy,
            "cta_copy": attempt.cta_copy,
        }
        limits = {"hook": 500, "body_copy": 10_000, "cta_copy": 200}
        for label, value in copy_fields.items():
            if len(value) > limits[label] or "\x00" in value:
                raise InvalidJobError(f"{label} must contain approved bounded copy")
        copy_jobs = {"marketing_studio_image", "marketing_studio_video"}
        if attempt.job_type in copy_jobs and any(
            not value.strip() for value in copy_fields.values()
        ):
            raise InvalidJobError(
                "static and marketing video creatives require approved hook, body, and CTA copy"
            )
        all_text = "\n".join((attempt.prompt, *copy_fields.values()))
        for claim in self.prohibited_claims:
            if claim in all_text:
                raise InvalidJobError(f"brief contains prohibited claim: {claim}")
        if any(pattern.search(all_text) for pattern in _PROHIBITED_CLAIM_PATTERNS):
            raise InvalidJobError(
                "brief contains a prohibited performance or official-relationship claim"
            )

        source_ui = [item for item in attempt.input_assets if item.role == "source_ui"]
        has_source_ui = bool(source_ui)
        composited_jobs = {"marketing_studio_image", "marketing_studio_video"}
        if attempt.job_type == "gpt_image_2":
            if attempt.brief_format != "blog_hero_16_9":
                raise InvalidJobError(
                    "gpt_image_2 is reserved for the text-free blog hero"
                )
            if has_source_ui or attempt.params.get("composite_source_ui") is True:
                raise InvalidJobError(
                    "blog hero generation must remain a text-free background without source_ui"
                )
        if attempt.job_type in composited_jobs:
            if len(source_ui) != 1:
                raise InvalidJobError(
                    "generated creatives require exactly one real source_ui input"
                )
            composite = attempt.params.get(
                "composite_source_ui", attempt.params.get("composite-source-ui")
            )
            if composite is not True:
                raise InvalidJobError(
                    "source_ui must be composited after generation, never sent through the model"
                )
            approved_source_hashes = {
                asset.sha256
                for asset in self.source_ui_assets
                if asset.campaign_approved
            }
            if source_ui[0].sha256 not in approved_source_hashes:
                raise InvalidJobError(
                    "source_ui is not campaign-approved in the local brand manifest"
                )
        if (
            attempt.job_type == "marketing_studio_image"
            and attempt.brief_format
            not in {
                "static_4_5",
                "static_1_1",
            }
        ):
            raise InvalidJobError(
                "marketing_studio_image requires static_4_5 or static_1_1 format"
            )
        if (
            attempt.job_type == "marketing_studio_image"
            and has_source_ui
            and not source_ui[0].mime_type.startswith("image/")
        ):
            raise InvalidJobError(
                "generated image creatives require an image source_ui input"
            )
        if attempt.job_type == "marketing_studio_video":
            if attempt.brief_format != "video_9_16":
                raise InvalidJobError(
                    "marketing_studio_video requires the approved video_9_16 format"
                )
            voiceovers = [
                item for item in attempt.input_assets if item.role == "voiceover"
            ]
            if len(voiceovers) != 1 or not voiceovers[0].mime_type.startswith("audio/"):
                raise InvalidJobError(
                    "marketing_studio_video requires exactly one approved real voiceover input"
                )
            storyboards = [
                item
                for item in attempt.input_assets
                if item.role == "storyboard" and item.mime_type.startswith("image/")
            ]
            if len(storyboards) != 1:
                raise InvalidJobError(
                    "marketing_studio_video requires exactly one approved storyboard image"
                )
        if (
            attempt.job_type == "reframe"
            and attempt.params.get("composite_source_ui") is True
        ):
            raise InvalidJobError(
                "reframe operates on the already-composited source and must not overlay source_ui again"
            )
