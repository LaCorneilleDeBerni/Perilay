# Guide de configuration — Perilay

Bienvenue dans l'addon Perilay. Ce guide vous accompagne pas à pas pour configurer et utiliser l'addon.

---

## 1. Prérequis

- Une imprimante thermique **PeriPage** (A6, A6p, A40, A40p)
- Home Assistant avec Bluetooth fonctionnel
- L'addon installé depuis le dépôt : `https://github.com/LaCorneilleDeBerni/perilay-addon`

---

## 2. Trouver l'adresse MAC de votre imprimante

Allumez votre imprimante, puis cherchez-la de deux façons :

**Via l'interface HA :** Paramètres → Bluetooth → Annonces
Elle apparaît sous la forme `PeriPage_XXXX_BLE`. Notez l'adresse MAC associée.

**Via le terminal SSH :**
```bash
hcitool scan
```

---

## 3. Configuration de l'addon

Renseignez les champs suivants dans l'onglet **Configuration** de l'addon :

| Paramètre | Description | Exemple |
|---|---|---|
| `printer_mac` | Adresse MAC de l'imprimante | `B5:5B:13:0A:76:95` |
| `printer_model` | Modèle de l'imprimante | `A6` |
| `font` | Police par défaut | `DejaVu` |
| `font_size` | Taille de police en pixels | `24` |
| `port` | Port HTTP de l'addon | `8766` |

Cliquez sur **Enregistrer** puis **Démarrer**.

---

## 4. Polices disponibles

Trois polices sont intégrées :

- **DejaVu** — police standard, lisible
- **DejaVuBold** — police grasse
- **Liberation** — alternative à DejaVu

### Polices personnalisées

Vous pouvez ajouter vos propres polices `.ttf` :

1. Placez le fichier dans `/config/www/fonts/` sur votre serveur HA
2. Déclarez-la dans la configuration :

```yaml
custom_fonts:
  - name: "MaPolice"
    url: "http://<IP_HA>:8123/local/fonts/MaPolice.ttf"
```

> Les polices sont téléchargées au démarrage de l'addon. Redémarrez l'addon après tout changement.

---

## 5. Intégration dans Home Assistant

Ajoutez ces deux commandes dans `/config/configuration.yaml` :

```yaml
rest_command:
  peripage_print:
    url: "http://<IP_HA>:8766/print"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"

  peripage_print_todo:
    url: "http://<IP_HA>:8766/print_todo"
    method: POST
    content_type: "application/json"
    payload: "{{ payload }}"
```

Remplacez `<IP_HA>` par l'adresse IP de votre serveur Home Assistant, puis redémarrez HA.

---

## 6. Vérifier que tout fonctionne

Depuis un terminal, testez l'impression :

```bash
curl -X POST http://<IP_HA>:8766/print \
  -H "Content-Type: application/json" \
  -d '{"blocks": [{"type": "text", "text": "Hello !"}]}'
```

Vérifiez le statut de l'addon :

```bash
curl http://<IP_HA>:8766/health
curl http://<IP_HA>:8766/status
```

La réponse de `/status` indique si l'imprimante est occupée (`busy: true`) et la profondeur de la file d'attente (`queue_depth`).

---

## 7. Composer une page — les blocs

Une page est composée d'une liste de blocs JSON. Chaque bloc correspond à un élément visuel.

> ⚠️ Dans un script HA, le payload doit être sur **une seule ligne** avec `>-`.

### Texte simple
```json
{"type": "text", "text": "Votre texte", "align": "left", "font_size": 24, "bold": false, "font": "DejaVu"}
```

| Champ | Valeurs | Défaut |
|---|---|---|
| `align` | `left` / `center` / `right` | `left` |
| `font_size` | entier (pixels) | config addon |
| `bold` | `true` / `false` | `false` |
| `font` | nom de police | config addon |

### Titre
```json
{"type": "title", "text": "Mon titre", "align": "center", "font": "DejaVuBold"}
```

Identique à `text` mais bold et taille augmentée par défaut.

### Liste à puces
```json
{"type": "list", "items": ["Élément 1", "Élément 2"], "bullet": "•", "font": "DejaVu"}
```

### Séparateur
```json
{"type": "separator", "style": "line"}
```

| Style | Rendu |
|---|---|
| `line` | Ligne horizontale noire (défaut) |
| `dotted` | Pointillés noirs |
| `blank` | Espace vide |

### Image depuis une URL
```json
{"type": "image_url", "url": "http://<IP_HA>:8123/local/images/photo.png"}
```

L'image est automatiquement redimensionnée à 384px de large.

> ⚠️ Les URLs du réseau Docker interne (`172.16.x.x`) sont bloquées. Les IPs locales (`192.168.x.x`) sont autorisées.

### Image en base64
```json
{"type": "image_b64", "image": "iVBORw0KGgo..."}
```

Taille maximale : 5 Mo encodés.

---

## 8. Imprimer une liste Todo

L'addon peut récupérer et imprimer directement une liste Todo de HA :

```bash
curl -X POST http://<IP_HA>:8766/print_todo \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "todo.ma_liste", "title": "Liste de courses"}'
```

Seuls les éléments **non complétés** sont imprimés, avec une case à cocher `[ ]` devant chaque élément pour pouvoir les cocher sur le papier.

---

## 9. Blueprints

Trois blueprints sont disponibles dans le dossier `blueprints/` du dépôt :

**Routine du matin** (`morning_routine.yaml`)
Imprime chaque matin : prénom, date, image aléatoire, phrase d'encouragement, RDV du jour, phrase finale.

**Météo du jour** (`weather_print.yaml`)
Imprime un récapitulatif météo : conditions, températures, précipitations, vent.

**Liste Todo** (`todo_print.yaml`)
Imprime le contenu d'une liste Todo HA en un clic.

Pour importer un blueprint : **Paramètres → Automatisations → Blueprints → Importer un blueprint**

---

## 10. Gestion des erreurs

L'addon effectue jusqu'à **2 tentatives** en cas d'échec Bluetooth, avec 10 secondes d'attente entre chaque.

**Important :** en cas de timeout, l'addon ne retente **pas** automatiquement pour éviter les doubles impressions (l'imprimante a peut-être bien reçu les données mais la connexion Bluetooth s'est coupée juste après).

En cas d'échec complet, une **notification persistante** apparaît dans HA avec le message d'erreur.

Messages possibles dans les logs :

- `Imprimante éteinte ou hors de portée Bluetooth` — rallumez l'imprimante
- `Imprimante occupée` — fermez l'application mobile PeriPage
- `Imprimante introuvable` — vérifiez l'adresse MAC dans la configuration
- `Timeout` — l'impression a peut-être réussi, vérifiez le papier avant de relancer

---

## 11. Dépannage

**L'addon ne démarre pas**
Vérifiez que l'adresse MAC est correcte et non égale à `XX:XX:XX:XX:XX:XX`.

**L'impression ne sort pas mais les logs disent "succès"**
Assurez-vous que l'imprimante n'est pas connectée à l'application mobile en même temps.

**Double impression**
Cela peut arriver si vous relancez manuellement après un timeout. Vérifiez toujours le papier avant de relancer.

**Les polices personnalisées ne s'affichent pas**
Vérifiez que l'URL est accessible depuis le navigateur : `http://<IP_HA>:8123/local/fonts/MaPolice.ttf`
Redémarrez l'addon après avoir ajouté une nouvelle police.

**Le blueprint ne trouve pas les images**
Vérifiez le dossier et le préfixe. Les fichiers doivent être numérotés sur 5 chiffres : `Maurice_00001.png`.

**Les images locales sont bloquées**
Les URLs doivent pointer vers votre IP locale (ex. `192.168.1.x`), pas vers `localhost` ou le réseau Docker interne.
