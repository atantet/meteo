"""Diagnostic : pourquoi le webservice MF (48 h) est injoignable depuis les runners.

But : trancher **IP vs token**, et au passage vérifier si la clé Données Publiques
perso (``METEOFRANCE_DP_BASIC``) ouvre — contre toute attente — le webservice mobile.

On exécute, depuis le runner GitHub (IP datacenter), une matrice d'appels et on
imprime pour chacun l'issue EXACTE (code HTTP, ou classe d'exception : timeout /
connexion reset / …). Rien n'est envoyé, rien n'est mis en cache.

Lecture du verdict :
- webservice avec token mobile → **403/401/429 (statut HTTP)** = blocage **token** ;
  **timeout/reset sans statut** = blocage **IP** (pare-feu qui droppe le datacenter).
- webservice avec clé DP (Bearer ou ?token=) → si 2xx, la clé perso marche (surprise) ;
  sinon le code dit pourquoi (401 = clé refusée, timeout = IP).
- contrôles (portail-api DP, host neutre) → situent le problème : si portail-api
  répond et webservice timeout depuis la MÊME IP au MÊME instant → IP ciblée sur le
  webservice ; si tout timeout → coupure réseau générale du runner.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# Bootstrap d'import : exécutable depuis n'importe quel cwd (cf. autres scripts).
REPO_ROOT = Path(__file__).resolve().parents[1]
for p in (REPO_ROOT, REPO_ROOT / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import requests  # noqa: E402
import yaml  # noqa: E402

from meteo_socle.sources.meteofrance_arpege import (  # noqa: E402
    ENV_BASIC,
    TOKEN_URL,
    _bearer,
)
from meteo_socle.sources.meteofrance_officiel import (  # noqa: E402
    DEFAULT_TOKEN,
    ENV_TOKEN,
    WEBSERVICE_URL,
)

CONFIG = REPO_ROOT / "config" / "veille.yaml"
_TIMEOUT = (10.0, 30.0)  # (connect, read), comme la prod


def _coords() -> tuple[float, float]:
    site = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))["site"]
    return site["latitude"], site["longitude"]


def _essai(label: str, fn) -> None:
    """Exécute un appel, imprime l'issue exacte (statut HTTP ou type d'exception)."""
    t0 = time.monotonic()
    try:
        resp = fn()
    except requests.RequestException as e:
        dt = time.monotonic() - t0
        # La CLASSE de l'exception est le signal clé : Timeout/ConnectionError sans
        # statut HTTP = blocage réseau/IP ; une HTTPError porterait un statut.
        print(f"  [{label}] ÉCHEC réseau en {dt:4.1f}s : {type(e).__name__}: {e}")
        return
    dt = time.monotonic() - t0
    taille = len(resp.content)
    apercu = ""
    if resp.status_code != 200:
        apercu = f" | corps: {resp.text[:160]!r}"
    print(f"  [{label}] HTTP {resp.status_code} en {dt:4.1f}s ({taille} o){apercu}")


def main() -> None:
    lat, lon = _coords()
    session = requests.Session()

    token_mobile = os.environ.get(ENV_TOKEN, DEFAULT_TOKEN)
    source_mobile = ENV_TOKEN if os.environ.get(ENV_TOKEN) else "défaut codé en dur"
    basic = os.environ.get(ENV_BASIC, "")

    print(f"Coords : {lat}, {lon}")
    print(f"Token mobile : {source_mobile}")
    print(f"Clé DP ({ENV_BASIC}) présente : {'oui' if basic else 'NON'}")
    print()

    # 1) webservice + token mobile public (le cas de prod actuel).
    print("== webservice.meteofrance.com (48 h) ==")
    _essai(
        "token mobile public (?token=)",
        lambda: session.get(
            WEBSERVICE_URL,
            params={"lat": f"{lat}", "lon": f"{lon}", "lang": "fr", "token": token_mobile},
            timeout=_TIMEOUT,
        ),
    )

    # 2-3) webservice + clé DP perso, deux variantes d'injection.
    bearer = ""
    if basic:
        try:
            bearer = _bearer(session, basic)
            print("  (échange OAuth DP → bearer : OK)")
        except requests.RequestException as e:
            print(f"  (échange OAuth DP → bearer : ÉCHEC {type(e).__name__}: {e})")
    if bearer:
        _essai(
            "clé DP en Authorization: Bearer",
            lambda: session.get(
                WEBSERVICE_URL,
                params={"lat": f"{lat}", "lon": f"{lon}", "lang": "fr"},
                headers={"Authorization": f"Bearer {bearer}"},
                timeout=_TIMEOUT,
            ),
        )
        _essai(
            "clé DP en ?token= (JWT)",
            lambda: session.get(
                WEBSERVICE_URL,
                params={"lat": f"{lat}", "lon": f"{lon}", "lang": "fr", "token": bearer},
                timeout=_TIMEOUT,
            ),
        )
    else:
        print("  (pas de clé DP → variantes Bearer/?token= sautées)")

    # 4) Contrôle : portail-api DP (même réseau, autre hôte MF). Doit répondre.
    print("\n== Contrôles (situer le blocage) ==")
    _essai(
        "portail-api.meteofrance.fr (token endpoint, HEAD)",
        lambda: session.head(TOKEN_URL, timeout=_TIMEOUT),
    )
    # 5) Contrôle : host neutre. Confirme que l'egress runner marche en général.
    _essai(
        "host neutre (example.com)",
        lambda: session.get("https://example.com", timeout=_TIMEOUT),
    )


if __name__ == "__main__":
    main()
