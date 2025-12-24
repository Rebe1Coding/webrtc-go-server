FROM python:3.11-slim

WORKDIR /app

# Копируем файлы зависимостей
COPY requirements.txt .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем файлы приложения
COPY server.py .
COPY index.html .

# Открываем порт
EXPOSE 8000

# Запускаем сервер
CMD ["python", "server.py"]