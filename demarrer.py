"""Démarrage de l'application avec une fenêtre d'attente.

Sans lui, l'utilisateur double-clique et ne voit rien pendant plusieurs secondes,
le temps que le serveur se lance — de quoi cliquer une deuxième fois et ouvrir
deux instances. Cette fenêtre annonce ce qui se passe, puis reste à l'écran
comme moyen d'arrêter l'application proprement.

Utilise uniquement la bibliothèque standard (tkinter) : aucune dépendance
supplémentaire. Sans interface graphique disponible, le démarrage se poursuit
en mode console.

Usage :
    python demarrer.py          # fenêtre d'attente puis navigateur
    python demarrer.py --console  # sans fenêtre, pour le diagnostic
"""

from __future__ import annotations

import atexit
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

RACINE = Path(__file__).parent
PORT_SOUHAITE = 8501


def chemin_base() -> Path:
    """Chemin de la base, lu dans config.toml — même source que l'interface."""
    import os
    import tomllib

    surcharge = os.environ.get("TRS_BASE")
    if surcharge:
        return Path(surcharge)
    config = RACINE / "config.toml"
    if config.exists():
        try:
            contenu = tomllib.loads(config.read_text(encoding="utf-8"))
            return RACINE / contenu.get("base", {}).get("chemin", "data/trs.db")
        except tomllib.TOMLDecodeError:
            pass
    return RACINE / "data" / "trs.db"


DELAI_DEMARRAGE = 90          # secondes avant d'abandonner
ETAPES = (
    "Préparation de l'environnement",
    "Chargement des composants de calcul",
    "Ouverture de la base de données",
    "Démarrage du serveur local",
)

# Palette de l'application (CDC §7.0) — sobre, sans décoration.
FOND = "#fcfcfb"
ENCRE = "#0b0b0b"
ENCRE_SECONDAIRE = "#52514e"
ACCENT = "#2a78d6"
ALERTE = "#d03b3b"


def trouver_port(depart: int = PORT_SOUHAITE, essais: int = 20) -> int:
    """Premier port libre à partir de celui souhaité.

    Choisir le port ici, plutôt que de laisser Streamlit le faire, évite qu'une
    instance oubliée occupe le port et que l'adresse annoncée soit fausse.
    """
    for numero in range(depart, depart + essais):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as prise:
            prise.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                prise.bind(("127.0.0.1", numero))
                return numero
            except OSError:
                continue
    raise RuntimeError(
        f"Aucun port disponible entre {depart} et {depart + essais - 1}. "
        "Une autre application occupe peut-être ces ports."
    )


def reglages_sauvegarde() -> tuple[Path | None, int, int]:
    """Destination et rétention des sauvegardes, lues dans la base puis le poste.

    Ordre : ce qui est saisi dans l'écran Paramètres, sinon le dossier
    synchronisé trouvé sur la machine. Aucun chemin n'est écrit en dur : il
    diffère d'un poste à l'autre.
    """
    from core import db as base, sauvegarde as module_sauvegarde

    destination, jours, mois = None, 30, 12
    try:
        conn = base.ouvrir_connexion(chemin_base())
        try:
            parametres = dict(conn.execute("SELECT cle, valeur FROM parametre").fetchall())
        finally:
            conn.close()
        if parametres.get("chemin_sauvegarde"):
            destination = Path(parametres["chemin_sauvegarde"])
        jours = int(parametres.get("retention_jours", 30))
        mois = int(parametres.get("retention_mois", 12))
    except Exception:
        pass

    if destination is None or not destination.parent.exists():
        trouve = module_sauvegarde.trouver_dossier_synchronise()
        if trouve is not None:
            destination = trouve
    return destination, jours, mois


def sauvegarder_maintenant(moment: str) -> None:
    """Sauvegarde automatique, silencieuse en cas d'échec côté utilisateur.

    Appelée à l'ouverture et à la fermeture. La fermeture est un moment fiable
    ici parce que c'est ce lanceur qui arrête le serveur : le cahier des charges
    déconseillait de s'y fier sous Streamlit seul, où rien ne garantit qu'un
    code de sortie s'exécute.
    """
    from core import sauvegarde as module_sauvegarde

    base_donnees = chemin_base()
    if not base_donnees.exists():
        return
    destination, jours, mois = reglages_sauvegarde()
    cible, message = module_sauvegarde.sauvegarder_si_possible(
        base_donnees, destination, retention_jours=jours, retention_mois=mois
    )
    print(f"[{moment}] {message}")


def arreter_serveur(processus: subprocess.Popen | None) -> None:
    """Arrête le serveur, puis sauvegarde la base une fois les écritures closes.

    Un serveur resté en vie après la fermeture du lanceur occupe le port et
    continue de servir une version périmée du code : c'est indétectable pour
    l'utilisateur et très déroutant.
    """
    if processus is None or processus.poll() is not None:
        return
    processus.terminate()
    try:
        processus.wait(timeout=5)
    except subprocess.TimeoutExpired:
        processus.kill()
    # Après l'arrêt : la base n'est plus écrite, la copie est donc cohérente.
    try:
        sauvegarder_maintenant("fermeture")
    except Exception:
        pass


def lancer_serveur(port: int) -> subprocess.Popen:
    """Lance Streamlit sans lui laisser ouvrir le navigateur : la séquence est
    pilotée ici, pour n'afficher la page qu'une fois le serveur réellement prêt."""
    processus = _demarrer_processus(port)
    # Filet de sécurité : quelle que soit la façon dont le lanceur se termine,
    # le serveur s'arrête avec lui.
    atexit.register(arreter_serveur, processus)
    for numero in (signal.SIGTERM, signal.SIGINT):
        try:
            precedent = signal.getsignal(numero)

            def _quitter(_signal, _trame, _precedent=precedent):
                arreter_serveur(processus)
                if callable(_precedent):
                    _precedent(_signal, _trame)
                sys.exit(0)

            signal.signal(numero, _quitter)
        except (ValueError, OSError):
            # Hors du thread principal ou signal indisponible : atexit suffit.
            pass
    return processus


def _demarrer_processus(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", str(RACINE / "app.py"),
         "--server.port", str(port),
         "--server.address", "localhost",
         "--server.headless", "true"],
        cwd=str(RACINE),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def serveur_pret(port: int, delai: float = 0.4) -> bool:
    """Interroge le point de santé de Streamlit."""
    try:
        with urllib.request.urlopen(
            f"http://localhost:{port}/_stcore/health", timeout=delai
        ) as reponse:
            return reponse.status == 200
    except (urllib.error.URLError, OSError, ValueError):
        return False


def attendre_serveur(processus: subprocess.Popen, port: int,
                     rappel=None) -> bool:
    """Attend que le serveur réponde. Retourne False s'il s'est arrêté avant."""
    debut = time.monotonic()
    etape = 0
    while time.monotonic() - debut < DELAI_DEMARRAGE:
        if processus.poll() is not None:
            return False
        if serveur_pret(port):
            return True
        if rappel is not None:
            ecoule = time.monotonic() - debut
            nouvelle = min(int(ecoule / 1.5), len(ETAPES) - 1)
            if nouvelle != etape:
                etape = nouvelle
                rappel(ETAPES[etape])
        time.sleep(0.2)
    return False


def journal_du_serveur(processus: subprocess.Popen) -> str:
    """Dernières lignes écrites par le serveur, pour expliquer un échec."""
    if processus.stdout is None:
        return ""
    try:
        sortie = processus.stdout.read() or ""
    except (ValueError, OSError):
        return ""
    lignes = [l for l in sortie.splitlines() if l.strip()]
    return "\n".join(lignes[-8:])


# --------------------------------------------------------------- mode console

def demarrer_en_console() -> int:
    if serveur_pret(PORT_SOUHAITE, delai=1.0):
        adresse = f"http://localhost:{PORT_SOUHAITE}"
        print(f"L'application est déjà ouverte : {adresse}")
        webbrowser.open(adresse)
        return 0
    port = trouver_port()
    print(f"Démarrage de l'application sur le port {port}...")
    processus = lancer_serveur(port)
    if attendre_serveur(processus, port, rappel=lambda e: print(f"  {e}...")):
        adresse = f"http://localhost:{port}"
        print(f"Application prête : {adresse}")
        try:
            sauvegarder_maintenant("ouverture")
        except Exception:
            pass
        webbrowser.open(adresse)
        try:
            processus.wait()
        except KeyboardInterrupt:
            pass
        finally:
            arreter_serveur(processus)
        return 0
    print("Le démarrage a échoué.")
    print(journal_du_serveur(processus))
    arreter_serveur(processus)
    return 1


# --------------------------------------------------------------- mode fenêtre

def demarrer_avec_fenetre() -> int:
    import tkinter as tk

    etat = {"processus": None, "port": None, "ouverte": False}

    racine = tk.Tk()
    racine.title("Application TRS")
    racine.configure(bg=FOND)
    racine.resizable(False, False)

    largeur, hauteur = 460, 200
    racine.geometry(
        f"{largeur}x{hauteur}"
        f"+{(racine.winfo_screenwidth() - largeur) // 2}"
        f"+{(racine.winfo_screenheight() - hauteur) // 3}"
    )

    cadre = tk.Frame(racine, bg=FOND, padx=28, pady=24)
    cadre.pack(fill="both", expand=True)

    titre = tk.Label(
        cadre, text="Rendement et TRS de la ligne", bg=FOND, fg=ENCRE,
        font=("Segoe UI", 13, "bold"), anchor="w",
    )
    titre.pack(fill="x")

    message = tk.Label(
        cadre, text="Démarrage en cours...", bg=FOND, fg=ENCRE_SECONDAIRE,
        font=("Segoe UI", 10), anchor="w", justify="left", wraplength=390,
    )
    message.pack(fill="x", pady=(10, 0))

    detail = tk.Label(
        cadre, text="Première ouverture de la journée : quelques secondes.",
        bg=FOND, fg=ENCRE_SECONDAIRE, font=("Segoe UI", 9), anchor="w",
        justify="left", wraplength=390,
    )
    detail.pack(fill="x", pady=(6, 0))

    barre = tk.Frame(cadre, bg=ACCENT, height=3)
    barre.pack(fill="x", pady=(16, 0))

    boutons = tk.Frame(cadre, bg=FOND)
    boutons.pack(fill="x", pady=(14, 0))

    def arreter() -> None:
        arreter_serveur(etat["processus"])
        racine.destroy()

    def rouvrir() -> None:
        if etat["port"]:
            webbrowser.open(f"http://localhost:{etat['port']}")

    bouton_rouvrir = tk.Button(
        boutons, text="Rouvrir dans le navigateur", command=rouvrir,
        state="disabled", relief="flat", bg="#f0efe9", fg=ENCRE,
        activebackground="#e1e0d9", padx=12, pady=5, borderwidth=0,
        font=("Segoe UI", 9), cursor="arrow",
    )
    bouton_rouvrir.pack(side="left")

    bouton_arret = tk.Button(
        boutons, text="Arrêter l'application", command=arreter,
        relief="flat", bg="#f0efe9", fg=ENCRE, activebackground="#e1e0d9",
        padx=12, pady=5, borderwidth=0, font=("Segoe UI", 9),
    )
    bouton_arret.pack(side="right")

    racine.protocol("WM_DELETE_WINDOW", arreter)

    def afficher_echec(texte: str, journal: str = "") -> None:
        message.configure(text=texte, fg=ALERTE)
        detail.configure(
            text=journal or "Transmettez ce message au responsable de l'outil."
        )
        barre.configure(bg=ALERTE)
        bouton_arret.configure(text="Fermer")

    def travail() -> None:
        # Double-clic sur le raccourci alors que l'application tourne déjà :
        # on rouvre la page existante au lieu de lancer un second serveur.
        if serveur_pret(PORT_SOUHAITE, delai=1.0):
            etat["port"] = PORT_SOUHAITE
            etat["deja_ouverte"] = True
            racine.after(0, terminer, PORT_SOUHAITE)
            return
        try:
            port = trouver_port()
        except RuntimeError as erreur:
            racine.after(0, afficher_echec, str(erreur))
            return
        etat["port"] = port
        processus = lancer_serveur(port)
        etat["processus"] = processus

        def annoncer(etape: str) -> None:
            racine.after(0, message.configure, {"text": etape + "..."})

        if attendre_serveur(processus, port, rappel=annoncer):
            try:
                sauvegarder_maintenant("ouverture")
            except Exception:
                pass
            racine.after(0, terminer, port)
        else:
            racine.after(0, afficher_echec,
                         "Le démarrage de l'application a échoué.",
                         journal_du_serveur(processus))

    def terminer(port: int) -> None:
        adresse = f"http://localhost:{port}"
        if etat.get("deja_ouverte"):
            message.configure(text="L'application était déjà ouverte.", fg=ENCRE)
            detail.configure(
                text=f"Adresse : {adresse}\n"
                     "Cette fenêtre peut être fermée : elle ne pilote pas la "
                     "session en cours."
            )
            bouton_arret.configure(text="Fermer cette fenêtre")
        else:
            message.configure(
                text="L'application est ouverte dans votre navigateur.", fg=ENCRE
            )
            detail.configure(
                text=f"Adresse : {adresse}\n"
                     "Laissez cette fenêtre ouverte pendant l'utilisation."
            )
        bouton_rouvrir.configure(state="normal")
        if not etat["ouverte"]:
            etat["ouverte"] = True
            webbrowser.open(adresse)
        surveiller()

    def surveiller() -> None:
        """Si le serveur s'arrête de lui-même, la fenêtre le dit au lieu de mentir."""
        if etat.get("deja_ouverte"):
            return
        processus = etat["processus"]
        if processus is not None and processus.poll() is not None:
            afficher_echec("L'application s'est arrêtée.",
                           journal_du_serveur(processus))
            return
        racine.after(1000, surveiller)

    threading.Thread(target=travail, daemon=True).start()
    racine.mainloop()

    processus = etat["processus"]
    if processus is not None and processus.poll() is None:
        processus.terminate()
    return 0


def principal() -> int:
    if "--console" in sys.argv:
        return demarrer_en_console()
    try:
        import tkinter  # noqa: F401
    except ImportError:
        # Python sans interface graphique (distribution embarquée) : on continue
        # en console plutôt que d'échouer.
        return demarrer_en_console()
    return demarrer_avec_fenetre()


if __name__ == "__main__":
    sys.exit(principal())
