// Sem console no executável final; em desenvolvimento, o console mostra os logs.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    std::process::exit(pxg_app_lib::run());
}
