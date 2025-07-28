import pandas as pd
from .base import connect_postgres
from .models import Recruit, Subregion, RecruitOut
from .JobPreprocessor import JobPreprocessor
from datetime import date
import logging
from dotenv import load_dotenv
import os
import json
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, Session, joinedload
from typing import List


load_dotenv(override=True)
RECRUIT_TITLE_ORG_PATH = os.getenv("RECRUIT_TITLE_ORG_PATH")

# ──────────────────────────────
# DATABASE CONNECTION
# ──────────────────────────────
DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ──────────────────────────────
# DATA READING & DELETE
# ──────────────────────────────
def read_recruitOut(limit: int = 10000, order_desc: bool = False) -> List[RecruitOut]:
    today = date.today()
    session = SessionLocal()
    
    try:   
        query = (
            session.query(Recruit)
            .options(
                joinedload(Recruit.company),
                joinedload(Recruit.subregion).joinedload(Subregion.region)
            )
            .filter(Recruit.deadline >= today)
        )

        # order_desc=True 이면 역순 정렬
        if order_desc:
            query = query.order_by(Recruit.id.desc())
        else:
            query = query.order_by(Recruit.id.asc())

        data = query.limit(limit).all()

        return [
            RecruitOut(
                id=r.id,
                company_name=r.company.company_name,
                announcement_name=r.announcement_name,
                link=r.link,
                deadline=r.deadline,
                annual_salary=r.annual_salary,
                experience=r.experience,
                education=r.education,
                form=r.form,
                tags=[tag.name for tag in r.tags],
                region_name=r.subregion.region.name if r.subregion and r.subregion.region else None
            ) for r in data
        ]
    finally:
        session.close()

def read_recruits_by_ids(recruit_ids: List[int]) -> List[RecruitOut]:
    session = SessionLocal()
    
    try:
        recruits = (
            session.query(Recruit)
            .options(
                joinedload(Recruit.company),
                joinedload(Recruit.subregion).joinedload(Subregion.region)
            )
            .filter(Recruit.id.in_(recruit_ids))
            .all()
        )

        return [
            RecruitOut(
                id=r.id,
                company_name=r.company.company_name,
                announcement_name=r.announcement_name,
                link=r.link,
                deadline=r.deadline,
                annual_salary=r.annual_salary,
                experience=r.experience,
                education=r.education,
                form=r.form,
                tags=[tag.name for tag in r.tags],
                region_name=r.subregion.region.name if r.subregion and r.subregion.region else None
            )
            for r in recruits
        ]
    finally:
        session.close()

def _read_table_as_dataframe(table_name):
    conn = connect_postgres()
    try:
        df = pd.read_sql_query(f"SELECT * FROM {table_name}", conn)
        return df
    finally:
        conn.close()

def read_recruits():
    return _read_table_as_dataframe("recruits")

def read_companies():
    return _read_table_as_dataframe("companies")

def read_tags():
    return _read_table_as_dataframe("tags")

def read_recruit_tags():
    return _read_table_as_dataframe("recruit_tags")

def read_regions():
    return _read_table_as_dataframe("regions")

def read_subregions():
    return _read_table_as_dataframe("subregions")

def read_full_region_names():
    """
    regions와 subregions를 JOIN하여 full_region_name(예: 서울 강남구) 컬럼을 반환하는 DataFrame 생성
    """
    conn = connect_postgres()
    try:
        query = """
        SELECT
            subregions.id AS subregion_id,
            regions.name AS region,
            subregions.name AS subregion,
            regions.name || ' ' || subregions.name AS full_region_name
        FROM subregions
        JOIN regions ON subregions.region_id = regions.id
        ORDER BY region, subregion;
        """
        df = pd.read_sql_query(query, conn)
        return df
    finally:
        conn.close()

def delete_expired_jobs():
    conn = connect_postgres()
    cursor = conn.cursor()

    today = date.today()
    cursor.execute("DELETE FROM recruits WHERE deadline < %s", (today,))
    deleted = cursor.rowcount

    conn.commit()
    conn.close()
    logging.info(f"{deleted}개의 마감된 공고가 삭제되었습니다.")

def export_titles_to_json():
    # 1. DB에서 공고 테이블 로드
    df = read_recruits()

    # 2. 공고명 컬럼만 추출, NaN 제거
    titles = df["announcement_name"].dropna().unique()

    # 3. JSON 포맷에 맞게 변환
    json_data = [{"text": title} for title in titles]

    # 4. JSON 파일로 저장
    with open(RECRUIT_TITLE_ORG_PATH, "w", encoding="utf-8") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)

    print(f"✅ {len(json_data)}개 공고명을 '{RECRUIT_TITLE_ORG_PATH}'에 저장했습니다.")