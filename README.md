# 채용 공고 검색 디스코드 봇

<div align="center">
  <img src="img/job_search_bot1.png" alt="봇 사용 예시 1" width="600"/>
  <img src="img/job_search_bot2.png" alt="봇 사용 예시 2" width="600"/>
</div>

---

## 요약

잡코리아에서 채용 공고를 수집하고 PostgreSQL에 저장하며, 디스코드 봇을 통해 자연어 검색과 구독 알림을 제공하는 파이프라인입니다.

---

## 아키텍처

```
[잡코리아]
    │  Playwright 크롤링 (systemd 타이머, 일 1회)
    ▼
[PostgreSQL]
  ├─ recruits       (공고: 경력/형태/연봉/마감일)
  ├─ companies      (기업명)
  ├─ tags           (기술스택 등 키워드)
  ├─ regions        (지역 대분류)
  ├─ subregions     (지역 소분류)
  ├─ user_profiles  (사용자 공통 필터)
  ├─ user_subscriptions (키워드 구독)
  ├─ notification_log   (알림 발송 이력)
  └─ data_quality_log   (파싱 이상값 이력)
    │
    ├─ [Discord Bot]
    │    ├─ 자연어 검색  →  extract_filters (정규식) → SQL WHERE 절
    │    ├─ 구독 등록/해제 (드롭다운 UI)
    │    └─ 정기 알림 (24h 백그라운드 태스크)
```

### 검색 흐름

```
사용자 입력: "서울 백엔드 정규직 신입 공고"
        │
        ▼
extract_filters()  ← 정규식 기반 파싱 (DB 불필요, ms 단위 응답)
  { region: "서울", keyword: "백엔드", form: "정규직", max_experience: 0 }
        │
        ▼
search_recruits_by_filter()  ← SQLAlchemy ORM
  AND 검색 → 결과 없으면 OR 폴백
        │
        ▼
Discord 메시지 반환
```

---

## 주요 기술 결정

| 결정 | 이유 |
|------|------|
| Playwright (Selenium 대체) | 봇 탐지 우회를 위해 브라우저 레벨 직접 제어 필요 |
| 정규식 필터 추출 (LLM 제거) | 필터 대부분이 정형 패턴 — LLM 대비 응답 수 ms, 결정론적 |
| FAISS 벡터 검색 제거 | 공고 데이터가 키워드 목록 형식이라 시맨틱 임베딩 효과 낮음, 730MB 상시 점유 대비 효과 미미 |
| PostgreSQL SQL 검색 | 지역/경력/연봉/형태는 정형 컬럼 → WHERE 절이 벡터 거리보다 정확 |
| Connection Pool (psycopg2) | 크롤링 배치 삽입 시 연결 생성 오버헤드 제거 |
| AND → OR 폴백 | 복합 키워드 검색 시 결과 0건 방지 |

---

## DB 인덱스

검색 필터로 자주 쓰이는 컬럼에 인덱스를 생성합니다.

```sql
-- 단일 컬럼
CREATE INDEX idx_recruits_deadline   ON recruits(deadline);
CREATE INDEX idx_recruits_form       ON recruits(form);
CREATE INDEX idx_recruits_experience ON recruits(experience);
CREATE INDEX idx_recruits_salary     ON recruits(annual_salary);

-- 복합 (빈번한 필터 조합)
CREATE INDEX idx_recruits_deadline_form ON recruits(deadline, form);
CREATE INDEX idx_recruits_deadline_exp  ON recruits(deadline, experience);

-- 공고명 ILIKE 검색 (pg_trgm)
CREATE EXTENSION pg_trgm;
CREATE INDEX idx_recruits_name_trgm ON recruits USING gin(announcement_name gin_trgm_ops);
```

**EXPLAIN ANALYZE 비교 (announcement_name ILIKE '%백엔드%'):**

| | 플랜 | 실행 시간 |
|---|---|---|
| 인덱스 없음 | Seq Scan | 전체 테이블 스캔 |
| trigram 인덱스 | Bitmap Index Scan on idx_recruits_name_trgm | 후보군만 스캔 |

> 현재 규모(~14만 건)에서 수치 필터는 플래너가 Seq Scan을 선택하나, 데이터 증가 시 자동으로 인덱스 스캔으로 전환됩니다.

---

## 데이터 품질

수집 시점에 이상값을 차단하고 이력을 저장합니다.

```python
SALARY_MIN, SALARY_MAX = 600, 50000  # 만원

def validate_salary(value):
    if value < SALARY_MIN: return None, "below_minimum"
    if value > SALARY_MAX: return None, "above_maximum"
    return value, None
```

위반 건은 `data_quality_log` 테이블에 기록됩니다.

---

## 테스트

```bash
# 단위 테스트 (DB 불필요 — extract_filters 파싱 로직)
python -m pytest tests/ -v

# 통합 테스트 (실 DB 필요 — SQL 검색 결과 50케이스)
python tests/test_search.py

# 스냅샷 갱신 (extract_filters 수정 후 기준선 재설정)
python tests/test_search.py --update-snapshot
```

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. `.env` 파일 작성

`.env.example`을 복사하여 작성합니다.

```bash
cp .env.example .env
```

| 변수 | 설명 |
|------|------|
| `POSTGRES_HOST` | PostgreSQL 호스트 |
| `POSTGRES_PORT` | PostgreSQL 포트 (기본 5432) |
| `POSTGRES_DB` | 데이터베이스 이름 |
| `POSTGRES_USER` | 사용자 |
| `POSTGRES_PASSWORD` | 비밀번호 |
| `DISCORD_BOT_TOKEN` | 디스코드 봇 토큰 |
| `TARGET_URL` | 크롤링 대상 URL |
| `CRAWL_LOG_DIR` | 크롤링 로그 저장 경로 |

### 3. 크롤링 실행

```bash
# 최근 1일치 수집 (기본)
python main.py

# 최근 N일치 수집
python main.py --days 7

# 기존 데이터 전체 삭제 후 재수집
python main.py --fresh
```

### 4. 디스코드 봇 실행

```bash
python -m discord_bot.bot
```

### 5. systemd 자동화 (Linux)

`systemd.txt` 파일을 참고하여 크롤러와 봇을 서비스로 등록합니다.

---

## 디스코드 명령어

| 명령어 | 설명 |
|--------|------|
| `!도움` | 명령어 목록 |
| `!구독` | 필터(지역/형태/경력/연봉) + 키워드 등록 |
| `!내구독` | 현재 구독 조건 확인 |
| `!구독해제 <번호>` | 특정 키워드 구독 해제 |
| `!구독해제 전체` | 모든 구독 해제 |
| `!알림테스트` | 즉시 알림 조건 확인 및 DM 발송 |
| 자연어 입력 | 공고 검색 (예: `서울 백엔드 정규직 신입`) |

---

## 트러블슈팅

개발 과정에서 발생한 주요 문제와 해결 과정은 [TROUBLE_SHOOT.md](TROUBLE_SHOOT.md)에 기록되어 있습니다.
