# TradePilot AI - dry run sweep
# Runs every candidate market and prints a summary table.
#
# Usage:
#   cd C:\Users\chris\tradepilot
#   .\.venv\Scripts\Activate.ps1
#   .\dry-run.ps1
#
# Requires the LIVE backend running on port 8000.
# Takes roughly 5 minutes - each run does a real browser capture plus an
# agent call. Let it work.

$api = "http://127.0.0.1:8000"

# Long levels for each candidate. Direction does not change what the agent
# sees on the chart, so one pass is enough to learn the trend read.
$candidates = @(
    @{ symbol="EURUSD"; tf="4h"; dir="long"; entry=1.1560; stop=1.1460; target=1.1760 },
    @{ symbol="GBPUSD"; tf="4h"; dir="long"; entry=1.3490; stop=1.3390; target=1.3690 },
    @{ symbol="AUDUSD"; tf="4h"; dir="long"; entry=0.7070; stop=0.6970; target=0.7270 },
    @{ symbol="EURUSD"; tf="1d"; dir="long"; entry=1.1560; stop=1.1360; target=1.1960 },
    @{ symbol="USDJPY"; tf="1d"; dir="long"; entry=157.50; stop=155.50; target=161.50 }
)

Write-Host ""
Write-Host "Checking backend..." -ForegroundColor Cyan
try {
    $health = Invoke-RestMethod -Uri "$api/health" -TimeoutSec 5
    Write-Host "  backend: $($health.status), database: $($health.database)" -ForegroundColor Green
} catch {
    Write-Host "  Backend is not responding on $api" -ForegroundColor Red
    Write-Host "  Start it first: uvicorn backend.main:app --reload" -ForegroundColor Red
    exit 1
}

$results = @()
$n = 0

foreach ($c in $candidates) {
    $n++
    Write-Host ""
    Write-Host "[$n/$($candidates.Count)] $($c.symbol) $($c.tf) $($c.dir)..." -ForegroundColor Cyan

    $body = @{
        symbol    = $c.symbol
        timeframe = $c.tf
        direction = $c.dir
        entry     = $c.entry
        stop      = $c.stop
        target    = $c.target
    } | ConvertTo-Json

    try {
        $run = Invoke-RestMethod -Method Post -Uri "$api/runs" `
            -ContentType 'application/json' -Body $body
    } catch {
        Write-Host "  create failed: $_" -ForegroundColor Red
        continue
    }

    Write-Host "  capturing chart and analyzing (this takes ~30s)..." -ForegroundColor DarkGray

    try {
        $d = Invoke-RestMethod -Method Post -Uri "$api/runs/$($run.id)/analyze" `
            -TimeoutSec 180
    } catch {
        Write-Host "  analyze failed: $_" -ForegroundColor Red
        continue
    }

    $a    = $d.analyses[0]
    $e    = $d.evaluations[0]
    $cap  = $d.captures[0]
    $md   = $d.market_data[0]

    $failed = ($d.guardrail_results | Where-Object { -not $_.passed } |
               ForEach-Object { $_.guardrail_name }) -join ", "

    $results += [PSCustomObject]@{
        Pair        = $c.symbol
        TF          = $c.tf
        Price       = $md.price
        Capture     = $cap.status
        Analysis    = $a.status
        Trend       = "$($a.trend_direction)/$($a.trend_quality)"
        Structure   = $a.structure_quality
        Setup       = $a.setup_quality
        Context     = $a.context_risk
        Uncertainty = $a.uncertainty
        Total       = $e.total_score
        Outcome     = $d.guardrail_outcome
        FailedRules = $failed
        RunId       = $run.id
    }

    Write-Host "  -> $($a.status) | score $($e.total_score) | $($d.guardrail_outcome)" -ForegroundColor Green
}

Write-Host ""
Write-Host "=================== SUMMARY ===================" -ForegroundColor Yellow
$results | Format-Table Pair, TF, Trend, Structure, Setup, Context, Uncertainty, Total, Outcome -AutoSize

Write-Host "Component scores for the best run:" -ForegroundColor Yellow
$best = $results | Where-Object { $_.Total -ne $null } |
        Sort-Object Total -Descending | Select-Object -First 1

if ($best) {
    Write-Host "  $($best.Pair) $($best.TF) - total $($best.Total)" -ForegroundColor Green
    $bd = Invoke-RestMethod -Uri "$api/runs/$($best.RunId)"
    $bd.evaluations[0] | Format-List trend_score, structure_score, entry_score,
        risk_reward_score, timing_context_score, total_score, risk_reward_ratio
    Write-Host "  Failed guardrails: $($best.FailedRules)"
    Write-Host "  Screenshot: $($bd.captures[0].screenshot_path)"
} else {
    Write-Host "  No run produced a score. Check the Analysis column above." -ForegroundColor Red
}

Write-Host ""
Write-Host "Paste the SUMMARY table above back into the chat." -ForegroundColor Cyan
Write-Host ""
Write-Host "Reset before recording:" -ForegroundColor DarkGray
Write-Host "  rm database/tradepilot.db; python -m database.init_db" -ForegroundColor DarkGray
