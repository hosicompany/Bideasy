from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.types import TypeDecorator
from datetime import datetime, timezone
from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


class EncryptedString(TypeDecorator):
    """빌링키 등 민감 문자열의 투명 at-rest 암호화 컬럼 타입.

    BILLING_ENC_KEY 설정 시에만 암호화하고, 미설정/레거시 평문은 그대로 통과.
    호출부는 평문처럼 읽고 쓰면 된다(암복호화는 이 레이어에서 처리).
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from app.core.crypto import encrypt_secret
        return encrypt_secret(value)

    def process_result_value(self, value, dialect):
        from app.core.crypto import decrypt_secret
        return decrypt_secret(value)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    hashed_password = Column(String(255), nullable=True)
    company_name = Column(String(255), default="")
    ceo_name = Column(String(100))

    # Social auth
    social_provider = Column(String(20), nullable=True)  # 'kakao' | 'naver'
    social_id = Column(String(100), nullable=True, index=True)
    profile_image_url = Column(String(500), nullable=True)

    # My Page Fields
    licenses = Column(Text)
    location = Column(String(100))
    capacity_cost = Column(Integer, default=0)
    performance_record = Column(Integer, default=0)

    points = Column(Integer, default=0)

    # Subscription
    tier = Column(String(20), default="free")  # free | pro | pro_plus
    subscription_expires_at = Column(DateTime, nullable=True)

    # 14일 Pro 체험 (신규 가입 시 자동 활성화, 만료 후 Free 다운그레이드)
    # trial_started_at != None 이면 이미 체험을 시작한 적이 있는 사용자 (재체험 불가)
    trial_started_at = Column(DateTime, nullable=True)
    trial_expires_at = Column(DateTime, nullable=True)

    # 관리자 권한 (require_admin 의존성에서 검사)
    is_admin = Column(Boolean, nullable=False, default=False, server_default="false")

    # 토큰 무효화용 버전. 비밀번호 변경·로그아웃·강제 로그아웃 시 +1 하면
    # 발급된 기존 JWT(tv 클레임이 옛 값)가 전부 즉시 무효화된다.
    token_version = Column(Integer, nullable=False, default=0, server_default="0")

    # === 자동결제(빌링) ===
    # 토스 빌링키 — 카드 등록(requestBillingAuth) 후 발급, 영구 보관하며 매 주기 자동청구에 사용.
    # at-rest 암호화(EncryptedString): BILLING_ENC_KEY 설정 시 암호문 저장(길이 여유 위해 500).
    billing_key = Column(EncryptedString(500), nullable=True)
    # 빌링키 발급 시 사용한 customerKey — 청구 시 동일 값 필요 (사용자당 1개 재사용)
    billing_customer_key = Column(EncryptedString(500), nullable=True)
    # 표시용 마스킹 카드정보 (예: "신한 ****1234") — 보안상 원본 카드번호 미보관
    billing_card = Column(String(80), nullable=True)
    # 자동 갱신 주기 (monthly | annual)
    billing_cycle = Column(String(20), nullable=True)
    # 자동 갱신 on/off — 해지 시 false (구독은 만료일까지 유지)
    auto_renew = Column(Boolean, nullable=False, default=False, server_default="false")
    # 빌링키 발급 PG (toss | payple) — 자동청구 시 어느 PG API 를 쓸지 구분
    billing_provider = Column(String(20), nullable=True)

    # === 유입 귀속(attribution) — 가입 시점 first-touch 채널 ===
    # UTM(utm_source/medium/campaign) + 최초 유입 referrer. "어느 채널이 가입·결제를
    # 데려오나"를 우리 데이터로 직접 집계(외부 분석도구·쿠키 불요). 프론트 first-touch 캡처.
    signup_source = Column(String(120), nullable=True)
    signup_medium = Column(String(120), nullable=True)
    signup_campaign = Column(String(160), nullable=True)
    signup_referrer = Column(String(300), nullable=True)

    # === 광고성 정보 수신동의 (선택) ===
    # 체험 시퀀스·신규 공고 알림 등 아웃바운드 발송의 전제. 거래 관련 안내(결제·영수증·
    # 체험 만료 고지)는 광고가 아니므로 이 동의와 무관하게 발송한다. 발송 판정은
    # services/consent.py can_send_marketing/sendable_filter 만 사용(2년 재확인 포함).
    marketing_consent = Column(Boolean, nullable=False, default=False, server_default="false")
    marketing_consent_at = Column(DateTime, nullable=True)
    marketing_withdrawn_at = Column(DateTime, nullable=True)
    marketing_confirmed_at = Column(DateTime, nullable=True)
    consent_text_version = Column(String(30), nullable=True)
    consent_ip = Column(String(45), nullable=True)
    consent_user_agent = Column(String(300), nullable=True)

    bids = relationship("UserBid", back_populates="user")
    point_transactions = relationship("PointTransaction", back_populates="user")


class Notice(Base):
    __tablename__ = "notices"

    bid_no = Column(String(100), primary_key=True, index=True)
    title = Column(String(500), index=True)
    content = Column(Text)
    basic_price = Column(Float)
    contract_type = Column(String(50), default="CONSTRUCTION")
    start_date = Column(DateTime)
    end_date = Column(DateTime)

    # Extended fields
    organization = Column(String(255))
    demand_organization = Column(String(255))
    bid_method = Column(String(100))
    contract_method = Column(String(100))
    bid_type = Column(String(100))
    status = Column(String(50))
    region = Column(String(100))
    budget_amount = Column(Float)
    opening_date = Column(String(100))
    international_bid = Column(String(10))
    joint_contract = Column(String(10))
    sme_only = Column(String(10))
    big_company_ok = Column(String(10))
    bid_qualification = Column(String(255))
    emergency_bid = Column(String(10))
    rebid_yn = Column(String(10))
    attachment_url = Column(String(500))
    attachment_name = Column(String(255))

    # Calculator Fields
    a_value = Column(Integer, default=0)
    net_cost = Column(Integer, default=0)

    # Relationships
    bids = relationship("UserBid", back_populates="notice")
    ai_log = relationship("AIAnalysisLog", back_populates="notice", uselist=False)
    favorites = relationship("Favorite", back_populates="notice")

    def to_dict(self):
        return {
            "bid_no": self.bid_no,
            "title": self.title,
            "content": self.content,
            "basic_price": self.basic_price,
            "contract_type": self.contract_type,
            "start_date": self.start_date.isoformat() if self.start_date else None,
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "organization": self.organization,
            "demand_organization": self.demand_organization,
            "bid_method": self.bid_method,
            "contract_method": self.contract_method,
            "bid_type": self.bid_type,
            "status": self.status,
            "region": self.region,
            "budget_amount": self.budget_amount,
            "opening_date": self.opening_date,
            "international_bid": self.international_bid,
            "joint_contract": self.joint_contract,
            "sme_only": self.sme_only,
            "big_company_ok": self.big_company_ok,
            "bid_qualification": self.bid_qualification,
            "emergency_bid": self.emergency_bid,
            "rebid_yn": self.rebid_yn,
            "attachment_url": self.attachment_url,
            "attachment_name": self.attachment_name,
            "a_value": self.a_value,
            "net_cost": self.net_cost,
        }


class UserBid(Base):
    __tablename__ = "user_bids"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    notice_id = Column(String(100), ForeignKey("notices.bid_no"))

    bid_price = Column(Integer)
    rate = Column(Float)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="bids")
    notice = relationship("Notice", back_populates="bids")


class OpeningResult(Base):
    __tablename__ = "opening_results"

    bid_no = Column(String(100), primary_key=True, index=True)

    organization = Column(String(255), index=True)
    region = Column(String(100), index=True)

    open_date = Column(DateTime, index=True)
    basic_price = Column(Float)
    reserved_price = Column(Float)
    bid_method = Column(String(100))

    winner_company = Column(String(255))
    winner_price = Column(Float)
    winner_rate = Column(Float)

    participants_count = Column(Integer)

    crawled_at = Column(DateTime, default=_utcnow)


class AIAnalysisLog(Base):
    __tablename__ = "ai_analysis_logs"

    bid_no = Column(String(100), ForeignKey("notices.bid_no"), primary_key=True)
    summary_json = Column(JSON)
    risk_factors = Column(JSON)
    llm_model = Column(String(50), default="gpt-4o-mini")
    token_usage = Column(Integer)
    created_at = Column(DateTime, default=_utcnow)

    notice = relationship("Notice", back_populates="ai_log")


class PointTransaction(Base):
    __tablename__ = "point_transactions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    amount = Column(Integer, nullable=False)
    balance_after = Column(Integer, nullable=False)
    tx_type = Column(String(50), nullable=False)
    description = Column(String(255))
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User", back_populates="point_transactions")


class PaymentOrder(Base):
    __tablename__ = "payment_orders"

    id = Column(Integer, primary_key=True, index=True)
    # user_id nullable=True — SET NULL 정책 (사용자 삭제 시 회계 기록 보존)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), default="PENDING", index=True)  # PENDING/CONFIRMED/FAILED
    payment_key = Column(String(200), unique=True, nullable=True)
    method = Column(String(50), nullable=True)
    point_transaction_id = Column(Integer, ForeignKey("point_transactions.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    confirmed_at = Column(DateTime, nullable=True, index=True)
    fail_reason = Column(String(500), nullable=True)

    # 환불 추적 (관리자 환불 처리 시)
    refund_amount = Column(Integer, nullable=True)  # 부분 환불 누적 합
    refund_reason = Column(String(500), nullable=True)
    refunded_at = Column(DateTime, nullable=True)  # idempotency 검사 키
    refund_payment_key = Column(String(200), nullable=True)  # Toss 환불 응답

    # 캠페인 할인 (예: 첫 달 50% 자동 win-back)
    # amount + discount_amount = 정가. discount_reason 으로 효과 분석.
    discount_amount = Column(Integer, nullable=True)
    discount_reason = Column(String(50), nullable=True)  # 예: TRIAL_WINBACK_50

    user = relationship("User")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    # user_id: 멀티유저 관심목록 분리. 기존 행(공유 버그 시절)은 NULL → 어떤 사용자
    # 조회에도 안 잡힘. nullable=True 로 무중단 마이그레이션.
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    notice = relationship("Notice", back_populates="favorites")
    user = relationship("User")


class BidTrack(Base):
    """마감 추적 — 사용자가 추적하는 공고. remind=True 면 마감 리마인더 발송."""
    __tablename__ = "bid_tracks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=False)
    remind = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")
    notice = relationship("Notice")


class DeviceToken(Base):
    __tablename__ = "device_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    fcm_token = Column(String(500), nullable=False, index=True)
    device_type = Column(String(20), nullable=False)  # android | ios | web
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    user = relationship("User")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    title = Column(String(255), nullable=False)
    body = Column(String(1000), nullable=False)
    noti_type = Column(String(50), nullable=False)  # new_bid | favorite_update | subscription_expiry
    data_json = Column(JSON, nullable=True)  # extra payload (bid_no, etc.)
    is_read = Column(Integer, default=0)  # 0=unread, 1=read
    created_at = Column(DateTime, default=_utcnow)

    user = relationship("User")


class SupportMessage(Base):
    """고객 챗봇 대화 로그 — 자가학습(질문 군집·FAQ 마이닝)의 데이터 소스.

    session_id 로 한 대화를 묶음. role=user/assistant. 비로그인도 기록(user_id NULL).
    """
    __tablename__ = "support_messages"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String(64), index=True, nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    role = Column(String(16), nullable=False)  # user | assistant
    content = Column(Text, nullable=False)
    # 자가학습용 — 군집 라벨/해결여부 등 후속 단계에서 채움
    resolved = Column(Boolean, nullable=True)
    topic = Column(String(80), nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)

    user = relationship("User")


class SupportTicket(Base):
    """고객 문의 접수 — 챗봇이 못 풀었거나 '상담원 연결' 요청한 건."""
    __tablename__ = "support_tickets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    email = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    session_id = Column(String(64), nullable=True)
    status = Column(String(20), default="open", index=True)  # open | closed
    created_at = Column(DateTime, default=_utcnow, index=True)

    user = relationship("User")


class BlogPost(Base):
    """DB 기반 블로그 글 — 런타임 발행(배포 0)용.

    마크다운 파일 블로그(content/blog/*.md)와 **하이브리드**: 손으로 쓰는 상록수
    가이드는 파일(git), 자동 데이터스토리·관리자 즉석글은 이 테이블. 읽는 경로는
    services/blog.py 에서 하나로 병합(slug 중복 시 파일 우선). 필드는 마크다운
    post dict 와 동형 — 템플릿/sitemap 무변경. author 는 저장 안 하고 읽을 때
    BLOG_AUTHOR 주입.

    status=draft 는 목록·sitemap 제외(직접 URL 은 noindex 미리보기). 발행=published.
    source=auto 는 Track B 자동초안, admin 은 수동 작성.
    """
    __tablename__ = "blog_posts"

    id = Column(Integer, primary_key=True, index=True)
    slug = Column(String(200), unique=True, index=True, nullable=False)
    title = Column(String(300), nullable=False)
    summary = Column(Text, default="")
    category = Column(String(80), default="")
    tags = Column(String(300), default="")        # 콤마 구분 (마크다운과 동일)
    cover = Column(String(500), default="")
    hero = Column(String(500), default="")
    body_md = Column(Text, nullable=False, default="")     # 원본 마크다운 (편집 대상)
    body_html = Column(Text, nullable=False, default="")   # 렌더 캐시 (저장 시 생성)
    reading_time = Column(Integer, nullable=False, default=1)
    status = Column(String(20), nullable=False, default="draft", server_default="draft", index=True)  # draft | published
    source = Column(String(20), nullable=False, default="admin", server_default="admin")  # admin | auto
    date = Column(String(10), default="")          # YYYY-MM-DD 발행일 (정렬·sitemap 용, 발행 시 세팅)
    publish_at = Column(DateTime, nullable=True)   # 예약 발행(옵션)
    # 콘텐츠 엔진 Phase 1 (docs/CONTENT_ENGINE.md §2) — 구조화 정본 블록.
    # 블록이 원본, body_md 는 블록에서 렌더된 파생(채널 간 메시지 정합의 근원).
    blocks_json = Column(JSON, nullable=True)          # ContentSource 블록 (훅·요약·핵심·데이터·CTA)
    channel_assets_json = Column(JSON, nullable=True)  # 채널 파생 캐시 (Phase 2 — 카드/릴스/유튜브)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)


class Lead(Base):
    """무료 자격 진단 리드 — 비로그인 방문자가 남긴 연락처 + 진단 입력.

    리드 마그넷("우리 회사가 넣을 수 있는 공고 무료 진단")의 산출물. 두 목적을
    한 번에: ① 재접촉 가능한 리드 확보 ② 비치헤드 검증 마이크로설문(업종·지역·
    월 투찰 습관 추정). 진단은 로그인·발송 인프라 없이 동작 — QualificationChecker
    로 활성 공고를 필터해 매칭 수/샘플을 즉시 보여주고, 연락처를 남기면 이 행을 저장.

    육성(nurture)은 pluggable: nurture_channel 로 카카오 알림톡/이메일(SES) 병행.
    지금은 캡처만 라이브, 발송은 설계(docs/LEAD_ACQUISITION.md). 가입 전환 시
    converted_user_id 로 연결해 채널별 리드→유료 성과를 우리 데이터로 직접 집계.
    """
    __tablename__ = "leads"

    id = Column(Integer, primary_key=True, index=True)

    # 연락처 — email 또는 phone 중 최소 하나 (캡처 시점에 검증)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(30), nullable=True)

    # 진단 입력 = 검증 마이크로설문
    industry = Column(String(60), nullable=True)     # 업종(예: 전기공사) — 대표 면허 루트
    licenses = Column(String(255), nullable=True)    # 보유 면허(콤마 구분)
    region = Column(String(100), nullable=True)      # 사업장 소재지
    capacity_cost = Column(Integer, nullable=True)   # 시공능력평가액(선택)

    # 진단 결과 스냅샷
    matched_count = Column(Integer, nullable=False, default=0, server_default="0")

    # 유입 귀속(first-touch UTM) — users 와 동일 스키마
    utm_source = Column(String(120), nullable=True)
    utm_medium = Column(String(120), nullable=True)
    utm_campaign = Column(String(160), nullable=True)
    referrer = Column(String(300), nullable=True)

    # 육성 채널·상태 (pluggable: kakao | email | null)
    nurture_channel = Column(String(20), nullable=True)
    nurture_status = Column(String(20), nullable=False, default="new", server_default="new")  # new|queued|sent|converted|unsub

    # 전환 연결 — 가입 시 users.id (리드→유료 성과 측정)
    converted_user_id = Column(Integer, nullable=True)

    # ── 수신동의 증적 (정보통신망법 제50조 / 개인정보보호법 제22조) ──
    # 여기 컬럼은 "현재 상태"이고, 변경 이력·증명자료는 consent_records 에 append-only
    # 로 쌓인다. 발송 대상 판정은 services/consent.py 의 can_send_marketing/
    # sendable_filter 만 사용한다(2년 재확인·철회가 자동 반영됨).
    privacy_consent = Column(Boolean, nullable=False, default=False, server_default="false")
    privacy_consent_at = Column(DateTime, nullable=True)
    marketing_consent = Column(Boolean, nullable=False, default=False, server_default="false")
    marketing_consent_at = Column(DateTime, nullable=True)
    marketing_withdrawn_at = Column(DateTime, nullable=True)  # 수신거부 시각(이후 발송 금지)
    marketing_confirmed_at = Column(DateTime, nullable=True)  # 최근 동의 확인 시각(2년 주기)
    consent_text_version = Column(String(30), nullable=True)  # 동의 당시 문구 버전
    consent_ip = Column(String(45), nullable=True)            # IPv6 포함
    consent_user_agent = Column(String(300), nullable=True)

    # 유입 지점 (web_diagnose | ext_diagnose 등)
    source = Column(String(40), nullable=False, default="web_diagnose", server_default="web_diagnose")
    created_at = Column(DateTime, default=_utcnow, index=True)


class ConsentRecord(Base):
    """동의·철회 증적 로그 (append-only) — 광고성 정보 전송의 증명책임 대응.

    정보통신망법 제50조는 수신동의 사실의 증명책임을 전송자에게 지운다. Lead/User 의
    상태 컬럼은 철회·재동의로 덮어써지므로, "언제·어디서·무슨 문구에 동의했는가"는
    이 테이블에만 남는다. **어떤 경로로도 UPDATE/DELETE 하지 않는다**(대상 행이 삭제돼도
    증적은 남아야 하므로 FK 를 걸지 않고 연락처를 스냅샷으로 복사해 둔다).

    text_hash 는 동의 문구 본문의 sha256 — 나중에 문구를 고쳐도 그때 무엇에 동의했는지
    지문으로 특정된다(services/consent.py CONSENT_TEXTS 가 버전별 본문을 보존).
    """
    __tablename__ = "consent_records"

    id = Column(Integer, primary_key=True, index=True)

    # 동의 주체 — FK 없음(대상 삭제 후에도 증적 보존)
    subject_type = Column(String(10), nullable=False, index=True)  # lead | user
    subject_id = Column(Integer, nullable=True, index=True)
    email = Column(String(255), nullable=True, index=True)
    phone = Column(String(30), nullable=True)

    purpose = Column(String(20), nullable=False)   # privacy | marketing
    action = Column(String(12), nullable=False)    # grant | withdraw | reconfirm
    channel = Column(String(20), nullable=True)    # email | kakao | all

    text_version = Column(String(30), nullable=False)
    text_hash = Column(String(64), nullable=False)

    source = Column(String(40), nullable=False)    # web_diagnose | web_signup | email_unsub | admin
    ip = Column(String(45), nullable=True)
    user_agent = Column(String(300), nullable=True)
    note = Column(String(200), nullable=True)

    created_at = Column(DateTime, default=_utcnow, index=True)


class OutboundMessage(Base):
    """아웃바운드 발송 기록 — "무엇을 누구에게 언제 보냈나"의 단일 원장.

    세 가지를 동시에 해결한다:
      1) **멱등성**: `dedupe_key` 유니크 — 재시도·중복 스케줄이 같은 메일을 두 번 보내지
         않는다(사용자 체감상 스팸이자 신뢰 손실). 키 충돌은 skipped 로 남는다.
      2) **사고 추적**: 민원("왜 보냈나")이 오면 이 원장 + consent_records 로 즉시 답한다.
      3) **차단 사유 가시화**: 동의 없음·수신거부로 **보내지 않은 건도** status=skipped 로
         남긴다. 조용히 사라지면 발송 게이트가 도는지 알 수 없다.
    """
    __tablename__ = "outbound_messages"

    id = Column(Integer, primary_key=True, index=True)

    subject_type = Column(String(10), nullable=False, index=True)  # lead | user
    subject_id = Column(Integer, nullable=True, index=True)
    email = Column(String(255), nullable=True, index=True)

    channel = Column(String(20), nullable=False, default="email")   # email | kakao
    template = Column(String(60), nullable=False)                   # lead_welcome 등
    category = Column(String(20), nullable=False)                   # marketing | transactional
    subject = Column(String(200), nullable=True)                    # 발송된 제목

    status = Column(String(20), nullable=False)   # sent | dry_run | skipped | failed
    reason = Column(String(60), nullable=True)    # skipped/failed 사유 코드
    provider = Column(String(20), nullable=True)  # ses
    provider_message_id = Column(String(120), nullable=True)
    error = Column(String(300), nullable=True)

    # 멱등 키 — 예: "lead_welcome:lead:42". 같은 키는 한 번만 전송된다.
    dedupe_key = Column(String(160), nullable=True, unique=True, index=True)

    created_at = Column(DateTime, default=_utcnow, index=True)


class EmailSuppression(Base):
    """발송 금지 주소 목록 — 반송·불만 자동 억제.

    **왜 필요한가**: 하드 반송(없는 주소)에 계속 보내거나 스팸 신고(complaint)를 받은
    주소에 또 보내면, AWS 가 반송률 5%·불만율 0.1% 초과 시 **계정 발송을 정지**시킨다.
    한 번 평판이 깎이면 광고 메일뿐 아니라 결제·영수증 같은 거래 메일까지 안 들어간다.
    그래서 억제는 광고/거래를 가리지 않고 **모든 발송 경로 앞단**에서 걸린다.

    SES 계정 차원의 suppression list 와 별개로 우리 DB 에 두는 이유:
      - 왜 막혔는지(이벤트 원문 일부)를 남겨 고객 문의에 답할 수 있어야 하고,
      - 발송 판정을 외부 API 왕복 없이 로컬에서 끝내야 하며,
      - 오탐(일시 반송을 영구로 오인 등)을 사람이 해제할 수 있어야 하기 때문이다.
    """
    __tablename__ = "email_suppressions"

    id = Column(Integer, primary_key=True, index=True)
    # 소문자·trim 정규화해서 저장한다(대소문자 다른 같은 주소가 뚫리지 않도록)
    email = Column(String(255), nullable=False, unique=True, index=True)

    reason = Column(String(20), nullable=False)      # bounce | complaint | manual
    subtype = Column(String(40), nullable=True)      # Permanent/General, abuse 등 원문 분류
    source = Column(String(20), nullable=False)      # ses_sns | admin
    detail = Column(String(300), nullable=True)      # 진단 코드·피드백 요약(원문 일부)

    event_count = Column(Integer, nullable=False, default=1, server_default="1")
    last_event_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=_utcnow, index=True)
