param([int]$Jobs = 3)
$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$runtime = Join-Path $root "models\visionpsy-nano-flash\qvac-runtime"
$runtimeSource = Join-Path $runtime "llama-cpp-inference\llama.cpp-custom"
$revision = "4effbda7afed28688498147759f62cd487e90944"
$modelDir = Join-Path $root "models\visionpsy-nano-flash"
$hasher = [Security.Cryptography.SHA256]::Create()
try { $rootHash = ([BitConverter]::ToString($hasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($root)))).Replace("-", "").Substring(0, 10) }
finally { $hasher.Dispose() }
$buildWorkspace = Join-Path ([IO.Path]::GetTempPath()) "vpsy-$rootHash-$($revision.Substring(0, 8))"
$source = Join-Path $buildWorkspace "src"
$cudaRoot = Join-Path $modelDir "cuda-13.1.2"
$nvcc = Join-Path $cudaRoot "Library\bin\nvcc.exe"
$cudaBin = Join-Path $cudaRoot "Library\bin"
$vsRoot = "C:\Program Files\Microsoft Visual Studio\2022\Community"
$hostCompilerPath = Join-Path $vsRoot "VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64\cl.exe"
# 8.3 path avoids nvcc/CMake dropping quotes from the -ccbin value.
$hostCompiler = "cl"
$cmake = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$ninja = Join-Path $vsRoot "Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja"
$ninjaExe = Join-Path $ninja "ninja.exe"
$devCmd = Join-Path $vsRoot "Common7\Tools\VsDevCmd.bat"

if (-not (Test-Path $runtime)) {
    git clone --filter=blob:none --no-checkout https://github.com/tether-ai-research/qvac-visionpsy-nano.git $runtime
    git -C $runtime sparse-checkout init --cone
    git -C $runtime sparse-checkout set llama-cpp-inference
    git -C $runtime checkout $revision
}
if ((git -C $runtime rev-parse HEAD).Trim() -ne $revision) {
    throw "Runtime source revision mismatch; expected $revision"
}
if (-not (Test-Path $nvcc)) { throw "CUDA 13.1.2 local environment missing; prepare it with the pinned micromamba lock first." }
if (-not (Test-Path $cmake) -or -not (Test-Path $devCmd)) { throw "Visual Studio 2022 CMake/MSVC toolchain not found." }
if (-not (Test-Path $hostCompilerPath)) { throw "Pinned MSVC 19.44 host compiler not found." }

$build = Join-Path $buildWorkspace "b"
New-Item -ItemType Directory -Force -Path $buildWorkspace | Out-Null
if (-not (Test-Path (Join-Path $source "CMakeLists.txt"))) {
    New-Item -ItemType Directory -Force -Path $source | Out-Null
    robocopy $runtimeSource $source /E /XD build_server build_server_ninja build_cpu_server build_cpu_server_ninja build-x64-windows-msvc-release build86 /NFL /NDL /NJH /NJS | Out-Null
    if ($LASTEXITCODE -gt 7) { throw "Could not stage the pinned QVAC runtime source (robocopy=$LASTEXITCODE)." }
}
$env:PATH = "$cudaBin;$ninja;$env:PATH"
$env:CUDA_PATH = $cudaRoot
$envText = & cmd.exe /c "`"$devCmd`" -no_logo -arch=x64 && set"
if ($LASTEXITCODE -ne 0) { throw "VsDevCmd failed ($LASTEXITCODE)." }
foreach ($line in $envText) {
    if ($line -match '^([^=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process") }
}

# QVAC's build.sh disables examples/app and enables GGML_CUDA. Its CUDA
# default is H100 (90); this RTX 2050 reports 8.6, so build for sm_86.
& $cmake -S $source -B $build -G Ninja `
    "-DCMAKE_MAKE_PROGRAM=$ninjaExe" "-DCMAKE_CUDA_COMPILER=$nvcc" "-DCMAKE_CUDA_HOST_COMPILER=$hostCompiler" `
    "-DCMAKE_CXX_COMPILER=$hostCompiler" "-DCUDAToolkit_ROOT=$cudaRoot" `
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_TRY_COMPILE_CONFIGURATION=Release `
    -DCMAKE_CUDA_ARCHITECTURES=86 -DGGML_CUDA=ON -DGGML_NATIVE=OFF -DGGML_AVX512=OFF -DLLAMA_BUILD_TESTS=OFF `
    -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_APP=OFF -DLLAMA_BUILD_WEBUI=OFF `
    -DCMAKE_C_COMPILER_WORKS=TRUE -DCMAKE_CXX_COMPILER_WORKS=TRUE
if ($LASTEXITCODE -ne 0) { throw "CUDA CMake configure failed ($LASTEXITCODE)." }
& $cmake --build $build --config Release --target llama-server --parallel $Jobs
if ($LASTEXITCODE -ne 0) { throw "CUDA runtime build failed ($LASTEXITCODE)." }
$exe = Get-ChildItem $build -Recurse -Filter llama-server.exe | Select-Object -First 1 -ExpandProperty FullName
if (-not $exe) { throw "Build completed without llama-server.exe." }
$runtimeBin = Join-Path $modelDir "runtime"
New-Item -ItemType Directory -Force -Path $runtimeBin | Out-Null
Copy-Item -LiteralPath (Split-Path $exe -Parent) -Destination $runtimeBin -Recurse -Force
$runtimeExe = Join-Path (Join-Path $runtimeBin (Split-Path (Split-Path $exe -Parent) -Leaf)) "llama-server.exe"
& $runtimeExe --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Built llama-server could not start." }
Write-Output "Runtime: $revision"
Write-Output "CUDA: 13.1.2, compute capability 8.6"
Write-Output "Server: $runtimeBin"
