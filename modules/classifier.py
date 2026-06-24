import re
import sqlite3
import pandas as pd
from modules.db import get_conn


# ── 카드 결제 코드 패턴 (제외 처리) ────────────────────────────
_CARD_CODE_RE = re.compile(
    r"^("
    r"KB\d{6,}"         # KB90517769
    r"|NH\d{6,}"        # NH농협
    r"|BC\d{6,}"        # BC카드
    r"|\d{6,}BC"        # 710987629BC
    r"|SHC\d{5,}"       # 신한카드
    r"|하나\d{5,}"      # 하나카드
    r"|국민\d{5,}"      # 국민카드
    r"|우리\d{5,}"      # 우리카드
    r"|삼성\d{5,}"      # 삼성카드
    r"|롯데\d{5,}"      # 롯데카드
    r"|현대\d{5,}"      # 현대카드
    r"|토스_\d{8}"      # 토스_20260501
    r"|\d{9,}"          # 순수 숫자 10자리 이상 (VAN코드)
    r")",
    re.IGNORECASE,
)

# ── 통장이동 패턴 (제외 처리) ────────────────────────────────
_TRANSFER_KEYWORDS = [
    "주식회사 라온스포츠",
    "(주)라온스포츠",
    "㈜라온스포츠",
    "자금대체",
    "타행이체수수료",
]

# ── 지점 키워드 맵 (순서 중요: 더 구체적인 것 먼저) ──────────────
_BRANCH_KEYWORDS: list[tuple[str, str]] = [
    # 위례 — 두 지점 구분
    ("위례힐스",      "위례힐스테이트"),
    ("힐스테이트위례", "위례힐스테이트"),
    ("위례그린",      "위례그린푸르지오"),
    ("그린푸르지오",   "위례그린푸르지오"),
    # 배곧 — 두 지점 구분
    ("배곧베르",      "배곧베르디움"),
    ("베르디움",      "배곧베르디움"),
    ("배곧C1",       "배곧C1"),
    ("배곧c1",       "배곧C1"),
    ("배곧씨원",      "배곧C1"),
    # 송파 — 두 지점 구분
    ("송파하비오",     "송파하비오"),
    ("하비오",        "송파하비오"),
    ("송파와이즈",     "송파와이즈파크"),
    ("와이즈파크",     "송파와이즈파크"),
    # 나머지 단일 지점
    ("다산",          "다산캠퍼스몰"),
    ("캠퍼스몰",       "다산캠퍼스몰"),
    ("구월",          "구월아시아드"),
    ("아시아드",       "구월아시아드"),
    ("청라",          "청라국제도시"),
    ("루원",          "루원시티"),
    ("검단",          "검단신도시"),
    ("당진",          "당진합덕"),
    ("합덕",          "당진합덕"),
    ("의왕",          "의왕내손"),
    ("내손",          "의왕내손"),
    ("평택",          "평택비전"),
    ("비전",          "평택비전"),
    ("고색",          "수원고색"),
    ("수원고색",       "수원고색"),
    ("영통",          "수원영통"),
    ("수원영통",       "수원영통"),
    ("화성",          "화성반월"),
    ("반월",          "화성반월"),
    ("오산",          "오산세교"),
    ("세교",          "오산세교"),
    ("김포",          "김포한강"),
    ("한강",          "김포한강"),
    ("파주",          "파주운정"),
    ("운정",          "파주운정"),
    ("양주",          "양주옥정"),
    ("옥정",          "양주옥정"),
]

# ── 계정과목 키워드 맵 ──────────────────────────────────────
_CATEGORY_KEYWORDS: list[tuple[str, str]] = [
    # 매출 관련
    ("PT",        "PT매출(현금)"),
    ("GX",        "GX매출(현금)"),
    ("골프",       "골프매출(현금)"),
    ("키즈",       "키즈매출(현금)"),
    # 지출 관련
    ("관리비",     "임차료"),
    ("임차료",     "임차료"),
    ("임대료",     "임차료"),
    ("렌탈",       "렌탈비"),
    ("렌탈비",     "렌탈비"),
    ("수리",       "AS비용"),
    ("AS",        "AS비용"),
    ("a/s",       "AS비용"),
    ("점검",       "AS비용"),
    ("유지보수",    "AS비용"),
    ("소모품",     "비품구매"),
    ("비품",       "비품구매"),
    ("구입",       "비품구매"),
    ("식대",       "복리후생비"),
    ("식비",       "복리후생비"),
    ("복리",       "복리후생비"),
    ("4대보험",    "4대보험료"),
    ("고용보험",    "4대보험료"),
    ("국민연금",    "4대보험료"),
    ("건강보험",    "4대보험료"),
    ("산재보험",    "4대보험료"),
    ("보험",       "기타보험료"),
    ("차량",       "차량유지비"),
    ("주유",       "차량유지비"),
    ("통신",       "운영경비"),
    ("전기",       "운영경비"),
    ("수도",       "운영경비"),
    ("가스",       "운영경비"),
    ("이자",       "이자비용"),
    ("대출이자",    "이자비용"),
    ("외주",       "외주용역비"),
    ("용역",       "외주용역비"),
    ("세금",       "기타세금"),
    ("부가세",     "부가세"),
    ("환불",       "환불"),
    ("법인카드",    "법인카드"),
]


def _get_rules(bank: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT keyword, branch, category, hit_count FROM keyword_rules WHERE bank=? ORDER BY hit_count DESC",
        (bank,)
    ).fetchall()
    conn.close()
    return [{"keyword": r[0], "branch": r[1], "category": r[2], "hit_count": r[3]} for r in rows]


def _is_card_code(text: str) -> bool:
    """카드 결제 코드 여부 (제외 대상)"""
    return bool(_CARD_CODE_RE.match(text.strip()))


def _is_transfer(description: str, counterpart: str, deposit: int) -> bool:
    """통장이동 여부 (제외 대상)"""
    combined = f"{description} {counterpart}"
    for kw in _TRANSFER_KEYWORDS:
        if kw in combined:
            return True
    return False


def _smart_classify(description: str, counterpart: str) -> tuple[str, str]:
    """
    description(적요/내용)과 counterpart(의뢰인/수취인)에서
    지점과 계정과목을 추출. 실패 시 ("", "") 반환.
    """
    combined = f"{description} {counterpart}"

    branch = ""
    for kw, br in _BRANCH_KEYWORDS:
        if kw in combined:
            branch = br
            break

    category = ""
    for kw, cat in _CATEGORY_KEYWORDS:
        if kw.lower() in combined.lower():
            category = cat
            break

    return branch, category


def classify_transactions(df: pd.DataFrame, bank: str) -> pd.DataFrame:
    """
    1) 이미 branch/category가 채워진 행 → 스킵
    2) 카드코드 / 통장이동 → 제외(is_excluded=1)
    3) 키워드 규칙(DB) 매칭 → classification_source='rule'
    4) 스마트 텍스트 추출 → classification_source='smart'
    5) 미분류 → needs_review=1, classification_source=''
    """
    rules = _get_rules(bank)

    # classification_source 컬럼 초기화
    if "classification_source" not in df.columns:
        df["classification_source"] = ""

    for idx, row in df.iterrows():
        # 이미 분류됨
        branch_filled = bool(str(row.get("branch", "")).strip())
        cat_filled    = bool(str(row.get("category", "")).strip())
        if branch_filled and cat_filled:
            continue

        description = str(row.get("description", ""))
        counterpart = str(row.get("counterpart", ""))
        deposit     = int(row.get("deposit", 0) or 0)

        # ── 1. 카드 결제 코드 제외 ─────────────────────────
        if _is_card_code(description):
            df.at[idx, "is_excluded"] = 1
            df.at[idx, "needs_review"] = 0
            df.at[idx, "category"] = "제외"
            df.at[idx, "classification_source"] = "card_code"
            continue

        # ── 2. 통장이동 제외 ──────────────────────────────
        if _is_transfer(description, counterpart, deposit):
            df.at[idx, "is_excluded"] = 1
            df.at[idx, "needs_review"] = 0
            df.at[idx, "category"] = "제외"
            df.at[idx, "classification_source"] = "transfer"
            continue

        # ── 3. DB 키워드 규칙 매칭 ─────────────────────────
        matched = False
        for rule in rules:
            if rule["keyword"] in description:
                df.at[idx, "branch"]   = rule["branch"]
                df.at[idx, "category"] = rule["category"]
                df.at[idx, "is_excluded"] = 1 if rule["category"] == "제외" else 0
                df.at[idx, "needs_review"] = 0
                df.at[idx, "classification_source"] = "rule"
                matched = True
                break

        if matched:
            continue

        # ── 4. 스마트 텍스트 추출 ────────────────────────
        smart_branch, smart_cat = _smart_classify(description, counterpart)
        if smart_branch or smart_cat:
            if smart_branch:
                df.at[idx, "branch"] = smart_branch
            if smart_cat:
                df.at[idx, "category"] = smart_cat
            df.at[idx, "needs_review"] = 1 if not (smart_branch and smart_cat) else 0
            df.at[idx, "classification_source"] = "smart"
            continue

        # ── 5. 미분류 ────────────────────────────────────
        df.at[idx, "needs_review"] = 1
        df.at[idx, "classification_source"] = ""

    return df


def add_rule(bank: str, keyword: str, branch: str, category: str):
    conn = get_conn()
    conn.execute("""
        INSERT INTO keyword_rules (bank, keyword, branch, category, hit_count)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(bank, keyword, branch, category) DO UPDATE SET hit_count = hit_count + 1
    """, (bank, keyword, branch, category))
    conn.commit()
    conn.close()


def get_all_rules(bank: str = None) -> pd.DataFrame:
    conn = get_conn()
    if bank:
        df = pd.read_sql("SELECT * FROM keyword_rules WHERE bank=? ORDER BY hit_count DESC", conn, params=(bank,))
    else:
        df = pd.read_sql("SELECT * FROM keyword_rules ORDER BY bank, hit_count DESC", conn)
    conn.close()
    return df
