$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\python.exe"
$cli = Join-Path $projectRoot ".venv\Scripts\parallel-agent.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Missing .venv. Follow the environment setup in README.md first."
}

New-Item -ItemType Directory -Path (Join-Path $projectRoot "work\pytest") -Force |
    Out-Null

Push-Location $projectRoot
try {
    & $python -m pytest -q
    & $cli benchmark benchmarks\prime_count\workload.py `
        --size 16 --workers 4 --backend multiprocessing `
        --modes serial naive optimized --repeats 3 --warmups 1 `
        --output results\raw\prime_count_first.json
    & $cli benchmark benchmarks\tiny_tasks\workload.py `
        --size 1000 --workers 4 --backend multiprocessing `
        --modes serial naive optimized --repeats 3 --warmups 1 `
        --output results\raw\tiny_tasks_first.json
    & $cli analyze benchmarks\prefix_sum\serial.py `
        --output results\raw\prefix_sum_analysis.json
}
finally {
    Pop-Location
}

