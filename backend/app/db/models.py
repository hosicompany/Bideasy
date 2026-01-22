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
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    
    # Relationships
    bids = relationship("UserBid", back_populates="notice")
    ai_log = relationship("AIAnalysisLog", back_populates="notice", uselist=False)

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
