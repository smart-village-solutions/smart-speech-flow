FROM python:3.12-slim

WORKDIR /app

COPY services/api_gateway/requirements.txt /tmp/requirements.txt
RUN python -m pip install --disable-pip-version-check --no-cache-dir --require-hashes \
    -r /tmp/requirements.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* /tmp/requirements.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY services/__init__.py /app/services/__init__.py
COPY services/studio_mock/ /app/services/studio_mock/

ENV PYTHONPATH=/app
USER app

CMD ["uvicorn", "services.studio_mock.app:app", "--host", "0.0.0.0", "--port", "8000"]
