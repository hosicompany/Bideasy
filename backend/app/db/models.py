from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime, timezone
from app.db.base import Base


def _utcnow():
    return datetime.now(timezone.utc)


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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    order_id = Column(String(64), unique=True, index=True, nullable=False)
    amount = Column(Integer, nullable=False)
    status = Column(String(20), default="PENDING")  # PENDING/CONFIRMED/FAILED
    payment_key = Column(String(200), unique=True, nullable=True)
    method = Column(String(50), nullable=True)
    point_transaction_id = Column(Integer, ForeignKey("point_transactions.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    confirmed_at = Column(DateTime, nullable=True)
    fail_reason = Column(String(500), nullable=True)

    user = relationship("User")


class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    bid_no = Column(String(100), ForeignKey("notices.bid_no"), nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    notice = relationship("Notice", back_populates="favorites")
