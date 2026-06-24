"""
domains/payroll/payslip/service.py — 급여명세서/원천징수영수증 HTML 생성
"""
from shared.utils import fn


def gen_payslip_html(entry: dict, company_name: str = "라온스포츠") -> str:
    """4대보험 가입자 급여명세서 HTML"""
    year   = entry["year"]
    month  = entry["month"]
    name   = entry.get("name", "")
    branch = entry.get("branch", "")
    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>급여명세서 {year}년 {month}월 · {name}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Pretendard Variable',sans-serif;background:#fff;color:#1F1B1B;padding:40px;max-width:600px;margin:0 auto}}
.header{{border-bottom:2px solid #E60028;padding-bottom:16px;margin-bottom:24px}}
.header h1{{font-size:20px;font-weight:800}}
.header p{{font-size:12px;color:#9A918C;margin-top:4px}}
.info-grid{{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:24px;
  background:#FAF7F5;border-radius:8px;padding:16px}}
.info-item label{{font-size:10px;color:#9A918C;font-weight:700;text-transform:uppercase;display:block;margin-bottom:2px}}
.info-item span{{font-size:13px;font-weight:600}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px}}
th{{background:#FAF7F5;padding:8px 10px;text-align:left;font-size:10px;color:#9A918C;font-weight:700;
  text-transform:uppercase;border-bottom:1px solid rgba(31,27,27,.1)}}
td{{padding:9px 10px;border-bottom:1px solid rgba(31,27,27,.06)}}
td:last-child{{text-align:right;font-feature-settings:'tnum' 1}}
.total-row td{{font-weight:700;font-size:14px;border-top:2px solid rgba(31,27,27,.15);padding:12px 10px}}
.net-box{{background:#E60028;color:#fff;border-radius:10px;padding:16px 20px;
  display:flex;justify-content:space-between;align-items:center;margin-top:8px}}
.net-box .label{{font-size:13px;font-weight:600}}
.net-box .amount{{font-size:20px;font-weight:800}}
@media print{{body{{padding:20px}}@page{{margin:10mm}}}}
</style></head><body>
<div class="header">
  <h1>급여명세서</h1>
  <p>{company_name} · {year}년 {month}월</p>
</div>
<div class="info-grid">
  <div class="info-item"><label>성명</label><span>{name}</span></div>
  <div class="info-item"><label>소속</label><span>{branch}</span></div>
</div>

<table>
  <tr><th colspan="2">지급 내역</th></tr>
  <tr><td>기본급</td><td>{fn(entry.get('gross_pay',0))} 원</td></tr>
  <tr><td>식대</td><td>{fn(entry.get('meal_allowance',0))} 원</td></tr>
  <tr><td>교통비</td><td>{fn(entry.get('transport',0))} 원</td></tr>
  <tr class="total-row"><td>지급 합계</td>
    <td>{fn(entry.get('gross_pay',0)+entry.get('meal_allowance',0)+entry.get('transport',0))} 원</td></tr>
</table>

<table>
  <tr><th colspan="2">공제 내역</th></tr>
  <tr><td>소득세</td><td>{fn(entry.get('income_tax',0))} 원</td></tr>
  <tr><td>지방소득세</td><td>{fn(entry.get('local_tax',0))} 원</td></tr>
  <tr><td>국민연금 (직원부담)</td><td>{fn(entry.get('pension_emp',0))} 원</td></tr>
  <tr><td>건강보험 (직원부담)</td><td>{fn(entry.get('health_emp',0))} 원</td></tr>
  <tr><td>고용보험 (직원부담)</td><td>{fn(entry.get('employ_emp',0))} 원</td></tr>
  <tr class="total-row"><td>공제 합계</td><td>{fn(entry.get('total_deduction',0))} 원</td></tr>
</table>

<div class="net-box">
  <span class="label">실 수령액</span>
  <span class="amount">{fn(entry.get('net_pay',0))} 원</span>
</div>
</body></html>"""


def gen_withholding_html(entry: dict, company_name: str = "라온스포츠") -> str:
    """사업소득자 사업소득 원천징수영수증 HTML"""
    year    = entry["year"]
    month   = entry["month"]
    name    = entry.get("name", "")
    branch  = entry.get("branch", "")
    payment = entry.get("gross_pay", 0)
    inc_tax = entry.get("income_tax", 0)
    loc_tax = entry.get("local_tax", 0)
    net_pay = entry.get("net_pay", 0)

    return f"""<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8">
<title>사업소득 원천징수영수증 {year}년 {month}월 · {name}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Pretendard Variable',sans-serif;background:#fff;color:#1F1B1B;padding:40px;max-width:600px;margin:0 auto}}
.header{{border-bottom:2px solid #1F1B1B;padding-bottom:16px;margin-bottom:24px;text-align:center}}
.header h1{{font-size:18px;font-weight:800;letter-spacing:.05em}}
.header p{{font-size:11px;color:#9A918C;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px}}
th{{background:#FAF7F5;padding:8px 10px;text-align:left;font-size:10px;color:#9A918C;font-weight:700;
  border-bottom:1px solid rgba(31,27,27,.1)}}
td{{padding:9px 10px;border-bottom:1px solid rgba(31,27,27,.06)}}
td:last-child{{text-align:right;font-feature-settings:'tnum' 1}}
.total-row td{{font-weight:700;border-top:2px solid rgba(31,27,27,.15);padding:12px 10px}}
.sign-box{{margin-top:40px;text-align:right;font-size:12px;color:#9A918C}}
@media print{{body{{padding:20px}}@page{{margin:10mm}}}}
</style></head><body>
<div class="header">
  <h1>사업소득 원천징수영수증</h1>
  <p>{year}년 {month}월 귀속분</p>
</div>

<table>
  <tr><th colspan="2">지급자 정보</th></tr>
  <tr><td>상호(법인명)</td><td>{company_name}</td></tr>
  <tr><td>소재지</td><td>{branch}</td></tr>
</table>

<table>
  <tr><th colspan="2">소득자 정보</th></tr>
  <tr><td>성명</td><td>{name}</td></tr>
</table>

<table>
  <tr><th colspan="2">지급 및 원천징수 내역</th></tr>
  <tr><td>지급 금액</td><td>{fn(payment)} 원</td></tr>
  <tr><td>소득세 (3%)</td><td>{fn(inc_tax)} 원</td></tr>
  <tr><td>지방소득세 (0.3%)</td><td>{fn(loc_tax)} 원</td></tr>
  <tr class="total-row"><td>원천징수 합계 (3.3%)</td><td>{fn(inc_tax+loc_tax)} 원</td></tr>
  <tr class="total-row"><td>실 지급액</td><td>{fn(net_pay)} 원</td></tr>
</table>

<div class="sign-box">
  <p>{year}년 {month}월 말일</p>
  <p style="margin-top:8px">{company_name} (인)</p>
</div>
</body></html>"""
