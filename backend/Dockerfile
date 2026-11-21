# Install Python dependencies in a builder stage so build tools and pip cache
# do not become part of the runtime image.
FROM python:3.12-slim AS dependencies

ENV VIRTUAL_ENV=/opt/venv
ENV PATH="${VIRTUAL_ENV}/bin:${PATH}"
WORKDIR /build

COPY backend/requirements.txt ./requirements.txt
RUN python -m venv "${VIRTUAL_ENV}" \
    && pip install --no-cache-dir -r requirements.txt

# Runtime image contains only the app, its virtual environment, and Python.
FROM python:3.12-slim AS runtime

ENV VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATABASE_URL=sqlite:////data/app.db

RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --create-home app \
    && mkdir -p /data \
    && chown app:app /data

WORKDIR /app
COPY --from=dependencies /opt/venv /opt/venv
COPY --chown=app:app backend/app ./app

USER app
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
