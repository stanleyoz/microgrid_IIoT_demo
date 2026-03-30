FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY sim_site.py .
COPY ca.crt .

CMD ["python", "sim_site.py"]
