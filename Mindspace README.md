# Mindspace — Panel Spacing & Kerning AI untuk GlyphsApp

Satu entri menu (**Scripts → Mindspace**) membuka panel melayang. Dari panel
itu semua alur dijalankan — tidak perlu lagi mengedit konstanta di file script.

Server AI-nya jalan lokal di Mac mini (`http://100.93.212.20:8000`, Tailscale),
otomatis nyala saat boot. Titik hijau di panel = terhubung.

## Cara pakai

1. Buka font di GlyphsApp, pilih master yang mau dikerjakan.
2. **Scripts → Mindspace** → panel muncul (kalau sudah terbuka, cuma dibawa ke depan).
3. Atur opsi (tersimpan otomatis antar sesi), lalu klik salah satu tombol.

### Jalankan Spacing (fase 1)

Alur control-glyph klasik:

1. Set spacing **H O V n o v** manual dulu sesuai rhythm yang kamu mau.
2. Klik **Jalankan Spacing** → dengan ≥3 anchor, semua glyph lain digenerate
   mengikuti rhythm-mu (o→c/e, n→m/h/u, tepi mirip H→I/M/N). Anchor tidak
   pernah disentuh. Lebar `space` diisi via aturan Tracy kalau belum kamu set.
3. Cek proof tab → koreksi LSB/RSB yang kurang pas → jalankan lagi.
   Koreksimu otomatis jadi anchor baru.

### Jalankan Kern (fase 2)

State machine, jalan sesuai kondisi font:

1. **Gate spacing** — kalau spacing masih berantakan (deviasi > 2,5% UPM),
   run ditolak: rapikan spacing dulu (kerning di atas spacing rusak =
   kompensasi salah alamat).
2. **Auto kerning groups** — grup kosong diisi: huruf dasar → grup namanya
   sendiri; composite (Á) dan varian suffix (a.ss01) mewarisi grup base per
   sisi hanya kalau tepinya masih match secara visual (Ľ kanan sengaja ditolak).
3. **Bootstrap master baru** — master yang kern-nya hampir kosong disalin dari
   master lain yang sudah jadi, × skala rasio rhythm; run berhenti untuk review.
4. **Kerning** — kern manual-mu (≥10 pair) dipakai sebagai sampel style
   (`/personalize`); kurang dari itu pakai model global (atau, kalau opsi
   fallback dimatikan, dibuka tab saran pair untuk dikern manual dulu).
   Nilai ditulis di **level grup** (@MMK) — aksen otomatis ikut base.
5. Proof tab + dialog ringkasan. Koreksi pair yang kurang pas → jalankan
   lagi → koreksimu jadi sampel style baru.

## Opsi panel

| Opsi | Default | Artinya |
|------|---------|---------|
| Pair set (kern) | `full` | Semua glyph ber-unicode (±5-8rb pair, run 10-25 menit). `latin_extended` = huruf saja (~3-5 menit), `latin_basic` = 89 pair klasik (~30 detik). |
| Glyph set (spacing) | `all_encoded` | Semua glyph ber-cmap. `letters_all` = huruf saja, `latin_basic` = A-Z. |
| Cek spacing dulu (gate) | ✓ | Tolak kerning kalau spacing belum rapi. |
| Auto kerning groups | ✓ | Isi kerning group yang kosong tiap run. |
| Bootstrap master baru | ✓ | Master kosong disalin dari master jadi × skala rhythm. |
| Proof pakai konteks (HAVAH) | ✓ | Proof tab membungkus pair dengan konteks kontrol, bukan pair telanjang. |
| Kern global tanpa sampel | ✓ | Sampel < 10: tetap kerning pakai model global. Matikan kalau mau alur personal ketat (disuruh kern sampel dulu). |
| ⚠ Timpa SEMUA kern lama (sekali run) | ✗ | Mulai bersih total: SELURUH kerning master dihapus dulu, lalu diisi output model global murni (personalisasi & bootstrap mati untuk run ini) — tabel kern dan catatan dijamin sinkron. Untuk reset / menyembuhkan catatan tercemar. Bisa di-undo (⌘Z). Tidak disimpan — selalu mati saat panel dibuka dan auto-uncheck setelah run. |

Semua opsi tersimpan di `Glyphs.defaults` (`com.bahasatype.mindspace.*`).
Credential dan alamat server dibaca dari `awal_config.json`; lihat
`awal_config.example.json` sebagai template. File konfigurasi lokal tersebut
diabaikan Git. Ambang confidence dan opsi internal lain tetap berupa konstanta
di atas `Mindspace.py`.

## Penting diketahui

- **Glyphs tetap responsif selama menunggu server** — kern `full` bisa
  belasan menit, tapi UI tidak beachball: kamu bisa lanjut kerja di Glyphs.
  Baris status panel menunjukkan "berjalan…" + estimasi durasi. Catatan:
  hasil dihitung dari bentuk glyph saat run DIMULAI — edit di tengah run
  boleh, tapi tidak ikut dianalisis; kalau font-nya kamu tutup di tengah
  run, apply dibatalkan dengan pesan jelas (tidak crash). Momen apply
  sendiri (beberapa detik di akhir) tetap nge-block sebentar.
- **Proof tab kern** menampilkan maksimal 400 pair ber-kern terbesar
  (pair set `full` bisa ribuan — tab raksasa bikin Glyphs berat; sisanya
  tetap ter-apply, cek dialog).
- **Undo**: ⌘Z setelah run, atau tutup tanpa save / File → Revert.
- Kern/spacing **manual-mu tidak pernah disentuh** — script hanya menimpa
  nilai yang dia tulis sendiri (tercatat di `font.userData`).

## Troubleshooting

- **● merah / "offline"** — server mati. Di Mac mini:
  `launchctl unload ~/Library/LaunchAgents/com.mindspace.server.plist && launchctl load ~/Library/LaunchAgents/com.mindspace.server.plist`
- **"modul vanilla tidak termuat"** — Plugin Manager → Modules → Vanilla,
  lalu restart Glyphs.
- **Export error "Tidak ada instance…"** — buat instance yang namanya match
  master aktif (Font Info → Exports).
- **Rollback ke script lama** — copy `_archive/Mindspace Kern.py` +
  `_archive/Mindspace Spacing.py` balik ke folder OneDrive Awal Script,
  hapus `Mindspace.py` di sana, Refresh Scripts.

## Lokasi file

- Copy aktif (yang dibaca Glyphs): `OneDrive / 02 Work / 01 Awal Studio / Tools / Awal Script / Mindspace.py` (symlink `Awal Script` di folder Scripts Glyphs)
- Copy dev (source of truth): `~/mindspace-glyphs/Mindspace.py` — setiap edit wajib di-mirror ke OneDrive.
- Plugin terpisah: `Mindspace Rhythm.glyphsReporter` (View → Show Mindspace Rhythm) — badge konsistensi live di editor, tanpa server.
