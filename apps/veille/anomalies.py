"""Anomalies non bloquantes du mail Veille + rapport de bug.

Quand une partie dégrade (ex. ARPEGE indisponible → repli sur ECMWF, cartes
omises…), on **ne casse pas le mail** : on pose une **note inline** discrète juste
avant la partie concernée (« … voir rapport de bug ci-dessous ») et on accumule un
**rapport de bug en fin de mail** (regroupé, pour ne pas polluer la lecture), avec
le maximum d'infos utiles au debug.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class Anomalie:
    """Une anomalie non bloquante détectée pendant la composition du mail.

    Parameters
    ----------
    section :
        Partie concernée (ex. « La semaine », « Cartes »).
    resume :
        Phrase courte pour la note inline (ex. « ARPEGE indisponible, repli sur
        ECMWF »). Affichée juste avant la partie concernée.
    detail :
        Détail technique pour le rapport de bug (modèle, run, code HTTP, message
        d'erreur…) — destiné à accélérer le debug.
    """

    section: str
    resume: str
    detail: str


def note_inline(resume: str) -> str:
    """Bandeau discret signalant une anomalie + renvoi au rapport en fin de mail."""
    return (
        '<div style="margin:8px 0;padding:6px 10px;background:#fff8e1;'
        "border-left:3px solid #E69F00;border-radius:0 3px 3px 0;"
        'font-size:12px;color:#8a6d3b;">⚠ '
        f"{resume} — voir le rapport de bug en fin de mail.</div>"
    )


def bloc_rapport_bug(anomalies: list[Anomalie], now_utc: pd.Timestamp) -> str:
    """Rapport de bug en bas de mail (vide s'il n'y a aucune anomalie)."""
    if not anomalies:
        return ""
    lignes = "".join(
        f'<li style="margin:4px 0;"><strong>{a.section}</strong> — {a.resume}'
        f'<div style="color:#9a6a6a;font-size:11px;margin-top:1px;">{a.detail}</div></li>'
        for a in anomalies
    )
    return (
        '<div style="margin:24px 0 0 0;padding:10px 12px;background:#fbeaea;'
        'border:1px solid #e0b4b4;border-radius:4px;font-size:12px;color:#7a3b3b;">'
        "<strong>🐞 Rapport de bug — anomalies détectées</strong>"
        '<div style="font-size:11px;color:#999;margin:2px 0 6px 0;">'
        f"Généré le {now_utc:%Y-%m-%d %H:%M} UTC. À transmettre tel quel pour debug.</div>"
        f'<ul style="margin:0;padding-left:18px;">{lignes}</ul></div>'
    )
