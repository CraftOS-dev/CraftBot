FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir "aiohttp>=3.9"
COPY broker.py .

EXPOSE 8788
# BROKER_BASE_DOMAIN must be provided at run time, e.g.
#   docker run -e BROKER_BASE_DOMAIN=craft-dev.com -p 8788:8788 ...
CMD ["python", "broker.py"]
