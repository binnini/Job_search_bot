from langchain_core.prompts import PromptTemplate

recruit_filter_prompt = PromptTemplate.from_template("""
아래의 질문에서 채용 조건을 추출해줘.
가능한 조건: 기업명(company_name), 최소마감기한(min_deadline), 최소연봉(annual_salary)
                                              
최소마감기한은 yyyy/mm/dd 형식이고 사용자가 특정 month를 지정하는 경우 그 달의 1일을 min_deadline으로 설정해. 그리고 오늘 내일, 이번주 같은 명령어도 {today}를 오늘로 삼고 계산해서 보내줘. 예를 들어, "8월에 모집하는 공고 보여줘"라고 질문이 오면 {today}에서 수집한 년도 yyyy/08/01 형태가 되는거야.
최소연봉은 만원 단위로 설정해줘.

만약 조건을 모르겠다면 null로 설정해줘.
형식은 JSON으로 출력해줘.

질문: {query}
                                                                                            
예시:
{{
  "company_name": "카카오",
  "min_deadline": "2025/07/04",
  "min_annual_salary": "5000",
}}

JSON 결과:
""")