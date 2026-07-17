FROM python:3.12-slim
WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .
EXPOSE 3000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "3000"]
