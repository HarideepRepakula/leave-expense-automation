<#
.SYNOPSIS
  One-time setup for a LOCAL PostgreSQL 16 install (the non-Docker alternative, amendment F1).
  Creates the migrator role, the application roles, the dev and test databases, and btree_gist in the
  test database. Equivalent to what sql/init/*.sql does inside the Docker container.

.USAGE  (PowerShell, from the project root, after copying .env.example to .env and editing passwords)
  .\scripts\init_local_db.ps1 -SuperuserPassword "<the password you chose for 'postgres' at install time>"

  Optional: -PsqlPath "C:\Program Files\PostgreSQL\16\bin\psql.exe"  -HostName localhost  -Port 5432
#>
param(
    [Parameter(Mandatory = $true)] [string] $SuperuserPassword,
    [string] $PsqlPath = "C:\Program Files\PostgreSQL\16\bin\psql.exe",
    [string] $HostName = "localhost",
    [int]    $Port = 5432
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $PsqlPath)) {
    Write-Error "psql not found at '$PsqlPath'. Install PostgreSQL 16 or pass -PsqlPath."
}
if (-not (Test-Path ".env")) {
    Write-Error "No .env file. Copy .env.example to .env and set the passwords first."
}

# Read .env into a hashtable (simple KEY=VALUE lines).
$envMap = @{}
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$') { $envMap[$matches[1]] = $matches[2] }
}
function Get-EnvOrDefault([string]$key, [string]$default) {
    if ($envMap.ContainsKey($key) -and $envMap[$key] -ne "") { return $envMap[$key] } else { return $default }
}

$migratorUser = Get-EnvOrDefault "POSTGRES_MIGRATOR_USER" "lea_migrator"
$migratorPw   = Get-EnvOrDefault "POSTGRES_MIGRATOR_PASSWORD" "change-me-migrator"
$appPw        = Get-EnvOrDefault "POSTGRES_APP_PASSWORD" "change-me-app"
$analyticsPw  = Get-EnvOrDefault "POSTGRES_ANALYTICS_PASSWORD" "change-me-analytics"
$evaluationPw = Get-EnvOrDefault "POSTGRES_EVALUATION_PASSWORD" "change-me-evaluation"
$devDb        = Get-EnvOrDefault "POSTGRES_DEV_DB" "lea_dev"
$testDb       = Get-EnvOrDefault "POSTGRES_TEST_DB" "lea_test"

function Sql-Literal([string]$s) { return "'" + ($s -replace "'", "''") + "'" }

$env:PGPASSWORD = $SuperuserPassword

$rolesSql = @"
DO `$`$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '$migratorUser') THEN
    CREATE ROLE $migratorUser LOGIN CREATEDB CREATEROLE;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_app') THEN CREATE ROLE lea_app LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_analytics_ro') THEN CREATE ROLE lea_analytics_ro LOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'lea_evaluation') THEN CREATE ROLE lea_evaluation LOGIN; END IF;
END
`$`$;
ALTER ROLE $migratorUser PASSWORD $(Sql-Literal $migratorPw);
ALTER ROLE lea_app PASSWORD $(Sql-Literal $appPw);
ALTER ROLE lea_analytics_ro PASSWORD $(Sql-Literal $analyticsPw);
ALTER ROLE lea_evaluation PASSWORD $(Sql-Literal $evaluationPw);
"@

Write-Host "Creating roles ..."
$rolesSql | & $PsqlPath -h $HostName -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -q
if ($LASTEXITCODE -ne 0) { throw "Role creation failed." }

foreach ($db in @($devDb, $testDb)) {
    $exists = & $PsqlPath -h $HostName -p $Port -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$db'"
    if ($exists -ne "1") {
        Write-Host "Creating database $db ..."
        & $PsqlPath -h $HostName -p $Port -U postgres -d postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE $db OWNER $migratorUser"
        if ($LASTEXITCODE -ne 0) { throw "Database $db creation failed." }
    } else {
        Write-Host "Database $db already exists."
    }
    & $PsqlPath -h $HostName -p $Port -U postgres -d $db -v ON_ERROR_STOP=1 -q -c "REVOKE CREATE ON SCHEMA public FROM PUBLIC; GRANT ALL ON SCHEMA public TO $migratorUser;"
}

Write-Host "Enabling btree_gist in $testDb (test-only EXCLUDE constraint) ..."
& $PsqlPath -h $HostName -p $Port -U postgres -d $testDb -v ON_ERROR_STOP=1 -q -c "CREATE EXTENSION IF NOT EXISTS btree_gist"
if ($LASTEXITCODE -ne 0) { throw "btree_gist creation failed." }

Remove-Item Env:\PGPASSWORD
Write-Host "Done. Next:  alembic upgrade head   then   pytest -m db"
