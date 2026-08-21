"""Génère un jeu de données entièrement fictif pour développer sans extraction réelle.

Usage :
    python generer_donnees_test.py            # complète data/trs.db si vide
    python generer_donnees_test.py --reset    # repart d'une base vide

Tout est synthétique (ART-001, Famille A, Zone 1 / Machine 1...) : aucun nom
d'entreprise, de produit ou de procédé réel ne doit entrer dans ce dépôt.
Le jeu couvre les situations du CDC §9 : bascule de cadence 24 -> 30 ppm au
01/07/2026, données antérieures au début d'historique exploitable, arrêts qui
se chevauchent, arrêts absorbés, équipement retiré et équipement remplacé,
motifs doublons, anomalies volontaires, fichiers d'extraction piégés.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from core import arrets, cadences, db, elements, historisation, motifs

AUTEUR = "generateur"
CHEMIN_BASE = Path(__file__).parent / "data" / "trs.db"
DOSSIER_EXEMPLES = Path(__file__).parent / "data" / "exemples"

FAMILLES = [("FAM-A", "Famille A"), ("FAM-B", "Famille B"), ("FAM-C", "Famille C")]
ARTICLES = [(f"ART-{i:03d}", f"Article fictif {i}", FAMILLES[i % 3][0]) for i in range(1, 9)]

# Arborescence purement synthétique : 4 zones, 8 machines.
ARBRE = {
    "Zone 1": ["Machine 1", "Machine 2"],
    "Zone 2": ["Machine 3", "Machine 4", "Machine 5"],
    "Zone 3": ["Machine 6", "Machine 7"],
    "Zone 4": ["Machine 8"],
}

DEBUT_DONNEES = date(2026, 4, 1)       # antérieur au début d'historique exploitable
DEBUT_HISTORIQUE = date(2026, 6, 1)
FIN_DONNEES = date(2026, 8, 20)
BASCULE_CADENCE = date(2026, 7, 1)     # 24 ppm -> 30 ppm


def generer(conn, graine: int = 2026) -> None:
    alea = random.Random(graine)

    conn.execute(
        "INSERT INTO ligne (id, code, libelle, date_debut)"
        " VALUES (1, 'LIGNE-1', 'Ligne fictive 1', '2026-01-01')"
    )
    for code, libelle in FAMILLES:
        conn.execute("INSERT INTO famille (code, libelle) VALUES (?, ?)", (code, libelle))
    conn.commit()

    for code, libelle, famille_code in ARTICLES:
        conn.execute("INSERT INTO article (code, libelle) VALUES (?, ?)", (code, libelle))
        famille_id = conn.execute(
            "SELECT id FROM famille WHERE code = ?", (famille_code,)
        ).fetchone()[0]
        historisation.cloturer_et_inserer(
            conn, "article_famille", {"article_code": code}, {"famille_id": famille_id},
            "2026-01-01", "Rattachement initial fictif", AUTEUR,
        )
        cadences.changer_cadence(conn, code, 1, 24, "2026-04-01",
                                 "Cadence fictive initiale", AUTEUR)
        cadences.changer_cadence(conn, code, 1, 30, BASCULE_CADENCE,
                                 "Bascule de cadence fictive du 1er juillet", AUTEUR)

    # Un article change de famille en cours de période (deux modes de lecture, §4.1).
    famille_b = conn.execute("SELECT id FROM famille WHERE code = 'FAM-B'").fetchone()[0]
    historisation.cloturer_et_inserer(
        conn, "article_famille", {"article_code": "ART-001"}, {"famille_id": famille_b},
        "2026-08-01", "Réorganisation fictive du catalogue", AUTEUR,
    )

    # Calendrier : 5 j/7 à 840/570, un changement d'ouverture au 1er août (840 -> 960).
    for jour_semaine in range(5):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 840, "tr_min": 570}, "2026-01-01", "Calendrier fictif initial", AUTEUR,
        )
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 960, "tr_min": 690}, "2026-08-01",
            "Allongement fictif de l'ouverture", AUTEUR,
        )
    for jour_semaine in (5, 6):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 0, "tr_min": 0}, "2026-01-01", "Fermeture le week-end", AUTEUR,
        )
    # Trois fériés et une semaine d'arrêt annuel.
    for ferie, motif in (("2026-05-01", "Férié"), ("2026-05-08", "Férié"), ("2026-07-14", "Férié")):
        conn.execute(
            "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min, motif)"
            " VALUES (1, ?, 0, 0, ?)", (ferie, motif),
        )
    jour = date(2026, 8, 10)
    while jour <= date(2026, 8, 14):
        conn.execute(
            "INSERT INTO calendrier_exception (ligne_id, date, to_min, tr_min, motif)"
            " VALUES (1, ?, 0, 0, 'Arrêt annuel fictif')", (jour.isoformat(),),
        )
        jour += timedelta(days=1)

    historisation.cloturer_et_inserer(
        conn, "parametre_date", {"cle": "DATE_DEBUT_HISTORIQUE"},
        {"valeur": DEBUT_HISTORIQUE.isoformat()},
        "1900-01-01", "Début d'historique exploitable du jeu fictif", AUTEUR,
    )

    # Arborescence.
    ids_machines = []
    for zone, machines in ARBRE.items():
        numero_zone = zone.split()[-1]
        zone_id = elements.ajouter_element(
            conn, 1, None, f"ZONE-{numero_zone}", zone, "ZONE", "2026-01-01",
            commentaire="Arborescence fictive", auteur=AUTEUR,
        )
        for machine in machines:
            numero = machine.split()[-1]
            ids_machines.append(elements.ajouter_element(
                conn, 1, zone_id, f"MACH-{numero}", machine, "EQUIPEMENT", "2026-01-01",
                commentaire="Arborescence fictive", auteur=AUTEUR,
            ))

    # Un équipement retiré du service en cours de période, un équipement remplacé.
    elements.retirer_element(conn, ids_machines[6], "2026-07-20",
                             "Dépose fictive", AUTEUR)
    remplacee = elements.remplacer_element(
        conn, ids_machines[3], "MACH-4B", "Machine 4 nouvelle génération",
        "2026-07-10", "Remplacement fictif", AUTEUR,
    )
    machines_actives = [m for m in ids_machines if m not in (ids_machines[6], ids_machines[3])]
    machines_actives.append(remplacee)

    # Motifs propres aux équipements + deux doublons volontaires.
    motifs_equipement = []
    for element_id, (code, libelle, famille) in zip(machines_actives[:6], [
        ("BOURRAGE-M", "Bourrage", "MECANIQUE"),
        ("SONDE-TEMP", "Sonde de température défaillante", "ELECTRIQUE"),
        ("DEFAUT-SOUDURE", "Défaut de soudure", "PROCESS"),
        ("CAPTEUR-HS", "Capteur hors service", "ELECTRIQUE"),
        ("MANQUE-MATIERE", "Manque matière amont", "MATIERE"),
        ("DERIVE-POIDS", "Dérive de poids", "QUALITE"),
    ]):
        motifs_equipement.append(motifs.creer_motif(
            conn, code, libelle, "ARRET_PROPRE", "2026-04-01",
            "Motif fictif d'équipement", AUTEUR, famille=famille, element_id=element_id,
        ))
    # Doublons volontaires pour éprouver la détection et la fusion.
    motifs_equipement.append(motifs.creer_motif(
        conn, "BOURAGE-M", "Bourage", "ARRET_PROPRE", "2026-04-01",
        "Doublon volontaire (faute de frappe)", AUTEUR, element_id=machines_actives[0],
    ))
    motifs_equipement.append(motifs.creer_motif(
        conn, "BOURRAGE-TAPIS", "Bourrage tapis", "ARRET_PROPRE", "2026-04-01",
        "Doublon volontaire (variante)", AUTEUR, element_id=machines_actives[0],
    ))

    # Une reclassification de motif en cours de période (le passé ne bouge pas).
    chgt_serie = conn.execute(
        "SELECT id FROM motif_arret WHERE code = 'CHGT_SERIE'"
    ).fetchone()[0]
    motifs.reclasser_motif(conn, chgt_serie, "HORS_REQUIS", "2026-08-01",
                           "Reclassification fictive du changement de série", AUTEUR)

    panne = conn.execute("SELECT id FROM motif_arret WHERE code = 'PANNE'").fetchone()[0]
    pause = conn.execute("SELECT id FROM motif_arret WHERE code = 'PAUSE'").fetchone()[0]

    # Production et arrêts, jour par jour.
    jour = DEBUT_DONNEES
    compteur_of = 0
    while jour <= FIN_DONNEES:
        if jour.weekday() >= 5 or jour.isoformat() in (
            "2026-05-01", "2026-05-08", "2026-07-14"
        ) or date(2026, 8, 10) <= jour <= date(2026, 8, 14):
            jour += timedelta(days=1)
            continue

        cadence_du_jour = 24 if jour < BASCULE_CADENCE else 30
        tr_du_jour = 570 if jour < date(2026, 8, 1) else 690
        rendement = alea.uniform(0.62, 0.92)
        # qte_ensachee renseignée sur un mois seulement (juillet) : bascule niveau 3.
        qualite_mesuree = date(2026, 7, 1) <= jour <= date(2026, 7, 31)

        production_du_jour = cadence_du_jour * tr_du_jour * rendement
        nb_articles = alea.randint(2, 4)
        choix = alea.sample(ARTICLES, nb_articles)
        parts = [alea.uniform(0.5, 1.5) for _ in choix]
        for (code, _, _), part in zip(choix, parts):
            compteur_of += 1
            produite = round(production_du_jour * part / sum(parts))
            planifiee = round(produite * alea.uniform(0.95, 1.25))
            ensachee = round(produite * alea.uniform(1.0, 1.04)) if qualite_mesuree else None
            conn.execute(
                "INSERT INTO production (date, ligne_id, article_code, of_numero,"
                " qte_planifiee, qte_produite, qte_ensachee)"
                " VALUES (?, 1, ?, ?, ?, ?, ?)",
                (jour.isoformat(), code, f"OF-{compteur_of:05d}",
                 planifiee, produite, ensachee),
            )

        # Arrêts propres : 40 à 100 min par jour, répartis sur l'arborescence.
        minutes_restantes = alea.uniform(40, 100)
        heure = datetime.combine(jour, datetime.min.time()).replace(hour=6)
        while minutes_restantes > 5:
            duree = min(alea.uniform(8, 45), minutes_restantes)
            heure += timedelta(minutes=alea.uniform(20, 120))
            arrets.saisir_arret(
                conn, 1, jour,
                alea.choice([panne, *motifs_equipement]),
                debut=heure, fin=heure + timedelta(minutes=duree),
                element_id=alea.choice(machines_actives) if alea.random() > 0.1 else None,
                arrete_ligne=1,
            )
            # De temps en temps, un arrêt simultané qui chevauche partiellement.
            if alea.random() < 0.15:
                arrets.saisir_arret(
                    conn, 1, jour, alea.choice(motifs_equipement),
                    debut=heure + timedelta(minutes=duree / 2),
                    fin=heure + timedelta(minutes=duree / 2 + 10),
                    element_id=alea.choice(machines_actives), arrete_ligne=1,
                )
            # Et un arrêt absorbé par un tampon, sans effet sur la cascade.
            if alea.random() < 0.1:
                arrets.saisir_arret(
                    conn, 1, jour, alea.choice(motifs_equipement),
                    debut=heure + timedelta(minutes=duree + 15),
                    fin=heure + timedelta(minutes=duree + 27),
                    element_id=alea.choice(machines_actives), arrete_ligne=0,
                )
            minutes_restantes -= duree

        # Quelques arrêts hors requis déclarés : sans effet en MODE_TR = 'FIXE'.
        if alea.random() < 0.3:
            debut_pause = datetime.combine(jour, datetime.min.time()).replace(hour=12)
            arrets.saisir_arret(conn, 1, jour, pause,
                                debut=debut_pause, fin=debut_pause + timedelta(minutes=30),
                                arrete_ligne=1)
        jour += timedelta(days=1)

    # Anomalies volontaires (CDC §9) — pour éprouver rejets et alertes à l'import.
    conn.execute(
        "INSERT INTO article (code, libelle) VALUES ('ART-SANS-CADENCE', 'Article sans cadence')"
    )
    conn.execute(
        "INSERT INTO production (date, ligne_id, article_code, of_numero,"
        " qte_planifiee, qte_produite) VALUES ('2026-07-22', 1, 'ART-SANS-CADENCE',"
        " 'OF-ANOMALIE-1', 1000, 900)"
    )
    conn.commit()


def generer_fichiers_exemples() -> None:
    """Fichiers d'extraction fictifs : xlsx piégé, CSV Windows, trois extractions."""
    import openpyxl

    DOSSIER_EXEMPLES.mkdir(parents=True, exist_ok=True)

    # Classeur piégé : titre, ligne vide, nombres en texte, formules non évaluées,
    # feuille parasite (CDC §6.2).
    classeur = openpyxl.Workbook()
    feuille = classeur.active
    feuille.title = "Production"
    feuille.append(["Extraction fictive du 20/08/2026"])
    feuille.append([])
    feuille.append(["Date", "Article", "OF", "Quantite planifiee",
                    "Quantite produite", "Total calcule"])
    lignes = [
        ("17/08/2026", "ART-001", "OF-90001", "15 000", "13 200"),
        ("18/08/2026", "ART-002", "OF-90002", "10 000", "9 000,5"),
        ("19/08/2026", "ART-003", "OF-90003", "8 000", "7 450"),
    ]
    for numero, ligne in enumerate(lignes, start=4):
        feuille.append([*ligne, f"=E{numero}*2"])
    classeur.create_sheet("Parametres")
    classeur.save(DOSSIER_EXEMPLES / "extraction_piegee.xlsx")

    # CSV Windows français : cp1252, point-virgule, virgule décimale, insécables.
    contenu = (
        "Date;Article;OF;Quantite planifiee;Quantite produite\r\n"
        "17/08/2026;ART-001;OF-90001;15\xa0000;13\xa0200\r\n"
        "18/08/2026;ART-002;OF-90002;10\xa0000;9\xa0000,5\r\n"
        "19/08/2026;ART-004;OF-90004;-500;-100\r\n"          # anomalie volontaire
    )
    (DOSSIER_EXEMPLES / "extraction_windows.csv").write_bytes(contenu.encode("cp1252"))

    # Trois extractions : incrémentale, cumulative recouvrant une période déjà
    # importée, et corrigée de même période.
    def _xlsx(nom: str, lignes_donnees: list[tuple]) -> None:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["Date", "Article", "OF", "Quantite planifiee", "Quantite produite"])
        for ligne in lignes_donnees:
            ws.append(list(ligne))
        wb.save(DOSSIER_EXEMPLES / nom)

    _xlsx("extraction_incrementale.xlsx", [
        ("17/08/2026", "ART-001", "OF-90001", 15000, 13200),
        ("18/08/2026", "ART-002", "OF-90002", 10000, 9000),
    ])
    _xlsx("extraction_cumulative.xlsx", [
        ("17/08/2026", "ART-001", "OF-90001", 15000, 13200),
        ("18/08/2026", "ART-002", "OF-90002", 10000, 9000),
        ("19/08/2026", "ART-003", "OF-90003", 8000, 7450),
        ("20/08/2026", "ART-004", "OF-90005", 9000, 8100),
    ])
    _xlsx("extraction_corrigee.xlsx", [
        ("17/08/2026", "ART-001", "OF-90001", 15000, 13350),   # quantité corrigée
        ("18/08/2026", "ART-002", "OF-90002", 10000, 9000),
        ("19/08/2026", "ART-003", "OF-90003", 8000, 7450),
        ("20/08/2026", "ART-004", "OF-90005", 9000, 8100),
    ])


def principal() -> int:
    parseur = argparse.ArgumentParser(description=__doc__)
    parseur.add_argument("--reset", action="store_true",
                         help="supprime la base existante avant de générer")
    parseur.add_argument("--base", type=Path, default=CHEMIN_BASE,
                         help="chemin de la base à générer (défaut : data/trs.db)")
    options = parseur.parse_args()

    if options.reset and options.base.exists():
        options.base.unlink()
    if options.base.exists():
        conn = db.ouvrir_base(options.base)
        deja = conn.execute("SELECT COUNT(*) FROM production").fetchone()[0]
        if deja:
            print(f"La base {options.base} contient déjà {deja} lignes de production. "
                  "Utilisez --reset pour repartir de zéro.")
            conn.close()
            return 1
    else:
        conn = db.ouvrir_base(options.base)

    generer(conn)
    nb = conn.execute("SELECT COUNT(*) FROM production").fetchone()[0]
    conn.close()
    generer_fichiers_exemples()
    print(f"Base fictive générée : {options.base} ({nb} lignes de production).")
    print(f"Fichiers d'exemple : {DOSSIER_EXEMPLES}/")
    return 0


if __name__ == "__main__":
    sys.exit(principal())
