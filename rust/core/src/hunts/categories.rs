//! Categorias de sessão: Hunts comuns e os quatro tipos de boss do PokeXGames (equivale a
//! `app/services/categories.py`).
//!
//! O JSON do Analyzer é igual para Hunts e bosses, então a categoria não vem no arquivo: ela é
//! decidida na importação e pode ser trocada depois. O valor gravado em
//! `hunt_sessions.category` é o de [`Category::as_str`].

use std::path::{Path, PathBuf};

use crate::macros::text_enum;

text_enum!(Category {
    Hunt = "hunt" => "Hunt",
    Rift = "rift" => "Rift",
    BossRed = "boss_red" => "Boss de Energia Vermelha",
    BossBlue = "boss_blue" => "Boss de Energia Azul",
    Terror = "terror" => "Terror",
});

impl Category {
    /// Categoria gravada no banco; valores desconhecidos contam como Hunt.
    pub fn from_value(value: Option<&str>) -> Self {
        value.and_then(|v| v.parse().ok()).unwrap_or(Self::Hunt)
    }

    pub fn is_boss(self) -> bool {
        self != Self::Hunt
    }

    /// Nome da categoria em abas e listas ("Terrors").
    pub fn plural(self) -> &'static str {
        match self {
            Self::Hunt => "Hunts",
            Self::Rift => "Rifts",
            Self::BossRed => "Energia Vermelha",
            Self::BossBlue => "Energia Azul",
            Self::Terror => "Terrors",
        }
    }

    /// Subpasta de `imports` onde os JSONs colados são salvos (Hunts: a própria).
    pub fn folder(self) -> Option<&'static str> {
        match self {
            Self::Hunt => None,
            Self::Rift => Some("rifts"),
            Self::BossRed => Some("energia_vermelha"),
            Self::BossBlue => Some("energia_azul"),
            Self::Terror => Some("terrors"),
        }
    }

    pub fn bosses() -> impl Iterator<Item = Self> {
        Self::ALL.iter().copied().filter(|c| c.is_boss())
    }
}

/// Pasta dos JSONs colados da categoria.
pub fn category_dir(imports_dir: &Path, category: Category) -> PathBuf {
    match category.folder() {
        Some(folder) => imports_dir.join(folder),
        None => imports_dir.to_path_buf(),
    }
}

/// Categoria indicada pela pasta do arquivo (`imports/terrors/x.json` → Terror).
pub fn category_from_folder(path: &Path) -> Option<Category> {
    let folder = path.parent()?.file_name()?.to_str()?.to_lowercase();
    Category::bosses().find(|c| c.folder() == Some(folder.as_str()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn values_labels_and_folders() {
        assert_eq!(Category::from_value(Some("terror")), Category::Terror);
        assert_eq!(Category::from_value(Some("xx")), Category::Hunt);
        assert_eq!(Category::from_value(None), Category::Hunt);
        assert_eq!(Category::bosses().count(), 4);
        assert_eq!(Category::BossRed.label(), "Boss de Energia Vermelha");
        assert_eq!(Category::BossRed.plural(), "Energia Vermelha");
        let imports = Path::new("imports");
        assert_eq!(category_dir(imports, Category::Hunt), imports);
        assert_eq!(category_dir(imports, Category::Terror), imports.join("terrors"));
        assert_eq!(category_from_folder(Path::new("imports/Terrors/x.json")), Some(Category::Terror));
        assert_eq!(category_from_folder(Path::new("imports/x.json")), None);
        assert_eq!(category_from_folder(Path::new("x.json")), None);
    }
}
