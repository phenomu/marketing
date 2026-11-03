# MARKETING — Final Release Checklist (PHASE 9)

Checklist gate rilis. Semua item harus ✅ sebelum go-live.
Status kolom "Otomatis" = sudah terverifikasi test/verifikasi live; "Manual" = operator harus jalankan/dokumentasikan sendiri.

## A. Kode & Test

- [x] Full test suite pass — native 276/276 (Otomatis, T-050..T-052)
- [x] Full test suite pass — container PG real (Otomatis)
- [x] 8 fase TRACKER COMPLETE: pipeline discovery→crawl→extract→validate→lead→outreach→dashboard→QA (Otomatis)
- [x] Security audit bersih: SQLi/LFI/path-traversal/RCE/unauth — SSRF fixed D-031; HTML injection fixed D-040; CSV formula injection fixed D-041 (Otomatis, T-033/T-043)
- [x] Never-raise contract semua service loop (D-019/D-042) (Otomatis)
- [x] Auth layer test 14/14 — off by default, public paths /health /ready /unsubscribe (Otomatis)
- [ ] Smoke live manual di server target post-deploy (Manual)

## B. Konfigurasi Produksi

- [x] `.env.prod.example` template lengkap + generator secret didokumentasikan (Otomatis)
- [x] APP_ENV=production → docs/OpenAPI off (D-032) (Otomatis, test)
- [x] docker-compose.prod.yml: named volumes, no db host port, restart always, mem limit (Otomatis, `config --quiet` merge valid)
- [ ] `.env` server terisi: POSTGRES_PASSWORD kuat (Manual)
- [ ] API_AUTH_TOKEN diset (wajib saat port > localhost) (Manual)
- [ ] UNSUBSCRIBE_SECRET diset + dicatat offline (link lama bergantung padanya) (Manual)
- [ ] UNSUBSCRIBE_BASE_URL = URL publik reachable penerima (Manual)

## C. Infrastruktur

- [x] Deploy guide lengkap: prasyarat, first deploy, reverse proxy, update, rollback, hybrid, systemd (Otomatis — docs/DEPLOYMENT.md)
- [x] Monitoring script 7 check + cron template (Otomatis — scripts/health_monitor.py)
- [x] Backup/restore/verify script + cron template + off-site (Otomatis — scripts/backup_db.py)
- [ ] Reverse proxy + TLS di server (Caddy/nginx) (Manual)
- [ ] Firewall: hanya 22/80/443 (Manual)
- [ ] DNS A record api + dashboard (Manual)

## D. Data & Recovery

- [x] Backup round-trip verified live: 100 bisnis/182 kontak/20 leads identik restore (Otomatis — T-051)
- [x] Restore single-transaction (gagal = rollback penuh) (Otomatis)
- [x] Rotasi backup keep-N (Otomatis)
- [ ] Cron backup aktif di server + first backup manual (Manual)
- [ ] Off-site sync (rclone/rsync) aktif (Manual)
- [ ] Test restore pernah dijalankan di server (Manual — sekali sebelum go-live)

## E. Kepatuhan (detail docs/COMPLIANCE.md)

- [x] Unsubscribe satu-klik RFC 8058 GET+POST aktif (Otomatis, T-038)
- [x] Suppression pre-send + permanen (Otomatis, T-038)
- [x] List-Unsubscribe header otomatis tiap email (Otomatis)
- [x] Dedup 2 lapis + daily cap 50 (Otomatis, D-038)
- [x] Live sending triple-armed default OFF (Otomatis, D-036)
- [ ] SPF/DKIM/DMARC domain pengirim (Manual — DNS operator)
- [ ] Domain verified di SMTP provider (Manual)
- [ ] Tes inbox sendiri: email sampai + unsubscribe jalan (Manual)

## F. Go-Live Sending (opsional — hanya kalau mau kirim nyata)

- [ ] SMTP creds lengkap di .env (Manual)
- [ ] DRY_RUN=false (Manual)
- [ ] OUTREACH_SEND_LIVE=true (Manual)
- [ ] Campaign draft → review subjek/body di Email Preview (Manual)
- [ ] Volume ramp: minggu 1 < 20 email/hari (Manual)
- [ ] Monitor bounce rate < 3%, complaint < 0.1% (Manual — dashboard Analytics)

## Sign-off

| Gate | Status | Tanggal | Bukti |
|---|---|---|---|
| Fase 1-8 complete | ✅ | 2026-11-03 | TRACKER T-001..T-048 |
| UI NEON COMMAND 3 pass | ✅ | 2026-11-03 | commit a2b143c, 0ddeb5a, ffe2d71 |
| PHASE 9 build | ✅ | 2026-11-03 | TRACKER T-051..T-053 |
| Deploy server | ⬜ | — | operator (docs/DEPLOYMENT.md) |
| Live sending | ⬜ | — | operator (docs/COMPLIANCE.md §6, checklist F) |
