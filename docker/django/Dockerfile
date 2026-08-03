FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Системные библиотеки
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    unixodbc \
    unixodbc-dev \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Microsoft ODBC Driver 18
RUN curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /usr/share/keyrings/microsoft-prod.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/microsoft-prod.gpg] https://packages.microsoft.com/debian/12/prod bookworm main" \
    > /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql18 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .

RUN pip install --no-cache-dir -r requirements-prod.txt

COPY . .

RUN chmod +x docker/django/entrypoint.sh

ENTRYPOINT ["docker/django/entrypoint.sh"]