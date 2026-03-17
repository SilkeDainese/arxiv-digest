FROM python:3.12-slim

WORKDIR /app

# Copy setup wizard files
COPY setup/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY setup/ setup/
COPY brand.py .
COPY student_registry.py .

EXPOSE 8080

CMD ["python", "setup/server.py"]
