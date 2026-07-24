"""
Make emotion CLI runnable as a module: python -m src.emotion.cli
"""
from .cli import cli

if __name__ == '__main__':
    cli()
