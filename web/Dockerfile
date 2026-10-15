FROM python:3.11-slim-bookworm

WORKDIR /app

COPY web/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY web/ .

ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/var/data
ENV PORT=8080

RUN mkdir -p /var/data

EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 60 app:app"]
