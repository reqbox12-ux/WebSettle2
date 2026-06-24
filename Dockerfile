# WebSettle2 — ERP(8503) + CRM 포털(8502) 통합 이미지
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 TZ=Asia/Seoul

WORKDIR /app

# 의존성 먼저 (캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 앱 전체 복사
COPY . .

# 데이터/백업 디렉터리 (볼륨으로 덮어씀)
RUN mkdir -p /app/data /app/backups

EXPOSE 8503 8502

# 기본은 ERP. CRM은 compose에서 command 오버라이드.
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8503"]
