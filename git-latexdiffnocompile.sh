#!/bin/bash
# Compatibility entry point; the diff implementation lives in pydifft.
exec pydifft pd --no-compile "$@"
