"""
CSV 데이터로 recruits.region_id / subregion_name을 일괄 복구하는 스크립트.

CSV의 원본 지역 문자열("서울 강동구")을 파싱해 region_id와 subregion_name을
기존 DB 행에 UPDATE한다. 삽입이 아닌 업데이트만 수행.

Usage:
    python backfill_region.py
    python backfill_region.py --dry-run   # 실제 UPDATE 없이 통계만 출력
"""
import argparse
import glob
import logging
import os

import pandas as pd
from dotenv import load_dotenv

load_dotenv(override=True)

import log_config
from db.base import connect_postgres, init_connection_pool, release_connection
from db.JobPreprocessor import JobPreprocessor

logging.basicConfig(level=logging.INFO)


def load_region_map(cursor) -> dict:
    """regions 테이블 {name: id} 반환."""
    cursor.execute("SELECT id, name FROM regions")
    return {name: id_ for id_, name in cursor.fetchall()}


def load_company_map(cursor) -> dict:
    """companies 테이블 {company_name: id} 반환."""
    cursor.execute("SELECT id, company_name FROM companies")
    return {name: id_ for id_, name in cursor.fetchall()}


def collect_updates(files: list, region_map: dict, company_map: dict) -> list:
    """
    CSV 전체를 읽어 UPDATE할 (region_id, subregion_name, company_id, announcement_name, deadline) 튜플 목록 반환.
    동일 키가 여러 CSV에 중복 등장하면 마지막 값으로 덮어쓴다.
    """
    updates = {}  # (company_id, announcement_name, deadline) -> (region_id, subregion_name)

    for path in sorted(files):
        try:
            df = pd.read_csv(path)
        except Exception as e:
            logging.warning(f"{path} 읽기 실패: {e}")
            continue

        today = _extract_date_from_path(path)

        for _, row in df.iterrows():
            company_name = str(row.get('기업명', '') or '').strip().replace(',', '')
            announcement_name = str(row.get('공고명', '') or '').strip().replace(',', '')
            deadline_raw = str(row.get('마감일', '') or '')
            location_raw = str(row.get('지역', '') or '')

            company_id = company_map.get(company_name)
            if company_id is None:
                continue

            parsed_deadline = JobPreprocessor.parse_deadline(deadline_raw, today=today)
            parsed_region = JobPreprocessor.parse_region(location_raw)
            if not parsed_region:
                continue

            region_name, subregion_name = parsed_region
            region_id = region_map.get(region_name)
            if region_id is None:
                continue

            key = (company_id, announcement_name, str(parsed_deadline))
            updates[key] = (region_id, subregion_name)

    return [
        (region_id, subregion_name, company_id, announcement_name, deadline)
        for (company_id, announcement_name, deadline), (region_id, subregion_name) in updates.items()
    ]


def _extract_date_from_path(path):
    import re
    from datetime import date
    m = re.search(r'(\d{4})-(\d{2})-(\d{2})', path)
    if m:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def run(dry_run: bool = False):
    init_connection_pool()
    conn = connect_postgres()

    try:
        cursor = conn.cursor()
        region_map = load_region_map(cursor)
        company_map = load_company_map(cursor)

        files = glob.glob(os.path.join('data', 'jobkorea_data*.csv'))
        logging.info(f"CSV {len(files)}개 파일 읽는 중...")

        updates = collect_updates(files, region_map, company_map)
        logging.info(f"업데이트 대상: {len(updates):,}건")

        if dry_run:
            logging.info("--dry-run 모드: DB 변경 없음")
            region_none = sum(1 for r, s, *_ in updates if r is None)
            logging.info(f"  region_id 확인 불가: {region_none}건")
            return

        cursor.executemany("""
            UPDATE recruits
            SET region_id = %s, subregion_name = %s
            WHERE company_id = %s
              AND announcement_name = %s
              AND deadline::TEXT = %s
              AND (region_id IS NULL OR subregion_name IS DISTINCT FROM %s)
        """, [(*t, t[1]) for t in updates])  # 마지막 %s는 subregion_name 중복 비교용

        updated = cursor.rowcount
        conn.commit()
        logging.info(f"완료: {updated:,}건 업데이트됨")

        # 결과 검증
        cursor.execute("SELECT COUNT(*) FROM recruits WHERE region_id IS NOT NULL")
        filled = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM recruits")
        total = cursor.fetchone()[0]
        logging.info(f"region_id 채움률: {filled:,}/{total:,} ({filled/total*100:.1f}%)")

    finally:
        release_connection(conn)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='실제 UPDATE 없이 통계만 출력')
    args = parser.parse_args()
    run(dry_run=args.dry_run)
