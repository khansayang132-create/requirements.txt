# APEX worker image: Blender (bpy) + ffmpeg + espeak-ng.
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg espeak-ng fonts-dejavu-core libgl1 libxi6 libxrender1 libxkbcommon0 libsm6 libxfixes3 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY apex ./apex
COPY samples ./samples
VOLUME ["/data"]
# One worker per container; it resumes queued and abandoned jobs from /data/jobs.db on start.
CMD ["python", "-m", "apex.cli", "worker", "--db", "/data/jobs.db"]
