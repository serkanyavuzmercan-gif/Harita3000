"""Outbound HTTPS settings shared by geocoding and routing."""

import ssl

import truststore

# OS trust store, so antivirus or corporate TLS inspection roots are accepted like in the browser.
SSL_CONTEXT = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
