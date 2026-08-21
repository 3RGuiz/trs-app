-- Schéma complet de la base TRS (CDC §4).
-- Toutes les dates sont stockées en texte ISO (AAAA-MM-JJ), tous les temps en minutes,
-- toutes les quantités en UVC, toutes les cadences en UVC par minute.
-- Règle générale : les référentiels sont historisés (date_debut / date_fin, NULL = en vigueur)
-- et ne se modifient jamais en place. Les données de production et d'arrêts sont des faits,
-- non historisés : elles se corrigent par réimport.

-- ---------------------------------------------------------------- référentiels articles

CREATE TABLE IF NOT EXISTS famille (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    libelle     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article (
    code        TEXT PRIMARY KEY,           -- code article ERP
    libelle     TEXT NOT NULL,
    actif       INTEGER NOT NULL DEFAULT 1
);

-- Rattachement article -> famille, historisé : le catalogue produits se réorganise.
CREATE TABLE IF NOT EXISTS article_famille (
    id           INTEGER PRIMARY KEY,
    article_code TEXT NOT NULL REFERENCES article(code),
    famille_id   INTEGER NOT NULL REFERENCES famille(id),
    date_debut   DATE NOT NULL,
    date_fin     DATE
);

-- Format / grammage, historisé. poids_unitaire_g ne sert qu'aux vues tonnage, jamais au TRS.
CREATE TABLE IF NOT EXISTS article_format (
    id               INTEGER PRIMARY KEY,
    article_code     TEXT NOT NULL REFERENCES article(code),
    libelle_format   TEXT,
    poids_unitaire_g REAL,
    date_debut       DATE NOT NULL,
    date_fin         DATE
);

-- ---------------------------------------------------------------- ligne et éléments

-- La ligne est le périmètre de mesure du TRS (CDC §4.6). Pas la machine.
CREATE TABLE IF NOT EXISTS ligne (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    libelle     TEXT NOT NULL,
    date_debut  DATE NOT NULL,              -- mise en service
    date_fin    DATE                        -- retrait ; NULL = en service
);

-- Les éléments composent la ligne : zones, machines, organes. Arborescence libre,
-- entièrement gérée par l'utilisateur, historisée. Sert à ANALYSER l'origine des arrêts,
-- jamais à calculer la cascade des temps.
CREATE TABLE IF NOT EXISTS element_ligne (
    id          INTEGER PRIMARY KEY,
    ligne_id    INTEGER NOT NULL REFERENCES ligne(id),
    parent_id   INTEGER REFERENCES element_ligne(id),   -- NULL = niveau racine (zone)
    code        TEXT NOT NULL,
    libelle     TEXT NOT NULL,
    type        TEXT NOT NULL CHECK (type IN ('ZONE', 'EQUIPEMENT', 'ORGANE')),
    ordre       INTEGER,                    -- position dans le flux, pour l'affichage
    chemin      TEXT NOT NULL,              -- chemin matérialisé, ex : '/3/12/47/'
    remplace_id INTEGER REFERENCES element_ligne(id),   -- élément remplacé (lignée)
    date_debut  DATE NOT NULL,              -- mise en service
    date_fin    DATE,                       -- retrait ; NULL = en service
    UNIQUE(ligne_id, code, date_debut)
);
CREATE INDEX IF NOT EXISTS idx_element_chemin ON element_ligne(ligne_id, chemin);

-- ---------------------------------------------------------------- cadences

-- Cadence de référence = capacité de la LIGNE COMPLÈTE, goulot inclus (CDC §4.2).
CREATE TABLE IF NOT EXISTS cadence (
    id           INTEGER PRIMARY KEY,
    article_code TEXT NOT NULL REFERENCES article(code),
    ligne_id     INTEGER NOT NULL REFERENCES ligne(id),
    valeur_ppm   REAL NOT NULL CHECK (valeur_ppm > 0),
    date_debut   DATE NOT NULL,
    date_fin     DATE,
    commentaire  TEXT,
    cree_le      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    cree_par     TEXT
);
CREATE INDEX IF NOT EXISTS idx_cadence_lookup ON cadence(article_code, ligne_id, date_debut);

-- ---------------------------------------------------------------- motifs d'arrêt

CREATE TABLE IF NOT EXISTS motif_arret (
    id          INTEGER PRIMARY KEY,
    code        TEXT NOT NULL UNIQUE,
    libelle     TEXT NOT NULL,
    date_debut  DATE NOT NULL,
    date_fin    DATE                        -- retrait ; un motif utilisé ne se supprime pas
);

-- Classement historisé : reclasser un motif ne réécrit pas l'historique.
-- La catégorie pilote la cascade ; la famille ne sert qu'à l'analyse.
CREATE TABLE IF NOT EXISTS motif_classement (
    id          INTEGER PRIMARY KEY,
    motif_id    INTEGER NOT NULL REFERENCES motif_arret(id),
    categorie   TEXT NOT NULL CHECK (categorie IN ('HORS_REQUIS', 'ARRET_PROPRE')),
    famille     TEXT CHECK (famille IN ('MECANIQUE', 'ELECTRIQUE', 'PROCESS', 'MATIERE',
                                        'HUMAIN', 'ORGANISATION', 'QUALITE')),
    date_debut  DATE NOT NULL,
    date_fin    DATE
);

-- Quels motifs sont proposés sur quel élément. element_id NULL = motif global.
CREATE TABLE IF NOT EXISTS motif_element (
    id          INTEGER PRIMARY KEY,
    motif_id    INTEGER NOT NULL REFERENCES motif_arret(id),
    element_id  INTEGER REFERENCES element_ligne(id),
    date_debut  DATE NOT NULL,
    date_fin    DATE
);
CREATE INDEX IF NOT EXISTS idx_motif_element ON motif_element(element_id, motif_id);

-- ---------------------------------------------------------------- calendrier

-- Modèle horaire hebdomadaire, historisé.
CREATE TABLE IF NOT EXISTS calendrier_type (
    id           INTEGER PRIMARY KEY,
    ligne_id     INTEGER NOT NULL REFERENCES ligne(id),
    jour_semaine INTEGER NOT NULL CHECK (jour_semaine BETWEEN 0 AND 6),  -- 0 = lundi
    to_min       INTEGER NOT NULL CHECK (to_min >= 0),
    tr_min       INTEGER NOT NULL CHECK (tr_min >= 0),
    date_debut   DATE NOT NULL,
    date_fin     DATE,
    CHECK (tr_min <= to_min)
);

-- Fériés, arrêts annuels, renforts, journées atypiques. Prime sur le calendrier type.
CREATE TABLE IF NOT EXISTS calendrier_exception (
    id       INTEGER PRIMARY KEY,
    ligne_id INTEGER NOT NULL REFERENCES ligne(id),
    date     DATE NOT NULL,
    to_min   INTEGER NOT NULL CHECK (to_min >= 0),   -- 0 = fermeture
    tr_min   INTEGER NOT NULL CHECK (tr_min >= 0),
    motif    TEXT,
    UNIQUE(ligne_id, date),
    CHECK (tr_min <= to_min)
);

-- ---------------------------------------------------------------- objectifs

CREATE TABLE IF NOT EXISTS objectif (
    id            INTEGER PRIMARY KEY,
    perimetre     TEXT NOT NULL CHECK (perimetre IN ('GLOBAL', 'FAMILLE', 'ARTICLE')),
    perimetre_ref TEXT,                     -- NULL si GLOBAL, sinon code famille ou article
    indicateur    TEXT NOT NULL CHECK (indicateur IN ('TRS', 'TRG', 'TRE', 'TQ', 'TP', 'DO')),
    cible         REAL NOT NULL CHECK (cible BETWEEN 0 AND 1),
    seuil_alerte  REAL,
    date_debut    DATE NOT NULL,
    date_fin      DATE
);

-- ---------------------------------------------------------------- production et arrêts (faits)

CREATE TABLE IF NOT EXISTS production (
    id            INTEGER PRIMARY KEY,
    date          DATE NOT NULL,
    ligne_id      INTEGER NOT NULL REFERENCES ligne(id),
    article_code  TEXT NOT NULL REFERENCES article(code),
    of_numero     TEXT,
    qte_planifiee REAL,
    qte_produite  REAL NOT NULL,            -- seule quantité disponible aujourd'hui -> Tu
    qte_ensachee  REAL,                     -- compteur sortie ensacheuse, NULL tant qu'il n'existe pas
    import_id     INTEGER REFERENCES import_log(id),
    UNIQUE(date, ligne_id, article_code, of_numero)
);
CREATE INDEX IF NOT EXISTS idx_production_jour ON production(ligne_id, date);

CREATE TABLE IF NOT EXISTS arret (
    id           INTEGER PRIMARY KEY,
    date         DATE NOT NULL,             -- jour de production de rattachement
    ligne_id     INTEGER NOT NULL REFERENCES ligne(id),      -- ce qui est mesuré
    element_id   INTEGER REFERENCES element_ligne(id),       -- origine, peut être NULL
    motif_id     INTEGER NOT NULL REFERENCES motif_arret(id),
    debut        TIMESTAMP,                 -- horodatage de début (fortement recommandé)
    fin          TIMESTAMP,
    duree_min    REAL NOT NULL CHECK (duree_min >= 0),
    arrete_ligne INTEGER NOT NULL DEFAULT 1 CHECK (arrete_ligne IN (0, 1)),
    commentaire  TEXT,
    import_id    INTEGER REFERENCES import_log(id)
);
CREATE INDEX IF NOT EXISTS idx_arret_jour ON arret(ligne_id, date);

-- ---------------------------------------------------------------- import et journalisation

CREATE TABLE IF NOT EXISTS import_log (
    id              INTEGER PRIMARY KEY,
    fichier         TEXT NOT NULL,
    empreinte       TEXT NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('PRODUCTION', 'ARRET', 'CADENCE')),
    mode_ecriture   TEXT NOT NULL CHECK (mode_ecriture IN
                        ('UPSERT', 'REMPLACEMENT_PERIODE', 'REIMPORT_COMPLET')),
    periode_debut   DATE,
    periode_fin     DATE,
    date_import     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    nb_ajouts       INTEGER,
    nb_maj          INTEGER,
    nb_suppressions INTEGER,
    nb_rejets       INTEGER,
    sauvegarde      TEXT,                   -- chemin de la sauvegarde prise avant écriture
    rapport         TEXT                    -- JSON du détail
);
CREATE INDEX IF NOT EXISTS idx_import_empreinte ON import_log(empreinte);

CREATE TABLE IF NOT EXISTS journal_referentiel (
    id              INTEGER PRIMARY KEY,
    table_cible     TEXT NOT NULL,
    cle_metier      TEXT NOT NULL,
    action          TEXT NOT NULL CHECK (action IN ('CREATION', 'CLOTURE', 'CORRECTION')),
    ancienne_valeur TEXT,
    nouvelle_valeur TEXT,
    date_effet      DATE NOT NULL,
    commentaire     TEXT NOT NULL CHECK (length(trim(commentaire)) > 0),
    auteur          TEXT NOT NULL,
    horodatage      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------------- paramètres

-- Préférences sans effet sur les résultats (chemin de base, format d'export...).
CREATE TABLE IF NOT EXISTS parametre (
    cle    TEXT PRIMARY KEY,
    valeur TEXT NOT NULL
);

-- Paramètres de calcul datés : leur changement modifierait sinon tout l'historique.
-- Cas connus : MODE_TR, POINT_COMPTAGE_TU, DATE_DEBUT_HISTORIQUE.
CREATE TABLE IF NOT EXISTS parametre_date (
    id          INTEGER PRIMARY KEY,
    cle         TEXT NOT NULL,
    valeur      TEXT NOT NULL,
    date_debut  DATE NOT NULL,
    date_fin    DATE
);
