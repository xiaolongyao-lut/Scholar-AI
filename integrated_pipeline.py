"""Root shim forwarding to literature_assistant.core.integrated_pipeline."""
import sys as _sys
from literature_assistant.core import integrated_pipeline as _impl
from literature_assistant.core.integrated_pipeline import (
    run_pipeline,
    main,
    _build_help_parser,
    _should_print_help,
)

if __name__ == "__main__":
    if _should_print_help(_sys.argv[1:]):
        _build_help_parser().print_help()
        raise SystemExit(0)
    raise SystemExit(main())
