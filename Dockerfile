# harbor-sas — secondary packaging: container image for headless/server installs (Q3)
FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
RUN mkdir -p /data

EXPOSE 8799
VOLUME ["/data"]

CMD ["harbor", "serve", "--data-dir", "/data"]
