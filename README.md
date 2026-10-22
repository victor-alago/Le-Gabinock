# Le GabinOck — réservation de salles avec authentification

## Lancer en local
```bash
python -m pip install -r requirements.txt
uvicorn main:app --reload
```
Puis ouvrir http://127.0.0.1:8000

## Comptes de démonstration
- f.eric@legabinock.net / ericfabre77
- r.rose@legabinock.net / rosinerone6

Les mots de passe sont enregistrés sous forme de hachage PBKDF2 dans SQLite, pas en clair.
Changez ces mots de passe avant un déploiement réel.

## Fonctions
- Authentification e-mail / mot de passe et déconnexion.
- Chaque utilisateur ne voit et n'annule que ses propres réservations.
- Les endpoints de réservation et de salles nécessitent un jeton de session.
- Une transaction SQLite `BEGIN IMMEDIATE` vérifie les chevauchements avant insertion pour empêcher les doubles réservations concurrentes.

Le fichier `salles.db` est créé automatiquement au premier démarrage. Si une ancienne base existe, les tables et réservations existantes sont conservées ; les comptes de démonstration sont ajoutés s'ils n'existent pas.
