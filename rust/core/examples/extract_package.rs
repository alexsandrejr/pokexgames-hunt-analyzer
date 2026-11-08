//! Extrai o `.zip` do pacote como a atualização automática faz e mostra a pasta do programa.
//!
//! Usado por `tools/build_exe.mjs`, para testar a instalação a partir do próprio `.zip`.
//! Uso: cargo run -p pxg-core --example extract_package -- <pacote.zip> <versão> <pasta de destino>

use std::path::PathBuf;

use pxg_core::update::UpdateService;

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let [archive, version, destination] = arguments.as_slice() else {
        eprintln!("Uso: extract_package <pacote.zip> <versão> <pasta de destino>");
        std::process::exit(2);
    };
    match UpdateService::new(PathBuf::from(destination)).extract(&PathBuf::from(archive), version) {
        Ok(root) => println!("{}", root.display()),
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
