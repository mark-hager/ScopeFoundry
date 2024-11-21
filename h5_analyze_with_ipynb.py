import json
import os
from pathlib import Path

from ScopeFoundry.generate_loaders_py import generate_loaders_py, get_measurement_name

IPYNB_DEMO_FNAME = "overview.ipynb"


def new_empty_nb_content(n_cells=2):
    """returns the content of ipynb with n_cell empty cells"""
    return {
        "cells": [
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [],
            }
            for _ in range(n_cells)
        ]
    }


def update_cells(new_sources, nb_content):
    # 1st cell: only update specific lines
    nb_content["cells"][0]["source"] = new_sources[0]
    nb_content["cells"][0]["execution_count"] = None

    # 2nd cell: only update specific lines
    for s in new_sources[1]:
        skipp = False
        for o in nb_content["cells"][1]["source"]:
            if s in o:
                skipp = True
                break
        if not skipp:
            nb_content["cells"][1]["source"].append(s)
    nb_content["cells"][1]["execution_count"] = None
    return nb_content


def mk_cell_sources(folder):
    path = Path(folder)

    file_load_lines = []
    fname = "your_file_name.h5"
    for fname in path.rglob("*.h5"):
        mm_name = get_measurement_name(fname)
        file_load_lines.append(f"load_{mm_name}(r'{fname.relative_to(folder)}')")

    src_0 = [
        "# CELL #1: AUTOGENERATED CELL: DO NOT ALTER THIS CELL, PROGRESS MAY BE LOST. use CELL #3 onwards",
        "import numpy as np",
        "from matplotlib import pylab as plt",
        "",
        "",
        f"from h5_data_loaders import load",
        "",
        f"data = load(r'{fname}')",
    ]

    src_1 = [
        "# CELL #2 ALTERNATIVE TO CELL #1. Only addition of lines and commenting generated lines are presistant",
        "import h5_data_loaders as loaders",
    ] + [f"data = loaders.{a}\n" for a in file_load_lines]

    return [src_0, src_1]


def generate_ipynb(folder=".", ipynb_fname: Path = None):
    if ipynb_fname is None:
        ipynb_fname = Path(folder) / IPYNB_DEMO_FNAME

    new_sources = mk_cell_sources(folder)

    nb_content = {}

    if ipynb_fname.exists():
        with open(ipynb_fname, "r") as file:
            nb_content = json.load(file)

    if not "cells" in nb_content or len(nb_content["cells"]) < 2:
        # assuming nb_content is invalid
        nb_content = new_empty_nb_content(2)

    with open(ipynb_fname, "w") as file:
        json.dump(update_cells(new_sources, nb_content), file)

    return ipynb_fname


def analyze_with_ipynb(folder="."):
    loaders_fname, dset_names = generate_loaders_py(folder)
    ipynb_path = generate_ipynb(folder)

    print("")
    print("generated", loaders_fname, f"with {len(dset_names)} loader(s)")
    print("")
    print("check", ipynb_path)
    print("")

    if ipynb_path.exists():
        os.startfile(ipynb_path)


if __name__ == "__main__":
    analyze_with_ipynb()