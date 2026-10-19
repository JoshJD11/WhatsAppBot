"""Write the Excel template to templates/bosca_bot.xlsx (or to the path given).

Usage: python -m scripts.create_excel_template [output.xlsx]
"""

import sys
from pathlib import Path

from bot.template import build_template

DEFAULT_OUTPUT = Path("templates/bosca_bot.xlsx")


def main(argv: list[str]) -> None:
    output = Path(argv[1]) if len(argv) > 1 else DEFAULT_OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    build_template().save(output)
    print(f"Template written to {output}")


if __name__ == "__main__":
    main(sys.argv)
