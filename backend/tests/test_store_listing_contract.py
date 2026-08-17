"""Chrome Web Store 정본의 개인정보·활성화 고지 회귀 계약."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
STORE_LISTING = ROOT / "docs" / "STORE_LISTING.md"
HOME_PAGE = ROOT / "infra" / "nginx" / "html" / "index.html"
DIAGNOSE_PAGE = ROOT / "infra" / "nginx" / "html" / "diagnose.html"
CALCULATOR_PAGE = ROOT / "infra" / "nginx" / "html" / "calculator.html"
SIGNUP_PAGE = ROOT / "infra" / "nginx" / "html" / "signup.html"
LOGIN_PAGE = ROOT / "infra" / "nginx" / "html" / "login.html"
MESSAGE_ENDPOINT = ROOT / "backend" / "app" / "api" / "v1" / "endpoints" / "message_validation.py"
EMAIL_TEMPLATES = ROOT / "backend" / "app" / "services" / "email_templates.py"
CONTENT_ENGINE = ROOT / "backend" / "app" / "services" / "content_engine.py"
DATA_STORY = ROOT / "backend" / "app" / "services" / "data_story.py"


def test_store_listing_discloses_notice_activation_data_boundary():
    listing = STORE_LISTING.read_text(encoding="utf-8")

    for required in (
        "공개 공고번호",
        "확인 시각",
        "서비스 활성화",
        "동일 사용자",
        "동일 공고",
        "방문 페이지 URL",
        "공고명",
        "회사 프로필",
    ):
        assert required in listing, f"Web Store 활성화 데이터 고지 누락: {required}"

    assert "Privacy practices 제출 고지" in listing
    assert "기존 설치 사용자에게 데이터 처리 변경 사항" in listing


def test_acquisition_pages_keep_approved_message_hierarchy_and_claim_guardrails():
    home = HOME_PAGE.read_text(encoding="utf-8")
    diagnose = DIAGNOSE_PAGE.read_text(encoding="utf-8")
    calculator = CALCULATOR_PAGE.read_text(encoding="utf-8")
    signup = SIGNUP_PAGE.read_text(encoding="utf-8")
    message_endpoint = MESSAGE_ENDPOINT.read_text(encoding="utf-8")

    for required in (
        "나라장터 공고 옆에서,",
        "자격·A값·하한선",
        "낙찰가는 예측하지 않습니다.",
        "투찰 전 마지막 확인, BidEasy.",
        "조달청·나라장터의 공식 또는 제휴 서비스가 아닌 민간 서비스입니다.",
    ):
        assert required in home, f"홈페이지 승인 메시지 누락: {required}"

    for required in (
        "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        "이 공고, 우리 회사가 진짜 넣어도 될까요?",
        "투찰 전 마지막 확인, BidEasy.",
    ):
        assert required in message_endpoint, f"메시지 테스트 승인 카피 누락: {required}"

    for banned in (
        "낙찰 보장",
        "적중률",
        "100% 자격 판정",
        "실격 방지",
        "무효·적자 0",
        "안전 투찰가",
        "30초",
    ):
        assert banned not in home, f"홈페이지 금지·미입증 주장 재유입: {banned}"
        assert banned not in diagnose, f"무료 진단 금지·미입증 주장 재유입: {banned}"
        assert banned not in calculator, f"계산기 금지·미입증 주장 재유입: {banned}"
        assert banned not in signup, f"가입 화면 금지·미입증 주장 재유입: {banned}"


def test_campaign_generators_do_not_reintroduce_removed_performance_claims():
    generated_copy_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (EMAIL_TEMPLATES, CONTENT_ENGINE, DATA_STORY)
    )

    for removed_claim in (
        "무효·적자 없는 안전 투찰가",
        "무효·적자 입찰을 막는 데 집중",
        "넣기 전에 30초만 확인",
        "30초면 됩니다",
    ):
        assert removed_claim not in generated_copy_sources


def test_social_entry_pages_forward_first_touch_without_referrer():
    for page in (SIGNUP_PAGE, LOGIN_PAGE):
        source = page.read_text(encoding="utf-8")
        for field in (
            "signup_source",
            "signup_medium",
            "signup_campaign",
            "signup_content",
            "signup_creative_id",
        ):
            assert field in source, f"소셜 가입 first-touch 누락: {page.name} {field}"
        assert "signup_referrer" not in source[source.index("async function social"):]
