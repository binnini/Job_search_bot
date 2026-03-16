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

## 18. Discord 봇 검색 응답이 '잠시 기다려 주세요'에서 멈추는 문제

### Problem

Discord 봇이 정상 실행 중임에도 불구하고 검색 명령을 입력하면
'잠시 기다려 주세요' 메시지 이후 응답이 오지 않는 현상이 발생했습니다.

로그를 확인하니 다음 에러가 반복되었습니다.

```
psycopg2.OperationalError: SSL connection has been closed unexpectedly
```

SQLAlchemy Connection Pool이 유지하는 idle 연결이 PostgreSQL 서버 쪽에서
타임아웃으로 끊겼는데, Pool은 이를 모르고 끊어진 연결을 재사용하다 실패하는 구조였습니다.

### Solution

`create_engine`에 `pool_pre_ping=True` 옵션을 추가했습니다.

```python
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
```

`pool_pre_ping=True`는 Pool에서 연결을 꺼낼 때 `SELECT 1`로 연결 상태를 먼저 확인합니다.
끊어진 연결이 감지되면 자동으로 재연결 후 반환하여 `OperationalError`를 방지합니다.

---

## 19. 기존 CSV 적재 시 마감일이 2026년으로 밀리는 문제

### Problem

2025년 수집된 CSV 파일을 2026년에 DB에 적재하면,
`~07/20` 같은 마감일이 `parse_deadline()` 내부에서 오늘 날짜(2026-03-15) 기준으로 파싱되어
모두 2026~2027년으로 설정되는 문제가 있었습니다.

```python
# parse_deadline 내부 — today를 기준으로 연도 결정
year = today.year  # 2026
deadline = datetime(year, month, day).date()
if deadline < today:  # 이미 지났으면 내년으로 보정
    deadline = datetime(year + 1, month, day).date()  # 2027년!
```

`jobkorea_data_2025-07-15.csv`에 담긴 마감일 `~07/20`은
실제로는 2025-07-20이지만 2026-07-20으로 적재되어 데이터가 왜곡되었습니다.

### Solution

`csv_to_db()`에 `today` 파라미터를 추가하고,
파일명(`jobkorea_data_2025-07-15.csv`)에서 날짜를 정규식으로 추출하여 기준 날짜로 사용했습니다.

```python
def csv_to_db(csv_path, today=None):
    if today is None:
        m = re.search(r'(\d{4})-(\d{2})-(\d{2})', csv_path)
        if m:
            today = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    ...
    deadline=JobPreprocessor.parse_deadline(row['마감일'], today=today)
```

파일명에 날짜가 없는 경우(`jobkorea_data.csv`)는 현재 날짜로 fallback됩니다.

---

## 20. Ollama 원격 접속 불가 — localhost 바인딩 문제

### Problem

동일 로컬 네트워크 내 Mac에서 Ollama를 실행하고
다른 서버(192.168.219.155)에서 `http://192.168.219.114:11434`로 접속 시
`Connection refused` 오류가 발생했습니다.

### Solution

Ollama는 기본적으로 `127.0.0.1`(localhost)에만 바인딩되어 같은 기기에서만 접속 가능합니다.
같은 LAN의 다른 기기도 Mac 입장에서는 외부 접속이므로, `0.0.0.0` 바인딩이 필요합니다.

```bash
OLLAMA_HOST=0.0.0.0 ollama serve
```

`0.0.0.0`으로 바인딩하면 인터넷이 아닌 LAN 내 모든 기기에서 접속 가능합니다.

---

## 21. LLM 태깅 출력 형식 불일치 — 긴 구 형태 태그

### Problem

EXAONE을 이용한 공고 태깅 시, 기존 DB의 단어형 태그(`백엔드`, `Java`, `SNS마케팅`)와 달리
LLM이 구 형태의 긴 태그를 생성하는 문제가 발생했습니다.

```
기존 태그: 소프트웨어개발, C++, Linux
LLM 생성:  자동차 전장 소프트웨어 개발, Linux 기반 시스템, C++ 전문가
```

공백이 포함된 태그는 `tag.name ILIKE '%token%'` 검색에서 부분 매칭이 불안정하고,
기존 태그와 형식이 달라 검색 노이즈가 증가합니다.

또한 기업명, 지역, 연봉 같은 메타 정보가 태그에 포함되는 케이스도 있었습니다.

```
gemma3 생성: 방산, 품질관리, ISO, 신입, 듀라텍  ← 기업명 포함
```

### Solution

프롬프트에 명확한 형식 규칙과 나쁜 예시를 추가했습니다.

```
규칙:
- 공백 없는 단어만 (예: 백엔드, Java, 데이터분석, UI디자인)
- 직무/기술/산업 도메인만 포함 (지역·연봉·고용형태·기업명 제외)
- 5~8개, 쉼표 구분, 태그만 출력

예시 출력: 백엔드, Java, Spring, REST API, MySQL, 서버개발
```

출력 파싱 시에도 첫 줄만 사용하고, 공백이 2개 이상 포함된 태그를 필터링하여 방어적으로 처리합니다.

```python
tags = [t for t in tags if 1 <= len(t) <= 20 and t.count(" ") <= 1]
```

---

## 22. LLM 구독 키워드 과확장 — Recall 증가와 Precision 저하

### Problem

방안 1(구독 키워드 확장) 구현 시 EXAONE이 원래 직무와 관련 없는 상위 개념 키워드까지 포함하여
매칭 공고가 폭발적으로 증가하는 과확장 문제가 발생했습니다.

```
ML엔지니어 → 머신러닝, AI, 데이터분석, 소프트웨어개발  ← 너무 넓음
서비스기획  → Before 1,291건 → After 10,691건  ← 9,400건 과확장
```

첫 번째 프롬프트가 "관련된 키워드"를 요청했기 때문에
LLM이 같은 직무의 동의어가 아니라 연관 직무 전체를 포함했습니다.

### Solution

프롬프트를 "동의어·기술 스택만 추가, 상위 개념 금지"로 강화하고 나쁜 예시를 추가했습니다.

```
규칙: 같은 직무를 다르게 표현한 동의어·기술 스택만 추가해줘.
      상위 개념이나 관련 직무는 포함하지 마.

나쁜 예 (너무 넓음): ML엔지니어, 데이터분석, AI, 소프트웨어개발
좋은 예: ML엔지니어, MLOps, 머신러닝엔지니어, 딥러닝, PyTorch, TensorFlow
```

개선 결과: 전체 매칭 증가율 **86% → 30%** 로 과확장이 억제되었으며,
방안 2(재순위)와 함께 사용하여 Recall 증가 + Precision 보완 구조로 운영합니다.

---

## 23. 방안 3 Before/After 평가 결과가 동일 — 테스트셋 편향

### Problem

LLM 시맨틱 태깅(방안 3) 적용 전후 검색 품질을 `evaluate.py`로 측정했을 때
Before와 After가 완전히 동일한 결과가 나왔습니다.

```
Before: Hit@5=52.0%  Hit@10=58.0%  MRR=0.3941
After:  Hit@5=52.0%  Hit@10=58.0%  MRR=0.3941  ← 변화 없음
```

원인은 `testset.json` 생성 방식에 있었습니다.
`generate_testset.py`는 LLM에게 "이 공고를 찾을 쿼리를 만들어줘"라고 요청하는 역방향 생성 방식이었습니다.

LLM은 공고명에서 직접 단어를 가져와 쿼리를 생성하기 때문에,
생성된 쿼리는 이미 공고명에 포함된 단어를 사용합니다.
공고명으로 검색하면 이미 찾히므로, LLM 태그를 추가해도 결과가 바뀌지 않았습니다.

```
공고명: "백엔드 API 개발자 채용 (Spring Boot)"
생성 쿼리: "서울 백엔드 Spring Boot 신입"  ← 공고명 단어 그대로 사용
→ 태그 없이도 공고명 ILIKE로 이미 검색됨
```

태그 기반 검색의 진짜 가치는 공고명에 없는 표현으로 검색할 때 나타납니다.

### Solution

공고명에 나타나지 않는 동의어·기술 스택 쿼리로 측정하는 `evaluate_tagging.py`를 별도로 작성했습니다.

```python
# 공고명에 없지만 의미적으로 연관된 동의어 쿼리 쌍 정의
SYNONYM_PAIRS = [
    ("프론트엔드", ["frontend", "React", "Vue", "UI개발"]),
    ("데이터분석", ["analytics", "SQL", "Python", "tableau"]),
    ("UX디자인",   ["사용자경험", "UI/UX", "Figma"]),
    ...
]
```

Before(공고명만 매칭)와 After(공고명+LLM 태그 매칭)를 비교한 결과:

```
평균 Recall@10 Before: 37.8%
평균 Recall@10 After:  88.9%  (+51.1%p)
```

프론트엔드(+80%p), 데이터분석(+100%p), UX디자인(+90%p), 임베디드(+90%p) 에서 특히 큰 효과가 확인되었습니다.

---

## 24. `_jobkorea_write()`가 recruit_id를 반환하지 않아 LLM 태깅 불가

### Problem

`batch_to_db()`에 LLM 태깅 연동을 추가하려면 신규 삽입된 공고의 ID 목록이 필요했습니다.
그러나 `_jobkorea_write()`는 반환값이 없었고, 중복 공고(`ON CONFLICT DO NOTHING`)와 신규 삽입을 구분할 방법도 없었습니다.

```python
def _jobkorea_write(conn, cursor, row, today):
    cursor.execute("INSERT INTO recruits ... ON CONFLICT DO NOTHING")
    conn.commit()
    # return 없음 → 신규 삽입 여부 알 수 없음
```

태깅 대상을 알 수 없어 전체 배치를 다시 쿼리하거나, 중복 공고도 불필요하게 재태깅하는 문제가 발생할 수 있었습니다.

### Solution

`_jobkorea_write()`에서 신규 삽입 시 `recruit_id`를 반환하고, 중복(CONFLICT)이면 `None`을 반환하도록 변경했습니다.

```python
def _jobkorea_write(conn, cursor, row, today):
    recruit_id = None
    # ... INSERT 로직 ...
    cursor.execute("INSERT INTO recruits ... ON CONFLICT DO NOTHING RETURNING id")
    row_result = cursor.fetchone()
    if row_result:
        recruit_id = row_result[0]  # 신규 삽입 시 ID 반환
    conn.commit()
    return recruit_id  # 중복이면 None
```

`batch_to_db()`에서 `None`이 아닌 ID만 모아 태깅 대상으로 전달합니다.

```python
new_recruit_ids = [rid for rid in insert_results if rid is not None]
if use_llm_tagging and new_recruit_ids:
    tag_recruit_batch(new_recruit_ids)
```

---

## 25. cron 크롤링 시 LLM 태깅이 자동 실행되지 않는 문제

### Problem

`db/tagger.py`와 `batch_to_db(use_llm_tagging=True)` 연동을 구현했지만,
실제 크롤링을 담당하는 `crawling/scraper.py`에서는 기본값(`False`)으로 호출하고 있었습니다.

```python
# scraper.py (변경 전)
batch_to_db(data_batch)  # use_llm_tagging 기본값=False → 태깅 안 됨
```

매일 06시 cron이 `main.py → scraper.py → batch_to_db()` 경로로 실행되므로,
소급 태깅 스크립트(`db/tag_recruits.py`)를 별도로 수동 실행하지 않는 한 신규 공고에 태그가 붙지 않았습니다.

### Solution

`scraper.py`의 모든 `batch_to_db()` 호출에 `use_llm_tagging=True`를 명시했습니다.

```python
# 5페이지마다 중간 저장
batch_to_db(data_batch, use_llm_tagging=True)

# 크롤링 종료 후 잔여 배치
batch_to_db(data_batch, use_llm_tagging=True)
```

Ollama 서버(Mac)가 꺼져 있는 경우 `call_tagger()` 내부에서 예외를 잡아 `failed` 카운트만 증가하고 크롤링/저장 자체는 정상 진행됩니다.

---

## 26. LLM 동기 호출이 Discord 이벤트 루프를 블로킹하는 문제

### Problem

`notify_subscribers()` 실행 시 `expand_keyword()`와 `rerank()`가 Ollama에 동기 HTTP 요청을 보내는데,
이 함수들이 Discord의 async 이벤트 루프 위에서 직접 호출되어 루프 전체가 블로킹되었습니다.

```python
# 문제: async 함수 내에서 동기 blocking 호출
async def notify_subscribers(client):
    expanded_map = {kw: expand_keyword(kw) for kw in all_keywords}  # blocking!
    to_notify = rerank(keywords[0], to_notify)                       # blocking!
```

결과적으로 notify 태스크가 실행되는 동안 `!인사이트`, `!도움` 등 모든 명령어가 응답하지 않았습니다.
Ollama 서버 응답이 느리거나 연결이 끊기는 경우 수십 초~수 분간 봇이 멈춘 것처럼 보였습니다.

### Solution

`loop.run_in_executor(None, ...)` 로 동기 함수를 스레드 풀에서 실행하여 이벤트 루프를 해방했습니다.

```python
import asyncio
loop = asyncio.get_event_loop()

# 키워드 확장 — 스레드에서 실행
for kw in all_keywords:
    expanded_map[kw] = await loop.run_in_executor(None, expand_keyword, kw)

# 재순위 — 스레드에서 실행
to_notify = await loop.run_in_executor(None, rerank, keywords[0], to_notify)
```

`bot.py`의 `sql_search()` 호출도 동일하게 적용했습니다.

```python
response = await loop.run_in_executor(None, lambda: sql_search(content, limit=5))
```

LLM 호출 중에도 다른 명령어가 정상 응답합니다.

---

## 27. 직접 검색에 LLM 기능이 적용되지 않는 문제

### Problem

방안 1(키워드 확장)·방안 2(재순위)를 구독 알림 흐름에만 적용했고,
사용자가 Discord에서 직접 자연어로 검색할 때는 적용되지 않았습니다.

```
# 구독 알림: 키워드 확장 + 재순위 ✅
# 직접 검색: extract_filters() → SQL → 결과 반환  ← LLM 없음 ❌
```

"프론트 엔지니어"처럼 공고명과 다른 표현으로 검색 시 확장 없이 정확한 매칭에만 의존했습니다.

### Solution

`sql_search()`에 키워드 확장과 재순위를 통합했습니다.

```python
def sql_search(query, limit=5):
    keyword = filters.get('keyword')

    # 방안 1: 키워드 확장
    expanded = expand_keyword(keyword) if keyword else None

    # 확장 키워드 OR 매칭으로 후보 넉넉히 검색
    recruits = search_recruits_by_filter(..., expanded_keywords=expanded, limit=50)

    # 방안 2: 관련도 재순위 후 상위 limit건
    recruits = rerank(keyword, recruits)
    return format(recruits[:limit])
```

`search_recruits_by_filter()`에 `expanded_keywords` 파라미터를 추가하여
확장 키워드 전달 시 OR 매칭, 미전달 시 기존 AND/OR 폴백 방식을 유지했습니다.

---

## 28. 분석 레이어 부재 — 수집 데이터에서 인사이트 추출 불가

### Problem

18만 건의 채용 공고 데이터가 쌓였지만 운영(OLTP) 용도로만 사용되었습니다.
"요즘 어떤 기술 스택이 많이 뽑히나요?", "평균 연봉은 얼마인가요?" 같은 분석 질문에 답할 수 없었습니다.

### Solution

데이터 웨어하우스 역할의 분석 레이어를 추가했습니다.

**`job_market_daily` 테이블** — 날짜별 마켓 스냅샷

```sql
CREATE TABLE job_market_daily (
    date DATE PRIMARY KEY,
    total_valid_jobs INTEGER,
    new_jobs INTEGER,
    avg_salary INTEGER,
    top_tags JSONB,       -- 인기 태그 TOP 10
    region_dist JSONB,    -- 지역별 분포
    experience_dist JSONB -- 경력별 분포
);
```

**`db/analytics.py`** — 분석 쿼리 함수 모음
- `get_top_tags()`: 유효 공고 기준 인기 기술 스택 TOP N
- `get_salary_by_tags()`: 키워드별 평균 연봉
- `get_regional_dist()`: 지역별 공고 수
- `get_experience_dist()`: 경력별 분포
- `get_market_snapshot()`: 현황 종합

**`analytics/snapshot.py`** — 일별 스냅샷 생성, `main.py`에서 크롤링 완료 후 자동 호출

**Discord `!인사이트` 명령어** — 현재 채용 시장 현황을 즉시 조회

```
📊 채용 시장 현황 (2026-03-15)
유효 공고 30,655건 | 오늘 신규 171,228건 | 전체 평균연봉 4,212만원

🔥 인기 기술 스택 TOP 10
 1. 재고관리  1,917건  (평균 4,151만원)
 2. 데이터분석  1,553건
 ...

📍 지역별 공고 분포
· 서울  15,224건
· 경기  7,764건
...
```

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

## 29. 태그 기반 검색(방안 3)의 성능 평가 — 태그가 오히려 검색 품질을 악화

### Problem

시맨틱 태깅(방안 3)이 실제로 검색 품질을 개선하는지 확인할 객관적 지표가 없었습니다. 기존 `evaluate_tagging.py`는 "백엔드 검색 결과에 '백엔드'가 있는가"처럼 순환 논리를 사용하여 의미 없는 수치를 산출했습니다.

### Evaluation Setup

**TREC-style 풀링 + 룰 기반 관련도 판정** 방식으로 재설계:

- **평가 쿼리**: `tests/judge_queries.json` — 43개 수동 작성 쿼리
  - Type A (12개): 키워드 직접형 — 통제군
  - Type B (16개): 시맨틱형 — "Spring Boot로 API 서버 만드는 개발자"처럼 자연어
  - Type C (12개): 모호형 — 직무가 불명확한 광범위 쿼리
  - Type D (3개): 엣지케이스 — 부정 조건, 복합 추론
- **후보 수집**: `tests/collect_candidates.py --no-rerank` → 480건 (`tests/candidates.json`)
- **관련도 판정**: `tests/generate_judgments.py` — 지역/고용형태/경력/직무 키워드 매칭 규칙으로 0–3점 부여 (`tests/my_judgments.json`)
- **지표 계산**: `tests/compute_metrics.py` → NDCG@K, P@K, Hit@K

### Results

**전체 지표 (baseline vs +tags)**

| 지표 | baseline | +tags | Delta |
|------|----------|-------|-------|
| NDCG@10 | 0.7534 | 0.6572 | **-0.0961** |
| P@10 | 0.6024 | 0.5190 | -0.0833 |
| Hit@10 | 0.9048 | 0.8810 | -0.0238 |

**쿼리 유형별 NDCG@10**

| 유형 | baseline | +tags | Delta |
|------|----------|-------|-------|
| A (키워드 직접형) | 0.7844 | 0.8681 | **+0.0837** |
| B (시맨틱형) | 0.6630 | 0.4842 | **-0.1788** |
| C (모호형) | 0.9528 | 0.7770 | **-0.1758** |
| D (엣지케이스) | 0.2832 | 0.1997 | -0.0836 |

### Root Cause

**① 태그 AND 조건 과도 적용 — 결과 과소 반환**

C11 "경기 제조 생산 공장 경력 무관 신입": +tags 모드는 "제조", "생산", "공장" 세 토큰이 모두 AND 매칭되는 공고만 반환 → 1건 (NDCG 0.9938 → 0.0). baseline은 `announcement_name` OR 조건으로 9건의 관련 공고를 찾습니다.

**② 태그 의미 범위 과도 확장 — 노이즈 유입**

B05 "파이썬으로 데이터 분석하는 직무 서울 경기": +tags 상위에 "글로벌 크리에이티브 매니저", "피부과의원 컨설팅" 등 완전 무관한 공고가 노출. "데이터", "분석" 태그가 본래 의도와 다른 직군에도 붙어 있어 노이즈가 상위로 올라옵니다. (NDCG 0.8928 → 0.1175, -87%)

**③ 시스템 구조적 한계**

D01 "SI 업체 말고 자사 서비스 개발하는 백엔드 신입 서울": 부정 조건 처리 불가. 두 모드 모두 백엔드 개발자 공고를 단 하나도 반환하지 못함 (NDCG 0.0).

### 4-Mode 비교 결과 (rerank 포함)

`tests/collect_candidates.py` (rerank 포함) 재실행 후 4-mode 비교:

**전체 지표**

| 지표 | baseline | +tags | +rerank | +tags+rerank |
|------|----------|-------|---------|--------------|
| NDCG@10 | 0.7534 | 0.6572 | **0.7708** | 0.6592 |
| P@10 | 0.6024 | 0.5190 | 0.6024 | 0.5190 |
| Hit@10 | 0.9048 | 0.8810 | 0.9048 | 0.8810 |

**유형별 NDCG@10**

| 유형 | baseline | +tags | +rerank | +tags+rerank |
|------|----------|-------|---------|--------------|
| A (키워드 직접형) | 0.7844 | 0.8681 | 0.7881 | 0.8614 |
| B (시맨틱형) | 0.6630 | 0.4842 | **0.7070** | 0.4923 |
| C (모호형) | 0.9528 | 0.7770 | **0.9552** | 0.7805 |
| D (엣지케이스) | 0.2832 | 0.1997 | 0.2832 | 0.1997 |

**주요 발견:**

- **+rerank는 baseline 대비 NDCG@10 +2.3% 개선** (0.7534 → 0.7708)
- **+tags+rerank는 +tags 대비 미미한 개선** (0.6572 → 0.6592): 재순위가 노이즈 유입 문제를 해결하지 못함
- B13 "국제 배송 무역 사무직": baseline=0.4860 → **+rerank=0.9469** (극적 개선), 반면 +tags+rerank=0.1413 (여전히 최악)
- Gemini 피드백 "태깅=Recall 확장, 재순위=노이즈 필터링" 가설은 **부분적으로만 맞음** — 재순위가 baseline recall 향상에는 효과적이나, 태깅이 끌어온 무관한 공고는 필터링 못 함

### Root Cause

**① 태그 AND 조건 과도 적용 — 결과 과소 반환**

C11 "경기 제조 생산 공장 경력 무관 신입": +tags 모드는 "제조", "생산", "공장" 세 토큰이 모두 AND 매칭되는 공고만 반환 → 1건 (NDCG 0.9938 → 0.0). baseline은 `announcement_name` OR 조건으로 9건의 관련 공고를 찾습니다.

**② 태그 의미 범위 과도 확장 — 노이즈 유입**

B05 "파이썬으로 데이터 분석하는 직무 서울 경기": +tags 상위에 "글로벌 크리에이티브 매니저", "피부과의원 컨설팅" 등 완전 무관한 공고가 노출. "데이터", "분석" 태그가 본래 의도와 다른 직군에도 붙어 있어 노이즈가 상위로 올라옵니다. (NDCG 0.8928 → 0.1175, -87%)

**③ 시스템 구조적 한계**

D01 "SI 업체 말고 자사 서비스 개발하는 백엔드 신입 서울": 부정 조건 처리 불가. 두 모드 모두 백엔드 개발자 공고를 단 하나도 반환하지 못함 (NDCG 0.0).

### Solution (미완)

1. **태그 매칭 AND → OR 완화** — 다단어 쿼리에서 토큰 전부 AND 매칭 대신 OR 또는 majority 조건 적용 (`db/io.py` `_build_query` 수정)
2. **태그 Taxonomy 기반 품질 통제** — LLM 태깅 프롬프트에 사전 정의된 직무 분류 목록을 제공하여 해당 목록 내에서만 태그 생성 (자유 텍스트 태그로 인한 오매핑 방지)
3. **태그 가중치 조정** — 태그 일치를 title 일치보다 낮은 점수로 처리하여 노이즈 억제
4. **재순위 단독 운용** — 태깅 개선 전까지는 +rerank만 사용 (baseline 대비 +2.3% NDCG 개선 확인됨)

---

## #30. LLM 쿼리 확장(+expanded) 평가 — keyword_expander 프롬프트 개선

**일자**: 2026-03-16
**목표**: 기존 AND 태그 매칭(+tags) 대비, LLM 쿼리 확장(+expanded) 모드의 검색 품질 비교

### 변경 사항

- `discord_bot/keyword_expander.py` PROMPT_TEMPLATE 교체
  - 구독 키워드 동의어 확장 → **채용 공고 제목·태그 인식형 확장**
  - 공고 제목 동의어 + DB 태그명을 한 번의 LLM 호출(EXAONE)로 생성
  - `search_recruits_by_filter(expanded_keywords=...)` → 제목·태그 OR 매칭
- `tests/collect_candidates.py` `+expanded` 모드 추가 (v4)
- LLM 호출: 기존 `expand_keyword()` 1회 → 그대로 1회 (추가 호출 없음)

### 평가 결과 (candidates_v4.json, 43 쿼리)

| Metric   | baseline | +tags  | +expanded | vs baseline |
|----------|----------|--------|-----------|-------------|
| ndcg@5   | 0.6617   | 0.5587 | 0.5051    | -0.1566     |
| p@5      | 0.6571   | 0.5905 | 0.5220    | -0.1352     |
| hit@5    | 0.8571   | 0.8333 | 0.7805    | -0.0767     |
| ndcg@10  | 0.6644   | 0.5789 | 0.5274    | -0.1370     |
| p@10     | 0.6048   | 0.5571 | 0.4976    | -0.1072     |
| hit@10   | 0.8810   | 0.8333 | **0.9024**| **+0.0215** |

**타입별 NDCG@10:**

| Type | baseline | +tags  | +expanded | vs baseline |
|------|----------|--------|-----------|-------------|
| A    | 0.7283   | 0.7839 | 0.5542    | -0.1741     |
| B    | 0.5332   | 0.3743 | **0.4846**| -0.0486     |
| C    | 0.8624   | 0.7513 | 0.6932    | -0.1692     |
| D    | 0.2724   | 0.0930 | 0.0256    | -0.2468     |

**+expanded 승리 케이스 (NDCG@10 기준):**

| QID | 쿼리 요약 | baseline | +expanded | delta |
|-----|-----------|----------|-----------|-------|
| B02 | AWS/쿠버네티스 인프라 | 0.000 | 0.841 | +0.841 |
| B11 | 유아 영어 방문 선생님 | 0.359 | 0.934 | +0.575 |
| B10 | 커피 음료 카페 직원 | 0.499 | 1.000 | +0.501 |
| B13 | 국제 배송 무역 사무직 | 0.121 | 0.506 | +0.385 |
| C08 | 영업직 인센티브 | 0.491 | 0.867 | +0.376 |

**+expanded 패배 케이스 (NDCG@10 기준):**

| QID | 쿼리 요약 | baseline | +expanded | delta |
|-----|-----------|----------|-----------|-------|
| B01 | Spring Boot 백엔드 | 1.000 | 0.066 | -0.934 |
| A10 | 임원 비서 경력직 | 0.760 | 0.000 | -0.760 |
| D03 | 그로스 마케터 | 0.817 | 0.077 | -0.740 |
| A06 | 경기 생산직 신입 | 1.000 | 0.258 | -0.742 |
| B05 | 파이썬 데이터 분석 | 0.739 | 0.109 | -0.630 |

### 분석

**전체 결론**: baseline > +tags > +expanded (NDCG@5/10 모두)

**방향은 맞지만 OR 매칭이 문제**:
- 의미 쿼리(B-type)에서 +expanded(0.485)는 +tags(0.374) 대비 +0.111 개선 → 어휘 불일치 해소 효과 확인
- 그러나 직접 키워드 쿼리(A·C type)에서 OR 확장이 오히려 정밀도를 낮춤
- 핵심 원인: `expanded_keywords` 설정 시 AND 매칭이 OR 매칭으로 완전 대체됨 → precision↓
  - B01 사례: "Spring Boot API 서버 개발자" → 확장 후 다양한 개발 용어 OR 매칭 → 가장 최신 공고(id.desc) 순으로 나열되어 관련성 낮은 결과 등장
  - A06 사례: "생산직" → "공장, 라인, 조립, 제조" 등 확장 → 지역(경기) 조건과 결합해도 너무 많은 결과

**Hit@10은 +0.021 개선**: 확장 키워드가 recall을 높임. 관련 공고를 찾긴 찾되 순위가 낮아진 것.

### 다음 과제

**적응형 확장(Adaptive Expansion)**: 일반 AND 매칭 결과가 충분하면 baseline, 부족하면 LLM 확장으로 fallback
- 현재 `fallback_threshold = 3`(use_tags=True) / `1`(use_tags=False)을 활용해 확장 키워드를 fallback으로 사용
- 즉: `AND keyword match → 결과 < 3 → expanded OR match`
- 이렇게 하면 직접 키워드 케이스는 baseline 유지, 어휘 불일치 케이스에서만 확장 동작

→ **#31에서 구현 및 평가 완료**

---

## #31. 적응형 LLM 확장(+adaptive) 구현 및 평가

**일자**: 2026-03-16
**목표**: AND 결과 부족 시에만 LLM 쿼리 확장 OR 매칭으로 fallback하는 적응형 방식 평가

### 변경 사항

- `discord_bot/llm.py` `sql_search()` 수정
  - 기존: 항상 `expand_keyword()` 호출 → `expanded_keywords`로 검색
  - 변경: 1차 AND 매칭 → 결과 < `ADAPTIVE_THRESHOLD(3)` 이면 LLM 확장 2차 검색
  - LLM 호출: 결과 부족 케이스에서만 1회 (충분한 경우 0회)
- `tests/collect_candidates.py` `+adaptive` 모드 추가 (v5)

### 평가 결과 (candidates_v5.json, 43 쿼리)

| Metric   | baseline | +tags  | +expanded | +adaptive | vs baseline |
|----------|----------|--------|-----------|-----------|-------------|
| ndcg@5   | 0.6569   | 0.5587 | 0.5511    | 0.6529    | -0.0040     |
| p@5      | 0.6571   | 0.5905 | 0.5641    | **0.6732**| **+0.0160** |
| hit@5    | 0.8571   | 0.8333 | 0.8718    | 0.8293    | -0.0279     |
| ndcg@10  | 0.6587   | 0.5803 | 0.5865    | **0.6673**| **+0.0086** |
| p@10     | 0.6048   | 0.5571 | 0.5538    | **0.6317**| **+0.0269** |
| hit@10   | 0.8810   | 0.8333 | 0.9231    | 0.8537    | -0.0273     |

**타입별 NDCG@10:**

| Type | baseline | +tags  | +expanded | +adaptive | vs baseline |
|------|----------|--------|-----------|-----------|-------------|
| A    | 0.7139   | 0.7833 | 0.5615    | 0.7387    | **+0.0249** |
| B    | 0.5370   | 0.3828 | 0.5408    | 0.5243    | -0.0127     |
| C    | 0.8522   | 0.7459 | 0.7312    | **0.8922**| **+0.0400** |
| D    | 0.2724   | 0.0930 | 0.4174    | 0.2724    | +0.0000     |

### 분석

**핵심 결과**: **+adaptive가 최초로 baseline을 초과** (NDCG@10: +0.0086, p@10: +0.0269)

**adaptive가 발동된 쿼리 (len(no_tags) < 3, 5건):**

| QID | 쿼리 | baseline | +adaptive | delta |
|-----|------|----------|-----------|-------|
| A02 | 인천 물류센터 계약직 신입 | 0.449 | 0.859 | **+0.410** |
| A07 | 서울 일본어 강사 계약직 | 0.220 | 0.359 | **+0.139** |
| A10 | 서울 임원 비서 경력직 | 0.562 | 0.311 | -0.251 |
| B11 | 유아 영어 방문 선생님 | 0.494 | 0.303 | -0.191 |
| C01 | 서울 경력무관 사무직 연봉 3000 | 0.413 | 0.000 | -0.413 |

- 발동률 5/43 (≈12%) — AND 결과 충분한 대다수는 baseline 그대로 유지
- 승리 2건, 패배 3건 — LLM 확장이 발동해도 항상 개선되는 것은 아님

**남은 한계**: 어휘 불일치이면서 AND가 3건 이상 반환하는 케이스(B02 AWS/쿠버네티스 등)는 여전히 미개선.
`ADAPTIVE_THRESHOLD=3`이 너무 낮아 관련 없는 3건을 반환해도 발동 안 됨 — 임계값 상향(예: 5) 또는 rerank 점수 기반 발동 조건 검토 필요.

---
