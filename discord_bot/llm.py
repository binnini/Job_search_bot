import re
from datetime import date
from db.io import search_recruits_by_filter
from db.JobPreprocessor import JobPreprocessor

REGIONS = [
    '서울', '경기', '인천', '부산', '대구', '광주', '대전', '울산', '세종',
    '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]

FORM_KEYWORDS = ['정규직', '계약직', '인턴', '파견직', '프리랜서', '아르바이트']

STOPWORDS = [
    '공고', '채용', '보여줘', '찾아줘', '알려줘', '검색해줘', '검색', '추천',
    '이상', '이하', '까지', '에서', '부터', '으로',
    '좀', '주세요', '해줘', '해주세요', '연봉', '경력',
    '모집하는', '모집', '마감',
]


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
    remaining = query

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

    # 연봉 — "N천만원" → "N만원" → "연봉 N" 순서로 매칭
    if m := re.search(r'(\d+)\s*천\s*만\s*원', remaining):
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

    # 키워드 — 구조화된 패턴 제거 후 남은 유효 텍스트
    for sw in STOPWORDS:
        remaining = remaining.replace(sw, ' ')
    keyword = re.sub(r'\s+', ' ', remaining).strip()
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
