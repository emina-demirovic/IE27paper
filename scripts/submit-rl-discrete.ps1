param(
    [Parameter(Mandatory = $true)]
    [string]$CoordinatorUrl,
    [ValidateRange(1, 2147483647)]
    [int]$MaxSteps = 10000,
    [int]$Seed = 42,
    [ValidateRange(1, 1000)]
    [int]$Repeat = 1
)

$environments = @('CartPole', 'Blackjack', 'FrozenLake', 'Taxi')
$ErrorActionPreference = 'Stop'
$url = $CoordinatorUrl.TrimEnd('/') + '/api/experiments'
for ($round = 1; $round -le $Repeat; $round++) {
    foreach ($environment in $Environments) {
        $body = @{
            name = "Q-learning - $environment"
            algorithm = 'q-learning-discrete'
            environment = $environment
            seed = $Seed
            maxSteps = $MaxSteps
            timeoutSeconds = 300
        } | ConvertTo-Json

        $job = Invoke-RestMethod -Method Post -Uri $url -ContentType 'application/json' -Body $body
        $job | Select-Object id, name
    }
}
