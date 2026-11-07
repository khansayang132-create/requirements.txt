FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY promovent ./promovent
COPY migrations ./migrations
RUN useradd -m app && mkdir -p /data && chown app /data
USER app
ENV PROMOVENT_DB=/data/promovent.db PROMOVENT_MODE=paper
EXPOSE 8000
CMD ["sh", "-c", "uvicorn promovent.api:app --host 0.0.0.0 --port ${PORT:-8000}"]
