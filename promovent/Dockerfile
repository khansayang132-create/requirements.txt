# Backend API and worker (same image, different command). No apt: LightGBM's one system
# dependency (libgomp) is copied from the matching full Python image.
# syntax=docker/dockerfile:1
FROM python:3.12-trixie AS gomp
RUN mkdir /gomp && cp -L /usr/lib/*-linux-gnu/libgomp.so.1 /gomp/

FROM python:3.12-slim-trixie
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
COPY --from=gomp /gomp/libgomp.so.1 /usr/local/lib/
RUN ldconfig
WORKDIR /app
COPY requirements.txt .
# Optional build secret `extra_ca` (PEM bundle) for builds behind a TLS-intercepting proxy; never stored in the image.
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -f /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; pip install -r requirements.txt
COPY alembic.ini ./
COPY alembic ./alembic
COPY promovent ./promovent
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh && useradd -m -u 10001 app && mkdir -p /data/models && chown -R app /data \
 && python -c "import lightgbm, sklearn, promovent.api"
USER app
ENV PROMOVENT_MODEL_DIR=/data/models PROMOVENT_ENV=production
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.getenv(\"PORT\",\"8000\")}/api/health', timeout=4)"
ENTRYPOINT ["/entrypoint.sh"]
CMD ["api"]
