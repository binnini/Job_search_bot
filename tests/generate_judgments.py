"""
Rule-based LLM-as-judge 대체 스크립트.
candidates.json의 pool을 읽어 (query, candidate) 관련도 0-3점 부여.

스코어링 기준:
  3 = 직무/역할 + 지역 + 고용형태 + 경력 모두 충족
  2 = 직무/역할 충족 + 1~2개 조건 부분 불일치
  1 = 직무/역할 부분 일치 또는 조건 대부분 불일치
  0 = 직무/역할 완전 불일치
"""
import json
import re

CANDIDATES = "tests/candidates_v5.json"
OUTPUT     = "tests/my_judgments_v5.json"

# query_id → 관련 키워드 (이 중 하나라도 announcement_name에 있으면 직무 일치)
JOB_KEYWORDS = {
    "A01": ["백엔드", "서버", "backend", "Back-end"],
    "A02": ["물류", "로지스", "창고", "배송", "센터"],
    "A03": ["바리스타", "카페", "커피"],
    "A04": ["콜센터", "고객", "상담", "CS", "인바운드"],
    "A05": ["호텔", "프론트", "객실", "리셉션", "숙박"],
    "A06": ["생산", "제조", "공장", "라인", "조립"],
    "A07": ["일본어", "강사", "어학원", "교육"],
    "A08": ["웹", "디자이너", "디자인", "UI", "UX", "그래픽"],
    "A09": ["조리", "요리", "주방", "한식", "셰프"],
    "A10": ["비서", "임원", "어시스턴트", "수행"],
    "A11": ["영상편집", "편집", "영상", "마케터", "광고"],
    "A12": ["물류", "창고", "배송", "로지스"],
    # Semantic (B type): 자연어 쿼리 → 기대 직무 키워드
    "B01": ["백엔드", "서버", "Spring", "Java", "Kotlin", "Node", "Python", "개발자"],
    "B02": ["인프라", "DevOps", "AWS", "쿠버네티스", "Kubernetes", "클라우드", "시스템", "서버"],
    "B03": ["프론트엔드", "Front", "React", "Vue", "퍼블리셔", "UI개발", "FE"],
    "B04": ["디자이너", "UI", "UX", "Figma", "웹디자인", "그래픽"],
    "B05": ["데이터", "분석", "Python", "SQL", "머신러닝", "AI", "BI"],
    "B06": ["HR", "인사", "채용", "HRD", "인재"],
    "B07": ["마케터", "마케팅", "SNS", "디지털", "광고", "퍼포먼스"],
    "B08": ["전기", "설비", "기술", "전기기사", "시설", "엔지니어"],
    "B09": ["경리", "회계", "세무", "재무", "총무", "장부"],
    "B10": ["바리스타", "카페", "커피", "음료"],
    "B11": ["강사", "교사", "튜터", "영어", "방문"],
    "B12": ["영상편집", "편집", "유튜브", "영상"],
    "B13": ["무역", "수출", "수입", "통관", "포워딩", "물류"],
    "B14": ["C#", "WPF", ".NET", "윈도우", "Windows"],
    "B15": ["보안", "취약점", "정보보안", "Security", "해킹", "침해"],
    "B16": ["매니저", "점장", "식음", "F&B", "레스토랑", "외식"],
    # Ambiguous (C type): 넓은 직무 범위
    "C01": ["사무", "행정", "총무", "기획", "경영지원"],
    "C02": ["물류", "창고", "배송", "유통"],
    "C03": ["마케터", "마케팅", "브랜드", "광고", "홍보"],
    "C04": ["요리", "주방", "조리", "홀", "서빙", "식당", "외식"],
    "C05": [],  # 연봉 5000+ 경력직 서울 → 직무 제한 없음
    "C06": ["IT", "개발", "SW", "소프트웨어", "서버", "프론트", "데이터"],
    "C07": [],  # 주 4~5일 경기 신입 → 직무 제한 없음
    "C08": ["영업", "영업직", "세일즈", "B2B", "B2C"],
    "C09": [],  # 부산 경남 경력 무관 → 직무 제한 없음
    "C10": ["디자인", "디자이너", "그래픽", "UI", "UX", "영상"],
    "C11": ["생산", "제조", "공장", "품질", "조립", "라인"],
    "C12": [],  # 단기 알바 → 직무 제한 없음
    # Edge case (D type)
    "D01": ["백엔드", "서버", "개발자", "풀스택"],
    "D02": ["백엔드", "서버", "개발자"],
    "D03": ["마케터", "마케팅", "그로스", "데이터"],
}

# 지역 매핑: query region → 허용 지역 키워드
REGION_MAP = {
    "A01": ["서울"], "A02": ["인천"], "A03": ["서울"], "A04": ["서울"],
    "A05": ["부산"], "A06": ["경기"], "A07": ["서울"], "A08": ["서울"],
    "A09": ["서울"], "A10": ["서울"], "A11": ["서울"], "A12": ["경기"],
    "B01": ["서울"], "B02": ["서울", "경기", "인천"],
    "B03": ["서울"], "B04": ["서울"], "B05": ["서울", "경기"],
    "B06": ["서울"], "B07": ["서울"], "B08": ["서울", "경기"],
    "B09": ["서울"], "B10": ["서울", "경기"],
    "B11": ["경기"], "B12": [],  # 재택 → 지역 무관
    "B13": ["서울"], "B14": ["경기"], "B15": ["서울", "경기"],
    "B16": ["서울"],
    "C01": ["서울"], "C02": ["경기", "인천"],
    "C03": ["서울"], "C04": ["서울", "경기"],
    "C05": ["서울"], "C06": ["서울"],
    "C07": ["경기"], "C08": ["서울"],
    "C09": ["부산", "경남"], "C10": ["서울"],
    "C11": ["경기"], "C12": ["서울"],
    "D01": ["서울"], "D02": ["서울", "경기"],
    "D03": ["서울"],
}

# 고용형태: query form → 허용 form
FORM_MAP = {
    "A01": "정규직", "A02": "계약직", "A03": "정규직", "A04": "정규직",
    "A05": "정규직", "A06": "정규직", "A07": "계약직", "A08": "정규직",
    "A09": "정규직", "A10": None, "A11": None, "A12": "계약직",
    "B01": "정규직", "B02": None, "B03": None, "B04": None,
    "B05": None, "B06": None, "B07": None, "B08": None,
    "B09": None, "B10": None, "B11": "프리랜서", "B12": "프리랜서",
    "B13": None, "B14": None, "B15": "정규직", "B16": None,
    "C01": "정규직", "C02": "계약직", "C03": "정규직", "C04": "정규직",
    "C05": None, "C06": "정규직", "C07": "정규직", "C08": None,
    "C09": "정규직", "C10": "정규직", "C11": None, "C12": None,
    "D01": None, "D02": None, "D03": None,
}

# 경력 요구: None=무관, "신입"=신입 우선, "경력"=경력 우선, 숫자=최소년수
EXPERIENCE_MAP = {
    "A01": 3, "A02": "신입", "A03": "신입", "A04": "신입",
    "A05": "신입", "A06": "신입", "A07": None, "A08": 2,
    "A09": None, "A10": "경력", "A11": "경력", "A12": None,
    "B01": None, "B02": "경력", "B03": "경력", "B04": "경력",
    "B05": None, "B06": None, "B07": None, "B08": None,
    "B09": "신입", "B10": None, "B11": None, "B12": None,
    "B13": None, "B14": None, "B15": None, "B16": None,
    "C01": None, "C02": None, "C03": 2, "C04": None,
    "C05": "경력", "C06": "신입", "C07": "신입", "C08": None,
    "C09": None, "C10": "신입", "C11": None, "C12": None,
    "D01": "신입", "D02": 3, "D03": None,
}

# 최소 연봉 (만원, None이면 무관)
MIN_SALARY_MAP = {
    "A03": 3000, "C05": 5000, "C01": 3000,
}


def parse_salary(sal_str):
    """'3000만원/년' → 3000, '협의' → None"""
    if not sal_str or sal_str == "협의":
        return None
    m = re.search(r"(\d+)만원", sal_str)
    return int(m.group(1)) if m else None


def parse_experience_years(exp_str):
    """'3년 이상' → 3, '신입' → 0, '경력무관' → None"""
    if not exp_str:
        return None
    if "신입" in exp_str:
        return 0
    if "경력무관" in exp_str or "무관" in exp_str:
        return None
    m = re.search(r"(\d+)년", exp_str)
    return int(m.group(1)) if m else None


def score_candidate(qid, query, candidate):
    name = candidate["announcement_name"]
    region = candidate["region"]
    form = candidate["form"]
    experience = candidate["experience"]
    salary_str = candidate["salary"]

    score = 0

    # 1. 직무 매칭 (필수)
    keywords = JOB_KEYWORDS.get(qid, [])
    if keywords:
        job_match = any(kw.lower() in name.lower() for kw in keywords)
        if not job_match:
            return 0  # 직무 불일치 → 0
        score = 2  # 기본 2점 (직무 일치)
    else:
        # 직무 무관 (C05, C07, C09, C12) → 지역/형태로만 판단
        score = 2

    # 2. 지역 매칭
    allowed_regions = REGION_MAP.get(qid, [])
    if allowed_regions and not any(r in region for r in allowed_regions):
        score -= 1

    # 3. 고용형태 매칭
    required_form = FORM_MAP.get(qid)
    if required_form and required_form != form:
        score -= 1

    # 4. 경력 매칭
    required_exp = EXPERIENCE_MAP.get(qid)
    cand_years = parse_experience_years(experience)
    if required_exp == "신입":
        if cand_years is not None and cand_years > 1:
            score -= 1
        elif cand_years == 0 or cand_years is None:
            score += 1  # bonus for exact match
    elif required_exp == "경력":
        if cand_years == 0:
            score -= 1
    elif isinstance(required_exp, int):
        if cand_years is not None:
            if cand_years >= required_exp:
                score += 1  # bonus for meeting requirement
            elif cand_years < required_exp - 1:
                score -= 1

    # 5. 연봉 조건
    min_sal = MIN_SALARY_MAP.get(qid)
    if min_sal:
        cand_sal = parse_salary(salary_str)
        if cand_sal is not None and cand_sal < min_sal:
            score -= 1

    # D타입 특수 규칙
    if qid == "D01":
        # SI 업체 제외 조건 - 우리는 공고 이름만 보이므로 conservative
        # '백엔드/서버 개발자' 매칭되면 1점, 나머지는 0
        if not any(kw in name for kw in ["백엔드", "서버", "풀스택"]):
            return 0
        score = max(1, score)  # 자사서비스 여부 알 수 없으므로 최대 2
    elif qid == "D02":
        # 판교/강남 + 재택 조건 → 검색 결과에서 판별 불가, conservative
        score = min(2, score)
    elif qid == "D03":
        # 스타트업 + 그로스마케터 → 마케팅이면 2, 그로스/성장해킹 언급 있으면 3
        if any(kw in name for kw in ["그로스", "Growth", "퍼포먼스", "데이터"]):
            score = min(score + 1, 3)
        else:
            score = min(2, score)

    return max(0, min(3, score))


def main():
    with open(CANDIDATES, encoding="utf-8") as f:
        candidates = json.load(f)

    judgments = {}
    total_pairs = 0

    for q in candidates:
        qid = q["id"]
        query = q["query"]
        pool = q["pool"]
        scores = {}
        for cand in pool:
            cid = cand["id"]
            s = score_candidate(qid, query, cand)
            scores[str(cid)] = s
        judgments[qid] = scores
        total_pairs += len(scores)
        # Debug: print score distribution
        from collections import Counter
        dist = Counter(scores.values())
        print(f"{qid}: {len(scores)} candidates, dist={dict(sorted(dist.items()))}")

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(judgments, f, ensure_ascii=False, indent=2)

    print(f"\nTotal pairs scored: {total_pairs}")
    print(f"Saved to {OUTPUT}")


if __name__ == "__main__":
    main()
