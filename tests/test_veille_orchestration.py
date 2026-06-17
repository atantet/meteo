"""Tests d'intégration App 1 Veille — pipeline complet (prévi MF, ADR-0014)."""

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


def _config_test() -> dict:
    return {
        "site": {"latitude": 48.5, "longitude": -1.6, "altitude": 30, "tz": "Europe/Paris"},
        "alertes": {
            "gel": {"actif": True, "seuil_celsius": 4.0},
            "canicule_aeration": {"actif": True, "seuil_celsius": 25.0},
            "canicule_stress": {"actif": True, "seuil_celsius": 30.0},
            "risque_maladies": {"actif": True, "t_min_nuit_celsius": 15.0},
            "pluie_intense": {"actif": True, "seuil_mm_24h": 20.0},
            "vent_fort": {"actif": True, "seuil_kmh": 60.0},
        },
        "indicateurs": {},
        "email": {
            "format": "html_mobile",
            "sujet_template": "Veille {date} — {alertes_resume}",
            "inclure_lien_fiches_indices": False,
            "url_fiches_indices": "",
        },
        "diffusion": {"envoi_reel": False},
    }


def _prevision_synthetique(
    t_celsius: float = 15.0, debut: str = "2024-06-15 00:00"
) -> pd.DataFrame:
    """72 h de prévision horaire homogène, colonnes socle (comme la source MF)."""
    index = pd.date_range(debut, periods=72, freq="h", tz="UTC")
    return pd.DataFrame(
        {
            "temperature_2m": np.full(72, t_celsius + 273.15),
            "humidite_relative": np.full(72, 0.7),
            "precipitation": np.full(72, 0.0),
            "probabilite_pluie_pct": np.full(72, 0.0),
            "vitesse_vent_10m": np.full(72, 5.0),
            "rafales_vent_10m": np.full(72, 9.0),
            "direction_vent_deg": np.full(72, 270.0),
            "cloud_cover": np.full(72, 0.5),
            "weather_code": pd.array([1] * 72, dtype="Int64"),
        },
        index=index,
    )


def _prev48h(df: pd.DataFrame, vig=None):
    """Tuple ``(Prevision48h, VigilanceDP)`` tel que renvoyé par ``assembler_prevision_48h``."""
    from apps.veille.prevision_48h import Prevision48h
    from meteo_socle.sources.dpvigilance import VigilanceDepartementDP

    prev = Prevision48h(
        df=df,
        proba_bins=df["probabilite_pluie_pct"],
        updated_on=pd.Timestamp("2024-06-15 03:00", tz="UTC"),
        position={"name": "Sains", "timezone": "Europe/Paris"},
    )
    if vig is None:
        vig = VigilanceDepartementDP(departement="35", phenomenes=[])
    return prev, vig


def test_executer_veille_dry_run_capture_stdout() -> None:
    """Pipeline complet : assemblage 48 h mocké → indicateurs → alertes → email → dry-run."""
    from apps.veille import __main__ as veille_main

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    # 10 °C constant → ni gel (>4), ni maladies (<15), ni canicule (<25) → RAS.
    buf = io.StringIO()
    with (
        patch.object(
            veille_main,
            "assembler_prevision_48h",
            return_value=_prev48h(_prevision_synthetique(10.0)),
        ) as asm,
        patch("sys.stdout", buf),
    ):
        code = veille_main.executer_veille(config, secrets=None, now_utc=now, inclure_semaine=False)

    assert code == 0
    output = buf.getvalue()
    assert "dry-run" in output
    assert "Veille 2024-06-15 — RAS" in output
    asm.assert_called_once()


def test_run_recent_grilles_arome_pearome() -> None:
    """Sélection de run : grilles AROME (mult. de 3) et PE-AROME (03/09/15/21), fraîcheur."""
    from apps.veille.__main__ import (
        CYCLE_AROME_H,
        CYCLE_PEAROME_H,
        OFFSET_AROME_H,
        OFFSET_PEAROME_H,
        _run_recent,
    )

    now = pd.Timestamp("2026-06-15 19:30:00+00:00")
    # AROME : 18 Z trop frais (1,5 h) → 15 Z (4,5 h ≥ 3,5).
    assert _run_recent(now, CYCLE_AROME_H, OFFSET_AROME_H) == pd.Timestamp("2026-06-15 15:00Z")
    # PE-AROME : grille 03/09/15/21 → 15 Z (pas 12 Z).
    assert _run_recent(now, CYCLE_PEAROME_H, OFFSET_PEAROME_H) == pd.Timestamp("2026-06-15 15:00Z")
    # PE-AROME début d'après-midi : 15 Z pas encore → 09 Z.
    midi = pd.Timestamp("2026-06-15 13:00:00+00:00")
    assert _run_recent(midi, CYCLE_PEAROME_H, OFFSET_PEAROME_H) == pd.Timestamp("2026-06-15 09:00Z")
    # AROME en pleine nuit → run de la veille (21 Z).
    nuit = pd.Timestamp("2026-06-15 01:00:00+00:00")
    assert _run_recent(nuit, CYCLE_AROME_H, OFFSET_AROME_H) == pd.Timestamp("2026-06-14 21:00Z")


def test_executer_veille_portail_etiquette_modele_arome() -> None:
    """48 h portail-api : étiquetée « modèle AROME (picto dérivé) », pas « officielle »."""
    from apps.veille import __main__ as veille_main

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    buf = io.StringIO()
    with (
        patch.object(
            veille_main,
            "assembler_prevision_48h",
            return_value=_prev48h(_prevision_synthetique(12.0)),
        ) as asm,
        patch("sys.stdout", buf),
    ):
        code = veille_main.executer_veille(config, secrets=None, now_utc=now, inclure_semaine=False)
    assert code == 0
    asm.assert_called_once()
    sortie = buf.getvalue()
    assert "MODÈLE AROME" in sortie
    assert "PRÉVISION MÉTÉO-FRANCE OFFICIELLE" not in sortie


def test_executer_veille_portail_repli_run_precedent() -> None:
    """Run le plus frais pas publié → repli sur le run précédent (pas d'omission)."""
    from apps.veille import __main__ as veille_main
    from meteo_socle.sources.meteofrance_arome import AromeIndisponibleError

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    # 1er run (frais) pas publié → 2e appel (run précédent) réussit.
    asm = MagicMock(
        side_effect=[
            AromeIndisponibleError("run 404"),
            _prev48h(_prevision_synthetique(12.0)),
        ]
    )

    buf = io.StringIO()
    with patch.object(veille_main, "assembler_prevision_48h", asm), patch("sys.stdout", buf):
        code = veille_main.executer_veille(config, secrets=None, now_utc=now, inclure_semaine=False)
    assert code == 0
    assert asm.call_count == 2  # repli effectué (1 échec + 1 succès)
    # 2e appel sur un run AROME plus ancien que le 1er (1ᵉʳ arg positionnel).
    run1 = asm.call_args_list[0].args[0]
    run2 = asm.call_args_list[1].args[0]
    assert run2 < run1


def test_grille_couvre_plusieurs_periodes() -> None:
    """La grille du mail couvre plusieurs périodes 6 h (pictos depuis weather_code MF).

    Envoi après-midi : la grille s'arrête au soir de J+1 (cap aligné sur l'horizon
    Vigilance) → créneau Soir de J + 4 périodes de J+1 = au moins 5 pictos.
    """
    from apps.veille.alertes import evaluer_alertes
    from apps.veille.email import composer_email
    from apps.veille.indicateurs import calculer_indicateurs

    prevision = _prevision_synthetique(12.0, debut="2024-06-15 04:00")
    config = _config_test()
    now = pd.Timestamp("2024-06-15 17:30:00+00:00")
    ind = calculer_indicateurs(prevision, now, config)
    alertes = evaluer_alertes(ind, config)
    email = composer_email(ind, alertes, config, now.to_pydatetime(), prevision_horaire=prevision)
    assert "Tendance jusqu" in email.html
    assert email.html.count("data:image") >= 5


def test_executer_veille_gel_plus_dans_le_corps_48h() -> None:
    """Vigilance exploitation 48 h retirée : un gel ne rend plus d'alerte dans le corps.

    L'alerte reste évaluée (le template de test la résume via {alertes_resume} dans le
    sujet), mais le bloc « Vigilance exploitation » a disparu — le gel est désormais
    porté par le guide « purge + voiles » de la semaine.
    """
    from apps.veille import __main__ as veille_main

    config = _config_test()
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")
    buf = io.StringIO()
    with (
        patch.object(
            veille_main,
            "assembler_prevision_48h",
            return_value=_prev48h(_prevision_synthetique(-5.0)),
        ),
        patch("sys.stdout", buf),
    ):
        code = veille_main.executer_veille(config, secrets=None, now_utc=now, inclure_semaine=False)

    assert code == 0
    out = buf.getvalue()
    # Résumé d'alertes encore disponible pour le sujet (template de test).
    assert "— gel" in out
    # Mais plus de bloc « Vigilance exploitation » ni d'action gel dans le corps.
    assert "VIGILANCE EXPLOITATION" not in out
    assert "purger" not in out.lower()


def test_executer_veille_48h_down_returns_2() -> None:
    """48 h portail injoignable (essai intermédiaire) → exit code 2."""
    from apps.veille import __main__ as veille_main
    from meteo_socle.sources.meteofrance_arome import AromeIndisponibleError

    config = _config_test()
    now = pd.Timestamp("2024-06-15 04:30:00+00:00")
    asm = MagicMock(side_effect=AromeIndisponibleError("500"))
    with patch.object(veille_main, "assembler_prevision_48h", asm):
        code = veille_main.executer_veille(config, secrets=None, now_utc=now, inclure_semaine=False)
    assert code == 2


def test_executer_veille_48h_down_sans_repli_nenvoie_pas_echec() -> None:
    """Essai intermédiaire (fallback_mf=False) : 48 h down → code 2 SANS mail d'échec.

    Le portail peut être momentanément injoignable depuis les runners ; le workflow
    retente puis, en dernier recours, omet la 48 h (mail « semaine seule »). Les
    essais intermédiaires ne doivent pas spammer de mails d'échec.
    """
    from apps.veille import __main__ as veille_main
    from meteo_socle.sources.meteofrance_arome import AromeIndisponibleError

    now = pd.Timestamp("2024-06-15 04:30:00+00:00")
    asm = MagicMock(side_effect=AromeIndisponibleError("timeout"))
    with (
        patch.object(veille_main, "assembler_prevision_48h", asm),
        patch.object(veille_main, "_envoyer_echec") as mock_echec,
    ):
        code = veille_main.executer_veille(
            _config_test(),
            secrets=None,
            now_utc=now,
            inclure_semaine=False,
            fallback_mf=False,
        )
    assert code == 2
    mock_echec.assert_not_called()


def test_executer_veille_48h_down_dernier_recours_sans_semaine_envoie_echec() -> None:
    """Dernier recours (fallback_mf=True) sans semaine : 48 h down → mail d'échec.

    48 h injoignable → on omet la 48 h. Mais ici la section semaine est désactivée
    (``inclure_semaine=False``) → aucun contenu exploitable → vrai échec notifié
    (on ne livre jamais un mail vide).
    """
    from apps.veille import __main__ as veille_main
    from meteo_socle.sources.meteofrance_arome import AromeIndisponibleError

    now = pd.Timestamp("2024-06-15 04:30:00+00:00")
    asm = MagicMock(side_effect=AromeIndisponibleError("timeout"))
    with (
        patch.object(veille_main, "assembler_prevision_48h", asm),
        patch.object(veille_main, "_envoyer_echec") as mock_echec,
    ):
        code = veille_main.executer_veille(
            _config_test(),
            secrets=None,
            now_utc=now,
            inclure_semaine=False,
            fallback_mf=True,
        )
    assert code == 2
    mock_echec.assert_called_once()


def test_executer_veille_envoi_reel_appelle_smtp() -> None:
    """En mode envoi_reel=True, vérifie que envoyer() invoque le SMTP."""
    from apps.veille import __main__ as veille_main

    config = _config_test()
    config["diffusion"]["envoi_reel"] = True
    secrets = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "u@example.com",
        "password": "pwd",
        "email_from": "u@example.com",
        "email_to": ["dest@example.com"],
    }
    now = pd.Timestamp("2024-06-15 06:00:00+00:00")

    with (
        patch.object(
            veille_main,
            "assembler_prevision_48h",
            return_value=_prev48h(_prevision_synthetique(15.0)),
        ),
        patch("apps.veille.sender.smtplib.SMTP") as mock_smtp,
    ):
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server
        code = veille_main.executer_veille(
            config, secrets=secrets, now_utc=now, inclure_semaine=False
        )

    assert code == 0
    mock_smtp.assert_called_once_with("smtp.example.com", 587)
    mock_server.send_message.assert_called_once()
