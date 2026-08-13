FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app
COPY oms/app/plugin_egress.py ./app/plugin_egress.py

USER 65534:65534
EXPOSE 8080
CMD ["python3", "-m", "app.plugin_egress"]
