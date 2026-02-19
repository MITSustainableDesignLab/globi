"""GloBI CLI."""

import click

from .get import get
from .simulate import simulate
from .submit import submit
from .tests import tests


@click.group()
def cli():
    """The GloBI CLI.

    Use this to create, manage, and submit GloBI experiments.
    """
    pass


cli.add_command(submit)
cli.add_command(simulate)
cli.add_command(tests)
cli.add_command(get)


if __name__ == "__main__":
    cli()
