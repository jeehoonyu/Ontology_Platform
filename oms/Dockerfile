FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY oms/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY oms/app ./app
COPY oms/AgentStudio.py ./AgentStudio.py
COPY oms/availability_probe.py ./availability_probe.py
COPY oms/tier_b_evidence.py ./tier_b_evidence.py
COPY oms/alembic.ini ./alembic.ini
COPY oms/alembic ./alembic
COPY oms/entrypoint.sh ./entrypoint.sh
COPY --from=frontend-build /frontend/dist /frontend/dist
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

CMD ["/app/entrypoint.sh"]
