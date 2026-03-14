# 트러블슈팅

---

## 1. 크롤링 차단 문제

### Problem
잡코리아는 JavaScript로 렌더링되는 동적 페이지입니다.
정적 파싱 라이브러리인 BeautifulSoup4로는 렌더링 완료 전 HTML을 수집하기 때문에
채용 공고 데이터를 가져올 수 없었습니다.

동적 렌더링을 지원하는 Selenium으로 교체했으나,
사이트 자체의 봇 탐지 시스템에 의해 자동화 접근으로 감지되어 크롤링이 차단되었습니다.

### Solution
실제 사용자의 커서 동작을 브라우저 레벨에서 재현하는 **Playwright** 라이브러리로 교체했습니다.
Playwright는 Selenium보다 낮은 수준에서 브라우저를 직접 제어하기 때문에
봇 탐지 시스템을 우회할 수 있었습니다.

---

## 2. Local LLM inference time 문제

### Problem
사용자 쿼리에서 채용 조건(마감일, 회사명 등)을 추출하기 위해
처음에는 **Mistral 7B** 모델을 Ollama로 로컬 실행했습니다.

Mac Mini M4 환경에서 7B 모델의 inference time이 요청당 수십 초에 달해
디스코드 봇 응답 대기 시간이 너무 길어 실사용이 어려웠습니다.

### Solution
모델을 **Gemma3:4b**로 교체하여 파라미터 수를 줄이고 응답 속도를 확보했습니다.
추가로, 반복적으로 들어오는 쿼리 패턴을 분석하여
프롬프트 엔지니어링과 정규 표현식을 조합해 필터 추출의 일관성을 높였습니다.

---

## 3. CSV 이중 읽기로 인한 파이프라인 불안정 문제

### Problem
ETL 실행 시 CSV 파일을 두 번 읽는 구조였습니다.

```python
base.csv_to_db(full_csv_path)   # 1회: PostgreSQL 적재
df = pd.read_csv(full_csv_path) # 2회: 행 수를 세기 위한 재읽기
limit = len(df) - 1
data = io.read_recruitOut(limit=limit, order_desc=True)
add_embedding(data)
```

CSV를 두 번 읽기 때문에 파일이 변경되거나 유실될 경우
PostgreSQL과 FAISS의 데이터가 불일치할 수 있는 구조적 취약점이 있었습니다.
또한 `pandas`를 행 수 계산 용도로만 import하는 것도 불필요한 의존성이었습니다.

### Solution
DB에 적재한 뒤 DB에서 직접 조회하는 방식으로 변경하여 CSV 재읽기를 제거했습니다.
`add_documents`에서 이미 중복 ID를 체크하고 건너뛰기 때문에
전체 레코드를 조회해도 FAISS 인덱스의 일관성이 유지됩니다.

```python
base.csv_to_db(full_csv_path)
data = io.read_recruitOut(order_desc=True)  # DB에서 직접 조회
add_embedding(data)
```

---

## 4. DB 연결을 행마다 생성하는 성능 문제

### Problem
CSV 적재 시 `_jobkorea_write` 함수가 행마다 DB 연결을 새로 맺고 닫는 구조였습니다.

```python
# _jobkorea_write 내부 — 행마다 실행됨
conn = connect_postgres()  # 연결 생성
...
conn.commit()
conn.close()               # 연결 해제
```

1만 건 적재 시 연결을 1만 번 맺는 셈이었고,
연결 생성 오버헤드가 누적되어 적재 시간이 불필요하게 길어졌습니다.

### Solution
**Connection Pool(`psycopg2.SimpleConnectionPool`)** 을 도입하고,
`csv_to_db`에서 하나의 연결을 열어 모든 행이 공유하도록 구조를 변경했습니다.

```python
# csv_to_db — 연결을 1회만 생성
conn = connect_postgres()   # Pool에서 연결 획득
try:
    for row in reader:
        _jobkorea_write(conn, cursor, ...)  # 연결 공유
finally:
    release_connection(conn)  # Pool에 반환
```

연결 생성 비용을 1만 번 → 1번으로 줄이고,
Pool을 통해 연결 재사용이 가능한 구조로 개선했습니다.

---

## 5. FAISS 인덱스를 매 검색마다 디스크에서 로드하는 문제

### Problem
디스코드 봇이 검색 요청을 받을 때마다 `load_vectorDB()`가 호출되어
FAISS 인덱스를 디스크에서 반복해서 읽어오는 구조였습니다.

```python
def vector_similar_search(query, filter, k):
    vector_store = load_vectorDB()  # 매 검색마다 디스크 I/O 발생
    ...
```

인덱스 파일 크기가 커질수록 검색 응답 시간이 함께 늘어나는 구조적 문제였습니다.

### Solution
모듈 레벨에 `_vector_store` 캐시 변수를 두고,
최초 요청 시에만 디스크에서 로드한 뒤 이후 요청은 메모리에서 직접 반환하도록 변경했습니다.
ETL 실행 후 인덱스가 갱신될 때는 캐시도 함께 업데이트합니다.

```python
_vector_store = None  # 모듈 로드 시 초기화

def get_vector_store():
    global _vector_store
    if _vector_store is None:
        _vector_store = load_vectorDB()  # 최초 1회만 디스크 로드
    return _vector_store

def add_embedding(data):
    ...
    vector_store.save_local(INDEX_DIR)
    _vector_store = vector_store  # 갱신 시 캐시 동기화
```

---

## 6. CSV를 파이프라인 중간 허브로 사용하는 구조적 취약점

### Problem
초기 파이프라인은 크롤러가 CSV에 저장하고, 별도 ETL 단계에서 CSV를 읽어 DB에 적재하는 구조였습니다.

```
크롤러 → CSV 저장 → (main.py 실행) → csv_to_db() → PostgreSQL → FAISS
```

이 구조에는 두 가지 취약점이 있었습니다.

첫째, 크롤러 실행 중 프로세스가 비정상 종료되면 CSV는 일부만 기록된 상태로 남고,
다음 ETL 실행 시 불완전한 데이터가 DB에 적재될 수 있었습니다.

둘째, 크롤러와 ETL이 별도 프로세스로 분리되어 있어 CSV 파일 유실, 경로 불일치 등
운영 환경에서 발생할 수 있는 장애 요인이 파이프라인 중간에 존재했습니다.

### Solution
크롤러 내부에서 5페이지마다 수집한 배치를 DB에 직접 적재하는 `batch_to_db()`를 도입했습니다.

```python
# scraper.py — 5페이지마다 직접 DB 적재
if current_page % SAVE_CNT == 0:
    batch_to_db(data_batch)
    data_batch.clear()
```

CSV 파일을 중간 매개체로 두지 않아 크롤러 중단 시에도 이미 적재된 데이터는 DB에 안전하게 보존됩니다.
또한 `ON CONFLICT DO NOTHING` 패턴이 적용되어 있어 크롤러 재실행 시에도 중복 적재가 발생하지 않습니다.

---

## 8. LLM 필터 추출의 오버엔지니어링

### Problem
사용자 쿼리에서 검색 조건을 추출하기 위해 Ollama + Gemma3:4b LLM을 사용했습니다.

```python
def recruit_filter(query):
    chain = recruit_filter_prompt | llm | JsonOutputParser()
    return chain.invoke({"today": date.today(), "query": query})
```

그러나 실제로 LLM이 추출하는 조건들을 분석해보니, 대부분 패턴이 명확한 정형 데이터였습니다.

| 필드 | 예시 | 실제 필요 |
|------|------|----------|
| `form` | 정규직, 계약직, 인턴 | 유한 목록 매칭 |
| `region` | 서울, 부산, 경기 | 유한 목록 매칭 |
| `max_experience` | 신입, 경력 3년 | 정규식 |
| `min_annual_salary` | 연봉 5000만원 | 정규식 |
| `min_deadline` | 8월까지, 다음달 | 정규식 + 날짜 계산 |

추가로 다음과 같은 문제가 있었습니다.

- **응답 지연**: LLM 추론에 수 초가 소요되어 Discord 봇 응답이 느렸습니다.
- **Ollama 서버 의존**: 홈 서버(Mac Mini)가 항상 켜져 있어야 했습니다.
- **불안정성**: JSON 파싱 실패나 필드 누락이 발생할 수 있었습니다.
- **필터 미적용**: 구현 당시 salary, company 필터는 주석 처리된 채 방치되었습니다.

### Solution
LLM을 제거하고 정규식 기반 `extract_filters()`로 교체했습니다.

```python
def extract_filters(query: str) -> dict:
    remaining = query

    # 지역 — 유한 목록 매칭
    for region in REGIONS:
        if region in remaining:
            filters['region'] = region
            ...

    # 경력 — 정규식
    if '신입' in remaining:
        filters['max_experience'] = 0
    elif m := re.search(r'경력\s*(\d+)\s*년\s*(?:이상|차)?', remaining):
        filters['max_experience'] = int(m.group(1))

    # 마감일 — 정규식 + 날짜 계산
    elif m := re.search(r'(\d{1,2})\s*월', remaining):
        month = int(m.group(1))
        filters['min_deadline'] = date(year, month, 1)

    # 키워드 — 구조화된 패턴 제거 후 남은 텍스트
    ...
```

결과적으로 Ollama/LangChain 의존성을 완전히 제거하고,
응답 속도는 수 초 → 밀리초 수준으로 개선되었습니다.
7개 필터 모두 실제로 동작하며 결과도 결정론적으로 예측 가능해졌습니다.

---

## 7. FAISS 벡터 검색의 구조적 한계

### Problem
사용자 질문을 처리하기 위해 KR-SBERT 임베딩과 FAISS MMR 검색을 도입했습니다.
그러나 실제 운영 중 검색 품질이 기대에 미치지 못했고, 원인을 분석한 결과 구조적 문제를 발견했습니다.

**임베딩 대상이 공고명 하나뿐이었습니다.**

```python
content = item.announcement_name  # "백엔드 개발자 채용"만 임베딩
```

사용자가 "서울 정규직 신입 백엔드 공고 보여줘"라고 질문해도 벡터 검색은
공고명 텍스트 유사도만 계산할 뿐, 지역·고용형태·경력 조건은 반영되지 않았습니다.

**수집된 데이터가 벡터 검색에 적합하지 않은 구조였습니다.**

잡코리아에서 수집되는 공고 설명(description)은 문단 형식의 자연어가 아니라
`"Python, Django, REST API, 백엔드"` 형태의 키워드 목록이었습니다.
임베딩 대상을 확장해도 의미 있는 시맨틱 벡터를 만들기 어려운 데이터 특성이었습니다.

**필터링이 필요한 조건들이 정형 데이터였습니다.**

연봉, 경력, 지역, 고용형태는 모두 정수 코드로 저장된 정형 데이터입니다.
이 조건들은 벡터 거리보다 SQL WHERE 절로 처리하는 것이 정확합니다.

**리소스 비용 대비 효과가 낮았습니다.**

- FAISS 인덱스(14만 건 × 768차원): 약 430MB
- KR-SBERT 모델: 약 300MB
- 상시 메모리 점유: 약 730MB 이상

### Solution
FAISS를 제거하고, LLM이 사용자 질문에서 구조화된 필터를 추출하면
PostgreSQL에서 직접 SQL 쿼리로 검색하는 방식으로 전환했습니다.

```
사용자 질문
    │
    ▼
Local LLM (Gemma3:4b) — 필터 추출
    { "keyword": "백엔드", "region": "서울", "form": "정규직", "max_experience": 0 }
    │
    ▼
PostgreSQL SQL 쿼리 (announcement_name ILIKE + tags ILIKE + WHERE 절)
    │
    ▼
Discord 응답
```

LLM이 추출한 `keyword`는 공고명과 태그 테이블 양쪽에 `ILIKE` 검색으로 적용하고,
나머지 조건(연봉, 경력, 지역, 고용형태)은 정형 필드 그대로 WHERE 절에 사용합니다.

결과적으로 FAISS 관련 인프라(모델, 인덱스, 캐시 관리)를 제거하고,
사용자가 실제로 필요로 하는 조건 기반 검색의 정확도가 높아졌습니다.

---

## 9. 억 단위 연봉 파싱 미지원

### Problem
`extract_filters()`에서 연봉 파싱이 `만원`, `천만원` 단위만 처리하여
"연봉 2억 이상" 쿼리가 잘못 파싱되었습니다.

```python
# 기존 파싱 순서: 천만원 → 만원 → 연봉 N
elif m := re.search(r'연봉\s*(\d+)', remaining):
    filters['min_annual_salary'] = int(m.group(1))  # "연봉 2" → 2만원
```

"연봉 2억 이상 신입 공고" 입력 시:
- `r'연봉\s*(\d+)'` 가 "연봉 2"에 매칭 → `min_annual_salary: 2` (2만원)
- 남은 "억"이 keyword로 추출 → 검색 결과 없음

### Solution
억 단위 패턴을 최우선으로 처리하고, 복합 표현(`1억 5천만원`)도 지원하도록 추가했습니다.

```python
# 억 단위를 먼저 처리
if m := re.search(r'(\d+)\s*억\s*(?:(\d+)\s*천\s*만\s*원?)?', remaining):
    eok = int(m.group(1)) * 10000
    cheon = int(m.group(2)) * 1000 if m.group(2) else 0
    filters['min_annual_salary'] = eok + cheon  # "2억" → 20000만원
elif m := re.search(r'(\d+)\s*천\s*만\s*원', remaining):
    ...
```

---

## 10. 기업명 검색 시 엉뚱한 결과 노출

### Problem
"카카오 공고 알려줘" 쿼리에서 카카오 회사의 채용 공고가 아닌,
공고명에 "카카오"가 포함된 무관한 공고가 노출되었습니다.

```
필터: {'keyword': '카카오'}
결과: 카카오 벤티 고급택시 운전자 모집 @ 신광상운주식회사  ← 엉뚱한 결과
     (합)신영산업 법인택시 기사모집(카카오T블루) @ 합자회사 신영산업
```

`keyword`는 `announcement_name`과 `tags`를 검색하기 때문에
"카카오T", "카카오 벤티" 등 서비스명이 공고명에 포함된 공고가 모두 매칭되었습니다.

### Solution
`"X 공고"` / `"X 채용"` 패턴에서 첫 단어를 `company_name` 필터로 추출하는 휴리스틱을 추가했습니다.

```python
# "카카오 공고 알려줘" → company_name: '카카오'
if m := re.match(r'^(\S+)\s+(?:공고|채용)', query.strip()):
    candidate = m.group(1)
    if candidate not in REGIONS and candidate not in FORM_KEYWORDS:
        filters['company_name'] = candidate
        remaining = remaining.replace(candidate, ' ', 1)
```

`company_name` 필터는 `companies.company_name` 컬럼에 `ILIKE` 검색을 적용하여
실제 카카오, 카카오뱅크, 카카오페이 등 카카오 계열사 공고만 반환합니다.

---

## 11. 대용량 테이블 DELETE 시 성능 저하

### Problem
기존 데이터 초기화를 위해 `DELETE FROM` 방식으로 테이블을 비우는 코드를 작성했습니다.

```python
cursor.execute("DELETE FROM recruit_tags")  # 897,114건
cursor.execute("DELETE FROM recruits")
cursor.execute("DELETE FROM tags")          # ← 6분 이상 소요
...
```

`recruit_tags`(89만 건), `recruits`, `tags`(17,635건) 테이블을 순서대로 DELETE하는 과정에서
`DELETE FROM tags` 단계가 6분 이상 진행되어 사실상 멈춘 것처럼 보였습니다.

추가로, `api_server`와 `discord_bot`이 SQLAlchemy 세션을 유지 중이어서
`TRUNCATE` 시도 시에도 `ACCESS EXCLUSIVE` 락 대기가 발생했습니다.

### Solution
`DELETE FROM` 대신 `TRUNCATE ... RESTART IDENTITY CASCADE`로 교체했습니다.

```python
cursor.execute("""
    TRUNCATE TABLE recruit_tags, recruits, tags, companies, subregions, regions
    RESTART IDENTITY CASCADE
""")
```

`TRUNCATE`는 행 단위가 아닌 페이지 단위로 삭제하여 대용량 테이블에서 훨씬 빠릅니다.
`RESTART IDENTITY`로 시퀀스(AUTO_INCREMENT)도 함께 초기화하고,
`CASCADE`로 외래키 의존 테이블을 한 번에 처리합니다.

---

## 12. 크롤링 날짜 범위 버그 — "N일 전 등록" 패턴 미처리

### Problem
14일치 데이터를 수집하기 위해 날짜 기반 중단 조건을 추가했으나
실제로는 1일치만 수집하고 종료되었습니다.

```python
def _posted_within_days(time_text, days):
    if "분 전 등록" in time_text or "시간 전 등록" in time_text:
        return True
    # MM/DD 형식만 처리
    m = re.search(r'(\d{2})/(\d{2})', time_text)
    if m:
        ...
    return False  # ← 매칭 안 되면 무조건 중단
```

잡코리아의 등록 시간 표기 형식이 24시간 이후부터 `"N일 전 등록"`으로 바뀌는 것을 파악하지 못했습니다.
`"2일 전 등록"` 텍스트가 어느 조건에도 매칭되지 않아 `False`를 반환,
크롤러가 1일치 수집 직후 종료되었습니다.

| 경과 시간 | 실제 표기 형식 |
|---|---|
| 0~24시간 | `"N분 전 등록"` / `"N시간 전 등록"` |
| 1일 이후 | **`"N일 전 등록"`** |
| 날짜 표기 | `"MM/DD 등록"` |

### Solution
`"N일 전 등록"` 패턴을 중간에 추가하여 세 가지 형식 모두 처리합니다.

```python
def _posted_within_days(time_text, days):
    if "분 전 등록" in time_text or "시간 전 등록" in time_text:
        return True
    m = re.search(r'(\d+)\s*일\s*전\s*등록', time_text)  # 추가
    if m:
        return int(m.group(1)) <= days
    m = re.search(r'(\d{2})/(\d{2})', time_text)
    if m:
        ...
    return False
```

---

## 13. 데이터 품질 이상값 — 연봉 파싱 오류

### Problem
구독 알림 테스트 중 "연봉 5,000만원 이상" 조건에 6,388건이 매칭되는 이상 현상을 발견했습니다.
실제 DB를 조회하니 연봉 컬럼에 `3,720,000만원(372억)` 같은 극단적 이상값이 존재했습니다.

원인은 `parse_salary()`가 범위 검사 없이 파싱된 숫자를 그대로 저장하기 때문입니다.

```python
# 기존: 범위 검사 없음
if "월" in value:
    num = cls.extract_first_number(value)
    return num * 12  # "260만원/월" → 3120 (정상)
                     # "2000만원/월" → 24000 (의심값)
                     # 잘못된 입력 → 극단값 그대로 저장
```

### Solution
데이터 거버넌스 3계층을 구축하여 근본적으로 해결했습니다.

**① Validation Gate** — 수집 시점 이상값 차단

```python
SALARY_MIN, SALARY_MAX = 600, 50000  # 만원

def validate_salary(value):
    if value < SALARY_MIN: return None, f"below_minimum({SALARY_MIN})"
    if value > SALARY_MAX: return None, f"above_maximum({SALARY_MAX})"
    return value, None
```

**② data_quality_log 테이블** — 이상값 발생 이력 추적

```sql
CREATE TABLE data_quality_log (
    batch_id TEXT, field TEXT, rule TEXT,
    original_value TEXT, parsed_value TEXT, created_at TIMESTAMP
);
```

**③ 품질 리포트 + 소급 정제** — 기존 데이터 일회성 정제

```python
clean_existing_data()   # 기존 이상값 NULL 처리
generate_quality_report()  # 완전성·분포·이벤트 현황 출력
```

정제 후 연봉 평균이 **5,067만원 → 4,026만원**으로 정상화되었습니다.

---

## 14. 검색 품질 개선 — 동의어 사전 · AND/OR 폴백 · 태그 정규화

### Problem

50개 테스트 케이스 기반으로 검색 품질을 분석한 결과 세 가지 구조적 한계가 발견되었습니다.

**① 사용자 쿼리 동의어 미처리**

영문 약어나 구어체 표현이 그대로 keyword로 넘어가 DB 매칭에 실패했습니다.

```
"FE 공고"        → keyword: 'FE'       → 0건 (DB에 'FE' 태그 없음)
"BE 신입 서울"   → keyword: 'BE'       → 0건
"데이터분석가 공고" → keyword: '데이터분석가' → 0건
```

**② keyword AND-only 검색으로 복합 키워드 검색 실패**

`keyword = "프론트엔드 개발자"` 처럼 두 토큰이 모두 공고명·태그에 존재해야 AND로 결과가 나왔습니다.
한 토큰만 포함한 공고는 누락되었고, 조건이 추가될수록 0건이 되는 경우가 많았습니다.

**③ 태그 중복·불일치**

크롤링 시점이나 사이트 표기 차이로 동일 기술이 다른 이름으로 저장되었습니다.

```
Vue: 'vue.js', 'vuejs', 'Vue'  → 모두 다른 태그로 관리
Java: 'Java', 'JAVA'
Spring: 'SPRING', 'springboot', 'spring Framework개발'
프론트엔드: 'Backend', 'Front-end 개발', '백엔드'
```

사용자가 "Vue" 검색 시 `ILIKE '%Vue%'`로 어느 정도 커버되지만, 대소문자·포맷 불일치로 누락되는 케이스가 있었습니다. 또한 미래 수집 데이터에서 같은 불일치가 반복될 수 있는 구조였습니다.

### Solution

**① QUERY_SYNONYMS — 쿼리 동의어 사전 (discord_bot/llm.py)**

```python
QUERY_SYNONYMS = {
    'FE': '프론트엔드', 'BE': '백엔드',
    'frontend': '프론트엔드', 'backend': '백엔드',
    'fullstack': '풀스택', 'devops': 'DevOps',
    '데이터분석가': '데이터 분석', '데이터과학자': '데이터 분석',
    '개발직': '개발자', '기획자': '서비스기획',
}

def _normalize_query(query: str) -> str:
    return ' '.join(QUERY_SYNONYMS.get(t, t) for t in query.split())
```

`extract_filters()` 진입 전 토큰 단위로 치환하여 단어 파괴 없이 동의어를 정규화합니다.

**② AND → OR 폴백 (db/io.py)**

```python
def _build_query(keyword_mode: str = 'and'):
    ...
    if keyword_mode == 'and':
        for token in tokens:
            q = q.filter(or_(announcement_name ILIKE, tags any))
    else:  # 'or' 폴백
        q = q.filter(or_(*[or_(announcement_name ILIKE, tags any) for token in tokens]))
    ...

results = _build_query('and').limit(limit).all()

# AND 결과 없고 키워드가 여러 토큰이면 OR 폴백
if not results and keyword and len(keyword.split()) > 1:
    results = _build_query('or').limit(limit).all()
```

다른 필터(지역·경력·연봉·고용형태)는 AND/OR 양쪽 모두 동일하게 적용됩니다.

**③ TAG_SYNONYMS — 태그 정규화 (db/JobPreprocessor.py + db/io.py)**

```python
TAG_SYNONYMS = {
    'JAVA': 'Java', 'SPRING': 'Spring',
    'vue.js': 'Vue.js', 'vuejs': 'Vue.js', 'Vue': 'Vue.js',
    'springboot': 'Spring Boot', 'React 기반': 'React',
    'Backend': '백엔드', 'Front-end 개발': '프론트엔드',
}
```

- `parse_explanation()` — 수집 시 자동 적용 (미래 데이터 방지)
- `normalize_existing_tags()` — 기존 DB 일회성 정리 함수 (태그 병합 or 이름 변경)

### Result

```
FE 공고 보여줘      → keyword: '프론트엔드' → ✅ 결과 반환
BE 신입 서울        → keyword: '백엔드'     → ✅ 결과 반환
데이터분석가 공고   → keyword: '데이터 분석' → ✅ 결과 반환
```

테스트 결과: 49/50 통과 유지 (실패 1건은 의도된 "결과없음" 케이스).

---

## 15. extract_filters 오분류 — 직무 키워드가 회사명으로 처리되는 문제

### Problem

`extract_filters()`에 50개 테스트 케이스를 실행한 결과 42/50만 통과하였고, 실패 원인이 세 가지 버그로 압축되었습니다.

**① `company_name` 검출이 원본 쿼리 기준으로 동작**

```python
# 버그: 이미 처리된 필터가 남아 있는 원본 query를 다시 검사
if m := re.match(r'^(\S+)\s+(?:공고|채용)', query.strip()):
```

"5년차 공고 보여줘" 처리 시:
1. 경력 파싱 → `remaining`에서 "5년차" 제거, `max_experience = 5`
2. company_name 검사 → 원본 `query`("5년차 공고 보여줘")에서 다시 "5년차" 매칭 → `company_name = '5년차'`

두 필터가 동시에 잘못 설정되어 결과 없음.

**② `JOB_KEYWORDS` 제외 조건 없음**

`개발자`, `백엔드`, `프론트엔드`, `디자이너`, `영업직`, `고객응대` 등 직무 키워드가 `"X 공고"` 패턴에 매칭되어 `company_name`으로 오분류되었습니다.

```
"개발자 공고 보여줘" → company_name: '개발자'  (keyword가 되어야 함)
"백엔드 공고"       → company_name: '백엔드'
"디자이너 채용 공고" → company_name: '디자이너'
```

**③ STOPWORD를 문자열 치환으로 제거하여 단어 파괴**

```python
for sw in STOPWORDS:
    remaining = remaining.replace(sw, ' ')  # 단어 중간도 치환됨
```

`STOPWORDS`에 `'이'`, `'가'` 등 단일 글자 조사를 추가하자 복합 명사가 파괴되었습니다.

```
"데이터 분석" → "데 터 분석"   ('이' 치환)
"디자이너"    → "디자 너"      ('이' 치환)
```

추가로 `"부산 채용 공고"` → `remaining = " 채용 공고"` → `company_name: '채용'` 오류도 발생했습니다. `채용`이 `STOPWORDS`에 있었지만 `company_name` 검출 제외 조건에는 없었기 때문입니다.

### Solution

세 가지를 순서대로 수정했습니다.

**① `remaining` 기준으로 변경**

```python
# 수정: 이미 처리된 필터가 제거된 remaining을 검사
if m := re.match(r'^(\S+)\s+(?:공고|채용)', remaining.strip()):
```

**② `JOB_KEYWORDS` 집합 추가 및 제외 조건 반영**

```python
JOB_KEYWORDS = {
    '개발', '개발자', '백엔드', '프론트엔드', '풀스택',
    '디자이너', '디자인', '마케팅', '마케터',
    '영업', '영업직', '회계', '재무', '경리',
    '고객응대', '고객서비스', 'CS', '물류', ...
}

if (candidate not in REGIONS and
        candidate not in FORM_KEYWORDS and
        candidate not in ['신입', '경력'] and
        candidate not in JOB_KEYWORDS and      # 추가
        candidate not in STOPWORDS):           # 추가
    filters['company_name'] = candidate
```

**③ STOPWORD 제거를 토큰 단위로 변경**

```python
# 수정: 공백 기준으로 토큰을 분리한 뒤 집합 조회로 제거
tokens = [t for t in remaining.split() if t not in STOPWORDS]
keyword = ' '.join(tokens).strip()
```

단일 글자 조사(`이`, `가`, `을`, `를` 등)를 STOPWORDS에서 제거하고, 토큰 단위 비교이므로 복합 명사 내부를 파괴하지 않습니다.

### Result

| | 통과 | 실패 |
|---|---|---|
| 수정 전 | 42/50 | 8 |
| 수정 후 | 49/50 | 1 |

실패 1건(`[50] 제주 데이터 분석 정규직 신입 연봉 5000만원 이상`)은 DB에 조건을 만족하는 공고가 없는 케이스로, 의도된 결과입니다.

---

## 16. 중복 코드 · 데드 코드 누적

### Problem

프로젝트가 커지면서 더 이상 사용되지 않는 코드와 동일한 로직이 여러 곳에 반복되는 문제가 생겼습니다.

**① 데드 코드 — 삭제된 기능의 잔재**

| 파일 | 이유 |
|------|------|
| `rag/`, `NER/` | FAISS 벡터 검색·NER 파이프라인 제거 후 디렉토리만 남음 |
| `crawling/saver.py` | `batch_to_db()` 도입 후 CSV 저장 함수 미사용 |
| `discord_bot/prompt_templates.py` | LangChain 제거 후 프롬프트 템플릿 미사용 |
| `db/io.py export_titles_to_json()` | NER 모듈 전용 함수, 의존 모듈 삭제됨 |

**② 중복 코드 — RecruitOut 변환 블록**

`read_recruitOut`, `search_recruits_by_filter`, `read_recruits_by_ids`, `get_new_recruits` 4개 함수에서 동일한 11줄짜리 `RecruitOut(...)` 변환 블록이 반복되었습니다. 필드 하나를 추가하려면 4곳을 모두 수정해야 했습니다.

**③ 중복 코드 — 공고 포매팅 문자열**

`discord_bot/notifier.py`의 `_format_recruit()`와 `discord_bot/llm.py`의 `sql_search()` 내부에 거의 동일한 공고 출력 포매팅 코드가 따로 존재했습니다.

**④ 중복 코드 — `safe_wait_networkidle` 내부 함수**

`crawling/scraper.py` 안에 `safe_wait_networkidle()` 내부 함수가 정의되어 있었는데, `crawling/utils.py`의 `safe_wait()`과 동일한 로직(재시도 + 리로드)이었습니다.

### Solution

**① 데드 코드 삭제**

`rag/`, `NER/`, `crawling/saver.py`, `discord_bot/prompt_templates.py`, `export_titles_to_json()`을 모두 제거했습니다.

**② `_to_recruit_out()` 헬퍼 추출 (db/io.py)**

```python
def _to_recruit_out(r: Recruit) -> RecruitOut:
    return RecruitOut(
        id=r.id,
        company_name=r.company.company_name,
        ...
        region_name=r.subregion.region.name if r.subregion and r.subregion.region else None,
    )
```

4개 함수의 변환 블록을 `[_to_recruit_out(r) for r in results]` 한 줄로 교체했습니다.

**③ `format_recruit()` 공개화 (discord_bot/notifier.py)**

`_format_recruit` → `format_recruit`으로 이름을 바꾸고 `include_education` 파라미터를 추가했습니다. `llm.py`에서 이를 import하여 인라인 포매팅 블록을 제거했습니다.

```python
# discord_bot/llm.py
from discord_bot.notifier import format_recruit

result_lines = [format_recruit(i, r, include_education=True) for i, r in enumerate(recruits, start=1)]
```

**④ `safe_wait` 재사용 (crawling/scraper.py)**

`safe_wait_networkidle` 내부 함수(22줄)를 삭제하고 4개 호출부를 `utils.safe_wait(load_state='networkidle', ...)` 로 교체했습니다.

---

## 17. 소스 파일이 gitignored 디렉토리에 위치하는 문제

### Problem

로깅 설정 모듈인 `logs/log.py`가 런타임 로그 파일이 쌓이는 `logs/` 디렉토리 안에 있었습니다.

`.gitignore`에 `logs/`가 등록되어 있어 소스 파일이 git에서 무시되어야 하는 상황이었습니다. 실제로는 명시적으로 트래킹되고 있었지만, 이후 `git add .` 실행 시 의도치 않게 추적이 끊길 수 있는 구조적 위험이 있었습니다.

또한 테스트 파일이 루트(`test_search.py`, `test_quality.py`, `test_subscription.py`)와 `tests/` 디렉토리에 분산되어 있었고, 테스트 결과 파일(`test_results.txt` 등)도 루트에 생성되어 저장소가 지저분해졌습니다.

### Solution

**① `logs/log.py` → `log_config.py` (루트 이동)**

소스 파일을 런타임 산출물 디렉토리 밖으로 꺼냈습니다. `main.py`와 `db/base.py`의 import를 `import log_config`로 수정했습니다.

**② 통합 테스트 파일 `tests/` 통합**

루트의 `test_search.py`, `test_quality.py`, `test_subscription.py`를 모두 `tests/`로 이동했습니다. 단위 테스트(`pytest`)와 통합 테스트가 한 디렉토리에서 관리됩니다.

**③ 테스트 결과 파일 경로 고정 및 gitignore 추가**

각 테스트 파일의 출력 경로를 `os.path.dirname(__file__)` 기준으로 고정하여 실행 위치에 무관하게 `tests/` 내부에 결과가 저장되도록 했습니다. `.gitignore`에 `tests/*.txt`를 추가하여 결과 파일이 커밋되지 않도록 했습니다. `test_snapshots.json`은 회귀 테스트 기준선이므로 커밋 대상으로 유지했습니다.

---
