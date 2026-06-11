# WebSettle2 — 라온스포츠 차세대 ERP

기존 Streamlit ERP(WebSettle)를 FastAPI + 일반 웹앱으로 재구축하는 프로젝트.

## 핵심 설계

- **DB 공유**: 기존 `../WEBAPP/data/settlement.db`를 그대로 사용 (복사 ❌)
- **로직 재사용**: `sys.path`에 WEBAPP을 추가해 기존 집계/인증 모듈 import
- **포트**: 8503 (기존 ERP 8501, 지점 포털 8502와 공존)
- **인증**: 기존 users 테이블 + bcrypt + HMAC 토큰 그대로 사용
  → 기존 admin 계정으로 바로 로그인 가능

## 실행 (로컬)

```bash
pip install -r requirements.txt
./run.bat          # 또는: python -m uvicorn main:app --port 8503
# http://localhost:8503
```

전제: 같은 부모 폴더에 기존 WEBAPP 폴더가 있어야 함.

```
Project/
├── WEBAPP/    ← 기존 (DB·로직 원본)
└── WEBAPP2/   ← 이 저장소
```

## NAS Docker 배포 시

WEBAPP 폴더를 `/app/legacy`로 마운트:

```yaml
volumes:
  - ./WEBAPP2:/app
  - ./webapp:/app/legacy     # 기존 코드+DB
ports:
  - "8503:8503"
```

## 진행 상황

- [x] 골격: 로그인 + 사이드바 레이아웃 + 인증 API
- [x] 대시보드: KPI + 전월/전년 비교 + 추이 차트(고정형) + Excel 내보내기
- [x] 지점 상세: 손익계산서 + 목표 매출/달성률
- [x] 출퇴근 현황: 월별·지점별 조회 + 요약 KPI
- [x] 직원: 마스터 조회
- [x] 데이터 업로드: 카드/통장(자동분류)/급여 + 삭제
- [x] 설정: 미분류 검토(분류+규칙 동시 저장) + 규칙 관리
- [ ] 급여 계산·명세서 발행 (당분간 기존 ERP 사용)
- [ ] 4대보험 고지내역 업로드 (당분간 기존 ERP 사용)
- [ ] 백업/복원 (당분간 기존 ERP 사용)
- [ ] 정산서 HTML/Excel 내보내기 (지점 상세)
- [ ] NAS Docker 배포 + erp 도메인 전환
