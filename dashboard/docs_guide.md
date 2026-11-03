# Panduan Penggunaan MARKETING

Panduan cara pakai semua fitur aplikasi — ditulis untuk operator, bukan developer.

## 1. Memulai

Dashboard berjalan di `http://127.0.0.1:8501`, API di `http://127.0.0.1:8000`. Semua service hanya bind ke localhost — akses dari perangkat lain butuh port-forward.

**Navigasi:** sidebar kiri. Logo di atas, daftar halaman di tengah (klik di mana saja pada baris — bukan hanya teksnya), status sistem di bawah.

**Status sistem di sidebar selalu real:**

| Baris | Arti |
|---|---|
| `env` | environment aktif (`development` / `production`) |
| `dry_run` | `True` = semua email SIMULASI, tidak pernah terkirim |
| `send_live` | `False` = live send dimatikan di level worker |
| `bind` | alamat bind — `127.0.0.1` artinya hanya lokal |

Halaman terdiri dari: **Overview** (ringkasan pipeline), **Lead Discovery** (antrian job), **Lead Management** (tabel lead), **Lead Detail** (satu lead), **Campaigns** (email campaign), **Email Preview** (editor template), **Analytics** (grafik), **Export** (unduh CSV), **Dokumentasi** (halaman ini).

Semua angka di dashboard berasal dari database live — tidak ada angka yang dibuat-buat.

## 2. Lead Discovery — Menambah Prospek

Discovery = mencari bisnis baru dari sumber (Google Maps scraping / SerpAPI / import CSV-JSON-XLSX).

**Cara menambah job:**

1. Buka halaman **Lead Discovery** → tab **Tambah job**
2. Isi query (contoh: `kopi jakarta`), lokasi, pilih source
3. Klik **Enqueue job** — job masuk antrian `pending`
4. Worker memproses otomatis tiap tick (±30 detik, 5 job per tick)

**Yang terjadi setelah job jalan:** bisnis ditemukan → disimpan ke database → domain bisnis otomatis di-enqueue jadi job crawl.

Tab **Discovery jobs** menampilkan semua job + statusnya (`pending` / `done` / `failed`). Tab **Crawl jobs** menampilkan crawling website per domain.

> Job `failed` biasanya domain mati nyata (DNS gagal / SSL / robots.txt melarang). Tekan tombol retry via CLI — lihat bagian Operasi.

## 3. Crawl & Ekstraksi Kontak

Worker otomatis mengunjungi website tiap bisnis (taat robots.txt, jeda antar request, maksimal halaman per domain) lalu mengekstrak kontak: email, telepon, alamat.

- **Bisnis** = data perusahaan hasil discovery
- **Kontak** = email/phone/address yang ditemukan di website-nya (satu bisnis bisa punya banyak kontak)
- **Lead** = satu baris kesimpulan per bisnis: skor + email terbaik + status

Email divalidasi via MX lookup. Status `unknown` berarti server email tidak bisa diverifikasi dari jaringan lokal (ISP blok port 25) — normal di dev, di VPS jadi `valid`/`invalid`.

**Skor (0-100)** transparan — breakdown lengkapnya ada di halaman **Lead Detail**:

| Komponen | Bobot |
|---|---|
| Punya email valid | besar |
| Punya website aktif | sedang |
| Kelengkapan kontak (phone/address) | kecil |
| Kesesuaian kategori | kecil |

## 4. Lead Management — Filter & Cari Lead

1. Buka **Filter** (expanded default): skor minimum, status email, status lead
2. Tabel update otomatis — maksimum 500 baris per view
3. Klik **⬇ Download CSV** untuk unduh hasil filter saat ini

Status lead: `new` (belum dikontak), `contacted` (sudah dikirim email), `suppressed` (berhenti berlangganan / diblokir), `bounced` (email ditolak).

Untuk lihat detail satu lead: pilih di **Lead Detail** (dropdown atas) — skor breakdown, semua kontak, riwayat outreach.

## 5. Campaigns — Mengirim Email

Campaign = template email + aturan siapa yang dikirim.

**Membuat campaign:**

1. **Campaign baru** di bawah halaman Campaigns
2. Isi nama (unik), subjek, body — pakai placeholder (tabel di bawah)
3. Set skor minimum (hanya lead ≥ skor ini yang dikirim) dan follow-up hari
4. Klik **Buat (draft)** — campaign baru status `draft`, TIDAK aktif

**Menjalankan:**

| Tombol | Efek |
|---|---|
| ▶ Start | status → `running`: worker kirim batch kecil tiap tick (maks 50 email/hari) |
| ⏸ Pause | status → `paused`: kirim berhenti, bisa start lagi |
| ⏹ Selesai | status → `done`: campaign berakhir |
| ⚡ Kirim 1 batch | kirim langsung sekali jalan (dry) tanpa menunggu worker |

**Mengubah template campaign aktif:** form **Edit template** — subjek, body, skor minimum, follow-up. Nama/status/id tidak bisa diubah dari sini. Perubahan langsung dipakai worker tick berikutnya; pratinjau perubahan di halaman **Email Preview**.

**Placeholder template:**

| Placeholder | Diganti dengan |
|---|---|
| `{{name}}` | nama bisnis |
| `{{category}}` | kategori bisnis |
| `{{location}}` | lokasi |
| `{{domain}}` | website bisnis |
| `{{sender_name}}` | nama pengirim |
| `{{sender_email}}` | email pengirim |
| `{{unsubscribe_url}}` | link berhenti berlangganan (WAJIB ada di body) |

## 6. Email Preview — Uji Template Sebelum Kirim

Halaman ini merender email **persis seperti yang akan diterima penerima**.

1. Pilih campaign + lead (dropdown atas)
2. Edit subjek/body langsung di form — placeholder terlihat tersubstitusi di hasil render
3. **👁 Render preview** = pratinjau tanpa menyimpan
4. **💾 Simpan ke campaign** = perubahan disimpan permanen ke campaign
5. Panel **Pratinjau HTML** menampilkan body HTML seperti di mail client

Setiap email otomatis dapat header `List-Unsubscribe` + `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058) — penerima bisa berhenti berlangganan satu klik dari Gmail dll.

## 7. Analytics & Export

**Analytics:** distribusi skor lead (bucket 20 poin), kontak per jenis, outreach per hari — semua dari data nyata.

**Export:**

1. Set filter (skor minimum, status email, maks baris)
2. **⬇ Download leads.csv** — UTF-8, Excel-friendly
3. Preview 25 baris pertama di tabel bawah

CSV aman dibuka di Excel/Sheets: karakter formula (`=`, `+`, `-`, `@`) di awal sel otomatis di-prefix `'` agar tidak dieksekusi sebagai formula.

## 8. Mode Aman & Kepatuhan

**Default: DRY RUN.** Email tidak pernah benar-benar terkirim — semua event tercatat `sent-dry`. Tidak ada risiko kirim nyata tanpa sengaja.

Kirim nyata butuh TIGA kondisi sekaligus (satu pun kurang = tetap dry):

1. `DRY_RUN=false` di environment
2. SMTP credentials lengkap (`SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`)
3. `OUTREACH_SEND_LIVE=true` di environment

**Perlindungan penerima yang selalu aktif:**

- Suppression list dicek sebelum kirim — alamat unsubscribed/bounce/complaint tidak pernah dikirim ulang
- Unsubscribe satu-klik (RFC 8058) di setiap email
- Dedup 2 lapis: per campaign + per lead (tidak ada email ganda)
- Cap harian 50 email/UTC-day
- Header pengirim jujur, subjek tidak menipu, identitas jelas

**Uji unsubscribe:** link `Unsubscribe` di email preview → buka di browser → alamat langsung masuk suppression (token ber-HMAC, tidak bisa ditebak).

## 9. CLI & Operasi

Perintah CLI utama (jalan dari root repo, native mode):

| Perintah | Fungsi |
|---|---|
| `python -m app.worker` | jalankan worker pipeline penuh (loop 30s) |
| `python -m app.scheduler` | enqueue discovery + crawl terjadwal (loop 60s) |
| `python -m app.export --min-score 60` | export CSV lead ke stdout |
| `python -m app.outreach_cli preview --id 1 --lead 3` | render email campaign 1 untuk lead 3 |
| `python -m app.outreach_cli campaign-start --id 1` | aktifkan campaign 1 |
| `python -m scrapers.run --source gmaps_scrape ...` | discovery manual |
| `python -m pytest tests/ -q` | test suite penuh |
| `python scripts/sanity.py` | sanity check env + DB |

Retry crawl gagal (massal):

```
python -c "from app.db import get_engine; from app.crawl import reset_failed_crawls; print(reset_failed_crawls(get_engine()))"
```

Docker: `docker compose --profile full up -d` (semua service) atau `docker compose up -d db` (DB saja, app native).

## 10. Troubleshooting

**Angka tidak berubah setelah aksi?** Worker tick 30 detik — tunggu satu tick lalu refresh. Data dashboard dibaca per-render, tidak live-stream.

**Job stuck `pending`?** Pastikan worker jalan: `docker compose ps` → service `worker` harus healthy. Native: cek proses `python -m app.worker`.

**Email semua `unknown`?** Normal di jaringan lokal (ISP blok port 25). Di server/VPS status jadi akurat.

**Campaign jalan tapi tidak ada email terkirim?** Cek: (1) campaign status `running`? (2) ada lead ≥ skor minimum dengan email? (3) sudah kirim 50 hari ini (cap)? (4) `DRY_RUN` — kalau `true`, event = `sent-dry` (ini BUKAN gagal).

**Kontak/lead tidak bertambah setelah crawl?** Cek tab Crawl jobs — job `failed` artinya domain mati atau robots.txt melarang; itu terminal, tidak di-requeue otomatis.

**Dashboard blank / error DB?** Cek `docker compose ps` (db healthy?) atau `curl http://127.0.0.1:8000/health`.
