# MARKETING — Compliance Review (PHASE 9)

Review kepatuhan outreach email. Status per mekanisme — semua diverifikasi
dengan test + live run (lihat TRACKER T-037/T-038/T-043).

## Ringkasan status

| Area | Mekanisme | Status | Bukti |
|---|---|---|---|
| Consent/opt-out | Unsubscribe satu-klik RFC 8058 + landing GET/POST | ✅ aktif | test + live (T-038) |
| Suppression | Pre-send check + permanent list | ✅ aktif | live: campaign skip suppressed (T-038) |
| Identitas pengirim | SMTP_FROM/SENDER_NAME jelas, tanpa spoofing | ✅ aktif | render template |
| Header wajib | List-Unsubscribe + List-Unsubscribe-Post | ✅ aktif | test render_message |
| Stop pengiriman paksa | DRY_RUN + OUTREACH_SEND_LIVE + SMTP creds (triple) | ✅ aktif | D-036 |
| Rate control | Cap harian 50 + batch 10/tick + delay | ✅ aktif | D-038 |
| Duplikat | UNIQUE(campaign, lead, event_type) + runtime check | ✅ aktif | live dedup (T-037) |
| Konten jujur | Subjek template milik operator; tidak ada klaim palsu default | ✅ aktif | review template |
| Data privacy | Kontak hanya dari website publik bisnis; bisa dihapus | ✅ desain | delete = hapus row DB |
| Keamanan data | Bind 127.0.0.1, auth layer opsional, secret via env | ✅ aktif | PHASE 9 auth |

## 1. Opt-out (paling kritikal)

**Satu klik, langsung, permanen.** Link unsubscribe di SETIAP email:
- Token HMAC stateless `b64url(email) + sig16` — tak bisa dipalsukan tanpa `UNSUBSCRIBE_SECRET`.
- GET (klik browser) dan POST (RFC 8058 one-click di Gmail/Outlook) keduanya jalan.
- Tanpa expiry — link berlaku selamanya (unsubscribe yang kedaluwarsa = pelanggaran).
- Token diverifikasi ulang di setiap klik; email yang sudah suppress tidak bisa di-unsupscribe via link lain.
- Endpoint publik by design (D-037/D-039) — tidak dimungkinkan auth menghalangi penerima menolak email.

**Verifikasi manual:** klik link unsubscribe di email preview → cek halaman Campaigns → alamat masuk suppression; kirim ulang → `skipped_suppressed` di stats campaign.

## 2. Suppression list

- Dicek SEBELUM render + send di campaign runner dan follow-up.
- Entry: unsubscribed (via link), bounced (SMTP reject), complained (manual).
- Tidak ada UI untuk menghapus suppression — sengaja. (Hapus manual via DB = keputusan operator, dicatat di log.)
- Follow-up hari N tetap mengecek suppression saat pengiriman — bukan saat enqueue.

## 3. Identitas & header

- `From` = `SMTP_FROM` (domain milik operator — wajib di-set sebelum live).
- `List-Unsubscribe: <mailto:...>, <https://...>` dan `List-Unsubscribe-Post: List-Unsubscribe=One-Click` otomatis di setiap email.
- Template default jujur: subjek "Kerja sama untuk {name}?" — tanpa urgency palsu/deceptive subject line.

## 4. Rate & reputasi

- Hard cap: `OUTREACH_SEND_PER_DAY` (default 50, dry-run ikut dihitung — rehearsal = produksi).
- Provider SMTP punya limit sendiri (Brevo free 300/hari) — jangan naikkan di atas provider.
- Domain warm-up: mulai <20/hari minggu pertama. SPF/DKIM/DMARC = tanggung jawab domain operator (set di DNS provider) — di luar scope aplikasi tapi WAJIB sebelum live.

## 5. Sumber data

- Kontak hanya dari website bisnis publik (crawl taat robots.txt, UA jujur `marketing-research-bot/0.1`, delay antar request).
- Tidak scrape personal social media content; hanya email/telepon bisnis yang dipublikasikan sendiri.
- robots.txt disallow → domain tidak dicrawl (verified live: audydental robots-block).
- Hapus data (GDPR-style erasure): hapus row `businesses`/`contacts`/`leads`/`suppressions` — tidak ada downstream cache.

## 6. Yang HARUS dilakukan operator sebelum live send

1. Set SPF/DKIM/DMARC di DNS domain pengirim.
2. Daftar SMTP provider + verifikasi domain (bukan cuma email).
3. Isi `.env`: `SMTP_HOST/PORT/USER/PASS/FROM`, `SENDER_NAME`, `UNSUBSCRIBE_SECRET`, `UNSUBSCRIBE_BASE_URL` (publik — penerima harus bisa buka link).
4. Tes ke inbox sendiri: unsubscribe link jalan, email sampai inbox (bukan spam).
5. Baru arm triple-switch (D-036) — dan mulai dari volume kecil.

## 7. Batasan compliance yang diketahui

- Bounce/complaint feedback loop (FBL) provider belum ter-automate — bounce SMTP real-time tercatat, tapi complaint dari FBL provider (spam-report) harus di-suppress manual.
- Tidak ada double opt-in — ini outreach B2B cold email (bukan newsletter); jurisdiction tertentu (EU GDPR lebih ketat) = review hukum lokal sebelum kirim.
- Log event menyimpan email penerima (perlu untuk bukti opt-out) — retensi log = kebijakan operator.
