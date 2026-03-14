import pandas as pd
from .base import connect_postgres
from .models import Recruit, Subregion, RecruitOut, Tag, Company, Region, UserSubscription, NotificationLog
from .JobPreprocessor import JobPreprocessor
from datetime import date, datetime, timedelta
from dataclasses import dataclass
import logging
from dotenv import load_dotenv
import os
import json
from sqlalchemy import create_engine, func, or_
from sqlalchemy.orm import sessionmaker, Session, joinedload
from typing import List, Optional


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

def search_recruits_by_filter(
    keyword: str = None,
    min_deadline=None,
    min_annual_salary: int = None,
    company_name: str = None,
    max_experience: int = None,
    form: int = None,
    region: str = None,
    limit: int = 5,
) -> List[RecruitOut]:
    today = date.today()
    session = SessionLocal()
    try:
        query = (
            session.query(Recruit)
            .options(
                joinedload(Recruit.company),
                joinedload(Recruit.subregion).joinedload(Subregion.region),
                joinedload(Recruit.tags),
            )
            .filter(Recruit.deadline >= today)
        )

        if keyword:
            for token in keyword.split():
                query = query.filter(
                    or_(
                        Recruit.announcement_name.ilike(f"%{token}%"),
                        Recruit.tags.any(Tag.name.ilike(f"%{token}%")),
                    )
                )
        if min_deadline:
            query = query.filter(Recruit.deadline >= min_deadline)
        if min_annual_salary:
            query = query.filter(Recruit.annual_salary >= min_annual_salary)
        if company_name:
            query = query.join(Recruit.company).filter(
                Company.company_name.ilike(f"%{company_name}%")
            )
        if max_experience is not None:
            query = query.filter(
                or_(Recruit.experience == None, Recruit.experience <= max_experience)
            )
        if form is not None:
            query = query.filter(Recruit.form == form)
        if region:
            query = (
                query
                .join(Recruit.subregion)
                .join(Subregion.region)
                .filter(Region.name.ilike(f"%{region}%"))
            )

        results = query.order_by(Recruit.id.desc()).limit(limit).all()

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
                region_name=r.subregion.region.name if r.subregion and r.subregion.region else None,
            )
            for r in results
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

def get_new_recruits(hours: int = 24) -> List[RecruitOut]:
    """최근 N시간 이내에 추가된 신규 공고를 반환."""
    since = datetime.now() - timedelta(hours=hours)
    session = SessionLocal()
    try:
        recruits = (
            session.query(Recruit)
            .options(
                joinedload(Recruit.company),
                joinedload(Recruit.subregion).joinedload(Subregion.region),
                joinedload(Recruit.tags),
            )
            .filter(Recruit.created_at >= since)
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
                region_name=r.subregion.region.name if r.subregion and r.subregion.region else None,
            )
            for r in recruits
        ]
    finally:
        session.close()


# ──────────────────────────────
# SUBSCRIPTION DATA CLASS
# ──────────────────────────────
@dataclass
class SubscriptionOut:
    discord_user_id: str
    keyword: Optional[str]
    region: Optional[str]
    form: Optional[int]
    max_experience: Optional[int]
    min_annual_salary: Optional[int]


# ──────────────────────────────
# SUBSCRIPTION CRUD
# ──────────────────────────────
def save_subscription(
    discord_user_id: str,
    keyword: str = None,
    region: str = None,
    form: int = None,
    max_experience: int = None,
    min_annual_salary: int = None,
):
    session = SessionLocal()
    try:
        existing = session.query(UserSubscription).filter_by(discord_user_id=discord_user_id).first()
        if existing:
            existing.keyword = keyword
            existing.region = region
            existing.form = form
            existing.max_experience = max_experience
            existing.min_annual_salary = min_annual_salary
        else:
            session.add(UserSubscription(
                discord_user_id=discord_user_id,
                keyword=keyword,
                region=region,
                form=form,
                max_experience=max_experience,
                min_annual_salary=min_annual_salary,
            ))
        session.commit()
    finally:
        session.close()


def delete_subscription(discord_user_id: str) -> bool:
    session = SessionLocal()
    try:
        sub = session.query(UserSubscription).filter_by(discord_user_id=discord_user_id).first()
        if sub:
            session.delete(sub)
            session.commit()
            return True
        return False
    finally:
        session.close()


def get_subscription(discord_user_id: str) -> Optional[SubscriptionOut]:
    session = SessionLocal()
    try:
        s = session.query(UserSubscription).filter_by(discord_user_id=discord_user_id).first()
        if not s:
            return None
        return SubscriptionOut(
            discord_user_id=s.discord_user_id,
            keyword=s.keyword,
            region=s.region,
            form=s.form,
            max_experience=s.max_experience,
            min_annual_salary=s.min_annual_salary,
        )
    finally:
        session.close()


def get_all_subscriptions() -> List[SubscriptionOut]:
    session = SessionLocal()
    try:
        subs = session.query(UserSubscription).all()
        return [
            SubscriptionOut(
                discord_user_id=s.discord_user_id,
                keyword=s.keyword,
                region=s.region,
                form=s.form,
                max_experience=s.max_experience,
                min_annual_salary=s.min_annual_salary,
            )
            for s in subs
        ]
    finally:
        session.close()


# ──────────────────────────────
# NOTIFICATION LOG
# ──────────────────────────────
def get_notified_recruit_ids(discord_user_id: str) -> set:
    """해당 사용자에게 이미 알림 발송한 recruit_id 집합을 반환."""
    session = SessionLocal()
    try:
        rows = session.query(NotificationLog.recruit_id).filter_by(
            discord_user_id=discord_user_id
        ).all()
        return {row[0] for row in rows}
    finally:
        session.close()


def save_notification_log(discord_user_id: str, recruit_ids: List[int]):
    """알림 발송 이력을 저장. 이미 존재하는 (user, recruit) 쌍은 무시."""
    from .base import connect_postgres, release_connection
    conn = connect_postgres()
    try:
        cursor = conn.cursor()
        cursor.executemany("""
            INSERT INTO notification_log (discord_user_id, recruit_id)
            VALUES (%s, %s)
            ON CONFLICT (discord_user_id, recruit_id) DO NOTHING
        """, [(discord_user_id, rid) for rid in recruit_ids])
        conn.commit()
    finally:
        release_connection(conn)


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