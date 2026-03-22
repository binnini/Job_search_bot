"""
수동 관련도 판정(Relevance Judgment) 기반 검색 품질 테스트.

판정 점수 기준:
  0 = 관련 없음
  1 = 낮은 관련도 (직종·지역·경력 중 하나 이상 불일치)
  2 = 부분 관련  (일부 조건 불일치 — 경력 부족, 지역 근접, form 불일치 등)
  3 = 높은 관련도 (모든 주요 조건 충족)

테스트 구성:
  - TestJudgmentStructure : 판정 데이터 형식·일관성 검증 (DB 불필요, 항상 실행)
  - TestSearchQuality     : 실제 검색 결과와 판정 비교 (DB 필요, --db 플래그로 실행)
                            pytest tests/test_relevance_judgments.py --db

쿼리 유형:
  A 시리즈 — 명시적 쿼리 (지역·직종·경력·고용형태 직접 명시)
  B 시리즈 — 시맨틱 쿼리 (자연어, 직종·기술 암시)
  C 시리즈 — 모호한 쿼리 (조건이 복합적이거나 느슨함)
  D 시리즈 — 엣지케이스 (특수 조건, SI 제외 등)
"""

import pytest
from tests.write_judgments import JUDGMENTS

# ── 쿼리 ID → 검색어 매핑 ──────────────────────────────────────────────────────

QUERIES: dict[str, str] = {
    # A 시리즈: 명시적 쿼리
    "A01": "서울 백엔드 개발자 경력 3년 정규직",
    "A02": "인천 물류센터 계약직 신입",
    "A03": "서울 바리스타 신입 정규직 연봉 3000만원",
    "A04": "서울 콜센터 고객응대 신입 정규직",
    "A05": "부산 호텔 프론트 신입 정규직",
    "A06": "경기 생산직 신입 정규직",
    "A07": "서울 일본어 강사 계약직",
    "A08": "서울 웹 디자이너 경력 2년 정규직",
    "A09": "서울 조리사 한식당 정규직 경력 무관",
    "A10": "서울 임원 비서 경력직",
    "A11": "서울 영상편집 마케터 경력직 광고대행사",
    "A12": "경기 물류 관리 사원 계약직",
    # B 시리즈: 시맨틱 쿼리
    "B01": "Spring Boot로 API 서버 만드는 개발자 서울 정규직",
    "B02": "AWS나 쿠버네티스 다루는 인프라 엔지니어 경력직",
    "B03": "React 쓰는 화면 개발자 경력직 서울",
    "B04": "Figma로 UI 디자인하는 경력 디자이너 서울",
    "B05": "파이썬으로 데이터 분석하는 직무 서울 경기",
    "B06": "직원 채용하고 온보딩 관리하는 HR 담당자 서울",
    "B07": "인스타그램 페이스북 광고 운영하는 마케터 서울",
    "B08": "건물 전기 설비 점검하는 기술직 서울 경기",
    "B09": "세금 신고 장부 관리하는 경리 신입 서울",
    "B10": "커피 음료 만드는 카페 직원 서울 경기",
    "B11": "유아 영어 방문 수업 선생님 프리랜서 경기",
    "B12": "집에서 할 수 있는 유튜브 영상 편집 프리랜서",
    "B13": "국제 배송 서류 처리하는 무역 사무직 서울",
    "B14": "C#이나 WPF로 윈도우 프로그램 만드는 개발자 경기",
    "B15": "보안 취약점 분석하는 엔지니어 서울 경기 정규직",
    "B16": "식당 오픈부터 직원 관리까지 하는 매니저 서울",
    # C 시리즈: 모호한 쿼리
    "C01": "서울 경력 무관 사무직 정규직 연봉 3000만원",
    "C02": "경기 수도권 물류 관련 계약직",
    "C03": "서울 마케팅 경력 2~3년 정규직",
    "C04": "서울 경기 요식업 주방 홀 정규직 경력 무관",
    "C05": "연봉 5000만원 이상 경력직 서울",
    "C06": "IT 분야 신입 서울 연봉 협의 정규직",
    "C07": "주 4~5일 근무 경기 신입 정규직",
    "C08": "서울 영업직 경력 무관 인센티브 있는 곳",
    "C09": "부산 경남 정규직 경력 무관",
    "C10": "서울 디자인 관련 신입 정규직",
    "C11": "경기 제조 생산 공장 경력 무관 신입",
    "C12": "서울 단기 아르바이트 일당 높은 곳 경력 무관",
    # D 시리즈: 엣지케이스
    "D01": "SI 업체 말고 자사 서비스 개발하는 백엔드 신입 서울",
    "D02": "판교나 강남 재택 주 2회 이상 되는 서버 개발자 경력 3년",
    "D03": "서울 스타트업에서 마케팅이랑 데이터 분석 같이 하는 그로스 마케터",
}

VALID_SCORES = {0, 1, 2, 3}
RELEVANT_THRESHOLD = 2      # 이 점수 이상을 '관련 있음'으로 간주
MIN_SEARCH_AVG_SCORE = 1.0  # 검색 결과의 최소 평균 관련도 기준

# 관련 결과가 거의 없는 검색 한계 케이스 — 낮은 관련도 비율이 설계 의도
# D 시리즈: SI 제외·재택 조건·그로스 마케터 등 복합 조건 엣지케이스
# B08: 전기 설비 기술직 — 판정 pool에 관련 공고 희소
# B13: 무역 사무직 국제 배송 — 판정 pool에 관련 공고 없음
EDGE_CASE_QUERIES = {"D01", "D02", "D03", "B08", "B13", "B14"}


# ── 구조 검증 (DB 불필요) ──────────────────────────────────────────────────────

class TestJudgmentStructure:
    """판정 데이터 형식·일관성 검증. DB 연결 없이 항상 실행."""

    def test_all_scores_in_valid_range(self):
        """모든 판정 점수가 0~3 범위 내에 있어야 한다."""
        invalid = [
            (qid, rid, score)
            for qid, recruits in JUDGMENTS.items()
            for rid, score in recruits.items()
            if score not in VALID_SCORES
        ]
        assert not invalid, f"유효하지 않은 점수 발견: {invalid}"

    def test_all_query_ids_have_mapping(self):
        """JUDGMENTS의 모든 쿼리 ID가 QUERIES에 정의되어 있어야 한다."""
        missing = set(JUDGMENTS) - set(QUERIES)
        assert not missing, f"QUERIES에 없는 쿼리 ID: {missing}"

    def test_non_edge_queries_have_highly_relevant(self):
        """엣지케이스 제외 쿼리는 최소 1건 이상 score=3 공고를 포함해야 한다."""
        missing = [
            qid for qid, recruits in JUDGMENTS.items()
            if recruits
            and qid not in EDGE_CASE_QUERIES
            and not any(s == 3 for s in recruits.values())
        ]
        assert not missing, f"score=3 판정이 없는 쿼리: {missing}"

    def test_no_duplicate_recruit_per_query(self):
        """쿼리 내 동일 recruit_id가 중복 판정되면 안 된다."""
        for qid, recruits in JUDGMENTS.items():
            ids = list(recruits.keys())
            assert len(ids) == len(set(ids)), f"{qid}에 중복 recruit_id 존재"

    @pytest.mark.parametrize("query_id", [
        qid for qid in JUDGMENTS if qid not in EDGE_CASE_QUERIES
    ])
    def test_relevant_ratio_per_query(self, query_id):
        """엣지케이스 제외 쿼리는 관련 있음(score >= 2) 비율이 10% 이상이어야 한다."""
        recruits = JUDGMENTS[query_id]
        if not recruits:
            pytest.skip(f"{query_id}: 판정 데이터 없음")
        relevant = sum(1 for s in recruits.values() if s >= RELEVANT_THRESHOLD)
        ratio = relevant / len(recruits)
        assert ratio >= 0.1, (
            f"{query_id}: 관련 공고 비율 {ratio:.0%} < 10% "
            f"(관련={relevant}/{len(recruits)})"
        )


# ── 검색 품질 (DB 필요) ────────────────────────────────────────────────────────

def pytest_addoption(parser):
    parser.addoption("--db", action="store_true", default=False,
                     help="DB 연결이 필요한 검색 품질 테스트 실행")


@pytest.fixture(scope="session")
def db_enabled(request):
    return request.config.getoption("--db")


@pytest.fixture(scope="session")
def search_fn(db_enabled):
    if not db_enabled:
        pytest.skip("DB 테스트는 --db 플래그 필요: pytest --db")
    from dotenv import load_dotenv
    load_dotenv(override=True)
    from db.io import search_recruits_by_filter
    return search_recruits_by_filter


class TestSearchQuality:
    """실제 검색 결과와 수동 판정 비교. pytest --db 로 실행."""

    @pytest.mark.parametrize("query_id,query_str", QUERIES.items())
    def test_average_relevance_at_5(self, query_id, query_str, search_fn):
        """상위 5건 결과 중 판정이 있는 공고의 평균 관련도가 기준 이상이어야 한다."""
        judgments = JUDGMENTS.get(query_id, {})
        if not judgments:
            pytest.skip(f"{query_id}: 판정 데이터 없음")

        results = search_fn(keyword=query_str, limit=5)
        result_ids = {r.id for r in results}

        judged_results = {
            rid: score
            for rid, score in judgments.items()
            if rid in result_ids
        }
        if not judged_results:
            pytest.skip(f"{query_id}: 검색 결과 중 판정된 공고 없음 (공고 만료 가능성)")

        avg_score = sum(judged_results.values()) / len(judged_results)
        assert avg_score >= MIN_SEARCH_AVG_SCORE, (
            f"{query_id} ({query_str!r}): "
            f"평균 관련도 {avg_score:.2f} < 기준 {MIN_SEARCH_AVG_SCORE} "
            f"(판정된 결과 {len(judged_results)}건: {judged_results})"
        )

    @pytest.mark.parametrize("query_id,query_str", QUERIES.items())
    def test_hit_at_5(self, query_id, query_str, search_fn):
        """상위 5건 결과 중 관련 있는 공고(score >= 2)가 1건 이상 포함되어야 한다."""
        judgments = JUDGMENTS.get(query_id, {})
        if not judgments:
            pytest.skip(f"{query_id}: 판정 데이터 없음")

        results = search_fn(keyword=query_str, limit=5)
        result_ids = {r.id for r in results}

        hit = any(
            judgments.get(rid, 0) >= RELEVANT_THRESHOLD
            for rid in result_ids
        )
        if not any(rid in judgments for rid in result_ids):
            pytest.skip(f"{query_id}: 검색 결과 중 판정된 공고 없음 (공고 만료 가능성)")

        assert hit, (
            f"{query_id} ({query_str!r}): "
            f"상위 5건에 관련 공고 없음 (returned={result_ids})"
        )
