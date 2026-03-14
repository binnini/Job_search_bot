# 채용 공고 검색 디스코드 봇

> 취업 준비생이 자연어로 채용 공고를 검색할 수 있는 RAG 기반 대화형 검색 시스템

<div align="center">
  <img src="img/job_search_bot1.png" width="600"/>
  <img src="img/job_search_bot2.png" width="600"/>
</div>

---

## 1. 개요

| 항목 | 내용 |
|------|------|
| 개발 기간 | 2025.xx ~ 2025.xx |
| 운영 환경 | Mac Mini M4 32GB (홈 서버) |
| 수집 규모 | 2주간 약 14만 건 (일 1만 건 제한) |
| 인터페이스 | Discord Bot |

### 개발 배경
취업 준비 중 채용 사이트를 매번 직접 검색하는 방식이 번거롭다고 느꼈습니다.
"AI 스타트업 백엔드 공고 중 마감 안 된 것 보여줘"처럼 자연어로 물어보면
바로 결과를 주는 대화형 검색 도구를 만들고자 시작했습니다.

---

## 2. 시스템 아키텍처

### 전체 구조

```
[잡코리아]
    │ Playwright 크롤링 (매일 06:00, cron job)
    ▼
[CSV (일별 스냅샷)]
    │ ETL 파이프라인 (JobPreprocessor)
    ▼
[PostgreSQL] ◄──────────────────────────────┐
    │ KR-SBERT 임베딩                        │
    ▼                                        │
[FAISS 벡터 DB]                             │
                                             │
[Discord 사용자]                             │
    │ 자연어 질문                             │
    ▼                                        │
[Local LLM, Gemma3:4b]                      │
    │ 필터 추출 (JSON)                        │
    ▼                                        │
[FAISS MMR 유사도 검색] → Top-5 ID ────────►│
                                    상세 조회 │
                                             ▼
                                    [결과 → Discord]
```

### ETL 파이프라인

```
Extract          Transform                   Load
크롤링      →    JobPreprocessor        →    PostgreSQL
(Playwright)     - 경력/학력/형태 인코딩     FAISS
                 - 마감일 파싱               (KR-SBERT 임베딩)
                 - 월급 → 연봉 환산
                 - 태그 분리
```

### DB 스키마

```
regions ──< subregions ──< recruits >── companies
                               │
                          recruit_tags
                               │
                             tags
```

- `recruits`: 채용 공고 (경력·학력·형태는 Integer 코드로 저장)
- `companies`, `regions`, `subregions`: 정규화 분리
- `tags`: 공고 설명 키워드 (M:N 관계)
- 중복 방지: `UNIQUE(company_id, announcement_name, deadline)`

### RAG 검색 흐름

```
사용자 질문
    │
    ├─► Local LLM (Gemma3:4b)
    │       └─► JSON 필터 추출
    │           { "min_deadline": "2025/08/01" }
    │
    ├─► KR-SBERT 임베딩 → FAISS MMR 검색 (Top-5 ID)
    │
    └─► PostgreSQL 상세 조회 → Discord 응답
```

---

## 3. 핵심 구현

### 3-1. JobPreprocessor — 원시 데이터 정형화

크롤링 텍스트를 DB 적재 가능한 정형 데이터로 변환합니다.

| 원시 데이터 | 변환 결과 | 처리 방식 |
|-------------|-----------|-----------|
| `"경력 3년 이상"` | `3` | 정규식 숫자 추출 |
| `"대졸↑"` | `3` | 학력 레벨 매핑 |
| `"정규직"` | `1` | 고용형태 코드 매핑 |
| `"~06/10(화)"` | `date(2025, 6, 10)` | 정규식 날짜 파싱 |
| `"상시채용"` | `date(9999, 12, 31)` | Sentinel value |
| `"월 300만원"` | `3600` | 월급 → 연봉 환산 |
| `"AI, 백엔드, ..."` | `["AI", "백엔드"]` | 쉼표 분리 |

`parse_*` (문자열 → 숫자/날짜) / `stringify_*` (숫자 → 표시 문자열)
대칭 구조로 저장과 표시 로직을 분리했습니다.

### 3-2. 멱등성 보장 — 중복 없는 적재

크롤러 재실행 시 DB에 중복이 쌓이지 않도록 `ON CONFLICT DO NOTHING` 패턴을 사용했습니다.

```sql
INSERT INTO recruits (company_id, announcement_name, deadline, ...)
VALUES (...)
ON CONFLICT (company_id, announcement_name, deadline) DO NOTHING;
```

`companies`, `subregions`, `tags` 등 모든 참조 테이블에 동일 패턴 적용.

### 3-3. 이중 저장소 설계

| 저장소 | 역할 | 선택 이유 |
|--------|------|-----------|
| PostgreSQL | 조건 필터링 (마감일, 경력, 연봉 등) | 정형 데이터 범위 쿼리 |
| FAISS | 의미 유사도 검색 (공고 제목) | 자연어 → 벡터 검색 |

FAISS로 ID를 추출하고 PostgreSQL에서 상세 정보를 조회하는
2단계 구조로 각 저장소의 강점을 분리했습니다.

### 3-4. 벡터 DB 관리

- **임베딩 모델**: `snunlp/KR-SBERT-V40K-klueNLI-augSTS` (한국어 특화)
- **검색 방식**: MMR(Maximal Marginal Relevance) — 유사도 높은 결과 중 다양성 확보
- **만료 문서 자동 삭제**: 매일 ETL 실행 시 `deadline < today` 문서를 인덱스에서 제거하여 최신성 유지

### 3-5. Local LLM 기반 필터 추출

```
입력: "8월까지 모집하는 백엔드 공고 보여줘"
출력: { "min_deadline": "2025/08/01", "company_name": null }
```

Ollama + Gemma3:4b를 로컬 실행하여 API 비용 없이 운영.
프롬프트 엔지니어링과 정규 표현식 패턴을 조합하여 필터 추출 안정성을 높였습니다.

### 3-6. 운영 환경

- **서버**: Mac Mini M4 32GB 홈 서버
- **상시 운영**: systemd로 Discord Bot, FastAPI 서버 등록 (재부팅 후 자동 시작)
- **ETL 자동화**: cron job 기반 매일 06:00 실행
- **수집 규모**: 2주간 약 14만 건 (일 1만 건 제한으로 대상 서버 부하 조절)

---

## 4. 데이터 수집 현황

| 기간 | 일별 수집량 | 누적 수집량 |
|------|------------|------------|
| 1주차 | ~10,000건 / 일 | ~70,000건 |
| 2주차 | ~10,000건 / 일 | ~140,000건 |

크롤링 대상 서버의 부하를 고려하여 일 수집량을 1만 건으로 제한했습니다.

---

## 5. 트러블슈팅

### 5-1. 크롤링 차단 문제

**Problem**
잡코리아는 동적 페이지이기 때문에 BeautifulSoup4로는 렌더링된 데이터를 수집할 수 없었습니다.
동적 렌더링을 지원하는 Selenium으로 전환했으나, 사이트 자체의 봇 탐지 시스템에 의해 크롤링이 차단되었습니다.

**Solution**
실제 사용자의 커서 동작을 그대로 재현하는 Playwright 라이브러리로 교체하여 차단을 우회했습니다.
Playwright는 브라우저를 직접 제어하여 사람의 행동 패턴과 유사하게 동작하기 때문에
봇 탐지 시스템을 통과할 수 있었습니다.

---

### 5-2. Local LLM inference time 문제

**Problem**
사용자 쿼리에서 채용 조건을 추출하기 위해 처음에는 Mistral 7B 모델을 사용했습니다.
그러나 홈 서버 환경에서 7B 모델의 inference time이 너무 길어 실사용이 어려웠습니다.

**Solution**
모델을 Gemma3:4b로 교체하여 속도를 확보했습니다.
추가로, 반복적으로 들어오는 쿼리 패턴을 분석하여
프롬프트 엔지니어링과 정규 표현식 조합으로 필터 추출의 일관성을 높였습니다.

---

## 6. 회고

### 잘 된 점
- ETL 파이프라인, 벡터 DB, 로컬 LLM 서버 운영까지 전 과정을 직접 구축하며
  데이터 엔지니어링의 기초를 실전으로 익힐 수 있었습니다.
- 정규화된 DB 설계와 멱등성 보장 덕분에 2주간 안정적으로 데이터를 수집할 수 있었습니다.

### 아쉬운 점

**RAG 검색 품질**
벡터 유사도 기반 검색이다 보니, 사용자의 다양한 자연어 표현에 일관된 품질을 내지 못했습니다.
공고명과 태그 데이터로 직접 라벨링한 1,000건의 데이터로 LLM 파인튜닝을 시도해봤으나
유의미한 성능 향상을 얻지 못했습니다.
통계 기반 유사도 검색의 근본적인 한계였고, LLM 기반 re-ranking이나
하이브리드 검색(키워드 + 벡터) 도입이 필요하다고 생각합니다.

**파이프라인 안정성**
CSV를 중간 매개체로 사용하는 구조여서, 파일 유실 시 PostgreSQL과 FAISS의 데이터가
불일치할 수 있는 구조적 취약점이 있습니다.
크롤러에서 DB로 직접 적재하는 방식으로 개선이 필요합니다.

**엔지니어링 성숙도**
행마다 DB 연결을 새로 맺는 구조, FAISS 인덱스를 매 검색마다 디스크에서 로드하는 방식 등
처음 구현 당시 엔지니어링 지식이 부족하여 성능 측면에서 미흡한 부분이 있습니다.

---

## 7. 개선 방향

| 한계 | 개선 방향 |
|------|----------|
| CSV 경유 파이프라인 — DB·FAISS 불일치 가능성 | 크롤러 → DB 직접 적재 |
| 매 검색마다 FAISS 디스크 로드 | 앱 기동 시 1회 로드, 메모리 유지 |
| 행마다 DB 연결 생성 | Connection Pool 도입 |
| ETL 실패 시 알림 없음 | Discord 알림 또는 모니터링 연동 |
| 통계 기반 검색의 질의 다양성 한계 | 하이브리드 검색 또는 LLM re-ranking 도입 |

---

## 8. 기술 스택

| 분류 | 기술 |
|------|------|
| 크롤링 | Playwright |
| ETL / 데이터 처리 | Python, Pandas |
| 정형 DB | PostgreSQL, SQLAlchemy |
| 벡터 DB | FAISS, LangChain |
| 임베딩 | KR-SBERT (HuggingFace) |
| LLM | Ollama, Gemma3:4b |
| API 서버 | FastAPI, uvicorn |
| 봇 인터페이스 | discord.py |
| 자동화 | cron job, systemd |
| 서버 환경 | Mac Mini M4 32GB |
