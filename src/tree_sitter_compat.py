import warnings


_TREE_SITTER_LANGUAGE_DEPRECATION = (
    r"Language\(path, name\) is deprecated\. Use Language\(ptr, name\) instead\."
)


def get_tree_sitter_parser(lang_name: str):
    """Load a tree-sitter parser while hiding a known upstream compatibility warning."""
    try:
        from tree_sitter_languages import get_parser
    except ImportError as exc:
        raise ImportError(
            f"tree-sitter-languages is required for {lang_name} parsing: {exc}"
        ) from exc

    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message=_TREE_SITTER_LANGUAGE_DEPRECATION,
            category=FutureWarning,
        )
        return get_parser(lang_name)
