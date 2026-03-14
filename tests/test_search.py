"""
sql_search 통합 테스트 — 50개 케이스
결과는 tests/test_results.txt 에 출력됩니다.

스냅샷 비교 모드:
  tests/test_snapshots.json 이 존재하면 현재 필터 추출 결과와 비교하여
  회귀(regression) 여부를 함께 출력합니다.

스냅샷 갱신:
  python tests/test_search.py --update-snapshot
"""
from dotenv import load_dotenv
load_dotenv(override=True)

import json
import time
import sys
import os
from datetime import date
from discord_bot.llm import extract_filters, sql_search

_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_PATH = os.path.join(_DIR, "test_snapshots.json")

TEST_CASES = [
    # ── 단일 조건: 키워드 ──────────────────────────────────
    ("키워드 - 개발",           "개발자 공고 보여줘"),
    ("키워드 - 백엔드",         "백엔드 공고"),
    ("키워드 - 프론트엔드",     "프론트엔드 개발자 찾아줘"),
    ("키워드 - 마케팅",         "마케팅 공고 알려줘"),
    ("키워드 - 데이터 분석",    "데이터 분석 공고"),
    ("키워드 - 디자인",         "디자이너 채용 공고"),
    ("키워드 - 영업",           "영업직 공고 보여줘"),
    ("키워드 - 회계",           "회계 공고"),
    ("키워드 - CS",             "고객응대 공고"),
    ("키워드 - 물류",           "물류 공고 알려줘"),

    # ── 단일 조건: 지역 ──────────────────────────────────
    ("지역 - 서울",             "서울 공고"),
    ("지역 - 경기",             "경기 공고 보여줘"),
    ("지역 - 부산",             "부산 채용 공고"),
    ("지역 - 대전",             "대전 공고 찾아줘"),
    ("지역 - 인천",             "인천 공고"),

    # ── 단일 조건: 고용형태 ───────────────────────────────
    ("고용형태 - 정규직",       "정규직 공고 보여줘"),
    ("고용형태 - 계약직",       "계약직 공고"),
    ("고용형태 - 인턴",         "인턴 공고 찾아줘"),
    ("고용형태 - 프리랜서",     "프리랜서 공고"),
    ("고용형태 - 아르바이트",   "아르바이트 공고"),

    # ── 단일 조건: 경력 ──────────────────────────────────
    ("경력 - 신입",             "신입 공고"),
    ("경력 - 1년",              "경력 1년 공고"),
    ("경력 - 3년",              "경력 3년 이상 공고"),
    ("경력 - 5년",              "5년차 공고 보여줘"),

    # ── 단일 조건: 연봉 ──────────────────────────────────
    ("연봉 - 3000만원",         "연봉 3000만원 이상 공고"),
    ("연봉 - 4000만원",         "연봉 4천만원 이상 채용"),
    ("연봉 - 5000만원",         "연봉 5000만원 이상"),
    ("연봉 - 억 단위",          "연봉 1억 이상 공고"),

    # ── 복합 조건: 키워드 + 지역 ──────────────────────────
    ("키워드+지역 - 마케팅 서울",        "서울 마케팅 공고"),
    ("키워드+지역 - 개발 경기",          "경기 개발자 공고"),
    ("키워드+지역 - 영업 부산",          "부산 영업 공고"),
    ("키워드+지역 - 디자이너 서울",      "서울 디자이너 채용"),

    # ── 복합 조건: 키워드 + 고용형태 ──────────────────────
    ("키워드+고용형태 - 개발 정규직",    "개발자 정규직 공고"),
    ("키워드+고용형태 - 마케팅 인턴",    "마케팅 인턴 공고"),
    ("키워드+고용형태 - 디자인 계약직",  "디자인 계약직 채용"),

    # ── 복합 조건: 키워드 + 경력 ──────────────────────────
    ("키워드+경력 - 개발 신입",          "백엔드 신입 공고"),
    ("키워드+경력 - 영업 3년",           "영업 경력 3년 공고"),
    ("키워드+경력 - 회계 5년",           "회계 5년 이상 공고"),

    # ── 복합 조건: 3개 이상 ────────────────────────────────
    ("3개 - 개발+서울+정규직",           "서울 개발자 정규직 공고"),
    ("3개 - 마케팅+서울+신입",           "서울 마케팅 신입 공고"),
    ("3개 - 영업+경기+정규직",           "경기 영업 정규직 채용"),
    ("4개 - 개발+서울+정규직+신입",      "서울 백엔드 정규직 신입 공고"),
    ("4개 - 개발+서울+정규직+연봉",      "서울 개발자 정규직 연봉 4000만원 이상"),

    # ── 자연어 표현 ────────────────────────────────────────
    ("자연어 - 회사명",                  "카카오 공고 알려줘"),
    ("자연어 - 이번달 마감",             "이번달 마감 공고"),
    ("자연어 - 다음달",                  "다음달 마감 공고 보여줘"),
    ("자연어 - 억 단위 연봉",            "연봉 2억 공고"),
    ("자연어 - 복합 구어체",             "서울에서 신입으로 일할 수 있는 마케팅 공고 찾아줘"),

    # ── 결과 없는 케이스 ──────────────────────────────────
    ("결과없음 - 연봉 너무 높음",        "연봉 5억 이상 신입 공고"),
    ("결과없음 - 너무 좁은 조건",        "제주 데이터 분석 정규직 신입 연봉 5000만원 이상"),
]


def _serialize_filters(filters: dict) -> dict:
    """None 제거 + date 직렬화."""
    return {
        k: (v.isoformat() if isinstance(v, date) else v)
        for k, v in filters.items()
        if v is not None
    }


def _compare_filters(current: dict, snapshot: dict) -> tuple[bool, list]:
    """현재 필터와 스냅샷 비교. (일치 여부, 차이 목록) 반환."""
    diffs = []
    all_keys = set(current) | set(snapshot)
    for k in sorted(all_keys):
        c, s = current.get(k), snapshot.get(k)
        if c != s:
            diffs.append(f"{k}: 스냅샷={s!r} → 현재={c!r}")
    return len(diffs) == 0, diffs


def load_snapshots() -> dict:
    if not os.path.exists(SNAPSHOT_PATH):
        return {}
    with open(SNAPSHOT_PATH, encoding="utf-8") as f:
        return json.load(f)


def save_snapshots(snapshots: dict):
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as f:
        json.dump(snapshots, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 스냅샷 저장 완료: {SNAPSHOT_PATH}")


def update_snapshot():
    """현재 extract_filters 출력으로 스냅샷을 갱신."""
    snapshots = {}
    for desc, query in TEST_CASES:
        filters = _serialize_filters(extract_filters(query))
        snapshots[desc] = {"query": query, "filters": filters}
    save_snapshots(snapshots)


def run_tests(output_path=os.path.join(_DIR, "test_results.txt")):
    snapshots = load_snapshots()
    has_snapshot = bool(snapshots)

    lines = []
    passed = failed = 0
    filter_match = filter_mismatch = 0

    header = (
        "=" * 60
        + f"\n  sql_search 테스트 결과 (총 {len(TEST_CASES)}개)"
        + ("\n  📸 스냅샷 비교 활성화" if has_snapshot else "\n  ⚠️  스냅샷 없음 (--update-snapshot 으로 생성)")
        + "\n" + "=" * 60
    )
    lines.append(header)

    for idx, (desc, query) in enumerate(TEST_CASES, start=1):
        lines.append(f"\n[{idx:02d}] {desc}")
        lines.append(f"  Q: {query}")

        # 필터 추출 + 시간 측정
        t0 = time.perf_counter()
        filters = extract_filters(query)
        result = sql_search(query, limit=3)
        elapsed_ms = (time.perf_counter() - t0) * 1000

        active = _serialize_filters(filters)
        lines.append(f"  필터: {active}")

        # 스냅샷 비교
        if has_snapshot and desc in snapshots:
            snap_filters = snapshots[desc]["filters"]
            matched, diffs = _compare_filters(active, snap_filters)
            if matched:
                filter_match += 1
                lines.append("  필터 회귀: ✅ 스냅샷 일치")
            else:
                filter_mismatch += 1
                lines.append("  필터 회귀: ⚠️  스냅샷 불일치")
                for d in diffs:
                    lines.append(f"    {d}")

        # 결과 유무
        has_result = "조건에 맞는 채용 공고를 찾지 못했습니다" not in result
        if has_result:
            passed += 1
            lines.append(f"  결과: ✅ 공고 반환됨  ({elapsed_ms:.0f}ms)")
        else:
            failed += 1
            lines.append(f"  결과: ❌ 공고 없음  ({elapsed_ms:.0f}ms)")

        for line in result.splitlines():
            lines.append(f"    {line}")
        lines.append("-" * 60)

    # 요약
    summary_lines = [
        f"\n{'=' * 60}",
        f"  검색 결과:  총 {len(TEST_CASES)}개 | ✅ 반환됨 {passed}개 | ❌ 없음 {failed}개",
    ]
    if has_snapshot:
        summary_lines.append(
            f"  필터 회귀:  ✅ 일치 {filter_match}개 | ⚠️  불일치 {filter_mismatch}개"
        )
    summary_lines.append("=" * 60)
    lines.append("\n".join(summary_lines))

    output = "\n".join(lines)
    print(output)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n✅ 결과 저장 완료: {output_path}")


if __name__ == "__main__":
    if "--update-snapshot" in sys.argv:
        update_snapshot()
    else:
        run_tests()
