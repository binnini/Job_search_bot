"""
기존 DB 공고에 EXAONE 의미 태그를 소급 적용하는 배치 스크립트.

Usage:
    python db/tag_recruits.py                  # 마감 유효 공고 전체
    python db/tag_recruits.py --limit 1000     # 1000건만
    python db/tag_recruits.py --batch-size 50  # 배치 크기 조정
"""
import argparse
import logging
import sys
import os
from datetime import date
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import log_config
from db.io import SessionLocal
from db.models import Recruit
from db.tagger import tag_recruit_batch


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 공고 수")
    parser.add_argument("--batch-size", type=int, default=100, help="한 번에 처리할 건수 (기본 100)")
    parser.add_argument("--date", type=str, default=None, help="특정 수집일 필터 (예: 2026-03-14)")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        from sqlalchemy import func, cast
        import sqlalchemy as sa
        query = session.query(Recruit.id).order_by(Recruit.id.asc())
        if args.date:
            query = query.filter(func.date(Recruit.created_at) == args.date)
        else:
            query = query.filter(Recruit.deadline >= date.today())
        if args.limit:
            query = query.limit(args.limit)
        recruit_ids = [row[0] for row in query.all()]
    finally:
        session.close()

    total = len(recruit_ids)
    logging.info(f"소급 태깅 대상: {total}건 (배치 크기: {args.batch_size})")
    print(f"소급 태깅 시작: {total}건")

    tagged_total = skipped_total = failed_total = 0

    for start in range(0, total, args.batch_size):
        batch = recruit_ids[start:start + args.batch_size]
        stats = tag_recruit_batch(batch)

        tagged_total += stats["tagged"]
        skipped_total += stats["skipped"]
        failed_total += stats["failed"]

        done = start + len(batch)
        logging.info(
            f"[{done}/{total}] 태깅됨: {tagged_total} / 변화없음: {skipped_total} / 실패: {failed_total}"
        )
        print(
            f"[{done:>5}/{total}] 태깅됨: {tagged_total} | 변화없음: {skipped_total} | 실패: {failed_total}"
        )

    print(f"\n완료 — 태깅됨: {tagged_total} / 변화없음: {skipped_total} / 실패: {failed_total}")


if __name__ == "__main__":
    main()
