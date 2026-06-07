"""Bulletin eau mensuel — produit-mail léger (état de la ressource en eau).

Réutilise l'infra mail de la Veille (``apps.veille.sender``) et trois
sources socle (Hub'Eau piézo, VigiEau, Open-Meteo archive). Observation
uniquement : niveau de nappe (proxy régional), restrictions sécheresse en
vigueur, écart de pluie récent à la normale. Pas de prévision saisonnière.
"""
