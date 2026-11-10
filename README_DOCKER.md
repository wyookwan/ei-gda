# Deploy Ei-GDA V14.3 with Docker Compose

Requires Docker Engine with Compose v2, access to image/package registries, and network access from the container to the configured model APIs. Run commands inside this project directory.

## First deployment

```sh
git clone <repository-url>
cd <repository-directory>
cp .env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'
```

Edit `.env`: use the generated value for `SECRET_KEY`, set two distinct database passwords, Gemini credentials/model, and the Local Model URL. The model IP must be reachable from the deployment host/container (including any required VPN or firewall rules). `localhost` inside the container is the container itself. For the current internal deployment, set `LOCAL_MODEL_API_URL` to the supplied internal endpoint in the server's `.env` only. Neither the API nor its model weights are included in this image.

```sh
docker compose up -d --build
docker compose exec web python docker/bootstrap.py
docker compose ps
docker compose logs --tail=100 web
```

Bootstrap asks for an administrator email/password interactively, imports the full catalog, and refuses a non-empty application database. Do not run `seed.py` or `reset_db.py` on a production database: those development utilities may reset accounts/data.

Open http://127.0.0.1:5000. Compose uses MySQL internally at `db:3306`; it does not expose the database port. Uploads, reports and MySQL data use named volumes and survive container replacement. Startup applies the existing additive schema migration, not catalog reseeding.

## Remote access and ThaiD

Place an HTTPS reverse proxy in front of localhost port 5000, with an upload limit of at least 30 MB and request timeouts suitable for synchronous multi-batch assessments (default Gunicorn timeout: 1800 seconds). For direct LAN access set `APP_BIND_ADDRESS=0.0.0.0` and configure firewall access. This Compose stack does not provision TLS.

For ThaiD, enable `THAID_ENABLED`, set the endpoints or discovery URL and credentials, and register the exact public HTTPS `THAID_REDIRECT_URI` with the provider. Keep `SECRET_KEY` stable across restarts. Configure the provider/model names supported by your own accounts.

## Updates

Back up the database and both document volumes before upgrades. Keep the same directory/Compose project name so the existing named volumes are reused.

```sh
mkdir -p backups
docker compose exec -T db sh -c 'MYSQL_PWD="$MYSQL_PASSWORD" mysqldump --no-tablespaces --single-transaction -u"$MYSQL_USER" "$MYSQL_DATABASE"' > backups/database.sql
git pull --ff-only
docker compose up -d --build
docker compose logs --tail=100 web
```

Do not use `docker compose down -v` unless you intend to delete persistent data. Catalog updates are explicit maintenance operations; they are not run at each restart. This migration supports this project's schema, not arbitrary older database versions.

## Git handoff

Commit source, Dockerfile, Compose, `docker/`, this guide and `.env.example`. `.gitignore` and `.dockerignore` exclude `.env`, local virtual environments, uploaded PDFs, reports and database backups. Check `git status --short` before committing. Ignore rules do not untrack files already committed; remove any previously tracked sensitive files and rotate exposed credentials before publishing.

```sh
docker compose --env-file .env.example config --quiet
docker compose build
```

The web image runs as UID 10001, uses Gunicorn, and contains no runtime `.env` file. Restoring files into named volumes must preserve write permission for UID 10001.
