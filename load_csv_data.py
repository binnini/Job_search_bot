"""
data/ 디렉토리의 CSV 파일들을 DB에 일괄 적재하는 스크립트.

Usage:
    python load_csv_data.py              # data/ 전체 CSV
    python load_csv_data.py --file data/jobkorea_data_2025-07-15.csv  # 특정 파일
"""
import argparse
import glob
import logging
import os
from dotenv import load_dotenv

import log_config
from db.base import csv_to_db, init_connection_pool

load_dotenv(override=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', type=str, default=None, help='특정 CSV 파일 경로 (미지정 시 data/ 전체)')
    args = parser.parse_args()

    init_connection_pool()

    if args.file:
        files = [args.file]
    else:
        files = sorted(glob.glob(os.path.join('data', 'jobkorea_data*.csv')))

    logging.info(f"총 {len(files)}개 파일 적재 시작")

    for i, path in enumerate(files, 1):
        logging.info(f"[{i}/{len(files)}] {path} 처리 중...")
        try:
            csv_to_db(path)  # today는 파일명에서 자동 추출
            logging.info(f"[{i}/{len(files)}] {path} 완료")
        except Exception as e:
            logging.error(f"[{i}/{len(files)}] {path} 실패: {e}")

    logging.info("전체 CSV 적재 완료")


if __name__ == "__main__":
    main()
