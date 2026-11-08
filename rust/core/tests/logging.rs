//! Log em arquivo: formato, filtro e rotação (como o `RotatingFileHandler` do Python).

use log::{Level, Log, Record};
use pxg_core::logging::{FileLogger, LOG_BACKUPS, LOG_FILE_NAME, MAX_LOG_BYTES, format_line};

fn write(logger: &FileLogger, target: &str, level: Level, text: &str) {
    logger.log(&Record::builder().target(target).level(level).args(format_args!("{text}")).build());
}

#[test]
fn line_follows_python_format() {
    let line = format_line(&Record::builder().target("pxg_core::db").level(Level::Warn).args(format_args!("oi")).build());
    // 2026-11-08 09:02:59,123 WARNING pxg_core::db: oi
    let (date, rest) = line.split_at(23);
    assert_eq!(date.as_bytes()[19], b',');
    assert_eq!(rest, " WARNING pxg_core::db: oi\n");
}

#[test]
fn keeps_only_own_records_from_info_up() {
    let dir = tempfile::tempdir().unwrap();
    let logger = FileLogger::open(&dir.path().join("logs")).unwrap();
    write(&logger, "pxg_app_lib", Level::Info, "nosso");
    write(&logger, "tauri::manager", Level::Info, "do tauri");
    write(&logger, "pxg_core", Level::Debug, "detalhe");
    logger.flush();
    let text = std::fs::read_to_string(dir.path().join("logs").join(LOG_FILE_NAME)).unwrap();
    assert!(text.contains("nosso"));
    assert!(!text.contains("do tauri"));
    assert!(!text.contains("detalhe"));
}

#[test]
fn rotates_after_one_megabyte_keeping_three_old_files() {
    let dir = tempfile::tempdir().unwrap();
    let logger = FileLogger::open(dir.path()).unwrap();
    let chunk = "x".repeat(100_000);
    // Cada arquivo cabe 9 linhas de ~100 kB; 50 linhas giram o log várias vezes.
    for _ in 0..50 {
        write(&logger, "pxg_core", Level::Info, &chunk);
    }
    logger.flush();
    let main = dir.path().join(LOG_FILE_NAME);
    assert!(std::fs::metadata(&main).unwrap().len() <= MAX_LOG_BYTES);
    for n in 1..=LOG_BACKUPS {
        let old = dir.path().join(format!("{LOG_FILE_NAME}.{n}"));
        let size = std::fs::metadata(&old).unwrap().len();
        assert!(size > MAX_LOG_BYTES - 200_000 && size <= MAX_LOG_BYTES, "{n}: {size}");
    }
    assert!(!dir.path().join(format!("{LOG_FILE_NAME}.{}", LOG_BACKUPS + 1)).exists());
}
