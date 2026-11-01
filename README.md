# MARKETING

Lead generation + email outreach toolkit. Kumpulkan data bisnis dari berbagai sumber, cari email kontak dari website mereka, validasi, lalu kelola campaign email (mode dry-run secara default).

**Status: tahap awal — belum ada aplikasi yang bisa dijalankan. Bagian di bawah menggambarkan rencana arsitektur dan fitur target, bukan fitur yang sudah jadi.**

## 1. Gambaran Proyek

- **Masalah yang dipecahkan**: mencari calon pelanggan (lead) secara manual itu lambat — proyek ini mengotomatiskan rantai: temukan bisnis → cari kontak → validasi → outreach.
- **Tujuan utama**: pipeline data terverifikasi (bisnis + email valid) untuk keperluan promosi.
- **Kemampuan target**: business discovery multi-sumber, crawling website untuk kontak, ekstraksi + validasi email, pengelolaan lead, campaign email dengan dry-run.

## 2. Fitur

Sudah diimplementasikan: tidak ada — repo saat ini berisi scaffolding + dokumentasi tata kelola.

Direncanakan:

- Business discovery (keyword/lokasi, multi sumber)
- Crawling website (kontak, about, footer)
- Ekstraksi email/telepon/sosmed
- Validasi email (sintaks, domain, MX)
- Lead management + scoring + export CSV
- Campaign email: template, personalisasi, dry-run, unsubscribe, suppression list
- Reporting/analytics

## 3. Arsitektur

```
marketing/
├── AGENTS.md               # aturan operasi agent
├── README.md
├── requirements.txt
├── config/                 # settings loader, keywords, logging
├── scrapers/               # adapter sumber data (Maps/search/direktori)
├── extractors/             # ekstraksi kontak dari HTML
├── outreach/               # mailer SMTP, template, follow-up
├── data/                   # output mentah + leads (TIDAK di-commit)
├── scripts/                # entrypoint CLI
└── tests/
```

Alur data: source adapter → business discovery → crawler → contact extraction → validation → lead store → outreach engine (dry-run default) → reporting.

Database: SQLite untuk development, PostgreSQL direncanakan untuk produksi (belum diimplementasikan).

## 4. Sumber Data yang Direncanakan

| Sumber | Peruntungan | Status |
|---|---|---|
| Google Places API | Discovery bisnis per lokasi | Belum |
| Search API resmi (mis. SerpAPI) | Discovery website bisnis | Belum |
| Direktori bisnis (dengan izin) | Data tambahan | Belum |
| Open data | Data publik | Belum |
| Import CSV/JSON/XLSX | Data milik sendiri | Belum |

## 5. Teknologi

Python 3, `requests`, `beautifulsoup4`, `lxml`, `pyyaml` (lihat `requirements.txt`). Belum ada dependency lain yang terintegrasi.

## 6. Instalasi

Belum bisa dijalankan sebagai aplikasi. Setup saat ini:

```bash
git clone git@github.com:phenomu/marketing.git
cd marketing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Bagian usage akan diisi setelah modul pertama ada.

## 7. Konfigurasi

Variabel environment yang direncanakan (tanpa nilai rahasia di repo): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASS`, `SENDER_NAME`. File `.env` tidak di-commit; contoh nanti di `.env.example`.

## 8. Penggunaan

Belum ada perintah yang bisa dijalankan.

## 9. Kepatuhan & Penggunaan yang Bertanggung Jawab

- Data source: patuhi ToS layanan dan robots.txt; jangan bypass CAPTCHA/anti-bot.
- Email: identitas pengirim jelas, subjek tidak menyesatkan, wajib ada mekanisme unsubscribe dan suppression list; rate limit pengiriman.
- Regulasi yang relevan untuk target Indonesia: UU ITE, UU PDP; target Eropa: GDPR.
- Kirim nyata hanya dengan otorisasi eksplisit; mode DRY RUN adalah default.

## 10. Development

Aturan kerja untuk agent/manusia kontributor ada di `AGENTS.md`. Test dijalankan dari `tests/` (belum ada). Bahasa dokumentasi: Indonesia; kode dan identifier: Inggris.

## 11. Lisensi

Belum ditentukan.
