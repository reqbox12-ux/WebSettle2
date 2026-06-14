import pandas as pd
import json
from pathlib import Path

MAPPING_PATH = Path(__file__).parent.parent / "mapping" / "branch_mapping.json"


def _load_branch_mapping() -> dict:
    with open(MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)["card_merchant_to_branch"]


def _to_int(val) -> int:
    try:
        return int(float(str(val).replace(",", "").replace(" ", "")))
    except Exception:
        return 0


# ══════════════════════════════════════════════════════════════════════
#  카드 파서 (기존 유지)
# ══════════════════════════════════════════════════════════════════════

def _find_col(header_list: list, keywords: list, fallback: int) -> int:
    for kw in keywords:
        for i, h in enumerate(header_list):
            if kw in str(h).strip():
                return i
    return fallback


def _find_header_row(filepath: str, search_kws=('가맹점', '합계금액', '수수료')) -> int:
    probe = pd.read_excel(filepath, header=None, dtype=str, nrows=10)
    for i, row in probe.iterrows():
        vals = [str(v).strip() for v in row if pd.notna(v)]
        if sum(1 for v in vals if any(k in v for k in search_kws)) >= 2:
            return i
    return 0


def parse_card_aggregate(filepath: str, year: int, month: int) -> pd.DataFrame:
    merchant_map = _load_branch_mapping()
    header_row = _find_header_row(filepath)
    df = pd.read_excel(filepath, header=header_row, dtype=str)
    n = len(df.columns)
    hdrs = [str(c).strip() for c in df.columns]
    c_merchant = _find_col(hdrs, ['가맹점명', '가맹점 명', '가맹점'], min(18, n-1))
    c_total    = _find_col(hdrs, ['합계금액', '총금액', '합  계금액'], min(14, n-1))
    c_fee      = _find_col(hdrs, ['수수료'], min(15, n-1))
    c_date     = _find_col(hdrs, ['청구일', '입금일', '매입일'], min(4, n-1))
    c_company  = _find_col(hdrs, ['매입사', '카드사'], min(1, n-1))
    df.columns = range(n)
    rows = []
    for _, row in df.iterrows():
        merchant     = str(row.iloc[c_merchant]).strip()
        total_amount = _to_int(row.iloc[c_total])
        fee          = _to_int(row.iloc[c_fee])
        if total_amount == 0 or merchant in ('nan', '', 'None'):
            continue
        vat           = total_amount // 11
        supply_amount = total_amount - vat
        net_amount    = supply_amount - fee
        branch        = merchant_map.get(merchant, "미매핑")
        rows.append({
            "branch":        branch,
            "raw_merchant":  merchant,
            "card_company":  str(row.iloc[c_company]).strip() if pd.notna(row.iloc[c_company]) else "",
            "total_amount":  total_amount,
            "vat":           vat,
            "supply_amount": supply_amount,
            "fee":           fee,
            "net_amount":    net_amount,
            "sale_date":     str(row.iloc[c_date]).strip() if pd.notna(row.iloc[c_date]) else "",
        })
    return pd.DataFrame(rows)


def parse_credit_card(filepath: str, year: int, month: int) -> pd.DataFrame:
    merchant_map = _load_branch_mapping()
    header_row = _find_header_row(filepath, search_kws=('가맹점', '거래금액', '공급가액', '부가세'))
    df = pd.read_excel(filepath, header=header_row, dtype=str)
    n = len(df.columns)
    hdrs = [str(c).strip() for c in df.columns]
    c_merchant = _find_col(hdrs, ['가맹점명', '가맹점'], min(0, n-1))
    c_total    = _find_col(hdrs, ['거래금액', '총금액'], min(6, n-1))
    c_supply   = _find_col(hdrs, ['공급가액', '공급금액'], min(7, n-1))
    c_vat      = _find_col(hdrs, ['부가세', '부가가치세'], min(8, n-1))
    c_fee      = _find_col(hdrs, ['수수료'], min(11, n-1))
    c_date     = _find_col(hdrs, ['거래일자', '거래일', '매입일'], min(1, n-1))
    df.columns = range(n)
    rows = []
    for _, row in df.iterrows():
        merchant      = str(row.iloc[c_merchant]).strip()
        total_amount  = _to_int(row.iloc[c_total])
        supply_amount = _to_int(row.iloc[c_supply])
        vat           = _to_int(row.iloc[c_vat])
        fee           = _to_int(row.iloc[c_fee])
        net_amount    = supply_amount - fee
        branch        = merchant_map.get(merchant, "미매핑")
        if total_amount == 0 or merchant in ('nan', '', 'None'):
            continue
        rows.append({
            "branch":        branch,
            "raw_merchant":  merchant,
            "card_company":  "",
            "total_amount":  total_amount,
            "vat":           vat,
            "supply_amount": supply_amount,
            "fee":           fee,
            "net_amount":    net_amount,
            "sale_date":     str(row.iloc[c_date]).strip() if pd.notna(row.iloc[c_date]) else "",
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
#  통장 자동 파서 (하나 / 신한 자동 감지)
# ══════════════════════════════════════════════════════════════════════

_REVENUE_CATS = {
    "기타매출(현금)", "PT매출(현금)", "GX매출(현금)",
    "골프매출(현금)", "키즈매출(현금)", "도급비", "시설상환비", "카페매출",
    "기타매출(카드)",
}


def is_revenue_cat(cat: str) -> bool:
    return cat in _REVENUE_CATS


# 내부 alias (기존 코드 호환)
_is_revenue_cat = is_revenue_cat


def _normalize_category(cat) -> str:
    if pd.isna(cat):
        return ""
    cat = str(cat).strip()
    mapping = {
        "GX매출":        "기타매출(현금)",
        "PT매출":        "기타매출(현금)",
        "기타매출":      "기타매출(현금)",
        "카드매출":      "기타매출(카드)",
        "골프매출":      "골프매출(현금)",
        "키즈매출":      "키즈매출(현금)",
        "소득세·지방세": "소득세·지방세 합계",
        "소득세지방세":  "소득세·지방세 합계",
    }
    return mapping.get(cat, cat)


def _clean(val) -> str:
    """NaN / None → 빈 문자열"""
    s = str(val).strip()
    return "" if s in ("nan", "None", "NaN") else s


def _get_col(df: pd.DataFrame, keywords: list):
    """컬럼 이름 부분 일치로 찾기. 없으면 None."""
    for kw in keywords:
        for col in df.columns:
            if kw in str(col).strip():
                return col
    return None


def _find_bank_header_row(raw: pd.DataFrame) -> int:
    """제목행을 건너뛰고 실제 헤더 행 번호 반환.
    'No' 와 ('거래일시' or '거래일자') 가 동시에 있는 행을 찾는다."""
    for i, row in raw.iterrows():
        vals = {str(v).strip() for v in row if pd.notna(v) and str(v).strip() not in ("nan", "")}
        if "No" in vals and (vals & {"거래일시", "거래일자"}):
            return i
    return 0


def _detect_bank(header_vals: list) -> str:
    """헤더 리스트로 은행 종류 판별. 'hana' | 'shinhan' | '' """
    hv = [v.strip() for v in header_vals]
    # 신한: '전체선택' 컬럼이 있음
    if any("전체선택" in v for v in hv):
        return "shinhan"
    # 하나: '거래일시' + '의뢰인' or '수취인' 있음
    has_date = any("거래일시" in v or "거래일자" in v for v in hv)
    has_party = any("의뢰인" in v or "수취인" in v for v in hv)
    if has_date and has_party:
        return "hana"
    return ""


def _parse_hana_sheet(df: pd.DataFrame, year: int, month: int):
    """하나통장 시트 1개 파싱 (컬럼명 기반, 지점/계정과목 없어도 OK)"""
    col_date    = _get_col(df, ["거래일시", "거래일자"])
    col_desc    = _get_col(df, ["적요"])
    col_counter = _get_col(df, ["의뢰인", "수취인"])
    col_dep     = _get_col(df, ["입금"])
    col_with    = _get_col(df, ["출금"])
    col_bal     = _get_col(df, ["거래후잔액", "잔액"])
    col_branch  = _get_col(df, ["지점"])
    col_content = _get_col(df, ["내용"])
    col_cat     = _get_col(df, ["계정과목"])

    if not col_date or not col_desc:
        return None

    rows = []
    for _, row in df.iterrows():
        tx_date = pd.to_datetime(_clean(row.get(col_date, "")), errors="coerce")
        if pd.isna(tx_date):
            continue
        if tx_date.year != year or tx_date.month != month:
            continue

        deposit    = _to_int(row[col_dep])  if col_dep  else 0
        withdrawal = _to_int(row[col_with]) if col_with else 0
        balance    = _to_int(row[col_bal])  if col_bal  else 0
        branch     = _clean(row[col_branch])  if col_branch  else ""
        content    = _clean(row[col_content]) if col_content else ""
        category   = _normalize_category(row[col_cat] if col_cat else "")

        rows.append({
            "tx_date":     tx_date.strftime("%Y-%m-%d %H:%M:%S"),
            "description": _clean(row[col_desc]),
            "counterpart": _clean(row[col_counter]) if col_counter else "",
            "deposit":     deposit,
            "withdrawal":  withdrawal,
            "balance":     balance,
            "branch":      branch,
            "content":     content,
            "category":    category,
            "vat":         0,
            "is_excluded": 0,
            "needs_review": 0,
        })

    return pd.DataFrame(rows) if rows else None


def _parse_shinhan_sheet(df: pd.DataFrame, year: int, month: int):
    """신한통장 시트 파싱 (컬럼명 기반, 지점/계정과목 없어도 OK)
    신한 헤더: No | 전체선택 | 거래일시 | 적요 | 입금액 | 출금액 | 내용 | 잔액 | 거래점명 | 입금인코드 | 메모 ...
    수기 컬럼(있는 경우): 지점 | 내용 | 계정과목
    """
    col_date    = _get_col(df, ["거래일시", "거래일자"])
    col_desc    = _get_col(df, ["적요"])
    col_dep     = _get_col(df, ["입금액", "입금"])
    col_with    = _get_col(df, ["출금액", "출금"])
    col_bal     = _get_col(df, ["잔액"])
    # 신한의 은행 제공 '내용' 컬럼 → description 보강용
    col_content_bank = _get_col(df, ["내용"])
    col_counter = _get_col(df, ["입금인코드"])
    # 수기 입력 컬럼 (없을 수 있음)
    col_branch  = _get_col(df, ["지점"])
    col_cat     = _get_col(df, ["계정과목"])
    # 수기 '내용'은 은행 '내용' 뒤에 있으므로 .1 접미사가 붙을 수 있음
    col_content_manual = _get_col(df, ["내용.1"])

    if not col_date or not col_desc:
        return None

    rows = []
    for _, row in df.iterrows():
        tx_date = pd.to_datetime(_clean(row.get(col_date, "")), errors="coerce")
        if pd.isna(tx_date):
            continue
        if tx_date.year != year or tx_date.month != month:
            continue

        deposit    = _to_int(row[col_dep])  if col_dep  else 0
        withdrawal = _to_int(row[col_with]) if col_with else 0
        balance    = _to_int(row[col_bal])  if col_bal  else 0

        # description: 은행 '내용' 우선, 없으면 '적요'
        desc_bank = _clean(row[col_content_bank]) if col_content_bank else ""
        desc_txn  = _clean(row[col_desc])
        description = desc_bank if desc_bank else desc_txn

        branch   = _clean(row[col_branch])        if col_branch        else ""
        content  = _clean(row[col_content_manual]) if col_content_manual else ""
        category = _normalize_category(row[col_cat] if col_cat else "")
        counterpart = _clean(row[col_counter]) if col_counter else ""

        rows.append({
            "tx_date":     tx_date.strftime("%Y-%m-%d %H:%M:%S"),
            "description": description,
            "counterpart": counterpart,
            "deposit":     deposit,
            "withdrawal":  withdrawal,
            "balance":     balance,
            "branch":      branch,
            "content":     content,
            "category":    category,
            "vat":         0,
            "is_excluded": 0,
            "needs_review": 0,
        })

    return pd.DataFrame(rows) if rows else None


def parse_bank_auto(xl: pd.ExcelFile, year: int, month: int) -> dict:
    """
    모든 시트를 자동 스캔하여 하나/신한 통장을 판별하고 파싱한다.
    - 하나통장 시트가 여러 개여도 모두 합쳐서 반환
    - 지점/계정과목 컬럼이 없어도 OK (자동분류에서 처리)

    Returns:
        {'hana': DataFrame, 'shinhan': DataFrame}
        값이 없는 경우 빈 DataFrame
    """
    results = {"hana": [], "shinhan": []}

    for sheet_name in xl.sheet_names:
        try:
            raw = xl.parse(sheet_name, header=None, dtype=str)
            if raw.empty:
                continue

            header_row_idx = _find_bank_header_row(raw)
            header_vals = [str(v) for v in raw.iloc[header_row_idx] if pd.notna(v)]
            bank_type = _detect_bank(header_vals)
            if not bank_type:
                continue

            # 헤더 행부터 다시 로드
            df = xl.parse(sheet_name, header=header_row_idx, dtype=str)

            if bank_type == "hana":
                parsed = _parse_hana_sheet(df, year, month)
            else:
                parsed = _parse_shinhan_sheet(df, year, month)

            if parsed is not None and len(parsed) > 0:
                results[bank_type].append(parsed)

        except Exception:
            continue

    final = {}
    for bank in ["hana", "shinhan"]:
        if results[bank]:
            final[bank] = pd.concat(results[bank], ignore_index=True)
        else:
            final[bank] = pd.DataFrame()

    return final


def recalc_vat(df: pd.DataFrame) -> pd.DataFrame:
    """classify_transactions() 실행 후 category 기준으로 VAT 재계산"""
    df = df.copy()
    df["vat"] = df.apply(
        lambda r: int(r["deposit"]) // 11
        if is_revenue_cat(str(r.get("category", ""))) and int(r.get("deposit", 0)) > 0
        else 0,
        axis=1,
    )
    df["is_excluded"] = (df["category"] == "제외").astype(int)
    return df


# ══════════════════════════════════════════════════════════════════════
#  하위 호환 래퍼 (기존 코드에서 parse_hana / parse_shinhan 호출 시)
# ══════════════════════════════════════════════════════════════════════

def parse_hana(xl: pd.ExcelFile, year: int, month: int) -> pd.DataFrame:
    result = parse_bank_auto(xl, year, month)
    df = result.get("hana", pd.DataFrame())
    if df.empty:
        raise ValueError("하나통장 시트를 찾을 수 없습니다")
    return df


def parse_shinhan(xl: pd.ExcelFile, year: int, month: int) -> pd.DataFrame:
    result = parse_bank_auto(xl, year, month)
    df = result.get("shinhan", pd.DataFrame())
    if df.empty:
        raise ValueError("신한통장 시트를 찾을 수 없습니다")
    return df


# ══════════════════════════════════════════════════════════════════════
#  인건비 파서 (기존 유지)
# ══════════════════════════════════════════════════════════════════════

def parse_payroll_freelance(xl: pd.ExcelFile, year: int, month: int) -> pd.DataFrame:
    df_raw = xl.parse("사업소득자", header=None)
    col = 1 + (month - 1) * 5
    rows = []
    for i in range(2, len(df_raw)):
        branch = df_raw.iloc[i, 0]
        if pd.isna(branch):
            continue
        gross   = _to_int(df_raw.iloc[i, col])
        inc_tax = _to_int(df_raw.iloc[i, col + 1])
        loc_tax = _to_int(df_raw.iloc[i, col + 2])
        net     = _to_int(df_raw.iloc[i, col + 4])
        rows.append({
            "branch": str(branch), "gross_pay": gross, "net_pay": net,
            "insurance": 0, "income_tax": inc_tax, "local_tax": loc_tax, "headcount": 0,
        })
    return pd.DataFrame(rows)


def parse_payroll_insured(xl: pd.ExcelFile, year: int, month: int) -> pd.DataFrame:
    df_raw = xl.parse("지점별집계", header=None)
    col = 1 + (month - 1) * 4
    rows = []
    for i in range(2, len(df_raw)):
        branch = df_raw.iloc[i, 0]
        if pd.isna(branch):
            continue
        headcount = _to_int(df_raw.iloc[i, col])
        net       = _to_int(df_raw.iloc[i, col + 1])
        insurance = _to_int(df_raw.iloc[i, col + 2])
        inc_tax   = _to_int(df_raw.iloc[i, col + 3])
        rows.append({
            "branch": str(branch), "gross_pay": net + insurance + inc_tax,
            "net_pay": net, "insurance": insurance, "income_tax": inc_tax,
            "local_tax": 0, "headcount": headcount,
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════
#  4대보험 본사/직원 부담 파서
# ══════════════════════════════════════════════════════════════════════

_INS_COLS = {
    "지점":       "branch",
    "국민연금_본사": "pension_co",
    "국민연금_직원": "pension_emp",
    "건강보험_합산": "health_total",
    "고용보험_본사": "employ_co",
    "고용보험_직원": "employ_emp",
    "산재보험":    "accident",
}

def parse_insurance_excel(xl: pd.ExcelFile) -> pd.DataFrame:
    """4대보험 지점별 입력 양식 파싱.

    시트명: '4대보험' 또는 첫 번째 시트.
    헤더 행: 지점 | 국민연금_본사 | 국민연금_직원 | 건강보험_합산 | 고용보험_본사 | 고용보험_직원 | 산재보험

    건강보험은 합산만 입력하면 본사/직원 각 50% 로 자동 분할.
    """
    sheet = "4대보험" if "4대보험" in xl.sheet_names else xl.sheet_names[0]

    # 헤더 행 자동 감지: 첫 번째 열에 '지점'이 있는 행을 헤더로 사용
    df_probe = xl.parse(sheet, header=None)
    header_row = 0
    for idx in range(min(5, len(df_probe))):
        cell = str(df_probe.iloc[idx, 0]).strip()
        if cell in ("지점", "branch"):
            header_row = idx
            break

    df_raw = xl.parse(sheet, header=header_row)

    # 컬럼명 한글 → 내부 영문 매핑
    rename = {k: v for k, v in _INS_COLS.items() if k in df_raw.columns}
    df = df_raw.rename(columns=rename)

    required = ["branch", "pension_co", "pension_emp", "health_total",
                "employ_co", "employ_emp", "accident"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"4대보험 양식에 필수 컬럼 없음: {missing}")

    # 숫자 정제 (설명 텍스트 행 제거 포함)
    for col in required[1:]:
        df[col] = pd.to_numeric(
            df[col].astype(str).str.replace(",", "").str.strip(),
            errors="coerce"
        ).fillna(0).astype(int)

    # 빈 지점 행 + 합계 행 제거
    df = df.dropna(subset=["branch"])
    df["branch"] = df["branch"].astype(str).str.strip()
    df = df[df["branch"].str.len() > 0]
    df = df[~df["branch"].isin(["지점명", "합  계", "합계", "계"])]

    return df[required].reset_index(drop=True)
