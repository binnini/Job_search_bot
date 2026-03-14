"""
extract_filters() 단위 테스트 — DB 연결 불필요
"""
import pytest
from discord_bot.llm import extract_filters


# ── 단일 필터 ─────────────────────────────────────────────

class TestKeyword:
    def test_job_keyword_not_classified_as_company(self):
        f = extract_filters("개발자 공고 보여줘")
        assert f["keyword"] == "개발자"
        assert f["company_name"] is None

    def test_keyword_preserved_after_stopword_removal(self):
        f = extract_filters("백엔드 공고")
        assert f["keyword"] == "백엔드"

    def test_compound_keyword(self):
        f = extract_filters("데이터 분석 공고")
        assert f["keyword"] == "데이터 분석"

    def test_keyword_not_broken_by_stopwords(self):
        # '이', '가' 등 단일 글자 제거가 단어 내부를 파괴하면 안 됨
        f = extract_filters("데이터분석 공고")
        assert "데이터분석" in (f["keyword"] or "")


class TestRegion:
    def test_region_extracted(self):
        f = extract_filters("서울 공고")
        assert f["region"] == "서울"
        assert f["keyword"] is None

    def test_region_with_keyword(self):
        f = extract_filters("서울 마케팅 공고")
        assert f["region"] == "서울"
        assert f["keyword"] == "마케팅"

    def test_region_not_classified_as_company(self):
        # "부산 채용 공고" → company_name이 '채용'이 되면 안 됨
        f = extract_filters("부산 채용 공고")
        assert f["region"] == "부산"
        assert f["company_name"] is None


class TestForm:
    @pytest.mark.parametrize("query,expected", [
        ("정규직 공고", "정규직"),
        ("계약직 공고", "계약직"),
        ("인턴 공고 찾아줘", "인턴"),
        ("프리랜서 공고", "프리랜서"),
        ("아르바이트 공고", "아르바이트"),
    ])
    def test_form_extracted(self, query, expected):
        assert extract_filters(query)["form"] == expected


class TestExperience:
    def test_shinip(self):
        assert extract_filters("신입 공고")["max_experience"] == 0

    def test_years_with_prefix(self):
        assert extract_filters("경력 3년 이상 공고")["max_experience"] == 3

    def test_years_suffix(self):
        assert extract_filters("5년차 공고 보여줘")["max_experience"] == 5

    def test_5nyeoncha_no_company_name(self):
        # 경력 파싱 후 remaining에서 '5년차'가 사라져야 함 → company_name 오분류 방지
        f = extract_filters("5년차 공고 보여줘")
        assert f["company_name"] is None
        assert f["max_experience"] == 5


class TestSalary:
    def test_cheonman(self):
        assert extract_filters("연봉 3000만원 이상 공고")["min_annual_salary"] == 3000

    def test_cheonman_shorthand(self):
        assert extract_filters("연봉 4천만원 이상 채용")["min_annual_salary"] == 4000

    def test_eok(self):
        assert extract_filters("연봉 1억 이상 공고")["min_annual_salary"] == 10000

    def test_eok_large(self):
        assert extract_filters("연봉 2억 공고")["min_annual_salary"] == 20000


# ── 복합 필터 ─────────────────────────────────────────────

class TestMultipleFilters:
    def test_keyword_region_form(self):
        f = extract_filters("서울 개발자 정규직 공고")
        assert f["region"] == "서울"
        assert f["form"] == "정규직"
        assert f["keyword"] == "개발자"

    def test_keyword_experience_region(self):
        f = extract_filters("서울 마케팅 신입 공고")
        assert f["region"] == "서울"
        assert f["max_experience"] == 0
        assert f["keyword"] == "마케팅"

    def test_four_filters(self):
        f = extract_filters("서울 백엔드 정규직 신입 공고")
        assert f["region"] == "서울"
        assert f["keyword"] == "백엔드"
        assert f["form"] == "정규직"
        assert f["max_experience"] == 0


# ── 동의어 사전 ───────────────────────────────────────────

class TestQuerySynonyms:
    def test_FE_expands_to_frontend(self):
        f = extract_filters("FE 공고")
        assert f["keyword"] == "프론트엔드"

    def test_BE_expands_to_backend(self):
        f = extract_filters("BE 신입")
        assert f["keyword"] == "백엔드"
        assert f["max_experience"] == 0

    def test_backend_english_expands(self):
        f = extract_filters("backend 정규직")
        assert f["keyword"] == "백엔드"

    def test_data_analyst_synonym(self):
        f = extract_filters("데이터분석가 공고")
        assert f["keyword"] == "데이터 분석"


# ── 회사명 감지 ───────────────────────────────────────────

class TestCompanyName:
    def test_company_name_detected(self):
        f = extract_filters("카카오 공고 알려줘")
        assert f["company_name"] == "카카오"
        assert f["keyword"] is None

    def test_job_keyword_not_company(self):
        for kw in ["개발자", "백엔드", "디자이너", "마케팅", "영업직"]:
            f = extract_filters(f"{kw} 공고 보여줘")
            assert f["company_name"] is None, f"'{kw}'이 company_name으로 오분류됨"

    def test_stopword_not_company(self):
        # '채용' 자체가 company_name이 되면 안 됨
        f = extract_filters("부산 채용 공고")
        assert f["company_name"] is None


# ── 자연어 ────────────────────────────────────────────────

class TestNaturalLanguage:
    def test_colloquial_complex(self):
        f = extract_filters("서울에서 신입으로 일할 수 있는 마케팅 공고 찾아줘")
        assert f["region"] == "서울"
        assert f["max_experience"] == 0
        assert f["keyword"] == "마케팅"
