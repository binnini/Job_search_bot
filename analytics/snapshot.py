"""
일별 채용 시장 스냅샷을 job_market_daily 테이블에 저장하는 스크립트.

매일 크롤링 완료 후 main.py에서 자동 호출되거나, 단독 실행 가능.

Usage:
    python analytics/snapshot.py
    python analytics/snapshot.py --date 2026-03-14   # 특정 날짜 재생성
"""
import argparse
import json
import logging
import os
import sys
from datetime import date

from dotenv import load_dotenv
load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import log_config  # noqa: F401
from db.io import SessionLocal
from db.models import JobMarketDaily
from db.analytics import get_market_snapshot


def save_snapshot(target_date: date = None) -> None:
    if target_date is None:
        target_date = date.today()

    logging.info(f"[snapshot] {target_date} 스냅샷 생성 시작")
    snap = get_market_snapshot()

    session = SessionLocal()
    try:
        existing = session.get(JobMarketDaily, target_date)
        if existing:
            existing.total_valid_jobs = snap["total_valid_jobs"]
            existing.new_jobs = snap["new_jobs_today"]
            existing.avg_salary = snap["avg_salary"]
            existing.top_tags = snap["top_tags"]
            existing.region_dist = snap["region_dist"]
            existing.experience_dist = snap["experience_dist"]
            logging.info(f"[snapshot] {target_date} 기존 레코드 업데이트")
        else:
            session.add(JobMarketDaily(
                date=target_date,
                total_valid_jobs=snap["total_valid_jobs"],
                new_jobs=snap["new_jobs_today"],
                avg_salary=snap["avg_salary"],
                top_tags=snap["top_tags"],
                region_dist=snap["region_dist"],
                experience_dist=snap["experience_dist"],
            ))
            logging.info(f"[snapshot] {target_date} 새 레코드 삽입")
        session.commit()
    finally:
        session.close()

    print(f"[snapshot] {target_date} 완료 — 유효공고 {snap['total_valid_jobs']:,}건 / 신규 {snap['new_jobs_today']:,}건 / 평균연봉 {snap['avg_salary']:,}만원")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", type=str, default=None, help="스냅샷 날짜 (기본: 오늘)")
    args = parser.parse_args()

    target = date.fromisoformat(args.date) if args.date else None
    save_snapshot(target)
