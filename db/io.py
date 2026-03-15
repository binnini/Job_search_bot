import pandas as pd
from .models import Recruit, Subregion, RecruitOut, Tag, Company, Region, UserSubscription, UserProfile, NotificationLog
from .JobPreprocessor import JobPreprocessor
from datetime import date, datetime, timedelta
from dataclasses import dataclass
import logging
from dotenv import load_dotenv
import os
from sqlalchemy import create_engine, or_
from sqlalchemy.orm import sessionmaker, joinedload
from typing import List, Optional


load_dotenv(override=True)

# ──────────────────────────────
# DATABASE CONNECTION
# ──────────────────────────────
DATABASE_URL = (
    f"postgresql://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}"
    f"@{os.getenv('POSTGRES_HOST')}:{os.getenv('POSTGRES_PORT')}/{os.getenv('POSTGRES_DB')}"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _to_recruit_out(r: Recruit) -> RecruitOut:
    return RecruitOut(
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
        return [_to_recruit_out(r) for r in data]
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
    expanded_keywords: list = None,
) -> List[RecruitOut]:
    today = date.today()
    session = SessionLocal()
    try:
        def _build_query(keyword_mode: str = 'and'):
            q = (
                session.query(Recruit)
                .options(
                    joinedload(Recruit.company),
                    joinedload(Recruit.subregion).joinedload(Subregion.region),
                    joinedload(Recruit.tags),
                )
                .filter(Recruit.deadline >= today)
            )
            if expanded_keywords:
                # 확장 키워드 OR 매칭: 하나라도 공고명·태그에 포함되면 통과
                q = q.filter(or_(*[
                    or_(
                        Recruit.announcement_name.ilike(f"%{kw}%"),
                        Recruit.tags.any(Tag.name.ilike(f"%{kw}%")),
                    )
                    for kw in expanded_keywords
                ]))
            elif keyword:
                tokens = keyword.split()
                if keyword_mode == 'and':
                    for token in tokens:
                        q = q.filter(or_(
                            Recruit.announcement_name.ilike(f"%{token}%"),
                            Recruit.tags.any(Tag.name.ilike(f"%{token}%")),
                        ))
                else:  # 'or' 폴백
                    q = q.filter(or_(*[
                        or_(
                            Recruit.announcement_name.ilike(f"%{token}%"),
                            Recruit.tags.any(Tag.name.ilike(f"%{token}%")),
                        )
                        for token in tokens
                    ]))
            if min_deadline:
                q = q.filter(Recruit.deadline >= min_deadline)
            if min_annual_salary:
                q = q.filter(Recruit.annual_salary >= min_annual_salary)
            if company_name:
                q = q.join(Recruit.company).filter(
                    Company.company_name.ilike(f"%{company_name}%")
                )
            if max_experience is not None:
                q = q.filter(or_(Recruit.experience == None, Recruit.experience <= max_experience))
            if form is not None:
                q = q.filter(Recruit.form == form)
            if region:
                q = (
                    q.join(Recruit.subregion)
                    .join(Subregion.region)
                    .filter(Region.name.ilike(f"%{region}%"))
                )
            return q

        results = _build_query('and').order_by(Recruit.id.desc()).limit(limit).all()

        # AND 결과 없고 키워드가 여러 토큰이면 OR 폴백 (expanded_keywords 미사용 시만)
        if not results and not expanded_keywords and keyword and len(keyword.split()) > 1:
            results = _build_query('or').order_by(Recruit.id.desc()).limit(limit).all()

        return [_to_recruit_out(r) for r in results]
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

        return [_to_recruit_out(r) for r in recruits]
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
        return [_to_recruit_out(r) for r in recruits]
    finally:
        session.close()


# ──────────────────────────────
# PROFILE & SUBSCRIPTION DATA CLASSES
# ──────────────────────────────
@dataclass
class ProfileOut:
    discord_user_id: str
    region: Optional[str]
    form: Optional[int]
    max_experience: Optional[int]
    min_annual_salary: Optional[int]


@dataclass
class SubscriptionOut:
    id: int
    discord_user_id: str
    keyword: Optional[str]


# ──────────────────────────────
# PROFILE CRUD
# ──────────────────────────────
def save_user_profile(
    discord_user_id: str,
    region: str = None,
    form: int = None,
    max_experience: int = None,
    min_annual_salary: int = None,
) -> None:
    """사용자 프로필 저장 (없으면 생성, 있으면 덮어쓰기)."""
    session = SessionLocal()
    try:
        profile = session.query(UserProfile).filter_by(
            discord_user_id=discord_user_id
        ).first()
        if profile:
            profile.region = region
            profile.form = form
            profile.max_experience = max_experience
            profile.min_annual_salary = min_annual_salary
        else:
            session.add(UserProfile(
                discord_user_id=discord_user_id,
                region=region,
                form=form,
                max_experience=max_experience,
                min_annual_salary=min_annual_salary,
            ))
        session.commit()
    finally:
        session.close()


def get_user_profile(discord_user_id: str) -> Optional[ProfileOut]:
    """사용자 프로필 반환. 없으면 None."""
    session = SessionLocal()
    try:
        p = session.query(UserProfile).filter_by(
            discord_user_id=discord_user_id
        ).first()
        if not p:
            return None
        return ProfileOut(
            discord_user_id=p.discord_user_id,
            region=p.region,
            form=p.form,
            max_experience=p.max_experience,
            min_annual_salary=p.min_annual_salary,
        )
    finally:
        session.close()


def get_all_user_profiles() -> dict:
    """전체 사용자 프로필 {discord_user_id: ProfileOut} 반환 (알림 발송용)."""
    session = SessionLocal()
    try:
        profiles = session.query(UserProfile).all()
        return {
            p.discord_user_id: ProfileOut(
                discord_user_id=p.discord_user_id,
                region=p.region,
                form=p.form,
                max_experience=p.max_experience,
                min_annual_salary=p.min_annual_salary,
            )
            for p in profiles
        }
    finally:
        session.close()


# ──────────────────────────────
# SUBSCRIPTION CRUD (키워드 전용)
# ──────────────────────────────
MAX_SUBSCRIPTIONS_PER_USER = 5


def save_subscription(discord_user_id: str, keyword: str = None) -> tuple:
    """키워드 구독 추가. (성공 여부, 메시지) 반환."""
    session = SessionLocal()
    try:
        count = session.query(UserSubscription).filter_by(
            discord_user_id=discord_user_id
        ).count()
        if count >= MAX_SUBSCRIPTIONS_PER_USER:
            return False, f"구독은 최대 {MAX_SUBSCRIPTIONS_PER_USER}개까지 등록할 수 있습니다."
        session.add(UserSubscription(
            discord_user_id=discord_user_id,
            keyword=keyword,
        ))
        session.commit()
        return True, None
    finally:
        session.close()


def delete_subscription(discord_user_id: str, index: int) -> bool:
    """1-based 인덱스로 사용자의 특정 구독 삭제."""
    session = SessionLocal()
    try:
        subs = session.query(UserSubscription).filter_by(
            discord_user_id=discord_user_id
        ).order_by(UserSubscription.id).all()
        if index < 1 or index > len(subs):
            return False
        session.delete(subs[index - 1])
        session.commit()
        return True
    finally:
        session.close()


def delete_all_subscriptions(discord_user_id: str) -> int:
    """사용자의 모든 구독 삭제. 삭제 건수 반환."""
    session = SessionLocal()
    try:
        count = session.query(UserSubscription).filter_by(
            discord_user_id=discord_user_id
        ).delete()
        session.commit()
        return count
    finally:
        session.close()


def get_subscriptions(discord_user_id: str) -> List[SubscriptionOut]:
    """사용자의 키워드 구독 목록 반환."""
    session = SessionLocal()
    try:
        subs = session.query(UserSubscription).filter_by(
            discord_user_id=discord_user_id
        ).order_by(UserSubscription.id).all()
        return [
            SubscriptionOut(id=s.id, discord_user_id=s.discord_user_id, keyword=s.keyword)
            for s in subs
        ]
    finally:
        session.close()


def get_all_subscriptions() -> List[SubscriptionOut]:
    """전체 사용자의 키워드 구독 반환 (알림 발송용)."""
    session = SessionLocal()
    try:
        subs = session.query(UserSubscription).all()
        return [
            SubscriptionOut(id=s.id, discord_user_id=s.discord_user_id, keyword=s.keyword)
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
    from sqlalchemy.dialects.postgresql import insert as pg_insert
    session = SessionLocal()
    try:
        for rid in recruit_ids:
            stmt = pg_insert(NotificationLog).values(
                discord_user_id=discord_user_id,
                recruit_id=rid,
            ).on_conflict_do_nothing()
            session.execute(stmt)
        session.commit()
    finally:
        session.close()


def normalize_existing_tags() -> dict:
    """TAG_SYNONYMS 기준으로 기존 DB 태그 정규화.

    - old_tag만 있으면 이름 변경
    - new_tag도 있으면 recruit_tags를 new_tag로 이전 후 old_tag 삭제
    반환: {'renamed': [...], 'merged': [...], 'skipped': [...]}
    """
    from .JobPreprocessor import TAG_SYNONYMS
    from sqlalchemy import text
    session = SessionLocal()
    report = {'renamed': [], 'merged': [], 'skipped': []}
    try:
        for old_name, new_name in TAG_SYNONYMS.items():
            old_tag = session.query(Tag).filter_by(name=old_name).first()
            if not old_tag:
                report['skipped'].append(old_name)
                continue

            new_tag = session.query(Tag).filter_by(name=new_name).first()
            if new_tag:
                session.execute(text("""
                    INSERT INTO recruit_tags (recruit_id, tag_id)
                    SELECT recruit_id, :new_id FROM recruit_tags WHERE tag_id = :old_id
                    ON CONFLICT DO NOTHING
                """), {"new_id": new_tag.id, "old_id": old_tag.id})
                session.execute(text("DELETE FROM recruit_tags WHERE tag_id = :old_id"), {"old_id": old_tag.id})
                session.delete(old_tag)
                report['merged'].append(f"{old_name} → {new_name}")
            else:
                old_tag.name = new_name
                report['renamed'].append(f"{old_name} → {new_name}")

        session.commit()
        logging.info(f"태그 정규화 완료: {report}")
        return report
    finally:
        session.close()


def _read_table_as_dataframe(table_name):
    with engine.connect() as conn:
        return pd.read_sql_query(f"SELECT * FROM {table_name}", conn)

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
    """regions + subregions JOIN → full_region_name(예: 서울 강남구) DataFrame 반환."""
    query = """
        SELECT
            subregions.id AS subregion_id,
            regions.name AS region,
            subregions.name AS subregion,
            regions.name || ' ' || subregions.name AS full_region_name
        FROM subregions
        JOIN regions ON subregions.region_id = regions.id
        ORDER BY region, subregion
    """
    with engine.connect() as conn:
        return pd.read_sql_query(query, conn)


def delete_expired_jobs():
    session = SessionLocal()
    try:
        deleted = session.query(Recruit).filter(Recruit.deadline < date.today()).delete()
        session.commit()
        logging.info(f"{deleted}개의 마감된 공고가 삭제되었습니다.")
    finally:
        session.close()

