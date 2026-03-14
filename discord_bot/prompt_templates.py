from langchain_core.prompts import PromptTemplate

recruit_filter_prompt = PromptTemplate.from_template("""
아래 채용 공고 검색 질문에서 조건을 추출해줘.

추출할 조건:
- keyword: 직무/기술 키워드 (예: "백엔드", "Python", "React"). 없으면 null
- company_name: 기업명. 없으면 null
- min_deadline: 최소 마감일 (yyyy/mm/dd). 없으면 null
- min_annual_salary: 최소 연봉 (만원 단위 정수). 없으면 null
- max_experience: 최대 요구 경력 연수 (정수). 신입이면 0. 없으면 null
- form: 고용형태 (정규직/계약직/인턴/파견직/프리랜서 중 하나). 없으면 null
- region: 근무 지역 (예: "서울", "부산"). 없으면 null

규칙:
- min_deadline: 특정 월 지정 시 그 달 1일로 설정 (예: "8월" → {today_year}/08/01)
- "오늘", "이번주" 등 상대적 날짜는 오늘({today}) 기준으로 계산
- JSON만 출력하고 설명은 쓰지 마

질문: {query}

예시:
{{
  "keyword": "백엔드",
  "company_name": null,
  "min_deadline": "2026/08/01",
  "min_annual_salary": 5000,
  "max_experience": 3,
  "form": "정규직",
  "region": "서울"
}}

JSON 결과:
""")