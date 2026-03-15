import argparse
from crawling import scraper
from db.base import clear_recruit_data
from dotenv import load_dotenv
import log_config
import logging

if __name__ == "__main__":
    load_dotenv(override=True)

    parser = argparse.ArgumentParser()
    parser.add_argument('--days', type=int, default=1, help='크롤링할 날짜 범위 (기본: 1일)')
    parser.add_argument('--fresh', action='store_true', help='크롤링 전 기존 공고 데이터 전체 삭제')
    args = parser.parse_args()

    logging.info("프로그램 시작됨")

    if args.fresh:
        logging.info("기존 데이터 삭제 중...")
        clear_recruit_data()

    try:
        scraper.run_crawler_with_retry(max_retries=3, days=args.days)
    except KeyboardInterrupt:
        logging.warning("사용자에 의해 강제 종료됨")
        print("\n[종료] Ctrl+C에 의해 프로그램이 종료되었습니다.")
    except Exception as e:
        logging.error(f"예기치 못한 오류 발생: {e}")

    try:
        from analytics.snapshot import save_snapshot
        save_snapshot()
    except Exception as e:
        logging.warning(f"스냅샷 저장 실패 (크롤링 결과에는 영향 없음): {e}")

    logging.info("프로그램 종료")
