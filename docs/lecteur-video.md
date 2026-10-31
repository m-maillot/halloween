# Lecteur de vidéos (Shield + Kodi)

Le composant **lecteur vidéo** joue une vidéo sur un écran ou un rétroprojecteur depuis un scénario, puis revient à un **écran noir**. Le moteur ne parle pas à la Shield : il appelle un script Home Assistant, qui pilote Kodi.

## Principe

- **Kodi** tourne sur la Shield (lancé à l'avance : le moteur ne le démarre pas).
- Un **script Home Assistant** (`script.lire_video_shield` dans notre cas) reçoit deux champs et lance la lecture :
  - `video` : la source du média (`media-source://media_source/local/halloween_video.mp4`) ;
  - `boucle` : `true` ou `false`.
- Le **lecteur** du moteur désigne ce script et liste les vidéos. Il en a une de **repos** : un fichier noir, joué en boucle au démarrage, à l'arrêt, et à la fin de chaque scénario qui a commandé le lecteur.
- Jouer une vidéo **remplace** celle en cours, sans attendre sa fin. « Écran noir » rejoue la vidéo de repos quand on veut.

Les vidéos vont dans le dossier média local de Home Assistant (`/media`). Un simple nom de fichier suffit dans le formulaire ; le moteur le transforme en `media-source://media_source/local/<fichier>`.

## Le script Home Assistant

Le moteur envoie ceci, exactement comme la commande de test :

```bash
curl -X POST \
  -H "Authorization: Bearer TON_JETON" \
  -H "Content-Type: application/json" \
  -d '{"video": "media-source://media_source/local/halloween_video.mp4", "boucle": true}' \
  http://IP_DE_HA:8123/api/services/script/lire_video_shield
```

Si cette commande lance bien la vidéo, le moteur fonctionnera. Le script doit déclarer les champs `video` et `boucle` ; le reste (entité Kodi, répétition) dépend de votre installation.

## Configuration dans l'interface

1. **Composants → Vidéos → Ajouter un lecteur vidéo.**
2. Choisir le **script** (la liste vient de Home Assistant ; sinon saisir `script.lire_video_shield`).
3. Ajouter les vidéos : nom, fichier, et **durée** (facultative, nécessaire pour « attendre la fin »).
   - `black_screen.mp4` (10 s, jouée en boucle)
   - `halloween_video.mp4` (21 s)
   - `ghost.mkv` (1 min 18 s)
4. Choisir `black_screen.mp4` comme **vidéo de repos**.
5. Enregistrer, puis **Tester** : « Jouer » une vidéo, « Écran noir ».

## Dans un scénario

Catégorie **Vidéos** de la palette : « jouer une vidéo » (avec « en boucle » et « attendre la fin ») et « revenir à l'écran noir ».

Exemple : un fantôme de 78 s, puis retour au noir.

1. `jouer` *ghost.mkv*, **attendre la fin** coché (le scénario patiente 78 s) ;
2. rien d'autre à faire : à la fin du scénario, le moteur remet l'écran noir (`on_end: reset`). Pour revenir au noir plus tôt, ajoutez « revenir à l'écran noir ».

## À savoir

- **Délai** : Home Assistant et Kodi mettent de une à plusieurs secondes à démarrer une vidéo. « Attendre la fin » compte la durée saisie **après** la réponse de Home Assistant, pas depuis l'image à l'écran : prévoir une marge.
- **Kodi arrêté** : si Home Assistant renvoie une erreur, le moteur la journalise et continue (comme pour une lumière injoignable) ; un script qui échoue en silence côté Home Assistant ne se voit que sur l'écran. Au démarrage du moteur, la remise à l'écran noir est retentée tant que Home Assistant ne répond pas.
- **Une vidéo sans boucle** s'arrête sur sa dernière image ou sur l'interface de Kodi : terminez par « revenir à l'écran noir » (ou laissez la fin du scénario le faire).
- Ce composant n'a **pas été essayé sur le matériel réel** (Shield, Kodi, rétroprojecteur) : la recette est dans la liste ci-dessous.

## Recette sur le matériel

- [ ] `halloween-cli ha-check` : `retro : script script.lire_video_shield existe`.
- [ ] Au démarrage du service, l'écran noir apparaît.
- [ ] Composants → lecteur → Tester : « Jouer » *Fête* joue la vidéo ; « Écran noir » revient au noir.
- [ ] Un scénario « jouer + attendre la fin » enchaîne bien, et la fin du scénario remet le noir.
- [ ] STOP (arrêt global) remet le noir.
- [ ] Kodi fermé : le scénario continue ; noter ce que Home Assistant répond (erreur visible dans le journal du moteur ou non).
