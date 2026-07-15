#MenuTitle: Mindspace
# -*- coding: utf-8 -*-
"""
Panel Mindspace — spacing + kerning AI dalam satu window.

Buka sekali (Scripts → Mindspace), panel melayang tetap hidup:
- Jalankan Spacing: anchor HOVnov + koreksimu → personalize/predict →
  apply LSB/RSB → proof rhythm.
- Jalankan Kern: gate spacing → auto kerning groups → bootstrap master →
  personalize/predict → apply level grup → cleanup → proof.
Opsi di panel tersimpan otomatis (Glyphs.defaults) — tidak perlu lagi
mengedit konstanta di file ini.

Catatan jujur: selama run panjang (kern pair set "full" bisa belasan
menit) Glyphs freeze — Glyphs API harus jalan di main thread, sama
seperti script lama. Status panel di-set "berjalan…" sebelum mulai.
"""
import os
import json
import math
import time
import uuid
import tempfile
import urllib.request
import urllib.error
from dataclasses import dataclass

# ── CONFIG (jarang diubah — opsi harian ada di panel) ──────────────────────
def _load_local_config():
    """Load credentials kept outside Git from the script directory."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "awal_config.json")
    try:
        with open(config_path, "r", encoding="utf-8") as config_file:
            return json.load(config_file)
    except (OSError, ValueError):
        return {}


_LOCAL_CONFIG = _load_local_config()
SERVER_URL = _LOCAL_CONFIG.get("server_url", "http://100.93.212.20:8000")
API_KEY = _LOCAL_CONFIG.get("api_key", "local-secret-key")

# Kern
KERN_MIN_CONFIDENCE = 0.15  # low on purpose — confidence is a magnitude proxy,
                            # not real certainty; "review" status is what
                            # actually flags pairs to double-check
KERN_ROUND_TO      = 5
IGNORE_SMALL       = 8
KERN_MIN_SAMPLES   = 10     # minimal sampel manual sebelum personalisasi aktif
KERN_USERDATA_KEY  = "com.mindspace.appliedKern"   # {master.id: {"L|R": kern}}
SPACING_MAX_DEV    = 0.025  # gate: rata-rata |delta sidebearing| per sisi
                            # > 2.5% UPM = spacing belum rapi (MAE model ~1%)
SUGGEST_COUNT      = 30     # jumlah saran pair sampel
SLOPE_TOL          = 0.15   # toleransi kemiripan tepi utk pewarisan grup (= server)
PROTR_TOL          = 0.06
PROOF_MAX_PAIRS    = 400    # proof tab dibatasi N pair ber-|kern| terbesar —
                            # pair set full bisa ribuan pair, satu tab dengan
                            # puluhan ribu karakter bikin Glyphs megap-megap

# Spacing
SPACING_MIN_CONFIDENCE = 0.3
SPACING_ROUND_TO       = 1
APPLY_REVIEW           = True   # False = hanya apply glyph berstatus "auto"
# Alur klasik control-glyph: set spacing glyph-glyph ini MANUAL dulu sesuai
# rhythm yang kamu mau — sisanya digenerate senada. Anchor tak pernah disentuh.
SAMPLE_GLYPHS          = ["H", "O", "V", "n", "o", "v"]
SPACING_MIN_SAMPLES    = 3
SPACING_USERDATA_KEY   = "com.mindspace.appliedSpacing"  # {master.id: {glyph: [lsb, rsb]}}

# Kalibrasi HOVnov awal (vendored dari HT Letterspacer, lihat blok
# "HOVnov calibration" di bawah) — H/O/V pakai zona vertikal H, n/o/v pakai
# zona x, sama seperti default HT Letterspacer (Letter,upper→H factor 1.25 /
# Letter,lower→x factor 1). Override via master custom parameter paramArea/
# paramDepth/paramOver kalau ada (sama seperti HT Letterspacer asli).
HOVNOV_REFS  = {"H": ("H", 1.25), "O": ("H", 1.25), "V": ("H", 1.25),
                "n": ("x", 1.0),  "o": ("x", 1.0),  "v": ("x", 1.0)}
HOVNOV_AREA  = 400   # area putih (ribuan unit)
HOVNOV_DEPTH = 15    # depth, % xHeight
HOVNOV_OVER  = 0     # overshoot, % xHeight
HOVNOV_FREQ  = 5     # frekuensi ukur vertikal, font units

# Teks tooltip (hover) buat field Area/Depth/Over di panel — user gak harus
# baca kode/CLAUDE.md buat tau efeknya tiap parameter.
HOVNOV_TOOLTIPS = {
    "area": (
        "AREA — target luas 'ruang putih' (sidebearing) kiri+kanan glyph, "
        "dalam ribuan unit (skala UPM 1000; auto disesuaikan ke UPM font-mu).\n"
        "Makin BESAR → sidebearing makin LEBAR (spasi makin longgar).\n"
        "Makin KECIL → sidebearing makin SEMPIT (spasi makin rapat).\n"
        "Default HT Letterspacer: 400."
    ),
    "depth": (
        "DEPTH — seberapa dalam ceruk/lekukan glyph (mis. lengkung O, celah "
        "V) dianggap 'tertutup' saat dihitung areanya, dalam % x-height.\n"
        "Makin BESAR → lekukan dalam dianggap lebih penuh/tertutup, "
        "pengaruhnya ke lebar sidebearing jadi lebih KECIL.\n"
        "Makin KECIL → lekukan dalam dianggap lebih terbuka, bikin "
        "sidebearing jadi lebih LEBAR (banyak 'udara' dihitung).\n"
        "Default: 15."
    ),
    "over": (
        "OVER(SHOOT) — perpanjangan zona ukur vertikal di atas & bawah "
        "acuan (H utk uppercase, x utk lowercase), dalam % x-height.\n"
        "Buat nangkep bagian glyph yang sedikit melewati batas acuan (mis. "
        "ujung lancip V yang undershoot tipis di bawah baseline).\n"
        "0 = zona ukur pas di tinggi acuan, tanpa toleransi.\n"
        "Default: 0 — naikkan kalau glyph diagonal/lancip kamu banyak yang "
        "overshoot/undershoot dan hasilnya kelihatan kurang pas."
    ),
}

# ── Opsi panel (tersimpan di Glyphs.defaults, default = perilaku lama) ──────
PREF_PREFIX = "com.bahasatype.mindspace."
DEFAULTS = {
    "pair_set":          "full",          # full / latin_extended / latin_basic
    "glyph_set":         "all_encoded",   # all_encoded / letters_all / latin_basic
    "check_spacing":     True,   # gate: tolak kern kalau spacing belum rapi
    "auto_groups":       True,   # isi kerning group kosong + suffix variant (a.001) ikut spacing/group base-nya, tiap run
    "bootstrap_masters": True,   # master hampir kosong disalin dari master jadi
    "proof_context":     True,   # proof tab pakai konteks kontrol (HAVAH)
    "global_fallback":   True,   # sampel < minimum: tetap kern pakai model global
}
PAIR_SETS  = ["full", "latin_extended", "latin_basic"]
GLYPH_SETS = ["all_encoded", "letters_all", "latin_basic"]


def pref(key):
    """Glyphs.defaults menyimpan bool sebagai 0/1 dan mengembalikan None
    kalau belum pernah di-set — koersi balik ke tipe default lama."""
    default = DEFAULTS[key]
    try:
        v = Glyphs.defaults[PREF_PREFIX + key]
    except Exception:
        v = None
    if v is None:
        return default
    if isinstance(default, bool):
        try:
            return bool(int(v))
        except Exception:
            return default
    return str(v)


def set_pref(key, value):
    Glyphs.defaults[PREF_PREFIX + key] = int(value) if isinstance(value, bool) else value


@dataclass
class KernPair:
    left: str
    right: str
    kern: int
    confidence: float
    status: str
    source: str = "generated"
    rhythm_dev: object = None   # audit konsistensi: deviasi gap pair (setelah
                                # kern) dari rhythm HOVnov-mu, font units;
                                # besar = keluar rhythm → status "review"


@dataclass
class SpacingGlyph:
    glyph: str
    char: str
    current_lsb: int
    current_rsb: int
    predicted_lsb: int
    predicted_rsb: int
    delta_lsb: int
    delta_rsb: int
    confidence: float
    status: str
    source: str = "generated"


class MindspaceClient:
    """HTTP client using only stdlib (urllib) — no third-party deps needed,
    since GlyphsApp's embedded Python doesn't reliably see pip-installed packages."""

    def __init__(self, server_url, api_key):
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key

    def health_check(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.server_url}/health")
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status == 200
        except Exception:
            return False

    def predict_kern(
        self,
        font_path: str,
        pair_set: str = "latin_basic",
        max_pairs: int = 5000,
        min_confidence: float = 0.65,
        round_to: int = 5,
        ignore_small: int = 8,
        samples=None,
        extra_pairs=None,
    ):
        """samples berisi list dict {left,right,kern} → pakai /personalize;
        None/kosong → /predict biasa. Returns (pairs, meta)."""
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Font not found: {font_path}")

        personalized = bool(samples)
        endpoint = "/v1/kern/personalize" if personalized else "/v1/kern/predict"

        boundary = uuid.uuid4().hex
        fields = {
            "pair_set": pair_set,
            "max_pairs": str(max_pairs),
            "min_confidence": str(min_confidence),
            "round_to": str(round_to),
            "ignore_small": str(ignore_small),
        }
        if personalized:
            fields["samples"] = json.dumps(samples)
        if extra_pairs:
            fields["extra_pairs"] = json.dumps(extra_pairs)

        with open(font_path, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        for name, value in fields.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            body += f"{value}\r\n".encode()

        filename = os.path.basename(font_path)
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="font_file"; filename="{filename}"\r\n'
        ).encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_bytes
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.server_url}{endpoint}",
            data=bytes(body),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

        try:
            # pair set "full" bisa belasan menit di server — timeout longgar
            with urllib.request.urlopen(req, timeout=1800) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")

        pairs = [KernPair(**p) for p in data["pairs"]]
        meta = {
            "personalized": personalized,
            "n_samples_used": data.get("n_samples_used", 0),
            "calibration": data.get("calibration"),
        }
        return pairs, meta

    def predict_spacing(
        self,
        font_path: str,
        glyph_set: str = "latin_basic",
        min_confidence: float = 0.3,
        round_to: int = 1,
        samples=None,
    ):
        """samples berisi list dict {glyph,lsb,rsb} → /personalize (anchor
        dipakai kalibrasi & dikembalikan persis); None → /predict global.
        Returns (glyphs, meta)."""
        if not os.path.exists(font_path):
            raise FileNotFoundError(f"Font not found: {font_path}")

        personalized = bool(samples)
        endpoint = "/v1/spacing/personalize" if personalized else "/v1/spacing/predict"

        boundary = uuid.uuid4().hex
        fields = {
            "glyph_set": glyph_set,
            "min_confidence": str(min_confidence),
            "round_to": str(round_to),
        }
        if personalized:
            fields["samples"] = json.dumps(samples)

        with open(font_path, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        for name, value in fields.items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            body += f"{value}\r\n".encode()

        filename = os.path.basename(font_path)
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="font_file"; filename="{filename}"\r\n'
        ).encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_bytes
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.server_url}{endpoint}",
            data=bytes(body),
            method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")

        glyphs = [SpacingGlyph(**g) for g in data["glyphs"]]
        meta = {
            "personalized": personalized,
            "n_samples_used": data.get("n_samples_used", 0),
            "calibration": data.get("calibration"),
            "suggested_space_width": data.get("suggested_space_width"),
        }
        return glyphs, meta

    def check_spacing(self, font_path):
        """Nilai kerapian spacing via SpacingNet: rata-rata |delta sidebearing|
        per sisi relatif UPM (lowercase saja — rhythm teks didominasi lc).
        Return (mean_dev, upm) atau None kalau endpoint spacing tak tersedia."""
        boundary = uuid.uuid4().hex
        with open(font_path, "rb") as f:
            file_bytes = f.read()

        body = bytearray()
        for name, value in (("glyph_set", "lowercase_only"), ("min_confidence", "0")):
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            body += f"{value}\r\n".encode()
        filename = os.path.basename(font_path)
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="font_file"; filename="{filename}"\r\n'
        ).encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_bytes
        body += f"\r\n--{boundary}--\r\n".encode()

        req = urllib.request.Request(
            f"{self.server_url}/v1/spacing/predict",
            data=bytes(body), method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                data = json.loads(r.read().decode())
        except Exception:
            return None   # spacing model belum ada / error → jangan blokir kerning

        glyphs = data.get("glyphs") or []
        if not glyphs:
            return None
        devs = [abs(g["delta_lsb"]) + abs(g["delta_rsb"]) for g in glyphs]
        mean_dev_per_side = (sum(devs) / len(devs)) / 2.0
        return mean_dev_per_side, data.get("upm", 1000)

    def _post_font(self, endpoint, font_path, fields=None, timeout=300):
        """POST multipart sederhana: font + field form opsional."""
        boundary = uuid.uuid4().hex
        with open(font_path, "rb") as f:
            file_bytes = f.read()
        body = bytearray()
        for name, value in (fields or {}).items():
            body += f"--{boundary}\r\n".encode()
            body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
            body += f"{value}\r\n".encode()
        filename = os.path.basename(font_path)
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="font_file"; filename="{filename}"\r\n'
        ).encode()
        body += b"Content-Type: application/octet-stream\r\n\r\n"
        body += file_bytes
        body += f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"{self.server_url}{endpoint}", data=bytes(body), method="POST",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')}")

    def suggest_samples(self, font_path, count=30):
        return self._post_font("/v1/kern/suggest-samples", font_path,
                               {"count": str(count)})

    def font_edges(self, font_path):
        return self._post_font("/v1/font/edges", font_path,
                               {"glyph_set": "groupable"})


def call_server(fn):
    """fn = panggilan network MURNI (method MindspaceClient, tanpa Glyphs).
    Jalan di thread belakang sementara main thread memompa NSRunLoop —
    UI Glyphs tetap hidup selama server mikir (kern full bisa belasan menit),
    semua API Glyphs tetap di main thread. Tanpa PyObjC (exec-test dengan
    /usr/bin/python3) jatuh ke join() = perilaku freeze lama."""
    import threading
    box = {}

    def worker():
        try:
            box["result"] = fn()
        except BaseException as e:
            box["error"] = e

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    try:
        from Foundation import NSRunLoop, NSDate, NSDefaultRunLoopMode
        rl = NSRunLoop.currentRunLoop()
        while t.is_alive():
            rl.runMode_beforeDate_(
                NSDefaultRunLoopMode, NSDate.dateWithTimeIntervalSinceNow_(0.1))
    except Exception:
        pass
    t.join()
    if "error" in box:
        raise box["error"]
    return box["result"]


# ═══ GLYPHS-ONLY SECTION (semua di bawah ini butuh API GlyphsApp) ═══════════


def _empty_info_values(font, instance):
    """Entri Font Info yang ADA tapi kosong (mis. Copyrights) bikin Glyphs
    menolak export — padahal TTF ini cuma buat analisis sekali pakai.
    Kumpulkan supaya bisa diisi placeholder sementara lalu dikembalikan."""
    found = []
    for owner in (font, instance):
        for prop in list(getattr(owner, "properties", []) or []):
            subvalues = getattr(prop, "values", None) or []
            targets = list(subvalues) if len(subvalues) else [prop]
            for t in targets:
                try:
                    if t.value == "":
                        found.append(t)
                except Exception:
                    pass
    return found


def export_master_ttf(font, master):
    tmp_dir = tempfile.mkdtemp(prefix="mindspace_")
    matching = [i for i in font.instances if i.linkStyle == master.name or i.name == master.name]
    if not matching:
        # multi-master: fallback diam-diam ke instance pertama = menganalisis
        # BENTUK weight lain lalu apply ke master ini — salah senyap. Tolak.
        names = ", ".join(i.name for i in font.instances) or "(tidak ada)"
        raise RuntimeError(
            f"Tidak ada instance bernama/ber-linkStyle '{master.name}'.\n"
            f"Instance yang ada: {names}.\n"
            f"Buat instance yang match master ini dulu (Font Info → Exports).")
    instance = matching[0]

    empty_values = _empty_info_values(font, instance)
    for v in empty_values:
        v.value = "-"
    try:
        result = instance.generate(
            FontPath=tmp_dir, Format="TTF", AutoHint=False, RemoveOverlap=False,
            UseProductionNames=False,
        )
    finally:
        for v in empty_values:
            try:
                v.value = ""
            except Exception:
                pass
    if result is not True:
        raise RuntimeError(f"Glyphs generate() gagal: {result}")

    for root, _, files in os.walk(tmp_dir):
        for f in files:
            if f.lower().endswith(".ttf"):
                return os.path.join(root, f)
    raise RuntimeError(f"generate() sukses tapi tidak ada .ttf ditemukan di {tmp_dir}")


def cleanup_ttf(font_path):
    try:
        os.unlink(font_path)
        os.rmdir(os.path.dirname(font_path))
    except Exception:
        pass


def _font_alive(font):
    """Selama call_server memompa run loop, user bisa menutup font — mutasi
    ke font zombie = crash. Cek sebelum apply pasca-network."""
    try:
        return any(f == font for f in Glyphs.fonts)
    except Exception:
        return True   # ragu = jangan blokir (perilaku lama)


def _abort_font_closed(flow):
    Message("Font ditutup di tengah run — tidak ada yang di-apply.",
            f"Mindspace {flow} — Dibatalkan")
    return f"{flow}: dibatalkan (font ditutup)"


# ── Kern: groups, samples, bootstrap, apply ────────────────────────────────


OTHER_SLOPE_TOL = 0.06   # jauh lebih ketat dari SLOPE_TOL (0.15) biasa — kelas
                         # "other" mewadahi bentuk jauh lebih beragam (a, e, g,
                         # s, dst — apa pun yg bukan flat/round/diagonal murni),
                         # jadi ambang kemiripannya harus lebih ketat dulu
                         # sebelum dipercaya mewarisi grup
OTHER_PROTR_TOL = 0.03


def _edges_match(a, b):
    """a/b = [class, slope, protrusion] — aturan match sama dengan server.

    Kelas "other" DULU auto-reject total (kasus nyata: a.001 vs a — bowl+stem
    'a' selalu terklasifikasi "other", jadi varian suffix-nya tak pernah
    diwarisi grup meski slope/protrusion-nya nyaris identik, lihat runs.jsonl
    2026-07-10/11: diff slope ~0.03-0.04, protrusion ~0 — jauh di bawah
    toleransi normal). Sekarang tetap dicek numerik tapi pakai ambang jauh
    lebih ketat (OTHER_SLOPE_TOL/OTHER_PROTR_TOL) — bukan auto-lolos, supaya
    pasangan "other" yang BENERAN beda bentuk (mis. 'a' vs 'g') tetap ditolak."""
    if a is None or b is None:
        return False
    if a[0] != b[0]:
        return False
    if a[0] == "other":
        return abs(a[1] - b[1]) <= OTHER_SLOPE_TOL and abs(a[2] - b[2]) <= OTHER_PROTR_TOL
    return abs(a[1] - b[1]) <= SLOPE_TOL and abs(a[2] - b[2]) <= PROTR_TOL


def _base_letter_component(font, layer):
    """Nama glyph huruf dasar dari composite (komponen pertama yang beneran
    huruf — bukan mark/aksen)."""
    for comp in layer.components:
        ref = font.glyphs[comp.componentName]
        if ref is None or not ref.unicode:
            continue
        try:
            if chr(int(ref.unicode, 16)).isalpha():
                return ref.name
        except Exception:
            pass
    return None


def ensure_groups(font, master, client, font_path):
    """Isi kerning group yang KOSONG, setiap run (grup yang sudah ada tidak
    pernah disentuh). Dulu di-skip total kalau font sudah punya grup apa pun —
    bug nyata: Glyphs mengisi grup otomatis utk glyph baru (Ydieresis dapat
    grup "Y" dari database) sementara huruf dasar yang digambar duluan (Y)
    tidak, dan guard lama membuat Y tak pernah diisi → grup tak nyambung.

    Huruf dasar → grup namanya sendiri. Composite murni (Aacute) mewarisi
    grup base per sisi HANYA kalau tepinya masih match secara visual dengan
    base (server /v1/font/edges) — aksen macam caron-apostrof Ľ mengubah
    tepi kanan, sisi itu sengaja tidak diwarisi.
    Return string ringkasan, atau None kalau tidak ada yang perlu diisi.
    """
    if not pref("auto_groups"):
        return None

    def _letter(g):
        if not g.unicode:
            return False
        try:
            return chr(int(g.unicode, 16)).isalpha()
        except Exception:
            return False

    # pass 1: huruf dasar (tanpa server) — isi yang kosong saja
    n_base = 0
    need_edges = False
    for g in font.glyphs:
        if not _letter(g):
            continue
        layer = g.layers[master.id]
        if layer is None:
            continue
        if layer.paths:
            changed = False
            if not g.leftKerningGroup:
                g.leftKerningGroup = g.name
                changed = True
            if not g.rightKerningGroup:
                g.rightKerningGroup = g.name
                changed = True
            if changed:
                n_base += 1
        elif layer.components and (not g.leftKerningGroup or not g.rightKerningGroup):
            need_edges = True

    # varian suffix tak ber-unicode (a.ss01) yang grupnya belum lengkap?
    for g in font.glyphs:
        if g.unicode or "." not in g.name or g.name.startswith("."):
            continue
        base_name = g.name.split(".", 1)[0]
        if "_" in base_name or font.glyphs[base_name] is None:
            continue
        if not g.leftKerningGroup or not g.rightKerningGroup:
            need_edges = True
            break

    # pass 2: composite yang grupnya belum lengkap — butuh cek visual server
    edges = {}
    if need_edges:
        try:
            edges = call_server(lambda: client.font_edges(font_path)).get("edges", {})
        except Exception:
            edges = {}
        if not _font_alive(font):
            return None   # font ditutup selama menunggu server

    n_l = n_r = 0
    rejected = []
    for g in font.glyphs:
        if not edges or not _letter(g):
            continue
        layer = g.layers[master.id]
        if layer is None:
            continue
        if layer.paths:
            pass
        elif layer.components:
            base_name = _base_letter_component(font, layer)
            if base_name is None or base_name == g.name:
                continue
            base = font.glyphs[base_name]
            ge, be = edges.get(g.name), edges.get(base_name)
            if ge is None or be is None:
                continue
            if not g.leftKerningGroup:
                if _edges_match(ge.get("left"), be.get("left")):
                    g.leftKerningGroup = base.leftKerningGroup or base_name
                    n_l += 1
                else:
                    rejected.append(f"{g.name}·kiri")
            if not g.rightKerningGroup:
                if _edges_match(ge.get("right"), be.get("right")):
                    g.rightKerningGroup = base.rightKerningGroup or base_name
                    n_r += 1
                else:
                    rejected.append(f"{g.name}·kanan")

    # pass 3: varian suffix (a.ss01, T.alt — tak ber-unicode, base ada) —
    # warisi grup base per sisi kalau tepinya masih match secara visual;
    # stylistic set memang SERING berubah bentuk, penolakan = fitur
    for g in font.glyphs:
        if not edges or g.unicode:
            continue
        name = g.name
        if "." not in name or name.startswith("."):
            continue
        base_name = name.split(".", 1)[0]
        if "_" in base_name:
            continue
        base = font.glyphs[base_name]
        if base is None:
            continue
        layer = g.layers[master.id]
        if layer is None or not (layer.paths or layer.components):
            continue
        ge, be = edges.get(name), edges.get(base_name)
        if ge is None or be is None:
            continue
        if not g.leftKerningGroup:
            if _edges_match(ge.get("left"), be.get("left")):
                g.leftKerningGroup = base.leftKerningGroup or base_name
                n_l += 1
            else:
                rejected.append(f"{name}·kiri")
        if not g.rightKerningGroup:
            if _edges_match(ge.get("right"), be.get("right")):
                g.rightKerningGroup = base.rightKerningGroup or base_name
                n_r += 1
            else:
                rejected.append(f"{name}·kanan")

    if n_base == 0 and n_l == 0 and n_r == 0 and not rejected:
        return None   # semua grup sudah lengkap
    rej = f" | tidak diwarisi (tepi beda): {', '.join(rejected[:6])}" if rejected else ""
    if len(rejected) > 6:
        rej += f" +{len(rejected) - 6}"
    return f"Grup diisi: {n_base} huruf dasar, composite mewarisi {n_l} kiri/{n_r} kanan{rej}"


def _group_reps(font):
    """Peta grup → glyph perwakilan (buat menerjemahkan group kerning ke
    pair glyph konkret untuk server). Prioritas: glyph yang namanya = nama
    grup (base-nya), fallback anggota pertama ber-unicode."""
    right_rep, left_rep = {}, {}   # rightKerningGroup → glyph (posisi KIRI pair), dst.
    for g in font.glyphs:
        if g.rightKerningGroup:
            cur = right_rep.get(g.rightKerningGroup)
            if cur is None or g.name == g.rightKerningGroup:
                if g.unicode:
                    right_rep[g.rightKerningGroup] = g.name
        if g.leftKerningGroup:
            cur = left_rep.get(g.leftKerningGroup)
            if cur is None or g.name == g.leftKerningGroup:
                if g.unicode:
                    left_rep[g.leftKerningGroup] = g.name
    return right_rep, left_rep


def collect_kern_samples(font, master):
    """Pair kern manual milik user di master ini = sampel style.

    Pakai catatan userData dari run sebelumnya: pair yang TIDAK tercatat
    berarti dikern manual; pair tercatat tapi nilainya berubah berarti user
    mengoreksi output mesin — dua-duanya sampel. Group kerning (@MMK) ikut
    dibaca: diterjemahkan ke glyph perwakilan grup untuk server.
    """
    record = {}
    try:
        record = dict((font.userData[KERN_USERDATA_KEY] or {}).get(master.id, {}))
    except Exception:
        pass

    right_rep, left_rep = _group_reps(font)

    def _resolve(key):
        """Kunci kern dict → (nama kunci mentah, nama glyph perwakilan)."""
        k = str(key)
        if k.startswith("@MMK_L_"):
            grp = k[len("@MMK_L_"):]
            return k, right_rep.get(grp)
        if k.startswith("@MMK_R_"):
            grp = k[len("@MMK_R_"):]
            return k, left_rep.get(grp)
        if k.startswith("@"):
            return k, None
        g = font.glyphForId_(key)
        return (g.name, g.name) if g is not None else (k, None)

    samples = []
    corrections = []
    kern_dict = font.kerning.get(master.id) or {}
    for lkey in list(kern_dict.keys()):
        lraw, lname = _resolve(lkey)
        if lname is None:
            continue
        rights = kern_dict[lkey]
        for rkey in list(rights.keys()):
            rraw, rname = _resolve(rkey)
            if rname is None:
                continue
            val = int(rights[rkey])
            recorded = record.get(f"{lraw}|{rraw}")
            if recorded is None:
                samples.append({"left": lname, "right": rname, "kern": val})
            elif int(recorded) != val:
                corrections.append({"left": lname, "right": rname, "kern": val})

    # Guard revert massal (bug yang sama dengan alur Spacing): koreksi
    # sungguhan itu segelintir pair — kalau mayoritas catatan berubah, user
    # me-revert hasil run sebelumnya; catatan basi, buang.
    if len(corrections) > max(10, int(0.3 * len(record))):
        corrections = []
        try:
            record_all = dict(font.userData[KERN_USERDATA_KEY] or {})
            record_all.pop(master.id, None)
            font.userData[KERN_USERDATA_KEY] = record_all
        except Exception:
            pass

    return samples + corrections


def _strip_machine_kern(font, master):
    """Anti-fosil: kern MESIN (tercatat di record & nilainya belum diubah
    user) dihapus sementara supaya TTF export tidak memuatnya — server
    membaca existing_kern sbg ground truth conf 1.0, sehingga nilai mesin
    lama tak pernah dire-prediksi/di-clamp (kasus nyata: :; -105 bertahan).
    Return snapshot [(lkey, rkey, val)] untuk _restore_kern SEGERA setelah
    export."""
    record = {}
    try:
        record = dict((font.userData[KERN_USERDATA_KEY] or {}).get(master.id, {}))
    except Exception:
        pass
    snapshot = []
    for key, rec_val in record.items():
        try:
            lkey, rkey = key.split("|", 1)
            cur = font.kerningForPair(master.id, lkey, rkey)
            if cur is None or abs(float(cur)) > 1e15:
                continue
            if int(cur) != int(rec_val):
                continue   # user mengoreksi → miliknya, jangan disentuh
            font.removeKerningForPair(master.id, lkey, rkey)
            snapshot.append((lkey, rkey, int(cur)))
        except Exception:
            continue
    return snapshot


def _restore_kern(font, master, snapshot):
    for lkey, rkey, val in snapshot:
        try:
            font.setKerningForPair(master.id, lkey, rkey, val)
        except Exception:
            pass


def _kern_entry_count(kern_dict):
    try:
        return sum(len(kern_dict[k]) for k in kern_dict.keys())
    except Exception:
        return 0


def _master_rhythm_ref(font, master):
    """Referensi rhythm master (UC & lc) dihitung native dari layer H/O/n/o —
    softmin ber-zona, matematika sama dengan plugin/server. None kalau gagal."""
    from math import exp
    try:
        upm = font.upm
        tau = 0.08 * upm
        lo = min(master.descender * 0.4, -10)
        hi = master.ascender * 0.95
        step = (hi - lo) / 24.0
        xh, cap = master.xHeight, master.capHeight

        def edges_at(layer, y):
            try:
                pts = layer.intersectionsBetweenPoints(
                    (-4000, y), (layer.width + 4000, y), components=True)
            except Exception:
                return None
            if pts is None or len(pts) <= 2:
                return None
            xs = [pt.x for pt in list(pts)[1:-1]]
            return (min(xs), max(xs)) if xs else None

        def dist(ll, rl):
            gaps, zones = [], []
            y = lo
            while y <= hi:
                le, re = edges_at(ll, y), edges_at(rl, y)
                if le is not None and re is not None:
                    gaps.append((ll.width - le[1]) + re[0])
                    zones.append(1.0 if 0 <= y <= xh else (0.6 if y <= cap else 0.3))
                y += step
            if len(gaps) < 3:
                return None
            gmin = min(gaps)
            num = den = 0.0
            for gp, z in zip(gaps, zones):
                w = exp(-(gp - gmin) / tau) * z
                num += gp * w
                den += w
            return num / den if den > 0 else None

        lays = {}
        for ch in "HOno":
            gl = font.glyphs[ch]
            if gl is None:
                return None
            l = gl.layers[master.id]
            if l is None or not (l.paths or l.components):
                return None
            lays[ch] = l

        refs = {}
        for bucket, combos in (("UC", ("HH", "HO", "OH", "OO")),
                               ("lc", ("nn", "no", "on", "oo"))):
            ds = [d for c in combos
                  if (d := dist(lays[c[0]], lays[c[1]])) is not None]
            if not ds:
                return None
            ds.sort()
            refs[bucket] = ds[len(ds) // 2]
        return refs
    except Exception:
        return None


def bootstrap_from_master(font, master):
    """Master aktif hampir kosong kern-nya? Salin kerning master lain yang
    sudah jadi × skala rasio rhythm (Bold lebih gemuk → rhythm lebih rapat →
    kern ikut diskalakan). Return (n, nama_sumber, skala) atau None."""
    kern_t = font.kerning.get(master.id) or {}
    if _kern_entry_count(kern_t) >= 20:
        return None

    src_master, src_count = None, 0
    for m in font.masters:
        if m.id == master.id:
            continue
        c = _kern_entry_count(font.kerning.get(m.id) or {})
        if c > src_count:
            src_master, src_count = m, c
    if src_master is None or src_count < 40:
        return None

    scale = 1.0
    rs = _master_rhythm_ref(font, src_master)
    rt = _master_rhythm_ref(font, master)
    if rs and rt and rs["UC"] > 0 and rs["lc"] > 0:
        scale = ((rt["UC"] / rs["UC"]) + (rt["lc"] / rs["lc"])) / 2.0
        scale = max(0.7, min(1.3, scale))

    def key_name(k):
        s = str(k)
        if s.startswith("@"):
            return s
        gl = font.glyphForId_(k)
        return gl.name if gl is not None else None

    record_all = {}
    try:
        record_all = dict(font.userData[KERN_USERDATA_KEY] or {})
    except Exception:
        pass
    master_rec = dict(record_all.get(master.id, {}))

    src_dict = font.kerning.get(src_master.id) or {}
    n = 0
    for lkey in list(src_dict.keys()):
        ln = key_name(lkey)
        if ln is None:
            continue
        rights = src_dict[lkey]
        for rkey in list(rights.keys()):
            rn = key_name(rkey)
            if rn is None:
                continue
            try:
                cur = font.kerningForPair(master.id, ln, rn)
                if cur is not None and abs(float(cur)) < 1e15:
                    continue   # target sudah punya nilai utk pair ini
            except Exception:
                pass
            val = int(round(float(rights[rkey]) * scale / KERN_ROUND_TO) * KERN_ROUND_TO)
            if val == 0:
                continue
            font.setKerningForPair(master.id, ln, rn, val)
            master_rec[f"{ln}|{rn}"] = val
            n += 1

    if n:
        record_all[master.id] = master_rec
        font.userData[KERN_USERDATA_KEY] = record_all
    return (n, src_master.name, scale) if n else None


def collect_extra_pairs(font, master):
    """Multi-master coverage: pair yang sudah dikern di master LAIN ikut
    dievaluasi di master ini — semua master mencakup pair set yang sama,
    interpolasi tidak bergelombang karena pair bolong sebelah."""
    record_all = {}
    try:
        record_all = dict(font.userData[KERN_USERDATA_KEY] or {})
    except Exception:
        pass
    right_rep, left_rep = _group_reps(font)
    extra = set()
    for mid, rec in record_all.items():
        if mid == master.id:
            continue
        for key in rec.keys():
            try:
                lraw, rraw = key.split("|", 1)
            except ValueError:
                continue
            l = right_rep.get(lraw[len("@MMK_L_"):]) if lraw.startswith("@MMK_L_") else lraw
            r = left_rep.get(rraw[len("@MMK_R_"):]) if rraw.startswith("@MMK_R_") else rraw
            if l and r:
                extra.add((l, r))
    return [[l, r] for l, r in sorted(extra)]


def cross_master_report(font, master, master_rec):
    """Bandingkan nilai master ini vs record master lain untuk pair key yang
    sama: beda tanda atau rasio >3× (pada |kern|≥15) = kandidat interpolasi
    bergelombang — dilaporkan, TIDAK diubah (nilai per master boleh beda)."""
    record_all = {}
    try:
        record_all = dict(font.userData[KERN_USERDATA_KEY] or {})
    except Exception:
        pass
    mname = {m.id: m.name for m in font.masters}
    flags = []
    for mid, rec in record_all.items():
        if mid == master.id:
            continue
        for key, other_val in rec.items():
            mine = master_rec.get(key)
            if mine is None:
                continue
            a, b = int(mine), int(other_val)
            if abs(a) < 15 and abs(b) < 15:
                continue
            if (a * b < 0) or (min(abs(a), abs(b)) > 0 and
                               max(abs(a), abs(b)) / max(min(abs(a), abs(b)), 1) > 3):
                flags.append((abs(a - b), key.replace("@MMK_L_", "@").replace("@MMK_R_", "@"),
                              a, mname.get(mid, "master lain"), b))
    flags.sort(reverse=True)
    return flags


def _make_name_resolver(font):
    """Server memakai nama glyph dari TTF export (tabel post) — bisa beda
    dari nama di file .glyphs: AGL 'guillemotleft' vs nice name Glyphs
    'guillemetleft'. Resolve nama server → GSGlyph via nama langsung,
    nice name Glyphs, lalu unicode; None kalau tetap tak ketemu."""
    by_unicode = {}
    for g in font.glyphs:
        if g.unicode and g.unicode.upper() not in by_unicode:
            by_unicode[g.unicode.upper()] = g
    cache = {}

    def resolve(name):
        if name in cache:
            return cache[name]
        g = font.glyphs[name]
        if g is None:
            try:
                nice = Glyphs.niceGlyphName(name)
                if nice and nice != name:
                    g = font.glyphs[nice]
            except Exception:
                pass
        if g is None:
            try:
                info = Glyphs.glyphInfoForName(name)
                if info is not None:
                    # GSGlyphInfo.name ADALAH nice name — jalur kedua yang
                    # independen dari niceGlyphName()
                    nice2 = getattr(info, "name", None)
                    if nice2 and nice2 != name:
                        g = font.glyphs[nice2]
                    if g is None:
                        uni = getattr(info, "unicode", None)
                        if uni:
                            g = by_unicode.get(str(uni).upper())
            except Exception:
                pass
        cache[name] = g
        return g

    return resolve


def _wipe_master_kerning(font, master):
    """Hapus SELURUH kerning master ini (jalur overwrite) — per pair lewat
    removeKerningForPair supaya teregistrasi undo. Tanpa wipe, pair lama di
    luar respons server (model bilang ~0 → difilter ignore_small) tinggal di
    font tanpa tercatat → run berikutnya dikira kern manual. Return jumlah."""
    def key_name(k):
        s = str(k)
        if s.startswith("@"):
            return s
        gl = font.glyphForId_(k)
        return gl.name if gl is not None else None

    kern_dict = font.kerning.get(master.id) or {}
    targets = []
    for lkey in list(kern_dict.keys()):
        ln = key_name(lkey)
        rights = kern_dict[lkey]
        for rkey in list(rights.keys()):
            rn = key_name(rkey)
            if ln and rn:
                targets.append((ln, rn))
    n = 0
    for ln, rn in targets:
        try:
            font.removeKerningForPair(master.id, ln, rn)
            n += 1
        except Exception:
            pass
    return n


def apply_kerning(font, master, pairs, overwrite=False):
    """Apply pair hasil generate; pair sampel milik user tidak disentuh.

    overwrite=True (opsi sekali-run di panel): SELURUH kerning master ini
    dihapus dulu lalu diisi output run ini — tabel kern dan catatan userData
    dijamin 100% sinkron (menyembuhkan catatan yang tercemar, mis. sisa run
    yang crash).

    Kalau kedua glyph punya kerning group, nilai ditulis di LEVEL GRUP
    (@MMK) — satu nilai mencakup seluruh anggota (aksen ikut base-nya).
    Exception per-glyph hanya untuk yang tak bergrup.
    Exception per-glyph PENINGGALAN MESIN dari run lama dihapus kalau pair
    itu kini tercakup grup (di Glyphs, exception menimpa group kerning).
    Semua yang di-apply dicatat ke userData."""
    record_all = {}
    try:
        record_all = dict(font.userData[KERN_USERDATA_KEY] or {})
    except Exception:
        pass
    master_rec = {} if overwrite else dict(record_all.get(master.id, {}))

    resolve = _make_name_resolver(font)
    unknown = []
    written = set()
    # bulk edit ribuan pair tanpa memicu update UI per operasi —
    # enable HARUS di finally, kalau tidak UI Glyphs tinggal beku
    try:
        font.disableUpdateInterface()
    except Exception:
        pass
    try:
        if overwrite:
            _wipe_master_kerning(font, master)
        try:
            applied, removed = _apply_kerning_inner(
                font, master, pairs, resolve, master_rec, written, unknown)
        finally:
            # ditulis APA PUN yang terjadi — pair yang sudah ke-apply saat crash
            # tapi tak tercatat akan menyamar jadi "kern manual" di run berikutnya
            # dan mencemari personalisasi (kejadian nyata 2026-07-10)
            record_all[master.id] = master_rec
            font.userData[KERN_USERDATA_KEY] = record_all
    finally:
        try:
            font.enableUpdateInterface()
        except Exception:
            pass
    return applied, master_rec, removed, unknown


def _apply_kerning_inner(font, master, pairs, resolve, master_rec, written, unknown):
    applied = 0
    for p in pairs:
        if p.source == "sample":
            continue
        lg = resolve(p.left)
        rg = resolve(p.right)
        if lg is None or rg is None:
            # nama dari server tidak ada di file .glyphs (bahkan setelah
            # nice-name/unicode lookup) — lewati, jangan gagalkan seluruh run
            unknown.append(f"{p.left}+{p.right}")
            continue
        lkey = ("@MMK_L_" + lg.rightKerningGroup) if lg.rightKerningGroup else lg.name
        rkey = ("@MMK_R_" + rg.leftKerningGroup) if rg.leftKerningGroup else rg.name
        pair_id = f"{lkey}|{rkey}"
        if pair_id in written:
            continue   # dua pair kandidat memetakan ke pasangan grup yang sama
        written.add(pair_id)

        # bersihkan exception per-glyph bekas mesin yang kini tercakup grup
        if (lkey.startswith("@") or rkey.startswith("@")):
            old_key = f"{lg.name}|{rg.name}"
            old_rec = master_rec.get(old_key)
            if old_rec is not None:
                try:
                    cur = font.kerningForPair(master.id, lg.name, rg.name)
                    if cur is not None and abs(float(cur)) < 1e15 and int(cur) == int(old_rec):
                        font.removeKerningForPair(master.id, lg.name, rg.name)
                    master_rec.pop(old_key, None)
                except Exception:
                    pass

        try:
            font.setKerningForPair(master.id, lkey, rkey, p.kern)
        except Exception:
            unknown.append(f"{p.left}+{p.right}")
            continue
        master_rec[pair_id] = p.kern
        applied += 1

    # ── Cleanup exception redundan (ala MetricsMachine Round): exception
    # glyph↔glyph yang nilainya PERSIS sama dengan nilai grupnya = nol efek
    # visual, murni sampah tabel — aman dihapus by construction. ──
    removed = 0
    kern_dict = font.kerning.get(master.id) or {}
    for lkey in list(kern_dict.keys()):
        if str(lkey).startswith("@"):
            continue
        lg2 = font.glyphForId_(lkey)
        if lg2 is None or not lg2.rightKerningGroup:
            continue
        rights = kern_dict[lkey]
        for rkey in list(rights.keys()):
            if str(rkey).startswith("@"):
                continue
            rg2 = font.glyphForId_(rkey)
            if rg2 is None or not rg2.leftKerningGroup:
                continue
            try:
                gval = font.kerningForPair(
                    master.id,
                    "@MMK_L_" + lg2.rightKerningGroup,
                    "@MMK_R_" + rg2.leftKerningGroup)
                if gval is None or abs(float(gval)) > 1e15:
                    continue
                if int(round(float(rights[rkey]))) == int(round(float(gval))):
                    font.removeKerningForPair(master.id, lg2.name, rg2.name)
                    master_rec.pop(f"{lg2.name}|{rg2.name}", None)
                    removed += 1
            except Exception:
                continue

    return applied, removed


def open_kern_proof_tab(font, pairs):
    """Proof dibatasi PROOF_MAX_PAIRS ber-|kern| terbesar dan dipecah per
    baris — pair set full bisa ribuan pair, satu baris raksasa bikin tab
    berat sendiri. Return jumlah pair yang tampil."""
    resolve = _make_name_resolver(font)
    proof_context = pref("proof_context")
    show = sorted(pairs, key=lambda p: abs(p.kern), reverse=True)[:PROOF_MAX_PAIRS]
    chars = []
    for p in show:
        lg, rg = resolve(p.left), resolve(p.right)
        if lg is None or rg is None or not (lg.unicode and rg.unicode):
            continue
        l, r = chr(int(lg.unicode, 16)), chr(int(rg.unicode, 16))
        if proof_context:
            # ala MetricsMachine: pair dalam konteks kontrol, bukan telanjang —
            # HAVAH kelihatan rhythm-nya, AV doang tidak
            lctx = "H" if l.isupper() else ("n" if l.islower() else "")
            rctx = "H" if r.isupper() else ("n" if r.islower() else "")
            chars.append(f"{lctx}{l}{r}{rctx}")
        else:
            chars.append(l + r)
    if chars:
        lines = ["  ".join(chars[i:i + 8]) for i in range(0, len(chars), 8)]
        font.newTab("\n".join(lines))
    return len(chars)


# ── HOVnov calibration (vendored, trimmed HT Letterspacer area algorithm) ──
# Port dari github.com/huertatipografica/HTLetterspacer inti pengukuran area
# putih-vs-tinta — dipangkas: tanpa config-file rule engine (referensi/factor
# di-hardcode lewat HOVNOV_REFS di atas, cukup utk 6 glyph kontrol), tanpa
# tabular/UI. Kenapa vendor, bukan import modul HT Letterspacer yang sudah
# terpasang: Mindspace sengaja zero-dependency (lihat catatan di atas soal
# stdlib-only) — kalau HT Letterspacer dicopot/pindah mesin, kalibrasi ini
# tetap jalan. Titik margin direpresentasikan tuple (x, y) polos, BUKAN
# NSPoint — konsisten dgn pola intersectionsBetweenPoints((x,y),(x,y)) yang
# sudah dipakai _master_rhythm_ref di atas (tak perlu import Foundation).

def _ht_shoelace(points):
    s = 0.0
    n = len(points)
    for i in range(-1, n - 1):
        s += points[i][0] * points[i + 1][1] - points[i + 1][0] * points[i][1]
    return abs(s) * 0.5


def _ht_margins_at(layer, y):
    try:
        pts = layer.intersectionsBetweenPoints((-4000, y), (layer.width + 4000, y),
                                                components=True)
    except Exception:
        return None
    if pts is None or len(pts) <= 2:
        return None
    xs = [p.x for p in list(pts)[1:-1]]
    return (min(xs), max(xs)) if xs else None


def _ht_triangle(angle_deg, y):
    return y * math.tan(math.radians(angle_deg))


def _ht_total_margins(layer, min_y, max_y, angle, min_yref, max_yref, freq):
    """List titik (x,y) margin kiri/kanan per y-step dari min_y..max_y. Slot
    tanpa tinta diisi garis default sejajar italic angle (ala HTLetterspacer)
    supaya polygon tetap tertutup rapi. None kalau tak ada tinta sama sekali
    di zona referensi (min_yref..max_yref)."""
    origin = layer.bounds.origin.x
    top_y = layer.bounds.origin.y + layer.bounds.size.height
    end_x = origin + layer.bounds.size.width
    slant_x = _ht_triangle(angle, top_y) + origin
    default_depth = end_x - slant_x

    y = min_y
    left, right, found = [], [], False
    while y <= max_y:
        m = _ht_margins_at(layer, y)
        if m is not None:
            left.append((m[0], y))
            right.append((m[1], y))
            if min_yref <= y <= max_yref:
                found = True
        else:
            left.append((origin + _ht_triangle(angle, y) + default_depth, y))
            right.append((origin + _ht_triangle(angle, y), y))
        y += freq
    return (left, right) if found else (None, None)


def _ht_zone_margins(left, right, min_yref, max_yref):
    zl = [p for p in left if min_yref <= p[1] <= max_yref]
    zr = [p for p in right if min_yref <= p[1] <= max_yref]
    return zl, zr


def _ht_deslant(points, xheight, angle):
    if not angle:
        return points
    mline = xheight / 2.0
    t = math.tan(math.radians(angle))
    return [(p[0] - (p[1] - mline) * t, p[1]) for p in points]


def _ht_extremes(left, right):
    l = sorted(left, key=lambda p: p[0])[0]
    r = sorted(right, key=lambda p: p[0])[-1]
    return l, r


def _ht_set_depth(left, right, l_extreme, r_extreme, xheight, depth_pct,
                   min_yref, max_yref, freq):
    depth = xheight * depth_pct / 100.0
    maxdepth = l_extreme[0] + depth
    mindepth = r_extreme[0] - depth
    left = [(min(p[0], maxdepth), p[1]) for p in left]
    right = [(max(p[0], mindepth), p[1]) for p in right]

    y = left[0][1] - freq
    while y > min_yref:
        left.insert(0, (maxdepth, y))
        right.insert(0, (mindepth, y))
        y -= freq
    y = left[-1][1] + freq
    while y < max_yref:
        left.append((maxdepth, y))
        right.append((mindepth, y))
        y += freq
    return left, right


def _ht_diagonize(left, right):
    ystep = abs(left[0][1] - left[1][1]) if len(left) > 1 else HOVNOV_FREQ
    for i in range(len(left) - 1):
        if left[i + 1][0] - left[i][0] > ystep:
            left[i + 1] = (left[i][0] + ystep, left[i + 1][1])
        if right[i + 1][0] - right[i][0] < -ystep:
            right[i + 1] = (right[i][0] - ystep, right[i + 1][1])
    for i in reversed(range(len(left) - 1)):
        if left[i][0] - left[i + 1][0] > ystep:
            left[i] = (left[i + 1][0] + ystep, left[i][1])
        if right[i][0] - right[i + 1][0] < -ystep:
            right[i] = (right[i + 1][0] - ystep, right[i][1])
    return left, right


def _ht_close_counters(margin, extreme, min_yref, max_yref):
    return [(extreme[0], min_yref)] + list(margin) + [(extreme[0], max_yref)]


def _ht_sb_value(polygon, min_yref, max_yref, xheight, upm, area_param, factor):
    amplitude_y = max_yref - min_yref
    area_upm = area_param * ((upm / 1000.0) ** 2)
    white_area = area_upm * factor * 100
    prop_area = (amplitude_y * white_area) / xheight
    value = prop_area - _ht_shoelace(polygon)
    return value / amplitude_y


def _ht_space_glyph(font, master, glyph_name, ref_name, factor,
                     area_param=HOVNOV_AREA, depth_param=HOVNOV_DEPTH,
                     over_param=HOVNOV_OVER, freq=HOVNOV_FREQ):
    """Hitung (LSB, RSB) baru utk glyph_name lewat area algorithm HT
    Letterspacer, zona vertikal dari ref_name (H utk uppercase, x utk
    lowercase). None kalau gagal total (glyph/referensi kosong, aligned
    width, metric key di KEDUA sisi, atau tak ada tinta di zona referensi).

    Metric key SATU sisi (mis. V.rsb terkunci ke A demi simetri — umum
    utk huruf diagonal V/W/Y) TIDAK bikin skip total: sisi itu dikembalikan
    apa adanya (nilai LSB/RSB saat ini), sisi lain tetap dihitung normal —
    sama seperti HT_LetterSpacer_script.py asli (`setSpace`: newL/newR
    di-override balik ke `layer.LSB`/`layer.RSB` HANYA kalau metric key sisi
    itu ada). Sebelumnya di-skip total kalau salah satu terkunci — itu bug:
    kalau cuma satu sisi terkunci, sisi yg BEBAS harusnya tetap dihitung."""
    g = font.glyphs[glyph_name]
    if g is None:
        return None
    src_layer = g.layers[master.id]
    if src_layer is None or (not src_layer.paths and not src_layer.components):
        return None
    if src_layer.hasAlignedWidth():
        return None
    left_locked = g.leftMetricsKey is not None
    right_locked = g.rightMetricsKey is not None
    if left_locked and right_locked:
        return None

    ref_g = font.glyphs[ref_name]
    ref_layer = ref_g.layers[master.id] if ref_g else None
    if ref_layer is None or (not ref_layer.paths and not ref_layer.components):
        ref_layer = src_layer   # fallback: zona sendiri

    layer = src_layer.copyDecomposedLayer()
    xheight = master.xHeight
    angle = master.italicAngle
    upm = font.upm
    overshoot = xheight * over_param / 100.0

    min_yref = ref_layer.bounds.origin.y - overshoot
    max_yref = ref_layer.bounds.origin.y + ref_layer.bounds.size.height + overshoot
    min_y = layer.bounds.origin.y
    max_y = layer.bounds.origin.y + layer.bounds.size.height

    left, right = _ht_total_margins(layer, min_y, max_y, angle, min_yref, max_yref, freq)
    if left is None:
        return None
    zl, zr = _ht_zone_margins(left, right, min_yref, max_yref)

    if angle:
        zl = _ht_deslant(zl, xheight, angle)
        zr = _ht_deslant(zr, xheight, angle)
        left = _ht_deslant(left, xheight, angle)
        right = _ht_deslant(right, xheight, angle)

    l_full, r_full = _ht_extremes(left, right)
    l_ext, r_ext = _ht_extremes(zl, zr)

    zl, zr = _ht_set_depth(zl, zr, l_ext, r_ext, xheight, depth_param, min_yref, max_yref, freq)
    zl, zr = _ht_diagonize(zl, zr)
    l_poly = _ht_close_counters(zl, l_ext, min_yref, max_yref)
    r_poly = _ht_close_counters(zr, r_ext, min_yref, max_yref)

    dist_l = math.ceil(l_ext[0] - l_full[0])
    dist_r = math.ceil(r_full[0] - r_ext[0])

    new_l = math.ceil(0 - dist_l + _ht_sb_value(l_poly, min_yref, max_yref, xheight, upm, area_param, factor))
    new_r = math.ceil(0 - dist_r + _ht_sb_value(r_poly, min_yref, max_yref, xheight, upm, area_param, factor))

    if left_locked:
        # sisi terkunci: biarkan, jangan hitung ulang. round() di sini, bukan
        # cuma int() di return — LSB asli float (mis. 45.7), truncate polos
        # bikin sisi yg "harusnya gak disentuh" malah geser diam-diam ke 45.
        new_l = round(src_layer.LSB)
    if right_locked:
        new_r = round(src_layer.RSB)
    return int(new_l), int(new_r)


def _clean_num(v):
    """400.0 -> 400, 12.5 -> 12.5 — field/Font Info sebaiknya gak nampilin
    '.0' palsu utk angka bulat (paramArea/Depth/Over biasanya bulat)."""
    v = float(v)
    return int(v) if v == int(v) else v


def calibrate_hovnov(font, master, area_param=None, depth_param=None, over_param=None):
    """Kalibrasi awal H O V n o v lewat area algorithm HT Letterspacer —
    gantikan langkah manual buka script HT Letterspacer terpisah. Ditulis
    LANGSUNG ke LSB/RSB master (LSB dulu baru RSB — sama urutan seperti
    apply_spacing: LSB menggeser outline/width, RSB baru koreksi width).

    area_param/depth_param/over_param eksplisit (dari field panel) dipakai
    kalau diisi, DAN ditulis balik ke master custom parameter paramArea/
    paramDepth/paramOver — supaya font baru yang belum pernah disentuh HT
    Letterspacer pun bisa diisi langsung dari popup Mindspace, bukan lewat
    Font Info manual, dan nilainya nempel utk run berikutnya. Kalau ketiganya
    None (dipanggil tanpa lewat panel), fallback baca dari custom parameter
    yang sudah ada, atau default HOVNOV_* kalau font belum pernah diisi
    sama sekali (mis. font baru)."""
    if area_param is None:
        area_param = float(master.customParameters["paramArea"] or HOVNOV_AREA)
    if depth_param is None:
        depth_param = float(master.customParameters["paramDepth"] or HOVNOV_DEPTH)
    if over_param is None:
        over_param = float(master.customParameters["paramOver"] or HOVNOV_OVER)
    master.customParameters["paramArea"] = _clean_num(area_param)
    master.customParameters["paramDepth"] = _clean_num(depth_param)
    master.customParameters["paramOver"] = _clean_num(over_param)
    area_p, depth_p, over_p = area_param, depth_param, over_param

    results = {}
    for glyph_name in SAMPLE_GLYPHS:
        ref_name, factor = HOVNOV_REFS.get(glyph_name, (glyph_name, 1.0))
        try:
            r = _ht_space_glyph(font, master, glyph_name, ref_name, factor,
                                 area_p, depth_p, over_p)
        except Exception:
            r = None
        if r is None:
            continue
        new_l, new_r = r
        g = font.glyphs[glyph_name]
        layer = g.layers[master.id]
        layer.LSB = new_l
        layer.RSB = new_r
        results[glyph_name] = (int(round(layer.LSB)), int(round(layer.RSB)))
    return results


# ── Spacing: samples, apply, proof ─────────────────────────────────────────


def collect_spacing_samples(font, master):
    """Anchor spacing = nilai LSB/RSB SAMPLE_GLYPHS saat ini (control glyphs
    yang kamu set manual), plus glyph mana pun yang kamu KOREKSI setelah run
    sebelumnya (nilai sekarang beda dari catatan userData)."""
    record = {}
    try:
        record = dict((font.userData[SPACING_USERDATA_KEY] or {}).get(master.id, {}))
    except Exception:
        pass

    samples = {}
    for char in SAMPLE_GLYPHS:
        g = font.glyphs[char]
        if g is None:
            continue
        layer = g.layers[master.id]
        if layer is None or (not layer.paths and not layer.components):
            continue
        samples[g.name] = {"glyph": g.name,
                           "lsb": int(round(layer.LSB)), "rsb": int(round(layer.RSB))}

    # koreksi user atas output mesin = anchor tambahan
    corrections = {}
    for gname, rec in record.items():
        if gname in samples:
            continue
        g = font.glyphs[gname]
        if g is None:
            continue
        layer = g.layers[master.id]
        if layer is None:
            continue
        cur_l, cur_r = int(round(layer.LSB)), int(round(layer.RSB))
        if cur_l != int(rec[0]) or cur_r != int(rec[1]):
            corrections[gname] = {"glyph": gname, "lsb": cur_l, "rsb": cur_r}

    # Guard revert massal: koreksi sungguhan itu segelintir glyph. Kalau
    # mayoritas catatan "berubah", itu artinya user undo/revert hasil run
    # sebelumnya (atau reset massal) — catatan sudah basi: buang, jangan
    # perlakukan seluruh font sebagai anchor (bug nyata: 50/50 glyph jadi
    # sampel → server echo semua → "tidak ada yang berubah").
    if len(corrections) > max(5, int(0.3 * len(record))):
        corrections = {}
        try:
            record_all = dict(font.userData[SPACING_USERDATA_KEY] or {})
            record_all.pop(master.id, None)
            font.userData[SPACING_USERDATA_KEY] = record_all
        except Exception:
            pass

    samples.update(corrections)
    return list(samples.values())


def apply_spacing(font, master, glyphs):
    """Set LSB/RSB on the master layer of each returned glyph.

    LSB dulu baru RSB: mengubah LSB menggeser outline (width ikut), RSB
    kemudian mengoreksi width — urutan sebaliknya bikin RSB final melenceng.
    Komponen auto-aligned di composite mengikuti base glyph secara otomatis.
    Anchor (source=sample) tidak disentuh; yang di-apply dicatat ke userData.
    """
    applied = 0
    skipped = []
    record_all = {}
    try:
        record_all = dict(font.userData[SPACING_USERDATA_KEY] or {})
    except Exception:
        pass
    master_rec = dict(record_all.get(master.id, {}))

    resolve = _make_name_resolver(font)
    # bulk edit tanpa update UI per glyph; enable wajib di finally
    try:
        font.disableUpdateInterface()
    except Exception:
        pass
    try:
        for g in glyphs:
            if g.source == "sample":
                continue
            if not APPLY_REVIEW and g.status != "auto":
                continue
            # nama server = nama TTF (AGL 'guillemotleft'), bisa beda dari
            # nice name Glyphs ('guillemetleft') — resolve, jangan skip buta
            gs_glyph = resolve(g.glyph)
            if gs_glyph is None:
                skipped.append(g.glyph)
                continue
            layer = gs_glyph.layers[master.id]
            if layer is None or not layer.paths and not layer.components:
                skipped.append(g.glyph)
                continue
            if layer.components and not layer.paths:
                # pure composite (mis. Á = A + acute, auto-aligned) — metrics-nya
                # mengikuti base glyph di Glyphs; jangan diutak-atik langsung
                skipped.append(g.glyph)
                continue
            layer.LSB = g.predicted_lsb
            layer.RSB = g.predicted_rsb
            # dicatat dengan nama glyph versi FONT — deteksi koreksi run
            # berikutnya membaca font.glyphs[nama], bukan nama server
            master_rec[gs_glyph.name] = [g.predicted_lsb, g.predicted_rsb]
            applied += 1
    finally:
        # ditulis apa pun yang terjadi — glyph ter-apply yang tak tercatat
        # akan menyamar jadi "koreksi manual" di run berikutnya
        record_all[master.id] = master_rec
        font.userData[SPACING_USERDATA_KEY] = record_all
        try:
            font.enableUpdateInterface()
        except Exception:
            pass
    return applied, skipped


FOLLOW_SPACING_USERDATA_KEY = "com.mindspace.followedSpacing"  # {master.id: {glyph: [lsb, rsb]}}


def follow_spacing_suffix_variants(font, master, client, font_path):
    """Setelah predict_spacing: varian suffix tak ber-unicode (a.001, T.alt,
    dll — SEMUA yang cocok pola, bukan cuma yang kebetulan diketik user)
    ikut disesuaikan spacingnya, bukan cuma base-nya.

    Beda dari kerning group: spacing TIDAK punya mekanisme grup bawaan Glyphs
    (LSB/RSB itu properti per-glyph, bukan class), jadi ini menyalin nilai
    LSB/RSB base ke varian tiap run — bukan link permanen kayak metricsKey.
    Base berubah di run berikutnya → varian ikut lagi otomatis selama fungsi
    ini dipanggil lagi (bukan sekali set lalu lupa).

    Gate-nya SAMA seperti pewarisan kerning group: _edges_match per sisi
    (server /v1/font/edges, glyph_set=groupable) — kalau bentuknya beda
    (mis. varian swash yang memang didesain beda), sisi itu SENGAJA tidak
    disalin, bukan bug (lihat catatan _edges_match soal kelas "other").

    Anchor guard (sama prinsip dgn collect_spacing_samples/apply_kerning di
    seluruh file ini): kalau LSB/RSB varian saat ini BEDA dari catatan run
    follow SEBELUMNYA, itu koreksi manual user — DILEWATI, tidak ditimpa lagi.
    Tanpa ini, tweak manual di a.001 bakal senyap ketiban lagi tiap kali
    Jalankan Spacing — melanggar prinsip "anchor/koreksi tak pernah disentuh"
    yang dipegang di semua alur lain di file ini. Guard revert massal juga
    sama seperti collect_spacing_samples: kalau >30% catatan "berubah",
    anggap user revert, buang catatan lawas alih-alih block semuanya.

    Return (n_followed, rejected_list) — glyph rejected dicatat "nama·sisi"
    sama seperti ensure_groups, biar formatnya konsisten di dialog."""
    if not pref("auto_groups"):
        return 0, []

    record = {}
    try:
        record = dict((font.userData[FOLLOW_SPACING_USERDATA_KEY] or {}).get(master.id, {}))
    except Exception:
        pass

    candidates = []   # (glyph, base_glyph)
    for g in font.glyphs:
        name = g.name
        if g.unicode or "." not in name or name.startswith("."):
            continue
        base_name = name.split(".", 1)[0]
        if "_" in base_name:
            continue
        base = font.glyphs[base_name]
        if base is None:
            continue
        layer = g.layers[master.id]
        blayer = base.layers[master.id]
        if layer is None or blayer is None:
            continue
        if not (layer.paths or layer.components):
            continue
        if not (blayer.paths or blayer.components):
            continue
        candidates.append((g, base))

    if not candidates:
        return 0, []

    # deteksi koreksi manual SEBELUM query server — gak perlu tunggu network
    # kalau semua kandidat toh bakal dilewati
    manual = set()
    for g, base in candidates:
        rec = record.get(g.name)
        if rec is None:
            continue
        layer = g.layers[master.id]
        cur_l, cur_r = int(round(layer.LSB)), int(round(layer.RSB))
        if int(rec[0]) != cur_l or int(rec[1]) != cur_r:
            manual.add(g.name)

    if len(manual) > max(5, int(0.3 * len(record))):
        manual = set()   # revert massal — catatan basi, jangan block semuanya
        record = {}

    todo = [(g, base) for g, base in candidates if g.name not in manual]
    if not todo:
        return 0, []

    try:
        edges = call_server(lambda: client.font_edges(font_path)).get("edges", {})
    except Exception:
        edges = {}
    if not _font_alive(font) or not edges:
        return 0, []

    followed, rejected = 0, []
    new_record = dict(record)
    for g, base in todo:
        ge, be = edges.get(g.name), edges.get(base.name)
        if ge is None or be is None:
            continue
        layer = g.layers[master.id]
        blayer = base.layers[master.id]
        left_ok = _edges_match(ge.get("left"), be.get("left"))
        right_ok = _edges_match(ge.get("right"), be.get("right"))
        if not left_ok and not right_ok:
            rejected.append(g.name)
            continue
        if left_ok:
            layer.LSB = blayer.LSB
        else:
            rejected.append(f"{g.name}·kiri")
        if right_ok:
            layer.RSB = blayer.RSB
        else:
            rejected.append(f"{g.name}·kanan")
        new_record[g.name] = [int(round(layer.LSB)), int(round(layer.RSB))]
        followed += 1

    try:
        record_all = dict(font.userData[FOLLOW_SPACING_USERDATA_KEY] or {})
        record_all[master.id] = new_record
        font.userData[FOLLOW_SPACING_USERDATA_KEY] = record_all
    except Exception:
        pass

    return followed, rejected


def _rhythm_proof_line(glyphs, repeat=3):
    """Baris proof: SEMUA 9 kombinasi bigram dari `glyphs` (bukan cuma
    beberapa dipilih tangan — sebelumnya ada 'A' nyelip padahal kalibrasi
    cuma nyentuh H/O/V, gak pernah kena A). Bigram-bigram digabung TANPA
    spasi (spasi = lebar glyph 'space', bukan bagian ritme yg mau dibaca —
    kebanyakan spasi motong-motong ritmenya jadi susah dibaca) jadi satu
    kata panjang, diulang `repeat` kali (dipisah 1 spasi per ulangan) biar
    cukup panjang buat mata membandingkan ritme di rentang lebar."""
    import itertools
    pairs = "".join("".join(p) for p in itertools.product(glyphs, repeat=2))
    return " ".join([pairs] * repeat)


HOVNOV_PROOF_LINES = [
    _rhythm_proof_line(["H", "O", "V"]),   # straight vs round vs diagonal
    _rhythm_proof_line(["n", "o", "v"]),   # versi lowercase
]
PROOF_LINES = HOVNOV_PROOF_LINES + [
    "the quick brown fox jumps over the lazy dog",
    "Typography handgloves",
]


def open_spacing_proof_tab(font):
    font.newTab("\n".join(PROOF_LINES))


def open_hovnov_proof_tab(font):
    """Tab Edit khusus H O V n o v — dibuka tiap Kalibrasi/Terapkan supaya
    rhythm-nya langsung KELIHATAN, tak perlu jalankan Spacing penuh dulu."""
    font.newTab("\n".join(HOVNOV_PROOF_LINES))


# ── Alur run (dipanggil tombol panel; return string ringkas utk baris status)


def run_spacing():
    font = Glyphs.font
    if not font:
        Message("Tidak ada font yang terbuka.", "Mindspace Spacing")
        return "Spacing: tidak ada font terbuka"

    master = font.selectedFontMaster
    client = MindspaceClient(server_url=SERVER_URL, api_key=API_KEY)

    if not call_server(client.health_check):
        Message(
            f"Tidak bisa terhubung ke {SERVER_URL}\n"
            "Pastikan Mindspace server nyala di Mac mini.",
            "Mindspace Spacing — Connection Error",
        )
        return "Spacing: server offline"

    samples = collect_spacing_samples(font, master)
    use_personalize = len(samples) >= SPACING_MIN_SAMPLES

    try:
        font_path = export_master_ttf(font, master)
    except Exception as e:
        Message(f"Gagal export font ke TTF:\n{e}", "Mindspace Spacing — Export Error")
        return "Spacing: export gagal"

    try:
        glyphs, meta = call_server(lambda: client.predict_spacing(
            font_path,
            glyph_set=pref("glyph_set"),
            min_confidence=SPACING_MIN_CONFIDENCE,
            round_to=SPACING_ROUND_TO,
            samples=samples if use_personalize else None,
        ))
    except Exception as e:
        cleanup_ttf(font_path)
        Message(f"Error dari server:\n{e}", "Mindspace Spacing — API Error")
        return "Spacing: error server"

    if not glyphs:
        cleanup_ttf(font_path)
        Message("Tidak ada prediksi spacing yang dikembalikan.", "Mindspace Spacing")
        return "Spacing: 0 glyph"

    if not _font_alive(font):
        cleanup_ttf(font_path)
        return _abort_font_closed("Spacing")

    applied, skipped = apply_spacing(font, master, glyphs)

    # varian suffix tak ber-unicode (a.001, T.alt, dst — predict_spacing tak
    # pernah menyentuhnya, glyph_set dibangun dari font.unicode_map) ikut
    # disesuaikan dari base-nya di sini. HARUS sebelum cleanup_ttf — butuh
    # font_path yang sama buat POST /v1/font/edges (LSB/RSB tak mengubah
    # outline, jadi TTF pre-apply_spacing masih akurat buat cek edge).
    followed, follow_rejected = follow_spacing_suffix_variants(font, master, client, font_path)
    cleanup_ttf(font_path)

    # glyph spasi tidak punya tinta — modelnya tak bisa memprediksi, jadi
    # server menyarankan lebar via aturan Tracy (≈ advance 'i' hasil
    # personalisasi); di-apply hanya kalau kamu belum menyentuh space
    # (belum pernah tercatat atau masih sama dengan catatan)
    space_line = ""
    sw = meta.get("suggested_space_width")
    if sw:
        space = font.glyphs["space"]
        if space is not None:
            layer = space.layers[master.id]
            if layer is not None:
                record = {}
                try:
                    record = dict((font.userData[SPACING_USERDATA_KEY] or {}).get(master.id, {}))
                except Exception:
                    pass
                rec = record.get("space")
                untouched = rec is None or int(round(layer.width)) == int(rec[0])
                if untouched:
                    layer.width = sw
                    record["space"] = [sw, sw]
                    try:
                        record_all = dict(font.userData[SPACING_USERDATA_KEY] or {})
                        record_all[master.id] = record
                        font.userData[SPACING_USERDATA_KEY] = record_all
                    except Exception:
                        pass
                    space_line = f"Space width: {sw} (aturan Tracy: ≈ advance 'i')\n"
                else:
                    space_line = f"Space width: kamu set manual, tidak disentuh (saran: {sw})\n"

    open_spacing_proof_tab(font)

    gen    = [g for g in glyphs if g.source != "sample"]
    auto   = sum(1 for g in gen if g.status == "auto")
    review = sum(1 for g in gen if g.status == "review")
    big    = sorted(gen, key=lambda g: abs(g.delta_lsb) + abs(g.delta_rsb), reverse=True)[:5]
    big_txt = ", ".join(f"{g.glyph} ({g.delta_lsb:+d}/{g.delta_rsb:+d})" for g in big)

    if meta["personalized"]:
        anchors = ", ".join(s["glyph"] for s in samples[:8])
        style_line = (
            f"Mode: PERSONAL — {meta['n_samples_used']} anchor dipakai ({anchors}).\n"
            "Semua glyph lain digenerate mengikuti rhythm anchor-mu.\n"
        )
        mode = "PERSONAL"
    else:
        style_line = (
            f"Mode: GLOBAL — anchor baru {len(samples)} "
            f"(butuh ≥{SPACING_MIN_SAMPLES}).\n"
            f"Set spacing {', '.join(SAMPLE_GLYPHS)} manual dulu untuk hasil personal.\n"
        )
        mode = "GLOBAL"

    follow_line = f"Varian suffix ikut (a.001 dst): {followed} glyph"
    if follow_rejected:
        follow_line += f" | tidak diikuti (tepi beda): {', '.join(follow_rejected[:6])}"
        if len(follow_rejected) > 6:
            follow_line += f" +{len(follow_rejected) - 6}"
    follow_line += "\n"

    Message(
        f"Master: {master.name}\n"
        f"{style_line}\n"
        f"{space_line}"
        f"Applied: {applied} glyphs (anchor-mu tidak disentuh)\n"
        f"Skipped (tidak ada di font/kosong): {len(skipped)}\n"
        f"Auto: {auto}   Review: {review}\n"
        f"{follow_line}"
        f"Perubahan terbesar: {big_txt}\n\n"
        "Cek rhythm di proof tab. Ada yang kurang pas? Koreksi LSB/RSB-nya\n"
        "langsung, jalankan lagi — koreksimu otomatis jadi anchor baru.\n"
        "Setelah spacing beres, klik Jalankan Kern.\n"
        "Batal total: tutup tanpa save / File → Revert.",
        "Mindspace Spacing — Done",
    )
    return f"Spacing: {applied} glyph ({followed} suffix ikut) · {mode}"


def run_kern(overwrite=False):
    font = Glyphs.font
    if not font:
        Message("Tidak ada font yang terbuka.", "Mindspace Kern")
        return "Kern: tidak ada font terbuka"

    master = font.selectedFontMaster
    client = MindspaceClient(server_url=SERVER_URL, api_key=API_KEY)

    if not call_server(client.health_check):
        Message(
            f"Tidak bisa terhubung ke {SERVER_URL}\n"
            "Pastikan Mindspace server nyala di Mac mini.",
            "Mindspace Kern — Connection Error",
        )
        return "Kern: server offline"

    # overwrite: semua kern lama = output mesin, tidak ada yang jadi sampel
    samples = [] if overwrite else collect_kern_samples(font, master)
    use_personalize = len(samples) >= KERN_MIN_SAMPLES

    # strip kern mesin HANYA selama export (restore di finally — jendela
    # tanpa-kern cuma sepanjang generate TTF)
    stripped = _strip_machine_kern(font, master)
    try:
        font_path = export_master_ttf(font, master)
    except Exception as e:
        Message(f"Gagal export font ke TTF:\n{e}", "Mindspace Kern — Export Error")
        return "Kern: export gagal"
    finally:
        _restore_kern(font, master, stripped)

    # ── Spacing gate (ala Kern On): kerning di atas spacing berantakan itu
    # kompensasi salah alamat — cek dulu, tolak kalau masih jauh. ────────────
    if pref("check_spacing"):
        check = call_server(lambda: client.check_spacing(font_path))
        if not _font_alive(font):
            cleanup_ttf(font_path)
            return _abort_font_closed("Kern")
        if check is not None:
            mean_dev, upm = check
            if mean_dev > SPACING_MAX_DEV * upm:
                cleanup_ttf(font_path)
                Message(
                    f"Spacing font ini kelihatan belum rapi:\n"
                    f"rata-rata deviasi sidebearing ~{mean_dev:.0f} unit/sisi "
                    f"(ambang {SPACING_MAX_DEV * upm:.0f}).\n\n"
                    "Rapikan spacing dulu (manual atau klik Jalankan Spacing) —\n"
                    "kerning di atas spacing yang belum beres cuma menambal\n"
                    "masalah di tempat yang salah.\n\n"
                    "Kalau yakin mau lanjut, matikan 'Cek spacing dulu' di panel.",
                    "Mindspace Kern — Spacing Belum Rapi",
                )
                return "Kern: spacing belum rapi (gate)"

    # ── Kerning groups otomatis (mengisi grup yang kosong) ──────────────────
    groups_line = ensure_groups(font, master, client, font_path)
    if not _font_alive(font):
        cleanup_ttf(font_path)
        return _abort_font_closed("Kern")

    # ── Bootstrap master baru dari master yang sudah jadi ───────────────────
    # (di-skip saat overwrite: user minta output model murni, bukan salinan)
    if pref("bootstrap_masters") and not overwrite:
        boot = bootstrap_from_master(font, master)
        if boot:
            n_copied, src_name, scale = boot
            cleanup_ttf(font_path)
            Message(
                f"Master: {master.name}\n"
                f"{(groups_line + chr(10)) if groups_line else ''}\n"
                f"Bootstrap: {n_copied} pair disalin dari master '{src_name}'\n"
                f"× skala {scale:.2f} (rasio rhythm kedua master).\n\n"
                "Review/koreksi hasilnya, lalu jalankan lagi —\n"
                "koreksimu jadi sampel personalisasi master ini.",
                "Mindspace Kern — Bootstrap Master",
            )
            return f"Kern: bootstrap {n_copied} pair dari '{src_name}'"

    # ── Belum cukup sampel → buka tab saran pair buat dikern manual ─────────
    if not use_personalize and not pref("global_fallback") and not overwrite:
        try:
            data = call_server(lambda: client.suggest_samples(font_path, count=SUGGEST_COUNT))
        except Exception as e:
            Message(f"Error dari server:\n{e}", "Mindspace Kern — API Error")
            return "Kern: error server"
        finally:
            cleanup_ttf(font_path)
        if not _font_alive(font):
            return _abort_font_closed("Kern")
        sugg = data.get("suggestions", [])
        if sugg:
            chunks = [s["chars"] for s in sugg]
            lines = ["  ".join(chunks[i:i + 6]) for i in range(0, len(chunks), 6)]
            lines.append("")
            words = [s.get("example") or s["chars"] for s in sugg]
            lines += [" ".join(words[i:i + 6]) for i in range(0, len(words), 6)]
            font.newTab("\n".join(lines))
        Message(
            f"Master: {master.name}\n"
            f"{(groups_line + chr(10)) if groups_line else ''}"
            f"Sampel kern manual-mu baru {len(samples)} pair — "
            f"butuh ≥{KERN_MIN_SAMPLES} untuk personalisasi.\n\n"
            f"{len(sugg)} pair paling berharga dibuka di tab baru\n"
            "(baris bawahnya kata contoh nyata — kern dalam konteks).\n"
            "Kern semampunya sesuai selera, lalu klik Jalankan Kern lagi.\n\n"
            "(Mau langsung kerning global tanpa sampel? Centang\n"
            "'Kern global tanpa sampel' di panel.)",
            "Mindspace Kern — Kern Sampel Dulu",
        )
        return f"Kern: {len(sugg)} saran pair dibuka (sampel {len(samples)}/{KERN_MIN_SAMPLES})"

    extra_pairs = collect_extra_pairs(font, master)

    try:
        pairs, meta = call_server(lambda: client.predict_kern(
            font_path,
            pair_set=pref("pair_set"),
            max_pairs=20000,
            min_confidence=KERN_MIN_CONFIDENCE,
            round_to=KERN_ROUND_TO,
            ignore_small=IGNORE_SMALL,
            samples=samples if use_personalize else None,
            extra_pairs=extra_pairs,
        ))
    except Exception as e:
        Message(f"Error dari server:\n{e}", "Mindspace Kern — API Error")
        return "Kern: error server"
    finally:
        cleanup_ttf(font_path)

    if not pairs:
        Message("Tidak ada kern pairs yang dikembalikan.", "Mindspace Kern")
        return "Kern: 0 pair"

    if not _font_alive(font):
        return _abort_font_closed("Kern")

    applied, master_rec, n_removed, unknown = apply_kerning(font, master, pairs,
                                                            overwrite=overwrite)
    gen_pairs = [p for p in pairs if p.source != "sample"]
    n_proof = open_kern_proof_tab(font, gen_pairs)
    proof_line = (f"Proof: {n_proof} pair terbesar (dari {len(gen_pairs)})\n"
                  if len(gen_pairs) > PROOF_MAX_PAIRS else "")

    if unknown:
        contoh = ", ".join(unknown[:5]) + (f" +{len(unknown) - 5}" if len(unknown) > 5 else "")
        unknown_line = (f"Dilewati {len(unknown)} pair — nama glyph dari server "
                        f"tidak ada di font: {contoh}\n")
    else:
        unknown_line = ""

    flags = cross_master_report(font, master, master_rec)
    if flags:
        worst = "\n".join(f"  {k}: {master.name} {a:+d} vs {mn} {b:+d}"
                           for _, k, a, mn, b in flags[:5])
        xmaster_line = (f"\n⚠ {len(flags)} pair beda liar antar master "
                        f"(risiko interpolasi bergelombang):\n{worst}\n")
    else:
        xmaster_line = ""

    auto   = sum(1 for p in pairs if p.status == "auto" and p.source != "sample")
    review = sum(1 for p in pairs if p.status == "review" and p.source != "sample")

    if overwrite:
        style_line = (
            "Mode: OVERWRITE — semua kern lama dianggap output mesin dan\n"
            "ditimpa prediksi global; catatan run lama di-reset bersih.\n"
        )
        mode = "OVERWRITE"
    elif meta["personalized"]:
        cal = meta.get("calibration") or {}
        a = cal.get("a", 1.0)
        pct = abs(1.0 - a) * 100
        arah = "lebih ringan" if a < 1.0 else "lebih kuat"
        style_line = (
            f"Mode: PERSONAL — {meta['n_samples_used']} sampel style-mu dipakai.\n"
            f"Kalibrasi: kerning-mu ~{pct:.0f}% {arah} dari model global (a={a:.2f}).\n"
        )
        mode = "PERSONAL"
    else:
        style_line = (
            f"Mode: GLOBAL — sampel manual baru {len(samples)} pair "
            f"(butuh ≥{KERN_MIN_SAMPLES} untuk personalisasi).\n"
            "Kern ±15 pair manual sesuai seleramu lalu run lagi →\n"
            "hasilnya mengikuti style-mu, bukan rata-rata corpus.\n"
        )
        mode = "GLOBAL"

    preserved = "semua pair ditimpa" if overwrite else "kern manual-mu tidak disentuh"
    Message(
        f"Master: {master.name}\n"
        f"{(groups_line + chr(10)) if groups_line else ''}"
        f"{style_line}\n"
        f"Applied: {applied} kern pairs ({preserved};\n"
        f"pair antar glyph bergrup ditulis di level grup — aksen ikut base)\n"
        f"Auto: {auto}   Review: {review}"
        f"{f'   Exception redundan dihapus: {n_removed}' if n_removed else ''}\n"
        f"{unknown_line}"
        f"{proof_line}\n"
        f"{xmaster_line}"
        "Koreksi pair hasil generate yang kurang pas, lalu jalankan lagi —\n"
        "koreksimu otomatis jadi sampel style baru.",
        "Mindspace Kern — Done",
    )
    skip_note = f" · {len(unknown)} dilewati" if unknown else ""
    return f"Kern: {applied} pair · {mode}{skip_note}"


# ── Panel ──────────────────────────────────────────────────────────────────

try:
    import vanilla
except Exception:
    vanilla = None


class MindspacePanel(object):

    CHECKBOXES = [
        # (pref key, label)
        ("check_spacing",     "Cek spacing dulu sebelum kern (gate)"),
        ("auto_groups",       "Auto kerning groups + suffix variant (a.001 dst)"),
        ("bootstrap_masters", "Bootstrap master baru dari master lain"),
        ("proof_context",     "Proof pakai konteks (HAVAH)"),
        ("global_fallback",   "Kern global tanpa sampel (fallback)"),
    ]

    def __init__(self):
        self.running = False
        self.w = vanilla.FloatingWindow((310, 572), "Mindspace")

        y = 12
        self.w.serverDot = vanilla.TextBox((14, y, 16, 17), "●")
        self.w.serverText = vanilla.TextBox((30, y, -48, 17), "memeriksa server…")
        self.w.refreshButton = vanilla.Button((-42, y - 3, 28, 22), "↻",
                                              callback=self.refreshServer)
        y += 28

        self.w.hovnovLabel = vanilla.TextBox((14, y, -14, 17),
                                             "Kalibrasi HOVnov (HT Letterspacer)",
                                             sizeStyle="small")
        y += 20

        # Area/Depth/Over: master custom parameter paramArea/paramDepth/
        # paramOver. Font baru (belum pernah disentuh HT Letterspacer) tidak
        # punya nilai ini — field terisi default 400/15/0 dan bisa diedit
        # di sini langsung, tak perlu buka Font Info manual (lihat
        # calibrate_hovnov: field ini ditulis balik ke custom parameter).
        self.w.hovnovAreaLabel = vanilla.TextBox((14, y + 2, 34, 17), "Area", sizeStyle="small")
        self.w.hovnovArea = vanilla.EditText((48, y, 32, 20), "", sizeStyle="small")
        self.w.hovnovDepthLabel = vanilla.TextBox((90, y + 2, 38, 17), "Depth", sizeStyle="small")
        self.w.hovnovDepth = vanilla.EditText((128, y, 32, 20), "", sizeStyle="small")
        self.w.hovnovOverLabel = vanilla.TextBox((170, y + 2, 34, 17), "Over", sizeStyle="small")
        self.w.hovnovOver = vanilla.EditText((204, y, 32, 20), "", sizeStyle="small")
        for ctrl, tip in (
            (self.w.hovnovAreaLabel, HOVNOV_TOOLTIPS["area"]),
            (self.w.hovnovArea, HOVNOV_TOOLTIPS["area"]),
            (self.w.hovnovDepthLabel, HOVNOV_TOOLTIPS["depth"]),
            (self.w.hovnovDepth, HOVNOV_TOOLTIPS["depth"]),
            (self.w.hovnovOverLabel, HOVNOV_TOOLTIPS["over"]),
            (self.w.hovnovOver, HOVNOV_TOOLTIPS["over"]),
        ):
            try:
                ctrl.getNSTextField().setToolTip_(tip)
            except Exception:
                pass
        y += 26

        # grid 2 kolom (UC: H O V | lc: n o v) — muat nilai LSB/RSB skrg,
        # diedit langsung di sini, ditulis balik via tombol Terapkan; jadi
        # anchor bisa dicek/di-tweak tanpa pindah ke Font view tiap kali.
        self.hovnov_fields = {}
        cols = [SAMPLE_GLYPHS[0:3], SAMPLE_GLYPHS[3:6]]
        col_x = [14, 155]
        row_y0 = y
        for col, glyphs_in_col in zip(col_x, cols):
            yy = row_y0
            for glyph_name in glyphs_in_col:
                lbl = vanilla.TextBox((col, yy + 2, 16, 17), glyph_name, sizeStyle="small")
                lsb = vanilla.EditText((col + 18, yy, 48, 20), "", sizeStyle="small")
                rsb = vanilla.EditText((col + 70, yy, 48, 20), "", sizeStyle="small")
                setattr(self.w, f"hovnov_{glyph_name}_lbl", lbl)
                setattr(self.w, f"hovnov_{glyph_name}_lsb", lsb)
                setattr(self.w, f"hovnov_{glyph_name}_rsb", rsb)
                self.hovnov_fields[glyph_name] = (lsb, rsb)
                yy += 22
        y = row_y0 + 3 * 22 + 6

        self.w.hovnovCalibrate = vanilla.Button((14, y, 130, 22), "Kalibrasi",
                                                callback=self.hovnovCalibrateCallback)
        self.w.hovnovApply = vanilla.Button((155, y, -14, 22), "Terapkan",
                                            callback=self.hovnovApplyCallback)
        y += 30
        self.w.lineHovnov = vanilla.HorizontalLine((14, y, -14, 1))
        y += 12

        self.w.spacingButton = vanilla.Button((14, y, -14, 32), "Jalankan Spacing",
                                              callback=self.spacingCallback)
        y += 40
        self.w.kernButton = vanilla.Button((14, y, -14, 32), "Jalankan Kern",
                                           callback=self.kernCallback)
        y += 44
        self.w.line1 = vanilla.HorizontalLine((14, y, -14, 1))
        y += 10

        self.w.pairSetLabel = vanilla.TextBox((14, y + 2, 140, 17), "Pair set (kern)")
        self.w.pairSet = vanilla.PopUpButton((158, y, -14, 20), PAIR_SETS,
                                             callback=self.pairSetCallback)
        try:
            self.w.pairSet.set(PAIR_SETS.index(pref("pair_set")))
        except ValueError:
            self.w.pairSet.set(0)
        y += 28

        self.w.glyphSetLabel = vanilla.TextBox((14, y + 2, 140, 17), "Glyph set (spacing)")
        self.w.glyphSet = vanilla.PopUpButton((158, y, -14, 20), GLYPH_SETS,
                                              callback=self.glyphSetCallback)
        try:
            self.w.glyphSet.set(GLYPH_SETS.index(pref("glyph_set")))
        except ValueError:
            self.w.glyphSet.set(0)
        y += 30

        for key, label in self.CHECKBOXES:
            cb = vanilla.CheckBox((14, y, -14, 20), label, value=pref(key),
                                  callback=self.checkboxCallback, sizeStyle="small")
            cb._prefKey = key
            setattr(self.w, "cb_" + key, cb)
            y += 22

        # sekali-run, sengaja TIDAK disimpan ke defaults dan auto-uncheck
        # setelah run — overwrite bukan mode yang boleh ketinggalan nyala;
        # diberi jarak dari opsi persisten di atasnya supaya beda kelas
        y += 6
        self.w.cb_overwrite = vanilla.CheckBox(
            (14, y, -14, 20), "⚠ Timpa SEMUA kern lama (sekali run)",
            value=False, sizeStyle="small")
        y += 22

        y += 6
        self.w.line2 = vanilla.HorizontalLine((14, y, -14, 1))
        y += 8
        self.w.status = vanilla.TextBox((14, y, -14, 30), "Siap.", sizeStyle="small")

        self.w.bind("close", self.windowClosed)
        self.w.open()
        self.refreshServer(None)
        self._loadHovNovFields()

    # ── HOVnov calibration ──

    def _loadHovNovFields(self):
        """Isi field LSB/RSB (+ Area/Depth/Over) dari nilai yang ADA di font
        sekarang — dipanggil saat panel dibuka dan sesudah Kalibrasi/Terapkan,
        supaya field selalu mencerminkan state font, bukan run terakhir. Font
        baru yang belum pernah disentuh HT Letterspacer tidak punya custom
        parameter paramArea/Depth/Over — field jatuh ke default HOVNOV_*."""
        font = Glyphs.font
        master = font.selectedFontMaster if font else None

        if master is not None:
            self.w.hovnovArea.set(str(_clean_num(master.customParameters["paramArea"] or HOVNOV_AREA)))
            self.w.hovnovDepth.set(str(_clean_num(master.customParameters["paramDepth"] or HOVNOV_DEPTH)))
            self.w.hovnovOver.set(str(_clean_num(master.customParameters["paramOver"] or HOVNOV_OVER)))
        else:
            self.w.hovnovArea.set(str(HOVNOV_AREA))
            self.w.hovnovDepth.set(str(HOVNOV_DEPTH))
            self.w.hovnovOver.set(str(HOVNOV_OVER))

        for glyph_name, (lsb_field, rsb_field) in self.hovnov_fields.items():
            layer = None
            if font and master is not None:
                g = font.glyphs[glyph_name]
                layer = g.layers[master.id] if g else None
            if layer is None:
                lsb_field.set("")
                rsb_field.set("")
            else:
                lsb_field.set(str(int(round(layer.LSB))))
                rsb_field.set(str(int(round(layer.RSB))))

    def hovnovCalibrateCallback(self, sender):
        font = Glyphs.font
        if not font:
            Message("Tidak ada font yang terbuka.", "Kalibrasi HOVnov")
            return
        master = font.selectedFontMaster
        try:
            area_p = float(self.w.hovnovArea.get())
            depth_p = float(self.w.hovnovDepth.get())
            over_p = float(self.w.hovnovOver.get())
        except ValueError:
            Message("Area/Depth/Over harus angka.", "Kalibrasi HOVnov")
            return
        try:
            results = calibrate_hovnov(font, master, area_p, depth_p, over_p)
        except Exception as e:
            import traceback
            Message(f"Error kalibrasi:\n{e}\n\n{traceback.format_exc()[-500:]}",
                    "Kalibrasi HOVnov — Error")
            return
        self._loadHovNovFields()
        open_hovnov_proof_tab(font)
        missing = [g for g in SAMPLE_GLYPHS if g not in results]
        note = f" (dilewati: {', '.join(missing)})" if missing else ""
        self._setStatus(f"Kalibrasi HOVnov: {len(results)}/6 glyph{note} · {time.strftime('%H:%M')}")

    def hovnovApplyCallback(self, sender):
        """Tulis balik nilai yang kamu edit di field ke LSB/RSB font —
        untuk tweak manual langsung dari popup tanpa buka Font view."""
        font = Glyphs.font
        if not font:
            Message("Tidak ada font yang terbuka.", "Terapkan HOVnov")
            return
        master = font.selectedFontMaster
        applied, errors = 0, []
        for glyph_name, (lsb_field, rsb_field) in self.hovnov_fields.items():
            g = font.glyphs[glyph_name]
            layer = g.layers[master.id] if g else None
            if layer is None:
                continue
            try:
                new_l = int(round(float(lsb_field.get())))
                new_r = int(round(float(rsb_field.get())))
            except ValueError:
                errors.append(glyph_name)
                continue
            layer.LSB = new_l   # LSB dulu, RSB baru — sama urutan seperti apply_spacing
            layer.RSB = new_r
            applied += 1
        self._loadHovNovFields()
        if applied:
            open_hovnov_proof_tab(font)
        note = f" (gagal parse: {', '.join(errors)})" if errors else ""
        self._setStatus(f"Terapkan HOVnov: {applied} glyph{note} · {time.strftime('%H:%M')}")

    # ── status & server ──

    def _setStatus(self, text):
        # try/except penuh: panel bisa DITUTUP user di tengah run (run loop
        # dipompa selama menunggu server) — jangan mati gara-gara status
        try:
            self.w.status.set(text)
            # paksa repaint SEKARANG — bagian ber-API-Glyphs tetap nge-block
            # main thread, tanpa ini teks baru muncul setelah selesai
            self.w.getNSWindow().display()
        except Exception:
            pass

    def refreshServer(self, sender):
        # health check bisa nunggu 5 dtk kalau server mati — kasih tahu dulu
        self.w.serverText.set("memeriksa…")
        try:
            self.w.getNSWindow().display()
        except Exception:
            pass
        client = MindspaceClient(SERVER_URL, API_KEY)
        ok = client.health_check()
        self.w.serverText.set("terhubung" if ok else f"offline — {SERVER_URL}")
        try:
            from AppKit import NSColor
            color = NSColor.systemGreenColor() if ok else NSColor.systemRedColor()
            self.w.serverDot.getNSTextField().setTextColor_(color)
        except Exception:
            self.w.serverDot.set("●" if ok else "○")

    # ── opsi ──

    def pairSetCallback(self, sender):
        set_pref("pair_set", PAIR_SETS[sender.get()])

    def glyphSetCallback(self, sender):
        set_pref("glyph_set", GLYPH_SETS[sender.get()])

    def checkboxCallback(self, sender):
        set_pref(sender._prefKey, bool(sender.get()))

    # ── run ──

    def spacingCallback(self, sender):
        self._run("Spacing", run_spacing)

    def kernCallback(self, sender):
        overwrite = bool(self.w.cb_overwrite.get())
        durasi = {"full": "full — bisa 10-25 mnt",
                  "latin_extended": "latin_extended — ±3-5 mnt",
                  "latin_basic": "latin_basic — ±30 dtk"}
        self._run("Kern", lambda: run_kern(overwrite=overwrite),
                  note=durasi.get(pref("pair_set")))
        self.w.cb_overwrite.set(False)

    def _drain_stale_events(self):
        """Klik/ketikan yang menumpuk selama freeze di-dispatch SETELAH
        callback selesai — saat itu flag running sudah False, jadi guard
        biasa tembus dan klik ganda memicu run kedua. Buang antriannya."""
        try:
            from AppKit import NSApplication, NSEventMaskAny
            from Foundation import NSDate, NSDefaultRunLoopMode
            app = NSApplication.sharedApplication()
            for _ in range(1000):
                ev = app.nextEventMatchingMask_untilDate_inMode_dequeue_(
                    NSEventMaskAny, NSDate.distantPast(), NSDefaultRunLoopMode, True)
                if ev is None:
                    break
        except Exception:
            pass

    def _run(self, label, fn, note=None):
        if self.running:
            return   # re-entrancy; klik ter-queue diurus _drain_stale_events
        self.running = True
        self.w.spacingButton.enable(False)
        self.w.kernButton.enable(False)
        extra = f" ({note})" if note else ""
        self._setStatus(f"{label}: berjalan{extra}… Glyphs tetap bisa dipakai.")
        try:
            result = fn()
        except Exception as e:
            import traceback
            Message(f"Error tak terduga:\n{e}\n\n{traceback.format_exc()[-600:]}",
                    f"Mindspace {label} — Error")
            result = f"{label}: error — {e}"
        finally:
            self._drain_stale_events()
            try:
                self.w.spacingButton.enable(True)
                self.w.kernButton.enable(True)
            except Exception:
                pass   # panel ditutup di tengah run
            try:
                self._loadHovNovFields()   # cerminkan rhythm anchor terkini
            except Exception:
                pass
            self.running = False
        stamp = time.strftime("%H:%M")
        self._setStatus(f"{result or (label + ': selesai')} · {stamp}")

    def windowClosed(self, sender):
        try:
            Glyphs.MindspacePanel = None
        except Exception:
            pass


def main():
    if vanilla is None:
        Message(
            "Modul 'vanilla' tidak termuat di Python Glyphs.\n"
            "Cek Plugin Manager → Modules → Vanilla (lalu restart Glyphs).",
            "Mindspace — vanilla tidak ada",
        )
        return
    panel = getattr(Glyphs, "MindspacePanel", None)
    if panel is not None:
        try:
            panel.w.show()
            panel.refreshServer(None)
            return
        except Exception:
            pass   # window sudah mati → buat baru
    Glyphs.MindspacePanel = MindspacePanel()


main()
