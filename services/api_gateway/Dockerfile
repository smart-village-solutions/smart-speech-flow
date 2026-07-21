FROM python:3.12-slim AS wheel-builder

WORKDIR /build
COPY services/api_gateway/requirements.txt ./requirements.txt

# Pin the installer before it resolves the hash-locked application dependencies.
RUN printf '%s%s\n' \
    'pip==25.1.1 --hash=sha256:' \
    '2913a38a2abf4ea6b64ab507bd9e967f3b53dc1ede74b01b0931e1ce548751af' \
    > /tmp/pip-bootstrap.txt \
    && python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --require-hashes \
        -r /tmp/pip-bootstrap.txt \
    && python -m pip download \
        --disable-pip-version-check \
        --no-cache-dir \
        --only-binary=:all: \
        --require-hashes \
        --dest /wheels \
        -r /tmp/pip-bootstrap.txt

# All gateway dependencies have published wheels. Verify their hashes before
# they enter the wheelhouse copied into the runtime image.
RUN python -m pip wheel \
    --disable-pip-version-check \
    --no-cache-dir \
    --only-binary=:all: \
    --require-hashes \
    --wheel-dir /wheels \
    -r requirements.txt

FROM python:3.12-slim

WORKDIR /app
COPY --from=wheel-builder /wheels /wheels
COPY services/api_gateway/requirements.txt ./requirements.txt

RUN printf '%s%s\n' \
    'pip==25.1.1 --hash=sha256:' \
    '2913a38a2abf4ea6b64ab507bd9e967f3b53dc1ede74b01b0931e1ce548751af' \
    > /tmp/pip-bootstrap.txt \
    && python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --only-binary=:all: \
        --require-hashes \
        -r /tmp/pip-bootstrap.txt \
    && apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && python -m pip install \
        --disable-pip-version-check \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --only-binary=:all: \
        --require-hashes \
        -r requirements.txt \
    && rm -rf /wheels /var/lib/apt/lists/* /tmp/pip-bootstrap.txt \
    && addgroup --system app \
    && adduser --system --ingroup app app \
    && chown -R app:app /app

COPY services/api_gateway/ /app/services/api_gateway/
COPY services/__init__.py /app/services/__init__.py
COPY examples/ /app/examples/

ENV PYTHONPATH=/app
USER app

CMD ["uvicorn", "services.api_gateway.app:app", "--host", "0.0.0.0", "--port", "8000"]
