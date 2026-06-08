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
| **France Stratégie — étude « demande vs ressource »** | Confronte demande (rapport 2025) et ressource par territoire → zones de tension | strategie.gouv.fr | annoncée « à paraître » |

## Journal des révisions

- **2026-06 — Création.** Mise en place de la veille. État initial : livre complet (Parties I/II
  + annexes A/B/C), 20 fichiers, dernier rendu CI vert. Intégrations récentes : prospective
  France Stratégie « demande en eau 2050 », note SDAGE 2028-2033 / pré-HMUC SAGE Dol, annexe C
  (lectures approfondies). Prochaine passe : **2026-10**.
