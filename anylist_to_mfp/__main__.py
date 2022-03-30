import click

from .core import sync_from_anylist_to_mfp


@click.command()
@click.option("--no-headless", is_flag=True, help="Don't use headless mode.")
@click.option("--ignore-existing", is_flag=True, help="Ignore existing recipes.")
def cli(no_headless=False, ignore_existing=False):
    """Sync recipes from AnyList to MyFitnessPal."""
    sync_from_anylist_to_mfp(headless=not no_headless, ignore_existing=ignore_existing)
