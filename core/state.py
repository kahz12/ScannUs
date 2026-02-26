# Global mutable runtime state singleton.
# This module acts as a transient data store for the application's active session.
# It caches the artifacts of the current operation to avoid passing large data structures
# explicitly through deeply nested function calls in the CLI loops.

# ULTIMOS_RESULTADOS (Last Results):
# Stores an array of the most recent search result objects.
# Useful for immediate post-processing or pagination without re-querying.
ULTIMOS_RESULTADOS = []

# CASO_ACTUAL (Current Case):
# A structured dictionary tracking the active investigation's parameters and findings.
# terminos: A dictionary of the search parameters used (query, engine, etc.)
# resultados: A list of result objects persisted during the session.
CASO_ACTUAL = {"terminos": {}, "resultados": []}
