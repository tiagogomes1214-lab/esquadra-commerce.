FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py run.py start_server.py ./
COPY static ./static
COPY templates ./templates
RUN mkdir -p /app/data/uploads
EXPOSE 8080
CMD ["python","start_server.py"]
