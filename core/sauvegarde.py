"""Sauvegarde de la base par VACUUM INTO (CDC §13.7).

La base de travail ne vit JAMAIS dans un dossier synchronisé : seules des copies
propres, produites par VACUUM INTO, partent vers la destination. Une sauvegarde
qui échoue en silence est pire que pas de sauvegarde : chaque tentative est
journalisée, le fichier produit est vérifié après écriture, et la date de la
dernière réussite est consultable.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from pathlib import Path

from core.erreurs import SauvegardeEchouee

NOM_JOURNAL = "sauvegarde.log"


def _cible_disponible(destination_dir: Path, prefixe: str, jour: date) -> Path:
    """Chemin de sauvegarde du jour. Deuxième sauvegarde de la journée : suffixe
    numérique — l'erreur « output file already exists » ne remonte jamais
    à l'utilisateur."""
    base = destination_dir / f"{prefixe}_{jour:%Y-%m-%d}.db"
    if not base.exists():
        return base
    numero = 2
    while (destination_dir / f"{prefixe}_{jour:%Y-%m-%d}_{numero}.db").exists():
        numero += 1
    return destination_dir / f"{prefixe}_{jour:%Y-%m-%d}_{numero}.db"


def _journaliser(journal: Path, resultat: str, cible: Path, taille: int | None) -> None:
    ligne = (
        f"{datetime.now().isoformat(sep=' ', timespec='seconds')}\t{resultat}\t"
        f"{cible}\t{taille if taille is not None else '-'}\n"
    )
    with open(journal, "a", encoding="utf-8") as fichier:
        fichier.write(ligne)


def _verifier(cible: Path, nb_lignes_source: int) -> None:
    """Le fichier produit existe, n'est pas vide, s'ouvre en SQLite, et contient
    le même nombre de lignes de production que la source."""
    if not cible.exists() or cible.stat().st_size == 0:
        raise SauvegardeEchouee(
            f"La sauvegarde {cible.name} est absente ou vide après écriture."
        )
    controle = sqlite3.connect(str(cible))
    try:
        etat = controle.execute("PRAGMA quick_check").fetchone()[0]
        if etat != "ok":
            raise SauvegardeEchouee(
                f"La sauvegarde {cible.name} est corrompue (quick_check : {etat})."
            )
        nb_lignes = controle.execute("SELECT COUNT(*) FROM production").fetchone()[0]
        if nb_lignes != nb_lignes_source:
            raise SauvegardeEchouee(
                f"La sauvegarde {cible.name} contient {nb_lignes} ligne(s) de production "
                f"au lieu de {nb_lignes_source} : copie incohérente."
            )
    finally:
        controle.close()


def sauvegarder(
    chemin_db: Path | str,
    destination_dir: Path | str,
    prefixe: str = "trs",
    journal: Path | str | None = None,
) -> Path:
    """Écrit une copie cohérente et compactée de la base dans destination_dir.

    Utilise une connexion dédiée : VACUUM INTO échoue depuis une transaction
    ouverte, et la copie doit être cohérente même si la base est utilisée.
    Retourne le chemin du fichier créé ; lève SauvegardeEchouee sinon.
    """
    chemin_db = Path(chemin_db)
    destination_dir = Path(destination_dir)
    journal = Path(journal) if journal else destination_dir / NOM_JOURNAL
    destination_dir.mkdir(parents=True, exist_ok=True)
    cible = _cible_disponible(destination_dir, prefixe, date.today())

    connexion = sqlite3.connect(str(chemin_db))
    try:
        nb_lignes_source = connexion.execute("SELECT COUNT(*) FROM production").fetchone()[0]
        connexion.execute("VACUUM INTO ?", (str(cible),))
        _verifier(cible, nb_lignes_source)
    except sqlite3.Error as erreur:
        _journaliser(journal, "ECHEC", cible, None)
        raise SauvegardeEchouee(
            f"La sauvegarde vers {cible} a échoué : {erreur}. "
            "Vérifiez que le dossier de destination est accessible."
        ) from erreur
    except SauvegardeEchouee:
        _journaliser(journal, "ECHEC", cible, None)
        raise
    finally:
        connexion.close()

    _journaliser(journal, "REUSSITE", cible, cible.stat().st_size)
    return cible


def derniere_reussite(journal: Path | str) -> datetime | None:
    """Horodatage de la dernière sauvegarde réussie, ou None — à afficher sur
    l'écran Paramètres, avec alerte en accueil au-delà de 3 jours."""
    journal = Path(journal)
    if not journal.exists():
        return None
    derniere = None
    for ligne in journal.read_text(encoding="utf-8").splitlines():
        morceaux = ligne.split("\t")
        if len(morceaux) >= 2 and morceaux[1] == "REUSSITE":
            derniere = datetime.fromisoformat(morceaux[0])
    return derniere


def rotation(
    destination_dir: Path | str,
    prefixe: str = "trs",
    retention_jours: int = 30,
    retention_mois: int = 12,
) -> list[Path]:
    """Purge les sauvegardes au-delà de la rétention.

    Conserve les `retention_jours` sauvegardes quotidiennes les plus récentes,
    et les copies mensuelles (celles du 1er du mois) sur `retention_mois` mois —
    jamais purgées par la rétention quotidienne. Retourne les fichiers supprimés.
    """
    destination_dir = Path(destination_dir)
    fichiers = sorted(destination_dir.glob(f"{prefixe}_????-??-??*.db"))

    def jour_de(fichier: Path) -> date | None:
        try:
            return date.fromisoformat(fichier.stem.split("_")[1])
        except (IndexError, ValueError):
            return None

    dates = sorted({jour_de(f) for f in fichiers if jour_de(f)}, reverse=True)
    jours_gardes = set(dates[:retention_jours])
    mois_gardes = sorted({(d.year, d.month) for d in dates if d.day == 1}, reverse=True)
    mois_gardes = set(mois_gardes[:retention_mois])

    supprimes = []
    for fichier in fichiers:
        jour = jour_de(fichier)
        if jour is None:
            continue
        est_mensuelle = jour.day == 1 and (jour.year, jour.month) in mois_gardes
        if jour not in jours_gardes and not est_mensuelle:
            fichier.unlink()
            supprimes.append(fichier)
    return supprimes
