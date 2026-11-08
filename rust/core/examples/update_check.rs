//! Consulta o último release no GitHub, como o app faz ao abrir (só leitura).
//!
//! ```text
//! cargo run -q -p pxg-core --example update_check -- [versão atual]
//! ```

fn main() {
    let current = std::env::args().nth(1).unwrap_or_else(|| pxg_core::APP_VERSION.to_owned());
    let service = pxg_core::update::UpdateService::with_http(
        std::env::temp_dir().join("pxg-update-check"),
        &current,
        Box::new(pxg_core::update::UreqHttp),
    );
    match service.check() {
        Ok(Some(release)) => println!(
            "versão nova para quem tem a {current}: {} (instalável: {}, {} bytes, página {})",
            release.version, release.installable(), release.asset_size, release.page_url
        ),
        Ok(None) => println!("a {current} já é a mais recente"),
        Err(error) => println!("erro: {error}"),
    }
}
