from langchain_community.llms import Ollama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from dotenv import load_dotenv
from discord_bot.prompt_templates import recruit_filter_prompt
from rag.vector_db_manager import vector_similar_search
import os
from datetime import date, datetime
from db.io import read_recruits_by_ids
from db.JobPreprocessor import JobPreprocessor

load_dotenv()

llm = Ollama(
    model="gemma3:4b",
    base_url=os.getenv("LOCAL_LLM_URL")
)

def recruit_filter(query):
    chain = recruit_filter_prompt | llm | JsonOutputParser()
    response = chain.invoke({"today":date.today(),"query":query})
    return build_filter(response)

def build_filter(metadata: dict) -> dict:
    filter_query = {}

    # # 연봉 필터 처리
    # salary = metadata.get("min_annual_salary")
    # if salary:
    #     filter_query["annual_salary"] = {"$gte": int(salary)}

    # 마감일 필터 처리
    deadline = metadata.get("min_deadline")
    if deadline:
        filter_query["deadline"] = {"$gte": deadline}

    # # 기업명 필터 (정확히 일치할 경우만 필터링)
    # company = metadata.get("company_name")
    # if company:
    #     filter_query["company_name"] = {"$eq": company}

    return filter_query

def rag_search(query,k=5):
    filter = recruit_filter(query)
    docs = vector_similar_search(query, filter, k)
    ids = [doc.id for doc in docs]
    recruits = read_recruits_by_ids(ids)
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