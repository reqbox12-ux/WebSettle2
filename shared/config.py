"""
공통 설정 — 지점 목록, 카테고리, 상수
"""
import json
from pathlib import Path

MAPPING_PATH = Path(__file__).parent.parent / "mapping" / "branch_mapping.json"
with open(MAPPING_PATH, encoding="utf-8") as _f:
    _mapping = json.load(_f)

BRANCH_LIST: list[str] = _mapping["branch_list"]

REVENUE_CATEGORIES = {
    "카드": ["PT매출(카드)", "GX매출(카드)", "골프매출(카드)", "키즈매출(카드)", "기타매출(카드)"],
    "현금": ["PT매출(현금)", "GX매출(현금)", "골프매출(현금)", "키즈매출(현금)", "기타매출(현금)"],
    "기타": ["도급비", "시설상환비", "카페매출"],
}

EXPENSE_CATEGORIES: list[str] = [
    "급여", "4대보험료", "소득세·지방세 합계", "프리랜서", "퇴직금",
    "기타세금", "부가세", "카드수수료", "법인카드", "환불",
    "렌탈비", "관리비", "임차료", "비품구매", "기타지출",
    "운영경비", "외주용역비", "감가상각비", "기타보험료",
    "복리후생비", "이자비용", "AS비용", "차량유지비",
]

CARD_CATS = ["PT매출(카드)", "GX매출(카드)", "골프매출(카드)", "키즈매출(카드)", "기타매출(카드)"]
CASH_CATS = [
    "PT매출(현금)", "GX매출(현금)", "골프매출(현금)", "키즈매출(현금)", "기타매출(현금)",
    "도급비", "시설상환비", "카페매출",
]

ALL_CATEGORIES: list[str] = (
    ["기타매출(현금)", "기타매출(카드)", "PT매출(현금)", "PT매출(카드)",
     "GX매출(현금)", "GX매출(카드)", "골프매출(현금)", "골프매출(카드)",
     "키즈매출(현금)", "키즈매출(카드)", "도급비", "시설상환비", "카페매출"]
    + EXPENSE_CATEGORIES + ["제외"]
)
