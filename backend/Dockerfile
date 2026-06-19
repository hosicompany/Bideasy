FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Runtime ---
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl && \
    rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

COPY . .

# 비-root 사용자로 실행 (컨테이너 탈출 시 권한 상승 표면 축소).
# 쓰기 경로(전략 저장소·celerybeat·data)를 미리 만들어 소유권을 부여하면,
# 새로 생성되는 named 볼륨이 이 소유권을 상속한다.
# ※ 기존 배포의 strategy_data/celerybeat_data 볼륨은 root 소유이므로, 최초 1회
#   호스트에서 `chown -R 10001:10001` 적용이 필요할 수 있다(배포 노트 참조).
RUN useradd --system --no-create-home --uid 10001 appuser \
    && mkdir -p /app/data/strategy /app/celerybeat \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
