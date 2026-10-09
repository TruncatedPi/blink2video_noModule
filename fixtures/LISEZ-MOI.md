# Pièces de test

`clip_usb_reel_neutre.mp4` : un vrai clip de détection enregistré sur la clé USB d'un Sync Module Blink (caméra de bureau, 2026-10-05), 1280x720, 21,5 s, 1,6 Mo, publié tel quel, octet pour octet. Il montre un objet sombre devant une étagère blanche : personne, rien d'identifiable. Sa piste audio ne contient que le bruit de fond du micro (niveau moyen environ -51 dB, crête -34 dB), vérifié avant publication.

Il sert à une chose précise : chaque clip enregistré sur la clé USB d'un Sync Module contient une unité d'accès H.264 sans image, que `ffprobe` signale par `missing picture in access unit with size 9` alors que la vidéo est complète (issue #49). Les clips fabriqués par FFmpeg ou venus du cloud n'ont pas cette particularité, et c'est pourquoi la CI n'a jamais vu ce défaut. Voir `test_validation_clip_usb_reel.py`.

Ne remplacez pas ce fichier par un clip retouché : le test en vérifie l'empreinte SHA-256.
