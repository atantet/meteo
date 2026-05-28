"""Helper retry/backoff partagé entre les sources Open-Meteo.

Open-Meteo applique des quotas par IP (free tier ≈ 5000 req/h, 600/min).
En CI, plusieurs builds rapprochés (chaque build climato = 30 requêtes
annuelles) peuvent saturer la fenêtre et déclencher un 429.

Politique : 4 tentatives max, backoff exponentiel base 5 s, respect du
header ``Retry-After`` si présent.
"""

from __future__ import annotations

import time

import requests

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
_MAX_TENTATIVES = 4
_BACKOFF_BASE_S = 5.0


def get_avec_retry(
    session: requests.Session,
    url: str,
    *,
    params: dict[str, str],
    timeout: float = 30,
) -> requests.Response:
    """GET avec retry/backoff exponentiel sur 429 et 5xx.

    Parameters
    ----------
    session :
        Session requests à utiliser (permet la réutilisation TCP).
    url :
        URL cible.
    params :
        Paramètres query string.
    timeout :
        Timeout par requête, en secondes.

    Returns
    -------
    requests.Response
        Réponse 2xx.

    Raises
    ------
    requests.HTTPError
        Si toutes les tentatives échouent, ou sur erreur non-retryable.
    """
    for tentative in range(1, _MAX_TENTATIVES + 1):
        response = session.get(url, params=params, timeout=timeout)
        if response.status_code not in _RETRY_STATUSES:
            response.raise_for_status()
            return response
        if tentative == _MAX_TENTATIVES:
            response.raise_for_status()
        retry_after = response.headers.get("Retry-After")
        attente = (
            float(retry_after)
            if retry_after and retry_after.isdigit()
            else _BACKOFF_BASE_S * (2 ** (tentative - 1))
        )
        time.sleep(attente)
    raise RuntimeError("retry loop exhausted")
