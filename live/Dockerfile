FROM python:3.12-alpine
WORKDIR /app
COPY server.py /app/server.py
RUN python -m py_compile /app/server.py
CMD ["python", "-u", "/app/server.py"]
