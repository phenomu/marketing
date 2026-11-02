# MARKETING

Lead generation + email outreach toolkit. Kumpulkan data bisnis dari berbagai sumber, cari email kontak dari website mereka, validasi, lalu kelola campaign email (mode dry-run secara default).

**Status: tahap awal — foundation + Docker-ready selesai (2026-11-01). Sudah jalan & terverifikasi: FastAPI backend (health/readiness), worker + scheduler loop dengan heartbeat, dashboard Streamlit status, PostgreSQL Docker (opsional/hybrid), Docker Compose orchestration, 12 unit test. Modul scraper/ekstraksi email/outreach nyata belum diimplementasi.**

## 1. Gambaran Proyek

- **Masalah**: mencari lead secara manual lambat — proyek ini mengotomatiskan rantai: temukan bisnis → cari kontak → validasi → outreach.
- **Tujuan**: pipeline data terverifikasi (bisnis + email valid) untuk keperluan promosi.
- **Mode eksekusi**: native Python ATAU Docker — kode dan konfigurasi sama persis (env-only).

## 2. Fitur

Sudah diimplementasikan (terverifikasi test nyata):

- Konfigurasi env-only (`config/settings.py`) + loader `.env` (real env > .env file) — shared native/Docker
- FastAPI backend: `/`, `/health` (liveness), `/ready` (readiness, 503 saat DB down)
- Crawler worker + scheduler: loop interval + heartbeat file + graceful shutdown (logic scrape/jadwal nyata menyusul fase berikutnya)
- Dashboard Streamlit: status backend/DB/dry-run
- Database layer SQLAlchemy (PostgreSQL + SQLite fallback test), schema stamping idempotent
- Logging ganda: stdout (container) + rotating file (host `logs/`)
- Docker: satu image untuk semua service Python, compose profiles, healthcheck semua service, volume persisten

Direncanakan (belum ada): business discovery loop (keyword → job → penyimpanan), crawling website, ekstraksi email, validasi MX, lead management + scoring, campaign email, follow-up, reporting lengkap.

### Sumber data (implementasi awal)

Tiga adapter siap pakai, dipilih via env `LEAD_SOURCE`:

| Source | Mode | Kebutuhan | Status |
|---|---|---|---|
| `gmaps_scrape` (default) | free — hasil Google Maps via endpoint internal `tbm=map` (JSON) | tanpa key | terverifikasi live (nama, telepon, website, rating, kategori, alamat, koordinat) |
| `google_places` | paid — Google Places API (New) resmi | `GOOGLE_PLACES_API_KEY` | implementasi selesai; live test menunggu key |
| `serpapi` | paid — SerpAPI engine Google Maps | `SERPAPI_KEY` (free tier 250 pencarian/bln) | implementasi selesai; live test menunggu key |

```python
from scrapers import get_adapter
result = get_adapter().search("kedai kopi", location="Yogyakarta", max_results=20)
for b in result.businesses:
    print(b.name, b.phone, b.website, b.rating)
```

Catatan kepatuhan: `gmaps_scrape` memakai endpoint tidak resmi — risiko ToS Google; tidak ada bypass CAPTCHA/anti-bot, hanya GET dengan delay antar-halaman. Pindah ke `google_places` (satu env var) kalau butuh kepatuhan penuh/stabilitas.

## 3. Arsitektur

```
marketing/
├── app/
│   ├── main.py             # FastAPI: / /health /ready
│   ├── worker.py           # crawler worker loop (scaffold)
│   ├── scheduler.py        # background scheduler loop (scaffold)
│   ├── db.py               # SQLAlchemy engine + schema
│   └── heartbeat.py        # liveness file utk service non-HTTP
├── scrapers/               # PHASE 1: source adapters
│   ├── base.py             # Business, SearchResult, SourceAdapter ABC
│   ├── registry.py         # LEAD_SOURCE resolver
│   ├── gmaps_scrape.py     # free: Google Maps tbm=map JSON
│   ├── google_places.py    # paid: Places API (New)
│   └── serpapi.py          # paid: SerpAPI google_maps engine
├── config/
│   ├── settings.py         # env-only settings (single source of truth)
│   └── logging_setup.py    # stdout + rotating file
├── dashboard/app.py        # Streamlit status page
├── scripts/                # sanity.py, init_db.py, heartbeat_check.py
├── tests/                  # 25 unit test
├── conftest.py
├── Dockerfile              # SATU image utk api/worker/scheduler/dashboard
├── docker-compose.yml      # dev: db default, app via profile
├── docker-compose.prod.yml # prod overrides (named volumes, db tanpa host port)
└── .env.example
```

Alur data (target): source adapter → business discovery → crawler → contact extraction → validation → lead store → outreach (dry-run default) → reporting.

Database: PostgreSQL 17 (Docker, hybrid/produksi), SQLite untuk unit test otomatis.

## 4. Arsitektur Docker (OPSIONAL)

Docker **tidak wajib** untuk development. Tiga mode:

| Mode | Cara | Keterangan |
|---|---|---|
| **Hybrid (default)** | `docker compose up -d db` + app native | PG di container, Python di host (venv) |
| **Full Docker** | `docker compose --profile full up -d` | semua service containerized |
| **Full native** | tanpa Docker | app + SQLite/PG sendiri |

Prinsip: SATU image `marketing-app` dipakai api/worker/scheduler/dashboard (beda command saja — tidak ada container/image ekstra), PostgreSQL image terpisah. Tidak ada Redis/Celery/K8s — queue/task direncanakan via tabel PostgreSQL saat ada kebutuhan nyata.

Service bisa jalan independen: `docker compose --profile api|worker|scheduler|dashboard up -d` (db selalu ikut karena dependency `service_healthy`).

Volume persisten: `pgdata` (named volume, data DB), `./logs` + `./data` (bind mount dev; named volume `applogs`/`appdata` di prod). Container jalan non-root (uid 1000 = user host) supaya file bind mount bukan milik root. Bind port default hanya `127.0.0.1` (tidak expose LAN).

## 5. Teknologi

Python 3.14, FastAPI, SQLAlchemy 2, psycopg 3, uvicorn, Streamlit, requests, beautifulsoup4, lxml, PyYAML. PostgreSQL 17 (container). Docker Compose v2. Lihat `requirements.txt` / `requirements-dev.txt`.

## 6. Instalasi

Prasyarat: Python ≥ 3.12; Docker + Compose v2 hanya kalau pakai mode Docker/hybrid.

### Native penuh (tanpa Docker)

```bash
git clone git@github.com:phenomu/marketing.git
cd marketing
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
cp .env.example .env
python -m pytest tests/ -q
python -m uvicorn app.main:api --reload --port 8000
```

### Hybrid (disarankan): PostgreSQL di Docker, app native

```bash
cp .env.example .env              # set POSTGRES_PASSWORD
docker compose up -d db           # PG 17 di 127.0.0.1:5432
source .venv/bin/activate
python scripts/init_db.py         # buat schema
python scripts/sanity.py          # harus: db check = UP
```

### Full Docker

```bash
cp .env.example .env
docker compose --profile full up -d --build
docker compose --profile full ps  # semua service harus (healthy)
```

### Produksi

```bash
cp .env.example .env.prod         # isi nilai produksi (APP_ENV=production)
docker compose --env-file .env.prod -f docker-compose.yml -f docker-compose.prod.yml \
  -p marketing-prod --profile full up -d --build
```

## 7. Konfigurasi

Semua via environment variable, tidak ada secret hardcode. Daftar lengkap di `.env.example`: `APP_ENV`, `LOG_LEVEL`, `DRY_RUN`, `LOG_DIR`, `POSTGRES_USER/PASSWORD/DB/HOST/PORT`, `DATABASE_URL`, `API_BIND`, `DASHBOARD_BIND`, `BACKEND_URL`, `WORKER_INTERVAL_S`, `SCHEDULER_INTERVAL_S`, `SMTP_*`, `SENDER_NAME`. Variable sama untuk native dan container; compose men-set `POSTGRES_HOST=db` dan `BACKEND_URL=http://api:8000` untuk network internal.

## 8. Penggunaan

```bash
python scripts/sanity.py                       # cek settings + DB (native/container)
python scripts/init_db.py                      # schema init/migrasi
python scripts/heartbeat_check.py worker       # healthcheck manual service non-HTTP
python -m streamlit run dashboard/app.py       # dashboard native
docker compose --profile dashboard up -d       # dashboard container → 127.0.0.1:8501
```

Endpoint API: `/` (info), `/health` (liveness), `/ready` (readiness — 503 kalau DB down), `/docs` (Swagger). Perintah scrape/ekstraksi/outreach menyusul fase implementasinya.

## 9. Kepatuhan & Penggunaan yang Bertanggung Jawab

- Data source: patuhi ToS layanan dan robots.txt; jangan bypass CAPTCHA/anti-bot.
- Email: identitas pengirim jelas, subjek tidak menyesatkan, wajib unsubscribe + suppression list; DRY_RUN default, kirim nyata hanya dengan otorisasi eksplisit.
- Regulasi relevan: UU ITE, UU PDP (Indonesia); GDPR (target Eropa).

## 10. Development

- Test: `python -m pytest tests/ -q` (conftest auto-SQLite; set `DATABASE_URL` untuk test ke PG).
- Docker compatibility wajib dijaga: semua service harus tetap bisa jalan native; satu image untuk semua service Python.
- Bahasa dokumentasi: Indonesia; kode/identifier: Inggris.

## 11. Hasil Test Nyata (2026-11-01)

| Eksekusi | Hasil |
|---|---|
| Unit test native (venv 3.14, SQLite) | 12 passed |
| Unit test dalam container (PG nyata, network compose) | 12 passed |
| Hybrid: sanity native → PG container | db check = UP, schema 0.1 |
| Full Docker: 5 service | api/worker/scheduler/dashboard/db semua (healthy) |
| Volume shared: container worker tulis heartbeat | file `pid:1` muncul di `./logs` host |
| Native uvicorn/worker/scheduler/streamlit | semua endpoint health 200 |

## 12. Lisensi

Belum ditentukan.
