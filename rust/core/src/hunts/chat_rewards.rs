//! Leitura das mensagens "Você recebeu: ..." do chat do PokeXGames (equivale a
//! `app/services/chat_rewards.py`).
//!
//! Recompensas de boss, Secret Lab etc. podem vir numa sacola aberta depois da sessão: os itens
//! aparecem só no chat, não no JSON do Analyzer. Este módulo extrai quantidade e nome de cada
//! item e aproxima o nome do item já conhecido no banco (`Echo Shards` → `Echo Shard`). Não
//! conhece o banco: os nomes conhecidos são passados por quem chama.

use std::collections::HashMap;
use std::sync::LazyLock;

use regex::Regex;

use crate::text::{py_split, py_strip};

/// O texto depois de "Você recebeu:" até o fim da linha. Aceita o chat em inglês.
static MESSAGE: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"(?i)(?:voc[eê]\s+recebeu|you\s+received)\s*:\s*(.+)").expect("regex válida")
});
/// Os itens são separados por vírgula.
static ITEM_SEPARATOR: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\s*,\s*").expect("regex válida"));
/// "1380 tech data", "1.380 tech data", "1 10.000 carat emerald" (1 × "10.000 carat emerald").
static ITEM: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^([0-9]{1,3}(?:\.[0-9]{3})+|[0-9]+)\s+(.+)$").expect("regex válida")
});
/// Sufixo entre parênteses que não faz parte do plural: "Technological Crystal (Tier: 7)".
static SUFFIX: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(.*?)(\s*\(.*\))?$").expect("regex válida"));

/// Nomes do chat que diferem do nome do item no Analyzer (em minúsculas).
fn alias(name: &str) -> Option<&'static str> {
    match name {
        "hundred dollars" | "hundred dollar" => Some("one hundred dollars"),
        _ => None,
    }
}

/// Um item da mensagem, com o nome como veio no chat.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChatItem {
    pub name: String,
    pub count: i64,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ParsedChatRewards {
    /// Uma por "Você recebeu:".
    pub messages: Vec<String>,
    pub items: Vec<ChatItem>,
    /// Trechos sem quantidade.
    pub invalid: Vec<String>,
}

fn collapse_spaces(text: &str) -> String {
    py_split(text).collect::<Vec<_>>().join(" ")
}

/// Extrai os itens de uma ou mais mensagens "Você recebeu:" (uma por linha).
///
/// Linhas sem a mensagem (horário, outras falas do chat) são ignoradas.
pub fn parse_chat_rewards(text: &str) -> ParsedChatRewards {
    let mut parsed = ParsedChatRewards::default();
    for captures in MESSAGE.captures_iter(text) {
        let body = py_strip(py_strip(&captures[1]).trim_end_matches('.'));
        if body.is_empty() {
            continue;
        }
        parsed.messages.push(normalize_message(&captures[0]));
        for part in ITEM_SEPARATOR.split(body) {
            let part = py_strip(part);
            let parsed_item = ITEM.captures(part).and_then(|item| {
                let count = item[1].replace('.', "").parse::<i64>().ok()?;
                Some(ChatItem { name: collapse_spaces(&item[2]), count })
            });
            match parsed_item {
                Some(item) => parsed.items.push(item),
                None if !part.is_empty() => parsed.invalid.push(part.to_owned()),
                None => {}
            }
        }
    }
    parsed
}

/// Mensagem sem espaços repetidos nem ponto final (para reconhecer repetições).
pub fn normalize_message(message: &str) -> String {
    py_strip(collapse_spaces(message).trim_end_matches('.')).to_owned()
}

/// Nome do item no banco para o nome do chat; devolve `(nome, conhecido)`.
///
/// `known` é `{nome em minúsculas: nome como exibido}`. Tenta o nome exato, os apelidos e as
/// formas no singular; se nenhuma for conhecida, um nome no plural (quantidade maior que 1) vai
/// para o singular.
pub fn resolve_item_name(name: &str, count: i64, known: &HashMap<String, String>) -> (String, bool) {
    let candidates = std::iter::once(name.to_owned()).chain(singular_forms(name));
    for candidate in candidates {
        let key = candidate.to_lowercase();
        let key = alias(&key).map_or(key, str::to_owned);
        if let Some(found) = known.get(&key) {
            return (found.clone(), true);
        }
    }
    if let Some(alias) = alias(&name.to_lowercase()) {
        return (alias.to_owned(), false);
    }
    if count > 1 {
        return (default_singular(name), false);
    }
    (name.to_owned(), false)
}

/// Última palavra sem os `n` últimos caracteres (índices do Python contam caracteres).
fn drop_last(word: &str, n: usize) -> String {
    let keep = word.chars().count().saturating_sub(n);
    word.chars().take(keep).collect()
}

fn singular_forms(name: &str) -> Vec<String> {
    let (head, suffix) = split_suffix(name);
    let words: Vec<&str> = head.split(' ').collect();
    let last = *words.last().unwrap_or(&"");
    let lower = last.to_lowercase();
    let length = last.chars().count();
    let mut forms = Vec::new();
    if lower.ends_with("ies") && length > 3 {
        forms.push(drop_last(last, 3) + "y");
    }
    if lower.ends_with("es") && length > 2 {
        forms.push(drop_last(last, 2));
    }
    if lower.ends_with('s') && !lower.ends_with("ss") && length > 1 {
        forms.push(drop_last(last, 1));
    }
    let prefix = &words[..words.len().saturating_sub(1)];
    forms
        .into_iter()
        .map(|form| {
            let mut all: Vec<&str> = prefix.to_vec();
            all.push(&form);
            all.join(" ") + &suffix
        })
        .collect()
}

/// Singular por regra simples, usado só para nomes que o banco ainda não conhece.
fn default_singular(name: &str) -> String {
    let (head, suffix) = split_suffix(name);
    let words: Vec<&str> = head.split(' ').collect();
    let last = *words.last().unwrap_or(&"");
    let lower = last.to_lowercase();
    let length = last.chars().count();
    let singular = if lower.ends_with("ies") && length > 3 {
        drop_last(last, 3) + "y"
    } else if ["ches", "shes", "sses", "xes", "zes"].iter().any(|end| lower.ends_with(end)) {
        drop_last(last, 2)
    } else if lower.ends_with('s') && !["ss", "us", "is"].iter().any(|end| lower.ends_with(end)) && length > 1 {
        drop_last(last, 1)
    } else {
        last.to_owned()
    };
    let mut all: Vec<&str> = words[..words.len().saturating_sub(1)].to_vec();
    all.push(&singular);
    all.join(" ") + &suffix
}

fn split_suffix(name: &str) -> (String, String) {
    let captures = SUFFIX.captures(name).expect("o padrão aceita qualquer texto");
    (
        captures.get(1).map_or("", |m| m.as_str()).to_owned(),
        captures.get(2).map_or("", |m| m.as_str()).to_owned(),
    )
}
