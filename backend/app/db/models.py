from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Text
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.base import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    company_name = Column(String, default="Hosi Company") # Default or user input
    points = Column(Integer, default=0)
    
    bids = relationship("UserBid", back_populates="user")

class Notice(Base):
    __tablename__ = "notices"

    bid_no = Column(String, primary_key=True, index=True) # 공고번호
    title = Column(String, index=True)
    content = Column(Text) # HTML or Text content
    basic_price = Column(Float) # 기초금액
    contract_type = Column(String, default="CONSTRUCTION") # CONSTRUCTION(시설), SERVICE(용역), GOODS(물품)
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    
    # Extended fields
    organization = Column(String)
    demand_organization = Column(String)
    bid_method = Column(String)
    contract_method = Column(String)
    bid_type = Column(String)
    status = Column(String)
    region = Column(String)
    budget_amount = Column(Float)
    opening_date = Column(String)
    international_bid = Column(String)
    joint_contract = Column(String)
    sme_only = Column(String)
    big_company_ok = Column(String)
    bid_qualification = Column(String)
    emergency_bid = Column(String)
    rebid_yn = Column(String)
    attachment_url = Column(String)
    attachment_name = Column(String)
    
    # Relationships
    bids = relationship("UserBid", back_populates="notice")
    ai_log = relationship("AIAnalysisLog", back_populates="notice", uselist=False)
    favorites = relationship("Favorite", back_populates="notice")

    def to_dict(self):
        """Convert model instance to dictionary."""
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
        }

class UserBid(Base):
    __tablename__ = "user_bids"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    notice_id = Column(String, ForeignKey("notices.bid_no"))
    
    bid_price = Column(Integer) # Calculated price (1 won precision)
    rate = Column(Float) # Sagyeongyul (e.g. 1.25)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="bids")
    notice = relationship("Notice", back_populates="bids")

class AIAnalysisLog(Base):
    """
    AI Logic Analysis Cache
    Ref: TechSpec v2.2 - 2.2 AI_Analysis_Logs
    """
    __tablename__ = "ai_analysis_logs"

    bid_no = Column(String, ForeignKey("notices.bid_no"), primary_key=True)
    summary_json = Column(JSON) # 3-line summary
    risk_factors = Column(JSON) # Risk factors list
    llm_model = Column(String, default="gpt-4o-mini")
    token_usage = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    notice = relationship("Notice", back_populates="ai_log")

class Favorite(Base):
    """
    User Favorites (Bookmarks)
    """
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    bid_no = Column(String, ForeignKey("notices.bid_no"), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    notice = relationship("Notice", back_populates="favorites")

