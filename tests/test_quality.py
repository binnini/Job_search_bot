"""
데이터 품질 리포트 실행 스크립트.
결과는 콘솔 출력 + test_quality_results.txt 저장.
"""
from dotenv import load_dotenv
load_dotenv(override=True)

import os
from db.quality import generate_quality_report, clean_existing_data

if __name__ == "__main__":
    print("기존 데이터 정제 중...")
    cleaned = clean_existing_data()
    print(f"  연봉 이상값 정제: {cleaned['salary_cleaned']}건")
    print(f"  경력 이상값 정제: {cleaned['experience_cleaned']}건\n")

    report = generate_quality_report()
    print(report)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "test_quality_results.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\n✅ 결과 저장 완료: {output_path}")
