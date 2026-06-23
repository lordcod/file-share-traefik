FROM python:3.12-alpine

RUN pip install --no-cache-dir pyftpdlib

COPY server.py /server.py

EXPOSE 21 40000-40100

CMD ["python", "/server.py"]