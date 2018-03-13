import copy
import math
import numpy as num
from pyrocko import gf, moment_tensor as pmt, trace
from pyrocko import plot

from wafe import measure as wmeasure

km = 1000.


def model(
        engine,
        store_id,
        magnitude_min, magnitude_max,
        moment_tensor,
        stress_drop_min, stress_drop_max,
        rupture_velocity_min, rupture_velocity_max,
        depth_min, depth_max,
        distance_min, distance_max,
        measures,
        nsources=400,
        nreceivers=1,
        apply_source_response_via_spectra=True,
        debug=True):

    d2r = math.pi / 180.

    components = set()
    for measure in measures:
        if not measure.components:
            raise Exception('no components given in measurement rule')

        for component in measure.components:
            components.add(component)

    components = list(components)

    data = []
    nerrors = 0
    traces_debug = []
    markers_debug = []
    for isource in xrange(nsources):
        magnitude = num.random.uniform(
            magnitude_min, magnitude_max)
        stress_drop = num.random.uniform(
            stress_drop_min, stress_drop_max)
        rupture_velocity = num.random.uniform(
            rupture_velocity_min, rupture_velocity_max)

        radius = (pmt.magnitude_to_moment(magnitude) * 7./16. /
                  stress_drop)**(1./3.)

        duration = 1.5 * radius / rupture_velocity

        if moment_tensor is None:
            mt = pmt.MomentTensor.random_dc(magnitude=magnitude)
        else:
            mt = copy.deepcopy(moment_tensor)
            mt.magnitude = magnitude

        depth = num.random.uniform(depth_min, depth_max)
        if apply_source_response_via_spectra:
            source = gf.MTSource(
                m6=mt.m6(),
                depth=depth)

            extra_responses = [
                wmeasure.BruneResponse(duration=duration)]
        else:
            source = gf.MTSource(
                m6=mt.m6(),
                depth=depth,
                stf=gf.HalfSinusoidSTF(effective_duration=duration))

            extra_responses = []

        for ireceiver in xrange(nreceivers):
            angle = num.random.uniform(0., 360.)
            distance = num.exp(num.random.uniform(
                math.log(distance_min), math.log(distance_max)))

            targets = []
            for comp in components:
                targets.append(gf.Target(
                    quantity='displacement',
                    codes=('', '%i_%i' % (isource, ireceiver), '', comp),
                    north_shift=distance*math.cos(d2r*angle),
                    east_shift=distance*math.sin(d2r*angle),
                    depth=0.,
                    store_id=store_id))

            resp = engine.process(source, targets)
            amps = []
            for measure in measures:
                comp_to_tt = {}
                for (source, target, tr) in resp.iter_results():
                    comp_to_tt[target.codes[-1]] = (target, tr)

                targets, trs = zip(*(
                    comp_to_tt[c] for c in measure.components))

                try:
                    result = wmeasure.evaluate(
                        engine, source, targets, trs,
                        extra_responses,
                        debug=debug)

                    if not debug:
                        amps.append(result)
                    else:
                        amp, trs, marker = result
                        amps.append(amp)
                        traces_debug.extend(trs)
                        markers_debug.append(marker)

                except wmeasure.AmplitudeMeasurementFailed:
                    nerrors += 1
                    amps.append(None)

            data.append([magnitude, duration, depth, distance] + amps)

    if debug:
        trace.snuffle(traces_debug, markers=markers_debug)

    return num.array(data, dtype=num.float)


if __name__ == '__main__':
    engine = gf.get_engine()
    store_id = 'crust2_m5_hardtop_8Hz_fine'
    magnitude_min, magnitude_max = 3., 7.
    moment_tensor = None  # random DC
    # moment_tensor = pmt.MomentTensor.from_values([strike, dip, rake])
    stress_drop_min, stress_drop_max = 1.0e6, 10.0e6
    rupture_velocity_min, rupture_velocity_max = 2500.*0.9, 3600.*0.9
    depth_min, depth_max = 1.*km, 30.*km
    distance_min, distance_max = 100*km, 100*km

    measure_ML = wmeasure.AmplitudeMeasure(
        timing_tmin=gf.Timing('vel:8'),
        timing_tmax=gf.Timing('vel:2'),
        fmin=None,
        fmax=None,
        response=wmeasure.response_wa,
        components=['N', 'E'],
        quantity='velocity',
        maximum_method='peak_component')

    data = model(
        engine, store_id,
        magnitude_min, magnitude_max,
        moment_tensor,
        stress_drop_min, stress_drop_max,
        rupture_velocity_min, rupture_velocity_max,
        depth_min, depth_max,
        distance_min, distance_max,
        measures=[measure_ML],
        apply_source_response_via_spectra=False,
        debug=True)

    plt = plot.mpl_init(fontsize=9.)
    plt.switch_backend('Qt5Agg')

    magnitudes = data[:, 0]
    durations = data[:, 1]
    depths = data[:, 2]
    distances = data[:, 3]
    amps = data[:, 4:]

    fig = plt.figure()
    axes = fig.add_subplot(1, 1, 1)
    axes.plot(magnitudes, amps[:, 0], 'o')
    axes.set_yscale('log')
    plt.show()
