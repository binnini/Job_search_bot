"""
trigram GIN 인덱스 성능 벤치마크

인덱스 활성화 vs 비활성화(강제 seqscan) 상태에서
EXPLAIN ANALYZE 실행 시간을 비교합니다.
"""

import os
import re
import sys
import time
import statistics

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "localhost"),
    "port": os.getenv("POSTGRES_PORT", "5432"),
    "dbname": os.getenv("POSTGRES_DB", "recruit_db"),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "1234"),
}

# 테스트할 검색 키워드 (실제 사용 패턴 반영)
TEST_KEYWORDS = [
    # 2글자 영문 (trigram 최소 단위 미달)
    "AI", "ML", "Go", "QA",
    # 짧은 영문 3~4글자 (히트율 높음)
    "iOS", "Java", "React", "Vue", "Ruby",
    # 중간 영문 5~7글자
    "Swift", "Scala", "Kafka", "Spark", "Redis", "MySQL", "Linux",
    # 긴 영문 / 복합어 (히트율 낮음)
    "Python", "Django", "FastAPI", "TypeScript", "JavaScript",
    "Kubernetes", "TensorFlow", "PostgreSQL", "Elasticsearch",
    "GraphQL", "RabbitMQ", "Terraform", "Prometheus", "Airflow",
    "SpringBoot", "MLOps", "DevOps", "Golang", "Rust",
    # 짧은 한국어 (히트율 높음)
    "신입", "경력", "개발자", "백엔드", "프론트",
    # 중간 한국어
    "머신러닝", "블록체인", "클라우드", "보안", "인공지능",
    # 멀티워드 한국어
    "데이터 엔지니어", "클라우드 엔지니어", "자연어처리",
    "소프트웨어 엔지니어", "데이터 분석",
]

REPEAT = 3  # 각 쿼리를 몇 번 반복할지 (통계적 안정성)


def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def extract_execution_time_ms(explain_output: list[str]) -> float:
    """EXPLAIN ANALYZE 출력에서 실제 실행 시간(ms) 추출"""
    for line in reversed(explain_output):
        m = re.search(r"Execution Time:\s+([\d.]+)\s+ms", line)
        if m:
            return float(m.group(1))
    # Planning Time만 있을 경우 fallback
    for line in explain_output:
        m = re.search(r"Planning Time:\s+([\d.]+)\s+ms", line)
        if m:
            return float(m.group(1))
    return -1.0


def run_explain(cur, sql: str, params: tuple) -> tuple[float, list[str]]:
    """EXPLAIN (ANALYZE, BUFFERS) 실행 후 (실행시간ms, 플랜라인) 반환"""
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}", params)
    rows = [r[0] for r in cur.fetchall()]
    ms = extract_execution_time_ms(rows)
    return ms, rows


def benchmark_query(conn, keyword: str, use_index: bool) -> list[float]:
    """
    announcement_name ILIKE 검색을 REPEAT 회 실행해 실행시간 목록 반환.
    use_index=False 이면 bitmapscan/indexscan 비활성화로 seqscan 강제.
    """
    sql = """
        SELECT r.id, r.announcement_name
        FROM recruits r
        WHERE r.announcement_name ILIKE %s
        LIMIT 50
    """
    pattern = f"%{keyword}%"
    times = []

    with conn.cursor() as cur:
        if not use_index:
            cur.execute("SET enable_bitmapscan = off")
            cur.execute("SET enable_indexscan = off")
        else:
            cur.execute("SET enable_bitmapscan = on")
            cur.execute("SET enable_indexscan = on")

        # 캐시 워밍업 1회 (측정 제외)
        cur.execute(sql, (pattern,))
        cur.fetchall()

        for _ in range(REPEAT):
            ms, _ = run_explain(cur, sql, (pattern,))
            times.append(ms)

    return times


def benchmark_tag_query(conn, keyword: str, use_index: bool) -> list[float]:
    """
    tag name ILIKE 검색 (JOIN) 성능 측정
    """
    sql = """
        SELECT DISTINCT r.id, r.announcement_name
        FROM recruits r
        JOIN recruit_tags rt ON rt.recruit_id = r.id
        JOIN tags t ON t.id = rt.tag_id
        WHERE t.name ILIKE %s
        LIMIT 50
    """
    pattern = f"%{keyword}%"
    times = []

    with conn.cursor() as cur:
        if not use_index:
            cur.execute("SET enable_bitmapscan = off")
            cur.execute("SET enable_indexscan = off")
        else:
            cur.execute("SET enable_bitmapscan = on")
            cur.execute("SET enable_indexscan = on")

        cur.execute(sql, (pattern,))
        cur.fetchall()

        for _ in range(REPEAT):
            ms, _ = run_explain(cur, sql, (pattern,))
            times.append(ms)

    return times


def get_table_stats(conn) -> dict:
    """테이블 크기 정보 조회"""
    stats = {}
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM recruits")
        stats["recruits_count"] = cur.fetchone()[0]

        cur.execute("SELECT COUNT(*) FROM tags")
        stats["tags_count"] = cur.fetchone()[0]

        cur.execute("""
            SELECT pg_size_pretty(pg_total_relation_size('recruits')) AS total,
                   pg_size_pretty(pg_relation_size('recruits')) AS heap
        """)
        row = cur.fetchone()
        stats["recruits_total_size"] = row[0]
        stats["recruits_heap_size"] = row[1]

        # 인덱스 존재 여부 확인
        cur.execute("""
            SELECT indexname, indexdef
            FROM pg_indexes
            WHERE tablename IN ('recruits', 'tags')
              AND indexdef ILIKE '%trgm%'
        """)
        stats["trigram_indexes"] = cur.fetchall()

    return stats


def print_result(label: str, times_with: list[float], times_without: list[float]):
    avg_with = statistics.mean(times_with)
    avg_without = statistics.mean(times_without)
    speedup = avg_without / avg_with if avg_with > 0 else float("inf")
    reduction_pct = (1 - avg_with / avg_without) * 100 if avg_without > 0 else 0

    print(f"\n  [{label}]")
    print(f"    seqscan (인덱스 없음): avg={avg_without:.2f}ms  "
          f"(samples={[f'{t:.1f}' for t in times_without]})")
    print(f"    trigram GIN (인덱스): avg={avg_with:.2f}ms  "
          f"(samples={[f'{t:.1f}' for t in times_with]})")
    print(f"    → 속도 향상: {speedup:.1f}x  /  응답시간 {reduction_pct:.0f}% 감소")
    return {
        "label": label,
        "avg_without_ms": round(avg_without, 2),
        "avg_with_ms": round(avg_with, 2),
        "speedup_x": round(speedup, 1),
        "reduction_pct": round(reduction_pct, 1),
    }


def main():
    print("=" * 60)
    print("trigram GIN 인덱스 성능 벤치마크")
    print("=" * 60)

    conn = get_conn()
    conn.autocommit = True

    # 테이블 통계
    stats = get_table_stats(conn)
    print(f"\n[DB 현황]")
    print(f"  recruits 행 수: {stats['recruits_count']:,}건")
    print(f"  tags 행 수:     {stats['tags_count']:,}건")
    print(f"  recruits 테이블 크기: {stats['recruits_total_size']}")
    print(f"\n  trigram 인덱스 목록:")
    if stats["trigram_indexes"]:
        for name, defn in stats["trigram_indexes"]:
            print(f"    - {name}")
            print(f"      {defn}")
    else:
        print("    (없음)")

    results = []

    print(f"\n[announcement_name ILIKE 검색] — 각 키워드 {REPEAT}회 반복")
    for kw in TEST_KEYWORDS:
        times_with = benchmark_query(conn, kw, use_index=True)
        times_without = benchmark_query(conn, kw, use_index=False)
        r = print_result(f'"{kw}"', times_with, times_without)
        results.append(r)

    # 종합 요약
    speedups = [r["speedup_x"] for r in results]
    helped = [r for r in results if r["speedup_x"] >= 2.0]   # 실질적으로 도움된 케이스
    neutral = [r for r in results if r["speedup_x"] < 2.0]   # 효과 없거나 미미한 케이스

    print("\n" + "=" * 60)
    print(f"[종합 요약] — {len(TEST_KEYWORDS)}개 키워드")
    print(f"  전체 평균 속도 향상: {statistics.mean(speedups):.1f}x")
    print(f"  중앙값:              {statistics.median(speedups):.1f}x")
    print(f"  최대:                {max(speedups):.1f}x  ({results[speedups.index(max(speedups))]['label']})")
    print(f"  최소:                {min(speedups):.1f}x  ({results[speedups.index(min(speedups))]['label']})")
    print(f"\n  인덱스 실효 케이스 (2x 이상, {len(helped)}개):")
    print(f"    평균 {statistics.mean(r['speedup_x'] for r in helped):.1f}x  "
          f"/ 최대 {max(r['speedup_x'] for r in helped):.1f}x")
    print(f"\n  효과 미미 케이스 (<2x, {len(neutral)}개):")
    for r in sorted(neutral, key=lambda x: x["speedup_x"]):
        print(f"    {r['label']}: {r['speedup_x']}x "
              f"({r['avg_without_ms']}ms → {r['avg_with_ms']}ms)")

    conn.close()
    print("=" * 60)


if __name__ == "__main__":
    main()
