"""
domains/branch/pdf.py — 정산서 HTML 생성
"""
from shared.utils import fn


def gen_pdf_html(df, branches: list, year: int, month: int,
                 exp_df=None, rev_df=None) -> str:
    payroll_cats = {"급여", "4대보험료", "소득세·지방세 합계", "프리랜서", "퇴직금", "소득세지방세"}
    CARD_CATS = ["PT매출(카드)", "GX매출(카드)", "골프매출(카드)", "키즈매출(카드)", "기타매출(카드)"]
    CASH_CATS = ["PT매출(현금)", "GX매출(현금)", "골프매출(현금)", "키즈매출(현금)", "기타매출(현금)",
                 "도급비", "시설상환비", "카페매출"]

    rows_html = ""
    for _, row in df[df.branch.isin(branches)].iterrows():
        b   = row.branch
        pnl = int(row["손익"])
        rt  = row["이익률"]
        pnl_col = "#2E7D5B" if pnl >= 0 else "#E60028"
        sign    = "▲" if pnl >= 0 else "▼"

        rev_by_cat: dict = {}
        if rev_df is not None and not rev_df.empty:
            br_rev = rev_df[rev_df.branch == b]
            rev_by_cat = br_rev.set_index("category")["supply_amount"].to_dict()

        card_detail_html = "".join(
            f'<tr class="sub"><td>&nbsp;&nbsp;{cat}</td><td class="amt">{fn(int(rev_by_cat.get(cat, 0)))} 원</td></tr>'
            for cat in CARD_CATS if int(rev_by_cat.get(cat, 0)) > 0
        ) or '<tr class="sub"><td>&nbsp;&nbsp;내역 없음</td><td class="amt">—</td></tr>'

        cash_detail_html = "".join(
            f'<tr class="sub"><td>&nbsp;&nbsp;{cat}</td><td class="amt">{fn(int(rev_by_cat.get(cat, 0)))} 원</td></tr>'
            for cat in CASH_CATS if int(rev_by_cat.get(cat, 0)) > 0
        ) or '<tr class="sub"><td>&nbsp;&nbsp;내역 없음</td><td class="amt">—</td></tr>'

        other_rows_html = ""
        if exp_df is not None and not exp_df.empty:
            br_exp   = exp_df[(exp_df.branch == b) & (~exp_df.category.isin(payroll_cats))]
            cat_sums = br_exp.groupby("category")["amount"].sum().sort_values(ascending=False)
            other_rows_html = "".join(
                f'<tr class="sub"><td>&nbsp;&nbsp;{cat}</td><td class="amt">{fn(amt)} 원</td></tr>'
                for cat, amt in cat_sums.items() if amt > 0
            )
        other_rows_html = other_rows_html or '<tr class="sub"><td>&nbsp;&nbsp;내역 없음</td><td class="amt">—</td></tr>'

        rows_html += f"""
        <div class="branch-block">
          <div class="branch-title">{b}</div>
          <table>
            <tr class="sec-head"><th colspan="2">[ 카드 매출 세부 ]</th></tr>
            {card_detail_html}
            <tr class="sub info-row"><td>&nbsp;&nbsp;부가세 {fn(row["카드VAT"])}원 · 수수료 {fn(row["카드수수료"])}원 차감</td><td></td></tr>
            <tr class="bold"><td>카드 실수령</td><td class="amt">{fn(row["카드실수령"])} 원</td></tr>
            <tr class="sec-head"><th colspan="2">[ 현금·기타 매출 세부 ]</th></tr>
            {cash_detail_html}
            <tr class="sub info-row"><td>&nbsp;&nbsp;부가세 {fn(row["현금VAT"])}원 차감</td><td></td></tr>
            <tr class="bold"><td>현금 공급가액</td><td class="amt">{fn(row["현금공급가액"])} 원</td></tr>
            <tr class="bold total"><td>총 매출</td><td class="amt">{fn(row["총매출"])} 원</td></tr>
            <tr class="sec-head"><th colspan="2">[ 인건비 ]</th></tr>
            <tr class="sub"><td>&nbsp;&nbsp;급여 (실수령)</td><td class="amt">{fn(row["급여"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;4대보험료 (직원부담)</td><td class="amt">{fn(row["4대보험료_직원"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;4대보험료 (본사부담)</td><td class="amt">{fn(row["4대보험_본사"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;소득세·지방세</td><td class="amt">{fn(row["소득세지방세"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;프리랜서</td><td class="amt">{fn(row["프리랜서"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;프리랜서 세금</td><td class="amt">{fn(row["프리랜서세금"])} 원</td></tr>
            <tr class="bold"><td>인건비 합계</td><td class="amt">{fn(row["인건비합계"])} 원</td></tr>
            <tr class="sec-head"><th colspan="2">[ 기타지출 ]</th></tr>
            {other_rows_html}
            <tr class="bold"><td>기타지출 합계</td><td class="amt">{fn(row["기타지출"])} 원</td></tr>
            <tr class="sec-head"><th colspan="2">[ 부가세 ]</th></tr>
            <tr class="sub"><td>&nbsp;&nbsp;카드 VAT</td><td class="amt">{fn(row["카드VAT"])} 원</td></tr>
            <tr class="sub"><td>&nbsp;&nbsp;현금 VAT</td><td class="amt">{fn(row["현금VAT"])} 원</td></tr>
            <tr class="bold"><td>부가세 합계</td><td class="amt">{fn(row["부가세합계"])} 원</td></tr>
            <tr class="bold total"><td>총 지출</td><td class="amt">{fn(row["총지출"])} 원</td></tr>
            <tr class="result"><td>순 손익</td>
              <td class="amt" style="color:{pnl_col}">{sign} {fn(abs(pnl))} 원</td></tr>
            <tr class="result"><td>이익률</td>
              <td class="amt" style="color:{pnl_col}">{("+" if rt >= 0 else "")}{rt}%</td></tr>
          </table>
        </div>"""

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
    <title>정산 보고서 {year}년 {month}월</title>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
    <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:'Pretendard Variable',sans-serif;background:#FAF7F5;color:#1F1B1B;padding:40px}}
    .report-header{{margin-bottom:32px;padding-bottom:20px;border-bottom:2px solid #E60028}}
    .report-header h1{{font-size:24px;font-weight:800;letter-spacing:-.02em}}
    .report-header p{{font-size:13px;color:#9A918C;margin-top:6px}}
    .branch-block{{background:#fff;border:1px solid rgba(31,27,27,.09);border-radius:12px;
      padding:20px;margin-bottom:20px;page-break-inside:avoid}}
    .branch-title{{font-size:16px;font-weight:700;margin-bottom:14px;padding-bottom:10px;
      border-bottom:1px solid rgba(31,27,27,.09);color:#1F1B1B}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    td{{padding:7px 4px;border-bottom:1px solid rgba(31,27,27,.06)}}
    td:last-child{{text-align:right}}
    .amt{{font-feature-settings:'tnum' 1;font-weight:500}}
    .sec-head th{{padding:10px 4px 6px;font-size:10.5px;color:#9A918C;font-weight:700;
      text-transform:uppercase;letter-spacing:.05em;text-align:left}}
    .sub td{{padding:5px 4px 5px;color:#5B5450;font-size:12px}}
    .bold td{{font-weight:700}}
    .total td{{border-top:1px solid rgba(31,27,27,.15);padding:10px 4px}}
    .result td{{font-size:14px;font-weight:700;padding:10px 4px;border-top:2px solid rgba(31,27,27,.1)}}
    .info-row td{{color:#9A918C;font-size:11.5px;padding:3px 4px;border-bottom:none}}
    @media print{{body{{padding:20px}}@page{{margin:15mm}}}}
    </style></head><body>
    <div class="report-header">
      <h1>정산 보고서</h1>
      <p>{year}년 {month}월 · 라온스포츠 · 선택 지점 {len(branches)}개 · 브라우저에서 인쇄(Ctrl+P) → PDF로 저장</p>
    </div>
    {rows_html}
    </body></html>"""
