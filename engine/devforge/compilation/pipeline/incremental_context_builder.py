"""
IncrementalContextBuilder has been consolidated into ContextAssembler.

This module is retained as a compatibility stub.  All session-operation
tracking and code context building now lives in:

    devforge.compilation.pipeline.context_assembler

Import ContextAssembler and use its `record_operation()` method directly.
"""
