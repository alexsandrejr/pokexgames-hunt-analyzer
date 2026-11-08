// Gera o pacote do PokeXGames Hunt Analyzer para Windows (equivale a scripts/build_exe.py).
//
// Uso (na pasta rust/):  node tools/build_exe.mjs [--skip-test]
//
// Etapas: confere a versão → `tauri build` → pasta do pacote e .zip → teste do .exe
// (`--smoke-test`, com dados temporários) → teste da instalação de uma atualização a partir do
// próprio .zip, extraído pelo mesmo código da atualização automática. Se um teste falhar, o .zip
// é apagado, para não sobrar um pacote sem teste.
// Resultado em rust/dist/: a pasta "PokeXGames Hunt Analyzer" e o
// PokeXGames-Hunt-Analyzer-X.Y.Z-windows.zip, no formato que a atualização automática espera.

import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const RUST = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const APP = join(RUST, "app");
const DIST = join(RUST, "dist");
const APP_NAME = "PokeXGames Hunt Analyzer";
const EXE_NAME = `${APP_NAME}.exe`;
const options = new Set(process.argv.slice(2));

// O Rust fica em %USERPROFILE%\.cargo\bin, que nem todo terminal tem no PATH.
const cargoBin = join(process.env.USERPROFILE ?? "", ".cargo", "bin");
if (existsSync(cargoBin)) process.env.PATH = `${cargoBin};${process.env.PATH}`;

function step(message) {
  console.log(`\n==> ${message}`);
}

/** Pacote gerado nesta execução; apagado se algo falhar depois. */
let untestedArchive = null;

function fail(message) {
  console.error(`\nErro: ${message}`);
  if (untestedArchive) rmSync(untestedArchive, { force: true });
  process.exit(1);
}

function run(command, args, settings = {}) {
  const result = spawnSync(command, args, { stdio: "inherit", shell: false, ...settings });
  if (result.error) fail(`${command}: ${result.error.message}`);
  return result.status;
}

/** Apaga uma pasta temporária; o WebView2 às vezes demora a soltar os arquivos. */
function removeLater(path) {
  try {
    rmSync(path, { recursive: true, force: true, maxRetries: 10, retryDelay: 500 });
  } catch {
    console.log(`(pasta temporária não apagada: ${path})`);
  }
}

function megabytes(bytes) {
  return `${(bytes / 1_048_576).toFixed(1)} MB`;
}

// ------------------------------------------------------------------------------ versão

function readVersion() {
  const config = JSON.parse(readFileSync(join(APP, "src-tauri", "tauri.conf.json"), "utf8"));
  const cargo = readFileSync(join(RUST, "Cargo.toml"), "utf8");
  const workspace = cargo.match(/\[workspace\.package\][^[]*?version\s*=\s*"([^"]+)"/);
  if (!workspace) fail("versão não encontrada em rust/Cargo.toml ([workspace.package]).");
  if (config.version !== workspace[1]) {
    fail(`versões diferentes: tauri.conf.json tem ${config.version} e Cargo.toml tem ${workspace[1]}.`);
  }
  if (config.mainBinaryName !== APP_NAME) fail(`mainBinaryName precisa ser "${APP_NAME}".`);
  return config.version;
}

// ------------------------------------------------------------------------------ testes

/** Ambiente isolado: LOCALAPPDATA e banco temporários, longe dos dados reais. */
function testEnvironment(folder) {
  return { ...process.env, LOCALAPPDATA: folder, PXG_HUNTS_DB: join(folder, "smoke", "hunts.db") };
}

function checkLog(logFile, code, what) {
  const text = existsSync(logFile) ? readFileSync(logFile, "utf8") : "(sem log)";
  if (code !== 0 || !text.includes("Smoke test concluído") || / ERROR /.test(text)) {
    console.log(text);
    fail(`${what} falhou no teste (código ${code}).`);
  }
}

function smokeTest(exe) {
  const folder = mkdtempSync(join(tmpdir(), "pxg-smoke-"));
  try {
    const code = run(exe, ["--smoke-test"], { env: testEnvironment(folder), timeout: 240_000 });
    checkLog(join(folder, APP_NAME, "logs", "app.log"), code, "O executável");
  } finally {
    removeLater(folder);
  }
  console.log("Executável testado: abriu, visitou todas as telas e fechou sem erros.");
}

/** Extrai o .zip como a atualização automática e instala por cima de uma cópia antiga em Python. */
function updateTest(archive, version) {
  const folder = mkdtempSync(join(tmpdir(), "pxg-update-"));
  try {
    const extract = spawnSync(
      "cargo",
      ["run", "-q", "-p", "pxg-core", "--example", "extract_package", "--", archive, version, join(folder, "updates")],
      { cwd: RUST, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] },
    );
    if (extract.status !== 0) fail("o .zip não passou pela extração da atualização automática.");
    const packageDir = extract.stdout.trim();

    const target = join(folder, "instalado");
    mkdirSync(join(target, "_internal"), { recursive: true });
    writeFileSync(join(target, "_internal", "arquivo_antigo.txt"), "antigo");
    writeFileSync(join(target, EXE_NAME), "antigo");
    mkdirSync(join(target, "data"));
    writeFileSync(join(target, "data", "hunts.db"), "dados");

    const env = testEnvironment(folder);
    let code = run(join(packageDir, EXE_NAME), ["--apply-update", target, "0", "--smoke-test"], {
      env,
      timeout: 300_000,
    });
    if (code !== 0) fail(`a instalação da atualização falhou (código ${code}).`);
    const installed = join(target, EXE_NAME);
    if (
      readFileSync(join(target, "data", "hunts.db"), "utf8") !== "dados" ||
      existsSync(join(target, "_internal")) ||
      statSync(installed).size < 1024 ||
      !existsSync(join(target, "LEIA-ME.txt"))
    ) {
      fail("a atualização não deixou a pasta como deveria.");
    }
    // A pasta "data" faz a cópia usar o modo portátil: o log fica nela, e o banco é o de PXG_HUNTS_DB.
    code = run(installed, ["--smoke-test"], { env, timeout: 240_000 });
    checkLog(join(target, "data", "logs", "app.log"), code, "O programa atualizado");
  } finally {
    removeLater(folder);
  }
  console.log("Atualização testada: trocou os arquivos, apagou a _internal, manteve a pasta data e abriu.");
}

// ------------------------------------------------------------------------------ pacote

function makePackage(exe) {
  const packageDir = join(DIST, APP_NAME);
  rmSync(packageDir, { recursive: true, force: true });
  mkdirSync(packageDir, { recursive: true });
  cpSync(exe, join(packageDir, EXE_NAME));
  cpSync(join(APP, "LEIA-ME.txt"), join(packageDir, "LEIA-ME.txt"));
  return packageDir;
}

/** O tar do Windows (bsdtar) grava .zip; o da Git Bash não, por isso o caminho completo. */
function makeZip(version) {
  const archive = join(DIST, `PokeXGames-Hunt-Analyzer-${version}-windows.zip`);
  rmSync(archive, { force: true });
  const tar = join(process.env.SystemRoot ?? "C:\\Windows", "System32", "tar.exe");
  const code = run(tar, ["-a", "-c", "-f", archive, "-C", DIST, APP_NAME]);
  if (code !== 0 || !existsSync(archive)) fail("não foi possível gerar o .zip.");
  return archive;
}

// ------------------------------------------------------------------------------ principal

const version = readVersion();
console.log(`${APP_NAME} ${version}`);

step("Compilando com o Tauri (pode levar alguns minutos)");
const code = run("npx tauri build --no-bundle", [], { cwd: APP, shell: true });
if (code !== 0) fail(`o tauri build falhou (código ${code}).`);
const exe = join(RUST, "target", "release", EXE_NAME);
if (!existsSync(exe)) fail(`executável não encontrado: ${exe}`);

step("Montando a pasta do pacote");
const packageDir = makePackage(exe);
step("Compactando para distribuir");
const archive = makeZip(version);
untestedArchive = archive;

if (options.has("--skip-test")) {
  console.log("\nTestes pulados (--skip-test): não publique este .zip.");
} else {
  step("Testando o executável gerado");
  smokeTest(join(packageDir, EXE_NAME));
  step("Testando a instalação de uma atualização a partir do .zip");
  updateTest(archive, version);
}
untestedArchive = null;

console.log(
  `\nPronto!\n  Executável:  ${join(packageDir, EXE_NAME)} (${megabytes(statSync(exe).size)})\n` +
    `  Para enviar: ${archive} (${megabytes(statSync(archive).size)})`,
);
