from __future__ import print_function
import logging
import os.path as op

from pyrocko import gf, trace, util

from wafe import measure as wmeasure, dataset, config as wconfig


logger = logging.getLogger('wafe.core')


class NoData(Exception):
    pass


def run_extract(config, debug=False):
    engine = config.get_engine()

    output_path = config.expand_path(config.output_path)

    util.ensuredir(output_path)

    output_measures_path = op.join(output_path, 'measures.txt')
    output_config_path = op.join(output_path, 'config.yaml')

    wconfig.write_config(config, output_config_path)

    with open(output_measures_path, 'w') as out:

        out.write('# event station %s\n' % ' '.join(
            measure.name for measure in config.measures))

        event_names = config.get_event_names()
        for event_name in event_names:
            logger.info('processing event %s' % event_name)

            try:
                ds = config.get_dataset(event_name)
            except OSError as e:
                logger.warn('could not get dataset for event %s' % event_name)
                continue

            event = ds.get_event()
            source = gf.DCSource.from_pyrocko_event(event)
            stations = ds.get_stations()

            debug_infos = []
            for station in stations:

                values = []
                try:
                    for measure in config.measures:
                        targets = [
                            gf.Target(
                                quantity='velocity',
                                codes=station.nsl() + (component,),
                                store_id=config.store_id,
                                lat=station.lat,
                                lon=station.lon,
                                depth=station.depth,
                                elevation=station.elevation)

                            for component in measure.components]

                        value, debug_info = measure.evaluate(
                            engine, source, targets, ds, debug=debug)

                        values.append(value)
                        debug_infos.append(debug_info)

                    out.write('%s %s %s\n' % (
                        event.name,
                        '.'.join(x for x in station.nsl()),
                        ' '.join('%g' % value for value in values)))

                except (wmeasure.FeatureMeasurementFailed,
                        dataset.NotFound,
                        gf.OutOfBounds) as e:

                    logger.warn(
                        'feature extraction failed for %s, %s:\n   %s' % (
                            event.name,
                            '.'.join(x for x in station.nsl()),
                            e))

            if debug:
                traces = []
                markers = []
                for traces_this, markers_this in debug_infos:
                    traces.extend(traces_this)
                    markers.extend(markers_this)

                trace.snuffle(
                    traces, markers=markers,
                    events=[event],
                    stations=stations)
