FROM python:3.12-slim
WORKDIR /app
COPY asset_manager/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY common/ ./common/
COPY asset_manager/ ./asset_manager/
EXPOSE 8007
CMD ["uvicorn", "asset_manager.main:app", "--host", "0.0.0.0", "--port", "8007"]
