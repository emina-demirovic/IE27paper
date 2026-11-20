# Lokalna procena trajanja

## V2: proveravanje neviđenih porodica

```sh
python3 demonstracija_v2.py
python3 proceni.py primeri_v2/test_svm_veci.py --baza podaci/v2/kalibracija.json
python3 proceni.py /putanja/do/moj_fajl.py --baza podaci/v2/kalibracija.json --detalji
```

Bez `--detalji` stdout ostaje samo broj sekundi. Sa tom opcijom dobija se JSON
sa procenom, odvojenim overhead/compute komponentama, empirijskim opsegom,
statički izdvojenim parametrima i razlozima za nisku pouzdanost. Izvor se ne
izvršava niti uvozi. Postojeće baze ostaju nezavisne; V2 se bira preko `--baza`.

V2 demonstracija pravi 46 kalibracionih konfiguracija (svaka 3 puta), dva
overhead testa (svaki 5 puta) i 17 finalnih konfiguracija (svaka 5 puta).
Sva izvršavanja su sekvencijalna, u novim procesima, sa jednom numeričkom niti.
Obuhvaćeni su logistička regresija, stablo, šuma, SGD, SVM, K-means i MLP.
Boosting i PCA uopšte nemaju svoje kalibracione konfiguracije. Završni testovi
imaju nove otiske i ne ulaze u obuku ni izbor hiperparametara. Duži trening
primeri su uključeni unapred; demonstracija ne podešava modele nakon rezultata.

Prvih pet konfiguracija svake porodice menja jedan faktor u odnosu na osnovu:
broj uzoraka, broj karakteristika, efektivni parametar rada ili broj ponavljanja.
Kod SVM-a dodatno varira n, jer broj stabala ili iteracija SGD-a za njega nema
isto značenje. Dodate su konfiguracije CV-a, skaliranja i dužeg treninga.
Za MLP su isključeni rani prekidi zbog stagnacije (`tol=0`, veliki
`n_iter_no_change`), pa broj epoha zaista pravi razliku u obimu rada. To je
izmena eksperimentalnog protokola u odnosu na prethodnu demonstraciju.

### Šta model radi

`ml_v2.py` parsira konstruktore, literalne konstante, završni poziv funkcije
(i jednostavan main guard), dimenzije `make_classification`, CV i spoljne
`range` petlje koje obuhvataju `fit`. Podržani su import aliasi. Ne evaluira
dinamički Python. Nepoznati podaci, višestruki konstruktori i pozicioni
parametri konstruktora prijavljuju se kao ograničenja.

Iz tih podataka pravi grube pokazatelje računanja (npr. broj stabala i
prolazaka kroz podatke, kvadratni broj parova za SVM, veze i epohe MLP-a).
To nisu tačni brojevi operacija ni tvrdnje da svaka implementacija ima istu
složenost. Konvergencija, solver, raspodela podataka i C mogu menjati stvarno
trajanje. Skaliranje se prepoznaje u profilu, ali nema zaseban naučen
koeficijent. V2 nije interpreter svih Python programa.

Posebno se mere prazan Python i Python sa zajedničkim sklearn importima bez
pokretanja eksperimenta. Model koristi medijanu drugog merenja kao približan
fiksni overhead. Različiti importi mogu imati drugačiji trošak. Ostatak cilja
je ukupno vreme minus taj overhead, ograničen odozdo na 2 ms zbog šuma.
Regresija logaritma tog ostatka koristi logaritme pokazatelja obima rada sa
fiksnom regularizacijom alpha=3. Postoje regresije po poznatoj porodici i
zajednička regresija za nepoznate porodice. Overhead se dodaje na kraju.

### Pošteno poređenje

Za svaki finalni test postoje dve V2 procene: sa poznatom porodicom i LOFO
(leave-one-family-out). LOFO model, uključujući računanje njegovog empirijskog
opsega, nema nijedno merenje porodice tog testa. Ovo znači izostavljanje iz
određenog modela, a ne da proces te porodice nikada nije pokrenut za druge
modele. Boosting i PCA nisu korišćeni ni u jednom trening skupu.

Poredimo sa V1 metodom ponovo obučenom na istom dozvoljenom skupu i konstantom
jednakom medijani trajanja konfiguracija tog skupa. JSON čuva i predikciju
starog zamrznutog V1 modela. Svi modeli i sve finalne procene zapisani su pre
prvog kontrolnog izvršavanja. Rezultati se ne vraćaju u fit. Konačni produkcioni
model koristi svih 46 kalibracionih konfiguracija, ali nijedan finalni test.

Opseg se računa iz 90. percentila apsolutne log greške unutrašnjeg izostavljanja
porodica, uz dodatno proširenje za ekstrapolaciju/nepodržan izvor. To je
empirijski pokazatelj nesigurnosti, **nije garantovani 90% interval**.
Neviđena porodica uvek dobija `confidence=low`. Ni poznata porodica ne dobija
oznaku visoke pouzdanosti. Za dinamičke ulaze prikazana tačka je samo fallback.

Rezultati su u `REZULTATI_V2.md`, a plan, sva trajanja, upozorenja, modeli po
izostavljenoj porodici, zamrznute procene i okruženje u `podaci/v2/`.
`python3 demonstracija_v2.py --resume` nastavlja prekinut isti plan i iste
verzije izvora koristeći sačuvana merenja. Obično pokretanje ponovo meri sve.

## ML eksperimenti

```sh
python3 demonstracija_ml.py
python3 demonstracija_ml_teski.py
python3 proceni.py primeri_ml/svm_veliki.py --baza podaci/ml/kalibracija.json
python3 proceni.py /putanja/do/moj_cetvrti.py --baza podaci/ml/kalibracija.json
```

ML demonstracija zahteva lokalno instalirane NumPy i scikit-learn. Verzije
stvarnog izvršavanja beleže se u `podaci/ml/okruzenje.json`. Ne preuzima podatke:
svaki proces generiše klasifikacioni skup sa fiksnim seed-om, deli podatke,
trenira i izvršava predikciju (PCA radi transformaciju). K-means koristi isti
skup bez oznaka. Sve skripte na kraju pozivaju `experiment(...)`.

16 trening konfiguracija četiri algoritma meri se po tri puta. Potom se jednom
trenira ridge regresija logaritma trajanja sa fiksnim alpha=10. Karakteristike
su logaritmi literalnih ulaznih parametara, prisustvo API poziva i AST brojači.
Trening primeri menjaju nekoliko parametara zajedno: ovo je praktičan mali
benchmark, ne izolovana analiza uzročnog uticaja svakog parametra.

21 test obuhvata nove ulaze i parametre, ekstrapolaciju, CV sa pet podela,
pet ponavljanja treninga, kao i sedam potpuno neviđenih porodica algoritama:
SVM, KNN, K-means, PCA, MLP, histogram boosting i Naive Bayes.
Svi test otisci su novi; nijedan njihov rezultat ne ulazi u fit. Sve procene
su trajno zapisane u `podaci/ml/procene_pre_testova.json` pre prvog kontrolnog
procesa. Svaka konfiguracija se zatim izvršava pet puta. Test rezultati se
nikada ne vraćaju u kalibraciju niti se prema njima podešavaju hiperparametri.

`demonstracija_ml_teski.py` dodaje dva veća testa: SVM sa 30.000 uzoraka i
80 karakteristika i MLP sa 20.000 uzoraka, 100 karakteristika i 200 iteracija.
Koristi prethodno sačuvan model bez ponovnog treniranja. Obe dodatne procene
čuva pre bilo kog dodatnog izvršavanja, pa meri po pet procesa. Objedinjena
tabela ima 23 reda; dodaje i poređenje sa konstantnom procenom jednakom
medijani trening trajanja. Ova dva testa izabrana su nakon prvih 21 rezultata
da provere duže poslove, ali nijedan njihov rezultat nije korišćen za obuku.
Za reprodukciju cele tabele pokrenuti obe komande redom; druga može trajati
nekoliko minuta. Samo prva komanda ponovo generiše tabelu sa 21 redom.

`REZULTATI_ML.md` sadrži tabelu, `podaci/ml/plan.json` sve parametre, a
`podaci/ml/rezultati.json` svih pet trajanja i stderr svakog izvršavanja.
U tabeli je i procena starog modela iz `podaci/kalibracija.json`, ako je prethodno
pokrenuta osnovna demonstracija; u suprotnom taj estimator koristi default 1 s.

Izvršavanje je lokalno i sekvencijalno. `n_jobs=1` i promenljive za BLAS/OpenMP
ograničavaju interne numeričke niti na jednu. Ukupno trajanje uključuje novi
Python proces, import biblioteka, generisanje podataka, fit, predict/transform
i završetak. Zato import može dominirati kod malih zadataka. Ne meri se samo
`fit()`. Konvergencijska upozorenja čuvaju se: dostizanje zadatog broja iteracija
ne znači da je model konvergirao. Cilj je trajanje, ne kvalitet predikcije.

Ovaj estimator ne razume proizvoljnu semantiku Python programa. Za neviđene
API-je indikatorske karakteristike nemaju naučenu težinu. Ne može zaključiti
kompleksnost novog algoritma samo iz njegovog naziva. Ulazne parametre čita iz
literalnog završnog poziva lokalno definisane funkcije; za drugačiji stil koda
nedostajuće karakteristike dobijaju podrazumevanu vrednost 1. Rezultati važe za
ovaj mali sintetički benchmark na ovom računaru, ne za sve ML poslove. Nisu
obuhvaćeni GPU, mrežni I/O, veliki podaci sa diska ili duboke mreže.

Osnovna demonstracija i njena baza ostaju nezavisne; za ML model se eksplicitno
koristi `--baza podaci/ml/kalibracija.json`. Poziv procene ne zahteva NumPy ni
scikit-learn: sačuvani koeficijenti se primenjuju u čistom Pythonu.

Python 3.9+; samo standardna biblioteka, bez instalacije paketa, mreže ili
paralelnog izvršavanja. Priloženi `runtime_estimator.py` nije bio dostupan
u sesiji: ovaj modul je samostalna zamenska implementacija.

Iz ovog foldera:

```sh
python3 demonstracija.py
python3 proceni.py primeri/zbir.py
python3 proceni.py /apsolutna/putanja/moj_cetvrti.py
```

Ako je interpreter dostupan kao `python`, iste komande rade i sa `python`.
Na računaru na kojem je projekat napravljen komanda je `python3`.
Putanja ulazne skripte računa se od trenutnog radnog foldera; baza se uvek
nalazi pored projekta. `proceni.py` ispisuje samo broj u sekundama na stdout.
Ne izvršava niti uvozi zadati kod; greške šalje na stderr uz nenulti izlazni kod.

## Tri režima

- `default`: nema istog AST otiska ni obučenog modela; vraća 1.0 s.
- `measured`: medijana svih kalibracionih merenja sa istim AST otiskom i
  argumentima. Komentari i prazni redovi ne menjaju otisak; konstante ga menjaju.
- `model`: linearna regresija `intercept + seconds_per_n * n`, sa rezultatom
  ograničenim odozdo na nulu. Fit koristi medijanu tri merenja po trening
  konfiguraciji zbira kvadrata. Stvarna vrednost `n` iz završnog poziva
  prosleđuje se kao `args`. Podržan je i oblik `print(f(n))` i `f(n=...)`.

Za proizvoljan kod ovo je gruba procena, ne pouzdan prediktor. Model ne uči
semantiku algoritma, složenost sortiranja, I/O ili zavisnost od sadržaja ulaza.
Ako literalni `n` nije moguće statički izdvojiti, koristi se `n=0`, odnosno
slobodni član regresije. Nema evaluiranja izraza radi pronalaženja `n`.

## Demonstracija i sačuvani podaci

Svako pokretanje prazni samo `podaci/demo.json`, pa A uvek počinje od nule.
A zatim izvršava ispis pet puta i upisuje merenja. B koristi upravo njihovu
medijanu, a pet novih kontrolnih izvršavanja ne ulazi u kalibraciju. Kopija
sa četiri dodatna komentara takođe ima pet kontrolnih izvršavanja.
Trening izvršava pet konfiguracija zbira kvadrata po tri puta i jednom
poziva `fit()`. C1 i C2 se procenjuju i zapisuju pre njihovih izvršavanja;
sortiranje se ne koristi u treningu. Provere režima su ugrađene u demonstraciju.

Svako merenje koristi nov proces sa istim Python interpreterom i
`time.perf_counter()` oko `subprocess.run()`. Uključuje pokretanje i završetak
procesa. Radni folder procesa je folder skripte, stdout ide u DEVNULL,
stderr se hvata, a neuspešno izvršavanje prekida demonstraciju.
Prikazano stvarno vreme je medijana pet kontrolnih izvršavanja; greška je
apsolutna razlika u sekundama. Vreme procene je trajanje jednog poziva
`estimate()` sa učitanom bazom i modelom, uključujući AST analizu, bez
čitanja fajla i treniranja. Kratka merenja mogu varirati zbog OS raspoređivanja.

- `podaci/kalibracija.json`: model i 20 kalibracionih merenja za `proceni.py`.
- `podaci/demo.json`: odvojena demo baza sa istom konačnom kalibracijom.
- `podaci/procene_pre_C.json`: obe C procene sačuvane pre kontrolnih izvršavanja.
- `podaci/rezultati.json`: sve procene, svih pet kontrolnih trajanja po redu,
  medijane, greške, vremena procene i verzija korišćenog Pythona.
- `podaci/trening/`: generisane obične skripte za trening.

Ponovna demonstracija obnavlja kalibraciju za ovaj računar. Kontrolna merenja
C ne dodaju se u bazu, tako da `proceni.py primeri/zbir.py` i dalje koristi model.

Provere:

```sh
python3 -m unittest -v
```

## Veći test nepoznatog koda

Pokreni `python3 veliki_test.py` za svih 128 skripti ili otvori
[izmerene rezultate](REZULTATI_NEPOZNAT.md). Skripta koristi postojeće lokalne
kalibracije iz osnovne i V2 demonstracije. Za svoj fajl koristi:

```sh
python3 proceni.py /putanja/do/fajla.py --baza podaci/nepoznat/model.json
```

Testira se 16 ručno pisanih računanja sa po šest parova dimenzija i osam novih
sklearn klasa sa po četiri konfiguracije. To su nova tela i klase, uz srodne
operacije i algoritme u staroj kalibraciji. Svaka skripta poziva svoju funkciju.
Izvor i otisak svake skripte, sve zamrznute procene i po pet pojedinačnih
trajanja nalaze se u `podaci/nepoznat/`.

Metoda prenosi cenu jedne Python iteracije iz prethodnog merenja zbira kvadrata,
trošak po elementu iz SGD-a i logističke regresije i cenu dodatnog člana
ansambla iz slučajne šume. Koristi zajednički izmereni startup za sklearn.
Za direktni završni poziv prepoznaje jednostavne numeričke argumente i
ugnježdene range petlje. Dinamičke granice, pomoćne funkcije, vektorizovane
operacije i trošak drugih biblioteka mogu ostati neobuhvaćeni. Uz nepoznate
granice aproksimira prolazak kao jednu iteraciju. V2 i ML konstanta služe kao
raniji modeli za poređenje, a startup poređenje izoluje dobit od brojanja rada.

## V3 — procena po fazama

Iz ovog foldera, sa isporučenom kalibracijom:

```sh
python3 proceni.py moj_fajl.py --baza podaci/faze/model.json
python3 proceni.py moj_fajl.py --baza podaci/faze/model.json --detalji
```

Detalji sadrže procene za start/import, pripremu podataka, skaliranje, trening,
predikciju i rad u Pythonu. Prikazane su faze pronađene u izvoru. Za
ansamble se vide osnovni model, broj članova, redovi nakon trening podele,
redovi po članu i efektivni broj kolona. Zbir faza daje procenu trajanja.

Kalibracija koristi lokalne Python mikromere i nenegativnu regresiju za cenu
petlje, aritmetike, ostatka, indeksiranja, rada sa rečnikom, alokacije,
sortiranja i poziva. Za sortiranje koristi približno n log₂ n jedinica rada.
ML faze mere se zasebno unutar poznatih kalibracionih skripti. Vremena su
izmerena za tri veličine podataka i tri osnovna modela po tri puta. Trošak
stabla približava se proizvodom broja članova, redova po članu, ispitanih
kolona i dubine (ograničene sa log₂ broja redova). Za linearan fit koristi
se proizvod redova i kolona. Koeficijenti su specifični za ovu mašinu.

Analiza prati direktne funkcije i jednostavne metode, aliase i male pomoćne
.py module u istom folderu. Za podržani loadtxt/genfromtxt poziv po potrebi
broji redove i kolone jednostavnog numeričkog CSV-a do 16 MB iz istog foldera.
Ovo dodaje I/O u vreme procene. Ciljni Python kod i pomoćni moduli se samo
parsiraju. Dinamički oblici, while petlje, složene bibliotečke metode,
skrivena konvergencija i neprepoznati pozivi mogu doneti veliku grešku.
Za prepoznate neizvesnosti --detalji ispisuje unresolved i, kada postoje
podaci, istorijsku medijanu i 90. percentil apsolutne procentualne greške
za nerešene slučajeve iz odgovarajuće grupe razvojnog skupa. To nisu
granice trajanja konkretnog novog fajla.

Za reprodukciju kompletne kalibracije i obe završne provere redom:

```sh
python3 demonstracija_faze.py
python3 provera_novih_programa.py
```

[Kompletna tabela](REZULTATI_FAZE.md) uključuje rezultate po grupi, MAE u
sekundama i broj slučajeva sa stvarnim trajanjem preko dvostruke procene.
Sirove kalibracije, procene sačuvane pre izvršavanja i svih pet kontrola
su u podaci/faze/ i podaci/faze/nezavisni/. Rezultati probne serije su
odvojeni u podaci/faze/proba/.
