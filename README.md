# 채용 공고 검색 디스코드 봇

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)
![Discord](https://img.shields.io/badge/Discord.py-2.x-5865F2?logo=discord&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-1.x-2EAD33?logo=playwright&logoColor=white)

잡코리아 채용 공고를 매일 자동 수집하고, 디스코드에서 자연어로 검색하거나 관심 조건을 구독해두면 신규 공고를 DM으로 받을 수 있는 봇입니다.

---

## 주요 기능

- **자연어 검색** — `서울 백엔드 정규직 신입 공고` 형태의 구어체 쿼리를 정규식으로 파싱해 SQL WHERE 절로 변환
- **구독 알림** — 키워드·지역·경력·연봉 조건을 등록해두면 24시간마다 신규 공고를 DM으로 수신
- **데이터 품질 관리** — 수집 시점에 이상값을 차단하고 `data_quality_log` 테이블에 이력 기록
- **검색 품질 보장** — AND 검색 결과 없으면 자동으로 OR 폴백, 동의어 사전으로 `FE → 프론트엔드` 치환

---

## 아키텍처

```
[잡코리아]
    │  Playwright 크롤링 (systemd 타이머, 일 1회)
    ▼
[PostgreSQL]
  ├─ recruits            공고 (경력/형태/연봉/마감일)
  ├─ companies           기업명
  ├─ tags                기술스택 등 키워드
  ├─ regions/subregions  지역 대·소분류
  ├─ user_profiles       사용자 공통 필터 (지역/형태/경력/연봉)
  ├─ user_subscriptions  키워드 구독
  ├─ notification_log    알림 발송 이력
  └─ data_quality_log    파싱 이상값 이력
    │
    └─ [Discord Bot]
         ├─ 자연어 검색  →  extract_filters() → SQL WHERE 절
         ├─ 구독 등록/해제 (드롭다운 UI)
         └─ 정기 알림 (24h 백그라운드 태스크)
```

### 검색 흐름

```
사용자 입력: "서울 백엔드 정규직 신입 공고"
        │
        ▼
extract_filters()        정규식 기반 파싱 — DB 불필요, ms 단위 응답
  { region: "서울", keyword: "백엔드", form: "정규직", max_experience: 0 }
        │
        ▼
search_recruits_by_filter()   SQLAlchemy ORM
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
| FAISS 벡터 검색 제거 | 공고 데이터가 키워드 목록 형식 → 시맨틱 임베딩 효과 낮음, 730MB 상시 점유 대비 효과 미미 |
| PostgreSQL SQL 검색 | 지역/경력/연봉/형태는 정형 컬럼 → WHERE 절이 벡터 거리보다 정확 |
| Connection Pool (psycopg2) | 크롤링 배치 삽입 시 연결 생성 오버헤드 제거 |
| AND → OR 폴백 | 복합 키워드 검색 시 결과 0건 방지 |
| pg_trgm GIN 인덱스 | `announcement_name ILIKE` 검색을 Seq Scan → Bitmap Index Scan으로 개선 |

> 의사결정 과정의 상세 배경과 트러블슈팅은 [TROUBLE_SHOOT.md](TROUBLE_SHOOT.md)에 기록되어 있습니다.

---

## 데이터 품질

수집 시점에 이상값을 차단하고, 위반 건은 `data_quality_log` 테이블에 이력을 남깁니다.

```python
SALARY_MIN, SALARY_MAX = 600, 50000  # 만원

def validate_salary(value):
    if value < SALARY_MIN: return None, "below_minimum"
    if value > SALARY_MAX: return None, "above_maximum"
    return value, None
```

이상값 정제 전후 연봉 평균: **5,067만원 → 4,026만원**

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

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. `.env` 파일 작성

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
python main.py              # 최근 1일치 수집 (기본)
python main.py --days 7     # 최근 N일치 수집
python main.py --fresh      # 기존 데이터 전체 삭제 후 재수집
```

### 4. 디스코드 봇 실행

```bash
python -m discord_bot.bot
```

### 5. systemd 자동화 (Linux)

`systemd.txt` 파일을 참고하여 크롤러와 봇을 서비스로 등록합니다.

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
