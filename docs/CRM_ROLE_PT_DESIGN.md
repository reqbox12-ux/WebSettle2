# CRM 직무(Role) 체계 + PT/레슨 수업 라이프사이클 — 설계서 (v0.1, draft)

> 구현 전 설계 단계. 코드 작성 X. 검토/수정용 문서.
> 대상: WebSettle CRM(지점 포털, `branch_server.py`, 포트 8502) + WebSettle2 ERP(직무 입력 UI).
> 전제: WebSettle2 / CRM / (레거시 Streamlit) 모두 **동일한 `settlement.db`** 를 바라봄.

---

## 0. 전제 / 운영 제약 (반드시 확인)

- **DB 단일화**: WebSettle2(8503)의 "독립 DB 모드"(`main.py:22-27`)가 켜지면 별도 DB를 써서
  CRM이 직무를 못 읽음. 운영에서는 `SETTLEMENT_DB` 환경변수로 **CRM과 동일 파일**을 강제할 것.
- **마이그레이션 위치**: 신규 테이블/컬럼은 기존 `_migrate_*` 패턴으로 추가. 어느 앱이 먼저
  떠도 안전하도록 `CREATE TABLE IF NOT EXISTS` + 컬럼 존재검사.

---

## 1. 권한 계층 (3단계)

| 계층 | 정체 | 범위 |
|------|------|------|
| **본사 admin (최고관리자)** | ERP 관리자 계정 (기존 `admin=True`) | 전 지점. 환불/민원/AS 최종처리, **페이롤 확정→ERP 반영**, 타 직원 프로필·커리큘럼 수정, 상품등록 |
| **지점관리자 (manager role)** | 직무로 부여 | 자기 지점 전체 기능 열람·처리(상품등록·판매·요청처리·민원확인). 단 **환불 실집행·페이롤 확정은 본사** |
| **일반 직무** | info / trainer / golf_pro / gx | 직무별 제한된 기능 |

직무(role) enum: `info`, `trainer`, `golf_pro`, `gx`, `manager`
- trainer/golf_pro = **권한 동일**, 표시·페이롤 맥락만 구분(PT vs 골프레슨).
- **(사람 × 지점)당 최대 2개** 직무.

---

## 2. 데이터 모델

### 2.1 직무 / 멀티지점 로그인

```
employees (기존, 수정)
  + person_uid TEXT      -- 같은 사람의 여러 지점 행을 묶는 키 (주민번호 id_number 기반 생성)
  + commission_percent REAL DEFAULT 0   -- 트레이너/프로 %정산 상품용 개인 요율

employee_roles (신규)    -- 지점별 직무 (employee 행 = 지점단위이므로 자동으로 지점별 직무)
  employee_id INTEGER, role TEXT
  CHECK(role IN ('info','trainer','golf_pro','gx','manager'))
  -- (employee_id 당 최대 2행 = 앱 레벨에서 제한)

employee_accounts (수정)
  + person_uid TEXT      -- 계정은 '사람' 단위로 동작
  -- 로그인 = person_uid 인증 → 그 사람의 활성 employee 행들(=지점들) 조회
```

**로그인 흐름**
1. ID/PW 입력 → person_uid 인증
2. 서버가 person_uid로 묶인 활성 지점 + 각 지점 직무 반환
   `[{branch:'강남', emp_id:12, roles:['trainer','info']}, {branch:'송파', emp_id:34, roles:['manager']}]`
3. 지점 ≥2 → **모달로 지점 선택** / 1개면 자동
4. 토큰: `{person_uid, employee_id(선택지점), branch, roles:[...]}`
5. 헤더에서 지점 전환 = 토큰 재발급

### 2.2 상품 (정산 설정 확장)

```
products (기존, 수정)  -- category: 'gx'|'lesson'|'goods'
  price INTEGER          -- 상품가액 = VAT '미포함' 기준액 (정산·표시 기준)
  + pay_type TEXT DEFAULT ''   -- lesson 전용: 'percent' | 'per_session'
  + session_rate INTEGER DEFAULT 0   -- pay_type='per_session' 일 때 회당 강사단가
  -- percent 일 때 단가는 '트레이너 개인 %(commission_percent)' 사용

gx_pay_rules (신규)  -- GX 인원수 구간제 인센티브 (수업/상품 단위)
  product_id INTEGER, base_amount INTEGER, base_headcount INTEGER, extra_per_person INTEGER
  -- 예: base 40000 / base_headcount 10 / extra 1000
  --     정산 = base + max(0, 출석인원 - base_headcount) * extra
```

> **VAT는 결제수단으로 결정 (상품 속성 아님)**
> - 결제수단: `카드` / `계좌이체` / `관리비부과`
> - **카드결제만 VAT 발생** → 회원 청구액 = `상품가액 × 1.1` (예: 40만 → 44만 자동)
> - 계좌이체·관리비부과 = VAT 없음 → 청구액 = 상품가액
> - **강사 수당 기준액은 결제수단과 무관하게 항상 `상품가액`(VAT 제외)**
>   → 즉 `lesson_enrollments.base_amount = products.price`
> - 판매 시 `sales.amount`(실청구액, 카드면 VAT 포함)와 정산기준 `base_amount`를 분리 저장.

### 2.3 PT / 레슨 라이프사이클 (신규)

```
lesson_enrollments  -- 판매로 생성되는 '수강권'(회원 ↔ 담당강사 ↔ 패키지)
  id, branch, member_id, member_name,
  product_id, product_name, lesson_type('PT'|'골프레슨'),
  instructor_employee_id,            -- 담당강사 (판매시 지정, 이후 변경가능)
  total_sessions, used_sessions DEFAULT 0,
  pay_type, session_rate, percent_snapshot,  -- 판매시점 정산조건 스냅샷
  sale_id,                           -- sales 연결
  base_amount,                       -- %정산 기준액 = products.price (VAT 미포함, 결제수단 무관)
  pay_method,                        -- '카드'|'계좌이체'|'관리비' (청구액·VAT 계산용)
  status('active'|'done'|'refunded'),
  created_at

lesson_sessions  -- 개별 세션(예약 단위). 총 total_sessions 개까지 생성/예약
  id, enrollment_id, member_id, instructor_employee_id, branch,
  scheduled_date, scheduled_time,
  status('reserved'|'pending_sign'|'completed'|'no_show'|'canceled'),
  completed_at, signed_at, signature_png,   -- 캔버스 서명 이미지(base64/blob)
  payroll_period TEXT,               -- 'YYYY-MM' (완료 확정 시 기록)
  created_at
```

**상태기계**
```
reserved ──(강사 '진행완료')──▶ pending_sign ──(회원 캔버스 서명)──▶ completed  → 1회 차감·페이롤 카운트
reserved ──(강사 '노쇼')─────────────────────────────────────────▶ no_show    → 서명없이 진행인정·페이롤 카운트·1회 차감
reserved ──(취소)──▶ canceled  → 차감 없음, 슬롯 다시 예약 가능
```
- 10회권 = 최대 10개 reserved 생성. canceled 되면 그만큼 재예약 가능(`used_sessions` 미차감).
- completed/no_show 만 `used_sessions++` & 페이롤 집계 대상.

### 2.4 GX (신규/기존 통합)

```
gx_enrollments  -- 회원이 GX상품 구매 시 등록
  id, branch, gx_product_id, member_id, member_name, sale_id,
  status('active'|'expired'|'refunded'), created_at

gx_attendance  -- GX 강사가 날짜별 출석 체크
  id, gx_product_id, session_date, member_id, present(0/1),
  checked_by_employee_id, created_at
  UNIQUE(gx_product_id, session_date, member_id)
```
- GX상품은 `products(category='gx')` 에 **강사·요일·시간 미리 등록**(강사 변경은 상품편집에서).
- 판매 → `gx_enrollments` 자동 생성 → 해당 강사 '수업관리'에 회원 노출.
- 페이롤 = 세션 날짜별 출석인원 → `gx_pay_rules` 구간제 적용.

### 2.5 페이롤 정산

```
crm_payroll  -- CRM에서 계산되는 강사 보수 (월별·직원별)
  id, year, month, employee_id, branch,
  pt_session_count, pt_amount,       -- PT/레슨 합
  gx_session_count, gx_amount,       -- GX 합
  total_amount,
  status('draft'|'confirmed'),       -- 본사 admin 확정 시 'confirmed'
  confirmed_by, confirmed_at,
  UNIQUE(year, month, employee_id)
```
- **계산 위치 = CRM 내부**. 직원·지점관리자 모두 draft 열람.
- **확정 = 본사 admin** → `status='confirmed'` → **ERP가 confirmed 행만 읽어 표시**(별도 전송 X, 같은 DB 공유).

**정산 규칙 요약**
- PT/레슨 `percent`: 세션 1회 완료시 = `(base_amount / total_sessions) × 강사 commission_percent`
  (base_amount = 상품가액, VAT·결제수단 무관)
- PT/레슨 `per_session`: 세션 1회 완료시 = `session_rate` (고정)
- GX: 수업 발생일마다 = `base + max(0, 출석 - base_headcount) × extra_per_person`
- 모든 정산 기준액은 **상품가액(VAT 미포함)**. 카드결제 VAT(`×1.1`)는 청구액에만 반영, 수당엔 무관.

### 2.6 기타 기록 테이블 (신규)

```
daily_reports(employee_id, branch, report_date, comment, created_at)
  -- 화면에서 당일 매출/수업내역 자동집계 + comment 만 저장. (1인 1일 1행)

refund_requests(sale_id, enrollment_id, member_id, branch, reason,
                paid_amount,          -- 원결제액
                used_sessions, total_sessions,
                suggested_amount,     -- 자동 제안 환불액 (아래 공식)
                final_amount,         -- 처리자가 직접 입력하는 최종 환불액 (가변)
                requested_by_employee_id, created_at,
                approval_item_id)     -- 결재 라인 연결 (§2.7)
  -- 자동 제안 공식(기본): suggested = paid - (사용회차 단가) - 위약금
  --   사용회차 단가 = (상품가액/총횟수) × used_sessions
  --   위약금 = paid × 10% (최대), 면제 가능
  -- ★ '기본계산은 하되 최종 금액은 처리자가 적는다' — final_amount 가 실제 집행액

member_complaints(member_id, branch, content, status,
                  created_by_employee_id, created_at,
                  approval_item_id)   -- 결재 라인 연결 (§2.7)

product_suggestions(employee_id, branch, content, status('open'|'done'), created_at)
  -- 트레이너/프로 자유서술 → 관리자 확인 후 상품등록

instructor_profiles(employee_id, photo_png, intro, career, specialty, updated_at)
lesson_feedback(session_id, enrollment_id, member_id, instructor_employee_id,
                content, created_at)   -- 회원 페이지에 노출
curriculums(employee_id 또는 gx_product_id, title, body, updated_at)
```

**AS / 물품 (대부분 기존 활용 + 확장)**
- `as_requests`(기존): 자유서술 등록 → **결재 라인 진입(§2.7)** + 등록 즉시 알림.
- `inventory_items`(기존): + `min_qty` 임계치 → 차감(`inventory_transactions`)으로 재고 ≤ min_qty 시 **관리자 자동 알림**.
- `supply_requests`(기존): 물품 요청 → 결재 라인.

### 2.7 결재 / 이관 워크플로 (신규 — 핵심 축)

> 직원이 올리는 거의 모든 건(AS·물품요청·민원·환불·수업개설·일일보고)은
> **공통 결재 엔진**을 타고 `직원 → 지점관리자 → 본사관리자` 순으로 올라간다.
> 각 단계의 처리자/시각을 남겨 **누가 안 챙겼는지 감사추적** 가능.

```
approval_items  -- 모든 결재 대상의 공통 헤더
  id, branch,
  item_type ('as'|'supply'|'complaint'|'refund'|'suggestion'|'daily_report'|...),
  -- suggestion = 트레이너/골프프로의 상품/수업 의견제시 (수업개설 자체는 결재 X)
  ref_id,                 -- 해당 도메인 테이블 row id
  summary,                -- 알림/목록 표시용 한 줄
  created_by_employee_id, created_at,
  stage ('branch'|'hq'|'done'),     -- 현재 결재 단계
  branch_approved_by, branch_approved_at,
  hq_approved_by, hq_approved_at,
  status ('pending'|'branch_ok'|'completed'|'rejected'),
  reject_reason

notifications  -- 단계별 알림
  id, branch,
  target_kind ('branch_manager'|'hq_admin'|'employee'|'member'),
  target_employee_id,     -- target_kind='employee' 일 때
  approval_item_id,
  message, is_read, created_at
```

**흐름**
```
[생성] 직원이 AS/민원/환불/수업개설/일일보고 등록
        → approval_items(stage='branch') + 지점관리자에게 notification
        → (해당 지점에 manager 직무 없음? → stage='hq' 로 바로)
[1차]  지점관리자가 '결재처리(체크)'
        → branch_approved_*, stage='hq' → 본사관리자에게 notification
        → 그날 처리한 건들이 지점관리자 '일일보고'에 자동 누적
[2차]  본사관리자가 최종 처리(환불 집행/민원 종결 등)
        → hq_approved_*, stage='done', status='completed'
```

**지점관리자 일일보고 = 결재 롤업**
- 지점관리자의 일일보고 화면 = "오늘 내가 체크한 결재 항목"이 자동 정리 + 코멘트 입력.
- 예) 인포 매출 40만 / 트레이너 수업 2회 / 청소민원 / 트레드밀 AS
  → 인포·트레이너가 각자 일일보고·민원·AS 등록 → 지점관리자에게 체크 리스트로 표시
  → 모두 체크 시 지점관리자 일일보고에 자동 기록 → 코멘트 후 제출(=본사 이관)
  → 본사관리자에게도 체크내역 알림.
- **미체크 항목이 남아있으면** 누가 안 챙겼는지 한눈에 보임(감사추적 목적).

---

## 3. 직무별 화면(사이드바) 매핑

게이팅: 프론트 `PAGES`를 `allowedRoles:[...]`로 교체 + **백엔드 `require_role()` 이중 검사**.

| 모듈 | info | trainer/golf_pro | gx | manager | 본사admin |
|------|:--:|:--:|:--:|:--:|:--:|
| 홈/대시보드 | ✅ | ✅ | ✅ | ✅ | ✅ |
| 근태 | ✅ | ✅ | ❌ | ✅ | ✅ |
| 일일보고 | ✅ | ✅ | ❌ | ✅ | ✅ |
| 회원(등록/조회) | ✅ | ✅ | ❌ | ✅ | ✅ |
| 회원 상세 → 환불요청·민원등록 | ✅ | △ | ❌ | ✅ | ✅처리 |
| 상품 판매(POS) | ✅ | ✅ | ❌ | ✅ | ✅ |
| 상품 등록/수정 | ❌ | ❌ | ❌ | ✅ | ✅ |
| 수업관리(PT/레슨) | ❌ | ✅ | ❌ | ✅ | ✅ |
| 수업관리(GX 출석·회원) | ❌ | ❌ | ✅ | ✅ | ✅ |
| 운영(AS·물품요청·재고) | ✅ | 의견제시 | 의견제시 | ✅ | ✅ |
| 의견제시(상품) | ❌ | ✅ | ✅ | ✅ | ✅ |
| 프로필 | ❌ | ✅본인 | ✅본인 | ✅ | ✅타인 |
| 커리큘럼 | ❌ | ❌ | ✅등록 | ✅ | ✅수정 |
| 페이롤(본인 열람) | ❌ | ✅ | ✅ | ✅지점 | ✅확정 |
| 요청처리(AS/물품/민원/환불) | ❌ | ❌ | ❌ | ✅확인 | ✅집행 |

**회원(member) 포털**: PT 수강권/예정수업/**서명 대기(캔버스 서명)**/GX 일정/받은 피드백 표시.

---

## 4. 핵심 화면 흐름

**판매(PT/레슨)**: 상품 판매 → 회원 선택 → 상품 선택 → **담당 트레이너/프로 선택** → 결제완료
→ `lesson_enrollments` 생성. (담당강사 변경은 회원상세의 해당 수강권에서)

**판매(GX)**: 사전에 `products(gx)` + 강사 등록 → 판매 시 회원이 그 수업에 등록(`gx_enrollments`)
→ 해당 GX강사 수업관리에 회원 노출.

**PT 진행**: 강사·회원 협의로 세션 예약 → 회원포털에 예정일 표시 → 수업후 강사 '진행완료'
→ 회원 서명대기 → 회원 로그인 후 캔버스 서명 → 완료·차감·페이롤. (불참=강사 노쇼처리=진행인정)

**환불/민원**: 회원상세 → 판매상품 클릭 → 환불요청/민원 등록 → **결재(지점관리자 1차 → 본사 2차)**
→ 본사 최종처리(환불 집행/종결). 환불액은 자동 제안 + 처리자 최종 입력.

**결재 공통**: AS·물품·민원·환불·의견제시·일일보고 → 지점관리자 체크 → 본사 이관(§2.7).
(상품/수업 생성 자체는 결재 대상 아님 — 지점관리자·본사관리자가 직접 등록.)

**페이롤**: 월별 자동 집계(CRM) → 직원/지점관리자 열람 → 본사 admin 확정 → ERP 반영.

---

## 5. 단계별 구현 로드맵 (제안)

1. **Phase 1 — 직무/로그인 기반**: `person_uid`·`employee_roles` 스키마, WebSettle2 직원편집 UI(직무·지점),
   CRM 멀티지점 로그인 모달, 토큰 직무 적재, 사이드바+API 직무 게이팅.
2. **Phase 2 — 결재/알림 엔진**: `approval_items`·`notifications` 공통 엔진(이후 모든 기능이 여기 얹힘).
3. **Phase 3 — 상품/판매 정산설정**: products 정산필드(결제수단·VAT·pay_type), GX 구간제 룰, 담당강사 지정 판매흐름.
4. **Phase 4 — PT/레슨 라이프사이클**: enrollment/session, 예약·진행완료·노쇼·취소, 회원 캔버스 서명.
5. **Phase 5 — GX 출석·수업관리**, 프로필/커리큘럼/피드백.
6. **Phase 6 — 페이롤 집계·확정→ERP**, 일일보고(결재 롤업), 환불/민원/의견제시, AS·물품 알림.

> 결재 엔진을 앞단(Phase 2)에 두는 이유: 일일보고·AS·민원·환불·수업개설이 전부 그 위에 올라가므로 토대 먼저.

---

## 6. 확정된 결정 (resolved)

- **VAT**: 결제수단으로 결정(카드만 ×1.1). 강사 수당 기준은 항상 상품가액(VAT 제외).
- **환불**: 자동 제안값 계산 + 처리자가 최종금액 직접 입력. 진행분 보수는 유지.
- **결재 라인**: 직원 → 지점관리자(1차 체크) → 본사관리자(2차) 자동 이관 + 감사추적.
  지점관리자 일일보고는 그날 체크한 결재 항목 자동 롤업.
- **%정산 적립**: 세션 완료마다 `(상품가액/총횟수)×%`.

## 7. 남은 가정 (구현 중 확정)

1. **commission_percent 저장 위치**(가정): 사람×지점(=employee 행) 단위.
2. **person_uid 생성키**(가정): 주민번호(`id_number`). 미입력 직원 처리 정책 필요.
3. **노쇼 권한**: 트레이너/프로만(가정). GX는 노쇼 없음(출석체크로 대체).
4. **GX 페이롤 발생 단위**: '수업 발생일' 기준. 휴강/공휴일 처리 규칙 미정.
5. **지점관리자 없는 지점**: 1차 결재를 본사로 바로 올림(가정).
6. **상품/수업 생성**: 결재 대상 아님. 지점관리자·본사관리자 직접 등록. (트레이너/프로는 '의견제시'만)
