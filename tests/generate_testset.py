"""
DB에서 공고를 샘플링하고 EXAONE으로 자연어 검색 쿼리를 역생성하여 testset.json을 만든다.

Usage:
    python tests/generate_testset.py            # 기본 100개
    python tests/generate_testset.py --n 200    # 200개
    python tests/generate_testset.py --n 50 --out tests/testset_small.json
"""
import argparse
import json
import os
import random
import sys
import time

import requests
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.io import read_recruitOut
from db.JobPreprocessor import JobPreprocessor

OLLAMA_URL = "http://192.168.219.114:11434/api/generate"
MODEL = "exaone3.5:7.8b"
DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "testset.json")


def build_prompt(recruit) -> str:
    tags = ", ".join(recruit.tags) if recruit.tags else "없음"
    salary = JobPreprocessor.stringify_salary(recruit.annual_salary)
    experience = JobPreprocessor.stringify_experience(recruit.experience)
    region = recruit.region_name or "미상"
    form = JobPreprocessor.stringify_form(recruit.form)

    return f"""다음은 채용 공고 정보입니다.

기업명: {recruit.company_name}
공고명: {recruit.announcement_name}
지역: {region}
고용형태: {form}
경력: {experience}
연봉: {salary}
기술 태그: {tags}

이 채용 공고를 찾고 싶은 구직자가 검색창에 입력할 법한 자연어 검색어를 딱 1개만 작성해주세요.
- 공고명이나 기업명을 그대로 쓰지 말 것
- 구직자 관점의 구어체로 작성 (예: "서울 백엔드 신입 공고", "연봉 4천 이상 정규직")
- 검색어만 출력하고 다른 설명은 쓰지 말 것"""


def call_llm(prompt: str) -> str:
    resp = requests.post(OLLAMA_URL, json={
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 60},
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["response"].strip().strip('"').strip()


def sample_diverse(recruits, n: int):
    """태그/지역/고용형태 분포를 고려한 다양한 샘플링."""
    # 태그 있는 것 우선, 나머지는 랜덤
    with_tags = [r for r in recruits if r.tags]
    without_tags = [r for r in recruits if not r.tags]

    random.shuffle(with_tags)
    random.shuffle(without_tags)

    # 태그 있는 것 70%, 없는 것 30%
    n_tags = min(int(n * 0.7), len(with_tags))
    n_notags = min(n - n_tags, len(without_tags))

    return with_tags[:n_tags] + without_tags[:n_notags]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=100, help="생성할 테스트케이스 수")
    parser.add_argument("--out", type=str, default=DEFAULT_OUT, help="출력 JSON 경로")
    parser.add_argument("--seed", type=int, default=42, help="랜덤 시드")
    args = parser.parse_args()

    random.seed(args.seed)

    print(f"DB에서 공고 로딩 중...")
    all_recruits = read_recruitOut(limit=5000, order_desc=True)
    print(f"총 {len(all_recruits)}건 로드됨")

    sampled = sample_diverse(all_recruits, args.n)
    print(f"{len(sampled)}건 샘플링 완료 → EXAONE 쿼리 생성 시작\n")

    testset = []
    failed = 0

    for i, recruit in enumerate(sampled, 1):
        prompt = build_prompt(recruit)
        try:
            query = call_llm(prompt)
            entry = {
                "id": i,
                "recruit_id": recruit.id,
                "company_name": recruit.company_name,
                "announcement_name": recruit.announcement_name,
                "query": query,
            }
            testset.append(entry)
            print(f"[{i:03d}/{len(sampled)}] {recruit.announcement_name[:30]!r}")
            print(f"         → {query}")
        except Exception as e:
            failed += 1
            print(f"[{i:03d}/{len(sampled)}] 실패: {e}")

        time.sleep(0.1)  # 서버 부하 방지

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(testset, f, ensure_ascii=False, indent=2)

    print(f"\n완료: {len(testset)}개 생성, {failed}개 실패")
    print(f"저장 위치: {args.out}")


if __name__ == "__main__":
    main()
