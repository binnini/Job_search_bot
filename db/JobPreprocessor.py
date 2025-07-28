from datetime import datetime, date, timedelta
import re

class JobPreprocessor:
    @staticmethod
    def sanitize_string(value):
        if not value or not isinstance(value, str):
            return None
        return value.strip().replace(",", "")

    @staticmethod
    def extract_first_number(value):
        match = re.search(r"(\d+)", value)
        return int(match.group(1)) if match else None

    @classmethod
    def parse_experience(cls, value):
        """
        경력 문자열을 숫자로 변환
        """
        value = cls.sanitize_string(value)
        if not value:
            return None
        if any(kw in value for kw in ['신입', '경력무관']):
            return 0
        return cls.extract_first_number(value)

    @staticmethod
    def parse_region(value):
        """
        지역 문자열을 (region_name, subregion_name) 형태로 반환.
        - '외'는 제거
        - 형태 정보 포함 시 None 반환
        - 서브지역 없을 경우 subregion_name은 None
        """

        if not value or not isinstance(value, str):
            return None

        employment_keywords = ['정규직', '계약직', '인턴', '파견직', '프리랜서']
        if any(kw in value for kw in employment_keywords):
            return None

        # 전처리
        value = value.replace("외", "").strip()
        tokens = value.split(maxsplit=1)

        if len(tokens) == 1:
            return (tokens[0], None)
        elif len(tokens) == 2:
            return (tokens[0], tokens[1])
        else:
            return None

    @classmethod
    def parse_education(cls, value):
        """
        학력 문자열을 숫자 등급으로 변환
        """
        value = cls.sanitize_string(value)
        level_map = {
            '학력무관': 0,
            '고졸↑': 1,
            '초대졸↑': 2,
            '대졸↑': 3,
            '석사↑': 4,
            '박사↑': 5
        }
        return level_map.get(value, None)

    @staticmethod
    def parse_form(value):
        """
        형태 열을 정규화하여 숫자 등급으로 변환
        """
        if not value or not isinstance(value, str):
            return None

        value = value.strip()

        if re.search(r'\d', value):
            return None  # 숫자형 연봉 값 잘못 들어간 경우

        form_map = {
            '정규직': '정규직',
            '계약직': '계약직',
            '인턴': '인턴',
            '파견직': '파견직',
            '프리랜서': '프리랜서',
            '위촉직': '위촉직',
            '개인사업자': '위촉직',
            '도급': '도급',
            '연수생': '연수생',
            '교육생': '연수생',
            '병역특례': '병역특례',
            '아르바이트': '아르바이트',
        }

        for keyword, normalized in form_map.items():
            if keyword in value:
                level_map = {
                    '정규직': 1,
                    '계약직': 2,
                    '인턴': 3,
                    '파견직': 4,
                    '프리랜서': 5,
                    '위촉직': 6,
                    '도급': 7,
                    '연수생': 8,
                    '병역특례': 9,
                    '아르바이트': 10
                }
                return level_map.get(normalized, None)

        return None
    
    @classmethod
    def parse_salary(cls, value):
        """
        연봉 문자열을 숫자로 변환 (월급, 연봉)
        """
        value = cls.sanitize_string(value)
        if not value:
            return None

        if "일" in value:
            return None

        if "월" in value:
            num = cls.extract_first_number(value)
            return num * 12 if num else None

        if "만원" in value:
            return cls.extract_first_number(value)

        return None
    
    @staticmethod
    def parse_deadline(value, today=None):
        """
        '마감일' 문자열을 datetime.date 객체로 변환
        - '~06/10(화)' → datetime.date(2025, 6, 10)
        - '오늘마감' → 오늘 날짜
        - '내일마감' → 오늘 + 1
        - '모레마감' → 오늘 + 2
        - '상시채용' 등 → datetime.date(9999, 12, 31)
        """
        if not value or not isinstance(value, str):
            return datetime(9999, 12, 31).date()

        value = value.strip()

        # 기준 날짜를 외부에서 지정하지 않으면 오늘로 설정
        if today is None:
            today = datetime.today().date()

        # 상대적 마감일 처리
        if value == '오늘마감':
            return today
        elif value == '내일마감':
            return today + timedelta(days=1)
        elif value == '모레마감':
            return today + timedelta(days=2)
        elif '상시' in value:
            return datetime(9999, 12, 31).date()

        # 정규 표현식으로 날짜 추출: ~MM/DD(요일)
        match = re.match(r"~(\d{2})/(\d{2})", value)
        if match:
            month, day = map(int, match.groups())

            # 현재 연도 기준으로 날짜 구성
            year = today.year
            deadline = datetime(year, month, day).date()

            # 마감일이 이미 지났다면 내년으로 보정
            if deadline < today:
                deadline = datetime(year + 1, month, day).date()

            return deadline

        # 그 외에는 상시 채용으로 간주
        return datetime(9999, 12, 31).date()
    
    @staticmethod
    def parse_explanation(value):
        """
        쉼표로 나뉜 키워드 문자열을 리스트로 파싱
        - 각 태그의 내부 공백까지 제거 (ex: "기술 지원" → "기술지원")
        - 좌우 공백 제거
        - 빈 항목 제거
        - 문자열이 아니거나 내용이 없으면 None 반환
        """
        if not value or not isinstance(value, str):
            return None

        # 쉼표 기준 분리 후 각 항목 내 모든 공백 제거
        tags = [tag.replace(" ", "").strip() for tag in value.split(',') if tag.strip()]
        
        return tags if tags else None
    
    # 숫자 -> 문자열
    @staticmethod
    def stringify_deadline(deadline: date) -> str:
        """
        datetime.date 객체를 마감일 문자열로 변환
        - 오늘, 내일, 모레: 상대 표현
        - 9999-12-31: '상시채용'
        - 그 외: ~MM/DD 형식
        """
        if not isinstance(deadline, date):
            return "상시채용"

        today = date.today()
        delta = (deadline - today).days

        if deadline >= date(9999, 1, 1):
            return "상시채용"
        elif delta == 0:
            return "오늘마감"
        elif delta == 1:
            return "내일마감"
        elif delta == 2:
            return "모레마감"
        else:
            return f"~{deadline.month:02}/{deadline.day:02}"
    
    @staticmethod
    def stringify_salary(value: int | None) -> str:
        """
        숫자형 연봉을 문자열로 변환
        - None → '협의'
        - 3000 → '3000만원/년'
        """
        if value is None:
            return "협의"
        return f"{value}만원/년"

    @staticmethod
    def stringify_experience(value: int) -> str:
        """
        숫자형 경력을 문자열로 변환
        0 → '신입'
        """
        if value is None:
            return "경력무관"
        if value == 0:
            return "신입"
        return f"{value}년 이상"

    @staticmethod
    def stringify_education(value: int) -> str:
        """
        숫자형 학력을 문자열로 변환
        """
        level_map = {
            0: '학력무관',
            1: '고졸↑',
            2: '초대졸↑',
            3: '대졸↑',
            4: '석사↑',
            5: '박사↑'
        }
        return level_map.get(value, "기타")

    @staticmethod
    def stringify_form(value: int) -> str:
        """
        숫자형 고용형태를 문자열로 변환
        """
        form_map = {
            1: '정규직',
            2: '계약직',
            3: '인턴',
            4: '파견직',
            5: '프리랜서',
            6: '위촉직',
            7: '도급',
            8: '연수생',
            9: '병역특례',
            10: '아르바이트'
        }
        if value is None:
            return "기타"
        return form_map.get(value, "기타")