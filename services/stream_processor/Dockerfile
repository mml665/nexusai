FROM python:3.12-slim
WORKDIR /app
COPY stream_processor/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY stream_processor/ ./stream_processor/
EXPOSE 8002
CMD ["uvicorn", "stream_processor.main:app", "--host", "0.0.0.0", "--port", "8002"]
