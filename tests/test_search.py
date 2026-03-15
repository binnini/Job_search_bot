"""
sql_search 통합 테스트 — 150개 케이스
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
from tests.test_cases import TEST_CASES

_DIR = os.path.dirname(os.path.abspath(__file__))
SNAPSHOT_PATH = os.path.join(_DIR, "test_snapshots.json")


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
