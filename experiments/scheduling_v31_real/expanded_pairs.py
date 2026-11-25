"""Paired FIFO and V1 runs on identical randomized, held-out configurations."""
import csv
import json
import random
import statistics
import subprocess

from benchmark import DOTNET, ENV, PYTHON, RUNNER, save

from expanded_calibration import workload_parser

GROUP_TOTALS = {"short": 72, "medium": 36, "long": 12}


def read(path):
    return json.loads(path.read_text())


def write_table(path, records):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", newline="") as f:
        writer = csv.DictWriter(f, records[0])
        writer.writeheader()
        writer.writerows(records)
    temporary.replace(path)


def manifest(configs, seed):
    jobs = []
    counts = {group: sum(c["group"] == group for c in configs) for group in GROUP_TOTALS}
    if any(n == 0 or GROUP_TOTALS[group] % n for group, n in counts.items()):
        raise ValueError("Configuration counts must evenly divide the short, medium and long job totals.")
    for cfg in configs:
        for i in range(GROUP_TOTALS[cfg["group"]] // counts[cfg["group"]]):
            jobs.append(dict(Id=f"{cfg['config']}-{i:02}", K=cfg["predicted_ms"], Algorithm=cfg["algorithm"],
                             Environment=cfg["environment"], MaxSteps=cfg["maxSteps"], Seed=cfg["seed"]))
    assert len(jobs) == 120
    random.Random(seed).shuffle(jobs)
    for idx,j in enumerate(jobs):
        j["ArrivalIndex"] = idx
    return jobs


def verified_arm(jobs, manifest_path, policy, dest, references):
    if not dest.exists():
        temp = dest.with_suffix(".tmp")
        subprocess.run([str(DOTNET), str(RUNNER / "bin/Debug/net10.0/SchedulingV1.dll"),
                        str(manifest_path), policy, str(temp), str(PYTHON)], cwd=RUNNER, env=ENV,
                       check=True, timeout=720)
        temp.replace(dest)
    run = read(dest)
    expected = jobs if policy == "FIFO" else sorted(jobs,key=lambda j:(-j["K"],j["ArrivalIndex"]))
    rows = run["rows"]
    assert run["policy"] == policy and run["workers"] == 10
    assert [r["Name"] for r in rows] == [j["Id"] for j in expected]
    for row in rows:
        cfg = row["Name"].rsplit("-",1)[0]
        if row["metrics"] != references[cfg]["metrics"]:
            raise ValueError(f"Incorrect worker result for {row['Name']}")
    end = max(r["completion"] for r in rows)
    assert end == run["makespan"]
    last = max(r["dispatch"] for r in rows)
    return dict(makespan=end, last_dispatch=last, tail=end-last)


def main():
    parser = workload_parser()
    parser.add_argument("--pairs", type=int, default=2,
                        help="Total pairs to complete, including saved pairs (default: 2)")
    args = parser.parse_args()
    if args.pairs < 1:
        parser.error("--pairs must be positive")
    out = args.output
    # Keep the original six-pair report paths and retain shorter pilot reports.
    suffix = "" if args.pairs == 6 else f"-{args.pairs}"
    configs = read(out / "predictions.json")["configurations"]
    refs = {c["config"]:read(out / f"reference-{c['config']}.json") for c in configs}
    ranking = sorted(configs,key=lambda c:-c["predicted_ms"])
    reference_order = sorted(configs,key=lambda c:-refs[c["config"]]["duration_ms"])
    ranks = {c["config"]:i for i,c in enumerate(reference_order,1)}
    comparison = [dict(config=c["config"], group=c["group"], predicted_s=c["predicted_ms"]/1000,
                       solo_s=refs[c["config"]]["duration_ms"]/1000, estimated_rank=i, solo_rank=ranks[c["config"]])
                  for i,c in enumerate(ranking,1)]
    write_table(out / "ranking.csv", comparison)
    print("Calibrated ranges (seconds):",flush=True)
    for group in GROUP_TOTALS:
        times=[r["solo_s"] for r in comparison if r["group"]==group]
        print(group, min(times), max(times), flush=True)
    pairs=[]
    for number in range(1, args.pairs + 1):
        seed = 2700+number
        jobs = manifest(configs,seed)
        file = out / f"r{number}-manifest.json"
        if file.exists():
            assert read(file) == jobs
        else:
            save(file, jobs)
        order = ["FIFO","LPT"] if number % 2 else ["LPT","FIFO"]
        arms = {}
        for policy in order:
            print(f"Starting pair {number}, {policy}",flush=True)
            arms[policy]=verified_arm(jobs,file,policy,out/f"r{number}-{policy}.json",refs)
            print(number,policy,arms[policy],flush=True)
        fifo,lpt = arms["FIFO"],arms["LPT"]
        saved = fifo["makespan"]-lpt["makespan"]
        pairs.append(dict(pair=number,seed=seed,first=order[0],fifo_s=fifo["makespan"],v1_s=lpt["makespan"],
                          saved_s=saved,reduction_pct=100*saved/fifo["makespan"],
                          fifo_last_dispatch_s=fifo["last_dispatch"],v1_last_dispatch_s=lpt["last_dispatch"],
                          fifo_tail_s=fifo["tail"],v1_tail_s=lpt["tail"],tail_saved_s=fifo["tail"]-lpt["tail"]))
        write_table(out / f"pairs{suffix}.csv", pairs)
    keys=["fifo_s","v1_s","saved_s","reduction_pct","fifo_tail_s","v1_tail_s","tail_saved_s"]
    summary=dict(pairs=len(pairs),v1_wins=sum(p["saved_s"]>0 for p in pairs),tasks_per_arm=len(jobs),
                 completed_tasks=2*len(pairs)*len(jobs),medians={k:statistics.median(p[k] for p in pairs) for k in keys},
                 range_reduction_pct=[min(p["reduction_pct"] for p in pairs),max(p["reduction_pct"] for p in pairs)],
                 solo_top_four_in_predicted_top_four=len({r["config"] for r in comparison[:4]} & {c["config"] for c in reference_order[:4]}))
    save(out / f"summary{suffix}.json", summary)
    print(summary,flush=True)


if __name__ == "__main__":
    main()
