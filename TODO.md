# TODO

État au 2026-08-26. Détail dans [docs/SPECIFICATION.md](docs/SPECIFICATION.md).

## Fait

v1.0 déployée. Timer actif sur le VPS depuis le 2026-08-26.

| | |
|---|---|
| M1 | Package `src/` |
| M2 | Config, CLI, codes de sortie, logs |
| M3 | Résilience, état, idempotence |
| M4 | Calibration du matching — 100 pistes, 0 faux positif |
| M6 | README + doc de déploiement |

## En cours

**M5 — 7 jours sans intervention.** Démarré le 26/08, à valider le **02/09**.

```sh
journalctl --user -u lb2tidal --since '2026-08-26' | grep -E 'ERROR|failed'
```

## À faire

### 1. Notification d'échec  ← prochain chantier

Un run qui échoue le fait en silence. C'est le plus gros manque maintenant que
le timer tourne.

- `OnFailure=lb2tidal-notify@%n.service` sur l'unité
- unité template qui lit le code de sortie + les dernières lignes de journald
- webhook (ntfy / Discord) plutôt que mail : pas de MTA sur le VPS
- distinguer exit 1 (partiel) de exit 4 (total) — cf. §6.4
- ~20 lignes d'unité + un petit script

### 2. Observer ce qui n'a jamais tourné

Code écrit, aucune preuve en production (§10.1) :

| Chemin | Déclencheur attendu |
|---|---|
| `updated` — seul chemin d'écriture non testé | **lundi 31/08**, régénération hebdo |
| `missed` | quand une piste manquera à Tidal |
| `failed` + coupe-circuit | panne Tidal |
| Retry / backoff | premier `429` ou `5xx` |

### 3. Plus tard (§8.3)

- Résolution par ISRC (MBID → MusicBrainz → Tidal) — exact au lieu de flou
- Calibrer `artist_weight`, toujours à la valeur héritée
- Durée comme garde-fou anti-faux-positif
- `--report-misses PATH`
