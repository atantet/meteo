"""Helper retry/backoff partagé entre les sources HTTP (Open-Meteo, MF).

Open-Meteo applique des quotas par IP (free tier ≈ 5000 req/h, 600/min).
En CI, plusieurs builds rapprochés (chaque build climato = 30 requêtes
annuelles) peuvent saturer la fenêtre et déclencher un 429.

Le backend officiel MF (``webservice.meteofrance.com``, App 1 Veille) est lui
**injoignable par intermittence** depuis les runners CI (datacenter) : la
connexion *time out* sans jamais renvoyer de statut HTTP. On réessaie donc aussi
sur les erreurs **réseau** (connexion/timeout), pas seulement sur les codes HTTP.

Politique : 4 tentatives max, backoff exponentiel base 5 s, respect du
header ``Retry-After`` si présent ; retry sur 429/5xx **et** sur
``ConnectionError``/``Timeout``.
"""

from __future__ import annotations

import time

import requests

_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
# Erreurs réseau transitoires (connexion refusée/coupée, lecture/connexion qui
# time out). ``Timeout`` couvre ``ConnectTimeout`` et ``ReadTimeout``.
_RETRY_EXCEPTIONS = (requests.ConnectionError, requests.Timeout)
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
        Si toutes les tentatives échouent sur un statut retryable, ou sur
        erreur HTTP non-retryable.
    requests.ConnectionError or requests.Timeout
        Si toutes les tentatives échouent sur une erreur réseau.
    """
    for tentative in range(1, _MAX_TENTATIVES + 1):
        try:
            response = session.get(url, params=params, timeout=timeout)
        except _RETRY_EXCEPTIONS:
            # Erreur réseau (ex. webservice MF injoignable depuis le runner) :
            # on réessaie, sauf si c'était la dernière tentative.
            if tentative == _MAX_TENTATIVES:
                raise
            time.sleep(_BACKOFF_BASE_S * (2 ** (tentative - 1)))
            continue
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
