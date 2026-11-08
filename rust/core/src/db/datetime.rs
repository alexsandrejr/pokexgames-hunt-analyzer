//! Datas no banco, no mesmo texto que o SQLAlchemy grava nas colunas `DATETIME` do SQLite:
//! `AAAA-MM-DD HH:MM:SS.ffffff`, sempre com microssegundos.

use chrono::{NaiveDate, NaiveDateTime};

const STORAGE_FORMAT: &str = "%Y-%m-%d %H:%M:%S%.6f";

pub fn to_db(value: NaiveDateTime) -> String {
    value.format(STORAGE_FORMAT).to_string()
}

/// Lê o texto gravado pelo SQLAlchemy, com ou sem microssegundos, ou só a data.
pub fn from_db(text: &str) -> Option<NaiveDateTime> {
    let text = text.trim();
    ["%Y-%m-%d %H:%M:%S%.f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%.f", "%Y-%m-%d %H:%M"]
        .iter()
        .find_map(|fmt| NaiveDateTime::parse_from_str(text, fmt).ok())
        .or_else(|| {
            NaiveDate::parse_from_str(text, "%Y-%m-%d").ok().and_then(|d| d.and_hms_opt(0, 0, 0))
        })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn same_text_as_sqlalchemy() {
        let moment = NaiveDate::from_ymd_opt(2026, 11, 5)
            .unwrap()
            .and_hms_micro_opt(19, 18, 1, 26490)
            .unwrap();
        assert_eq!(to_db(moment), "2026-11-05 19:18:01.026490");
        assert_eq!(from_db("2026-11-05 19:18:01.026490"), Some(moment));
        let whole = NaiveDate::from_ymd_opt(2026, 11, 5).unwrap().and_hms_opt(19, 18, 1).unwrap();
        assert_eq!(to_db(whole), "2026-11-05 19:18:01.000000");
        assert_eq!(from_db("2026-11-05 19:18:01"), Some(whole));
        assert_eq!(from_db("ontem"), None);
    }
}
