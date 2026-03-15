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

PROMPT_TEMPLATE = """구직자가 '{keyword}' 직무로 채용 공고를 구독합니다.
같은 직무를 다르게 표현한 동의어·기술 스택만 추가해줘. 상위 개념이나 관련 직무는 포함하지 마.

규칙:
- 공백 없는 단어만 (화살표·설명 금지)
- 원래 키워드 포함 5~8개
- 쉼표 구분, 키워드만 출력

나쁜 예 (너무 넓음): ML엔지니어, 데이터분석, AI, 소프트웨어개발
좋은 예: ML엔지니어, MLOps, 머신러닝엔지니어, 딥러닝, PyTorch, TensorFlow, 모델배포

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
