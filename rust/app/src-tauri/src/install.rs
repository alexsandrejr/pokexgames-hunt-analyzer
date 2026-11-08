//! Instalação feita pelo `.exe` novo (`--apply-update <pasta> <pid>`), antes de abrir o banco
//! (equivale a `app/ui/update/install_window.py`): uma janela pequena de progresso enquanto os
//! arquivos são trocados, o aviso se der errado e o programa reaberto no final.

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicI32, Ordering};

use pxg_core::update::{self, APP_NAME, InstallRequest};
use tauri::{Context, State, WebviewUrl, WebviewWindowBuilder};

/// Usado pelo script de build: instala sem avisos e sem reabrir o programa.
pub const SMOKE_TEST_ARG: &str = "--smoke-test";

/// Caixa de mensagem nativa, para os erros antes de existir uma janela.
pub fn native_error(text: &str) {
    #[cfg(windows)]
    {
        use windows_sys::Win32::UI::WindowsAndMessaging::{MB_ICONERROR, MB_OK, MessageBoxW};
        let wide = |s: &str| s.encode_utf16().chain(std::iter::once(0)).collect::<Vec<u16>>();
        let (text, title) = (wide(text), wide(APP_NAME));
        // SAFETY: os dois textos terminam em zero e vivem até o fim da chamada.
        unsafe {
            MessageBoxW(std::ptr::null_mut(), text.as_ptr(), title.as_ptr(), MB_OK | MB_ICONERROR);
        }
    }
    #[cfg(not(windows))]
    eprintln!("{text}");
}

/// Tema das configurações, para a janela de progresso seguir o do programa.
pub struct InstallTheme(pub String);

#[tauri::command]
pub fn install_theme(theme: State<'_, InstallTheme>) -> String {
    theme.0.clone()
}

static EXIT_CODE: AtomicI32 = AtomicI32::new(1);

/// Troca os arquivos, avisa se falhou e reabre o programa; devolve o código de saída.
fn finish(source: &Path, request: &InstallRequest, smoke_test: bool) -> i32 {
    let result = update::install(source, request);
    if let Err(error) = &result {
        log::error!("Falha ao instalar a atualização: {error}");
        if !smoke_test {
            native_error(&format!("A atualização não foi instalada.\n\n{error}"));
        }
    }
    if !smoke_test && request.target.join(update::EXE_NAME).is_file() {
        if let Err(error) = update::relaunch(&request.target, source) {
            log::error!("Falha ao reabrir o programa: {error}");
            native_error(&format!(
                "O programa não pôde ser aberto de novo. Abra-o pela pasta {}.\n\n{error}",
                request.target.display()
            ));
            return 1;
        }
    }
    log::info!("Atualização {}", if result.is_ok() { "instalada" } else { "falhou" });
    if result.is_ok() { 0 } else { 1 }
}

/// `None` sem `--apply-update` (o programa abre normalmente); senão, o código de saída. O contexto
/// só é consumido na instalação.
pub fn run_install(arguments: &[String], installed: bool, theme: String, context: &mut Option<Context>) -> Option<i32> {
    let request = match update::install_request(arguments) {
        None => return None,
        Some(Ok(request)) => request,
        Some(Err(message)) => {
            log::error!("{message}");
            return Some(2);
        }
    };
    let exe = std::env::current_exe().unwrap_or_default();
    // Fora do `.exe` instalado, a pasta de origem não tem o programa novo para copiar.
    if !update::can_install_itself(installed, &exe) {
        log::error!("A atualização só pode ser instalada pelo executável");
        return Some(2);
    }
    let source: PathBuf = exe.parent().map(Path::to_path_buf).unwrap_or_default();
    let smoke_test = arguments.iter().any(|a| a == SMOKE_TEST_ARG);
    log::info!("Instalando a atualização de {} em {}", source.display(), request.target.display());

    let context = context.take()?;
    let result = tauri::Builder::default()
        .manage(InstallTheme(theme))
        .invoke_handler(tauri::generate_handler![install_theme])
        .setup(move |app| {
            // Sem a janela, a instalação continua: ela só mostra o progresso.
            let window = WebviewWindowBuilder::new(app, "install", WebviewUrl::App("index.html#install".into()))
                .title(APP_NAME)
                .inner_size(420.0, 120.0)
                .resizable(false)
                .maximizable(false)
                .minimizable(false)
                .closable(false)
                .center()
                .build();
            if let Err(error) = window {
                log::warn!("Janela de instalação não aberta: {error}");
            }
            let handle = app.handle().clone();
            std::thread::spawn(move || {
                let code = finish(&source, &request, smoke_test);
                EXIT_CODE.store(code, Ordering::SeqCst);
                handle.exit(code);
            });
            Ok(())
        })
        .run(context);
    if let Err(error) = result {
        log::error!("Falha ao abrir a janela de instalação: {error}");
    }
    Some(EXIT_CODE.load(Ordering::SeqCst))
}
