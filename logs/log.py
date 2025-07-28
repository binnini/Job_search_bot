import os
import logging
from datetime import date
from dotenv import load_dotenv

load_dotenv()

LOG_DIR = os.getenv("CRAWL_LOG_DIR", "./logs")  # 기본값 지정
os.makedirs(LOG_DIR, exist_ok=True)

log_file = os.path.join(LOG_DIR, f"crawl_{date.today().strftime('%Y-%m-%d')}.log")

logging.basicConfig(
    filename=log_file,
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logging.info("🔧 Logging initialized")