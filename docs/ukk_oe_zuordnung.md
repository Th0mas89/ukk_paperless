# Benutzer einer OE zuordnen (und der Weg zur AD-Synchronisation)

## Ist-Zustand: Was ist eine "OE" technisch?

Es gibt aktuell **kein eigenes OE-Modell**. Eine Organisationseinheit (OE) ist
schlicht eine ganz normale Django-**Gruppe** (`auth.Group`):

- [`Case.organizational_unit`](../src/documents/models.py) ist ein Freitextfeld.
  Ein Fall gehört zu der OE, deren Name hier eingetragen ist
  (z. B. `"Station A"`).
- [`IndexView.get_context_data`](../src/documents/views.py) ermittelt die für
  einen Benutzer sichtbaren OEs aus `request.user.groups` und filtert die
  Patientenliste auf `Case.objects.filter(organizational_unit__in=active_oes)`.
- D. h. **Gruppenname == OE-Name**. Ein Benutzer kann schon heute mehreren
  Gruppen angehören und sieht dann die Patienten aller dieser OEs gleichzeitig
  (`user_groups`/`active_oes` ist eine Liste, kein Einzelwert).

Konsequenz: Um `osterholt` einer OE zuzuordnen, muss er lediglich Mitglied der
gleichnamigen Django-Gruppe werden.

## Schritt 1 (jetzt): Benutzer manuell einer OE zuordnen

**Empfohlen — über die Paperless-ngx-Oberfläche selbst**
(nicht das Django-Admin, sondern die reguläre App-UI, da Paperless-ngx Gruppen
über eine eigene API verwaltet, `GroupViewSet` in
[`src/paperless/views.py`](../src/paperless/views.py)):

1. Als Admin einloggen → **Einstellungen → Benutzer & Gruppen**.
2. Falls die OE als Gruppe noch nicht existiert: neue Gruppe mit dem exakten
   OE-Namen anlegen (z. B. `Station A`). Der Name muss **exakt** so lauten wie
   der Wert, der später in `Case.organizational_unit` steht.
3. Beim Benutzer `osterholt` unter "Gruppen" die gewünschte(n) OE-Gruppe(n)
   auswählen und speichern. Mehrfachauswahl ist möglich → ein Benutzer kann
   bereits heute mehreren OEs zugeordnet werden.

**Alternativ — per Management-Shell** (z. B. im Container):

```bash
docker compose exec webserver python manage.py shell -c "
from django.contrib.auth.models import User, Group
u = User.objects.get(username='Thomas.Osterholt@uk-koeln.de')
g, _ = Group.objects.get_or_create(name='Station A')
u.groups.add(g)
"
```

**Zum Testen mit Beispieldaten:** Der Management-Befehl `seed_patients`
(`src/documents/management/commands/seed_patients.py`) legt pro OE 5
Test-Patienten mit Fall an, standardmäßig für alle existierenden Gruppen:

```bash
docker compose exec webserver python manage.py seed_patients --oe "Station A" "Station B" --count 5
```

## Schritt 2 (Ziel): OE-Zuordnung per AD-Synchronisation

Paperless-ngx bringt bereits einen fertigen Mechanismus mit, der bei jedem
SSO-Login die Gruppenmitgliedschaft eines Benutzers aus einem Claim des
Identity Providers übernimmt — **das ist der vorgesehene Weg für die
AD-Anbindung**, es muss kein eigener Sync-Job geschrieben werden.

### Funktionsweise (bereits im Code vorhanden)

- [`paperless/signals.py::handle_social_account_updated`](../src/paperless/signals.py)
  wird bei jedem Social-/OIDC-/SAML-Login ausgeführt.
- Ist `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=true`, liest die Funktion aus dem
  Login-Claim (Standard-Claim-Name: `groups`) die Liste der Gruppen des
  Benutzers beim IdP und setzt sie 1:1 als Django-Gruppen:
  `sociallogin.user.groups.set(groups, clear=True)`.
- Es wird **nach Namen gematcht**: Es werden nur die Django-Gruppen gesetzt,
  deren Name exakt einem Eintrag in der Claim-Liste entspricht
  (`Group.objects.filter(name__in=social_account_groups)`). Gruppen, die es in
  Paperless noch nicht gibt, werden **nicht automatisch angelegt**.
- `clear=True` bedeutet: bei jedem Login werden die Gruppen komplett neu
  gesetzt (kein manuelles Hinzufügen/Entfernen von OEs nötig, aber auch keine
  manuellen OE-Zuordnungen, die einen Sync-Login überleben — AD ist dann die
  "Source of Truth").

### Relevante Einstellungen (`docker-compose.env`)

| Variable | Zweck |
|---|---|
| `PAPERLESS_SOCIALACCOUNT_PROVIDERS` | JSON-Konfiguration des OIDC/SAML-Providers (Client-ID, Secret, Endpunkte etc.) |
| `PAPERLESS_SOCIAL_AUTO_SIGNUP` | Benutzer beim ersten SSO-Login automatisch anlegen |
| `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS` | `true` aktiviert den oben beschriebenen Gruppen-Sync |
| `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS_CLAIM` | Name des Claims mit der Gruppenliste (Default: `groups`) |
| `PAPERLESS_SOCIAL_ACCOUNT_DEFAULT_GROUPS` | Gruppen, die jedem neuen Social-Login-Benutzer zusätzlich fest zugewiesen werden |
| `PAPERLESS_SOCIAL_ACCOUNT_SYNC_SUPERUSER_GROUP` / `..._SYNC_STAFF_GROUP` | Optional: bestimmte AD-Gruppe schaltet Admin-/Staff-Rechte frei |

### Voraussetzung, die noch offen ist

Dieser Mechanismus setzt einen **OIDC- oder SAML-Identity-Provider** voraus,
der die AD-Gruppen als Claim herausgibt (z. B. Microsoft Entra ID/ADFS direkt,
oder Keycloak mit AD/LDAP als Backend). Für UKK ist noch zu klären:

1. Über welchen IdP soll SSO laufen (Entra ID / ADFS / Keycloak / anderer)?
2. Wird der Claim `groups` die AD-Gruppennamen 1:1 enthalten, oder müssen sie
   im IdP erst gemappt/gefiltert werden (AD-Gruppen sind oft sehr viele; hier
   sollten nur die OE-relevanten Gruppen im Claim landen)?
3. Die Django-Gruppen (= OE-Namen) müssen **vorab in Paperless existieren**
   und exakt den Namen aus dem Claim entsprechen — sonst greift der
   Namensabgleich nicht und die OE-Zuordnung bleibt leer.
4. Falls stattdessen ein direkter LDAP-Bind gegen das AD gewünscht ist (ohne
   IdP dazwischen), ist das **aktuell nicht implementiert** — dafür wäre
   zusätzlich `django-auth-ldap` samt eigener Gruppen-Mapping-Konfiguration
   nötig. Das ist eine separate Entscheidung, kein Teil des bestehenden
   Social-Login-Mechanismus.

## Kurzfassung

- **Heute:** OE-Zuordnung = Django-Gruppen-Mitgliedschaft, manuell über
  Einstellungen → Benutzer & Gruppen (oder Shell) pflegbar, mehrere OEs pro
  Benutzer funktionieren bereits.
- **Später:** `PAPERLESS_SOCIAL_ACCOUNT_SYNC_GROUPS=true` am bestehenden
  OIDC/SAML-Login aktivieren, AD-Gruppen im `groups`-Claim bereitstellen, und
  die gleichnamigen Gruppen einmalig in Paperless anlegen. Kein
  Zusatzentwicklung nötig — nur Konfiguration des IdP und der Env-Variablen.
