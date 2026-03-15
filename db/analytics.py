"""
채용 시장 분석 쿼리 모듈.

- get_top_tags()         인기 기술 스택 TOP N
- get_salary_by_tags()   키워드별 평균 연봉
- get_regional_dist()    지역별 공고 분포
- get_experience_dist()  경력별 공고 분포
- get_daily_new_jobs()   일별 신규 공고 수 트렌드
- get_market_snapshot()  현재 시장 현황 종합
"""
from datetime import date, timedelta
from sqlalchemy import func, case

from db.io import SessionLocal
from db.models import Recruit, Tag, Region, Subregion, recruit_tags


def get_top_tags(limit: int = 10, valid_only: bool = True) -> list[dict]:
    """유효 공고 기준 인기 태그 TOP N."""
    session = SessionLocal()
    try:
        q = (
            session.query(Tag.name, func.count(recruit_tags.c.recruit_id).label("count"))
            .join(recruit_tags, Tag.id == recruit_tags.c.tag_id)
            .join(Recruit, Recruit.id == recruit_tags.c.recruit_id)
        )
        if valid_only:
            q = q.filter(Recruit.deadline >= date.today())
        rows = (
            q.group_by(Tag.name)
            .order_by(func.count(recruit_tags.c.recruit_id).desc())
            .limit(limit)
            .all()
        )
        return [{"name": r.name, "count": r.count} for r in rows]
    finally:
        session.close()


def get_salary_by_tags(keywords: list[str]) -> list[dict]:
    """키워드별 평균/중간 연봉 (유효 공고, 연봉 데이터 있는 것만)."""
    session = SessionLocal()
    try:
        results = []
        for kw in keywords:
            row = (
                session.query(
                    func.avg(Recruit.annual_salary).label("avg"),
                    func.count(Recruit.id).label("count"),
                )
                .filter(Recruit.deadline >= date.today())
                .filter(Recruit.annual_salary.isnot(None))
                .filter(
                    Recruit.tags.any(Tag.name.ilike(f"%{kw}%"))
                    | Recruit.announcement_name.ilike(f"%{kw}%")
                )
                .one()
            )
            if row.count > 0:
                results.append({
                    "keyword": kw,
                    "avg_salary": int(row.avg),
                    "count": row.count,
                })
        return results
    finally:
        session.close()


def get_regional_dist(top_n: int = 8) -> list[dict]:
    """지역별 유효 공고 수 (상위 N개 지역)."""
    session = SessionLocal()
    try:
        rows = (
            session.query(Region.name, func.count(Recruit.id).label("count"))
            .join(Subregion, Subregion.region_id == Region.id)
            .join(Recruit, Recruit.subregion_id == Subregion.id)
            .filter(Recruit.deadline >= date.today())
            .group_by(Region.name)
            .order_by(func.count(Recruit.id).desc())
            .limit(top_n)
            .all()
        )
        return [{"region": r.name, "count": r.count} for r in rows]
    finally:
        session.close()


def get_experience_dist() -> list[dict]:
    """경력별 유효 공고 수."""
    session = SessionLocal()
    try:
        label_case = case(
            (Recruit.experience == None, "경력무관"),
            (Recruit.experience == 0, "신입"),
            (Recruit.experience <= 3, "1~3년"),
            (Recruit.experience <= 7, "4~7년"),
            else_="8년 이상",
        )
        rows = (
            session.query(label_case.label("label"), func.count(Recruit.id).label("count"))
            .filter(Recruit.deadline >= date.today())
            .group_by(label_case)
            .order_by(func.count(Recruit.id).desc())
            .all()
        )
        return [{"label": r.label, "count": r.count} for r in rows]
    finally:
        session.close()


def get_daily_new_jobs(days: int = 7) -> list[dict]:
    """최근 N일간 일별 신규 수집 공고 수."""
    session = SessionLocal()
    try:
        since = date.today() - timedelta(days=days - 1)
        rows = (
            session.query(
                func.date(Recruit.created_at).label("day"),
                func.count(Recruit.id).label("count"),
            )
            .filter(func.date(Recruit.created_at) >= since)
            .group_by(func.date(Recruit.created_at))
            .order_by(func.date(Recruit.created_at))
            .all()
        )
        return [{"date": str(r.day), "count": r.count} for r in rows]
    finally:
        session.close()


def get_market_snapshot() -> dict:
    """현재 채용 시장 종합 현황."""
    session = SessionLocal()
    try:
        today = date.today()
        total_valid = session.query(Recruit).filter(Recruit.deadline >= today).count()
        new_today = (
            session.query(Recruit)
            .filter(func.date(Recruit.created_at) == today)
            .count()
        )
        avg_salary_row = (
            session.query(func.avg(Recruit.annual_salary))
            .filter(Recruit.deadline >= today)
            .filter(Recruit.annual_salary.isnot(None))
            .scalar()
        )
    finally:
        session.close()

    return {
        "date": str(today),
        "total_valid_jobs": total_valid,
        "new_jobs_today": new_today,
        "avg_salary": int(avg_salary_row) if avg_salary_row else None,
        "top_tags": get_top_tags(10),
        "region_dist": get_regional_dist(6),
        "experience_dist": get_experience_dist(),
    }
