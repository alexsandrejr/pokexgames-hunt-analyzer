//! PDF da exportação: o WebView2 imprime o HTML de `document_html` numa janela oculta.
//!
//! Faz o papel do `QPdfWriter` do Python: A4, margens de 12 mm, retrato ou paisagem.

use std::path::Path;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{mpsc, Mutex};
use std::time::Duration;

use tauri::webview::{PageLoadEvent, PlatformWebview};
use tauri::{AppHandle, Url, WebviewUrl, WebviewWindowBuilder};
use webview2_com::Microsoft::Web::WebView2::Win32::{
    ICoreWebView2Environment6, ICoreWebView2_7, COREWEBVIEW2_PRINT_ORIENTATION_LANDSCAPE,
    COREWEBVIEW2_PRINT_ORIENTATION_PORTRAIT,
};
use webview2_com::PrintToPdfCompletedHandler;
use windows::core::{Interface, HSTRING};

const MM_PER_INCH: f64 = 25.4;
const A4_WIDTH: f64 = 210.0 / MM_PER_INCH;
const A4_HEIGHT: f64 = 297.0 / MM_PER_INCH;
const MARGIN: f64 = 12.0 / MM_PER_INCH;
const PRINT_TIMEOUT: Duration = Duration::from_secs(60);

static COUNTER: AtomicUsize = AtomicUsize::new(0);

type PrintResult = Result<(), String>;

/// Imprime `html` em `target` (já com a extensão). Bloqueia até o arquivo ficar pronto.
pub async fn print_html(app: &AppHandle, html: &str, landscape: bool, target: &Path) -> PrintResult {
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    // Um arquivo, e não NavigateToString, porque este último recusa textos acima de 2 MB.
    let source = std::env::temp_dir().join(format!("pxg-pdf-{}-{n}.html", std::process::id()));
    std::fs::write(&source, with_print_style(html)).map_err(|e| format!("Não foi possível preparar o PDF: {e}"))?;
    let result = print_file(app, &source, n, landscape, target).await;
    let _ = std::fs::remove_file(&source);
    result
}

/// Acrescenta a codificação e as regras de quebra de página, sem mexer no HTML do núcleo
/// (que é conferido byte a byte com o do Python).
fn with_print_style(html: &str) -> String {
    const HEAD: &str = "<head><meta charset='utf-8'><style>\
        h2, h3 { break-after: avoid; } tr { break-inside: avoid; }\
        </style></head>";
    match html.strip_prefix("<html>") {
        Some(rest) => format!("<html>{HEAD}{rest}"),
        None => format!("{HEAD}{html}"),
    }
}

async fn print_file(app: &AppHandle, source: &Path, n: usize, landscape: bool, target: &Path) -> PrintResult {
    let url = Url::from_file_path(source).map_err(|()| "Caminho temporário inválido para o PDF.".to_owned())?;
    let (sender, receiver) = mpsc::channel::<PrintResult>();
    // Só a primeira carga completa imprime.
    let pending = Mutex::new(Some((sender, target.to_path_buf())));
    let window = WebviewWindowBuilder::new(app, format!("pdf-{n}"), WebviewUrl::External(url))
        .visible(false)
        .skip_taskbar(true)
        .on_page_load(move |window, payload| {
            if payload.event() != PageLoadEvent::Finished {
                return;
            }
            let Some((sender, target)) = pending.lock().unwrap_or_else(|e| e.into_inner()).take() else {
                return;
            };
            let fallback = sender.clone();
            if let Err(e) = window.with_webview(move |platform| {
                if let Err(e) = start_print(&platform, landscape, &target, sender.clone()) {
                    let _ = sender.send(Err(e));
                }
            }) {
                let _ = fallback.send(Err(e.to_string()));
            }
        })
        .build()
        .map_err(|e| format!("Não foi possível preparar o PDF: {e}"))?;
    let outcome = tauri::async_runtime::spawn_blocking(move || receiver.recv_timeout(PRINT_TIMEOUT)).await;
    let _ = window.destroy();
    match outcome {
        Ok(Ok(result)) => result,
        Ok(Err(_)) => Err("O PDF demorou demais para ficar pronto.".to_owned()),
        Err(e) => Err(e.to_string()),
    }
}

/// Configura a página e pede o PDF; o resultado chega em `sender`.
fn start_print(platform: &PlatformWebview, landscape: bool, target: &Path, sender: mpsc::Sender<PrintResult>) -> PrintResult {
    let windows_error = |e: windows::core::Error| e.message();
    // SAFETY: chamadas COM na thread da janela, que é onde o Tauri roda `with_webview`.
    unsafe {
        let webview = platform.controller().CoreWebView2().map_err(windows_error)?;
        let webview: ICoreWebView2_7 = webview.cast().map_err(windows_error)?;
        let environment: ICoreWebView2Environment6 = platform.environment().cast().map_err(windows_error)?;
        let settings = environment.CreatePrintSettings().map_err(windows_error)?;
        settings
            .SetOrientation(if landscape {
                COREWEBVIEW2_PRINT_ORIENTATION_LANDSCAPE
            } else {
                COREWEBVIEW2_PRINT_ORIENTATION_PORTRAIT
            })
            .map_err(windows_error)?;
        settings.SetPageWidth(A4_WIDTH).map_err(windows_error)?;
        settings.SetPageHeight(A4_HEIGHT).map_err(windows_error)?;
        settings.SetMarginTop(MARGIN).map_err(windows_error)?;
        settings.SetMarginBottom(MARGIN).map_err(windows_error)?;
        settings.SetMarginLeft(MARGIN).map_err(windows_error)?;
        settings.SetMarginRight(MARGIN).map_err(windows_error)?;
        // As linhas alternadas e o cabeçalho das tabelas têm fundo.
        settings.SetShouldPrintBackgrounds(true).map_err(windows_error)?;
        settings.SetShouldPrintHeaderAndFooter(false).map_err(windows_error)?;
        let handler = PrintToPdfCompletedHandler::create(Box::new(move |result, ok| {
            let _ = sender.send(match result {
                Err(e) => Err(e.message()),
                Ok(()) if !ok => Err("O WebView2 não conseguiu gravar o PDF.".to_owned()),
                Ok(()) => Ok(()),
            });
            Ok(())
        }));
        webview.PrintToPdf(&HSTRING::from(target), &settings, &handler).map_err(windows_error)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::with_print_style;

    #[test]
    fn print_style_goes_inside_html_tag() {
        let html = with_print_style("<html><body>Sessões</body></html>");
        assert!(html.starts_with("<html><head><meta charset='utf-8'><style>"));
        assert!(html.ends_with("</style></head><body>Sessões</body></html>"));
    }
}
