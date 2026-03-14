import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv
import os
from .JobPreprocessor import JobPreprocessor
import csv
import logs.log as log
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
        cursor.execute("DROP TABLE IF EXISTS subregions;")
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

        # 지역 대분류
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS regions (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE NOT NULL
        );
        """)

        # 지역 소분류
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS subregions (
            id SERIAL PRIMARY KEY,
            name TEXT NOT NULL,
            region_id INTEGER REFERENCES regions(id) ON DELETE CASCADE,
            UNIQUE(name, region_id)
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
            form INTEGER,
            subregion_id INTEGER REFERENCES subregions(id),
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

        logging.info("테이블 생성 완료")
    except Exception as e:
        logging.error(f"테이블 생성 중 오류 발생: {e}")
        raise


# ──────────────────────────────
# DATA INSERTION
# ──────────────────────────────
def csv_to_db(csv_path):
    conn = connect_postgres()
    try:
        cursor = conn.cursor()
        create_tables(conn, cursor)
        conn.commit()

        with open(csv_path, newline='', encoding='utf-8-sig') as csvfile:
            reader = csv.DictReader(csvfile)
            for i, row in enumerate(reader):
                try:
                    logging.info(f"{i}번째 행 입력")
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
                        deadline=JobPreprocessor.parse_deadline(row['마감일']),
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


def _ensure_subregion_and_get_id(cursor, region_name, subregion_name):
    region_id = _ensure_region_and_get_id(cursor, region_name)

    cursor.execute("""
        INSERT INTO subregions (name, region_id)
        VALUES (%s, %s)
        ON CONFLICT (name, region_id) DO NOTHING
        RETURNING id
    """, (subregion_name, region_id))
    result = cursor.fetchone()
    if result:
        return result[0]
    else:
        cursor.execute("""
            SELECT id FROM subregions
            WHERE name = %s AND region_id = %s
        """, (subregion_name, region_id))
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

    # 2. 지역 ID 확보
    if region and isinstance(region, tuple) and len(region) == 2 and region[1]:
        region_name, subregion_name = region
        subregion_id = _ensure_subregion_and_get_id(cursor, region_name, subregion_name)
    else:
        subregion_id = None

    # 3. recruits 테이블에 삽입
    cursor.execute("""
        INSERT INTO recruits (
            company_id,
            announcement_name,
            experience,
            education,
            form,
            subregion_id,
            annual_salary,
            deadline,
            link
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (company_id, announcement_name, deadline) DO NOTHING
        RETURNING id
    """, (
        company_id,
        announcement_name,
        experience,
        education,
        form,
        subregion_id,
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
        logging.info(f"[SKIPPED - DUPLICATE] {company_name} / {announcement_name} / {deadline} 은 이미 존재하여 삽입되지 않았습니다.")

    conn.commit()
