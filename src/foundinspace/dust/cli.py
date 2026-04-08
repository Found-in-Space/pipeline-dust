"""CLI entry point for pipeline-dust (dust-pipeline)."""

from __future__ import annotations

from pathlib import Path

import click

from foundinspace.dust.project import DustProject, load_project


class LazyGroup(click.Group):
    def __init__(self, *args, lazy_subcommands=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.lazy_subcommands = lazy_subcommands or {}

    def list_commands(self, ctx):
        return sorted(set(super().list_commands(ctx)) | set(self.lazy_subcommands))

    def get_command(self, ctx, name):
        if name in self.lazy_subcommands:
            from importlib import import_module

            module_path, obj_name = self.lazy_subcommands[name].split(":")
            mod = import_module(module_path)
            return getattr(mod, obj_name)
        return super().get_command(ctx, name)


@click.group(
    cls=LazyGroup,
    lazy_subcommands={
        "mccallum2025": "foundinspace.dust.mccallum2025.cli:cli",
        "rezaei2024": "foundinspace.dust.rezaei2024.cli:cli",
        "project": "foundinspace.dust.project_cli:cli",
    },
)
@click.version_option()
def cli() -> None:
    """Dust map pipeline: fetch and build steps for 3D interstellar dust data."""


def load_project_or_die(project_path: Path, *required: str) -> DustProject:
    """Load project file and validate required sections, raising ClickException on failure."""
    try:
        project = load_project(project_path)
        if required:
            project.require(*required)
        return project
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
