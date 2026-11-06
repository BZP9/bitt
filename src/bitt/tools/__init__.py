"""The tool packages (docs/v2/rebuild.md §2): what the CLI and the tests load on top of the kernel."""


def packages():
    from . import artifact, data, module, recipe, run, tag
    return [module.package(), artifact.package(), data.package(), recipe.package(), run.package(), tag.package()]
