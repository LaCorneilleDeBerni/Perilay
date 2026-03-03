# Perilay — Peripage Home Assistant Addon

Addon Home Assistant pour composer et imprimer des pages structurées sur les imprimantes thermiques A6, A6p, A40, et A40p **PeriPage** via Bluetooth. Attention, je n'ai personnellement testé que l'A6.
## (English below)

L'addon reçoit une liste de **blocs de contenu** en JSON, compose la page automatiquement (mise en page, word-wrap, redimensionnement des images) et imprime en une seule connexion Bluetooth. 

---

## Installation

1. Dans HA : **Paramètres → Addons → Store → ⋮ → Dépôts**
2. Ajoutez : `https://github.com/LaCorneilleDeBerni/perilay-addon`
3. Installez **Perilay**
4. Configurez votre adresse MAC et démarrez

> ⚠️ Après toute modification de la configuration, **redémarrez l'addon**.

---

## Trouver l'adresse MAC de votre imprimante

Depuis le terminal SSH de Home Assistant :

```bash
hcitool scan
```

Elle est également visible dans **Paramètres → Bluetooth → Annonces** sous la forme `PeriPage_XXXX_BLE`.

---

## Configuration

| Paramètre | Description | Défaut |
|---|---|---|
| `printer_mac` | Adresse MAC Bluetooth de l'imprimante | `XX:XX:XX:XX:XX:XX` |
| `printer_model` | Modèle : `A6`, `A6p`, `A40`, `A40p` | `A6` |
| `font` | Police par défaut : `DejaVu`, `DejaVuBold`, `Liberation` | `DejaVu` |
| `font_size` | Taille de police par défaut en pixels | `24` |
| `port` | Port HTTP du service | `8766` |
| `custom_fonts` | Polices personnalisées (nom + URL .ttf) | `[]` |

### Polices personnalisées

Placez vos fichiers `.ttf` dans `/config/www/fonts/` puis déclarez-les dans la configuration :

```yaml
custom_fonts:
  - name: "MaPolice"
    url: "http://<IP_HOME_ASSISTANT>:8123/local/fonts/MaPolice.ttf"
```

---

## Intégration Home Assistant

Ajoutez dans `/config/configuration.yaml` :

```yaml
rest_command:
  peripage_print:
    url: "http://<IP_HOME_ASSISTANT>:8766/print"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"

  peripage_print_todo:
    url: "http://<IP_HOME_ASSISTANT>:8766/print_todo"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"
```

Puis redémarrez Home Assistant.

---

## Endpoints API

| Méthode | Route | Description |
|---|---|---|
| `POST` | `/print` | Compose et imprime une page par blocs |
| `POST` | `/print_todo` | Récupère et imprime une liste Todo HA |
| `GET` | `/health` | Statut de l'addon |
| `GET` | `/status` | Imprimante occupée ou disponible |

---

## Référence des blocs

> ⚠️ Dans un script HA, le payload JSON doit être sur **une seule ligne** avec `>-`. Le YAML multiligne casse le JSON.

### `text` — Texte

```json
{
  "type": "text",
  "text": "Votre texte ici",
  "align": "left",
  "font_size": 24,
  "bold": false,
  "font": "DejaVu"
}
```

| Champ | Valeurs | Défaut |
|---|---|---|
| `text` | string | requis |
| `align` | `left` / `center` / `right` | `left` |
| `font_size` | entier (pixels) | config addon |
| `bold` | `true` / `false` | `false` |
| `font` | nom de police | config addon |

---

### `title` — Titre

```json
{
  "type": "title",
  "text": "Mon titre",
  "align": "center",
  "font": "DejaVuBold"
}
```

Identique à `text` mais bold et taille augmentée par défaut.

---

### `list` — Liste

```json
{
  "type": "list",
  "items": ["Premier élément", "Deuxième élément"],
  "bullet": "•",
  "font_size": 22,
  "font": "DejaVu"
}
```

| Champ | Valeurs | Défaut |
|---|---|---|
| `items` | liste de strings | requis |
| `bullet` | string | `•` |
| `font_size` | entier | config addon |
| `font` | nom de police | config addon |

---

### `separator` — Séparateur

```json
{ "type": "separator", "style": "line" }
```

| Style | Rendu |
|---|---|
| `line` | Ligne horizontale noire (défaut) |
| `dotted` | Ligne en pointillés noirs |
| `blank` | Espace vide |

---

### `image_url` — Image depuis une URL

```json
{
  "type": "image_url",
  "url": "http://<IP_HOME_ASSISTANT>:8123/local/images/photo.png"
}
```

L'image est automatiquement redimensionnée à 384px de large.

> ⚠️ Les URLs pointant vers le réseau Docker interne (`172.16.x.x`) sont bloquées pour des raisons de sécurité. Les IPs du réseau local (`192.168.x.x`) sont autorisées.

---

### `image_b64` — Image en base64

```json
{
  "type": "image_b64",
  "image": "iVBORw0KGgo..."
}
```

Taille maximale : 5 Mo encodés.

---

## Endpoint `/print_todo`

Récupère automatiquement les éléments non complétés d'une liste Todo HA et les imprime.

```bash
curl -X POST http://<IP_HOME_ASSISTANT>:8766/print_todo \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "todo.ma_liste", "title": "Ma liste"}'
```

| Champ | Description | Défaut |
|---|---|---|
| `entity_id` | Entité Todo HA | requis |
| `title` | Titre affiché en haut de la page | `Ma liste` |

---

## Blueprints disponibles

Les blueprints sont dans le dossier [`blueprints/`](./blueprints/) :

| Fichier | Description |
|---|---|
| `morning_routine.yaml` | Routine du matin : image aléatoire, encouragement, RDV, phrase finale |
| `weather_print.yaml` | Récapitulatif météo du jour |
| `todo_print.yaml` | Impression d'une liste Todo HA |

---

## Comportement en cas d'erreur

- **2 tentatives** automatiques en cas d'échec Bluetooth transitoire (imprimante occupée, hors de portée)
- **Pas de nouvelle tentative** en cas de timeout pour éviter les doubles impressions
- **10 secondes** d'attente entre les tentatives
- **Notification persistante** dans HA après échec
- Messages clairs dans les logs : imprimante éteinte, hors de portée, occupée...

---

## Test depuis le terminal

```bash
# Texte simple
curl -X POST http://<IP_HOME_ASSISTANT>:8766/print \
  -H "Content-Type: application/json" \
  -d '{"blocks": [{"type": "text", "text": "Test !"}]}'

# Liste Todo
curl -X POST http://<IP_HOME_ASSISTANT>:8766/print_todo \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "todo.ma_liste", "title": "Ma liste"}'

# Statut
curl http://<IP_HOME_ASSISTANT>:8766/health
curl http://<IP_HOME_ASSISTANT>:8766/status
```

---

## Compatibilité

Testé sur Raspberry Pi 4 (aarch64) avec PeriPage A6.

---

## ⚠️ Disclaimer

Ce projet a été réalisé avec l'aide de [Claude.ai](https://claude.ai). Créé pour aider une personne ayant un TDAH via des routines imprimées sur papier.

Merci à [bitrate16](https://github.com/bitrate16) pour la librairie `peripage-python` et à [Elias Weingärtner](https://github.com/eliasweingaertner) pour le reverse engineering du protocole.

## Licence

GPL-3.0


# Perilay — PeriPage Home Assistant Addon

A Home Assistant addon to compose and print structured pages on a **PeriPage** thermal printer via Bluetooth.

The addon receives a list of **content blocks** in JSON, automatically lays out the page (word-wrap, image resizing), and prints in a single Bluetooth connection.

## Installation

1. In Home Assistant: **Settings → Add-ons → Add-on Store → ⋮ → Repositories**
2. Add: `https://github.com/LaCorneilleDeBerni/perilay-addon`
3. Install **Perilay**
4. Configure your MAC address and start

> ⚠️ After any configuration change, **restart the addon**.

## Finding Your Printer's MAC Address

From the Home Assistant SSH terminal:

```
hcitool scan
```

It is also visible in **Settings → Bluetooth → Devices** as `PeriPage_XXXX_BLE`.

## Configuration

| Parameter | Description | Default |
| --- | --- | --- |
| `printer_mac` | Printer Bluetooth MAC address | `XX:XX:XX:XX:XX:XX` |
| `printer_model` | Model: `A6`, `A6p`, `A40`, `A40p` | `A6` |
| `font` | Default font: `DejaVu`, `DejaVuBold`, `Liberation` | `DejaVu` |
| `font_size` | Default font size in pixels | `24` |
| `port` | HTTP service port | `8766` |
| `custom_fonts` | Custom fonts (name + .ttf URL) | `[]` |

### Custom Fonts

Place your `.ttf` files in `/config/www/fonts/` and declare them in the configuration:

```
custom_fonts:
  - name: "MyFont"
    url: "http://<HOME_ASSISTANT_IP>:8123/local/fonts/MyFont.ttf"
```

## Home Assistant Integration

Add to `/config/configuration.yaml`:

```
rest_command:
  peripage_print:
    url: "http://<HOME_ASSISTANT_IP>:8766/print"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"

  peripage_print_todo:
    url: "http://<HOME_ASSISTANT_IP>:8766/print_todo"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"
```

Then restart Home Assistant.

## API Endpoints

| Method | Route | Description |
| --- | --- | --- |
| `POST` | `/print` | Compose and print a page from blocks |
| `POST` | `/print_todo` | Fetch and print a Home Assistant Todo list |
| `GET` | `/health` | Addon status |
| `GET` | `/status` | Printer busy or available |

## Block Reference

### `text` — Text

```
{
  "type": "text",
  "text": "Your text here",
  "align": "left",
  "font_size": 24,
  "bold": false,
  "font": "DejaVu"
}
```

| Field | Values | Default |
| --- | --- | --- |
| `text` | string | required |
| `align` | `left` / `center` / `right` | `left` |
| `font_size` | integer (pixels) | addon config |
| `bold` | `true` / `false` | `false` |
| `font` | font name | addon config |

### `title` — Title

Same as `text` but bold and larger by default.

### `list` — List

```
{
  "type": "list",
  "items": ["First item", "Second item"],
  "bullet": "•",
  "font_size": 22,
  "font": "DejaVu"
}
```

### `separator` — Separator

```
{ "type": "separator", "style": "line" }
```

| Style | Rendering |
| --- | --- |
| `line` | Black horizontal line (default) |
| `dotted` | Black dotted line |
| `blank` | Empty space |

### `image_url` — Image from URL

```
{
  "type": "image_url",
  "url": "http://<HOME_ASSISTANT_IP>:8123/local/images/photo.png"
}
```

### `image_b64` — Base64 Image

```
{
  "type": "image_b64",
  "image": "iVBORw0KGgo..."
}
```

## `/print_todo` Endpoint

Automatically fetches uncompleted items from a Home Assistant Todo list and prints them.

```
curl -X POST http://<HOME_ASSISTANT_IP>:8766/print_todo \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "todo.my_list", "title": "My List"}'
```

## Available Blueprints

| File | Description |
| --- | --- |
| `morning_routine.yaml` | Morning routine: random image, encouragement, appointments, final phrase |
| `weather_print.yaml` | Daily weather summary |
| `todo_print.yaml` | Print a Home Assistant Todo list |

## Error Handling

- **2 automatic retries** for transient Bluetooth failures (printer busy, out of range)
- **No retry** on timeout to avoid duplicate prints
- **10-second delay** between attempts
- **Persistent notification** in Home Assistant after failure
- Clear log messages: printer off, out of range, busy, etc.

## Testing from Terminal

```
# Simple text
curl -X POST http://<HOME_ASSISTANT_IP>:8766/print \
  -H "Content-Type: application/json" \
  -d '{"blocks": [{"type": "text", "text": "Test!"}]}'

# Todo list
curl -X POST http://<HOME_ASSISTANT_IP>:8766/print_todo \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "todo.my_list", "title": "My List"}'

# Status
curl http://<HOME_ASSISTANT_IP>:8766/health
curl http://<HOME_ASSISTANT_IP>:8766/status
```

## Compatibility

Tested on Raspberry Pi 4 (aarch64) with PeriPage A6.

## ⚠️ Disclaimer

This project was created with the help of [Claude.ai](https://claude.ai). Designed to assist a person with ADHD through printed routines.

## License

GPL-3.0
