"""
EXAONE 기반 채용 공고 의미 태깅 모듈.

- call_tagger(): 공고 1건 → 태그 리스트 반환
- tag_recruit_batch(): recruit_id 리스트 일괄 태깅 후 DB 저장
"""
import re
import logging
import requests
from typing import Optional

OLLAMA_URL = "http://192.168.219.114:11434/api/generate"
MODEL = "exaone3.5:7.8b"

PROMPT_TEMPLATE = """채용 공고에서 직무·기술·산업 키워드 태그를 추출해줘.

규칙:
- 공백 없는 단어만 (예: 백엔드, Java, 데이터분석, UI디자인)
- 직무/기술/산업 도메인만 포함 (지역·연봉·고용형태·기업명 제외)
- 5~8개, 쉼표 구분, 태그만 출력

예시 출력: 백엔드, Java, Spring, REST API, MySQL, 서버개발

공고명: {announcement_name}
기존태그: {existing_tags}

태그:"""


def _parse_tags(raw: str) -> list[str]:
    """LLM 출력에서 태그 리스트를 파싱하고 정제."""
    # 첫 줄만 사용 (부연 설명 제거)
    first_line = raw.strip().splitlines()[0]
    # 쉼표 구분 분리
    tags = [t.strip() for t in first_line.split(",") if t.strip()]
    # 길이 필터: 1~20자, 공백 2개 이상 포함 태그 제거
    tags = [t for t in tags if 1 <= len(t) <= 20 and t.count(" ") <= 1]
    return tags


def call_tagger(announcement_name: str, existing_tags: list[str]) -> Optional[list[str]]:
    """공고 1건에 대해 EXAONE으로 태그를 생성하고 반환.
    실패 시 None 반환.
    """
    prompt = PROMPT_TEMPLATE.format(
        announcement_name=announcement_name,
        existing_tags=", ".join(existing_tags) if existing_tags else "없음",
    )
    try:
        resp = requests.post(OLLAMA_URL, json={
            "model": MODEL,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 60},
        }, timeout=30)
        resp.raise_for_status()
        raw = resp.json()["response"]
        tags = _parse_tags(raw)
        return tags if tags else None
    except Exception as e:
        logging.warning(f"[tagger] LLM 호출 실패: {e}")
        return None


def tag_recruit_batch(recruit_ids: list[int]) -> dict:
    """recruit_id 리스트를 받아 태깅 후 DB에 저장.
    반환: {'tagged': N, 'skipped': N, 'failed': N}
    """
    from sqlalchemy.orm import joinedload
    from db.io import SessionLocal
    from db.models import Recruit, Tag, Region

    session = SessionLocal()
    stats = {"tagged": 0, "skipped": 0, "failed": 0}

    try:
        recruits = (
            session.query(Recruit)
            .options(joinedload(Recruit.tags))
            .filter(Recruit.id.in_(recruit_ids))
            .all()
        )

        for recruit in recruits:
            existing_tag_names = [t.name for t in recruit.tags]
            new_tags = call_tagger(recruit.announcement_name, existing_tag_names)

            if new_tags is None:
                stats["failed"] += 1
                continue

            added = 0
            for tag_name in new_tags:
                if tag_name in existing_tag_names:
                    continue
                tag = session.query(Tag).filter_by(name=tag_name).first()
                if not tag:
                    tag = Tag(name=tag_name)
                    session.add(tag)
                    session.flush()
                recruit.tags.append(tag)
                added += 1

            session.commit()
            if added > 0:
                stats["tagged"] += 1
            else:
                stats["skipped"] += 1

    except Exception as e:
        session.rollback()
        logging.error(f"[tagger] 배치 처리 오류: {e}")
    finally:
        session.close()

    return stats
