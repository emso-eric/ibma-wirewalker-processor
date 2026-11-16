#!/usr/bin/env python3
"""
Simple wrapper for erddap config in emso_metadata_harmonizer package
"""

import emso_metadata_harmonizer as emh
import argparse
import os
import shutil



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_file", help="input file")
    parser.add_argument("dataset_id", help="dataset id")
    parser.add_argument("erddap_dataset_path", help="erddap dataset path, usually /datasets/<myfolder>")
    parser.add_argument("-x", "--xml", help="Path to datasets.xml", default=os.path.join("erddap", "conf", "datasets.xml"))
    args = parser.parse_args()

    emh.erddap_config(args.input_file, args.dataset_id, args.erddap_dataset_path, datasets_xml_file=args.xml)


if __name__ == "__main__":
    main()
