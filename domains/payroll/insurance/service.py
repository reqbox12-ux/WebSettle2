"""
domains/payroll/insurance/service.py
공단 4대보험 고지내역 파싱 + 실납부액 급여 반영
"""
import pandas as pd


# ── 국민연금 파싱 ─────────────────────────────────────────────
def parse_pension(file) -> tuple[list[dict], list[str]]:
    """
    국민연금 고지내역 엑셀 파싱.
    구조: 행0=타이틀(2차결정내역통보서), 행1=실제 컬럼명, 행2~=데이터
    → header=None으로 읽고, 행1을 컬럼명으로 사용
    """
    records = []
    errors  = []
    try:
        df_raw = pd.read_excel(file, header=None)
        # 컬럼명이 있는 행 탐색 (행0=타이틀, 행1=빈행, 행2=실제 컬럼명)
        header_idx = next(
            (i for i, row in df_raw.iterrows() if "성명" in [str(v).strip() for v in row]),
            2,
        )
        cols = [str(c).strip() for c in df_raw.iloc[header_idx]]
        df   = df_raw.iloc[header_idx + 1:].copy()
        df.columns = cols
        df   = df.reset_index(drop=True)

        # 성명 컬럼 확인
        if "성명" not in df.columns:
            errors.append("국민연금: '성명' 컬럼을 찾지 못했습니다.")
            return records, errors

        # 필요 컬럼 탐색 (컬럼명 내 부분 일치)
        col_base = next((c for c in df.columns if "기준소득월액" in c and "당월" in c), None)
        col_emp  = next((c for c in df.columns if "본인기여금"   in c and "당월" in c), None)
        col_co   = next((c for c in df.columns if "사용자부담금"  in c and "당월" in c), None)

        if not (col_base and col_emp and col_co):
            errors.append(f"국민연금: 필수 컬럼 없음 (기준소득월액/본인기여금/사용자부담금). 실제 컬럼: {list(df.columns[:10])}")
            return records, errors

        for _, row in df.iterrows():
            name = str(row["성명"]).strip()
            if not name or name in ("nan", "성명"):
                continue
            try:
                base = _to_int(row[col_base])
                emp  = _to_int(row[col_emp])
                co   = _to_int(row[col_co])
                if base <= 0:
                    continue
                records.append({
                    "employee_name": name,
                    "pension_base":  base,
                    "pension_emp":   emp,
                    "pension_co":    co,
                })
            except Exception as e:
                errors.append(f"국민연금 [{name}]: {e}")
    except Exception as e:
        errors.append(f"국민연금 파일 오류: {e}")
    return records, errors


# ── 건강보험 파싱 ─────────────────────────────────────────────
def parse_health(file) -> tuple[list[dict], list[str]]:
    """
    건강보험 고지내역 CSV 파싱 (cp949).
    건강 + 요양 컬럼이 한 행에 나란히 배치.
    고지보험료 = 직원 부담분 (사용자 부담 동일 금액)
    """
    records = []
    errors  = []
    try:
        df = pd.read_csv(file, encoding="cp949")

        # 건강보험 행만 필터 (구분=='건강', 보수월액 > 0)
        df["_base"] = pd.to_numeric(df["보수월액"], errors="coerce").fillna(0)
        df_filt = df[(df["구분"] == "건강") & (df["_base"] > 0)].copy()

        # 중복 제거 (같은 사람이 여러 행일 경우 최신/정산 기준으로 합산)
        for name, grp in df_filt.groupby("성명"):
            name = str(name).strip()
            base       = _to_int(grp["보수월액"].iloc[0])
            health_emp = int(grp["고지보험료"].apply(_to_int).sum())
            care_emp   = int(grp["고지보험료.1"].apply(_to_int).sum()) if "고지보험료.1" in grp.columns else 0
            total_emp  = health_emp + care_emp
            records.append({
                "employee_name": name,
                "health_base": base,
                "health_emp":  total_emp,
                "health_co":   total_emp,  # 사용자 부담 = 직원 부담 (50/50)
            })
    except Exception as e:
        errors.append(f"건강보험 파일 오류: {e}")
    return records, errors


# ── 고용보험 파싱 ─────────────────────────────────────────────
def parse_employment(file) -> tuple[list[dict], list[str]]:
    """
    고용보험 고지내역 엑셀 파싱.
    구조: 행0=헤더(컬럼명), 행1=서브헤더(무시), 행2~=데이터
    보험료합계 컬럼:
      [0] = 근로자실업급여 (직원)
      [.1] = 사업주실업급여 (회사)
      [.2] = 사업주고안직능 (회사)
    """
    records = []
    errors  = []
    try:
        df = pd.read_excel(file)
        df = df.iloc[1:].copy()  # 서브헤더 행 제거
        df = df.reset_index(drop=True)

        col_name  = "근로자명"
        col_base  = "월평균보수금액"

        # 보험료합계 컬럼 4개 찾기
        sum_cols  = [c for c in df.columns if "보험료합계" in str(c)]
        if len(sum_cols) < 3:
            errors.append("고용보험: 보험료합계 컬럼을 찾지 못했습니다.")
            return records, errors

        col_emp = sum_cols[0]   # 근로자실업급여
        col_co1 = sum_cols[1]   # 사업주실업급여
        col_co2 = sum_cols[2]   # 사업주고안직능

        df["_base"] = pd.to_numeric(df[col_base], errors="coerce").fillna(0)
        df_filt = df[df["_base"] > 0].copy()

        for _, row in df_filt.iterrows():
            name = str(row[col_name]).strip()
            if not name or name in ("nan", "합계"):
                continue
            try:
                base    = _to_int(row[col_base])
                emp     = _to_int(row[col_emp])
                co1     = _to_int(row[col_co1])
                co2     = _to_int(row[col_co2])
                records.append({
                    "employee_name": name,
                    "employ_base":   base,
                    "employ_emp":    emp,
                    "employ_co":     co1 + co2,
                })
            except Exception as e:
                errors.append(f"고용보험 [{name}]: {e}")
    except Exception as e:
        errors.append(f"고용보험 파일 오류: {e}")
    return records, errors


# ── 3개 파일 병합 ─────────────────────────────────────────────
def merge_insurance_records(
    pension: list[dict],
    health:  list[dict],
    employ:  list[dict],
) -> list[dict]:
    """
    3개 파일 파싱 결과를 이름 기준으로 병합.
    어느 파일에만 있어도 저장 (없는 항목은 0).
    """
    merged: dict[str, dict] = {}

    def _upsert(name: str, data: dict):
        if name not in merged:
            merged[name] = {"employee_name": name}
        merged[name].update(data)

    for r in pension:
        _upsert(r["employee_name"], {
            "pension_base": r.get("pension_base", 0),
            "pension_emp":  r.get("pension_emp",  0),
            "pension_co":   r.get("pension_co",   0),
        })
    for r in health:
        _upsert(r["employee_name"], {
            "health_base": r.get("health_base", 0),
            "health_emp":  r.get("health_emp",  0),
            "health_co":   r.get("health_co",   0),
        })
    for r in employ:
        _upsert(r["employee_name"], {
            "employ_base": r.get("employ_base", 0),
            "employ_emp":  r.get("employ_emp",  0),
            "employ_co":   r.get("employ_co",   0),
        })

    return list(merged.values())


# ── 실납부액 급여 반영 ────────────────────────────────────────
def apply_insurance_actuals(entry: dict, actual: dict) -> dict:
    """
    calc_insured() 결과에 공단 고지 실납부액을 덮어씀.
    pension/health/employ 중 실납부액이 있는 항목만 대체.
    """
    entry = entry.copy()

    if actual.get("pension_emp", 0) > 0:
        entry["pension_emp"]      = actual["pension_emp"]
        entry["company_pension"]  = actual["pension_co"]

    if actual.get("health_emp", 0) > 0:
        entry["health_emp"]       = actual["health_emp"]
        entry["company_health"]   = actual["health_co"]

    if actual.get("employ_emp", 0) > 0:
        entry["employ_emp"]       = actual["employ_emp"]
        entry["company_employ"]   = actual["employ_co"]

    # 공제 합계 및 실수령액 재계산
    entry["total_deduction"] = (
        entry["income_tax"] + entry["local_tax"] +
        entry["pension_emp"] + entry["health_emp"] + entry["employ_emp"]
    )
    entry["net_pay"] = (
        entry["gross_pay"] + entry["meal_allowance"] + entry["transport"]
        - entry["total_deduction"]
    )
    return entry


# ── 간이세액표 파싱 (국세청 원본 포맷) ───────────────────────
def parse_tax_brackets(file, tax_year: int) -> tuple[list[dict], str]:
    """
    국세청 간이세액표 엑셀 파싱.
    - 행 0~4: 타이틀/헤더 (무시)
    - 행 5~: 실제 데이터 (이상/미만, 부양가족 1~11명, 단위: 천원)
    반환: (rows, error_msg)
    """
    try:
        df = pd.read_excel(file, header=None)
        data = df.iloc[5:].copy()

        # 숫자인 행만 (마지막 수식 텍스트 행 제거)
        data = data[pd.to_numeric(data[0], errors="coerce").notna()].copy()
        data = data[pd.to_numeric(data[1], errors="coerce").notna()].copy()
        data = data.reset_index(drop=True)

        rows = []
        for _, row in data.iterrows():
            s_from = int(float(row[0])) * 1000   # 천원 → 원
            s_to   = int(float(row[1])) * 1000

            # 부양가족 1~11명 → dependents_0~10
            deps = {}
            for i in range(11):
                col_idx = i + 2
                val = row[col_idx] if col_idx < len(row) else 0
                if str(val).strip() in ("-", "", "nan"):
                    val = 0
                deps[f"dependents_{i}"] = int(float(val) or 0)

            # dependents_0 = 파일의 1명 컬럼 (부양가족 없음 → 본인만 1명 적용)
            # 이미 deps["dependents_0"] = 1명 컬럼 값으로 매핑됨

            rows.append({
                "salary_from": s_from,
                "salary_to":   s_to,
                **deps,
                "tax_year": tax_year,
            })

        return rows, ""
    except Exception as e:
        return [], str(e)


# ── 내부 유틸 ────────────────────────────────────────────────
def _to_int(val) -> int:
    try:
        s = str(val).replace(",", "").strip()
        if s in ("-", "", "nan", "None"):
            return 0
        return int(float(s))
    except Exception:
        return 0
