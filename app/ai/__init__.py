"""Community AI subsystem.

The HTTP app may build redacted snapshots from the core database.  The worker is
intentionally composed only from modules in this package and consumes immutable
requests from the separate AI database.
"""
