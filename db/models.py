from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Date, DateTime, ForeignKey, Table, JSON
from sqlalchemy.orm import relationship
from typing import List, Optional
from datetime import date, datetime
from pydantic import BaseModel, ConfigDict

Base = declarative_base()

recruit_tags = Table(
    "recruit_tags",
    Base.metadata,
    Column("recruit_id", Integer, ForeignKey("recruits.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", Integer, ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)
)

class Region(Base):
    __tablename__ = "regions"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)
    subregions = relationship("Subregion", back_populates="region", cascade="all, delete")

class Subregion(Base):
    __tablename__ = "subregions"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    region_id = Column(Integer, ForeignKey("regions.id", ondelete="CASCADE"))
    region = relationship("Region", back_populates="subregions")
    recruits = relationship("Recruit", back_populates="subregion")

class Company(Base):
    __tablename__ = "companies"
    id = Column(Integer, primary_key=True)
    company_name = Column(String, unique=True, nullable=False)
    recruits = relationship("Recruit", back_populates="company")

class Recruit(Base):
    __tablename__ = "recruits"
    id = Column(Integer, primary_key=True)
    company_id = Column(Integer, ForeignKey("companies.id"))
    announcement_name = Column(String)
    experience = Column(Integer)
    education = Column(Integer)
    form = Column(Integer)
    subregion_id = Column(Integer, ForeignKey("subregions.id"))
    annual_salary = Column(Integer)
    deadline = Column(Date)
    link = Column(String)

    created_at = Column(DateTime, default=datetime.now)

    company = relationship("Company", back_populates="recruits")
    subregion = relationship("Subregion", back_populates="recruits")
    tags = relationship("Tag", secondary=recruit_tags, back_populates="recruits")

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    recruits = relationship("Recruit", secondary=recruit_tags, back_populates="tags")

class NotificationLog(Base):
    __tablename__ = "notification_log"
    id = Column(Integer, primary_key=True)
    discord_user_id = Column(String, nullable=False)
    recruit_id = Column(Integer, ForeignKey("recruits.id", ondelete="CASCADE"), nullable=False)
    notified_at = Column(DateTime, default=datetime.now)


class UserProfile(Base):
    """사용자 공통 필터 (지역/고용형태/경력/연봉). 사용자당 1개."""
    __tablename__ = "user_profiles"
    discord_user_id = Column(String, primary_key=True)
    region = Column(String, nullable=True)
    form = Column(Integer, nullable=True)
    max_experience = Column(Integer, nullable=True)
    min_annual_salary = Column(Integer, nullable=True)
    updated_at = Column(DateTime, default=datetime.now)


class UserSubscription(Base):
    """키워드 구독. 사용자당 최대 N개."""
    __tablename__ = "user_subscriptions"
    id = Column(Integer, primary_key=True)
    discord_user_id = Column(String, nullable=False)
    keyword = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)


class JobMarketDaily(Base):
    """날짜별 채용 시장 스냅샷 — 분석 레이어."""
    __tablename__ = "job_market_daily"
    date = Column(Date, primary_key=True)
    total_valid_jobs = Column(Integer)   # 마감 미도래 공고 수
    new_jobs = Column(Integer)           # 당일 신규 수집 공고 수
    avg_salary = Column(Integer)         # 유효 공고 평균 연봉 (만원)
    top_tags = Column(JSON)              # 인기 태그 TOP 10 [{name, count}, ...]
    region_dist = Column(JSON)           # 지역별 분포 [{region, count}, ...]
    experience_dist = Column(JSON)       # 경력별 분포 [{label, count}, ...]
    created_at = Column(DateTime, default=datetime.now)


class RecruitOut(BaseModel):
    id: int
    company_name: str
    announcement_name: str
    link: str
    deadline: date
    annual_salary: Optional[int]
    experience: Optional[int]
    education: Optional[int]
    form: Optional[int]
    region_name: Optional[str]
    tags: List[str]

    model_config = ConfigDict(from_attributes=True)