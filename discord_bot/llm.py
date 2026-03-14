from langchain_community.llms import Ollama
from langchain_core.output_parsers import JsonOutputParser
from dotenv import load_dotenv
from discord_bot.prompt_templates import recruit_filter_prompt
import os
from datetime import date, datetime
from db.io import search_recruits_by_filter
from db.JobPreprocessor import JobPreprocessor

load_dotenv()

llm = Ollama(
    model="gemma3:4b",
    base_url=os.getenv("LOCAL_LLM_URL")
)

def recruit_filter(query):
    chain = recruit_filter_prompt | llm | JsonOutputParser()
    return chain.invoke({"today": date.today(), "today_year": date.today().year, "query": query})

def sql_search(query, limit=5):
    filters = recruit_filter(query)

    min_deadline = None
    raw_deadline = filters.get("min_deadline")
    if raw_deadline:
        try:
            min_deadline = datetime.strptime(raw_deadline, "%Y/%m/%d").date()
        except ValueError:
            pass

    form_code = JobPreprocessor.parse_form(filters.get("form") or "")

    recruits = search_recruits_by_filter(
        keyword=filters.get("keyword"),
        min_deadline=min_deadline,
        min_annual_salary=filters.get("min_annual_salary"),
        company_name=filters.get("company_name"),
        max_experience=filters.get("max_experience"),
        form=form_code,
        region=filters.get("region"),
        limit=limit,
    )

    if not recruits:
        return "조건에 맞는 채용 공고를 찾지 못했습니다."

    result_lines = []
    for i, r in enumerate(recruits, start=1):
        result_lines.append(
            f"📌 [{i}] {r.announcement_name} @ {r.company_name}\n"
            f"- 경력: {JobPreprocessor.stringify_experience(r.experience) or '무관'}\n"
            f"- 학력: {JobPreprocessor.stringify_education(r.education) or '무관'}\n"
            f"- 형태: {JobPreprocessor.stringify_form(r.form) or '정보 없음'}\n"
            f"- 연봉: {JobPreprocessor.stringify_salary(r.annual_salary) or '협의'}\n"
            f"- 마감일: {JobPreprocessor.stringify_deadline(r.deadline)}\n"
            f"🔗 {r.link}\n"
        )

    return "\n".join(result_lines)