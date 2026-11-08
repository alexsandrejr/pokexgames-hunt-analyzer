//! Utilidades de texto.

/// `str.isspace()` do Python: o espaço em branco do Unicode mais os separadores `\x1c`–`\x1f`,
/// que o `char::is_whitespace` do Rust não considera.
pub fn is_py_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()` do Python.
pub fn py_strip(text: &str) -> &str {
    text.trim_matches(is_py_space)
}

/// `str.lstrip()` do Python.
pub fn py_lstrip(text: &str) -> &str {
    text.trim_start_matches(is_py_space)
}

/// `str.split()` do Python (sem argumentos): separa em qualquer espaço e ignora os vazios.
pub fn py_split(text: &str) -> impl Iterator<Item = &str> {
    text.split(is_py_space).filter(|part| !part.is_empty())
}

/// Como o `str.casefold()` do Python, usado para comparar e ordenar nomes sem diferenciar
/// maiúsculas. Cobre os casos práticos: minúsculas e `ß` → `ss`.
pub fn casefold(text: &str) -> String {
    text.to_lowercase().replace('ß', "ss")
}

/// `sorted(items, key=lambda x: key(x).casefold())`: ordem estável, sem diferenciar maiúsculas.
pub fn sort_casefold<T>(items: &mut [T], key: impl Fn(&T) -> &str) {
    items.sort_by_cached_key(|item| casefold(key(item)));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn casefold_ignores_case() {
        assert_eq!(casefold("PADRÃO"), casefold("padrão"));
        assert_eq!(casefold("Straße"), "strasse");
        let mut names = vec!["muq", "Chumbin", "Muq", "bartolomeu"];
        sort_casefold(&mut names, |n| n);
        assert_eq!(names, ["bartolomeu", "Chumbin", "muq", "Muq"]); // estável nos empates
    }
}
