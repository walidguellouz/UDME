# UDME — Universal Database Mapping Engine

Implémentation du cahier des charges (plan v1.0) : agent local en lecture seule → paquet de métadonnées
canonique signé → API SaaS multi-tenant → inférence de relations → mapping métier → revue humaine → exports.

```
core/      udme_core : modèle canonique, connecteur SQLAlchemy, fingerprint, inférence, mapper, signature, exports
agent/     udme-agent : CLI (discover | scan | analyze | diff)
frontend/  Angular 19 (standalone) + Cytoscape : connexion, scans, schéma, graphe, revue, diff, export
backend/   Django + DRF + Celery : tenants, enrôlement, ingestion, revue, audit, export
tests/     fixture synthétique « legacy sans FK » + tests du cœur
```

## Démarrage rapide (sans serveur)
```bash
pip install -e core -e agent
python tests/make_fixture.py demo.db
UDME_DB_URL=sqlite:///demo.db udme-agent scan --out out --product-hint WinGest
# -> out/package.json, mapping.json, relationships.csv, dictionary.md (ERD Mermaid), schema.ddl.sql
```
Moteur inconnu : `udme-agent discover --path <fichier_db> --config <fichier.ini>` (aucun fichier brut n'est envoyé).
SQL Server / Firebird etc. : installez le pilote SQLAlchemy voulu, fournissez un compte lecture seule et `--confirm-read-only`.

## Déploiement
Voir **DEPLOY_RENDER.md** (Blueprint `render.yaml`, Dockerfile unique, enrôlement de l'agent).

## Backend
```bash
pip install -e core && pip install -r backend/requirements.txt
cd backend && python manage.py migrate && python manage.py test udme_api && python manage.py runserver
# ou : docker compose up --build
```
Flux : admin `POST /api/v1/sites/{id}/enrollment-tokens` → (ou page Agents du site) → `POST /agents/enroll` (secret affiché une fois)
→ agent `enroll --server URL --token JETON` (identifiants stockés dans ~/.udme/agent.json) → agent `scan --upload`
→ `GET /scans/{id}/graph` → `POST /relationships|mappings/{id}/review` → `GET /scans/{id}/export?fmt=json|csv|md|ddl`.

## Frontend
```bash
cd frontend && npm install
npm start            # http://localhost:4200, proxy /api -> http://localhost:8000
npm run build        # dist/udme : à servir derrière le même domaine que l'API (reverse proxy)
```
Écrans : connexion (jeton, sessionStorage) · liste des scans · aperçu (avertissements de couverture en évidence) · explorateur de schéma ·
graphe ERD filtrable (score min., masquer tables isolées, plafond 300 nœuds, FK déclarées en trait plein) · revue avec preuves
(accepter / rejeter / modifier ; boutons masqués pour le rôle viewer) · vue tableau accessible · comparaison de scans · export avec confirmation.

## Recherche automatique des bases sur le PC
```bash
udme-agent find-databases              # parcourt tous les disques fixes, liste, VOUS choisissez, puis suite guidée
udme-agent find-databases --gui        # même chose avec une fenêtre de sélection (Tk)
udme-agent find-databases --root D:\\ --json      # liste seule, non interactif
# options : --include-noise (navigateurs/système) --include-removable --max-minutes 15
```
Détecte : SQLite, Access (.mdb/.accdb), SQL Server (.mdf/.ndf/.bak), Firebird/InterBase, dBase/FoxPro, MySQL/InnoDB, DuckDB,
dumps `.sql` / PostgreSQL. Tri : chemin évoquant WinGest/pharmacie, puis en-tête vérifié, puis taille.
Garde-fous : lecture des ~32 premiers octets seulement (4 Ko pour `.sql`, résultat oui/non, contenu jamais conservé) · aucun envoi ·
aucune écriture · liens symboliques ignorés · dossiers système et navigateurs masqués · fichiers verrouillés signalés, jamais copiés ·
rien ne s'exécute avant votre confirmation. SQLite : extraction proposée directement en lecture seule. Autres moteurs : empreinte +
avertissement « travaillez sur une copie » + modèle de connexion ; jamais de scan automatique.
Le navigateur ne peut pas parcourir le disque : cette fonction vit dans l'agent local, pas dans l'interface web.

## Connecteur WinGest (profil de découverte guidée)
Le moteur réel de WinGest n'est documenté nulle part publiquement : **rien n'est supposé** (Gate 1 du plan).
```bash
udme-agent wingest-discover --dir "C:\\WinGest"     # indices locaux + checklist Annexe A pré-remplie (TO_VERIFY)
set UDME_DB_URL=<URL SQLAlchemy d'un compte LECTURE SEULE>   # modèles : udme_core/profiles/wingest.py
udme-agent wingest-scan --dir "C:\\WinGest" [--engine firebird|sqlserver|access|...] --confirm-read-only --out out
```
`wingest-scan` refuse de s'exécuter si le moteur n'est ni établi sans ambiguïté par les preuves, ni confirmé explicitement par l'opérateur.
Seuls le dossier choisi (profondeur ≤ 2) et de petits fichiers de config sont lus, localement ; leur contenu n'est jamais rapporté.
Une fois le moteur confirmé sur une installation autorisée, on ajoutera le jeu de requêtes de catalogue spécifique (si besoin) et les règles de vocabulaire vérifiées.

## Garanties implémentées
Lecture seule fail-closed · requêtes de catalogue fixes (pas de SQL arbitraire) · métadonnées uniquement ·
paquet signé HMAC + checksum + anti-rejeu (horodatage, nonce unique) + idempotence · jeton d'enrôlement à usage unique ·
révocation d'agent · isolation par tenant (404 inter-tenant) · RBAC admin/reviewer/viewer · journal d'audit ·
un label < 0,60 reste `UNKNOWN` · aucune règle ne dépasse 0,94 · rejets humains respectés à l'export.

## Non implémenté / à faire (honnêtement)
- Frontend : compile (Angular strict) mais **non testé dans un navigateur** ; pas encore d'assistant d'enrôlement d'agent ni de tableau de bord d'agents (API prête : tokens, révocation).
- **Requêtes de catalogue spécifiques à WinGest** : impossibles avant la confirmation du moteur sur une installation autorisée (Annexe A).
- Signature agent : HMAC à secret partagé stocké en base → remplacer par Ed25519 (clé publique) + KMS avant pilote.
- Stockage objet S3 (paquet en JSONField pour l'instant), RLS PostgreSQL, MFA/OIDC, rétention, installeur signé (WiX/PyInstaller), SBOM.
- Mapper LLM : interface `SemanticProvider` prévue, aucun fournisseur branché ; règles seules pour l'instant.
- Reports de décisions humaines d'un scan à l'autre (plan 8.4) ; profilage de valeurs (opt-in) ; pilotes Firebird/Access non testés.
