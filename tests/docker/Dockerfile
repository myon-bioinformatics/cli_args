FROM python:3.14.0-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl coreutils systemd \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY cli_args.py pytest.ini ./
COPY tests ./tests
RUN python -m pip install --no-cache-dir -r tests/requirements.txt

CMD ["python", "-m", "pytest", "-q", "tests/test_container_commands.py"]
