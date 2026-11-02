FROM python:3.14.0-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV CLI_ARGS_CONTAINER_REAL=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends git curl coreutils sed grep findutils tar gzip ripgrep systemd ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace
COPY cli_args.py pytest.ini pyproject.toml uv.lock ./
COPY tests ./tests
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/
RUN uv sync --locked --python "$(command -v python)"
ENV PATH="/workspace/.venv/bin:$PATH"

CMD ["uv", "run", "--locked", "pytest", "-q", "tests/test_container_commands.py"]
