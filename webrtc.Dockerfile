FROM python:3.11-slim

# Клонируем Python-репозиторий
RUN git clone https://github.com/kadr8/webrtc-py.git /app
WORKDIR /app

# Устанавливаем зависимости и запускаем
RUN pip install --no-cache-dir -r requirements.txt
CMD ["python", "server.py"]