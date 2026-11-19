# Diskretni RL eksperimenti

| Skripta u folderu `scripts` | Gymnasium okruženja |
|---|---|
| `submit-rl-discrete.ps1` | CartPole-v1, Blackjack-v1, FrozenLake-v1, Taxi-v4 |

## Priprema Workera

Za prvo pokretanje koristi računar sa Python okruženjem za ML. Pre dodavanja ostalih Workera instaliraj istu reviziju projekta i RL zavisnosti na svakom računaru koji će preuzimati RL zadatke. Starija verzija izvršne skripte može za nepoznat algoritam pokrenuti demo. U uspešnom RL rezultatu proveri da `metricsJson` sadrži `"algorithm": "q-learning"` i očekivani broj koraka.

Iz korena projekta preko PowerShell-a na Windowsu instaliraj zavisnosti u postojeće okruženje:

```powershell
& "$HOME\ie27-ml-env\Scripts\python.exe" -m pip install -r src/Worker/Scripts/requirements-rl-discrete.txt
```

Na MacBooku pokreni:

```bash
"$HOME/ie27-ml-env/bin/python" -m pip install -r src/Worker/Scripts/requirements-rl-discrete.txt
```

Sačekaj završetak tekućih poslova i zatvori stare Worker procese na računaru pomoću Ctrl+C. Pokreni `dotnet build src/Worker` na tom računaru. Ponovo pokreni prethodnu komandu za Worker uz jedinstven ID, adresu Coordinatora i putanju do tog Python okruženja. Rebuild kopira novu Python skriptu u izlazni folder. Coordinator može nastaviti da radi.

## Slanje grupe iz PowerShell-a

```powershell
$serija = @(./scripts/submit-rl-discrete.ps1 -CoordinatorUrl http://10.1.158.23:5031)
```

Adresu prilagodi Coordinatoru. Skripta vraća ID i naziv svakog prihvaćenog zadatka. Parametar `-Repeat 5` šalje 20 nezavisnih zadataka po grupi (četiri okruženja, pet puta). Podrazumevani budžet po zadatku je `-MaxSteps 10000`. Ponavljanja zadržavaju isti `-Seed` (podrazumevano 42) radi poređenja trajanja za isto opterećenje.

```powershell
$serija | ForEach-Object {
    Invoke-RestMethod "http://10.1.158.23:5031/api/experiments/$($_.id)"
} | Format-List name, status, assignedWorkerId, executionDurationMs, metricsJson, resultMessage
```

## Kako se tumači rezultat

Implementiran je tablični Q-learning sa epsilon-greedy izborom akcije, stopom učenja 0,1 i diskontnim faktorom 0,99. Agent uči tokom tačno `MaxSteps` interakcija. Početak nove epizode ne menja preostali budžet. Kontinuirana opažanja mapiraju se u intervale definisane u `rl_discrete.py`.

`steps` je broj interakcija, `episodes` broj završenih epizoda, a `mean_completed_episode_return` prosečan zbir nagrada po završenoj epizodi tokom treninga. Ako se nijedna epizoda još nije završila, ta vrednost je `null`. `total_reward` uključuje i eventualnu poslednju nedovršenu epizodu. Za vreme po zadatku koristi `executionDurationMs` iz odgovora Coordinatora. Povrat agenta je dijagnostička metrika treninga; procena kvaliteta naučene politike zahtevala bi posebne evaluacione epizode.
