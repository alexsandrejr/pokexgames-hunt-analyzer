//! Macros internos do crate.

/// Gera um enum guardado no banco como texto, com rótulo para a interface.
///
/// Equivale aos `Enum` do Python com `value` e `label`: `as_str` devolve o valor gravado,
/// `label` o nome na tela, e `FromStr` lê o valor gravado. A ordem das variantes é a da
/// declaração, também usada pelo `Ord`.
macro_rules! text_enum {
    (
        $(#[$meta:meta])* $name:ident {
            $($(#[$vmeta:meta])* $variant:ident = $value:literal => $label:literal),+ $(,)?
        }
    ) => {
        $(#[$meta])*
        #[derive(
            Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash,
            ::serde::Serialize, ::serde::Deserialize,
        )]
        pub enum $name {
            $($(#[$vmeta])* #[serde(rename = $value)] $variant),+
        }

        impl $name {
            pub const ALL: &'static [Self] = &[$(Self::$variant),+];

            /// Valor gravado no banco.
            pub fn as_str(self) -> &'static str {
                match self { $(Self::$variant => $value),+ }
            }

            pub fn label(self) -> &'static str {
                match self { $(Self::$variant => $label),+ }
            }
        }

        impl ::std::str::FromStr for $name {
            type Err = $crate::UserError;

            fn from_str(text: &str) -> ::std::result::Result<Self, $crate::UserError> {
                match text {
                    $($value => Ok(Self::$variant),)+
                    _ => Err($crate::UserError::new(format!(
                        "Valor desconhecido para {}: {text:?}.", stringify!($name)))),
                }
            }
        }

        impl ::std::fmt::Display for $name {
            fn fmt(&self, f: &mut ::std::fmt::Formatter<'_>) -> ::std::fmt::Result {
                f.write_str(self.label())
            }
        }
    };
}

pub(crate) use text_enum;
