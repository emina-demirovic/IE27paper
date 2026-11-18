param(
    [Parameter(Mandatory = $true)]
    [string]$CoordinatorUrl,
    [ValidateRange(1, 10000)]
    [int]$Trees = 50
)

$ErrorActionPreference = 'Stop'
$url = $CoordinatorUrl.TrimEnd('/') + '/api/experiments'
foreach ($dataset in 'Iris', 'Wine', 'Breast Cancer', 'California Housing') {
    $body = @{
        name = "Random forest - $dataset"
        algorithm = 'random-forest'
        environment = $dataset
        seed = 42
        maxSteps = $Trees
        timeoutSeconds = 300
    } | ConvertTo-Json
    $job = Invoke-RestMethod -Uri $url -Method Post -ContentType 'application/json' -Body $body
    $job | Select-Object id, name
}
