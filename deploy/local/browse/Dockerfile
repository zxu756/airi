FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY fetch.py search.py server.py /app/
COPY tests /app/tests

ENV PORT=8791
ENV PYTHONUNBUFFERED=1
EXPOSE 8791

CMD ["python", "server.py"]
