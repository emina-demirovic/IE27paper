# Svi rezultati ML eksperimenata

Stvarno vreme: medijana pet procesa. Greška: apsolutna. Model je zamrznut pre testova.

| Fajl | Scenario | Režim | n × d | Procena [s] | Stara [s] | Izmereno [s] | Greška [s] | Greška [%] | Procena [ms] |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|
| logreg_novi_ulaz.py | novi parametri | model | 4000 × 40 | 0.8208 | 0.0103 | 0.7871 | 0.0337 | 4.3 | 0.784 |
| logreg_ekstrapolacija.py | van trening opsega | model | 16000 × 100 | 0.9058 | 0.0106 | 0.8269 | 0.0789 | 9.5 | 0.757 |
| tree_dubina_3.py | novi parametri | model | 5000 × 40 | 0.9420 | 0.0103 | 0.8588 | 0.0833 | 9.7 | 0.738 |
| tree_dubina_25.py | novi parametri | model | 5000 × 40 | 1.0428 | 0.0103 | 0.9422 | 0.1005 | 10.7 | 0.730 |
| forest_15.py | novi parametri | model | 4000 × 30 | 1.2463 | 0.0103 | 0.9353 | 0.3110 | 33.3 | 0.753 |
| forest_100.py | novi parametri | model | 4000 × 30 | 1.3765 | 0.0103 | 1.3425 | 0.0340 | 2.5 | 0.746 |
| sgd_iter_20.py | novi parametri | model | 5000 × 40 | 0.7986 | 0.0103 | 0.7885 | 0.0101 | 1.3 | 0.741 |
| sgd_iter_300.py | novi parametri | model | 5000 × 40 | 0.9190 | 0.0103 | 0.8330 | 0.0860 | 10.3 | 0.775 |
| logreg_cv5.py | novi tok: CV=5 | model | 4000 × 30 | 1.0832 | 0.0103 | 0.7939 | 0.2893 | 36.4 | 0.754 |
| logreg_ponovi5.py | novi tok: ponovi=5 | model | 4000 × 30 | 0.7290 | 0.0103 | 0.8042 | 0.0752 | 9.4 | 0.756 |
| svm_mali.py | neviđen algoritam | model | 1500 × 20 | 0.9320 | 0.0102 | 0.7974 | 0.1346 | 16.9 | 0.733 |
| svm_veliki.py | neviđen algoritam | model | 8000 × 60 | 1.0040 | 0.0104 | 1.1425 | 0.1385 | 12.1 | 0.725 |
| knn_mali.py | neviđen algoritam | model | 2000 × 10 | 0.9181 | 0.0103 | 0.8095 | 0.1086 | 13.4 | 0.745 |
| knn_veliki.py | neviđen algoritam | model | 12000 × 80 | 1.0231 | 0.0105 | 0.8932 | 0.1299 | 14.5 | 0.725 |
| kmeans_4.py | neviđen algoritam | model | 5000 × 30 | 0.9709 | 0.0103 | 0.9047 | 0.0662 | 7.3 | 0.750 |
| kmeans_32.py | neviđen algoritam | model | 5000 × 30 | 0.9709 | 0.0103 | 0.9345 | 0.0363 | 3.9 | 0.736 |
| pca.py | neviđen algoritam | model | 8000 × 120 | 1.0167 | 0.0104 | 0.8353 | 0.1814 | 21.7 | 0.739 |
| mlp_20.py | neviđen algoritam | model | 3000 × 30 | 0.8832 | 0.0103 | 0.8031 | 0.0801 | 10.0 | 0.758 |
| mlp_100.py | neviđen algoritam | model | 3000 × 30 | 0.9595 | 0.0103 | 0.9772 | 0.0177 | 1.8 | 0.750 |
| boost.py | neviđen algoritam | model | 6000 × 40 | 1.0052 | 0.0104 | 1.2041 | 0.1989 | 16.5 | 0.732 |
| naive_bayes.py | neviđen algoritam | model | 8000 × 60 | 1.0040 | 0.0104 | 0.7647 | 0.2393 | 31.3 | 0.708 |
| svm_30000.py | neviđen algoritam — veliki | model | 30000 × 80 | 1.0450 | 0.0110 | 4.0252 | 2.9802 | 74.0 | 0.766 |
| mlp_20000.py | neviđen algoritam — veliki | model | 20000 × 100 | 1.0814 | 0.0107 | 1.4604 | 0.3790 | 26.0 | 0.737 |

Konstantna procena (medijana trening merenja): 0.8379 s.

| Grupa | Broj | Model MAPE [%] | Konstantna procena MAPE [%] |
|---|---:|---:|---:|
| svi | 23 | 16.4 | 14.2 |
| poznate porodice | 10 | 12.7 | 8.6 |
| neviđene porodice | 13 | 19.2 | 18.5 |
| veliki neviđeni | 2 | 50.0 | 60.9 |

MAPE je srednja apsolutna procentualna greška, nije garancija za budući kod.
Veliki testovi nisu korišćeni za promenu modela. Njihove procene su zamrznute zajedno pre oba izvršavanja.
