# Déployer UDME sur Render

Architecture : **1 service web** (Docker : API Django + frontend Angular, même domaine, pas de CORS) + **1 base PostgreSQL**.
Les paquets ne contiennent que des métadonnées de schéma (jamais de données de pharmacie).

## 1. Mettre le code sur GitHub
```bash
cd udme && git init && git add . && git commit -m "UDME" && git branch -M main
git remote add origin https://github.com/<vous>/udme.git && git push -u origin main
```
(`.gitignore` exclut node_modules, dist, bases locales. Ne commitez jamais de mot de passe.)

## 2. Créer le Blueprint
1. Render → **New → Blueprint** → choisissez le dépôt (Render lit `render.yaml`).
2. Renseignez `UDME_ADMIN_PASSWORD` (mot de passe long : c'est votre compte administrateur). `DJANGO_SECRET_KEY` est généré automatiquement.
3. **Apply**. Le premier build compile Angular puis l'image Django (quelques minutes).
4. Au démarrage : migrations + création idempotente de l'admin, du tenant et du site (variables `UDME_*`).

Vérifiez : `https://<votre-service>.onrender.com/api/v1/health` → `{"status":"ok"}`, puis ouvrez l'URL et connectez-vous (`admin`).

## 3. Enrôler l'agent (PC de la pharmacie)
1. Dans le site web : **Agents → Générer un jeton d'enrôlement** (valable 30 min, usage unique).
2. Sur le PC : 
```bash
pip install udme-core udme-agent      # ou l'installeur quand il sera packagé
udme-agent enroll --server https://<votre-service>.onrender.com --token <jeton>
udme-agent find-databases             # cherche les bases, VOUS choisissez
udme-agent scan --upload              # extraction lecture seule + envoi signé
```
3. Le scan apparaît dans **Scans** (revue des relations/mappings, export).
Sur Windows, le raccourci **Démarrer UDME Agent** lance le parcours guidé : il demande le jeton si le PC n'est pas encore enrôlé, puis envoie le schéma SQLite après confirmation. Les erreurs d'enrôlement ou d'envoi sont affichées dans une boîte de dialogue. Dans **Scans**, les envois en cours sont actualisés automatiquement ; ouvrez **Ouvrir** pour voir le mapping proposé sur l'aperçu et dans l'onglet Revue. Un scan marqué « Échec de l’analyse » nécessite de consulter les logs du service Render.

Les fichiers `.sql`/`.dump` sont des sauvegardes et ne sont ni exécutés ni importés ; pour les autres moteurs, connectez une base active avec un compte en lecture seule et son pilote.
À l'enrôlement l'agent génère une paire de clés **Ed25519** : la clé privée reste dans `~/.udme/agent.json` (droits 600 ; sous Windows, protégée par le profil utilisateur), le serveur ne reçoit que la clé publique. Révoquer un agent (`POST /agents/{id}/revoke`) bloque ses envois. Les agents enrôlés avant cette version doivent être ré-enrôlés.

### Installer l'agent Windows
L'installateur autonome se construit sur Windows avec Python 3.12 :
```powershell
.\packaging\windows\build.ps1
```
Le résultat est `dist\UDME-Agent-Setup.exe`. Il installe l'agent pour l'utilisateur courant (sans droits administrateur) et crée un raccourci de recherche. L'installateur n'embarque aucun jeton ni secret. Les exécutables produits localement ne sont pas signés ; Windows peut afficher un avertissement SmartScreen.

## Limites du plan gratuit (à lire avant d'inviter un client)
- La base **free expire après 30 jours** (export ou passage à un plan payant avant l'échéance) ; le service **free s'endort après ~15 min** (premier appel lent, ~1 min).
- Pas de shell sur le plan gratuit : tout est piloté par l'interface web et les variables d'environnement.
- Pour un pilote réel : plan payant pour le service **et** la base, et sauvegardes.
- Sans `REDIS_URL`, l'analyse s'exécute dans la requête d'envoi (limite 120 s). Pour de gros schémas : ajoutez une instance Key Value + un worker (`celery -A config worker -l info`) et définissez `REDIS_URL`.

## Avant de traiter des données de clients réels
Voir « Non implémenté » du README : stockage objet pour les paquets, MFA, politique de rétention, rotation des clés d'agent, et valider hébergement/RGPD avec un conseil juridique, notamment pour des clients en Tunisie. La base et le service sont en Oregon (États-Unis), hors UE.
