from __future__ import annotations

import logging
import re, os
import traceback
from tqdm import tqdm
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from swebench.harness.constants import DEF_IMAGE_BUILD_DIR

from swebench.harness.docker_build import (
    close_logger,
    setup_logger,
)

from swebench.harness.test_spec.test_spec import (
    get_test_specs_from_dataset,
    make_test_spec,
    TestSpec,
)


# test x86 first
APPTAINER_DEF_FORMAT = r"""
Bootstrap: docker
From: ubuntu:22.04

%environment
    export TZ=Etc/UTC
    export PATH=/opt/miniconda3/bin:$PATH

%files
    setup_env.sh /root/setup_env.sh
    setup_repo.sh /root/setup_repo.sh

%post
    # 1. Basic setup
    export DEBIAN_FRONTEND=noninteractive
    apt update && apt install -y \
        wget git build-essential libffi-dev libtiff-dev \
        python3 python3-pip python-is-python3 jq curl \
        locales locales-all tzdata \
        && rm -rf /var/lib/apt/lists/*

    # 2. Install conda
    wget 'https://repo.anaconda.com/miniconda/Miniconda3-py311_23.11.0-2-Linux-x86_64.sh' -O miniconda.sh
    bash miniconda.sh -b -p /opt/miniconda3
    /opt/miniconda3/bin/conda init --all
    /opt/miniconda3/bin/conda config --append channels conda-forge

    # 3. Create non-root user
    adduser --disabled-password --gecos 'dog' nonroot

    # 4. Setup testbed conda environment
    chmod +x /root/setup_env.sh
    bash /root/setup_env.sh

    # 5. Clone and configure astropy repo
    chmod +x /root/setup_repo.sh
    bash /root/setup_repo.sh

    # Optional: Activate env in bashrc
    echo "source /opt/miniconda3/etc/profile.d/conda.sh && conda activate testbed" >> ~/.bashrc
"""

def build_def(dataset):
    test_specs = get_test_specs_from_dataset(dataset)
    for test_spec in test_specs:
        # build setup file and put in logs/instance_id folder
        setup_scripts = {
                    "setup_env.sh": test_spec.setup_env_script,
                    "setup_repo.sh": test_spec.install_repo_script,
                }
        
        build_dir = DEF_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
        logger = setup_logger("def", build_dir / "build_image.log")
        logger.info("Building image def\n")

        # if not os.path.exists(DEF_IMAGE_BUILD_DIR):
        #     os.mkdir(DEF_IMAGE_BUILD_DIR)

        # build_dir = DEF_IMAGE_BUILD_DIR / test_spec.instance_image_key.replace(":", "__")
        # if not os.path.exists(build_dir):
        #     os.mkdir(build_dir)

        try:
            # Write the setup scripts to the build directory
            for setup_script_name, setup_script in setup_scripts.items():
                logger.info(f"[SETUP SCRIPT] {setup_script_name}:\n{setup_script}")
                setup_script_path = build_dir / setup_script_name
                with open(setup_script_path, "w") as f:
                    f.write(setup_script)
                
            # Write the Apptainer definition file
            logger.info("Writing Apptainer definition file...")
            def_file_path = build_dir / "apptainer.def"
            with open(def_file_path, "w") as def_file:
                def_file.write(APPTAINER_DEF_FORMAT)

        except Exception as e:
            logger.error(f"Error building image: {e}")
        finally:
            logger.info("Finished building definition file.")
            close_logger(logger)  # functions that create loggers should close them