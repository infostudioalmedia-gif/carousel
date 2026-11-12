FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg chromium ca-certificates fonts-noto-core \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir pillow yt-dlp
RUN useradd -m -u 1000 user
USER user
WORKDIR /home/user/carousel/app
COPY --chown=user app /home/user/carousel/app
ENV ROOYA_CHROME=/usr/bin/chromium ROOYA_HOST=0.0.0.0 ROOYA_PORT=7860 ROOYA_NOSANDBOX=1 \
    ROOYA_JOBS=/home/user/jobs PYTHONIOENCODING=utf-8
EXPOSE 7860
CMD ["python", "server.py"]
