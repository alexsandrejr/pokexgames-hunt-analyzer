//! Atualização do executável pelos releases do GitHub (equivale a
//! `app/services/update_service.py` e à parte sem interface de `install_window.py`).
//!
//! Um programa em execução não pode substituir a própria pasta. Por isso, a instalação tem dois
//! processos:
//!
//! 1. A versão atual baixa o `.zip` do release, confere o SHA-256 informado pelo GitHub, extrai
//!    o pacote em `updates/`, abre o `.exe` novo com `--apply-update <pasta> <pid>` e fecha.
//! 2. O `.exe` novo espera a versão atual fechar, troca os arquivos e abre o programa já
//!    atualizado.
//!
//! **Compatibilidade:** a 1.6.0 em Python executa o passo 1 e chama o `.exe` em Rust com
//! `--apply-update`. Toda versão precisa continuar aceitando esse argumento, e o pacote precisa
//! se chamar `PokeXGames-Hunt-Analyzer-X.Y.Z-windows.zip`, com a pasta
//! `PokeXGames Hunt Analyzer` e o `.exe` dentro. Na primeira troca vinda do Python, a pasta
//! `_internal` do PyInstaller, que não vem no pacote novo, também sai.
//!
//! Só os arquivos do pacote são trocados: a pasta `data` do modo portátil e qualquer outro
//! arquivo do usuário ao lado do `.exe` continuam onde estão.

use std::collections::HashMap;
use std::io::{Read, Write};
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Duration;

use regex::Regex;
use serde_json::Value;
use sha2::{Digest, Sha256};

pub const APP_NAME: &str = "PokeXGames Hunt Analyzer";
pub const GITHUB_REPOSITORY: &str = "alexsandrejr/pokexgames-hunt-analyzer";
pub const APPLY_UPDATE_ARG: &str = "--apply-update";
pub const EXE_NAME: &str = "PokeXGames Hunt Analyzer.exe";

pub const CHECK_TIMEOUT: Duration = Duration::from_secs(10);
pub const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(30);
const CHUNK_BYTES: usize = 256 * 1024;
pub const MAX_EXTRACTED_BYTES: u64 = 2 * 1024 * 1024 * 1024;
pub const WAIT_EXIT: Duration = Duration::from_secs(60);
const MOVE_ATTEMPTS: usize = 20;
const MOVE_RETRY: Duration = Duration::from_millis(500);

pub const STAGING_DIR: &str = ".update-new";
pub const OLD_DIR: &str = ".update-old";
/// Nunca são trocadas, mesmo se um pacote as trouxer: é onde ficam os dados do modo portátil.
pub const PROTECTED_NAMES: [&str; 3] = ["data", STAGING_DIR, OLD_DIR];
/// Pastas de versões anteriores que o pacote novo não traz mais e que saem na troca.
pub const LEGACY_NAMES: [&str; 1] = ["_internal"];

pub fn api_url() -> String {
    format!("https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest")
}

pub fn releases_url() -> String {
    format!("https://github.com/{GITHUB_REPOSITORY}/releases/latest")
}

pub fn download_prefix() -> String {
    format!("https://github.com/{GITHUB_REPOSITORY}/releases/download/")
}

pub fn user_agent() -> String {
    format!("PokeXGames-Hunt-Analyzer/{}", crate::APP_VERSION)
}

/// Falha na atualização, com a mensagem pronta para mostrar ao usuário.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpdateError {
    Message(String),
    /// O usuário cancelou o download.
    Cancelled,
}

impl UpdateError {
    fn new(message: impl Into<String>) -> Self {
        Self::Message(message.into())
    }
}

impl std::fmt::Display for UpdateError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Message(message) => f.write_str(message),
            Self::Cancelled => f.write_str("Download cancelado."),
        }
    }
}

impl std::error::Error for UpdateError {}

pub type UpdateResult<T> = Result<T, UpdateError>;

static VERSION: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^v?([0-9]+(?:\.[0-9]+)*)$").expect("regex válida"));
static SHA256_DIGEST: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^sha256:[0-9a-fA-F]{64}$").expect("regex válida"));

/// `v1.10.0` → `[1, 10, 0]`; `None` se não for uma versão.
pub fn parse_version(text: &str) -> Option<Vec<u64>> {
    let captures = VERSION.captures(crate::text::py_strip(text))?;
    captures[1].split('.').map(|part| part.parse().ok()).collect()
}

/// Compara como números, completando com zeros: `1.6` é igual a `1.6.0`.
pub fn is_newer(candidate: &[u64], current: &[u64]) -> bool {
    let size = candidate.len().max(current.len());
    let pad = |v: &[u64]| v.iter().copied().chain(std::iter::repeat(0)).take(size).collect::<Vec<_>>();
    pad(candidate) > pad(current)
}

pub fn asset_name(version: &str) -> String {
    format!("PokeXGames-Hunt-Analyzer-{version}-windows.zip")
}

#[derive(Debug, Clone, PartialEq, Eq, serde::Serialize)]
pub struct ReleaseInfo {
    pub version: String,
    pub notes: String,
    pub page_url: String,
    /// Vazios se o release não tiver o pacote esperado: aí, só dá para abrir a página.
    pub asset_url: String,
    pub asset_size: u64,
    pub sha256: String,
}

impl ReleaseInfo {
    pub fn page_only(version: &str, notes: &str, page_url: &str) -> Self {
        Self {
            version: version.to_owned(),
            notes: notes.to_owned(),
            page_url: page_url.to_owned(),
            asset_url: String::new(),
            asset_size: 0,
            sha256: String::new(),
        }
    }

    pub fn installable(&self) -> bool {
        !self.asset_url.is_empty() && !self.sha256.is_empty() && self.asset_size > 0
    }
}

/// A versão publicada, se for mais nova que a atual.
pub fn parse_release(data: &Value, current_version: &str) -> UpdateResult<Option<ReleaseInfo>> {
    let unexpected = || UpdateError::new("O GitHub devolveu uma resposta inesperada.");
    let object = data.as_object().ok_or_else(unexpected)?;
    let tag = object.get("tag_name").and_then(Value::as_str).ok_or_else(unexpected)?;
    let version = parse_version(tag).ok_or_else(unexpected)?;
    let current = parse_version(current_version).ok_or_else(unexpected)?;
    let truthy = |key| object.get(key).is_some_and(|v| !matches!(v, Value::Null | Value::Bool(false)));
    if truthy("draft") || truthy("prerelease") || !is_newer(&version, &current) {
        return Ok(None);
    }
    let stripped = crate::text::py_strip(tag);
    let text = stripped.strip_prefix('v').unwrap_or(stripped); // o `removeprefix("v")` do Python
    let notes = object.get("body").and_then(Value::as_str).unwrap_or("");
    let own_pages = format!("https://github.com/{GITHUB_REPOSITORY}/");
    let page = object
        .get("html_url")
        .and_then(Value::as_str)
        .filter(|p| p.starts_with(&own_pages))
        .map_or_else(releases_url, str::to_owned);
    let release = ReleaseInfo::page_only(text, notes, &page);
    let assets = object.get("assets").and_then(Value::as_array).cloned().unwrap_or_default();
    for asset in assets.iter().filter_map(Value::as_object) {
        if asset.get("name").and_then(Value::as_str) != Some(asset_name(text).as_str()) {
            continue;
        }
        let url = asset.get("browser_download_url").and_then(Value::as_str);
        let size = asset.get("size").and_then(|s| if s.is_u64() { s.as_u64() } else { None });
        let digest = asset.get("digest").and_then(Value::as_str);
        if let (Some(url), Some(size), Some(digest)) = (url, size, digest) {
            if url.starts_with(&download_prefix()) && SHA256_DIGEST.is_match(digest) {
                return Ok(Some(ReleaseInfo {
                    asset_url: url.to_owned(),
                    asset_size: size,
                    sha256: digest["sha256:".len()..].to_lowercase(),
                    ..release
                }));
            }
        }
    }
    Ok(Some(release))
}

// ------------------------------------------------------------------ rede

/// Falha de um pedido HTTP.
#[derive(Debug)]
pub enum HttpError {
    /// O servidor respondeu com este código de erro.
    Status(u16),
    /// Sem resposta: rede, tempo esgotado, certificado.
    Network(String),
}

/// Quem faz os pedidos; os testes usam respostas simuladas.
pub trait Http: Send + Sync {
    /// `GET` com os cabeçalhos informados; devolve o corpo para leitura.
    fn get(&self, url: &str, headers: &[(&str, String)], timeout: Duration) -> Result<Box<dyn Read + Send>, HttpError>;
}

/// Cliente HTTP real, com TLS próprio (não depende do Windows nem do Python).
pub struct UreqHttp;

impl Http for UreqHttp {
    fn get(&self, url: &str, headers: &[(&str, String)], timeout: Duration) -> Result<Box<dyn Read + Send>, HttpError> {
        let config = ureq::Agent::config_builder()
            .timeout_connect(Some(timeout))
            .timeout_per_read(Some(timeout))
            .timeout_recv_response(Some(timeout))
            .build();
        let agent = ureq::Agent::new_with_config(config);
        let mut request = agent.get(url);
        for (name, value) in headers {
            request = request.header(*name, value.as_str());
        }
        match request.call() {
            Ok(response) => Ok(Box::new(response.into_body().into_reader())),
            Err(ureq::Error::StatusCode(code)) => Err(HttpError::Status(code)),
            Err(error) => Err(HttpError::Network(error.to_string())),
        }
    }
}

/// Identifica só o aplicativo: nenhum dado do usuário vai no pedido.
fn request_headers() -> Vec<(&'static str, String)> {
    vec![("User-Agent", user_agent()), ("Accept", "application/vnd.github+json".to_owned())]
}

pub struct UpdateService {
    updates_dir: PathBuf,
    current_version: String,
    http: Box<dyn Http>,
}

impl UpdateService {
    pub fn new(updates_dir: PathBuf) -> Self {
        Self::with_http(updates_dir, crate::APP_VERSION, Box::new(UreqHttp))
    }

    pub fn with_http(updates_dir: PathBuf, current_version: &str, http: Box<dyn Http>) -> Self {
        Self { updates_dir, current_version: current_version.to_owned(), http }
    }

    /// A versão mais nova publicada, ou `None` se esta já for a mais recente.
    pub fn check(&self) -> UpdateResult<Option<ReleaseInfo>> {
        let offline = || UpdateError::new("Não foi possível falar com o GitHub. Confira a internet e tente de novo.");
        let mut body = match self.http.get(&api_url(), &request_headers(), CHECK_TIMEOUT) {
            Ok(body) => body,
            Err(HttpError::Status(404)) => return Ok(None), // o repositório ainda não tem release
            Err(HttpError::Status(code)) => {
                return Err(UpdateError::new(format!(
                    "O GitHub recusou a verificação (código {code}). Tente mais tarde."
                )));
            }
            Err(HttpError::Network(_)) => return Err(offline()),
        };
        let mut bytes = Vec::new();
        body.read_to_end(&mut bytes).map_err(|_| offline())?;
        let data: Value = serde_json::from_slice(&bytes).map_err(|_| offline())?;
        parse_release(&data, &self.current_version)
    }

    /// Baixa o pacote e confere o tamanho e o SHA-256.
    pub fn download(
        &self,
        release: &ReleaseInfo,
        progress: Option<&dyn Fn(u64, u64)>,
        cancelled: Option<&AtomicBool>,
    ) -> UpdateResult<PathBuf> {
        if !release.installable() {
            return Err(UpdateError::new("Este release não tem um pacote para instalar sozinho."));
        }
        let target = self.updates_dir.join(asset_name(&release.version));
        let partial = target.with_extension("part");
        let interrupted = || {
            UpdateError::new("O download foi interrompido. Confira a internet e o espaço em disco, e tente de novo.")
        };
        let result = (|| -> UpdateResult<(u64, String)> {
            std::fs::create_dir_all(&self.updates_dir).map_err(|_| interrupted())?;
            let mut body = self
                .http
                .get(&release.asset_url, &request_headers(), DOWNLOAD_TIMEOUT)
                .map_err(|_| interrupted())?;
            let mut file = std::fs::File::create(&partial).map_err(|_| interrupted())?;
            let mut digest = Sha256::new();
            let mut received = 0u64;
            let mut buffer = vec![0u8; CHUNK_BYTES];
            loop {
                let count = body.read(&mut buffer).map_err(|_| interrupted())?;
                if count == 0 {
                    break;
                }
                if cancelled.is_some_and(|c| c.load(Ordering::Relaxed)) {
                    return Err(UpdateError::Cancelled);
                }
                received += count as u64;
                if received > release.asset_size {
                    return Err(UpdateError::new("O download veio maior que o esperado e foi descartado."));
                }
                digest.update(&buffer[..count]);
                file.write_all(&buffer[..count]).map_err(|_| interrupted())?;
                if let Some(progress) = progress {
                    progress(received, release.asset_size);
                }
            }
            Ok((received, digest.finalize().iter().map(|b| format!("{b:02x}")).collect()))
        })();
        let (received, sha256) = match result {
            Ok(done) => done,
            Err(error) => {
                let _ = std::fs::remove_file(&partial);
                return Err(error);
            }
        };
        if received != release.asset_size || sha256 != release.sha256 {
            let _ = std::fs::remove_file(&partial);
            return Err(UpdateError::new(
                "O arquivo baixado não confere com o publicado no GitHub e foi descartado. Nada foi alterado.",
            ));
        }
        std::fs::rename(&partial, &target).map_err(|_| interrupted())?;
        Ok(target)
    }

    /// Extrai o pacote e devolve a pasta com o `.exe` novo.
    pub fn extract(&self, archive: &Path, version: &str) -> UpdateResult<PathBuf> {
        let destination = self.updates_dir.join(version);
        let _ = std::fs::remove_dir_all(&destination);
        let unreadable = || UpdateError::new("Não foi possível extrair o pacote baixado.");
        let file = std::fs::File::open(archive).map_err(|_| unreadable())?;
        let mut package = zip::ZipArchive::new(file).map_err(|_| unreadable())?;
        let mut total = 0u64;
        let mut names = Vec::with_capacity(package.len());
        for index in 0..package.len() {
            let entry = package.by_index(index).map_err(|_| unreadable())?;
            total += entry.size();
            names.push(entry.name().to_owned());
        }
        if total > MAX_EXTRACTED_BYTES {
            return Err(UpdateError::new("O pacote é grande demais para ser desta aplicação."));
        }
        for name in &names {
            let parts: Vec<&str> = name.split(['/', '\\']).collect();
            if parts[0] != APP_NAME || parts.contains(&"..") || name.contains(':') {
                return Err(UpdateError::new("O pacote baixado tem um formato inesperado."));
            }
        }
        for index in 0..package.len() {
            let mut entry = package.by_index(index).map_err(|_| unreadable())?;
            let path = destination.join(entry.name().replace('\\', "/"));
            if entry.is_dir() {
                std::fs::create_dir_all(&path).map_err(|_| unreadable())?;
                continue;
            }
            if let Some(parent) = path.parent() {
                std::fs::create_dir_all(parent).map_err(|_| unreadable())?;
            }
            let mut out = std::fs::File::create(&path).map_err(|_| unreadable())?;
            std::io::copy(&mut entry, &mut out).map_err(|_| unreadable())?;
        }
        let root = destination.join(APP_NAME);
        if !root.join(EXE_NAME).is_file() {
            return Err(UpdateError::new("O pacote baixado não tem o executável do programa."));
        }
        Ok(root)
    }
}

// ------------------------------------------------------------- instalação

/// Só o `.exe` com o nome original se atualiza; em desenvolvimento, o update é pelo git.
pub fn can_install_itself(installed: bool, executable: &Path) -> bool {
    installed && executable.file_name().is_some_and(|n| n == EXE_NAME)
}

/// Falha antes do download se o programa estiver numa pasta sem permissão de escrita.
pub fn ensure_writable(folder: &Path) -> UpdateResult<()> {
    let probe = folder.join(format!(".pxg-teste-{}", std::process::id()));
    match std::fs::OpenOptions::new().write(true).create_new(true).open(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
            Ok(())
        }
        Err(_) => Err(UpdateError::new(format!(
            "Sem permissão para alterar a pasta do programa ({}). Mova o programa para Documentos ou \
             baixe a versão nova pela página do GitHub.",
            folder.display()
        ))),
    }
}

/// Ambiente de um programa aberto pelo `.exe`: sem as bibliotecas da pasta dele. As variáveis do
/// PyInstaller e do Qt continuam tratadas, porque um `.exe` antigo pode abrir o novo e vice-versa.
pub fn child_environment(leaving_dir: &Path, environ: &HashMap<String, String>) -> HashMap<String, String> {
    let mut environment = environ.clone();
    environment.insert("PYINSTALLER_RESET_ENVIRONMENT".to_owned(), "1".to_owned());
    environment.remove("QT_PLUGIN_PATH");
    environment.remove("QT_QPA_PLATFORM_PLUGIN_PATH");
    let normalize = |p: &str| p.replace('/', "\\").to_lowercase();
    let folder = normalize(&leaving_dir.to_string_lossy());
    let separator = if cfg!(windows) { ';' } else { ':' };
    let path = environment.get("PATH").cloned().unwrap_or_default();
    let kept: Vec<&str> = path
        .split(separator)
        .filter(|entry| {
            let entry_norm = normalize(entry);
            !entry.is_empty() && entry_norm != folder && !entry_norm.starts_with(&format!("{folder}\\"))
        })
        .collect();
    environment.insert("PATH".to_owned(), kept.join(&separator.to_string()));
    environment
}

fn start_detached(program: &Path, arguments: &[String], cwd: &Path, environment: &HashMap<String, String>) -> std::io::Result<()> {
    let mut command = std::process::Command::new(program);
    command
        .args(arguments)
        .current_dir(cwd)
        .env_clear()
        .envs(environment)
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NEW_PROCESS_GROUP: u32 = 0x0000_0200;
        command.creation_flags(DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP);
    }
    command.spawn().map(|_| ())
}

fn current_environment() -> HashMap<String, String> {
    std::env::vars().collect()
}

/// Abre o `.exe` novo para instalar por cima de `target`, assim que `pid` fechar.
pub fn start_installer(new_root: &Path, target: &Path, pid: u32) -> UpdateResult<()> {
    let arguments = vec![APPLY_UPDATE_ARG.to_owned(), target.to_string_lossy().into_owned(), pid.to_string()];
    start_detached(&new_root.join(EXE_NAME), &arguments, new_root, &child_environment(target, &current_environment()))
        .map_err(|e| UpdateError::new(format!("Não foi possível abrir o instalador: {e}")))
}

/// Abre o programa instalado em `target`.
pub fn relaunch(target: &Path, leaving_dir: &Path) -> std::io::Result<()> {
    start_detached(&target.join(EXE_NAME), &[], target, &child_environment(leaving_dir, &current_environment()))
}

/// Espera o processo fechar; `false` se ele continuar aberto depois do tempo limite.
pub fn wait_for_exit(pid: u32, timeout: Duration) -> bool {
    #[cfg(windows)]
    {
        use windows_sys::Win32::Foundation::{CloseHandle, WAIT_TIMEOUT};
        use windows_sys::Win32::System::Threading::{OpenProcess, PROCESS_SYNCHRONIZE, WaitForSingleObject};
        // SAFETY: chamadas simples da API do Windows; o handle é fechado logo depois.
        unsafe {
            let handle = OpenProcess(PROCESS_SYNCHRONIZE, 0, pid);
            if handle.is_null() {
                return true; // já fechou
            }
            let millis = u32::try_from(timeout.as_millis()).unwrap_or(u32::MAX);
            let result = WaitForSingleObject(handle, millis);
            CloseHandle(handle);
            result != WAIT_TIMEOUT
        }
    }
    #[cfg(not(windows))]
    {
        let _ = (pid, timeout);
        true
    }
}

/// Operações de arquivo da troca; os testes simulam falhas no meio dela.
pub trait FileOps {
    fn rename(&self, source: &Path, target: &Path) -> std::io::Result<()>;
    fn copy_file(&self, source: &Path, target: &Path) -> std::io::Result<()>;
    fn sleep(&self, duration: Duration);
}

pub struct RealFileOps;

impl FileOps for RealFileOps {
    fn rename(&self, source: &Path, target: &Path) -> std::io::Result<()> {
        std::fs::rename(source, target)
    }

    fn copy_file(&self, source: &Path, target: &Path) -> std::io::Result<()> {
        std::fs::copy(source, target).map(|_| ())
    }

    fn sleep(&self, duration: Duration) {
        std::thread::sleep(duration);
    }
}

fn copy_tree(ops: &dyn FileOps, source: &Path, target: &Path) -> std::io::Result<()> {
    if source.is_dir() {
        std::fs::create_dir_all(target)?;
        for entry in std::fs::read_dir(source)? {
            let entry = entry?;
            copy_tree(ops, &entry.path(), &target.join(entry.file_name()))?;
        }
        Ok(())
    } else {
        ops.copy_file(source, target)
    }
}

/// Renomeia com novas tentativas: o antivírus pode segurar um arquivo por um instante.
fn move_with_retries(ops: &dyn FileOps, source: &Path, target: &Path) -> std::io::Result<()> {
    let mut attempt = 0;
    loop {
        match ops.rename(source, target) {
            Ok(()) => return Ok(()),
            Err(error) if attempt + 1 >= MOVE_ATTEMPTS => return Err(error),
            Err(_) => {
                attempt += 1;
                ops.sleep(MOVE_RETRY);
            }
        }
    }
}

pub fn apply_update(source: &Path, target: &Path) -> UpdateResult<()> {
    apply_update_with(source, target, &RealFileOps)
}

/// Troca os arquivos do programa em `target` pelos de `source`.
///
/// Primeiro copia tudo para dentro de `target`, a parte demorada e que pode falhar sem causar
/// dano. Depois só renomeia. Se algo falhar, devolve os arquivos antigos.
pub fn apply_update_with(source: &Path, target: &Path, ops: &dyn FileOps) -> UpdateResult<()> {
    if !source.join(EXE_NAME).is_file() || !target.join(EXE_NAME).is_file() {
        return Err(UpdateError::new("Não encontrei o executável do programa para atualizar."));
    }
    let same = match (source.canonicalize(), target.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => source == target,
    };
    if same {
        return Err(UpdateError::new("A versão nova já está na pasta do programa."));
    }
    let mut names: Vec<String> = std::fs::read_dir(source)
        .map_err(|e| UpdateError::new(format!("Não foi possível copiar a versão nova: {e}")))?
        .filter_map(|entry| entry.ok().map(|e| e.file_name().to_string_lossy().into_owned()))
        .filter(|name| !PROTECTED_NAMES.contains(&name.as_str()))
        .collect();
    names.sort();
    // Pastas antigas que o pacote não traz mais saem junto com os arquivos trocados.
    let legacy: Vec<String> = LEGACY_NAMES
        .iter()
        .filter(|name| !names.iter().any(|n| n == *name) && target.join(name).exists())
        .map(|name| (*name).to_owned())
        .collect();
    let (staging, old) = (target.join(STAGING_DIR), target.join(OLD_DIR));
    for folder in [&staging, &old] {
        let _ = std::fs::remove_dir_all(folder);
    }
    let copied = (|| -> std::io::Result<()> {
        std::fs::create_dir(&staging)?;
        std::fs::create_dir(&old)?;
        for name in &names {
            copy_tree(ops, &source.join(name), &staging.join(name))?;
        }
        Ok(())
    })();
    if let Err(error) = copied {
        let _ = std::fs::remove_dir_all(&staging);
        let _ = std::fs::remove_dir_all(&old);
        return Err(UpdateError::new(format!("Não foi possível copiar a versão nova: {error}")));
    }

    let mut moved_out: Vec<&String> = Vec::new();
    let mut moved_in: Vec<&String> = Vec::new();
    let swapped = (|| -> std::io::Result<()> {
        for name in names.iter().chain(&legacy) {
            if target.join(name).exists() {
                move_with_retries(ops, &target.join(name), &old.join(name))?;
                moved_out.push(name);
            }
        }
        for name in &names {
            move_with_retries(ops, &staging.join(name), &target.join(name))?;
            moved_in.push(name);
        }
        Ok(())
    })();
    if let Err(error) = swapped {
        let restored = (|| -> std::io::Result<()> {
            for name in &moved_in {
                move_with_retries(ops, &target.join(name), &staging.join(name))?;
            }
            for name in &moved_out {
                move_with_retries(ops, &old.join(name), &target.join(name))?;
            }
            Ok(())
        })();
        if let Err(restore_error) = restored {
            // Não apaga nada: os arquivos antigos continuam na pasta citada na mensagem.
            return Err(UpdateError::new(format!(
                "Não foi possível trocar os arquivos do programa nem devolver os antigos, que estão em {}. \
                 Baixe a versão nova pela página do GitHub. ({restore_error})",
                old.display()
            )));
        }
        let _ = std::fs::remove_dir_all(&staging);
        let _ = std::fs::remove_dir_all(&old);
        return Err(UpdateError::new(format!(
            "Não foi possível trocar os arquivos do programa, e a versão anterior foi mantida. Feche outras \
             janelas do programa e tente de novo. ({error})"
        )));
    }
    let _ = std::fs::remove_dir_all(&staging);
    let _ = std::fs::remove_dir_all(&old);
    Ok(())
}

/// Apaga o que sobrou de uma atualização; o que estiver em uso fica para a próxima abertura.
pub fn clean_leftovers(updates_dir: &Path, app_dir: &Path) {
    let _ = std::fs::remove_dir_all(updates_dir);
    let _ = std::fs::remove_dir_all(app_dir.join(OLD_DIR));
    let _ = std::fs::remove_dir_all(app_dir.join(STAGING_DIR));
}

/// O que o `.exe` novo faz com `--apply-update <pasta> <pid>` antes de abrir a janela.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct InstallRequest {
    pub target: PathBuf,
    pub pid: u32,
}

/// Lê `--apply-update <pasta> <pid>` dos argumentos; `None` se o argumento não estiver lá.
pub fn install_request(arguments: &[String]) -> Option<Result<InstallRequest, String>> {
    let position = arguments.iter().position(|a| a == APPLY_UPDATE_ARG)?;
    let target = arguments.get(position + 1);
    let pid = arguments.get(position + 2).and_then(|p| p.parse::<u32>().ok());
    Some(match (target, pid) {
        (Some(target), Some(pid)) => Ok(InstallRequest { target: PathBuf::from(target), pid }),
        _ => Err(format!("Argumentos inválidos para a atualização: {arguments:?}")),
    })
}

/// Espera a versão antiga fechar e troca os arquivos (a janela de progresso fica na interface).
pub fn install(source: &Path, request: &InstallRequest) -> UpdateResult<()> {
    if !wait_for_exit(request.pid, WAIT_EXIT) {
        return Err(UpdateError::new("O programa antigo não fechou a tempo. Feche-o e tente de novo."));
    }
    apply_update(source, &request.target)
}
