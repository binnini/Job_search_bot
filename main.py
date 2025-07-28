from crawling import scraper
import os
from dotenv import load_dotenv
from datetime import date
from db import base, io
import logs.log as log
import logging
from rag.vector_db_manager import add_embedding
import pandas as pd

if __name__ == "__main__":
    logging.info("프로그램 시작됨")
    load_dotenv(override=True)

    try:
        scraper.run_crawler_with_retry(max_retries=3)
    
        # Postgre DB
        base_path = os.getenv("RECRUIT_CSV_PATH")
        dir_path = os.path.dirname(base_path)
        today_str = date.today().strftime("%Y-%m-%d")
        csv_filename = f"jobkorea_data_{today_str}.csv"
        full_csv_path = os.path.join(dir_path, csv_filename)
        base.csv_to_db(full_csv_path)

        # FAISS DB
        df = pd.read_csv(full_csv_path)
        limit = len(df)-1
        data = io.read_recruitOut(limit=limit, order_desc=True)
        add_embedding(data)
        # io.export_titles_to_json()
    except KeyboardInterrupt:
        logging.warning("사용자에 의해 강제 종료됨")
        print("\n[종료] Ctrl+C에 의해 프로그램이 종료되었습니다.")
    except Exception as e:
        logging.error(f"예기치 못한 오류 발생: {e}")
    logging.info("프로그램 종료")