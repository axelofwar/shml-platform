# shl-nano inference server — T8.4
# Built on PyTorch base; nanochat + trained weights mounted at /app/runs
FROM python:3.11-slim

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl build-essential git && \
    rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the server
COPY shl_nano_server.py ./

# nanochat source (bind-mounted from inference/shl-nano so weights stay on host)
# PYTHONPATH includes /nanochat which is bind-mounted at runtime
ENV PYTHONPATH=/nanochat

EXPOSE 8021

CMD ["python", "shl_nano_server.py"]
