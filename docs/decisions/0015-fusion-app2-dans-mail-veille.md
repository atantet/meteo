# ADR-0015 — Fusion de l'App 2 dans le mail Veille (semaine du matin) + atelier irrigation

## Statut

**Accepté** (2026-06-09). **Amende [ADR-0014](0014-prevision-officielle-mf-veille.md)** :
l'« App 2 Opérationnelle » n'est plus un dashboard Streamlit autonome. Sa partie
**statique** (tendance, guides, cartes) est composée **dans le mail Veille du matin** ;
sa seule partie **interactive** (bilan hydrique) devient un mini-Streamlit dédié,
l'**atelier irrigation**. Le partage de sources d'ADR-0014 (App 1 = prévi officielle
MF ; semaine = Single Runs ARPEGE + ECMWF, UTC) est **inchangé** — seul le canal de
diffusion de la semaine change (dashboard → mail).

## Contexte

Déclencheur (2026-06-09, porteur) : « pas pratique d'avoir un mail pour les 48 h et
une app Streamlit pour la semaine ». Deux canaux pour un même geste de consultation
quotidienne. La 48 h (mail) est stabilisée ; la semaine (dashboard) demandait une
seconde action (ouvrir l'app).

Constat sur le contenu de l'ex-App 2 :

- **Statique** (rend en HTML mail sans perte) : tendance jour/nuit ARPEGE + ECMWF,
  guides de décision de la semaine, cartes ARPEGE-Europe, repères MF.
- **Interactif** (ne survit pas à un mail) : bilan hydrique (culture / stade / texture
  sol / cailloux / RU / seuil irrigation / preset tunnel), courbes horaires en onglets,
  sliders d'ajustement des seuils de guides.

## Décision

1. **Un seul canal quotidien : le mail.** Le mail du **matin** = Partie 1 (48 h, App 1
   inchangée) **+** Partie 2 « La semaine ». Le mail de l'**après-midi** reste 48 h seul
   (la tendance bouge peu en une demi-journée ; on n'alourdit pas l'après-midi).
   Aiguillage par `moment_envoi(...) == "matin"`.
2. **La semaine en UTC, la 48 h en heure locale**, chacune étiquetée. Les fenêtres
   Nuit/Jour (18-06 / 06-18) restent calées sur les cycles de run (UTC) — les forcer en
   local les décalerait (cf. mémoire `runs_deterministes_utc`).
3. **Tendance jusqu'à 10 j**, ARPEGE (≤ J+4) + ECMWF IFS empilés par cellule, rendue en
   **tables empilées par jour** (mobile-first, pas de table large à scroll horizontal qui
   passe mal en e-mail). Démarre aujourd'hui (on écarte le bout de passé du run ECMWF
   12Z J-1).
4. **Toutes les cartes regroupées** en une seule série « Situation synoptique » :
   Met Office → AROME (48 h) → **ARPEGE-Europe J+3 / J+4** (00Z, prolongement),
   placée **après** guides + tendance. ARPEGE-Europe plafonne à J+4 ; J+5/J+6 ne sont
   pas servis par Météociel en mode « Résumé » (ECMWF/GFS y renvoient 404).
5. **Seuils d'exploitation en pied de mail**, valables pour la 48 h (Vigilance
   exploitation) **et** la semaine (guides).
6. **Bilan hydrique → atelier irrigation** (`apps/atelier_irrigation/`, Streamlit) :
   seul rescapé interactif. Lié depuis le mail (URL à renseigner une fois déployé).
7. **Suppressions** : dashboard `apps/operationnelle/streamlit_app.py`, son `__main__`,
   `streamlit_app_demo.py`, `ui_helpers.py`, les courbes horaires et les sliders de
   seuils. Les modules de **calcul** (`tendances`, `decisions`, `indicateurs`,
   `cartes_geo`, `series_temp`, `charts`, `config`, `demo`) restent dans
   `apps/operationnelle/` et sont **réutilisés** par le mail (`apps/veille/semaine.py`)
   et l'atelier.

## Conséquences

- **+** Un seul geste quotidien ; tout est dans la boîte mail. La 48 h stabilisée n'est
  pas touchée (Partie 2 purement additive, en dégradation gracieuse : si le fetch
  semaine échoue, le mail 48 h part seul).
- **+** Le bilan hydrique garde son interactivité là où elle a du sens.
- **−** Perte de l'exploration interactive de la tendance et des seuils de guides (les
  guides utilisent désormais les seuils config par défaut). Acceptable : la valeur
  décisionnelle est dans les guides (texte) et la tendance (table).
- **−** Poids du mail du matin (cartes synoptiques + 2 cartes ARPEGE). Dominé par les
  cartes synoptiques 48 h préexistantes ; au-delà du seuil de clipping Gmail (~102 ko),
  qui affiche « message entier » en un clic. Levier futur si gênant : alléger les cartes
  synoptiques 48 h (hors périmètre de cette décision, partie stabilisée).
- **Déploiement** : repointer (ou recréer) l'app Streamlit Cloud sur
  `apps/atelier_irrigation/streamlit_app.py`.
- **Tests** : test d'intégration offline du mail matin fusionné
  (`tests/test_veille_semaine_integration.py`, source Single Runs injectée).
