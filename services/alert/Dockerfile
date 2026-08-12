FROM python:3.12-slim
WORKDIR /app
COPY alert/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY alert/ ./alert/
EXPOSE 8006
CMD ["uvicorn", "alert.main:app", "--host", "0.0.0.0", "--port", "8006"]
