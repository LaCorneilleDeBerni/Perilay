# Perilay — Home Assistant Addon

Addon Home Assistant pour composer et imprimer des pages structurées sur une imprimante thermique **PeriPage** via Bluetooth.

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
