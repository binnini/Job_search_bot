import sys
import os
import re

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from db.io import read_recruits, read_companies, read_full_region_names
import pandas as pd
from datetime import date
import logging
import spacy
from spacy.matcher import Matcher

def create_pattern_list():
    recruits = read_recruits()
    companies = read_companies()
    # recruit_tags = read_recruit_tags()
    full_regions = read_full_region_names()
    # tags = read_tags()

    # # SKILL (직무)
    # skill_names = recruits["name"].unique()
    # skill_patterns = [
    #     {"label": "SKILL", "pattern": skill} for skill in skill_names
    # ]

    # COMPNAY (회사명)
    company_names = companies["company_name"].unique()
    company_patterns = [
        {"label": "COMPANY", "pattern": company_name} for company_name in company_names
    ]

    # REGION (지역)
    region_names = full_regions["full_region_name"].unique()
    region_patterns = [
        {"label": "REGION", "pattern": region} for region in region_names
    ]

    # FORM (고용 형태)


    # EXPERIENCE (경력)
    nlp = spacy.load("ko_core_news_sm")  # 또는 custom pipeline
    matcher = Matcher(nlp.vocab)

    pattern = [
        {"IS_DIGIT": True},               # 숫자: 1, 2, 3...
        {"TEXT": {"REGEX": r"년(차)?"}},  # "년", "년차"
        {"TEXT": {"REGEX": r"이상|이하"}} # "이상", "이하"
    ]

    matcher.add("EXPERIENCE", [pattern])

    doc = nlp("경력 3년 이상 또는 5년차 이상만 지원 가능합니다.")
    matches = matcher(doc)

    for match_id, start, end in matches:
        span = doc[start:end]
        print("🔹 Found:", span.text)
    
    # sample_titles = recruits["announcement_name"]
    # experience_pattern = re.compile(r"""
    #     (신입(사원)?|초보\s*가능)                                      # 신입 관련
    # | (경력(직|자)?(\s*우대)?|경력\s*무관|무관)                       # 경력 관련
    # | (신입\s*[·/]\s*경력|신입\s+및\s+경력|신입\s+또는\s+경력)        # 신입/경력 복합형
    # | (\d+\s*년(\s*차)?\s*(이상|이하)?|\d+\s*~\s*\d+\s*년(차)?)        # 연차 표현
    # | (경력\s*\d+\s*년(\s*이상)?)                                     # 예: 경력 3년 이상
    # | (경험자|실무\s*경험자)                                          # 경험 기반
    # """, re.VERBOSE)

    # # 샘플 텍스트 리스트
    # keywords = set()
    # for title in sample_titles:
    #     matches = experience_pattern.findall(title)
    #     # findall이 group tuple을 반환하므로, 평탄화 후 빈 문자열 제외
    #     flattened = [m for group in matches for m in group if m]
    #     keywords.update(flattened)
    
    # print("keywords : ", keywords)
    
    # exp_lists = ["신입","경력","경력직","경력 사원","경력사원","경력자","경력무관","년이상"]
    # region_names = recruits["experience"].unique()
    # region_patterns = [
    #     {"label": "REGION", "pattern": region} for region in region_names
    # ]

    all_patterns = (
        company_patterns +
        region_patterns
    )

    # print(all_patterns)
    # ruler = nlp.add_pipe("entity_ruler", before="ner")
    # ruler.add_patterns(all_patterns)


if __name__ == "__main__":
    create_pattern_list()
