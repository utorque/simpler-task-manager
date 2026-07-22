FROM python:3.11-slim

WORKDIR /app

COPY sandbox/requirements.txt ./sandbox-requirements.txt
RUN pip install --no-cache-dir -r sandbox-requirements.txt

COPY sandbox/ ./sandbox/

# Non-root: snippets run as an unprivileged user owning only /workspace.
RUN useradd --create-home --uid 1000 sandbox \
    && mkdir -p /workspace \
    && chown sandbox:sandbox /workspace
USER sandbox

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV SANDBOX_WORKSPACE=/workspace
# matplotlib config/cache for the non-root user
ENV MPLCONFIGDIR=/tmp/mpl

EXPOSE 8766

CMD ["python", "sandbox/server.py"]
