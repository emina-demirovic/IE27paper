# V2: procena novih ML zadataka

Svi redovi su model procene za prethodno neizvršene finalne fajlove. LOFO model nikada ne dobija merenja porodice iz svog reda. Medijana pet novih procesa uključuje pokretanje, import, podatke, fit i predikciju.

| Fajl | Scenario | V2 LOFO [s] | V1 isti trening [s] | Konstanta [s] | V2 poznata porodica [s] | Stvarno [s] | LOFO greška [s] | LOFO greška [%] | Empirijski opseg [s] | Procena [ms] |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| test_logreg_novi.py | novi parametri | 0.905 | 3.694 | 0.903 | 0.782 | 0.795 | 0.111 | 13.9 | 0.670–1.223 | 0.350 |
| test_logreg_veci.py | ekstrapolacija | 1.538 | 10.863 | 0.903 | 0.808 | 0.823 | 0.715 | 86.8 | 0.569–4.156 | 0.339 |
| test_tree_novi.py | novi parametri | 0.812 | 4.166 | 0.889 | 0.900 | 0.912 | 0.099 | 10.9 | 0.599–1.102 | 0.337 |
| test_tree_veci.py | ekstrapolacija | 1.025 | 10.594 | 0.889 | 1.041 | 1.839 | 0.814 | 44.3 | 0.378–2.780 | 0.337 |
| test_forest_novi.py | novi parametri | 0.832 | 1.419 | 0.848 | 1.346 | 1.283 | 0.451 | 35.1 | 0.660–1.050 | 0.344 |
| test_forest_veci.py | ekstrapolacija | 1.006 | 2.146 | 0.848 | 5.201 | 7.317 | 6.311 | 86.3 | 0.399–2.537 | 0.343 |
| test_sgd_novi.py | novi parametri | 0.875 | 3.507 | 0.897 | 0.800 | 0.796 | 0.078 | 9.8 | 0.673–1.137 | 0.340 |
| test_sgd_veci.py | ekstrapolacija | 1.394 | 10.261 | 0.897 | 0.835 | 0.926 | 0.468 | 50.6 | 0.536–3.623 | 0.344 |
| test_svm_novi.py | novi parametri | 0.940 | 3.422 | 0.857 | 0.965 | 0.898 | 0.042 | 4.7 | 0.703–1.258 | 0.334 |
| test_svm_veci.py | ekstrapolacija | 1.815 | 9.619 | 0.857 | 1.988 | 2.871 | 1.055 | 36.8 | 0.679–4.857 | 0.335 |
| test_kmeans_novi.py | novi parametri | 0.915 | 4.885 | 0.850 | 0.920 | 0.923 | 0.008 | 0.9 | 0.695–1.204 | 0.343 |
| test_kmeans_veci.py | ekstrapolacija | 1.810 | 14.741 | 0.850 | 0.925 | 1.274 | 0.536 | 42.0 | 0.688–4.764 | 0.344 |
| test_mlp_novi.py | novi parametri | 0.996 | 3.433 | 0.853 | 0.936 | 0.998 | 0.002 | 0.2 | 0.739–1.344 | 0.358 |
| test_mlp_veci.py | ekstrapolacija | 1.931 | 9.914 | 0.853 | 2.099 | 3.016 | 1.085 | 36.0 | 0.716–5.208 | 0.353 |
| test_logreg_cv5.py | novi tok | 1.694 | 2.310 | 0.903 | 0.820 | 0.812 | 0.882 | 108.6 | 0.627–4.577 | 0.343 |
| test_boost_nikad.py | potpuno izostavljena porodica | 1.248 | 2.752 | 0.857 | 1.248 | 1.652 | 0.404 | 24.5 | 0.940–1.657 | 0.341 |
| test_pca_nikad.py | potpuno izostavljena porodica | 1.237 | 2.308 | 0.857 | 1.237 | 0.870 | 0.367 | 42.2 | 0.466–3.287 | 0.343 |

| Grupa | V2 LOFO MAPE [%] | V1 isti trening [%] | Konstanta [%] | V2 poznata porodica [%] |
|---|---:|---:|---:|---:|
| svi | 37.3 | 396.4 | 28.1 | 15.4 |
| izostavljene porodice sa kalibracionim parom | 37.8 | 433.8 | 28.6 | 13.0 |
| potpuno izostavljene porodice | 33.3 | 115.9 | 24.9 | 33.3 |

V1 je ista prethodna metoda ponovo obučena na potpuno istom dozvoljenom trening skupu kao LOFO V2. Konstanta je medijana trajanja tog trening skupa. V2 poznata porodica koristi i kalibraciju te porodice, ali nikada finalne testove. Njena kolona nije rezultat za neviđenu porodicu.

Opsezi su empirijski, izvedeni iz unutrašnjeg izostavljanja porodica. Nisu garantovani intervali od 90%. Sve LOFO procene imaju nisku pouzdanost. Stara zamrznuta V1 procena, upozorenja i sva pojedinačna merenja nalaze se u podaci/v2/rezultati.json.
