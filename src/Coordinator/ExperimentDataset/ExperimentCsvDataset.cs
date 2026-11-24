using System.Globalization;
using System.Text.Json;
using Contracts.ResourceMonitoring;
using Coordinator.Data;
using Coordinator.ResourceMonitoring;
using Coordinator.Services;
using Microsoft.EntityFrameworkCore;

namespace Coordinator.ExperimentDataset;

public sealed class ExperimentCsvDataset(
    IConfiguration configuration,
    IHostEnvironment environment,
    IDbContextFactory<CoordinatorDbContext> dbContextFactory,
    WorkerRegistry workers,
    HostResourceRegistry resources,
    ILogger<ExperimentCsvDataset> logger) : BackgroundService
{
    private const string Header =
        "experiment_id,attempt,worker_id,host_id,git_commit,entry_point,algorithm,environment,seed,max_steps," +
        "for_count,while_count,call_count,max_syntactic_loop_depth,snapshot_at_utc,sample_measured_at_utc," +
        "sample_received_at_utc,sample_stale,cpu_usage_percent,total_memory_bytes,memory_bytes,memory_kind," +
        "finished_at_utc,status,execution_duration_ms,analysis_json";

    internal sealed record Assignment(DateTimeOffset CapturedAtUtc, string? HostId, HostResourceStatus? Resources);

    internal Assignment CaptureAssignment(string workerId)
    {
        var hostId = workers.GetAll().FirstOrDefault(worker => worker.WorkerId == workerId)?.HostId;
        var sample = hostId is null
            ? null
            : resources.GetAll().FirstOrDefault(resource => resource.HostId == hostId);

        return new Assignment(DateTimeOffset.UtcNow, hostId, sample);
    }

    internal static bool IsAnalysisRecord(JsonElement analysis)
    {
        var version = Property(analysis, "schemaVersion");
        var task = Property(analysis, "task");
        return version is { ValueKind: JsonValueKind.Number } &&
            version.Value.TryGetInt32(out var schema) && schema == 1 &&
            !string.IsNullOrWhiteSpace(StringProperty(task, "gitCommit")) &&
            !string.IsNullOrWhiteSpace(StringProperty(task, "entryPoint")) &&
            Property(analysis, "features") is { ValueKind: JsonValueKind.Object };
    }

    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var path = Path.GetFullPath(configuration["Coordinator:ExperimentCsvPath"]!,
            environment.ContentRootPath);
        using var interval = new PeriodicTimer(TimeSpan.FromSeconds(2));
        string? lastPublished = null;

        do
        {
            try
            {
                var csv = await ReadCsvAsync(stoppingToken);
                if (csv != lastPublished || !File.Exists(path))
                {
                    await PublishAsync(path, csv, stoppingToken);
                    lastPublished = csv;
                }
            }
            catch (Exception exception) when (exception is IOException or UnauthorizedAccessException or
                System.Data.Common.DbException or JsonException)
            {
                logger.LogWarning(exception, "Could not write experiment CSV to {Path}.", path);
            }
        }
        while (await interval.WaitForNextTickAsync(stoppingToken));
    }

    private async Task<string> ReadCsvAsync(CancellationToken cancellationToken)
    {
        await using var db = await dbContextFactory.CreateDbContextAsync(cancellationToken);
        var events = await db.ExperimentEvents.AsNoTracking()
            .Where(item => item.Type == ExperimentEventType.DatasetTaskAnalysis ||
                item.Type == ExperimentEventType.DatasetAssignment ||
                item.Type == ExperimentEventType.DatasetDuration ||
                item.Type == ExperimentEventType.Completed ||
                item.Type == ExperimentEventType.Failed ||
                item.Type == ExperimentEventType.Cancelled ||
                item.Type == ExperimentEventType.Requeued ||
                item.Type == ExperimentEventType.RecoveredOnStartup)
            .Select(item => new
            {
                item.ExperimentId, item.Attempt, item.Type, item.OccurredAtUtc, item.WorkerId, item.Details,
                item.Experiment.Algorithm, item.Experiment.Environment, item.Experiment.Seed, item.Experiment.MaxSteps
            })
            .ToListAsync(cancellationToken);

        var analyses = events.Where(item => item.Type == ExperimentEventType.DatasetTaskAnalysis)
            .ToDictionary(item => item.ExperimentId, item => item.Details);
        var attempts = events.Where(item => item.Attempt > 0)
            .GroupBy(item => (item.ExperimentId, item.Attempt));
        var rows = new List<string> { Header };

        foreach (var attempt in attempts.OrderBy(group => group.Key.ExperimentId).ThenBy(group => group.Key.Attempt))
        {
            var assignment = attempt.SingleOrDefault(item => item.Type == ExperimentEventType.DatasetAssignment);
            var outcome = attempt.FirstOrDefault(item =>
                item.WorkerId == assignment?.WorkerId &&
                item.Type is (ExperimentEventType.Completed or ExperimentEventType.Failed or
                    ExperimentEventType.Cancelled or ExperimentEventType.Requeued or
                    ExperimentEventType.RecoveredOnStartup));
            if (assignment?.Details is null || outcome is null)
            {
                continue;
            }

            var snapshot = JsonSerializer.Deserialize<Assignment>(assignment.Details)!;
            var resource = snapshot.Resources;
            var analysisJson = analyses.GetValueOrDefault(assignment.ExperimentId);
            using var analysis = analysisJson is null ? null : JsonDocument.Parse(analysisJson);
            var task = Property(analysis?.RootElement, "task");
            var derived = Property(Property(analysis?.RootElement, "features"), "derived");
            var ast = Property(Property(derived, "ast"), "entryPoint");
            var duration = attempt.SingleOrDefault(item => item.Type == ExperimentEventType.DatasetDuration)?.Details;

            rows.Add(string.Join(",", new object?[]
            {
                assignment.ExperimentId, assignment.Attempt, assignment.WorkerId, snapshot.HostId,
                StringProperty(task, "gitCommit"), StringProperty(task, "entryPoint"),
                assignment.Algorithm, assignment.Environment, assignment.Seed, assignment.MaxSteps,
                Property(ast, "forCount"), Property(ast, "whileCount"), Property(ast, "callCount"),
                Property(ast, "maxSyntacticLoopDepth"), snapshot.CapturedAtUtc,
                resource?.Sample.MeasuredAtUtc, resource?.ReceivedAtUtc, resource?.IsStale,
                resource?.Sample.CpuUsagePercent, resource?.Sample.TotalMemoryBytes,
                resource?.Sample.MemoryBytes, resource?.Sample.MemoryKind, outcome.OccurredAtUtc,
                outcome.Type, duration, analysisJson
            }.Select(CsvField)));
        }

        return string.Join("\r\n", rows) + "\r\n";
    }

    private static JsonElement? Property(JsonElement? value, string name) =>
        value is { ValueKind: JsonValueKind.Object } obj && obj.TryGetProperty(name, out var property)
            ? property : null;

    private static string? StringProperty(JsonElement? value, string name) =>
        Property(value, name) is { ValueKind: JsonValueKind.String } property
            ? property.GetString() : null;

    private static string CsvField(object? value)
    {
        var text = value switch
        {
            DateTimeOffset time => time.ToString("O", CultureInfo.InvariantCulture),
            bool flag => flag ? "true" : "false",
            _ => Convert.ToString(value, CultureInfo.InvariantCulture) ?? ""
        };
        return text.IndexOfAny([',', '"', '\r', '\n']) < 0
            ? text
            : "\"" + text.Replace("\"", "\"\"") + "\"";
    }

    private static async Task PublishAsync(string path, string csv, CancellationToken cancellationToken)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var temporary = path + "." + Guid.NewGuid().ToString("N") + ".tmp";
        try
        {
            await File.WriteAllTextAsync(temporary, csv, cancellationToken);
            File.Move(temporary, path, overwrite: true);
        }
        finally
        {
            File.Delete(temporary);
        }
    }
}
