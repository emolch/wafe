from __future__ import print_function

import os.path as op
import logging

import numpy as num

from pyrocko import util

from wafe import config as wconfig


km = 1000.
logger = logging.getLogger('wafe.plot')


def run_plot(
        results_path,
        formats=['png'],
        min_bin_count=10,
        mag_step=0.1,
        nbins_dist=20):

    config = wconfig.read_config(op.join(results_path, 'config.yaml'))

    dists = []
    mags = []
    measures = []
    old_event_name = None
    with open(op.join(results_path, 'measures.txt'), 'r') as f:
        for line in f:

            if line.strip().startswith('#'):
                continue

            toks = line.split()
            event_name, station_codes = toks[:2]
            measures_this = list(map(float, toks[2:]))

            if event_name != old_event_name:
                ds = config.get_dataset(event_name)

            old_event_name = event_name

            station = ds.get_station(tuple(station_codes.split('.')))

            event = ds.get_event()
            dist = station.distance_to(event)
            mag = event.magnitude

            dists.append(dist)
            mags.append(mag)
            measures.append(measures_this)

    dists = num.array(dists, dtype=num.float)
    mags = num.array(mags, dtype=num.float)
    measures = num.array(measures, dtype=num.float)

    from matplotlib import pyplot as plt
    from pyrocko import plot
    from scipy.stats import binned_statistic_2d

    plot.mpl_init()

    mag_min = num.floor(num.min(mags) / mag_step) * mag_step - mag_step/2.
    mag_max = num.ceil(num.max(mags) / mag_step) * mag_step + mag_step/2.
    nbins_mag = int(round((mag_max - mag_min) / mag_step))
    mag_bins = num.linspace(mag_min, mag_max, nbins_mag+1)
    # mag_centers = 0.5*(mag_bins[:-1] + mag_bins[1:])

    dist_min = num.min(dists)
    dist_max = num.max(dists)
    dist_bins = num.linspace(dist_min, dist_max, nbins_dist+1)
    # dist_centers = 0.5*(dist_bins[:-1] + dist_bins[1:])

    measure_names = [m.name for m in config.measures]
    for imeasure, measure_name in enumerate(measure_names):
        fontsize = 9.0
        fig = plt.figure(figsize=plot.mpl_papersize('a5', 'landscape'))
        labelpos = plot.mpl_margins(fig, w=7, h=5., units=fontsize)

        axes = fig.add_subplot(1, 1, 1)
        axes.set_xlabel('Distance [km]')
        axes.set_ylabel('Magnitude')

        labelpos(axes, 2., 1.5)

        fig.suptitle(measure_name)

        medians, _, _, _ = binned_statistic_2d(
            dists, mags, measures[:, imeasure],
            statistic='median',
            bins=[dist_bins, mag_bins])

        counts, _, _, _ = binned_statistic_2d(
            dists, mags, measures[:, imeasure],
            statistic='count',
            bins=[dist_bins, mag_bins])

        medians[counts < min_bin_count] = None
        medians = num.log10(medians)

        im = axes.pcolorfast(
            dist_bins/km, mag_bins, medians.T,
            vmin=num.nanmin(medians), vmax=num.nanmax(medians),
            cmap='YlOrBr')

        fig.colorbar(im).set_label('$log_{10}$ measure')

        for fmt in formats:
            plot_path = op.join(
                results_path, 'plots',
                'dist_mag_median_%s.%s' % (measure_name, fmt))

            util.ensuredirs(plot_path)

            fig.savefig(plot_path)
            logger.info('plot saved: %s' % plot_path)
