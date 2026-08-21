"""Import des extractions ERP (CDC §6).

Principes non négociables :

- rien ne s'écrit sans aperçu des différences, et l'aperçu annonce exactement
  ce que l'écriture fera ;
- une sauvegarde automatique est prise avant chaque import ; « annuler le
  dernier import » restaure cette sauvegarde, jamais un upsert inversé ;
- l'import est idempotent : réimporter le même fichier ne double rien ;
- en mode remplacement, seule une fenêtre de rafraîchissement est réellement
  remplacée, et une suppression massive est bloquée en attente de confirmation.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from core import conversion, historisation, temps
from core.db import iso
from core.erreurs import ConfirmationRequise, ImportInvalide

CHAMPS_CIBLES = ("date", "article_code", "of_numero",
                 "qte_planifiee", "qte_produite", "qte_ensachee")
CHAMPS_OBLIGATOIRES = ("date", "article_code", "qte_produite")
FENETRE_RAFRAICHISSEMENT_JOURS = 90
SEUIL_SUPPRESSION = 0.10
RETENTION_AVANT_IMPORT = 5


# ---------------------------------------------------------------- lecture des fichiers

def calculer_empreinte(chemin: Path | str) -> str:
    """Empreinte du contenu du fichier — détecte un réimport à l'identique."""
    return hashlib.sha256(Path(chemin).read_bytes()).hexdigest()


def detecter_entete(df: pd.DataFrame) -> int:
    """Première ligne dont toutes les cellules sont non vides et textuelles.

    Les exports ERP portent souvent un titre, une date d'édition, une ligne vide
    avant le tableau : une lecture naïve produit des colonnes « Unnamed ».
    """
    for numero, (_, ligne) in enumerate(df.iterrows()):
        valeurs = list(ligne)
        if valeurs and all(
            isinstance(v, str) and v.strip() != "" for v in valeurs
        ):
            return numero
    raise ImportInvalide(
        "Impossible de trouver la ligne d'en-tête du tableau : aucune ligne ne "
        "contient un libellé texte dans chaque colonne. Vérifiez le fichier, ou "
        "indiquez la ligne d'en-tête dans le profil d'import."
    )


def _lire_xlsx(chemin: Path, profil: dict) -> pd.DataFrame:
    lecture = {"sheet_name": profil.get("feuille", 0), "header": None, "dtype": object}
    try:
        brut = pd.read_excel(chemin, engine="calamine", **lecture)
    except ImportError:
        brut = pd.read_excel(chemin, engine="openpyxl", **lecture)
    brut = brut.dropna(axis=1, how="all")
    entete = profil.get("entete_ligne")
    if entete is None:
        entete = detecter_entete(brut)
        profil["entete_ligne"] = entete
    colonnes = [str(v).strip() for v in brut.iloc[entete]]
    donnees = brut.iloc[entete + 1:].copy()
    donnees.columns = colonnes
    return donnees.dropna(how="all").reset_index(drop=True)


def _lire_csv(chemin: Path, profil: dict) -> pd.DataFrame:
    encodage = profil.get("encodage")
    contenu = None
    for essai in ([encodage] if encodage else ["utf-8-sig", "cp1252"]):
        try:
            contenu = chemin.read_text(encoding=essai)
            profil["encodage"] = essai
            break
        except UnicodeDecodeError:
            continue
    if contenu is None:
        raise ImportInvalide(
            f"Impossible de décoder le fichier {chemin.name} : encodage non reconnu "
            "(utf-8 et cp1252 essayés)."
        )
    separateur = profil.get("separateur")
    if separateur is None:
        premiere_ligne = contenu.splitlines()[0] if contenu.splitlines() else ""
        separateur = ";" if premiere_ligne.count(";") >= premiere_ligne.count(",") else ","
        profil["separateur"] = separateur
    from io import StringIO
    return pd.read_csv(StringIO(contenu), sep=separateur, dtype=str)


def lire_fichier(chemin: Path | str, profil: dict | None = None) -> tuple[pd.DataFrame, dict]:
    """Lit un fichier ERP (.xlsx ou .csv) en texte brut, sans rien convertir.

    Le profil (feuille, ligne d'en-tête, encodage, séparateur) est enrichi au
    passage pour être mémorisé et réutilisé au prochain import.
    """
    chemin = Path(chemin)
    profil = dict(profil or {})
    if not chemin.exists():
        raise ImportInvalide(f"Le fichier {chemin} n'existe pas.")
    if chemin.suffix.lower() in (".xlsx", ".xls"):
        return _lire_xlsx(chemin, profil), profil
    if chemin.suffix.lower() == ".csv":
        return _lire_csv(chemin, profil), profil
    raise ImportInvalide(
        f"Format non pris en charge : {chemin.suffix}. Formats acceptés : .xlsx, .csv."
    )


# ---------------------------------------------------------------- normalisation

def normaliser(df_brut: pd.DataFrame, mapping: dict, profil: dict | None = None) -> pd.DataFrame:
    """Applique le mapping de colonnes et convertit les types, avec assertion.

    mapping : {champ cible -> nom de colonne du fichier}. Champs obligatoires :
    date, article_code, qte_produite. Une colonne mappée entièrement vide arrête
    l'import (formules non évaluées, colonne déplacée...), plutôt que d'importer
    des zéros.
    """
    profil = profil or {}
    inconnus = set(mapping) - set(CHAMPS_CIBLES)
    if inconnus:
        raise ImportInvalide(f"Champs cibles inconnus dans le mapping : {sorted(inconnus)}.")
    manquants = [c for c in CHAMPS_OBLIGATOIRES if c not in mapping]
    if manquants:
        raise ImportInvalide(
            f"Le mapping doit couvrir les champs obligatoires : {', '.join(manquants)}."
        )
    absentes = [c for c in mapping.values() if c not in df_brut.columns]
    if absentes:
        raise ImportInvalide(
            f"Colonnes absentes du fichier : {', '.join(absentes)}. "
            f"Colonnes disponibles : {', '.join(map(str, df_brut.columns))}."
        )

    if len(df_brut):
        for champ, colonne in mapping.items():
            serie = df_brut[colonne]
            if serie.isna().all() or (serie.astype(str).str.strip() == "").all():
                raise ImportInvalide(
                    f"La colonne « {colonne} » est entièrement vide. Si elle contient "
                    "des formules, le fichier n'a peut-être jamais été ouvert dans "
                    "Excel : ouvrez-le une fois, réenregistrez-le, puis réimportez."
                )

    resultat = pd.DataFrame()
    resultat["date"] = conversion.convertir_colonne_date(
        df_brut[mapping["date"]], mapping["date"], profil.get("format_date")
    )
    resultat["article_code"] = df_brut[mapping["article_code"]].astype(str).str.strip()
    if "of_numero" in mapping:
        resultat["of_numero"] = (
            df_brut[mapping["of_numero"]].fillna("").astype(str).str.strip()
        )
    else:
        # La clé naturelle utilise '' plutôt que NULL : SQLite considère deux NULL
        # comme distincts, ce qui casserait l'idempotence de l'import.
        resultat["of_numero"] = ""
    for champ in ("qte_planifiee", "qte_produite", "qte_ensachee"):
        if champ in mapping:
            resultat[champ] = conversion.convertir_colonne_nombre(
                df_brut[mapping[champ]], mapping[champ]
            )
        else:
            resultat[champ] = None
    return resultat


# ---------------------------------------------------------------- validation

def valider(conn: sqlite3.Connection, df: pd.DataFrame, ligne_id: int) -> dict:
    """Sépare lignes valides et rejets, et rassemble les avertissements du rapport.

    Les lignes sans cadence applicable sont importées (les faits ne dépendent pas
    du référentiel) mais listées : elles resteront exclues des calculs de temps
    tant qu'aucune cadence ne les couvre.
    """
    lignes_valides, rejets = [], []
    for _, ligne in df.iterrows():
        motif_rejet = None
        if ligne["date"] is None or pd.isna(ligne["date"]):
            motif_rejet = "date absente ou illisible"
        elif not ligne["article_code"] or ligne["article_code"].lower() in ("nan", "none"):
            motif_rejet = "code article absent"
        elif ligne["qte_produite"] is None or pd.isna(ligne["qte_produite"]):
            motif_rejet = "quantité produite absente"
        elif ligne["qte_produite"] < 0:
            motif_rejet = "quantité produite négative"
        elif (
            ligne["qte_ensachee"] is not None and not pd.isna(ligne["qte_ensachee"])
            and ligne["qte_produite"] > ligne["qte_ensachee"]
        ):
            motif_rejet = (
                "quantité produite supérieure au compteur d'ensacheuse "
                "(décalage d'en-cours ou compteurs mal rapprochés)"
            )
        if motif_rejet:
            rejets.append({"ligne": ligne.to_dict(), "motif": motif_rejet})
        else:
            lignes_valides.append(ligne)

    valides = pd.DataFrame(lignes_valides, columns=df.columns)

    articles_inconnus = []
    sans_cadence = []
    sans_planifie = 0
    if len(valides):
        connus = {a[0] for a in conn.execute("SELECT code FROM article")}
        articles_inconnus = sorted(set(valides["article_code"]) - connus)
        for _, ligne in valides.iterrows():
            cadence = historisation.resoudre(
                conn, "cadence",
                {"article_code": ligne["article_code"], "ligne_id": ligne_id},
                ligne["date"],
            )
            if cadence is None:
                sans_cadence.append((ligne["article_code"], iso(ligne["date"])))
        sans_planifie = int(valides["qte_planifiee"].isna().sum())

    return {
        "valides": valides,
        "rejets": rejets,
        "articles_inconnus": articles_inconnus,
        "sans_cadence": sorted(set(sans_cadence)),
        "sans_quantite_planifiee": sans_planifie,
    }


def _jours_sans_calendrier(conn, ligne_id: int, debut: date, fin: date) -> list[str]:
    """Jours de la période couverte sans aucune entrée au calendrier — sinon
    To = 0 et les indicateurs de ces jours seront muets sans explication."""
    concernes = []
    jour = debut
    while jour <= fin:
        exception = conn.execute(
            "SELECT 1 FROM calendrier_exception WHERE ligne_id = ? AND date = ?",
            (ligne_id, jour.isoformat()),
        ).fetchone()
        type_jour = historisation.resoudre(
            conn, "calendrier_type",
            {"ligne_id": ligne_id, "jour_semaine": jour.weekday()}, jour,
        )
        if exception is None and type_jour is None:
            concernes.append(jour.isoformat())
        jour += timedelta(days=1)
    return concernes


# ---------------------------------------------------------------- aperçu et écriture

def _cle(ligne) -> tuple:
    return (iso(ligne["date"]), ligne["article_code"], ligne["of_numero"])


def _existant(conn, ligne_id: int, debut: str, fin: str) -> dict[tuple, dict]:
    lignes = conn.execute(
        "SELECT * FROM production WHERE ligne_id = ? AND date BETWEEN ? AND ?",
        (ligne_id, debut, fin),
    ).fetchall()
    return {(l["date"], l["article_code"], l["of_numero"] or ""): dict(l) for l in lignes}


def _classer(conn, valides: pd.DataFrame, ligne_id: int, mode: str,
             fenetre_jours: int | None) -> dict:
    """Classement commun à l'aperçu et à l'écriture : c'est ce qui garantit que
    l'aperçu annonce exactement les compteurs constatés après écriture."""
    if not len(valides):
        return {"periode_debut": None, "periode_fin": None, "ajouts": [], "maj": [],
                "inchangees": [], "suppressions": [], "hors_fenetre": 0}

    periode_debut = min(valides["date"])
    periode_fin = max(valides["date"])

    retenues = valides
    hors_fenetre = 0
    debut_effectif = periode_debut
    if mode == "REMPLACEMENT_PERIODE" and fenetre_jours is not None:
        # Seuls les N derniers jours sont réellement remplacés : un export
        # cumulatif tronqué ne peut pas effacer des années de données.
        limite = periode_fin - timedelta(days=fenetre_jours - 1)
        if periode_debut < limite:
            dans_fenetre = valides["date"] >= limite
            hors_fenetre = int((~dans_fenetre).sum())
            retenues = valides[dans_fenetre]
            debut_effectif = limite

    existant = _existant(conn, ligne_id, iso(debut_effectif), iso(periode_fin))
    ajouts, maj, inchangees = [], [], []
    cles_fichier = set()
    for _, ligne in retenues.iterrows():
        cle = _cle(ligne)
        cles_fichier.add(cle)
        actuel = existant.get(cle)
        if actuel is None:
            ajouts.append(ligne)
            continue
        differe = any(
            _different(actuel[champ], ligne[champ])
            for champ in ("qte_planifiee", "qte_produite", "qte_ensachee")
        )
        (maj if differe else inchangees).append(ligne)

    suppressions = []
    if mode in ("REMPLACEMENT_PERIODE", "REIMPORT_COMPLET"):
        suppressions = [
            valeur for cle, valeur in existant.items() if cle not in cles_fichier
        ]

    return {
        "periode_debut": iso(periode_debut), "periode_fin": iso(periode_fin),
        "periode_remplacee_debut": iso(debut_effectif),
        "ajouts": ajouts, "maj": maj, "inchangees": inchangees,
        "suppressions": suppressions, "hors_fenetre": hors_fenetre,
        "nb_existants_periode": len(existant),
    }


def _different(a, b) -> bool:
    a_vide = a is None or (isinstance(a, float) and pd.isna(a))
    b_vide = b is None or (isinstance(b, float) and pd.isna(b))
    if a_vide and b_vide:
        return False
    if a_vide != b_vide:
        return True
    return float(a) != float(b)


def apercu_differences(
    conn: sqlite3.Connection,
    df: pd.DataFrame,
    ligne_id: int,
    mode: str = "UPSERT",
    fenetre_jours: int | None = FENETRE_RAFRAICHISSEMENT_JOURS,
    empreinte: str | None = None,
) -> dict:
    """Aperçu des différences AVANT écriture — rien ne s'écrit sans lui."""
    validation = valider(conn, df, ligne_id)
    classement = _classer(conn, validation["valides"], ligne_id, mode, fenetre_jours)
    deja_importe = None
    if empreinte:
        connu = conn.execute(
            "SELECT date_import FROM import_log WHERE empreinte = ? ORDER BY id DESC",
            (empreinte,),
        ).fetchone()
        deja_importe = connu["date_import"] if connu else None
    return {
        "periode_debut": classement["periode_debut"],
        "periode_fin": classement["periode_fin"],
        "nb_lues": int(len(df)),
        "nb_ajouts": len(classement["ajouts"]),
        "nb_maj": len(classement["maj"]),
        "nb_inchangees": len(classement["inchangees"]),
        "nb_suppressions": len(classement["suppressions"]),
        "nb_rejets": len(validation["rejets"]),
        "nb_hors_fenetre": classement["hors_fenetre"],
        "rejets": validation["rejets"],
        "articles_inconnus": validation["articles_inconnus"],
        "sans_cadence": validation["sans_cadence"],
        "deja_importe": deja_importe,
    }


def importer_production(
    conn: sqlite3.Connection,
    chemin_db: Path | str,
    df: pd.DataFrame,
    ligne_id: int,
    mode: str = "UPSERT",
    fichier: str = "extraction",
    empreinte: str | None = None,
    fenetre_jours: int | None = FENETRE_RAFRAICHISSEMENT_JOURS,
    confirmer_suppressions: bool = False,
    confirmer_reimport: bool = False,
    dossier_sauvegarde: Path | str | None = None,
) -> dict:
    """Écrit les données de production en base, après sauvegarde automatique.

    df est un DataFrame normalisé (sorti de normaliser()). Retourne le rapport
    d'import, également stocké dans import_log.rapport.
    """
    from core import sauvegarde as sauvegarde_module

    if mode not in ("UPSERT", "REMPLACEMENT_PERIODE", "REIMPORT_COMPLET"):
        raise ImportInvalide(f"Mode d'écriture inconnu : {mode}.")
    if mode == "REIMPORT_COMPLET":
        fenetre_jours = None   # réservé au chargement initial et aux reconstructions

    if empreinte:
        connu = conn.execute(
            "SELECT date_import FROM import_log WHERE empreinte = ? ORDER BY id DESC",
            (empreinte,),
        ).fetchone()
        if connu and not confirmer_reimport:
            raise ConfirmationRequise(
                f"Ce fichier a déjà été importé le {connu['date_import']}. "
                "Le réimporter ne changera rien. Continuer quand même ?"
            )

    validation = valider(conn, df, ligne_id)
    classement = _classer(conn, validation["valides"], ligne_id, mode, fenetre_jours)

    # Seuil d'alerte : un export incomplet se reconnaît toujours à ses suppressions.
    nb_existants = classement.get("nb_existants_periode", 0)
    if (
        classement["suppressions"]
        and nb_existants
        and len(classement["suppressions"]) / nb_existants > SEUIL_SUPPRESSION
        and not confirmer_suppressions
    ):
        raise ConfirmationRequise(
            f"Cet import supprimerait {len(classement['suppressions'])} ligne(s) sur les "
            f"{nb_existants} existantes de la période — plus de "
            f"{SEUIL_SUPPRESSION:.0%}. Un export incomplet ou tronqué produit "
            "exactement ce symptôme. Confirmez explicitement pour continuer."
        )

    # Sauvegarde avant toute écriture — c'est elle qui rend l'annulation fiable.
    chemin_db = Path(chemin_db)
    dossier_sauvegarde = (
        Path(dossier_sauvegarde) if dossier_sauvegarde
        else chemin_db.parent / "avant_import"
    )
    conn.commit()
    chemin_sauvegarde = sauvegarde_module.sauvegarder(
        chemin_db, dossier_sauvegarde, prefixe="avant_import"
    )
    _purger_avant_import(dossier_sauvegarde)

    try:
        # Articles inconnus : créés en famille « À classer », signalés au rapport.
        for code in validation["articles_inconnus"]:
            _creer_article_a_classer(conn, code, classement["periode_debut"])

        cur = conn.execute(
            "INSERT INTO import_log (fichier, empreinte, type, mode_ecriture,"
            " periode_debut, periode_fin, nb_ajouts, nb_maj, nb_suppressions,"
            " nb_rejets, sauvegarde) VALUES (?, ?, 'PRODUCTION', ?, ?, ?, ?, ?, ?, ?, ?)",
            (fichier, empreinte or "", mode,
             classement["periode_debut"], classement["periode_fin"],
             len(classement["ajouts"]), len(classement["maj"]),
             len(classement["suppressions"]), len(validation["rejets"]),
             str(chemin_sauvegarde)),
        )
        import_id = cur.lastrowid

        for supprimee in classement["suppressions"]:
            conn.execute("DELETE FROM production WHERE id = ?", (supprimee["id"],))
        for ligne in [*classement["ajouts"], *classement["maj"], *classement["inchangees"]]:
            conn.execute(
                "INSERT INTO production (date, ligne_id, article_code, of_numero,"
                " qte_planifiee, qte_produite, qte_ensachee, import_id)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(date, ligne_id, article_code, of_numero) DO UPDATE SET"
                " qte_planifiee = excluded.qte_planifiee,"
                " qte_produite = excluded.qte_produite,"
                " qte_ensachee = excluded.qte_ensachee,"
                " import_id = excluded.import_id",
                (iso(ligne["date"]), ligne_id, ligne["article_code"], ligne["of_numero"],
                 _ou_none(ligne["qte_planifiee"]), float(ligne["qte_produite"]),
                 _ou_none(ligne["qte_ensachee"]), import_id),
            )

        rapport = _rapport(conn, ligne_id, validation, classement, mode)
        conn.execute(
            "UPDATE import_log SET rapport = ? WHERE id = ?",
            (json.dumps(rapport, ensure_ascii=False, default=str), import_id),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return rapport


def _ou_none(valeur):
    if valeur is None or (isinstance(valeur, float) and pd.isna(valeur)):
        return None
    return float(valeur)


def _creer_article_a_classer(conn, code: str, date_debut: str) -> None:
    famille = conn.execute("SELECT id FROM famille WHERE code = 'A-CLASSER'").fetchone()
    if famille is None:
        cur = conn.execute(
            "INSERT INTO famille (code, libelle) VALUES ('A-CLASSER', 'À classer')"
        )
        famille_id = cur.lastrowid
    else:
        famille_id = famille["id"]
    conn.execute(
        "INSERT INTO article (code, libelle) VALUES (?, ?)", (code, code)
    )
    conn.execute(
        "INSERT INTO article_famille (article_code, famille_id, date_debut)"
        " VALUES (?, ?, ?)",
        (code, famille_id, date_debut),
    )


def _rapport(conn, ligne_id, validation, classement, mode) -> dict:
    anomalies = []
    for _, ligne in validation["valides"].iterrows():
        cadence = historisation.resoudre(
            conn, "cadence",
            {"article_code": ligne["article_code"], "ligne_id": ligne_id}, ligne["date"],
        )
        if cadence is not None:
            _, tr_min = temps.calendrier_du_jour(conn, ligne_id, ligne["date"])
            produisible = cadence["valeur_ppm"] * tr_min
            if tr_min and ligne["qte_produite"] > produisible:
                anomalies.append(
                    f"{iso(ligne['date'])} {ligne['article_code']} : quantité produite "
                    f"({ligne['qte_produite']:.0f}) supérieure à la quantité produisible "
                    f"sur Tr ({produisible:.0f}) — cadence sous-évaluée ou calendrier faux."
                )
    jours_sans_calendrier = []
    if classement["periode_debut"]:
        jours_sans_calendrier = _jours_sans_calendrier(
            conn, ligne_id,
            date.fromisoformat(classement["periode_debut"]),
            date.fromisoformat(classement["periode_fin"]),
        )
    return {
        "mode_ecriture": mode,
        "periode_debut": classement["periode_debut"],
        "periode_fin": classement["periode_fin"],
        "nb_lues": len(validation["valides"]) + len(validation["rejets"]),
        "nb_ajouts": len(classement["ajouts"]),
        "nb_maj": len(classement["maj"]),
        "nb_inchangees": len(classement["inchangees"]),
        "nb_suppressions": len(classement["suppressions"]),
        "nb_rejets": len(validation["rejets"]),
        "nb_hors_fenetre": classement["hors_fenetre"],
        "rejets": [r["motif"] for r in validation["rejets"]],
        "articles_inconnus_crees": validation["articles_inconnus"],
        "sans_cadence": validation["sans_cadence"],
        "sans_quantite_planifiee": validation["sans_quantite_planifiee"],
        "jours_sans_calendrier": jours_sans_calendrier,
        "anomalies": anomalies,
    }


def _purger_avant_import(dossier: Path) -> None:
    """Ne conserve que les sauvegardes des derniers imports."""
    fichiers = sorted(
        dossier.glob("avant_import_*.db"), key=lambda f: f.stat().st_mtime, reverse=True
    )
    for fichier in fichiers[RETENTION_AVANT_IMPORT:]:
        fichier.unlink()


def annuler_dernier_import(chemin_db: Path | str) -> Path:
    """Restaure la sauvegarde prise avant le dernier import.

    Ne tente jamais d'inverser un upsert ligne à ligne : un upsert ayant écrasé
    des valeurs n'est pas réversible, la restauration l'est toujours.
    Toutes les connexions à la base doivent être fermées avant l'appel.
    """
    chemin_db = Path(chemin_db)
    connexion = sqlite3.connect(str(chemin_db))
    connexion.row_factory = sqlite3.Row
    try:
        dernier = connexion.execute(
            "SELECT * FROM import_log WHERE sauvegarde IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        connexion.close()
    if dernier is None:
        raise ImportInvalide("Aucun import à annuler : le journal des imports est vide.")
    chemin_sauvegarde = Path(dernier["sauvegarde"])
    if not chemin_sauvegarde.exists():
        raise ImportInvalide(
            f"La sauvegarde {chemin_sauvegarde} n'existe plus : "
            "l'annulation est impossible. Restaurez une sauvegarde SharePoint."
        )
    shutil.copy2(chemin_sauvegarde, chemin_db)
    return chemin_db
