# anton — secondary packaging: container image for headless/server installs (Q3)
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssh-client && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .
RUN mkdir -p /data

ENTRYPOINT ["/app/entrypoint.sh"]

EXPOSE 8799
VOLUME ["/data"]

CMD ["anton", "serve", "--data-dir", "/data"]
