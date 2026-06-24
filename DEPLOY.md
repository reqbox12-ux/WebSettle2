# WebSettle2 NAS 배포 가이드

기존 Streamlit(8501)·구 포털(8502)을 새 ERP(8503)·새 CRM 포털로 교체.
**데이터(settlement.db)는 이전·복사 없이 기존 것을 그대로 공유**합니다.

원칙: **병행 가동 → 검증 → 전환 → 구버전 제거** (문제 시 즉시 롤백 가능)

---

## 0. 사전 확인 (NAS에 SSH 접속해서)

```bash
# 기존 앱 폴더와 실제 DB 위치 확인
ls /volume1/docker/webapp/data/settlement.db
# (경로가 다르면 아래 명령들의 DB_DIR 를 그 경로로 바꾸세요)
```

### 0-1. DB 백업 (필수)
```bash
cp /volume1/docker/webapp/data/settlement.db \
   /volume1/docker/webapp/data/settlement_backup_$(date +%Y%m%d).db
```

---

## 1. 새 앱 내려받기

```bash
cd /volume1/docker
sudo git clone -b feature/merge-crm https://github.com/reqbox12-ux/WebSettle2.git webapp2
cd webapp2
```
(이미 받았다면: `cd /volume1/docker/webapp2 && sudo git pull`)

---

## 2. 환경 설정 (.env 작성)

`webapp2` 폴더에 `.env` 파일 생성:
```bash
sudo tee .env > /dev/null <<'EOF'
DB_DIR=/volume1/docker/webapp/data
BACKUP_DIR=/volume1/docker/webapp/backups
PORTAL_BASE_URL=https://attend.laonfitness.com
ERP_BASE_URL=https://erp.laonfitness.com
CRM_PORT=8512
EOF
```
- **DB_DIR** : 기존 DB 폴더 (위 0번에서 확인한 경로) → 새 앱이 같은 DB 사용
- **CRM_PORT=8512** : 검증 단계엔 임시 포트(구 포털 8502와 충돌 방지). 전환 때 8502로 변경

---

## 3. 빌드 & 가동 (구버전은 그대로 둔 채 병행)

```bash
sudo docker-compose up -d --build
sudo docker-compose ps        # erp, crm 둘 다 Up 확인
sudo docker-compose logs -f   # 오류 없는지 확인 (Ctrl+C로 빠져나옴)
```

이 시점:
- 기존 Streamlit ERP(8501) · 구 포털(8502) **계속 정상 운영 중**
- 새 ERP = `http://<NAS_IP>:8503`, 새 CRM = `http://<NAS_IP>:8512`

---

## 4. 실데이터 검증 (NAS 내부망 IP로 접속)

브라우저에서:
- `http://192.168.0.237:8503` → admin 로그인 → 대시보드·지점·급여 숫자가 맞는지
- `http://192.168.0.237:8512/login` → 직원 로그인
- `http://192.168.0.237:8512/login/member` → 회원 로그인

새 앱 **설정 화면에서 운영 키 입력**:
- 토스 클라이언트키/시크릿키/variantKey
- 알리고 아이디/발신번호/API키
- 지점별 입금계좌

결제·문자 1건씩 실제로 테스트 (문자 링크는 폰에서 열려야 정상).

> ❗ 검증 중 문제 → `sudo docker-compose down` 하면 기존 시스템만 남아 업무 지장 없음.

---

## 5. 전환 (구버전 종료 → 새 포털을 8502로)

검증 OK면:

```bash
# 5-1. 구버전(Streamlit + 구 포털) 종료
cd /volume1/docker/webapp
sudo docker-compose down        # 8501, 8502 비워짐

# 5-2. 새 CRM 포트를 8502로 변경
cd /volume1/docker/webapp2
sudo sed -i 's/CRM_PORT=8512/CRM_PORT=8502/' .env
sudo docker-compose up -d       # crm 이 8502로 재가동
sudo docker-compose ps
```

---

## 6. 도메인 연결 (Cloudflare)

Cloudflare 대시보드 → **Zero Trust → Networks → Tunnels → (해당 터널) → Public Hostnames**:
- `erp.laonfitness.com`   → Service: `http://localhost:8503`
- `attend.laonfitness.com` → Service: `http://localhost:8502`

저장하면 직원·회원은 **같은 주소**로 접속하는데 내용만 새 앱으로 바뀝니다.
(cloudflared 컨테이너가 `network_mode: host` 면 localhost로 접근 가능)

확인: `https://erp.laonfitness.com`, `https://attend.laonfitness.com` 정상 동작.

---

## 7. 마무리

며칠 안정 운영 확인 후:
```bash
# 구버전 이미지/컨테이너 정리 (선택)
cd /volume1/docker/webapp
sudo docker-compose rm -f
```
`webapp` 폴더 자체는 **삭제하지 마세요** — 백업 DB·롤백용으로 보존.

---

## 🔙 롤백 (문제 발생 시)

```bash
# 새 앱 내리고
cd /volume1/docker/webapp2 && sudo docker-compose down
# 구버전 다시 올림
cd /volume1/docker/webapp  && sudo docker-compose up -d
# Cloudflare 도메인을 다시 8501/구포트로 되돌림
```
데이터는 같은 파일을 써서 유실 없음. (만일 대비 0-1 백업 보관)

---

## 자주 막히는 곳
- **DB가 비어보임** → `.env`의 `DB_DIR` 경로가 실제 DB 폴더와 다름. 0번 확인 경로로 수정.
- **결제 문자 링크가 폰에서 안 열림** → `PORTAL_BASE_URL` 미설정. .env 확인.
- **8502 포트 충돌** → 구 포털이 아직 떠 있음. 5-1 먼저 수행.
- **빌드 느림/실패** → `sudo docker-compose build --no-cache` 후 재시도.
