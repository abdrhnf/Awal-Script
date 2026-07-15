# Protokol Test Mindweight — di GlyphsApp

Semua verifikasi otomatis LULUS: v2 global tetap ada sebagai fallback, v3
glyph-level sudah trained dari corpus (Thin 24.462 row, Black 41.045 row) dan
smoke test mengalahkan global baseline di Fira/SourceSans/IBMPlex. v4 memakai
**Cape-style apply engine** di client: unslant/reslant italic, restore tinggi,
sidebearing kiri, anchors/guides, dan rollback per glyph kalau filter gagal.
Yang tersisa: perilaku di dalam Glyphs — hasil visual engine baru, risk
marking, pembuatan master, self-check.

**Pakai font percobaan / copy** — test ini menambah master (dan mungkin
instance) ke file. Rollback: hapus master di Font Info → Masters / ⌘Z /
tutup tanpa save.

## Checklist (±10 menit)

1. **Panel** — Reload Scripts → menu **Mindweight** → panel muncul,
   dot server hijau.
   - [ ] Ada dua entri terpisah: Mindspace & Mindweight

2. **Generate ekstrem utama** — buka font percobaan (yang ada instance
   match master aktif, punya H O n o), target **Thin (100)** lalu
   **Black (900)** → Generate.
   - [ ] Master baru "Thin" / "Black" muncul di Font Info → Masters
   - [ ] Dialog self-check: stem tercapai dekat target (±5-10u wajar)
   - [ ] Dialog menyebut mode `Cape engine + glyph-level path-only`
   - [ ] Visual: buka tab, bandingkan master Regular vs ekstrem — Thin tidak
     pecah; Black menebal ke dalam secukupnya, counter tidak langsung
     menutup, tanpa outline rusak
   - [ ] Path-only glyph kena; component-only (Á dsb.) ikut via base-nya
   - [ ] Mixed path+component kalau ada dihitung sebagai skipped
   - [ ] Jika ada tab risk glyph terbuka, cek glyph itu dulu
   - [ ] Selama run Glyphs tetap responsif; klik ganda tidak memicu run kedua

3. **Guard duplikat** — Generate target yang sama lagi tanpa menghapus master.
   - [ ] Ditolak dengan pesan jelas (tidak menimpa)

4. **Target stem eksplisit** — hapus master Bold, isi field
   "Target stem H" (mis. angka stem Bold yang kamu mau) → Generate.
   - [ ] Master "Stem NNN" jadi; self-check H ≈ angka yang kamu isi

5. **Interpolasi & instance** — dengan master Regular + Thin/Black:
   - [ ] Font Info → Exports: preview instance di antaranya terinterpolasi
     mulus (kalau "Outline tetap kompatibel" ✓ dan tidak ada glyph gagal)
   - [ ] (Kalau "Insert instance otomatis" dicentang) instance dengan nilai
     axis saran De Groot ikut dibuat

6. **Pipeline penuh** — pilih master Bold baru → Mindspace: Jalankan
   Spacing → Jalankan Kern.
   - [ ] Spacing merapikan sidebearing master baru; kern jalan (bootstrap
     antar master otomatis menawarkan salin×skala — itu normal)

## Sesudahnya

- Semua lolos → Mindweight v4 resmi FUNGSIONAL; lapor supaya status
  project diupdate.
- Ada yang aneh → kirim teks error / isi Macro Panel + nomor langkah.
  Cek juga `~/mindspace-server/storage/logs/runs.jsonl` (entri
  `weight/params` per run — parameter & anatomi tercatat lengkap).

## Ekspektasi yang jujur

- Hasil = **DRAFT** (ala RMX/Cape-style tool): joint diagonal (v/w/y), titik
  temu bowl-stem (n/b/d), dan ink trap bisa jadi gelap — memang harus
  dirapikan manual. v4 memakai engine apply yang lebih matang, tapi belum
  generative outline.
- Font serif/kontras tinggi: serif bisa membengkak (offset-Y seragam) —
  ada warning otomatis dari server; periksa serif secara manual.
- Black (900) dari Regular = draft ekstrem — cek counter e/a/o, joint
  v/w/y, dan spacing. Kalau terlalu gelap, pakai target stem eksplisit yang
  sedikit lebih rendah lalu interpolasi.

## Test v5 — Manual+AI (2026-07-10)

1. Panel Mindweight → pilih target (mis. Black) → **Muat nilai AI** (status: "AI dimuat: N glyph").
2. Buka glyph di edit tab (mis. n) → klik **⟳** → field dx/dy/pos%/w% terisi nilai AI + sumbernya.
3. Ubah dx → **Preview** → glyph berubah di kanvas; baris konsistensi muncul (stem vs target). Preview berulang aman (non-destruktif); **Reset** balik semula.
4. **Simpan override** → Generate master penuh → dialog "override manual: N" dan glyph itu memakai nilaimu.
5. **Hapus** → generate lagi → kembali nilai AI.

## Test v6 — Panel Lanjutan + Terapkan ke Terpilih (2026-07-11)

1. **Panel default lebih sederhana** — Reload Scripts → Mindweight.
   - [ ] Panel terbuka kecil: cuma status server, Target, tombol Generate,
     dan baris "▸ Lanjutan" — checkbox/field manual TIDAK kelihatan
   - [ ] Klik "▸ Lanjutan" → panel melebar, semua kontrol lama (stem
     override, 3 checkbox, section Manual) muncul, tombol berubah jadi
     "▾ Lanjutan"
   - [ ] Klik lagi → panel mengecil balik, kontrol hilang
   - [ ] Tutup script, buka lagi → status Lanjutan (buka/tutup) diingat
     sama seperti sebelum ditutup

2. **Terapkan ke Terpilih — TANPA bikin master baru** — buka master yang
   sudah ada (mis. draft Black hasil Generate sebelumnya, atau master
   apapun), buka "Lanjutan".
   - [ ] Pilih 2-3 glyph di Font view (mis. yang kena tandai risk, atau
     sembarang) → **Muat nilai AI** (target sesuai popup)
   - [ ] Klik **Terapkan** → HANYA glyph yang dipilih berubah bentuknya di
     master yang SEDANG DIBUKA — cek Font Info → Masters TIDAK ada master
     baru muncul
   - [ ] Status bar melaporkan jumlah "Diterapkan: N glyph" (+ override/
     fallback/risk kalau ada)
   - [ ] ⌘Z membatalkan; tombol **Reset** juga membatalkan (dua-duanya harus
     jalan)
   - [ ] Ulangi tanpa "Muat nilai AI" (klik Terapkan langsung setelah isi
     field dx/dy/pos%/w% manual) → semua glyph terpilih pakai nilai manual
     yang sama (uniform), kecuali yang punya override tersimpan (menang)
   - [ ] Glyph berisiko (jika ada) tetap ditandai warna + tab proof muncul,
     sama seperti Generate penuh

## Test v7 — Slider Ketebalan per-glyph (2026-07-11)

1. Buka "Lanjutan" → **Muat nilai AI** — status harus bilang "anchor [100, 700, 900]" (3 anchor, bukan 1).
2. Pilih SATU glyph (mis. `o`) di edit tab/font view.
   - [ ] Geser slider Ketebalan dari 100→900 — field dx/dy/pos%/w% ikut berubah HALUS (bukan lompat), dan di 700 nilainya harus SAMA PERSIS dengan yang muncul kalau klik ⟳ (⟳ pakai AI single-anchor lama, keduanya harus konsisten di titik 700).
3. Pilih 2-3 glyph yang BEDA sekaligus (mis. `o`, `v`, `s`) — geser slider ke posisi manapun (mis. 500) → klik **Terapkan**.
   - [ ] Cek tiap glyph berubah dengan JUMLAH BERBEDA (bukan identik) — itu tandanya interpolasi per-glyph jalan, bukan 1 nilai dicopy ke semua.
4. Klik **Terapkan** lagi tanpa geser slider tapi ganti seleksi glyph — pastikan tetap jalan tanpa perlu klik Muat nilai AI ulang (cache `_ai_multi` dipakai lagi).
5. Tutup & buka lagi font tanpa Muat nilai AI, coba Terapkan — harus fallback ke perilaku manual (field manual dipakai seragam), bukan error.

## Test v8 — Slider Counter (2026-07-11)

1. Pilih SATU glyph berkonter (mis. `o` atau `s`), Muat nilai AI, geser
   slider Ketebalan ke suatu posisi (mis. 700) — catat posisi Counter yg
   ditampilkan (itu posisi AI-predicted).
2. Geser slider **Counter** sendiri (independen) → bentuk glyph di kanvas
   harus berubah (counter buka/tutup) TANPA stem/ketebalan ikut berubah.
   - [ ] dx/dy field TIDAK berubah waktu geser Counter, cuma pos% yang berubah
3. Pindah ke glyph LAIN (mis. dari `o` ke `v`), geser slider Ketebalan.
   - [ ] Slider Counter harus balik nunjukin posisi AI utk `v` sendiri,
     BUKAN nilai override yg tadi dituning buat `o`
4. Klik **Terapkan** dengan override Counter masih aktif di satu glyph.
   - [ ] Setelah Terapkan, geser Counter lagi tanpa pindah glyph — pastikan
     mulai dari posisi AI lagi (override lama udah "dibakar", bukan
     nyangkut sebagai override baru)
5. Reset dengan override aktif → pastikan balik ke bentuk asli DAN slider
   Counter balik nunjukin posisi AI (bukan angka override yg td dihapus).

## Test v9 — Panel Cape Weightor-style (2026-07-11)

1. Buka "Lanjutan" — cek visual: slider Ketebalan/X/Y/Outer-Inner sekarang
   full-width dgn angka gede DI ATAS slider (bukan di ujung kecil), diapit
   garis atas-bawah jadi satu blok.
2. Pilih 1 glyph berkontras (mis. `n` atau `o`), Muat nilai AI.
   - [ ] Cek checkbox "Sync X & Y" defaultnya NYALA, dan slider X/Y
     kelihatan DISABLED (abu2, gak bisa digeser)
   - [ ] Geser Ketebalan → slider X dan Y ikut update angkanya (readout),
     meski gak bisa digeser manual
3. Matikan "Sync X & Y".
   - [ ] Slider X dan Y jadi aktif/bisa digeser
   - [ ] Geser X SENDIRIAN → cek dy TIDAK ikut berubah (independen beneran)
   - [ ] Geser Y SENDIRIAN → cek dx TIDAK ikut berubah
4. Cek slider **Outer/Inner** — geser ke 0 (kiri penuh): counter glyph
   HARUS tetap besar/gak menyusut (siluet luar yg berubah). Geser ke 100
   (kanan penuh): counter HARUS menyusut banyak (siluet luar nyaris tetap).
   Ini KEBALIKAN dari v8 (`Counter` lama: kiri=dalam menyusut, kanan=luar
   tetap) — pastikan gak kebalik/salah arah.
5. Nyalain lagi "Sync X & Y" → override manual X/Y harus ke-reset,
   kembali ngikutin Ketebalan+AI.
6. Klik Terapkan dengan Sync OFF + X/Y manual aktif → override harus
   "dibakar" (gak nyangkut kalau geser lagi tanpa pindah glyph).

## Test v10 — Overlap cleanup pass (2026-07-11)

1. Pilih glyph dengan junction diagonal tajam (mis. `v`, `w`, `x`, `y`) di
   master apapun, pastikan checkbox "Outline tetap kompatibel" di
   "Lanjutan" **DIMATIKAN**.
2. Set Ketebalan ke berat (mis. 800-900), Terapkan/Preview.
   - [ ] Cek junction-nya — harusnya lebih bersih/gak ada garis
     potong-menyilang aneh di titik ketemunya diagonal, dibanding sebelum
     v10 (kalau masih kelihatan bermasalah, bandingkan dgn versi lama utk
     konfirmasi ini beneran regresi atau memang belum cukup)
3. **Regresi check**: nyalain lagi "Outline tetap kompatibel", ulangi
   langkah 1-2 pada glyph yang sama.
   - [ ] Hasilnya HARUS PERSIS sama seperti sebelum v10 (jalur kode ini
     gak disentuh sama sekali kalau checkbox nyala)
4. Interpolasi: dengan "Outline tetap kompatibel" MATI dan beberapa master
   sudah di-generate, cek preview instance — kalau ada broken
   interpolation (titik gak match antar master), itu ekspektasi wajar dari
   checkbox itu sendiri dimatikan, BUKAN bug baru dari v10.

## Verifikasi fix kern `:;` (Mindspace)

Jalankan Mindspace Kern lagi di font-mu (biasa saja, tanpa overwrite — kern mesin lama otomatis dire-prediksi segar + terklamp): pair `colon+semicolon` dkk. sekarang ≤20u & berstatus review → `:;` tidak dempet. Cek juga dialog: pair huruf tidak berubah drastis.
