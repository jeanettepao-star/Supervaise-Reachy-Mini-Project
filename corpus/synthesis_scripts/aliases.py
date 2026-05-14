"""
Entity alias maps for the CJ Panganiban corpus.
Canonical names + variants. Built from observed entities across 89 docs.

When new docs arrive (speeches), append to this dict — re-running synthesis
will pick up new mentions and merge them under canonical identities.
"""

PEOPLE_ALIASES = {
    # =========== The CJ himself ===========
    "panganiban_avp": {
        "canonical_name": "Artemio V. Panganiban",
        "aliases": ["Artemio V. Panganiban", "Artemio Panganiban", "CJ Panganiban",
                    "Justice Panganiban", "Justice Artemio V. Panganiban",
                    "Chief Justice Panganiban", "Panganiban, J.", "Panganiban"],
        "role": "self (corpus author)",
    },

    # =========== Personal pantheon ===========
    "salonga_jovito": {
        "canonical_name": "Jovito R. Salonga",
        "aliases": ["Jovito R. Salonga", "Jovito Salonga", "Senator Salonga",
                    "Sen. Salonga", "Salonga", "Dean Salonga", "Dr. Jovito R. Salonga",
                    "Sen. Jovito Salonga"],
        "role": "mentor/guru, FEU dean, Senate President, Liberal Party head",
    },
    "diokno_jose": {
        "canonical_name": "Jose W. Diokno",
        "aliases": ["Jose W. Diokno", "Jose Diokno", "Pepe Diokno",
                    "Sen. Jose W. Diokno", "Diokno"],
        "role": "co-1944-bar-topnotcher with Salonga; legal-trinity figure",
    },
    "teehankee_claudio": {
        "canonical_name": "Claudio Teehankee Sr.",
        "aliases": ["Claudio Teehankee", "Claudio Teehankee Sr.",
                    "Dingdong Teehankee", "CJ Teehankee", "Chief Justice Teehankee",
                    "Teehankee"],
        "role": "Ateneo law alumnus, 1940 bar topnotcher, CJ; legal-trinity",
    },
    "leni_panganiban": {
        "canonical_name": "Elenita 'Leni' Carpio-Panganiban",
        "aliases": ["Leni", "Elenita Panganiban", "Elenita C. Panganiban",
                    "Leni Panganiban", "Elenita Carpio-Panganiban",
                    "Elenita 'Leni' Carpio-Panganiban", "Associate Dean Elenita C. Panganiban"],
        "role": "wife of CJ",
    },
    "carpio_jose_sr": {
        "canonical_name": "Jose A. Carpio Sr.",
        "aliases": ["Jose A. Carpio Sr.", "Jose Carpio Sr.", "Jose A. Carpio",
                    "Mr. Carpio"],
        "role": "Leni's father; PRSP founding father; Dean of Filipino PR Practitioners",
    },
    "carpio_antonio": {
        "canonical_name": "Antonio T. Carpio",
        "aliases": ["Antonio T. Carpio", "Antonio Carpio", "Justice Carpio",
                    "J. Carpio", "Sr. Justice Antonio T. Carpio"],
        "role": "'CJ we never had'; WPS arbitral-award advocate",
    },
    "davide_hilario": {
        "canonical_name": "Hilario G. Davide Jr.",
        "aliases": ["Hilario G. Davide Jr.", "Hilario Davide", "Davide",
                    "CJ Davide", "Chief Justice Davide", "Justice Davide",
                    "J. Davide", "Davide Jr.", "Hilario G. Davide"],
        "role": "Chief Justice (1998-2005); Davide Watch reformer",
    },

    # =========== Pope/spiritual ===========
    "pope_jp2": {
        "canonical_name": "Pope John Paul II",
        "aliases": ["Pope John Paul II", "John Paul II"],
        "role": "appointed CJ to Pontifical Council for the Laity",
    },
    "bishop_tudtud": {
        "canonical_name": "Bishop Benny Tudtud",
        "aliases": ["Benny Tudtud", "Bishop Benny Tudtud", "Bishop Tudtud"],
        "role": "author of 'Disturb Us O Lord' prayer",
    },
    "cardinal_sin": {
        "canonical_name": "Jaime Cardinal Sin",
        "aliases": ["Jaime Cardinal Sin", "Cardinal Sin", "Archbishop Sin"],
        "role": "Manila archbishop, EDSA II pastoral letter",
    },

    # =========== Presidents ===========
    "ramos_fidel": {
        "canonical_name": "Fidel V. Ramos",
        "aliases": ["Fidel V. Ramos", "Fidel Ramos", "President Ramos", "FVR",
                    "Pres. Ramos", "Ramos"],
        "role": "President 1992-1998; appointed CJ to SC",
    },
    "estrada_joseph": {
        "canonical_name": "Joseph Ejercito Estrada",
        "aliases": ["Joseph Ejercito Estrada", "Joseph Estrada", "Estrada",
                    "Erap", "former President Estrada", "JEE", "Mr. Joseph Estrada"],
        "role": "President 1998-2001; ousted via EDSA II",
    },
    "gma_arroyo": {
        "canonical_name": "Gloria Macapagal-Arroyo",
        "aliases": ["Gloria Macapagal-Arroyo", "Gloria Macapagal Arroyo",
                    "GMA", "President Arroyo", "Mrs. Arroyo", "Arroyo",
                    "Mme. Gloria Macapagal-Arroyo"],
        "role": "President 2001-2010; sworn in by Davide at EDSA II",
    },
    "duterte_rodrigo": {
        "canonical_name": "Rodrigo Duterte",
        "aliases": ["Rodrigo Duterte", "Duterte", "President Duterte",
                    "Rodrigo R. Duterte"],
        "role": "President 2016-2022; ICC drug-war case subject",
    },
    "marcos_ferdinand": {
        "canonical_name": "Ferdinand Marcos",
        "aliases": ["Ferdinand Marcos", "Marcos", "Marcos Sr.",
                    "Ferdinand Marcos Sr."],
        "role": "President 1965-1986; declared martial law",
    },
    "marcos_bbm": {
        "canonical_name": "Ferdinand 'Bongbong' Marcos Jr.",
        "aliases": ["Ferdinand Marcos Jr.", "Bongbong Marcos", "BBM",
                    "President Marcos Jr.", "Marcos Jr."],
        "role": "President 2022-present",
    },
    "aquino_corazon": {
        "canonical_name": "Corazon C. Aquino",
        "aliases": ["Corazon C. Aquino", "Cory Aquino", "Corazon Aquino",
                    "President Aquino", "Mrs. Aquino"],
        "role": "President 1986-1992; EDSA I restoration",
    },

    # =========== Justices (Court colleagues) ===========
    "puno_reynato": {
        "canonical_name": "Reynato S. Puno",
        "aliases": ["Reynato S. Puno", "Reynato Puno", "Puno", "Justice Puno",
                    "CJ Puno", "J. Puno"],
        "role": "SC Justice / Chief Justice",
    },
    "gesmundo_alexander": {
        "canonical_name": "Alexander G. Gesmundo",
        "aliases": ["Alexander G. Gesmundo", "Alexander Gesmundo",
                    "CJ Gesmundo", "Chief Justice Gesmundo", "Gesmundo"],
        "role": "incumbent Chief Justice (during late columns)",
    },
    "gutierrez_angelina": {
        "canonical_name": "Angelina Sandoval-Gutierrez",
        "aliases": ["Angelina Sandoval-Gutierrez", "Angelina Gutierrez",
                    "Gutierrez", "J. Gutierrez"],
        "role": "SC Justice (Bengson dissenter)",
    },
    "carpio_morales_conchita": {
        "canonical_name": "Conchita Carpio Morales",
        "aliases": ["Conchita Carpio Morales", "Conchita Carpio-Morales",
                    "Ombudsman Carpio Morales", "Carpio Morales"],
        "role": "Ombudsman (post-SC)",
    },
    "perlas_bernabe_estela": {
        "canonical_name": "Estela M. Perlas-Bernabe",
        "aliases": ["Estela M. Perlas-Bernabe", "Estela Perlas-Bernabe",
                    "Justice Perlas-Bernabe"],
        "role": "SC Justice",
    },
    "vitug_jose": {
        "canonical_name": "Jose C. Vitug",
        "aliases": ["Jose C. Vitug", "Vitug", "J. Vitug", "Justice Vitug"],
        "role": "SC Justice colleague",
    },
    "mendoza_vicente": {
        "canonical_name": "Vicente V. Mendoza",
        "aliases": ["Vicente V. Mendoza", "Mendoza", "J. Mendoza", "Justice Mendoza"],
        "role": "SC Justice colleague",
    },
    "bellosillo_josue": {
        "canonical_name": "Josue N. Bellosillo",
        "aliases": ["Josue N. Bellosillo", "Bellosillo", "J. Bellosillo"],
        "role": "SC Justice colleague",
    },
    "melo_jose_ar": {
        "canonical_name": "Jose A. R. Melo",
        "aliases": ["Jose A. R. Melo", "Jose A.R. Melo", "Melo", "J. Melo"],
        "role": "SC Justice colleague",
    },
    "kapunan_santiago": {
        "canonical_name": "Santiago M. Kapunan",
        "aliases": ["Santiago M. Kapunan", "Kapunan", "J. Kapunan"],
        "role": "SC Justice colleague (Bengson ponente)",
    },
    "pardo_bernardo": {
        "canonical_name": "Bernardo P. Pardo",
        "aliases": ["Bernardo P. Pardo", "Pardo", "J. Pardo"],
        "role": "SC Justice colleague",
    },
    "reyes_minerva": {
        "canonical_name": "Minerva P. Gonzaga-Reyes",
        "aliases": ["Minerva P. Gonzaga-Reyes", "Minerva Gonzaga-Reyes",
                    "Justice Minnie", "MPGR", "Minerva Perez Gonzaga-Reyes"],
        "role": "SC Justice; MPGR mnemonic tribute",
    },
    "quisumbing_leonardo": {
        "canonical_name": "Leonardo A. Quisumbing",
        "aliases": ["Leonardo A. Quisumbing", "Quisumbing", "J. Quisumbing"],
        "role": "SC Justice colleague",
    },
    "melencio_herrera_ameurfina": {
        "canonical_name": "Ameurfina A. Melencio Herrera",
        "aliases": ["Ameurfina A. Melencio Herrera", "Ameurfina Melencio Herrera",
                    "Ameurfina Aguinaldo Melencio Herrera",
                    "Justice Herrera", "Philja Chancellor Herrera"],
        "role": "retired SC Justice, Philja Chancellor",
    },
    "narvasa_andres": {
        "canonical_name": "Andres R. Narvasa",
        "aliases": ["Andres R. Narvasa", "Andres Narvasa", "CJ Narvasa", "Narvasa"],
        "role": "retired Chief Justice (1991-1998)",
    },
    "santiago_consuelo": {
        "canonical_name": "Consuelo Ynares-Santiago",
        "aliases": ["Consuelo Ynares-Santiago", "Consuelo Y. Santiago",
                    "Santiago, J.", "J. Santiago"],
        "role": "SC Justice colleague",
    },

    # =========== Founders/historical ===========
    "rizal_jose": {
        "canonical_name": "Jose Rizal",
        "aliases": ["Jose Rizal", "Rizal", "Dr. Jose Rizal"],
        "role": "national hero",
    },
    "macliing_dulag": {
        "canonical_name": "Macli-ing Dulag",
        "aliases": ["Macli-ing Dulag", "Macli-ing", "Macliing Dulag"],
        "role": "Kalinga chieftain; quoted in IPRA case",
    },

    # =========== Foreign jurisprudence figures ===========
    "hand_learned": {
        "canonical_name": "Learned Hand",
        "aliases": ["Learned Hand", "Judge Learned Hand"],
        "role": "US jurist; well-rounded-judge model",
    },
    "frankfurter_felix": {
        "canonical_name": "Felix Frankfurter",
        "aliases": ["Felix Frankfurter", "Frankfurter, J.", "Frankfurter"],
        "role": "US SC Justice quoted on legal arenas",
    },
    "warren_earl": {
        "canonical_name": "Earl Warren",
        "aliases": ["Earl Warren", "Chief Justice Warren"],
        "role": "US Chief Justice; Estes v Texas concurrence",
    },

    # =========== Additional Justice colleagues / staff ===========
    "buena_arturo": {
        "canonical_name": "Arturo B. Buena",
        "aliases": ["Arturo B. Buena", "Buena", "J. Buena"],
        "role": "SC Justice colleague",
    },
    "de_leon_sabino": {
        "canonical_name": "Sabino R. de Leon Jr.",
        "aliases": ["Sabino R. de Leon Jr.", "De Leon Jr.", "J. De Leon", "Sabino de Leon"],
        "role": "SC Justice colleague",
    },
    "martinez_antonio": {
        "canonical_name": "Antonio M. Martinez",
        "aliases": ["Antonio M. Martinez", "Justice Martinez", "J. Martinez"],
        "role": "SC Justice colleague (1999 retiree)",
    },
    "purisima_fidel": {
        "canonical_name": "Fidel P. Purisima",
        "aliases": ["Fidel P. Purisima", "Justice Purisima"],
        "role": "SC Justice (retired October 2000)",
    },
    "peralta_diosdado": {
        "canonical_name": "Diosdado M. Peralta",
        "aliases": ["Diosdado M. Peralta", "Diosdado Peralta", "Peralta", "CJ Peralta"],
        "role": "SC Justice / Chief Justice",
    },
    "leonen_marvic": {
        "canonical_name": "Marvic M.V.F. Leonen",
        "aliases": ["Marvic M.V.F. Leonen", "Marvic Leonen", "Justice Leonen", "Leonen"],
        "role": "SC Justice (active)",
    },
    "concepcion_roberto": {
        "canonical_name": "Roberto Concepcion",
        "aliases": ["Roberto Concepcion", "CJ Concepcion", "Concepcion"],
        "role": "former Chief Justice; Tañada v. Cuenco ponente",
    },
    "perlas_singh": {
        "canonical_name": "Maria Filomena D. Singh",
        "aliases": ["Maria Filomena D. Singh", "Justice Singh"],
        "role": "SC Justice",
    },
    "lazaro_javier": {
        "canonical_name": "Amy C. Lazaro-Javier",
        "aliases": ["Amy C. Lazaro-Javier", "Justice Lazaro-Javier"],
        "role": "SC Justice",
    },
    "hernando_ramon": {
        "canonical_name": "Ramon Paul L. Hernando",
        "aliases": ["Ramon Paul L. Hernando", "Hernando, J."],
        "role": "SC Justice",
    },

    # =========== Family / personal pantheon ===========
    "prieto_marixi": {
        "canonical_name": "Marixi R. Prieto",
        "aliases": ["Marixi R. Prieto", "Marixi Prieto", "Marixi"],
        "role": "Inquirer publisher; close family friend",
    },
    "nolan_michael": {
        "canonical_name": "Fr. Michael Nolan",
        "aliases": ["Fr. Michael Nolan", "Father Michael Nolan", "Michael Nolan"],
        "role": "FEU chaplain; spiritual mentor",
    },
    "roces_alejandro": {
        "canonical_name": "Alejandro R. Roces",
        "aliases": ["Alejandro R. Roces", "Alejandro Roces", "Sec. Roces"],
        "role": "youngest education secretary at 37",
    },

    # =========== FLP / civic associates ===========
    "borja_sean": {
        "canonical_name": "Sean James Borja",
        "aliases": ["Sean James Borja", "Sean Borja"],
        "role": "FLP scholar / awardee",
    },
    "tetangco_amando": {
        "canonical_name": "Amando M. Tetangco Jr.",
        "aliases": ["Amando M. Tetangco Jr.", "Amando Tetangco", "Tetangco"],
        "role": "BSP Governor; FLP supporter",
    },
    "gregorio_joel": {
        "canonical_name": "Joel Emerson Gregorio",
        "aliases": ["Joel Emerson Gregorio", "Joel Gregorio"],
        "role": "FLP awardee / scholar",
    },
    "pangilinan_mvp": {
        "canonical_name": "Manuel V. Pangilinan",
        "aliases": ["Manuel V. Pangilinan", "MVP", "Manny Pangilinan"],
        "role": "businessman / FLP supporter",
    },
    "pangalangan_raul": {
        "canonical_name": "Raul Pangalangan",
        "aliases": ["Raul Pangalangan", "Dean Pangalangan", "Dean Raul Pangalangan"],
        "role": "UP Law dean; ICC judge",
    },
    "khan_ismael": {
        "canonical_name": "Ismael G. Khan Jr.",
        "aliases": ["Ismael G. Khan Jr.", "Atty. Khan", "Ismael Khan"],
        "role": "SC Public Information Officer (PIO)",
    },
    "dumdum_evelyn": {
        "canonical_name": "Evelyn T. Dumdum",
        "aliases": ["Evelyn T. Dumdum", "Ms. Dumdum", "Evelyn Dumdum"],
        "role": "SC Project Management Office head",
    },

    # =========== ICC / Geopolitical ===========
    "xi_jinping": {
        "canonical_name": "Xi Jinping",
        "aliases": ["Xi Jinping", "President Xi"],
        "role": "President of China",
    },
    "trump_donald": {
        "canonical_name": "Donald Trump",
        "aliases": ["Donald Trump", "Trump", "President Trump"],
        "role": "US President",
    },
    "khan_karim": {
        "canonical_name": "Karim Khan",
        "aliases": ["Karim Khan", "ICC Prosecutor Khan", "Karim A.A. Khan"],
        "role": "ICC Chief Prosecutor",
    },
    "bensouda_fatou": {
        "canonical_name": "Fatou Bensouda",
        "aliases": ["Fatou Bensouda", "Bensouda", "ICC Prosecutor Bensouda"],
        "role": "former ICC Chief Prosecutor",
    },
    "guevarra_menardo": {
        "canonical_name": "Menardo I. Guevarra",
        "aliases": ["Menardo I. Guevarra", "Menardo Guevarra", "Secretary Guevarra"],
        "role": "Secretary of Justice / Solicitor General",
    },
    "de_jesus_edilberto": {
        "canonical_name": "Edilberto C. de Jesus",
        "aliases": ["Edilberto C. de Jesus", "Edilberto de Jesus", "Ed de Jesus"],
        "role": "FLP trustee; AIM president",
    },

    # =========== US jurisprudential ===========
    "scalia_antonin": {
        "canonical_name": "Antonin Scalia",
        "aliases": ["Antonin Scalia", "Justice Scalia"],
        "role": "US Supreme Court Justice (textualist)",
    },
    "malcolm_george": {
        "canonical_name": "George Malcolm",
        "aliases": ["George Malcolm", "Justice Malcolm", "Malcolm"],
        "role": "American-era Philippine SC Justice",
    },
    "laurel_jose": {
        "canonical_name": "Jose P. Laurel",
        "aliases": ["Jose P. Laurel", "Justice Laurel", "Laurel, J.", "Laurel"],
        "role": "Philippine President (WWII); American-era SC Justice",
    },
    "beinisch_dorit": {
        "canonical_name": "Dorit Beinisch",
        "aliases": ["Dorit Beinisch", "Justice Beinisch"],
        "role": "Israeli Supreme Court Justice",
    },
}

CASE_ALIASES = {
    # Major doctrinal cases — all CJ's own ponencias or signature dissents
    "tanada_v_angara": {
        "canonical_name": "Tañada v. Angara (1997)",
        "aliases": ["Tañada v. Angara", "Tanada v. Angara",
                    "Tañada v. Angara (May 2, 1997)", "Tañada vs Angara"],
        "doctrine": "WTO membership constitutionality; grave-abuse-of-discretion definition",
        "ponente": "panganiban_avp",
    },
    "frivaldo_v_comelec": {
        "canonical_name": "Frivaldo v. Comelec (1996)",
        "aliases": ["Frivaldo v. Comelec", "Frivaldo v. Comelec (June 28, 1996)"],
        "doctrine": "voter-will primacy in citizenship-elections; repatriation",
        "ponente": "panganiban_avp",
    },
    "bengson_v_hret": {
        "canonical_name": "Bengson v. HRET (2001)",
        "aliases": ["Bengson v. HRET",
                    "Bengson v. House of Representatives Electoral Tribunal",
                    "Bengson v. HRET (GR 142840, May 7, 2001)"],
        "doctrine": "repatriation restores original natural-born status",
        "ponente": "kapunan_santiago",
    },
    "veterans_federation": {
        "canonical_name": "Veterans Federation Party v. Comelec (2000)",
        "aliases": ["Veterans Federation Party v. Comelec",
                    "Veterans Federation Party v. Comelec (October 6, 2000)"],
        "doctrine": "four parameters of party-list system",
        "ponente": "panganiban_avp",
    },
    "ang_bagong_bayani": {
        "canonical_name": "Ang Bagong Bayani v. Comelec (2001)",
        "aliases": ["Ang Bagong Bayani-OFW Labor Party v. Comelec",
                    "Ang Bagong Bayani v. Comelec",
                    "Ang Bagong Bayani-OFW Labor Party v. Comelec (GR 147589, June 26, 2001)"],
        "doctrine": "party-list as social-justice tool; marginalized-only exclusivity",
        "ponente": "panganiban_avp",
    },
    "estrada_v_desierto": {
        "canonical_name": "Estrada v. Desierto / Estrada v. Arroyo (2001)",
        "aliases": ["Estrada v. Desierto", "Estrada v. Arroyo",
                    "Estrada v. Desierto (March 2, 2001)",
                    "Estrada v. Desierto / Estrada v. Arroyo"],
        "doctrine": "constitutional succession; resignation-by-totality",
        "ponente": "puno_reynato",
    },
    "echegaray": {
        "canonical_name": "People v. Echegaray (1996/1997)",
        "aliases": ["People v. Echegaray", "Echegaray v. Secretary of Justice",
                    "Echegaray v. Secretary of Justice (October 12, 1998)"],
        "doctrine": "death-penalty constitutionality; CJ's dissent",
        "ponente": "per curiam",
    },
    "manila_prince_hotel": {
        "canonical_name": "Manila Prince Hotel v. GSIS (1997)",
        "aliases": ["Manila Prince Hotel v. GSIS",
                    "Manila Prince Hotel v. GSIS (February 3, 1997)"],
        "doctrine": "Filipino First as self-executing for national patrimony",
        "ponente": "bellosillo_josue",
    },
    "perez_v_estrada": {
        "canonical_name": "Perez v. Estrada (2001)",
        "aliases": ["Perez v. Estrada", "Perez v. Estrada (AM 01-4-03-SC)"],
        "doctrine": "live media coverage banned; CJ's single-fixed-camera dissent",
        "ponente": "vitug_jose",
    },
    "cruz_v_environment": {
        "canonical_name": "Cruz v. Sec of Environment (2000) - IPRA",
        "aliases": ["Cruz v. Secretary of Environment", "Cruz v. Secretary of Environment (GR 135385, December 6, 2000)"],
        "doctrine": "IPRA constitutionality (7-7 stalemate); CJ's reverse-discrimination Separate Opinion",
        "ponente": "per curiam",
    },
    "arbitral_award_2016": {
        "canonical_name": "PCA Arbitral Award (2016)",
        "aliases": ["Republic of the Philippines v. People's Republic of China",
                    "Republic of the Philippines v. People's Republic of China (2016 Arbitral Award)",
                    "2016 Arbitral Award", "PCA Arbitral Award",
                    "the Arbitral Award", "Hague arbitral ruling"],
        "doctrine": "UNCLOS adjudication of WPS / South China Sea claims",
        "ponente": "PCA Tribunal (international)",
    },
    "oposa_v_factoran": {
        "canonical_name": "Oposa v. Factoran (1993)",
        "aliases": ["Oposa v. Factoran", "Oposa v. Factoran (July 30, 1993)"],
        "doctrine": "intergenerational right to balanced ecology",
        "ponente": "davide_hilario",
    },
    "santiago_v_guingona": {
        "canonical_name": "Santiago v. Guingona (1998)",
        "aliases": ["Santiago v. Guingona",
                    "Santiago v. Guingona Jr. (November 18, 1998)"],
        "doctrine": "Senate minority-leader jurisdiction",
        "ponente": "panganiban_avp",
    },
    "ople_v_torres": {
        "canonical_name": "Ople v. Torres (1998)",
        "aliases": ["Ople v. Torres", "Ople v. Torres (July 23, 1998)"],
        "doctrine": "right to privacy; National ID system void",
        "ponente": "puno_reynato",
    },
    "avelino_v_cuenco": {
        "canonical_name": "Avelino v. Cuenco (1949)",
        "aliases": ["Avelino v. Cuenco", "Avelino v. Cuenco (March 4, 1949)"],
        "doctrine": "judicial review of legislative leadership disputes",
        "ponente": "per curiam",
    },
    "cyberlibel_ressa": {
        "canonical_name": "Disini v. SOJ / Ressa cyberlibel cases",
        "aliases": ["Disini v. Secretary of Justice", "Maria Ressa cyberlibel",
                    "Ressa cyberlibel case"],
        "doctrine": "cyberlibel constitutionality + actual-malice doctrine for journalists",
        "ponente": "various",
    },
}

LAW_ALIASES = {
    "constitution_1987": {
        "canonical_name": "1987 Constitution",
        "aliases": ["1987 Constitution", "the Constitution", "the 1987 Charter",
                    "the present Constitution", "the fundamental law"],
    },
    "constitution_1935": {
        "canonical_name": "1935 Constitution",
        "aliases": ["1935 Constitution", "the 1935 Constitution"],
    },
    "constitution_1973": {
        "canonical_name": "1973 Constitution",
        "aliases": ["1973 Constitution", "the 1973 Constitution",
                    "the Freedom Constitution"],
    },
    "act_136_1901": {
        "canonical_name": "Act 136 of 1901 (Judiciary Law)",
        "aliases": ["Act 136 of 1901", "Act No. 136", "the Judiciary Law",
                    "Act 136 of 1901 (Judiciary Law)"],
    },
    "unclos": {
        "canonical_name": "UNCLOS (UN Convention on the Law of the Sea)",
        "aliases": ["UNCLOS", "UN Convention on the Law of the Sea",
                    "Law of the Sea Convention", "1982 UNCLOS"],
    },
    "ra_8371_ipra": {
        "canonical_name": "RA 8371 (Indigenous Peoples' Rights Act, 1997)",
        "aliases": ["RA 8371", "Republic Act 8371",
                    "Indigenous Peoples' Rights Act", "IPRA",
                    "Indigenous Peoples' Rights Act of 1997"],
    },
    "ra_7659_death_penalty": {
        "canonical_name": "RA 7659 (Death Penalty Law, 1993)",
        "aliases": ["RA 7659", "Republic Act 7659", "Death Penalty Law"],
    },
    "ra_2630_repatriation": {
        "canonical_name": "RA 2630 (Repatriation Act)",
        "aliases": ["RA 2630", "Republic Act 2630"],
    },
    "ra_7941_party_list": {
        "canonical_name": "RA 7941 (Party-List Act)",
        "aliases": ["RA 7941", "Republic Act 7941", "Party-List Act",
                    "Party-list Law"],
    },
    "rome_statute": {
        "canonical_name": "Rome Statute (ICC)",
        "aliases": ["Rome Statute", "the Rome Statute"],
    },
    "ca_63_citizenship": {
        "canonical_name": "Commonwealth Act 63 (Citizenship Loss/Reacquisition)",
        "aliases": ["Commonwealth Act 63", "CA 63"],
    },
    "ra_8792_eca": {
        "canonical_name": "RA 8792 (Electronic Commerce Act, 2000)",
        "aliases": ["Republic Act No. 8792", "RA 8792",
                    "Electronic Commerce Act", "ECA"],
    },
    "matt_22_34_40": {
        "canonical_name": "Matthew 22:34-40 (Greatest Commandment)",
        "aliases": ["Matthew 22:34-40", "Mt 22:34-40"],
    },
    "rom_8_28": {
        "canonical_name": "Romans 8:28",
        "aliases": ["Romans 8:28", "Rom 8:28"],
    },
    "isa_55_8_9": {
        "canonical_name": "Isaiah 55:8-9",
        "aliases": ["Isaiah 55:8-9", "Isa 55:8-9"],
    },
}

if __name__ == "__main__":
    print(f"People canonical entries: {len(PEOPLE_ALIASES)}")
    print(f"Case canonical entries: {len(CASE_ALIASES)}")
    print(f"Law canonical entries: {len(LAW_ALIASES)}")
    total_aliases = sum(len(v['aliases']) for v in PEOPLE_ALIASES.values())
    total_aliases += sum(len(v['aliases']) for v in CASE_ALIASES.values())
    total_aliases += sum(len(v['aliases']) for v in LAW_ALIASES.values())
    print(f"Total alias variants: {total_aliases}")
