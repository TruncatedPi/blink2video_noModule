import ssl


def contexte_tls() -> ssl.SSLContext:
    contexte = ssl.create_default_context()
    try:
        import certifi
    except ImportError:
        return contexte
    contexte.load_verify_locations(cafile=certifi.where())
    return contexte
