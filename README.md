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
- [x] 대시보드: KPI 4종 + 지점별 손익 테이블
- [ ] 대시보드: 차트, 전월/전년 비교, Excel 내보내기
- [ ] 지점 상세 (손익계산서)
- [ ] 출퇴근 현황
- [ ] 인사/급여
- [ ] 데이터 업로드
- [ ] 설정 (규칙/계정)
