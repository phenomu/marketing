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

Tiga adapter Google + tiga importer file, dipilih via env `LEAD_SOURCE`:

| Source | Mode | Kebutuhan | Status |
|---|---|---|---|
| `gmaps_scrape` (default) | free — hasil Google Maps via endpoint internal `tbm=map` (JSON) | tanpa key | terverifikasi live (nama, telepon, website, rating, kategori, alamat, koordinat) |
| `google_places` | paid — Google Places API (New) resmi | `GOOGLE_PLACES_API_KEY` | implementasi + mock test selesai; live test menunggu key |
| `serpapi` | paid — SerpAPI engine Google Maps | `SERPAPI_KEY` (free tier 250 pencarian/bln) | implementasi + mock test selesai; live test menunggu key |
| `csv_import` | file | `CSV_IMPORT_PATH` | terverifikasi (12 test) |
| `json_import` | file | `JSON_IMPORT_PATH` | terverifikasi (list & wrapper) |
| `xlsx_import` | file | `XLSX_IMPORT_PATH` | terverifikasi (openpyxl) |

Importer membaca header EN/ID otomatis (name/nama, telepon/phone, situs/website, kategori, ulasan).

```python
from scrapers import get_adapter
result = get_adapter().search("kedai kopi", location="Yogyakarta", max_results=20)
for b in result.businesses:
    print(b.name, b.phone, b.website, b.rating)
```

Atau via CLI (tanpa masuk Python):

```bash
.venv/bin/python -m scrapers.run "kedai kopi" --location Yogyakarta --max 10
.venv/bin/python -m scrapers.run "laundry" --source serpapi --location Bandung --max 10
.venv/bin/python -m scrapers.run "x" --source csv_import --path data/leads_lama.csv
.venv/bin/python -m scrapers.run "klinik" --source gmaps_scrape --location Jakarta --out data/leads.csv
```

`--out` menyimpan hasil ke CSV (kolom: nama, alamat, telepon, website, kategori, rating, jumlah review, place_id, koordinat). Exit code: 0 sukses, 1 error adapter (termasuk belum terkonfigurasi), 2 nama source salah.

Catatan kepatuhan: `gmaps_scrape` memakai endpoint tidak resmi — risiko ToS Google; tidak ada bypass CAPTCHA/anti-bot, hanya GET dengan delay antar-halaman. Pindah ke `google_places` (satu env var) kalau butuh kepatuhan penuh/stabilitas.

### Website crawling (PHASE 3)

Antrian crawl dibangun otomatis dari domain bisnis hasil discovery (profil platform seperti Facebook/WhatsApp/linktree dilewati — bukan situs bisnis yang bisa ditambang kontaknya). Tiap job: robots.txt dihormati (4xx/5xx/network gagal = allow + log), delay antar-request ke domain sama (`CRAWL_DELAY_S`, default 5s), max halaman per domain (`CRAWL_MAX_PAGES`, default 10), retry + backoff untuk network error/429/5xx, timeout + body cap 2MB. Halaman kontak/about diprioritaskan via kata kunci EN+ID (kontak/contact/hubungi/tentang/about...). Hasil tersimpan di `crawl_jobs` + `crawl_pages` (teks halaman disimpan utuh untuk ekstraksi email fase berikutnya; mailto yang ketemu langsung dihitung).

Verifikasi live: blancocoffee.id 10 halaman (halaman `/contact` ditemukan + email ada di teks tersimpan), avadental.co.id 10 halaman, audydental.com ditolak robots.txt (sesuai aturan).

Test manual:

```bash
.venv/bin/python -m app.crawl_cli --domain example.com   # crawl 1 domain
.venv/bin/python -m app.crawl_cli --limit 3              # jalankan 3 job dari queue
.venv/bin/python -m app.crawl_cli --list                 # status job
.venv/bin/python -m app.crawl_cli --pages 4              # halaman hasil job #4
```

### Industry filtering (config-driven)

`config/industries.yaml` — daftar keyword include/exclude (EN+ID). Bisnis yang match ditandai `industry_match=true` di DB (tidak ada data yang dibuang; filter dipakai saat export/lead management). Edit file kapan saja — scheduler membaca ulang tiap tick, tanpa restart.

### Lead management & validation (PHASE 5)

Email hasil ekstraksi divalidasi 3 lapis sebelum dipakai: syntax (regex + filter sampah), domain (DNS resolve, lewat SSRF guard), dan MX (lookup record + **connect ke mail server tanpa mengirim apa pun** — hanya EHLO/QUIT). Mail server yang menolak/di-timeout dianggap `unknown`, bukan `invalid` — jaringan lokal yang memblokir port 25 tidak akan menandai email valid sebagai mati.

Dari kontak tervalidasi, sistem membangun **leads**: satu baris per bisnis berisi kontak terbaik + skor 0-100 (email valid 40/unknown 25, telepon 20, sosmed 5, alamat 10, website 15, kesegaran data 10/5 — rincian per lead tersimpan agar bisa diaudit). Export CSV siap pakai:

```bash
python -m app.export                       # semua leads → data/leads.csv
python -m app.export --min-score 60        # hanya lead bagus
python -m app.export --email-status valid  # hanya email tervalidasi
```

### Outreach engine (PHASE 6)

Campaign email dengan **DRY RUN sebagai mode default** — tanpa `DRY_RUN=false` + kredensial SMTP lengkap + `OUTREACH_SEND_LIVE=true` (tiga syarat sekaligus), tidak ada email yang benar-benar keluar. Semua "kirim" dicatat sebagai event `sent-dry`:

```bash
python -m app.outreach_cli campaign-create --name q1 --subject "..." --body-file body.txt
python -m app.outreach_cli campaign-run --id 1        # dry-run batch
python -m app.outreach_cli campaign-start --id 1      # worker kirim tiap tick (dry)
python -m app.outreach_cli preview --id 1 --lead 3    # lihat email hasil render
```

Fitur kepatuhan bawaan: personalisasi dari data bisnis (nama/kategori/lokasi), header `List-Unsubscribe` (RFC 8058 one-click) di tiap email, link unsubscribe publik (`/unsubscribe?token=...` — HMAC, berlaku selamanya), suppression list, deteksi hard-bounce via import CSV, duplicate-send prevention per campaign, dan limit harian global (`OUTREACH_SEND_PER_DAY`). Follow-up otomatis per `followup_days` campaign.

### Dashboard (PHASE 7)

Streamlit multi-page di `http://127.0.0.1:8501` (atau `python -m streamlit run dashboard/main.py`):

- **Overview** — metrik bisnis/kontak/lead/suppression + status crawl, campaign, dan event outreach.
- **Lead Discovery** — antrian job discovery & crawl + form enqueue job baru.
- **Lead Management** — filter skor/status + tabel + download CSV.
- **Lead Detail** — bisnis, breakdown skor, kontak, riwayat outreach per lead.
- **Campaigns** — start/pause/done, kirim 1 batch (dry), riwayat event, buat campaign baru.
- **Email Preview** — render email persis seperti yang dikirim.
- **Analytics** — distribusi skor, kontak per jenis, outreach per hari.
- **Export** — CSV lead (byte-identical dengan `python -m app.export`).

Dashboard membaca DB langsung via layer store yang sama dengan worker — tidak ada endpoint API data baru. Aksi tulis memakai fungsi yang sama dengan CLI/worker (DRY RUN dan safety rail PHASE 6 tetap berlaku).

### Contact extraction (PHASE 4)

Setiap crawl selesai, worker otomatis menambang kontak dari teks halaman tersimpan: email (mailto + teks + bentuk obfuscated `nama (at) domain (dot) com`), nomor telepon Indonesia (08xx/+62 dinormalisasi ke +62…, termasuk link wa.me), profil sosmed (Instagram/Facebook/TikTok/LinkedIn/YouTube/X), dan alamat jalan (`Jl./Jalan/…`). Kontak disimpan di tabel `contacts` dengan dedup per bisnis, sumber URL, dan skor confidence (halaman kontak > about > home; mailto > link > teks).

Hasil live (10 domain Yogyakarta/Bandung): 87 kontak — 7 email, 24 telepon, 56 alamat; contoh email confidence 80: `inquiry@blancocoffee.id`, `hello@klinikperigigi.com`.

Validasi deliverability email (syntax/domain/MX) dan lead scoring = fase berikutnya.

### Business discovery (PHASE 2)

Pipeline otomatis berjalan di service worker + scheduler:

1. `config/keywords.yaml` — daftar keyword × lokasi (+ override per source)
2. Scheduler tiap `SCHEDULER_INTERVAL_S` (default 60s) men-enqueue job pencarian yang belum pernah dijalankan (idempoten; job gagal auto-retry tick berikutnya)
3. Worker tiap `WORKER_INTERVAL_S` (default 30s) menjalankan job: search via adapter → simpan ke tabel `businesses` (dedup by place_id / nama+alamat; website dinormalisasi + domain diindeks)

Contoh plan:

```yaml
queries: [kedai kopi, klinik gigi]
locations: [Yogyakarta, Bandung]
max_results: 20
# sources:
#   gmaps_scrape: false          # matikan source default
#   serpapi: {queries: [laundry], locations: [Jakarta]}
```

Hasil live test: 2 keyword × 2 kota → 80 bisnis tersimpan di PostgreSQL, 64 dengan domain unik (antrian crawling website fase berikutnya). Email tidak berasal dari sumber Google — didapat dengan crawling website tiap bisnis (fase crawling + ekstraksi kontak).

## 3. Arsitektur

```
marketing/
├── app/
│   ├── main.py             # FastAPI: / /health /ready
│   ├── worker.py           # crawler worker loop (scaffold)
│   ├── scheduler.py        # background scheduler loop (scaffold)
│   ├── db.py               # SQLAlchemy engine + schema
│   └── heartbeat.py        # liveness file utk service non-HTTP
├── scrapers/               # PHASE 1: source adapters + importers
│   ├── base.py             # Business, SearchResult, SourceAdapter ABC
│   ├── registry.py         # LEAD_SOURCE resolver (6 source)
│   ├── gmaps_scrape.py     # free: Google Maps tbm=map JSON
│   ├── google_places.py    # paid: Places API (New)
│   ├── serpapi.py          # paid: SerpAPI google_maps engine
│   └── file_import.py      # CSV / JSON / XLSX importer
├── config/
│   ├── settings.py         # env-only settings (single source of truth)
│   └── logging_setup.py    # stdout + rotating file
├── dashboard/main.py        # Streamlit status page
├── scripts/                # sanity.py, init_db.py, heartbeat_check.py
├── tests/                  # 236 test (unit + integration hermetic)
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
python scripts/health_monitor.py               # monitor semua service (exit 0/1, --json)
python scripts/backup_db.py backup             # backup DB (restore/verify ada juga)
python -m streamlit run dashboard/main.py       # dashboard native
docker compose --profile dashboard up -d       # dashboard container → 127.0.0.1:8501
```

Endpoint API: `/` (info), `/health` (liveness), `/ready` (readiness — 503 kalau DB down), `/unsubscribe` (RFC 8058, publik by design), `/docs` (Swagger, dev only). Saat `API_AUTH_TOKEN` di-set, semua endpoint lain butuh header `X-Auth-Token` (atau `Bearer`); dashboard butuh `?token=…` sekali di awal.

## 8b. Production (PHASE 9)

- Deployment lengkap (server, reverse proxy + TLS, cron, update, rollback): `docs/DEPLOYMENT.md`
- Review kepatuhan outreach (unsubscribe, suppression, header, rate): `docs/COMPLIANCE.md`
- Checklist gate rilis: `docs/RELEASE_CHECKLIST.md`
- Template env produksi: `.env.prod.example`
- Backup/restore: `python scripts/backup_db.py backup|verify|restore` — restore wajib `--confirm-my-data`, single-transaction
- Monitoring: `python scripts/health_monitor.py` — 7 cek (api, ready, dashboard, db, heartbeat worker/scheduler, disk), exit 1 = alert

## 9. Kepatuhan & Penggunaan yang Bertanggung Jawab

- Crawler identitas jelas (User-Agent bot), robots.txt dihormati, delay antar-request, max halaman per domain, body cap.
- SSRF guard: semua request crawler wajib resolve ke IP publik — alamat internal (cloud metadata, private network) ditolak sebelum connect, termasuk di tiap hop redirect.
- DRY RUN default untuk semua pengiriman email; identitas pengirim jelas; unsubscribe dihormati (fase outreach).
- Data dipakai hanya untuk keperluan riset lead yang sah; jangan bypass anti-bot/CAPTCHA; hormati ToS penyedia data.

- Data source: patuhi ToS layanan dan robots.txt; jangan bypass CAPTCHA/anti-bot.
- Email: identitas pengirim jelas, subjek tidak menyesatkan, wajib unsubscribe + suppression list; DRY_RUN default, kirim nyata hanya dengan otorisasi eksplisit.
- Regulasi relevan: UU ITE, UU PDP (Indonesia); GDPR (target Eropa).

## 10. Development

- Test: `python -m pytest tests/ -q` (conftest auto-SQLite; set `DATABASE_URL` untuk test ke PG).
- Docker compatibility wajib dijaga: semua service harus tetap bisa jalan native; satu image untuk semua service Python.
- Bahasa dokumentasi: Indonesia; kode/identifier: Inggris.

## 11. Hasil Test Nyata (2026-11-03)

| Eksekusi | Hasil |
|---|---|
| Full suite native (venv 3.14, SQLite hermetic) | 236 passed |
| Full suite dalam container (PG nyata, network compose) | 236 passed |
| Integration e2e (PHASE 8) | pipeline discovery→crawl→extract→validate→leads→campaign→unsubscribe, 43 test |
| Live crawl retry pass | 8 failed + 2 stale requeue → 21 done, +14 kontak, leads 15→17 |
| Full Docker: 5 service | api/worker/scheduler/dashboard/db semua (healthy) |
| Native uvicorn/worker/scheduler/streamlit | semua endpoint health 200 |

### Hardening hasil QA (PHASE 8)

- Field bisnis hasil scrape di-HTML-escape saat render body email (anti phishing/link injection).
- CSV export menetralkan formula injection (`=`, `+`, `-`, `@` di awal field → quote-prefix).
- Validasi email per-row guard: satu baris crash tidak lagi membunuh batch worker.
- Endpoint unsubscribe mengembalikan 503 (bukan 500) saat DB down.
- Crawl retry: `reset_failed_crawls` (dipakai via kode/worker) me-requeue job failed + stale.

## 12. Lisensi

Belum ditentukan.
