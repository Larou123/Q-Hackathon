# Q-Hackathon — Agnes DSI

**Agnes DSI** (Deep Sourcing Intelligence) ist ein KI-gestütztes Einkaufs- und Lieferanten-Dashboard.

---

## Farbsystem (Material Design 3 – Light Theme)

Das gesamte UI basiert auf einem Material You Farbsystem. Alle Farben sind als Tailwind-Custom-Properties definiert.

### Primärfarben

| Token                      | Hex       | Verwendung                                              |
|----------------------------|-----------|---------------------------------------------------------|
| `primary`                  | `#0040a1` | Hauptakzent: Buttons, Links, Icons, Highlights          |
| `on-primary`               | `#ffffff` | Text/Icons auf `primary`-Hintergrund                   |
| `primary-container`        | `#0056d2` | Karten-Hintergründe mit starkem Akzent (z.B. Savings-Card) |
| `on-primary-container`     | `#ccd8ff` | Text auf `primary-container`                           |
| `primary-fixed`            | `#dae2ff` | Helle Variante für fixe Primärelemente                 |
| `primary-fixed-dim`        | `#b2c5ff` | Gedimmte Fixvariante, Glow-Effekte                     |
| `on-primary-fixed`         | `#001847` | Text auf hellem Primary-Fixed                          |
| `on-primary-fixed-variant` | `#0040a1` | Variante für Text auf Fixed-Hintergründen              |
| `inverse-primary`          | `#b2c5ff` | Primärfarbe auf inversen (dunklen) Oberflächen         |
| `surface-tint`             | `#0056d2` | Tint-Overlay für Oberflächen                           |

### Sekundärfarben

| Token                        | Hex       | Verwendung                                  |
|------------------------------|-----------|---------------------------------------------|
| `secondary`                  | `#525f73` | Sekundäre UI-Elemente                       |
| `on-secondary`               | `#ffffff` | Text auf `secondary`                        |
| `secondary-container`        | `#d6e3fb` | Helle Container in Sekundärfarbe            |
| `on-secondary-container`     | `#586579` | Text in `secondary-container`               |
| `secondary-fixed`            | `#d6e3fb` | Fixe Sekundärfarbe (hell)                   |
| `secondary-fixed-dim`        | `#bac7de` | Gedimmte Sekundärfarbe                      |
| `on-secondary-fixed`         | `#002111` | Text auf sekundärem Fixed                   |
| `on-secondary-fixed-variant` | `#3b485a` | Variante für Text auf sekundärem Fixed      |

### Tertiärfarben (Grün — Compliance / Erfolg)

| Token                        | Hex       | Verwendung                                                    |
|------------------------------|-----------|---------------------------------------------------------------|
| `tertiary`                   | `#005232` | Grün für "Auto-Approve"-Badges, Verified-Icons                |
| `on-tertiary`                | `#ffffff` | Text auf `tertiary`                                           |
| `tertiary-container`         | `#006d44` | Badge-Hintergrund für Compliance-Status                       |
| `on-tertiary-container`      | `#6ef1ad` | Text in `tertiary-container`                                  |
| `tertiary-fixed`             | `#78fbb6` | Helles Grün für fixe Elemente                                 |
| `tertiary-fixed-dim`         | `#59de9b` | Gedimmtes Grün                                                |
| `on-tertiary-fixed`          | `#002111` | Text auf hellem tertiärem Fixed                               |
| `on-tertiary-fixed-variant`  | `#005232` | Variante für Text auf tertiärem Fixed                         |

### Fehlerfarben

| Token               | Hex       | Verwendung                         |
|---------------------|-----------|------------------------------------|
| `error`             | `#ba1a1a` | Fehlermeldungen, kritische Alerts  |
| `on-error`          | `#ffffff` | Text auf `error`                   |
| `error-container`   | `#ffdad6` | Hintergrund für Fehlerbereiche     |
| `on-error-container`| `#93000a` | Text in `error-container`          |

### Oberflächen & Hintergründe

| Token                        | Hex       | Verwendung                                              |
|------------------------------|-----------|---------------------------------------------------------|
| `background`                 | `#f8f9fa` | Seitenhintergrund                                       |
| `on-background`              | `#191c1d` | Standardtext auf Hintergrund                            |
| `surface`                    | `#f8f9fa` | Basis-Oberfläche für Karten/Panels                      |
| `on-surface`                 | `#191c1d` | Primärer Text auf Oberflächen                           |
| `surface-variant`            | `#e1e3e4` | Variante für abgehobene Oberflächen                     |
| `on-surface-variant`         | `#424654` | Sekundärer Text, Labels, Hints                          |
| `surface-dim`                | `#d9dadb` | Abgedunkelte Oberfläche                                 |
| `surface-bright`             | `#f8f9fa` | Aufgehellte Oberfläche                                  |
| `surface-container-lowest`   | `#ffffff` | Karten, Tabellenzellen (hellste Variante)               |
| `surface-container-low`      | `#f3f4f5` | Tabellenhintergrund, Suchfelder                         |
| `surface-container`          | `#edeeef` | Mittlerer Container                                     |
| `surface-container-high`     | `#e7e8e9` | Erhöhter Container                                      |
| `surface-container-highest`  | `#e1e3e4` | Höchster Container-Kontrast                             |
| `inverse-surface`            | `#2e3132` | Dunkle Tooltips (z.B. "Ask Agnes"-Tooltip)              |
| `inverse-on-surface`         | `#f0f1f2` | Text auf `inverse-surface`                             |

### Konturen & Outlines

| Token              | Hex       | Verwendung                          |
|--------------------|-----------|-------------------------------------|
| `outline`          | `#737785` | Rahmen, Trennlinien                 |
| `outline-variant`  | `#c3c6d6` | Dezente Trennlinien                 |

---

## Compliance-Status Farbcodierung

| Status         | Hintergrund         | Textfarbe        | Punkt          |
|----------------|---------------------|------------------|----------------|
| Auto-Approve   | `tertiary/10%`      | `tertiary` (grün)| `bg-tertiary`  |
| Human Review   | `amber-100`         | `amber-700`      | `bg-amber-500` |

---

## Typografie

| Rolle       | Familie   | Verwendung                        |
|-------------|-----------|-----------------------------------|
| `headline`  | Manrope   | Überschriften, Zahlen, Markennamen |
| `body`      | Inter     | Fließtext, Tabellendaten          |
| `label`     | Inter     | Labels, Badges, Metadaten         |

---

## Dateien

| Datei        | Beschreibung                  |
|--------------|-------------------------------|
| `index.html` | Haupt-Dashboard (Agnes DSI)   |
| `README.md`  | Dokumentation & Farbsystem    |
