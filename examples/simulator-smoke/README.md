# Simulator Smoke Example

fuzzing engine 없이 `user-interaction-simulator`만 확인하기 위한 작은 예제입니다.

## Files

- `index.html`: 작고 독립적인 테스트 페이지입니다.
- `actions.json`: simulator action wire format 예제입니다.

## Manual Check

브라우저에서 `index.html`을 열고 `actions.json`의 순서대로 동작을 직접 수행하면 됩니다. 화면 아래의 log 영역에 click/input/focus/drag 결과가 누적됩니다.

## Simulator IPC Check

프로젝트 루트에서 아래 PowerShell을 실행하면 `.env`의 `BROWSER_PATH`를 읽고 simulator에 `initialize`, `run_testcase`, `shutdown`을 보냅니다.

`browser_kind`는 비워두지 마세요. v1에서는 `chromium`만 지원합니다.

```powershell
$root = Resolve-Path .
$envText = Get-Content .env
$browserPath = ($envText | Where-Object { $_ -match '^BROWSER_PATH=' }) -replace '^BROWSER_PATH=', ''
$browserKind = 'chromium'
$htmlPath = Join-Path $root 'examples\simulator-smoke\index.html'
$actions = Get-Content 'examples\simulator-smoke\actions.json' -Raw | ConvertFrom-Json

$init = @{
  cmd = 'initialize'
  protocol_version = 1
  browser_path = $browserPath
  browser_kind = $browserKind
  sancov_dir = (Join-Path $root 'out\simulator-smoke\sancov')
  asan_dir = (Join-Path $root 'out\simulator-smoke\asan')
  out_dir = (Join-Path $root 'out\simulator-smoke')
  iteration_timeout_ms = 12000
  action_timeout_ms = 1000
  page_ready_timeout_ms = 500
  post_actions_settle_ms = 100
  inter_action_delay_ms = 20
  disable_breakpad = $true
} | ConvertTo-Json -Compress

$run = @{
  cmd = 'run_testcase'
  protocol_version = 1
  iteration = 1
  seed_id = 'simulator_smoke'
  html_path = $htmlPath
  initial_url = $null
  actions = @($actions)
} | ConvertTo-Json -Depth 20 -Compress

$shutdown = @{ cmd = 'shutdown'; protocol_version = 1 } | ConvertTo-Json -Compress
$init, $run, $shutdown | uv run --directory src\user-interaction-simulator python -m user_interaction_simulator serve
```

정상 동작하면 두 번째 응답에서 `status`가 `ok`이고 `actions_succeeded`가 0보다 큰 값으로 나옵니다.
