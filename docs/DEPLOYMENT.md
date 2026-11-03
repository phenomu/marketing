# MARKETING — Deployment Guide (PHASE 9)

Target: Linux server (Ubuntu 22.04+/Debian 12+), Docker + Compose v2.24+.
Semua perintah dari repo root di server.

## 1. Prasyarat

- Server dengan Docker Engine + Compose plugin (`docker compose version` ≥ v2.24 — file prod memakai `!override`).
- Akses SSH non-root (deploy sebagai user biasa; daemon docker jalan tanpa sudo).
- DNS: `api.example.com` → IP server (untuk unsubscribe link + API), `dash.example.com` → IP server (opsional, dashboard).
- SMTP provider siap (mis. Brevo/Mailgun/SendGrid) — kredensial disiapkan SEBELUM live sending.
- Firewall (ufw/cloud): hanya 22, 80, 443 terbuka. Port 8000/8501/5432 TIDAK boleh publik — reverse proxy yang expose.

## 2. Deploy pertama kali

```bash
# 1) ambil repo
git clone git@github.com:phenomu/marketing.git && cd marketing

# 2) siapkan environment produksi
cp .env.prod.example .env
# EDIT .env — isi SEMUA nilai REQUIRED:
#   POSTGRES_PASSWORD, API_AUTH_TOKEN, UNSUBSCRIBE_SECRET, UNSUBSCRIBE_BASE_URL
python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # generator token

# 3) bangun image + start full stack (project name terpisah dari dev)
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  -p marketing-prod --profile full up -d --build

# 4) verifikasi
docker compose -p marketing-prod ps          # 5/5 healthy
python scripts/health_monitor.py --api http://127.0.0.1:8000 --dashboard http://127.0.0.1:8501
```

Perbedaan prod vs dev (docker-compose.prod.yml):
- DB tanpa host port — hanya jalan di network compose internal.
- State di named volumes `pgdata`, `applogs`, `appdata` (bukan bind mount host).
- `restart: always` + memory limit per service.
- `APP_ENV=production` → Swagger/ReDoc/OpenAPI disabled.
- Image tag `marketing-app:prod`.

## 3. Reverse proxy (wajib untuk akses publik)

Semua port aplikasi bind 127.0.0.1. Akses publik HANYA via reverse proxy dengan TLS.

Caddy (paling simpel — auto-HTTPS):

```
api.example.com {
    reverse_proxy 127.0.0.1:8000
}
dash.example.com {
    reverse_proxy 127.0.0.1:8501
}
```

API menyertakan header auth sendiri (`X-Auth-Token`/`Bearer`), dashboard pakai `?token=…`.
Unsubscribe endpoint (`/unsubscribe`) sengaja publik — jangan diblokir proxy (RFC 8058).

nginx (alternatif):

```nginx
server {
    server_name api.example.com;
    location / { proxy_pass http://127.0.0.1:8000; }
    listen 443 ssl;  # sertifikat via certbot
}
```

## 4. Auth layer (API_AUTH_TOKEN)

- `API_AUTH_TOKEN` kosong → auth OFF (hanya aman untuk localhost).
- Diisi → backend minta `X-Auth-Token: <token>` atau `Authorization: Bearer <token>` di semua endpoint KECUALI `/health`, `/ready`, `/unsubscribe` (publik by design — healthcheck infra + RFC 8058).
- Dashboard: buka `https://dash.example.com/?token=<token>` — token dicek sekali lalu dihapus dari URL (disimpan di session Streamlit, tidak bocor via referrer/bookmark).
- Rotasi token: ganti nilai di `.env` → `docker compose -p marketing-prod up -d` (restart). Semua client harus update token.
- Token tidak pernah di-log; percobaan gagal di-log path + IP saja.

## 5. Backup database

```bash
python scripts/backup_db.py backup             # dump sekarang (custom format, gzip)
python scripts/backup_db.py verify backups/marketing-...dump
python scripts/backup_db.py restore backups/marketing-...dump --confirm-my-data
```

- Otomatis pakai `pg_dump` versi container DB (server 17 ↔ client 17 — host client 16 akan gagal).
- Password hanya via `PGPASSWORD` env, tidak pernah di argv.
- Restore = single transaction: gagal di tengah → rollback penuh.
- Rotasi: `--keep N` (default 14). Direktori `backups/` — masukkan ke backup off-site (rclone/rsync ke storage lain).

Cron harian (02:00 UTC, simpan log):

```cron
0 2 * * * cd /opt/marketing && python scripts/backup_db.py backup >> logs/backup.log 2>&1
```

Cron off-site (contoh rclone ke S3-compatible):

```cron
30 2 * * * rclone sync /opt/marketing/backups remote:marketing-backups --transfers 4
```

## 6. Monitoring

```bash
python scripts/health_monitor.py            # human-readable, exit 0/1
python scripts/health_monitor.py --json     # untuk exporter/ingest
```

Cek: api `/health`, api `/ready`, dashboard `/_stcore/health`, DB connect + row counts, worker/scheduler heartbeat freshness (max 90s), disk free (min 1 GB).

Cron alert (contoh — setiap 5 menit, email saat gagal):

```cron
*/5 * * * * cd /opt/marketing && python scripts/health_monitor.py >> logs/monitor.log 2>&1 || echo "MARKETING unhealthy $(date)" | mail -s "[MARKETING] alert" ops@example.com
```

Aturan umum: alert pada `exit != 0`; dashboard Overview menampilkan data yang sama (health worker/scheduler = heartbeat age).

## 7. Update aplikasi

```bash
cd /opt/marketing
git pull origin master
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  -p marketing-prod --profile full up -d --build
python scripts/health_monitor.py
```

Skema DB migrasi additive otomatis saat service start (`app.db.init_db` — ALTER ADD COLUMN, tanpa drop). Backup dulu saat update besar:

```bash
python scripts/backup_db.py backup
```

## 8. Rollback

```bash
git checkout <commit-sebelumnya>
docker compose --env-file .env -f docker-compose.yml -f docker-compose.prod.yml \
  -p marketing-prod --profile full up -d --build
# kalau butuh data rollback:
python scripts/backup_db.py restore backups/marketing-<timestamp>.dump --confirm-my-data
```

## 9. Mode hybrid (opsional)

Native Python + DB container di server (hemat resource):

```bash
docker compose up -d db                    # hanya postgres
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.prod.example .env && $EDITOR .env  # POSTGRES_HOST=127.0.0.1
.venv/bin/python -m uvicorn app.main:api --host 127.0.0.1 --port 8000
.venv/bin/python -m app.worker &
.venv/bin/python -m app.scheduler &
.venv/bin/python -m streamlit run dashboard/main.py --server.headless true --server.port 8501
```

Sistemd unit untuk auto-restart native service — lihat template di bagian bawah file ini.

## 10. Troubleshooting deploy

- `docker compose ps` ada service unhealthy → `docker compose logs <service> --tail 50`.
- Healthcheck api gagal → cek DB: `docker exec marketing-prod-db-1 pg_isready -U marketing`.
- Worker unhealthy → heartbeat stale: cek `logs/heartbeat/worker.json` mtime; `docker compose logs worker`.
- Backup gagal "version mismatch" → pastikan container DB jalan (script otomatis pakai container tools).
- 401 di API padahal token benar → cek header: `X-Auth-Token` (bukan `X-Auth-Token:`) atau `Authorization: Bearer …`; cek `.env` yang benar ter-load (`--env-file .env`).
- Dashboard 401/token salah → URL `?token=…` harus persis sama dengan `API_AUTH_TOKEN`; token dihapus dari URL setelah sukses — bookmark tanpa token akan gagal, simpan URL ber-token.

---

## Template systemd (mode hybrid)

`/etc/systemd/system/marketing-worker.service`:

```ini
[Unit]
Description=MARKETING worker
After=network.target docker.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/marketing
EnvironmentFile=/opt/marketing/.env
ExecStart=/opt/marketing/.venv/bin/python -m app.worker
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

(salin + ubah `ExecStart` untuk scheduler/uvicorn/streamlit; `systemctl daemon-reload && systemctl enable --now marketing-worker`).
