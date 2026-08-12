FROM python:3.12-slim

WORKDIR /app

COPY ai_engine/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ai_engine/ ./ai_engine/
COPY common/ ./common/

EXPOSE 8004

CMD ["uvicorn", "ai_engine.main:app", "--host", "0.0.0.0", "--port", "8004"]
