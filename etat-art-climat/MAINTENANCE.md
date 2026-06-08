# Maintenance & veille de l'état de l'art

Ce fichier est la **source de vérité** pour tenir l'état de l'art à jour. Toute révision
(humaine ou par agent planifié) **commence par le lire**, puis met à jour le **journal**
en bas. Il est versionné : il fait foi sur *quoi re-vérifier, à quel rythme, et où on en est*.

## Cadence

- **Révision tous les 6 mois** : une passe en **avril**, une en **octobre** (octobre = après
  l'été, quand arrêtés sécheresse, bulletins de campagne et éditions d'automne sont frais).
- **Dernière révision : 2026-06.** **Prochaine révision prévue : 2026-10.**
- En plus du calendrier, certains documents sont attendus **« par jalon »** (date imprévisible) :
  ils sont listés dans la section *Jalons à surveiller* — à vérifier à chaque passe, et à
  intégrer dès qu'ils paraissent, sans attendre l'échéance.

## Procédure de révision (à chaque passe)

1. **Parcourir le tableau de veille** ci-dessous : pour chaque source, vérifier à l'URL s'il
   existe une **édition plus récente** que la « dernière vérif » / que ce qui est cité.
2. **Vérifier les jalons** (section dédiée) : une HMUC publiée ? le SDAGE 2028-2033 en
   consultation/adopté ? l'étude France Stratégie « demande vs ressource » parue ?
3. Pour chaque nouveauté : **lire la source**, l'**archiver** (`sources/`, cf. [règle PDF] —
   transcription Markdown si volumineux), **mettre à jour** le chapitre concerné + un repère
   historique entre parenthèses si chiffré, **l'entrée `references.bib`** et le **manifeste
   `sources/README.md`**.
3bis. Respecter les principes du dossier : **valeurs exactes** (pas d'approximation),
   **provenance signalée** si donnée transposée (hors maraîchage breton), **une seule méthode
   par phénomène**, pas de référence « ADR-XXXX » dans le texte affiché.
4. **Mettre à jour** la date « dernière révision » (ici **et** la préface `index.qmd`) et la
   « prochaine révision ».
5. **Rendre** le livre (`quarto render`) — 0 warning attendu — puis **commit thématique** et
   push (le workflow Pages republie HTML + PDF).
6. **Compléter le journal** en bas de ce fichier (date, ce qui a changé, ce qui a été écarté).

> Si une vérification est faite mais ne mène à **aucun** changement, le noter quand même au
> journal (« vérifié, rien de neuf ») : l'absence de mise à jour doit être *traçable*, pas
> ambiguë.

## Tableau de veille (sources existantes)

| Source | Rythme propre | Où vérifier | Dernière vérif | Chapitres impactés |
|---|---|---|---|---|
| OEB — chiffres-clés climat Bretagne (`oeb-temperatures`, `oeb-precipitations`, `oeb-vague-chaleur`) | **annuel** (éd. AAAA) | bretagne-environnement.fr (rubrique climat) | 2026-06 | 01-climat, 03-chaleur |
| OEB — « Mon territoire sous +4 °C » (indicateurs Explore2 commune/SAGE) | mises à jour | bretagne-environnement.fr / ambition-climat-bretagne.bzh | 2026-06 (repéré, non encore exploité) | 02-eau, annexe C |
| ORACLE Bretagne (`oracle2021`) | bulletins ~annuels | chambres-agriculture Bretagne / OEB | 2026-06 | 01-climat |
| Arrêtés sécheresse 35 (`pref35-secheresse`, `arrete-secheresse35-2023`) | **annuel / chaque été** | ille-et-vilaine.gouv.fr ; VigiEau/Propluvia | 2026-06 | 02-eau, 12-adapt-eau |
| Agence Bio — chiffres (`agencebio2025`, `agencebio-vd2023`) | **annuel** | agencebio.org | 2026-06 | 08-filiere |
| Explore2 / fiches TRACC (`explore2`, `explore2-bretagne`) | pluriannuel (stable) | recherche.data.gouv.fr ; ofb.fr Explore2 | 2026-06 | 02-eau, annexe C, annexe forage |
| DRIAS-Eau (données débits/recharge/humidité sols au point) | données stables | drias-eau.fr | 2026-06 (non exploité — piste data locale) | 02-eau, 10-annexe-forage |
| SDAGE Loire-Bretagne (`sdage-lb`, `sdage-lb-adaptation2050`) | cycle 6 ans + jalons | sdage-sage.eau-loire-bretagne.fr | 2026-06 | 02-eau, annexe C |
| Réglementation travail chaleur (`legifrance-decret-chaleur2025`, `inrs-*`) | événementiel | legifrance.gouv.fr ; inrs.fr | 2026-06 | 03-chaleur, 13-adapt-chaleur-gel |
| TRACC / PNACC-3 (`tracc2025`, `pnacc3-2025`) | stable (cadre) | ecologie.gouv.fr | 2026-06 | index, 00-synthese |

## Jalons à surveiller (publications attendues, date imprévisible)

| Document attendu | Pourquoi c'est important | Où / qui | Statut au 2026-06 |
|---|---|---|---|
| **HMUC du bassin du Couesnon** (chiffrée : DCR, volumes prélevables, projections 2030/2050) | 1re règle locale de partage de l'eau opposable (sous-bassin Chenelais) | Syndicat BV Couesnon — bassin-couesnon.fr | étude lancée fin 2023, **non publiée** |
| **Pré-HMUC du SAGE des bassins côtiers de Dol** | Territoire **du forage** (Guyoult) — référence locale la plus directe | SBCDol — sage-dol.fr | engagée, **non publiée** |
| **SDAGE Loire-Bretagne 2028-2033** | Stratégie climat = enjeu n°1, sur Explore2 ; cadre de prélèvement à venir | eau-loire-bretagne.fr | en préparation (consultation ~2026-27) |
| ~~France Stratégie — étude « demande vs ressource »~~ | Confronte demande (rapport 2025) et ressource par territoire → zones de tension | strategie-plan.gouv.fr | **PARU** (NA 156 + DT 2025-03, 25 juin 2025) — **intégré le 2026-06-08** (`francestrategie-eau-tension2025`) |

## Ce qui est attendu d'Alexis à chaque veille

La routine **propose** (une issue), elle n'**applique** rien. Voici précisément ton rôle :

**S'il y a des nouveautés :**
1. **Lire** la section « Nouveautés détectées » de l'issue.
2. Pour chaque item, **trancher** en cochant : *à intégrer* / *à différer* / *à écarter* (un mot de justification suffit).
3. Ouvrir une **session Claude Code dans le dépôt `meteo`** et écrire : **« traite l'issue de veille #N »** (préciser les items retenus si tu n'en gardes qu'une partie). Claude fait **toute** l'intégration — archivage de la source, rédaction du chapitre, `references.bib`, manifeste, render, PR. **Tu n'édites rien à la main.**
4. **Relire la PR** que Claude ouvrira (valeurs exactes, provenance, lisibilité) puis la **merger** → la CI republie le site (HTML + PDF). L'issue se ferme à la fusion.

**S'il n'y a rien de neuf :** rien à intégrer — **fermer simplement l'issue** (elle prouve que la vérification a eu lieu).

> En résumé, tu n'interviens qu'à **deux moments** : décider *quoi* intégrer (l'issue) et valider *comment* c'est rédigé (la PR). Tout le reste est automatisé ou délégué à une session Claude locale.

## Gabarit de l'issue de veille

La routine (et toute révision manuelle) produit une issue suivant **exactement** ce gabarit.
Titre : `Veille état de l'art — AAAA-MM` (suffixe ` — rien de neuf` si aucune nouveauté).
Label : `veille`.

```markdown
## Synthèse
Veille du {date}. **{N} nouveauté(s)** à arbitrer{, dont {J} jalon(s) paru(s)} ·
**{M} source(s) vérifiée(s) sans changement**.
<!-- si rien : « Aucune nouveauté — cette issue est une trace de vérification, rien à intégrer. » -->

## 👉 Ce qui est attendu de toi (Alexis)
<!-- si nouveautés -->
1. Lis « Nouveautés détectées » et **coche** ta décision pour chaque item.
2. En session Claude Code dans `meteo`, écris : **« traite l'issue de veille #{N} »** (précise les items retenus). Claude fait l'intégration ; tu n'édites rien à la main.
3. **Relis la PR** de Claude (valeurs exactes, provenance, lisibilité) puis **merge** → la CI republie le site.
4. L'issue se ferme à la fusion de la PR.
<!-- si rien de neuf -->
- Rien à intégrer. **Ferme simplement cette issue.**

## Nouveautés détectées
### 1. {source / jalon} — {titre court}
- **Lien** : {url}
- **Type** : nouvelle édition / jalon paru / révision réglementaire
- **Robustesse** : primaire / officiel / scientifique / expert
- **Ce qui change** : {valeur/édition citée aujourd'hui → nouvelle valeur ; ou « publication parue »}
- **À mettre à jour** : `etat-art-climat/{fichier}.qmd` · bib `{clef}` · `sources/README.md`
- **Reco de l'agent** : intégrer maintenant / continuer à surveiller / écarter — {pourquoi}
- **Ta décision** : [ ] intégrer  [ ] différer  [ ] écarter
<!-- répéter par item -->

## Vérifié sans changement (traçabilité)
- {source} — {url} — inchangé depuis {dernière vérif}
- {jalon} — toujours non publié au {date}

## Pour Claude — rappel de la procédure d'intégration
Archiver la source dans `sources/` (+ transcription Markdown si volumineux) ; **valeurs exactes**
(pas d'approximation) avec **valeur historique 1976-2005 entre parenthèses** pour tout chiffre
projeté ; **signaler la provenance** d'une donnée transposée (hors maraîchage breton) ; **une seule
méthode par phénomène** ; **pas de référence « ADR-XXXX »** dans le texte affiché ; bumper « dernière
révision » (préface + ce fichier) + compléter le journal ; `quarto render` (0 warning) ; commit
thématique ; PR sans merge automatique.

---
*Généré par la routine « Veille état de l'art climat » le {date}. Prochaine veille : {next}.*
```

## Journal des révisions

- **2026-06-08 — Traitement de l'issue de veille #4** (1ʳᵉ passe). **Intégré** : France Stratégie
  NA 156 *L'eau en 2050* (confrontation demande↔ressource, jalon paru — national, muet sur la
  Bretagne) ; **État des lieux 2025** Loire-Bretagne (préalable SDAGE 2028-2033) ; brochure
  consolidée **OEB Chiffres clés 2025** ; **23ᵉ Baromètre Agence Bio** (reprise conso 2025) ;
  **sécheresse été 2025** en Ille-et-Vilaine (bassins côtiers/forage en alerte). 5 entrées bib
  ajoutées, 1 transcription archivée. **Différé / à surveiller à la prochaine passe** : *Chiffres
  du bio 2025* (non parus, attendus fin juin 2026) ; nouvel **arrêté-cadre sécheresse 35**
  (consultation publique référencée) ; HMUC Couesnon et pré-HMUC SAGE Dol (toujours non publiées).
- **2026-06 — Création.** Mise en place de la veille. État initial : livre complet (Parties I/II
  + annexes A/B/C), 20 fichiers, dernier rendu CI vert. Intégrations récentes : prospective
  France Stratégie « demande en eau 2050 », note SDAGE 2028-2033 / pré-HMUC SAGE Dol, annexe C
  (lectures approfondies). Prochaine passe : **2026-10**.
