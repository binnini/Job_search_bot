from crawling import scraper
from dotenv import load_dotenv
from db import io
import logs.log as log
import logging
from rag.vector_db_manager import add_embedding

if __name__ == "__main__":
    logging.info("프로그램 시작됨")
    load_dotenv(override=True)

    try:
        # 크롤링 → DB 직접 적재
        scraper.run_crawler_with_retry(max_retries=3)

        # FAISS DB 업데이트
        data = io.read_recruitOut(order_desc=True)
        add_embedding(data)
    except KeyboardInterrupt:
        logging.warning("사용자에 의해 강제 종료됨")
        print("\n[종료] Ctrl+C에 의해 프로그램이 종료되었습니다.")
    except Exception as e:
        logging.error(f"예기치 못한 오류 발생: {e}")
    logging.info("프로그램 종료")