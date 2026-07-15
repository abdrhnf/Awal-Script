# Protokol Test Mindspace — gerbang sebelum riset Weight

Semua verifikasi sisi kode sudah lulus (compile, exec-test live ke server,
grep-audit, mirror sync). Yang belum terbukti: perilaku DI DALAM Glyphs sejak
crash guillemot — resolver nama, overwrite-wipe, dan arsitektur responsif.
Checklist ini sekali jalan ±5 menit dengan font percobaan.

**Pakai font percobaan / copy** (atau siap ⌘Z + jangan save) — test 5 dan 6
mengubah kerning.

## Checklist

1. **Panel** — Opt+klik menu Scripts → Reload Scripts → jalankan **Mindspace**.
   - [ ] Menu hanya ada satu entri Mindspace (Kern/Spacing lama hilang)
   - [ ] Panel muncul, dot server ● hijau "terhubung"
   - [ ] Jalankan lagi dari menu → tidak muncul panel kedua (window sama ke depan)

2. **Kern cepat** — set Pair set = **latin_basic** (±30 detik) → Jalankan Kern.
   - [ ] Tuntas sampai dialog "Done" TANPA error (dulu: crash `guillemotleft`)
   - [ ] Status bawah panel terisi ("Kern: N pair · GLOBAL/PERSONAL · jam")

3. **Responsif + klik ganda** — jalankan Kern lagi (boleh `latin_extended`
   biar kerasa durasinya).
   - [ ] Selama "berjalan…": scroll/zoom/pindah tab di Glyphs tetap lancar
     (tidak beachball)
   - [ ] Tombol run abu-abu selama proses
   - [ ] Klik tombol Kern 2-3× saat berjalan → tetap CUMA satu run
     (tidak ada run kedua setelah selesai)

4. **Resolver tanda baca** — set Pair set = **full** sekali (10-25 menit,
   biarkan jalan sambil kerja lain — Glyphs tetap bisa dipakai).
   - [ ] Dialog Done muncul; kalau ada baris "Dilewati N pair" catat contohnya
   - [ ] Window → Kerning: pair guillemet (« ») / tanda baca ikut ter-apply

5. **Spacing** — Jalankan Spacing sekali (glyph set bebas).
   - [ ] Tuntas sampai dialog Done, proof tab rhythm terbuka

6. **Overwrite & pembatalan** (opsional, paling berharga di master percobaan):
   - [ ] Centang ⚠ Timpa SEMUA → Jalankan Kern → tabel kern = persis output
     baru; checkbox otomatis tidak tercentang lagi setelah run
   - [ ] Mulai run lalu TUTUP font-nya di tengah → dialog "Dibatalkan
     (font ditutup)" muncul tenang, Glyphs tidak crash

## Sesudahnya

- **Semua lolos** → lapor "aman" → `_archive/` (script lama) dihapus,
  Mindspace resmi stabil → mulai riset tools Weight.
- **Ada yang gagal** → kirim persis: teks error / isi Macro Window
  (Window → Macro Panel) + langkah nomor berapa. Diperbaiki dulu sebelum
  lanjut ke mana-mana.
