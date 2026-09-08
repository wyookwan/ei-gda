# Ei-GDA Docker + Git Deployment

## Push to Git

```bash
git init
git add .
git status
git commit -m "Ei-GDA V14: Test Suites, local AI, committee comparison"
git branch -M main
git remote add origin <YOUR_PRIVATE_REPOSITORY_URL>
git push -u origin main
```

Before pushing:

```bash
git ls-files .env
git grep -n "THAID_CLIENT_SECRET"
git grep -n "MYSQL_ROOT_PASSWORD"
```

`git ls-files .env` should return nothing, and no real secrets should appear in tracked files.

Never copy real API keys into `.env.example`. If a key has been pasted into chat,
terminal history, or an earlier commit, rotate it before production deployment.

## Deploy on another server

```bash
git clone <YOUR_PRIVATE_REPOSITORY_URL>
cd Ei-GDA-V14
cp .env.example .env
# edit .env

docker compose build
docker compose up -d
# Schema migration runs automatically on container startup.
docker compose exec web python seed.py
docker compose exec web python check_v14.py
docker compose ps
```

`web` and `mysql` should both report `healthy`. Run `seed.py` only for a new
installation or when intentionally restoring the bundled reference catalog.
