# Container Dependency Policy

Each Python service has a `requirements.in` source file and a generated,
hash-verified `requirements.txt` runtime lock. Regenerate all locks from the
repository root with pip-tools 7.5.2:

```bash
PIP_COMPILE=pip-compile scripts/generate_container_locks.sh
```

Do not edit generated lock files manually. Every Dockerfile bootstraps
`pip==25.1.1` using the pinned wheel hash
`2913a38a2abf4ea6b64ab507bd9e967f3b53dc1ede74b01b0931e1ce548751af` before
it resolves application dependencies. The builder downloads that same verified
pip wheel into its controlled wheelhouse. The runtime stage installs that
identical pip version only from the wheelhouse, with `--no-index` and
`--require-hashes`, before it installs service wheels offline using
`--no-index`, `--only-binary=:all:`, and `--no-deps`.

The CUDA images use Ubuntu's package-managed Python. Their bootstrap includes
`--break-system-packages --ignore-installed`, which places the verified pip
wheel in `/usr/local` instead of attempting to remove Debian's pip package.

The builder verifies the application lock with `--require-hashes`; runtime
installs the complete verified wheelhouse directly because a wheel built from a
verified source distribution has a different artifact hash. Source
distributions are permitted only in a builder stage and are verified against
the lock before a local wheel is produced.

## GPU Matrix

ASR, Translation, and TTS use `nvidia/cuda:13.0.0-cudnn-runtime-ubuntu24.04`.
Ubuntu 24.04 provides Python 3.12, and their locks pin `torch==2.13.0` together
with the CUDA 13.0 dependency chain (`cuda-toolkit==13.0.3.0`). No service uses
the CUDA 12.1 PyTorch index. `torchvision` and `torchaudio` are intentionally
absent because none of the three services imports them; adding either requires
an explicit compatible, hash-locked version and a GPU smoke test.

## Verification

Build all production images from the repository root. The GPU images include
the shared `services/gpu_metrics.py` module:

```bash
docker build -f services/api_gateway/Dockerfile -t ssf-api-gateway .
docker build -f services/asr/Dockerfile -t ssf-asr .
docker build -f services/translation/Dockerfile -t ssf-translation .
docker build -f services/tts/Dockerfile -t ssf-tts .
```

After a GPU build, verify `torch.cuda.is_available()` with the NVIDIA runtime
and call each service's `/health` endpoint. Run `pip-audit -r` against every
generated lock before merging dependency changes.
