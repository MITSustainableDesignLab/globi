"""GloBI CLI."""

import click

from globi.tools.cli.get import get
from globi.tools.cli.simulate import simulate
from globi.tools.cli.submit import submit
from globi.tools.cli.tests import tests


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
