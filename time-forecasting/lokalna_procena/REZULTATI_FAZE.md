# Procena po fazama

Razvojni skup ima 128 starih merenja. Zasebni završni skupovi imaju 41 i 12 fajlova. Svaka tačka je medijana pet procesa. Oba skupa imaju procene sačuvane pre svojih kontrola. Model koristi iste koeficijente u oba skupa. Trošak procene uključuje statičku analizu i, gde je primenljivo, pregled dimenzija lokalnog CSV-a.

Skup od 41 fajla obuhvata nove konfiguracije, uključujući obrasce pregledane u probnoj seriji. Poslednjih 12 fajlova iz šest novih tela koristi zaseban izvor i nove porodice računanja. Kalibracione ML klase su DecisionTreeClassifier, ExtraTreeClassifier i LogisticRegression. Procena ansambala koristi kalibraciju osnovnih stabala. Skup je sintetički, sa fiksnim seed-om i jednom numeričkom niti.

| Skup | Grupa | Broj | Metoda | MAE [s] | MAPE [%] | Stvarno > 2 × procena |
|---|---|---:|---|---:|---:|---:|
| Razvojni | Python | 96 | route | 0.0142 | 22.2 | 5 |
| Razvojni | Python | 96 | v3 | 0.0194 | 22.2 | 4 |
| Razvojni | sklearn | 32 | route | 0.4678 | 12.1 | 2 |
| Razvojni | sklearn | 32 | v3 | 0.2508 | 10.7 | 0 |
| Razvojni | svi | 128 | route | 0.1276 | 19.7 | 7 |
| Razvojni | svi | 128 | v3 | 0.0772 | 19.3 | 4 |
| Nove konfiguracije | Python | 18 | route | 0.2315 | 50.5 | 9 |
| Nove konfiguracije | Python | 18 | v3 | 0.0262 | 11.4 | 0 |
| Nove konfiguracije | sklearn | 23 | route | 0.4059 | 19.0 | 2 |
| Nove konfiguracije | sklearn | 23 | v3 | 0.5420 | 31.4 | 0 |
| Nove konfiguracije | svi | 41 | route | 0.3293 | 32.8 | 11 |
| Nove konfiguracije | svi | 41 | v3 | 0.3156 | 22.6 | 0 |
| Nezavisna tela | Python | 6 | route | 0.0380 | 42.5 | 2 |
| Nezavisna tela | Python | 6 | v3 | 0.0509 | 71.5 | 1 |
| Nezavisna tela | sklearn | 6 | route | 0.1828 | 15.1 | 0 |
| Nezavisna tela | sklearn | 6 | v3 | 0.1991 | 17.0 | 1 |
| Nezavisna tela | svi | 12 | route | 0.1104 | 28.8 | 2 |
| Nezavisna tela | svi | 12 | v3 | 0.1250 | 44.2 | 2 |
| Svi završni | Python | 24 | route | 0.1832 | 48.5 | 11 |
| Svi završni | Python | 24 | v3 | 0.0324 | 26.4 | 1 |
| Svi završni | sklearn | 29 | route | 0.3597 | 18.1 | 2 |
| Svi završni | sklearn | 29 | v3 | 0.4711 | 28.4 | 1 |
| Svi završni | svi | 53 | route | 0.2798 | 31.9 | 13 |
| Svi završni | svi | 53 | v3 | 0.2724 | 27.5 | 2 |

Route bira raniju statičku procenu za Python i V2 Ridge za sklearn. V3 procenjuje svaku fazu i sabira trajanja.

| Skripta | Grupa | V3 [s] | Route [s] | Statički [s] | Ridge [s] | Izmereno [s] | Aps. greška V3 [s] | Procena [ms] |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| transition_counts_19000 | Python | 0.0124 | 0.0113 | 0.0113 | 0.7758 | 0.0130 | 0.0007 | 0.108 |
| scaled_ridge_2100 | sklearn | 0.7580 | 0.7759 | 0.7721 | 0.7759 | 0.8097 | 0.0517 | 0.136 |
| transition_counts_155000 | Python | 0.0182 | 0.0149 | 0.0149 | 0.7758 | 0.0195 | 0.0013 | 0.103 |
| block_order_19000 | Python | 0.0127 | 0.0113 | 0.0113 | 0.7758 | 0.0131 | 0.0004 | 0.098 |
| scratch_space_155000 | Python | 0.0386 | 0.0149 | 0.0149 | 0.7758 | 0.0302 | 0.0084 | 0.101 |
| bag_reg_2100 | sklearn | 0.7964 | 0.7759 | 0.7912 | 0.7759 | 0.9082 | 0.1117 | 0.137 |
| spectral_bins_450000 | Python | 0.0474 | 0.0228 | 0.0228 | 0.7758 | 0.0323 | 0.0150 | 0.111 |
| opaque_svr_7200 | sklearn | 0.7654 | 0.7759 | 0.7944 | 0.7759 | 0.8001 | 0.0348 | 0.132 |
| block_order_450000 | Python | 0.0438 | 0.0228 | 0.0228 | 0.7758 | 0.0482 | 0.0044 | 0.119 |
| bag_reg_14500 | sklearn | 9.5338 | 0.7759 | 2.0216 | 0.7759 | 5.5159 | 4.0180 | 0.189 |
| class_distance_19000 | Python | 0.0315 | 0.0108 | 0.0108 | 0.7758 | 0.0313 | 0.0002 | 0.119 |
| csv_bag_35 | sklearn | 1.7021 | 0.8270 | 0.7981 | 0.8270 | 1.5030 | 0.1991 | 0.940 |
| mixture_diag_14500 | sklearn | 0.7847 | 0.7759 | 0.8523 | 0.7759 | 0.9368 | 0.1521 | 0.124 |
| extra_reg_14500 | sklearn | 6.4143 | 0.7759 | 2.0216 | 0.7759 | 1.4068 | 5.0076 | 0.129 |
| spectral_bins_19000 | Python | 0.0131 | 0.0113 | 0.0113 | 0.7758 | 0.0130 | 0.0001 | 0.102 |
| latent_pls_7200 | sklearn | 0.7654 | 0.7759 | 0.7944 | 0.7759 | 0.7612 | 0.0042 | 0.124 |
| latent_pls_14500 | sklearn | 0.7847 | 0.7759 | 0.8523 | 0.7759 | 0.7608 | 0.0238 | 0.145 |
| bag_reg_7200 | sklearn | 1.7678 | 0.7759 | 1.0110 | 0.7759 | 1.4526 | 0.3153 | 0.143 |
| scratch_space_450000 | Python | 0.1050 | 0.0228 | 0.0228 | 0.7758 | 0.0884 | 0.0166 | 0.131 |
| opaque_svr_14500 | sklearn | 0.7847 | 0.7759 | 0.8523 | 0.7759 | 0.8011 | 0.0164 | 0.138 |
| cross_moment_19000 | Python | 0.0324 | 0.0108 | 0.0108 | 0.7758 | 0.0338 | 0.0014 | 0.193 |
| spectral_bins_155000 | Python | 0.0239 | 0.0149 | 0.0149 | 0.7758 | 0.0194 | 0.0045 | 0.103 |
| transition_counts_450000 | Python | 0.0307 | 0.0228 | 0.0228 | 0.7758 | 0.0336 | 0.0030 | 0.103 |
| class_distance_155000 | Python | 0.3354 | 0.0108 | 0.0108 | 0.7758 | 0.3090 | 0.0263 | 0.122 |
| cross_moment_450000 | Python | 1.7010 | 0.0108 | 0.0108 | 0.7758 | 1.8777 | 0.1768 | 0.212 |
| scaled_ridge_14500 | sklearn | 0.7877 | 0.7759 | 0.8523 | 0.7759 | 0.8000 | 0.0123 | 0.132 |
| csv_bag_85 | sklearn | 3.0217 | 0.8270 | 0.7981 | 0.8270 | 2.0609 | 0.9608 | 0.889 |
| extra_reg_2100 | sklearn | 0.8565 | 0.7759 | 0.7912 | 0.7759 | 0.8810 | 0.0245 | 0.136 |
| isolation_14500 | sklearn | 0.7845 | 0.7759 | 2.0216 | 0.7759 | 0.8991 | 0.1146 | 0.123 |
| extra_reg_7200 | sklearn | 1.8321 | 0.7759 | 1.0110 | 0.7759 | 0.9870 | 0.8450 | 0.125 |
| block_order_155000 | Python | 0.0220 | 0.0149 | 0.0149 | 0.7758 | 0.0239 | 0.0018 | 0.096 |
| cross_moment_155000 | Python | 0.3501 | 0.0108 | 0.0108 | 0.7758 | 0.3803 | 0.0302 | 0.170 |
| scaled_ridge_7200 | sklearn | 0.7663 | 0.7759 | 0.7944 | 0.7759 | 0.7906 | 0.0243 | 0.135 |
| class_distance_450000 | Python | 1.6273 | 0.0108 | 0.0108 | 0.7758 | 1.4474 | 0.1799 | 0.125 |
| opaque_svr_2100 | sklearn | 0.7579 | 0.7759 | 0.7721 | 0.7759 | 0.7881 | 0.0303 | 0.156 |
| mixture_diag_2100 | sklearn | 0.7579 | 0.7759 | 0.7721 | 0.7759 | 0.8998 | 0.1419 | 0.127 |
| isolation_2100 | sklearn | 0.7584 | 0.7759 | 0.7912 | 0.7759 | 0.8718 | 0.1135 | 0.125 |
| latent_pls_2100 | sklearn | 0.7579 | 0.7759 | 0.7721 | 0.7759 | 0.7557 | 0.0021 | 0.144 |
| mixture_diag_7200 | sklearn | 0.7654 | 0.7759 | 0.7944 | 0.7759 | 0.9167 | 0.1513 | 0.126 |
| isolation_7200 | sklearn | 0.7656 | 0.7759 | 1.0110 | 0.7759 | 0.8765 | 0.1109 | 0.123 |
| scratch_space_19000 | Python | 0.0145 | 0.0113 | 0.0113 | 0.7758 | 0.0138 | 0.0006 | 0.100 |
| prefix_queries_20000 | Python | 0.0176 | 0.0118 | 0.0118 | 0.7758 | 0.0129 | 0.0046 | 0.240 |
| prefix_queries_350000 | Python | 0.1161 | 0.0294 | 0.0294 | 0.7758 | 0.0468 | 0.0693 | 0.159 |
| levenshtein_140 | Python | 0.0162 | 0.0113 | 0.0113 | 0.7758 | 0.0135 | 0.0027 | 0.167 |
| levenshtein_700 | Python | 0.1265 | 0.0239 | 0.0239 | 0.7758 | 0.0631 | 0.0634 | 0.157 |
| binary_lookup_12000 | Python | 0.0120 | 0.0111 | 0.0111 | 0.7758 | 0.0185 | 0.0065 | 0.129 |
| binary_lookup_210000 | Python | 0.0183 | 0.0164 | 0.0164 | 0.7758 | 0.1773 | 0.1589 | 0.127 |
| random_projection_3500 | sklearn | 0.7675 | 0.7758 | 0.7974 | 0.7758 | 0.7164 | 0.0511 | 0.120 |
| random_projection_28000 | sklearn | 0.8459 | 0.7758 | 1.0053 | 0.7758 | 0.7275 | 0.1184 | 0.114 |
| covariance_4000 | sklearn | 0.7670 | 0.7758 | 0.7942 | 0.7758 | 0.8046 | 0.0377 | 0.122 |
| covariance_24000 | sklearn | 0.8202 | 0.7758 | 0.9268 | 0.7758 | 0.8028 | 0.0173 | 0.120 |
| optics_450 | sklearn | 0.7566 | 0.7758 | 0.7685 | 0.7758 | 0.9623 | 0.2056 | 0.114 |
| optics_3200 | sklearn | 0.7586 | 0.7758 | 0.7736 | 0.7758 | 1.5228 | 0.7642 | 0.132 |
