def register_all(mcp):
    """Register every tool and prompt with the FastMCP instance."""
    from .diagnostics import register as register_diag
    from .branches   import register as register_branches
    from .branch_ops import register as register_ops
    from ..prompts   import register as register_prompts
    register_diag(mcp)
    register_branches(mcp)
    register_ops(mcp)
    register_prompts(mcp)
