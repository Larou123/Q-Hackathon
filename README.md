# Q-Hackathon — Agnes DSI

**Agnes DSI** (Deep Sourcing Intelligence) ist ein KI-gestütztes Einkaufs- und Lieferanten-Dashboard.

## Idee

Die Idee hinter Agnes DSI ist ein Procurement-Copilot für Sourcing-Entscheidungen:

- `db.sqlite` bildet die interne Datenbasis mit Produkten, BOMs, Rohstoffen, Lieferanten und Unternehmen.
- `server.py` liest diese Daten lokal aus, erzeugt daraus eine kompakte `data.json` und stellt das Projekt auf Port `3000` bereit.
- `index.html` ist die Demo-Oberfläche und zeigt zentrale Kennzahlen sowie den fokussierten Rohstoff aus der SQLite-Datenbank.
- Das Dashboard startet jetzt mit einer kugelartigen Agnes-Orb-Ansicht: per Text oder Mikrofon fragt man nach Empfehlungen, und Agnes antwortet mit live aus `db.sqlite` abgeleiteten Replacement-, Supplier- und BOM-Empfehlungen.
- Die Suppliers-Seite rendert die vollständige Registry mit allen `40` Lieferanten direkt aus `db.sqlite`.
- Die BOM-Seite zeigt jetzt die vollständige Registry aller `149` BOMs inklusive Komponentenanzahl, Top-Unternehmen und Markierung der `11` BOMs mit `Vitamin D3 Cholecalciferol`.
- Der neue Finished-Goods-Reiter zeigt alle `149` Finished Goods aus `db.sqlite` und listet pro Produkt exakt die verknüpften Raw Materials aus der BOM.
- Der neue Standardization-Reiter bündelt wahrscheinliche Duplicate- oder Alias-Rohstoffe zu Material-Clustern, damit Agnes früh auf supplierübergreifende Standardisierungschancen hinweisen kann, bevor später ein Qualitätsranking pro Supplier folgt.
- Die Cluster-Heuristik berücksichtigt jetzt auch robuste Schreibvarianten wie Hyphen-/Spacing-Unterschiede, zum Beispiel `softgel` vs `soft-gel` oder `Hydroxypropyl Methylcellulose` vs `Hydroxypropyl Methyl Cellulose`.
- Auf den Material-Clustern liegt jetzt eine erste Recommendation Layer: Agnes schlägt pro Cluster einen `Preferred Supplier` und einen `Backup Supplier` vor, basierend auf internen Signalen wie Cluster-Abdeckung, Produktreichweite, Supplier-Netzwerkstärke und Kontinuität auf dem Fokusmaterial. Qualität, Compliance, Preis, Lead Time und MOQ sind bewusst noch als nächster Schritt offen markiert.
- Die Recommendation Layer hat jetzt zusätzlich eine ehrliche `Decision Readiness`: Agnes markiert pro Cluster, ob es nur shortlist-ready ist, noch Procurement-Review braucht oder wegen claim-/formulierungsnahen Namenssignalen externe Evidenz erfordert. Fehlende Quality-, Compliance- und Commercial-Nachweise werden direkt im UI als offene Checks angezeigt.
- Der `Sourcing Decisions`-Reiter ist jetzt kein statischer Pitch-Screen mehr, sondern ein echter Decision Workspace aus `db.sqlite`: Agnes zeigt dort den aktuellen Fokus-Cluster, Lead- und Backup-Supplier, die betroffenen BOMs und Finished Goods, Supplier-Pfade im Vergleich sowie die klare Grenze zwischen internen Signalen und noch fehlender externer Evidenz.
- Zusätzlich gibt es jetzt ein lokales `evidence_store.json` als Integrationsgerüst für die nächste Stufe: Dort können später Scraping-Ergebnisse, PDFs, API-Responses, Extraktionen, Auditor-Urteile und Commercial-Daten pro Material-Cluster und Supplier gecacht werden. Die UI zeigt diese Pipeline schon heute als vorbereitete Supplier-Tracks mit Retrieval-, Extraction-, Audit- und Commercial-Status an.
- Die Hauptoberfläche ist jetzt bewusst einfacher geschnitten: Statt vieler technischer Hauptreiter liegt die Kernnavigation auf `Dashboard`, `Decisions`, `Products` und `Suppliers`. BOMs, Finished Goods und Standardization bleiben als Deep-Dives erhalten, aber die primäre Story für Demo und Jury ist deutlich klarer.
- Das Dashboard hat jetzt eine echte, datengetriebene `Agnes action queue`: `server.py` priorisiert konkrete nächste Moves wie Lead-Lane-Shift, Backup-Coverage oder Standardisierung als klickbare Action-Objekte mit Status, Begründung und Deep Link in die passende Detailansicht.
- Der `Decisions`-Screen wurde zusätzlich entschlackt: Sichtbar bleiben nur Decision Brief, Schlüssel-Supplier, betroffene Products und Next Actions. Boundary, offene Evidenz, alle Supplier-Pfade und die Evidence-Pipeline liegen als Deep Dives hinter Toggles. Preferred Supplier, Backup Supplier, Cluster und betroffene Products sind jetzt direkt klickbar.
- Der `Decisions`-Screen visualisiert Agnes' Entscheidung jetzt klarer: eine kompakte `Detect → Verify → Recommend`-Leiste erklärt den Weg zur Entscheidung, Supplier-Lanes zeigen echte Balken für Score, Coverage und Product Reach, und die rechte Seite fasst `Decision footprint` sowie `Evidence readiness` als kleine Graphen statt nur als Zahlenboxen zusammen.
- Die Supplier-Lanes im `Decisions`-Screen erklären jetzt direkt auf der Karte, warum eine Lane bevorzugt ist oder warum der Backup-Score niedriger liegt, zum Beispiel wenn der Unterschied nur aus `network strength` entsteht.
- Die `Open checks`-, `Evidence deep dive`- und ähnlichen CTA-Buttons im `Decisions`-Screen öffnen ihre Bereiche jetzt nicht nur, sondern scrollen auch direkt zur passenden Sektion, damit der Deep Dive sofort sichtbar wird.
- Damit der Fokus nicht immer nur auf `Vitamin D3` festhängt, zeigt `Decisions` jetzt zusätzlich eine kompakte Leiste `Other live lanes`: Von dort kann man ohne komplizierten Umbau direkt in andere shortlist-ready oder review-relevante Material-Lanes springen und den passenden Cluster-Deep-Dive öffnen.
- Agnes kann jetzt optional in einen echten ElevenLabs-Live-Conversation-Modus wechseln: Die Orb startet dann eine Voice-Session, typed Fragen gehen in dieselbe laufende Konversation, und Agnes bekommt zur Laufzeit einen internen Snapshot-Prompt plus lokale Client-Tools für Material-/Supplier-Lookups wie `gelatin`.
- Wenn der ElevenLabs-Live-Agent die Session unerwartet beendet, fällt Agnes für typed Fragen automatisch auf den lokalen Snapshot-Modus zurück und beantwortet die offene Frage trotzdem weiter aus `db.sqlite`.
- Um die häufigen ElevenLabs-Audio-Disconnects zu vermeiden, startet Agnes jetzt standardmäßig über eine stabilere textbasierte ElevenLabs-Session; Browser-Mikrofon-Eingaben können trotzdem in dieselbe Session fließen.
- Antworten aus dieser stabilen Text-Session werden jetzt zusätzlich direkt über den Browser vorgelesen, damit Agnes trotz textbasierter Live-Session hörbar bleibt.
- Der Voice-Flow ist jetzt hands-free: Wenn Agnes eine Antwort fertig vorgelesen hat, öffnet sie automatisch wieder das Mikrofon, damit ein fließendes Gespräch mit Follow-up-Fragen möglich bleibt, solange die Session aktiv ist.
- Follow-up-Fragen in der Web-UI laufen bei aktiver textbasierter ElevenLabs-Session jetzt bewusst über Agnes' stabile lokale Entscheidungslogik weiter. Dadurch bleiben mehrstufige Rückfragen und Anschlussfragen möglich, ohne dass der Voice-Loop oder das Mikrofon dabei neu kaputtgehen.
- Agnes ist im Web-UI jetzt auf Englisch festgesetzt: Browser-Mikrofon, lokale Antworten und ElevenLabs-TTS laufen bewusst mit `en-US`/`en`, damit kein deutscher Antwortpfad mehr dazwischenfunkt.
- Die sichtbaren Agnes-Texte im Dashboard sprechen jetzt bewusster in Business-Sprache: technische Begriffe wie Session-IDs, Agent-Typen oder Voice-Provider stehen nicht mehr im Vordergrund, damit die Oberfläche eher wie ein Enterprise-Copilot und weniger wie ein Tool-Debug-Panel wirkt.
- Die Suche oben rechts ist jetzt eine echte globale Agnes-Suche: Sie findet Actions, Material-Lanes, Suppliers und Products, zeigt direkte Trefferlisten unter dem Feld und springt per Klick oder Enter direkt in die passende Detailansicht.
- Begrifflich ist die Oberfläche ebenfalls klarer geworden: Statt technischer Labels wie `Affected finished goods` oder `Underlying BOM registry` spricht Agnes jetzt an den relevanten Stellen eher von `Affected products` und `Source formula records`.
- Der lokale Agnes-Q&A-Layer beantwortet jetzt direkte Supplier-Fragen sauberer, zum Beispiel `Which suppliers sell gelatin?` oder `What does Prinova USA sell?`, ohne wieder in allgemeine Reformulation- oder Standardisierungsantworten abzudriften.
- Die vier Dashboard-`Quick prompts` laufen jetzt bewusst über feste lokale Agnes-Intents: `What should we replace?`, `Who should lead Vitamin D3?`, `Where is the biggest BOM risk?` und `What should we standardize?` geben dadurch stabilere, deterministische Antworten statt vom Live-Agent zufällig umgedeutet zu werden.
- Der lokale Intent `Who should lead Vitamin D3?` greift jetzt sauber auf den echten `sourcing_decision`-Kontext zu. Damit beantwortet Agnes die Lead-Supplier-Frage wieder zuverlässig mit Scope, Backup und Decision Stage statt an einem kaputten Feldzugriff still zu scheitern.
- Die Web-UI registriert die Agnes-Client-Tools jetzt wieder direkt beim ElevenLabs-Sessionstart. Dadurch können Live-Fragen wie `Which suppliers sell gelatin?` dieselben lokalen Lookup-Funktionen verwenden wie die stabile Snapshot-Ansicht, statt mit `Tool failed` zu enden.
- Supplier und BOMs sind klickbar: Ein Detail-Modal zeigt bei Suppliern alle gelinkten Products und bei BOMs alle enthaltenen Components aus der echten Datenbank.
- Die Supplier-Karten zeigen jetzt nur noch die sinnvolle Kennzahl `raw materials`; der Klick öffnet weiterhin alle gelinkten Products.

Aktuell basiert die Live-Demo auf diesen echten Werten aus `db.sqlite`:

- `1025` Produkte insgesamt
- `876` Rohmaterialien
- `149` Finished Goods und `149` BOMs
- `1528` BOM-Komponenten
- `40` Lieferanten
- `61` Companies
- Fokusmaterial: `Vitamin D3 Cholecalciferol`
- Lieferanten dafür: `Prinova USA`, `PureBulk`
- Betroffene Company: `Nature Made`

## Start

```bash
python3 server.py
```

Danach ist die Demo unter `http://localhost:3000` erreichbar.

## ElevenLabs Voice

Für die Live-Conversation mit ElevenLabs:

```bash
export ELEVENLABS_AGENT_ID=your_agent_id
export ELEVENLABS_API_KEY=your_api_key   # optional, only needed for private agents
# optional overrides for spoken Agnes answers
export ELEVENLABS_TTS_VOICE_ID=your_voice_id
export ELEVENLABS_TTS_MODEL_ID=eleven_multilingual_v2
python3 server.py
```

- Ohne `ELEVENLABS_API_KEY` nutzt Agnes einen öffentlichen Agent per `agentId`.
- Mit `ELEVENLABS_API_KEY` stellt `server.py` zusätzlich einen privaten Token-Endpunkt unter `/api/agnes/elevenlabs/conversation-token` bereit.
- Für hörbare Agnes-Antworten kann `server.py` jetzt zusätzlich echte ElevenLabs-TTS-Audiofiles unter `/api/agnes/elevenlabs/tts` generieren. Wenn keine `ELEVENLABS_TTS_VOICE_ID` gesetzt ist, versucht der Server die Voice automatisch aus der ElevenLabs-Agent-Konfiguration zu lesen.
- Wenn der private Token-Pfad in der Web-UI mit `The AI agent you are trying to reach does not exist.` scheitert, versucht Agnes automatisch noch einmal denselben Agenten direkt per `agentId`, damit die Web-App näher an der funktionierenden Public-Preview bleibt.
- Im Live-Modus nutzt Agnes Laufzeit-Prompt-Overrides, dynamische Variablen und lokale Client-Tools für `lookupMaterialSuppliers`, `lookupSupplierCatalog`, `openSupplierDetail` und `openMaterialCluster`.
- Die Client-Tools für Supplier- und Material-Lookups gehen jetzt zuerst auf dieselben JSON-Endpunkte wie die späteren Server-/Webhook-Tools und fallen nur bei Fehlern kontrolliert auf den lokalen Snapshot zurück, statt die Session mit `Tool failed` zu verlieren.
- Die Web-UI startet die ElevenLabs-Session inzwischen bewusst näher an der funktionierenden ElevenLabs-Preview: stabile textbasierte WebSocket-Session, dynamische Variablen und Context-Updates bleiben aktiv, aber Agent-Prompt und Tool-Konfiguration kommen primär aus dem in ElevenLabs gespeicherten Agent selbst.
- Für ElevenLabs Server-/Webhook-Tools stehen jetzt zusätzlich diese Backend-Endpunkte bereit:
  - `POST /api/elevenlabs/material-suppliers`
  - `POST /api/elevenlabs/supplier-catalog`
- Diese Webhook-Endpunkte funktionieren auch per `GET` mit Query-Parametern, zum Beispiel `?query=gelatin`.
- Wichtig: Für ElevenLabs Server Tools reicht `localhost` nicht. Du brauchst dafür eine öffentlich erreichbare URL auf deinen lokalen Server, zum Beispiel über einen Tunnel.
