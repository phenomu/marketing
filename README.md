# MARKETING

Lead-generation + email outreach toolkit. Scrape business contacts dari Google (Maps/Search) dan sumber lainnya, ekstrak email, lalu kirim email promosi.

## Arsitektur (Rencana)

```
marketing/
├── README.md
├── requirements.txt        # dependensi Python
├── config/                 # konfigurasi (keywords, target, SMTP)
├── scrapers/
│   ├── google_maps.py      # scraper Google Maps (nama, alamat, website, telepon)
│   ├── google_search.py    # scraper Google Search (bisa via SerpAPI / dork)
│   └── generic.py          # scraper website umum (kontak page, footer)
├── extractors/
│   ├── email_extractor.py  # regex + validasi email dari HTML/teks
│   └── enrich.py           # tambah data: LinkedIn, sosmed, dsb (opsional)
├── outreach/
│   ├── templates/          # template email promosi (plain text / HTML)
│   ├── mailer.py           # kirim email via SMTP (batch, delay acak)
│   └── followup.py         # sekuens follow-up otomatis
├── data/
│   ├── raw/                # hasil scrape mentah (JSON/CSV)
│   ├── leads.csv           # database leads: company, email, status
│   └── sent.log            # log email terkirim (hindari dobel kirim)
├── scripts/
│   └── dedupe.py           # bersihkan duplikat + validasi email
└── tests/
```

## Alur Kerja

1. **Scrape** — kumpulkan daftar bisnis/website target dari Google Maps/Search atau direktori lain. Input: keyword + lokasi (mis. `"kedai kopi" "Jakarta"`).
2. **Ekstrak** — kunjungi tiap website, cari email di halaman kontak/about/footer (regex `[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}`).
3. **Bersihkan** — dedupe, buang role-based email jika perlu (`noreply@`, `postmaster@`), validasi MX record.
4. **Outreach** — kirim email promosi pakai SMTP, personalisasi (nama bisnis, kota), jeda acak antar-kirim supaya tidak kena spam-flag.
5. **Follow-up** — 2-3 follow-up terjadwal untuk yang belum balas.

## Status

- [ ] requirements.txt + scaffolding modul
- [ ] Scraper Google Maps
- [ ] Scraper Google Search
- [ ] Ekstraktor email
- [ ] Validasi + dedupe leads
- [ ] Mailer SMTP + template
- [ ] Follow-up otomatis
- [ ] Log & reporting

## Catatan Legal

- Kirim email promosi wajib patuhi peraturan: identitas pengirim jelas, subjek tidak menyesatkan, sediakan opsi berhenti berlangganan (unsubscribe). (Indonesia: UU ITE & PERPU / UU PDP; kalau target Eropa: GDPR.)
- Jangan scrape berlebihan — beri delay antar-request, hormati robots.txt dan ToS layanan.
- Gunakan domain + SMTP khusus outreach untuk melindungi reputasi domain utama.
