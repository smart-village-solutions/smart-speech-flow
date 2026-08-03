FROM nvidia/cuda:13.3.1-cudnn-runtime-ubuntu24.04 AS wheel-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY services/asr/requirements.txt ./requirements.txt

# Ubuntu's system pip is used once to install this hash-verified, fixed pip.
RUN printf '%s%s\n' \
    'pip==25.1.1 --hash=sha256:' \
    '2913a38a2abf4ea6b64ab507bd9e967f3b53dc1ede74b01b0931e1ce548751af' \
    > /tmp/pip-bootstrap.txt \
    && python3 -m pip install \
        --disable-pip-version-check \
        --break-system-packages \
        --ignore-installed \
        --no-cache-dir \
        --require-hashes \
        -r /tmp/pip-bootstrap.txt \
    && python3 -m pip download \
        --disable-pip-version-check \
        --no-cache-dir \
        --only-binary=:all: \
        --require-hashes \
        --dest /wheels \
        -r /tmp/pip-bootstrap.txt

# Source-only packages are built here. Runtime receives only the resulting
# wheelhouse; all downloaded source and wheel artifacts are hash-verified.
RUN python3 -m pip wheel \
    --disable-pip-version-check \
    --no-cache-dir \
    --require-hashes \
    --wheel-dir /wheels \
    -r requirements.txt

FROM nvidia/cuda:13.3.1-cudnn-runtime-ubuntu24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ffmpeg python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=wheel-builder /wheels /wheels
COPY services/asr/requirements.txt ./requirements.txt
COPY services/asr/app.py ./app.py
COPY services/gpu_metrics.py ./services/gpu_metrics.py

RUN printf '%s%s\n' \
    'pip==25.1.1 --hash=sha256:' \
    '2913a38a2abf4ea6b64ab507bd9e967f3b53dc1ede74b01b0931e1ce548751af' \
    > /tmp/pip-bootstrap.txt \
    && python3 -m pip install \
        --disable-pip-version-check \
        --break-system-packages \
        --ignore-installed \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --only-binary=:all: \
        --require-hashes \
        -r /tmp/pip-bootstrap.txt \
    && python3 -m pip install \
        --disable-pip-version-check \
        --break-system-packages \
        --no-cache-dir \
        --no-index \
        --find-links=/wheels \
        --only-binary=:all: \
        --no-deps \
        /wheels/*.whl \
    && rm -rf /wheels /tmp/pip-bootstrap.txt \
    && useradd --system --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
