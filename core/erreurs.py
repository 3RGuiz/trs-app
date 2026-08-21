"""Erreurs métier de l'application.

Toutes les erreurs destinées à l'utilisateur héritent d'ErreurMetier et portent un
message en français, orienté utilisateur. Aucune stack trace brute ne doit être
affichée à l'écran : les pages interceptent ErreurMetier et affichent son message.
"""


class ErreurMetier(Exception):
    """Erreur porteuse d'un message compréhensible par un utilisateur non développeur."""


class ChevauchementPeriode(ErreurMetier):
    """Deux périodes d'un même référentiel se recouvrent."""


class CommentaireObligatoire(ErreurMetier):
    """Une modification de référentiel a été tentée sans justification écrite."""


class CadenceIntrouvable(ErreurMetier):
    """Aucune cadence en vigueur pour un article à une date donnée."""


class SuppressionInterdite(ErreurMetier):
    """Suppression physique refusée : l'objet porte des données ou des descendants."""


class MotifInterdit(ErreurMetier):
    """Motif d'arrêt refusé (libellé évoquant une sous-cadence : double comptage garanti)."""


class ImportInvalide(ErreurMetier):
    """Fichier d'import illisible, mal mappé ou incohérent."""


class ValeurNonConvertible(ImportInvalide):
    """Une valeur numérique ou une date du fichier importé résiste à la conversion."""


class ConfirmationRequise(ErreurMetier):
    """L'opération est bloquée en attente d'une confirmation explicite de l'utilisateur."""


class SauvegardeEchouee(ErreurMetier):
    """La sauvegarde de la base n'a pas pu être écrite ou vérifiée."""
