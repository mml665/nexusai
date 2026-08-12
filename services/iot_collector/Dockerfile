FROM python:3.12-slim
WORKDIR /app
COPY iot_collector/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY iot_collector/ ./iot_collector/
EXPOSE 8001
CMD ["uvicorn", "iot_collector.main:app", "--host", "0.0.0.0", "--port", "8001"]
