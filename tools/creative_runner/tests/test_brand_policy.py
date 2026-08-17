from __future__ import annotations

import json
from dataclasses import replace

import pytest
from bideasy_creative_runner.api import ClaimedAttempt, InputAsset
from bideasy_creative_runner.brand_policy import BrandPolicy
from bideasy_creative_runner.errors import ConfigurationError, InvalidJobError


def _attempt(prompt="safe background", params=None, inputs=(), body_copy=None):
    return ClaimedAttempt(
        1,
        "cr_test",
        1,
        "gpt_image_2",
        prompt,
        params or {},
        inputs,
        None,
        None,
        "blog_hero_16_9",
        hook="나라장터 공고 옆에서",
        body_copy=(
            "확인 가능한 기준을 보여드립니다." if body_copy is None else body_copy
        ),
        cta_copy="이 공고 확인하기",
    )


def _policy_with_first_source_approved(tmp_path, runner_config):
    payload = json.loads(runner_config.brand_policy_path.read_text(encoding="utf-8"))
    payload["source_ui_assets"][0]["campaign_approved"] = True
    policy_path = tmp_path / "approved-source-policy.json"
    policy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return BrandPolicy.load(policy_path)


def test_brand_policy_rejects_prohibited_claim_and_uncomposited_ui(
    tmp_path, runner_config
):
    policy = BrandPolicy.load(runner_config.brand_policy_path)
    with pytest.raises(InvalidJobError, match="prohibited claim"):
        policy.validate_attempt(_attempt("낙찰 보장 서비스"))

    source_ui = InputAsset(
        "https://bideasy.kr/guide-assets/01-main-g2b-with-sidepanel.png",
        "bdff901a2882995afd19bf0476cb99fb1407abb1011365e9616ec787d006d765",
        "image/png",
        "source_ui",
    )
    static_attempt = replace(
        _attempt(),
        job_type="marketing_studio_image",
        brief_format="static_1_1",
        input_assets=(source_ui,),
    )
    with pytest.raises(InvalidJobError, match="composited after generation"):
        policy.validate_attempt(static_attempt)

    _policy_with_first_source_approved(tmp_path, runner_config).validate_attempt(
        replace(static_attempt, params={"composite_source_ui": True})
    )

    with pytest.raises(InvalidJobError, match="campaign-approved"):
        policy.validate_attempt(
            replace(static_attempt, params={"composite_source_ui": True})
        )


@pytest.mark.parametrize(
    "copy",
    [
        "낙찰을 보장합니다",
        "업무 시간 50% 절감",
        "투찰량 2배 증가",
        "수주율 30% 향상",
        "조달청 공식 도구",
        "안전 투찰가를 30초에 계산",
        "낙찰확률을 높입니다",
    ],
)
def test_brand_policy_rejects_claim_variants(copy, runner_config):
    policy = BrandPolicy.load(runner_config.brand_policy_path)
    with pytest.raises(InvalidJobError, match="prohibited"):
        policy.validate_attempt(_attempt(prompt=copy))

    policy.validate_attempt(
        _attempt(prompt="조달청·나라장터의 공식 또는 제휴 서비스가 아닌 민간 서비스")
    )


def test_blog_hero_is_text_free_and_rejects_source_ui(runner_config):
    policy = BrandPolicy.load(runner_config.brand_policy_path)
    policy.validate_attempt(_attempt(body_copy=""))

    source_ui = InputAsset(
        "https://bideasy.kr/guide-assets/01-main-g2b-with-sidepanel.png",
        "bdff901a2882995afd19bf0476cb99fb1407abb1011365e9616ec787d006d765",
        "image/png",
        "source_ui",
    )
    with pytest.raises(InvalidJobError, match="text-free background"):
        policy.validate_attempt(_attempt(inputs=(source_ui,)))


def test_brand_policy_requires_approved_real_voice_for_marketing_video(
    tmp_path, runner_config
):
    policy = _policy_with_first_source_approved(tmp_path, runner_config)
    source_ui = InputAsset(
        "https://bideasy.kr/guide-assets/01-main-g2b-with-sidepanel.png",
        "bdff901a2882995afd19bf0476cb99fb1407abb1011365e9616ec787d006d765",
        "image/png",
        "source_ui",
    )
    storyboard = InputAsset(
        "https://bideasy.kr/story.png", "d" * 64, "image/png", "storyboard"
    )
    video_attempt = replace(
        _attempt(),
        job_type="marketing_studio_video",
        brief_format="video_9_16",
        params={"composite_source_ui": True},
        input_assets=(source_ui, storyboard),
    )
    with pytest.raises(InvalidJobError, match="real voiceover"):
        policy.validate_attempt(video_attempt)

    voice = InputAsset(
        "https://bideasy.kr/voice.wav", "b" * 64, "audio/wav", "voiceover"
    )
    policy.validate_attempt(
        replace(
            video_attempt,
            params={"composite_source_ui": True},
            input_assets=(voice, source_ui, storyboard),
        )
    )


def test_runner_config_repr_does_not_leak_service_token(runner_config):
    config = replace(runner_config, service_token="super-secret-runner-token")
    assert "super-secret-runner-token" not in repr(config)


def test_brand_policy_verifies_canonical_logo_and_source_asset_hashes(runner_config):
    policy = BrandPolicy.load(runner_config.brand_policy_path)
    policy.verify_local_assets(runner_config.brand_asset_root)

    assert len(policy.source_ui_assets) == 5
    assert policy.source_ui_assets[0].sha256.startswith("bdff901a")
    assert all(not asset.campaign_approved for asset in policy.source_ui_assets)


@pytest.mark.parametrize("section", ["higgsfield", "visual"])
def test_malformed_brand_policy_section_fails_as_configuration_error(
    tmp_path, runner_config, section
):
    payload = json.loads(runner_config.brand_policy_path.read_text(encoding="utf-8"))
    payload[section] = ["not", "an", "object"]
    policy_path = tmp_path / "brand-policy.json"
    policy_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(ConfigurationError):
        BrandPolicy.load(policy_path)
