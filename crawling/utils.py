import time
import random
import logging
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

def random_sleep(min_sec=1.5, max_sec=3.5):
    duration = random.uniform(min_sec, max_sec)
    logging.info(f"⏱ {duration:.2f}초 대기")
    time.sleep(duration)

def periodic_rest(current_page, every_n=20, min_rest=20.0, max_rest=40.0):
    if current_page % every_n == 0:
        rest_time = random.uniform(min_rest, max_rest)
        logging.info(f"🛌 {current_page}페이지 도달 — {rest_time:.1f}초 휴식")
        time.sleep(rest_time)

def safe_wait(
    page,
    *,
    selector: str = None,
    state: str = "visible",
    load_state: str = None,
    desc: str = None,
    retries: int = 3,
    timeout: int = 30000,
    retry_delay: float = 1.0
) -> bool:
    """
    - selector + state 조합으로 wait_for_selector 호출
    - load_state 지정 시 wait_for_load_state 호출
    - 둘 다 지정 불허 (selector 또는 load_state 중 하나만)
    - 실패 시 최대 retries 만큼 재시도, retry_delay 초 대기
    """
    if bool(selector) == bool(load_state):
        raise ValueError("selector 또는 load_state 중 하나만 지정해야 합니다.")
    desc = desc or (selector or f"load_state={load_state}")

    for attempt in range(1, retries + 1):
        try:
            if load_state:
                page.wait_for_load_state(load_state, timeout=timeout)
            else:
                page.wait_for_selector(selector, state=state, timeout=timeout)
            return True
        except PlaywrightTimeoutError as e:
            logging.warning(f"[{desc}] 대기 실패 {attempt}/{retries}: {e!r}")
            if attempt < retries:
                time.sleep(retry_delay)
                # networkidle 재시도 시 리로드 한 번만
                if load_state:
                    try:
                        page.reload()
                    except Exception:
                        pass
            else:
                logging.error(f"[{desc}] {retries}회 모두 실패했습니다.")
                return False
    return False