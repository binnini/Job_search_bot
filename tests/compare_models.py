"""
3개 모델의 태깅 품질 및 속도 비교 스크립트.

Usage:
    python tests/compare_models.py
"""
import json
import time
import sys
import os
import requests
from dotenv import load_dotenv

load_dotenv(override=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.io import read_recruitOut
from db.JobPreprocessor import JobPreprocessor

OLLAMA_URL = "http://192.168.219.114:11434/api/generate"
MODELS = ["gemma3:4b", "qwen2.5:7b", "exaone3.5:7.8b"]
N_SAMPLES = 10


def build_prompt(recruit) -> str:
    tags = ", ".join(recruit.tags) if recruit.tags else "없음"

    return f"""채용 공고에서 직무·기술·산업 키워드 태그를 추출해줘.

규칙:
- 공백 없는 단어만 (예: 백엔드, Java, 데이터분석, UI디자인)
- 직무/기술/산업 도메인만 포함 (지역·연봉·고용형태·기업명 제외)
- 5~8개, 쉼표 구분, 태그만 출력

예시 출력: 백엔드, Java, Spring, REST API, MySQL, 서버개발

공고명: {recruit.announcement_name}
기존태그: {tags}

태그:"""


def call_llm(model: str, prompt: str) -> tuple[str, float]:
    t0 = time.perf_counter()
    resp = requests.post(OLLAMA_URL, json={
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 80},
    }, timeout=60)
    resp.raise_for_status()
    elapsed = time.perf_counter() - t0
    return resp.json()["response"].strip(), elapsed


def main():
    print("DB에서 샘플 로딩 중...")
    recruits = read_recruitOut(limit=5000, order_desc=True)

    import random
    random.seed(42)
    samples = random.sample(recruits, N_SAMPLES)

    print(f"{N_SAMPLES}개 샘플 선택 완료\n")
    print("=" * 70)

    model_stats = {m: {"times": [], "outputs": []} for m in MODELS}

    for i, recruit in enumerate(samples, 1):
        print(f"\n[{i:02d}] {recruit.company_name} / {recruit.announcement_name[:40]}")
        print(f"     기존태그: {', '.join(recruit.tags[:5]) if recruit.tags else '없음'}")
        prompt = build_prompt(recruit)

        for model in MODELS:
            try:
                output, elapsed = call_llm(model, prompt)
                model_stats[model]["times"].append(elapsed)
                model_stats[model]["outputs"].append(output)
                short_name = model.split(":")[0]
                print(f"  [{short_name:12s}] ({elapsed:.1f}s) {output[:80]}")
            except Exception as e:
                print(f"  [{model:20s}] 오류: {e}")
                model_stats[model]["times"].append(None)
                model_stats[model]["outputs"].append("")

    # 요약
    print("\n" + "=" * 70)
    print("  모델별 평균 응답 시간")
    print("=" * 70)
    for model in MODELS:
        times = [t for t in model_stats[model]["times"] if t is not None]
        avg = sum(times) / len(times) if times else 0
        est_30k = avg * 30655 / 3600
        print(f"  {model:20s} 평균 {avg:.1f}초  →  30k건 소급 예상 {est_30k:.0f}시간")
    print("=" * 70)

    # JSON 저장
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "compare_models_result.json")
    output = []
    for i, recruit in enumerate(samples):
        entry = {
            "id": i + 1,
            "company": recruit.company_name,
            "title": recruit.announcement_name,
            "existing_tags": recruit.tags or [],
            "results": {},
        }
        for model in MODELS:
            times = model_stats[model]["times"]
            outputs = model_stats[model]["outputs"]
            entry["results"][model] = {
                "tags": outputs[i],
                "elapsed_sec": round(times[i], 2) if times[i] else None,
            }
        output.append(entry)

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\n결과 저장: {out_path}")


if __name__ == "__main__":
    main()
