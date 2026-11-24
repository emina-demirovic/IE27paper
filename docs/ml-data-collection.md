# Prikupljanje podataka za predikciju trajanja

Emina i Danilo pokreću po jedan lokalni Coordinator i Worker na svojim računarima. Svako dobija svoj CSV, pa obe datoteke zajedno koristimo za evaluaciju. Dovoljan je lokalni pristup repozitorijumu. Koristite isti Git commit sa skriptom za prikupljanje i numeričkim zadatkom, a svakom fizičkom računaru dodelite različit, stalan `HostId`, npr. `emina-mac` i `danilo-windows`.

Skripta analizira kod iz Git commita, prilaže karakteristike i šalje zadatke jedan po jedan. Coordinator pri dodeli beleži stanje CPU-a i RAM-a. Kad se pokušaj završi, CSV se osveži sa statusom i trajanjem, ako je dostupno. Ključ reda je `experiment_id + attempt`. Kod ponovnog pokušaja nastaje zaseban red.

## Priprema

Potreban je .NET 10 SDK, Git i Python. Sve komande pokrenite iz korena `IE27paper`. U svakom od tri terminala postavite promenljive za svoj sistem i računar.

**macOS** (Terminal)

```bash
data="$HOME/ie27-podaci"
hostId="emina-mac"
workerPython="$data/venv/bin/python"
```

Jednom napravite okruženje i instalirajte zavisnosti:

```bash
mkdir -p "$data"
python3 -m venv "$data/venv"
"$workerPython" -m pip install scikit-learn gymnasium numpy
```

**Windows** (PowerShell)

```powershell
$data = Join-Path $env:USERPROFILE "ie27-podaci"
$hostId = "danilo-windows"
$workerPython = Join-Path $data 'venv\Scripts\python.exe'
```

Jednom napravite okruženje i instalirajte zavisnosti:

```powershell
New-Item -ItemType Directory -Force -Path $data
py -3 -m venv "$data/venv"
& "$workerPython" -m pip install scikit-learn gymnasium numpy
```

## Pokretanje

Komande za .NET su iste na oba sistema. Prva dva terminala ostavite otvorena dok traje serija.

**Terminal 1 — Coordinator**

```text
dotnet run --project src/Coordinator --no-launch-profile -- --urls http://127.0.0.1:5031 "--Coordinator:DatabasePath=$data/coordinator.db" "--Coordinator:ExperimentCsvPath=$data/attempts.csv" --Raft:ClientCommandReplicationEnabled=false
```

**Terminal 2 — Worker**

```text
dotnet run --project src/Worker --no-launch-profile -- "--Worker:Id=${hostId}-worker" "--Worker:HostId=$hostId" --Worker:CoordinatorBaseUrl=http://127.0.0.1:5031 --Worker:ResourceMonitor:Enabled=true --Worker:Executor:Mode=Process "--Worker:Executor:PythonCommand=$workerPython"
```

**Terminal 3 — serija**

Sačekajte prvi brojčani CPU uzorak, približno 5–10 sekundi od registracije Workera. Za prvu proveru pokrenite jednu rundu.

macOS:

```bash
"$workerPython" scripts/collect-experiment-data.py --csv "$data/attempts.csv" --host-id "$hostId" --rounds 1
```

Windows:

```powershell
& "$workerPython" scripts/collect-experiment-data.py --csv "$data/attempts.csv" --host-id "$hostId" --rounds 1
```

Jedna runda daje šest novih završenih eksperimenata, po dve konfiguracije za Random Forest, Q-learning i NumPy množenje matrica. Skripta ispisuje ID, broj pokušaja i trajanje za svaki potvrđeni CSV red. Za dodatna merenja koristite veći `--rounds` i zadržite isti par `coordinator.db` i `attempts.csv`. CSV je izvoz iz lokalne baze.

## Zajednička evaluacija

Po završetku razmenite kopije CSV fajlova. Sačuvajte ih pod različitim imenima, npr. `attempts-emina.csv` i `attempts-danilo.csv`. Prediktor prihvata oba fajla direktno i uklanja duplikate po ključu pokušaja:

```bash
python3 src/ML/runtime_predictor.py attempts-emina.csv attempts-danilo.csv
```

U PowerShellu koristite `py -3` umesto `python3`. Za poređenje računara pokrenite iste konfiguracije i isti broj rundi na oba. Dobijene greške su pilot rezultati za tri implementacije. Puna serija na fizičkom Windows računaru još čeka potvrdu.
