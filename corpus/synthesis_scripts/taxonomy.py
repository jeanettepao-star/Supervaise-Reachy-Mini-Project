"""
Canonical topic taxonomy for the CJ Panganiban corpus.

Each topic has:
- id: snake_case canonical identifier
- display_name: human-readable
- tier: anchor (10+ docs) | major (4-9) | subordinate (2-5)
- definition: 1-2 sentence description
- doc_ids: explicit assignment (not auto-clustered)
- subtopic_keywords: regex/substring patterns matched against raw sub_topics
                   (used as evidence-trail / verification)
- invokes_frameworks: mnemonic frameworks regularly referenced
- key_cases: case ids from CASE_ALIASES
- relations: typed edges to other topics

Doc-id assignments are based on having extracted all 89 docs.
"""

TOPIC_TAXONOMY = {
    # ============== ANCHOR TIER (10+ docs) ==============
    "rule_of_law": {
        "display_name": "The Rule of Law",
        "tier": "anchor",
        "definition": "CJ's most-repeated organizing concept: law as supreme over force, applied to specific institutional contexts (AFP loyalty, ICC obligations, international order, anti-authoritarianism).",
        "doc_ids": [
            "col_2021_0221", "col_2021_0425", "col_2021_0725",
            "col_2023_1023", "col_2024_0212", "col_2024_0219",
            "col_2024_0930", "col_2025_0811", "col_2020_1227",
            "book_01_ch01", "book_01_ch03", "book_01_ch06",
            "book_01_ch10", "book_01_ch16", "book_01_appendix-d",
        ],
        "subtopic_keywords": ["rule of law", "Rule of Law"],
        "invokes_frameworks": ["four_ins"],
        "key_cases": [],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "anchor_for", "weight": 10},
            {"target": "judicial_reform", "type": "anchor_for", "weight": 8},
            {"target": "martial_law_critique", "type": "anchor_for", "weight": 6},
            {"target": "icc_jurisdiction", "type": "anchor_for", "weight": 5},
            {"target": "west_philippine_sea", "type": "anchor_for", "weight": 5},
        ],
    },

    "liberty_and_prosperity": {
        "display_name": "Liberty and Prosperity (Twin Beacons)",
        "tier": "anchor",
        "definition": "CJ's signature jurisprudential thesis: liberty and prosperity must always go together — 'one is useless without the other'. The Foundation for Liberty and Prosperity (FLP) embodies this philosophy.",
        "doc_ids": [
            "col_2015_0301", "col_2019_1103", "col_2021_0725",
            "col_2022_0102", "col_2022_0411", "col_2024_0909",
            "book_01_ch02", "book_01_ch03",
        ] + [f"col_{y}_{md}" for y, md in [
            ("2014","0601"),("2016","1127"),("2019","0217"),("2020","0510"),
            ("2022","0808"),("2023","0731"),("2024","0902"),("2025","0825"),
            ("2026","0112"),  # FLP-specific columns
        ]],
        "subtopic_keywords": ["liberty and prosperity", "twin beacons",
                              "twin and inseparable"],
        "invokes_frameworks": ["twin_beacons", "time_talent_treasure"],
        "key_cases": ["tanada_v_angara"],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 10},
            {"target": "flp_institutional_history", "type": "embodied_by", "weight": 10},
            {"target": "judicial_activism", "type": "operationalized_via", "weight": 6},
            {"target": "constitutional_globalization", "type": "complements", "weight": 5},
        ],
    },

    "personal_formation": {
        "display_name": "Personal Formation: Sampaloc → FEU → SC",
        "tier": "anchor",
        "definition": "Autobiographical formation arc: Sampaloc poverty, 15-centavo bus fare, UST/FEU scholarships, 1956 FEU strike encounter with Salonga, 1960 bar exam wading, Yale-denied, law practice, 1992-1995 JBC failures, 1995 Ramos appointment.",
        "doc_ids": [
            "col_2014_0302", "col_2015_0104", "col_2016_0320",
            "col_2017_0212", "col_2018_0429", "col_2023_0424",
            "book_01_appendix-a", "book_01_appendix-b",
            "book_01_ch12",
        ],
        "subtopic_keywords": ["Sampaloc", "FEU", "bar exam", "Yale", "JBC", "Mapa High"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "mentor_salonga", "type": "shaped_by", "weight": 10},
            {"target": "leni_and_family", "type": "intertwined_with", "weight": 7},
            {"target": "theological_jurisprudence", "type": "shaped_by", "weight": 6},
        ],
    },

    "flp_institutional_history": {
        "display_name": "Foundation for Liberty and Prosperity (FLP)",
        "tier": "anchor",
        "definition": "Founded December 2011 on CJ's 75th birthday. Operationalizes the twin-beacons philosophy via law scholarships, bar-passer awards, professorial chairs, ESMEL essay prizes, P2.5B Prosperity Fund (decade 2).",
        "doc_ids": [
            "col_2016_1127", "col_2019_0217", "col_2020_0510",
            "col_2021_1031", "col_2022_0411", "col_2022_0808",
            "col_2023_0731", "col_2024_0902", "col_2025_0825",
            "col_2026_0112", "col_2022_0102", "col_2022_1114",
        ],
        "subtopic_keywords": ["FLP", "Foundation for Liberty and Prosperity",
                              "LibPros", "scholar", "Prosperity Fund", "ESMEL"],
        "invokes_frameworks": ["time_talent_treasure"],
        "key_cases": [],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "instantiates", "weight": 10},
            {"target": "legal_education_reform", "type": "operationalizes", "weight": 8},
            {"target": "personal_formation", "type": "culminates_in", "weight": 7},
        ],
    },

    "judicial_reform": {
        "display_name": "Judicial Reform and Excellence",
        "tier": "anchor",
        "definition": "Reforming the bench through structured mnemonics: Four Ins (integrity, intelligence, independence, industry), 3 E-values, 4 Cs of decision-writing, plus institutional reforms (APJR, Benchbook, zero-backlog).",
        "doc_ids": [
            "book_01_front-matter", "book_01_ch01", "book_01_ch03",
            "book_01_ch06", "book_01_ch07", "book_01_ch08",
            "book_01_ch09", "book_01_ch11", "book_01_ch12",
            "book_01_appendix-d", "col_2022_1114",
        ],
        "subtopic_keywords": ["four Ins", "judicial reform", "Benchbook",
                              "APJR", "zero backlog", "judicial excellence"],
        "invokes_frameworks": ["four_ins", "three_es", "four_cs",
                              "four_acid", "mpgr", "plague_of_ships"],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 9},
            {"target": "chief_davide", "type": "embodied_by", "weight": 8},
            {"target": "decision_writing_craft", "type": "encompasses", "weight": 7},
            {"target": "legal_education_reform", "type": "complements", "weight": 6},
        ],
    },

    # ============== MAJOR TIER (4-9 docs) ==============
    "west_philippine_sea": {
        "display_name": "West Philippine Sea / Arbitral Award",
        "tier": "major",
        "definition": "2016 PCA Arbitral Award sovereignty doctrine, EEZ rights, China-Philippines disputes, joint-development debate, Carpio as advocate.",
        "doc_ids": [
            "col_2019_0728", "col_2019_0804", "col_2019_0818",
            "col_2019_0825", "col_2021_0613", "col_2023_0116",
            "col_2024_0219", "col_2024_1125", "col_2026_0330",
        ],
        "subtopic_keywords": ["WPS", "West Philippine Sea", "Arbitral Award",
                              "South China Sea", "UNCLOS", "EEZ", "PCA"],
        "invokes_frameworks": [],
        "key_cases": ["arbitral_award_2016"],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 8},
            {"target": "carpio_legacy", "type": "advocated_by", "weight": 10},
            {"target": "national_interest", "type": "embodies", "weight": 7},
        ],
    },

    "icc_jurisdiction": {
        "display_name": "ICC Jurisdiction and the Drug-War Cases",
        "tier": "major",
        "definition": "ICC jurisdiction over Philippines post-withdrawal (two-year prescriptive period), complementarity doctrine, drug-war prosecutions targeting Duterte, role of DOJ/OSG.",
        "doc_ids": [
            "col_2023_0227", "col_2023_0807", "col_2023_1211",
            "col_2025_0324",
        ],
        "subtopic_keywords": ["ICC", "Rome Statute", "complementarity",
                              "two-year prescriptive period", "drug war"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 9},
            {"target": "duterte_critique", "type": "applied_to", "weight": 9},
        ],
    },

    "death_penalty": {
        "display_name": "Death Penalty",
        "tier": "major",
        "definition": "CJ's anti-death-penalty doctrine: 1987 Constitution abolished it, RA 7659 unconstitutional, DNA exonerations show irreversibility, five international treaties oppose it, Echegaray procedural error.",
        "doc_ids": [
            "book_01_ch02", "book_01_ch10", "book_01_ch14",
        ],
        "subtopic_keywords": ["death penalty", "Echegaray", "RA 7659",
                              "DNA evidence", "heinous crimes"],
        "invokes_frameworks": [],
        "key_cases": ["echegaray"],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 7},
            {"target": "due_process", "type": "applies", "weight": 7},
            {"target": "theological_jurisprudence", "type": "supported_by", "weight": 5},
        ],
    },

    "citizenship_and_elections": {
        "display_name": "Citizenship and Elections",
        "tier": "major",
        "definition": "Voter-will primacy doctrine across citizenship cases: Frivaldo, Bengson, Mercado v Comelec; repatriation as recovery of original citizenship, popular-mandate trumps fractured legalism.",
        "doc_ids": ["book_01_ch02", "book_01_ch19"],
        "subtopic_keywords": ["Frivaldo", "Bengson", "repatriation",
                              "natural-born", "citizenship"],
        "invokes_frameworks": [],
        "key_cases": ["frivaldo_v_comelec", "bengson_v_hret"],
        "relations": [
            {"target": "judicial_activism", "type": "instantiated_by", "weight": 7},
            {"target": "rule_of_law", "type": "child_of", "weight": 6},
        ],
    },

    "party_list_system": {
        "display_name": "Party-List System (Philippine Style)",
        "tier": "major",
        "definition": "Four parameters of party-list elections (Veterans Federation), eight-guideline framework, marginalized-and-underrepresented exclusivity (Ang Bagong Bayani), Niemeyer-formula rejection.",
        "doc_ids": ["book_01_ch02", "book_01_ch16"],
        "subtopic_keywords": ["party-list", "Veterans Federation",
                              "Ang Bagong Bayani", "marginalized",
                              "underrepresented", "Niemeyer"],
        "invokes_frameworks": [],
        "key_cases": ["veterans_federation", "ang_bagong_bayani"],
        "relations": [
            {"target": "social_justice", "type": "instantiates", "weight": 9},
        ],
    },

    "judicial_activism": {
        "display_name": "Judicial Activism (Article VIII Sec 1)",
        "tier": "major",
        "definition": "Constitutional judicial-review framework: grave abuse of discretion as expanded prerogative, twofold SC responsibility, anti-political-question doctrine. Distinguished from judicial overreach.",
        "doc_ids": [
            "book_01_ch03", "book_01_ch10", "book_01_ch13", "book_01_ch18",
            "col_2023_0410", "col_2013_0427", "col_2014_0601",
            "col_2024_0715",
        ],
        "subtopic_keywords": ["judicial activism", "grave abuse of discretion",
                              "Article VIII", "political question"],
        "invokes_frameworks": [],
        "key_cases": ["tanada_v_angara", "santiago_v_guingona",
                      "avelino_v_cuenco"],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 8},
            {"target": "judicial_reform", "type": "complements", "weight": 6},
        ],
    },

    "edsa_ii_succession": {
        "display_name": "EDSA II and Constitutional Succession",
        "tier": "major",
        "definition": "January 20, 2001 Davide oath-taking of GMA; March 2 unanimous Estrada v Desierto decision (Puno ponencia); CJ and Davide voluntary inhibition; totality test; EDSA II-vs-EDSA I distinction.",
        "doc_ids": ["book_01_ch02", "book_01_ch08", "book_01_ch13"],
        "subtopic_keywords": ["EDSA II", "Estrada v. Desierto",
                              "oath-taking", "totality test", "Angara Diary"],
        "invokes_frameworks": [],
        "key_cases": ["estrada_v_desierto"],
        "relations": [
            {"target": "judicial_activism", "type": "instantiates", "weight": 7},
            {"target": "chief_davide", "type": "stars", "weight": 8},
        ],
    },

    "due_process": {
        "display_name": "Due Process",
        "tier": "major",
        "definition": "Themistocles + Webster framing ('a law that hears before it condemns'), procedural-protection doctrine, applied across contexts (extradition, criminal procedure, qualifying-circumstance allegation).",
        "doc_ids": [
            "col_2012_0114", "book_01_ch02", "book_01_ch17",
        ],
        "subtopic_keywords": ["due process", "Themistocles", "Webster",
                              "hearing before condemning"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 8},
            {"target": "death_penalty", "type": "applies_to", "weight": 6},
        ],
    },

    "constitutional_globalization": {
        "display_name": "Constitutional Globalization and the New Economy",
        "tier": "major",
        "definition": "Tañada v. Angara doctrine: Constitution as both stable and adaptive, designed for 'future and unknown circumstances'. WTO membership, paradigm shifts (deregulation, privatization, globalization), Filipino-First clauses as non-self-executing.",
        "doc_ids": [
            "book_01_ch02", "book_01_appendix-c", "book_01_ch10",
        ],
        "subtopic_keywords": ["globalization", "WTO", "deregulation",
                              "privatization", "Tañada", "TRIPs"],
        "invokes_frameworks": [],
        "key_cases": ["tanada_v_angara", "manila_prince_hotel"],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "doctrinal_basis_for", "weight": 8},
            {"target": "rule_of_law", "type": "child_of", "weight": 6},
        ],
    },

    "judicial_independence": {
        "display_name": "Judicial Independence",
        "tier": "major",
        "definition": "Three-prong definition: (1) unreviewable decisional power, (2) constitutionally guaranteed financial autonomy, (3) security of tenure to 70 + security of compensation. Founded on Act 136 of 1901.",
        "doc_ids": [
            "book_01_ch06", "book_01_ch08", "book_01_ch10",
            "book_01_front-matter", "col_2011_0703",
        ],
        "subtopic_keywords": ["judicial independence", "Act 136",
                              "security of tenure", "financial autonomy"],
        "invokes_frameworks": ["plague_of_ships"],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 8},
            {"target": "judicial_reform", "type": "precondition_for", "weight": 7},
        ],
    },

    # ============== SUBORDINATE TIER (2-5 docs) ==============
    "legal_education_reform": {
        "display_name": "Legal Education Reform",
        "tier": "subordinate",
        "definition": "Bar exam reform, Foundation for Enhancement of Legal Education, national professorial chairs, law-school curriculum, FLP scholarships.",
        "doc_ids": [
            "col_2014_0201", "col_2014_0907", "col_2019_0217",
            "col_2024_0916", "book_01_ch04",
        ],
        "subtopic_keywords": ["legal education", "bar exam", "law school"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "judicial_reform", "type": "child_of", "weight": 7},
            {"target": "flp_institutional_history", "type": "funded_by", "weight": 8},
        ],
    },

    "alternative_dispute_resolution": {
        "display_name": "Alternative Dispute Resolution / Court Backlog",
        "tier": "subordinate",
        "definition": "ADR (negotiation, conciliation, mediation, arbitration) as Asian/Filipino-cultural fit, zero-backlog program, court-congestion solutions.",
        "doc_ids": ["book_01_ch05", "book_01_ch06"],
        "subtopic_keywords": ["ADR", "mediation", "backlog", "Philja"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "judicial_reform", "type": "child_of", "weight": 6},
        ],
    },

    "electronic_evidence_age": {
        "display_name": "Electronic Age and Paperless Courts",
        "tier": "subordinate",
        "definition": "Electronic Commerce Act (RA 8792), Philippine Rules on Electronic Evidence, paperless-court possibilities, single-fixed-camera judicial-transparency proposal.",
        "doc_ids": ["book_01_ch17", "book_01_appendix-c"],
        "subtopic_keywords": ["electronic", "paperless", "ECA", "digital"],
        "invokes_frameworks": [],
        "key_cases": ["perez_v_estrada"],
        "relations": [
            {"target": "judicial_reform", "type": "modernizes", "weight": 6},
        ],
    },

    "freedom_of_expression": {
        "display_name": "Freedom of Expression",
        "tier": "subordinate",
        "definition": "Free-speech evolution (speech → press → strike → broadcast → internet), exit polls as protected speech (ABS-CBN v Comelec), actual-malice doctrine for public figures (Vasquez v CA), cyberlibel (Ressa).",
        "doc_ids": [
            "book_01_ch02", "book_01_ch17", "col_2020_0621",
            "col_2023_1030",
        ],
        "subtopic_keywords": ["exit poll", "libel", "free expression",
                              "actual malice", "cyberlibel"],
        "invokes_frameworks": [],
        "key_cases": ["cyberlibel_ressa"],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 6},
        ],
    },

    "environment_natural_resources": {
        "display_name": "Environment and Natural Resources",
        "tier": "subordinate",
        "definition": "Oposa v. Factoran intergenerational ecology right, Regalian doctrine, IPRA constitutionality debate (CJ's reverse-discrimination position).",
        "doc_ids": ["book_01_ch02", "book_01_ch15"],
        "subtopic_keywords": ["Oposa", "Regalian", "IPRA", "ancestral domain",
                              "natural resources"],
        "invokes_frameworks": [],
        "key_cases": ["oposa_v_factoran", "cruz_v_environment"],
        "relations": [
            {"target": "social_justice", "type": "contested_in", "weight": 7},
        ],
    },

    "medical_jurisprudence": {
        "display_name": "Medical Jurisprudence",
        "tier": "subordinate",
        "definition": "Medical-malpractice doctrine (Batiquin, Ramos v CA), res ipsa loquitur, four elements (duty/breach/injury/causation), Two Cs (competence, care).",
        "doc_ids": ["book_01_ch02", "col_2017_0212"],
        "subtopic_keywords": ["medical malpractice", "res ipsa loquitur",
                              "Batiquin", "Ramos v. CA"],
        "invokes_frameworks": ["two_cs"],
        "key_cases": [],
        "relations": [],
    },

    "theological_jurisprudence": {
        "display_name": "Theological Jurisprudence",
        "tier": "subordinate",
        "definition": "Justice as God's work; BLD (Bukas Loob sa Diyos) spiritual rebirth 1986-1995; biblical citations (Romans 8:28, Isaiah 55:8-9, Matthew 22:34-40); 'separation of church from state, but no separation of state from God'.",
        "doc_ids": [
            "book_01_appendix-b", "book_01_ch08", "book_01_ch11",
            "col_2012_0407", "col_2016_0724", "col_2022_0418",
            "col_2024_1007", "col_2025_1027",
        ],
        "subtopic_keywords": ["BLD", "Bukas Loob", "Romans 8:28", "Isaiah",
                              "PCP 2", "Pontifical Council", "theological"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "personal_formation", "type": "shapes", "weight": 8},
            {"target": "rule_of_law", "type": "supplements", "weight": 5},
        ],
    },

    "lawyer_ethics": {
        "display_name": "Lawyer Ethics and Vocation",
        "tier": "subordinate",
        "definition": "Code of Professional Responsibility, threefold hierarchy (court > client > self), three E-values for lawyers, religious-vocation parallel.",
        "doc_ids": ["book_01_ch11", "col_2025_1027", "book_01_ch12"],
        "subtopic_keywords": ["Code of Professional Responsibility",
                              "threefold hierarchy", "three E-values"],
        "invokes_frameworks": ["three_es"],
        "key_cases": [],
        "relations": [
            {"target": "judicial_reform", "type": "complements", "weight": 6},
        ],
    },

    "decision_writing_craft": {
        "display_name": "Decision Writing Craft",
        "tier": "subordinate",
        "definition": "4 Cs (correct, complete, clear, concise), obra maestra anthology, anti-extraordinary-verbiage, accessible-to-high-school-graduates principle, decisions as literature/philosophy/history.",
        "doc_ids": ["book_01_ch03", "book_01_ch09", "book_01_front-matter"],
        "subtopic_keywords": ["4 Cs", "decision writing", "obra maestra",
                              "kilometric decisions"],
        "invokes_frameworks": ["four_cs"],
        "key_cases": [],
        "relations": [
            {"target": "judicial_reform", "type": "child_of", "weight": 7},
        ],
    },

    "social_justice": {
        "display_name": "Social Justice (Less in Life → More in Law)",
        "tier": "subordinate",
        "definition": "Foundational aphorism: 'those who have less in life should have more in law'. Embodied in party-list, FLP, IPRA debate, anti-reverse-discrimination boundary.",
        "doc_ids": [
            "book_01_ch15", "book_01_ch16", "col_2024_0506",
            "col_2025_0421",
        ],
        "subtopic_keywords": ["social justice", "less in life", "more in law",
                              "marginalized"],
        "invokes_frameworks": [],
        "key_cases": ["ang_bagong_bayani", "cruz_v_environment"],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "complements", "weight": 7},
            {"target": "party_list_system", "type": "instantiates", "weight": 8},
        ],
    },

    # ============== PERSONAL-PANTHEON TIER ==============
    "mentor_salonga": {
        "display_name": "Mentor: Jovito R. Salonga",
        "tier": "personal-pantheon",
        "definition": "Salonga as guru: 1956 FEU strike encounter, 1960 bar wading, law-firm partner, JBC-rejection-years prayer support, 'things money cannot buy' framework, Romans 8:28 anchor.",
        "doc_ids": [
            "col_2016_0320", "col_2018_0429", "col_2024_0916",
            "col_2019_1117", "book_01_appendix-a", "book_01_ch11",
        ],
        "subtopic_keywords": ["Salonga", "guru", "mentor", "FEU dean"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "personal_formation", "type": "shapes", "weight": 10},
            {"target": "diokno_teehankee", "type": "trinity_with", "weight": 8},
        ],
    },

    "chief_davide": {
        "display_name": "Chief Justice Hilario G. Davide Jr.",
        "tier": "personal-pantheon",
        "definition": "Davide as institutional embodiment: four pillars (integrity, simplicity, dedication, faith), daily 3:30 am Bible-cutting (2 Macc 10 / Isaiah 62), Davide Watch APJR reform, Estrada Impeachment Court chair, 'Filipino of the Year 2000'.",
        "doc_ids": [
            "book_01_ch01", "book_01_ch08", "book_01_ch09",
            "book_01_ch12", "book_01_front-matter",
        ],
        "subtopic_keywords": ["Davide", "Davide Watch", "Filipino of the Year",
                              "Bible-cutting"],
        "invokes_frameworks": ["four_ins"],
        "key_cases": [],
        "relations": [
            {"target": "judicial_reform", "type": "embodies", "weight": 9},
            {"target": "edsa_ii_succession", "type": "stars_in", "weight": 8},
        ],
    },

    "leni_and_family": {
        "display_name": "Leni and the Carpio Family",
        "tier": "personal-pantheon",
        "definition": "Wife Leni, AIM Associate Dean. Father-in-law Jose A. Carpio Sr.: PRSP founding father, Dean of Filipino PR Practitioners. BLD spiritual rebirth journey 1986-1995.",
        "doc_ids": [
            "col_2023_0424", "col_2022_0418", "book_01_appendix-b",
            "book_01_ch12",
        ],
        "subtopic_keywords": ["Leni", "Carpio Sr.", "AIM", "PRSP",
                              "Manila-Naga"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "personal_formation", "type": "intertwined_with", "weight": 8},
            {"target": "theological_jurisprudence", "type": "embedded_in", "weight": 7},
        ],
    },

    "diokno_teehankee": {
        "display_name": "Diokno-Salonga-Teehankee Trinity",
        "tier": "personal-pantheon",
        "definition": "CJ's legal-trinity: Salonga (UP/Harvard, 1944 bar 95.3%), Diokno (no law degree, same bar tie), Teehankee (Ateneo summa, 1940 bar numero uno) — Ateneo's 'greatest law alumnus'.",
        "doc_ids": ["col_2018_0429", "col_2024_0916"],
        "subtopic_keywords": ["Diokno", "Teehankee", "bar topnotcher",
                              "1944 bar", "Pepe Diokno"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "mentor_salonga", "type": "trinity_with", "weight": 9},
        ],
    },

    "carpio_legacy": {
        "display_name": "Antonio Carpio Legacy ('CJ We Never Had')",
        "tier": "personal-pantheon",
        "definition": "Senior Justice Carpio: WPS arbitral-award champion, 'the CJ we never had', sovereignty defender, signature column 'Crosscurrents'.",
        "doc_ids": [
            "col_2019_0728", "col_2023_0116", "col_2026_0330",
        ],
        "subtopic_keywords": ["Carpio", "CJ we never had", "Crosscurrents",
                              "sovereignty defender"],
        "invokes_frameworks": [],
        "key_cases": ["arbitral_award_2016"],
        "relations": [
            {"target": "west_philippine_sea", "type": "champions", "weight": 10},
        ],
    },

    # ============== CIVIC/CONTEMPORARY TIER ==============
    "national_interest": {
        "display_name": "National Interest in Foreign Affairs",
        "tier": "subordinate",
        "definition": "Negotiating posture analysis, EEZ joint-development debate, constitutional safeguards on foreign agreements, CJ-Yang exchange.",
        "doc_ids": [
            "col_2023_0116", "col_2024_1125", "col_2019_0825",
        ],
        "subtopic_keywords": ["national interest", "joint development",
                              "foreign agreement"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "west_philippine_sea", "type": "child_of", "weight": 7},
            {"target": "rule_of_law", "type": "child_of", "weight": 5},
        ],
    },

    "ai_and_law": {
        "display_name": "AI and Law / Future Jurisprudence",
        "tier": "subordinate",
        "definition": "AI ethics, liberty-prosperity in technology contexts, paperless courts, electronic evidence as bridge to AI-era jurisprudence.",
        "doc_ids": ["col_2024_0909"],
        "subtopic_keywords": ["AI", "artificial intelligence"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "child_of", "weight": 7},
            {"target": "electronic_evidence_age", "type": "successor_to", "weight": 6},
        ],
    },

    "martial_law_critique": {
        "display_name": "Anti-Martial-Law / Anti-Cha-Cha",
        "tier": "subordinate",
        "definition": "Critique of authoritarianism and constitutional revision movements; defending the 1987 Charter against revisionist threats.",
        "doc_ids": ["col_2017_1001", "col_2024_0930"],
        "subtopic_keywords": ["martial law", "cha-cha", "constitutional revision",
                              "authoritarian"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "defends_against", "weight": 7},
        ],
    },

    "duterte_critique": {
        "display_name": "Critique of the Duterte Administration",
        "tier": "subordinate",
        "definition": "Drug-war ICC prosecution, jurisdictional analysis, complementarity arguments, prescriptive-period strategy.",
        "doc_ids": [
            "col_2023_0227", "col_2023_0807", "col_2023_1211",
            "col_2025_0324",
        ],
        "subtopic_keywords": ["Duterte", "drug war", "ICC investigation"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "icc_jurisdiction", "type": "applies_to", "weight": 10},
            {"target": "rule_of_law", "type": "violates", "weight": 7},
        ],
    },

    "ombudsman_constitutional_office": {
        "display_name": "Office of the Ombudsman",
        "tier": "subordinate",
        "definition": "Constitutional office and jurisdiction of the Ombudsman; Conchita Carpio Morales tenure; Chiong v. Anonymous MIAA Officials doctrinal restatement.",
        "doc_ids": ["col_2024_0408"],
        "subtopic_keywords": ["Ombudsman", "Carpio Morales", "Chiong"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 6},
            {"target": "judicial_independence", "type": "complements", "weight": 5},
        ],
    },

    "writ_of_amparo": {
        "display_name": "Writ of Amparo / Red-Tagging",
        "tier": "subordinate",
        "definition": "Amparo as remedy against extrajudicial threats; red-tagging as actionable harassment (Deduro v. Vinoya); SND v. Manalo precedent.",
        "doc_ids": ["col_2024_0513"],
        "subtopic_keywords": ["amparo", "red-tagging", "Deduro", "Manalo"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "rule_of_law", "type": "child_of", "weight": 6},
            {"target": "freedom_of_expression", "type": "protects", "weight": 5},
        ],
    },

    "baguio_civic_initiatives": {
        "display_name": "Civic and Local Initiatives",
        "tier": "subordinate",
        "definition": "Baguio rejuvenation Blue-Zone urban model; civic engagement beyond purely legal-doctrinal work; BCDA case as illustrative.",
        "doc_ids": ["col_2025_0113"],
        "subtopic_keywords": ["Baguio", "Blue Zone", "BCDA", "civic"],
        "invokes_frameworks": [],
        "key_cases": [],
        "relations": [
            {"target": "liberty_and_prosperity", "type": "applies_locally", "weight": 5},
        ],
    },
}


# ============== FRAMEWORK INDEX ==============
# Doctrinal mnemonics that recur across the corpus

FRAMEWORK_INDEX = {
    "four_ins": {
        "display_name": "Four Ins of a Great Magistrate",
        "components": ["integrity", "intelligence", "independence", "industry"],
        "domain": "judicial character",
        "primary_source_doc": "book_01_ch09",
        "verbatim_anchor": "the four 'Ins' of a great magistrate; namely, integrity, intelligence, independence and industry",
    },
    "three_es": {
        "display_name": "3 E-Values for Lawyers",
        "components": ["excellence", "ethics", "eternity"],
        "domain": "lawyer formation",
        "primary_source_doc": "book_01_ch11",
        "verbatim_anchor": "the three E's; namely, excellence, ethics and eternity",
    },
    "four_cs": {
        "display_name": "4 Cs of Effective Legal Writing",
        "components": ["correct", "complete", "clear", "concise"],
        "domain": "decision writing",
        "primary_source_doc": "book_01_ch03",
        "verbatim_anchor": "the '4 Cs' of effective legal writing: correct, complete, clear and concise",
    },
    "four_acid": {
        "display_name": "Four ACID Reform Priorities",
        "components": ["access", "corruption", "incompetence", "delay"],
        "domain": "judicial reform priorities",
        "primary_source_doc": "col_2014_0601",
        "verbatim_anchor": "Four ACID — access, corruption, incompetence, delay",
    },
    "plague_of_ships": {
        "display_name": "Plague of Ships (judicial independence tests)",
        "components": ["kinship", "relationship", "friendship", "fellowship"],
        "domain": "judicial independence",
        "primary_source_doc": "col_2014_0601",
        "verbatim_anchor": "kinship, relationship, friendship, fellowship",
    },
    "dhl": {
        "display_name": "DHL (employee virtues)",
        "components": ["dedication", "honesty", "loyalty"],
        "domain": "employee virtues",
        "primary_source_doc": "col_2014_0601",
        "verbatim_anchor": "DHL — dedication, honesty, loyalty",
    },
    "two_cs": {
        "display_name": "Two Cs of Medical Practice",
        "components": ["competence", "care"],
        "domain": "medical practice",
        "primary_source_doc": "col_2017_0212",
        "verbatim_anchor": "the Two Cs of medical practice: competence and care",
    },
    "mpgr": {
        "display_name": "MPGR (Gonzaga-Reyes tribute)",
        "components": ["modesty", "perspicacity", "gentility", "rectitude"],
        "domain": "judicial-character tribute",
        "primary_source_doc": "book_01_appendix-d",
        "verbatim_anchor": "MODESTY, PERSPICACITY, GENTILITY and RECTITUDE",
    },
    "twin_beacons": {
        "display_name": "Twin Beacons (Liberty + Prosperity)",
        "components": ["liberty", "prosperity"],
        "domain": "jurisprudential thesis",
        "primary_source_doc": "col_2015_0301",
        "verbatim_anchor": "the twin and inseparable beacons; one is useless without the other",
    },
    "time_talent_treasure": {
        "display_name": "Time + Talent + Treasure",
        "components": ["time", "talent", "treasure"],
        "domain": "philanthropy",
        "primary_source_doc": "col_2022_0411",
        "verbatim_anchor": "time, talent and treasure",
    },
}


if __name__ == "__main__":
    from collections import Counter
    tier_counts = Counter(t["tier"] for t in TOPIC_TAXONOMY.values())
    print(f"Topics total: {len(TOPIC_TAXONOMY)}")
    for tier, c in sorted(tier_counts.items()):
        print(f"  {tier}: {c}")
    print(f"\nFrameworks: {len(FRAMEWORK_INDEX)}")
    all_doc_assignments = sum(len(t["doc_ids"]) for t in TOPIC_TAXONOMY.values())
    print(f"\nTotal doc-topic assignments: {all_doc_assignments}")
    print(f"(89 docs × avg topics per doc = approx {all_doc_assignments / 89:.1f})")
