import re
from datetime import date
from db.io import search_recruits_by_filter
from db.JobPreprocessor import JobPreprocessor
from discord_bot.notifier import format_recruit

REGIONS = [
    '서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '세종',
    '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]

FORM_KEYWORDS = ['정규직', '계약직', '인턴', '파견직', '프리랜서', '아르바이트']

STOPWORDS = {
    '공고', '채용', '보여줘', '찾아줘', '알려줘', '검색해줘', '검색', '추천',
    '이상', '이하', '까지', '에서', '부터', '으로', '에서의', '로서',
    '좀', '주세요', '해줘', '해주세요', '연봉', '경력',
    '모집하는', '모집', '마감',
    '일할', '수', '있는', '있어', '원하는', '하는', '하고', '싶은', '싶어',
    '찾는', '구하는', '되는', '위한', '관련', '관한',
}

# 사용자 쿼리 동의어: 영문 약어·구어체 → 검색 키워드로 정규화 (토큰 단위 적용)
QUERY_SYNONYMS = {
    'FE': '프론트엔드',
    'BE': '백엔드',
    'frontend': '프론트엔드',
    'backend': '백엔드',
    'fullstack': '풀스택',
    'devops': 'DevOps',
    '데이터분석가': '데이터 분석',
    '데이터사이언티스트': '데이터 분석',
    '데이터과학자': '데이터 분석',
    '개발직': '개발자',
    '기획자': '서비스기획',
    '퍼블리셔': 'UI퍼블리셔',
}

# 회사명으로 오인하면 안 되는 직무/직종 키워드
JOB_KEYWORDS = {
    '개발', '개발자', '백엔드', '프론트엔드', '풀스택',
    '디자이너', '디자인', 'UI', 'UX',
    '마케팅', '마케터',
    '영업', '영업직',
    '회계', '재무', '경리',
    '고객응대', '고객서비스', 'CS',
    '물류', '유통', '배송',
    '데이터', '데이터분석',
    '기획', 'PM', 'PO',
    'HR', '인사', '총무',
    '연구', '연구원',
    '생산', '제조', '품질',
    '교육', '강사',
}


def _normalize_query(query: str) -> str:
    """사용자 쿼리 토큰 단위로 동의어 치환."""
    return ' '.join(QUERY_SYNONYMS.get(t, t) for t in query.split())


def extract_filters(query: str) -> dict:
    filters = {
        'keyword': None,
        'region': None,
        'form': None,
        'max_experience': None,
        'min_annual_salary': None,
        'min_deadline': None,
        'company_name': None,
    }
    remaining = _normalize_query(query)

    # 지역
    for region in REGIONS:
        if region in remaining:
            filters['region'] = region
            remaining = remaining.replace(region, ' ', 1)
            break

    # 고용형태
    for form in FORM_KEYWORDS:
        if form in remaining:
            filters['form'] = form
            remaining = remaining.replace(form, ' ', 1)
            break

    # 경력 — "신입" / "경력 N년" / "N년 이상·차"
    if '신입' in remaining:
        filters['max_experience'] = 0
        remaining = remaining.replace('신입', ' ', 1)
    elif m := re.search(r'경력\s*(\d+)\s*년\s*(?:이상|차)?', remaining):
        filters['max_experience'] = int(m.group(1))
        remaining = remaining[:m.start()] + remaining[m.end():]
    elif m := re.search(r'(\d+)\s*년\s*(?:이상|차)', remaining):
        filters['max_experience'] = int(m.group(1))
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 연봉 — "N억..." → "N천만원" → "N만원" → "연봉 N" 순서로 매칭
    if m := re.search(r'(\d+)\s*억\s*(?:(\d+)\s*천\s*만\s*원?)?', remaining):
        eok = int(m.group(1)) * 10000
        cheon = int(m.group(2)) * 1000 if m.group(2) else 0
        filters['min_annual_salary'] = eok + cheon
        remaining = remaining[:m.start()] + remaining[m.end():]
    elif m := re.search(r'(\d+)\s*천\s*만\s*원', remaining):
        filters['min_annual_salary'] = int(m.group(1)) * 1000
        remaining = remaining[:m.start()] + remaining[m.end():]
    elif m := re.search(r'(\d+)\s*만\s*원', remaining):
        filters['min_annual_salary'] = int(m.group(1))
        remaining = remaining[:m.start()] + remaining[m.end():]
    elif m := re.search(r'연봉\s*(\d+)', remaining):
        filters['min_annual_salary'] = int(m.group(1))
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 마감일 — "오늘" / "이번달" / "다음달" / "N월"
    today = date.today()
    if '오늘' in remaining:
        filters['min_deadline'] = today
        remaining = remaining.replace('오늘', ' ', 1)
    elif re.search(r'이번\s*달', remaining):
        filters['min_deadline'] = today.replace(day=1)
        remaining = re.sub(r'이번\s*달', ' ', remaining, count=1)
    elif re.search(r'다음\s*달', remaining):
        month = today.month % 12 + 1
        year = today.year + (1 if today.month == 12 else 0)
        filters['min_deadline'] = date(year, month, 1)
        remaining = re.sub(r'다음\s*달', ' ', remaining, count=1)
    elif m := re.search(r'(\d{1,2})\s*월', remaining):
        month = int(m.group(1))
        year = today.year if month >= today.month else today.year + 1
        filters['min_deadline'] = date(year, month, 1)
        remaining = remaining[:m.start()] + remaining[m.end():]

    # 기업명 — "X 공고" / "X 채용" 패턴: remaining 기준으로 검사 (이미 처리된 필터 제외)
    if m := re.match(r'^(\S+)\s+(?:공고|채용)', remaining.strip()):
        candidate = m.group(1)
        if (candidate not in REGIONS and
                candidate not in FORM_KEYWORDS and
                candidate not in ['신입', '경력'] and
                candidate not in JOB_KEYWORDS and
                candidate not in STOPWORDS):
            filters['company_name'] = candidate
            remaining = remaining.replace(candidate, ' ', 1)

    # 키워드 — 구조화된 패턴 제거 후 남은 유효 텍스트 (토큰 단위 stopword 제거)
    tokens = [t for t in remaining.split() if t not in STOPWORDS]
    keyword = ' '.join(tokens).strip()
    if keyword:
        filters['keyword'] = keyword

    return filters


def sql_search(query, limit=5):
    filters = extract_filters(query)
    form_code = JobPreprocessor.parse_form(filters.get('form') or '')

    recruits = search_recruits_by_filter(
        keyword=filters.get('keyword'),
        min_deadline=filters.get('min_deadline'),
        min_annual_salary=filters.get('min_annual_salary'),
        company_name=filters.get('company_name'),
        max_experience=filters.get('max_experience'),
        form=form_code,
        region=filters.get('region'),
        limit=limit,
    )

    if not recruits:
        return "조건에 맞는 채용 공고를 찾지 못했습니다."

    result_lines = [format_recruit(i, r, include_education=True) for i, r in enumerate(recruits, start=1)]
    return "\n\n".join(result_lines)
