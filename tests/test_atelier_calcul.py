"""Tests offline de la prévision de l'atelier irrigation (run MF partagé + repli).

Vérifie que l'atelier lit en priorité le run ARPEGE MF-direct publié par le mail
(asset de release) quand il correspond au run du jour, et retombe sur Open-Meteo
sinon — sans aucun appel réseau (parquet local + source stubée).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from apps.atelier_irrigation import calcul  # noqa: E402

RUN = pd.Timestamp("2026-06-13 00:00", tz="UTC")


def _parquet(tmp_path: Path, debut: pd.Timestamp, nom: str = "run.parquet") -> str:
    """Écrit un parquet (index horaire UTC depuis ``debut``) et renvoie son chemin."""
    idx = pd.date_range(debut, periods=24, freq="h", tz="UTC", name="time")
    df = pd.DataFrame({"temperature_2m": [288.0] * len(idx)}, index=idx)
    chemin = tmp_path / nom
    df.to_parquet(chemin)
    return str(chemin)


class _SourceInterdite:
    """Source Open-Meteo qui échoue si on l'appelle (prouve la non-dépendance)."""

    def obtenir_run(self, *a, **k):
        raise AssertionError("Open-Meteo ne doit PAS être appelé quand le run MF est frais")


class _SourceOpenMeteo:
    """Stub Open-Meteo : renvoie un df socle minimal."""

    def obtenir_run(self, modele, run_utc, latitude, longitude, horizon_jours, variables):
        idx = pd.date_range(run_utc, periods=24, freq="h", tz="UTC", name="time")
        return pd.DataFrame({"temperature_2m": [290.0] * len(idx)}, index=idx)


def test_charger_run_partage_frais(tmp_path: Path) -> None:
    """Parquet dont le 1ᵉʳ pas = run du jour → servi."""
    df = calcul.charger_run_partage(_parquet(tmp_path, RUN), RUN)
    assert df is not None and not df.empty


def test_charger_run_partage_perime(tmp_path: Path) -> None:
    """Parquet d'un run de la veille → écarté (None), pas de vieille prévi en douce."""
    veille = _parquet(tmp_path, RUN - pd.Timedelta(days=1))
    assert calcul.charger_run_partage(veille, RUN) is None


def test_charger_run_partage_absent() -> None:
    """URL/chemin illisible → None (repli)."""
    assert calcul.charger_run_partage("/tmp/inexistant_xyz.parquet", RUN) is None


def test_obtenir_prevision_mf_prioritaire_sans_open_meteo(tmp_path: Path) -> None:
    """Run MF frais → utilisé ; Open-Meteo n'est PAS appelé."""
    df, source = calcul.obtenir_prevision(
        48.5, -1.6, 4, RUN, url_partage=_parquet(tmp_path, RUN), source=_SourceInterdite()
    )
    assert not df.empty
    assert "Météo-France" in source


def test_obtenir_prevision_repli_open_meteo(tmp_path: Path) -> None:
    """Run MF périmé → repli Open-Meteo (libellé explicite)."""
    perime = _parquet(tmp_path, RUN - pd.Timedelta(days=1))
    df, source = calcul.obtenir_prevision(
        48.5, -1.6, 4, RUN, url_partage=perime, source=_SourceOpenMeteo()
    )
    assert not df.empty
    assert source == "Open-Meteo (repli)"


def test_obtenir_prevision_sans_url_partage_va_sur_open_meteo() -> None:
    """Sans URL partagée → Open-Meteo directement."""
    df, source = calcul.obtenir_prevision(48.5, -1.6, 4, RUN, source=_SourceOpenMeteo())
    assert not df.empty
    assert source == "Open-Meteo (repli)"
