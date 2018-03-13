from __future__ import print_function

import os.path as op

import numpy as num

from wafe import config as wconfig


def run_plot(results_path):

    config = wconfig.read_config(op.join(results_path, 'config.yaml'))

    with open(op.join(results_path, 'measures.txt'), 'r') as f:
        for line in f:
            if line.strip().startswith('#'):
                continue

            toks = line.split()
            event_name, station_codes = toks[:2]
            measures = map(float, toks[2:])

            ds = config.get_dataset(event_name)
            station = ds.get_station(tuple(station_codes.split('.')))

            print(station, measures)
