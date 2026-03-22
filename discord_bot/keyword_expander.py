"""
EXAONE 기반 구독 키워드 확장 모듈.

- expand_keyword(): 구독 키워드 1개 → 관련 키워드 리스트 반환
- 알림 발송 시 확장된 키워드로 OR 매칭하여 recall 향상
"""
import logging
import requests
from typing import Optional

OLLAMA_URL = "http://192.168.219.114:11434/api/generate"
MODEL = "exaone3.5:7.8b"

PROMPT_TEMPLATE = """채용 검색 쿼리: '{keyword}'

이 쿼리와 관련된 채용 공고 제목·태그에 나올 법한 키워드를 추출해줘.
직무명, 기술 스택, 직종 동의어를 포함하고 지역·연봉·고용형태는 제외해.

규칙:
- 공백 없는 단어만 (화살표·설명 금지)
- 5~10개, 쉼표 구분, 키워드만 출력

예시) 쿼리: 'Spring Boot API 서버 개발자'
출력: 백엔드,SpringBoot,Java,서버개발자,API서버,Kotlin,백엔드개발자,Spring

키워드:"""


def expand_keyword(keyword: str) -> list[str]:
    """키워드를 EXAONE으로 확장. 실패 시 원본 키워드만 반환."""
    prompt = PROMPT_TEMPLATE.format(keyword=keyword)
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 80},
        }, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["response"].strip().splitlines()[0]
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        tags = [t for t in tags if 1 <= len(t) <= 20]
        # 원본 키워드는 반드시 포함
        if keyword not in tags:
            tags = [keyword] + tags
        logging.info(f"[expander] '{keyword}' → {tags}")
        return tags
    except Exception as e:
        logging.warning(f"[expander] 키워드 확장 실패 ({keyword}): {e}")
        return [keyword]
