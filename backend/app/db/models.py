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
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
