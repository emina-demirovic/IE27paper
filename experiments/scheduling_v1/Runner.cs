namespace SchedulingV1;

internal static class Runner
{
    public static async Task<int> Main(string[] args)
    {
        if (args.Length == 0 || args[0] is not ("smoke" or "full"))
            return Usage();

        int repeats = 1;
        bool inProcess = false;
        for (int i = 1; i < args.Length; i++)
        {
            if (args[i] == "--in-process")
                inProcess = true;
            else if (args[i] == "--repeats" && i + 1 < args.Length &&
                     int.TryParse(args[++i], out var count) && count > 0)
                repeats = count;
            else
                return Usage();
        }

        using var stop = new CancellationTokenSource();
        Console.CancelKeyPress += (_, e) => { e.Cancel = true; stop.Cancel(); };
        int millisecondsPerSecond = args[0] == "smoke" ? 20 : 1000;
        string session = $"{DateTime.UtcNow:yyyyMMddTHHmmssZ}-{args[0]}-{Guid.NewGuid():N}";
        var directory = Directory.CreateDirectory(Path.Combine("results", session)).FullName;
        Console.WriteLine($"Results in {directory}");

        var scenarios = new[] { "A", "B" }.ToDictionary(key => key, Workload.Generate);
        if (Workload.IdealMakespan(scenarios["A"], "FIFO") != 108 ||
            Workload.IdealMakespan(scenarios["A"], "LPT") != 78)
            throw new InvalidOperationException("Scenario A failed its zero-overhead reference check.");

        foreach (var (scenario, tasks) in scenarios)
            Workload.WriteCsv(Path.Combine(directory, $"arrival-{scenario}.csv"), "task_id,arrival_index,K",
                tasks.Select(t => Workload.Row($"{t.Id},{t.ArrivalIndex},{t.K}")));

        var summary = new List<string>();
        const string header = "repeat,scenario,first_policy,fifo_s,lpt_s,saved_s,reduction_pct,ms_per_workload_second,transport,shuffle_seed";
        string transport = inProcess ? "TestServer" : "Kestrel";
        for (int repeat = 1; repeat <= repeats; repeat++)
        {
            foreach (var (scenario, tasks) in scenarios)
            {
                bool fifoFirst = (repeat % 2 == 1) == (scenario == "A");
                string[] policies = fifoFirst ? ["FIFO", "LPT"] : ["LPT", "FIFO"];
                var times = new Dictionary<string, double>();
                foreach (var policy in policies)
                {
                    var runId = $"{session}-r{repeat:D2}-{scenario}-{policy}";
                    Console.WriteLine($"Starting repeat {repeat}, scenario {scenario}, {policy} ({transport}).");
                    times[policy] = await Platform.RunAsync(tasks, scenario, policy, runId, directory,
                        millisecondsPerSecond, inProcess, stop.Token);
                }
                var fifo = times["FIFO"];
                var lpt = times["LPT"];
                double saved = fifo - lpt;
                double pct = 100 * saved / fifo;
                summary.Add(Workload.Row($"{repeat},{scenario},{policies[0]},{fifo:R},{lpt:R},{saved:R},{pct:R},{millisecondsPerSecond},{transport},{Workload.ShuffleSeed}"));
                Workload.WriteCsv(Path.Combine(directory, "summary.csv"), header, summary);
                Console.WriteLine($"Scenario {scenario} FIFO {fifo:F3}s, LPT {lpt:F3}s, saved {saved:F3}s ({pct:F2}%).");
            }
        }
        return 0;
    }

    private static int Usage()
    {
        Console.Error.WriteLine("Usage: bash run.sh smoke|full [--repeats N] [--in-process]");
        return 2;
    }
}
