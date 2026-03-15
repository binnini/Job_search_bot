# Job Search Bot
**채용 공고 자동 수집 · 검색 · 알림 시스템**

`Python` `Playwright` `PostgreSQL` `Discord.py` `EXAONE 3.5 7.8B` `Ollama` `Cron`

---

## Overview

잡코리아에서 매일 신규 채용 공고를 자동으로 수집하고, Discord를 통해 자연어로 검색하거나 관심 조건을 구독하면 맞춤 공고를 DM으로 자동 알림하는 end-to-end 데이터 파이프라인을 설계·구현했다.

- 크롤링 → 정제 → 저장 → 검색 · 알림까지 전 과정 직접 구현
- testset 100건 기반 검색 품질 측정 후, LLM 3가지 방안으로 수치 개선 증명

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
[EXAONE 3.5 7.8B via Ollama]  ← 방안 3: LLM 시맨틱 태깅
        │  · 공고명 + 기존 태그 → 직무·기술 태그 자동 생성
        │  · 공고명에 없는 키워드로도 검색 가능
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
        ├─ 자연어 검색
        │    extract_filters() → expand_keyword() → SQL → rerank() → 결과 반환
        └─ 구독 알림 (24h)
             expand_keyword() → 신규 공고 매칭 → rerank() → DM 발송
             notification_log로 중복 발송 방지
```

---

## Implemented

| 영역 | 구현 내용 |
|---|---|
| **크롤링** | Playwright 기반 동적 페이지 크롤링. 랜덤 UA · sleep · periodic rest로 차단 회피. 네트워크 타임아웃 3회 재시도 |
| **데이터 정제** | `JobPreprocessor` — 6개 필드 파싱 + 유효성 검사. 정제 이벤트를 `data_quality_log`에 배치 기록 |
| **DB 설계** | 정규화 5개 테이블 (회사·지역·공고·태그·관계). 복합 인덱스 + trigram 인덱스로 검색 성능 확보 |
| **자연어 검색** | `extract_filters()` — 지역·고용형태·경력·연봉·마감일·기업명을 regex로 구조화 파싱. 동의어 사전 적용. AND 검색 결과 없을 시 OR 폴백 |
| **방안 1: 키워드 확장** | EXAONE으로 구독·검색 키워드를 동의어·기술 스택으로 확장. OR 매칭으로 recall 향상. 과확장 방지 프롬프트 설계 |
| **방안 2: 재순위** | 10건 배치 LLM 관련도 평가 후 점수 순 재정렬. 검색·구독 알림 양쪽 적용 |
| **방안 3: 시맨틱 태깅** | 크롤링 시 EXAONE으로 공고 시맨틱 태그 자동 생성. `tag_recruits.py`로 소급 태깅 |
| **구독 알림** | 사용자별 공통 프로필 필터 + 다중 키워드 구독. `notification_log`로 중복 발송 방지. 1회 최대 10건 DM |
| **품질 관리** | `generate_quality_report()` — 완전성·연봉 분포·위반 샘플 리포트 자동 생성 |
| **운영 자동화** | Cron 06:00 매일 실행. LLM 태깅 자동 연동. 날짜별 로그 파일 분리 |

---

## Trouble Shooting

### 1. BeautifulSoup → Selenium → Playwright (크롤링 차단 우회)

**Problem**
잡코리아는 JavaScript로 렌더링되는 동적 페이지로, `BeautifulSoup`으로는 데이터를 수집할 수 없었다. `Selenium`으로 교체했으나 봇 탐지에 의해 차단되었다.

**Solution**
브라우저 레벨에서 직접 제어하는 `Playwright`로 교체. 랜덤 User-Agent, 페이지간 랜덤 sleep, 주기적 rest를 추가해 탐지 가능성을 낮췄다.

---

### 2. LLM → 정규식 전환 (검색 필터 추출)

**Problem**
`Mistral 7B` → `Gemma3:4b`로 쿼리 필터를 추출했으나 쿼리당 수 초 지연, JSON 파싱 실패, Ollama 상시 의존 문제가 있었다. 추출 조건들을 분석하니 지역·고용형태·경력·연봉 모두 정형 패턴이었다.

**Solution**
LLM을 제거하고 정규식 기반 `extract_filters()`로 교체. 응답 속도 **수 초 → 밀리초**, Ollama·LangChain 의존성 완전 제거, 7개 필터 모두 결정론적으로 동작.

---

### 3. 검색 정확도: 50개 테스트케이스 기반 버그 수정

**Problem**
50개 테스트케이스 실행 결과 42/50 통과. 실패 원인을 분석하니 3가지 버그로 압축됐다.

- `company_name` 추출이 원본 `query` 기준으로 동작 → 경력 값이 동시에 기업명으로 오분류
- 직무 키워드(`개발자`, `백엔드` 등)가 `"X 공고"` 패턴에 매칭되어 `company_name`으로 오인
- STOPWORD를 문자열 치환으로 제거 → `"데이터 분석"` → `"데 터 분석"` 복합 명사 파괴

**Solution**
`remaining` 기준 변경, `JOB_KEYWORDS` 제외 집합 추가, STOPWORD 토큰 단위 처리.

| | 통과 | 실패 |
|---|---|---|
| 수정 전 | 42 / 50 | 8 |
| 수정 후 | **49 / 50** | 1 (DB에 해당 공고 없는 의도된 케이스) |

---

### 4. 연봉 이상값으로 인한 검색 품질 오염

**Problem**
"연봉 5,000만원 이상" 조건에 6,388건 매칭. DB에 `372억원` 등 극단값 존재. `parse_salary()`가 범위 검사 없이 그대로 저장하는 구조가 원인.

**Solution**
데이터 거버넌스 3계층 구축.

- **Validation Gate** — 수집 시 범위 초과값 즉시 NULL 처리 (600 ~ 50,000만원)
- **data_quality_log** — 이상값 발생 이력 추적 (field, rule, 원본값, 파싱값)
- **clean_existing_data()** — 기존 DB 소급 정제 + `generate_quality_report()` 현황 출력

정제 후 연봉 평균 **5,067 → 4,026만원** 정상화.

---

### 5. LLM 키워드 과확장 억제

**Problem**
방안 1(키워드 확장) 초기 구현 시 "관련된 키워드"를 요청하는 프롬프트가 상위 개념까지 포함하여 매칭 건수 +86% 폭증 (서비스기획: 1,291 → 10,691건).

**Solution**
"동의어·기술 스택만, 상위 개념 금지" + 나쁜 예시 추가로 프롬프트 강화. 매칭 증가율 **+86% → +30%**로 억제. 방안 2 재순위와 조합하여 recall 증가 + precision 보완 구조로 운영.

---

### 6. 방안 3 Before/After 결과 동일 — testset 편향 발견

**Problem**
LLM 태깅 적용 후 `evaluate.py` 측정 결과가 Before와 완전히 동일(Hit@5=52%, Hit@10=58%). testset 쿼리가 공고명 기반으로 생성되어 태그 추가 효과가 반영되지 않는 편향이 원인이었다.

**Solution**
공고명에 없는 동의어 쿼리로 평가하는 `evaluate_tagging.py`를 별도 작성. Before(공고명 매칭만) vs After(공고명+LLM 태그 매칭) 비교.

→ **Recall@10: 37.8% → 88.9% (+51.1%p)** 확인.

---

## Results

| 항목 | 수치 |
|---|---|
| **누적 수집 공고** | 약 18만 건 (유효 공고 약 3만 건) |
| **일 처리 공고 (평일)** | 평균 ~6,400건 |
| **일 처리 공고 (주말)** | 평균 ~740건 |
| **수집 기업 수** | 6,335개 |
| **태그 종류 / 공고 연결** | 3,664종 / 59,294건 |
| **검색 정확도** | 42 / 50 → **49 / 50** (테스트케이스 기반) |
| **연봉 데이터 정제** | 이상값 제거 후 평균 5,067 → **4,026만원** |
| **검색 응답 속도** | LLM 수 초 → 정규식 **밀리초** |
| **DB 연결 오버헤드** | 10,000회 → **1회** (Connection Pool) |
| **메모리 절감** | FAISS + KR-SBERT 제거 → **~730MB** 회수 |
| **방안 1: 키워드 확장** | 구독 매칭 건수 **+30%** (recall 향상) |
| **방안 2: 재순위** | Precision@10 **45.0% → 64.0%** (+19.0%p) |
| **방안 3: 시맨틱 태깅** | 동의어 Recall@10 **37.8% → 88.9%** (+51.1%p) |
