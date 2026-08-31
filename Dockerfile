FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml README.md THIRD_PARTY.md ./
COPY bastioncam ./bastioncam

RUN pip install --no-cache-dir . \
    && groupadd --gid 10001 bastioncam \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin bastioncam \
    && mkdir -p /data \
    && chown 10001:10001 /data

USER 10001:10001
VOLUME ["/data"]
EXPOSE 8787

ENTRYPOINT ["bastioncam"]
CMD ["--db", "/data/history.db", "serve", "--host", "0.0.0.0", "--port", "8787"]

