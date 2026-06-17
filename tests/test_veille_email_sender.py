"""Tests `apps.veille.email` + `apps.veille.sender`."""

from __future__ import annotations

import io
import re
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))


CONFIG_TEST = {
    "email": {
        "format": "html_mobile",
        "sujet_template": "Veille {date} — {alertes_resume}",
        "inclure_lien_fiches_indices": True,
        "url_fiches_indices": "https://example.com/fiches",
    }
}


def _ind(**kwargs):
    import pandas as pd

    from apps.veille.indicateurs import IndicateursVeille

    defaults = dict(
        temperature_min_24h_celsius=8.0,
        temperature_max_24h_celsius=18.0,
        temperature_min_48h_celsius=6.0,
        temperature_max_48h_celsius=19.0,
        cumul_pluie_24h_mm=2.5,
        cumul_pluie_48h_mm=5.0,
        vent_max_24h_kmh=20.0,
        rafales_max_24h_kmh=35.0,
        direction_vent_dominante_deg=270.0,
        direction_vent_dominante_cardinal="O",
        prob_pluie_max_24h_pct=15.0,
        prob_pluie_max_48h_pct=30.0,
        prevision_t0_local=pd.Timestamp("2024-06-15 06:00:00+00:00"),
    )
    defaults.update(kwargs)
    return IndicateursVeille(**defaults)


def _alerte_gel():
    from apps.veille.alertes import Alerte

    return Alerte("gel", "critique", "Gel — T° min −3.0 °C", -3.0, "°C", -2.0)


def test_composer_sujet_ras() -> None:
    from apps.veille.email import composer_sujet

    sujet = composer_sujet([], datetime(2024, 6, 15, 7, 30), "Veille {date} — {alertes_resume}")
    assert sujet == "Veille 2024-06-15 — RAS"


def test_composer_sujet_avec_alertes() -> None:
    from apps.veille.email import composer_sujet

    sujet = composer_sujet(
        [_alerte_gel()],
        datetime(2024, 6, 15),
        "Veille {date} — {alertes_resume}",
    )
    assert "gel" in sujet
    assert "2024-06-15" in sujet


def test_composer_sujet_moment() -> None:
    """{moment} est substitué dans le sujet (distingue matin / après-midi)."""
    from apps.veille.email import composer_sujet

    tmpl = "Veille {moment} {date} — {alertes_resume}"
    s_matin = composer_sujet([], datetime(2024, 6, 15, 7, 30), tmpl, moment="matin")
    s_pm = composer_sujet([], datetime(2024, 6, 15, 7, 30), tmpl, moment="après-midi")
    assert s_matin == "Veille matin 2024-06-15 — RAS"
    assert s_pm == "Veille après-midi 2024-06-15 — RAS"


def test_composer_email_moment_deduit_de_l_heure() -> None:
    """composer_email déduit matin/après-midi de l'heure locale d'envoi."""
    from apps.veille.email import composer_email

    config = {
        "site": {"tz": "Europe/Paris"},
        "email": {"sujet_template": "{titre} — {alertes_resume}"},
    }
    # Moment = créneau de run UTC (bornes 05:30 / 17:30 UTC), ADR-0011 D3.
    # 07:00 UTC → matin.
    matin = composer_email(_ind(), [], config, datetime(2024, 6, 15, 7, 0))
    # 18:00 UTC (≥ 17:30) → après-midi.
    pm = composer_email(_ind(), [], config, datetime(2024, 6, 15, 18, 0))
    # Sujet aligné sur le titre affiché, suffixé du résumé d'alertes (RAS).
    assert matin.sujet.startswith("Météo du") and "matin — RAS" in matin.sujet
    assert pm.sujet.startswith("Météo du") and "après-midi — RAS" in pm.sujet
    # Titre HTML « Météo du … matin/après-midi » (tiret seulement devant RAS).
    assert "Météo du" in matin.html and "matin" in matin.html
    assert "Météo du" in pm.html and "après-midi" in pm.html


def test_sujet_aligne_sur_titre_du_contenu() -> None:
    """Le sujet = titre affiché du mail + résumé d'alertes (RAS ou autre)."""
    from apps.veille.email import _titre_mail, composer_sujet

    maintenant = datetime(2024, 6, 15, 16, 0)
    titre = _titre_mail(maintenant, moment="après-midi")
    sujet = composer_sujet([], maintenant, "{titre} — {alertes_resume}", moment="après-midi")
    # Le sujet commence exactement par le titre du contenu, puis « — RAS ».
    assert sujet == f"{titre} — RAS"
    assert sujet.startswith(titre)


def test_composer_html_titre_moment_apres_midi_montre_12h() -> None:
    """Titre « Météo … après-midi » + fraîcheur MF (updated_on) sous la section."""
    import pandas as pd

    from apps.veille.email import composer_html

    # updated_on = 10:00 UTC = 12:00 locale (Europe/Paris été).
    maj = pd.Timestamp("2024-06-15 10:00:00+00:00")
    html = composer_html(
        _ind(),
        [],
        datetime(2024, 6, 15, 16, 0),
        moment="après-midi",
        tz_locale="Europe/Paris",
        updated_on=maj,
    )
    assert "Météo du" in html and "après-midi" in html
    assert "modèle AROME" in html
    assert "Mise à jour" in html and "12h00" in html


def test_composer_texte_contient_alertes_et_indicateurs() -> None:
    from apps.veille.email import composer_texte

    txt = composer_texte(_ind(), [_alerte_gel()], datetime(2024, 6, 15, 7, 30))
    # Vigilance exploitation 48 h retirée (2026-06-14) — plus de bloc d'alertes ici.
    assert "VIGILANCE EXPLOITATION" not in txt
    assert "INDICATEURS" in txt
    # Valeurs présentes.
    assert "8.0" in txt or "8" in txt  # T° min
    # Section 48 h nommée (source par section, pas de footer).
    assert "PRÉVISION MÉTÉO-FRANCE — MODÈLE AROME" in txt
    # Titre « Météo du … » en date courte (jour J/MM).
    assert "Météo du samedi 15/06" in txt
    # Direction du vent dominante.
    assert "Vent direction dom." in txt


def test_composer_texte_sans_bloc_vigilance_exploitation() -> None:
    """La Vigilance exploitation 48 h a été retirée du corps texte (2026-06-14)."""
    from apps.veille.email import composer_texte

    txt = composer_texte(_ind(), [], datetime(2024, 6, 15, 7, 30))
    assert "VIGILANCE EXPLOITATION" not in txt
    assert "INDICATEURS" in txt


def test_composer_html_structure() -> None:
    from apps.veille.email import composer_html

    html = composer_html(_ind(), [_alerte_gel()], datetime(2024, 6, 15, 7, 30))
    assert "<!DOCTYPE html>" in html
    assert 'name="viewport"' in html  # responsive mobile
    # Vigilance exploitation 48 h retirée → l'alerte gel ne s'affiche plus ici
    # (le gel est porté par le guide « purge + voiles » de la semaine).
    assert "Vigilance exploitation" not in html
    # Footer + source (prévision officielle MF) garantis.
    assert "Météo-France" in html


def test_composer_email_bundle() -> None:
    from apps.veille.email import composer_email

    result = composer_email(_ind(), [], CONFIG_TEST, datetime(2024, 6, 15, 7, 30))
    assert result.sujet == "Veille 2024-06-15 — RAS"
    assert "INDICATEURS" in result.texte
    assert "<!DOCTYPE html>" in result.html


def test_construire_message_multipart() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import construire_message

    email = EmailComposed(sujet="S", texte="T", html="<p>H</p>")
    msg = construire_message(email, "a@b.com", ["c@d.com", "e@f.com"])
    assert msg["Subject"] == "S"
    assert msg["From"] == "a@b.com"
    assert msg["To"] == "c@d.com, e@f.com"
    payloads = msg.get_payload()
    assert len(payloads) == 2  # texte + html


def test_construire_message_images_inline_cid() -> None:
    """Images data-URI → parties inline CID, dédupliquées par contenu."""
    from apps.veille.email import EmailComposed
    from apps.veille.sender import construire_message

    img_a = "data:image/png;base64,QUJD"  # "ABC" — utilisée 2×
    img_b = "data:image/svg+xml;base64,WFla"  # "XYZ" — utilisée 1×
    html = f'<p><img src="{img_a}"><img src="{img_a}"><img src="{img_b}"></p>'
    email = EmailComposed(sujet="S", texte="T", html=html)
    msg = construire_message(email, "a@b.com", ["c@d.com"])

    # Structure multipart/related = 1 alternative + 2 images uniques (img_a dédupliquée).
    assert msg.get_content_subtype() == "related"
    parts = msg.get_payload()
    assert len(parts) == 3

    # Le HTML ne contient plus de data:, mais 3 références cid: (2 distinctes).
    html_part = parts[0].get_payload()[1].get_payload(decode=True).decode("utf-8")
    assert "data:image" not in html_part
    assert html_part.count("cid:img") == 3

    images = parts[1:]
    assert len(images) == 2
    for im in images:
        assert im.get("Content-ID", "").startswith("<img")
        assert im.get("Content-Disposition") == "inline"
    assert sorted(im.get_content_subtype() for im in images) == ["png", "svg+xml"]
    # Chaque cid du HTML correspond à un Content-ID joint.
    cids_html = set(re.findall(r"cid:(img\d+@veille)", html_part))
    cids_parts = {im.get("Content-ID").strip("<>") for im in images}
    assert cids_html == cids_parts


def test_envoyer_dry_run() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer_dry_run

    email = EmailComposed(sujet="Sujet test", texte="Corps texte", html="<p>H</p>")
    stream = io.StringIO()
    envoyer_dry_run(email, stream=stream)
    output = stream.getvalue()
    assert "Sujet test" in output
    assert "Corps texte" in output
    assert "dry-run" in output


def test_envoyer_dispatch_dry_run() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer

    email = EmailComposed(sujet="S", texte="T", html="H")
    stream = io.StringIO()
    envoyer(email, secrets=None, envoi_reel=False, stream=stream)
    assert "dry-run" in stream.getvalue()


def test_envoyer_smtp_mock() -> None:
    """Vérifie le pattern d'appel SMTP : ehlo / starttls / login / send_message."""
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer_smtp

    email = EmailComposed(sujet="S", texte="T", html="<p>H</p>")
    secrets = {
        "host": "smtp.gmail.com",
        "port": 587,
        "user": "test@gmail.com",
        "password": "abcd",
        "email_from": "test@gmail.com",
        "email_to": ["dest@example.com"],
    }
    mock_smtp = MagicMock()
    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    envoyer_smtp(email, secrets, smtp_class=mock_smtp)

    mock_smtp.assert_called_once_with("smtp.gmail.com", 587)
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("test@gmail.com", "abcd")
    mock_server.send_message.assert_called_once()


def test_envoyer_envoi_reel_sans_secrets_raise() -> None:
    from apps.veille.email import EmailComposed
    from apps.veille.sender import envoyer

    email = EmailComposed(sujet="S", texte="T", html="H")
    with pytest.raises(ValueError):
        envoyer(email, secrets=None, envoi_reel=True)


# --- Tests d'intégration cartes synoptiques + vigilance MF (2026-05-31) ---


def _cartes_grille_factice():
    """Fixture CartesGrille avec 8 placeholders data_uri non vides.

    - Met Office : run 2026-06-01 00 UTC, échéances 0/12/24/36 h.
    - AROME : run 2026-05-31 18 UTC (veille), échéances 6/18/30/42 h.

    Les 4 cibles UTC sont identiques entre les 2 sources.
    """
    import pandas as pd

    from apps.veille.cartes_synoptiques import CartesGrille, CarteSynoptique

    placeholder = "data:image/jpeg;base64,iVBORw0KGgoAAAANSU"  # tronqué, valide pour test HTML
    run_metoffice = pd.Timestamp("2026-06-01 00:00", tz="UTC")
    run_arome = pd.Timestamp("2026-05-31 18:00", tz="UTC")
    metoffice = [
        CarteSynoptique(
            source="metoffice",
            run_utc=run_metoffice,
            cible_utc=run_metoffice + pd.Timedelta(hours=ech),
            data_uri=placeholder,
        )
        for ech in (0, 12, 24, 36)
    ]
    arome = [
        CarteSynoptique(
            source="arome",
            run_utc=run_arome,
            cible_utc=run_arome + pd.Timedelta(hours=ech),
            data_uri=placeholder,
        )
        for ech in (6, 18, 30, 42)
    ]
    return CartesGrille(metoffice=metoffice, arome=arome)


def _vigilance_jaune_orages():
    """Fixture VigilanceDepartement avec Orages en jaune (niveau courant)."""
    import pandas as pd

    from meteo_socle.sources.dpvigilance import (
        PHENOMENES_NOMS,
        PHENOMENES_PERTINENTS,
        VigilanceDepartementDP,
        VigilancePhenomeneDP,
    )

    phenomenes = [
        VigilancePhenomeneDP(code=pid, nom=PHENOMENES_NOMS[pid], niveau_max=2 if pid == 3 else 1)
        for pid in PHENOMENES_PERTINENTS
    ]
    return VigilanceDepartementDP(
        departement="35",
        update_time=pd.Timestamp("2026-05-31 16:00", tz="UTC"),
        fin_validite=pd.Timestamp("2026-06-01 04:00", tz="UTC"),
        phenomenes=phenomenes,
    )


def test_bloc_vigilance_affiche_fenetres_horodatees() -> None:
    """Un phénomène jaune horodaté (DPVigilance) affiche sa fenêtre locale sous le niveau.

    Vérifie : conversion UTC→heure locale, fusion des tranches contiguës (MF découpe
    parfois heure par heure), et que seules les fenêtres au niveau affiché remontent.
    """
    import pandas as pd

    from apps.veille.email import _bloc_vigilance_mf
    from meteo_socle.sources.dpvigilance import (
        TrancheVigilance,
        VigilanceDepartementDP,
        VigilancePhenomeneDP,
    )

    # Orages jaune jeudi : deux tranches CONTIGUËS (12-18 puis 18-20 UTC) → fusionnées.
    orages = VigilancePhenomeneDP(
        code=3,
        nom="Orages",
        niveau_max=2,
        tranches=[
            TrancheVigilance(
                pd.Timestamp("2026-06-18 12:00", tz="UTC"),
                pd.Timestamp("2026-06-18 18:00", tz="UTC"),
                2,
            ),
            TrancheVigilance(
                pd.Timestamp("2026-06-18 18:00", tz="UTC"),
                pd.Timestamp("2026-06-18 20:00", tz="UTC"),
                2,
            ),
        ],
    )
    vig = VigilanceDepartementDP(
        departement="35",
        phenomenes=[orages],
        fin_validite=pd.Timestamp("2026-06-19 00:00", tz="UTC"),
    )
    html = _bloc_vigilance_mf(vig, tz_locale="Europe/Paris")
    assert "Orages" in html
    assert "Horizon" in html  # 3e colonne dédiée
    # CEST = UTC+2 ; tranches fusionnées en une seule plage.
    assert "jeu. 14h–22h" in html  # 12-20 UTC → 14-22 CEST, en-dash


def test_bloc_vigilance_sans_tranches_horizon_tiret() -> None:
    """Phénomène jaune sans tranche horodatée → colonne Horizon = « — » (robuste)."""
    import pandas as pd

    from apps.veille.email import _bloc_vigilance_mf
    from meteo_socle.sources.dpvigilance import VigilanceDepartementDP, VigilancePhenomeneDP

    canicule = VigilancePhenomeneDP(code=6, nom="Canicule", niveau_max=2, tranches=[])
    vig = VigilanceDepartementDP(
        departement="35",
        phenomenes=[canicule],
        fin_validite=pd.Timestamp("2026-06-19 00:00", tz="UTC"),
    )
    html = _bloc_vigilance_mf(vig, tz_locale="Europe/Paris")
    assert "Canicule" in html and "Jaune" in html
    ligne_canicule = html.split("Canicule")[1].split("</tr>")[0]
    # Aucune fenêtre (en-dash) ; la cellule Horizon affiche le tiret cadratin.
    assert "–" not in ligne_canicule  # pas de plage horaire
    assert "—" in ligne_canicule  # cellule Horizon = « — »


def test_composer_html_avec_cartes_grille_contient_les_2_sections() -> None:
    """Le HTML doit contenir les sections Met Office + AROME, avec runs et cibles synchrones."""
    from apps.veille.email import composer_html

    html = composer_html(
        _ind(),
        [],
        datetime(2026, 6, 1, 5, 30),
        cartes_grille=_cartes_grille_factice(),
    )
    assert "Situation synoptique" in html
    assert "Met Office" in html
    assert "AROME" in html
    # Les 2 sections affichent leur run (Met Office = 02h locale, AROME veille = 20h locale).
    assert "Run lun. 01/06 02 h" in html
    assert "Run dim. 31/05 20 h" in html
    assert "(veille)" in html
    # Les 4 échéances UTC (00Z J / 12Z J / 00Z J+1 / 12Z J+1) en heure locale Paris été
    # (UTC+2), affichées sans préfixe « Échéance : ». Chacune apparaît dans les 2 sections.
    for cible in (
        "lun. 01/06 02 h",  # 00 UTC J
        "lun. 01/06 14 h",  # 12 UTC J
        "mar. 02/06 02 h",  # 00 UTC J+1
        "mar. 02/06 14 h",  # 12 UTC J+1
    ):
        assert html.count(cible) >= 2, f"Échéance absente ou non répétée : {cible!r}"
    # Le préfixe « Échéance : » a été retiré (la date en gras suffit).
    assert "Échéance :" not in html


def test_composer_html_sans_cartes_grille_nempeche_pas_le_rendu() -> None:
    """Sans cartes (None), le HTML reste valide et ne contient pas le bloc."""
    from apps.veille.email import composer_html

    html = composer_html(_ind(), [], datetime(2026, 5, 31, 7, 0), cartes_grille=None)
    assert "<html>" in html.lower() or "<html " in html.lower()
    assert "Situation synoptique" not in html


def test_composer_html_avec_vigilance_orages_jaune() -> None:
    """Une vigilance avec orages jaune doit produire le bloc tableau."""
    from apps.veille.email import composer_html

    html = composer_html(
        _ind(),
        [],
        datetime(2026, 5, 31, 7, 0),
        vigilance=_vigilance_jaune_orages(),
    )
    assert "Vigilance Météo-France" in html
    assert "Orages" in html
    assert "Jaune" in html


def test_composer_html_sans_vigilance_pas_de_bloc() -> None:
    """Sans vigilance (None), pas de bloc Vigilance dans le HTML."""
    from apps.veille.email import composer_html

    html = composer_html(_ind(), [], datetime(2026, 5, 31, 7, 0), vigilance=None)
    assert "Vigilance Météo-France" not in html


def test_composer_html_sans_alerte_section_exploitation_separee() -> None:
    """Sans alerte exploitation : section dédiée, pas de bandeau vert global.

    Le bandeau « Aucune alerte seuil franchi » trompait quand MF était en
    vigilance orages : on a désormais une section « Vigilance exploitation »
    distincte qui annonce séparément l'absence de seuil franchi.
    """
    from apps.veille.email import composer_html

    html = composer_html(
        _ind(),
        [],
        datetime(2026, 5, 31, 7, 0),
        vigilance=_vigilance_jaune_orages(),
    )
    # Vigilance exploitation 48 h retirée (2026-06-14) : la section n'existe plus.
    assert "Vigilance exploitation" not in html
    # La Vigilance MF d'État (orages) reste bien affichée.
    assert "Vigilance Météo-France" in html
    assert "Orages" in html


def test_composer_html_titres_vigilance_conserves_si_vide() -> None:
    """Sans alerte ET MF tout vert : les 2 titres <h3> restent affichés."""
    import pandas as pd

    from apps.veille.email import composer_html
    from meteo_socle.sources.dpvigilance import (
        PHENOMENES_NOMS,
        PHENOMENES_PERTINENTS,
        VigilanceDepartementDP,
        VigilancePhenomeneDP,
    )

    vigilance_verte = VigilanceDepartementDP(
        departement="35",
        update_time=pd.Timestamp("2026-05-31 16:00", tz="UTC"),
        fin_validite=pd.Timestamp("2026-06-01 04:00", tz="UTC"),
        phenomenes=[
            VigilancePhenomeneDP(code=pid, nom=PHENOMENES_NOMS[pid], niveau_max=1)
            for pid in PHENOMENES_PERTINENTS
        ],
    )
    html = composer_html(_ind(), [], datetime(2026, 5, 31, 7, 0), vigilance=vigilance_verte)
    # Le titre Vigilance MF d'État est rendu en <h3> même tout vert.
    assert ">Vigilance Météo-France</h3>" in html
    assert "Aucune vigilance en cours" in html
    # La Vigilance exploitation 48 h a été retirée (2026-06-14).
    assert "Vigilance exploitation" not in html


def test_bloc_seuils_guides_documente_chaque_guide_depuis_la_config() -> None:
    """Le pied « Seuils des guides » (après les sources) liste chaque seuil, lu config."""
    from apps.veille.semaine import bloc_seuils_guides

    exploitation = {
        "seuils_gel": {
            "purge_voiles_t_seuil_celsius": 4.0,
            "recolte_racines_t_seuil_celsius": 0.0,
        },
        "seuils_tunnel": {"fermeture_nuit_t_min_celsius": 3.0},
        "seuils_hydrique": {"deficit_mm": -10.0},
        "seuils_thermique": {"stress_t_max_celsius": 28.0, "stress_jours_min": 2},
        "seuils_maladie": {"nuit_douce_t_min_celsius": 15.0},
        "seuils_travail_sol": {
            "fenetre_seche_pluie_max_mm_par_jour": 1.0,
            "fenetre_seche_duree_min_jours": 3,
            "fenetre_pluvieuse_pluie_min_mm_par_jour": 5.0,
            "fenetre_pluvieuse_duree_min_jours": 2,
        },
    }
    html = bloc_seuils_guides(exploitation, horizon_court=4)
    assert "Seuils des guides de la semaine (4 j)" in html
    assert "purge + voiles si T° min ≤ 4 °C" in html
    assert "racines si T° min ≤ 0 °C" in html
    assert "fermer la nuit si T° min ≤ 3 °C" in html
    assert "nuits douces si T° min ≥ 15 °C" in html
    assert "Vigilance d'État" in html


def test_composer_html_sans_pied_48h_obsolete() -> None:
    """Le pied 48 h « Vigilance exploitation » a disparu (seuils portés par la semaine)."""
    from apps.veille.email import composer_html

    html = composer_html(_ind(), [], datetime(2026, 6, 1, 5, 30))
    assert "Vigilance exploitation (48" not in html
    assert "sur une plage de 6 h" not in html
