#!/usr/bin/env python3
"""
Perilay — layout_service.py
"""

import sys
import json
import logging
import threading
import queue
import base64
import textwrap
import urllib.request
import urllib.parse
import io
import os
import re
import time
import ipaddress
import locale

import peripage as pp
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from PIL import Image, ImageDraw, ImageFont

if len(sys.argv) < 6:
    print("Usage: layout_service.py <MAC> <MODEL> <FONT> <FONT_SIZE> <PORT> [CUSTOM_FONTS_JSON]")
    sys.exit(1)

PRINTER_MAC       = sys.argv[1]
PRINTER_MODEL     = sys.argv[2]
FONT_NAME         = sys.argv[3]
FONT_SIZE         = int(sys.argv[4])
PORT              = int(sys.argv[5])
CUSTOM_FONTS_JSON = sys.argv[6] if len(sys.argv) > 6 else "[]"
PRINT_WIDTH       = 384

# Taille max d'une image base64 encodée (5 Mo)
MAX_B64_SIZE = 5 * 1024 * 1024
# Taille max d'un fichier de police custom (2 Mo)
MAX_FONT_SIZE = 2 * 1024 * 1024
# Taille max d'une image URL (10 Mo)
MAX_IMAGE_SIZE = 10 * 1024 * 1024

# Polices custom chargées au démarrage : {"NomPolice": "/tmp/...", ...}
CUSTOM_FONT_CACHE = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("perilay")

FONT_MAP = {
    "DejaVu":     "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "DejaVuBold": "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "Liberation": "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
}

FONT_MAP_BOLD = {
    "DejaVu":     "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuBold": "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
    "Liberation": "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
}

# ------------------------------------------------------------------
# Sécurité — validation d'URL et protection SSRF
# ------------------------------------------------------------------

# Regex de validation d'entity_id Home Assistant
_ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def validate_entity_id(entity_id: str) -> bool:
    """Vérifie que l'entity_id respecte le format domain.name."""
    return bool(_ENTITY_ID_RE.match(entity_id))


def _is_blocked_ip(host: str) -> bool:
    """
    Retourne True uniquement pour les adresses vraiment dangereuses :
    - loopback (127.x.x.x)
    - réseau interne Docker/supervisor HA (172.16.x.x – 172.31.x.x)
    Les IPs du réseau local (192.168.x.x, 10.x.x.x) sont autorisées
    car elles sont nécessaires pour accéder aux médias de Home Assistant.
    """
    # Noms spéciaux autorisés
    if host in ("supervisor", "localhost"):
        return False
    try:
        addr = ipaddress.ip_address(host)
        # Bloquer loopback
        if addr.is_loopback:
            return True
        # Bloquer le réseau Docker interne (172.16.0.0/12) utilisé par le supervisor
        if addr in ipaddress.ip_network("172.16.0.0/12"):
            return True
        return False
    except ValueError:
        # Hostname — on laisse passer
        return False


def validate_http_url(url: str) -> tuple:
    """
    Valide une URL HTTP/HTTPS.
    Bloque loopback et réseau interne Docker/supervisor.
    Autorise les IPs du réseau local (192.168.x.x, 10.x.x.x)
    nécessaires pour accéder aux médias Home Assistant.
    Retourne (ok: bool, reason: str).
    """
    if not url.startswith(("http://", "https://")):
        return False, "Schéma non autorisé (http:// ou https:// requis)"
    try:
        parsed = urllib.parse.urlparse(url)
        host = parsed.hostname or ""
        if not host:
            return False, "Hôte manquant dans l'URL"
        if _is_blocked_ip(host):
            return False, f"Accès à cette adresse non autorisé ({host})"
        return True, ""
    except Exception as e:
        return False, f"URL invalide : {e}"


# ------------------------------------------------------------------
# Polices custom
# ------------------------------------------------------------------

def load_custom_fonts():
    """Télécharge et charge les polices custom déclarées dans la config."""
    global CUSTOM_FONT_CACHE
    fonts = []
    try:
        with open("/data/options.json", "r") as f:
            options = json.load(f)
        fonts = options.get("custom_fonts", [])
    except Exception:
        try:
            fonts = json.loads(CUSTOM_FONTS_JSON)
        except Exception:
            log.warning("Impossible de lire custom_fonts depuis la config")
            return
    if not fonts:
        return
    for entry in fonts:
        name = entry.get("name", "").strip()
        url  = entry.get("url", "").strip()
        if not name or not url:
            continue
        # Validation de l'URL pour éviter le SSRF
        ok, reason = validate_http_url(url)
        if not ok:
            log.warning(f"Police custom '{name}' ignorée : {reason}")
            continue
        dest = f"/tmp/custom_font_{name}.ttf"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Perilay-Addon/1.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                # Vérifier la taille avant de lire
                content_length = resp.headers.get("Content-Length")
                if content_length and int(content_length) > MAX_FONT_SIZE:
                    log.warning(f"Police custom '{name}' trop volumineuse ({content_length} bytes), ignorée")
                    continue
                data = resp.read(MAX_FONT_SIZE + 1)
                if len(data) > MAX_FONT_SIZE:
                    log.warning(f"Police custom '{name}' dépasse {MAX_FONT_SIZE} bytes, ignorée")
                    continue
            with open(dest, "wb") as f:
                f.write(data)
            # Vérifie que Pillow peut lire la police
            ImageFont.truetype(dest, 24)
            CUSTOM_FONT_CACHE[name] = dest
            log.info(f"Police custom '{name}' chargée depuis {url}")
        except Exception as e:
            log.warning(f"Police custom '{name}' impossible à charger : {e}")


EMOJI_FONT_PATHS = [
    "/usr/share/fonts/NotoEmoji-Regular.ttf",
    "/usr/share/fonts/noto/NotoEmoji-Regular.ttf",
    "/usr/share/fonts/noto-emoji/NotoEmoji-Regular.ttf",
]

_emoji_font_cache = {}


def _get_emoji_font(size: int):
    if size in _emoji_font_cache:
        return _emoji_font_cache[size]
    for path in EMOJI_FONT_PATHS:
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, size)
                _emoji_font_cache[size] = f
                return f
            except Exception:
                pass
    _emoji_font_cache[size] = None
    return None


def _is_emoji(code: int) -> bool:
    return (
        0x1F300 <= code <= 0x1FAFF or
        0x2600  <= code <= 0x27BF  or
        0x1F000 <= code <= 0x1F02F or
        0x1F0A0 <= code <= 0x1F0FF or
        0x2300  <= code <= 0x23FF  or
        0x2B00  <= code <= 0x2BFF
    )


# ------------------------------------------------------------------
# Chargement de polices
# ------------------------------------------------------------------

def load_font(size: int, bold: bool = False, font_name: str = None) -> ImageFont.FreeTypeFont:
    name = font_name if font_name else FONT_NAME
    # 1. Chercher dans les polices custom
    if name in CUSTOM_FONT_CACHE:
        try:
            return ImageFont.truetype(CUSTOM_FONT_CACHE[name], size)
        except Exception:
            pass
    # 2. Chercher dans les polices système
    font_map = FONT_MAP_BOLD if bold else FONT_MAP
    path = font_map.get(name)
    # 3. Fallback vers police globale puis DejaVu
    if not path or not os.path.exists(path):
        path = font_map.get(FONT_NAME)
    if not path or not os.path.exists(path):
        path = font_map.get("DejaVu")
    if path and os.path.exists(path):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    log.warning(f"Police '{name}' introuvable, fallback PIL.")
    return ImageFont.load_default()


# ------------------------------------------------------------------
# Cache line_height — clé stable (path, size, bold)
# ------------------------------------------------------------------

_lh_cache = {}


def line_height(font, font_path: str = "", size: int = 0, bold: bool = False) -> int:
    """
    Calcule la hauteur de ligne d'une police.
    La clé de cache est (font_path, size, bold) pour éviter les collisions d'id().
    """
    key = (font_path, size, bold)
    if key not in _lh_cache:
        dummy = Image.new("L", (PRINT_WIDTH, 10))
        _lh_cache[key] = ImageDraw.Draw(dummy).textbbox((0, 0), "Ay", font=font)[3] + 4
    return _lh_cache[key]


def _get_font_and_lh(size: int, bold: bool, font_name: str):
    """Helper qui retourne (font, line_height) avec un cache stable."""
    name = font_name if font_name else FONT_NAME
    font_map = FONT_MAP_BOLD if bold else FONT_MAP
    path = (
        CUSTOM_FONT_CACHE.get(name)
        or font_map.get(name)
        or font_map.get(FONT_NAME)
        or font_map.get("DejaVu")
        or ""
    )
    font = load_font(size, bold, font_name)
    lh   = line_height(font, font_path=path, size=size, bold=bold)
    return font, lh


def measure_text(text: str, font, size: int) -> int:
    emoji_font = _get_emoji_font(size)
    dummy = Image.new("L", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    total = 0
    for char in text:
        f    = emoji_font if (_is_emoji(ord(char)) and emoji_font) else font
        bbox = draw.textbbox((0, 0), char, font=f)
        total += bbox[2] - bbox[0]
    return total


def _measure_avg_char_width(font) -> int:
    """Mesure la largeur moyenne d'un caractère via textbbox (plus précis que heuristique)."""
    dummy = Image.new("L", (1, 1))
    draw  = ImageDraw.Draw(dummy)
    sample = "abcdefghijklmnopqrstuvwxyz"
    bbox   = draw.textbbox((0, 0), sample, font=font)
    return max(1, (bbox[2] - bbox[0]) // len(sample))


def draw_text_with_emoji(draw, pos, text: str, font, size: int, fill=0):
    emoji_font = _get_emoji_font(size)
    x, y = pos
    for char in text:
        f = emoji_font if (_is_emoji(ord(char)) and emoji_font) else font
        try:
            draw.text((x, y), char, font=f, fill=fill)
        except Exception:
            draw.text((x, y), char, font=font, fill=fill)
            f = font
        bbox = draw.textbbox((0, 0), char, font=f)
        x += bbox[2] - bbox[0]
    return x


# ------------------------------------------------------------------
# File d'attente d'impression
# ------------------------------------------------------------------

print_queue   = queue.Queue()
printer_busy  = threading.Event()


def _print_worker():
    """Thread dédié qui traite les impressions une par une depuis la queue."""
    while True:
        image = print_queue.get()
        if image is None:
            break
        printer_busy.set()
        try:
            _do_print(image)
        finally:
            printer_busy.clear()
            print_queue.task_done()


# ------------------------------------------------------------------
# Validation MAC
# ------------------------------------------------------------------

def validate_mac(mac: str) -> bool:
    if mac.lower() == "xx:xx:xx:xx:xx:xx":
        return False
    parts = mac.split(":")
    if len(parts) != 6:
        return False
    try:
        [int(p, 16) for p in parts]
        return True
    except ValueError:
        return False


# ------------------------------------------------------------------
# Renderers de blocs
# ------------------------------------------------------------------

def render_separator(block: dict) -> Image.Image:
    style = block.get("style", "line")
    # Hauteur suffisante pour que le séparateur soit bien visible
    height = 20
    img  = Image.new("L", (PRINT_WIDTH, height), color=255)
    draw = ImageDraw.Draw(img)
    y = height // 2
    if style == "dotted":
        # Points noirs de 3x3 px, espacés de 8 px
        for x in range(10, PRINT_WIDTH - 10, 8):
            draw.rectangle([x, y - 1, x + 2, y + 1], fill=0)
    elif style == "blank":
        pass  # Espace vide, rien à dessiner
    else:
        # Ligne noire pleine, 2 px d'épaisseur
        draw.line([(10, y), (PRINT_WIDTH - 10, y)], fill=0, width=2)
    return img


def render_text(block: dict) -> Image.Image:
    text      = str(block.get("text", "")).strip()
    font_size = int(block.get("font_size", FONT_SIZE))
    bold      = bool(block.get("bold", False))
    align     = block.get("align", "left")
    padding   = int(block.get("padding", 4))
    font_name = block.get("font", None)

    font, lh = _get_font_and_lh(font_size, bold, font_name)
    avg_w    = _measure_avg_char_width(font)
    max_chars = max(10, PRINT_WIDTH // avg_w)

    lines = []
    for paragraph in text.split("\n"):
        wrapped = textwrap.fill(paragraph, width=max_chars) if paragraph.strip() else ""
        lines.extend(wrapped.split("\n") if wrapped else [""])

    total_h = lh * len(lines) + padding * 2
    img  = Image.new("L", (PRINT_WIDTH, total_h), color=255)
    draw = ImageDraw.Draw(img)
    y = padding
    for line in lines:
        if not line.strip():
            y += lh
            continue
        w = measure_text(line, font, font_size)
        if align == "center":
            x = max(0, (PRINT_WIDTH - w) // 2)
        elif align == "right":
            x = max(0, PRINT_WIDTH - w - 8)
        else:
            x = 8
        draw_text_with_emoji(draw, (x, y), line, font, font_size, fill=0)
        y += lh
    return img


def render_title(block: dict) -> Image.Image:
    return render_text({
        **block,
        "bold":      True,
        "font_size": int(block.get("font_size", FONT_SIZE + 6)),
        "align":     block.get("align", "center"),
        "padding":   6,
    })


def render_list(block: dict) -> Image.Image:
    items     = block.get("items", [])
    font_size = int(block.get("font_size", FONT_SIZE))
    bold      = bool(block.get("bold", False))
    bullet    = block.get("bullet", "•")
    padding   = 4
    font_name = block.get("font", None)

    font, lh  = _get_font_and_lh(font_size, bold, font_name)
    # Calcul de max_chars via textbbox (plus précis que l'heuristique 0.58)
    avg_w     = _measure_avg_char_width(font)
    max_chars = max(10, (PRINT_WIDTH - 24) // avg_w)

    rendered_lines = []
    for item in items:
        text    = str(item).strip()
        wrapped = textwrap.fill(text, width=max_chars)
        sub     = wrapped.split("\n")
        rendered_lines.append((sub[0], True))
        for continuation in sub[1:]:
            rendered_lines.append((continuation, False))

    total_h = lh * len(rendered_lines) + padding * 2
    img  = Image.new("L", (PRINT_WIDTH, total_h), color=255)
    draw = ImageDraw.Draw(img)
    y = padding
    for line, is_first in rendered_lines:
        if is_first:
            # Toujours ajouter un espace entre le bullet et le texte
            bullet_with_space = bullet.rstrip() + " "
            bw = measure_text(bullet_with_space, font, font_size)
            draw_text_with_emoji(draw, (8, y), bullet_with_space, font, font_size, fill=0)
            draw_text_with_emoji(draw, (8 + bw, y), line, font, font_size, fill=0)
        else:
            bw = measure_text(bullet.rstrip() + " ", font, font_size)
            draw_text_with_emoji(draw, (8 + bw, y), line, font, font_size, fill=0)
        y += lh
    return img


def render_image_url(block: dict) -> Image.Image:
    url = block.get("url", "").strip()
    if not url:
        raise ValueError("Bloc image_url : champ 'url' manquant")
    ok, reason = validate_http_url(url)
    if not ok:
        raise ValueError(f"Bloc image_url : URL refusée — {reason}")
    req = urllib.request.Request(url, headers={"User-Agent": "Perilay-Addon/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        content_length = resp.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_IMAGE_SIZE:
            raise ValueError(f"Image trop volumineuse ({content_length} bytes)")
        data = resp.read(MAX_IMAGE_SIZE + 1)
        if len(data) > MAX_IMAGE_SIZE:
            raise ValueError(f"Image dépasse {MAX_IMAGE_SIZE} bytes")
    return _fit_image(Image.open(io.BytesIO(data)).convert("L"))


def render_image_b64(block: dict) -> Image.Image:
    b64 = block.get("image", "").strip()
    if not b64:
        raise ValueError("Bloc image_b64 : champ 'image' manquant")
    # Vérification de taille avant décodage
    if len(b64) > MAX_B64_SIZE:
        raise ValueError(f"Image base64 trop volumineuse (max {MAX_B64_SIZE} bytes encodés)")
    return _fit_image(Image.open(io.BytesIO(base64.b64decode(b64))).convert("L"))


def _fit_image(img: Image.Image) -> Image.Image:
    w, h  = img.size
    new_h = int(h * PRINT_WIDTH / w)
    return img.resize((PRINT_WIDTH, new_h), Image.LANCZOS)


# Traductions des jours et mois par langue
_DATE_TRANSLATIONS = {
    "fr": {
        "days":   ["Lundi","Mardi","Mercredi","Jeudi","Vendredi","Samedi","Dimanche"],
        "months": ["janvier","février","mars","avril","mai","juin",
                   "juillet","août","septembre","octobre","novembre","décembre"],
    },
    "de": {
        "days":   ["Montag","Dienstag","Mittwoch","Donnerstag","Freitag","Samstag","Sonntag"],
        "months": ["Januar","Februar","März","April","Mai","Juni",
                   "Juli","August","September","Oktober","November","Dezember"],
    },
    "es": {
        "days":   ["Lunes","Martes","Miércoles","Jueves","Viernes","Sábado","Domingo"],
        "months": ["enero","febrero","marzo","abril","mayo","junio",
                   "julio","agosto","septiembre","octubre","noviembre","diciembre"],
    },
    "it": {
        "days":   ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"],
        "months": ["gennaio","febbraio","marzo","aprile","maggio","giugno",
                   "luglio","agosto","settembre","ottobre","novembre","dicembre"],
    },
    "nl": {
        "days":   ["Maandag","Dinsdag","Woensdag","Donderdag","Vrijdag","Zaterdag","Zondag"],
        "months": ["januari","februari","maart","april","mei","juni",
                   "juli","augustus","september","oktober","november","december"],
    },
    "pt": {
        "days":   ["Segunda","Terça","Quarta","Quinta","Sexta","Sábado","Domingo"],
        "months": ["janeiro","fevereiro","março","abril","maio","junho",
                   "julho","agosto","setembro","outubro","novembro","dezembro"],
    },
    "en": {
        "days":   ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
        "months": ["January","February","March","April","May","June",
                   "July","August","September","October","November","December"],
    },
}

# Langue détectée depuis HA (initialisée à "en" par défaut)
_HA_LANGUAGE = "en"


def _format_date_localized(fmt: str = "%A %d %B %Y") -> str:
    """
    Formate la date courante dans la langue HA détectée au démarrage.
    Traduit manuellement les noms de jours et de mois pour contourner
    la limitation de musl-libc (Alpine Linux) qui ignore les locales dans strftime.
    """
    import datetime
    now   = datetime.datetime.now()
    lang  = _HA_LANGUAGE[:2].lower()
    trans = _DATE_TRANSLATIONS.get(lang, _DATE_TRANSLATIONS["en"])

    day_name   = trans["days"][now.weekday()]
    month_name = trans["months"][now.month - 1]

    # Remplacer %A (jour) et %B (mois) manuellement, laisser strftime gérer le reste
    fmt_intermediate = fmt.replace("%A", day_name).replace("%B", month_name)
    return now.strftime(fmt_intermediate)


def render_date(block: dict) -> Image.Image:
    """
    Bloc spécial qui formate la date courante dans la langue de Home Assistant.
    Paramètres optionnels :
      - format : format strftime (défaut: "%A %d %B %Y")
      - align, font_size, font, bold : identiques au bloc text
    """
    fmt      = block.get("format", "%A %d %B %Y")
    date_str = _format_date_localized(fmt)
    return render_text({**block, "text": date_str})


BLOCK_RENDERERS = {
    "text":      render_text,
    "title":     render_title,
    "list":      render_list,
    "separator": render_separator,
    "image_url": render_image_url,
    "image_b64": render_image_b64,
    "date":      render_date,
}


def compose_page(blocks: list) -> tuple:
    images, warnings = [], []
    for i, block in enumerate(blocks):
        block_type = block.get("type", "")
        renderer   = BLOCK_RENDERERS.get(block_type)
        if not renderer:
            warnings.append(f"Bloc #{i} : type inconnu '{block_type}', ignoré")
            continue
        try:
            images.append(renderer(block))
        except Exception as e:
            warnings.append(f"Bloc #{i} ({block_type}) : erreur de rendu — {e}")
            log.warning(f"Bloc #{i} ({block_type}) ignoré : {e}")
    if not images:
        return None, warnings
    # Marge basse
    images.append(Image.new("L", (PRINT_WIDTH, 40), color=255))
    total_h = sum(img.height for img in images)
    page    = Image.new("L", (PRINT_WIDTH, total_h), color=255)
    y = 0
    for img in images:
        page.paste(img, (0, y))
        y += img.height
    return page, warnings


# ------------------------------------------------------------------
# Impression Bluetooth
# ------------------------------------------------------------------

MODEL_MAP = {
    "A6":  pp.PrinterType.A6,
    "A6p": pp.PrinterType.A6p,
    "A40": pp.PrinterType.A40,
    "A40p": pp.PrinterType.A40p,
}


def _classify_error(error_str: str) -> str:
    """Retourne un message clair selon le type d'erreur Bluetooth."""
    e = error_str.lower()
    if "host is down" in e or "112" in e:
        return "Imprimante éteinte ou hors de portée Bluetooth"
    if "timeout" in e:
        return "Timeout — imprimante éteinte, hors de portée ou occupée par une autre connexion"
    if "busy" in e or "resource" in e or "16" in e:
        return "Imprimante occupée — peut-être connectée à l'application mobile"
    if "connection refused" in e or "111" in e:
        return "Connexion refusée par l'imprimante"
    if "no such device" in e or "19" in e:
        return "Imprimante introuvable — vérifiez l'adresse MAC"
    return f"Erreur Bluetooth : {error_str}"


def _attempt_print(image: Image.Image) -> dict:
    """
    Une tentative d'impression.
    Timeout global de 90 s pour laisser le temps à l'envoi Bluetooth
    même pour les grandes images.
    Après un succès, attend 3 s pour laisser l'imprimante libérer
    la connexion Bluetooth avant de rendre la main.
    """
    result = {"success": False, "error": None}

    def _thread():
        try:
            printer_type = MODEL_MAP.get(PRINTER_MODEL, pp.PrinterType.A6)
            printer = pp.Printer(PRINTER_MAC, printer_type)
            printer.connect()
            log.info(f"Connecté, envoi image {image.size}...")
            img_rgb = image.convert("RGB")
            printer.printImage(img_rgb)
            printer.printBreak(100)
            printer.disconnect()
            # Délai post-impression : laisse l'imprimante libérer la connexion BT
            log.info("Impression transmise, attente libération Bluetooth (3 s)...")
            time.sleep(3)
            result["success"] = True
            log.info("Impression terminée avec succès.")
        except Exception as e:
            result["error"] = str(e)

    t = threading.Thread(target=_thread, daemon=True)
    t.start()
    t.join(timeout=90)
    if t.is_alive():
        result["error"] = "timeout"
    return result


def _is_transient_error(error_str: str) -> bool:
    """
    Retourne True si l'erreur est transitoire et justifie une nouvelle tentative.
    Un timeout ne doit PAS être retenté pour éviter une double impression.
    """
    e = error_str.lower()
    if "busy" in e or "resource" in e or "16" in e:
        return True
    if "host is down" in e or "112" in e:
        return True
    if "connection refused" in e or "111" in e:
        return True
    # Timeout : ambigu — on ne retente pas (risque double impression)
    return False


def _do_print(image: Image.Image) -> dict:
    """
    Tente l'impression jusqu'à 2 fois.
    Ne retente PAS en cas de timeout (risque de double impression).
    Notifie HA en cas d'échec complet.
    """
    max_attempts = 2
    last_error   = None
    for attempt in range(1, max_attempts + 1):
        log.info(f"Tentative {attempt}/{max_attempts}...")
        result = _attempt_print(image)
        if result["success"]:
            return result
        raw_error  = result["error"] or "inconnue"
        last_error = _classify_error(raw_error)
        log.warning(f"Tentative {attempt} échouée : {last_error}")
        if attempt < max_attempts:
            if not _is_transient_error(raw_error):
                log.warning("Erreur non-transitoire — pas de nouvelle tentative (évite double impression).")
                break
            log.info("Nouvelle tentative dans 10 secondes...")
            time.sleep(10)
    log.error(f"Échec : {last_error}")
    fire_ha_notification(last_error)
    return {"success": False, "error": last_error}


def fire_ha_notification(error_msg: str):
    """Envoie une notification persistante dans HA."""
    try:
        token = os.environ.get("SUPERVISOR_TOKEN", "")
        if not token:
            return
        payload = json.dumps({
            "message": f"Impossible de se connecter à l'imprimante.\n{error_msg}",
            "title": "Perilay — Erreur d'impression",
            "notification_id": "peripage_print_error"
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://supervisor/core/api/services/persistent_notification/create",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        urllib.request.urlopen(req, timeout=5)
        log.info("Notification HA envoyée.")
    except Exception as e:
        log.warning(f"Impossible d'envoyer la notification HA : {e}")


# ------------------------------------------------------------------
# Récupération des items Todo
# ------------------------------------------------------------------

def get_todo_items(entity_id: str) -> tuple:
    """
    Récupère les items non complétés d'une liste Todo via l'API HA.
    Utilise /api/services/todo/get_items?return_response (seul endpoint fonctionnel).
    Structure de réponse : {"service_response": {"todo.xxx": {"items": [...]}}}
    """
    if not validate_entity_id(entity_id):
        return [], f"entity_id invalide : '{entity_id}'"

    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return [], "SUPERVISOR_TOKEN absent"

    try:
        url = "http://supervisor/core/api/services/todo/get_items?return_response"
        log.info(f"get_todo_items : appel {url} pour {entity_id}")
        payload = json.dumps({"entity_id": entity_id}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        # Parser la structure : service_response -> entity_id -> items
        raw_items = (
            data
            .get("service_response", {})
            .get(entity_id, {})
            .get("items", [])
        )

        items = []
        for item in raw_items:
            if item.get("status") != "completed":
                summary = item.get("summary", "").strip()
                if summary:
                    items.append(summary)

        log.info(f"get_todo_items : {len(items)} item(s) trouvé(s)")
        return items, None

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        log.error(f"get_todo_items HTTP {e.code} : {body}")
        return [], f"Erreur API HA : HTTP {e.code} — {body}"
    except Exception as e:
        log.error(f"get_todo_items erreur : {e}")
        return [], f"Erreur API HA : {e}"

def send_to_printer(image: Image.Image):
    """Enfile l'image dans la queue d'impression."""
    if printer_busy.is_set() or not print_queue.empty():
        log.warning("Impression déjà en cours, ajout à la queue.")
    print_queue.put(image)


# ------------------------------------------------------------------
# Lecture JSON et réponse HTTP
# ------------------------------------------------------------------

def _read_json(handler) -> tuple:
    try:
        length = int(handler.headers.get("Content-Length", 0))
        raw    = handler.rfile.read(length)
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"JSON invalide : {e}"
    except Exception as e:
        return None, f"Erreur lecture body : {e}"


def _send(handler, code: int, payload: dict):
    try:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", len(body))
        handler.end_headers()
        handler.wfile.write(body)
    except BrokenPipeError:
        pass  # Le client a fermé la connexion — impression déjà effectuée


# ------------------------------------------------------------------
# Handler HTTP
# ------------------------------------------------------------------

class LayoutHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log.info(fmt % args)

    def do_GET(self):
        if self.path == "/health":
            ok = validate_mac(PRINTER_MAC)
            _send(self, 200 if ok else 503, {
                "status":          "ok" if ok else "error",
                "mac":             PRINTER_MAC,
                "model":           PRINTER_MODEL,
                "font":            FONT_NAME,
                "font_size":       FONT_SIZE,
                "port":            PORT,
                "supported_blocks": list(BLOCK_RENDERERS.keys()),
                "endpoints":       ["/print", "/print_todo", "/health", "/status"],
            })
        elif self.path == "/status":
            _send(self, 200, {
                "busy":        printer_busy.is_set(),
                "queue_depth": print_queue.qsize(),
                "mac":         PRINTER_MAC,
            })
        else:
            _send(self, 404, {"error": "Route inconnue"})

    def do_POST(self):
        if self.path == "/print":
            data, err = _read_json(self)
            if err:
                return _send(self, 400, {"error": err})
            blocks = data.get("blocks", [])
            if not isinstance(blocks, list) or len(blocks) == 0:
                return _send(self, 400, {"error": "Champ 'blocks' manquant ou vide"})
            page, warnings = compose_page(blocks)
            if page is None:
                return _send(self, 422, {"error": "Aucun bloc n'a pu être rendu", "warnings": warnings})
            threading.Thread(target=send_to_printer, args=(page,), daemon=True).start()
            _send(self, 200, {
                "status":          "printing",
                "blocks_rendered": len(blocks) - len(warnings),
                "queue_depth":     print_queue.qsize(),
                "warnings":        warnings,
            })

        elif self.path == "/print_todo":
            data, err = _read_json(self)
            if err:
                return _send(self, 400, {"error": err})
            entity_id = data.get("entity_id", "").strip()
            title     = data.get("title", "Ma liste")
            if not entity_id:
                return _send(self, 400, {"error": "Champ 'entity_id' manquant"})
            if not validate_entity_id(entity_id):
                return _send(self, 400, {"error": f"entity_id invalide : '{entity_id}'"})
            items, err = get_todo_items(entity_id)
            if err:
                return _send(self, 500, {"error": err})
            if not items:
                items = ["Aucun élément dans cette liste."]
            blocks = [
                {"type": "title",     "text": title, "align": "center"},
                {"type": "separator"},
                {"type": "text",      "text": f"{len(items)} élément(s)", "align": "center", "font_size": 20},
                {"type": "separator"},
                {"type": "list",      "items": items, "bullet": "[ ] "},
            ]
            page, warnings = compose_page(blocks)
            if page is None:
                return _send(self, 422, {"error": "Impossible de composer la page", "warnings": warnings})
            threading.Thread(target=send_to_printer, args=(page,), daemon=True).start()
            _send(self, 200, {
                "status":      "printing",
                "items_count": len(items),
                "queue_depth": print_queue.qsize(),
                "warnings":    warnings,
            })

        else:
            _send(self, 404, {"error": "Route inconnue"})


# ------------------------------------------------------------------
# Démarrage
# ------------------------------------------------------------------

# Correspondance langue HA -> locale système
_HA_LANG_TO_LOCALE = {
    "fr": ("fr_FR.UTF-8", "fr_FR.utf8", "fr_FR", "fr"),
    "en": ("en_US.UTF-8", "en_US.utf8", "en_US", "en"),
    "de": ("de_DE.UTF-8", "de_DE.utf8", "de_DE", "de"),
    "es": ("es_ES.UTF-8", "es_ES.utf8", "es_ES", "es"),
    "it": ("it_IT.UTF-8", "it_IT.utf8", "it_IT", "it"),
    "nl": ("nl_NL.UTF-8", "nl_NL.utf8", "nl_NL", "nl"),
    "pt": ("pt_PT.UTF-8", "pt_PT.utf8", "pt_PT", "pt"),
    "pl": ("pl_PL.UTF-8", "pl_PL.utf8", "pl_PL", "pl"),
    "ru": ("ru_RU.UTF-8", "ru_RU.utf8", "ru_RU", "ru"),
    "zh": ("zh_CN.UTF-8", "zh_CN.utf8", "zh_CN", "zh"),
    "ja": ("ja_JP.UTF-8", "ja_JP.utf8", "ja_JP", "ja"),
}


def _apply_ha_locale():
    """
    Récupère la langue configurée dans Home Assistant via l'API supervisor
    et applique la locale système correspondante pour strftime.
    Fallback sur la locale système par défaut si non disponible.
    """
    ha_lang = None
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if token:
        try:
            req = urllib.request.Request(
                "http://supervisor/core/api/config",
                headers={"Authorization": f"Bearer {token}"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                config = json.loads(resp.read())
            ha_lang = config.get("language", "en")
            log.info(f"Langue HA détectée : {ha_lang}")
            global _HA_LANGUAGE
            _HA_LANGUAGE = ha_lang
        except Exception as e:
            log.warning(f"Impossible de récupérer la langue HA : {e}")

    # Chercher les locales candidates pour cette langue
    lang_key = (ha_lang or "en")[:2].lower()
    candidates = _HA_LANG_TO_LOCALE.get(lang_key, ("",))

    for loc in candidates:
        if not loc:
            continue
        try:
            locale.setlocale(locale.LC_TIME, loc)
            log.info(f"Locale appliquée : {loc}")
            return
        except locale.Error:
            continue

    log.warning(f"Aucune locale disponible pour '{ha_lang}' — dates en anglais par défaut")


def main():
    if not validate_mac(PRINTER_MAC):
        log.error(f"Adresse MAC invalide ou placeholder : '{PRINTER_MAC}'")
        sys.exit(1)

    # Récupérer la langue configurée dans HA et appliquer la locale correspondante
    _apply_ha_locale()

    log.info(f"Perilay démarré — port {PORT}")
    log.info(f"Imprimante : {PRINTER_MODEL} @ {PRINTER_MAC}")
    load_custom_fonts()
    log.info(f"Police par défaut : {FONT_NAME} {FONT_SIZE}px")

    # Avertir si une police système est absente
    for name in FONT_MAP:
        if not os.path.exists(FONT_MAP[name]) and not os.path.exists(FONT_MAP_BOLD.get(name, "")):
            log.warning(f"Police '{name}' absente du système")
    if not any(os.path.exists(p) for p in EMOJI_FONT_PATHS):
        log.warning("Police emoji introuvable — les emojis s'afficheront en carré")

    # Démarrer le worker d'impression en arrière-plan
    worker = threading.Thread(target=_print_worker, daemon=True)
    worker.start()
    log.info("Worker d'impression démarré.")

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(("0.0.0.0", PORT), LayoutHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log.info("Arrêt.")
    finally:
        # Signal d'arrêt au worker
        print_queue.put(None)
        worker.join(timeout=5)
        server.server_close()


if __name__ == "__main__":
    main()
