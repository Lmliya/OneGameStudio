FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy

RUN pip install --no-cache-dir uv

WORKDIR /app

# 先复制依赖清单，利用构建缓存
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --frozen --no-dev

# 再复制运行所需源码与演示数据
COPY backend ./backend
COPY frontend ./frontend
COPY talents ./talents
COPY demo ./demo

# 机械门禁使用 Playwright 做真实浏览器检查（仅 Live 模式需要）
RUN uv run playwright install --with-deps chromium

ENV APP_MODE=demo \
    DEMO_READ_ONLY=false \
    MOCK_MODE=true \
    OUTPUT_DIR=/data/output \
    EVOLUTION_DIR=/data/evolution \
    DEMO_DIR=/app/demo/tasks

EXPOSE 8000

# Render / Railway 会注入 PORT；本地默认 8000
CMD ["sh", "-c", "uv run uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
