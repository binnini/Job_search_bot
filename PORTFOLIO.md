# Job Search Bot
**채용 공고 자동 수집 · 검색 · 알림 시스템**

`Python` `Playwright` `PostgreSQL` `Discord.py` `Cron`

---

## Overview

잡코리아에서 매일 신규 채용 공고를 자동으로 수집하고, Discord를 통해 사용자가 자연어로 검색하거나 관심 조건을 구독하면 맞춤 공고를 DM으로 자동 알림하는 end-to-end 데이터 파이프라인을 설계·구현했다.

- 크롤링 → 정제 → 저장 → 검색 · 알림까지 전 과정 직접 구현
- 50개 테스트케이스 기반 검색 품질 측정 및 반복 개선

---

## Architecture & Flow

```
[Cron 06:00 매일]
        │
        ▼
[Scraper] ── Playwright headless browser
        │  · 등록일순 정렬, 페이지당 50건
        │  · 1일 이내 공고만 수집 (등록 시간 텍스트 파싱)
        │  · 5페이지(250건)마다 배치 저장
        │  · 실패 시 최대 3회 자동 재시도
        │
        ▼
[JobPreprocessor]
        │  · 경력 / 연봉 / 학력 / 고용형태 / 지역 → 숫자 코드 정규화
        │  · 연봉 범위 검증 (600 ~ 50,000만원)
        │  · 태그 동의어 정규화 (JAVA → Java, Vue → Vue.js 등)
        │  · 이상값 NULL 처리 + data_quality_log 기록
        │
        ▼
[PostgreSQL]
        │  · companies / regions / subregions / recruits / tags / recruit_tags
        │  · ON CONFLICT DO NOTHING → 중복 공고 자동 skip
        │  · pg_trgm 인덱스 → 공고명 ILIKE 고속 검색
        │  · 복합 인덱스 (deadline + form / deadline + experience)
        │
        ▼
[Discord Bot]
        ├─ 자연어 검색: extract_filters() → SQL 쿼리 → 결과 반환
        └─ 구독 알림: 24h 주기 태스크 → 신규 공고 매칭 → DM 발송
                     notification_log로 중복 발송 방지
```

---

## Implemented

| 영역 | 구현 내용 |
|---|---|
| **크롤링** | Playwright 기반 동적 페이지 크롤링. 랜덤 UA · sleep · periodic rest로 차단 회피. 네트워크 타임아웃 3회 재시도 |
| **데이터 정제** | `JobPreprocessor` 클래스 — 6개 필드 파싱 + 유효성 검사. 정제 이벤트를 `data_quality_log`에 배치 기록 |
| **DB 설계** | 정규화 5개 테이블 (회사 · 지역 · 공고 · 태그 · 관계). 복합 인덱스 + trigram 인덱스로 검색 성능 확보 |
| **자연어 검색** | `extract_filters()` — 지역 · 고용형태 · 경력 · 연봉 · 마감일 · 기업명을 regex로 구조화 파싱. 동의어 사전 적용 (FE → 프론트엔드 등). AND 검색 결과 없을 시 OR 폴백 |
| **구독 알림** | 사용자별 공통 프로필 필터 + 다중 키워드 구독. `notification_log`로 중복 발송 방지. 1회 최대 10건 DM |
| **품질 관리** | `generate_quality_report()` — 완전성 · 연봉 분포 · 경력 분포 · 위반 샘플 포함 리포트 자동 생성 |
| **운영 자동화** | Cron 06:00 매일 실행. 날짜별 로그 파일 분리 |

---

## Trouble Shooting

### 1. BeautifulSoup → Selenium → Playwright (크롤링 차단 우회)

**Problem**
잡코리아는 JavaScript로 렌더링되는 동적 페이지로, `BeautifulSoup`으로는 렌더링 완료 전 HTML을 수집하기 때문에 채용 공고 데이터를 가져올 수 없었다. 동적 렌더링을 지원하는 `Selenium`으로 교체했으나, 사이트의 봇 탐지 시스템에 의해 자동화 접근으로 감지되어 크롤링이 차단되었다.

**Solution**
실제 사용자의 커서 동작을 브라우저 레벨에서 재현하는 `Playwright`로 교체. Selenium보다 낮은 수준에서 브라우저를 직접 제어하여 봇 탐지를 우회했다. 추가로 랜덤 User-Agent, 페이지간 랜덤 sleep, 주기적 rest를 적용해 탐지 가능성을 낮췄다.

---

### 2. LLM → 정규식 전환 (검색 필터 추출)

**Problem**
사용자 쿼리에서 검색 조건을 추출하기 위해 `Mistral 7B` → `Gemma3:4b` 순으로 로컬 LLM을 사용했으나 쿼리당 수 초의 응답 지연, Ollama 서버 상시 의존, JSON 파싱 실패 문제가 있었다. 또한 실제로 LLM이 추출하는 조건들을 분석하니 지역 · 고용형태 · 경력 · 연봉 등 모두 패턴이 명확한 정형 데이터였다.

**Solution**
LLM을 제거하고 정규식 기반 `extract_filters()`로 교체. Ollama · LangChain 의존성을 완전히 제거하고 응답 속도를 **수 초 → 밀리초**로 개선. 7개 필터 모두 동작하며 결과도 결정론적으로 예측 가능해졌다.

---

### 3. 검색 정확도: 50개 테스트케이스 기반 버그 수정

**Problem**
50개 테스트케이스 실행 결과 42/50 통과. 실패 8건의 원인을 분석하니 3가지 버그로 압축됐다.

- `company_name` 추출이 처리된 필터가 제거된 `remaining` 대신 원본 `query` 기준으로 동작 → 경력 값이 동시에 기업명으로 오분류
- `개발자`, `백엔드`, `디자이너` 등 직무 키워드가 `"X 공고"` 패턴에 매칭되어 `company_name`으로 오인
- STOPWORD를 문자열 치환으로 제거 → `"데이터 분석"` → `"데 터 분석"` 복합 명사 파괴

**Solution**
`remaining` 기준으로 변경, `JOB_KEYWORDS` 제외 집합 추가, STOPWORD 제거를 토큰 단위 처리로 변경.

| | 통과 | 실패 |
|---|---|---|
| 수정 전 | 42 / 50 | 8 |
| 수정 후 | **49 / 50** | 1 (DB에 해당 공고 없는 의도된 케이스) |

---

### 4. 연봉 이상값으로 인한 검색 품질 오염

**Problem**
구독 알림 테스트 중 "연봉 5,000만원 이상" 조건에 6,388건이 매칭되는 이상 현상 발견. DB를 조회하니 `372억원` 등 극단값이 존재했다. `parse_salary()`가 범위 검사 없이 파싱된 숫자를 그대로 저장하는 구조가 원인이었다.

**Solution**
데이터 거버넌스 3계층 구축.

- **Validation Gate** — 수집 시 범위 초과값 즉시 NULL 처리 (600 ~ 50,000만원)
- **data_quality_log** — 이상값 발생 이력 추적 (field, rule, 원본값, 파싱값)
- **clean_existing_data()** — 기존 DB 소급 정제 + `generate_quality_report()` 현황 출력

정제 후 연봉 평균 **5,067 → 4,026만원** 정상화.

---

### 5. 대용량 테이블 초기화 성능 (DELETE → TRUNCATE)

**Problem**
`recruit_tags`(89만 건) 테이블을 `DELETE FROM`으로 초기화 시 `tags` 테이블 단계에서 **6분 이상** 멈추는 현상 발생. 추가로 Discord Bot이 SQLAlchemy 세션을 유지 중이어서 `ACCESS EXCLUSIVE` 락 대기도 발생.

**Solution**
`TRUNCATE TABLE ... RESTART IDENTITY CASCADE`로 교체. 행 단위가 아닌 페이지 단위 삭제로 대용량 테이블에서 즉시 완료. `CASCADE`로 외래키 의존 테이블을 한 번에 처리.

---

## Results

| 항목 | 수치 |
|---|---|
| **일 처리 공고 (평일)** | 평균 ~6,400건 (50건/페이지 × 약 128페이지) |
| **일 처리 공고 (주말)** | 평균 ~740건 |
| **2주 크롤링 누적** | 66,805건 처리 (2025.07.15 ~ 07.28 실측) |
| **2주 DB 예상 적재** | 약 47,000 ~ 53,000건 (중복 제거 후) |
| 수집 기업 수 | 6,335개 |
| 태그 종류 / 공고 연결 | 3,664종 / 59,294건 |
| 검색 정확도 | 42 / 50 → **49 / 50** (테스트케이스 기반) |
| 연봉 데이터 정제 | 이상값 제거 후 평균 5,067 → **4,026만원** |
| 검색 응답 속도 | LLM 수 초 → 정규식 **밀리초** |
| DB 연결 오버헤드 | 10,000회 → **1회** (Connection Pool 도입) |
| 메모리 절감 | FAISS + KR-SBERT 제거 → **~730MB** 회수 |
