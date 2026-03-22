import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
from datetime import datetime
import os
from .JobPreprocessor import JobPreprocessor
import csv
import log_config
import logging

load_dotenv()

# ──────────────────────────────
# CONNECTION POOL
# ──────────────────────────────
_connection_pool = None

def init_connection_pool():
    global _connection_pool
    _connection_pool = pool.SimpleConnectionPool(
        minconn=1,
        maxconn=10,
        host=os.getenv("POSTGRES_HOST"),
        port=os.getenv("POSTGRES_PORT"),
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )
    logging.info("Connection Pool 초기화 완료")

def connect_postgres():
    global _connection_pool
    try:
        if _connection_pool is None:
            init_connection_pool()
        return _connection_pool.getconn()
    except psycopg2.OperationalError as e:
        logging.error(f"PostgreSQL 연결 실패: {e}")
        raise

def release_connection(conn):
    global _connection_pool
    if _connection_pool and conn:
        _connection_pool.putconn(conn)

# ──────────────────────────────
# TABLE CREATION & RESET
# ──────────────────────────────
def reset_tables():
    try:
        conn = connect_postgres()
        cursor = conn.cursor()

        logging.info("테이블 초기화 시작")

        # 의존성 역순으로 삭제
        cursor.execute("DROP TABLE IF EXISTS recruit_tags;")
        cursor.execute("DROP TABLE IF EXISTS tags;")
        cursor.execute("DROP TABLE IF EXISTS recruits;")
        cursor.execute("DROP TABLE IF EXISTS regions;")
        cursor.execute("DROP TABLE IF EXISTS companies;")

        # create_tables(conn=conn, cursor=cursor)

        conn.commit()
        logging.info("테이블 초기화 완료")
    except Exception as e:
        logging.error(f"테이블 초기화 중 오류 발생: {e}")
        raise
    finally:
        if 'conn' in locals():
            conn.close()


def create_tables(conn, cursor):
    try:
        logging.info("테이블 생성 시작")

        # 고용형태 차원 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS employment_types (
            id INTEGER PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
        """)
        cursor.executemany("""
            INSERT INTO employment_types (id, name) VALUES (%s, %s) ON CONFLICT DO NOTHING
        """, [
            (1,'정규직'),(2,'계약직'),(3,'인턴'),(4,'파견직'),(5,'프리랜서'),
            (6,'위촉직'),(7,'도급'),(8,'연수생'),(9,'병역특례'),(10,'아르바이트'),
        ])

        # 지역 대분류
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
        """)

        # 기업
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id SERIAL PRIMARY KEY,
            company_name TEXT UNIQUE NOT NULL
        );
        """)

        # 채용 공고
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recruits (
            id SERIAL PRIMARY KEY,
            company_id INTEGER REFERENCES companies(id),
            announcement_name TEXT,
            experience INTEGER,
            education INTEGER,
            form INTEGER REFERENCES employment_types(id),
            region_id INTEGER REFERENCES regions(id),
            subregion_name TEXT,
            annual_salary INTEGER,
            deadline DATE,
            link TEXT,
            UNIQUE (company_id, announcement_name, deadline)
        );
        """)

        # 태그
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
        """)

        # 태그-공고 관계
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS recruit_tags (
            recruit_id INTEGER REFERENCES recruits(id) ON DELETE CASCADE,
            tag_id INTEGER REFERENCES tags(id) ON DELETE CASCADE,
            PRIMARY KEY (recruit_id, tag_id)
        );
        """)

        # recruits.created_at 컬럼 마이그레이션 (기존 테이블 대응)
        cursor.execute("""
        ALTER TABLE recruits
        ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT NOW()
        """)

        # recruits.region_id 마이그레이션 (기존 테이블 대응)
        cursor.execute("""
        ALTER TABLE recruits
        ADD COLUMN IF NOT EXISTS region_id INTEGER REFERENCES regions(id)
        """)

        # subregion 비정규화 마이그레이션: subregion_name 컬럼 추가 및 subregions 테이블 제거
        cursor.execute("""
        ALTER TABLE recruits
        ADD COLUMN IF NOT EXISTS subregion_name TEXT
        """)
        # 기존 데이터 backfill: subregion_id → subregion_name
        cursor.execute("""
        DO $$ BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'recruits' AND column_name = 'subregion_id'
            ) THEN
                UPDATE recruits r
                SET subregion_name = s.name
                FROM subregions s
                WHERE r.subregion_id = s.id AND r.subregion_name IS NULL;
            END IF;
        END $$;
        """)
        cursor.execute("DROP TRIGGER IF EXISTS trg_sync_region_id ON recruits")
        cursor.execute("DROP FUNCTION IF EXISTS sync_region_id()")
        cursor.execute("ALTER TABLE recruits DROP COLUMN IF EXISTS subregion_id")
        cursor.execute("DROP TABLE IF EXISTS subregions CASCADE")

        # recruits.form FK 마이그레이션 (기존 테이블 대응)
        cursor.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'fk_recruits_form'
            ) THEN
                ALTER TABLE recruits ADD CONSTRAINT fk_recruits_form
                FOREIGN KEY (form) REFERENCES employment_types(id);
            END IF;
        END $$;
        """)

        # 알림 발송 이력
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id SERIAL PRIMARY KEY,
            discord_user_id TEXT NOT NULL,
            recruit_id INTEGER REFERENCES recruits(id) ON DELETE CASCADE,
            notified_at TIMESTAMP DEFAULT NOW(),
            UNIQUE (discord_user_id, recruit_id)
        );
        """)

        # 사용자 프로필 (공통 필터)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_profiles (
            discord_user_id TEXT PRIMARY KEY,
            region TEXT,
            form INTEGER,
            max_experience INTEGER,
            min_annual_salary INTEGER,
            updated_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # 키워드 구독 테이블
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_subscriptions (
            id SERIAL PRIMARY KEY,
            discord_user_id TEXT NOT NULL,
            keyword TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        # 데이터 품질 로그
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS data_quality_log (
            id SERIAL PRIMARY KEY,
            batch_id TEXT NOT NULL,
            company_name TEXT,
            announcement_name TEXT,
            field TEXT NOT NULL,
            rule TEXT NOT NULL,
            original_value TEXT,
            parsed_value TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_market_daily (
            date DATE PRIMARY KEY,
            total_valid_jobs INTEGER,
            new_jobs INTEGER,
            avg_salary INTEGER,
            top_tags JSONB,
            region_dist JSONB,
            experience_dist JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_sub_user_id
            ON user_subscriptions(discord_user_id)
        """)

        # 검색 필터 컬럼 인덱스
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_deadline    ON recruits(deadline)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_form        ON recruits(form)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_experience  ON recruits(experience)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_salary      ON recruits(annual_salary)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_region_id   ON recruits(region_id)")
        # 복합 인덱스: 가장 빈번한 필터 조합 (deadline 필수 + form/experience)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_deadline_form ON recruits(deadline, form)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_deadline_exp  ON recruits(deadline, experience)")
        # ILIKE 검색용 trigram 인덱스 (pg_trgm 필요)
        cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruits_name_trgm ON recruits USING gin(announcement_name gin_trgm_ops)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_name_trgm ON tags USING gin(name gin_trgm_ops)")
        # 태그 → 공고 방향 JOIN 인덱스 (tag_id 단독 인덱스 없으면 recruit_tags 풀스캔 발생)
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_recruit_tags_tag_id ON recruit_tags(tag_id)")

        logging.info("테이블 생성 완료")
    except Exception as e:
        logging.error(f"테이블 생성 중 오류 발생: {e}")
        raise


# ──────────────────────────────
# DATA INSERTION
# ──────────────────────────────
def clear_recruit_data():
    """채용 공고 관련 테이블 데이터 전체 삭제. user_subscriptions는 유지."""
    conn = connect_postgres()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            TRUNCATE TABLE recruit_tags, recruits, tags, companies, regions
            RESTART IDENTITY CASCADE
        """)
        conn.commit()
        logging.info("채용 공고 데이터 전체 삭제 완료")
    finally:
        release_connection(conn)


def ensure_tables():
    """봇 시작 시 등 단독으로 테이블을 보장할 때 사용."""
    conn = connect_postgres()
    try:
        cursor = conn.cursor()
        create_tables(conn, cursor)
        conn.commit()
    finally:
        release_connection(conn)


def batch_to_db(data_batch, use_llm_tagging: bool = False):
    """크롤링된 배치 데이터를 직접 DB에 삽입.
    data_batch는 [company, title, career, education, emp_type, location, salary, deadline, description, position, link] 리스트의 리스트.
    use_llm_tagging=True 이면 신규 삽입된 공고에 EXAONE 의미 태그를 추가로 부여한다.
    """
    conn = connect_postgres()
    batch_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    quality_events = []
    new_recruit_ids = []

    try:
        cursor = conn.cursor()
        create_tables(conn, cursor)
        conn.commit()

        for i, row in enumerate(data_batch):
            try:
                company, title, career, education, emp_type, location, salary, deadline, description, position, link = row
                desc_tags = JobPreprocessor.parse_explanation(description) or []
                pos_tags = [t.strip() for t in position.replace('·', ',').split(',') if t.strip()] if position else []
                all_tags = desc_tags + [t for t in pos_tags if t not in desc_tags]

                # 파싱 후 유효성 검사
                parsed_salary = JobPreprocessor.parse_salary(salary)
                parsed_experience = JobPreprocessor.parse_experience(career)

                validated_salary, salary_rule = JobPreprocessor.validate_salary(parsed_salary)
                validated_experience, exp_rule = JobPreprocessor.validate_experience(parsed_experience)

                if salary_rule:
                    quality_events.append((batch_id, company, title, 'annual_salary', salary_rule, salary, str(parsed_salary)))
                if exp_rule:
                    quality_events.append((batch_id, company, title, 'experience', exp_rule, career, str(parsed_experience)))

                recruit_id = _jobkorea_write(
                    conn=conn,
                    cursor=cursor,
                    company_name=company,
                    announcement_name=title,
                    experience=validated_experience,
                    education=JobPreprocessor.parse_education(education),
                    form=JobPreprocessor.parse_form(emp_type),
                    region=JobPreprocessor.parse_region(location),
                    annual_salary=validated_salary,
                    deadline=JobPreprocessor.parse_deadline(deadline),
                    tags=all_tags or None,
                    link=link,
                )
                if recruit_id:
                    new_recruit_ids.append(recruit_id)
            except Exception as e:
                conn.rollback()
                logging.warning(f"배치 {i}번째 행 처리 실패: {e}")

        # 품질 이벤트 일괄 기록
        if quality_events:
            cursor.executemany("""
                INSERT INTO data_quality_log
                    (batch_id, company_name, announcement_name, field, rule, original_value, parsed_value)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, quality_events)
            conn.commit()
            logging.info(f"데이터 품질 이벤트 {len(quality_events)}건 기록 (batch_id={batch_id})")

        # 신규 공고 LLM 태깅
        if use_llm_tagging and new_recruit_ids:
            from db.tagger import tag_recruit_batch
            stats = tag_recruit_batch(new_recruit_ids)
            logging.info(f"LLM 태깅 완료: 태깅됨={stats['tagged']} / 변화없음={stats['skipped']} / 실패={stats['failed']}")

    finally:
        release_connection(conn)

def csv_to_db(csv_path, today=None):
    """CSV 파일을 DB에 적재.
    today: parse_deadline 기준 날짜. 미지정 시 파일명에서 추출, 그것도 없으면 현재 날짜.
    """
    import re as _re
    from datetime import date as _date

    if today is None:
        m = _re.search(r'(\d{4})-(\d{2})-(\d{2})', csv_path)
        if m:
            today = _date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    conn = connect_postgres()
    try:
        cursor = conn.cursor()
        create_tables(conn, cursor)
        conn.commit()

        with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            for i, row in enumerate(reader):
                try:
                    _jobkorea_write(
                        conn=conn,
                        cursor=cursor,
                        company_name=row['기업명'],
                        announcement_name=row['공고명'],
                        experience=JobPreprocessor.parse_experience(row['경력']),
                        education=JobPreprocessor.parse_education(row['학력']),
                        form=JobPreprocessor.parse_form(row['형태']),
                        region=JobPreprocessor.parse_region(row['지역']),
                        annual_salary=JobPreprocessor.parse_salary(row['연봉']),
                        deadline=JobPreprocessor.parse_deadline(row['마감일'], today=today),
                        tags=JobPreprocessor.parse_explanation(row['설명']),
                        link=row['링크'],
                    )
                except Exception as e:
                    conn.rollback()
                    logging.warning(f"{i}번째 행 처리 실패: {e}")
    finally:
        release_connection(conn)

def _ensure_company_and_get_id(cursor, company_name):
    cursor.execute("""
        INSERT INTO companies (company_name)
        VALUES (%s)
        ON CONFLICT (company_name) DO NOTHING
        RETURNING id
    """, (company_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        cursor.execute("SELECT id FROM companies WHERE company_name = %s", (company_name,))
        return cursor.fetchone()[0]

def _ensure_tag_and_get_id(cursor, tag_name):
    cursor.execute("""
        INSERT INTO tags (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id
    """, (tag_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        cursor.execute("SELECT id FROM tags WHERE name = %s", (tag_name,))
        return cursor.fetchone()[0]

def _ensure_region_and_get_id(cursor, region_name):
    cursor.execute("""
        INSERT INTO regions (name)
        VALUES (%s)
        ON CONFLICT (name) DO NOTHING
        RETURNING id
    """, (region_name,))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        cursor.execute("SELECT id FROM regions WHERE name = %s", (region_name,))
        return cursor.fetchone()[0]



def _jobkorea_write(
    conn,
    cursor,
    company_name,
    announcement_name,
    experience,
    education,
    form,
    region,
    annual_salary,
    deadline,
    tags,
    link
):
    # 1. 회사 ID 확보
    company_id = _ensure_company_and_get_id(cursor, company_name)

    # 2. 지역 ID 확보 및 subregion_name 추출
    region_id = None
    subregion_name = None
    if region and isinstance(region, tuple):
        region_name, sub = region
        region_id = _ensure_region_and_get_id(cursor, region_name)
        subregion_name = sub

    # 3. recruits 테이블에 삽입
    cursor.execute("""
        INSERT INTO recruits (
            company_id,
            announcement_name,
            experience,
            education,
            form,
            region_id,
            subregion_name,
            annual_salary,
            deadline,
            link
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (company_id, announcement_name, deadline) DO NOTHING
        RETURNING id
    """, (
        company_id,
        announcement_name,
        experience,
        education,
        form,
        region_id,
        subregion_name,
        annual_salary,
        deadline,
        link
    ))
    result = cursor.fetchone()

    # 4. 태그 연결
    if result:
        recruit_id = result[0]
        if tags:
            for tag in tags:
                tag_id = _ensure_tag_and_get_id(cursor, tag)
                cursor.execute("""
                    INSERT INTO recruit_tags (recruit_id, tag_id)
                    VALUES (%s, %s)
                    ON CONFLICT DO NOTHING
                """, (recruit_id, tag_id))
    else:
        recruit_id = None
        logging.info(f"[SKIPPED - DUPLICATE] {company_name} / {announcement_name} / {deadline} 은 이미 존재하여 삽입되지 않았습니다.")

    conn.commit()
    return recruit_id
