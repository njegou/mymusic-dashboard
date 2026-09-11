# Panneau de bureau

Reprend une partie du tableau de bord sur le bureau : état des services, disque,
mémoire, charge, compteurs de bibliothèque et lectures en cours.

`panel.py` fait tout le travail et sert les deux environnements :

- `panel.py --json` alimente **eww**, pour Wayland
- `panel.py --text` alimente **Conky**, pour X11

```
panel.py             récupération et mise en forme
panel.env.example    modèle de configuration (URL + jeton)
eww.yuck             widgets eww
eww.scss             styles eww
eww-mymusic.desktop  démarrage automatique
mymusic.conf         configuration Conky, pour une session X11
```

## Installation (Wayland, KDE Plasma)

```bash
sudo pacman -S eww ttf-jetbrains-mono
mkdir -p ~/.config/eww/mymusic
cp eww.yuck ~/.config/eww/mymusic/eww.yuck
cp eww.scss ~/.config/eww/mymusic/eww.scss
cp panel.py ~/.config/eww/mymusic/panel.py
cp panel.env.example ~/.config/eww/mymusic/panel.env
chmod +x ~/.config/eww/mymusic/panel.py
chmod 600 ~/.config/eww/mymusic/panel.env
```

Renseigner l'URL et le jeton dans `~/.config/eww/mymusic/panel.env`, puis
**tester le script seul** avant de lancer eww :

```bash
python3 ~/.config/eww/mymusic/panel.py --json | python3 -m json.tool
```

Le champ `ok` doit valoir `true`. S'il affiche `jeton refusé` ou
`serveur injoignable`, corriger le `.env` : eww n'apportera rien au diagnostic
tant que cette étape échoue.

```bash
eww --config ~/.config/eww/mymusic open mymusic-panel
```

Pour fermer : `eww --config ~/.config/eww/mymusic close mymusic-panel`.
Après modification d'`eww.yuck` ou `eww.scss` : `eww reload`.

## Si rien n'apparaît

C'est le point à vérifier en premier sous Plasma. `plasmashell` occupe la couche
de fond en plein écran, et un widget posé sur cette même couche peut passer
derrière. Dans `eww.yuck`, remplacer :

```
:stacking "bg"
```

par :

```
:stacking "bt"
```

Le panneau se place alors au-dessus du fond d'écran mais sous les fenêtres
normales, ce qui donne le même effet à l'usage. Recharger avec `eww reload`.

Si le panneau n'apparaît toujours pas, vérifier que le démon tourne
(`eww ping`) et regarder `eww logs`.

## Démarrage automatique

```bash
cp eww-mymusic.desktop ~/.config/autostart/
```

Adapter la ligne `Exec` si la config n'est pas à l'emplacement par défaut :
`eww --config ~/.config/eww/mymusic open mymusic-panel`. Le délai de 8 secondes
laisse Plasma se dessiner avant eww.

## Réglages courants

- **Position et taille** : bloc `:geometry` de `defwindow` dans `eww.yuck`.
- **Fréquence** : `:interval "30s"` du `defpoll`. C'est lui qui commande le
  nombre de requêtes HTTP vers le NAS.
- **Couleurs et tailles de texte** : variables en tête d'`eww.scss`.
- **Seuils de couleur des jauges** : fonction `level()` dans `panel.py`,
  actuellement 75 % pour l'orange et 90 % pour le rouge.
- **Nombre de morceaux affichés** : `playing[:3]` dans `build_view()`.

## Session X11

La configuration Conky reste fournie si tu repasses en X11 un jour :

```bash
sudo pacman -S conky
mkdir -p ~/.config/conky
cp mymusic.conf panel.py ~/.config/conky/
cp panel.env.example ~/.config/conky/panel.env
chmod 600 ~/.config/conky/panel.env
conky -c ~/.config/conky/mymusic.conf
```

Conky ne fonctionne pas sous Wayland : il dessine sur la fenêtre racine X11, qui
n'existe pas là-bas.

## Sécurité

`panel.env` contient le jeton de supervision en clair. Il est ignoré par git et
doit rester en `600`. Si tu changes le jeton sur le NAS, mets ce fichier à jour,
sinon le panneau affichera « jeton refusé ».
