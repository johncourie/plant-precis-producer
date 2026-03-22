-- Seed synonym data for the four corpus plants.
-- Representative plants from each seed text:
--   Potter's Cyclopaedia     → Atropa belladonna (belladonna)
--   Ellingwood's Am. Mat. Med. → Hydrastis canadensis (goldenseal)
--   Felter's Eclectic Mat. Med. → Achillea millefolium (yarrow)
--   King's American Dispensatory → Echinacea angustifolia (echinacea)

-- Achillea millefolium (yarrow) — Felter
INSERT OR IGNORE INTO synonyms (canonical_binomial, name_string, name_type, language, source) VALUES
('Achillea millefolium L.', 'Achillea millefolium L.', 'binomial', 'en', 'POWO'),
('Achillea millefolium L.', 'Achillea millefolium', 'binomial', 'en', 'POWO'),
('Achillea millefolium L.', 'yarrow', 'common', 'en', 'corpus_scan'),
('Achillea millefolium L.', 'milfoil', 'common', 'en', 'corpus_scan'),
('Achillea millefolium L.', 'Millefolii herba', 'drug_name', 'la', 'corpus_scan'),
('Achillea millefolium L.', 'thousand-leaf', 'common', 'en', 'corpus_scan'),
('Achillea millefolium L.', 'nosebleed', 'common', 'en', 'corpus_scan'),
('Achillea millefolium L.', 'Achillea lanulosa', 'deprecated_binomial', 'en', 'POWO'),
('Achillea millefolium L.', 'Achillea borealis', 'deprecated_binomial', 'en', 'POWO');

-- Atropa belladonna (belladonna) — Potter's
INSERT OR IGNORE INTO synonyms (canonical_binomial, name_string, name_type, language, source) VALUES
('Atropa belladonna L.', 'Atropa belladonna L.', 'binomial', 'en', 'POWO'),
('Atropa belladonna L.', 'Atropa belladonna', 'binomial', 'en', 'POWO'),
('Atropa belladonna L.', 'belladonna', 'common', 'en', 'corpus_scan'),
('Atropa belladonna L.', 'deadly nightshade', 'common', 'en', 'corpus_scan'),
('Atropa belladonna L.', 'Belladonnae folium', 'drug_name', 'la', 'corpus_scan'),
('Atropa belladonna L.', 'dwale', 'common', 'en', 'corpus_scan'),
('Atropa belladonna L.', 'Belladonnae radix', 'drug_name', 'la', 'corpus_scan');

-- Hydrastis canadensis (goldenseal) — Ellingwood
INSERT OR IGNORE INTO synonyms (canonical_binomial, name_string, name_type, language, source) VALUES
('Hydrastis canadensis L.', 'Hydrastis canadensis L.', 'binomial', 'en', 'POWO'),
('Hydrastis canadensis L.', 'Hydrastis canadensis', 'binomial', 'en', 'POWO'),
('Hydrastis canadensis L.', 'goldenseal', 'common', 'en', 'corpus_scan'),
('Hydrastis canadensis L.', 'golden seal', 'common', 'en', 'corpus_scan'),
('Hydrastis canadensis L.', 'Hydrastis', 'common', 'en', 'corpus_scan'),
('Hydrastis canadensis L.', 'yellow root', 'common', 'en', 'corpus_scan'),
('Hydrastis canadensis L.', 'orange root', 'common', 'en', 'corpus_scan'),
('Hydrastis canadensis L.', 'Hydrastidis rhizoma', 'drug_name', 'la', 'corpus_scan');

-- Echinacea angustifolia (echinacea) — King's
INSERT OR IGNORE INTO synonyms (canonical_binomial, name_string, name_type, language, source) VALUES
('Echinacea angustifolia DC.', 'Echinacea angustifolia DC.', 'binomial', 'en', 'POWO'),
('Echinacea angustifolia DC.', 'Echinacea angustifolia', 'binomial', 'en', 'POWO'),
('Echinacea angustifolia DC.', 'echinacea', 'common', 'en', 'corpus_scan'),
('Echinacea angustifolia DC.', 'narrow-leaved coneflower', 'common', 'en', 'corpus_scan'),
('Echinacea angustifolia DC.', 'purple coneflower', 'common', 'en', 'corpus_scan'),
('Echinacea angustifolia DC.', 'Echinaceae radix', 'drug_name', 'la', 'corpus_scan'),
('Echinacea angustifolia DC.', 'Brauneria angustifolia', 'deprecated_binomial', 'en', 'POWO'),
('Echinacea angustifolia DC.', 'black sampson', 'common', 'en', 'corpus_scan');
