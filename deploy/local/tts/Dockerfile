FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir edge-tts

COPY server.py /app/server.py

ENV PORT=8790
ENV EDGE_TTS_VOICE=zh-CN-XiaoxiaoNeural
EXPOSE 8790

CMD ["python", "server.py"]
