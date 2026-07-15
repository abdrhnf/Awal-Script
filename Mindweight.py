#MenuTitle: Mindweight
# -*- coding: utf-8 -*-
"""
Mindweight — generate DRAFT master weight baru dari satu master.

Gambar Regular → panel → pilih target (preset per weight class, atau stem
unit eksplisit ala RMX) → Generate: master baru dibuat di file yang sama,
outline ditebalkan/ditipiskan via Cape Weightor-style engine (OffsetCurve
native Glyphs + unslant/reslant, height normalization, anchor/guide restore)
dengan distribusi outer/inner dari corpus ekstrem (Thin/Black), parameter
per-glyph dari server Mindspace (/v1/weight/glyph-params).

Hasil = DRAFT untuk dirapikan manual (ala RMX Tools). Setelah jadi:
jalankan Mindspace → Jalankan Spacing di master baru, lalu Kern.
Rollback: hapus master baru / ⌘Z / tutup tanpa save.
"""
import os
import json
import math
import time
import uuid
import tempfile
import urllib.request
import urllib.error

# ── CONFIG ──────────────────────────────────────────────────────────────────
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

WEIGHT_PRESETS = [
    (100, "Thin",       0.295),
    (200, "ExtraLight", 0.435),
    (300, "Light",      0.700),
    (500, "Medium",     1.238),
    (600, "SemiBold",   1.451),
    (700, "Bold",       1.598),
    (800, "ExtraBold",  1.868),
    (900, "Black",      2.094),
]
PRESET_LABELS = [f"{name} ({wght}) — {ratio:.2f}× stem"
                 for wght, name, ratio in WEIGHT_PRESETS]

PREF_PREFIX = "com.bahasatype.mindweight."
DEFAULTS = {
    "target_wght":       "700",
    "keep_compatible":   True,   # keepCompatibleOutlines di OffsetCurve
    "suggest_instances": True,   # tampilkan distribusi geometris De Groot
    "insert_instances":  False,  # sekalian buat GSInstance-nya
    "offset_x":          "20",
    "offset_y":          "16",
    "position":          "35",    # outer %, Cape-style
    "width_pct":         "102",
    "panel_advanced_open": False,  # ingat status buka/tutup panel Lanjutan
    "sync_xy": True,  # Sync X & Y ala Cape Weightor — geser satu, dua2nya ikut
}


def pref(key):
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


class MindweightClient:
    """Stdlib urllib saja — Python embedded Glyphs tidak andal melihat
    paket pip (pelajaran Mindspace)."""

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

    def _post_font(self, endpoint, font_path, fields, timeout=120):
        boundary = uuid.uuid4().hex
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
            data=bytes(body), method="POST",
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

    def weight_params(self, font_path, target_wght=0, target_stem=0.0,
                      instance_steps=3):
        return self._post_font("/v1/weight/params", font_path, {
            "target_wght": str(int(target_wght)),
            "target_stem": str(float(target_stem)),
            "instance_steps": str(int(instance_steps)),
        })

    def glyph_weight_params(self, font_path, target_wght=0, target_stem=0.0):
        return self._post_font("/v1/weight/glyph-params", font_path, {
            "target_wght": str(int(target_wght)),
            "target_stem": str(float(target_stem)),
            "max_glyphs": "20000",
        })

    def glyph_weight_params_multi(self, font_path, targets=""):
        """Semua anchor terlatih (mis. 100/700/900) sekali panggil — dipakai
        slider weight per-glyph: fetch sekali, interpolasi lokal antar
        anchor tanpa round-trip server per geser."""
        return self._post_font("/v1/weight/glyph-params-multi", font_path, {
            "targets": targets,
            "max_glyphs": "20000",
        }, timeout=180)


def call_server(fn):
    """Network di thread belakang + main thread memompa NSRunLoop —
    Glyphs tetap responsif (pola sama dengan Mindspace). Tanpa PyObjC
    (exec-test) fallback join()."""
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
    """Font Info yang ADA tapi kosong bikin Glyphs menolak export —
    isi placeholder sementara (pola Mindspace)."""
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
    tmp_dir = tempfile.mkdtemp(prefix="mindweight_")
    matching = [i for i in font.instances
                if i.linkStyle == master.name or i.name == master.name]
    if not matching:
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
    raise RuntimeError(f"generate() sukses tapi tidak ada .ttf di {tmp_dir}")


def cleanup_ttf(font_path):
    try:
        os.unlink(font_path)
        os.rmdir(os.path.dirname(font_path))
    except Exception:
        pass


def _font_alive(font):
    try:
        return any(f == font for f in Glyphs.fonts)
    except Exception:
        return True


def _glyph_stem(layer):
    """Perkiraan tebal stem satu glyph: median lebar run tersempit per baris
    di beberapa ketinggian tinta (utk baris konsistensi mode Manual)."""
    try:
        b = layer.bounds
        y0, h = b.origin.y, b.size.height
    except Exception:
        return None
    if not h:
        return None
    vals = []
    for f in (0.2, 0.35, 0.5, 0.65, 0.8):
        xs = _ray_runs(layer, (-4000, y0 + h * f), (layer.width + 4000, y0 + h * f))
        if xs is None:
            continue
        runs = [xs[i + 1].x - xs[i].x for i in range(0, len(xs), 2)]
        if runs:
            vals.append(min(runs))
    return _median(vals)


# ── Override manual per glyph (mode Manual+AI) ──────────────────────────────
# Disimpan per FONT (bukan per master): sekali kamu override glyph, semua
# Generate berikutnya menghormatinya sampai dihapus. Prioritas di
# run_generate: override user > AI per-glyph > global.
OVERRIDES_KEY = "com.bahasatype.mindweight.overrides"


def _get_overrides(font):
    try:
        return dict(font.userData[OVERRIDES_KEY] or {})
    except Exception:
        return {}


def _set_override(font, gname, params):
    """params dict {dx,dy,position,width_ratio} — None = hapus override."""
    ov = _get_overrides(font)
    if params is None:
        ov.pop(gname, None)
    else:
        ov[gname] = params
    font.userData[OVERRIDES_KEY] = ov


# ── Self-check: ukur stem native via intersections (tanpa server) ──────────


def _ray_runs(layer, p1, p2):
    """Titik potong ray dengan outline → list koordinat (tanpa ujung ray).
    None kalau tidak bisa/ganjil."""
    try:
        pts = layer.intersectionsBetweenPoints(p1, p2, components=True)
    except Exception:
        return None
    if pts is None or len(pts) < 4:
        return None
    inner = list(pts)[1:-1]
    if len(inner) % 2:
        return None
    return inner


def _median(vals):
    if not vals:
        return None
    vals = sorted(vals)
    return vals[len(vals) // 2]


def measure_master_anatomy(font, master):
    """H_stem / n_stem / O_vwall / O_hwall dalam unit font, dari outline
    langsung (pola intersections yang sama dengan rhythm/bootstrap
    Mindspace). None per metrik kalau tak terukur."""
    out = {}

    def layer_of(ch):
        g = font.glyphs[ch]
        if g is None:
            return None
        l = g.layers[master.id]
        return l if (l is not None and (l.paths or l.components)) else None

    lH, ln, lO = layer_of("H"), layer_of("n"), layer_of("O")
    cap, xh = master.capHeight, master.xHeight

    # H: baris ber-2-run (crossbar otomatis lolos karena 1 run)
    widths = []
    if lH is not None:
        for f in (0.10, 0.15, 0.20, 0.25, 0.30, 0.70, 0.75, 0.80):
            xs = _ray_runs(lH, (-4000, cap * f), (lH.width + 4000, cap * f))
            if xs is not None and len(xs) == 4:
                widths += [xs[1].x - xs[0].x, xs[3].x - xs[2].x]
    out["H_stem"] = _median(widths)

    widths = []
    if ln is not None:
        for f in (0.15, 0.25, 0.35, 0.45):
            xs = _ray_runs(ln, (-4000, xh * f), (ln.width + 4000, xh * f))
            if xs is not None and len(xs) == 4:
                widths.append(xs[1].x - xs[0].x)   # run kiri = stem
    out["n_stem"] = _median(widths)

    widths, heights = [], []
    if lO is not None:
        for f in (0.40, 0.50, 0.60):
            xs = _ray_runs(lO, (-4000, cap * f), (lO.width + 4000, cap * f))
            if xs is not None and len(xs) == 4:
                widths += [xs[1].x - xs[0].x, xs[3].x - xs[2].x]
        for f in (0.40, 0.50, 0.60):
            x = lO.width * f
            ys = _ray_runs(lO, (x, -1000), (x, cap + 1000))
            if ys is not None and len(ys) == 4:
                heights += [ys[1].y - ys[0].y, ys[3].y - ys[2].y]
    out["O_vwall"] = _median(widths)
    out["O_hwall"] = _median(heights)
    return out


# ── Generate ────────────────────────────────────────────────────────────────


def _glyph_category(font, glyph):
    """uc / lc / other — dari unicode; varian suffix (a.ss01) ikut base."""
    uni = glyph.unicode
    name = glyph.name
    if not uni and "." in name and not name.startswith("."):
        base = font.glyphs[name.split(".", 1)[0]]
        if base is not None:
            uni = base.unicode
    if uni:
        try:
            ch = chr(int(uni, 16))
            if ch.isupper():
                return "uc"
            if ch.islower():
                return "lc"
        except Exception:
            pass
    return "other"


def _weight_axis_index(font):
    for i, ax in enumerate(font.axes):
        try:
            if ax.axisTag == "wght" or "weight" in str(ax.name).lower():
                return i
        except Exception:
            continue
    return 0 if len(font.axes) else None


def _is_off_curve(node):
    """Robust off-curve detection across Glyphs versions."""
    try:
        t = node.type
    except Exception:
        return False
    try:
        if t == GSOFFCURVE:
            return True
    except Exception:
        pass
    try:
        return str(t).lower() == "offcurve"
    except Exception:
        return False


def _path_is_closed(path):
    try:
        return bool(path.closed)
    except AttributeError:
        pass
    try:
        nodes = list(path.nodes)
        if len(nodes) < 2:
            return False
        a, b = nodes[0].position, nodes[-1].position
        return abs(a.x - b.x) < 0.01 and abs(a.y - b.y) < 0.01
    except Exception:
        return True


def _inside_point_for_path(path):
    """Return point inside a path for outer/inner contour classification."""
    try:
        from Foundation import NSPoint
    except Exception:
        return None
    try:
        bp = path.bezierPath
    except Exception:
        return None
    if bp is None:
        return None
    nodes = list(path.nodes)
    n = len(nodes)
    if n < 2:
        return None

    if not _path_is_closed(path):
        on_curve = [nn for nn in nodes if not _is_off_curve(nn)]
        picks = on_curve if on_curve else nodes
        mid = picks[len(picks) // 2]
        return NSPoint(mid.position.x, mid.position.y)

    eps = 1.0
    for i, node in enumerate(nodes):
        if _is_off_curve(node):
            continue
        prev_n = nodes[(i - 1) % n]
        next_n = nodes[(i + 1) % n]
        dx = next_n.position.x - prev_n.position.x
        dy = next_n.position.y - prev_n.position.y
        L = (dx * dx + dy * dy) ** 0.5
        if L < 1e-6:
            continue
        px, py = -dy / L, dx / L
        nx, ny = node.position.x, node.position.y
        for sign in (1.0, -1.0):
            cand = NSPoint(nx + sign * eps * px, ny + sign * eps * py)
            try:
                if bp.containsPoint_(cand):
                    return cand
            except Exception:
                pass
    return None


def _classify_contours(layer):
    """Return (outer_paths, inner_paths) using even-odd containment."""
    paths = list(layer.paths)
    if not paths:
        return [], []
    inside_pts = [_inside_point_for_path(p) for p in paths]
    bezier_ps = []
    for p in paths:
        try:
            bezier_ps.append(p.bezierPath)
        except Exception:
            bezier_ps.append(None)

    outer, inner = [], []
    for i, path in enumerate(paths):
        point = inside_pts[i]
        if point is None:
            outer.append(path)
            continue
        nesting = 0
        for j, other_bp in enumerate(bezier_ps):
            if j == i or other_bp is None:
                continue
            try:
                if other_bp.containsPoint_(point):
                    nesting += 1
            except Exception:
                pass
        (outer if nesting % 2 == 0 else inner).append(path)
    return outer, inner


def _offset_layer(OffsetCurve, layer, dx, dy, keep):
    try:
        OffsetCurve.offsetLayer_offsetX_offsetY_makeStroke_autoStroke_position_metrics_error_shadow_capStyleStart_capStyleEnd_keepCompatibleOutlines_(
            layer, dx, dy, False, False, 0.5, None, None, None, 0, 0, keep
        )
        return True
    except AttributeError:
        pass
    try:
        OffsetCurve.offsetLayer_offsetX_offsetY_makeStroke_position_(
            layer, dx, dy, False, 0.5
        )
        return True
    except Exception:
        return False


def _offset_layer_distributed(OffsetCurve, layer, dx, dy, keep, outer_share):
    """Offset outer and inner contours separately.

    outer_share = 1.0 keeps counters stable and grows the silhouette.
    outer_share = 0.0 keeps the silhouette stable and shrinks counters.
    Corpus Black sits around 0.35, so most growth goes inward.
    """
    if abs(dx) < 1e-6 and abs(dy) < 1e-6:
        return True
    if not list(layer.paths):
        return True

    outer_paths, inner_paths = _classify_contours(layer)
    outer_originals = [pp.copy() for pp in outer_paths]
    inner_originals = [pp.copy() for pp in inner_paths]

    f_outer = 2.0 * outer_share
    f_inner = 2.0 * (1.0 - outer_share)

    def _process(originals, fx, fy):
        for pp in list(layer.paths):
            layer.shapes.remove(pp)
        if not originals:
            return []
        for pp in originals:
            layer.shapes.append(pp.copy())
        if abs(fx) > 1e-6 or abs(fy) > 1e-6:
            if not _offset_layer(OffsetCurve, layer, fx, fy, keep):
                return None
        return [pp.copy() for pp in layer.paths]

    offset_outer = _process(outer_originals, dx * f_outer, dy * f_outer)
    if offset_outer is None:
        return False
    offset_inner = _process(inner_originals, dx * f_inner, dy * f_inner)
    if offset_inner is None:
        return False

    for pp in list(layer.paths):
        layer.shapes.remove(pp)
    for pp in offset_outer:
        layer.shapes.append(pp.copy())
    for pp in offset_inner:
        layer.shapes.append(pp.copy())
    return True


def _layer_bounds_tuple(layer):
    try:
        b = layer.bounds
        return (float(b.origin.x), float(b.origin.y),
                float(b.size.width), float(b.size.height))
    except Exception:
        return (0.0, 0.0, 0.0, 0.0)


def _italic_angle(master):
    for attr in ("italicAngle", "italicAngleValue"):
        try:
            v = float(getattr(master, attr))
            if abs(v) > 0.001:
                return v
        except Exception:
            pass
    return 0.0


def _capture_layer_state(layer):
    """Cape Weightor-style safety snapshot for rollback and restoration."""
    state = {
        "paths": [p.copy() for p in list(layer.paths)],
        "components": [c.copy() for c in list(layer.components)],
        "width": float(getattr(layer, "width", 0.0) or 0.0),
        "lsb": None,
        "rsb": None,
        "bounds": _layer_bounds_tuple(layer),
        "anchors": [],
        "guides": [],
    }
    try:
        state["lsb"] = float(layer.LSB)
    except Exception:
        pass
    try:
        state["rsb"] = float(layer.RSB)
    except Exception:
        pass
    try:
        for a in list(layer.anchors):
            state["anchors"].append(a.copy())
    except Exception:
        pass
    try:
        for guide in list(layer.guides):
            state["guides"].append(guide.copy())
    except Exception:
        pass
    return state


def _replace_layer_shapes(layer, paths, components=None):
    try:
        for sh in list(layer.shapes):
            layer.shapes.remove(sh)
    except Exception:
        try:
            for p in list(layer.paths):
                layer.shapes.remove(p)
            for c in list(layer.components):
                layer.shapes.remove(c)
        except Exception:
            pass
    for p in paths:
        layer.shapes.append(p.copy())
    if components:
        for c in components:
            layer.shapes.append(c.copy())


def _restore_layer_state(layer, state):
    _replace_layer_shapes(layer, state.get("paths", []), state.get("components", []))
    try:
        layer.width = state["width"]
    except Exception:
        pass
    _restore_layer_anchors(layer, state)
    _restore_layer_guides(layer, state)


def _restore_layer_anchors(layer, state):
    try:
        for a in list(layer.anchors):
            layer.anchors.remove(a)
    except Exception:
        pass
    try:
        for a in state.get("anchors", []):
            layer.anchors.append(a.copy())
    except Exception:
        pass


def _restore_layer_guides(layer, state):
    try:
        for guide in list(layer.guides):
            layer.guides.remove(guide)
    except Exception:
        pass
    try:
        for guide in state.get("guides", []):
            layer.guides.append(guide.copy())
    except Exception:
        pass


def _place_anchors_cape(layer, state, orig_x, orig_w):
    """Restore anchors after outline transforms.

    Cape Weightor keeps anchors useful by repositioning them by relative X in
    the old outline box. This is intentionally conservative: if geometry is
    weird, fall back to the copied anchor positions rather than deleting them.
    """
    _restore_layer_anchors(layer, state)
    if not state.get("anchors") or orig_w <= 0:
        return
    nbx, nby, nbw, nbh = _layer_bounds_tuple(layer)
    if nbw <= 0:
        return
    try:
        for old, new in zip(state.get("anchors", []), list(layer.anchors)):
            ox = float(old.position.x)
            rel = (ox - orig_x) / orig_w
            new.position.x = nbx + rel * nbw
    except Exception:
        _restore_layer_anchors(layer, state)


def _scale_layer_to_original_height(layer, orig_y, orig_h):
    if orig_h <= 0:
        return
    nbx, nby, nbw, nbh = _layer_bounds_tuple(layer)
    if nbh <= 0:
        return
    s = orig_h / nbh
    if abs(s - 1.0) < 0.001:
        return
    ty = orig_y - nby * s
    try:
        layer.applyTransform((1, 0, 0, s, 0, ty))
    except Exception:
        pass


def _resolve_glyph_params(g, cat, glyph_params, offsets, outer_share, adv_ratio,
                          overrides):
    """Resolve final (dx, dy, position, width_ratio) for one glyph, in the
    priority order used everywhere Mindweight commits a glyph: manual
    override (font.userData) > AI per-glyph > global/manual fallback.
    Shared by run_generate (whole-master) and applySelectedCallback
    (in-place, selected glyphs only) so the two commit paths never diverge.

    Returns (dx, dy, position, width_ratio, is_fallback, is_risk, is_override).
    """
    is_fallback = is_risk = is_override = False
    gp = glyph_params.get(g.name)
    if gp:
        dx, dy = gp.get("dx", 0.0), gp.get("dy", 0.0)
        position = max(0.0, min(1.0, float(gp.get("position", outer_share))))
        width_ratio = float(gp.get("width_ratio", adv_ratio))
        if gp.get("source") == "fallback":
            is_fallback = True
        if gp.get("risk"):
            is_risk = True
    else:
        o = offsets.get(cat) or offsets["other"]
        dx, dy = o["dx"], o["dy"]
        position = outer_share
        width_ratio = adv_ratio
        is_fallback = True
    ov = overrides.get(g.name)
    if ov:
        # editan manual user menang atas AI/global
        dx = float(ov.get("dx", dx))
        dy = float(ov.get("dy", dy))
        position = max(0.0, min(1.0, float(ov.get("position", position))))
        width_ratio = float(ov.get("width_ratio", width_ratio))
        is_override = True
    return dx, dy, position, width_ratio, is_fallback, is_risk, is_override


def _apply_cape_weight_layer(OffsetCurve, layer, dx, dy, keep, outer_share,
                             width_ratio, master):
    """Apply Mindweight parameters through a Cape Weightor-style pipeline.

    The important pieces are not the raw offset itself, but the surrounding
    craft: unslant before offset, restore height, keep anchors/guides sane,
    and roll back the layer if any operation fails.
    """
    if not list(layer.paths):
        return True

    state = _capture_layer_state(layer)
    orig_x, orig_y, orig_w, orig_h = state["bounds"]
    angle = _italic_angle(master)
    shear = math.tan(math.radians(angle)) if abs(angle) > 0.001 else 0.0
    unslanted = False
    try:
        if shear:
            layer.applyTransform((1, 0, -shear, 1, 0, 0))
            unslanted = True
        ux, uy, uw, uh = _layer_bounds_tuple(layer)
        if not _offset_layer_distributed(
                OffsetCurve, layer, dx, dy, keep, outer_share):
            raise RuntimeError("OffsetCurve failed")
        if not keep:
            # Bersihkan self-intersection dari offset outer/inner yg
            # dikerjakan TERPISAH (garis potong di pojok tajam/junction
            # diagonal v/w/x/y) — persis gejala "blind expand" yg dikeluhkan
            # user. HANYA kalau "Outline tetap kompatibel" MATI, krn
            # removeOverlap ubah struktur titik = merusak kompatibilitas
            # interpolasi yg jadi tujuan checkbox itu. Non-fatal: outline
            # yg belum dibersihkan tetap lebih baik drpd operasi gagal total.
            try:
                layer.correctPathDirection()
                layer.removeOverlap()
            except Exception:
                pass
        _scale_layer_to_original_height(layer, uy, uh)
        if unslanted:
            layer.applyTransform((1, 0, shear, 1, 0, 0))
            unslanted = False

        if state["width"] > 0 and abs(width_ratio - 1.0) > 0.001:
            try:
                layer.width = round(state["width"] * width_ratio)
            except Exception:
                pass
        # Cape's adjust-sidebearing behavior: keep the old left sidebearing
        # after width adjustment so the glyph grows into its intended body.
        if state.get("lsb") is not None:
            try:
                layer.LSB = state["lsb"]
            except Exception:
                pass
        _place_anchors_cape(layer, state, orig_x, orig_w)
        _restore_layer_guides(layer, state)
        return True
    except Exception:
        if unslanted:
            try:
                layer.applyTransform((1, 0, shear, 1, 0, 0))
            except Exception:
                pass
        _restore_layer_state(layer, state)
        return False


def run_generate(target_wght=0, target_stem=0.0, manual=None):
    import objc

    font = Glyphs.font
    if not font:
        Message("Tidak ada font yang terbuka.", "Mindweight")
        return "tidak ada font terbuka"

    src_master = font.selectedFontMaster
    client = MindweightClient(SERVER_URL, API_KEY)

    if manual is None and not call_server(client.health_check):
        Message(f"Tidak bisa terhubung ke {SERVER_URL}\n"
                "Pastikan Mindspace server nyala.", "Mindweight — Connection Error")
        return "server offline"

    try:
        OffsetCurve = objc.lookUpClass("GlyphsFilterOffsetCurve")
    except Exception:
        Message("Filter OffsetCurve tidak ditemukan di Glyphs ini.",
                "Mindweight — Error")
        return "filter tidak ada"

    # nama master baru + guard duplikat
    preset_names = {w: n for w, n, _ in WEIGHT_PRESETS}
    if target_stem:
        new_name = f"Stem {int(round(target_stem))}"
    else:
        new_name = preset_names.get(int(target_wght), f"W{target_wght}")
    if any(m.name == new_name for m in font.masters):
        Message(f"Master bernama '{new_name}' sudah ada — hapus/rename dulu\n"
                "kalau mau generate ulang (tidak menimpa otomatis).",
                "Mindweight — Master Sudah Ada")
        return f"master '{new_name}' sudah ada"

    if manual is None:
        try:
            font_path = export_master_ttf(font, src_master)
        except Exception as e:
            Message(f"Gagal export font ke TTF:\n{e}", "Mindweight — Export Error")
            return "export gagal"

        try:
            res = call_server(lambda: client.glyph_weight_params(
                font_path,
                target_wght=0 if target_stem else target_wght,
                target_stem=target_stem))
        except Exception as e:
            Message(f"Error dari server:\n{e}", "Mindweight — API Error")
            return "error server"
        finally:
            cleanup_ttf(font_path)

        if not _font_alive(font):
            Message("Font ditutup di tengah run — tidak ada yang dibuat.",
                    "Mindweight — Dibatalkan")
            return "dibatalkan (font ditutup)"

        global_res = res.get("global", res)
        glyph_params = res.get("glyphs", {})
        mode_line = f"AI glyph-level path-only · coverage {res.get('coverage', {})}"
    else:
        dx = float(manual.get("dx", 0.0))
        dy = float(manual.get("dy", 0.0))
        pos = max(0.0, min(1.0, float(manual.get("position", 0.5))))
        width_ratio = max(0.01, float(manual.get("width_ratio", 1.0)))
        global_res = {
            "k": 0.0,
            "position": pos,
            "adv_ratio": width_ratio,
            "offsets": {
                "uc": {"dx": dx, "dy": dy},
                "lc": {"dx": dx, "dy": dy},
                "other": {"dx": dx, "dy": dy},
            },
            "warnings": [],
            "predicted": {},
            "instances": [],
        }
        glyph_params = {}
        res = {"coverage": {"mode": "manual"}}
        mode_line = "Cape-style manual · AI hanya isi nilai"
    offsets = global_res["offsets"]
    keep = pref("keep_compatible")
    outer_share = max(0.0, min(1.0, float(global_res.get("position", 0.5))))
    adv_ratio = float(global_res.get("adv_ratio", 1.0))
    overrides = _get_overrides(font)

    # ── buat master baru + copy semua layer, lalu offset ────────────────────
    new_master = src_master.copy()
    new_master.name = new_name
    font.masters.append(new_master)
    ax = _weight_axis_index(font)
    if ax is not None:
        try:
            axes = list(new_master.axes)
            if target_stem:
                axes[ax] = int(round(float(src_master.axes[ax]) * global_res["k"]))
            else:
                axes[ax] = int(target_wght)
            new_master.axes = axes
        except Exception:
            pass

    n_offset = n_skip_comp = n_skip_mixed = n_fail = n_fallback = n_override = 0
    risk_names = []
    try:
        font.disableUpdateInterface()
    except Exception:
        pass
    try:
        for g in font.glyphs:
            src_layer = g.layers[src_master.id]
            if src_layer is None:
                continue
            new_layer = src_layer.copy()
            g.layers[new_master.id] = new_layer
            if new_layer.components and not new_layer.paths:
                n_skip_comp += 1   # auto-align: metrics & bentuk ikut base
                continue
            if new_layer.components and new_layer.paths:
                n_skip_mixed += 1
                continue
            if not new_layer.paths:
                continue
            cat = _glyph_category(font, g)
            dx, dy, glyph_outer, glyph_width, is_fb, is_risk, is_ov = \
                _resolve_glyph_params(g, cat, glyph_params, offsets,
                                      outer_share, adv_ratio, overrides)
            if is_fb:
                n_fallback += 1
            if is_risk:
                risk_names.append(g.name)
                try:
                    g.color = 0
                except Exception:
                    pass
            if is_ov:
                n_override += 1
            if _apply_cape_weight_layer(
                    OffsetCurve, new_layer, dx, dy, keep,
                    glyph_outer, glyph_width, new_master):
                n_offset += 1
            else:
                n_fail += 1
    finally:
        try:
            font.enableUpdateInterface()
        except Exception:
            pass

    # ── self-check: ukur ulang master baru, banding prediksi server ─────────
    achieved = measure_master_anatomy(font, new_master)
    pred = global_res.get("predicted", {})
    check_lines = []
    for m in ("H_stem", "n_stem", "O_vwall", "O_hwall"):
        a, p = achieved.get(m), pred.get(m)
        if a is not None and p is not None:
            check_lines.append(f"  {m}: target {p:.0f} → tercapai {a:.0f} "
                               f"({a - p:+.0f}u)")
    check_txt = "\n".join(check_lines) if check_lines else "  (tidak terukur)"

    warn_txt = ""
    if global_res.get("warnings"):
        warn_txt = "\n⚠ " + "\n⚠ ".join(global_res["warnings"]) + "\n"
    if risk_names:
        warn_txt += ("\n⚠ Review glyph risk: " +
                     ", ".join(risk_names[:30]) +
                     (" …" if len(risk_names) > 30 else "") + "\n")
        try:
            font.newTab(" ".join("/" + n for n in risk_names[:80]))
        except Exception:
            pass

    # ── saran instance (teori geometris Luc(as) de Groot) ───────────────────
    inst_txt = ""
    stems = global_res.get("instances") or []
    if pref("suggest_instances") and stems and ax is not None:
        s0 = res.get("global", res).get("anatomy", res.get("anatomy", {})).get("H_stem")
        s1 = s0 * global_res["k"] if s0 else None
        try:
            w0 = float(src_master.axes[ax])
            w1 = float(new_master.axes[ax])
            vals = [w0 + (st - s0) / (s1 - s0) * (w1 - w0) for st in stems]
            inst_txt = ("\nSaran instance intermediate (progresi geometris "
                        "De Groot):\n  stem " +
                        ", ".join(f"{st:.0f}" for st in stems) +
                        f"\n  ≈ nilai axis {', '.join(f'{v:.0f}' for v in vals)}\n")
            if pref("insert_instances"):
                n_ins = 0
                for st, v in zip(stems, vals):
                    inst = GSInstance()
                    inst.name = f"{new_name[:1]}{int(v)}"
                    try:
                        iaxes = list(inst.axes)
                        iaxes[ax] = v
                        inst.axes = iaxes
                        font.instances.append(inst)
                        n_ins += 1
                    except Exception:
                        pass
                inst_txt += f"  → {n_ins} instance dibuat.\n"
        except Exception:
            pass

    Message(
        f"Master baru: '{new_name}' (dari '{src_master.name}', "
        f"k={global_res['k']:.2f})\n\n"
        f"Mode: Cape engine + glyph-level path-only · coverage {res.get('coverage', {})}\n"
        f"Global fallback: outer {outer_share:.2f} · inner {1.0 - outer_share:.2f} "
        f"· width ×{adv_ratio:.3f}\n"
        f"Outline dioffset: {n_offset} glyph"
        f"{f' · gagal: {n_fail}' if n_fail else ''}\n"
        f"Composite auto-align dilewati (ikut base): {n_skip_comp}\n\n"
        f"Mixed path+component dilewati: {n_skip_mixed} · fallback: {n_fallback}"
        f"{f' · override manual: {n_override}' if n_override else ''}\n"
        f"Self-check stem (unit font):\n{check_txt}\n"
        f"{warn_txt}"
        f"{inst_txt}\n"
        "Ini DRAFT — engine-nya sekarang Cape-style; tetap rapikan joint/counter gelap manual.\n"
        "Lanjut: pilih master baru → Mindspace: Jalankan Spacing, lalu Kern\n"
        "(bootstrap kern antar master otomatis).\n"
        "Rollback: hapus master ini di Font Info → Masters, atau ⌘Z.",
        "Mindweight — Draft Master Jadi",
    )
    return (f"'{new_name}' jadi · {n_offset} glyph · "
            f"H {achieved.get('H_stem') or 0:.0f}u")


# ── Panel ──────────────────────────────────────────────────────────────────

try:
    import vanilla
except Exception:
    vanilla = None


class MindweightPanel(object):

    def __init__(self):
        self.running = False
        self.w = vanilla.FloatingWindow((310, 400), "Mindweight")

        self._ai = None            # cache respons glyph-params terakhir (1 anchor)
        self._ai_multi = None      # cache semua anchor (100/700/900) utk slider
        self._slider_wght = 700.0  # posisi slider Ketebalan saat ini
        self._snap = {}            # snapshot layer utk preview non-destruktif
        self._snap_layers = {}     # layerId -> layer object (utk cleanup saat tutup/pindah)
        self._live_layer_key = None  # layerId yg lagi live-preview via slider
        self._committed_keys = set()  # layerId yg sudah di-Terapkan (jangan auto-revert)
        self._position_override = None      # override manual slider Outer/Inner (0.0-1.0)
        self._position_override_key = None  # layerId tempat override itu berlaku
        self._dx_override = None            # override manual slider X (unit font)
        self._dy_override = None            # override manual slider Y (unit font)
        self._dxdy_override_key = None      # layerId tempat override X/Y berlaku
        self._advanced_widgets = []

        def _adv(name, widget):
            setattr(self.w, name, widget)
            self._advanced_widgets.append(widget)

        # ── Selalu terlihat: status server, target, tombol utama ───────────
        y = 12
        self.w.serverDot = vanilla.TextBox((14, y, 16, 17), "●")
        self.w.serverText = vanilla.TextBox((30, y, -48, 17), "memeriksa server…")
        self.w.refreshButton = vanilla.Button((-42, y - 3, 28, 22), "↻",
                                              callback=self.refreshServer)
        y += 30
        self.w.targetLabel = vanilla.TextBox((14, y + 2, 60, 17), "Target")
        self.w.target = vanilla.PopUpButton((76, y, -14, 20), PRESET_LABELS,
                                            callback=self.targetCallback)
        wghts = [str(w) for w, _, _ in WEIGHT_PRESETS]
        try:
            self.w.target.set(wghts.index(pref("target_wght")))
        except ValueError:
            self.w.target.set(5)   # Bold
        y += 28
        self.w.generateButton = vanilla.Button((14, y, -14, 32),
                                               "Generate Draft Master",
                                               callback=self.generateCallback)
        y += 40
        self.w.toggleButton = vanilla.Button((14, y, -14, 20), "▸ Lanjutan",
                                             callback=self.toggleAdvancedCallback,
                                             sizeStyle="small")
        y += 28
        self._adv_top = y

        # ── Lanjutan (disembunyikan default): stem override, opsi, manual ───
        _adv("line", vanilla.HorizontalLine((14, y, -14, 1)))
        y += 8
        _adv("stemLabel", vanilla.TextBox((14, y + 2, 170, 17),
                                          "Target stem H (unit, opsional)"))
        _adv("stem", vanilla.EditText((188, y, -14, 22), "", sizeStyle="small",
                                      placeholder="override"))
        y += 32
        for key, label in (
            ("keep_compatible",   "Outline tetap kompatibel (interpolasi)"),
            ("suggest_instances", "Sarankan instance (teori De Groot)"),
            ("insert_instances",  "Insert instance otomatis"),
        ):
            cb = vanilla.CheckBox((14, y, -14, 20), label, value=pref(key),
                                  callback=self.checkboxCallback, sizeStyle="small")
            cb._prefKey = key
            _adv("cb_" + key, cb)
            y += 22
        y += 8
        _adv("line2", vanilla.HorizontalLine((14, y, -14, 1)))
        y += 8

        # ── Manual per glyph (basis Cape Weightor, nilai default AI) ────────
        _adv("mTitle", vanilla.TextBox((14, y, 150, 16), "Manual — glyph terpilih",
                                       sizeStyle="small"))
        _adv("mLoadAI", vanilla.Button((-132, y - 3, 118, 20), "Muat nilai AI",
                                       callback=self.loadAICallback,
                                       sizeStyle="small"))
        y += 22
        _adv("mInfo", vanilla.TextBox((14, y, -14, 16), "(pilih glyph → Ambil)",
                                      sizeStyle="small"))
        y += 10
        _adv("mSliderCardTop", vanilla.HorizontalLine((14, y, -14, 1)))
        y += 10
        _adv("mSliderLabel", vanilla.TextBox((14, y, 90, 18), "Ketebalan",
                                             sizeStyle="regular"))
        _adv("mSliderVal", vanilla.TextBox((-56, y, 42, 18), "700",
                                           sizeStyle="regular"))
        y += 20
        _adv("mSlider", vanilla.Slider((14, y, -14, 22), minValue=100,
                                       maxValue=900, value=self._slider_wght,
                                       callback=self.sliderCallback,
                                       sizeStyle="regular"))
        y += 30
        _adv("mSyncXY", vanilla.CheckBox((14, y, -14, 20), "Sync X & Y",
                                         value=pref("sync_xy"),
                                         callback=self.syncXYCallback,
                                         sizeStyle="small"))
        y += 26
        _adv("mXLabel", vanilla.TextBox((14, y, 90, 18), "X", sizeStyle="regular"))
        _adv("mXVal", vanilla.TextBox((-56, y, 42, 18), "0.0", sizeStyle="regular"))
        y += 20
        _adv("mXSlider", vanilla.Slider((14, y, -14, 22), minValue=-150,
                                        maxValue=150, value=0,
                                        callback=self.xCallback,
                                        sizeStyle="regular"))
        y += 30
        _adv("mYLabel", vanilla.TextBox((14, y, 90, 18), "Y", sizeStyle="regular"))
        _adv("mYVal", vanilla.TextBox((-56, y, 42, 18), "0.0", sizeStyle="regular"))
        y += 20
        _adv("mYSlider", vanilla.Slider((14, y, -14, 22), minValue=-150,
                                        maxValue=150, value=0,
                                        callback=self.yCallback,
                                        sizeStyle="regular"))
        y += 30
        _adv("mCounterLabel", vanilla.TextBox((14, y, 90, 18), "Outer / Inner",
                                              sizeStyle="regular"))
        _adv("mCounterVal", vanilla.TextBox((-56, y, 42, 18), "65", sizeStyle="regular"))
        y += 20
        _adv("mCounterSlider", vanilla.Slider((14, y, -14, 22), minValue=0,
                                              maxValue=100, value=65,
                                              callback=self.counterCallback,
                                              sizeStyle="regular"))
        y += 18
        _adv("mCounterTickL", vanilla.TextBox((14, y, 90, 13), "luar tetap",
                                              sizeStyle="mini"))
        _adv("mCounterTickM", vanilla.TextBox((0, y, -0, 13), "seimbang",
                                              sizeStyle="mini", alignment="center"))
        _adv("mCounterTickR", vanilla.TextBox((-100, y, 86, 13), "dalam menyusut",
                                              sizeStyle="mini", alignment="right"))
        y += 18
        _adv("mSliderCardBottom", vanilla.HorizontalLine((14, y, -14, 1)))
        y += 12
        for i, (attr, label) in enumerate((("mdx", "dx"), ("mdy", "dy"),
                                           ("mpos", "pos%"), ("mwid", "w%"))):
            x = 14 + i * 72
            _adv(attr + "L", vanilla.TextBox((x, y + 3, 34, 15),
                                             label, sizeStyle="mini"))
            _adv(attr, vanilla.EditText((x + 26, y, 42, 20), "",
                                        sizeStyle="small"))
        _adv("mFill", vanilla.Button((-14 - 24, y - 1, 24, 20), "⟳",
                                     callback=self.fillCallback, sizeStyle="small"))
        y += 28
        _adv("mPreview", vanilla.Button((14, y, 70, 22), "Preview",
                                        callback=self.previewCallback,
                                        sizeStyle="small"))
        _adv("mApply", vanilla.Button((90, y, 84, 22), "Terapkan",
                                      callback=self.applySelectedCallback,
                                      sizeStyle="small"))
        _adv("mReset", vanilla.Button((180, y, 56, 22), "Reset",
                                      callback=self.resetCallback,
                                      sizeStyle="small"))
        y += 26
        _adv("mSave", vanilla.Button((14, y, 120, 22), "Simpan override",
                                     callback=self.saveOvCallback,
                                     sizeStyle="small"))
        _adv("mClear", vanilla.Button((140, y, 56, 22), "Hapus",
                                      callback=self.clearOvCallback,
                                      sizeStyle="small"))
        y += 26
        _adv("mCons", vanilla.TextBox((14, y, -14, 16), "", sizeStyle="small"))
        y += 20
        _adv("line3", vanilla.HorizontalLine((14, y, -14, 1)))
        y += 8
        self._adv_bottom = y

        # ── Status: selalu terlihat, posisinya digeser oleh toggle ──────────
        self.w.status = vanilla.TextBox((14, self._adv_top, -14, 30), "Siap.",
                                        sizeStyle="small")

        try:
            self.w.mXSlider.enable(not pref("sync_xy"))
            self.w.mYSlider.enable(not pref("sync_xy"))
        except Exception:
            pass
        self.w.bind("close", self.windowClosed)
        self._setAdvancedOpen(pref("panel_advanced_open"))
        self.w.open()
        self.refreshServer(None)

    def _setAdvancedOpen(self, open_):
        for widget in self._advanced_widgets:
            widget.show(open_)
        self.w.toggleButton.setTitle("▾ Lanjutan" if open_ else "▸ Lanjutan")
        status_y = self._adv_bottom if open_ else self._adv_top + 8
        self.w.status.setPosSize((14, status_y, -14, 30))
        try:
            self.w.resize((310, status_y + 30 + 14))
        except Exception:
            pass
        set_pref("panel_advanced_open", bool(open_))

    def toggleAdvancedCallback(self, sender):
        self._setAdvancedOpen(not pref("panel_advanced_open"))

    def _setStatus(self, text):
        try:
            self.w.status.set(text)
            self.w.getNSWindow().display()
        except Exception:
            pass

    def refreshServer(self, sender):
        try:
            self.w.serverText.set("memeriksa…")
            self.w.getNSWindow().display()
        except Exception:
            pass
        ok = MindweightClient(SERVER_URL, API_KEY).health_check()
        self.w.serverText.set("terhubung" if ok else f"offline — {SERVER_URL}")
        try:
            from AppKit import NSColor
            color = NSColor.systemGreenColor() if ok else NSColor.systemRedColor()
            self.w.serverDot.getNSTextField().setTextColor_(color)
        except Exception:
            self.w.serverDot.set("●" if ok else "○")

    def targetCallback(self, sender):
        set_pref("target_wght", str(WEIGHT_PRESETS[sender.get()][0]))

    def checkboxCallback(self, sender):
        set_pref(sender._prefKey, bool(sender.get()))

    def _drain_stale_events(self):
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

    def generateCallback(self, sender):
        if self.running:
            return
        self.running = True
        try:
            self.w.generateButton.enable(False)
        except Exception:
            pass
        stem_raw = str(self.w.stem.get() or "").strip()
        try:
            target_stem = float(stem_raw) if stem_raw else 0.0
        except ValueError:
            target_stem = 0.0
            self._setStatus(f"Target stem '{stem_raw}' bukan angka — pakai preset.")
        target_wght = WEIGHT_PRESETS[self.w.target.get()][0]
        self._setStatus("Generate berjalan… Glyphs tetap bisa dipakai.")
        try:
            result = run_generate(target_wght=target_wght, target_stem=target_stem)
        except Exception as e:
            import traceback
            Message(f"Error tak terduga:\n{e}\n\n{traceback.format_exc()[-600:]}",
                    "Mindweight — Error")
            result = f"error — {e}"
        finally:
            self._drain_stale_events()
            try:
                self.w.generateButton.enable(True)
            except Exception:
                pass
            self.running = False
        self._setStatus(f"{result} · {time.strftime('%H:%M')}")

    # ── Manual per glyph: nilai AI mengisi field, user mengedit, preview
    # non-destruktif ala Cape Weightor (snapshot → restore → re-apply),
    # override tersimpan dipakai run_generate ─────────────────────────────

    def _selected(self):
        """[(glyph, layer)] dari selection/edit tab di master aktif."""
        font = Glyphs.font
        if not font:
            return None, []
        out, seen = [], set()
        for l in (font.selectedLayers or []):
            g = l.parent
            if g is not None and g.name not in seen:
                seen.add(g.name)
                out.append((g, l))
        return font, out

    def loadAICallback(self, sender):
        font, _ = self._selected()
        if not font:
            self._setStatus("Tidak ada font terbuka.")
            return
        master = font.selectedFontMaster
        self._setStatus("Muat nilai AI… (export + server, semua anchor)")
        try:
            font_path = export_master_ttf(font, master)
        except Exception as e:
            self._setStatus(f"Export gagal: {e}")
            return
        try:
            client = MindweightClient(SERVER_URL, API_KEY)
            self._ai_multi = call_server(
                lambda: client.glyph_weight_params_multi(font_path))
            # self._ai tetap dipertahankan utk kompatibilitas fillCallback dkk
            # (global-fallback single-anchor) — pakai anchor terdekat target.
            anchors = sorted(int(a) for a in self._ai_multi)
            nearest = min(anchors, key=lambda a: abs(a - self._target_wght()))
            self._ai = self._ai_multi[str(nearest)]
            self._slider_wght = float(self._target_wght())
            try:
                self.w.mSlider.set(self._slider_wght)
            except Exception:
                pass
            n = len(self._ai.get("glyphs", {}))
            self._setStatus(f"AI dimuat: {n} glyph, anchor {anchors}. "
                            f"Pilih glyph → geser Ketebalan / ⟳.")
        except Exception as e:
            self._setStatus(f"Error server: {e}")
        finally:
            cleanup_ttf(font_path)

    def _target_wght(self):
        return WEIGHT_PRESETS[self.w.target.get()][0]

    def _interp_glyph(self, name, slider_wght):
        """Interpolasi linear dx/dy/position/width_ratio utk SATU glyph
        antar 2 anchor terdekat di self._ai_multi (mis. 550 → antara 100 &
        700). Angka per-anchor SUDAH final dari server (key/name/script/
        fallback + clamp + risk) — di sini cuma interpolasi 2 angka per
        field, bukan reimplementasi resolusi model.
        Return dict {"dx","dy","position","width_ratio","source","confidence"}
        atau None kalau glyph tak ada di anchor manapun (caller fallback ke
        field manual)."""
        if not self._ai_multi:
            return None
        anchors = sorted(int(a) for a in self._ai_multi)
        present = [a for a in anchors if name in self._ai_multi[str(a)]["glyphs"]]
        if not present:
            return None
        if len(present) == 1 or slider_wght <= present[0]:
            a = present[0]
            g = self._ai_multi[str(a)]["glyphs"][name]
            return dict(g, anchors=f"{a}")
        if slider_wght >= present[-1]:
            a = present[-1]
            g = self._ai_multi[str(a)]["glyphs"][name]
            return dict(g, anchors=f"{a}")
        lo = max(a for a in present if a <= slider_wght)
        hi = min(a for a in present if a >= slider_wght)
        if lo == hi:
            g = self._ai_multi[str(lo)]["glyphs"][name]
            return dict(g, anchors=f"{lo}")
        t = (slider_wght - lo) / (hi - lo)
        g_lo = self._ai_multi[str(lo)]["glyphs"][name]
        g_hi = self._ai_multi[str(hi)]["glyphs"][name]

        def lerp(k):
            return g_lo[k] + (g_hi[k] - g_lo[k]) * t

        # "fallback" kalau salah satu anchor fallback (biar penghitung
        # n_fallback di applySelectedCallback tetap benar); risk digabung
        # dari kedua anchor (union, dedup) biar risk-marking tetap jalan.
        source = "fallback" if "fallback" in (g_lo["source"], g_hi["source"]) \
            else g_lo["source"]
        risk = sorted(set(g_lo.get("risk", []) or []) | set(g_hi.get("risk", []) or []))
        return {
            "dx": lerp("dx"), "dy": lerp("dy"),
            "position": lerp("position"), "width_ratio": lerp("width_ratio"),
            "source": source,
            "risk": risk,
            "confidence": min(g_lo["confidence"], g_hi["confidence"]),
            "anchors": f"{lo}↔{hi} (t={t:.2f})",
        }

    def _glyph_params_or_uniform(self, g, uniform, layer=None):
        """Per-glyph via slider (_interp_glyph) kalau AI multi-anchor ada
        dan glyph ini punya data; else nilai manual seragam (self._fields())
        — jadi tiap glyph di multi-selection dapet angkanya sendiri2, bukan
        satu angka dicopy ke semua (inti permintaan user). Kalau `layer`
        dikasih dan slider Counter lagi override glyph ITU spesifik,
        `position` ditimpa manual (dx/dy/width_ratio tetap dari Ketebalan)."""
        if self._ai_multi:
            p = self._interp_glyph(g.name, self._slider_wght)
            if p is not None:
                dx, dy, position, width_ratio = p["dx"], p["dy"], p["position"], p["width_ratio"]
            else:
                dx, dy, position, width_ratio = (uniform["dx"], uniform["dy"],
                                                 uniform["position"], uniform["width_ratio"])
        else:
            dx, dy, position, width_ratio = (uniform["dx"], uniform["dy"],
                                             uniform["position"], uniform["width_ratio"])
        if (layer is not None and self._position_override is not None
                and layer.layerId == self._position_override_key):
            position = self._position_override
        if layer is not None and layer.layerId == self._dxdy_override_key:
            if self._dx_override is not None:
                dx = self._dx_override
            if self._dy_override is not None:
                dy = self._dy_override
        return dx, dy, position, width_ratio

    def _revert_snap(self, key):
        """Balikin SATU layer (by layerId) ke kondisi sebelum di-preview,
        lalu bersihkan dari _snap/_snap_layers. Dipakai saat pindah glyph
        (live-preview lama ditinggal) dan saat panel ditutup (jangan ada
        yg nyangkut berubah)."""
        state = self._snap.pop(key, None)
        layer = self._snap_layers.pop(key, None)
        if state and layer:
            try:
                _restore_layer_state(layer, state)
            except Exception:
                pass
        if self._live_layer_key == key:
            self._live_layer_key = None

    def _live_preview_current(self):
        """LIVE beneran ubah bentuk di kanvas — tapi SENGAJA cuma glyph
        PERTAMA yg terpilih (bukan massal/multi): kalau live-apply jalan ke
        banyak glyph sekaligus tiap tick geseran, itu bisa berat (tiap tick
        = OffsetCurve filter beneran). Terapkan (tombol, bukan slider) yang
        tetap bisa ke banyak glyph sekaligus, masing2 nilai sendiri — itu
        satu klik, bukan kontinu. Dipanggil oleh slider Ketebalan MAUPUN
        Counter — keduanya ujung2nya preview ke glyph yg sama."""
        font, sel = self._selected()
        if not sel or not _font_alive(font):
            return
        g, layer = sel[0]
        if not list(layer.paths) or list(layer.components):
            self._setStatus(f"{g.name}: bukan path-only, gak bisa live preview.")
            return

        # pindah ke glyph lain sambil masih ada live-preview/override
        # nyangkut di glyph SEBELUMNYA → balikin dulu glyph lama ke asli +
        # override posisi lama gak relevan lagi utk glyph baru (posisi
        # sangat spesifik per-glyph, jangan kebawa2 ke glyph lain).
        key = layer.layerId
        if self._live_layer_key and self._live_layer_key != key:
            self._revert_snap(self._live_layer_key)
            self._position_override = None
            self._position_override_key = None
            self._dx_override = None
            self._dy_override = None
            self._dxdy_override_key = None

        dx, dy, position, width_ratio = self._glyph_params_or_uniform(
            g, self._fields(), layer)
        self.w.mdx.set(f"{dx:.1f}")
        self.w.mdy.set(f"{dy:.1f}")
        self.w.mpos.set(f"{position * 100:.0f}")
        self.w.mwid.set(f"{width_ratio * 100:.1f}")
        # Slider X/Y/Outer-Inner selalu jujur nunjukin nilai yg BENERAN
        # dipakai (AI, atau override manual), biar gak diam2 beda sama yg
        # kejadian di kanvas. Outer/Inner dibalik polaritasnya di layar
        # supaya cocok konvensi Cape Weightor (0=luar tetap, 100=dalam
        # menyusut) — representasi internal `position` TETAP 1=luar/0=dalam
        # (kontrak sama server/training, jangan diubah).
        try:
            self.w.mXSlider.set(dx)
            self.w.mXVal.set(f"{dx:+.1f}")
            self.w.mYSlider.set(dy)
            self.w.mYVal.set(f"{dy:+.1f}")
            outer_inner = (1.0 - position) * 100
            self.w.mCounterSlider.set(outer_inner)
            self.w.mCounterVal.set(f"{outer_inner:.0f}")
        except Exception:
            pass

        p = self._interp_glyph(g.name, self._slider_wght)
        info_extra = f" · anchor {p['anchors']} · sumber {p['source']}" if p else ""
        if self._position_override is not None and key == self._position_override_key:
            info_extra += " · outer/inner: manual"
        if key == self._dxdy_override_key and (self._dx_override is not None
                                                or self._dy_override is not None):
            info_extra += " · X/Y: manual (unsynced)"
        if len(sel) > 1:
            info_extra += f" (live cuma glyph ini; +{len(sel)-1} lain nunggu Terapkan)"

        try:
            import objc
            OffsetCurve = objc.lookUpClass("GlyphsFilterOffsetCurve")
        except Exception:
            self._setStatus("Filter OffsetCurve tidak ada.")
            return
        master = font.selectedFontMaster
        keep = pref("keep_compatible")
        if key in self._snap:
            _restore_layer_state(layer, self._snap[key])
        else:
            self._snap[key] = _capture_layer_state(layer)
            self._snap_layers[key] = layer
        _apply_cape_weight_layer(OffsetCurve, layer, dx, dy, keep,
                                 position, width_ratio, master)
        self._live_layer_key = key
        self.w.mInfo.set(f"{g.name} · slider {int(self._slider_wght)}{info_extra}")
        self._setStatus(f"Live: {g.name} (geser terus / Reset utk balik).")

    def sliderCallback(self, sender):
        self._slider_wght = float(sender.get())
        try:
            self.w.mSliderVal.set(f"{int(self._slider_wght)}")
        except Exception:
            pass
        self._live_preview_current()

    def counterCallback(self, sender):
        """Slider Counter — override manual parameter `position` (share
        pertumbuhan outer/inner), independen dari Ketebalan. Sama seperti
        Ketebalan: cuma glyph PERTAMA yg terpilih, biar override yg
        dituning utk SATU glyph gak diam2 kepakai glyph lain."""
        font, sel = self._selected()
        if not sel:
            return
        # slider Outer/Inner di layar: 0=luar tetap, 100=dalam menyusut
        # (konvensi Cape Weightor) — dibalik ke `position` internal
        # (1=luar tetap, 0=dalam menyusut) yg dipakai server/training.
        self._position_override = 1.0 - float(sender.get()) / 100.0
        self._position_override_key = sel[0][1].layerId
        self._live_preview_current()

    def syncXYCallback(self, sender):
        """Sync X & Y ala Cape Weightor: ON (default) = X/Y ngikutin
        Ketebalan+AI, gak bisa digeser manual sendiri2. OFF = X dan Y jadi
        slider independen (bisa lepas dari rasio yg disaranin AI) — ini
        kapabilitas baru yg sebelumnya sengaja ditunda ("slider Kontras...
        lebih riskan") krn permintaan basis Cape Weightor eksplisit minta
        X/Y lepas-pasang."""
        synced = bool(sender.get())
        set_pref("sync_xy", synced)
        try:
            self.w.mXSlider.enable(not synced)
            self.w.mYSlider.enable(not synced)
        except Exception:
            pass
        if synced:
            # balik ke AI murni — buang override manual X/Y yg lagi aktif
            self._dx_override = None
            self._dy_override = None
            self._dxdy_override_key = None
        self._live_preview_current()

    def xCallback(self, sender):
        """Slider X (dx, stem vertikal) — cuma aktif kalau Sync X&Y OFF.
        Sama pola dgn Counter: override per-glyph, cuma glyph pertama yg
        terpilih, dibersihkan otomatis saat pindah glyph/Reset/Terapkan."""
        font, sel = self._selected()
        if not sel:
            return
        self._dx_override = float(sender.get())
        self._dxdy_override_key = sel[0][1].layerId
        self._live_preview_current()

    def yCallback(self, sender):
        """Slider Y (dy, kontras horizontal) — sama seperti xCallback."""
        font, sel = self._selected()
        if not sel:
            return
        self._dy_override = float(sender.get())
        self._dxdy_override_key = sel[0][1].layerId
        self._live_preview_current()

    def fillCallback(self, sender):
        """Isi field dari: override tersimpan > AI per-glyph > global AI."""
        font, sel = self._selected()
        if not sel:
            self.w.mInfo.set("(tidak ada glyph terpilih)")
            return
        g, _ = sel[0]
        src, p = "—", None
        ov = _get_overrides(font).get(g.name)
        if ov:
            src, p = "override", ov
        elif self._ai:
            gp = self._ai.get("glyphs", {}).get(g.name)
            if gp:
                src, p = gp.get("source", "AI"), gp
            else:
                glob = self._ai.get("global", {})
                cat = _glyph_category(font, g)
                o = (glob.get("offsets", {}) or {}).get(cat)
                if o:
                    src, p = "global", {
                        "dx": o["dx"], "dy": o["dy"],
                        "position": glob.get("position", 0.5),
                        "width_ratio": glob.get("adv_ratio", 1.0)}
        if p is None:
            self.w.mInfo.set(f"{g.name}: belum ada nilai — Muat nilai AI dulu")
            return
        self.w.mdx.set(f"{float(p.get('dx', 0)):.1f}")
        self.w.mdy.set(f"{float(p.get('dy', 0)):.1f}")
        self.w.mpos.set(f"{float(p.get('position', 0.5)) * 100:.0f}")
        self.w.mwid.set(f"{float(p.get('width_ratio', 1.0)) * 100:.1f}")
        extra = f" +{len(sel) - 1} glyph lain" if len(sel) > 1 else ""
        self.w.mInfo.set(f"{g.name} · sumber: {src}{extra}")

    def _fields(self):
        def f(w, default):
            try:
                return float(str(w.get()).strip().replace(",", "."))
            except Exception:
                return default
        return {"dx": f(self.w.mdx, 0.0), "dy": f(self.w.mdy, 0.0),
                "position": max(0.0, min(1.0, f(self.w.mpos, 50.0) / 100.0)),
                "width_ratio": max(0.01, f(self.w.mwid, 100.0) / 100.0)}

    def previewCallback(self, sender):
        import objc
        font, sel = self._selected()
        if not sel:
            self._setStatus("Pilih glyph dulu (edit tab / font view).")
            return
        try:
            OffsetCurve = objc.lookUpClass("GlyphsFilterOffsetCurve")
        except Exception:
            self._setStatus("Filter OffsetCurve tidak ada.")
            return
        uniform = self._fields()
        master = font.selectedFontMaster
        keep = pref("keep_compatible")
        n = 0
        for g, layer in sel:
            if not list(layer.paths) or list(layer.components):
                continue   # path-only, sama dengan run_generate
            dx, dy, position, width_ratio = self._glyph_params_or_uniform(g, uniform, layer)
            key = layer.layerId
            if key in self._snap:
                _restore_layer_state(layer, self._snap[key])
            else:
                self._snap[key] = _capture_layer_state(layer)
                self._snap_layers[key] = layer
            if _apply_cape_weight_layer(OffsetCurve, layer, dx, dy,
                                        keep, position, width_ratio,
                                        master):
                n += 1
        # baris konsistensi: stem glyph pertama vs target AI kategorinya
        cons = ""
        if sel and self._ai:
            g, layer = sel[0]
            st = _glyph_stem(layer)
            pred = (self._ai.get("global", {}) or {}).get("predicted", {})
            tgt = pred.get("H_stem" if _glyph_category(font, g) == "uc"
                           else "n_stem")
            if st and tgt:
                d = st - tgt
                cons = (f"konsistensi: stem {st:.0f}u · target {tgt:.0f}u "
                        f"({d:+.0f}) {'✓' if abs(d) <= 6 else '≠'}")
        self.w.mCons.set(cons)
        self._setStatus(f"Preview {n} glyph (non-destruktif — Reset utk balik).")

    def applySelectedCallback(self, sender):
        """Terapkan — commit langsung ke layer terpilih di master AKTIF
        (bukan bikin master baru). Tiap glyph pakai parameternya sendiri:
        override > AI per-glyph > global/manual fallback, lewat
        _resolve_glyph_params yang sama dipakai run_generate."""
        import objc
        font, sel = self._selected()
        if not sel:
            self._setStatus("Pilih glyph dulu (edit tab / font view).")
            return
        try:
            OffsetCurve = objc.lookUpClass("GlyphsFilterOffsetCurve")
        except Exception:
            self._setStatus("Filter OffsetCurve tidak ada.")
            return
        master = font.selectedFontMaster
        keep = pref("keep_compatible")
        overrides = _get_overrides(font)

        if self._ai_multi:
            # slider Ketebalan aktif — tiap glyph terpilih dapet interpolasi
            # sendiri antar 2 anchor terdekat (bukan 1 nilai AI seragam).
            glyph_params = {}
            for g, _ in sel:
                p = self._interp_glyph(g.name, self._slider_wght)
                if p is not None:
                    glyph_params[g.name] = p
            global_res = self._ai.get("global", {}) if self._ai else {}
            offsets = global_res.get("offsets", {}) or {}
            outer_share = max(0.0, min(1.0, float(global_res.get("position", 0.5))))
            adv_ratio = float(global_res.get("adv_ratio", 1.0))
        elif self._ai:
            global_res = self._ai.get("global", {})
            glyph_params = self._ai.get("glyphs", {})
            offsets = global_res.get("offsets", {}) or {}
            outer_share = max(0.0, min(1.0, float(global_res.get("position", 0.5))))
            adv_ratio = float(global_res.get("adv_ratio", 1.0))
        else:
            # belum ada AI dimuat — field manual jadi fallback seragam
            manual = self._fields()
            glyph_params = {}
            offsets = {"other": {"dx": manual["dx"], "dy": manual["dy"]}}
            outer_share = manual["position"]
            adv_ratio = manual["width_ratio"]

        n_applied = n_skip = n_fail = n_fallback = n_override = 0
        risk_names = []
        for g, layer in sel:
            if not layer.paths or layer.components:
                n_skip += 1
                continue
            cat = _glyph_category(font, g)
            dx, dy, position, width_ratio, is_fb, is_risk, is_ov = \
                _resolve_glyph_params(g, cat, glyph_params, offsets,
                                      outer_share, adv_ratio, overrides)
            key = layer.layerId
            if (self._position_override is not None
                    and key == self._position_override_key):
                position = self._position_override  # slider Outer/Inner menang
            if key == self._dxdy_override_key:
                if self._dx_override is not None:
                    dx = self._dx_override  # slider X menang
                if self._dy_override is not None:
                    dy = self._dy_override  # slider Y menang
            if is_fb:
                n_fallback += 1
            if is_ov:
                n_override += 1
            if is_risk:
                risk_names.append(g.name)
                try:
                    g.color = 0
                except Exception:
                    pass
            if key not in self._snap:
                self._snap[key] = _capture_layer_state(layer)
                self._snap_layers[key] = layer
            if _apply_cape_weight_layer(OffsetCurve, layer, dx, dy, keep,
                                        position, width_ratio, master):
                n_applied += 1
                # Terapkan = commit beneran (bukan preview) — jangan
                # auto-revert pas panel ditutup. Reset masih bisa
                # membatalkannya SELAMA snap-nya belum dibersihkan.
                self._committed_keys.add(key)
                if key == self._position_override_key:
                    self._position_override = None
                    self._position_override_key = None
                if key == self._dxdy_override_key:
                    self._dx_override = None
                    self._dy_override = None
                    self._dxdy_override_key = None
            else:
                n_fail += 1

        if risk_names:
            try:
                font.newTab(" ".join("/" + n for n in risk_names[:80]))
            except Exception:
                pass

        parts = [f"Diterapkan: {n_applied} glyph"]
        if n_override:
            parts.append(f"override:{n_override}")
        if n_fallback:
            parts.append(f"fallback:{n_fallback}")
        if n_fail:
            parts.append(f"gagal:{n_fail}")
        if n_skip:
            parts.append(f"dilewati:{n_skip}")
        if risk_names:
            parts.append(f"risk:{len(risk_names)}")
        self._setStatus(" · ".join(parts) + " (Reset/⌘Z utk batal)")

    def resetCallback(self, sender):
        font, sel = self._selected()
        n = 0
        for g, layer in sel:
            key = layer.layerId
            snap = self._snap.pop(key, None)
            self._snap_layers.pop(key, None)
            self._committed_keys.discard(key)
            if self._live_layer_key == key:
                self._live_layer_key = None
            if self._position_override_key == key:
                self._position_override = None
                self._position_override_key = None
            if self._dxdy_override_key == key:
                self._dx_override = None
                self._dy_override = None
                self._dxdy_override_key = None
            if snap:
                _restore_layer_state(layer, snap)
                n += 1
        self.w.mCons.set("")
        self._setStatus(f"Reset {n} glyph ke kondisi semula.")

    def saveOvCallback(self, sender):
        font, sel = self._selected()
        if not sel:
            return
        p = self._fields()
        for g, _ in sel:
            _set_override(font, g.name, dict(p))
        self._setStatus(f"Override disimpan utk {len(sel)} glyph — dipakai "
                        "setiap Generate berikutnya.")

    def clearOvCallback(self, sender):
        font, sel = self._selected()
        for g, _ in sel:
            _set_override(font, g.name, None)
        self._setStatus(f"Override dihapus utk {len(sel)} glyph (kembali ke AI).")

    def windowClosed(self, sender):
        # Panel ditutup — balikin apapun yg masih "preview nyangkut" (live
        # slider / tombol Preview yg belum di-Terapkan/Reset). Yang sudah
        # di-Terapkan (self._committed_keys) SENGAJA dibiarkan — itu commit
        # beneran, bukan preview, jangan ke-undo cuma gara2 nutup panel.
        for key in list(self._snap.keys()):
            if key not in self._committed_keys:
                self._revert_snap(key)
        try:
            Glyphs.MindweightPanel = None
        except Exception:
            pass


def main():
    if vanilla is None:
        Message("Modul 'vanilla' tidak termuat di Python Glyphs.\n"
                "Cek Plugin Manager → Modules → Vanilla (lalu restart Glyphs).",
                "Mindweight — vanilla tidak ada")
        return
    panel = getattr(Glyphs, "MindweightPanel", None)
    if panel is not None:
        try:
            panel.w.show()
            panel.refreshServer(None)
            return
        except Exception:
            pass
    Glyphs.MindweightPanel = MindweightPanel()


main()
