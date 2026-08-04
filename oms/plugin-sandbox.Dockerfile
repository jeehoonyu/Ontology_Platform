FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY plugin-sdk/python/src/ontologyos_plugin_sdk /usr/local/lib/python3.12/site-packages/ontologyos_plugin_sdk
RUN python -c "import ontologyos_plugin_sdk; assert ontologyos_plugin_sdk.SDK_API_VERSION == 1"

COPY oms/app/plugin_sandbox_runner.py /app/app/plugin_sandbox_runner.py

USER 65534:65534

ENTRYPOINT []
CMD ["python", "-I", "/app/app/plugin_sandbox_runner.py"]
