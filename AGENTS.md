# Kinayad — Contexte projet

Gestion de rendez-vous & rappels WhatsApp pour professionnels de santé au Maroc
(backend FastAPI/SQLAlchemy déployé sur Render, frontend statique sur Vercel).

> **À lire en premier à chaque session, avant toute action.** Ce fichier est lu
> par Hermès et Claude Code. Les règles ci-dessous s'appliquent à ce projet.

## Équipe (4 personnes)

Bouchaib (décideur, propriétaire), Hermès (code + tests locaux), Claude Code
(revue indépendante, déploiement, tests Docker/prod), Claude (assistant pilote).

- **Doute technique, sécurité ou architecture → demander une 2ᵉ vérification
  à Claude Code AVANT de coder** (via Bouchaib).
- Les deux agents travaillent sur les mêmes dépôts : toujours rebase avant push.

## Protocole de travail (obligatoire)

- **« 🛠 Je commence : … »** → annonce avant de lancer un chantier.
- **Silence** → l'agent travaille (ne pas interrompre).
- **« ✅ Terminé : … »** → résultat + preuves (sorties brutes, tests).
- **« ❓ J'ai besoin de toi : … »** → uniquement en cas de blocage nécessitant
  une décision (préciser quoi exactement).

## Gouvernance GitHub (règles non négociables)

1. **Rebase sur `origin/main` avant tout push** — vérifier `git log origin/main..branche`
   (ne doit contenir QUE ses propres commits). Un push basé sur un ancien main
   a déjà failli annuler le fix Dockerfile (polices DejaVu).
2. **Jamais de push direct sur `main`** — toujours `feat/… → PR → revue → merge`
   (approbation Claude Code ou Bouchaib requise).
3. **Préciser l'environnement de test** dans les messages et PRs :
   « local SQLite + DEMO_MODE » / « image Docker identique à Render » / « prod ».
4. **Jamais de secret en clair** dans un message, un log ou un commit — uniquement
   dans `.env` / fichiers `credentials/` (chmod 600).
5. **Token GitHub scopé à `kinayad-backend` uniquement** — jamais utilisé pour
   `kinayad-deploy` ni aucun autre dépôt.
6. **Signaler en tête de PR** tout changement Dockerfile / dépendances système /
   variables d'environnement / infra (impact silencieux).
7. **`tests/run_all.sh` avant chaque push** — donner le résultat brut dans la PR.

## Stack & conventions

- FastAPI + SQLAlchemy 2.0 (style déclaratif), Pydantic Settings, PostgreSQL
  (Render) / SQLite (dev).
- **Tous les datetimes sont stockés en UTC** (naive sur SQLite = UTC).
  Heures d'affichage patient : fuseau du tenant (`Africa/Casablanca`).
- Colonnes JSON mutables : `MutableDict.as_mutable(JSON)` — jamais de mutation
  in-place sans ça.
- Les modèles canoniques vivent dans `app/models.py` (`app/db/models.py` = re-export).
- WhatsApp : envoi via **Evolution API** (proxy Caddy), pas l'API Meta payante.
  `DEMO_MODE=true` = aucun envoi réel (journalisé).

## Tests

- `tests/run_all.sh` : batterie complète (parcours patient, annulation/opt-out,
  dashboard, agenda, auth+isolation). Doit être **5/5 vert**.
- Le serveur de test doit être relancé à chaque batterie (le rate-limiter du
  login est en mémoire et reste plein 60 s après un test).

## Leçons apprises (pièges réels)

- **Ne jamais renommer le profil WhatsApp d'un numéro récent** → LOGOUT WhatsApp
  (vécu sur Kinayad). Le nom du cabinet se fixe à la création du numéro.
- **Vérifier les chemins autorisés par le proxy Caddy avant tout nouvel endpoint
  d'envoi** : `sendMedia` était bloqué (404) = cartes perdues en silence.
- **Collisions d'entrées dans les machines d'états** : « 0 » = passer la question
  du nom vs « 0 » = opt-out (STOP_WORDS) — vérifier l'ordre des traitements.
- **Rate-limit par IP derrière un proxy** : IP constante → un compte attaqué
  bloque tous les cabinets. Toujours clé par email/compte.
- **Signaler TOUS les commits d'une branche** dans les messages (un commit non
  décrit a failli introduire un appel à un endpoint non mergé).

## Skills à charger

- `whatsapp-evolution-bots` — avant tout chantier touchant le canal WhatsApp
  (webhooks, envoi, proxy).
- `python-saas-backends` — avant tout chantier backend structurant (auth,
  multi-tenant, isolation).
- `requesting-code-review` — avant chaque push, en complément de la revue
  Claude Code.

## État courant (à mettre à jour à chaque session)

- Auth multi-cabinet : **FAIT** — PR #5 (backend) + PR #1 (frontend deploy)
  mergées et déployées ensemble le 30/08. Ancien mot de passe global désactivé
  (401 confirmé). Isolation vérifiée en vraie prod (deux tenants distincts).
- Compte admin du cabinet existant (Dr. Hachmi Bouchaib) : **FAIT** — créé et
  testé (connexion confirmée).
- Adresse du cabinet : branche backend `feat/adresse-cabinet` (endpoint `PUT
  /{slug}/address`) — revue séparée à faire, pas encore de PR ouverte.
- Tenant de test resté en base (`cabinet-verif-prod`, créé pendant la
  vérification post-déploiement) : inoffensif, pas de route de suppression de
  tenant pour l'instant.
