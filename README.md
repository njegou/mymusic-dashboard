# mymusic — tableau de bord de supervision

Vue d'ensemble en lecture seule du serveur mymusic : services, ressources du NAS,
bibliothèque, comptes, playlists, lectures en cours et journaux.

Volontairement séparé du projet mymusic : rien n'est ajouté à `njegou/mymusic`,
aucune modification de `upload_server.py`, aucun code partagé. Le dashboard
interroge Navidrome et le système, il n'écrit jamais.

```
backend/
  dashboard_api.py               API d'agrégation, port 5053, stdlib seule
  dashboard_config.example.json  modèle de configuration
frontend/
  index.html
  style.css
  dashboard.js
```

## Architecture

```
navigateur ──► Cloudflare Tunnel ──► NAS :5053 ──┬─► Navidrome :4533 (API Subsonic)
   (GitHub Pages)                                 ├─► /proc, df, ps
                                                  └─► journaux + dossier musique
```

Le backend n'a **aucune dépendance pip**. Il tourne sur `/usr/bin/python3.8` du
DS218 avec `http.server`, comme `upload_server.py`. C'est délibéré : FastAPI tire
pydantic, qui a besoin de roues compilées Rust, difficilement installable sur un
ARM64 en Python 3.8 avec 512 Mo de RAM et sans compilateur.

Ports : Navidrome 4533, `upload_server.py` 5051, dashboard **5053**.

## Installation du backend

1. Copier les deux fichiers sur le NAS (SCP n'existe pas sur le DS218) :

```bash
cat backend/dashboard_api.py | ssh Nicolas@192.168.1.7 "cat > /volume1/homes/Nicolas/dashboard_api.py"
cat backend/dashboard_config.example.json | ssh Nicolas@192.168.1.7 "cat > /volume1/homes/Nicolas/dashboard_config.json"
ssh Nicolas@192.168.1.7 "wc -c /volume1/homes/Nicolas/dashboard_api.py /volume1/homes/Nicolas/dashboard_config.json"
```

Vérifier la taille tout de suite : un chemin local erroné crée silencieusement un
fichier de 0 octet.

2. Générer un jeton et le mettre dans la config, avec le mot de passe Navidrome :

```bash
openssl rand -hex 32
ssh Nicolas@192.168.1.7 "vi /volume1/homes/Nicolas/dashboard_config.json"
chmod 600 /volume1/homes/Nicolas/dashboard_config.json
```

3. Lancer, puis vérifier que le processus a bien démarré :

```bash
ssh Nicolas@192.168.1.7 "cd /volume1/homes/Nicolas && nohup /usr/bin/python3.8 dashboard_api.py >> dashboard.log 2>&1 &"
ssh Nicolas@192.168.1.7 "curl -s localhost:5053/api/health"
ssh Nicolas@192.168.1.7 "curl -s 'localhost:5053/api/dashboard?token=LE_JETON' | head -c 400"
ssh Nicolas@192.168.1.7 "ps | grep [d]ashboard_api"
```

Pour redémarrer : `pkill -f "[d]ashboard_api.py"` puis relancer, en deux commandes
distinctes pour éviter que la commande se tue elle-même.

## Tunnel Cloudflare

Ajouter une entrée d'ingress **avant** la règle catch-all :

```yaml
ingress:
  - hostname: dashboard.mymusic-nj.com
    service: http://localhost:5053
  - hostname: api.mymusic-nj.com
    service: http://localhost:5051
  - hostname: navidrome.mymusic-nj.com
    service: http://localhost:4533
  - service: http_status:404
```

Créer l'enregistrement DNS du sous-domaine, redémarrer cloudflared, puis tester
`curl -s https://dashboard.mymusic-nj.com/api/health`.

## Frontend

Dépôt séparé, par exemple `njegou/mymusic-dashboard`, publié via GitHub Pages sur
la branche `main`, dossier racine. Avant de pousser, ajuster en tête de
`dashboard.js` :

```js
var API_BASE = 'https://dashboard.mymusic-nj.com';
var API_FALLBACK = 'http://192.168.1.7:5053';
```

Le jeton est demandé au premier chargement et conservé dans `localStorage`. Le
bouton « Oublier le jeton » le supprime. Incrémenter `?v=` sur les balises `<link>`
et `<script>` à chaque déploiement, comme sur mymusic.

## Ce que montre le tableau de bord

- **Services** : Navidrome, serveur d'import, API de supervision, état de l'analyse.
  PID, mémoire résidente, durée depuis le démarrage, réponse HTTP réelle.
- **Ressources** : remplissage de `/volume1`, RAM, charge processeur, taille du
  dossier musique et sa part du volume occupé.
- **En écoute** : qui écoute quoi, sur quel lecteur, il y a combien de temps.
- **Bibliothèque** : morceaux, albums, artistes, dossiers, fichiers `.lrc`, et la
  répartition du stockage par format.
- **Comptes** : utilisateurs Navidrome et leurs droits.
- **Playlists** : triées par taille, avec durée et date de modification.
- **Journaux** : 40 dernières lignes de Navidrome et du serveur d'import, lignes
  d'erreur mises en évidence.

Rafraîchissement toutes les 15 s. Côté serveur, chaque source a son propre cache
(15 s pour les processus, 60 s pour le disque, 120 s pour la bibliothèque, 5 min
pour les comptes) afin de ne pas solliciter le NAS en continu.

Le parcours du dossier musique est lent sur un DS218 avec ~3 500 morceaux : il
tourne sur un thread de fond, une fois toutes les 6 heures, et n'est jamais
exécuté pendant une requête. Au tout premier démarrage, la carte « Dossier
musique » affiche « analyse en cours » pendant une à deux minutes.

## Points de vigilance

**Le jeton est la seule protection.** Le tunnel est public : qui a l'URL et le
jeton voit tes journaux et tes comptes. Ne le commite pas, et préfère une
Cloudflare Access Application devant le sous-domaine si tu veux une vraie
authentification.

**Section « En écoute » possiblement vide.** Elle repose sur `getNowPlaying`, que
Navidrome n'alimente que si un client envoie une notification de lecture en cours
(`scrobble` avec `submission=false`). Si `POST /api/scrobble` de `upload_server.py`
relaie uniquement les scrobbles terminés, la section restera vide même pendant une
écoute. À vérifier avant de conclure à un bug.

**Comptes en erreur ?** `getUsers` exige un compte administrateur. Vérifie le
compte indiqué dans `navidrome_user`.

**Pas de redémarrage automatique.** Comme Navidrome, le processus n'est pas
supervisé : un `kill` ou un reboot du NAS l'arrête définitivement. Ajouter une
tâche planifiée DSM « au démarrage » si tu veux qu'il revienne seul.

**Mémoire.** Le processus occupe quelques dizaines de Mo, à surveiller sur les
512 Mo du DS218 avec Navidrome et le serveur d'import déjà en place.
