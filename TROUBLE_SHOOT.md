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
