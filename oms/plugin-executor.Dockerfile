FROM docker:27-cli@sha256:851f91d241214e7c6db86513b270d58776379aacc5eb9c4a87e5b47115e3065c

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

RUN apk add --no-cache python3 \
    && addgroup -S executor \
    && adduser -S -G executor -u 10001 executor

WORKDIR /app
COPY oms/app/plugin_oci.py ./app/plugin_oci.py
COPY oms/app/plugin_egress.py ./app/plugin_egress.py
COPY oms/app/plugin_executor.py ./app/plugin_executor.py

USER 10001:10001
EXPOSE 8092
CMD ["python3", "-m", "app.plugin_executor"]
