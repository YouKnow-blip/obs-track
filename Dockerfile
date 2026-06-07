# Детерминированная сборка релея для Railway.
# Используется вместо Nixpacks, чтобы сборка не зависела от автодетекта.
FROM python:3.11-slim

WORKDIR /app

# Сначала зависимости — для кэширования слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Затем код релея
COPY relay.py .

# Railway сам подставит переменную окружения PORT
CMD ["python", "relay.py"]
