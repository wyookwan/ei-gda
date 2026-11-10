FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --create-home --uid 10001 eigda
COPY --chown=eigda:eigda . .
RUN mkdir -p /app/uploads /app/reports \
    && chown -R eigda:eigda /app/uploads /app/reports \
    && chmod +x /app/docker/entrypoint.sh
USER eigda
EXPOSE 5000
ENTRYPOINT ["/app/docker/entrypoint.sh"]
CMD ["gunicorn", "--config", "docker/gunicorn.conf.py", "app:app"]
