import sys as _sys
from workspace_tests.evaluation_scripts import eval_retrieval_runtime as _impl

# Make this shim completely transparent: replace ourselves in sys.modules with
# the real implementation so that monkeypatching eval_mod.xxx in tests works
# correctly (patches land on the same module object the functions close over).
_sys.modules[__name__] = _impl
