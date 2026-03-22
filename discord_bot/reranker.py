"""
EXAONE 기반 구독 알림 공고 재순위 모듈 (방안 2).

- rerank(): 매칭된 공고 리스트를 구독 키워드 관련도 순으로 재정렬
- 한 번의 LLM 호출로 여러 공고를 배치 평가하여 속도 최적화
"""
import logging
import requests
from db.io import RecruitOut

OLLAMA_URL = "http://192.168.219.114:11434/api/generate"
MODEL = "exaone3.5:7.8b"
BATCH_SIZE = 10  # 한 번의 LLM 호출로 평가할 공고 수


def _build_prompt(keyword: str, recruits: list[RecruitOut]) -> str:
    lines = []
    for i, r in enumerate(recruits, 1):
        tags = ", ".join(r.tags[:5]) if r.tags else "없음"
        lines.append(f"{i}. {r.announcement_name} | 태그: {tags}")

    recruit_text = "\n".join(lines)
    return f"""구독 키워드: '{keyword}'

아래 채용 공고들이 이 키워드와 얼마나 관련 있는지 0~10점으로 평가해줘.
숫자만 쉼표로 출력. 다른 설명 없이.

{recruit_text}

점수:"""


def _parse_scores(raw: str, n: int) -> list[float]:
    """LLM 출력에서 점수 리스트 파싱. 파싱 실패 시 5.0으로 채움."""
    try:
        first_line = raw.strip().splitlines()[0]
        scores = []
        for token in first_line.replace("，", ",").split(","):
            token = token.strip()
            try:
                scores.append(float(token))
            except ValueError:
                # 숫자가 아닌 토큰 무시
                continue
        # 개수 맞추기
        while len(scores) < n:
            scores.append(5.0)
        return scores[:n]
    except Exception:
        return [5.0] * n


def rerank(keyword: str, recruits: list[RecruitOut]) -> list[RecruitOut]:
    """공고 리스트를 keyword 관련도 순으로 재정렬. 실패 시 원본 순서 반환."""
    if not recruits:
        return recruits

    scored = []
    for start in range(0, len(recruits), BATCH_SIZE):
        batch = recruits[start:start + BATCH_SIZE]
        prompt = _build_prompt(keyword, batch)
        try:
            resp = requests.post(OLLAMA_URL, json={
                "model": MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": 40},
            }, timeout=30)
            resp.raise_for_status()
            raw = resp.json()["response"]
            scores = _parse_scores(raw, len(batch))
        except Exception as e:
            logging.warning(f"[reranker] LLM 호출 실패: {e}")
            scores = [5.0] * len(batch)

        for recruit, score in zip(batch, scores):
            scored.append((recruit, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    logging.info(f"[reranker] '{keyword}' 재순위 완료: {len(scored)}건")
    return [r for r, _ in scored]
