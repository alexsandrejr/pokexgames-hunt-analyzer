//! Porta de `tests/test_update.py` (sem as telas). Nenhum teste acessa a internet: as respostas
//! são simuladas. Inclui a troca vinda do Python, que precisa tirar a pasta `_internal`.

use std::cell::RefCell;
use std::collections::HashMap;
use std::io::{Cursor, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::time::Duration;

use pxg_core::update::{
    APP_NAME, EXE_NAME, FileOps, Http, HttpError, OLD_DIR, RealFileOps, ReleaseInfo, STAGING_DIR, UpdateError,
    UpdateService, api_url, apply_update, apply_update_with, asset_name, can_install_itself, child_environment,
    clean_leftovers, download_prefix, ensure_writable, install_request, is_newer, parse_release, parse_version,
    releases_url, user_agent, wait_for_exit,
};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};

fn sha256(content: &[u8]) -> String {
    Sha256::digest(content).iter().map(|b| format!("{b:02x}")).collect()
}

fn package_bytes(entries: &[(&str, &[u8])]) -> Vec<u8> {
    let mut buffer = Cursor::new(Vec::new());
    {
        let mut archive = zip::ZipWriter::new(&mut buffer);
        for (name, content) in entries {
            archive.start_file(*name, zip::write::SimpleFileOptions::default()).unwrap();
            archive.write_all(content).unwrap();
        }
        archive.finish().unwrap();
    }
    buffer.into_inner()
}

fn default_package() -> Vec<u8> {
    let exe = format!("{APP_NAME}/{EXE_NAME}");
    let lib = format!("{APP_NAME}/_internal/lib.dll");
    package_bytes(&[(exe.as_str(), b"exe novo"), (lib.as_str(), b"lib nova")])
}

fn release_json(tag: &str, content: &[u8]) -> Value {
    let version = tag.trim_start_matches('v');
    json!({
        "tag_name": tag, "body": "## Novidades", "draft": false, "prerelease": false,
        "html_url": format!("https://github.com/alexsandrejr/pokexgames-hunt-analyzer/releases/tag/{tag}"),
        "assets": [{
            "name": asset_name(version), "size": content.len(),
            "digest": format!("sha256:{}", sha256(content)),
            "browser_download_url": format!("{}{tag}/{}", download_prefix(), asset_name(version)),
        }],
    })
}

fn release_info(content: &[u8]) -> ReleaseInfo {
    parse_release(&release_json("v9.0.0", content), "1.0.0").unwrap().unwrap()
}

/// Um pedido registrado: URL e cabeçalhos.
type Recorded = (String, Vec<(String, String)>);

/// Faz o papel da rede: uma resposta por URL e o registro dos pedidos.
struct FakeHttp {
    responses: HashMap<String, Result<Vec<u8>, u16>>,
    requests: Mutex<Vec<Recorded>>,
}

impl FakeHttp {
    fn new(responses: Vec<(String, Result<Vec<u8>, u16>)>) -> Self {
        Self { responses: responses.into_iter().collect(), requests: Mutex::new(Vec::new()) }
    }
}

impl Http for FakeHttp {
    fn get(&self, url: &str, headers: &[(&str, String)], _timeout: Duration) -> Result<Box<dyn Read + Send>, HttpError> {
        let headers = headers.iter().map(|(k, v)| ((*k).to_owned(), v.clone())).collect();
        self.requests.lock().unwrap().push((url.to_owned(), headers));
        match self.responses.get(url) {
            Some(Ok(bytes)) => Ok(Box::new(Cursor::new(bytes.clone()))),
            Some(Err(0)) | None => Err(HttpError::Network("sem rede".into())),
            Some(Err(code)) => Err(HttpError::Status(*code)),
        }
    }
}

fn message(error: UpdateError) -> String {
    match error {
        UpdateError::Message(text) => text,
        UpdateError::Cancelled => "cancelado".into(),
    }
}

// ----------------------------------------------------------------- versões

#[test]
fn versions() {
    assert_eq!(parse_version("v1.10.0"), Some(vec![1, 10, 0]));
    assert_eq!(parse_version("1.6"), Some(vec![1, 6]));
    for text in ["", "versao", "v1.2-beta", "1..2"] {
        assert_eq!(parse_version(text), None, "{text}");
    }
    assert!(is_newer(&[1, 10, 0], &[1, 9, 0]));
    assert!(!is_newer(&[1, 6, 0], &[1, 6, 0]));
    assert!(!is_newer(&[1, 5, 0], &[1, 6, 0]));
    assert!(!is_newer(&[1, 6], &[1, 6, 0]));
    assert!(is_newer(&[1, 6, 0, 1], &[1, 6]));
    // A primeira versão em Rust é oferecida a quem tem a 1.6.0.
    assert!(is_newer(&parse_version(pxg_core::APP_VERSION).unwrap(), &[1, 6, 0]));
}

#[test]
fn newer_release_is_installable() {
    let release = parse_release(&release_json("v9.0.0", b"abc"), "1.6.0").unwrap().unwrap();
    assert_eq!(release.version, "9.0.0");
    assert_eq!(release.notes, "## Novidades");
    assert_eq!(release.sha256, sha256(b"abc"));
    assert!(release.installable());
}

#[test]
fn same_older_draft_and_prerelease_are_not_offered() {
    assert_eq!(parse_release(&release_json("v1.6.0", b"zip"), "1.6.0").unwrap(), None);
    assert_eq!(parse_release(&release_json("v1.5.0", b"zip"), "1.6.0").unwrap(), None);
    for key in ["draft", "prerelease"] {
        let mut data = release_json("v9.0.0", b"zip");
        data[key] = json!(true);
        assert_eq!(parse_release(&data, "1.6.0").unwrap(), None);
    }
}

#[test]
fn without_a_safe_package_only_the_page_is_offered() {
    let changed = |key: &str, value: Value| {
        let mut data = release_json("v9.0.0", b"zip");
        data["assets"][0][key] = value;
        data
    };
    let mut no_assets = release_json("v9.0.0", b"zip");
    no_assets["assets"] = json!([]);
    let cases = [
        no_assets,
        changed("name", json!("outro.zip")),
        changed("digest", Value::Null),
        changed("digest", json!("md5:abc")),
        changed("browser_download_url", json!("https://exemplo.com/virus.zip")),
        changed("browser_download_url", json!("https://github.com/outro/repo/releases/download/x.zip")),
        changed("browser_download_url", json!(download_prefix().replace("https", "http") + "x.zip")),
    ];
    for data in cases {
        let release = parse_release(&data, "1.6.0").unwrap().unwrap();
        assert_eq!(release.version, "9.0.0");
        assert!(!release.installable(), "{data}");
    }
}

#[test]
fn page_url_from_elsewhere_is_ignored_and_bad_answers_fail() {
    let mut data = release_json("v9.0.0", b"zip");
    data["html_url"] = json!("https://exemplo.com/");
    assert_eq!(parse_release(&data, "1.6.0").unwrap().unwrap().page_url, releases_url());
    for data in [json!([]), json!({}), json!({"tag_name": "nightly"}), json!({"tag_name": 5})] {
        assert!(parse_release(&data, "1.6.0").is_err(), "{data}");
    }
}

// --------------------------------------------------------------- verificação

#[test]
fn request_identifies_only_the_app() {
    let http = FakeHttp::new(vec![(api_url(), Ok(release_json("v1.0.0", b"zip").to_string().into_bytes()))]);
    let service = UpdateService::with_http(PathBuf::from("."), "1.6.0", Box::new(http));
    assert_eq!(service.check().unwrap(), None);
}

#[test]
fn headers_have_only_the_app_name() {
    let http = FakeHttp::new(vec![(api_url(), Ok(b"{}".to_vec()))]);
    let _ = http.get(&api_url(), &[("User-Agent", user_agent())], Duration::ZERO);
    let requests = http.requests.lock().unwrap();
    assert_eq!(requests[0].1, [("User-Agent".to_owned(), user_agent())]);
    assert!(user_agent().starts_with("PokeXGames-Hunt-Analyzer/"));
}

#[test]
fn no_release_published_is_not_an_error_and_failures_become_a_message() {
    let check = |response: Result<Vec<u8>, u16>| {
        UpdateService::with_http(PathBuf::from("."), "1.6.0", Box::new(FakeHttp::new(vec![(api_url(), response)])))
            .check()
    };
    assert_eq!(check(Err(404)).unwrap(), None);
    assert!(message(check(Err(403)).unwrap_err()).contains("código 403"));
    assert!(message(check(Err(0)).unwrap_err()).contains("internet"));
    assert!(check(Ok(b"<html>".to_vec())).is_err());
}

// ----------------------------------------------------------------- download

struct Downloads {
    _dir: tempfile::TempDir,
    updates: PathBuf,
}

impl Downloads {
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let updates = dir.path().join("updates");
        Self { _dir: dir, updates }
    }

    fn service(&self, release: &ReleaseInfo, content: Result<Vec<u8>, u16>) -> UpdateService {
        UpdateService::with_http(self.updates.clone(), "1.0.0", Box::new(FakeHttp::new(vec![(release.asset_url.clone(), content)])))
    }

    fn leftovers(&self) -> usize {
        std::fs::read_dir(&self.updates).map_or(0, |entries| entries.count())
    }
}

#[test]
fn download_and_extract() {
    let d = Downloads::new();
    let content = default_package();
    let release = release_info(&content);
    let service = d.service(&release, Ok(content.clone()));
    let seen = RefCell::new(Vec::new());
    let progress = |done, total| seen.borrow_mut().push((done, total));
    let archive = service.download(&release, Some(&progress), None).unwrap();
    assert_eq!(seen.borrow().last(), Some(&(content.len() as u64, content.len() as u64)));
    let root = service.extract(&archive, &release.version).unwrap();
    assert_eq!(root.file_name().unwrap(), APP_NAME);
    assert_eq!(std::fs::read(root.join(EXE_NAME)).unwrap(), b"exe novo");
    assert_eq!(std::fs::read(root.join("_internal").join("lib.dll")).unwrap(), b"lib nova");
}

#[test]
fn different_shorter_and_bigger_contents_are_discarded() {
    let d = Downloads::new();
    let content = default_package();
    let release = release_info(&content);
    let mut tampered = content.clone();
    tampered[0] ^= 1;
    let error = d.service(&release, Ok(tampered)).download(&release, None, None).unwrap_err();
    assert!(message(error).contains("não confere"));
    assert_eq!(d.leftovers(), 0);
    let mut bigger = content.clone();
    bigger.push(b'x');
    for data in [content[..content.len() - 1].to_vec(), bigger] {
        assert!(d.service(&release, Ok(data)).download(&release, None, None).is_err());
        assert_eq!(d.leftovers(), 0);
    }
}

#[test]
fn network_failure_cancel_and_release_without_package() {
    let d = Downloads::new();
    let content = default_package();
    let release = release_info(&content);
    assert!(message(d.service(&release, Err(0)).download(&release, None, None).unwrap_err()).contains("interrompido"));
    let cancelled = AtomicBool::new(true);
    assert_eq!(d.service(&release, Ok(content)).download(&release, None, Some(&cancelled)).unwrap_err(), UpdateError::Cancelled);
    assert_eq!(d.leftovers(), 0);
    let page_only = ReleaseInfo::page_only("9.0.0", "", &releases_url());
    assert!(d.service(&page_only, Err(0)).download(&page_only, None, None).is_err());
}

#[test]
fn bad_packages_are_refused() {
    let d = Downloads::new();
    let exe = format!("{APP_NAME}/{EXE_NAME}");
    let up = format!("{APP_NAME}/../../virus.exe");
    let absolute = format!("{APP_NAME}/C:/virus.exe");
    let readme = format!("{APP_NAME}/LEIA-ME.txt");
    let cases: Vec<Vec<u8>> = vec![
        package_bytes(&[(exe.as_str(), b"x"), ("virus.exe", b"x")]),
        package_bytes(&[(exe.as_str(), b"x"), (up.as_str(), b"x")]),
        package_bytes(&[(absolute.as_str(), b"x")]),
        package_bytes(&[(readme.as_str(), b"x")]),
        b"isto nao e um zip".to_vec(),
    ];
    std::fs::create_dir_all(&d.updates).unwrap();
    for content in cases {
        let archive = d.updates.join("pacote.zip");
        std::fs::write(&archive, content).unwrap();
        assert!(UpdateService::new(d.updates.clone()).extract(&archive, "9.0.0").is_err());
    }
}

// ----------------------------------------------------------------- troca

struct Install {
    _dir: tempfile::TempDir,
    source: PathBuf,
    target: PathBuf,
}

fn write(path: &Path, text: &str) {
    std::fs::create_dir_all(path.parent().unwrap()).unwrap();
    std::fs::write(path, text).unwrap();
}

impl Install {
    /// Pacote novo (como o do PyInstaller) e uma instalação antiga com dados do usuário.
    fn new() -> Self {
        let dir = tempfile::tempdir().unwrap();
        let (source, target) = (dir.path().join("novo"), dir.path().join("instalado"));
        write(&source.join(EXE_NAME), "exe novo");
        write(&source.join("_internal").join("lib.dll"), "lib nova");
        write(&source.join("LEIA-ME.txt"), "leia novo");
        write(&target.join(EXE_NAME), "exe antigo");
        write(&target.join("_internal").join("lib.dll"), "lib antiga");
        write(&target.join("_internal").join("so_na_antiga.dll"), "antiga");
        write(&target.join("data").join("hunts.db"), "meus dados");
        write(&target.join("minhas_notas.txt"), "notas");
        Self { _dir: dir, source, target }
    }

    fn read(&self, parts: &[&str]) -> String {
        std::fs::read_to_string(parts.iter().fold(self.target.clone(), |p, part| p.join(part))).unwrap()
    }
}

#[test]
fn replaces_the_program_files() {
    let i = Install::new();
    apply_update(&i.source, &i.target).unwrap();
    assert_eq!(i.read(&[EXE_NAME]), "exe novo");
    assert_eq!(i.read(&["_internal", "lib.dll"]), "lib nova");
    assert_eq!(i.read(&["LEIA-ME.txt"]), "leia novo");
    assert!(!i.target.join("_internal").join("so_na_antiga.dll").exists());
    assert!(!i.target.join(STAGING_DIR).exists() && !i.target.join(OLD_DIR).exists());
}

#[test]
fn update_from_python_removes_the_pyinstaller_folder() {
    // O pacote em Rust traz só o .exe; a pasta _internal da 1.6.0 não pode sobrar.
    let i = Install::new();
    std::fs::remove_dir_all(i.source.join("_internal")).unwrap();
    apply_update(&i.source, &i.target).unwrap();
    assert_eq!(i.read(&[EXE_NAME]), "exe novo");
    assert!(!i.target.join("_internal").exists());
    assert_eq!(i.read(&["data", "hunts.db"]), "meus dados");
    assert_eq!(i.read(&["minhas_notas.txt"]), "notas");
}

#[test]
fn keeps_portable_data_and_other_files() {
    let i = Install::new();
    write(&i.source.join("data").join("hunts.db"), "pacote malfeito");
    apply_update(&i.source, &i.target).unwrap();
    assert_eq!(i.read(&["data", "hunts.db"]), "meus dados");
    assert_eq!(i.read(&["minhas_notas.txt"]), "notas");
}

/// Operações reais, com falhas programadas em renomeações específicas.
struct Failing {
    fail_on: Vec<PathBuf>,
    transient: RefCell<usize>,
}

impl FileOps for Failing {
    fn rename(&self, source: &Path, target: &Path) -> std::io::Result<()> {
        if *self.transient.borrow() > 0 {
            *self.transient.borrow_mut() -= 1;
            return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "antivírus"));
        }
        if self.fail_on.iter().any(|p| p == source) {
            return Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "em uso"));
        }
        RealFileOps.rename(source, target)
    }

    fn copy_file(&self, source: &Path, target: &Path) -> std::io::Result<()> {
        RealFileOps.copy_file(source, target)
    }

    fn sleep(&self, _duration: Duration) {}
}

#[test]
fn failure_while_swapping_restores_the_old_version() {
    let i = Install::new();
    // Já tirou os antigos e pôs parte dos novos; falha ao pôr o _internal novo.
    let ops = Failing { fail_on: vec![i.target.join(STAGING_DIR).join("_internal")], transient: RefCell::new(0) };
    assert!(message(apply_update_with(&i.source, &i.target, &ops).unwrap_err()).contains("versão anterior"));
    assert_eq!(i.read(&[EXE_NAME]), "exe antigo");
    assert_eq!(i.read(&["_internal", "lib.dll"]), "lib antiga");
    assert_eq!(i.read(&["_internal", "so_na_antiga.dll"]), "antiga");
    assert!(!i.target.join("LEIA-ME.txt").exists());
    assert!(!i.target.join(STAGING_DIR).exists() && !i.target.join(OLD_DIR).exists());
}

#[test]
fn failure_while_restoring_keeps_the_old_files_and_says_where() {
    let i = Install::new();
    let ops = Failing {
        fail_on: vec![i.target.join(STAGING_DIR).join("_internal"), i.target.join(OLD_DIR).join("_internal")],
        transient: RefCell::new(0),
    };
    assert!(message(apply_update_with(&i.source, &i.target, &ops).unwrap_err()).contains("nem devolver"));
    assert_eq!(std::fs::read_to_string(i.target.join(OLD_DIR).join("_internal").join("lib.dll")).unwrap(), "lib antiga");
    assert_eq!(i.read(&["data", "hunts.db"]), "meus dados");
}

struct DiskFull;

impl FileOps for DiskFull {
    fn rename(&self, source: &Path, target: &Path) -> std::io::Result<()> {
        RealFileOps.rename(source, target)
    }

    fn copy_file(&self, _source: &Path, _target: &Path) -> std::io::Result<()> {
        Err(std::io::Error::other("disco cheio"))
    }

    fn sleep(&self, _duration: Duration) {}
}

#[test]
fn failure_while_copying_changes_nothing() {
    let i = Install::new();
    assert!(message(apply_update_with(&i.source, &i.target, &DiskFull).unwrap_err()).contains("copiar"));
    assert_eq!(i.read(&[EXE_NAME]), "exe antigo");
    assert!(!i.target.join(STAGING_DIR).exists());
}

#[test]
fn temporary_lock_is_retried() {
    let i = Install::new();
    let ops = Failing { fail_on: vec![], transient: RefCell::new(2) };
    apply_update_with(&i.source, &i.target, &ops).unwrap();
    assert_eq!(i.read(&[EXE_NAME]), "exe novo");
}

#[test]
fn refuses_folders_without_the_program() {
    let i = Install::new();
    std::fs::remove_file(i.target.join(EXE_NAME)).unwrap();
    assert!(apply_update(&i.source, &i.target).is_err());
    assert!(apply_update(&i.source, &i.source).is_err()); // o exe existe, mas é a mesma pasta
    assert_eq!(i.read(&["data", "hunts.db"]), "meus dados");
}

#[test]
fn clean_leftovers_keeps_the_data() {
    let i = Install::new();
    let updates = i.target.join("data").join("updates");
    write(&updates.join("1.0.0").join("x.txt"), "x");
    write(&i.target.join(OLD_DIR).join("x.txt"), "x");
    clean_leftovers(&updates, &i.target);
    assert!(!updates.exists() && !i.target.join(OLD_DIR).exists());
    assert_eq!(i.read(&["data", "hunts.db"]), "meus dados");
}

// ---------------------------------------------------------------- ambiente

#[test]
fn only_the_original_exe_installs_itself() {
    assert!(can_install_itself(true, &Path::new("C:/app").join(EXE_NAME)));
    assert!(!can_install_itself(false, &Path::new("C:/app").join(EXE_NAME)));
    assert!(!can_install_itself(true, Path::new("C:/app/renomeado.exe")));
}

#[test]
fn child_does_not_inherit_the_old_libraries() {
    let old = Path::new("C:/app/antigo");
    let environ: HashMap<String, String> = [
        ("PATH", "C:\\app\\antigo\\_internal;C:\\app\\antigo;C:/Windows;C:/app/antigo2"),
        ("QT_PLUGIN_PATH", "x"),
        ("QT_QPA_PLATFORM_PLUGIN_PATH", "y"),
        ("OUTRA", "z"),
    ]
    .into_iter()
    .map(|(k, v)| (k.to_owned(), v.to_owned()))
    .collect();
    let environment = child_environment(old, &environ);
    assert_eq!(environment["PATH"], "C:/Windows;C:/app/antigo2");
    assert!(!environment.contains_key("QT_PLUGIN_PATH") && !environment.contains_key("QT_QPA_PLATFORM_PLUGIN_PATH"));
    assert_eq!(environment["PYINSTALLER_RESET_ENVIRONMENT"], "1");
    assert_eq!(environment["OUTRA"], "z");
}

#[test]
fn waits_for_the_process_to_exit() {
    let mut process = std::process::Command::new("cmd")
        .args(["/C", "ping -n 30 127.0.0.1 >NUL"])
        .stdout(std::process::Stdio::null())
        .spawn()
        .unwrap();
    assert!(!wait_for_exit(process.id(), Duration::from_millis(50)));
    process.kill().unwrap();
    process.wait().unwrap();
    assert!(wait_for_exit(process.id(), Duration::from_secs(5)));
}

#[test]
fn writable_folders() {
    let dir = tempfile::tempdir().unwrap();
    ensure_writable(dir.path()).unwrap();
    assert!(message(ensure_writable(&dir.path().join("nao_existe")).unwrap_err()).contains("Sem permissão"));
}

#[test]
fn install_arguments_from_python() {
    // É exatamente assim que a 1.6.0 em Python abre o .exe novo.
    let args: Vec<String> = ["C:\\novo\\PokeXGames Hunt Analyzer.exe", "--apply-update", "C:\\Programas\\PXG", "4242"]
        .iter()
        .map(|s| (*s).to_owned())
        .collect();
    let request = install_request(&args).unwrap().unwrap();
    assert_eq!((request.target, request.pid), (PathBuf::from("C:\\Programas\\PXG"), 4242));
    assert!(install_request(&args[..1]).is_none());
    assert!(install_request(&args[..3]).unwrap().is_err());
}
