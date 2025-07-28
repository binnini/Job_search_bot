import os
import math
import logging
from datetime import date
from dotenv import load_dotenv
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from .page_handler import init_browser
from .saver import save_to_csv
from .user_agent import random_user_agent
from .utils import random_sleep, periodic_rest

load_dotenv(override=True)

TARGET_URL = os.getenv("TARGET_URL")


def crawl_jobkorea_multiple_pages():
    MAX_ITEMS = 50
    SAVE_CNT = 5
    total_items = 0
    data_batch = []

    header = ["기업명", "공고명", "경력", "학력", "형태", "지역", "연봉", "마감일", "설명", "링크"]
    today_str = date.today().strftime("%Y-%m-%d")

    base_path = os.getenv("RECRUIT_CSV_PATH")
    dir_path = os.path.dirname(base_path)

    csv_filename = f"jobkorea_data_{today_str}.csv"
    output_csv = os.path.join(dir_path, csv_filename)

    ua = random_user_agent()
    headers = {
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://www.jobkorea.co.kr/",
        "DNT": "1"
    }

    playwright, browser, context, page = init_browser(ua, headers)

    def safe_wait_networkidle(page, desc="페이지", retries=3, timeout=30000):
        """
        networkidle 대기 중 TimeoutError 발생 시 재시도하고, 실패 시 False 리턴
        """
        for attempt in range(1, retries + 1):
            try:
                page.wait_for_load_state("networkidle", timeout=timeout)
                return True
            except PlaywrightTimeoutError:
                logging.warning(f"{desc} 로딩 시간 초과 ({attempt}/{retries}), 재시도합니다.")
                if attempt < retries:
                    try:
                        page.reload()
                        page.wait_for_load_state("networkidle", timeout=timeout)
                        return True
                    except PlaywrightTimeoutError:
                        continue
        return False

    try:
        page.goto(TARGET_URL)
        if not safe_wait_networkidle(page, desc="초기 페이지 이동"):  # 초기 로드 시도
            logging.error("초기 페이지 로드에 실패해 크롤러를 종료합니다.")
            return

        # 등록일순 정렬 및 페이지당 50개 설정
        page.wait_for_selector("select#orderTab")
        page.select_option("select#orderTab", value="2")
        page.select_option("select#pstab", value="50")
        page.click("button#dev-gi-search")
        if not safe_wait_networkidle(page, desc="필터 적용 후 페이지 이동"):  # 필터 적용 후
            logging.warning("필터 적용 후 페이지 로드에 문제가 발생했으나 계속 진행합니다.")

        # 총 공고 수 계산
        page.wait_for_selector("input#hdnGICnt", state="attached")
        total_jobs = int(
            page.query_selector("input#hdnGICnt").get_attribute("value").replace(",", "")
        )
        max_pages_estimate = math.ceil(total_jobs / MAX_ITEMS)
        logging.info(f"🔢 총 공고 수: {total_jobs}건 → 최대 페이지 수: {max_pages_estimate} 페이지")

        current_page = 1

        while True:
            logging.info(f"\n📄 현재 페이지: {current_page}")
            page.wait_for_selector("tr.devloopArea")
            rows = page.query_selector_all("tr.devloopArea")

            stop_crawl = False
            for row in rows[:MAX_ITEMS]:
                # 등록 시간 정보 읽기
                time_el = row.query_selector("td.odd .time")
                time_text = time_el.inner_text().strip() if time_el else ""
                # 1일 이내: '분 전 등록' 또는 '시간 전 등록'인 경우만 처리
                # title_el = row.query_selector("td.tplTit strong a")
                # title = title_el.inner_text().strip()
                # print(time_text, " : ",title)
                if "분 전 등록" in time_text or "시간 전 등록" in time_text:
                    try:
                        title_el = row.query_selector("td.tplTit strong a")
                        title = title_el.inner_text().strip()
                        link = f"https://www.jobkorea.co.kr{title_el.get_attribute('href')}"
                        company = row.query_selector("td.tplCo a").inner_text().strip()

                        etc_tags = row.query_selector_all("td.tplTit .etc .cell")
                        career = etc_tags[0].inner_text().strip() if len(etc_tags) > 0 else ""
                        education = etc_tags[1].inner_text().strip() if len(etc_tags) > 1 else ""
                        location = etc_tags[2].inner_text().strip() if len(etc_tags) > 2 else ""
                        emp_type = etc_tags[3].inner_text().strip() if len(etc_tags) > 3 else ""
                        salary = etc_tags[4].inner_text().strip() if len(etc_tags) > 4 else ""
                        position = etc_tags[5].inner_text().strip() if len(etc_tags) > 5 else ""

                        deadline_el = row.query_selector("td.odd .date")
                        deadline = deadline_el.inner_text().strip() if deadline_el else ""

                        description_el = row.query_selector("td.tplTit p.dsc")
                        description = description_el.inner_text().strip() if description_el else ""

                        data_batch.append([
                            company, title, career, education, emp_type,
                            location, salary, deadline, description, link
                        ])
                        total_items += 1
                        logging.info(f"{total_items:04d} | {company} | {title} | {time_text}")
                    except Exception as e:
                        logging.info(f"⚠️ 데이터 파싱 실패: {e}")
                else:
                    stop_crawl = True
                    break

            if stop_crawl:
                logging.info("⛔ 1일 이내 게시글 크롤링 완료 — 종료")
                break

            if current_page % SAVE_CNT == 0:
                save_to_csv(output_csv, data_batch, header)
                logging.info(f"✅ {SAVE_CNT}페이지마다 CSV 저장 완료 (총 {total_items}건)")
                data_batch.clear()

            random_sleep()
            periodic_rest(current_page)

            # 다음 페이지 이동 및 대기
            next_page = page.query_selector(f'div.tplPagination li a[data-page="{current_page + 1}"]')
            if next_page:
                next_page.click()
                if not safe_wait_networkidle(page, desc=f"{current_page+1}페이지 이동"):  # 페이지 전환
                    logging.warning(f"{current_page+1}페이지 로드 실패, 반복 중단")
                    break
                current_page += 1
            else:
                more_button = page.query_selector('a.btnPgnNext')
                if more_button and "disabled" not in (more_button.get_attribute("class") or ""):
                    more_button.click()
                    if not safe_wait_networkidle(page, desc="다음 블록 이동"):  # 블록 전환
                        logging.warning("다음 블록 로드 실패, 반복 중단")
                        break
                    current_page += 1
                else:
                    logging.info("🔚 페이지 탐색 종료")
                    break

        if data_batch:
            save_to_csv(output_csv, data_batch, header)
            logging.info(f"📝 마지막 데이터 저장 완료 (총 {total_items}건)")

    finally:
        browser.close()
        playwright.stop()

def run_crawler_with_retry(max_retries=3):
    """
    TimeoutError 등 예외 발생 시 전체 크롤러를 최대 max_retries까지 재시도
    """
    for attempt in range(1, max_retries + 1):
        try:
            logging.info(f"\n🚀 크롤러 실행 시도 {attempt}/{max_retries}")
            crawl_jobkorea_multiple_pages()
            logging.info("✅ 크롤러 정상 종료")
            break
        except Exception as e:
            logging.warning(f"⚠️ 크롤러 실행 중 예외 발생: {type(e).__name__} - {e}")
            if attempt < max_retries:
                logging.info("🔁 크롤러를 다시 실행합니다...")
            else:
                logging.error("❌ 최대 재시도 횟수 도달 — 크롤러 중단")