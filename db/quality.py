"""
데이터 품질 리포트 생성 및 기존 데이터 정제 모듈.
"""
from datetime import datetime
from .base import connect_postgres, release_connection
from .JobPreprocessor import SALARY_MIN, SALARY_MAX, EXPERIENCE_MAX


def clean_existing_data() -> dict:
    """
    기존 DB 데이터에 유효성 규칙을 소급 적용.
    허용 범위를 벗어난 값을 NULL로 업데이트하고 data_quality_log에 기록.
    """
    conn = connect_postgres()
    batch_id = f"backfill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    result = {"salary_cleaned": 0, "experience_cleaned": 0}

    try:
        cur = conn.cursor()

        # 연봉 이상값 → NULL
        cur.execute("""
            WITH updated AS (
                UPDATE recruits
                SET annual_salary = NULL
                WHERE annual_salary IS NOT NULL
                  AND (annual_salary < %s OR annual_salary > %s)
                RETURNING id, annual_salary
            )
            INSERT INTO data_quality_log
                (batch_id, announcement_name, field, rule, parsed_value)
            SELECT %s, r.announcement_name,
                'annual_salary',
                CASE
                    WHEN u.annual_salary < %s THEN 'below_minimum(%s)'
                    ELSE 'above_maximum(%s)'
                END,
                u.annual_salary::TEXT
            FROM updated u
            JOIN recruits r ON r.id = u.id
        """, (SALARY_MIN, SALARY_MAX, batch_id, SALARY_MIN, SALARY_MIN, SALARY_MAX))
        result["salary_cleaned"] = cur.rowcount

        # 경력 이상값 → NULL
        cur.execute("""
            WITH updated AS (
                UPDATE recruits
                SET experience = NULL
                WHERE experience IS NOT NULL
                  AND (experience < 0 OR experience > %s)
                RETURNING id, experience
            )
            INSERT INTO data_quality_log
                (batch_id, announcement_name, field, rule, parsed_value)
            SELECT %s, r.announcement_name,
                'experience', 'above_maximum(%s)', u.experience::TEXT
            FROM updated u
            JOIN recruits r ON r.id = u.id
        """, (EXPERIENCE_MAX, batch_id, EXPERIENCE_MAX))
        result["experience_cleaned"] = cur.rowcount

        conn.commit()
        return result
    finally:
        release_connection(conn)


def generate_quality_report() -> str:
    conn = connect_postgres()
    lines = []

    try:
        cur = conn.cursor()

        lines.append("=" * 60)
        lines.append(f"  데이터 품질 리포트")
        lines.append(f"  생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 60)

        # ── 1. 완전성 (Completeness) ─────────────────────────────
        lines.append("\n[1. 완전성 (Completeness)]")
        cur.execute("""
            SELECT
                COUNT(*) AS total,
                COUNT(annual_salary) AS has_salary,
                COUNT(experience) AS has_experience,
                COUNT(subregion_id) AS has_region,
                COUNT(form) AS has_form,
                COUNT(education) AS has_education
            FROM recruits
        """)
        row = cur.fetchone()
        total, has_salary, has_exp, has_region, has_form, has_edu = row

        lines.append(f"  총 공고 수: {total:,}건")
        if total > 0:
            for label, count in [
                ("연봉", has_salary), ("경력", has_exp), ("지역", has_region),
                ("고용형태", has_form), ("학력", has_edu),
            ]:
                pct = count / total * 100
                lines.append(f"  {label} 입력률: {pct:.1f}% ({count:,}건)")

        # ── 2. 연봉 분포 ─────────────────────────────────────────
        lines.append("\n[2. 연봉 분포 (만원/년, NULL 제외)]")
        cur.execute("""
            SELECT
                COUNT(*) AS cnt,
                MIN(annual_salary),
                MAX(annual_salary),
                ROUND(AVG(annual_salary)) AS avg,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY annual_salary) AS p25,
                PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY annual_salary) AS p50,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY annual_salary) AS p75,
                PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY annual_salary) AS p95
            FROM recruits
            WHERE annual_salary IS NOT NULL
        """)
        r = cur.fetchone()
        if r and r[0]:
            cnt, mn, mx, avg, p25, p50, p75, p95 = r
            lines.append(f"  유효 데이터: {cnt:,}건")
            lines.append(f"  최솟값: {int(mn):,}만원")
            lines.append(f"  25th:   {int(p25):,}만원")
            lines.append(f"  중앙값: {int(p50):,}만원")
            lines.append(f"  75th:   {int(p75):,}만원")
            lines.append(f"  95th:   {int(p95):,}만원")
            lines.append(f"  최댓값: {int(mx):,}만원")
            lines.append(f"  평균:   {int(avg):,}만원")
        else:
            lines.append("  연봉 데이터 없음")

        # ── 3. 경력 분포 ─────────────────────────────────────────
        lines.append("\n[3. 경력 분포]")
        cur.execute("""
            SELECT
                CASE
                    WHEN experience = 0 THEN '신입'
                    WHEN experience BETWEEN 1 AND 3 THEN '1~3년'
                    WHEN experience BETWEEN 4 AND 7 THEN '4~7년'
                    WHEN experience >= 8 THEN '8년 이상'
                END AS band,
                COUNT(*) AS cnt
            FROM recruits
            WHERE experience IS NOT NULL
            GROUP BY band
            ORDER BY MIN(experience)
        """)
        exp_rows = cur.fetchall()
        if exp_rows:
            for band, cnt in exp_rows:
                lines.append(f"  {band}: {cnt:,}건")
        else:
            lines.append("  경력 데이터 없음")

        # ── 4. 고용형태 분포 ─────────────────────────────────────
        lines.append("\n[4. 고용형태 분포]")
        cur.execute("""
            SELECT et.name, COUNT(r.id) AS cnt
            FROM employment_types et
            JOIN recruits r ON r.form = et.id
            GROUP BY et.id, et.name
            ORDER BY cnt DESC
        """)
        for name, cnt in cur.fetchall():
            lines.append(f"  {name}: {cnt:,}건")

        # ── 5. 데이터 품질 이벤트 요약 ───────────────────────────
        lines.append("\n[5. 데이터 품질 이벤트 (data_quality_log)]")
        cur.execute("SELECT COUNT(*) FROM data_quality_log")
        total_events = cur.fetchone()[0]
        lines.append(f"  누적 위반 건수: {total_events:,}건")

        cur.execute("""
            SELECT field, rule, COUNT(*) AS cnt
            FROM data_quality_log
            GROUP BY field, rule
            ORDER BY cnt DESC
        """)
        event_rows = cur.fetchall()
        if event_rows:
            for field, rule, cnt in event_rows:
                lines.append(f"  - {field} / {rule}: {cnt:,}건")
        else:
            lines.append("  품질 이벤트 없음")

        # ── 6. 최근 배치 품질 이벤트 샘플 ───────────────────────
        lines.append("\n[6. 최근 위반 샘플 (최대 5건)]")
        cur.execute("""
            SELECT company_name, announcement_name, field, rule, original_value, parsed_value
            FROM data_quality_log
            ORDER BY created_at DESC
            LIMIT 5
        """)
        samples = cur.fetchall()
        if samples:
            for company, title, field, rule, orig, parsed in samples:
                lines.append(f"  [{field}/{rule}] {company} | {title}")
                lines.append(f"    원본: {orig!r} → 파싱: {parsed!r} → NULL 처리")
        else:
            lines.append("  샘플 없음")

    finally:
        release_connection(conn)

    return "\n".join(lines)
