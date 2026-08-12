FROM python:3.12-slim
WORKDIR /app
COPY observability/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY observability/ ./observability/
EXPOSE 8008
CMD ["uvicorn", "observability.main:app", "--host", "0.0.0.0", "--port", "8008"]
