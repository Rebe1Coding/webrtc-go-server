FROM python:3.11-slim

WORKDIR /webrtc-go-server
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . https://github.com/Rebe1Coding/webrtc-go-server.git.


CMD ["python", "server.py"]