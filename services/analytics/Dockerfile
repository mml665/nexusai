FROM python:3.12-slim
WORKDIR /app
COPY analytics/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY analytics/ ./analytics/
EXPOSE 8005
CMD ["uvicorn", "analytics.main:app", "--host", "0.0.0.0", "--port", "8005"]
