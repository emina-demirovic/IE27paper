# Poređenje scheduling politika na Danilovom Macu

**Najbolji rezultat na kombinovanom skupu dala je CPU politika sa FIFO grupama od 20 i čekanjem na 99% CPU-a.** U prvom paru bila je 3,21 s sporija od FIFO-a, a u drugom 34,26 s brža. Medijana uštede je **+4,76%**. Dva redosleda su premalo da zaključimo da će politika dosledno pobediti FIFO.

## Test sa Emininim prediktorom

U svakom paru obe politike dobijaju isti redosled od 120 zadataka iz 14 konfiguracija. Skup čine 48 množenja matrica, 48 Random Forest treninga na Wine i 24 Q-learning treninga na CartPole-u. Deset radnika koristi po jednu nit po zadatku (`P = 1`). `B` je budžet niti, a `K` predviđeno trajanje. Ušteda je smanjenje vremena do poslednjeg završenog zadatka.

| Politika i pravilo dodele | B | Par 1 (s) | Par 2 (s) | Medijana uštede prema FIFO-u |
|---|---:|---:|---:|---:|
| V3.1 · najveći K koji staje u budžet prilagođen spoljnom CPU opterećenju | 12 | 279,35 | 301,11 | −9,12% |
| V3.1 · najviše 6 aktivnih matrica | 12 | 251,76 | 295,63 | −2,46% |
| V3.1 · najviše 4 aktivne matrice | 12 | 279,62 | 316,63 | −11,81% |
| FamilyFIFO · čuva FIFO redosled porodica i daje prednost dugim matricama dok su aktivne manje od dve duge | 10 | 300,11 | 312,90 | −10,25% |
| CpuBands · bira po CPU zoni iz celog reda | 10 | 292,53 | 309,33 | −10,18% |
| CpuBands · bira iz trenutne FIFO grupe od 10 | 10 | 245,83 | 297,26 | +1,49% |
| CpuBands · grupa od 20, bonus +3 s za dve duge matrice | 10 | 242,48 | 281,05 | **+4,76%** |
| Ista grupa i bonus, dodela dozvoljena i pri CPU ≥99% | 10 | 251,38 | 296,17 | +0,50% |

FIFO dodeljuje po dolasku. Vremena za parove 1 i 2 bila su **240,52 / 294,90 s** za V3.1, **248,73 / 313,43 s** za FamilyFIFO i **239,27 / 315,32 s** za CpuBands. Varijante sa ograničenjem matrica i FIFO grupama koriste sačuvana referentna merenja.

CpuBands koristi prosek četiri CPU očitavanja na 50 ms. Bira duge zadatke ispod 60%, srednje od 60% i kratke od 87,5%. Od 99% čeka, osim kad su svi radnici slobodni. Bez grupa duge matrice su se nagomilale na kraju. Sa grupama od 20 bonus za matrice 1536² i 1600² promenio je **0 od 240 odluka** pri zabeleženim očitavanjima. Uklanjanje čekanja na 99% produžilo je izvršavanje u oba para, za **8,90 s i 15,12 s**.

## Kako smo došli do ovih pravila

- **V1 / LPT** prvo dodeljuje zadatak sa najvećim K. Na simuliranim trajanjima ušteda prema FIFO-u bila je 28,18–28,53%. Sa Emininim predikcijama za Random Forest i matrice medijane su bile +0,54% za 32 kratka zadatka, −5,10% za 120 kratkih i −3,11% za 120 zahtevnijih (po šest parova). Na zahtevnijem skupu LPT je u svih šest parova skratio vreme od poslednje dodele do kraja, ali je samo dvaput prvi završio ceo skup.
- **V2 / LPT-KP** bira najveći K čiji broj BLAS niti staje u fiksni budžet. Na 115 matričnih zadataka sa različitim P uštede prema LPT-K bile su +5,71%, +5,11% i +1,94% za B od 10, 12 i 16.
- **V3.1 / CPU-LPT-KP** smanjuje raspoloživi budžet prema spoljnom opterećenju. Na istom matričnom testu medijane uštede prema fiksnom V2 bile su sledeće (tri para po uslovu).

| B | Bez generatora opterećenja | Stalno opterećenje | Promenljivo opterećenje |
|---:|---:|---:|---:|
| 10 | −8,45% | −17,82% | −11,94% |
| 12 | −7,04% | −1,76% | −2,76% |
| 14 | +6,19% | −3,15% | −0,89% |
| 16 | +1,23% | +0,19% | −0,41% |

## Šta rezultati znače za prediktor

Na primer, za `m1600x900` K je bio 13,46 s, a medijana izvršavanja uz druge zadatke u grupama od 10 bila je 157,2 s i 190,5 s u dva para. Zato sada čuvamo politiku, budžet, CPU i broj aktivnih matrica pri dodeli. Na dva prethodna izvršavanja izdvojena iz učenja, korekcija K pomoću istorije smanjila je srednju apsolutnu grešku sa **15,02 na 2,90 s** i sa **18,23 na 3,67 s**. Tabela politika koristi ranije, izvorne K vrednosti. Učinak korigovanih predikcija na ukupno vreme tek treba izmeriti. [Podaci po zadatku — attempts.csv](../benchmarks/data/attempts.csv)
