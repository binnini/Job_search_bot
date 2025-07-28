from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, Date, ForeignKey, Table
from sqlalchemy.orm import relationship
from typing import List, Optional
from datetime import date
from pydantic import BaseModel

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

    company = relationship("Company", back_populates="recruits")
    subregion = relationship("Subregion", back_populates="recruits")
    tags = relationship("Tag", secondary=recruit_tags, back_populates="recruits")

class Tag(Base):
    __tablename__ = "tags"
    id = Column(Integer, primary_key=True)
    name = Column(String, unique=True, nullable=False)

    recruits = relationship("Recruit", secondary=recruit_tags, back_populates="tags")

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

    class Config:
        orm_mode = True