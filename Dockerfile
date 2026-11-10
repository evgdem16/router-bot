FROM mcr.microsoft.com/playwright/python:v1.64.1-noble

WORKDIR /app

RUN pip install --no-cache-dir playwright==1.64.1

COPY main.py .

CMD ["python", "main.py"]
