FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY server /app/server
COPY solver /app/solver
COPY web /app/web
COPY config/server.production.example.json /app/config/server.production.json
ENV GRID_CONFIG=/app/config/server.production.json
ENV GRID_DATA_DIR=/data
ENV GRID_HOST=0.0.0.0
ENV GRID_PORT=8765
EXPOSE 8765
CMD ["python","/app/server/coordinator_v2.py"]
