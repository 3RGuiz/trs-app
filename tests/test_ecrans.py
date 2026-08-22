"""Tests des écrans Streamlit — la couche que les tests du moteur ne voient pas.

Les tests de core/ garantissent que le calcul est juste. Ils ne disent rien de
ce qui s'affiche : un mauvais bornage de période, un filtre inversé ou une
colonne mal choisie produirait un chiffre faux à l'écran sans qu'aucun d'eux ne
bronche. Ces tests-ci vérifient donc le chiffre **affiché**, pas le chiffre
calculé.

Ils tournent sur une base construite ici, pointée par la variable
d'environnement TRS_BASE, et non sur la base de travail.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from core import arrets, cadences, db, historisation, motifs

RACINE = Path(__file__).resolve().parent.parent
AUTEUR = "tests"
JOUR = date(2026, 7, 15)          # mercredi
DELAI = 90


@pytest.fixture
def application(tmp_path, monkeypatch):
    """Base connue + application pointée dessus.

    Cas de référence du CDC §5.2 bis : 30 UVC/min, To 840, Tr 570,
    13 200 UVC produites, 70 min d'arrêt propre. TRS attendu 77,19 %.
    """
    chemin = tmp_path / "ecrans.db"
    conn = db.ouvrir_base(chemin)
    conn.execute(
        "INSERT INTO ligne (id, code, libelle, date_debut)"
        " VALUES (1, 'L1', 'Ligne de test (UVC)', '2026-01-01')"
    )
    conn.execute("INSERT INTO famille (id, code, libelle) VALUES (1, 'F1', 'Famille test')")
    for code in ("ART-001", "ART-002"):
        conn.execute("INSERT INTO article (code, libelle) VALUES (?, ?)",
                     (code, f"Article {code}"))
        historisation.cloturer_et_inserer(
            conn, "article_famille", {"article_code": code}, {"famille_id": 1},
            "2026-01-01", "Rattachement", AUTEUR)
    # ART-001 a une cadence, ART-002 non : l'écran doit distinguer les deux.
    cadences.changer_cadence(conn, "ART-001", 1, 30, "2026-01-01", "Référence", AUTEUR)
    for jour_semaine in range(5):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 840, "tr_min": 570}, "2026-01-01", "Calendrier", AUTEUR)
    for jour_semaine in (5, 6):
        historisation.cloturer_et_inserer(
            conn, "calendrier_type", {"ligne_id": 1, "jour_semaine": jour_semaine},
            {"to_min": 0, "tr_min": 0}, "2026-01-01", "Week-end", AUTEUR)

    conn.execute(
        "INSERT INTO production (date, ligne_id, article_code, of_numero,"
        " qte_planifiee, qte_produite) VALUES (?, 1, 'ART-001', 'OF-1', 15000, 13200)",
        (JOUR.isoformat(),))
    panne = conn.execute("SELECT id FROM motif_arret WHERE code = 'PANNE'").fetchone()[0]
    arrets.saisir_arret(conn, 1, JOUR, panne,
                        debut=f"{JOUR} 08:00", fin=f"{JOUR} 09:10")   # 70 min
    conn.commit()
    conn.close()

    monkeypatch.setenv("TRS_BASE", str(chemin))
    return chemin


def ecran(nom: str) -> str:
    """Chemin absolu d'un écran : AppTest résout le relatif depuis tests/."""
    return str(RACINE / nom)


def _ouvrir(page: str, jour=JOUR) -> AppTest:
    """Lance un écran sur la période d'un seul jour connu."""
    test = AppTest.from_file(page, default_timeout=DELAI)
    test.run()
    if test.date_input:
        test.date_input[0].set_value(jour)
        test.date_input[1].set_value(jour).run()
    return test


def _metriques(test: AppTest) -> dict[str, str]:
    return {m.label: m.value for m in test.metric}


# --------------------------------------------------------------- exactitude

def test_le_dashboard_affiche_le_trs_du_cas_de_reference(application):
    """Le chiffre à l'écran doit être celui du CDC, pas seulement celui du moteur."""
    test = _ouvrir(ecran("app_pages/0_Dashboard.py"))
    assert not test.exception
    valeurs = _metriques(test)
    assert valeurs["TRS de la période"].startswith("77,2")
    # La décomposition est mesurable : un arrêt est saisi, pas de compteur qualité.
    assert valeurs["Disponibilité DO"].startswith("87,7")
    assert valeurs["Qualité TQ"] == "non mesuré", "TQ ne doit jamais être affiché à 100 %"


def test_l_ecran_trs_affiche_la_meme_valeur_que_le_dashboard(application):
    """Deux écrans, une seule vérité : un écart signalerait un filtre divergent."""
    dashboard = _metriques(_ouvrir(ecran("app_pages/0_Dashboard.py")))
    ecran_trs = _metriques(_ouvrir(ecran("app_pages/4_TRS.py")))
    assert dashboard["TRS de la période"] == ecran_trs["TRS de la période"]


@pytest.mark.parametrize("jour_analyse", [date(2026, 7, 14), date(2026, 7, 16)])
def test_la_periode_affichee_borne_bien_le_calcul(application, jour_analyse):
    """La production du 15 ne doit fuir ni vers la veille ni vers le lendemain.

    C'est le défaut qu'aucun test du moteur ne verrait : une borne décalée d'un
    jour ferait apparaître les 13 200 UVC du 15 dans l'analyse du 14 ou du 16,
    et le TRS afficherait 77,2 % un jour où rien n'a été produit.
    """
    test = _ouvrir(ecran("app_pages/0_Dashboard.py"), jour=jour_analyse)
    assert not test.exception
    valeurs = _metriques(test)
    trs = valeurs.get("TRS de la période")
    assert trs in (None, "non mesuré"), (
        f"le {jour_analyse} n'a aucune production, or l'écran affiche {trs}"
    )
    assert "13 200" not in " ".join(
        m.value for m in test.markdown
    ).replace(" ", " "), "la quantité du 15 juillet ne doit pas apparaître"


# --------------------------------------------------------------- règles métier

def test_aucun_ecran_n_affiche_de_trs_par_produit(application):
    """Règle 4 ter : le temps requis ne se ventile pas par article (CDC §5.2 ter)."""
    test = AppTest.from_file(ecran("app_pages/0_Dashboard.py"), default_timeout=DELAI)
    test.run()
    test.segmented_control[2].set_value("article").run()
    assert not test.exception
    libelles = {m.label.upper() for m in test.metric}
    assert not libelles & {"TRS", "TRG", "TRE", "TRS DE LA PÉRIODE"}
    assert "Taux de réalisation" in {m.label for m in test.metric}


def test_un_produit_sans_cadence_n_affiche_pas_zero(application):
    """Une production non mesurable ne doit jamais ressembler à une contre-performance."""
    from core import db as base_module
    conn = base_module.ouvrir_connexion(os.environ["TRS_BASE"])
    conn.execute(
        "INSERT INTO production (date, ligne_id, article_code, of_numero, qte_produite)"
        " VALUES ('2026-07-16', 1, 'ART-002', 'OF-2', 5000)")
    conn.commit()
    conn.close()

    test = _ouvrir(ecran("app_pages/0_Dashboard.py"), jour=date(2026, 7, 16))
    assert not test.exception
    valeurs = _metriques(test)
    assert valeurs.get("TRS de la période") != "0,0 %", "un TRS de 0 % serait faux ici"


# --------------------------------------------------------------- interactions

def test_changer_la_maille_recale_la_periode_sans_ecraser_un_choix_explicite(application):
    test = AppTest.from_file(ecran("app_pages/0_Dashboard.py"), default_timeout=DELAI)
    test.run()
    # Une période trop courte pour la maille est élargie...
    test.segmented_control[0].set_value("7 jours").run()
    test.segmented_control[1].set_value("mois").run()
    assert (test.session_state._periode_fin - test.session_state._periode_debut).days > 300

    # ...mais une période déjà exploitable est respectée.
    test.segmented_control[0].set_value("3 mois").run()
    avant = (test.session_state._periode_debut, test.session_state._periode_fin)
    test.segmented_control[1].set_value("semaine").run()
    assert (test.session_state._periode_debut, test.session_state._periode_fin) == avant


def test_la_periode_est_partagee_entre_les_ecrans(application):
    """Régler la période sur un écran doit valoir pour les suivants."""
    dashboard = AppTest.from_file(ecran("app_pages/0_Dashboard.py"), default_timeout=DELAI)
    dashboard.run()
    dashboard.segmented_control[0].set_value("7 jours").run()
    etat = {c: dashboard.session_state[c]
            for c in ("_periode_debut", "_periode_fin", "_periode_maille",
                      "_periode_version")}

    suivant = AppTest.from_file(ecran("app_pages/4_TRS.py"), default_timeout=DELAI)
    for cle, valeur in etat.items():
        suivant.session_state[cle] = valeur
    suivant.run()
    assert not suivant.exception
    assert suivant.session_state._periode_debut == etat["_periode_debut"]


def test_une_periode_a_l_envers_est_impossible_a_saisir(application):
    """Mieux vaut empêcher l'erreur que la signaler.

    Déplacer le début après la fin doit entraîner la fin avec lui, et non
    produire une période inversée qu'il faudrait ensuite refuser.
    """
    test = AppTest.from_file(ecran("app_pages/0_Dashboard.py"), default_timeout=DELAI)
    test.run()
    test.date_input[0].set_value(date(2026, 7, 31)).run()
    assert not test.exception
    assert test.session_state._periode_fin >= test.session_state._periode_debut, (
        "la date de fin doit suivre le début plutôt que rester en arrière"
    )


def test_le_filet_de_validation_tient_si_l_etat_devient_incoherent(application):
    """Ceinture et bretelles : même si une période inversée survient malgré la
    contrainte de saisie, l'écran l'explique au lieu de laisser passer une trace."""
    test = AppTest.from_file(ecran("app_pages/0_Dashboard.py"), default_timeout=DELAI)
    test.session_state._periode_debut = date(2026, 7, 31)
    test.session_state._periode_fin = date(2026, 7, 1)
    test.session_state._periode_maille = "semaine"
    test.session_state._periode_version = 0
    test.run()
    assert not test.exception, "aucune trace technique ne doit remonter"


# --------------------------------------------------------------- robustesse

def test_tous_les_ecrans_s_affichent_sur_une_base_peuplee(application):
    for page in (ecran("app_pages/0_Dashboard.py"), ecran("app_pages/1_Import.py"),
                 ecran("app_pages/2_Referentiel.py"), ecran("app_pages/3_Rendement.py"),
                 ecran("app_pages/4_TRS.py"), ecran("app_pages/5_Parametres.py"),
                 ecran("app_pages/6_Arrets.py"), ecran("app_pages/7_Aide.py")):
        test = AppTest.from_file(page, default_timeout=DELAI)
        test.run()
        assert not test.exception, f"{page} lève une exception"


def test_tous_les_ecrans_s_affichent_sur_une_base_vide(tmp_path, monkeypatch):
    """Premier lancement : les écrans doivent guider, pas planter."""
    chemin = tmp_path / "vide.db"
    db.ouvrir_base(chemin).close()
    monkeypatch.setenv("TRS_BASE", str(chemin))
    for page in (ecran("app_pages/0_Dashboard.py"), ecran("app_pages/2_Referentiel.py"),
                 ecran("app_pages/4_TRS.py"), ecran("app_pages/6_Arrets.py")):
        test = AppTest.from_file(page, default_timeout=DELAI)
        test.run()
        assert not test.exception, f"{page} lève une exception sur base vide"
